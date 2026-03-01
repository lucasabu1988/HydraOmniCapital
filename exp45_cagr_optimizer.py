"""
Experiment 45: CAGR Optimizer - Systematic Parameter Sweep
============================================================

Targets the most promising unexplored optimization vectors from the
comprehensive 38-experiment history. Uses the EXACT COMPASS v8.2 engine
with survivorship-bias-corrected data pool.

Vectors tested (one at a time, measured vs v8.2 bias-corrected baseline):

  PHASE 1 - STOP LOSS THRESHOLD SWEEP:
    -12%, -13%, -14%, -15% (baseline), -16%, -17%, -18%, -20%
    Rationale: -15% confirmed optimal vs -8%, but -12% to -20% range untested

  PHASE 2 - RECOVERY STAGE DURATION SWEEP:
    Stage 1 / Stage 2 pairs: 42/84, 50/100, 63/126 (baseline), 75/150, 90/180
    Rationale: faster recovery = more stops, but the optimal balance is unknown

  PHASE 3 - PROTECTION MODE PARTIAL TRADING:
    During protection, allow 1-2 positions (instead of full shutdown)
    With reduced leverage (0.15x - 0.25x)
    Rationale: 26.7% idle time is huge; even small gains could compound

  PHASE 4 - DEPLOYMENT RATIO:
    Current: 95% cash deployed, 5% buffer
    Test: 90%, 92%, 95% (baseline), 97%, 98%
    Rationale: tighter buffer = more capital at work, but riskier

  PHASE 5 - MOMENTUM LOOKBACK FINE-TUNE:
    75d, 80d, 85d, 90d (baseline), 95d, 100d, 105d
    With skip: 3d, 4d, 5d (baseline), 7d, 10d
    Rationale: 90d confirmed vs 60/120/252, but nearby values untested

  PHASE 6 - UNIVERSE SIZE:
    Top-25, Top-30, Top-35, Top-40 (baseline), Top-50
    Rationale: smaller universe = more momentum dispersion

Baseline: COMPASS v8.2 bias-corrected = 13.90% CAGR, Sharpe 0.646, MaxDD -66.25%
Data: survivorship_bias_pool.pkl (744 stocks, 2000-2026)
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
import sys
import time
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import warnings
import json

warnings.filterwarnings('ignore')

# ============================================================================
# BASE PARAMETERS (COMPASS v8.2 - will be overridden per experiment)
# ============================================================================

BASE_PARAMS = {
    # Universe
    'TOP_N': 40,
    'MIN_AGE_DAYS': 63,
    # Signal
    'MOMENTUM_LOOKBACK': 90,
    'MOMENTUM_SKIP': 5,
    'MIN_MOMENTUM_STOCKS': 20,
    # Regime
    'REGIME_SMA_PERIOD': 200,
    'REGIME_CONFIRM_DAYS': 3,
    # Positions
    'NUM_POSITIONS': 5,
    'NUM_POSITIONS_RISK_OFF': 2,
    'HOLD_DAYS': 5,
    # Position-level risk
    'POSITION_STOP_LOSS': -0.08,
    'TRAILING_ACTIVATION': 0.05,
    'TRAILING_STOP_PCT': 0.03,
    # Portfolio-level risk
    'PORTFOLIO_STOP_LOSS': -0.15,
    # Recovery stages
    'RECOVERY_STAGE_1_DAYS': 63,
    'RECOVERY_STAGE_2_DAYS': 126,
    # Protection mode
    'PROTECTION_MAX_POSITIONS': 0,    # 0 = full shutdown (baseline)
    'PROTECTION_STAGE1_LEVERAGE': 0.3,
    'PROTECTION_STAGE2_LEVERAGE': 1.0,
    # Leverage & Vol targeting
    'TARGET_VOL': 0.15,
    'LEVERAGE_MIN': 0.3,
    'LEVERAGE_MAX': 1.0,
    'VOL_LOOKBACK': 20,
    # Deployment
    'DEPLOY_RATIO': 0.95,
    # Costs
    'INITIAL_CAPITAL': 100_000,
    'MARGIN_RATE': 0.06,
    'COMMISSION_PER_SHARE': 0.001,
    'CASH_YIELD_RATE': 0.035,
}


# ============================================================================
# DATA LOADING
# ============================================================================

def _strip_tz_from_df(df):
    """Strip timezone from a DataFrame's DatetimeIndex if present."""
    if hasattr(df.index, 'tz') and df.index.tz is not None:
        df = df.copy()
        df.index = df.index.tz_localize(None)
    return df


