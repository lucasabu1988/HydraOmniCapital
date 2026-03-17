#!/usr/bin/env python3
"""
================================================================================
OMNICAPITAL v8 COMPASS -- TIINGO DATA SOURCE
================================================================================
IDENTICAL algorithm to omnicapital_v8_compass.py.
ONLY difference: data downloaded from Tiingo API instead of yfinance.

Purpose: Cross-validate COMPASS results against an independent data provider.
Tiingo provides split/dividend-adjusted OHLCV data (adjClose, adjOpen, etc.)
which may differ slightly from yfinance's adjustment methodology.

This allows us to verify:
1. Whether COMPASS results are data-source-dependent
2. If yfinance adjustments introduced any bias
3. How robust the algorithm is to minor price differences
================================================================================
"""

import pandas as pd
import numpy as np
import requests
import pickle
import os
import time as time_module
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# TIINGO CONFIGURATION
# =============================================================================

TIINGO_API_KEY = os.environ.get('TIINGO_API_KEY', '')
TIINGO_BASE_URL = 'https://api.tiingo.com/tiingo/daily'

# =============================================================================
# COMPASS PARAMETERS -- IDENTICAL TO PRODUCTION (DO NOT MODIFY)
# =============================================================================

# Universe
TOP_N = 40
MIN_AGE_DAYS = 63

# Signal
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
MIN_MOMENTUM_STOCKS = 20

# Regime
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3

# Positions
NUM_POSITIONS = 5
NUM_POSITIONS_RISK_OFF = 2
HOLD_DAYS = 5

# Position-level risk
POSITION_STOP_LOSS = -0.08
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03

# Portfolio-level risk
PORTFOLIO_STOP_LOSS = -0.15

# Recovery
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126

# Leverage & Vol targeting
TARGET_VOL = 0.15
LEVERAGE_MIN = 0.3
LEVERAGE_MAX = 1.0  # No leverage in production
VOL_LOOKBACK = 20

# Costs
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.035

# Data
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

# Broad pool -- IDENTICAL to COMPASS
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


# =============================================================================
# TIINGO DATA FUNCTIONS
# =============================================================================

def _tiingo_download_symbol(symbol: str, start: str, end: str,
                            max_retries: int = 3) -> Optional[pd.DataFrame]:
    """Download OHLCV data for one symbol from Tiingo with rate-limit handling."""
    url = f'{TIINGO_BASE_URL}/{symbol}/prices'
    params = {
        'startDate': start,
        'endDate': end,
        'token': TIINGO_API_KEY,
    }
    for attempt in range(max_retries):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                # Rate limited -- wait and retry
                wait = 30 * (attempt + 1)
                print(f"    [Rate limit] {symbol}: waiting {wait}s (attempt {attempt+1})...")
                time_module.sleep(wait)
                continue
            if r.status_code != 200:
                return None
            data = r.json()
            if not data:
                return None

            df = pd.DataFrame(data)
            df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
            df = df.set_index('date')

            # Map Tiingo adjusted columns to COMPASS expected format
            result = pd.DataFrame({
                'Open': df['adjOpen'],
                'High': df['adjHigh'],
                'Low': df['adjLow'],
                'Close': df['adjClose'],
                'Volume': df['adjVolume'],
            }, index=df.index)

            return result if len(result) > 100 else None
        except Exception:
            return None
    return None


def download_broad_pool_tiingo() -> Dict[str, pd.DataFrame]:
    """Download/load cached TIINGO data for the broad pool."""
    cache_file = f'data_cache/tiingo_broad_pool_{START_DATE}_{END_DATE}.pkl'

    if os.path.exists(cache_file):
        print("[Cache] Loading Tiingo broad pool data...")
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception:
            print("[Cache] Failed to load, re-downloading...")

    # Try loading partial cache first
    partial_cache = f'data_cache/tiingo_partial_{START_DATE}_{END_DATE}.pkl'
    already_downloaded = {}
    if os.path.exists(partial_cache):
        print("[Cache] Loading partial Tiingo download...")
        try:
            with open(partial_cache, 'rb') as f:
                already_downloaded = pickle.load(f)
            print(f"  Found {len(already_downloaded)} previously downloaded symbols")
        except Exception:
            already_downloaded = {}

    remaining = [s for s in BROAD_POOL if s not in already_downloaded]
    # Prioritize symbols most likely to appear in top-40 (skip obscure ones)
    # Download ALL from BROAD_POOL since we don't know top-40 without prior-year data
    print(f"[Tiingo] Downloading {len(remaining)} remaining symbols "
          f"({len(already_downloaded)} cached)...")

    data = dict(already_downloaded)
    failed = []

    for i, symbol in enumerate(remaining):
        df = _tiingo_download_symbol(symbol, START_DATE, END_DATE)
        if df is not None:
            data[symbol] = df
        else:
            failed.append(symbol)

        # Save partial progress after every successful download
        if df is not None:
            with open(partial_cache, 'wb') as f:
                pickle.dump(data, f)

        if (i + 1) % 10 == 0:
            print(f"  [{i+1}/{len(remaining)}] Downloaded {len(data)} symbols, "
                  f"{len(failed)} failed...")

        # Rate limiting: 3s between requests to stay well under 500/hr (~1200/hr max)
        time_module.sleep(3)

    print(f"[Tiingo] {len(data)} symbols valid, {len(failed)} failed")
    if failed:
        print(f"  Failed: {failed}")

    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)

    return data


