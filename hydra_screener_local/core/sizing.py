"""Whole-share sizing: what the sheet asks for in dollars vs what whole shares can actually buy.

The engine books dollars and fractional units; a broker fills whole shares. TASK-407 measured the
cost and put the per-order floor on the instruction sheet. The paper book (2026-09-10) needs the
same fact as one number per run, kept in the journal so it accumulates as evidence:

    sizing loss_t = target risky exposure_t - achievable whole-share exposure_t

over the BUY orders of the run (sells close positions and are never floored). Display and
measurement only: nothing here changes an order, a fill or the book.
"""
from __future__ import annotations

import math


def whole_share(order: dict) -> dict | None:
    """Floor one buy or trim to whole shares at its estimated price. None when the order carries no
    usable price or is not a priced buy/sell (transfers, parks, unpriced holds)."""
    # Same rule as the sheet has shown since TASK-407 (portfolio_v9.whole_share_display delegates here).
    if order.get("side") not in ("buy", "sell"):
        return None
    dollars = float(order.get("dollars") or 0.0)
    price = order.get("est_price")
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None
    if price is None or not math.isfinite(price) or price <= 0 or not math.isfinite(dollars) or dollars <= 0:
        return None
    shares = int(math.floor(dollars / price))
    at = shares * price
    return {"shares": shares, "at_est": round(at, 4), "leftover": round(dollars - at, 4)}


def sizing_summary(orders: list | None) -> dict:
    """One record per run over the priced BUY orders: dollars asked, dollars whole shares can place,
    the difference in dollars and as a share of the ask, how many buys round to zero shares and which."""
    target = 0.0
    achievable = 0.0
    n_buys = 0
    zero: list[str] = []
    for o in orders or []:
        if str(o.get("side") or "") != "buy":
            continue
        ws = whole_share(o)
        if ws is None:
            continue
        n_buys += 1
        target += float(o.get("dollars"))
        achievable += ws["at_est"]
        if ws["shares"] == 0:
            zero.append(str(o.get("ticker")))
    loss = target - achievable
    return {
        "n_buys": n_buys,
        "target_dollars": round(target, 2),
        "achievable_dollars": round(achievable, 2),
        "loss_dollars": round(loss, 2),
        "loss_share": round(loss / target, 4) if target > 0 else None,
        "n_zero_share": len(zero),
        "zero_share_names": sorted(zero),
    }
