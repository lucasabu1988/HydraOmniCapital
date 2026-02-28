"""
Experiment #39b: Crowding Filter Deep Sweep
============================================
The original crowding filter (Exp #39) only blocked 27 entries in 26 years.
Problem: requiring gap AND vol explosion AND z>2 simultaneously is too rare.

This sweep tests multiple crowding filter formulations:
  1. Z-score only: skip stocks with momentum z > threshold (no microstructure)
  2. Vol explosion only: skip stocks where today's range > Nx avg range
  3. Gap only: skip stocks with overnight gap > threshold
  4. Z + Vol (original minus gap requirement)
  5. Z + Gap (original minus vol requirement)
  6. Full original (Z + Gap + Vol) with loosened thresholds
  7. Momentum percentile filter: skip stocks above Pth percentile of 5d return
     (recent winners that already ran — the skip_5d component catches this partially
      but the filter would reject them entirely rather than just penalize scoring)

Sweep grid for each formulation across multiple threshold levels.
"""

import pandas as pd
import numpy as np
import os
import sys
import time
from itertools import product

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from omnicapital_v8_compass import (
    download_broad_pool, download_spy, download_cash_yield,
    compute_annual_top40, compute_regime, compute_momentum_scores,
    compute_volatility_weights, compute_dynamic_leverage,
    get_tradeable_symbols,
    INITIAL_CAPITAL, NUM_POSITIONS, NUM_POSITIONS_RISK_OFF, HOLD_DAYS,
    POSITION_STOP_LOSS, TRAILING_ACTIVATION, TRAILING_STOP_PCT,
    PORTFOLIO_STOP_LOSS, RECOVERY_STAGE_1_DAYS, RECOVERY_STAGE_2_DAYS,
    LEVERAGE_MIN, LEVERAGE_MAX, VOL_LOOKBACK,
    MARGIN_RATE, COMMISSION_PER_SHARE, CASH_YIELD_RATE,
)


# ============================================================================
# CROWDING FILTER VARIANTS
# ============================================================================

def crowding_filter_zscore_only(price_data, candidates, date, momentum_scores, params):
    """Skip stocks with momentum z-score above threshold."""
    if len(momentum_scores) < 5:
        return candidates, 0

    all_scores = np.array(list(momentum_scores.values()))
    mean_s = np.mean(all_scores)
    std_s = np.std(all_scores)
    if std_s < 1e-8:
        return candidates, 0

    filtered = []
    blocked = 0
    for sym in candidates:
        z = (momentum_scores.get(sym, mean_s) - mean_s) / std_s
        if z > params['z_thresh']:
            blocked += 1
        else:
            filtered.append(sym)
    return filtered, blocked


def crowding_filter_vol_only(price_data, candidates, date, momentum_scores, params):
    """Skip stocks where today's range > Nx average range."""
    filtered = []
    blocked = 0
    for sym in candidates:
        if sym not in price_data or date not in price_data[sym].index:
            filtered.append(sym)
            continue
        df = price_data[sym]
        idx = df.index.get_loc(date)
        if idx < VOL_LOOKBACK + 2:
            filtered.append(sym)
            continue

        today_range = df['High'].iloc[idx] - df['Low'].iloc[idx]
        avg_range = (df['High'].iloc[idx - VOL_LOOKBACK:idx] -
                     df['Low'].iloc[idx - VOL_LOOKBACK:idx]).mean()

        if avg_range > 0 and today_range / avg_range > params['vol_mult']:
            blocked += 1
        else:
            filtered.append(sym)
    return filtered, blocked


def crowding_filter_gap_only(price_data, candidates, date, momentum_scores, params):
    """Skip stocks with overnight gap above threshold."""
    filtered = []
    blocked = 0
    for sym in candidates:
        if sym not in price_data or date not in price_data[sym].index:
            filtered.append(sym)
            continue
        df = price_data[sym]
        idx = df.index.get_loc(date)
        if idx < 2:
            filtered.append(sym)
            continue

        gap = abs(df['Open'].iloc[idx] - df['Close'].iloc[idx - 1])
        if df['Close'].iloc[idx - 1] > 0:
            gap_pct = gap / df['Close'].iloc[idx - 1]
        else:
            gap_pct = 0

        if gap_pct > params['gap_thresh']:
            blocked += 1
        else:
            filtered.append(sym)
    return filtered, blocked


