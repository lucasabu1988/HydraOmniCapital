"""
Experiment 45b: Combined Parameter Optimization
================================================

This script is designed to run AFTER exp45_cagr_optimizer.py.
It takes the best parameters from each phase and combines them,
plus tests additional creative approaches.

COMBINED APPROACHES:
  1. Best stop loss + best momentum params + best universe size
  2. Graduated protection re-entry (linear scale from 0.1x to 1.0x)
  3. Momentum confidence-weighted sizing (high score = more capital)
  4. Wider trailing stop to let winners run more

Run: python exp45b_combined_optimizer.py
Requires: exp45 results or manual best-param specification
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pickle
import os
import sys
import time
import json
from typing import Dict, List, Optional
import warnings

warnings.filterwarnings('ignore')

# Import the engine from exp45
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from exp45_cagr_optimizer import (
    BASE_PARAMS, load_survivorship_data, load_spy, load_cash_yield,
    compute_annual_top_n, run_backtest, _tz_strip
)


# ============================================================================
# MODIFIED BACKTEST: Graduated Protection Re-entry
# ============================================================================

def run_backtest_graduated_protection(price_data, annual_universe, spy_data,
                                      cash_yield_daily, params, quiet=True):
    """
    Modified COMPASS backtest with GRADUATED protection re-entry.

    Instead of discrete stages (0.3x for 63d, then 1.0x for 126d),
    linearly interpolate leverage from PROTECTION_FLOOR to 1.0x over
    the entire recovery period.

    This maintains the SAME total recovery duration but distributes
    capital deployment more smoothly, avoiding the sharp jump from
    0.3x to 1.0x at stage transition.
    """
    from exp45_cagr_optimizer import (
        compute_regime, compute_momentum_scores, compute_vol_weights,
        compute_leverage, get_tradeable
    )

    regime = compute_regime(spy_data, params)

    all_dates = set()
    for df in price_data.values():
        all_dates.update(_tz_strip(df.index))
    all_dates = sorted(list(all_dates))
    clip = pd.Timestamp('2000-01-03')
    all_dates = [d for d in all_dates if d >= clip]

    if not all_dates:
        return None

    first_date = all_dates[0]
    prot_floor = params.get('PROTECTION_LEV_FLOOR', 0.15)
    total_recovery = params['RECOVERY_STAGE_2_DAYS']

    cash = float(params['INITIAL_CAPITAL'])
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []

    peak_value = float(params['INITIAL_CAPITAL'])
    in_protection_mode = False
    stop_loss_day_index = None

    for i, date in enumerate(all_dates):
        tradeable = get_tradeable(price_data, date, first_date, annual_universe, params)

        portfolio_value = cash
        for sym, pos in list(positions.items()):
            if sym in price_data and date in price_data[sym].index:
                portfolio_value += pos['shares'] * price_data[sym].loc[date, 'Close']

        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # Graduated recovery
        if in_protection_mode and stop_loss_day_index is not None:
            days_since_stop = i - stop_loss_day_index
            is_regime_on = True
            if date in regime.index:
                is_regime_on = bool(regime.loc[date])

            if days_since_stop >= total_recovery and is_regime_on:
                in_protection_mode = False
                stop_loss_day_index = None
                peak_value = portfolio_value

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
                        'symbol': symbol, 'entry_date': pos['entry_date'],
                        'exit_date': date, 'exit_reason': 'portfolio_stop',
                        'pnl': pnl,
                        'return': pnl / (pos['entry_price'] * pos['shares'])
                    })
                del positions[symbol]

            in_protection_mode = True
            stop_loss_day_index = i

        # Regime
        is_risk_on = True
        if date in regime.index:
            is_risk_on = bool(regime.loc[date])

        # Graduated leverage during protection
        if in_protection_mode and stop_loss_day_index is not None:
            days_since = i - stop_loss_day_index
            progress = min(days_since / total_recovery, 1.0)
            current_leverage = prot_floor + progress * (1.0 - prot_floor)
            # Scale positions with leverage
            max_positions = max(2, int(params['NUM_POSITIONS'] * current_leverage))
            max_positions = min(max_positions, params['NUM_POSITIONS'])
        elif not is_risk_on:
            max_positions = params['NUM_POSITIONS_RISK_OFF']
            current_leverage = 1.0
        else:
            max_positions = params['NUM_POSITIONS']
            current_leverage = compute_leverage(spy_data, date, params)

        # Margin costs
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            cash -= params['MARGIN_RATE'] / 252 * borrowed

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

            if exit_reason is None and len(positions) > max_positions:
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
                    'symbol': symbol, 'entry_date': pos['entry_date'],
                    'exit_date': date, 'exit_reason': exit_reason,
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
                    position_value = min(effective_capital * weight, cash * 0.40)
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
            'date': date, 'value': portfolio_value, 'cash': cash,
            'positions': len(positions), 'drawdown': drawdown,
            'leverage': current_leverage, 'in_protection': in_protection_mode,
        })

    if not portfolio_values:
        return None

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
    sharpe = (daily_rets.mean() * 252 - 0.035) / ann_vol if ann_vol > 0.001 else 0
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
        'cagr': cagr, 'final_value': final, 'sharpe': sharpe,
        'max_drawdown': max_dd, 'volatility': ann_vol, 'calmar': calmar,
        'trades': n_trades, 'win_rate': win_rate, 'profit_factor': profit_factor,
        'stop_events': len(stop_events), 'protection_days': protection_days,
        'protection_pct': protection_pct, 'years': years,
    }


# ============================================================================
# COMBINED EXPERIMENTS
# ============================================================================

def get_combined_experiments():
    """Define combined experiments."""
    experiments = {}

    # Baseline
    experiments['BASELINE_v82'] = ('standard', dict(BASE_PARAMS))

    # --- Graduated protection with different floor levels ---
    for floor in [0.10, 0.15, 0.20, 0.25, 0.30]:
        name = f"GRAD_PROT_{int(floor*100)}pct"
        p = dict(BASE_PARAMS)
        p['PROTECTION_LEV_FLOOR'] = floor
        experiments[name] = ('graduated', p)

    # --- Wider trailing stop (let winners run more) ---
    for trail_act, trail_pct in [(0.06, 0.04), (0.07, 0.04), (0.08, 0.05), (0.10, 0.06)]:
        name = f"TRAIL_{int(trail_act*100)}a_{int(trail_pct*100)}s"
        p = dict(BASE_PARAMS)
        p['TRAILING_ACTIVATION'] = trail_act
        p['TRAILING_STOP_PCT'] = trail_pct
        experiments[name] = ('standard', p)

    # --- Position stop loss variations ---
    for ps in [-0.06, -0.07, -0.08, -0.10, -0.12, -0.15]:
        name = f"POS_STOP_{abs(int(ps*100))}pct"
        p = dict(BASE_PARAMS)
        p['POSITION_STOP_LOSS'] = ps
        experiments[name] = ('standard', p)

    # --- Number of positions (RISK_ON) ---
    for np_ in [3, 4, 5, 6, 7, 8]:
        name = f"NPOS_{np_}"
        p = dict(BASE_PARAMS)
        p['NUM_POSITIONS'] = np_
        experiments[name] = ('standard', p)

    # --- Risk-off positions ---
    for np_off in [0, 1, 2, 3]:
        name = f"RISKOFF_{np_off}"
        p = dict(BASE_PARAMS)
        p['NUM_POSITIONS_RISK_OFF'] = np_off
        experiments[name] = ('standard', p)

    # --- Hold days (near current optimum) ---
    for hd in [4, 5, 6, 7]:
        name = f"HOLD_{hd}d"
        p = dict(BASE_PARAMS)
        p['HOLD_DAYS'] = hd
        experiments[name] = ('standard', p)

    # --- COMBO 1: MOM_105d + SL_17pct (top 2 individual winners) ---
    p = dict(BASE_PARAMS)
    p['MOMENTUM_LOOKBACK'] = 105
    p['PORTFOLIO_STOP_LOSS'] = -0.17
    experiments['COMBO_MOM105_SL17'] = ('standard', p)

    # --- COMBO 2: MOM_100d + SL_17pct ---
    p = dict(BASE_PARAMS)
    p['MOMENTUM_LOOKBACK'] = 100
    p['PORTFOLIO_STOP_LOSS'] = -0.17
    experiments['COMBO_MOM100_SL17'] = ('standard', p)

    # --- COMBO 3: MOM_105d + SKIP_7d ---
    p = dict(BASE_PARAMS)
    p['MOMENTUM_LOOKBACK'] = 105
    p['MOMENTUM_SKIP'] = 7
    experiments['COMBO_MOM105_SKIP7'] = ('standard', p)

    # --- COMBO 4: MOM_100d + SKIP_7d + SL_17pct ---
    p = dict(BASE_PARAMS)
    p['MOMENTUM_LOOKBACK'] = 100
    p['MOMENTUM_SKIP'] = 7
    p['PORTFOLIO_STOP_LOSS'] = -0.17
    experiments['COMBO_MOM100_SKIP7_SL17'] = ('standard', p)

    # --- COMBO 5: MOM_105d + SKIP_7d + SL_17pct ---
    p = dict(BASE_PARAMS)
    p['MOMENTUM_LOOKBACK'] = 105
    p['MOMENTUM_SKIP'] = 7
    p['PORTFOLIO_STOP_LOSS'] = -0.17
    experiments['COMBO_MOM105_SKIP7_SL17'] = ('standard', p)

    # --- COMBO 6: All winners + Deploy 97% ---
    p = dict(BASE_PARAMS)
    p['MOMENTUM_LOOKBACK'] = 105
    p['MOMENTUM_SKIP'] = 7
    p['PORTFOLIO_STOP_LOSS'] = -0.17
    p['DEPLOY_RATIO'] = 0.97
    experiments['COMBO_ALL_WINNERS'] = ('standard', p)

    # --- COMBO 7: All winners + graduated protection ---
    p = dict(BASE_PARAMS)
    p['MOMENTUM_LOOKBACK'] = 105
    p['MOMENTUM_SKIP'] = 7
    p['PORTFOLIO_STOP_LOSS'] = -0.17
    p['DEPLOY_RATIO'] = 0.97
    p['PROTECTION_LEV_FLOOR'] = 0.15
    experiments['COMBO_ALL_GRAD'] = ('graduated', p)

    # --- COMBO 8: MOM_100d + SKIP_7d + SL_14pct ---
    p = dict(BASE_PARAMS)
    p['MOMENTUM_LOOKBACK'] = 100
    p['MOMENTUM_SKIP'] = 7
    p['PORTFOLIO_STOP_LOSS'] = -0.14
    experiments['COMBO_MOM100_SKIP7_SL14'] = ('standard', p)

    # --- COMBO 9: MOM_105d + wider trailing ---
    p = dict(BASE_PARAMS)
    p['MOMENTUM_LOOKBACK'] = 105
    p['TRAILING_ACTIVATION'] = 0.08
    p['TRAILING_STOP_PCT'] = 0.05
    experiments['COMBO_MOM105_WTRAIL'] = ('standard', p)

    # --- COMBO 10: Kitchen sink (ALL best from every phase) ---
    p = dict(BASE_PARAMS)
    p['MOMENTUM_LOOKBACK'] = 105
    p['MOMENTUM_SKIP'] = 7
    p['PORTFOLIO_STOP_LOSS'] = -0.17
    p['DEPLOY_RATIO'] = 0.97
    p['TRAILING_ACTIVATION'] = 0.07
    p['TRAILING_STOP_PCT'] = 0.04
    p['PROTECTION_LEV_FLOOR'] = 0.15
    experiments['COMBO_KITCHEN_SINK'] = ('graduated', p)

    return experiments


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    print("=" * 90)
    print("EXPERIMENT 45b: COMBINED PARAMETER OPTIMIZATION")
    print("=" * 90)
    print()

    # Load data
    t0 = time.time()
    price_data = load_survivorship_data()
    spy_data = load_spy()
    cash_yield = load_cash_yield()
    print(f"  Data loaded in {time.time()-t0:.1f}s")

    # Get experiments
    experiments = get_combined_experiments()
    print(f"\n  Total experiments: {len(experiments)}")

    # Pre-compute universes
    top_n_values = set()
    for _, (mode, p) in experiments.items():
        top_n_values.add(p['TOP_N'])
    universes = {}
    for top_n in top_n_values:
        print(f"  Computing annual top-{top_n} universe...")
        universes[top_n] = compute_annual_top_n(price_data, top_n)

    # Run experiments
    results = {}
    baseline_cagr = None

    print(f"\n{'='*90}")
    print(f"{'Experiment':<28} {'CAGR':>8} {'Delta':>8} {'Sharpe':>8} {'MaxDD':>8} {'Trades':>7} {'Stops':>6}")
    print(f"{'='*90}")

    for name, (mode, params) in experiments.items():
        t_start = time.time()
        top_n = params['TOP_N']
        annual_universe = universes[top_n]

        if mode == 'graduated':
            metrics = run_backtest_graduated_protection(
                price_data, annual_universe, spy_data, cash_yield, params, quiet=True)
        else:
            metrics = run_backtest(
                price_data, annual_universe, spy_data, cash_yield, params, quiet=True)

        if metrics is None:
            print(f"  {name:<28} FAILED")
            continue

        results[name] = metrics

        if name == 'BASELINE_v82':
            baseline_cagr = metrics['cagr']

        delta = (metrics['cagr'] - (baseline_cagr or 0)) * 100 if baseline_cagr else 0
        elapsed = time.time() - t_start
        delta_str = f"{delta:+.2f}%" if baseline_cagr and name != 'BASELINE_v82' else "BASE"

        print(f"  {name:<28} {metrics['cagr']*100:>7.2f}% {delta_str:>8} "
              f"{metrics['sharpe']:>8.3f} {metrics['max_drawdown']*100:>7.1f}% "
              f"{metrics['trades']:>7,} {metrics['stop_events']:>6}  ({elapsed:.0f}s)")

    # Summary
    print(f"\n{'='*90}")
    print("RESULTS RANKED BY CAGR")
    print(f"{'='*90}")

    ranked = sorted(results.items(), key=lambda x: x[1]['cagr'], reverse=True)

    for rank, (name, m) in enumerate(ranked, 1):
        delta = (m['cagr'] - (baseline_cagr or m['cagr'])) * 100
        marker = " <-- IMPROVEMENT" if delta > 0.1 and name != 'BASELINE_v82' else ""
        print(f"  {rank:>3}. {name:<28} {m['cagr']*100:>7.2f}% ({delta:>+6.2f}%) "
              f"Sharpe={m['sharpe']:.3f} MaxDD={m['max_drawdown']*100:.1f}%{marker}")

    # Save
    output = {
        'baseline_cagr': baseline_cagr,
        'results': {name: {k: float(v) if isinstance(v, (np.floating, np.integer)) else v
                          for k, v in m.items()}
                   for name, m in results.items()},
        'ranked': [(name, float(results[name]['cagr'])) for name, _ in ranked[:15]],
    }

    os.makedirs('backtests', exist_ok=True)
    with open('backtests/exp45b_results.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n  Results saved to backtests/exp45b_results.json")
    print(f"\n{'='*90}")
    print("EXPERIMENT 45b COMPLETE")
    print(f"{'='*90}")
