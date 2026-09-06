"""TASK-349 — credit cash dividends into the live book (pure, no network).

Backtests use auto_adjust=True (total return). The live book marks units at the
market close and would miss the cash the broker pays. Same principle as interest:
the books model the real account. Do not import the engine.

For every ex-date after `state["last_run_date"]` up to `today`, each tranche that
held the ticker *before* the ex-date (fills with exec_date < ex-date) is credited
`units * dps`. Recorded in `state["dividends"]`. Idempotent on
(ex_date, sleeve, tranche, ticker).

The broker pays on pay-date, later than ex-date; reconcile.py lists that gap.
"""
from __future__ import annotations

from config import V9
from core.ledger import EFFECTIVE_STATUSES

#: kept as a module name for callers; the definition lives in core.ledger
FILLED = EFFECTIVE_STATUSES


def _f(x, default=0.0) -> float:
    try:
        if x is None:
            return default
        v = float(x)
        return default if v != v else v
    except (TypeError, ValueError):
        return default


def dividend_key(rec: dict) -> tuple:
    return (
        str(rec.get("ex_date") or ""),
        str(rec.get("sleeve") or ""),
        int(rec.get("tranche") or 0),
        str(rec.get("ticker") or ""),
    )


def tickers_from_state(state: dict | None, extra: list[str] | None = None) -> list[str]:
    """ETF universe + names with units now + names filled since last_run_date.

    Not the whole ledger history (TASK-358): a sold name from months ago does not
    need a Yahoo call every day.
    """
    names = set(V9["etf_universe"])
    names.update(extra or [])
    last = str((state or {}).get("last_run_date") or "")
    for sleeve in ((state or {}).get("sleeves") or {}).values():
        for tr in sleeve.get("tranches") or []:
            names.update(str(t) for t in (tr.get("units") or {}) if t)
    for f in (state or {}).get("ledger") or []:
        t = f.get("ticker")
        if not t or t in ("CASH", "TBILL"):
            continue
        d = str(f.get("exec_date") or "")
        if last and d > last:
            names.add(str(t))
        elif not last:
            names.add(str(t))
    return sorted(names)


def holdings_before(state: dict, as_of: str) -> dict[tuple, float]:
    """(sleeve, tranche, ticker) -> units after events strictly before `as_of`."""
    held: dict[tuple, float] = {}
    events = []
    for f in state.get("ledger") or []:
        if f.get("side") not in ("buy", "sell"):
            continue
        if str(f.get("status") or "") not in FILLED:
            continue
        d = str(f.get("exec_date") or "")
        if not d or d >= as_of:
            continue
        events.append((d, 0, f))
    for w in state.get("write_offs") or []:
        d = str(w.get("date") or "")
        if not d or d >= as_of:
            continue
        events.append((d, 1, w))
    events.sort(key=lambda x: (x[0], x[1]))
    for _, kind, ev in events:
        sleeve = str(ev.get("sleeve") or "")
        k = int(ev.get("tranche") or 0)
        ticker = str(ev.get("ticker") or "")
        if not sleeve or not ticker:
            continue
        key = (sleeve, k, ticker)
        if kind == 1:
            held[key] = 0.0
            continue
        u = held.get(key, 0.0)
        qty = _f(ev.get("units"))
        if ev.get("side") == "buy":
            u += qty
        else:
            u -= qty
        held[key] = u if u > 1e-12 else 0.0
    return held


def apply_dividends(state: dict, table, today: str) -> list[dict]:
    """Credit cash for ex-dates in (last_run_date, today]. Mutates state. Returns new records.

    `table` is an iterable of {ticker, ex_date, dps} (or a DataFrame with those columns).
    No last_run_date -> nothing (first run, all cash). Same key twice -> no-op.
    """
    last = state.get("last_run_date")
    if not last:
        return []
    rows = _as_rows(table)
    existing = {dividend_key(r) for r in (state.get("dividends") or [])}
    state.setdefault("dividends", [])
    new = []
    by_ex: dict[str, list] = {}
    for row in rows:
        ex = str(row.get("ex_date") or "")[:10]
        if not ex or not (str(last) < ex <= str(today)):
            continue
        by_ex.setdefault(ex, []).append(row)
    for ex in sorted(by_ex):
        held = holdings_before(state, ex)
        for row in by_ex[ex]:
            ticker = str(row.get("ticker") or "")
            dps = _f(row.get("dps"))
            if not ticker or dps <= 0:
                continue
            for (sleeve, k, t), units in held.items():
                if t != ticker or units <= 1e-12:
                    continue
                rec = dict(
                    date=str(today), since=str(last),
                    ex_date=ex, sleeve=sleeve, tranche=k, ticker=ticker,
                    units=float(units), dps=float(dps), dollars=float(units * dps),
                )
                if dividend_key(rec) in existing:
                    continue
                tr = state["sleeves"][sleeve]["tranches"][k]
                tr["cash"] = _f(tr.get("cash")) + rec["dollars"]
                state["dividends"].append(rec)
                existing.add(dividend_key(rec))
                new.append(rec)
    return new


def summarize_dividends(state: dict | None) -> dict:
    """Read-only rollup. Missing key -> zeros (old states)."""
    rows = list((state or {}).get("dividends") or [])
    cumulative = 0.0
    by_sleeve: dict[str, float] = {}
    for r in rows:
        d = _f(r.get("dollars"))
        cumulative += d
        sl = str(r.get("sleeve") or "?")
        by_sleeve[sl] = by_sleeve.get(sl, 0.0) + d
    last_date = rows[-1].get("date") if rows else None
    since = [r for r in rows if last_date is not None and r.get("date") == last_date]
    since_from = since[0].get("since") if since else None
    since_total = sum(_f(r.get("dollars")) for r in since)
    since_by: dict[str, float] = {}
    for r in since:
        sl = str(r.get("sleeve") or "?")
        since_by[sl] = since_by.get(sl, 0.0) + _f(r.get("dollars"))
    return {
        "records": rows,
        "cumulative": cumulative,
        "by_sleeve": by_sleeve,
        "since_last_run": since_total,
        "since_from": since_from,
        "since_last_by_sleeve": since_by,
        "last_date": last_date,
    }


def _as_rows(table) -> list[dict]:
    if table is None:
        return []
    if hasattr(table, "to_dict") and hasattr(table, "columns"):
        return [dict(r) for r in table.to_dict(orient="records")]
    return list(table)
