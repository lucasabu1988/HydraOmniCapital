"""
Experiment 42: COMPASS v8.3 "666 Framework" Backtest
=====================================================

Implementation of the mathematics PhD forum recommendations for COMPASS momentum strategy.

TIER 1 CHANGES (from v8.2 to v8.3):
1. Lookback period: 180 days → 666 trading days
2. Stock selection: 40 stocks → 66 stocks
3. Sector constraint: Add maximum 11 stocks per GICS sector
4. Rebalancing: 5-day hold → 6.66% drift threshold

BASELINE TO BEAT:
- Exp41 (v8.2, 30-year): 11.31% CAGR, Sharpe 0.528, -63.41% max DD

BACKTEST PERIOD:
- 1996-2026 (30 years) for fair comparison with Exp41
- Point-in-time S&P 500 constituents (survivorship-bias corrected)

HYPOTHESIS:
- Longer lookback (666d) captures multi-year trends, reduces noise
- More positions (66) increases diversification, reduces idiosyncratic risk
- Sector constraint prevents concentration in hot sectors (tech bubble, etc)
- Drift-based rebalancing reduces unnecessary turnover vs fixed hold period

OUTPUT:
- backtests/exp42_compass_666_daily.csv: Daily equity curve
- backtests/exp42_compass_666_trades.csv: All trades
- backtests/exp42_comparison_v82_v83.txt: Performance comparison
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
# PARAMETERS - COMPASS v8.3 "666 FRAMEWORK"
# ============================================================================

# Universe (CHANGED from v8.2)
TOP_N = 66  # Increased from 40
MIN_AGE_DAYS = 63

# Signal (CHANGED from v8.2)
MOMENTUM_LOOKBACK = 666  # Trading days! ~2.6 years
MOMENTUM_SKIP = 5  # Keep same (exclude last 5 days for reversal)
MIN_MOMENTUM_STOCKS = 33  # At least half of target universe

# Regime
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3

# Positions (CHANGED from v8.2)
NUM_POSITIONS = 66  # Equal-weight all 66 stocks
NUM_POSITIONS_RISK_OFF = 11  # Top 11 in risk-off (1/6 of 66, keeping 666 theme)
HOLD_DAYS = None  # REMOVED: Use drift-based rebalancing instead

# NEW: Sector constraint
SECTOR_MAX = 11  # Maximum stocks per GICS sector (66/6 = 11)

# NEW: Drift-based rebalancing
REBALANCE_DRIFT_PCT = 0.0666  # 6.66% relative drift from equal weight
TARGET_WEIGHT = 1.0 / NUM_POSITIONS  # 1.515% per stock

# Position-level risk
POSITION_STOP_LOSS = -0.08
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03

# Portfolio-level risk
PORTFOLIO_STOP_LOSS = -0.15

# Recovery stages
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126

# Leverage & Vol targeting
TARGET_VOL = 0.15
LEVERAGE_MIN = 0.3
LEVERAGE_MAX = 1.0
VOL_LOOKBACK = 20

# Costs
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.035
CASH_YIELD_SOURCE = 'AAA'

# Data
START_DATE = '1996-01-02'
END_DATE = '2027-01-01'

print("=" * 80)
print("EXPERIMENT 42: COMPASS v8.3 '666 FRAMEWORK' BACKTEST")
print("=" * 80)
print(f"\nImplementing mathematics PhD forum Tier 1 recommendations:")
print(f"  1. Lookback period: 90d -> {MOMENTUM_LOOKBACK} trading days (~{MOMENTUM_LOOKBACK/252:.1f} years)")
print(f"  2. Stock selection: 40 -> {TOP_N} stocks")
print(f"  3. Sector constraint: Maximum {SECTOR_MAX} stocks per GICS sector")
print(f"  4. Rebalancing: 5-day hold -> {REBALANCE_DRIFT_PCT:.2%} drift threshold")
print(f"\nBaseline (Exp41 v8.2): 11.31% CAGR, Sharpe 0.528, -63.41% max DD")
print(f"Period: {START_DATE} to 2026 (30 years)")
print()

# ============================================================================
# DATA FUNCTIONS (Import from Exp41)
# ============================================================================

import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from exp41_extended_1996 import (
    download_sp500_constituents_history,
    build_point_in_time_universe,
    download_expanded_pool,
    filter_anomalous_stocks,
    compute_annual_top40_corrected,
)

from omnicapital_v8_compass import (
    download_spy,
    download_cash_yield,
    compute_regime,
    compute_dynamic_leverage,
)

# ============================================================================
# NEW: GICS SECTOR DATA
# ============================================================================

def download_gics_sectors() -> Dict[str, str]:
    """
    Download GICS sector classification for S&P 500 stocks.

    Returns dict: {ticker: sector_name}

    Data source priority:
    1. Wikipedia S&P 500 list (current constituents)
    2. yfinance ticker.info['sector']
    3. Manual mapping for delisted stocks
    """
    cache_file = 'data_cache/gics_sectors.pkl'

    if os.path.exists(cache_file):
        print("[Cache] Loading GICS sector data...")
        with open(cache_file, 'rb') as f:
            sectors = pickle.load(f)
        print(f"  Loaded sectors for {len(sectors)} tickers")
        return sectors

    print("[Download] Downloading GICS sector classifications...")
    sectors = {}

    # Method 1: Wikipedia S&P 500 list
    try:
        print("  Trying Wikipedia S&P 500 list...")
        url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
        tables = pd.read_html(url)
        sp500_table = tables[0]

        for _, row in sp500_table.iterrows():
            ticker = row['Symbol'].replace('.', '-')  # Fix BRK.B -> BRK-B
            sector = row['GICS Sector']
            sectors[ticker] = sector

        print(f"  [OK] Got sectors for {len(sectors)} current S&P 500 stocks")
    except Exception as e:
        print(f"  [FAIL] Wikipedia failed: {e}")

    # Method 2: Fill gaps with yfinance (slower, for delisted stocks)
    print("  Filling gaps with yfinance...")
    missing_count = 0

    # Get all tickers from constituents history
    constituents = download_sp500_constituents_history()
    if constituents is not None:
        all_tickers = constituents['ticker'].unique()

        for ticker in all_tickers:
            if ticker in sectors:
                continue

            try:
                stock = yf.Ticker(ticker)
                info = stock.info
                sector = info.get('sector', 'Unknown')

                if sector and sector != 'Unknown':
                    sectors[ticker] = sector
                    missing_count += 1

                    if missing_count % 20 == 0:
                        print(f"    Filled {missing_count} sectors via yfinance...")

                time.sleep(0.1)  # Rate limiting
            except:
                continue

    print(f"  [OK] Filled {missing_count} additional sectors via yfinance")

    # Method 3: Manual mappings for known problematic cases
    manual_mappings = {
        'LEH': 'Financials',  # Lehman Brothers
        'BSC': 'Financials',  # Bear Stearns
        'WM': 'Financials',   # Washington Mutual
        'ENE': 'Energy',      # Enron
        'WCOM': 'Communication Services',  # WorldCom
        'CFC': 'Financials',  # Countrywide
    }

    for ticker, sector in manual_mappings.items():
        if ticker not in sectors:
            sectors[ticker] = sector

    print(f"\n[Download] Total sectors mapped: {len(sectors)} tickers")

    # Show sector distribution
    sector_counts = pd.Series(sectors).value_counts()
    print("\n  Sector distribution:")
    for sector, count in sector_counts.head(15).items():
        print(f"    {sector}: {count}")

    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(sectors, f)

    return sectors


# ============================================================================
# MODIFIED SIGNAL FUNCTIONS
# ============================================================================

def compute_momentum_scores_666(price_data: Dict[str, pd.DataFrame],
                                 tradeable: List[str],
                                 date: pd.Timestamp,
                                 all_dates: List[pd.Timestamp],
                                 date_idx: int) -> Dict[str, float]:
    """
    Compute 666-day momentum scores for each stock.

    Score = momentum_666d (excluding last 5 days) - skip_5d_return
    High score = strong long-term momentum + recent pullback = buy signal
    """
    scores = {}

    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue

        # Normalize index to timezone-naive for comparison
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            df_normalized = df.copy()
            df_normalized.index = df_normalized.index.tz_localize(None)
        else:
            df_normalized = df

        # Ensure date is also timezone-naive
        date_normalized = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date

        if date_normalized not in df_normalized.index:
            continue

        # Need at least 666 + 5 days of history
        needed = MOMENTUM_LOOKBACK + MOMENTUM_SKIP

        try:
            sym_idx = df_normalized.index.get_loc(date_normalized)
        except KeyError:
            continue

        if sym_idx < needed:
            # Use adaptive lookback for early period
            # Start with min 180 days, scale up to 666 as data becomes available
            adaptive_lookback = min(sym_idx - MOMENTUM_SKIP, MOMENTUM_LOOKBACK)
            if adaptive_lookback < 180:  # Minimum 180 days (old v8.2 lookback)
                continue
            lookback_actual = adaptive_lookback
        else:
            lookback_actual = MOMENTUM_LOOKBACK

        close_today = df_normalized['Close'].iloc[sym_idx]
        close_skip = df_normalized['Close'].iloc[sym_idx - MOMENTUM_SKIP]
        close_lookback = df_normalized['Close'].iloc[sym_idx - lookback_actual]

        if close_lookback <= 0 or close_skip <= 0 or close_today <= 0:
            continue

        # Long-term momentum (666d return, excluding last 5d)
        momentum_666d = (close_skip / close_lookback) - 1.0

        # Short-term return (last 5 days) - we want stocks that dipped recently
        skip_5d = (close_today / close_skip) - 1.0

        # Score: high long-term momentum + recent dip = buy
        score = momentum_666d - skip_5d
        scores[symbol] = score

    return scores


def select_stocks_with_sector_constraint(momentum_scores: Dict[str, float],
                                        gics_sectors: Dict[str, str],
                                        target_count: int = TOP_N,
                                        max_per_sector: int = SECTOR_MAX) -> List[str]:
    """
    Select top N stocks by momentum with sector constraint.

    Algorithm:
    1. Rank all stocks by momentum score (high to low)
    2. Iterate through ranked list
    3. Add stock if its sector has < max_per_sector stocks
    4. Stop when target_count reached

    Returns: List of selected tickers (length <= target_count)
    """
    # Rank by momentum
    ranked = sorted(momentum_scores.items(), key=lambda x: x[1], reverse=True)

    selected = []
    sector_counts = defaultdict(int)

    for ticker, score in ranked:
        if len(selected) >= target_count:
            break

        # Get sector (default to 'Unknown' if missing)
        sector = gics_sectors.get(ticker, 'Unknown')

        # Check sector constraint
        if sector_counts[sector] < max_per_sector:
            selected.append(ticker)
            sector_counts[sector] += 1

    # Debug: Log sector distribution if not hitting target
    if len(selected) < target_count:
        print(f"  [WARNING] Only selected {len(selected)}/{target_count} stocks (sector constraint limiting)")
        print(f"    Sector counts: {dict(sector_counts)}")

    return selected


# ============================================================================
# POSITION MANAGEMENT
# ============================================================================

def compute_equal_weights(selected: List[str]) -> Dict[str, float]:
    """Compute equal weights for selected stocks"""
    n = len(selected)
    if n == 0:
        return {}
    return {ticker: 1.0 / n for ticker in selected}


def check_rebalance_needed(positions: Dict[str, Dict],
                          price_data: Dict[str, pd.DataFrame],
                          date: pd.Timestamp,
                          target_weights: Dict[str, float],
                          portfolio_value: float) -> bool:
    """
    Check if rebalancing is needed based on drift threshold.

    Returns True if any position has drifted more than REBALANCE_DRIFT_PCT
    from its target weight.
    """
    if not positions or portfolio_value <= 0:
        return False

    # Normalize date
    date_normalized = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date

    for symbol, pos in positions.items():
        if symbol not in price_data:
            continue

        df = price_data[symbol]
        # Normalize df index
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            df_normalized = df.copy()
            df_normalized.index = df_normalized.index.tz_localize(None)
        else:
            df_normalized = df

        if date_normalized not in df_normalized.index:
            continue

        current_price = df_normalized.loc[date_normalized, 'Close']
        position_value = pos['shares'] * current_price
        current_weight = position_value / portfolio_value

        target_weight = target_weights.get(symbol, TARGET_WEIGHT)

        # Calculate relative drift
        if target_weight > 0:
            relative_drift = abs(current_weight - target_weight) / target_weight

            if relative_drift > REBALANCE_DRIFT_PCT:
                return True

    return False


# ============================================================================
# BACKTEST ENGINE
# ============================================================================

def get_tradeable_symbols_v83(price_data: Dict[str, pd.DataFrame],
                              date: pd.Timestamp,
                              first_date: pd.Timestamp,
                              annual_universe: Dict[int, List[str]]) -> List[str]:
    """Return tradeable symbols from top-66 for that year"""
    eligible = set(annual_universe.get(date.year, []))
    tradeable = []

    # Normalize dates
    date_normalized = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date
    first_date_normalized = first_date.tz_localize(None) if hasattr(first_date, 'tz') and first_date.tz else first_date

    for symbol in eligible:
        if symbol not in price_data:
            continue
        df = price_data[symbol]

        # Normalize df index
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            df_normalized = df.copy()
            df_normalized.index = df_normalized.index.tz_localize(None)
        else:
            df_normalized = df

        if date_normalized not in df_normalized.index:
            continue

        symbol_first_date = df_normalized.index[0]
        days_since_start = (date_normalized - symbol_first_date).days

        if date_normalized <= first_date_normalized + timedelta(days=30):
            tradeable.append(symbol)
        elif days_since_start >= MIN_AGE_DAYS:
            tradeable.append(symbol)

    return tradeable


def run_backtest_v83(price_data: Dict[str, pd.DataFrame],
                     annual_universe: Dict[int, List[str]],
                     spy_data: pd.DataFrame,
                     gics_sectors: Dict[str, str],
                     cash_yield_daily: Optional[pd.Series] = None) -> Dict:
    """
    Run COMPASS v8.3 "666 Framework" backtest.

    Key differences from v8.2:
    - 666-day momentum lookback
    - 66 equal-weighted positions
    - Sector constraint (max 11 per sector)
    - Drift-based rebalancing (6.66% threshold)
    - No fixed hold period
    """
    print("\n" + "=" * 80)
    print("RUNNING COMPASS v8.3 '666 FRAMEWORK' BACKTEST")
    print("=" * 80)

    # Get all trading dates
    all_dates = set()
    for df in price_data.values():
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            all_dates.update(df.index.tz_localize(None))
        else:
            all_dates.update(df.index)

    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    # Compute regime
    print("\nComputing market regime (SPY vs SMA200)...")
    regime = compute_regime(spy_data)

    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")
    print(f"Universe: Top-{TOP_N} stocks, max {SECTOR_MAX} per sector")
    print(f"Rebalancing: {REBALANCE_DRIFT_PCT:.2%} drift threshold")

    # Portfolio state
    cash = float(INITIAL_CAPITAL)
    positions = {}  # symbol -> {entry_price, shares, entry_date, entry_idx, high_price}
    target_weights = {}  # symbol -> target_weight
    portfolio_values = []
    trades = []
    stop_events = []
    rebalance_events = []

    peak_value = float(INITIAL_CAPITAL)
    in_protection_mode = False
    protection_stage = 0
    stop_loss_day_index = None

    risk_on_days = 0
    risk_off_days = 0

    current_year = None
    total_commissions = 0

    for i, date in enumerate(all_dates):
        # Annual rotation check
        if date.year != current_year:
            current_year = date.year

        tradeable_symbols = get_tradeable_symbols_v83(price_data, date, first_date, annual_universe)

        # --- Calculate portfolio value ---
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data:
                df = price_data[symbol]
                # Normalize
                if hasattr(df.index, 'tz') and df.index.tz is not None:
                    df_norm = df.copy()
                    df_norm.index = df_norm.index.tz_localize(None)
                else:
                    df_norm = df

                date_norm = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date

                if date_norm in df_norm.index:
                    price = df_norm.loc[date_norm, 'Close']
                    portfolio_value += pos['shares'] * price

        # --- Update peak ---
        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # --- Check recovery from protection mode ---
        if in_protection_mode and stop_loss_day_index is not None:
            days_since_stop = i - stop_loss_day_index

            # Normalize regime date
            regime_date = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date
            is_regime_on = True
            if regime_date in regime.index:
                is_regime_on = bool(regime.loc[regime_date])

            if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and is_regime_on:
                protection_stage = 2
                print(f"  [RECOVERY S1] {date.strftime('%Y-%m-%d')}: Stage 2 | Value: ${portfolio_value:,.0f}")

            if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and is_regime_on:
                in_protection_mode = False
                protection_stage = 0
                peak_value = portfolio_value
                stop_loss_day_index = None
                print(f"  [RECOVERY S2] {date.strftime('%Y-%m-%d')}: Full recovery | Value: ${portfolio_value:,.0f}")

        # --- Drawdown ---
        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # --- Portfolio stop loss ---
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({
                'date': date,
                'portfolio_value': portfolio_value,
                'drawdown': drawdown
            })
            print(f"\n  [STOP LOSS] {date.strftime('%Y-%m-%d')}: DD {drawdown:.1%} | Value: ${portfolio_value:,.0f}")

            # Close ALL positions
            for symbol in list(positions.keys()):
                if symbol in price_data:
                    df = price_data[symbol]
                    if hasattr(df.index, 'tz') and df.index.tz is not None:
                        df_norm = df.copy()
                        df_norm.index = df_norm.index.tz_localize(None)
                    else:
                        df_norm = df

                    date_norm = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date

                    if date_norm in df_norm.index:
                        exit_price = df_norm.loc[date_norm, 'Close']
                        pos = positions[symbol]
                        proceeds = pos['shares'] * exit_price
                        commission = pos['shares'] * COMMISSION_PER_SHARE
                        total_commissions += commission
                        cash += proceeds - commission
                        pnl = (exit_price - pos['entry_price']) * pos['shares'] - commission
                        trades.append({
                            'symbol': symbol,
                            'entry_date': pos['entry_date'],
                            'exit_date': date,
                            'exit_reason': 'portfolio_stop',
                            'pnl': pnl,
                            'return': pnl / (pos['entry_price'] * pos['shares'])
                        })
                del positions[symbol]

            in_protection_mode = True
            protection_stage = 1
            stop_loss_day_index = i
            target_weights = {}

        # --- Regime ---
        regime_date = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date
        is_risk_on = True
        if regime_date in regime.index:
            is_risk_on = bool(regime.loc[regime_date])
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # --- Determine target positions and leverage ---
        if in_protection_mode:
            if protection_stage == 1:
                target_positions = 11  # Reduce to 1/6 of normal (keeping 666 theme)
                current_leverage = 0.3
            else:  # stage 2
                target_positions = 33  # Half of normal
                current_leverage = 1.0
        elif not is_risk_on:
            target_positions = NUM_POSITIONS_RISK_OFF  # 11 stocks
            current_leverage = 1.0
        else:
            target_positions = NUM_POSITIONS  # 66 stocks
            current_leverage = compute_dynamic_leverage(spy_data, date)

        # --- Daily costs ---
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # --- Cash yield ---
        if cash > 0:
            regime_date = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date
            if cash_yield_daily is not None and regime_date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[regime_date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

        # --- Check for position-level stops ---
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data:
                continue

            df = price_data[symbol]
            if hasattr(df.index, 'tz') and df.index.tz is not None:
                df_norm = df.copy()
                df_norm.index = df_norm.index.tz_localize(None)
            else:
                df_norm = df

            date_norm = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date

            if date_norm not in df_norm.index:
                continue

            current_price = df_norm.loc[date_norm, 'Close']
            exit_reason = None

            # 1. Position stop loss (-8%)
            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            if pos_return <= POSITION_STOP_LOSS:
                exit_reason = 'position_stop'

            # 2. Trailing stop
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                trailing_level = pos['high_price'] * (1 - TRAILING_STOP_PCT)
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            # 3. Stock no longer in tradeable universe
            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'

            if exit_reason:
                shares = pos['shares']
                proceeds = shares * current_price
                commission = shares * COMMISSION_PER_SHARE
                total_commissions += commission
                cash += proceeds - commission
                pnl = (current_price - pos['entry_price']) * shares - commission
                trades.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'exit_reason': exit_reason,
                    'pnl': pnl,
                    'return': pnl / (pos['entry_price'] * shares)
                })
                del positions[symbol]
                if symbol in target_weights:
                    del target_weights[symbol]

        # --- Check drift-based rebalancing ---
        needs_rebalance = False

        # Force rebalance if position count doesn't match target
        if len(positions) != target_positions and len(tradeable_symbols) >= target_positions:
            needs_rebalance = True

        # Check drift for existing positions
        if not needs_rebalance and len(positions) > 0:
            needs_rebalance = check_rebalance_needed(positions, price_data, date,
                                                     target_weights, portfolio_value)

        # --- Rebalance if needed ---
        if needs_rebalance and cash > 1000 and len(tradeable_symbols) >= target_positions // 2:
            rebalance_events.append({
                'date': date,
                'reason': 'drift_threshold',
                'positions_before': len(positions),
                'portfolio_value': portfolio_value
            })

            # Close all positions
            for symbol in list(positions.keys()):
                if symbol in price_data:
                    df = price_data[symbol]
                    if hasattr(df.index, 'tz') and df.index.tz is not None:
                        df_norm = df.copy()
                        df_norm.index = df_norm.index.tz_localize(None)
                    else:
                        df_norm = df

                    date_norm = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date

                    if date_norm in df_norm.index:
                        exit_price = df_norm.loc[date_norm, 'Close']
                        pos = positions[symbol]
                        proceeds = pos['shares'] * exit_price
                        commission = pos['shares'] * COMMISSION_PER_SHARE
                        total_commissions += commission
                        cash += proceeds - commission
                        pnl = (exit_price - pos['entry_price']) * pos['shares'] - commission
                        trades.append({
                            'symbol': symbol,
                            'entry_date': pos['entry_date'],
                            'exit_date': date,
                            'exit_reason': 'rebalance',
                            'pnl': pnl,
                            'return': pnl / (pos['entry_price'] * pos['shares'])
                        })
                del positions[symbol]

            positions = {}
            target_weights = {}

            # Open new positions
            if len(tradeable_symbols) >= target_positions // 2:
                # Compute 666-day momentum scores
                scores = compute_momentum_scores_666(price_data, tradeable_symbols, date, all_dates, i)

                if len(scores) >= target_positions // 2:
                    # Select with sector constraint
                    selected = select_stocks_with_sector_constraint(
                        scores, gics_sectors, target_positions, SECTOR_MAX
                    )

                    if len(selected) > 0:
                        # Equal weights
                        target_weights = compute_equal_weights(selected)

                        # Effective capital
                        effective_capital = cash * current_leverage * 0.95

                        # Open positions
                        for symbol in selected:
                            if symbol not in price_data:
                                continue

                            df = price_data[symbol]
                            if hasattr(df.index, 'tz') and df.index.tz is not None:
                                df_norm = df.copy()
                                df_norm.index = df_norm.index.tz_localize(None)
                            else:
                                df_norm = df

                            date_norm = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date

                            if date_norm not in df_norm.index:
                                continue

                            entry_price = df_norm.loc[date_norm, 'Close']
                            if entry_price <= 0:
                                continue

                            weight = target_weights[symbol]
                            position_value = effective_capital * weight
                            shares = position_value / entry_price
                            cost = shares * entry_price
                            commission = shares * COMMISSION_PER_SHARE
                            total_commissions += commission

                            if cost + commission <= cash:
                                positions[symbol] = {
                                    'entry_price': entry_price,
                                    'shares': shares,
                                    'entry_date': date,
                                    'entry_idx': i,
                                    'high_price': entry_price,
                                }
                                cash -= cost + commission

        # --- Open positions if we have none (startup or post-stop) ---
        elif len(positions) == 0 and cash > 1000 and len(tradeable_symbols) >= target_positions // 2:
            scores = compute_momentum_scores_666(price_data, tradeable_symbols, date, all_dates, i)

            if len(scores) >= target_positions // 2:
                selected = select_stocks_with_sector_constraint(
                    scores, gics_sectors, target_positions, SECTOR_MAX
                )

                if len(selected) > 0:
                    target_weights = compute_equal_weights(selected)
                    effective_capital = cash * current_leverage * 0.95

                    for symbol in selected:
                        if symbol not in price_data:
                            continue

                        df = price_data[symbol]
                        if hasattr(df.index, 'tz') and df.index.tz is not None:
                            df_norm = df.copy()
                            df_norm.index = df_norm.index.tz_localize(None)
                        else:
                            df_norm = df

                        date_norm = date.tz_localize(None) if hasattr(date, 'tz') and date.tz else date

                        if date_norm not in df_norm.index:
                            continue

                        entry_price = df_norm.loc[date_norm, 'Close']
                        if entry_price <= 0:
                            continue

                        weight = target_weights[symbol]
                        position_value = effective_capital * weight
                        shares = position_value / entry_price
                        cost = shares * entry_price
                        commission = shares * COMMISSION_PER_SHARE
                        total_commissions += commission

                        if cost + commission <= cash:
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
            'in_protection': in_protection_mode,
            'risk_on': is_risk_on,
            'universe_size': len(tradeable_symbols)
        })

        # Progress
        if (i + 1) % 252 == 0 or i == len(all_dates) - 1:
            years = (i + 1) / 252
            print(f"  [{date.strftime('%Y-%m-%d')}] Year {years:.1f} | "
                  f"Value: ${portfolio_value:,.0f} | Positions: {len(positions)} | "
                  f"DD: {drawdown:.1%}")

    # --- Final summary ---
    print("\n" + "=" * 80)
    print("BACKTEST COMPLETE")
    print("=" * 80)

    final_value = portfolio_values[-1]['value']
    total_return = (final_value / INITIAL_CAPITAL - 1) * 100
    years = len(all_dates) / 252
    cagr = (pow(final_value / INITIAL_CAPITAL, 1 / years) - 1) * 100

    print(f"\nFinal Value: ${final_value:,.0f}")
    print(f"Total Return: {total_return:.2f}%")
    print(f"CAGR: {cagr:.2f}%")
    print(f"Years: {years:.2f}")
    print(f"Total Trades: {len(trades)}")
    print(f"Total Commissions: ${total_commissions:,.2f}")
    print(f"Rebalance Events: {len(rebalance_events)}")
    print(f"Stop Loss Events: {len(stop_events)}")
    print(f"Risk-On Days: {risk_on_days} ({risk_on_days/len(all_dates)*100:.1f}%)")
    print(f"Risk-Off Days: {risk_off_days} ({risk_off_days/len(all_dates)*100:.1f}%)")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': trades,
        'stop_events': stop_events,
        'rebalance_events': rebalance_events,
        'total_commissions': total_commissions,
        'final_metrics': {
            'final_value': final_value,
            'total_return': total_return,
            'cagr': cagr,
            'years': years,
            'total_trades': len(trades),
        }
    }


# ============================================================================
# COMPARISON ANALYSIS
# ============================================================================

def compare_v82_v83(results_v83: Dict):
    """
    Compare COMPASS v8.3 (666 Framework) vs v8.2 baseline (Exp41).
    """
    print("\n" + "=" * 80)
    print("PERFORMANCE COMPARISON: v8.2 (Baseline) vs v8.3 (666 Framework)")
    print("=" * 80)

    # Load Exp41 baseline results
    baseline_file = 'backtests/exp41_corrected_daily.csv'
    if not os.path.exists(baseline_file):
        print(f"[ERROR] Baseline file not found: {baseline_file}")
        print("Please run exp41_extended_1996.py first to generate baseline.")
        return

    baseline_df = pd.read_csv(baseline_file)
    baseline_final = baseline_df.iloc[-1]['value']
    baseline_years = len(baseline_df) / 252
    baseline_cagr = (pow(baseline_final / INITIAL_CAPITAL, 1 / baseline_years) - 1) * 100

    # Calculate baseline Sharpe and max DD
    baseline_df['returns'] = baseline_df['value'].pct_change()
    baseline_sharpe = (baseline_df['returns'].mean() * 252) / (baseline_df['returns'].std() * np.sqrt(252))
    baseline_max_dd = baseline_df['drawdown'].min() * 100

    # v8.3 metrics
    v83_equity = results_v83['portfolio_values']
    v83_final = v83_equity.iloc[-1]['value']
    v83_years = len(v83_equity) / 252
    v83_cagr = (pow(v83_final / INITIAL_CAPITAL, 1 / v83_years) - 1) * 100

    v83_equity['returns'] = v83_equity['value'].pct_change()
    v83_sharpe = (v83_equity['returns'].mean() * 252) / (v83_equity['returns'].std() * np.sqrt(252))
    v83_max_dd = v83_equity['drawdown'].min() * 100

    v83_trades = len(results_v83['trades'])
    baseline_trades_file = 'backtests/exp41_corrected_trades.csv'
    baseline_trades = len(pd.read_csv(baseline_trades_file)) if os.path.exists(baseline_trades_file) else 0

    # Print comparison
    print(f"\n{'Metric':<30} {'v8.2 (Exp41)':<20} {'v8.3 (666)':<20} {'Improvement':<15}")
    print("-" * 85)
    print(f"{'Final Value':<30} ${baseline_final:>18,.0f} ${v83_final:>18,.0f} ${v83_final - baseline_final:>13,.0f}")
    print(f"{'CAGR':<30} {baseline_cagr:>18.2f}% {v83_cagr:>18.2f}% {v83_cagr - baseline_cagr:>13.2f}%")
    print(f"{'Sharpe Ratio':<30} {baseline_sharpe:>18.3f} {v83_sharpe:>18.3f} {v83_sharpe - baseline_sharpe:>13.3f}")
    print(f"{'Max Drawdown':<30} {baseline_max_dd:>18.2f}% {v83_max_dd:>18.2f}% {v83_max_dd - baseline_max_dd:>13.2f}%")
    print(f"{'Total Trades':<30} {baseline_trades:>18,} {v83_trades:>18,} {v83_trades - baseline_trades:>13,}")
    print(f"{'Commissions Paid':<30} ${'N/A':>18} ${results_v83['total_commissions']:>18,.0f} {'N/A':>13}")
    print("-" * 85)

    improvement = v83_cagr - baseline_cagr
    print(f"\n{'=' * 85}")
    if improvement > 0:
        print(f"  IMPROVEMENT: +{improvement:.2f}% CAGR")
        print(f"  The '666 Framework' outperformed v8.2 baseline by {improvement:.2f}% per year")
    else:
        print(f"  REGRESSION: {improvement:.2f}% CAGR")
        print(f"  The '666 Framework' underperformed v8.2 baseline by {abs(improvement):.2f}% per year")
    print(f"{'=' * 85}")

    # Save detailed comparison
    os.makedirs('backtests', exist_ok=True)
    with open('backtests/exp42_comparison_v82_v83.txt', 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("EXPERIMENT 42: COMPASS v8.3 '666 FRAMEWORK' vs v8.2 BASELINE\n")
        f.write("=" * 80 + "\n\n")

        f.write("METHODOLOGY\n")
        f.write("-" * 80 + "\n")
        f.write("Tier 1 Changes from v8.2 to v8.3:\n")
        f.write("  1. Lookback period: 180 days → 666 trading days (~2.6 years)\n")
        f.write("  2. Stock selection: 40 stocks → 66 stocks\n")
        f.write("  3. Sector constraint: None → Maximum 11 stocks per GICS sector\n")
        f.write("  4. Rebalancing: 5-day fixed hold → 6.66% drift threshold\n\n")

        f.write("BACKTEST PARAMETERS\n")
        f.write("-" * 80 + "\n")
        f.write(f"Period: {START_DATE} to 2026 (30 years)\n")
        f.write(f"Universe: S&P 500 point-in-time (survivorship-bias corrected)\n")
        f.write(f"Initial Capital: ${INITIAL_CAPITAL:,}\n")
        f.write(f"Commission: ${COMMISSION_PER_SHARE}/share\n\n")

        f.write("RESULTS\n")
        f.write("-" * 80 + "\n")
        f.write(f"{'Metric':<30} {'v8.2 (Exp41)':<20} {'v8.3 (666)':<20} {'Improvement':<15}\n")
        f.write("-" * 80 + "\n")
        f.write(f"{'Final Value':<30} ${baseline_final:>18,.0f} ${v83_final:>18,.0f} ${v83_final - baseline_final:>13,.0f}\n")
        f.write(f"{'CAGR':<30} {baseline_cagr:>18.2f}% {v83_cagr:>18.2f}% {v83_cagr - baseline_cagr:>13.2f}%\n")
        f.write(f"{'Sharpe Ratio':<30} {baseline_sharpe:>18.3f} {v83_sharpe:>18.3f} {v83_sharpe - baseline_sharpe:>13.3f}\n")
        f.write(f"{'Max Drawdown':<30} {baseline_max_dd:>18.2f}% {v83_max_dd:>18.2f}% {v83_max_dd - baseline_max_dd:>13.2f}%\n")
        f.write(f"{'Total Trades':<30} {baseline_trades:>18,} {v83_trades:>18,} {v83_trades - baseline_trades:>13,}\n")
        f.write("-" * 80 + "\n\n")

        f.write("INTERPRETATION\n")
        f.write("-" * 80 + "\n")
        if improvement > 0:
            f.write(f"The '666 Framework' successfully improved performance by {improvement:.2f}% CAGR.\n\n")
            f.write("Key drivers:\n")
            f.write("  - Longer 666-day lookback captures sustained trends\n")
            f.write("  - 66-stock diversification reduces idiosyncratic risk\n")
            f.write("  - Sector constraint prevents concentration in bubbles\n")
            f.write("  - Drift rebalancing reduces unnecessary turnover\n")
        else:
            f.write(f"The '666 Framework' underperformed by {abs(improvement):.2f}% CAGR.\n\n")
            f.write("Possible reasons:\n")
            f.write("  - 666-day lookback too slow for mean-reverting markets\n")
            f.write("  - Over-diversification (66 stocks) dilutes alpha from top performers\n")
            f.write("  - Sector constraint excludes high-momentum stocks in winning sectors\n")
            f.write("  - Higher commission costs from 66 positions vs 5\n")

    print("\n[SAVED] Comparison saved to backtests/exp42_comparison_v82_v83.txt")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution"""

    print("\n" + "=" * 80)
    print("STEP 1: LOAD HISTORICAL DATA (FROM EXP41 CACHE)")
    print("=" * 80)

    # Download constituents and build universe
    constituents_df = download_sp500_constituents_history()
    pit_universe = build_point_in_time_universe(constituents_df, START_DATE, END_DATE)

    # Download price data (reuse Exp41 cache)
    expanded_data = download_expanded_pool(pit_universe)

    # Download SPY and cash yield
    spy_data = download_spy()
    cash_yield = download_cash_yield()

    print("\n" + "=" * 80)
    print("STEP 2: DOWNLOAD GICS SECTOR DATA")
    print("=" * 80)

    gics_sectors = download_gics_sectors()

    print("\n" + "=" * 80)
    print("STEP 3: COMPUTE ANNUAL TOP-66 UNIVERSE")
    print("=" * 80)

    # Recompute annual universe with TOP_N = 66
    print(f"\nComputing annual top-{TOP_N} rotation (by dollar volume)...")

    # We'll reuse the compute_annual_top40_corrected function but it will now select TOP_N = 66
    annual_universe_v83 = compute_annual_top40_corrected(expanded_data)

    print("\n" + "=" * 80)
    print("STEP 4: RUN COMPASS v8.3 '666 FRAMEWORK' BACKTEST")
    print("=" * 80)

    results_v83 = run_backtest_v83(expanded_data, annual_universe_v83, spy_data,
                                   gics_sectors, cash_yield)

    print("\n" + "=" * 80)
    print("STEP 5: SAVE RESULTS")
    print("=" * 80)

    os.makedirs('backtests', exist_ok=True)

    # Save equity curve
    results_v83['portfolio_values'].to_csv('backtests/exp42_compass_666_daily.csv', index=False)
    print("  Saved: backtests/exp42_compass_666_daily.csv")

    # Save trades
    pd.DataFrame(results_v83['trades']).to_csv('backtests/exp42_compass_666_trades.csv', index=False)
    print("  Saved: backtests/exp42_compass_666_trades.csv")

    # Save rebalance events
    pd.DataFrame(results_v83['rebalance_events']).to_csv('backtests/exp42_compass_666_rebalances.csv', index=False)
    print("  Saved: backtests/exp42_compass_666_rebalances.csv")

    print("\n" + "=" * 80)
    print("STEP 6: COMPARE vs BASELINE (EXP41)")
    print("=" * 80)

    compare_v82_v83(results_v83)

    print("\n" + "=" * 80)
    print("EXPERIMENT 42 COMPLETE")
    print("=" * 80)

    print("\nNext steps:")
    print("1. Review backtests/exp42_comparison_v82_v83.txt for detailed analysis")
    print("2. Compare equity curves: exp41_corrected_daily.csv vs exp42_compass_666_daily.csv")
    print("3. Analyze trade-level data in exp42_compass_666_trades.csv")
    print("4. Check rebalancing frequency in exp42_compass_666_rebalances.csv")


if __name__ == '__main__':
    main()
