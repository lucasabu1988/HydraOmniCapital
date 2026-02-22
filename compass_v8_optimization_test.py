"""
COMPASS v8.2 Optimization Backtest
===================================
Tests 4 independent improvements against the v8.2 baseline:
  A1: Dual SMA Crossover regime (SPY>SMA200 AND SMA50>SMA200)
  A2: VIX Override regime (VIX>30 forces RISK_OFF)
  B:  Risk-Adjusted Momentum (score / realized_vol)
  C:  Momentum Breadth Pre-Filter (only stocks with positive 200d return)

Each variant changes EXACTLY ONE function. Results compared in a table.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
from typing import Dict, List, Tuple, Optional, Callable
import warnings
import time
warnings.filterwarnings('ignore')

# ============================================================================
# PARAMETERS (identical to v8.2 production)
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
    """Download VIX data for variant A2"""
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
# BASE FUNCTIONS (identical to v8.2)
# ============================================================================

def compute_regime_base(spy_data: pd.DataFrame, **kwargs) -> pd.Series:
    """BASE: SPY > SMA200 with 3-day confirmation"""
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


def compute_momentum_base(price_data, tradeable, date, all_dates, date_idx, **kwargs):
    """BASE: score = momentum_90d - skip_5d"""
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


def get_tradeable_base(price_data, date, first_date, annual_universe, **kwargs):
    """BASE: top-40 with age check"""
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
# VARIANT A1: DUAL SMA CROSSOVER
# ============================================================================

def compute_regime_dual_sma(spy_data: pd.DataFrame, **kwargs) -> pd.Series:
    """A1: RISK_ON requires SPY > SMA200 AND SMA50 > SMA200"""
    spy_close = spy_data['Close']
    sma200 = spy_close.rolling(REGIME_SMA_PERIOD).mean()
    sma50 = spy_close.rolling(50).mean()

    # Combined: both conditions must be true
    raw_signal = (spy_close > sma200) & (sma50 > sma200)

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


# ============================================================================
# VARIANT A2: VIX OVERRIDE
# ============================================================================

def compute_regime_vix(spy_data: pd.DataFrame, vix_data: pd.DataFrame = None, **kwargs) -> pd.Series:
    """A2: Base regime + VIX > 30 forces RISK_OFF (no confirmation needed)"""
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

    # VIX override: if VIX > 30, force RISK_OFF regardless
    if vix_data is not None:
        vix_close = vix_data['Close']
        for date in regime.index:
            if date in vix_close.index:
                vix_val = vix_close.loc[date]
                if not pd.isna(vix_val) and vix_val > 30:
                    regime.loc[date] = False

    return regime


# ============================================================================
# VARIANT B: RISK-ADJUSTED MOMENTUM
# ============================================================================

def compute_momentum_risk_adj(price_data, tradeable, date, all_dates, date_idx, **kwargs):
    """B: score = (momentum_90d - skip_5d) / realized_vol_20d"""
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
        raw_score = momentum_90d - skip_5d

        # Risk adjustment: divide by 20d realized vol
        if sym_idx >= VOL_LOOKBACK + 1:
            returns = df['Close'].iloc[sym_idx - VOL_LOOKBACK:sym_idx + 1].pct_change().dropna()
            if len(returns) >= VOL_LOOKBACK - 2:
                realized_vol = returns.std() * np.sqrt(252)
                if realized_vol > 0.05:
                    scores[symbol] = raw_score / realized_vol
                else:
                    scores[symbol] = raw_score / 0.05
            else:
                scores[symbol] = raw_score
        else:
            scores[symbol] = raw_score
    return scores


# ============================================================================
# VARIANT C: MOMENTUM BREADTH PRE-FILTER
# ============================================================================

def get_tradeable_breadth(price_data, date, first_date, annual_universe, **kwargs):
    """C: Only stocks with positive 200d return are eligible"""
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
        if date > first_date + timedelta(days=30) and days_since_start < MIN_AGE_DAYS:
            continue

        # Breadth filter: require positive 200d return
        try:
            sym_idx = df.index.get_loc(date)
        except KeyError:
            tradeable.append(symbol)
            continue

        if sym_idx >= 200:
            close_today = df['Close'].iloc[sym_idx]
            close_200d = df['Close'].iloc[sym_idx - 200]
            if close_200d > 0 and close_today > 0:
                ret_200d = (close_today / close_200d) - 1.0
                if ret_200d < 0:
                    continue  # Skip stocks in downtrend

        tradeable.append(symbol)
    return tradeable


# ============================================================================
# SHARED FUNCTIONS (unchanged across all variants)
# ============================================================================

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


# ============================================================================
# PARAMETERIZED BACKTEST ENGINE
# ============================================================================

def run_backtest(price_data: Dict[str, pd.DataFrame],
                 annual_universe: Dict[int, List[str]],
                 spy_data: pd.DataFrame,
                 regime_fn: Callable = None,
                 score_fn: Callable = None,
                 tradeable_fn: Callable = None,
                 vix_data: pd.DataFrame = None,
                 label: str = "BASE") -> Dict:
    """
    Run COMPASS backtest with pluggable regime/score/tradeable functions.
    """
    if regime_fn is None:
        regime_fn = compute_regime_base
    if score_fn is None:
        score_fn = compute_momentum_base
    if tradeable_fn is None:
        tradeable_fn = get_tradeable_base

    print(f"\n{'='*60}")
    print(f"  RUNNING: {label}")
    print(f"{'='*60}")

    # Get all trading dates
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    # Compute regime (pass vix_data for A2 variant)
    regime = regime_fn(spy_data, vix_data=vix_data)

    # Portfolio state
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
    current_year = None

    for i, date in enumerate(all_dates):
        if date.year != current_year:
            current_year = date.year

        tradeable_symbols = tradeable_fn(price_data, date, first_date, annual_universe)

        # --- Calculate portfolio value ---
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        # --- Update peak ---
        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # --- Recovery ---
        if in_protection_mode and stop_loss_day_index is not None:
            days_since_stop = i - stop_loss_day_index
            is_regime_on = True
            if date in regime.index:
                is_regime_on = bool(regime.loc[date])
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
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    pos = positions[symbol]
                    proceeds = pos['shares'] * exit_price
                    commission = pos['shares'] * COMMISSION_PER_SHARE
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
            post_stop_base = cash

        # --- Regime ---
        is_risk_on = True
        if date in regime.index:
            is_risk_on = bool(regime.loc[date])
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # --- Max positions and leverage ---
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

        # --- Margin costs ---
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # --- Close positions ---
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue
            current_price = price_data[symbol].loc[date, 'Close']
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
                trades.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'exit_reason': exit_reason,
                    'pnl': pnl,
                    'return': pnl / (pos['entry_price'] * shares)
                })
                del positions[symbol]

        # --- Open new positions ---
        needed = max_positions - len(positions)

        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            scores = score_fn(price_data, tradeable_symbols, date, all_dates, i)
            available_scores = {s: sc for s, sc in scores.items() if s not in positions}

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

        # --- Record ---
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

        # Progress every 5 years
        if i % (252 * 5) == 0 and i > 0:
            print(f"  [{label}] Day {i}: ${portfolio_value:,.0f} | DD: {drawdown:.1%}")

    final_val = portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL
    print(f"  [{label}] DONE: ${final_val:,.0f} | Trades: {len(trades)} | Stops: {len(stop_events)}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': final_val,
        'annual_universe': annual_universe,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
        'label': label,
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
    avg_trade = trades_df['pnl'].mean() if len(trades_df) > 0 else 0

    exit_reasons = trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in trades_df.columns and len(trades_df) > 0 else {}

    protection_days = df['in_protection'].sum()
    protection_pct = protection_days / len(df) * 100
    risk_off_pct = results['risk_off_days'] / (results['risk_on_days'] + results['risk_off_days']) * 100

    df_annual = df['value'].resample('YE').last()
    annual_returns = df_annual.pct_change().dropna()

    pos_stop_count = exit_reasons.get('position_stop', 0)
    pos_stop_pct = pos_stop_count / len(trades_df) * 100 if len(trades_df) > 0 else 0

    return {
        'label': results['label'],
        'final_value': final_value,
        'cagr': cagr,
        'volatility': volatility,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'win_rate': win_rate,
        'avg_trade': avg_trade,
        'trades': len(trades_df),
        'stop_events': len(stop_df),
        'protection_days': int(protection_days),
        'protection_pct': protection_pct,
        'risk_off_pct': risk_off_pct,
        'best_year': annual_returns.max() if len(annual_returns) > 0 else 0,
        'worst_year': annual_returns.min() if len(annual_returns) > 0 else 0,
        'pos_stop_pct': pos_stop_pct,
        'exit_reasons': exit_reasons,
        'annual_returns': annual_returns,
    }


# ============================================================================
# COMPARISON OUTPUT
# ============================================================================

def print_comparison(all_metrics: List[Dict]):
    """Print Bloomberg-style comparison table"""
    print("\n")
    print("=" * 100)
    print("  COMPASS v8.2 OPTIMIZATION COMPARISON")
    print("=" * 100)

    labels = [m['label'] for m in all_metrics]
    col_w = 14

    # Header
    print(f"\n{'Metric':<22}", end='')
    for lbl in labels:
        short = lbl[:col_w-1]
        print(f"{short:>{col_w}}", end='')
    print()
    print("-" * (22 + col_w * len(labels)))

    # Rows
    rows = [
        ('Final Value',    'final_value',    lambda v: f"${v:,.0f}"),
        ('CAGR',           'cagr',           lambda v: f"{v:.2%}"),
        ('Sharpe',         'sharpe',         lambda v: f"{v:.3f}"),
        ('Sortino',        'sortino',        lambda v: f"{v:.3f}"),
        ('Max Drawdown',   'max_drawdown',   lambda v: f"{v:.1%}"),
        ('Calmar',         'calmar',         lambda v: f"{v:.3f}"),
        ('Volatility',     'volatility',     lambda v: f"{v:.2%}"),
        ('Win Rate',       'win_rate',       lambda v: f"{v:.1%}"),
        ('Avg Trade P&L',  'avg_trade',      lambda v: f"${v:,.0f}"),
        ('Total Trades',   'trades',         lambda v: f"{v:,}"),
        ('Stop Events',    'stop_events',    lambda v: f"{v}"),
        ('Protection Days','protection_days', lambda v: f"{v}"),
        ('RISK_OFF %',     'risk_off_pct',   lambda v: f"{v:.1f}%"),
        ('Pos Stop %',     'pos_stop_pct',   lambda v: f"{v:.1f}%"),
        ('Best Year',      'best_year',      lambda v: f"{v:.1%}"),
        ('Worst Year',     'worst_year',     lambda v: f"{v:.1%}"),
    ]

    for name, key, fmt_fn in rows:
        print(f"{name:<22}", end='')
        for m in all_metrics:
            val = m.get(key, 0)
            print(f"{fmt_fn(val):>{col_w}}", end='')
        print()

    # Delta row (vs BASE)
    base = all_metrics[0]
    print()
    print(f"{'d_Sharpe vs BASE':<22}", end='')
    for m in all_metrics:
        delta = m['sharpe'] - base['sharpe']
        s = f"{delta:+.3f}" if m != base else "---"
        print(f"{s:>{col_w}}", end='')
    print()

    print(f"{'d_CAGR vs BASE':<22}", end='')
    for m in all_metrics:
        delta = m['cagr'] - base['cagr']
        s = f"{delta:+.2%}" if m != base else "---"
        print(f"{s:>{col_w}}", end='')
    print()

    print(f"{'d_MaxDD vs BASE':<22}", end='')
    for m in all_metrics:
        delta = m['max_drawdown'] - base['max_drawdown']
        s = f"{delta:+.1%}" if m != base else "---"
        print(f"{s:>{col_w}}", end='')
    print()

    # Verdict
    print("\n" + "=" * 100)
    print("  VERDICT")
    print("=" * 100)

    for m in all_metrics[1:]:
        name = m['label']
        sharpe_ok = m['sharpe'] > base['sharpe']
        dd_ok = m['max_drawdown'] >= base['max_drawdown'] - 0.03  # within 3pp
        trades_ok = abs(m['trades'] - base['trades']) / base['trades'] < 0.20
        wr_ok = m['win_rate'] > 0.50

        verdict_parts = []
        if sharpe_ok:
            verdict_parts.append("Sharpe+")
        else:
            verdict_parts.append("Sharpe-")
        if dd_ok:
            verdict_parts.append("DD_OK")
        else:
            verdict_parts.append("DD_WORSE")
        if trades_ok:
            verdict_parts.append("Trades_OK")
        else:
            verdict_parts.append("Trades_DIFF")
        if wr_ok:
            verdict_parts.append("WR_OK")
        else:
            verdict_parts.append("WR_LOW")

        passed = sharpe_ok and dd_ok and trades_ok and wr_ok
        status = ">>> IMPROVEMENT <<<" if passed else "    NO IMPROVEMENT"
        print(f"  {name:<25} {' | '.join(verdict_parts):>40}  {status}")

    print("=" * 100)


def save_comparison_csv(all_metrics, all_results):
    """Save comparison table and daily CSVs"""
    os.makedirs('backtests', exist_ok=True)

    # Comparison table
    rows = []
    for m in all_metrics:
        rows.append({
            'variant': m['label'],
            'final_value': m['final_value'],
            'cagr': m['cagr'],
            'sharpe': m['sharpe'],
            'sortino': m['sortino'],
            'max_drawdown': m['max_drawdown'],
            'calmar': m['calmar'],
            'volatility': m['volatility'],
            'win_rate': m['win_rate'],
            'trades': m['trades'],
            'stop_events': m['stop_events'],
            'risk_off_pct': m['risk_off_pct'],
            'pos_stop_pct': m['pos_stop_pct'],
            'best_year': m['best_year'],
            'worst_year': m['worst_year'],
        })
    pd.DataFrame(rows).to_csv('backtests/v8_optimization_comparison.csv', index=False)
    print("\nSaved: backtests/v8_optimization_comparison.csv")

    # Individual daily CSVs
    for r in all_results:
        safe_label = r['label'].replace(' ', '_').replace(':', '').replace('/', '_').lower()
        fname = f"backtests/v8_opt_{safe_label}_daily.csv"
        r['portfolio_values'].to_csv(fname, index=False)
        print(f"Saved: {fname}")


def plot_equity_curves(all_results, all_metrics):
    """Plot equity curves for all variants"""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n[WARN] matplotlib not installed, skipping chart")
        return

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 10), gridspec_kw={'height_ratios': [3, 1]})
    fig.patch.set_facecolor('#0a0a0a')
    ax1.set_facecolor('#0a0a0a')
    ax2.set_facecolor('#0a0a0a')

    colors = ['#ff8c00', '#00ff41', '#4488ff', '#ff3333', '#00cccc']

    for idx, (r, m) in enumerate(zip(all_results, all_metrics)):
        df = r['portfolio_values']
        dates = pd.to_datetime(df['date'])
        values = df['value']
        dd = df['drawdown']
        color = colors[idx % len(colors)]
        lbl = f"{m['label']} (Sharpe: {m['sharpe']:.3f})"

        ax1.semilogy(dates, values, color=color, linewidth=1.2, label=lbl, alpha=0.9)
        ax2.fill_between(dates, dd * 100, 0, color=color, alpha=0.25)
        ax2.plot(dates, dd * 100, color=color, linewidth=0.5, alpha=0.7)

    ax1.set_title('COMPASS v8.2 Optimization — Equity Curves', color='#ff8c00',
                   fontsize=14, fontweight='bold', fontfamily='monospace')
    ax1.set_ylabel('Portfolio Value (log)', color='#888', fontfamily='monospace')
    ax1.legend(fontsize=9, loc='upper left', facecolor='#1a1a1a', edgecolor='#333',
               labelcolor='#ccc')
    ax1.grid(True, alpha=0.15, color='#333')
    ax1.tick_params(colors='#666')

    ax2.set_title('Drawdown', color='#ff8c00', fontsize=11, fontfamily='monospace')
    ax2.set_ylabel('Drawdown %', color='#888', fontfamily='monospace')
    ax2.set_xlabel('Date', color='#888', fontfamily='monospace')
    ax2.grid(True, alpha=0.15, color='#333')
    ax2.tick_params(colors='#666')

    for spine in ax1.spines.values():
        spine.set_color('#333')
    for spine in ax2.spines.values():
        spine.set_color('#333')

    plt.tight_layout()
    fname = 'backtests/v8_optimization_equity_curves.png'
    plt.savefig(fname, dpi=150, facecolor='#0a0a0a', bbox_inches='tight')
    plt.close()
    print(f"Saved: {fname}")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("  COMPASS v8.2 OPTIMIZATION BACKTEST")
    print("  4 variants vs BASE | 2000-2026")
    print("=" * 80)

    t_start = time.time()

    # 1. Load data (once, shared by all variants)
    price_data = download_broad_pool()
    print(f"Symbols loaded: {len(price_data)}")

    spy_data = download_spy()
    print(f"SPY data: {len(spy_data)} days")

    vix_data = download_vix()
    print(f"VIX data: {len(vix_data)} days")

    # 2. Compute annual top-40 (once)
    print("\nComputing annual top-40...")
    annual_universe = compute_annual_top40(price_data)

    # 3. Run all variants
    all_results = []
    all_metrics = []

    variants = [
        {
            'label': 'BASE v8.2',
            'regime_fn': compute_regime_base,
            'score_fn': compute_momentum_base,
            'tradeable_fn': get_tradeable_base,
        },
        {
            'label': 'A1: Dual SMA',
            'regime_fn': compute_regime_dual_sma,
            'score_fn': compute_momentum_base,
            'tradeable_fn': get_tradeable_base,
        },
        {
            'label': 'A2: VIX Override',
            'regime_fn': compute_regime_vix,
            'score_fn': compute_momentum_base,
            'tradeable_fn': get_tradeable_base,
        },
        {
            'label': 'B: Risk-Adj Mom',
            'regime_fn': compute_regime_base,
            'score_fn': compute_momentum_risk_adj,
            'tradeable_fn': get_tradeable_base,
        },
        {
            'label': 'C: Breadth Filter',
            'regime_fn': compute_regime_base,
            'score_fn': compute_momentum_base,
            'tradeable_fn': get_tradeable_breadth,
        },
    ]

    for v in variants:
        t0 = time.time()
        result = run_backtest(
            price_data, annual_universe, spy_data,
            regime_fn=v['regime_fn'],
            score_fn=v['score_fn'],
            tradeable_fn=v['tradeable_fn'],
            vix_data=vix_data,
            label=v['label'],
        )
        elapsed = time.time() - t0
        print(f"  Time: {elapsed:.1f}s")

        metrics = calculate_metrics(result)
        all_results.append(result)
        all_metrics.append(metrics)

    # 4. Compare
    print_comparison(all_metrics)

    # 5. Save outputs
    save_comparison_csv(all_metrics, all_results)
    plot_equity_curves(all_results, all_metrics)

    total_time = time.time() - t_start
    print(f"\nTotal time: {total_time:.0f}s ({total_time/60:.1f} min)")
    print("\nDONE.")
