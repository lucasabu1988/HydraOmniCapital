"""TASK-363 — stock splits in the live book (H-003, pre-registered by Claude; accounting, not scoring).

Yahoo closes are split-adjusted, the book's `units` are not: without this a 2:1 split halves the
position on paper at the next mark and `reconcile` shows a phantom quantity diff. For every split
effective in (last_run_date, today] on a ticker held in a tranche on that date:

    units *= ratio ; last_px /= ratio ; record in state["splits"]
    {date, since, sleeve, tranche, ticker, ratio, units_before, units_after}

Units held on the split date are reconstructed from the ledger (fills strictly before the date,
earlier splits applied), so a fill settled after the split is not scaled twice. Pending orders that
carry `est_units`/`est_price` for that ticker are rescaled (display); dollar orders are untouched;
`close` orders sell whatever units the tranche holds at settle, so they need nothing.
Idempotent on (date, sleeve, tranche, ticker). Pure; mutates the state dict it is given.
"""
from __future__ import annotations

import pandas as pd

from core.dividends import _f, holdings_before


def split_key(rec: dict) -> tuple:
    return (str(rec.get("date") or ""), str(rec.get("sleeve") or ""), int(rec.get("tranche") or 0),
            str(rec.get("ticker") or ""))


def _as_rows(table) -> list[dict]:
    if table is None:
        return []
    if isinstance(table, pd.DataFrame):
        return table.to_dict("records")
    return [dict(r) for r in table]


def apply_splits(state: dict, table, today: str) -> list[dict]:
    """Scale units for splits in (last_run_date, today]. Returns the new records."""
    last = state.get("last_run_date")
    if not last:
        return []
    rows = _as_rows(table)
    state.setdefault("splits", [])
    existing = {split_key(r) for r in state["splits"]}
    by_date: dict[str, list[dict]] = {}
    for row in rows:
        d = str(row.get("date") or "")[:10]
        ratio = _f(row.get("ratio"))
        ticker = str(row.get("ticker") or "")
        if not d or not ticker or ratio <= 0 or ratio == 1.0:
            continue
        if not (str(last) < d <= str(today)):
            continue
        by_date.setdefault(d, []).append((ticker, ratio))

    new = []
    for d in sorted(by_date):
        held = holdings_before(state, d)            # ledger fills + write-offs + recorded splits before d
        for ticker, ratio in by_date[d]:
            for (sleeve, k, t), units in held.items():
                if t != ticker or units <= 1e-12:
                    continue
                rec = dict(date=d, since=str(last), sleeve=sleeve, tranche=int(k), ticker=ticker,
                           ratio=float(ratio), units_before=float(units), units_after=float(units * ratio))
                if split_key(rec) in existing:
                    continue
                tr = state["sleeves"][sleeve]["tranches"][int(k)]
                cur = _f((tr.get("units") or {}).get(ticker))
                # scale only the pre-split part: current units may include a fill settled after d
                delta = float(units) * (ratio - 1.0)
                tr.setdefault("units", {})[ticker] = cur + delta
                lp = tr.get("last_px") or {}
                if ticker in lp and _f(lp.get(ticker)) > 0:
                    lp[ticker] = _f(lp[ticker]) / ratio
                    tr["last_px"] = lp
                state["splits"].append(rec)
                existing.add(split_key(rec))
                new.append(rec)
            for o in state.get("pending") or []:
                if str(o.get("ticker") or "") != ticker:
                    continue
                if o.get("est_units") is not None:
                    o["est_units"] = _f(o["est_units"]) * ratio
                if o.get("est_price") is not None and _f(o["est_price"]) > 0:
                    o["est_price"] = _f(o["est_price"]) / ratio
    return new


def summarize_splits(state: dict | None) -> dict:
    rows = list((state or {}).get("splits") or [])
    last_since = rows[-1].get("since") if rows else None
    since = [r for r in rows if last_since is not None and r.get("since") == last_since]
    return {"records": rows, "count": len(rows), "since_last_run": since, "last_date": rows[-1].get("date") if rows else None}