def download_spy_tiingo() -> pd.DataFrame:
    """Download SPY data from Tiingo."""
    cache_file = f'data_cache/tiingo_SPY_{START_DATE}_{END_DATE}.pkl'

    if os.path.exists(cache_file):
        print("[Cache] Loading Tiingo SPY data...")
        with open(cache_file, 'rb') as f:
            return pickle.load(f)

    print("[Tiingo] Downloading SPY...")
    df = _tiingo_download_symbol('SPY', START_DATE, END_DATE, max_retries=5)
    if df is None:
        raise RuntimeError("Failed to download SPY from Tiingo -- rate limit? Try again later.")

    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(df, f)
    return df


def compute_annual_top40(price_data: Dict[str, pd.DataFrame]) -> Dict[int, List[str]]:
    """For each year, compute top-40 by avg daily dollar volume (prior year)."""
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
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
            mask = (df.index >= ranking_start) & (df.index < ranking_end)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dollar_vol = (window['Close'] * window['Volume']).mean()
            scores[symbol] = dollar_vol

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


# =============================================================================
# SIGNAL & REGIME FUNCTIONS -- IDENTICAL TO COMPASS
# =============================================================================

def compute_regime(spy_data: pd.DataFrame) -> pd.Series:
    """Compute market regime based on SPY vs SMA200."""
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


def compute_momentum_scores(price_data, tradeable, date, all_dates, date_idx):
    """Compute cross-sectional momentum score for each stock."""
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
    """Compute inverse-volatility weights."""
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
    """Compute leverage via volatility targeting."""
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


# =============================================================================
# BACKTEST -- IDENTICAL TO COMPASS
# =============================================================================

def get_tradeable_symbols(price_data, date, first_date, annual_universe):
    """Return tradeable symbols from top-40 for that year."""
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


def run_backtest(price_data, annual_universe, spy_data):
    """Run COMPASS backtest -- IDENTICAL logic to production."""

    print("\n" + "=" * 80)
    print("RUNNING COMPASS BACKTEST (TIINGO DATA)")
    print("=" * 80)

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    print("\nComputing market regime (SPY vs SMA200)...")
    regime = compute_regime(spy_data)

    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")

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

        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        # --- Portfolio value ---
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        # --- Peak ---
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
                print(f"  [RECOVERY S1] {date.strftime('%Y-%m-%d')}: Stage 2 | Value: ${portfolio_value:,.0f}")

            if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and is_regime_on:
                in_protection_mode = False
                protection_stage = 0
                peak_value = portfolio_value
                stop_loss_day_index = None
                post_stop_base = None
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

        # --- Daily costs ---
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # --- Cash yield ---
        if cash > 0:
            cash += cash * (CASH_YIELD_RATE / 252)

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
            scores = compute_momentum_scores(price_data, tradeable_symbols, date, all_dates, i)
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

        # --- Daily snapshot ---
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

        if i % 252 == 0 and i > 0:
            year_num = i // 252
            regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
            prot_str = f" [PROTECTION S{protection_stage}]" if in_protection_mode else ""
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | DD: {drawdown:.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_str}{prot_str} | "
                  f"Pos: {len(positions)}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'annual_universe': annual_universe,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
    }


# =============================================================================
# METRICS -- IDENTICAL TO COMPASS
# =============================================================================

