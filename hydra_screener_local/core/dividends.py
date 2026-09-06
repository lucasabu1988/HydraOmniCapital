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

from datetime import datetime, timedelta, timezone

from config import DIVIDEND_OVERLAP_DAYS, V9
from core.ledger import EFFECTIVE_STATUSES
from typing import cast

from core.numbers import as_finite, is_finite_money

#: kept as a module name for callers; the definition lives in core.ledger
FILLED = EFFECTIVE_STATUSES

# --- event stages (phase 4.6) ----------------------------------------------------
# raw        what the provider returned, untouched (data/dividends.fetch_dividends)
# normalized deduped, validated, provenance-tagged (normalize_dividends)
# applied    credited to a tranche and recorded in state["dividends"] (apply_dividends)
RAW = "raw"
NORMALIZED = "normalized"
APPLIED = "applied"
RETRACTED = "retracted"


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _shift_days(date: str, days: int) -> str:
    return str((datetime.fromisoformat(str(date)[:10]) - timedelta(days=int(days))).date())


def coverage_through(state: dict | None) -> str | None:
    """How far dividend coverage is *verified*, not merely how far the book has run.

    Old states have no coverage record; `last_run_date` is the only watermark they
    ever had, so it is the migration fallback.
    """
    cov = (state or {}).get("dividend_coverage") or {}
    through = cov.get("through")
    return str(through) if through else ((state or {}).get("last_run_date") or None)


def query_window(state: dict | None, today: str, *, overlap_days: int | None = None) -> tuple[str, str]:
    """(start, end] to ask the provider about. Start is pulled back by the overlap.

    Phase 4.3. Without the overlap, a dividend the provider first published after the
    watermark had moved past its ex-date could never be credited (repro R-401).
    """
    overlap = DIVIDEND_OVERLAP_DAYS if overlap_days is None else int(overlap_days)
    through = coverage_through(state)
    if not through:
        return (str(today), str(today))
    return (_shift_days(through, overlap), str(today))


def is_verified(report: dict | None) -> bool:
    """Did the provider answer for every ticker we asked about?

    Fail closed: no report at all is *not* verified. `no_dividends` only counts as
    coverage when the ticker carries a fetch stamp, which is what data/dividends.py
    records (TASK-385).
    """
    if not report:
        return False
    if report.get("failed_tickers"):
        return False
    requested = report.get("requested")
    if requested is None:
        return False
    answered = len(report.get("skipped_fresh") or []) + int(report.get("downloaded") or 0)
    return answered >= int(requested)


def unverified_tickers(report: dict | None) -> list[str]:
    return sorted(str(t) for t in ((report or {}).get("failed_tickers") or []))


def normalize_dividends(table, *, source: str = "unknown", fetched_at: str | None = None) -> dict:
    """Raw provider rows -> validated, deduped, provenance-tagged rows (phase 4.6).

    Returns {"rows", "rejected", "conflicts"}. A non-finite or non-positive dps is a
    *rejected* row, not a silently dropped one (repro R-406), and two different
    amounts for the same (ticker, ex_date) are reported as a conflict instead of
    first-wins (repro R-405).
    """
    stamp = fetched_at or _utc()
    seen: dict[tuple, dict] = {}
    rejected: list[dict] = []
    conflicts: list[dict] = []
    for row in _as_rows(table):
        ticker = str(row.get("ticker") or "").strip().upper()
        ex = str(row.get("ex_date") or "")[:10]
        dps = row.get("dps")
        if not ticker:
            rejected.append({"row": dict(row), "reason": "empty ticker"})
            continue
        if not ex or len(ex) != 10:
            rejected.append({"row": dict(row), "reason": f"bad ex_date {row.get('ex_date')!r}"})
            continue
        if not is_finite_money(dps):
            rejected.append({"row": dict(row), "reason": f"dps is not finite: {dps!r}"})
            continue
        dps_num = as_finite(dps)          # the guard above rules out None and junk
        if dps_num <= 0.0:
            rejected.append({"row": dict(row), "reason": f"dps must be > 0, got {dps!r}"})
            continue
        key = (ticker, ex)
        rec = {"ticker": ticker, "ex_date": ex, "dps": float(dps_num),
               "stage": NORMALIZED, "source": str(source), "fetched_at": stamp}
        prior = seen.get(key)
        if prior is None:
            seen[key] = rec
            continue
        if abs(prior["dps"] - rec["dps"]) > 1e-12:
            conflicts.append({"ticker": ticker, "ex_date": ex,
                              "values": sorted({prior["dps"], rec["dps"]})})
            seen[key] = max(prior, rec, key=lambda r: r["dps"])   # the larger, and it is reported
    rows = [seen[k] for k in sorted(seen)]
    return {"rows": rows, "rejected": rejected, "conflicts": conflicts}


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


