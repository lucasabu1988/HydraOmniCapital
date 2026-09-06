"""Average-cost lots from the v9 ledger (TASK-367: one implementation, shared by the dashboard
and the attribution analytics).

Rule (per sleeve / tranche / ticker):
  filled buy  : qty += u;  cost_total += u * price;  avg = cost_total / qty
  filled sell : realised += (price - avg) * u;  qty -= u;  cost_total = avg * qty
  write-off   : realised += proceeds - cost_total;  qty = 0
  Fees (`cost` on fills) are tracked separately and are NOT in avg.
  not_filled / noted / transfers do not move units.
Pure; no I/O.
"""
from __future__ import annotations

from core.ledger import CASH_TICKERS, EFFECTIVE_STATUSES, is_trade

# Audit phase 1.7: no module keeps a private copy of "counts as a fill". This name stays
# because callers import it; it is the canonical set, not a second one.
FILLED_STATUSES = EFFECTIVE_STATUSES


def _f(x, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        v = float(x)
        if v != v:  # NaN
            return default
        return v
    except (TypeError, ValueError):
        return default


def lots_from_ledger(state: dict, *, statuses=None) -> dict:
    """(sleeve, tranche, ticker) -> {qty, cost_total, realised, fees}.

    The default projection is `core.ledger.is_trade` — every event that moves units of a
    real ticker. `statuses` narrows it to an explicit set, which is only for a caller that
    deliberately wants less than the book (R-108: the dashboard used to want "filled" only,
    and that is exactly the defect)."""
    lots: dict = {}

    def slot(sleeve, tranche, ticker):
        key = (sleeve, int(tranche), str(ticker))
        if key not in lots:
            lots[key] = {"qty": 0.0, "cost_total": 0.0, "realised": 0.0, "fees": 0.0}
        return lots[key]

    for fill in (state or {}).get("ledger") or []:
        if not is_trade(fill):
            continue
        if statuses is not None and fill.get("status") not in statuses:
            continue
        side = fill.get("side")
        ticker = fill.get("ticker")
        lot = slot(fill.get("sleeve"), fill.get("tranche", 0), ticker)
        u = _f(fill.get("units"))
        px = _f(fill.get("price"))
        lot["fees"] += _f(fill.get("cost"))
        if u <= 0 or px <= 0:
            continue
        if side == "buy":
            lot["qty"] += u
            lot["cost_total"] += u * px
        else:
            sold = min(u, lot["qty"])
            avg = lot["cost_total"] / lot["qty"] if lot["qty"] else 0.0
            lot["realised"] += (px - avg) * sold
            lot["qty"] -= sold
            lot["cost_total"] = avg * lot["qty"]

    for wo in (state or {}).get("write_offs") or []:
        ticker = wo.get("ticker")
        if not ticker:
            continue
        lot = slot(wo.get("sleeve"), wo.get("tranche", 0), ticker)
        lot["realised"] += _f(wo.get("proceeds")) - lot["cost_total"]
        lot["qty"] = 0.0
        lot["cost_total"] = 0.0
    return lots
