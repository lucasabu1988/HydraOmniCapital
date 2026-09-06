"""Pure helpers to replace presumed v9 fills with confirmed ones (TASK-345).

Does not rebalance. Uses Tranche cash/units math only. Does not import the engine.
"""
from __future__ import annotations

from core.tranche_book import Tranche


def fill_key(row: dict) -> tuple:
    return (
        str(row.get("exec_date") or row.get("date") or ""),
        str(row.get("sleeve") or ""),
        int(row.get("tranche") or 0),
        str(row.get("ticker") or ""),
        str(row.get("side") or ""),
    )


def _tranche(state: dict, sleeve: str, k: int) -> dict:
    return state["sleeves"][sleeve]["tranches"][k]


def _as_tranche(raw: dict) -> Tranche:
    return Tranche(
        cash=float(raw.get("cash") or 0.0),
        units={t: float(u) for t, u in (raw.get("units") or {}).items()},
        last_px={t: float(p) for t, p in (raw.get("last_px") or {}).items()},
    )


def _dump_tranche(raw: dict, tr: Tranche) -> None:
    raw["cash"] = float(tr.cash)
    raw["units"] = {t: float(u) for t, u in tr.units.items() if u > 1e-12}
    raw["last_px"] = {t: float(p) for t, p in tr.last_px.items() if t in raw["units"]}


def _apply_side(tr: Tranche, side: str, ticker: str, units: float, price: float, fee: float, reverse: bool = False):
    """Apply or reverse a buy/sell on a Tranche. No rebalancing."""
    u, p, f = float(units or 0.0), float(price or 0.0), float(fee or 0.0)
    dollars = u * p
    if reverse:
        if side == "buy":
            tr.units[ticker] = tr.units.get(ticker, 0.0) - u
            tr.cash += dollars + f
        elif side == "sell":
            tr.units[ticker] = tr.units.get(ticker, 0.0) + u
            tr.cash -= dollars - f
    else:
        if side == "buy":
            tr.units[ticker] = tr.units.get(ticker, 0.0) + u
            tr.cash -= dollars + f
            if p > 0:
                tr.last_px[ticker] = p
        elif side == "sell":
            tr.units[ticker] = tr.units.get(ticker, 0.0) - u
            tr.cash += dollars - f
    if tr.units.get(ticker, 0.0) <= 1e-12:
        tr.units.pop(ticker, None)
        tr.last_px.pop(ticker, None)


def _same_numbers(fill: dict, row: dict) -> bool:
    def g(a, b, key, rkey=None):
        rkey = rkey or key
        try:
            return abs(float(a.get(key) or 0) - float(b.get(rkey) or 0)) < 1e-9
        except (TypeError, ValueError):
            return a.get(key) == b.get(rkey)

    return (
        g(fill, row, "units")
        and g(fill, row, "price")
        and g(fill, row, "cost", "fee")
        and fill.get("status") in ("confirmed", "confirmed_unplanned")
    )


def apply_confirmations(state: dict, rows: list[dict]) -> dict:
    """Mutate `state` ledger + tranche cash/units. Returns a report dict.

    Matching key: exec_date, sleeve, tranche, ticker, side.
    A row with no presumed fill is recorded as confirmed_unplanned.
    Confirming the same numbers twice is a no-op (idempotent).
    """
    ledger = list(state.get("ledger") or [])
    index = {fill_key(f): i for i, f in enumerate(ledger)}
    report = []
    warnings = []
    for row in rows:
        key = fill_key(row)
        units = float(row.get("units") or 0.0)
        price = float(row.get("price") or 0.0)
        fee = float(row.get("fee") or row.get("cost") or 0.0)
        dollars = units * price
        side = str(row.get("side") or "")
        ticker = str(row.get("ticker") or "")
        sleeve = str(row.get("sleeve") or "")
        k = int(row.get("tranche") or 0)
        rec = {
            "key": key, "units": units, "price": price, "fee": fee,
            "dollars": dollars, "matched": key in index, "changed": False,
        }
        if key in index:
            fill = ledger[index[key]]
            if _same_numbers(fill, row):
                rec["status"] = fill.get("status")
                report.append(rec)
                continue
            raw = _tranche(state, sleeve, k)
            tr = _as_tranche(raw)
            if fill.get("status") == "filled" and fill.get("side") in ("buy", "sell"):
                _apply_side(tr, fill["side"], fill["ticker"], float(fill.get("units") or 0),
                            float(fill.get("price") or 0), float(fill.get("cost") or 0), reverse=True)
            if side in ("buy", "sell"):
                _apply_side(tr, side, ticker, units, price, fee, reverse=False)
            _dump_tranche(raw, tr)
            old_u, old_p = fill.get("units"), fill.get("price")
            fill.update(units=units, price=price, cost=fee, dollars=dollars, status="confirmed")
            rec.update(changed=True, old_units=old_u, old_price=old_p, status="confirmed",
                       cash_after=raw["cash"])
        else:
            warnings.append(f"unplanned fill {key}: recorded as confirmed_unplanned")
            raw = _tranche(state, sleeve, k)
            tr = _as_tranche(raw)
            if side in ("buy", "sell"):
                _apply_side(tr, side, ticker, units, price, fee, reverse=False)
            _dump_tranche(raw, tr)
            new = dict(row, cost=fee, dollars=dollars, status="confirmed_unplanned")
            ledger.append(new)
            index[key] = len(ledger) - 1
            rec.update(changed=True, status="confirmed_unplanned", cash_after=raw["cash"])
        report.append(rec)
    state["ledger"] = ledger
    return {"report": report, "warnings": warnings, "state": state}


def report_lines(result: dict) -> list[str]:
    lines = ["exec_date sleeve tranche side ticker  units  price  $  fee  status  matched"]
    for r in result.get("report") or []:
        k = r["key"]
        lines.append(
            f"{k[0]} {k[1]} {k[2]} {k[4]} {k[3]}  {r['units']:.4f}  {r['price']:.4f}  "
            f"{r['dollars']:.2f}  {r['fee']:.4f}  {r.get('status')}  {r['matched']}"
        )
    for w in result.get("warnings") or []:
        lines.append(f"WARN {w}")
    return lines
