"""
Experiment 43: COMPASS v9 "Adaptive Shield" Strategy
======================================================

A fundamentally redesigned strategy to beat COMPASS v8.2's bias-corrected benchmarks:
- 13.90% CAGR (2000-2026, 26 years)
- 0.646 Sharpe ratio
- -66.25% max drawdown
- Starting capital: $100,000

DIAGNOSIS OF v8.2 WEAKNESSES:
================================
1. EXCESSIVE STOP-LOSS TRIGGERS: -15% portfolio stop fires 10+ times in 26 years,
   each followed by 6 months of 0.3x leverage protection mode. This is the #1 source
   of underperformance -- the strategy sits in cash during recoveries.

2. PROTECTION MODE DEATH SPIRAL: During protection S1 at 0.3x leverage with only 2
   positions, the strategy continues losing while missing the recovery. In 2022, the
   stop fired at -18% but the equity curve fell to -39% because protection mode
   failed to protect AND missed the rebound.

3. SINGLE BINARY REGIME: SPY > SMA200 is too slow and binary. By the time regime
   flips to RISK_OFF, the market has already dropped significantly. And it stays
   RISK_OFF too long after recovery begins.

4. CONCENTRATED POSITIONS: 5 positions means one bad stock can trigger the -15%
   portfolio stop. This is the root cause of most stop-loss events.

5. SHORT HOLD PERIOD: 5-day holds generate ~1000 trades/year. Each trade has costs
   and is a noise-driven decision. Multi-week momentum is more reliable.

6. NO CORRELATION AWARENESS: Top-5 momentum stocks are often in the same sector
   (tech), creating hidden concentration risk.

ADAPTIVE SHIELD ARCHITECTURE:
=================================

SIGNAL LAYER:
- Dual momentum: Absolute (vs cash) + Relative (cross-sectional rank)
- Quality filter: Exclude stocks with >60% annualized vol
- Multi-timeframe: 60d + 120d + 252d momentum blend (avoiding single-period fragility)
- Skip period: 10 trading days (improved mean-reversion capture vs 5d)

REGIME LAYER (Multi-Signal):
- Trend: SPY vs SMA200 (long-term), SPY vs SMA50 (medium-term)
- Volatility: 20d realized vol vs 63d median vol (volatility breakout detection)
- Breadth: % of universe stocks above their own SMA50 (market internals)
- Combined regime score: 0.0 (extreme bear) to 1.0 (strong bull)
- Graduated: not binary risk_on/risk_off but 5 regime states

POSITION MANAGEMENT:
- 12 positions in bull (diversification benefit vs 5, manageable vs 66)
- 6 positions in mild bear
- 3 positions in severe bear
- Sector cap: max 3 stocks per sector (prevent concentration)
- Equal weight within positions (simpler, avoids inverse-vol overfitting)

RISK MANAGEMENT (the key innovation):
- NO portfolio stop-loss (the biggest source of v8.2 losses)
- Instead: SMOOTH drawdown-based leverage scaling
  * 0% to -5% DD: Full 1.0x leverage
  * -5% to -15% DD: Linear scale from 1.0x to 0.5x
  * -15% to -25% DD: Linear scale from 0.5x to 0.25x
  * Beyond -25% DD: Hold at 0.25x (never go to 0, always stay invested)
- Position stop-loss: -12% (wider than v8.2's -8%, reduces whipsaw)
- Trailing stop: 5% from peak (after +8% gain activation)
- NO protection mode (biggest innovation -- eliminates recovery delay)

HOLD PERIOD:
- Adaptive: 10 days in bull, 5 days in bear (faster exits in crisis)
- Drift rebalance: if any position drifts >50% from target weight, rebalance

RATIONALE:
===========
The key insight is that v8.2's binary portfolio stop-loss is the primary source of
both its worst drawdowns AND its missed recoveries. By removing the stop and
replacing it with smooth leverage scaling:

1. We NEVER go to effectively 0% invested (v8.2 in protection S1 at 0.3x with 2
   positions is ~6% invested). We stay at minimum 25% invested.

2. We automatically increase exposure as drawdown recovers (no waiting for
   recovery stage timers).

3. We avoid the "double hit" of selling at the bottom (stop) then missing
   the rebound (protection mode).

The cost is that max drawdown will not be capped at -15% in any single
event. But the key realization is that v8.2's -15% stop DOES NOT actually
limit drawdowns -- the worst drawdown was -66.25% because the protection
mode kept losing money after the stop fired. Our approach will have smoother
drawdowns because we scale down gradually, never panic-sell everything, and
always maintain some market exposure.

BACKTEST PERIOD:
- 2000-2026 (26 years) for direct comparison with v8.2 bias-corrected results
- Uses identical survivorship-bias-corrected data infrastructure from exp40

TARGET METRICS (vs v8.2 bias-corrected):
- CAGR: >14% (vs 13.90%)
- Sharpe: >0.80 (vs 0.646)
- Max DD: <-45% (vs -66.25%)
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
from typing import Dict, List, Tuple, Optional, Set
import warnings
import requests
from io import StringIO
import time
from collections import defaultdict

warnings.filterwarnings('ignore')

# ============================================================================
# PARAMETERS - COMPASS v9 "ADAPTIVE SHIELD"
# ============================================================================

# Universe
TOP_N = 50                  # Expanded from 40 for better selection pool
MIN_AGE_DAYS = 63           # 3-month minimum trading history

# Signal - Multi-timeframe momentum blend
MOMENTUM_SHORT = 60         # Short-term momentum (2-3 months)
MOMENTUM_MED = 120          # Medium-term momentum (5-6 months)
MOMENTUM_LONG = 252         # Long-term momentum (1 year)
MOMENTUM_SKIP = 10          # Days to skip for reversal (widened from 5)
MOMENTUM_WEIGHTS = [0.25, 0.40, 0.35]  # Blend weights (short, med, long)
MIN_MOMENTUM_STOCKS = 15    # Minimum stocks with valid score

# Quality filter
MAX_STOCK_VOL = 0.60        # Max annualized vol for stock to be eligible
VOL_LOOKBACK_QUAL = 63      # 3-month realized vol for quality filter

# Regime - Multi-signal
REGIME_SMA_LONG = 200       # Long-term trend
REGIME_SMA_MED = 50         # Medium-term trend
REGIME_VOL_SHORT = 20       # Short-term volatility
REGIME_VOL_MED = 63         # Medium-term median volatility
REGIME_BREADTH_SMA = 50     # SMA period for breadth calculation

# Positions
NUM_POSITIONS_BULL = 12     # Full positions in strong bull
NUM_POSITIONS_MILD = 8      # Positions in mild conditions
NUM_POSITIONS_BEAR = 5      # Positions in bear market
NUM_POSITIONS_SEVERE = 3    # Positions in severe bear

# Sector constraints
SECTOR_MAX_POSITIONS = 3    # Max stocks per sector

# Risk Management - Smooth drawdown scaling (NO portfolio stop-loss)
DD_TIER_1 = -0.05           # Start reducing leverage at -5%
DD_TIER_2 = -0.15           # Further reduction at -15%
DD_TIER_3 = -0.25           # Minimum leverage floor at -25%
LEV_FULL = 1.0              # Full leverage
LEV_REDUCED = 0.50          # Reduced leverage
LEV_MINIMUM = 0.25          # Minimum leverage (NEVER go to 0)

# Position-level risk (wider stops to reduce whipsaw)
POSITION_STOP_LOSS = -0.12  # -12% per position (vs -8% in v8.2)
TRAILING_ACTIVATION = 0.08  # Activate trailing after +8% (vs +5%)
TRAILING_STOP_PCT = 0.05    # Trailing stop: -5% from max (vs -3%)

# Hold periods
HOLD_DAYS_BULL = 10         # 10 trading days in bull (vs 5 in v8.2)
HOLD_DAYS_BEAR = 5          # 5 trading days in bear (faster exits)

# Leverage & Vol targeting
TARGET_VOL = 0.15           # 15% annualized target vol
LEVERAGE_MAX = 1.0          # No actual leverage (1x only)
VOL_LOOKBACK = 20           # Days for realized vol

# Costs
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.035
CASH_YIELD_SOURCE = 'AAA'

# Data
START_DATE = '2000-01-01'
END_DATE = '2027-01-01'

# Sector mapping for S&P 500 stocks
SECTOR_MAP = {
    # Technology
    'AAPL': 'Tech', 'MSFT': 'Tech', 'NVDA': 'Tech', 'GOOGL': 'Tech',
    'META': 'Tech', 'AVGO': 'Tech', 'ADBE': 'Tech', 'CRM': 'Tech',
    'AMD': 'Tech', 'INTC': 'Tech', 'CSCO': 'Tech', 'IBM': 'Tech',
    'TXN': 'Tech', 'QCOM': 'Tech', 'ORCL': 'Tech', 'ACN': 'Tech',
    'NOW': 'Tech', 'INTU': 'Tech', 'AMAT': 'Tech', 'MU': 'Tech',
    'LRCX': 'Tech', 'SNPS': 'Tech', 'CDNS': 'Tech', 'KLAC': 'Tech',
    'MRVL': 'Tech',
    # Financials
    'BRK-B': 'Fin', 'JPM': 'Fin', 'V': 'Fin', 'MA': 'Fin',
    'BAC': 'Fin', 'WFC': 'Fin', 'GS': 'Fin', 'MS': 'Fin',
    'AXP': 'Fin', 'BLK': 'Fin', 'SCHW': 'Fin', 'C': 'Fin',
    'USB': 'Fin', 'PNC': 'Fin', 'TFC': 'Fin', 'CB': 'Fin',
    'MMC': 'Fin', 'AIG': 'Fin',
    # Healthcare
    'UNH': 'Health', 'JNJ': 'Health', 'LLY': 'Health', 'ABBV': 'Health',
    'MRK': 'Health', 'PFE': 'Health', 'TMO': 'Health', 'ABT': 'Health',
    'DHR': 'Health', 'AMGN': 'Health', 'BMY': 'Health', 'MDT': 'Health',
    'ISRG': 'Health', 'SYK': 'Health', 'GILD': 'Health', 'REGN': 'Health',
    'VRTX': 'Health', 'BIIB': 'Health',
    # Consumer Discretionary
    'AMZN': 'ConsDis', 'TSLA': 'ConsDis', 'HD': 'ConsDis', 'NKE': 'ConsDis',
    'MCD': 'ConsDis', 'DIS': 'ConsDis', 'SBUX': 'ConsDis', 'TGT': 'ConsDis',
    'LOW': 'ConsDis', 'EL': 'ConsDis',
    # Consumer Staples
    'WMT': 'ConsStap', 'PG': 'ConsStap', 'COST': 'ConsStap', 'KO': 'ConsStap',
    'PEP': 'ConsStap', 'CL': 'ConsStap', 'KMB': 'ConsStap', 'GIS': 'ConsStap',
    'MO': 'ConsStap', 'PM': 'ConsStap',
    # Energy
    'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'SLB': 'Energy',
    'EOG': 'Energy', 'OXY': 'Energy', 'MPC': 'Energy', 'PSX': 'Energy',
    'VLO': 'Energy',
    # Industrials
    'GE': 'Indust', 'CAT': 'Indust', 'BA': 'Indust', 'HON': 'Indust',
    'UNP': 'Indust', 'RTX': 'Indust', 'LMT': 'Indust', 'DE': 'Indust',
    'UPS': 'Indust', 'FDX': 'Indust', 'MMM': 'Indust', 'GD': 'Indust',
    'NOC': 'Indust', 'EMR': 'Indust',
    # Utilities
    'NEE': 'Util', 'DUK': 'Util', 'SO': 'Util', 'D': 'Util', 'AEP': 'Util',
    # Telecom/Communication
    'VZ': 'Telecom', 'T': 'Telecom', 'TMUS': 'Telecom', 'CMCSA': 'Telecom',
}


print("=" * 80)
print("EXPERIMENT 43: COMPASS v9 'ADAPTIVE SHIELD'")
print("=" * 80)
print()
print("STRATEGY ARCHITECTURE:")
print(f"  Signal: Multi-timeframe momentum ({MOMENTUM_SHORT}d/{MOMENTUM_MED}d/{MOMENTUM_LONG}d blend, skip {MOMENTUM_SKIP}d)")
print(f"  Quality: Max stock vol {MAX_STOCK_VOL:.0%}")
print(f"  Regime: Multi-signal (SPY SMA{REGIME_SMA_MED}/{REGIME_SMA_LONG} + Vol + Breadth)")
print(f"  Positions: {NUM_POSITIONS_BULL} bull / {NUM_POSITIONS_MILD} mild / {NUM_POSITIONS_BEAR} bear / {NUM_POSITIONS_SEVERE} severe")
print(f"  Sector cap: {SECTOR_MAX_POSITIONS} per sector")
print(f"  Hold: {HOLD_DAYS_BULL}d bull / {HOLD_DAYS_BEAR}d bear")
print(f"  Position stop: {POSITION_STOP_LOSS:.0%} | Trail: {TRAILING_STOP_PCT:.0%} after +{TRAILING_ACTIVATION:.0%}")
print(f"  DD scaling: smooth from {LEV_FULL:.0%} -> {LEV_REDUCED:.0%} -> {LEV_MINIMUM:.0%}")
print(f"  NO portfolio stop-loss (replaced by smooth DD scaling)")
print()
print("TARGETS (vs v8.2 bias-corrected):")
print(f"  CAGR:     >14.0% (v8.2: 13.90%)")
print(f"  Sharpe:   >0.80  (v8.2: 0.646)")
print(f"  Max DD:   <-45%  (v8.2: -66.25%)")
print()


# ============================================================================
# DATA FUNCTIONS
# ============================================================================

def download_broad_pool() -> Dict[str, pd.DataFrame]:
    """Download/load cached data for the broad pool.
    Uses survivorship-bias corrected data if available."""

    # First try the corrected pool from exp40
    corrected_cache = 'data_cache/survivorship_bias_pool.pkl'
    if os.path.exists(corrected_cache):
        print("[Cache] Loading survivorship-bias corrected pool...")
        with open(corrected_cache, 'rb') as f:
            data = pickle.load(f)
        print(f"  Loaded data for {len(data)} symbols")
        # Filter anomalous data
        data = filter_anomalous_stocks(data)
        return data

    # Fallback to v8.2 broad pool
    cache_file = f'data_cache/broad_pool_{START_DATE}_{END_DATE}.pkl'
    if os.path.exists(cache_file):
        print("[Cache] Loading broad pool data (WARNING: not survivorship-bias corrected)...")
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception:
            print("[Cache] Failed to load, re-downloading...")

    # Use v8.2's BROAD_POOL as stock list
    BROAD_POOL = [
        'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AVGO', 'ADBE', 'CRM', 'AMD',
        'INTC', 'CSCO', 'IBM', 'TXN', 'QCOM', 'ORCL', 'ACN', 'NOW', 'INTU',
        'AMAT', 'MU', 'LRCX', 'SNPS', 'CDNS', 'KLAC', 'MRVL',
        'BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'AXP', 'BLK',
        'SCHW', 'C', 'USB', 'PNC', 'TFC', 'CB', 'MMC', 'AIG',
        'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
        'AMGN', 'BMY', 'MDT', 'ISRG', 'SYK', 'GILD', 'REGN', 'VRTX', 'BIIB',
        'AMZN', 'TSLA', 'WMT', 'HD', 'PG', 'COST', 'KO', 'PEP', 'NKE',
        'MCD', 'DIS', 'SBUX', 'TGT', 'LOW', 'CL', 'KMB', 'GIS', 'EL',
        'MO', 'PM',
        'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'OXY', 'MPC', 'PSX', 'VLO',
        'GE', 'CAT', 'BA', 'HON', 'UNP', 'RTX', 'LMT', 'DE', 'UPS', 'FDX',
        'MMM', 'GD', 'NOC', 'EMR',
        'NEE', 'DUK', 'SO', 'D', 'AEP',
        'VZ', 'T', 'TMUS', 'CMCSA',
    ]

    print(f"[Download] Downloading {len(BROAD_POOL)} symbols...")
    data = {}
    failed = []

    for i, symbol in enumerate(BROAD_POOL):
        try:
            df = yf.download(symbol, start=START_DATE, end=END_DATE, progress=False)
            if not df.empty and len(df) > 100:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                data[symbol] = df
                if (i + 1) % 20 == 0:
                    print(f"  [{i+1}/{len(BROAD_POOL)}] Downloaded {len(data)} symbols...")
            else:
                failed.append(symbol)
        except Exception:
            failed.append(symbol)

    print(f"[Download] {len(data)} symbols valid, {len(failed)} failed")
    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)
    return data


def filter_anomalous_stocks(data: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """Filter out stocks with anomalous price movements that indicate data corruption."""
    print("\n[Filter] Checking for anomalous price data...")
    filtered_data = {}
    removed_stocks = []

    for symbol, df in data.items():
        try:
            if len(df) < 20:
                continue
            returns = df['Close'].pct_change(fill_method=None).dropna()
            if len(returns) == 0:
                continue
            max_single_day = returns.max()
            volatility = returns.std() * np.sqrt(252)
            is_valid = True
            reason = None
            if max_single_day > 1.0:  # 100%+ single day
                is_valid = False
                reason = f"Extreme gain: {max_single_day*100:.0f}%"
            elif volatility > 2.0:  # 200%+ annualized vol
                is_valid = False
                reason = f"Extreme vol: {volatility*100:.0f}%"
            if is_valid:
                filtered_data[symbol] = df
            else:
                removed_stocks.append((symbol, reason))
        except Exception:
            continue

    print(f"  Filtered: {len(filtered_data)} stocks kept, {len(removed_stocks)} removed")
    if removed_stocks:
        for symbol, reason in removed_stocks[:5]:
            print(f"    {symbol}: {reason}")
        if len(removed_stocks) > 5:
            print(f"    ... and {len(removed_stocks) - 5} more")
    return filtered_data


def download_spy() -> pd.DataFrame:
    """Download SPY data for regime filter"""
    cache_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        print("[Cache] Loading SPY data...")
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)

    print("[Download] Downloading SPY...")
    df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def download_cash_yield() -> Optional[pd.Series]:
    """Download Moody's Aaa Corporate Bond Yield from FRED."""
    cache_file = 'data_cache/moody_aaa_yield.csv'
    if os.path.exists(cache_file):
        print("[Cache] Loading Moody's Aaa yield data...")
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        daily = df['yield_pct'].resample('D').ffill()
        print(f"  {len(daily)} daily rates, avg {daily.mean():.2f}%")
        return daily
    try:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA&cosd=1999-01-01&coed=2026-12-31'
        df = pd.read_csv(url, parse_dates=['observation_date'], index_col='observation_date')
        df.columns = ['yield_pct']
        os.makedirs('data_cache', exist_ok=True)
        df.to_csv(cache_file)
        daily = df['yield_pct'].resample('D').ffill()
        return daily
    except Exception as e:
        print(f"  FRED download failed: {e}. Using fixed {CASH_YIELD_RATE:.1%}")
        return None


