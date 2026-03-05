"""
Rattlesnake Signal Generator — Live Module
===========================================
Generates mean-reversion entry signals for the HYDRA multi-strategy system.
Called by omnicapital_live.py to find Rattlesnake candidates alongside COMPASS.

Signal: Buy stocks that dropped >=8% in 5 days, RSI(5)<25, above SMA200.
Exit: +4% profit target, -5% stop loss, 8-day max hold.
Regime: SPY SMA200 + VIX panic filter.
Universe: S&P 100 (OEX) — most liquid large-caps.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# PARAMETERS
# ============================================================================
R_DROP_THRESHOLD = -0.08
R_DROP_LOOKBACK = 5
R_RSI_PERIOD = 5
R_RSI_THRESHOLD = 25
R_TREND_SMA = 200
R_PROFIT_TARGET = 0.04
R_MAX_HOLD_DAYS = 8
R_STOP_LOSS = -0.05
R_MAX_POSITIONS = 5
R_POSITION_SIZE = 0.20
R_MAX_POS_RISK_OFF = 2
R_VIX_PANIC = 35
R_MIN_AVG_VOLUME = 500_000

# S&P 100 Universe
R_UNIVERSE = [
    'AAPL', 'ABBV', 'ABT', 'ACN', 'ADBE', 'AIG', 'AMGN', 'AMT', 'AMZN', 'AVGO',
    'AXP', 'BA', 'BAC', 'BK', 'BKNG', 'BLK', 'BMY', 'BRK-B', 'C', 'CAT',
    'CHTR', 'CL', 'CMCSA', 'COF', 'COP', 'COST', 'CRM', 'CSCO', 'CVS', 'CVX',
    'DE', 'DHR', 'DIS', 'DOW', 'DUK', 'EMR', 'EXC', 'F', 'FDX', 'GD',
    'GE', 'GILD', 'GM', 'GOOG', 'GS', 'HD', 'HON', 'IBM', 'INTC', 'INTU',
    'JNJ', 'JPM', 'KHC', 'KO', 'LIN', 'LLY', 'LMT', 'LOW', 'MA', 'MCD',
    'MDLZ', 'MDT', 'MET', 'META', 'MMM', 'MO', 'MRK', 'MS', 'MSFT', 'NEE',
    'NFLX', 'NKE', 'NVDA', 'ORCL', 'PEP', 'PFE', 'PG', 'PM', 'PYPL', 'QCOM',
    'RTX', 'SBUX', 'SCHW', 'SO', 'SPG', 'T', 'TGT', 'TMO', 'TMUS', 'TSLA',
    'TXN', 'UNH', 'UNP', 'UPS', 'USB', 'V', 'VZ', 'WBA', 'WFC', 'WMT', 'XOM',
]


def compute_rsi(prices: pd.Series, period: int = 5) -> float:
    """Compute current RSI value for a price series."""
    if len(prices) < period + 1:
        return 50.0  # neutral default
    delta = prices.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else 50.0


def check_rattlesnake_regime(spy_hist: pd.DataFrame, vix_current: float) -> dict:
    """
    Check Rattlesnake regime conditions.
    Returns dict with regime state and whether new entries are allowed.
    """
    regime = 'RISK_ON'
    vix_panic = vix_current > R_VIX_PANIC if vix_current else False

    if len(spy_hist) >= R_TREND_SMA:
        spy_close = spy_hist['Close'].iloc[-1]
        spy_sma = spy_hist['Close'].iloc[-R_TREND_SMA:].mean()
        if spy_close < spy_sma:
            regime = 'RISK_OFF'

    return {
        'regime': regime,
        'vix_panic': vix_panic,
        'entries_allowed': not vix_panic,
        'max_positions': R_MAX_POSITIONS if regime == 'RISK_ON' else R_MAX_POS_RISK_OFF,
    }


def find_rattlesnake_candidates(
    hist_data: Dict[str, pd.DataFrame],
    current_prices: Dict[str, float],
    held_symbols: set,
    max_candidates: int = 5,
) -> List[dict]:
    """
    Find mean-reversion entry candidates from the Rattlesnake universe.

    Args:
        hist_data: Historical price data keyed by symbol
        current_prices: Current prices dict
        held_symbols: Set of symbols already held (by any strategy)
        max_candidates: Maximum candidates to return

    Returns:
        List of candidate dicts sorted by oversold score (most oversold first)
    """
    candidates = []

    for ticker in R_UNIVERSE:
        if ticker in held_symbols:
            continue

        if ticker not in hist_data or ticker not in current_prices:
            continue

        df = hist_data[ticker]
        if len(df) < R_TREND_SMA + 10:
            continue

        current_price = current_prices[ticker]
        if current_price <= 0:
            continue

        close = df['Close']

        # 1. Drop threshold: fell >= 8% in last 5 days
        if len(close) < R_DROP_LOOKBACK + 1:
            continue
        past_price = float(close.iloc[-(R_DROP_LOOKBACK + 1)])
        if past_price <= 0:
            continue
        drop = (current_price / past_price) - 1.0
        if drop > R_DROP_THRESHOLD:
            continue

        # 2. RSI check
        rsi_val = compute_rsi(close, R_RSI_PERIOD)
        if rsi_val > R_RSI_THRESHOLD:
            continue

        # 3. Trend filter: above 200-day SMA
        sma_val = float(close.iloc[-R_TREND_SMA:].mean())
        if current_price < sma_val:
            continue

        # 4. Volume filter
        if 'Volume' in df.columns and len(df) >= 20:
            avg_vol = df['Volume'].iloc[-20:].mean()
            if pd.isna(avg_vol) or avg_vol < R_MIN_AVG_VOLUME:
                continue

        candidates.append({
            'symbol': ticker,
            'score': -drop,  # bigger drop = higher score
            'drop_pct': drop,
            'rsi': rsi_val,
            'price': current_price,
        })

    # Sort by most oversold
    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:max_candidates]


def check_rattlesnake_exit(
    symbol: str,
    entry_price: float,
    current_price: float,
    days_held: int,
) -> Optional[str]:
    """
    Check if a Rattlesnake position should exit.

    Returns exit reason string or None if position should be held.
    """
    pnl_pct = (current_price / entry_price) - 1.0

    if pnl_pct >= R_PROFIT_TARGET:
        return 'PROFIT'
    if pnl_pct <= R_STOP_LOSS:
        return 'STOP'
    if days_held >= R_MAX_HOLD_DAYS:
        return 'TIME'

    return None


def compute_rattlesnake_exposure(positions: list, current_prices: dict,
                                  account_value: float) -> float:
    """
    Compute current Rattlesnake exposure as fraction of account value.
    Used by cash recycling to determine idle capital.
    """
    if account_value <= 0:
        return 0.0

    invested = sum(
        pos.get('shares', 0) * current_prices.get(pos.get('symbol', ''), 0)
        for pos in positions
    )
    return min(invested / account_value, 1.0)