def crowding_filter_z_vol(price_data, candidates, date, momentum_scores, params):
    """Skip stocks with z-score > threshold AND vol explosion."""
    if len(momentum_scores) < 5:
        return candidates, 0

    all_scores = np.array(list(momentum_scores.values()))
    mean_s = np.mean(all_scores)
    std_s = np.std(all_scores)
    if std_s < 1e-8:
        return candidates, 0

    filtered = []
    blocked = 0
    for sym in candidates:
        z = (momentum_scores.get(sym, mean_s) - mean_s) / std_s

        if z <= params['z_thresh']:
            filtered.append(sym)
            continue

        if sym not in price_data or date not in price_data[sym].index:
            filtered.append(sym)
            continue
        df = price_data[sym]
        idx = df.index.get_loc(date)
        if idx < VOL_LOOKBACK + 2:
            filtered.append(sym)
            continue

        today_range = df['High'].iloc[idx] - df['Low'].iloc[idx]
        avg_range = (df['High'].iloc[idx - VOL_LOOKBACK:idx] -
                     df['Low'].iloc[idx - VOL_LOOKBACK:idx]).mean()

        if avg_range > 0 and today_range / avg_range > params['vol_mult']:
            blocked += 1
        else:
            filtered.append(sym)
    return filtered, blocked


def crowding_filter_z_gap(price_data, candidates, date, momentum_scores, params):
    """Skip stocks with z-score > threshold AND overnight gap."""
    if len(momentum_scores) < 5:
        return candidates, 0

    all_scores = np.array(list(momentum_scores.values()))
    mean_s = np.mean(all_scores)
    std_s = np.std(all_scores)
    if std_s < 1e-8:
        return candidates, 0

    filtered = []
    blocked = 0
    for sym in candidates:
        z = (momentum_scores.get(sym, mean_s) - mean_s) / std_s

        if z <= params['z_thresh']:
            filtered.append(sym)
            continue

        if sym not in price_data or date not in price_data[sym].index:
            filtered.append(sym)
            continue
        df = price_data[sym]
        idx = df.index.get_loc(date)
        if idx < 2:
            filtered.append(sym)
            continue

        gap = abs(df['Open'].iloc[idx] - df['Close'].iloc[idx - 1])
        if df['Close'].iloc[idx - 1] > 0:
            gap_pct = gap / df['Close'].iloc[idx - 1]
        else:
            gap_pct = 0

        if gap_pct > params['gap_thresh']:
            blocked += 1
        else:
            filtered.append(sym)
    return filtered, blocked


def crowding_filter_recent_winner(price_data, candidates, date, momentum_scores, params):
    """Skip stocks where 5d return is in top percentile (already ran too much)."""
    returns_5d = {}
    for sym in candidates:
        if sym not in price_data or date not in price_data[sym].index:
            continue
        df = price_data[sym]
        idx = df.index.get_loc(date)
        if idx < 6:
            continue
        ret = (df['Close'].iloc[idx] / df['Close'].iloc[idx - 5]) - 1
        returns_5d[sym] = ret

    if len(returns_5d) < 3:
        return candidates, 0

    threshold = np.percentile(list(returns_5d.values()), params['pct_thresh'])

    filtered = []
    blocked = 0
    for sym in candidates:
        if sym in returns_5d and returns_5d[sym] > threshold:
            blocked += 1
        else:
            filtered.append(sym)
    return filtered, blocked


# ============================================================================
# BACKTEST ENGINE
# ============================================================================

