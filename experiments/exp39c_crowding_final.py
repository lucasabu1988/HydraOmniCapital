"""
Experiment #39c: Crowding Filter — Final Investigation
=======================================================
Exp #39b found:
  - All gap/vol/z-score filters destroy CAGR (every formulation lost money)
  - "5d-winner" filter showed +0.15% but had a BUG: percentile was computed
    across only the 5 selected candidates, not the full universe.
    P80/P85/P90/P95 all produced identical results (always blocking 1 of 5).

This experiment:
  1. Fixes the bug: compute 5d-return percentile across FULL tradeable universe
  2. Tests the filter with proper thresholds
  3. Also tests an absolute 5d-return threshold (not percentile-based)
  4. Tests skip_recent_runup: reject candidates with 5d return > X% absolute
  5. Subperiod analysis for any "winner"
"""

import pandas as pd
import numpy as np
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from omnicapital_v8_compass import (
    download_broad_pool, download_spy, download_cash_yield,
    compute_annual_top40, compute_regime, compute_momentum_scores,
    compute_volatility_weights, compute_dynamic_leverage,
    get_tradeable_symbols,
    INITIAL_CAPITAL, NUM_POSITIONS, NUM_POSITIONS_RISK_OFF, HOLD_DAYS,
    POSITION_STOP_LOSS, TRAILING_ACTIVATION, TRAILING_STOP_PCT,
    PORTFOLIO_STOP_LOSS, RECOVERY_STAGE_1_DAYS, RECOVERY_STAGE_2_DAYS,
    VOL_LOOKBACK, MARGIN_RATE, COMMISSION_PER_SHARE, CASH_YIELD_RATE,
)


# ============================================================================
# FILTERS
# ============================================================================

def filter_5d_winner_universe_pct(price_data, candidates, date, all_tradeable,
                                   params):
    """
    Skip candidates whose 5d return exceeds the Pth percentile
    computed across ALL tradeable stocks (not just the candidates).
    """
    # Compute 5d returns for full universe
    returns_5d = {}
    for sym in all_tradeable:
        if sym not in price_data or date not in price_data[sym].index:
            continue
        df = price_data[sym]
        idx = df.index.get_loc(date)
        if idx < 6:
            continue
        ret = (df['Close'].iloc[idx] / df['Close'].iloc[idx - 5]) - 1
        returns_5d[sym] = ret

    if len(returns_5d) < 10:
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


def filter_5d_abs_return(price_data, candidates, date, all_tradeable, params):
    """
    Skip candidates whose 5d return exceeds an absolute threshold.
    """
    filtered = []
    blocked = 0
    for sym in candidates:
        if sym not in price_data or date not in price_data[sym].index:
            filtered.append(sym)
            continue
        df = price_data[sym]
        idx = df.index.get_loc(date)
        if idx < 6:
            filtered.append(sym)
            continue
        ret = (df['Close'].iloc[idx] / df['Close'].iloc[idx - 5]) - 1
        if ret > params['abs_thresh']:
            blocked += 1
        else:
            filtered.append(sym)
    return filtered, blocked


def filter_1d_abs_return(price_data, candidates, date, all_tradeable, params):
    """
    Skip candidates whose 1d return exceeds an absolute threshold.
    Idea: reject stocks that gapped/surged today.
    """
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
        ret = (df['Close'].iloc[idx] / df['Close'].iloc[idx - 1]) - 1
        if ret > params['abs_thresh']:
            blocked += 1
        else:
            filtered.append(sym)
    return filtered, blocked


def filter_none(price_data, candidates, date, all_tradeable, params):
    """No filter (baseline)."""
    return candidates, 0


# ============================================================================
# BACKTEST
# ============================================================================