def load_survivorship_data():
    """Load the survivorship-bias-corrected data pool."""
    path = 'data_cache/survivorship_bias_pool.pkl'
    if os.path.exists(path):
        print("[Cache] Loading survivorship-bias corrected pool...")
        with open(path, 'rb') as f:
            data = pickle.load(f)
        print(f"  Loaded {len(data)} symbols")
        # Filter anomalous and strip timezone
        kept = {}
        for sym, df in data.items():
            df = _strip_tz_from_df(df)
            if len(df) < 20:
                continue
            rets = df['Close'].pct_change(fill_method=None).dropna()
            if len(rets) == 0:
                continue
            if rets.max() > 1.0:
                continue
            vol = rets.std() * np.sqrt(252)
            if vol > 2.0:
                continue
            kept[sym] = df
        print(f"  After filtering: {len(kept)} symbols")
        return kept

    # Fallback to broad pool
    fallback = 'data_cache/broad_pool_2000-01-01_2027-01-01.pkl'
    if os.path.exists(fallback):
        print("[Cache] Loading broad pool (WARNING: not survivorship corrected)...")
        with open(fallback, 'rb') as f:
            data = pickle.load(f)
        return {sym: _strip_tz_from_df(df) for sym, df in data.items()}

    print("ERROR: No data cache found")
    sys.exit(1)


def load_spy():
    """Load SPY data."""
    for path in ['data_cache/SPY_2000-01-01_2027-01-01.csv',
                 'data_cache/SPY_2000-01-01_2026-02-09.csv']:
        if os.path.exists(path):
            print(f"[Cache] Loading SPY from {path}...")
            return pd.read_csv(path, index_col=0, parse_dates=True)
    print("ERROR: No SPY data found")
    sys.exit(1)


def load_cash_yield():
    """Load Moody's Aaa yield."""
    path = 'data_cache/moody_aaa_yield.csv'
    if os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        daily = df['yield_pct'].resample('D').ffill()
        return daily
    return None


# ============================================================================
# UNIVERSE CONSTRUCTION
# ============================================================================

def _tz_strip(idx):
    if hasattr(idx, 'tz') and idx.tz is not None:
        return idx.tz_localize(None)
    return idx


def compute_annual_top_n(price_data, top_n):
    """Rank by prior-year average daily dollar volume."""
    all_dates = set()
    for df in price_data.values():
        all_dates.update(_tz_strip(df.index))
    all_dates_sorted = sorted(all_dates)
    if not all_dates_sorted:
        return {}
    years = sorted({d.year for d in all_dates_sorted})
    annual = {}

    for year in years:
        r_end = pd.Timestamp(f'{year}-02-01' if year == years[0] else f'{year}-01-01')
        r_start = pd.Timestamp(f'{year-1}-01-01')
        scores = {}
        for sym, df in price_data.items():
            idx = _tz_strip(df.index)
            mask = (idx >= r_start) & (idx < r_end)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            try:
                cl = window['Close']
                vo = window['Volume']
                if isinstance(cl, pd.DataFrame):
                    cl = cl.iloc[:, 0]
                if isinstance(vo, pd.DataFrame):
                    vo = vo.iloc[:, 0]
                dv = float((cl * vo).mean())
                if not np.isnan(dv) and dv > 0:
                    scores[sym] = dv
            except Exception:
                continue
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        annual[year] = [s for s, _ in ranked[:top_n]]

    return annual


