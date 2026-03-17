"""
Catalyst Signals -- 4th Pillar: Cross-Asset Trend + Gold
=========================================================
10% of capital: equal-weight among ETFs above their SMA200
5% of capital: permanent gold (GLD) allocation

Trend assets: SPY, EFA, TLT, GLD, DBC
Rule: every 5 days, hold those above 200-day SMA. If none qualify, cash.
Gold: always hold GLD (separate from trend basket).

Backtest reference: EXP68 — CAGR 14.42% -> 15.62%, Sharpe 0.908 -> 1.079
"""
import logging
from typing import Dict, List

import pandas as pd

logger = logging.getLogger(__name__)

# Parameters
# Only assets NOT managed by other HYDRA pillars
# SPY excluded: covered by COMPASS (Momentum)
# EFA excluded: covered by EFA passive pillar
CATALYST_TREND_ASSETS = ['TLT', 'GLD', 'DBC']
CATALYST_GOLD_SYMBOL = 'GLD'
CATALYST_SMA_PERIOD = 200
CATALYST_REBALANCE_DAYS = 5

# Allocation within the 15% catalyst budget
CATALYST_TREND_WEIGHT = 0.667   # 10% of total = 2/3 of catalyst
CATALYST_GOLD_WEIGHT = 0.333    # 5% of total = 1/3 of catalyst


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
    trend_budget = catalyst_budget * CATALYST_TREND_WEIGHT
    gold_budget = catalyst_budget * CATALYST_GOLD_WEIGHT

    targets = []

    # 1. Cross-asset trend: equal-weight among qualifying assets
    trend_holdings = compute_trend_holdings(hist_data)
    if trend_holdings:
        per_asset = trend_budget / len(trend_holdings)
        for ticker in trend_holdings:
            price = current_prices.get(ticker, 0)
            if price <= 0:
                logger.warning(f"Catalyst: skipping {ticker} — zero/negative price ({price})")
                continue
            if price > 0:
                shares = int(per_asset / price)
                if shares > 0:
                    targets.append({
                        'symbol': ticker,
                        'target_shares': shares,
                        'target_value': shares * price,
                        'sub_strategy': 'trend',
                    })

    # 2. Gold: permanent allocation
    gold_price = current_prices.get(CATALYST_GOLD_SYMBOL, 0)
    if gold_price > 0:
        gold_shares = int(gold_budget / gold_price)
        if gold_shares > 0:
            existing = [t for t in targets if t['symbol'] == CATALYST_GOLD_SYMBOL]
            if existing:
                existing[0]['target_shares'] += gold_shares
                existing[0]['target_value'] += gold_shares * gold_price
                existing[0]['sub_strategy'] = 'trend+gold'
            else:
                targets.append({
                    'symbol': CATALYST_GOLD_SYMBOL,
                    'target_shares': gold_shares,
                    'target_value': gold_shares * gold_price,
                    'sub_strategy': 'gold',
                })

    logger.info(f"Catalyst targets: {len(targets)} positions, "
                f"trend={len(trend_holdings)}/{len(CATALYST_TREND_ASSETS)} above SMA200, "
                f"budget=${catalyst_budget:,.0f}")
    return targets
