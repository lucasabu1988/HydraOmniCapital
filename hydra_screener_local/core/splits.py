"""TASK-363 — stock splits in the live book (H-003, pre-registered by Claude; accounting, not scoring).

Yahoo closes are split-adjusted, the book's `units` are not: without this a 2:1 split halves the
position on paper at the next mark and `reconcile` shows a phantom quantity diff. For every split
effective in (watermark, today] on a ticker held in a tranche on that date:

    units *= ratio ; last_px /= ratio ; record in state["splits"]
    {date, since, sleeve, tranche, ticker, ratio, units_before, units_after}

Units held on the split date are reconstructed from the ledger (fills strictly before the date,
earlier splits applied), so a fill settled after the split is not scaled twice. Pending orders that
carry `est_units`/`est_price` for that ticker are rescaled (display); dollar orders are untouched.

ASTRA-02 — order of events by economic date. The caller settles fills and applies splits in two
passes around `settle`: `upto=<execution date>` first (a split effective on or before a fill is
already in the price the fill is booked at, so the position must be scaled BEFORE the fill), then
`after=<execution date>` (a split effective later scales the position the fill left behind). Moving
all splits to the front instead would double a late-confirmed fill's units, and leaving them all
behind leaves a phantom position when a `close` sell lands on the split date.

`state["split_marks"]` is a per-ticker watermark: the last effective date already processed for that
ticker. It is the window's lower bound, so an event the provider publishes late (effective before
`last_run_date`, after the mark) is still applied, and one already processed is never applied twice
even where no tranche held the name and no `state["splits"]` record was written. Idempotent on
(date, sleeve, tranche, ticker) and on the mark. Pure; mutates the state dict it is given.
"""
from __future__ import annotations

import pandas as pd

from core.dividends import FILLED, _f, holdings_before


class SplitOrderError(Exception):
    """A split effective on a date whose fills are already booked (order of events violated)."""


def split_key(rec: dict) -> tuple:
    return (str(rec.get("date") or ""), str(rec.get("sleeve") or ""), int(rec.get("tranche") or 0),
            str(rec.get("ticker") or ""))


def _as_rows(table) -> list[dict]:
    if table is None:
        return []
    if isinstance(table, pd.DataFrame):
        return table.to_dict("records")
    return [dict(r) for r in table]


def _fills_on(state: dict, date: str, ticker: str) -> list[str]:
    """"stocks[0]" for every filled buy/sell of `ticker` already booked at `date`."""
    out = []
    for f in state.get("ledger") or []:
        if str(f.get("ticker") or "") != ticker or str(f.get("exec_date") or "") != date:
            continue
        if str(f.get("status") or "") not in FILLED or f.get("side") not in ("buy", "sell"):
            continue
        out.append(f"{f.get('sleeve')}[{f.get('tranche')}]")
    return out


def split_mark(state: dict, ticker: str) -> str:
    """Last split effective date already processed for `ticker` ("" if never)."""
    return str(((state or {}).get("split_marks") or {}).get(str(ticker)) or "")


def apply_splits(state: dict, table, today: str, *, upto: str | None = None,
                 after: str | None = None) -> list[dict]:
    """Scale units for splits effective in (lower bound, today]. Returns the new records.

    Lower bound = the ticker's watermark if it has one, else `last_run_date`, raised to `after`
    when given. Upper bound = `today`, lowered to `upto` when given. Both bounds are exclusive on
    the left and inclusive on the right, so an event effective exactly on `upto` belongs to this
    pass and one effective exactly on `after` does not.
    """
    last = state.get("last_run_date")
    if not last:
        return []
    rows = _as_rows(table)
    state.setdefault("splits", [])
    marks = state.setdefault("split_marks", {})
    existing = {split_key(r) for r in state["splits"]}
    hi = str(today)
    if upto is not None and str(upto) < hi:
        hi = str(upto)
    events: dict[tuple[str, str], float] = {}
    for row in rows:
        d = str(row.get("date") or "")[:10]
        ratio = _f(row.get("ratio"))
        ticker = str(row.get("ticker") or "")
        if not d or not ticker or ratio <= 0 or ratio == 1.0:
            continue
        lo = str(marks.get(ticker) or last)
        if after is not None and str(after) > lo:
            lo = str(after)
        if not (lo < d <= hi):
            continue
        events[(d, ticker)] = float(ratio)      # a provider repeat inside one table is one event

    by_date: dict[str, list[tuple[str, float]]] = {}
    for (d, ticker), ratio in events.items():
        by_date.setdefault(d, []).append((ticker, ratio))

    new = []
    for d in sorted(by_date):
        held = holdings_before(state, d)            # ledger fills + write-offs + recorded splits before d
        for ticker, ratio in sorted(by_date[d]):
            # Fail closed on the order of events. A fill booked at `d` in THIS cycle (d after the
            # last plan) was priced post-split, so the position had to be scaled before it: the
            # traded units are gone and scaling the pre-event base now would hand the tranche a
            # phantom position (ASTRA-02, `close` sell on the split date). No unit arithmetic can
            # repair it here, so refuse instead of writing a wrong book. A fill at `d` booked in an
            # earlier cycle (d on or before the last plan) is a provider publishing the event late:
            # that fill is already post-split and the pre-`d` base is the right one, so it stands.
            booked = _fills_on(state, d, ticker) if d > str(last) else []
            if booked:
                raise SplitOrderError(
                    f"split {ticker} x{ratio:g} effective {d} reached apply_splits after the "
                    f"fill(s) already booked that day in {', '.join(booked)}; apply the splits "
                    f"effective on or before the execution date first (upto=<exec_date>), settle, "
                    f"then the rest (after=<exec_date>)")
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
            # the mark moves even when nothing was held: the event has been processed, and a
            # provider replaying it must not rescale the pending estimates a second time.
            if d > str(marks.get(ticker) or ""):
                marks[ticker] = d
    return new


def summarize_splits(state: dict | None) -> dict:
    rows = list((state or {}).get("splits") or [])
    last_since = rows[-1].get("since") if rows else None
    since = [r for r in rows if last_since is not None and r.get("since") == last_since]
    return {"records": rows, "count": len(rows), "since_last_run": since, "last_date": rows[-1].get("date") if rows else None}