# ============================================================================
# REGIME
# ============================================================================

def compute_regime(spy_data, params):
    """Compute market regime based on SPY vs SMA."""
    spy_close = spy_data['Close']
    sma_period = params['REGIME_SMA_PERIOD']
    confirm = params['REGIME_CONFIRM_DAYS']
    sma = spy_close.rolling(sma_period).mean()
    raw_signal = spy_close > sma

    regime = pd.Series(index=spy_close.index, dtype=bool)
    regime.iloc[:sma_period] = True

    current_regime = True
    consecutive_count = 0
    last_raw = True

    for i in range(sma_period, len(raw_signal)):
        raw = raw_signal.iloc[i]
        if pd.isna(raw):
            regime.iloc[i] = current_regime
            continue
        if raw == last_raw:
            consecutive_count += 1
        else:
            consecutive_count = 1
            last_raw = raw
        if raw != current_regime and consecutive_count >= confirm:
            current_regime = raw
        regime.iloc[i] = current_regime

    return regime


# ============================================================================
# SIGNAL
# ============================================================================

def compute_momentum_scores(price_data, tradeable, date, params):
    """Compute cross-sectional momentum scores."""
    lookback = params['MOMENTUM_LOOKBACK']
    skip = params['MOMENTUM_SKIP']
    scores = {}

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

        needed = lookback + skip
        if sym_idx < needed:
            continue

        close_today = df['Close'].iloc[sym_idx]
        close_skip = df['Close'].iloc[sym_idx - skip]
        close_lookback = df['Close'].iloc[sym_idx - lookback]

        if close_lookback <= 0 or close_skip <= 0 or close_today <= 0:
            continue

        momentum = (close_skip / close_lookback) - 1.0
        skip_return = (close_today / close_skip) - 1.0
        scores[symbol] = momentum - skip_return

    return scores


def compute_vol_weights(price_data, selected, date, params):
    """Inverse-volatility weighting."""
    vols = {}
    vol_lb = params['VOL_LOOKBACK']

    for symbol in selected:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        sym_idx = df.index.get_loc(date)
        if sym_idx < vol_lb + 1:
            continue
        returns = df['Close'].iloc[sym_idx - vol_lb:sym_idx + 1].pct_change().dropna()
        if len(returns) < vol_lb - 2:
            continue
        vol = returns.std() * np.sqrt(252)
        if vol > 0.01:
            vols[symbol] = vol

    if not vols:
        return {s: 1.0 / len(selected) for s in selected}

    raw_w = {s: 1.0 / v for s, v in vols.items()}
    total = sum(raw_w.values())
    return {s: w / total for s, w in raw_w.items()}


def compute_leverage(spy_data, date, params):
    """Vol-targeted leverage."""
    if date not in spy_data.index:
        return 1.0
    idx = spy_data.index.get_loc(date)
    vol_lb = params['VOL_LOOKBACK']
    if idx < vol_lb + 1:
        return 1.0
    returns = spy_data['Close'].iloc[idx - vol_lb:idx + 1].pct_change().dropna()
    if len(returns) < vol_lb - 2:
        return 1.0
    realized_vol = returns.std() * np.sqrt(252)
    if realized_vol < 0.01:
        return params['LEVERAGE_MAX']
    leverage = params['TARGET_VOL'] / realized_vol
    return max(params['LEVERAGE_MIN'], min(params['LEVERAGE_MAX'], leverage))


# ============================================================================
# TRADEABLE SYMBOLS
# ============================================================================

def get_tradeable(price_data, date, first_date, annual_universe, params):
    """Return tradeable symbols."""
    eligible = set(annual_universe.get(date.year, []))
    out = []
    for sym in eligible:
        if sym not in price_data:
            continue
        df = price_data[sym]
        if date not in df.index:
            continue
        sym_first = df.index[0]
        if date <= first_date + timedelta(days=30):
            out.append(sym)
        elif (date - sym_first).days >= params['MIN_AGE_DAYS']:
            out.append(sym)
    return out


