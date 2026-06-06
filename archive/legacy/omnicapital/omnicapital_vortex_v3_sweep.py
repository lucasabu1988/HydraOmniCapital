"""
OMNICAPITAL VORTEX v3 — Parameter Sweep
========================================
Instead of inventing new signals, we systematically sweep the COMPASS engine's
parameters to find if a superior configuration exists.

Strategy: Same COMPASS cross-sectional momentum engine, different tuning.

Phase 1: Coarse sweep (key params only)
Phase 2: Fine-tune around best region

Baseline: COMPASS v8.2 = 16.04% CAGR, 0.770 Sharpe, -28.8% Max DD
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
from typing import Dict, List, Tuple, Optional
from itertools import product
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# FIXED PARAMETERS (same as COMPASS)
# ============================================================================
TOP_N = 40
MIN_AGE_DAYS = 63
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3
POSITION_STOP_LOSS = -0.08
PORTFOLIO_STOP_LOSS = -0.15
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126
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
# DATA FUNCTIONS (identical to COMPASS)
# ============================================================================

def download_broad_pool():
    cache_file = f'data_cache/broad_pool_{START_DATE}_{END_DATE}.pkl'
    if os.path.exists(cache_file):
        print("[Cache] Loading broad pool data...")
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception:
            print("[Cache] Failed, re-downloading...")

    print(f"[Download] Downloading {len(BROAD_POOL)} symbols...")
    data = {}
    for i, symbol in enumerate(BROAD_POOL):
        try:
            df = yf.download(symbol, start=START_DATE, end=END_DATE, progress=False)
            if not df.empty and len(df) > 100:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                data[symbol] = df
        except Exception:
            pass
    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)
    return data


def download_spy():
    cache_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        return df
    df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def compute_annual_top40(price_data):
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    years = sorted(set(d.year for d in all_dates))
    annual_universe = {}
    for year in years:
        if year == years[0]:
            ranking_end = pd.Timestamp(f'{year}-02-01',
                tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            ranking_start = pd.Timestamp(f'{year-1}-01-01',
                tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
        else:
            ranking_end = pd.Timestamp(f'{year}-01-01',
                tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            ranking_start = pd.Timestamp(f'{year-1}-01-01',
                tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
        scores = {}
        for symbol, df in price_data.items():
            mask = (df.index >= ranking_start) & (df.index < ranking_end)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dollar_vol = (window['Close'] * window['Volume']).mean()
            scores[symbol] = dollar_vol
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        annual_universe[year] = [s for s, _ in ranked[:TOP_N]]
    return annual_universe


def compute_regime(spy_data):
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


# ============================================================================
# PARAMETRIZED BACKTEST ENGINE
# ============================================================================

def run_parametric_backtest(price_data, annual_universe, spy_data, regime,
                            all_dates, first_date, params):
    """
    Run a single backtest with given parameter dict.
    Returns dict with key metrics.
    """
    momentum_lookback = params['momentum_lookback']
    momentum_skip = params['momentum_skip']
    hold_days = params['hold_days']
    num_positions = params['num_positions']
    num_positions_roff = params.get('num_positions_roff', 2)
    target_vol = params['target_vol']
    trailing_activation = params.get('trailing_activation', 0.05)
    trailing_stop_pct = params.get('trailing_stop_pct', 0.03)
    leverage_min = params.get('leverage_min', 0.3)
    leverage_max = params.get('leverage_max', 2.0)

    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    daily_drawdowns = []
    trades = []
    peak_value = float(INITIAL_CAPITAL)
    in_protection = False
    protection_stage = 0
    stop_loss_day_idx = None
    stop_events = 0

    for i, date in enumerate(all_dates):
        # Tradeable
        eligible = set(annual_universe.get(date.year, []))
        tradeable = []
        for symbol in eligible:
            if symbol not in price_data:
                continue
            df = price_data[symbol]
            if date not in df.index:
                continue
            days_since = (date - df.index[0]).days
            if date <= first_date + timedelta(days=30) or days_since >= MIN_AGE_DAYS:
                tradeable.append(symbol)

        # Portfolio value
        pv = cash
        for symbol, pos in positions.items():
            if symbol in price_data and date in price_data[symbol].index:
                pv += pos['shares'] * price_data[symbol].loc[date, 'Close']

        if pv > peak_value and not in_protection:
            peak_value = pv
        dd = (pv - peak_value) / peak_value if peak_value > 0 else 0

        # Recovery
        if in_protection and stop_loss_day_idx is not None:
            days_since_stop = i - stop_loss_day_idx
            is_ron = bool(regime.loc[date]) if date in regime.index else True
            if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and is_ron:
                protection_stage = 2
            if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and is_ron:
                in_protection = False
                protection_stage = 0
                peak_value = pv
                stop_loss_day_idx = None

        # Portfolio stop
        if dd <= PORTFOLIO_STOP_LOSS and not in_protection:
            stop_events += 1
            for symbol in list(positions.keys()):
                if symbol in price_data and date in price_data[symbol].index:
                    ep = price_data[symbol].loc[date, 'Close']
                    pos = positions[symbol]
                    cash += pos['shares'] * ep - pos['shares'] * COMMISSION_PER_SHARE
                    pnl_ret = (ep - pos['entry_price']) / pos['entry_price']
                    trades.append({'ret': pnl_ret, 'reason': 'portfolio_stop'})
                del positions[symbol]
            in_protection = True
            protection_stage = 1
            stop_loss_day_idx = i

        # Regime
        is_risk_on = bool(regime.loc[date]) if date in regime.index else True

        # Position sizing
        if in_protection:
            max_pos = 2 if protection_stage == 1 else 3
            leverage = 0.3 if protection_stage == 1 else 1.0
        elif not is_risk_on:
            max_pos = num_positions_roff
            leverage = 1.0
        else:
            max_pos = num_positions
            # Vol targeting
            if date in spy_data.index:
                idx = spy_data.index.get_loc(date)
                if idx >= VOL_LOOKBACK + 1:
                    rets = spy_data['Close'].iloc[idx-VOL_LOOKBACK:idx+1].pct_change().dropna()
                    rv = rets.std() * np.sqrt(252)
                    leverage = target_vol / rv if rv > 0.01 else leverage_max
                    leverage = max(leverage_min, min(leverage_max, leverage))
                else:
                    leverage = 1.0
            else:
                leverage = 1.0

        # Margin cost
        if leverage > 1.0:
            borrowed = pv * (leverage - 1) / leverage
            cash -= MARGIN_RATE / 252 * borrowed

        # Close positions
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue
            cp = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            days_held = i - pos['entry_idx']
            if days_held >= hold_days:
                exit_reason = 'hold_expired'

            pos_ret = (cp - pos['entry_price']) / pos['entry_price']
            if pos_ret <= POSITION_STOP_LOSS:
                exit_reason = 'position_stop'

            if cp > pos['high_price']:
                pos['high_price'] = cp
            if pos['high_price'] > pos['entry_price'] * (1 + trailing_activation):
                if cp <= pos['high_price'] * (1 - trailing_stop_pct):
                    exit_reason = 'trailing_stop'

            if symbol not in tradeable:
                exit_reason = 'universe_rotation'

            if exit_reason is None and len(positions) > max_pos:
                pos_rets = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        pos_rets[s] = (price_data[s].loc[date, 'Close'] - p['entry_price']) / p['entry_price']
                worst = min(pos_rets, key=pos_rets.get)
                if symbol == worst:
                    exit_reason = 'regime_reduce'

            if exit_reason:
                proceeds = pos['shares'] * cp
                commission = pos['shares'] * COMMISSION_PER_SHARE
                cash += proceeds - commission
                pnl_ret = (cp - pos['entry_price']) / pos['entry_price']
                trades.append({'ret': pnl_ret, 'reason': exit_reason})
                del positions[symbol]

        # Open new positions
        needed = max_pos - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable) >= 5:
            # Momentum scores — compute for ALL tradeable (like COMPASS)
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
                need = momentum_lookback + momentum_skip
                if sym_idx < need:
                    continue
                ct = df['Close'].iloc[sym_idx]
                cs = df['Close'].iloc[sym_idx - momentum_skip]
                cl = df['Close'].iloc[sym_idx - momentum_lookback]
                if cl <= 0 or cs <= 0 or ct <= 0:
                    continue
                mom = (cs / cl) - 1.0
                skip_ret = (ct / cs) - 1.0
                scores[symbol] = mom - skip_ret

            # Filter out stocks already in portfolio (like COMPASS)
            available_scores = {s: sc for s, sc in scores.items() if s not in positions}

            if len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]

                # Inverse vol weights (matching COMPASS compute_volatility_weights)
                vols = {}
                for s in selected:
                    if s not in price_data:
                        continue
                    df = price_data[s]
                    if date not in df.index:
                        continue
                    si = df.index.get_loc(date)
                    if si < VOL_LOOKBACK + 1:
                        continue
                    r = df['Close'].iloc[si-VOL_LOOKBACK:si+1].pct_change().dropna()
                    if len(r) < VOL_LOOKBACK - 2:
                        continue
                    v = r.std() * np.sqrt(252)
                    if v > 0.01:
                        vols[s] = v
                if not vols:
                    weights = {s: 1.0/len(selected) for s in selected}
                else:
                    raw_w = {s: 1.0/v for s, v in vols.items()}
                    total_w = sum(raw_w.values())
                    weights = {s: w/total_w for s, w in raw_w.items()}

                eff_capital = cash * leverage * 0.95
                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue
                    ep = price_data[symbol].loc[date, 'Close']
                    if ep <= 0:
                        continue
                    w = weights.get(symbol, 1.0/len(selected))
                    position_value = eff_capital * w
                    max_per_pos = cash * 0.40
                    position_value = min(position_value, max_per_pos)
                    shares = position_value / ep
                    cost = shares * ep
                    commission = shares * COMMISSION_PER_SHARE
                    if cost + commission <= cash * 0.90:
                        positions[symbol] = {
                            'entry_price': ep, 'shares': shares,
                            'entry_date': date, 'entry_idx': i,
                            'high_price': ep
                        }
                        cash -= cost + commission

        portfolio_values.append(pv)
        daily_drawdowns.append(dd)

    # Calculate metrics
    pv_series = pd.Series(portfolio_values, index=all_dates)
    final = pv_series.iloc[-1]
    years = len(pv_series) / 252
    cagr = (final / INITIAL_CAPITAL) ** (1/years) - 1
    rets = pv_series.pct_change().dropna()
    vol = rets.std() * np.sqrt(252)
    sharpe = cagr / vol if vol > 0 else 0
    # Use drawdowns tracked with peak-reset (matches COMPASS exactly)
    dd_series = pd.Series(daily_drawdowns, index=all_dates)
    max_dd = dd_series.min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    # Sortino
    down_rets = rets[rets < 0]
    down_vol = down_rets.std() * np.sqrt(252) if len(down_rets) > 0 else vol
    sortino = cagr / down_vol if down_vol > 0 else 0

    # Win rate
    trade_rets = [t['ret'] for t in trades]
    wr = np.mean([1 for r in trade_rets if r > 0]) / len(trade_rets) if trade_rets else 0

    # Annual returns
    pv_df = pd.DataFrame({'value': portfolio_values}, index=all_dates)
    annual = pv_df['value'].resample('YE').last().pct_change().dropna()
    best_yr = annual.max() if len(annual) > 0 else 0
    worst_yr = annual.min() if len(annual) > 0 else 0

    return {
        'final': final,
        'cagr': cagr,
        'sharpe': sharpe,
        'sortino': sortino,
        'max_dd': max_dd,
        'calmar': calmar,
        'vol': vol,
        'trades': len(trades),
        'wr': wr,
        'stops': stop_events,
        'best_yr': best_yr,
        'worst_yr': worst_yr,
        'params': params,
        'pv_series': pv_series,
    }


# ============================================================================
# MAIN — PARAMETER SWEEP
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("VORTEX v3 — PARAMETER SWEEP")
    print("Same COMPASS engine, optimized parameters")
    print("=" * 80)

    # Load data
    price_data = download_broad_pool()
    spy_data = download_spy()
    print(f"Data: {len(price_data)} symbols, SPY: {len(spy_data)} days")

    # Compute shared data
    print("\nComputing annual top-40...")
    annual_universe = compute_annual_top40(price_data)
    print("Computing market regime...")
    regime = compute_regime(spy_data)

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    # ================================================================
    # PHASE 1: Coarse sweep
    # ================================================================
    print("\n" + "=" * 80)
    print("PHASE 1: COARSE SWEEP")
    print("=" * 80)

    # Key insight from analysis: momentum signal is 70% of alpha
    # So we sweep: lookback, skip, hold, positions, vol_target
    sweep_params = {
        'momentum_lookback': [60, 90, 120, 180],
        'momentum_skip':     [3, 5, 7, 10],
        'hold_days':         [3, 5, 7, 10],
        'num_positions':     [3, 5, 7],
        'target_vol':        [0.15, 0.20, 0.25],
    }

    # That's 4*4*4*3*3 = 576 combos — too many
    # Smart strategy: fix positions=5, vol=0.15 (known good), sweep signal params
    # Then fine-tune positions and vol around best signal

    print("\nPhase 1a: Signal sweep (lookback x skip x hold)")
    print(f"  Fixed: positions=5, target_vol=0.15")

    results_1a = []
    combos_1a = list(product(
        sweep_params['momentum_lookback'],
        sweep_params['momentum_skip'],
        sweep_params['hold_days'],
    ))
    total = len(combos_1a)
    print(f"  Combinations: {total}")

    for idx, (lb, skip, hold) in enumerate(combos_1a):
        params = {
            'momentum_lookback': lb,
            'momentum_skip': skip,
            'hold_days': hold,
            'num_positions': 5,
            'target_vol': 0.15,
        }
        result = run_parametric_backtest(
            price_data, annual_universe, spy_data, regime, all_dates, first_date, params
        )
        results_1a.append(result)

        # Progress
        if (idx + 1) % 8 == 0 or idx == total - 1:
            best_so_far = max(results_1a, key=lambda x: x['cagr'])
            bp = best_so_far['params']
            print(f"  [{idx+1}/{total}] Best: {best_so_far['cagr']:.2%} CAGR "
                  f"(lb={bp['momentum_lookback']}, skip={bp['momentum_skip']}, hold={bp['hold_days']})")

    # Sort by CAGR
    results_1a.sort(key=lambda x: x['cagr'], reverse=True)

    print("\n  TOP 10 SIGNAL CONFIGS:")
    print(f"  {'Rank':<5} {'Lookback':>8} {'Skip':>5} {'Hold':>5} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>8} {'Trades':>7}")
    print("  " + "-" * 60)
    for i, r in enumerate(results_1a[:10]):
        p = r['params']
        print(f"  {i+1:<5} {p['momentum_lookback']:>8} {p['momentum_skip']:>5} {p['hold_days']:>5} "
              f"{r['cagr']:>7.2%} {r['sharpe']:>8.3f} {r['max_dd']:>7.1%} {r['trades']:>7}")

    # Baseline comparison
    baseline = [r for r in results_1a if r['params']['momentum_lookback'] == 90
                and r['params']['momentum_skip'] == 5 and r['params']['hold_days'] == 5]
    if baseline:
        b = baseline[0]
        print(f"\n  BASELINE (90/5/5): {b['cagr']:.2%} CAGR | {b['sharpe']:.3f} Sharpe | {b['max_dd']:.1%} DD")

    best_signal = results_1a[0]
    bp = best_signal['params']
    print(f"\n  BEST SIGNAL: lb={bp['momentum_lookback']}, skip={bp['momentum_skip']}, hold={bp['hold_days']}")
    print(f"  CAGR: {best_signal['cagr']:.2%} | Sharpe: {best_signal['sharpe']:.3f} | DD: {best_signal['max_dd']:.1%}")

    # ================================================================
    # PHASE 1b: Sweep positions & vol around best signal
    # ================================================================
    print("\n" + "=" * 80)
    print("PHASE 1b: POSITION & VOL SWEEP (around best signal)")
    print("=" * 80)

    results_1b = []
    combos_1b = list(product(
        sweep_params['num_positions'],
        sweep_params['target_vol'],
    ))
    print(f"  Combinations: {len(combos_1b)}")

    for idx, (npos, tvol) in enumerate(combos_1b):
        params = {
            'momentum_lookback': bp['momentum_lookback'],
            'momentum_skip': bp['momentum_skip'],
            'hold_days': bp['hold_days'],
            'num_positions': npos,
            'target_vol': tvol,
        }
        result = run_parametric_backtest(
            price_data, annual_universe, spy_data, regime, all_dates, first_date, params
        )
        results_1b.append(result)
        p = result['params']
        print(f"  [{idx+1}/{len(combos_1b)}] pos={npos}, vol={tvol:.0%}: "
              f"{result['cagr']:.2%} CAGR | {result['sharpe']:.3f} Sharpe | {result['max_dd']:.1%} DD")

    results_1b.sort(key=lambda x: x['cagr'], reverse=True)
    best_pos = results_1b[0]
    bpp = best_pos['params']

    # ================================================================
    # PHASE 2: Fine-tune trailing stops around best config
    # ================================================================
    print("\n" + "=" * 80)
    print("PHASE 2: TRAILING STOP FINE-TUNE")
    print("=" * 80)

    trailing_combos = list(product(
        [0.03, 0.05, 0.07, 0.10],   # trailing activation
        [0.02, 0.03, 0.04, 0.05],   # trailing stop pct
    ))
    results_2 = []
    for idx, (ta, ts) in enumerate(trailing_combos):
        params = {
            'momentum_lookback': bpp['momentum_lookback'],
            'momentum_skip': bpp['momentum_skip'],
            'hold_days': bpp['hold_days'],
            'num_positions': bpp['num_positions'],
            'target_vol': bpp['target_vol'],
            'trailing_activation': ta,
            'trailing_stop_pct': ts,
        }
        result = run_parametric_backtest(
            price_data, annual_universe, spy_data, regime, all_dates, first_date, params
        )
        results_2.append(result)
        print(f"  [{idx+1}/{len(trailing_combos)}] trail_act={ta:.0%}, trail_stop={ts:.0%}: "
              f"{result['cagr']:.2%} | {result['sharpe']:.3f} | {result['max_dd']:.1%}")

    results_2.sort(key=lambda x: x['cagr'], reverse=True)
    best_final = results_2[0]
    bfp = best_final['params']

    # ================================================================
    # PHASE 3: Also try leverage range tuning
    # ================================================================
    print("\n" + "=" * 80)
    print("PHASE 3: LEVERAGE RANGE TUNING")
    print("=" * 80)

    lev_combos = list(product(
        [0.3, 0.5, 0.7],    # leverage min
        [1.5, 2.0, 2.5, 3.0],  # leverage max
    ))
    results_3 = []
    for idx, (lmin, lmax) in enumerate(lev_combos):
        if lmin >= lmax:
            continue
        params = dict(bfp)
        params['leverage_min'] = lmin
        params['leverage_max'] = lmax
        result = run_parametric_backtest(
            price_data, annual_universe, spy_data, regime, all_dates, first_date, params
        )
        results_3.append(result)
        print(f"  [{idx+1}/{len(lev_combos)}] lev=[{lmin:.1f}, {lmax:.1f}]: "
              f"{result['cagr']:.2%} | {result['sharpe']:.3f} | {result['max_dd']:.1%}")

    results_3.sort(key=lambda x: x['cagr'], reverse=True)
    best_lev = results_3[0]
    blp = best_lev['params']

    # ================================================================
    # FINAL COMPARISON
    # ================================================================

    # Pick the overall best
    all_results = results_1a + results_1b + results_2 + results_3
    all_results.sort(key=lambda x: x['cagr'], reverse=True)
    champion = all_results[0]
    cp = champion['params']

    print("\n" + "=" * 80)
    print("FINAL RESULTS: VORTEX v3 vs COMPASS v8.2")
    print("=" * 80)

    print(f"\n  CHAMPION CONFIG:")
    print(f"    Momentum lookback: {cp['momentum_lookback']}d")
    print(f"    Momentum skip:     {cp['momentum_skip']}d")
    print(f"    Hold days:         {cp['hold_days']}d")
    print(f"    Positions:         {cp['num_positions']}")
    print(f"    Target vol:        {cp['target_vol']:.0%}")
    ta = cp.get('trailing_activation', 0.05)
    ts = cp.get('trailing_stop_pct', 0.03)
    lmin = cp.get('leverage_min', 0.3)
    lmax = cp.get('leverage_max', 2.0)
    print(f"    Trailing:          +{ta:.0%} / -{ts:.0%}")
    print(f"    Leverage range:    [{lmin:.1f}, {lmax:.1f}]")

    # Comparison table
    c_final = champion['final']
    c_cagr = champion['cagr']
    c_sharpe = champion['sharpe']
    c_sortino = champion['sortino']
    c_dd = champion['max_dd']
    c_calmar = champion['calmar']
    c_wr = champion['wr']
    c_trades = champion['trades']
    c_stops = champion['stops']
    c_best = champion['best_yr']
    c_worst = champion['worst_yr']

    print(f"\n  {'Metric':<20} {'COMPASS':>15} {'VORTEX v3':>15} {'Delta':>15}")
    print("  " + "-" * 65)
    v_final = f"${c_final:,.0f}"
    print(f"  {'Final Value':<20} {'$4,822,626':>15} {v_final:>15}")
    print(f"  {'CAGR':<20} {'16.04%':>15} {c_cagr:>14.2%} {c_cagr-0.1604:>+14.2%}")
    print(f"  {'Sharpe':<20} {'0.770':>15} {c_sharpe:>15.3f} {c_sharpe-0.770:>+15.3f}")
    print(f"  {'Sortino':<20} {'0.987':>15} {c_sortino:>15.3f} {c_sortino-0.987:>+15.3f}")
    print(f"  {'Max DD':<20} {'-28.8%':>15} {c_dd:>14.1%} {c_dd+0.288:>+14.1%}")
    print(f"  {'Calmar':<20} {'0.557':>15} {c_calmar:>15.3f} {c_calmar-0.557:>+15.3f}")
    print(f"  {'Win Rate':<20} {'55.3%':>15} {c_wr:>14.1%}")
    print(f"  {'Trades':<20} {'5,386':>15} {c_trades:>15,}")
    print(f"  {'Stops':<20} {'11':>15} {c_stops:>15}")
    print(f"  {'Best Year':<20} {'110.2%':>15} {c_best:>14.1%}")
    print(f"  {'Worst Year':<20} {'-27.5%':>15} {c_worst:>14.1%}")

    winner = "VORTEX v3" if c_cagr > 0.1604 else "COMPASS"
    print(f"\n  >>> CAGR WINNER: {winner} <<<")

    if c_cagr > 0.1604:
        delta = c_cagr - 0.1604
        print(f"  >>> VORTEX v3 BEATS COMPASS BY {delta:.2%} CAGR <<<")
    else:
        delta = 0.1604 - c_cagr
        print(f"  >>> COMPASS STILL WINS BY {delta:.2%} CAGR <<<")

    # Save all results
    os.makedirs('backtests', exist_ok=True)
    summary = []
    for r in all_results[:50]:
        p = r['params']
        summary.append({
            'lookback': p['momentum_lookback'],
            'skip': p['momentum_skip'],
            'hold': p['hold_days'],
            'positions': p['num_positions'],
            'target_vol': p['target_vol'],
            'trail_act': p.get('trailing_activation', 0.05),
            'trail_stop': p.get('trailing_stop_pct', 0.03),
            'lev_min': p.get('leverage_min', 0.3),
            'lev_max': p.get('leverage_max', 2.0),
            'cagr': r['cagr'],
            'sharpe': r['sharpe'],
            'sortino': r['sortino'],
            'max_dd': r['max_dd'],
            'calmar': r['calmar'],
            'trades': r['trades'],
            'win_rate': r['wr'],
            'final_value': r['final'],
        })
    pd.DataFrame(summary).to_csv('backtests/vortex_v3_sweep_results.csv', index=False)
    print(f"\n  Sweep results saved: backtests/vortex_v3_sweep_results.csv")

    # WARNING about overfitting
    print("\n" + "=" * 80)
    print("  [!] OVERFITTING WARNING")
    print("  The champion config was found via in-sample optimization.")
    print("  True out-of-sample performance will likely be 2-5% lower CAGR.")
    print("  COMPASS v8.2 was designed with academic priors, not data-mined.")
    print("=" * 80)