# ============================================================================
# UNIVERSE CONSTRUCTION
# ============================================================================

def compute_annual_top_n(price_data: Dict[str, pd.DataFrame]) -> Dict[int, List[str]]:
    """For each year, compute top-N by avg daily dollar volume (prior year data).
    Handles timezone-aware and timezone-naive datetimes."""
    all_dates = set()
    for df in price_data.values():
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            all_dates.update(df.index.tz_localize(None))
        else:
            all_dates.update(df.index)

    all_dates = sorted(list(all_dates))
    if not all_dates:
        return {}

    years = sorted(set(d.year for d in all_dates))
    annual_universe = {}

    for year in years:
        if year == years[0]:
            ranking_end = pd.Timestamp(f'{year}-02-01')
            ranking_start = pd.Timestamp(f'{year-1}-01-01')
        else:
            ranking_end = pd.Timestamp(f'{year}-01-01')
            ranking_start = pd.Timestamp(f'{year-1}-01-01')

        scores = {}
        for symbol, df in price_data.items():
            if hasattr(df.index, 'tz') and df.index.tz is not None:
                df_n = df.copy()
                df_n.index = df_n.index.tz_localize(None)
            else:
                df_n = df

            mask = (df_n.index >= ranking_start) & (df_n.index < ranking_end)
            window = df_n.loc[mask]
            if len(window) < 20:
                continue
            try:
                close_data = window['Close']
                vol_data = window['Volume']
                if isinstance(close_data, pd.DataFrame):
                    close_data = close_data.iloc[:, 0]
                if isinstance(vol_data, pd.DataFrame):
                    vol_data = vol_data.iloc[:, 0]
                dv = float((close_data * vol_data).mean())
                if not np.isnan(dv) and dv > 0:
                    scores[symbol] = dv
            except Exception:
                continue

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_n = [s for s, _ in ranked[:TOP_N]]
        annual_universe[year] = top_n

        if year > years[0] and year - 1 in annual_universe:
            prev = set(annual_universe[year - 1])
            curr = set(top_n)
            added = curr - prev
            removed = prev - curr
            if added or removed:
                print(f"  {year}: Top-{TOP_N} | +{len(added)} added, -{len(removed)} removed")
        else:
            print(f"  {year}: Initial top-{TOP_N} = {len(top_n)} stocks")

    return annual_universe