# ============================================================================
# BACKTEST ENGINE
# ============================================================================

def run_backtest(price_data, annual_universe, spy_data, cash_yield_daily, params, quiet=True):
    """Run COMPASS backtest with given parameters. Returns metrics dict."""

    regime = compute_regime(spy_data, params)

    all_dates = set()
    for df in price_data.values():
        all_dates.update(_tz_strip(df.index))
    all_dates = sorted(list(all_dates))
    # Clip to 2000-01-03 onwards
    clip = pd.Timestamp('2000-01-03')
    all_dates = [d for d in all_dates if d >= clip]

    if not all_dates:
        return None

    first_date = all_dates[0]

    cash = float(params['INITIAL_CAPITAL'])
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []

    peak_value = float(params['INITIAL_CAPITAL'])
    in_protection_mode = False
    protection_stage = 0
    stop_loss_day_index = None

    for i, date in enumerate(all_dates):
        tradeable = get_tradeable(price_data, date, first_date, annual_universe, params)

        # Portfolio value
        portfolio_value = cash
        for sym, pos in list(positions.items()):
            if sym in price_data and date in price_data[sym].index:
                portfolio_value += pos['shares'] * price_data[sym].loc[date, 'Close']

        # Peak / drawdown
        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # Recovery check
        if in_protection_mode and stop_loss_day_index is not None:
            days_since_stop = i - stop_loss_day_index
            is_regime_on = True
            if date in regime.index:
                is_regime_on = bool(regime.loc[date])

            if protection_stage == 1 and days_since_stop >= params['RECOVERY_STAGE_1_DAYS'] and is_regime_on:
                protection_stage = 2

            if protection_stage == 2 and days_since_stop >= params['RECOVERY_STAGE_2_DAYS'] and is_regime_on:
                in_protection_mode = False
                protection_stage = 0
                peak_value = portfolio_value
                stop_loss_day_index = None

        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # Portfolio stop loss
        if drawdown <= params['PORTFOLIO_STOP_LOSS'] and not in_protection_mode:
            stop_events.append({'date': date, 'drawdown': drawdown})

            for symbol in list(positions.keys()):
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    pos = positions[symbol]
                    proceeds = pos['shares'] * exit_price
                    commission = pos['shares'] * params['COMMISSION_PER_SHARE']
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

        # Regime
        is_risk_on = True
        if date in regime.index:
            is_risk_on = bool(regime.loc[date])

        # Max positions and leverage
        if in_protection_mode:
            prot_max_pos = params.get('PROTECTION_MAX_POSITIONS', 0)
            if protection_stage == 1:
                max_positions = max(prot_max_pos, 2) if prot_max_pos > 0 else 2
                current_leverage = params['PROTECTION_STAGE1_LEVERAGE']
                # If no protection trading, keep 0 positions
                if prot_max_pos == 0:
                    max_positions = 0
                    current_leverage = 0.0
                else:
                    max_positions = min(prot_max_pos, 2)
                    current_leverage = params['PROTECTION_STAGE1_LEVERAGE']
            else:
                if prot_max_pos == 0:
                    max_positions = 0
                    current_leverage = 0.0
                else:
                    max_positions = min(prot_max_pos, 3)
                    current_leverage = params['PROTECTION_STAGE2_LEVERAGE']
        elif not is_risk_on:
            max_positions = params['NUM_POSITIONS_RISK_OFF']
            current_leverage = 1.0
        else:
            max_positions = params['NUM_POSITIONS']
            current_leverage = compute_leverage(spy_data, date, params)

        # Standard protection mode behavior (original COMPASS)
        if in_protection_mode and params.get('PROTECTION_MAX_POSITIONS', 0) == 0:
            if protection_stage == 1:
                max_positions = 2
                current_leverage = params['PROTECTION_STAGE1_LEVERAGE']
            else:
                max_positions = 3
                current_leverage = params['PROTECTION_STAGE2_LEVERAGE']

        # Margin costs
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = params['MARGIN_RATE'] / 252 * borrowed
            cash -= daily_margin

        # Cash yield
        if cash > 0:
            if cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = params['CASH_YIELD_RATE'] / 252
            cash += cash * daily_rate

        # Close positions
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue

            current_price = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            days_held = i - pos['entry_idx']
            if days_held >= params['HOLD_DAYS']:
                exit_reason = 'hold_expired'

            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            if pos_return <= params['POSITION_STOP_LOSS']:
                exit_reason = 'position_stop'

            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + params['TRAILING_ACTIVATION']):
                trailing_level = pos['high_price'] * (1 - params['TRAILING_STOP_PCT'])
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            if symbol not in tradeable:
                exit_reason = 'universe_rotation'

            if exit_reason is None and len(positions) > max_positions and max_positions > 0:
                pos_returns = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        pos_returns[s] = (price_data[s].loc[date, 'Close'] - p['entry_price']) / p['entry_price']
                if pos_returns:
                    worst = min(pos_returns, key=pos_returns.get)
                    if symbol == worst:
                        exit_reason = 'regime_reduce'

            if exit_reason:
                shares = pos['shares']
                proceeds = shares * current_price
                commission = shares * params['COMMISSION_PER_SHARE']
                cash += proceeds - commission
                pnl = (current_price - pos['entry_price']) * shares - commission
                trades.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'exit_reason': exit_reason,
                    'pnl': pnl,
                    'return': pnl / (pos['entry_price'] * shares) if pos['entry_price'] * shares > 0 else 0
                })
                del positions[symbol]

        # Open new positions
        needed = max_positions - len(positions)

        if needed > 0 and cash > 1000 and len(tradeable) >= 5:
            scores = compute_momentum_scores(price_data, tradeable, date, params)
            available = {s: sc for s, sc in scores.items() if s not in positions}

            if len(available) >= needed:
                ranked = sorted(available.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]
                weights = compute_vol_weights(price_data, selected, date, params)
                deploy = params['DEPLOY_RATIO']
                effective_capital = cash * current_leverage * deploy

                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue
                    entry_price = price_data[symbol].loc[date, 'Close']
                    if entry_price <= 0:
                        continue
                    weight = weights.get(symbol, 1.0 / len(selected))
                    position_value = effective_capital * weight
                    max_per = cash * 0.40
                    position_value = min(position_value, max_per)
                    shares = position_value / entry_price
                    cost = shares * entry_price
                    commission = shares * params['COMMISSION_PER_SHARE']

                    if cost + commission <= cash * 0.90:
                        positions[symbol] = {
                            'entry_price': entry_price,
                            'shares': shares,
                            'entry_date': date,
                            'entry_idx': i,
                            'high_price': entry_price,
                        }
                        cash -= cost + commission

        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'drawdown': drawdown,
            'leverage': current_leverage,
            'in_protection': in_protection_mode,
        })

    if not portfolio_values:
        return None

    # Calculate metrics
    pv_df = pd.DataFrame(portfolio_values).set_index('date')
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()

    initial = params['INITIAL_CAPITAL']
    final = pv_df['value'].iloc[-1]
    n_days = len(pv_df)
    years = n_days / 252

    cagr = (final / initial) ** (1 / years) - 1 if years > 0 else 0
    daily_rets = pv_df['value'].pct_change().dropna()
    ann_vol = daily_rets.std() * np.sqrt(252) if len(daily_rets) > 1 else 0.01
    max_dd = pv_df['drawdown'].min()

    sharpe = (daily_rets.mean() * 252 - 0.035) / (ann_vol) if ann_vol > 0.001 else 0
    calmar = cagr / abs(max_dd) if max_dd < 0 else 0

    n_trades = len(trades_df)
    win_rate = (trades_df['pnl'] > 0).mean() if n_trades > 0 else 0
    profit_factor = 0
    if n_trades > 0:
        wins = trades_df[trades_df['pnl'] > 0]['pnl'].sum()
        losses = abs(trades_df[trades_df['pnl'] < 0]['pnl'].sum())
        profit_factor = wins / losses if losses > 0 else float('inf')

    protection_days = pv_df['in_protection'].sum()
    protection_pct = protection_days / n_days * 100 if n_days > 0 else 0

    return {
        'cagr': cagr,
        'final_value': final,
        'sharpe': sharpe,
        'max_drawdown': max_dd,
        'volatility': ann_vol,
        'calmar': calmar,
        'trades': n_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'stop_events': len(stop_events),
        'protection_days': protection_days,
        'protection_pct': protection_pct,
        'years': years,
    }