def run_crowding_variant(price_data, annual_universe, spy_data, cash_yield_daily,
                         all_dates, first_date, regime,
                         filter_func, filter_params, label):
    """Run backtest with a specific crowding filter. Returns metrics dict."""

    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []
    total_blocks = 0

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

        tradeable_symbols = get_tradeable_symbols(price_data, date, all_dates[0], annual_universe)

        # Portfolio value
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # Recovery
        if in_protection_mode and stop_loss_day_index is not None:
            days_since_stop = i - stop_loss_day_index
            is_regime_on = bool(regime.loc[date]) if date in regime.index else True

            if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and is_regime_on:
                protection_stage = 2
            if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and is_regime_on:
                in_protection_mode = False
                protection_stage = 0
                peak_value = portfolio_value
                stop_loss_day_index = None
                post_stop_base = None

        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # Portfolio stop
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({'date': date, 'portfolio_value': portfolio_value, 'drawdown': drawdown})
            for symbol in list(positions.keys()):
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    pos = positions[symbol]
                    proceeds = pos['shares'] * exit_price
                    commission = pos['shares'] * COMMISSION_PER_SHARE
                    cash += proceeds - commission
                    pnl = (exit_price - pos['entry_price']) * pos['shares'] - commission
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

        # Regime
        is_risk_on = bool(regime.loc[date]) if date in regime.index else True
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # Max positions and leverage
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

        # Margin cost
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            cash -= MARGIN_RATE / 252 * borrowed

        # Cash yield
        if cash > 0:
            if cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

        # Close positions
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
                    'symbol': symbol, 'entry_date': pos['entry_date'],
                    'exit_date': date, 'exit_reason': exit_reason,
                    'pnl': pnl, 'return': pnl / (pos['entry_price'] * shares)
                })
                del positions[symbol]

        # Open new positions
        needed = max_positions - len(positions)

        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            scores = compute_momentum_scores(price_data, tradeable_symbols, date, all_dates, i)
            available_scores = {s: sc for s, sc in scores.items() if s not in positions}

            if len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]

                # === APPLY CROWDING FILTER ===
                if filter_func is not None:
                    original_count = len(selected)
                    selected, blocked = filter_func(price_data, selected, date, scores, filter_params)
                    total_blocks += blocked

                    # Backfill from next-ranked
                    if len(selected) < needed:
                        already = set(selected) | set(positions.keys())
                        remaining = [(s, sc) for s, sc in ranked if s not in already]
                        extras = [s for s, _ in remaining[:needed - len(selected)]]
                        extras, extra_blocked = filter_func(price_data, extras, date, scores, filter_params)
                        total_blocks += extra_blocked
                        selected.extend(extras)

                if not selected:
                    portfolio_values.append({
                        'date': date, 'value': portfolio_value, 'cash': cash,
                        'positions': len(positions), 'drawdown': drawdown,
                    })
                    continue

                weights = compute_volatility_weights(price_data, selected, date)
                effective_capital = cash * current_leverage * 0.95

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
                    commission = shares * COMMISSION_PER_SHARE

                    if cost + commission <= cash * 0.90:
                        positions[symbol] = {
                            'entry_price': entry_price, 'shares': shares,
                            'entry_date': date, 'entry_idx': i,
                            'high_price': entry_price,
                        }
                        cash -= cost + commission

        portfolio_values.append({
            'date': date, 'value': portfolio_value, 'cash': cash,
            'positions': len(positions), 'drawdown': drawdown,
        })

    # Metrics
    pv_df = pd.DataFrame(portfolio_values).set_index('date')
    final_value = pv_df['value'].iloc[-1]
    years = len(pv_df) / 252
    cagr = (final_value / INITIAL_CAPITAL) ** (1 / years) - 1
    returns = pv_df['value'].pct_change().dropna()
    vol = returns.std() * np.sqrt(252)
    sharpe = cagr / vol if vol > 0 else 0
    max_dd = pv_df['drawdown'].min()

    trades_df = pd.DataFrame(trades)
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0

    return {
        'label': label,
        'final_value': final_value,
        'cagr': cagr,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'vol': vol,
        'trades': len(trades_df),
        'win_rate': win_rate,
        'stops': len(stop_events),
        'blocks': total_blocks,
    }