# ============================================================================
# SIGNAL FUNCTIONS
# ============================================================================

def compute_multi_timeframe_momentum(price_data: Dict[str, pd.DataFrame],
                                      tradeable: List[str],
                                      date: pd.Timestamp) -> Dict[str, float]:
    """
    Compute blended multi-timeframe momentum score.

    Blends 60d, 120d, and 252d momentum (all skipping last 10 days).
    Each component is z-scored cross-sectionally to normalize.
    Stocks with negative absolute momentum (below 0% return) get a penalty.
    """
    raw_scores = {tf: {} for tf in [MOMENTUM_SHORT, MOMENTUM_MED, MOMENTUM_LONG]}

    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue

        try:
            sym_idx = df.index.get_loc(date)
        except KeyError:
            continue

        needed = MOMENTUM_LONG + MOMENTUM_SKIP
        if sym_idx < needed:
            continue

        close_today = df['Close'].iloc[sym_idx]
        close_skip = df['Close'].iloc[sym_idx - MOMENTUM_SKIP]

        if close_skip <= 0 or close_today <= 0:
            continue

        for tf in [MOMENTUM_SHORT, MOMENTUM_MED, MOMENTUM_LONG]:
            if sym_idx >= tf + MOMENTUM_SKIP:
                close_lookback = df['Close'].iloc[sym_idx - tf - MOMENTUM_SKIP]
                if close_lookback > 0:
                    # Momentum from (tf+skip) days ago to (skip) days ago
                    momentum = (close_skip / close_lookback) - 1.0
                    raw_scores[tf][symbol] = momentum

    # Z-score each timeframe cross-sectionally
    z_scores = {}
    for tf in [MOMENTUM_SHORT, MOMENTUM_MED, MOMENTUM_LONG]:
        values = list(raw_scores[tf].values())
        if len(values) < 5:
            continue
        mean_v = np.mean(values)
        std_v = np.std(values)
        if std_v < 0.001:
            continue
        for symbol, val in raw_scores[tf].items():
            if symbol not in z_scores:
                z_scores[symbol] = {}
            z_scores[symbol][tf] = (val - mean_v) / std_v

    # Blend z-scores with weights
    blended = {}
    weights = dict(zip([MOMENTUM_SHORT, MOMENTUM_MED, MOMENTUM_LONG], MOMENTUM_WEIGHTS))

    for symbol, tf_scores in z_scores.items():
        if len(tf_scores) < 2:  # Need at least 2 timeframes
            continue
        score = 0.0
        total_weight = 0.0
        for tf, w in weights.items():
            if tf in tf_scores:
                score += w * tf_scores[tf]
                total_weight += w
        if total_weight > 0:
            blended[symbol] = score / total_weight

    # Absolute momentum penalty: stocks with negative total return get penalized
    for symbol in list(blended.keys()):
        # Check if 252d absolute return is negative
        if MOMENTUM_LONG in raw_scores and symbol in raw_scores[MOMENTUM_LONG]:
            abs_return = raw_scores[MOMENTUM_LONG][symbol]
            if abs_return < 0:
                blended[symbol] *= 0.5  # Halve the score for negative absolute momentum

    return blended