def etf_universe() -> list[str]:
    """`V9["etf_universe"]` as a list of strings. V9 is a heterogeneous config dict,
    so every read out of it is untyped; this is the one place that says what it is."""
    return [str(t) for t in cast("list[str]", V9["etf_universe"])]


def tickers_from_state(state: dict | None, extra: list[str] | None = None) -> list[str]:
    """ETF universe + names with units now + names filled since last_run_date.

    Not the whole ledger history (TASK-358): a sold name from months ago does not
    need a Yahoo call every day.
    """
    names = set(etf_universe())
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
    # TASK-363: a split effective before `as_of` scales the units held at its open. Splits sort
    # before that day's fills (kind -1): fills settled on or after the split date are post-split.
    for sp in state.get("splits") or []:
        d = str(sp.get("date") or "")
        if not d or d >= as_of:
            continue
        events.append((d, -1, sp))
    events.sort(key=lambda x: (x[0], x[1]))
    for _, kind, ev in events:
        sleeve = str(ev.get("sleeve") or "")
        k = int(ev.get("tranche") or 0)
        ticker = str(ev.get("ticker") or "")
        if not sleeve or not ticker:
            continue
        key = (sleeve, k, ticker)
        if kind == -1:
            if key in held and held[key] > 1e-12:
                held[key] = held[key] * _f(ev.get("ratio"), 1.0)
            continue
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


def apply_dividends(state: dict, table, today: str, *, report: dict | None = None,
                    fetch_report: dict | None = None, overlap_days: int | None = None,
                    source: str = "unknown") -> list[dict]:
    """Credit cash for ex-dates in the overlap window. Mutates state. Returns new records.

    `table` is an iterable of {ticker, ex_date, dps} (or a DataFrame with those
    columns). Idempotent on (ex_date, sleeve, tranche, ticker).

    Two things changed in audit phase 4:

    * The window is `(coverage_through - DIVIDEND_OVERLAP_DAYS, today]`, not
      `(last_run_date, today]`. A provider that publishes an ex-date late used to
      lose that dividend permanently, because `plan()` advanced `last_run_date`
      whether or not the dividend query had succeeded (repro R-401).
    * The coverage watermark advances **only when the fetch is verified**. An
      unverified window is recorded in `state["dividend_gaps"]` — the pending queue
      the next run retries (phase 4.1/4.2/4.5).

    `fetch_report` is the report dict from `data.dividends.fetch_dividends`; without
    it the run counts as unverified and the watermark holds. Diagnostics are written
    into `report` in place.
    """
    out = report if report is not None else {}
    last = state.get("last_run_date")
    if not last:
        out.update(window=None, credited=0, verified=False, reason="first run")
        return []

    norm = normalize_dividends(table, source=source)
    start, end = query_window(state, today, overlap_days=overlap_days)
    verified = is_verified(fetch_report)

    existing = {dividend_key(r) for r in (state.get("dividends") or [])
                if r.get("stage") != RETRACTED}
    state.setdefault("dividends", [])
    new: list[dict] = []
    by_ex: dict[str, list] = {}
    for row in norm["rows"]:
        ex = row["ex_date"]
        if not (str(start) < ex <= str(end)):
            continue
        by_ex.setdefault(ex, []).append(row)
    for ex in sorted(by_ex):
        held = holdings_before(state, ex)
        for row in by_ex[ex]:
            ticker = row["ticker"]
            dps = float(row["dps"])
            for (sleeve, k, tkr), units in held.items():
                if tkr != ticker or units <= 1e-12:
                    continue
                rec = dict(
                    date=str(today), since=str(start),
                    ex_date=ex, sleeve=sleeve, tranche=k, ticker=ticker,
                    units=float(units), dps=dps, dollars=float(units * dps),
                    stage=APPLIED, source=row.get("source"), fetched_at=row.get("fetched_at"),
                    applied_at=_utc(), revision=1,
                )
                if dividend_key(rec) in existing:
                    continue
                tr = state["sleeves"][sleeve]["tranches"][k]
                tr["cash"] = _f(tr.get("cash")) + rec["dollars"]
                state["dividends"].append(rec)
                existing.add(dividend_key(rec))
                new.append(rec)

    _record_coverage(state, today, start=start, verified=verified,
                     fetch_report=fetch_report, credited=len(new))
    out.update(
        window=[start, end],
        credited=len(new),
        dollars=round(sum(r["dollars"] for r in new), 6),
        verified=verified,
        unverified_tickers=unverified_tickers(fetch_report),
        rejected=norm["rejected"],
        conflicts=norm["conflicts"],
        coverage_through=coverage_through(state),
        open_gaps=len(pending_gaps(state)),
    )
    return new