# ============================================================================
# EXPERIMENT DEFINITIONS
# ============================================================================

def get_experiments():
    """Define all experiment configurations."""
    experiments = {}

    # --- PHASE 1: Stop Loss Threshold ---
    for sl in [-0.12, -0.13, -0.14, -0.15, -0.16, -0.17, -0.18, -0.20]:
        name = f"SL_{abs(sl)*100:.0f}pct"
        p = dict(BASE_PARAMS)
        p['PORTFOLIO_STOP_LOSS'] = sl
        experiments[name] = p

    # --- PHASE 2: Recovery Duration ---
    for s1, s2 in [(42, 84), (50, 100), (63, 126), (75, 150), (90, 180)]:
        name = f"REC_{s1}d_{s2}d"
        p = dict(BASE_PARAMS)
        p['RECOVERY_STAGE_1_DAYS'] = s1
        p['RECOVERY_STAGE_2_DAYS'] = s2
        experiments[name] = p

    # --- PHASE 3: Deployment Ratio ---
    for dr in [0.90, 0.92, 0.95, 0.97, 0.98]:
        name = f"DEPLOY_{int(dr*100)}pct"
        p = dict(BASE_PARAMS)
        p['DEPLOY_RATIO'] = dr
        experiments[name] = p

    # --- PHASE 4: Momentum Lookback ---
    for lb in [75, 80, 85, 90, 95, 100, 105]:
        name = f"MOM_{lb}d"
        p = dict(BASE_PARAMS)
        p['MOMENTUM_LOOKBACK'] = lb
        experiments[name] = p

    # --- PHASE 5: Momentum Skip ---
    for sk in [3, 4, 5, 7, 10]:
        name = f"SKIP_{sk}d"
        p = dict(BASE_PARAMS)
        p['MOMENTUM_SKIP'] = sk
        experiments[name] = p

    # --- PHASE 6: Universe Size ---
    for n in [25, 30, 35, 40, 50]:
        name = f"TOP_{n}"
        p = dict(BASE_PARAMS)
        p['TOP_N'] = n
        experiments[name] = p

    # --- PHASE 7: Combined promising (if found) ---
    # Will be defined after phases 1-6 results

    return experiments


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    print("=" * 90)
    print("EXPERIMENT 45: CAGR OPTIMIZER - SYSTEMATIC PARAMETER SWEEP")
    print("=" * 90)
    print()

    # Load data
    t0 = time.time()
    price_data = load_survivorship_data()
    spy_data = load_spy()
    cash_yield = load_cash_yield()
    print(f"  Data loaded in {time.time()-t0:.1f}s")

    # Get experiments
    experiments = get_experiments()
    print(f"\n  Total experiments: {len(experiments)}")
    print()

    # Pre-compute universe for each TOP_N value used
    top_n_values = set(p['TOP_N'] for p in experiments.values())
    universes = {}
    for top_n in top_n_values:
        print(f"  Computing annual top-{top_n} universe...")
        universes[top_n] = compute_annual_top_n(price_data, top_n)

    # Run all experiments
    results = {}
    baseline_cagr = None

    print(f"\n{'='*90}")
    print(f"{'Experiment':<25} {'CAGR':>8} {'Delta':>8} {'Sharpe':>8} {'MaxDD':>8} {'Trades':>7} {'Stops':>6} {'Prot%':>6}")
    print(f"{'='*90}")

    for i, (name, params) in enumerate(experiments.items()):
        t_start = time.time()
        top_n = params['TOP_N']
        annual_universe = universes[top_n]

        metrics = run_backtest(price_data, annual_universe, spy_data, cash_yield, params, quiet=True)

        if metrics is None:
            print(f"  {name:<25} FAILED")
            continue

        results[name] = metrics

        if name == 'SL_15pct':
            baseline_cagr = metrics['cagr']

        delta = (metrics['cagr'] - (baseline_cagr or 0)) * 100 if baseline_cagr else 0

        elapsed = time.time() - t_start
        delta_str = f"{delta:+.2f}%" if baseline_cagr else "BASE"

        print(f"  {name:<25} {metrics['cagr']*100:>7.2f}% {delta_str:>8} "
              f"{metrics['sharpe']:>8.3f} {metrics['max_drawdown']*100:>7.1f}% "
              f"{metrics['trades']:>7,} {metrics['stop_events']:>6} "
              f"{metrics['protection_pct']:>5.1f}%  ({elapsed:.0f}s)")

    # Summary
    print(f"\n{'='*90}")
    print("RESULTS RANKED BY CAGR")
    print(f"{'='*90}")

    ranked = sorted(results.items(), key=lambda x: x[1]['cagr'], reverse=True)

    print(f"\n{'Rank':<5} {'Experiment':<25} {'CAGR':>8} {'Delta':>8} {'Sharpe':>8} {'MaxDD':>8} {'Calmar':>8}")
    print("-" * 80)

    for rank, (name, m) in enumerate(ranked, 1):
        delta = (m['cagr'] - (baseline_cagr or m['cagr'])) * 100
        marker = " <<<" if m['cagr'] > (baseline_cagr or 0) else ""
        print(f"  {rank:<4} {name:<25} {m['cagr']*100:>7.2f}% {delta:>+7.2f}% "
              f"{m['sharpe']:>8.3f} {m['max_drawdown']*100:>7.1f}% "
              f"{m['calmar']:>8.3f}{marker}")

    # Best from each phase
    print(f"\n{'='*90}")
    print("BEST PER PHASE")
    print(f"{'='*90}")

    phases = {
        'Stop Loss': [n for n in results if n.startswith('SL_')],
        'Recovery': [n for n in results if n.startswith('REC_')],
        'Deployment': [n for n in results if n.startswith('DEPLOY_')],
        'Momentum LB': [n for n in results if n.startswith('MOM_')],
        'Momentum Skip': [n for n in results if n.startswith('SKIP_')],
        'Universe Size': [n for n in results if n.startswith('TOP_')],
    }

    best_params = {}
    for phase, names in phases.items():
        phase_results = {n: results[n] for n in names if n in results}
        if not phase_results:
            continue
        best_name = max(phase_results, key=lambda x: phase_results[x]['cagr'])
        best = phase_results[best_name]
        delta = (best['cagr'] - (baseline_cagr or 0)) * 100
        print(f"  {phase:<18} {best_name:<25} {best['cagr']*100:.2f}% ({delta:+.2f}%) "
              f"Sharpe={best['sharpe']:.3f} MaxDD={best['max_drawdown']*100:.1f}%")
        best_params[phase] = best_name

    # Save results
    output = {
        'baseline_cagr': baseline_cagr,
        'results': {name: {k: float(v) if isinstance(v, (np.floating, np.integer)) else v
                          for k, v in m.items()}
                   for name, m in results.items()},
        'ranked': [(name, results[name]['cagr']) for name, _ in ranked[:10]],
        'best_per_phase': best_params,
    }

    os.makedirs('backtests', exist_ok=True)
    with open('backtests/exp45_results.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n  Results saved to backtests/exp45_results.json")
    print(f"\n{'='*90}")
    print("EXPERIMENT 45 COMPLETE")
    print(f"{'='*90}")