def compute_stock_quality(price_data: Dict[str, pd.DataFrame],
                          symbol: str,
                          date: pd.Timestamp) -> bool:
    """Check if stock passes quality filter (volatility screen)."""
    if symbol not in price_data:
        return False
    df = price_data[symbol]
    if date not in df.index:
        return False

    try:
        sym_idx = df.index.get_loc(date)
    except KeyError:
        return False

    if sym_idx < VOL_LOOKBACK_QUAL + 1:
        return True  # Not enough data, pass by default

    returns = df['Close'].iloc[sym_idx - VOL_LOOKBACK_QUAL:sym_idx + 1].pct_change().dropna()
    if len(returns) < VOL_LOOKBACK_QUAL - 5:
        return True

    ann_vol = returns.std() * np.sqrt(252)
    return ann_vol <= MAX_STOCK_VOL


# ============================================================================
# REGIME DETECTION (Multi-Signal)
# ============================================================================

def compute_regime_score(spy_data: pd.DataFrame, date: pd.Timestamp,
                          price_data: Dict[str, pd.DataFrame],
                          tradeable: List[str]) -> float:
    """
    Compute composite regime score from 0.0 (extreme bear) to 1.0 (strong bull).

    Components:
    1. Trend (40%): SPY vs SMA200 and SMA50
    2. Volatility (30%): Current vol vs historical median
    3. Breadth (30%): % of stocks above their SMA50

    Returns float between 0 and 1.
    """
    if date not in spy_data.index:
        return 0.5  # Neutral default

    spy_idx = spy_data.index.get_loc(date)
    if spy_idx < REGIME_SMA_LONG:
        return 0.5

    spy_close = spy_data['Close'].iloc[:spy_idx + 1]

    # --- Component 1: Trend (0 or 1 for each SMA) ---
    sma200 = spy_close.iloc[-REGIME_SMA_LONG:].mean()
    sma50 = spy_close.iloc[-REGIME_SMA_MED:].mean()
    current_price = spy_close.iloc[-1]

    trend_long = 1.0 if current_price > sma200 else 0.0
    trend_med = 1.0 if current_price > sma50 else 0.0
    # How far above/below SMA200 (clipped)
    sma200_dist = min(max((current_price / sma200 - 1.0) * 10, -1.0), 1.0)
    trend_score = 0.4 * trend_long + 0.3 * trend_med + 0.3 * (sma200_dist + 1) / 2

    # --- Component 2: Volatility regime ---
    if spy_idx >= REGIME_VOL_MED + 1:
        recent_returns = spy_close.pct_change().dropna()
        vol_short = recent_returns.iloc[-REGIME_VOL_SHORT:].std() * np.sqrt(252) if len(recent_returns) >= REGIME_VOL_SHORT else 0.15
        vol_med_arr = recent_returns.iloc[-REGIME_VOL_MED:]
        vol_med = vol_med_arr.std() * np.sqrt(252) if len(vol_med_arr) >= REGIME_VOL_MED else 0.15

        # High vol relative to recent = bearish, low vol = bullish
        if vol_med > 0.01:
            vol_ratio = vol_short / vol_med
        else:
            vol_ratio = 1.0

        # vol_ratio > 1 means volatility expanding (bearish)
        # vol_ratio < 1 means volatility contracting (bullish)
        vol_score = max(0, min(1, 1.5 - vol_ratio))  # 1 when low, 0 when high
    else:
        vol_score = 0.5

    # --- Component 3: Market breadth ---
    above_sma = 0
    total_checked = 0
    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        try:
            idx = df.index.get_loc(date)
        except KeyError:
            continue
        if idx < REGIME_BREADTH_SMA:
            continue
        stock_sma50 = df['Close'].iloc[idx - REGIME_BREADTH_SMA:idx + 1].mean()
        stock_price = df['Close'].iloc[idx]
        total_checked += 1
        if stock_price > stock_sma50:
            above_sma += 1

    breadth_score = above_sma / total_checked if total_checked > 5 else 0.5

    # --- Composite ---
    composite = 0.40 * trend_score + 0.30 * vol_score + 0.30 * breadth_score
    return max(0.0, min(1.0, composite))


