"""Ledger replay and integrity checks (TASK-360). Pure; does not import the engine."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, cast

from config import V9
from core.ledger import CASH_TICKERS, EFFECTIVE_STATUSES, check_invariants
from core.numbers import (
    WEIGHT_SUM_TOL,
    is_finite_money,
    is_finite_price,
    is_valid_units,
    weights_sum_to_one,
)
from core.state_migrations import SchemaError, migrate

STATE_SCHEMA = 1
#: kept as a module name for callers; the definition lives in core.ledger
FILLED = EFFECTIVE_STATUSES
REPLAY_TOL = 1e-6


@dataclass(frozen=True)
class Finding:
    level: str  # "ERROR" | "WARN"
    code: str
    message: str


def _f(x, default=0.0) -> float:
    try:
        if x is None:
            return default
        v = float(x)
        return default if v != v else v
    except (TypeError, ValueError):
        return default


def _empty_books(state: dict) -> dict:
    """capital_reference split by mix, then by tranche — the new_state layout."""
    capital = _f(state.get("capital_reference"))
    sleeves = state.get("sleeves") or {}
    # config.V9 is a heterogeneous literal, so mypy types every V9.get() as `object`.
    # cast() is a no-op at runtime; it says what the config value is, it does not change it.
    mix = dict(state.get("mix") or cast("dict[str, float] | None", V9.get("mix")) or {})
    names = list(sleeves.keys()) or list(mix.keys()) or ["stocks", "etf"]
    if not mix:
        mix = {n: 1.0 / len(names) for n in names}
    out = {}
    for name in names:
        trans = list((sleeves.get(name) or {}).get("tranches") or [])
        k_n = len(trans) or int(cast("int | None", V9.get("tranches")) or 4)
        w = _f(mix.get(name), 1.0 / len(names))
        each = capital * w / k_n if k_n else 0.0
        out[name] = {
            "tranches": [{"k": i, "units": {}, "cash": float(each)} for i in range(k_n)]
        }
    return out


def _tr(books: dict, sleeve: str, k: int) -> dict | None:
    trans = (books.get(sleeve) or {}).get("tranches") or []
    if k < 0 or k >= len(trans):
        return None
    return trans[k]


def replay(state: dict) -> dict:
    """Reconstruct tranche units/cash from capital + ledger + write_offs + transfers
    + interest + dividends. Splits land with TASK-363."""
    books = _empty_books(state)

    events: list[tuple] = []
    for i, f in enumerate(state.get("ledger") or []):
        d = str(f.get("exec_date") or f.get("date") or "")
        side = str(f.get("side") or "")
        phase = {"sell": 0, "transfer_out": 1, "transfer_in": 2, "buy": 3}.get(side, 9)
        events.append((d, 0, phase, i, ("fill", f)))
    for i, t in enumerate(state.get("transfers") or []):
        d = str(t.get("date") or "")
        events.append((d, 0, 1, i, ("transfer", t)))
    for i, rec in enumerate(state.get("dividends") or []):
        events.append((str(rec.get("ex_date") or rec.get("date") or ""), 1, 0, i, ("div", rec)))
    for i, rec in enumerate(state.get("interest") or []):
        events.append((str(rec.get("date") or ""), 2, 0, i, ("int", rec)))
    for i, w in enumerate(state.get("write_offs") or []):
        events.append((str(w.get("date") or ""), 3, 0, i, ("wo", w)))
    events.sort(key=lambda e: (e[0], e[1], e[2], e[3]))

    for _d, _a, _b, _i, (kind, rec) in events:
        if kind == "fill":
            _apply_fill(books, rec)
        elif kind == "transfer":
            tr = _tr(books, str(rec.get("sleeve") or ""), int(rec.get("tranche") or 0))
            if tr is not None:
                tr["cash"] += _f(rec.get("dollars"))
        elif kind == "div":
            tr = _tr(books, str(rec.get("sleeve") or ""), int(rec.get("tranche") or 0))
            if tr is not None:
                tr["cash"] += _f(rec.get("dollars"))
        elif kind == "int":
            _apply_interest(books, rec)
        elif kind == "wo":
            tr = _tr(books, str(rec.get("sleeve") or ""), int(rec.get("tranche") or 0))
            if tr is None:
                continue
            tk = str(rec.get("ticker") or "")
            tr["cash"] += _f(rec.get("proceeds"))
            tr["units"].pop(tk, None)
    return books


def _apply_fill(books: dict, f: dict) -> None:
    status = str(f.get("status") or "")
    side = str(f.get("side") or "")
    if status not in FILLED or side not in ("buy", "sell"):
        return
    tr = _tr(books, str(f.get("sleeve") or ""), int(f.get("tranche") or 0))
    if tr is None:
        return
    ticker = str(f.get("ticker") or "")
    if not ticker or ticker in CASH_TICKERS:
        return
    units = _f(f.get("units"))
    dollars = _f(f.get("dollars"))
    price = _f(f.get("price"))
    cost = _f(f.get("cost"))
    if dollars == 0.0 and units and price:
        dollars = units * price
    if side == "buy":
        tr["units"][ticker] = tr["units"].get(ticker, 0.0) + units
        tr["cash"] -= dollars + cost
        if tr["units"][ticker] <= 1e-12:
            tr["units"].pop(ticker, None)
    else:
        tr["units"][ticker] = tr["units"].get(ticker, 0.0) - units
        tr["cash"] += dollars - cost
        if tr["units"].get(ticker, 0.0) <= 1e-12:
            tr["units"].pop(ticker, None)


def _apply_interest(books: dict, rec: dict) -> None:
    sleeve = str(rec.get("sleeve") or "")
    dollars = _f(rec.get("dollars"))
    trans = (books.get(sleeve) or {}).get("tranches") or []
    weights = [max(_f(t.get("cash")), 0.0) for t in trans]
    total = sum(weights)
    if total <= 0 or abs(dollars) < 1e-15:
        return
    for t, w in zip(trans, weights, strict=True):
        t["cash"] += dollars * (w / total)


def check(state: dict) -> list[Finding]:
    findings: list[Finding] = []
    st = copy.deepcopy(state)
    try:
        migrate(st)
    except SchemaError as e:
        findings.append(Finding("ERROR", "schema", str(e)))
        return findings

    ver = st.get("schema_version")
    if ver != STATE_SCHEMA:
        findings.append(Finding(
            "ERROR", "schema_version",
            f"schema_version={ver!r} != {STATE_SCHEMA}",
        ))

    # Non-finite values first (audit phase 2.4). `_f` coerces NaN to 0.0 for the
    # replay arithmetic, which means a NaN cash whose replay also lands near zero
    # used to pass silently; and +/-inf reported only as a replay mismatch, never as
    # the impossible number it is (repros R-203, R-204).
    findings.extend(_non_finite_findings(st))
    findings.extend(_weight_findings(st))

    rebuilt = replay(st)
    for sleeve, block in (st.get("sleeves") or {}).items():
        rec_block = rebuilt.get(sleeve) or {"tranches": []}
        for i, tr in enumerate(block.get("tranches") or []):
            rec: dict[str, Any] = (rec_block["tranches"][i] if i < len(rec_block["tranches"])
                                   else {"units": {}, "cash": 0.0})
            cash = _f(tr.get("cash"))
            rec_cash = _f(rec.get("cash"))
            if abs(cash - rec_cash) > REPLAY_TOL:
                findings.append(Finding(
                    "ERROR", "replay_cash",
                    f"{sleeve}[{i}] cash stored={cash} replay={rec_cash}",
                ))
            stored_u = {str(k): _f(v) for k, v in (tr.get("units") or {}).items() if _f(v) > 1e-12}
            rec_u = {str(k): _f(v) for k, v in (rec.get("units") or {}).items() if _f(v) > 1e-12}
            keys = set(stored_u) | set(rec_u)
            for tk in sorted(keys):
                if abs(stored_u.get(tk, 0.0) - rec_u.get(tk, 0.0)) > REPLAY_TOL:
                    findings.append(Finding(
                        "ERROR", "replay_units",
                        f"{sleeve}[{i}] {tk} stored={stored_u.get(tk, 0.0)} replay={rec_u.get(tk, 0.0)}",
                    ))
            if any(_f(u) < -REPLAY_TOL for u in (tr.get("units") or {}).values()):
                findings.append(Finding("ERROR", "units_negative", f"{sleeve}[{i}] has negative units"))
            if cash < -REPLAY_TOL:
                findings.append(Finding("ERROR", "cash_negative", f"{sleeve}[{i}] cash={cash}"))
            stale = set((tr.get("stale") or {}).keys())
            units_keys = set((tr.get("units") or {}).keys())
            extra = stale - units_keys
            if extra:
                findings.append(Finding(
                    "ERROR", "stale_orphan",
                    f"{sleeve}[{i}] stale keys not in units: {sorted(extra)}",
                ))
            for tk in units_keys:
                if tk not in CASH_TICKERS and tk != tk.upper():
                    findings.append(Finding("WARN", "ticker_case", f"{sleeve}[{i}] units {tk!r} is not uppercase"))

    n_tranches = {
        s: len((b.get("tranches") or [])) for s, b in (st.get("sleeves") or {}).items()
    }
    for o in st.get("pending") or []:
        sleeve = str(o.get("sleeve") or "")
        try:
            k = int(o.get("tranche"))
        except (TypeError, ValueError):
            k = -1
        if sleeve not in n_tranches or k < 0 or k >= n_tranches.get(sleeve, 0):
            findings.append(Finding(
                "ERROR", "pending_tranche",
                f"pending {o.get('side')} {o.get('ticker')} references {sleeve}[{k}]",
            ))
            continue
        has_qty = any(_f(o.get(key)) for key in ("units", "dollars", "est_units", "est_price"))
        if not has_qty and str(o.get("side") or "") not in ("park", "hold_no_price"):
            findings.append(Finding(
                "ERROR", "pending_qty",
                f"pending {sleeve}[{k}] {o.get('ticker')} {o.get('side')} has no units-or-dollars",
            ))
        tk = str(o.get("ticker") or "")
        if tk and tk not in CASH_TICKERS and tk != tk.upper():
            findings.append(Finding("WARN", "ticker_case", f"pending ticker {tk!r} is not uppercase"))

    last = st.get("last_run_date")
    prev = ""
    pending = st.get("pending") or []
    for f in st.get("ledger") or []:
        d = str(f.get("exec_date") or f.get("date") or "")
        if prev and d < prev:
            findings.append(Finding("ERROR", "ledger_order", f"ledger dates not monotone: {prev} then {d}"))
        # last_run_date is the last plan() date. settle() books fills at the
        # next close (t+1), so exec_date can be after last_run_date until the
        # next plan() stamps it. That gap is legal only for fills of the
        # just-settled plan (pending empty, planned == last_run_date).
        if last and d and d > str(last):
            planned = str(f.get("planned") or "")
            if pending or planned != str(last):
                findings.append(Finding(
                    "ERROR", "ledger_future",
                    f"ledger {d} > last_run_date {last}",
                ))
        prev = d or prev
        tk = str(f.get("ticker") or "")
        if tk and tk not in CASH_TICKERS and tk != tk.upper():
            findings.append(Finding("WARN", "ticker_case", f"ledger ticker {tk!r} is not uppercase"))

    seen = set()
    for rec in st.get("dividends") or []:
        key = (
            str(rec.get("ex_date") or ""),
            str(rec.get("sleeve") or ""),
            int(rec.get("tranche") or 0),
            str(rec.get("ticker") or ""),
        )
        if key in seen:
            findings.append(Finding("ERROR", "dividend_dup", f"duplicate dividend {key}"))
        seen.add(key)

    return findings


def _non_finite_findings(st: dict) -> list[Finding]:
    """Every number in the state must be finite (audit rule 9)."""
    out: list[Finding] = []
    if not is_finite_money(st.get("capital_reference")):
        out.append(Finding("ERROR", "non_finite", f"capital_reference={st.get('capital_reference')!r}"))
    for sleeve, block in (st.get("sleeves") or {}).items():
        for i, tr in enumerate((block or {}).get("tranches") or []):
            if not is_finite_money(tr.get("cash")):
                out.append(Finding("ERROR", "non_finite", f"{sleeve}[{i}] cash={tr.get('cash')!r}"))
            for tk, u in (tr.get("units") or {}).items():
                if not is_valid_units(u, allow_zero=True):
                    out.append(Finding("ERROR", "non_finite", f"{sleeve}[{i}] units {tk}={u!r}"))
            for tk, px in (tr.get("last_px") or {}).items():
                if not is_finite_price(px):
                    out.append(Finding("ERROR", "non_finite", f"{sleeve}[{i}] last_px {tk}={px!r}"))
    for key in ("ledger", "transfers", "dividends", "interest", "write_offs"):
        for i, rec in enumerate(st.get(key) or []):
            for field in ("units", "price", "dollars", "cost", "dps", "proceeds", "rate"):
                if field not in rec or rec[field] is None:
                    continue
                if not is_finite_money(rec[field]):
                    out.append(Finding("ERROR", "non_finite", f"{key}[{i}] {field}={rec[field]!r}"))
    for o in st.get("pending") or []:
        for field in ("dollars", "est_units", "est_price"):
            if o.get(field) is None:
                continue
            if not is_finite_money(o[field]):
                out.append(Finding(
                    "ERROR", "non_finite",
                    f"pending {o.get('sleeve')} {o.get('side')} {o.get('ticker')} {field}={o[field]!r}",
                ))
        px = o.get("est_price")
        if px is not None and is_finite_money(px) and not is_finite_price(px):
            out.append(Finding(
                "ERROR", "order_price_invalid",
                f"pending {o.get('sleeve')} {o.get('side')} {o.get('ticker')} est_price={px!r}",
            ))
        units = o.get("est_units")
        if units is not None and is_finite_money(units) and not is_valid_units(units, allow_zero=True):
            out.append(Finding(
                "ERROR", "order_units_invalid",
                f"pending {o.get('sleeve')} {o.get('side')} {o.get('ticker')} est_units={units!r}",
            ))
        dollars = o.get("dollars")
        if dollars is not None and is_finite_money(dollars) and float(dollars) < 0.0:
            out.append(Finding(
                "ERROR", "order_dollars_negative",
                f"pending {o.get('sleeve')} {o.get('side')} {o.get('ticker')} dollars={dollars!r}",
            ))
    for v in check_invariants(st):
        if v.code in ("event_id_duplicated", "status_unknown", "side_unknown"):
            out.append(Finding("ERROR", v.code, v.message))
    return out


def _weight_findings(st: dict) -> list[Finding]:
    """The persisted sleeve mix must be finite, non-negative and sum to 1 (phase 8.3).

    Before this, a mix of {"stocks": -0.5, "etf": 1.5} produced only a cascade of
    replay_cash mismatches and no statement that the weights themselves were
    impossible (repro R-205).
    """
    out: list[Finding] = []
    mix = st.get("mix")
    if mix is None:
        return out
    if not isinstance(mix, dict) or not mix:
        out.append(Finding("ERROR", "mix_invalid", f"mix must be a non-empty mapping, got {mix!r}"))
        return out
    for name, w in mix.items():
        if not is_finite_money(w):
            out.append(Finding("ERROR", "mix_invalid", f"mix[{name!r}]={w!r} is not finite"))
        elif float(w) < 0.0:
            out.append(Finding("ERROR", "mix_invalid", f"mix[{name!r}]={w!r} is negative"))
        elif float(w) > 1.0:
            out.append(Finding("ERROR", "mix_invalid", f"mix[{name!r}]={w!r} is above 1"))
    if not out and not weights_sum_to_one(mix):
        total = sum(float(w) for w in mix.values())
        out.append(Finding(
            "ERROR", "mix_not_normalised",
            f"mix sums to {total!r}, not 1 within {WEIGHT_SUM_TOL:g}",
        ))
    sleeves = set((st.get("sleeves") or {}).keys())
    unknown = sorted(set(mix) - sleeves) if sleeves else []
    if unknown:
        out.append(Finding("ERROR", "mix_unknown_sleeve", f"mix names no such sleeve: {unknown}"))
    missing = sorted(sleeves - set(mix)) if sleeves else []
    if missing:
        # phase 8.4: omitting a sleeve from the mix must not hide the capital in it
        out.append(Finding("ERROR", "mix_missing_sleeve", f"sleeve(s) absent from mix: {missing}"))
    return out


def format_findings(findings: list[Finding]) -> str:
    if not findings:
        return "state check: clean (0 findings)"
    lines = [f"state check: {len(findings)} finding(s)"]
    for f in findings:
        lines.append(f"  {f.level:<5} {f.code:<16} {f.message}")
    return "\n".join(lines)
