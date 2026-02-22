"""
Test: Dynamic Recovery Signals vs Time-Based Baseline
=====================================================
Tests FIVE recovery variants after portfolio stop-loss (-15% DD):

A) BASELINE       -- Time-based: 63d->Stage2, 126d->Normal + regime gate (v8.2)
B) VIX_RECOVERY   -- Accelerate when VIX < SMA(20): halve wait times (32d/63d)
C) BREADTH_RECOV  -- Accelerate when >60% of universe above SMA(50)
D) COMBINED       -- Either VIX or Breadth signal can accelerate
E) AGGRESSIVE     -- Base times halved (32d/63d) + VIX can halve again (16d/32d)

All variants use identical COMPASS v8.2 engine (regime, stops, leverage, sizing)
and include cash yield (3% on idle cash). Only RECOVERY LOGIC differs.

Key question: Can we reduce 2,002 protection days (30.5%) without blowing up MaxDD?
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# CONSTANTS (matching COMPASS v8.2 exactly)
# ============================================================================
INITIAL_CAPITAL = 100_000
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
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.03  # 3% annual on positive cash (T-bill proxy)
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

# Dynamic Recovery parameters
VIX_SMA_PERIOD = 20         # VIX moving average for recovery signal
BREADTH_THRESHOLD = 0.60    # 60% of universe stocks above SMA(50)
BREADTH_SMA_PERIOD = 50     # SMA period for breadth calculation
AGGRESSIVE_STAGE_1_DAYS = 32   # Halved from 63
AGGRESSIVE_STAGE_2_DAYS = 63   # Halved from 126

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

# ============================================================================
# DATA FUNCTIONS
# ============================================================================

def download_broad_pool() -> Dict[str, pd.DataFrame]:
    cache_file = f'data_cache/broad_pool_{START_DATE}_{END_DATE}.pkl'
    if os.path.exists(cache_file):
        print("[Cache] Loading broad pool data...")
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception:
            print("[Cache] Failed to load, re-downloading...")

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


def download_spy() -> pd.DataFrame:
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


def download_vix() -> pd.DataFrame:
    cache_file = f'data_cache/VIX_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        print("[Cache] Loading VIX data...")
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    print("[Download] Downloading ^VIX...")
    df = yf.download('^VIX', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def compute_annual_top40(price_data: Dict[str, pd.DataFrame]) -> Dict[int, List[str]]:
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}
    for year in years:
        if year == years[0]:
            ranking_end = pd.Timestamp(f'{year}-02-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            ranking_start = pd.Timestamp(f'{year-1}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
        else:
            ranking_end = pd.Timestamp(f'{year}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            ranking_start = pd.Timestamp(f'{year-1}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)

        scores = {}
        for symbol, df in price_data.items():
            mask = (df.index >= ranking_start) & (df.index < ranking_end)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dollar_vol = (window['Close'] * window['Volume']).mean()
            scores[symbol] = dollar_vol

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_n = [s for s, _ in ranked[:TOP_N]]
        annual_universe[year] = top_n

    return annual_universe


# ============================================================================
# SIGNAL & REGIME FUNCTIONS
# ============================================================================

def compute_regime(spy_data: pd.DataFrame) -> pd.Series:
    spy_close = spy_data['Close']
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


def compute_momentum_scores(price_data, tradeable, date, date_idx):
    scores = {}
    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        needed = MOMENTUM_LOOKBACK + MOMENTUM_SKIP
        try:
            sym_idx = df.index.get_loc(date)
        except KeyError:
            continue
        if sym_idx < needed:
            continue

        close_today = df['Close'].iloc[sym_idx]
        close_skip = df['Close'].iloc[sym_idx - MOMENTUM_SKIP]
        close_lookback = df['Close'].iloc[sym_idx - MOMENTUM_LOOKBACK]

        if close_lookback <= 0 or close_skip <= 0 or close_today <= 0:
            continue

        momentum_90d = (close_skip / close_lookback) - 1.0
        skip_5d = (close_today / close_skip) - 1.0
        score = momentum_90d - skip_5d
        scores[symbol] = score

    return scores


def compute_volatility_weights(price_data, selected, date):
    vols = {}
    for symbol in selected:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        sym_idx = df.index.get_loc(date)
        if sym_idx < VOL_LOOKBACK + 1:
            continue
        returns = df['Close'].iloc[sym_idx - VOL_LOOKBACK:sym_idx + 1].pct_change().dropna()
        if len(returns) < VOL_LOOKBACK - 2:
            continue
        vol = returns.std() * np.sqrt(252)
        if vol > 0.01:
            vols[symbol] = vol

    if not vols:
        return {s: 1.0 / len(selected) for s in selected}

    raw_weights = {s: 1.0 / v for s, v in vols.items()}
    total = sum(raw_weights.values())
    return {s: w / total for s, w in raw_weights.items()}


def compute_dynamic_leverage(spy_data, date):
    if date not in spy_data.index:
        return 1.0
    idx = spy_data.index.get_loc(date)
    if idx < VOL_LOOKBACK + 1:
        return 1.0
    returns = spy_data['Close'].iloc[idx - VOL_LOOKBACK:idx + 1].pct_change().dropna()
    if len(returns) < VOL_LOOKBACK - 2:
        return 1.0
    realized_vol = returns.std() * np.sqrt(252)
    if realized_vol < 0.01:
        return LEVERAGE_MAX
    leverage = TARGET_VOL / realized_vol
    return max(LEVERAGE_MIN, min(LEVERAGE_MAX, leverage))


def get_tradeable_symbols(price_data, date, first_date, annual_universe):
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


# ============================================================================
# DYNAMIC RECOVERY SIGNALS (NEW)
# ============================================================================

def compute_vix_signal(vix_data: pd.DataFrame) -> pd.Series:
    """
    VIX recovery signal: True when VIX < SMA(20).
    Signals volatility is normalizing / institutional confidence returning.
    """
    vix_close = vix_data['Close']
    vix_sma = vix_close.rolling(VIX_SMA_PERIOD).mean()
    signal = vix_close < vix_sma
    # Fill NaN (first 20 days) with False (conservative)
    signal = signal.fillna(False)
    return signal


def compute_breadth_signal(price_data: Dict[str, pd.DataFrame],
                           annual_universe: Dict[int, List[str]],
                           all_dates: list) -> pd.Series:
    """
    Breadth recovery signal: fraction of universe stocks above SMA(50).
    Proxy for Zweig breadth thrust. Signal fires when >= 60%.
    Vectorized for performance.
    """
    # Collect all symbols ever in any universe
    all_symbols = set()
    for syms in annual_universe.values():
        all_symbols.update(syms)

    # Build close price matrix
    date_index = pd.DatetimeIndex(all_dates)
    close_df = pd.DataFrame(index=date_index)
    for symbol in all_symbols:
        if symbol in price_data:
            close_df[symbol] = price_data[symbol]['Close'].reindex(date_index)

    # 50-day SMA for all stocks
    sma50_df = close_df.rolling(BREADTH_SMA_PERIOD).mean()

    # Above SMA50 boolean matrix
    above_sma = close_df > sma50_df

    # For each date, compute fraction of that year's universe above SMA50
    breadth = pd.Series(index=date_index, dtype=float)
    for year, symbols in annual_universe.items():
        year_mask = date_index.year == year
        valid_symbols = [s for s in symbols if s in above_sma.columns]
        if valid_symbols:
            year_above = above_sma.loc[year_mask, valid_symbols]
            breadth.loc[year_mask] = year_above.mean(axis=1)
        else:
            breadth.loc[year_mask] = 0.0

    breadth = breadth.fillna(0.0)
    return breadth


# ============================================================================
# BACKTEST ENGINE WITH DYNAMIC RECOVERY VARIANTS
# ============================================================================

def run_backtest(price_data, annual_universe, spy_data,
                 variant='baseline',
                 vix_signal=None,
                 breadth_signal=None) -> Dict:
    """
    Run COMPASS backtest with variant-specific recovery modifications.

    Variants:
        'baseline'         - Time-based: 63d/126d + regime gate (v8.2)
        'vix_recovery'     - Accelerate when VIX < SMA(20)
        'breadth_recovery' - Accelerate when breadth >= 60%
        'combined'         - Either VIX or Breadth can accelerate
        'aggressive'       - Halved base times + VIX acceleration
    """

    use_vix = variant in ('vix_recovery', 'combined', 'aggressive')
    use_breadth = variant in ('breadth_recovery', 'combined')
    use_aggressive = variant in ('aggressive',)

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    regime = compute_regime(spy_data)

    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []

    peak_value = float(INITIAL_CAPITAL)
    in_protection_mode = False
    protection_stage = 0
    stop_loss_day_index = None
    post_stop_base = None

    risk_on_days = 0
    risk_off_days = 0
    total_cash_yield = 0.0
    total_turnover = 0.0

    # Recovery tracking
    recovery_events = []
    current_stop_date = None
    protection_day_count = 0

    for i, date in enumerate(all_dates):
        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        # --- Calculate portfolio value ---
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        # --- Update peak ---
        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # --- Recovery from protection mode (VARIANT-SPECIFIC) ---
        if in_protection_mode and stop_loss_day_index is not None:
            protection_day_count += 1
            days_since_stop = i - stop_loss_day_index
            is_regime_on = True
            if date in regime.index:
                is_regime_on = bool(regime.loc[date])

            # Check dynamic signals
            vix_ok = False
            if use_vix and vix_signal is not None and date in vix_signal.index:
                vix_ok = bool(vix_signal.loc[date])

            breadth_ok = False
            if use_breadth and breadth_signal is not None and date in breadth_signal.index:
                breadth_val = breadth_signal.loc[date]
                breadth_ok = breadth_val >= BREADTH_THRESHOLD

            can_accelerate = vix_ok or breadth_ok

            # Determine minimum days for each stage transition
            if use_aggressive:
                # Aggressive: halved base + VIX can halve again
                base_s1 = AGGRESSIVE_STAGE_1_DAYS  # 32
                base_s2 = AGGRESSIVE_STAGE_2_DAYS  # 63
                min_stage1 = base_s1 // 2 if vix_ok else base_s1  # 16 or 32
                min_stage2 = base_s2 // 2 if vix_ok else base_s2  # 32 or 63
            elif can_accelerate:
                # VIX/Breadth/Combined: halve times when signal fires
                min_stage1 = 32
                min_stage2 = 63
            else:
                # Baseline timing (or dynamic without signal firing)
                min_stage1 = RECOVERY_STAGE_1_DAYS  # 63
                min_stage2 = RECOVERY_STAGE_2_DAYS  # 126

            # Stage 1 -> Stage 2
            if protection_stage == 1 and days_since_stop >= min_stage1 and is_regime_on:
                protection_stage = 2
                print(f"  [RECOVERY S1] {date.strftime('%Y-%m-%d')}: Stage 2 | "
                      f"Days: {days_since_stop} | Value: ${portfolio_value:,.0f}")

            # Stage 2 -> Normal
            if protection_stage == 2 and days_since_stop >= min_stage2 and is_regime_on:
                in_protection_mode = False
                protection_stage = 0
                peak_value = portfolio_value
                stop_loss_day_index = None
                post_stop_base = None
                recovery_events.append({
                    'stop_date': current_stop_date,
                    'recovery_date': date,
                    'duration_days': days_since_stop,
                    'portfolio_at_recovery': portfolio_value,
                })
                print(f"  [RECOVERY S2] {date.strftime('%Y-%m-%d')}: Full recovery | "
                      f"Days: {days_since_stop} | Value: ${portfolio_value:,.0f}")

        # --- Drawdown ---
        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # --- Portfolio stop loss ---
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({'date': date, 'portfolio_value': portfolio_value, 'drawdown': drawdown})
            print(f"\n  [STOP LOSS] {date.strftime('%Y-%m-%d')}: DD {drawdown:.1%} | Value: ${portfolio_value:,.0f}")

            for symbol in list(positions.keys()):
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    pos = positions[symbol]
                    proceeds = pos['shares'] * exit_price
                    commission = pos['shares'] * COMMISSION_PER_SHARE
                    cash += proceeds - commission
                    pnl = (exit_price - pos['entry_price']) * pos['shares'] - commission
                    total_turnover += abs(proceeds)
                    trades.append({
                        'symbol': symbol, 'entry_date': pos['entry_date'],
                        'exit_date': date, 'exit_reason': 'portfolio_stop',
                        'pnl': pnl, 'return': pnl / (pos['entry_price'] * pos['shares'])
                    })
                del positions[symbol]

            in_protection_mode = True
            protection_stage = 1
            stop_loss_day_index = i
            post_stop_base = cash
            current_stop_date = date

        # --- Regime ---
        is_risk_on = True
        if date in regime.index:
            is_risk_on = bool(regime.loc[date])
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # --- Determine max positions and leverage ---
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
            current_leverage = compute_dynamic_leverage(spy_data, date)

        # --- Daily margin cost ---
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # --- Cash yield (always on -- T-bill on idle cash) ---
        if cash > 0:
            daily_yield = cash * (CASH_YIELD_RATE / 252)
            cash += daily_yield
            total_cash_yield += daily_yield

        # --- Compute momentum scores ---
        daily_scores = None
        if len(positions) < max_positions:
            daily_scores = compute_momentum_scores(price_data, tradeable_symbols, date, i)

        # --- Close positions (standard v8.2 5-day hold + stops) ---
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue

            current_price = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            # 1. Hold time (5 days)
            days_held = i - pos['entry_idx']
            if days_held >= HOLD_DAYS:
                exit_reason = 'hold_expired'

            # 2. Position stop loss (-8%)
            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            if pos_return <= POSITION_STOP_LOSS:
                exit_reason = 'position_stop'

            # 3. Trailing stop
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                trailing_level = pos['high_price'] * (1 - TRAILING_STOP_PCT)
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            # 4. Stock no longer in top-40
            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'

            # 5. Excess positions
            if exit_reason is None and len(positions) > max_positions:
                pos_returns = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        cp = price_data[s].loc[date, 'Close']
                        pos_returns[s] = (cp - p['entry_price']) / p['entry_price']
                worst = min(pos_returns, key=pos_returns.get)
                if symbol == worst:
                    exit_reason = 'regime_reduce'

            if exit_reason:
                shares = pos['shares']
                proceeds = shares * current_price
                commission = shares * COMMISSION_PER_SHARE
                cash += proceeds - commission
                pnl = (current_price - pos['entry_price']) * shares - commission
                total_turnover += abs(proceeds)
                trades.append({
                    'symbol': symbol, 'entry_date': pos['entry_date'],
                    'exit_date': date, 'exit_reason': exit_reason,
                    'pnl': pnl, 'return': pnl / (pos['entry_price'] * shares)
                })
                del positions[symbol]

        # --- Open new positions ---
        needed = max_positions - len(positions)

        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            if daily_scores is None:
                daily_scores = compute_momentum_scores(price_data, tradeable_symbols, date, i)

            available_scores = {s: sc for s, sc in daily_scores.items() if s not in positions}

            if len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]

                weights = compute_volatility_weights(price_data, selected, date)
                effective_capital = cash * current_leverage * 0.95

                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue
                    entry_price = price_data[symbol].loc[date, 'Close']
                    if entry_price <= 0:
                        continue

                    weight = weights.get(symbol, 1.0 / len(selected))
                    position_value = effective_capital * weight
                    max_per_position = cash * 0.40
                    position_value = min(position_value, max_per_position)

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
                        total_turnover += abs(cost)

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
            'protection_stage': protection_stage,
        })

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
        'total_cash_yield': total_cash_yield,
        'total_turnover': total_turnover,
        'recovery_events': recovery_events,
        'total_protection_days': protection_day_count,
    }


# ============================================================================
# METRICS
# ============================================================================

def calculate_metrics(results: Dict) -> Dict:
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']
    stop_df = results['stop_events']

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
    total_trades = len(trades_df)

    exit_reasons = trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in trades_df.columns and len(trades_df) > 0 else {}

    # Annual returns
    df_annual = df['value'].resample('YE').last()
    annual_returns = df_annual.pct_change().dropna()

    # Average holding period
    if len(trades_df) > 0 and 'entry_date' in trades_df.columns and 'exit_date' in trades_df.columns:
        trades_df_copy = trades_df.copy()
        trades_df_copy['entry_date'] = pd.to_datetime(trades_df_copy['entry_date'])
        trades_df_copy['exit_date'] = pd.to_datetime(trades_df_copy['exit_date'])
        avg_hold_days = (trades_df_copy['exit_date'] - trades_df_copy['entry_date']).dt.days.mean()
    else:
        avg_hold_days = 0

    # Turnover ratio
    avg_portfolio = df['value'].mean()
    turnover_ratio = results.get('total_turnover', 0) / avg_portfolio / years if avg_portfolio > 0 and years > 0 else 0

    # Recovery-specific metrics
    recovery_events = results.get('recovery_events', [])
    total_protection_days = results.get('total_protection_days', 0)
    protection_pct = total_protection_days / len(df) * 100 if len(df) > 0 else 0

    if recovery_events:
        durations = [e['duration_days'] for e in recovery_events]
        avg_recovery = np.mean(durations)
        fastest_recovery = min(durations)
        slowest_recovery = max(durations)
    else:
        avg_recovery = 0
        fastest_recovery = 0
        slowest_recovery = 0

    return {
        'final_value': final_value,
        'cagr': cagr,
        'volatility': volatility,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'win_rate': win_rate,
        'total_trades': total_trades,
        'trades_per_year': total_trades / years if years > 0 else 0,
        'avg_hold_days': avg_hold_days,
        'exit_reasons': exit_reasons,
        'stop_events': len(stop_df),
        'best_year': annual_returns.max() if len(annual_returns) > 0 else 0,
        'worst_year': annual_returns.min() if len(annual_returns) > 0 else 0,
        'positive_years': int((annual_returns > 0).sum()) if len(annual_returns) > 0 else 0,
        'total_years': len(annual_returns),
        'total_cash_yield': results.get('total_cash_yield', 0),
        'turnover_ratio': turnover_ratio,
        # Recovery-specific
        'total_protection_days': total_protection_days,
        'protection_pct': protection_pct,
        'num_recoveries': len(recovery_events),
        'avg_recovery_duration': avg_recovery,
        'fastest_recovery': fastest_recovery,
        'slowest_recovery': slowest_recovery,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("DYNAMIC RECOVERY TEST -- VIX + Breadth Signals vs Time-Based Baseline")
    print("=" * 80)
    print(f"VIX signal: Close < SMA({VIX_SMA_PERIOD})")
    print(f"Breadth signal: >{BREADTH_THRESHOLD:.0%} of universe above SMA({BREADTH_SMA_PERIOD})")
    print(f"Aggressive timing: {AGGRESSIVE_STAGE_1_DAYS}d/{AGGRESSIVE_STAGE_2_DAYS}d base")
    print(f"Cash yield: {CASH_YIELD_RATE:.1%} annual (all variants)")
    print()

    # 1. Load data
    price_data = download_broad_pool()
    print(f"Symbols available: {len(price_data)}")

    spy_data = download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    vix_data = download_vix()
    print(f"VIX data: {len(vix_data)} trading days")

    # 2. Annual top-40
    print("\nComputing annual top-40...")
    annual_universe = compute_annual_top40(price_data)

    # 3. Precompute signals
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))

    print("Computing VIX signal...")
    vix_signal = compute_vix_signal(vix_data)
    vix_true = vix_signal.sum()
    vix_total = len(vix_signal)
    print(f"  VIX < SMA20: {vix_true}/{vix_total} days ({vix_true/vix_total:.1%})")

    print("Computing breadth signal...")
    breadth_signal = compute_breadth_signal(price_data, annual_universe, all_dates)
    breadth_true = (breadth_signal >= BREADTH_THRESHOLD).sum()
    breadth_total = len(breadth_signal)
    print(f"  Breadth >= {BREADTH_THRESHOLD:.0%}: {breadth_true}/{breadth_total} days ({breadth_true/breadth_total:.1%})")

    # 4. Define variants
    VARIANTS = [
        ('A) BASELINE (v8.2)',         'baseline'),
        ('B) VIX_RECOVERY',            'vix_recovery'),
        ('C) BREADTH_RECOVERY',        'breadth_recovery'),
        ('D) COMBINED (VIX+Breadth)',  'combined'),
        ('E) AGGRESSIVE (halved+VIX)', 'aggressive'),
    ]

    # 5. Run all variants
    all_results = {}
    all_metrics = {}

    for label, variant in VARIANTS:
        print(f"\n{'='*60}")
        print(f"Running: {label}")
        print(f"{'='*60}")

        results = run_backtest(
            price_data, annual_universe, spy_data,
            variant=variant,
            vix_signal=vix_signal,
            breadth_signal=breadth_signal,
        )
        metrics = calculate_metrics(results)
        all_results[label] = results
        all_metrics[label] = metrics

        print(f"  Final: ${metrics['final_value']:,.0f} | CAGR: {metrics['cagr']:.2%} | "
              f"Sharpe: {metrics['sharpe']:.3f} | MaxDD: {metrics['max_drawdown']:.1%} | "
              f"Protection: {metrics['total_protection_days']}d ({metrics['protection_pct']:.1f}%)")

    # 6. Performance comparison table
    print("\n\n" + "=" * 110)
    print("PERFORMANCE COMPARISON")
    print("=" * 110)

    header = f"{'Metric':<22}"
    for label, _ in VARIANTS:
        short = label.split(')')[0] + ')'
        header += f" {short:>16}"
    print(header)
    print("-" * 110)

    metric_rows = [
        ('Final Value',     'final_value',    '${:>12,.0f}'),
        ('CAGR',            'cagr',           '{:>12.2%}'),
        ('Sharpe',          'sharpe',         '{:>12.3f}'),
        ('Sortino',         'sortino',        '{:>12.3f}'),
        ('Calmar',          'calmar',         '{:>12.3f}'),
        ('Max Drawdown',    'max_drawdown',   '{:>12.1%}'),
        ('Volatility',      'volatility',     '{:>12.1%}'),
        ('Win Rate',        'win_rate',       '{:>12.1%}'),
        ('Total Trades',    'total_trades',   '{:>12,}'),
        ('Avg Hold (days)', 'avg_hold_days',  '{:>12.1f}'),
        ('Best Year',       'best_year',      '{:>12.1%}'),
        ('Worst Year',      'worst_year',     '{:>12.1%}'),
        ('Cash Yield Total','total_cash_yield','${:>11,.0f}'),
    ]

    for row_label, key, fmt in metric_rows:
        row = f"{row_label:<22}"
        for label, _ in VARIANTS:
            val = all_metrics[label].get(key, 0)
            try:
                row += f" {fmt.format(val):>16}"
            except (ValueError, TypeError):
                row += f" {str(val):>16}"
        print(row)

    # 7. Recovery analysis table
    print(f"\n{'='*110}")
    print("RECOVERY ANALYSIS")
    print(f"{'='*110}")

    header = f"{'Metric':<22}"
    for label, _ in VARIANTS:
        short = label.split(')')[0] + ')'
        header += f" {short:>16}"
    print(header)
    print("-" * 110)

    recovery_rows = [
        ('Stop Events',         'stop_events',          '{:>12}'),
        ('Recoveries',          'num_recoveries',       '{:>12}'),
        ('Protection Days',     'total_protection_days', '{:>12,}'),
        ('% Time Protected',    'protection_pct',       '{:>11.1f}%'),
        ('Avg Recovery (days)', 'avg_recovery_duration', '{:>12.0f}'),
        ('Fastest Recovery',    'fastest_recovery',     '{:>12}'),
        ('Slowest Recovery',    'slowest_recovery',     '{:>12}'),
    ]

    for row_label, key, fmt in recovery_rows:
        row = f"{row_label:<22}"
        for label, _ in VARIANTS:
            val = all_metrics[label].get(key, 0)
            try:
                row += f" {fmt.format(val):>16}"
            except (ValueError, TypeError):
                row += f" {str(val):>16}"
        print(row)

    # 8. Verdict
    print(f"\n{'='*110}")
    print("VERDICT")
    print(f"{'='*110}")

    baseline_cagr = all_metrics[VARIANTS[0][0]]['cagr']
    baseline_dd = all_metrics[VARIANTS[0][0]]['max_drawdown']
    baseline_prot = all_metrics[VARIANTS[0][0]]['total_protection_days']

    for label, _ in VARIANTS[1:]:
        m = all_metrics[label]
        cagr_diff = m['cagr'] - baseline_cagr
        dd_diff = m['max_drawdown'] - baseline_dd
        prot_diff = m['total_protection_days'] - baseline_prot

        if m['cagr'] > baseline_cagr and m['max_drawdown'] >= baseline_dd - 0.02:
            verdict = "WINNER -- Higher CAGR, acceptable MaxDD"
        elif m['cagr'] > baseline_cagr and m['max_drawdown'] < baseline_dd - 0.02:
            verdict = "REJECT -- Higher CAGR but MaxDD too much worse (>2%)"
        elif m['cagr'] <= baseline_cagr and m['max_drawdown'] >= baseline_dd:
            verdict = "LOSE -- Lower CAGR"
        else:
            verdict = "LOSE -- Lower CAGR AND worse MaxDD"

        print(f"\n  {label}")
        print(f"    CAGR delta:       {cagr_diff:+.2%}")
        print(f"    MaxDD delta:      {dd_diff:+.1%} ({'better' if dd_diff > 0 else 'worse'})")
        print(f"    Protection delta: {prot_diff:+,} days")
        print(f"    Verdict:          {verdict}")

    # 9. Save daily CSVs
    os.makedirs('backtests', exist_ok=True)
    for label, variant in VARIANTS:
        safe_name = variant.replace(' ', '_')
        all_results[label]['portfolio_values'].to_csv(
            f'backtests/dynrecov_{safe_name}_daily.csv', index=False)

    print(f"\nDaily CSVs saved to backtests/dynrecov_*.csv")
    print("\n" + "=" * 80)
    print("DYNAMIC RECOVERY TEST COMPLETE")
    print("=" * 80)