def _record_coverage(state: dict, today: str, *, start: str, verified: bool,
                     fetch_report: dict | None, credited: int) -> None:
    """Advance the watermark only on a verified fetch; otherwise queue the gap."""
    cov = dict(state.get("dividend_coverage") or {})
    previous = cov.get("through")
    cov.update(
        checked_at=_utc(),
        last_attempt=str(today),
        last_window=[str(start), str(today)],
        last_verified=bool(verified),
        credited_last_run=int(credited),
    )
    if verified:
        cov["through"] = str(today)
        cov["verified_at"] = _utc()
        _close_gaps(state, str(today))
    else:
        cov["through"] = previous if previous else None
        _open_gap(state, start=str(start), end=str(today),
                  tickers=unverified_tickers(fetch_report),
                  reason="provider not verified for every requested ticker")
    state["dividend_coverage"] = cov


def _open_gap(state: dict, *, start: str, end: str, tickers: list[str], reason: str) -> dict:
    """Queue an unverified window. Re-opening the same window updates it in place."""
    gaps = state.setdefault("dividend_gaps", [])
    for g in gaps:
        if g.get("start") == start and g.get("end") == end and g.get("status") == "open":
            g.update(seen=int(g.get("seen") or 1) + 1, tickers=tickers, at=_utc())
            return g
    gap = {"start": start, "end": end, "tickers": tickers, "reason": reason,
           "status": "open", "seen": 1, "at": _utc()}
    gaps.append(gap)
    return gap


def _close_gaps(state: dict, through: str) -> int:
    """Close every open gap the verified window now covers.

    Append-only: the record stays and only its status changes, so an audit can still
    see that the outage happened.
    """
    n = 0
    for g in state.get("dividend_gaps") or []:
        if g.get("status") == "open" and str(g.get("end") or "") <= str(through):
            g.update(status="closed", closed_at=_utc(), closed_through=str(through))
            n += 1
    return n


def pending_gaps(state: dict | None) -> list[dict]:
    """Windows whose dividend coverage was never verified (phase 4.2/4.5)."""
    return [g for g in ((state or {}).get("dividend_gaps") or []) if g.get("status") == "open"]


def coverage_is_complete(state: dict | None, today: str) -> bool:
    """True only if coverage is verified through `today` and no gap is open.

    Phase 4.5: coverage is never reported complete while a window went unobserved.
    """
    if pending_gaps(state):
        return False
    through = ((state or {}).get("dividend_coverage") or {}).get("through")
    return bool(through) and str(through) >= str(today)


def retract_dividend(state: dict, key: tuple, *, reason: str, today: str | None = None) -> dict | None:
    """Reverse a credited dividend the provider has withdrawn (phase 4.4).

    The record is versioned, not deleted: cash goes back to the tranche and the
    record's stage becomes `retracted`, so `apply_dividends` may credit a corrected
    amount afterwards. Retracting twice is a no-op.
    """
    for rec in state.get("dividends") or []:
        if dividend_key(rec) != tuple(key):
            continue
        if rec.get("stage") == RETRACTED:
            return None
        sleeve, k = str(rec.get("sleeve") or ""), int(rec.get("tranche") or 0)
        try:
            tr = state["sleeves"][sleeve]["tranches"][k]
        except (KeyError, IndexError, TypeError):
            return None
        tr["cash"] = _f(tr.get("cash")) - _f(rec.get("dollars"))
        rec.setdefault("revisions", []).append({
            "stage": rec.get("stage"), "dps": rec.get("dps"), "dollars": rec.get("dollars"),
            "revision": rec.get("revision", 1),
        })
        rec.update(stage=RETRACTED, retracted_at=_utc(), retracted_on=str(today or ""),
                   retract_reason=str(reason), revision=int(rec.get("revision", 1)) + 1)
        return rec
    return None


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