def regime_to_params(regime_score: float) -> dict:
    """
    Convert regime score to position count and hold days.

    Regime Score -> State:
    0.70 - 1.00: Strong Bull  -> 12 positions, 10d hold
    0.45 - 0.70: Mild         -> 8 positions, 8d hold
    0.25 - 0.45: Bear         -> 5 positions, 5d hold
    0.00 - 0.25: Severe Bear  -> 3 positions, 5d hold
    """
    if regime_score >= 0.70:
        return {'max_positions': NUM_POSITIONS_BULL, 'hold_days': HOLD_DAYS_BULL, 'label': 'BULL'}
    elif regime_score >= 0.45:
        return {'max_positions': NUM_POSITIONS_MILD, 'hold_days': 8, 'label': 'MILD'}
    elif regime_score >= 0.25:
        return {'max_positions': NUM_POSITIONS_BEAR, 'hold_days': HOLD_DAYS_BEAR, 'label': 'BEAR'}
    else:
        return {'max_positions': NUM_POSITIONS_SEVERE, 'hold_days': HOLD_DAYS_BEAR, 'label': 'SEVERE'}


# ============================================================================
# DRAWDOWN-BASED LEVERAGE SCALING
# ============================================================================

def compute_dd_leverage(drawdown: float) -> float:
    """
    Smooth drawdown-based leverage scaling.
    NO cliff-style portfolio stop-loss. Instead, gradually reduce exposure.

    DD 0% to -5%:   Full 1.0x
    DD -5% to -15%: Linear from 1.0x to 0.50x
    DD -15% to -25%: Linear from 0.50x to 0.25x
    DD beyond -25%: Floor at 0.25x (NEVER go to zero)
    """
    dd = drawdown  # Already negative

    if dd >= DD_TIER_1:
        return LEV_FULL
    elif dd >= DD_TIER_2:
        # Linear interpolation from 1.0 to 0.50 as DD goes from -5% to -15%
        frac = (dd - DD_TIER_1) / (DD_TIER_2 - DD_TIER_1)
        return LEV_FULL + frac * (LEV_REDUCED - LEV_FULL)
    elif dd >= DD_TIER_3:
        # Linear interpolation from 0.50 to 0.25 as DD goes from -15% to -25%
        frac = (dd - DD_TIER_2) / (DD_TIER_3 - DD_TIER_2)
        return LEV_REDUCED + frac * (LEV_MINIMUM - LEV_REDUCED)
    else:
        return LEV_MINIMUM


# ============================================================================
# SECTOR-AWARE STOCK SELECTION
# ============================================================================

def select_stocks_with_sector_cap(scores: Dict[str, float],
                                   max_positions: int,
                                   existing_positions: Dict[str, dict]) -> List[str]:
    """
    Select top stocks by momentum score, respecting sector caps.
    Existing positions count toward sector limits.
    """
    # Count sectors from existing positions
    sector_counts = defaultdict(int)
    for symbol in existing_positions:
        sector = SECTOR_MAP.get(symbol, 'Other')
        sector_counts[sector] += 1

    # Rank available stocks
    available = {s: sc for s, sc in scores.items() if s not in existing_positions}
    ranked = sorted(available.items(), key=lambda x: x[1], reverse=True)

    selected = []
    needed = max_positions - len(existing_positions)

    for symbol, score in ranked:
        if len(selected) >= needed:
            break
        sector = SECTOR_MAP.get(symbol, 'Other')
        if sector_counts[sector] >= SECTOR_MAX_POSITIONS:
            continue  # Skip: sector full
        selected.append(symbol)
        sector_counts[sector] += 1

    return selected


