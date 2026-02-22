"""
OmniCapital v8.2 COMPASS -- Chassis Upgrade v1.0
=================================================
Same LOCKED motor (signal, parameters, regime filter) as production.
Upgraded chassis:
  1. Realistic execution: signal on Close[T], execute at Open[T+1] + slippage
  2. Parquet data cache (faster, smaller, type-safe)
  3. Unified date index with pre-aligned matrices (no per-stock get_loc)
  4. SGOV/BIL collateral simulation (replaces flat cash yield)

Purpose: measure TRUE net-of-friction CAGR and identify execution alpha.
Compare results vs original to quantify slippage drag.

IMPORTANT: The motor parameters are IDENTICAL to omnicapital_v8_compass.py.
           This file only changes HOW trades are executed, not WHAT trades.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import os
from typing import Dict, List, Optional
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# MOTOR PARAMETERS -- IDENTICAL TO PRODUCTION (DO NOT MODIFY)
# ============================================================================

TOP_N = 40
MIN_AGE_DAYS = 63
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
MIN_MOMENTUM_STOCKS = 20
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3
NUM_POSITIONS = 5
NUM_POSITIONS_RISK_OFF = 2
HOLD_DAYS = 5
POSITION_STOP_LOSS = -0.08
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03
PORTFOLIO_STOP_LOSS = -0.15
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126
TARGET_VOL = 0.15
LEVERAGE_MIN = 0.3
LEVERAGE_MAX = 2.0
VOL_LOOKBACK = 20
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001

# ============================================================================
# CHASSIS PARAMETERS -- NEW (execution & friction)
# ============================================================================

# Execution model: signal on Close[T], execute at Open[T+1]
USE_NEXT_DAY_OPEN = True        # True = realistic, False = legacy Close-to-Close

# Slippage: cost of crossing bid-ask + market impact
SLIPPAGE_BPS = 5                # 5 basis points (0.05%) per side -- conservative
                                # for top-40 liquid S&P 500 stocks
                                # Institutional estimate: 3-10 bps depending on urgency

# Capital efficiency: T-Bill ETF collateral
# Instead of flat CASH_YIELD_RATE, simulate holding uninvested cash in SGOV
# SGOV yield ~= Fed Funds Rate (we use historical proxy: 3-month T-Bill rate)
# Margin haircut on SGOV: ~2% (IBKR), so 98% usable as collateral
USE_TBILL_COLLATERAL = True
TBILL_HAIRCUT = 0.02            # 2% margin haircut on T-Bill ETFs
# Historical T-Bill yields (annual, approximate) by era:
# 2000-2003: ~4.0%, 2004-2007: ~4.5%, 2008-2015: ~0.2%, 2016-2019: ~2.0%
# 2020-2021: ~0.1%, 2022-2026: ~4.5%
TBILL_YIELD_BY_ERA = {
    2000: 0.055, 2001: 0.035, 2002: 0.016, 2003: 0.010, 2004: 0.022,
    2005: 0.040, 2006: 0.048, 2007: 0.045, 2008: 0.015, 2009: 0.002,
    2010: 0.001, 2011: 0.001, 2012: 0.001, 2013: 0.001, 2014: 0.001,
    2015: 0.002, 2016: 0.005, 2017: 0.013, 2018: 0.024, 2019: 0.021,
    2020: 0.004, 2021: 0.001, 2022: 0.030, 2023: 0.052, 2024: 0.050,
    2025: 0.043, 2026: 0.040,
}

# Data
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

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

print("=" * 80)
print("OMNICAPITAL v8.2 COMPASS -- CHASSIS UPGRADE v1.0")
print("=" * 80)
print(f"Motor: LOCKED (identical to production)")
print(f"Chassis upgrades:")
print(f"  [1] Execution: {'Open[T+1] + {SLIPPAGE_BPS}bps slippage' if USE_NEXT_DAY_OPEN else 'Close[T] (legacy)'}")
print(f"  [2] Data cache: Parquet (vs pickle/csv)")
print(f"  [3] Index: Pre-aligned unified matrix (vs per-stock get_loc)")
print(f"  [4] Capital: {'T-Bill collateral (historical rates)' if USE_TBILL_COLLATERAL else 'Flat 3.5% yield'}")
print()


# ============================================================================
# UPGRADE #2: PARQUET DATA CACHE
# ============================================================================

def download_broad_pool() -> Dict[str, pd.DataFrame]:
    """Download/load cached data using Parquet format.

    Parquet advantages over pickle:
    - 3-5x faster reads for time-series data
    - ~60% smaller file size with snappy compression
    - Preserves dtypes (no pickle version mismatch issues)
    - Human-inspectable schema
    """
    cache_dir = 'data_cache_parquet'
    os.makedirs(cache_dir, exist_ok=True)
    manifest_file = os.path.join(cache_dir, f'manifest_{START_DATE}_{END_DATE}.txt')

    # Check if we have a complete cache
    if os.path.exists(manifest_file):
        print("[Cache/Parquet] Loading broad pool data...")
        data = {}
        failed_loads = 0
        for symbol in BROAD_POOL:
            pq_file = os.path.join(cache_dir, f'{symbol}.parquet')
            if os.path.exists(pq_file):
                try:
                    df = pd.read_parquet(pq_file)
                    if len(df) > 100:
                        data[symbol] = df
                    else:
                        failed_loads += 1
                except Exception:
                    failed_loads += 1
            else:
                failed_loads += 1

        if failed_loads == 0 or len(data) >= len(BROAD_POOL) - 5:
            print(f"[Cache/Parquet] Loaded {len(data)} symbols")
            return data
        else:
            print(f"[Cache/Parquet] Incomplete cache ({failed_loads} missing), re-downloading...")

    # Download fresh data
    print(f"[Download] Downloading {len(BROAD_POOL)} symbols...")
    data = {}
    failed = []

    for i, symbol in enumerate(BROAD_POOL):
        try:
            df = yf.download(symbol, start=START_DATE, end=END_DATE, progress=False)
            if not df.empty and len(df) > 100:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                data[symbol] = df
                # Save individual parquet
                pq_file = os.path.join(cache_dir, f'{symbol}.parquet')
                df.to_parquet(pq_file, compression='snappy')
                if (i + 1) % 20 == 0:
                    print(f"  [{i+1}/{len(BROAD_POOL)}] Downloaded {len(data)} symbols...")
            else:
                failed.append(symbol)
        except Exception:
            failed.append(symbol)

    print(f"[Download] {len(data)} symbols valid, {len(failed)} failed")

    # Write manifest
    with open(manifest_file, 'w') as f:
        f.write(f"symbols={len(data)}\ndate={datetime.now().isoformat()}\n")
        for sym in sorted(data.keys()):
            f.write(f"{sym}: {len(data[sym])} rows\n")

    return data


def download_spy() -> pd.DataFrame:
    """Download SPY data using Parquet cache."""
    cache_dir = 'data_cache_parquet'
    os.makedirs(cache_dir, exist_ok=True)
    pq_file = os.path.join(cache_dir, f'SPY.parquet')

    if os.path.exists(pq_file):
        print("[Cache/Parquet] Loading SPY data...")
        return pd.read_parquet(pq_file)

    print("[Download] Downloading SPY...")
    df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.to_parquet(pq_file, compression='snappy')
    return df


# ============================================================================
# UPGRADE #3: UNIFIED DATE INDEX + PRE-ALIGNED MATRICES
# ============================================================================

def build_aligned_matrices(price_data: Dict[str, pd.DataFrame],
                           spy_data: pd.DataFrame):
    """Pre-align all stock data to a single unified date index.

    Instead of calling df.index.get_loc(date) thousands of times per day
    inside the backtest loop, we build NxM matrices (dates x symbols)
    for Close and Open prices. Then we use integer indexing (iloc[i])
    throughout the backtest -- O(1) per lookup instead of O(log N).

    Returns:
        all_dates: sorted list of trading dates
        close_matrix: DataFrame (dates x symbols) of Close prices
        open_matrix: DataFrame (dates x symbols) of Open prices
        volume_matrix: DataFrame (dates x symbols) of Volume
        symbols: list of symbol names (column order)
    """
    print("\n[Align] Building unified price matrices...")

    # Build master date index from SPY (most complete)
    all_dates = sorted(spy_data.index.tolist())

    symbols = sorted(price_data.keys())

    # Pre-allocate with NaN
    close_data = {}
    open_data = {}
    volume_data = {}

    for symbol in symbols:
        df = price_data[symbol]
        # Reindex to master dates (fills missing with NaN)
        close_data[symbol] = df['Close'].reindex(all_dates)
        open_data[symbol] = df['Open'].reindex(all_dates)
        volume_data[symbol] = df['Volume'].reindex(all_dates)

    close_matrix = pd.DataFrame(close_data, index=all_dates)
    open_matrix = pd.DataFrame(open_data, index=all_dates)
    volume_matrix = pd.DataFrame(volume_data, index=all_dates)

    # SPY columns
    spy_close = spy_data['Close'].reindex(all_dates)
    spy_open = spy_data['Open'].reindex(all_dates)

    pct_filled = close_matrix.notna().sum().sum() / (len(all_dates) * len(symbols)) * 100
    print(f"[Align] Matrix: {len(all_dates)} dates x {len(symbols)} symbols ({pct_filled:.1f}% filled)")

    return all_dates, close_matrix, open_matrix, volume_matrix, spy_close, spy_open, symbols


# ============================================================================
# SIGNAL & REGIME (same logic, matrix-optimized)
# ============================================================================

def compute_regime(spy_close: pd.Series) -> pd.Series:
    """Compute regime using pre-aligned SPY close series."""
    sma200 = spy_close.rolling(REGIME_SMA_PERIOD).mean()
    raw_signal = spy_close > sma200

    regime = pd.Series(index=spy_close.index, dtype=bool)
    regime.iloc[:REGIME_SMA_PERIOD] = True

    current_regime = True
    consecutive_count = 0
    last_raw = True

    for i in range(REGIME_SMA_PERIOD, len(raw_signal)):
        raw = raw_signal.iloc[i]
        if pd.isna(raw):
            regime.iloc[i] = current_regime
            continue

        if raw == last_raw:
            consecutive_count += 1
        else:
            consecutive_count = 1
            last_raw = raw

        if raw != current_regime and consecutive_count >= REGIME_CONFIRM_DAYS:
            current_regime = raw
        regime.iloc[i] = current_regime

    return regime


def compute_annual_top40(close_matrix: pd.DataFrame,
                         volume_matrix: pd.DataFrame,
                         all_dates: list) -> Dict[int, List[str]]:
    """Compute annual top-40 using aligned matrices (vectorized)."""
    years = sorted(set(d.year for d in all_dates))
    annual_universe = {}

    for year in years:
        if year == years[0]:
            mask = [(d.year == year - 1) or (d.year == year and d.month == 1) for d in all_dates]
        else:
            mask = [d.year == year - 1 for d in all_dates]

        mask = np.array(mask)
        if mask.sum() < 20:
            continue

        # Dollar volume = Close * Volume (vectorized across all symbols)
        dv = (close_matrix.iloc[mask] * volume_matrix.iloc[mask]).mean()
        dv = dv.dropna()

        if len(dv) < TOP_N:
            top_n = dv.index.tolist()
        else:
            top_n = dv.nlargest(TOP_N).index.tolist()

        annual_universe[year] = top_n

    return annual_universe


# ============================================================================
# UPGRADE #1: REALISTIC EXECUTION MODEL
# ============================================================================

def apply_slippage(price: float, direction: str) -> float:
    """Apply slippage to execution price.

    Args:
        price: raw execution price
        direction: 'buy' or 'sell'

    For buys: you pay MORE (price goes up by slippage)
    For sells: you receive LESS (price goes down by slippage)

    5 bps is conservative for top-40 S&P 500 stocks.
    """
    slip = SLIPPAGE_BPS / 10000.0
    if direction == 'buy':
        return price * (1.0 + slip)
    else:
        return price * (1.0 - slip)


def get_execution_price(close_matrix, open_matrix, i, symbol, direction):
    """Get the price at which a trade would actually execute.

    If USE_NEXT_DAY_OPEN:
        Signal computed on Close[T] -> Execute at Open[T+1] + slippage
        This is the realistic model: you see Close, compute signal overnight,
        submit order for next morning.

    If not USE_NEXT_DAY_OPEN:
        Execute at Close[T] (legacy mode, same as original backtest)
    """
    if USE_NEXT_DAY_OPEN:
        # Execute at next day's open
        if i + 1 < len(close_matrix):
            raw_price = open_matrix.iloc[i + 1][symbol]
            if pd.isna(raw_price) or raw_price <= 0:
                # Fallback to close if open not available
                raw_price = close_matrix.iloc[i][symbol]
        else:
            raw_price = close_matrix.iloc[i][symbol]
    else:
        raw_price = close_matrix.iloc[i][symbol]

    if pd.isna(raw_price) or raw_price <= 0:
        return None

    return apply_slippage(raw_price, direction)


# ============================================================================
# UPGRADE #4: T-BILL COLLATERAL YIELD
# ============================================================================

def get_daily_cash_yield(year: int) -> float:
    """Get daily cash yield based on historical T-Bill rates.

    Instead of a flat 3.5% forever, use era-appropriate rates.
    During ZIRP (2009-2021), cash earned almost nothing.
    This makes the backtest more realistic.
    """
    annual_rate = TBILL_YIELD_BY_ERA.get(year, 0.035)
    return annual_rate / 252


# ============================================================================
# BACKTEST ENGINE (same logic, upgraded execution)
# ============================================================================

def run_backtest(close_matrix: pd.DataFrame,
                 open_matrix: pd.DataFrame,
                 spy_close: pd.Series,
                 all_dates: list,
                 annual_universe: Dict[int, List[str]]) -> Dict:
    """Run COMPASS backtest with chassis upgrades.

    Motor logic: IDENTICAL to production
    Chassis changes:
    - Entries use get_execution_price() -> Open[T+1] + slippage
    - Exits use get_execution_price() -> Open[T+1] + slippage
    - Cash yield uses historical T-Bill rates (not flat 3.5%)
    - All price lookups use iloc[i] on pre-aligned matrices
    """

    print("\n" + "=" * 80)
    print("RUNNING COMPASS v8.2 BACKTEST -- CHASSIS UPGRADE")
    print("=" * 80)

    regime = compute_regime(spy_close)

    first_date = all_dates[0]
    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")
    print(f"Execution: {'Open[T+1] + ' + str(SLIPPAGE_BPS) + 'bps' if USE_NEXT_DAY_OPEN else 'Close[T] (legacy)'}")

    # Portfolio state
    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []
    slippage_costs = []      # Track total slippage drag

    peak_value = float(INITIAL_CAPITAL)
    in_protection_mode = False
    protection_stage = 0
    stop_loss_day_index = None
    post_stop_base = None

    risk_on_days = 0
    risk_off_days = 0
    current_year = None
    total_slippage_cost = 0.0

    symbols_list = close_matrix.columns.tolist()

    for i, date in enumerate(all_dates):

        if date.year != current_year:
            current_year = date.year

        # Tradeable symbols for this year
        eligible = set(annual_universe.get(date.year, []))
        tradeable_symbols = []
        for symbol in eligible:
            if symbol not in symbols_list:
                continue
            close_val = close_matrix.iloc[i][symbol]
            if pd.isna(close_val):
                continue
            # Check min age
            first_valid = close_matrix[symbol].first_valid_index()
            if first_valid is None:
                continue
            days_since_start = (date - first_valid).days
            if date <= first_date + timedelta(days=30):
                tradeable_symbols.append(symbol)
            elif days_since_start >= MIN_AGE_DAYS:
                tradeable_symbols.append(symbol)

        # --- Portfolio value (mark-to-market at Close[T]) ---
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            close_val = close_matrix.iloc[i][symbol]
            if not pd.isna(close_val):
                portfolio_value += pos['shares'] * close_val

        # --- Peak ---
        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # --- Recovery check ---
        if in_protection_mode and stop_loss_day_index is not None:
            days_since_stop = i - stop_loss_day_index
            is_regime_on = bool(regime.iloc[i]) if i < len(regime) else True

            if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and is_regime_on:
                protection_stage = 2

            if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and is_regime_on:
                in_protection_mode = False
                protection_stage = 0
                peak_value = portfolio_value
                stop_loss_day_index = None
                post_stop_base = None

        # --- Drawdown ---
        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # --- Portfolio stop loss ---
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({
                'date': date,
                'portfolio_value': portfolio_value,
                'drawdown': drawdown
            })

            for symbol in list(positions.keys()):
                exec_price = get_execution_price(
                    close_matrix, open_matrix, i, symbol, 'sell')
                if exec_price is None:
                    close_val = close_matrix.iloc[i][symbol]
                    exec_price = close_val if not pd.isna(close_val) else 0

                pos = positions[symbol]
                proceeds = pos['shares'] * exec_price
                commission = pos['shares'] * COMMISSION_PER_SHARE

                # Track slippage cost vs Close price
                close_val = close_matrix.iloc[i][symbol]
                if not pd.isna(close_val) and close_val > 0:
                    slip_cost = abs(exec_price - close_val) * pos['shares']
                    total_slippage_cost += slip_cost

                cash += proceeds - commission
                pnl = (exec_price - pos['entry_price']) * pos['shares'] - commission
                trades.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'exit_reason': 'portfolio_stop',
                    'entry_price': pos['entry_price'],
                    'exit_price': exec_price,
                    'pnl': pnl,
                    'return': pnl / (pos['entry_price'] * pos['shares'])
                })
                del positions[symbol]

            in_protection_mode = True
            protection_stage = 1
            stop_loss_day_index = i
            post_stop_base = cash

        # --- Regime ---
        is_risk_on = bool(regime.iloc[i]) if i < len(regime) else True
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # --- Max positions & leverage ---
        if in_protection_mode:
            if protection_stage == 1:
                max_positions = 2
                current_leverage = 0.3
            else:
                max_positions = 3
                current_leverage = 1.0
        elif not is_risk_on:
            max_positions = NUM_POSITIONS_RISK_OFF
            current_leverage = 1.0
        else:
            max_positions = NUM_POSITIONS
            # Vol targeting using pre-aligned SPY
            if i >= VOL_LOOKBACK + 1:
                returns = spy_close.iloc[i - VOL_LOOKBACK:i + 1].pct_change().dropna()
                if len(returns) >= VOL_LOOKBACK - 2:
                    realized_vol = returns.std() * np.sqrt(252)
                    if realized_vol < 0.01:
                        current_leverage = LEVERAGE_MAX
                    else:
                        current_leverage = max(LEVERAGE_MIN, min(LEVERAGE_MAX, TARGET_VOL / realized_vol))
                else:
                    current_leverage = 1.0
            else:
                current_leverage = 1.0

        # --- Daily costs ---
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # Cash yield (historical T-Bill rate)
        if cash > 0:
            if USE_TBILL_COLLATERAL:
                daily_yield = get_daily_cash_yield(date.year)
                cash += cash * daily_yield
            else:
                cash += cash * (0.035 / 252)

        # --- Exit positions ---
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            close_val = close_matrix.iloc[i][symbol]
            if pd.isna(close_val):
                continue

            current_price = close_val
            exit_reason = None

            days_held = i - pos['entry_idx']
            if days_held >= HOLD_DAYS:
                exit_reason = 'hold_expired'

            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            if pos_return <= POSITION_STOP_LOSS:
                exit_reason = 'position_stop'

            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                trailing_level = pos['high_price'] * (1 - TRAILING_STOP_PCT)
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'

            if exit_reason is None and len(positions) > max_positions:
                pos_returns = {}
                for s, p in positions.items():
                    cv = close_matrix.iloc[i][s]
                    if not pd.isna(cv):
                        pos_returns[s] = (cv - p['entry_price']) / p['entry_price']
                if pos_returns:
                    worst = min(pos_returns, key=pos_returns.get)
                    if symbol == worst:
                        exit_reason = 'regime_reduce'

            if exit_reason:
                exec_price = get_execution_price(
                    close_matrix, open_matrix, i, symbol, 'sell')
                if exec_price is None:
                    exec_price = current_price

                shares = pos['shares']
                proceeds = shares * exec_price
                commission = shares * COMMISSION_PER_SHARE

                # Track slippage
                if current_price > 0:
                    slip_cost = abs(exec_price - current_price) * shares
                    total_slippage_cost += slip_cost

                cash += proceeds - commission
                pnl = (exec_price - pos['entry_price']) * shares - commission
                trades.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'exit_reason': exit_reason,
                    'entry_price': pos['entry_price'],
                    'exit_price': exec_price,
                    'pnl': pnl,
                    'return': pnl / (pos['entry_price'] * shares)
                })
                del positions[symbol]

        # --- Open new positions ---
        needed = max_positions - len(positions)

        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            # Compute momentum scores using Close matrix (signal on Close[T])
            scores = {}
            for symbol in tradeable_symbols:
                if symbol not in symbols_list:
                    continue
                if i < MOMENTUM_LOOKBACK + MOMENTUM_SKIP:
                    continue

                close_today = close_matrix.iloc[i][symbol]
                close_skip = close_matrix.iloc[i - MOMENTUM_SKIP][symbol]
                close_lookback = close_matrix.iloc[i - MOMENTUM_LOOKBACK][symbol]

                if pd.isna(close_today) or pd.isna(close_skip) or pd.isna(close_lookback):
                    continue
                if close_lookback <= 0 or close_skip <= 0 or close_today <= 0:
                    continue

                momentum_90d = (close_skip / close_lookback) - 1.0
                skip_5d = (close_today / close_skip) - 1.0
                scores[symbol] = momentum_90d - skip_5d

            available_scores = {s: sc for s, sc in scores.items() if s not in positions}

            if len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]

                # Inverse-vol weights
                vols = {}
                for symbol in selected:
                    if i < VOL_LOOKBACK + 1:
                        continue
                    returns = close_matrix[symbol].iloc[i - VOL_LOOKBACK:i + 1].pct_change().dropna()
                    if len(returns) >= VOL_LOOKBACK - 2:
                        vol = returns.std() * np.sqrt(252)
                        if vol > 0.01:
                            vols[symbol] = vol

                if vols:
                    raw_weights = {s: 1.0 / v for s, v in vols.items()}
                    total_w = sum(raw_weights.values())
                    weights = {s: w / total_w for s, w in raw_weights.items()}
                else:
                    weights = {s: 1.0 / len(selected) for s in selected}

                effective_capital = cash * current_leverage * 0.95

                for symbol in selected:
                    # Execution at Open[T+1] + slippage
                    exec_price = get_execution_price(
                        close_matrix, open_matrix, i, symbol, 'buy')
                    if exec_price is None:
                        continue

                    close_val = close_matrix.iloc[i][symbol]

                    weight = weights.get(symbol, 1.0 / len(selected))
                    position_value = effective_capital * weight
                    max_per_position = cash * 0.40
                    position_value = min(position_value, max_per_position)

                    shares = position_value / exec_price
                    cost = shares * exec_price
                    commission = shares * COMMISSION_PER_SHARE

                    # Track slippage
                    if not pd.isna(close_val) and close_val > 0:
                        slip_cost = abs(exec_price - close_val) * shares
                        total_slippage_cost += slip_cost

                    if cost + commission <= cash * 0.90:
                        positions[symbol] = {
                            'entry_price': exec_price,
                            'shares': shares,
                            'entry_date': date,
                            'entry_idx': i,
                            'high_price': exec_price,
                        }
                        cash -= cost + commission

        # --- Daily snapshot ---
        portfolio_values.append({
            'date': date,
            'portfolio_value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'drawdown': drawdown,
            'leverage': current_leverage,
            'in_protection': in_protection_mode,
            'risk_on': is_risk_on,
            'universe_size': len(tradeable_symbols)
        })

        if i % 252 == 0 and i > 0:
            year_num = i // 252
            regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
            prot_str = f" [PROT S{protection_stage}]" if in_protection_mode else ""
            print(f"  Year {year_num:2d}: ${portfolio_value:>12,.0f} | DD: {drawdown:>7.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_str:8s}{prot_str} | "
                  f"Pos: {len(positions)} | Slip: ${total_slippage_cost:,.0f}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['portfolio_value'] if portfolio_values else INITIAL_CAPITAL,
        'annual_universe': annual_universe,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
        'total_slippage_cost': total_slippage_cost,
    }


# ============================================================================
# METRICS
# ============================================================================

def calculate_metrics(results: Dict) -> Dict:
    """Calculate performance metrics."""
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']
    stop_df = results['stop_events']

    initial = INITIAL_CAPITAL
    final_value = df['portfolio_value'].iloc[-1]

    years = len(df) / 252
    cagr = (final_value / initial) ** (1 / years) - 1

    returns = df['portfolio_value'].pct_change().dropna()
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

    protection_days = df['in_protection'].sum()
    protection_pct = protection_days / len(df) * 100

    risk_off_pct = results['risk_off_days'] / (results['risk_on_days'] + results['risk_off_days']) * 100

    df_annual = df['portfolio_value'].resample('YE').last()
    annual_returns = df_annual.pct_change().dropna()

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
        'stop_events': len(stop_df),
        'protection_days': protection_days,
        'protection_pct': protection_pct,
        'risk_off_pct': risk_off_pct,
        'annual_returns': annual_returns,
        'best_year': annual_returns.max() if len(annual_returns) > 0 else 0,
        'worst_year': annual_returns.min() if len(annual_returns) > 0 else 0,
        'total_slippage_cost': results.get('total_slippage_cost', 0),
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import time as time_module
    t_start = time_module.time()

    # 1. Download/load data (Parquet)
    price_data = download_broad_pool()
    print(f"\nSymbols available: {len(price_data)}")

    spy_data = download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    # 2. Build aligned matrices (Upgrade #3)
    all_dates, close_matrix, open_matrix, volume_matrix, spy_close, spy_open, symbols = \
        build_aligned_matrices(price_data, spy_data)

    # 3. Compute annual top-40 (vectorized)
    print("\n--- Computing Annual Top-40 ---")
    annual_universe = compute_annual_top40(close_matrix, volume_matrix, all_dates)

    # 4. Run backtest
    results = run_backtest(close_matrix, open_matrix, spy_close, all_dates, annual_universe)

    # 5. Calculate metrics
    metrics = calculate_metrics(results)

    t_elapsed = time_module.time() - t_start

    # 6. Print results
    print("\n" + "=" * 80)
    print("RESULTS -- COMPASS v8.2 CHASSIS UPGRADE v1.0")
    print("=" * 80)

    print(f"\n{'-'*50}")
    print(f"  PERFORMANCE (net of slippage & realistic execution)")
    print(f"{'-'*50}")
    print(f"  Initial capital:      ${metrics['initial']:>15,.0f}")
    print(f"  Final value:          ${metrics['final_value']:>15,.2f}")
    print(f"  Total return:         {metrics['total_return']:>15.2%}")
    print(f"  CAGR:                 {metrics['cagr']:>15.2%}")
    print(f"  Volatility (annual):  {metrics['volatility']:>15.2%}")

    print(f"\n{'-'*50}")
    print(f"  RISK-ADJUSTED")
    print(f"{'-'*50}")
    print(f"  Sharpe ratio:         {metrics['sharpe']:>15.2f}")
    print(f"  Sortino ratio:        {metrics['sortino']:>15.2f}")
    print(f"  Calmar ratio:         {metrics['calmar']:>15.2f}")
    print(f"  Max drawdown:         {metrics['max_drawdown']:>15.2%}")

    print(f"\n{'-'*50}")
    print(f"  TRADING")
    print(f"{'-'*50}")
    print(f"  Trades executed:      {metrics['trades']:>15,}")
    print(f"  Win rate:             {metrics['win_rate']:>15.2%}")
    print(f"  Avg P&L per trade:    ${metrics['avg_trade']:>15,.2f}")
    print(f"  Avg winner:           ${metrics['avg_winner']:>15,.2f}")
    print(f"  Avg loser:            ${metrics['avg_loser']:>15,.2f}")

    print(f"\n{'-'*50}")
    print(f"  EXIT REASONS")
    print(f"{'-'*50}")
    for reason, count in sorted(metrics['exit_reasons'].items(), key=lambda x: -x[1]):
        print(f"  {reason:25s}: {count:>6,} ({count/metrics['trades']*100:.1f}%)")

    print(f"\n{'-'*50}")
    print(f"  RISK MANAGEMENT")
    print(f"{'-'*50}")
    print(f"  Stop loss events:     {metrics['stop_events']:>15,}")
    print(f"  Days in protection:   {metrics['protection_days']:>15,} ({metrics['protection_pct']:.1f}%)")
    print(f"  Risk-off days:        {metrics['risk_off_pct']:>14.1f}%")

    print(f"\n{'-'*50}")
    print(f"  CHASSIS METRICS (new)")
    print(f"{'-'*50}")
    print(f"  Total slippage cost:  ${metrics['total_slippage_cost']:>15,.0f}")
    print(f"  Slippage per trade:   ${metrics['total_slippage_cost']/max(metrics['trades'],1):>15,.2f}")
    print(f"  Slippage drag (est):  {metrics['total_slippage_cost']/metrics['final_value']*100:>14.2f}%")
    print(f"  Execution model:      {'Open[T+1] + ' + str(SLIPPAGE_BPS) + 'bps' if USE_NEXT_DAY_OPEN else 'Close[T]':>15s}")
    print(f"  Cash yield model:     {'Historical T-Bill' if USE_TBILL_COLLATERAL else 'Flat 3.5%':>15s}")
    print(f"  Backtest time:        {t_elapsed:>14.1f}s")

    # 7. Comparison vs original
    print(f"\n{'-'*50}")
    print(f"  COMPARISON vs ORIGINAL v8.2")
    print(f"{'-'*50}")
    ORIG_CAGR = 0.1695
    ORIG_SHARPE = 0.815
    ORIG_MAXDD = -0.284
    ORIG_FINAL = 5_910_000
    print(f"  {'Metric':<25} {'Original':>12} {'Chassis+':>12} {'Delta':>12}")
    print(f"  {'-'*55}")
    print(f"  {'CAGR':<25} {ORIG_CAGR:>11.2%} {metrics['cagr']:>11.2%} {metrics['cagr']-ORIG_CAGR:>+11.2%}")
    print(f"  {'Sharpe':<25} {ORIG_SHARPE:>12.3f} {metrics['sharpe']:>12.3f} {metrics['sharpe']-ORIG_SHARPE:>+12.3f}")
    print(f"  {'Max DD':<25} {ORIG_MAXDD:>11.1%} {metrics['max_drawdown']:>11.1%} {metrics['max_drawdown']-ORIG_MAXDD:>+11.1%}")
    print(f"  {'Final Value':<25} ${ORIG_FINAL:>11,.0f} ${metrics['final_value']:>11,.0f} ${metrics['final_value']-ORIG_FINAL:>+11,.0f}")

    # 8. Save results
    os.makedirs('backtests', exist_ok=True)
    results['portfolio_values'].to_csv('backtests/v8_chassis_upgrade_daily.csv', index=False)
    if len(results['trades']) > 0:
        results['trades'].to_csv('backtests/v8_chassis_upgrade_trades.csv', index=False)

    print(f"\n  Results saved:")
    print(f"    backtests/v8_chassis_upgrade_daily.csv")
    print(f"    backtests/v8_chassis_upgrade_trades.csv")

    print("\n" + "=" * 80)
    print("CHASSIS UPGRADE BACKTEST COMPLETE")
    print("=" * 80)
