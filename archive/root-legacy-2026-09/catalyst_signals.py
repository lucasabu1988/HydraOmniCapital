"""
Catalyst Signals -- 4th Pillar: Cross-Asset Trend
===================================================
15% of capital: equal-weight among ETFs above their SMA200

Trend assets: TLT, ZROZ, GLD, DBC (SPY/EFA excluded — managed by other pillars)
Rule: every 5 days, hold those above 200-day SMA. If none qualify, cash.
Gold participates via trend filter (GLD held only when above SMA200).

Backtest reference:
  EXP68 — CAGR 14.42% -> 15.62%, Sharpe 0.908 -> 1.079 (original 10/5 split)
  EXP71 — CAGR 17.05% -> 18.15%, Sharpe 1.293 -> 1.365 (15% trend, no perm gold)
"""
import logging
from typing import Dict, List

import pandas as pd

logger = logging.getLogger(__name__)

# Parameters
# Only assets NOT managed by other HYDRA pillars
# SPY excluded: covered by COMPASS (Momentum)
# EFA excluded: covered by EFA passive pillar
CATALYST_TREND_ASSETS = ['TLT', 'ZROZ', 'GLD', 'DBC']
CATALYST_GOLD_SYMBOL = None  # no permanent gold — GLD participates via trend filter
CATALYST_SMA_PERIOD = 200
CATALYST_REBALANCE_DAYS = 5

# Allocation: 100% of catalyst budget goes to trend basket
CATALYST_TREND_WEIGHT = 1.0     # 15% of total portfolio
CATALYST_GOLD_WEIGHT = 0.0      # no permanent gold (EXP71: +1.10% CAGR, +0.073 Sharpe)


def compute_trend_holdings(hist_data: Dict[str, pd.DataFrame]) -> List[str]:
    """Determine which trend assets are above their SMA200."""
    holdings = []
    for ticker in CATALYST_TREND_ASSETS:
        df = hist_data.get(ticker)
        if df is None or len(df) < CATALYST_SMA_PERIOD:
            continue
        close = float(df['Close'].iloc[-1])
        sma = float(df['Close'].iloc[-CATALYST_SMA_PERIOD:].mean())
        if close > sma:
            holdings.append(ticker)
            logger.debug(f"Catalyst trend: {ticker} ABOVE SMA200 ({close:.2f} > {sma:.2f})")
        else:
            logger.debug(f"Catalyst trend: {ticker} below SMA200 ({close:.2f} < {sma:.2f})")
    return holdings


def compute_catalyst_targets(hist_data: Dict[str, pd.DataFrame],
                              catalyst_budget: float,
                              current_prices: Dict[str, float]) -> List[Dict]:
    """Compute target positions for the Catalyst pillar.

    Returns list of {symbol, target_shares, target_value, sub_strategy}
    """
    targets = []

    trend_holdings = compute_trend_holdings(hist_data)
    if trend_holdings:
        per_asset = catalyst_budget / len(trend_holdings)
        for ticker in trend_holdings:
            price = current_prices.get(ticker, 0)
            if price <= 0:
                logger.warning(f"Catalyst: skipping {ticker} — zero/negative price ({price})")
                continue
            shares = int(per_asset / price)
            if shares > 0:
                targets.append({
                    'symbol': ticker,
                    'target_shares': shares,
                    'target_value': shares * price,
                    'sub_strategy': 'trend',
                })

    logger.info(f"Catalyst targets: {len(targets)} positions, "
                f"trend={len(trend_holdings)}/{len(CATALYST_TREND_ASSETS)} above SMA200, "
                f"budget=${catalyst_budget:,.0f}")
    return targets