# ============================================================================
# BACKTEST ENGINE
# ============================================================================

def get_tradeable_symbols(price_data: Dict[str, pd.DataFrame],
                         date: pd.Timestamp,
                         first_date: pd.Timestamp,
                         annual_universe: Dict[int, List[str]]) -> List[str]:
    """Return tradeable symbols from top-N for that year."""
    eligible = set(annual_universe.get(date.year, []))
    tradeable = []
    for symbol in eligible:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        symbol_first_date = df.index[0]
        days_since_start = (date - symbol_first_date).days
        if date <= first_date + timedelta(days=30):
            tradeable.append(symbol)
        elif days_since_start >= MIN_AGE_DAYS:
            tradeable.append(symbol)
    return tradeable


def run_backtest(price_data: Dict[str, pd.DataFrame],
                 annual_universe: Dict[int, List[str]],
                 spy_data: pd.DataFrame,
                 cash_yield_daily: Optional[pd.Series] = None) -> Dict:
    """Run COMPASS v9 Adaptive Shield backtest."""

    print("\n" + "=" * 80)
    print("RUNNING COMPASS v9 ADAPTIVE SHIELD BACKTEST")
    print("=" * 80)

    # Get all trading dates
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")

    # Portfolio state
    cash = float(INITIAL_CAPITAL)
    positions = {}  # symbol -> {entry_price, shares, entry_date, entry_idx, high_price}
    portfolio_values = []
    trades = []

    peak_value = float(INITIAL_CAPITAL)
    current_year = None

    # Tracking
    regime_history = []
    leverage_history = []

    for i, date in enumerate(all_dates):
        if date.year != current_year:
            current_year = date.year

        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        # --- Calculate portfolio value ---
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        # --- Update peak ---
        if portfolio_value > peak_value:
            peak_value = portfolio_value

        # --- Drawdown ---
        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # --- Compute regime score ---
        regime_score = compute_regime_score(spy_data, date, price_data, tradeable_symbols)
        regime_params = regime_to_params(regime_score)
        max_positions = regime_params['max_positions']
        hold_days = regime_params['hold_days']
        regime_label = regime_params['label']

        # --- Compute drawdown-based leverage ---
        dd_leverage = compute_dd_leverage(drawdown)

        # --- Apply vol targeting on top of DD leverage ---
        # Use SPY vol as proxy
        if date in spy_data.index:
            spy_idx = spy_data.index.get_loc(date)
            if spy_idx >= VOL_LOOKBACK + 1:
                spy_returns = spy_data['Close'].iloc[spy_idx - VOL_LOOKBACK:spy_idx + 1].pct_change().dropna()
                realized_vol = spy_returns.std() * np.sqrt(252) if len(spy_returns) >= VOL_LOOKBACK - 2 else 0.15
                vol_leverage = min(TARGET_VOL / realized_vol, 1.0) if realized_vol > 0.01 else 1.0
            else:
                vol_leverage = 1.0
        else:
            vol_leverage = 1.0

        # Final leverage = min of DD-based and vol-based, capped at 1.0
        current_leverage = min(dd_leverage, vol_leverage, LEVERAGE_MAX)
        current_leverage = max(current_leverage, LEV_MINIMUM)  # Floor

        # --- Cash yield ---
        if cash > 0:
            if cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

        # --- Close positions (exits) ---
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue

            current_price = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            # 1. Hold time expired (adaptive based on regime)
            days_held = i - pos['entry_idx']
            if days_held >= hold_days:
                exit_reason = 'hold_expired'

            # 2. Position stop loss (-12%)
            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            if pos_return <= POSITION_STOP_LOSS:
                exit_reason = 'position_stop'

            # 3. Trailing stop (activated after +8%, stop at -5% from peak)
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                trailing_level = pos['high_price'] * (1 - TRAILING_STOP_PCT)
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            # 4. Universe rotation
            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'

            # 5. Excess positions (regime shifted to fewer positions)
            if exit_reason is None and len(positions) > max_positions:
                # Close worst-performing position
                pos_returns = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        cp = price_data[s].loc[date, 'Close']
                        pos_returns[s] = (cp - p['entry_price']) / p['entry_price']
                if pos_returns:
                    worst = min(pos_returns, key=pos_returns.get)
                    if symbol == worst:
                        exit_reason = 'regime_reduce'

            if exit_reason:
                shares = pos['shares']
                proceeds = shares * current_price
                commission = shares * COMMISSION_PER_SHARE
                cash += proceeds - commission
                pnl = (current_price - pos['entry_price']) * shares - commission
                trades.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'exit_reason': exit_reason,
                    'pnl': pnl,
                    'return': pnl / (pos['entry_price'] * shares) if pos['entry_price'] * shares > 0 else 0,
                    'days_held': days_held,
                })
                del positions[symbol]

        # --- Open new positions ---
        needed = max_positions - len(positions)

        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            # Apply quality filter
            quality_stocks = [s for s in tradeable_symbols
                              if compute_stock_quality(price_data, s, date)]

            # Compute multi-timeframe momentum scores
            scores = compute_multi_timeframe_momentum(price_data, quality_stocks, date)

            if len(scores) >= needed:
                # Select with sector cap
                selected = select_stocks_with_sector_cap(scores, max_positions, positions)

                # Equal weight with leverage
                effective_capital = cash * current_leverage * 0.95  # 5% buffer
                per_position = effective_capital / max(len(selected), 1)

                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue

                    entry_price = price_data[symbol].loc[date, 'Close']
                    if entry_price <= 0:
                        continue

                    # Cap at 40% of cash per position
                    position_value = min(per_position, cash * 0.40)
                    shares = position_value / entry_price
                    cost = shares * entry_price
                    commission = shares * COMMISSION_PER_SHARE

                    if cost + commission <= cash * 0.90:
                        positions[symbol] = {
                            'entry_price': entry_price,
                            'shares': shares,
                            'entry_date': date,
                            'entry_idx': i,
                            'high_price': entry_price,
                        }
                        cash -= cost + commission

        # --- Record daily snapshot ---
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'drawdown': drawdown,
            'leverage': current_leverage,
            'regime_score': regime_score,
            'regime_label': regime_label,
            'dd_leverage': dd_leverage,
            'universe_size': len(tradeable_symbols)
        })

        # Annual progress log
        if i % 252 == 0 and i > 0:
            year_num = i // 252
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | DD: {drawdown:.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_label} (R={regime_score:.2f}) | "
                  f"Pos: {len(positions)}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
    }