def calculate_metrics(results):
    """Calculate performance metrics."""
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
    avg_winner = trades_df.loc[trades_df['pnl'] > 0, 'pnl'].mean() if len(trades_df) > 0 and (trades_df['pnl'] > 0).any() else 0
    avg_loser = trades_df.loc[trades_df['pnl'] < 0, 'pnl'].mean() if len(trades_df) > 0 and (trades_df['pnl'] < 0).any() else 0

    exit_reasons = trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in trades_df.columns and len(trades_df) > 0 else {}

    protection_days = df['in_protection'].sum()
    protection_pct = protection_days / len(df) * 100
    risk_off_pct = results['risk_off_days'] / (results['risk_on_days'] + results['risk_off_days']) * 100

    df_annual = df['value'].resample('YE').last()
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
    }


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("OMNICAPITAL v8 COMPASS -- TIINGO DATA SOURCE")
    print("Cross-validation against independent data provider")
    print("=" * 80)
    print(f"\nBroad pool: {len(BROAD_POOL)} stocks | Top-{TOP_N} annual rotation")
    print(f"Signal: Momentum {MOMENTUM_LOOKBACK}d (skip {MOMENTUM_SKIP}d) + Inverse Vol sizing")
    print(f"Regime: SPY SMA{REGIME_SMA_PERIOD} | Vol target: {TARGET_VOL:.0%}")
    print(f"Hold: {HOLD_DAYS}d | Pos stop: {POSITION_STOP_LOSS:.0%} | Port stop: {PORTFOLIO_STOP_LOSS:.0%}")
    print()

    # 1. Download from Tiingo
    price_data = download_broad_pool_tiingo()
    print(f"\nSymbols available: {len(price_data)}")

    spy_data = download_spy_tiingo()
    print(f"SPY data: {len(spy_data)} trading days")

    # 2. Annual top-40
    print("\n--- Computing Annual Top-40 (Tiingo data) ---")
    annual_universe = compute_annual_top40(price_data)

    # 3. Run backtest
    results = run_backtest(price_data, annual_universe, spy_data)

    # 4. Calculate metrics
    metrics = calculate_metrics(results)

    # 5. Print results
    print("\n" + "=" * 80)
    print("RESULTS - COMPASS v8 (TIINGO DATA)")
    print("=" * 80)

    print(f"\n--- Performance ---")
    print(f"Initial capital:        ${metrics['initial']:>15,.0f}")
    print(f"Final value:            ${metrics['final_value']:>15,.2f}")
    print(f"Total return:           {metrics['total_return']:>15.2%}")
    print(f"CAGR:                   {metrics['cagr']:>15.2%}")
    print(f"Volatility (annual):    {metrics['volatility']:>15.2%}")

    print(f"\n--- Risk-Adjusted ---")
    print(f"Sharpe ratio:           {metrics['sharpe']:>15.2f}")
    print(f"Sortino ratio:          {metrics['sortino']:>15.2f}")
    print(f"Calmar ratio:           {metrics['calmar']:>15.2f}")
    print(f"Max drawdown:           {metrics['max_drawdown']:>15.2%}")

    print(f"\n--- Trading ---")
    print(f"Trades executed:        {metrics['trades']:>15,}")
    print(f"Win rate:               {metrics['win_rate']:>15.2%}")
    print(f"Avg P&L per trade:      ${metrics['avg_trade']:>15,.2f}")
    print(f"Avg winner:             ${metrics['avg_winner']:>15,.2f}")
    print(f"Avg loser:              ${metrics['avg_loser']:>15,.2f}")

    print(f"\n--- Exit Reasons ---")
    for reason, count in sorted(metrics['exit_reasons'].items(), key=lambda x: -x[1]):
        print(f"  {reason:25s}: {count:>6,} ({count/metrics['trades']*100:.1f}%)")

    print(f"\n--- Risk Management ---")
    print(f"Stop loss events:       {metrics['stop_events']:>15,}")
    print(f"Days in protection:     {metrics['protection_days']:>15,} ({metrics['protection_pct']:.1f}%)")
    print(f"Risk-off days:          {metrics['risk_off_pct']:>14.1f}%")

    print(f"\n--- Annual Returns ---")
    if len(metrics['annual_returns']) > 0:
        print(f"Best year:              {metrics['best_year']:>15.2%}")
        print(f"Worst year:             {metrics['worst_year']:>15.2%}")
        print(f"Positive years:         {(metrics['annual_returns'] > 0).sum()}/{len(metrics['annual_returns'])}")

    # 6. CROSS-VALIDATION: Tiingo vs yfinance
    print("\n" + "=" * 80)
    print("CROSS-VALIDATION: TIINGO vs YFINANCE")
    print("=" * 80)
    print(f"\n  {'METRIC':<25} {'TIINGO':>14} {'YFINANCE':>14} {'DELTA':>12}")
    print(f"  {'-' * 65}")

    yf_cagr = 0.1766
    yf_sharpe = 0.85
    yf_maxdd = -0.275
    yf_final = 6_910_000
    yf_trades = 5300
    yf_winrate = 0.528
    yf_vol = 0.208

    t_cagr = metrics['cagr']
    t_sharpe = metrics['sharpe']
    t_maxdd = metrics['max_drawdown']
    t_final = metrics['final_value']
    t_trades = metrics['trades']
    t_winrate = metrics['win_rate']
    t_vol = metrics['volatility']

    print(f"  {'CAGR':<25} {t_cagr:>13.2%} {yf_cagr:>13.2%} {t_cagr-yf_cagr:>+11.2%}")
    print(f"  {'Sharpe':<25} {t_sharpe:>14.3f} {yf_sharpe:>14.3f} {t_sharpe-yf_sharpe:>+12.3f}")
    print(f"  {'Max Drawdown':<25} {t_maxdd:>13.2%} {yf_maxdd:>13.2%} {t_maxdd-yf_maxdd:>+11.2%}")
    print(f"  {'Volatility':<25} {t_vol:>13.2%} {yf_vol:>13.2%} {t_vol-yf_vol:>+11.2%}")
    print(f"  {'Win Rate':<25} {t_winrate:>13.2%} {yf_winrate:>13.2%} {t_winrate-yf_winrate:>+11.2%}")
    print(f"  {'Total Trades':<25} {t_trades:>14,} {yf_trades:>14,} {t_trades-yf_trades:>+12,}")
    print(f"  {'$100K -> $':<25} {t_final:>13,.0f} {yf_final:>13,.0f}")

    # Divergence assessment
    cagr_diff = abs(t_cagr - yf_cagr)
    print(f"\n  DIVERGENCE ASSESSMENT:")
    if cagr_diff < 0.01:
        print(f"  MINIMAL divergence ({cagr_diff:.2%} CAGR delta) -- data sources are consistent")
    elif cagr_diff < 0.03:
        print(f"  MODERATE divergence ({cagr_diff:.2%} CAGR delta) -- minor adjustment differences")
    else:
        print(f"  SIGNIFICANT divergence ({cagr_diff:.2%} CAGR delta) -- data sources differ materially")
        print(f"  This could indicate different split/dividend adjustment methodology")

    # Annual comparison
    print(f"\n--- Annual Returns (Tiingo) ---")
    for yr, ret in metrics['annual_returns'].items():
        marker = ""
        if ret == metrics['best_year']:
            marker = " <-- BEST"
        elif ret == metrics['worst_year']:
            marker = " <-- WORST"
        print(f"  {yr.year:<8} {ret:>10.2%}{marker}")

    # 7. Save results
    os.makedirs('backtests', exist_ok=True)
    results['portfolio_values'].to_csv('backtests/v8_compass_tiingo_daily.csv', index=False)
    if len(results['trades']) > 0:
        results['trades'].to_csv('backtests/v8_compass_tiingo_trades.csv', index=False)

    with open('results_v8_compass_tiingo.pkl', 'wb') as f:
        pickle.dump({
            'params': {
                'data_source': 'Tiingo',
                'momentum_lookback': MOMENTUM_LOOKBACK,
                'momentum_skip': MOMENTUM_SKIP,
                'hold_days': HOLD_DAYS,
                'num_positions': NUM_POSITIONS,
                'target_vol': TARGET_VOL,
                'regime_sma': REGIME_SMA_PERIOD,
                'position_stop': POSITION_STOP_LOSS,
                'portfolio_stop': PORTFOLIO_STOP_LOSS,
                'trailing_activation': TRAILING_ACTIVATION,
                'trailing_stop': TRAILING_STOP_PCT,
            },
            'metrics': {k: v for k, v in metrics.items() if k != 'annual_returns'},
            'portfolio_values': results['portfolio_values'],
            'trades': results['trades'],
            'stop_events': results['stop_events'],
            'annual_universe': results['annual_universe'],
        }, f)

    print(f"\nResults saved:")
    print(f"  backtests/v8_compass_tiingo_daily.csv")
    print(f"  backtests/v8_compass_tiingo_trades.csv")
    print(f"  results_v8_compass_tiingo.pkl")

    print("\n" + "=" * 80)
    print(f"COMPASS (TIINGO) COMPLETE | {metrics['cagr']:.2%} CAGR | "
          f"{metrics['sharpe']:.3f} Sharpe | {metrics['max_drawdown']:.2%} MaxDD")
    print("=" * 80)