# ============================================================================
# MAIN — SWEEP
# ============================================================================

if __name__ == "__main__":
    t0 = time.time()

    print("=" * 100)
    print("EXPERIMENT #39b: CROWDING FILTER DEEP SWEEP")
    print("=" * 100)

    # Load data
    print("\n--- Loading data ---")
    price_data = download_broad_pool()
    spy_data = download_spy()
    cash_yield_daily = download_cash_yield()
    annual_universe = compute_annual_top40(price_data)

    # Precompute shared data
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]
    regime = compute_regime(spy_data)

    # ---- Define sweep grid ----
    sweep_configs = []

    # BASELINE
    sweep_configs.append(("BASELINE", None, {}))

    # 1. Z-score only: various thresholds
    for z in [1.0, 1.5, 2.0, 2.5, 3.0]:
        sweep_configs.append(
            (f"Z-only z>{z:.1f}", crowding_filter_zscore_only, {'z_thresh': z})
        )

    # 2. Vol explosion only: various multipliers
    for vm in [1.5, 2.0, 2.5, 3.0]:
        sweep_configs.append(
            (f"Vol-only >{vm:.1f}x", crowding_filter_vol_only, {'vol_mult': vm})
        )

    # 3. Gap only: various thresholds
    for g in [0.01, 0.02, 0.03, 0.04]:
        sweep_configs.append(
            (f"Gap-only >{g:.0%}", crowding_filter_gap_only, {'gap_thresh': g})
        )

    # 4. Z + Vol (no gap requirement)
    for z, vm in [(1.5, 1.5), (1.5, 2.0), (2.0, 1.5), (2.0, 2.0)]:
        sweep_configs.append(
            (f"Z>{z:.1f}+Vol>{vm:.1f}x", crowding_filter_z_vol, {'z_thresh': z, 'vol_mult': vm})
        )

    # 5. Z + Gap (no vol requirement)
    for z, g in [(1.5, 0.02), (1.5, 0.03), (2.0, 0.02), (2.0, 0.03)]:
        sweep_configs.append(
            (f"Z>{z:.1f}+Gap>{g:.0%}", crowding_filter_z_gap, {'z_thresh': z, 'gap_thresh': g})
        )

    # 6. Recent winner percentile filter
    for pct in [80, 85, 90, 95]:
        sweep_configs.append(
            (f"5d-winner>P{pct}", crowding_filter_recent_winner, {'pct_thresh': pct})
        )

    print(f"\nTotal configurations: {len(sweep_configs)}")
    print(f"Estimated runtime: ~{len(sweep_configs) * 13 // 60} min")

    # ---- Run sweep ----
    results = []
    for idx, (label, func, params) in enumerate(sweep_configs):
        print(f"\n[{idx+1}/{len(sweep_configs)}] {label}...")
        r = run_crowding_variant(
            price_data, annual_universe, spy_data, cash_yield_daily,
            all_dates, first_date, regime,
            func, params, label
        )
        results.append(r)
        print(f"  CAGR: {r['cagr']:.2%} | Sharpe: {r['sharpe']:.3f} | MaxDD: {r['max_dd']:.2%} | "
              f"Blocks: {r['blocks']:,}")

    # ---- Results table ----
    print("\n" + "=" * 120)
    print("SWEEP RESULTS")
    print("=" * 120)

    baseline = results[0]

    header = (f"{'Config':<25} {'Final $':>14} {'CAGR':>8} {'dCAGR':>8} "
              f"{'Sharpe':>7} {'dShp':>7} {'MaxDD':>8} {'dDD':>8} "
              f"{'WinR':>6} {'Trades':>7} {'Blocks':>7}")
    print(header)
    print("-" * 120)

    for r in results:
        d_cagr = r['cagr'] - baseline['cagr']
        d_sharpe = r['sharpe'] - baseline['sharpe']
        d_dd = r['max_dd'] - baseline['max_dd']

        row = (f"{r['label']:<25} ${r['final_value']:>12,.0f} {r['cagr']:>7.2%} {d_cagr:>+7.2%} "
               f"{r['sharpe']:>7.3f} {d_sharpe:>+6.3f} {r['max_dd']:>7.2%} {d_dd:>+7.2%} "
               f"{r['win_rate']:>5.1%} {r['trades']:>7,} {r['blocks']:>7,}")
        print(row)

    # ---- Best variants ----
    print("\n" + "=" * 120)
    print("TOP 5 BY CAGR (must beat baseline)")
    print("=" * 120)

    sorted_by_cagr = sorted(results[1:], key=lambda x: x['cagr'], reverse=True)
    beat_baseline = [r for r in sorted_by_cagr if r['cagr'] > baseline['cagr']]

    if beat_baseline:
        for r in beat_baseline[:5]:
            d_cagr = r['cagr'] - baseline['cagr']
            d_sharpe = r['sharpe'] - baseline['sharpe']
            d_dd = r['max_dd'] - baseline['max_dd']
            print(f"  {r['label']}: CAGR {r['cagr']:.2%} ({d_cagr:+.2%}) | "
                  f"Sharpe {r['sharpe']:.3f} ({d_sharpe:+.3f}) | "
                  f"MaxDD {r['max_dd']:.2%} ({d_dd:+.2%}) | "
                  f"Blocks: {r['blocks']:,}")
    else:
        print("  NONE beat baseline. All variants degrade CAGR.")

    # ---- Verdict ----
    print("\n" + "=" * 120)
    print("FINAL VERDICT")
    print("=" * 120)

    any_approved = False
    for r in sorted_by_cagr:
        d_cagr = r['cagr'] - baseline['cagr']
        d_sharpe = r['sharpe'] - baseline['sharpe']
        d_dd = r['max_dd'] - baseline['max_dd']

        if d_cagr > 0 and d_sharpe >= -0.02 and d_dd >= -0.03:
            print(f"  APPROVED: {r['label']}")
            print(f"    CAGR: {r['cagr']:.2%} ({d_cagr:+.2%})")
            print(f"    Sharpe: {r['sharpe']:.3f} ({d_sharpe:+.3f})")
            print(f"    MaxDD: {r['max_dd']:.2%} ({d_dd:+.2%})")
            print(f"    Blocks: {r['blocks']:,}")
            any_approved = True

    if not any_approved:
        print("  ALL VARIANTS FAILED. No crowding filter formulation beats baseline.")
        print(f"\n  Baseline: CAGR {baseline['cagr']:.2%} | Sharpe {baseline['sharpe']:.3f} | MaxDD {baseline['max_dd']:.2%}")
        print(f"\n  Best attempt: {sorted_by_cagr[0]['label']}")
        print(f"    CAGR: {sorted_by_cagr[0]['cagr']:.2%} ({sorted_by_cagr[0]['cagr'] - baseline['cagr']:+.2%})")
        print(f"    Blocks: {sorted_by_cagr[0]['blocks']:,}")

    elapsed = time.time() - t0
    print(f"\nTotal runtime: {elapsed:.1f}s ({elapsed/60:.1f} min)")

    # Save results CSV
    results_df = pd.DataFrame(results)
    results_df['d_cagr'] = results_df['cagr'] - baseline['cagr']
    results_df['d_sharpe'] = results_df['sharpe'] - baseline['sharpe']
    results_df['d_maxdd'] = results_df['max_dd'] - baseline['max_dd']
    os.makedirs('backtests', exist_ok=True)
    results_df.to_csv('backtests/exp39b_crowding_sweep.csv', index=False)
    print("Results saved: backtests/exp39b_crowding_sweep.csv")

    print("\n" + "=" * 100)
    print("EXPERIMENT #39b COMPLETE")
    print("=" * 100)