# ============================================================================
# METRICS
# ============================================================================

def calculate_metrics(results: Dict) -> Dict:
    """Calculate comprehensive performance metrics."""
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']

    initial = INITIAL_CAPITAL
    final_value = df['value'].iloc[-1]
    years = len(df) / 252
    cagr = (final_value / initial) ** (1 / years) - 1

    returns = df['value'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(252)
    max_dd = df['drawdown'].min()

    sharpe = cagr / volatility if volatility > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else volatility
    sortino = cagr / downside_vol if downside_vol > 0 else 0

    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    avg_trade = trades_df['pnl'].mean() if len(trades_df) > 0 else 0
    avg_winner = trades_df.loc[trades_df['pnl'] > 0, 'pnl'].mean() if len(trades_df) > 0 and (trades_df['pnl'] > 0).any() else 0
    avg_loser = trades_df.loc[trades_df['pnl'] < 0, 'pnl'].mean() if len(trades_df) > 0 and (trades_df['pnl'] < 0).any() else 0

    exit_reasons = trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in trades_df.columns and len(trades_df) > 0 else {}

    # Annual returns
    df_annual = df['value'].resample('YE').last()
    annual_returns = df_annual.pct_change().dropna()

    # Regime breakdown
    regime_counts = df['regime_label'].value_counts().to_dict() if 'regime_label' in df.columns else {}

    # Average leverage
    avg_leverage = df['leverage'].mean() if 'leverage' in df.columns else 1.0

    # Max consecutive losing days
    losing_days = (returns < 0).astype(int)
    max_losing_streak = 0
    current_streak = 0
    for val in losing_days:
        if val:
            current_streak += 1
            max_losing_streak = max(max_losing_streak, current_streak)
        else:
            current_streak = 0

    return {
        'initial': initial,
        'final_value': final_value,
        'total_return': (final_value - initial) / initial,
        'years': years,
        'cagr': cagr,
        'volatility': volatility,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'win_rate': win_rate,
        'avg_trade': avg_trade,
        'avg_winner': avg_winner,
        'avg_loser': avg_loser,
        'trades': len(trades_df),
        'exit_reasons': exit_reasons,
        'annual_returns': annual_returns,
        'best_year': annual_returns.max() if len(annual_returns) > 0 else 0,
        'worst_year': annual_returns.min() if len(annual_returns) > 0 else 0,
        'regime_breakdown': regime_counts,
        'avg_leverage': avg_leverage,
        'max_losing_streak': max_losing_streak,
    }


# ============================================================================
# COMPARISON
# ============================================================================

def print_comparison(metrics: Dict):
    """Print comparison vs COMPASS v8.2 bias-corrected benchmarks."""

    # v8.2 bias-corrected benchmarks from exp40
    v82_cagr = 0.1390
    v82_sharpe = 0.646
    v82_max_dd = -0.6625
    v82_sortino = 0.0  # Not available from logs
    v82_trades = 5309

    print("\n" + "=" * 80)
    print("COMPARISON: v9 ADAPTIVE SHIELD vs v8.2 COMPASS (bias-corrected)")
    print("=" * 80)

    print(f"\n{'Metric':<30} {'v8.2 Corrected':>15} {'v9 Shield':>15} {'Delta':>15} {'Target':>10}")
    print("-" * 85)
    print(f"{'CAGR':<30} {v82_cagr:>14.2%} {metrics['cagr']:>14.2%} {metrics['cagr']-v82_cagr:>+14.2%} {'>14.0%':>10}")
    print(f"{'Sharpe Ratio':<30} {v82_sharpe:>15.3f} {metrics['sharpe']:>15.3f} {metrics['sharpe']-v82_sharpe:>+15.3f} {'>0.800':>10}")
    print(f"{'Sortino Ratio':<30} {'N/A':>15} {metrics['sortino']:>15.3f} {'':>15} {'':>10}")
    print(f"{'Calmar Ratio':<30} {'N/A':>15} {metrics['calmar']:>15.3f} {'':>15} {'':>10}")
    print(f"{'Max Drawdown':<30} {v82_max_dd:>14.2%} {metrics['max_drawdown']:>14.2%} {metrics['max_drawdown']-v82_max_dd:>+14.2%} {'<-45%':>10}")
    print(f"{'Volatility':<30} {'N/A':>15} {metrics['volatility']:>14.2%} {'':>15} {'':>10}")
    print(f"{'Win Rate':<30} {'N/A':>15} {metrics['win_rate']:>14.2%} {'':>15} {'':>10}")
    print(f"{'Trades':<30} {v82_trades:>15,} {metrics['trades']:>15,} {metrics['trades']-v82_trades:>+15,} {'':>10}")
    print(f"{'Final Value':<30} {'$358,697':>15} ${metrics['final_value']:>14,.0f} {'':>15} {'':>10}")
    print(f"{'Avg Leverage':<30} {'~0.85':>15} {metrics['avg_leverage']:>15.3f} {'':>15} {'':>10}")
    print("-" * 85)

    # Verdict
    print(f"\n{'VERDICT':}")
    beats_cagr = metrics['cagr'] > v82_cagr
    beats_sharpe = metrics['sharpe'] > v82_sharpe
    beats_dd = metrics['max_drawdown'] > v82_max_dd  # Less negative = better

    results = []
    if beats_cagr:
        results.append(f"  [PASS] CAGR: {metrics['cagr']:.2%} > {v82_cagr:.2%}")
    else:
        results.append(f"  [FAIL] CAGR: {metrics['cagr']:.2%} <= {v82_cagr:.2%}")

    if beats_sharpe:
        results.append(f"  [PASS] Sharpe: {metrics['sharpe']:.3f} > {v82_sharpe:.3f}")
    else:
        results.append(f"  [FAIL] Sharpe: {metrics['sharpe']:.3f} <= {v82_sharpe:.3f}")

    if beats_dd:
        results.append(f"  [PASS] Max DD: {metrics['max_drawdown']:.2%} better than {v82_max_dd:.2%}")
    else:
        results.append(f"  [FAIL] Max DD: {metrics['max_drawdown']:.2%} worse than {v82_max_dd:.2%}")

    for r in results:
        print(r)

    overall = sum([beats_cagr, beats_sharpe, beats_dd])
    print(f"\n  Overall: {overall}/3 metrics beaten")
    if overall == 3:
        print("  >>> COMPASS v8.2 IS DEFEATED ON ALL FRONTS <<<")
    elif overall >= 2:
        print("  >>> Partial victory - most metrics improved <<<")
    else:
        print("  >>> More work needed <<<")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("STEP 1: LOAD DATA")
    print("=" * 80)

    price_data = download_broad_pool()
    print(f"\nSymbols available: {len(price_data)}")

    spy_data = download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    cash_yield_daily = download_cash_yield()

    print("\n" + "=" * 80)
    print("STEP 2: COMPUTE ANNUAL UNIVERSE")
    print("=" * 80)

    print(f"\n--- Computing Annual Top-{TOP_N} ---")
    annual_universe = compute_annual_top_n(price_data)

    print("\n" + "=" * 80)
    print("STEP 3: RUN ADAPTIVE SHIELD BACKTEST")
    print("=" * 80)

    results = run_backtest(price_data, annual_universe, spy_data, cash_yield_daily)

    print("\n" + "=" * 80)
    print("STEP 4: CALCULATE METRICS")
    print("=" * 80)

    metrics = calculate_metrics(results)

    # --- Print detailed results ---
    print("\n" + "=" * 80)
    print("RESULTS - COMPASS v9 ADAPTIVE SHIELD")
    print("=" * 80)

    print(f"\n--- Performance ---")
    print(f"Initial capital:        ${metrics['initial']:>15,.0f}")
    print(f"Final value:            ${metrics['final_value']:>15,.2f}")
    print(f"Total return:           {metrics['total_return']:>15.2%}")
    print(f"CAGR:                   {metrics['cagr']:>15.2%}")
    print(f"Volatility (annual):    {metrics['volatility']:>15.2%}")

    print(f"\n--- Risk-Adjusted ---")
    print(f"Sharpe ratio:           {metrics['sharpe']:>15.3f}")
    print(f"Sortino ratio:          {metrics['sortino']:>15.3f}")
    print(f"Calmar ratio:           {metrics['calmar']:>15.3f}")
    print(f"Max drawdown:           {metrics['max_drawdown']:>15.2%}")

    print(f"\n--- Trading ---")
    print(f"Trades executed:        {metrics['trades']:>15,}")
    print(f"Win rate:               {metrics['win_rate']:>15.2%}")
    print(f"Avg P&L per trade:      ${metrics['avg_trade']:>15,.2f}")
    print(f"Avg winner:             ${metrics['avg_winner']:>15,.2f}")
    print(f"Avg loser:              ${metrics['avg_loser']:>15,.2f}")
    print(f"Avg leverage:           {metrics['avg_leverage']:>15.3f}")
    print(f"Max losing streak:      {metrics['max_losing_streak']:>15} days")

    print(f"\n--- Exit Reasons ---")
    for reason, count in sorted(metrics['exit_reasons'].items(), key=lambda x: -x[1]):
        pct = count / metrics['trades'] * 100 if metrics['trades'] > 0 else 0
        print(f"  {reason:25s}: {count:>6,} ({pct:.1f}%)")

    print(f"\n--- Regime Breakdown ---")
    total_days = sum(metrics['regime_breakdown'].values()) if metrics['regime_breakdown'] else 1
    for regime, days in sorted(metrics['regime_breakdown'].items(), key=lambda x: -x[1]):
        print(f"  {regime:15s}: {days:>6,} days ({days/total_days*100:.1f}%)")

    print(f"\n--- Annual Returns ---")
    if len(metrics['annual_returns']) > 0:
        print(f"Best year:              {metrics['best_year']:>15.2%}")
        print(f"Worst year:             {metrics['worst_year']:>15.2%}")
        print(f"Positive years:         {(metrics['annual_returns'] > 0).sum()}/{len(metrics['annual_returns'])}")
        print(f"\nYear-by-year:")
        for date, ret in metrics['annual_returns'].items():
            year = date.year
            marker = " " if ret >= 0 else " *"
            print(f"  {year}: {ret:>+8.2%}{marker}")

    # --- Comparison ---
    print_comparison(metrics)

    # --- Save results ---
    os.makedirs('backtests', exist_ok=True)
    results['portfolio_values'].to_csv('backtests/exp43_adaptive_shield_daily.csv', index=False)
    if len(results['trades']) > 0:
        results['trades'].to_csv('backtests/exp43_adaptive_shield_trades.csv', index=False)

    output_file = 'backtests/exp43_results.pkl'
    with open(output_file, 'wb') as f:
        pickle.dump({
            'params': {
                'momentum_short': MOMENTUM_SHORT,
                'momentum_med': MOMENTUM_MED,
                'momentum_long': MOMENTUM_LONG,
                'momentum_skip': MOMENTUM_SKIP,
                'momentum_weights': MOMENTUM_WEIGHTS,
                'max_stock_vol': MAX_STOCK_VOL,
                'num_positions_bull': NUM_POSITIONS_BULL,
                'num_positions_mild': NUM_POSITIONS_MILD,
                'num_positions_bear': NUM_POSITIONS_BEAR,
                'num_positions_severe': NUM_POSITIONS_SEVERE,
                'sector_max': SECTOR_MAX_POSITIONS,
                'hold_days_bull': HOLD_DAYS_BULL,
                'hold_days_bear': HOLD_DAYS_BEAR,
                'position_stop': POSITION_STOP_LOSS,
                'trailing_activation': TRAILING_ACTIVATION,
                'trailing_stop': TRAILING_STOP_PCT,
                'dd_tier_1': DD_TIER_1,
                'dd_tier_2': DD_TIER_2,
                'dd_tier_3': DD_TIER_3,
                'target_vol': TARGET_VOL,
                'top_n': TOP_N,
            },
            'metrics': metrics,
            'portfolio_values': results['portfolio_values'],
            'trades': results['trades'],
        }, f)

    print(f"\nResults saved:")
    print(f"  Daily CSV: backtests/exp43_adaptive_shield_daily.csv")
    print(f"  Trades CSV: backtests/exp43_adaptive_shield_trades.csv")
    print(f"  Full results: {output_file}")

    print("\n" + "=" * 80)
    print("EXPERIMENT 43 COMPLETE")
    print("=" * 80)