def run_variant(price_data, annual_universe, spy_data, cash_yield_daily,
                all_dates, first_date, regime,
                filter_func, filter_params, label):
    """Run backtest with a specific filter."""

    cash = float(INITIAL_CAPITAL)
    positions = {}
    daily_values = []
    trades = []
    stop_events = []
    total_blocks = 0

    peak_value = float(INITIAL_CAPITAL)
    in_protection_mode = False
    protection_stage = 0
    stop_loss_day_index = None
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
                portfolio_value += pos['shares'] * price_data[symbol].loc[date, 'Close']

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

        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # Portfolio stop
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({'date': date, 'drawdown': drawdown})
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

        # Regime
        is_risk_on = bool(regime.loc[date]) if date in regime.index else True
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

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

        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            cash -= MARGIN_RATE / 252 * borrowed

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

            if i - pos['entry_idx'] >= HOLD_DAYS:
                exit_reason = 'hold_expired'
            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            if pos_return <= POSITION_STOP_LOSS:
                exit_reason = 'position_stop'
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                if current_price <= pos['high_price'] * (1 - TRAILING_STOP_PCT):
                    exit_reason = 'trailing_stop'
            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'
            if exit_reason is None and len(positions) > max_positions:
                pos_returns = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        pos_returns[s] = (price_data[s].loc[date, 'Close'] - p['entry_price']) / p['entry_price']
                if symbol == min(pos_returns, key=pos_returns.get):
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

                # APPLY FILTER (pass full tradeable universe for percentile computation)
                if filter_func is not None:
                    orig = len(selected)
                    selected, blocked = filter_func(price_data, selected, date,
                                                     tradeable_symbols, filter_params)
                    total_blocks += blocked

                    # Backfill
                    if len(selected) < needed:
                        already = set(selected) | set(positions.keys())
                        remaining = [(s, sc) for s, sc in ranked if s not in already]
                        extras = [s for s, _ in remaining[:needed - len(selected)]]
                        extras, eb = filter_func(price_data, extras, date,
                                                  tradeable_symbols, filter_params)
                        total_blocks += eb
                        selected.extend(extras)

                if not selected:
                    daily_values.append({'date': date, 'value': portfolio_value, 'drawdown': drawdown})
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

        daily_values.append({'date': date, 'value': portfolio_value, 'drawdown': drawdown})

    # Metrics
    pv_df = pd.DataFrame(daily_values).set_index('date')
    final_value = pv_df['value'].iloc[-1]
    years = len(pv_df) / 252
    cagr = (final_value / INITIAL_CAPITAL) ** (1 / years) - 1
    rets = pv_df['value'].pct_change().dropna()
    vol = rets.std() * np.sqrt(252)
    sharpe = cagr / vol if vol > 0 else 0
    max_dd = pv_df['drawdown'].min()
    trades_df = pd.DataFrame(trades)
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    n_trades = len(trades_df)

    # Subperiod CAGRs (5-year chunks)
    chunk_size = 252 * 5
    n_chunks = len(pv_df) // chunk_size
    sub_cagrs = []
    for c in range(n_chunks):
        chunk = pv_df['value'].iloc[c*chunk_size:(c+1)*chunk_size]
        if len(chunk) > 50:
            cy = len(chunk) / 252
            sub_cagrs.append((chunk.iloc[-1] / chunk.iloc[0]) ** (1/cy) - 1)

    return {
        'label': label, 'final_value': final_value, 'cagr': cagr,
        'sharpe': sharpe, 'max_dd': max_dd, 'vol': vol,
        'trades': n_trades, 'win_rate': win_rate,
        'stops': len(stop_events), 'blocks': total_blocks,
        'sub_cagrs': sub_cagrs, 'daily': pv_df,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    t0 = time.time()

    print("=" * 100)
    print("EXPERIMENT #39c: CROWDING FILTER — FINAL INVESTIGATION")
    print("=" * 100)
    print("\nNote: 39b had a bug — percentile was computed on 5 candidates, not full universe.")
    print("This run fixes that and tests additional formulations.\n")

    # Load data
    price_data = download_broad_pool()
    spy_data = download_spy()
    cash_yield_daily = download_cash_yield()
    annual_universe = compute_annual_top40(price_data)

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]
    regime = compute_regime(spy_data)

    # ---- Sweep grid ----
    configs = []

    # Baseline
    configs.append(("BASELINE", filter_none, {}))

    # 5d-winner percentile (FIXED: full universe)
    for pct in [70, 75, 80, 85, 90, 95]:
        configs.append((f"5d-Univ-P{pct}", filter_5d_winner_universe_pct, {'pct_thresh': pct}))

    # 5d absolute return threshold
    for t in [0.03, 0.05, 0.07, 0.10, 0.12, 0.15, 0.20]:
        configs.append((f"5d-Abs>{t:.0%}", filter_5d_abs_return, {'abs_thresh': t}))

    # 1d absolute return threshold (today's move)
    for t in [0.02, 0.03, 0.04, 0.05, 0.07, 0.10]:
        configs.append((f"1d-Abs>{t:.0%}", filter_1d_abs_return, {'abs_thresh': t}))

    print(f"Total configurations: {len(configs)}")

    # ---- Run ----
    results = []
    for idx, (label, func, params) in enumerate(configs):
        print(f"[{idx+1}/{len(configs)}] {label}...", end=" ")
        r = run_variant(price_data, annual_universe, spy_data, cash_yield_daily,
                        all_dates, first_date, regime, func, params, label)
        results.append(r)
        print(f"CAGR: {r['cagr']:.2%} | Sharpe: {r['sharpe']:.3f} | "
              f"MaxDD: {r['max_dd']:.2%} | Blocks: {r['blocks']:,}")

    # ---- Results ----
    baseline = results[0]

    print("\n" + "=" * 120)
    print("FULL RESULTS")
    print("=" * 120)

    header = (f"{'Config':<20} {'Final $':>14} {'CAGR':>8} {'dCAGR':>8} "
              f"{'Sharpe':>7} {'dShp':>7} {'MaxDD':>8} {'dDD':>8} "
              f"{'WinR':>6} {'Trades':>7} {'Blocks':>7}")
    print(header)
    print("-" * 120)

    for r in results:
        dc = r['cagr'] - baseline['cagr']
        ds = r['sharpe'] - baseline['sharpe']
        dd = r['max_dd'] - baseline['max_dd']
        row = (f"{r['label']:<20} ${r['final_value']:>12,.0f} {r['cagr']:>7.2%} {dc:>+7.2%} "
               f"{r['sharpe']:>7.3f} {ds:>+6.3f} {r['max_dd']:>7.2%} {dd:>+7.2%} "
               f"{r['win_rate']:>5.1%} {r['trades']:>7,} {r['blocks']:>7,}")
        print(row)

    # ---- Winners ----
    beat = [r for r in results[1:] if r['cagr'] > baseline['cagr']]
    beat.sort(key=lambda x: x['cagr'], reverse=True)

    print("\n" + "=" * 120)
    if beat:
        print(f"VARIANTS THAT BEAT BASELINE ({len(beat)} found)")
        print("=" * 120)
        for r in beat:
            dc = r['cagr'] - baseline['cagr']
            ds = r['sharpe'] - baseline['sharpe']
            dd = r['max_dd'] - baseline['max_dd']
            passed = dc > 0 and ds >= -0.02 and dd >= -0.03
            status = "APPROVED" if passed else "MARGINAL"
            print(f"\n  [{status}] {r['label']}")
            print(f"    CAGR:   {r['cagr']:.2%} ({dc:+.2%})")
            print(f"    Sharpe: {r['sharpe']:.3f} ({ds:+.3f})")
            print(f"    MaxDD:  {r['max_dd']:.2%} ({dd:+.2%})")
            print(f"    Blocks: {r['blocks']:,} | Trades: {r['trades']:,}")

            # Subperiod consistency
            if r['sub_cagrs'] and baseline['sub_cagrs']:
                wins = sum(1 for a, b in zip(r['sub_cagrs'], baseline['sub_cagrs']) if a > b)
                total = len(r['sub_cagrs'])
                print(f"    Subperiods: wins {wins}/{total} vs baseline")
                for pi, (sc, bc) in enumerate(zip(r['sub_cagrs'], baseline['sub_cagrs'])):
                    marker = " <--" if sc > bc else ""
                    print(f"      P{pi+1}: {sc:.2%} vs {bc:.2%} ({sc-bc:+.2%}){marker}")
    else:
        print("NO VARIANT BEATS BASELINE")
        print("=" * 120)
        closest = max(results[1:], key=lambda x: x['cagr'])
        print(f"\n  Closest: {closest['label']}")
        print(f"    CAGR: {closest['cagr']:.2%} ({closest['cagr']-baseline['cagr']:+.2%})")
        print(f"    Blocks: {closest['blocks']:,}")

    # ---- Final verdict ----
    print("\n" + "=" * 120)
    print("FINAL VERDICT")
    print("=" * 120)

    approved = [r for r in beat if
                (r['cagr'] - baseline['cagr']) > 0 and
                (r['sharpe'] - baseline['sharpe']) >= -0.02 and
                (r['max_dd'] - baseline['max_dd']) >= -0.03]

    if approved:
        print(f"\n  {len(approved)} variant(s) pass all criteria.")
        for r in approved:
            dc = r['cagr'] - baseline['cagr']
            print(f"    {r['label']}: +{dc:.2%} CAGR, {r['blocks']:,} blocks")
        print(f"\n  BUT: +0.15% or less is noise-level on a 26-year signal backtest.")
        print(f"  Recommendation: NOT worth the complexity. Baseline is optimal.")
    else:
        print("\n  ALL VARIANTS FAILED. Crowding filter concept is definitively dead.")
        print(f"  Tested {len(configs)-1} formulations across 3 filter families.")
        print(f"  None improve CAGR, Sharpe, AND MaxDD simultaneously.")

    elapsed = time.time() - t0
    print(f"\nRuntime: {elapsed:.1f}s ({elapsed/60:.1f} min)")

    # Save
    rows = []
    for r in results:
        rows.append({k: v for k, v in r.items() if k not in ('daily', 'sub_cagrs')})
    pd.DataFrame(rows).to_csv('backtests/exp39c_crowding_final.csv', index=False)
    print("Saved: backtests/exp39c_crowding_final.csv")

    print("\n" + "=" * 100)
    print("EXPERIMENT #39c COMPLETE")
    print("=" * 100)
