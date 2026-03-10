"""
HYDRA v8.4 — Dynamic Leverage Optimizer
==================================================================================
Grid search over LEVERAGE_MAX (1.0 → 2.5) × MARGIN_RATE (3%, 4.5%, 6%)
to find the maximum leverage that doesn't degrade Max DD or Sharpe vs baseline.

Constraint: MaxDD >= baseline_DD AND Sharpe >= baseline_Sharpe
Objective: Maximize CAGR within those constraints

Reuses exact v8.4 signal logic from backtest_quarterly_audit.py via import.
Only the leverage cap and margin rate are varied.

NOTE: pickle is used here for data caching (same as other HYDRA backtests).
All cached data is self-generated from yfinance downloads, never from
untrusted sources.
"""

import pandas as pd
import numpy as np
import os
import sys
import time
import pickle
import warnings
warnings.filterwarnings('ignore')

# Import the full v8.4 engine from quarterly audit backtest
# (suppress its print-on-import by redirecting stdout temporarily)
import io
_old_stdout = sys.stdout
sys.stdout = io.StringIO()
try:
    from backtest_quarterly_audit import (
        download_broad_pool,
        download_spy,
        download_cash_yield,
        compute_annual_top40,
        compute_regime_score,
        regime_score_to_positions,
        get_spy_trend_data,
        compute_momentum_scores,
        compute_volatility_weights,
        compute_quality_filter,
        compute_entry_vol,
        compute_adaptive_stop,
        compute_dynamic_leverage,
        compute_smooth_leverage,
        _dd_leverage,
        should_renew_position,
        filter_by_sector_concentration,
        get_tradeable_symbols,
        BROAD_POOL, SECTOR_MAP, TOP_N, MIN_AGE_DAYS,
        MOMENTUM_LOOKBACK, MOMENTUM_SKIP, MIN_MOMENTUM_STOCKS,
        NUM_POSITIONS, NUM_POSITIONS_RISK_OFF, HOLD_DAYS,
        HOLD_DAYS_MAX, RENEWAL_PROFIT_MIN, MOMENTUM_RENEWAL_THRESHOLD,
        QUALITY_VOL_MAX, QUALITY_VOL_LOOKBACK, QUALITY_MAX_SINGLE_DAY,
        DD_SCALE_TIER1, DD_SCALE_TIER2, DD_SCALE_TIER3,
        LEV_FULL, LEV_MID, LEV_FLOOR,
        CRASH_VEL_5D, CRASH_VEL_10D, CRASH_LEVERAGE, CRASH_COOLDOWN,
        TARGET_VOL, VOL_LOOKBACK,
        INITIAL_CAPITAL, COMMISSION_PER_SHARE, CASH_YIELD_RATE,
        BULL_OVERRIDE_THRESHOLD, BULL_OVERRIDE_MIN_SCORE,
        STOP_DAILY_VOL_MULT, STOP_FLOOR, STOP_CEILING,
        TRAILING_ACTIVATION, TRAILING_STOP_PCT, TRAILING_VOL_BASELINE,
        MAX_PER_SECTOR,
    )
finally:
    sys.stdout = _old_stdout

SEED = 666
np.random.seed(SEED)


# ============================================================================
# PARAMETERIZED BACKTEST (LEVERAGE_MAX and MARGIN_RATE as arguments)
# ============================================================================

def run_backtest_with_leverage(price_data, annual_universe, spy_data,
                                cash_yield_daily=None,
                                leverage_max=1.0,
                                margin_rate=0.06,
                                silent=True):
    """Run full v8.4 COMPASS backtest with parameterized leverage cap and margin rate."""
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    trades = []

    peak_value = float(INITIAL_CAPITAL)
    crash_cooldown = 0
    risk_on_days = 0
    risk_off_days = 0
    current_year = None
    current_universe = []

    for i, date in enumerate(all_dates):
        year = date.year

        if year != current_year:
            current_year = year
            if year in annual_universe:
                current_universe = annual_universe[year]
            else:
                available_years = [y for y in annual_universe.keys() if y <= year]
                if available_years:
                    current_universe = annual_universe[max(available_years)]

        if not current_universe:
            portfolio_values.append({'date': date, 'value': cash})
            continue

        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, current_universe)

        portfolio_value = cash
        for symbol, pos in positions.items():
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        if portfolio_value > peak_value:
            peak_value = portfolio_value

        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        regime_score = compute_regime_score(spy_data, date)
        is_risk_on = regime_score >= 0.50
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        dd_leverage_val, crash_cooldown = compute_smooth_leverage(
            drawdown, portfolio_values, max(i - 1, 0), crash_cooldown
        )

        # Leverage logic: scale vol-targeting to the leverage_max ceiling.
        # At 1.0x this reproduces exact v8.4 behavior.
        # At >1.0x, the base leverage is leverage_max, scaled down by:
        #   1) vol-targeting ratio (reduce when vol is high)
        #   2) DD-scaling (reduce in drawdowns)
        #   3) crash brake (floor at 15% in crashes)
        vol_leverage_raw = compute_dynamic_leverage(spy_data, date)
        # Scale: vol_leverage_raw is capped at 1.0 in original. Scale it to leverage_max.
        vol_leverage_scaled = vol_leverage_raw * leverage_max
        # DD scaling already returns values in [LEV_FLOOR, LEV_FULL=1.0].
        # Scale it to leverage_max range: if dd says 60%, apply 60% of leverage_max.
        dd_scaled = dd_leverage_val * leverage_max
        current_leverage = max(min(dd_scaled, vol_leverage_scaled), LEV_FLOOR)

        spy_trend = get_spy_trend_data(spy_data, date)
        if spy_trend is not None:
            spy_close_now, sma200_now = spy_trend
            max_positions = regime_score_to_positions(regime_score,
                                                      spy_close=spy_close_now,
                                                      sma200=sma200_now)
        else:
            max_positions = regime_score_to_positions(regime_score)

        # Daily margin cost (parameterized rate)
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = margin_rate / 252 * borrowed
            cash -= daily_margin

        # Cash yield
        if cash > 0:
            if cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

        quality_symbols = compute_quality_filter(price_data, tradeable_symbols, date)
        current_scores = compute_momentum_scores(price_data, quality_symbols, date, all_dates, i)

        # --- Close positions (exact v8.4 logic) ---
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue

            current_price = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            days_held = i - pos['entry_idx']
            total_days_held = i - pos['original_entry_idx']
            if days_held >= HOLD_DAYS:
                if should_renew_position(symbol, pos, current_price,
                                          total_days_held, current_scores):
                    pos['entry_idx'] = i
                else:
                    exit_reason = 'hold_expired'

            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            adaptive_stop = compute_adaptive_stop(pos.get('entry_daily_vol', 0.016))
            if pos_return <= adaptive_stop:
                exit_reason = 'position_stop'

            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                vol_ratio = pos.get('entry_vol', TRAILING_VOL_BASELINE) / TRAILING_VOL_BASELINE
                scaled_trailing = TRAILING_STOP_PCT * vol_ratio
                trailing_level = pos['high_price'] * (1 - scaled_trailing)
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
                    'return': pnl / (pos['entry_price'] * shares),
                })
                del positions[symbol]

        # --- Open new positions ---
        needed = max_positions - len(positions)

        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            available_scores = {s: sc for s, sc in current_scores.items() if s not in positions}

            if len(current_scores) >= MIN_MOMENTUM_STOCKS and len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                sector_filtered = filter_by_sector_concentration(ranked, positions)
                selected = sector_filtered[:needed]

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
                        entry_vol, entry_daily_vol = compute_entry_vol(price_data, symbol, date)

                        positions[symbol] = {
                            'entry_price': entry_price,
                            'shares': shares,
                            'entry_date': date,
                            'entry_idx': i,
                            'original_entry_idx': i,
                            'high_price': entry_price,
                            'entry_vol': entry_vol,
                            'entry_daily_vol': entry_daily_vol,
                            'sector': SECTOR_MAP.get(symbol, 'Unknown'),
                        }
                        cash -= cost + commission

        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'drawdown': drawdown,
            'leverage': current_leverage,
        })

    pv_df = pd.DataFrame(portfolio_values)
    pv = pv_df.set_index('date')['value']
    years = len(pv) / 252
    final = pv.iloc[-1]
    cagr = (final / INITIAL_CAPITAL) ** (1 / years) - 1
    maxdd = (pv / pv.cummax() - 1).min()
    returns = pv.pct_change().dropna()
    sharpe = cagr / (returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
    vol = returns.std() * np.sqrt(252)
    downside = returns[returns < 0]
    sortino = cagr / (downside.std() * np.sqrt(252)) if len(downside) > 0 and downside.std() > 0 else 0
    calmar = cagr / abs(maxdd) if maxdd != 0 else 0

    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()

    return {
        'portfolio_values': pv_df,
        'pv': pv,
        'cagr': cagr,
        'maxdd': maxdd,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'vol': vol,
        'final': final,
        'trades': trades_df,
    }


# ============================================================================
# HYDRA OVERLAY (COMPASS + Rattlesnake + EFA)
# ============================================================================

def run_hydra_overlay(compass_pv_df, rattle, efa):
    """Run HYDRA overlay: COMPASS returns + Rattlesnake + EFA (regime-filtered)."""
    MAX_COMPASS_ALLOC = 0.75
    BASE_COMPASS_ALLOC = 0.50
    BASE_RATTLE_ALLOC = 0.50

    c_ret = compass_pv_df.set_index('date')['value'].pct_change()
    r_ret = rattle['value'].pct_change()
    r_exposure = rattle['exposure']

    df_overlay = pd.DataFrame({
        'c_ret': c_ret,
        'r_ret': r_ret,
        'r_exposure': r_exposure,
    }).dropna()

    c_account = INITIAL_CAPITAL * BASE_COMPASS_ALLOC
    r_account = INITIAL_CAPITAL * BASE_RATTLE_ALLOC
    efa_value = 0.0

    portfolio_values_h = []

    for idx in range(len(df_overlay)):
        date = df_overlay.index[idx]
        r_exp = df_overlay['r_exposure'].iloc[idx]
        total_value = c_account + r_account + efa_value

        # Cash recycling (R -> C)
        r_idle = r_account * (1.0 - r_exp)
        max_c_account = total_value * MAX_COMPASS_ALLOC
        max_recyclable = max(0, max_c_account - c_account)
        recycle_amount = min(r_idle, max_recyclable)

        c_effective = c_account + recycle_amount
        r_effective = r_account - recycle_amount

        # Remaining idle cash for EFA
        r_still_idle = r_effective * (1.0 - r_exp)
        idle_cash = r_still_idle

        # EFA regime filter
        efa_eligible = True
        if date in efa.index:
            sma = efa.loc[date, 'sma200']
            close = efa.loc[date, 'close']
            if pd.notna(sma) and close < sma:
                efa_eligible = False

        target_efa = idle_cash if (date in efa.index and efa_eligible) else 0.0

        if target_efa > efa_value:
            buy_amount = target_efa - efa_value
            r_effective -= buy_amount
            efa_value += buy_amount
        elif target_efa < efa_value:
            sell_amount = efa_value - target_efa
            efa_value -= sell_amount
            r_effective += sell_amount

        # Apply daily returns
        c_r = df_overlay['c_ret'].iloc[idx]
        r_r = df_overlay['r_ret'].iloc[idx]
        efa_r = 0.0
        if date in efa.index and efa_value > 0:
            efa_r = efa.loc[date, 'ret']
            if pd.isna(efa_r):
                efa_r = 0.0

        c_account_new = c_effective * (1 + c_r)
        r_account_new = r_effective * (1 + r_r)
        efa_value_new = efa_value * (1 + efa_r)

        recycled_after = recycle_amount * (1 + c_r)
        c_account = c_account_new - recycled_after
        r_account = r_account_new + recycled_after
        efa_value = efa_value_new

        total_new = c_account + r_account + efa_value
        portfolio_values_h.append({'date': date, 'value': total_new})

    pv = pd.DataFrame(portfolio_values_h).set_index('date')['value']
    years = len(pv) / 252
    final = pv.iloc[-1]
    cagr = (final / INITIAL_CAPITAL) ** (1 / years) - 1
    maxdd = (pv / pv.cummax() - 1).min()
    returns = pv.pct_change().dropna()
    sharpe = cagr / (returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
    vol = returns.std() * np.sqrt(252)
    downside = returns[returns < 0]
    sortino = cagr / (downside.std() * np.sqrt(252)) if len(downside) > 0 and downside.std() > 0 else 0
    calmar = cagr / abs(maxdd) if maxdd != 0 else 0

    annual = pv.resample('YE').last().pct_change().dropna()

    return {
        'pv': pv,
        'cagr': cagr,
        'maxdd': maxdd,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'vol': vol,
        'final': final,
        'annual': annual,
    }


# ============================================================================
# MAIN: GRID SEARCH
# ============================================================================

def main():
    print("=" * 80)
    print("HYDRA v8.4 — DYNAMIC LEVERAGE OPTIMIZER")
    print("Grid search: LEVERAGE_MAX x MARGIN_RATE")
    print("Constraint: MaxDD and Sharpe must not degrade vs baseline (1.0x)")
    print("=" * 80)

    # ── Load data ──
    print("\n[1/4] Loading market data...")
    price_data = download_broad_pool()
    spy_data = download_spy()
    cash_yield_daily = download_cash_yield()

    print("\n[2/4] Computing annual top-40 universe...")
    annual_universe = compute_annual_top40(price_data)

    # Load Rattlesnake and EFA for HYDRA overlay
    rattle_path = 'backtests/rattlesnake_daily.csv'
    efa_cache = 'data_cache/efa_daily.pkl'

    if not os.path.exists(rattle_path):
        print(f"\n  ERROR: {rattle_path} not found. Cannot compute HYDRA overlay.")
        print("  Run Rattlesnake backtest first.")
        return

    rattle = pd.read_csv(rattle_path, index_col=0, parse_dates=True)

    if os.path.exists(efa_cache):
        with open(efa_cache, 'rb') as f:
            efa = pickle.load(f)
    else:
        import yfinance as yf
        print("  Downloading EFA data...")
        efa_raw = yf.download('EFA', start='2001-01-01', end='2027-01-01', progress=False)
        if isinstance(efa_raw.columns, pd.MultiIndex):
            efa_raw.columns = efa_raw.columns.get_level_values(0)
        efa = efa_raw[['Close']].rename(columns={'Close': 'close'})
        efa['ret'] = efa['close'].pct_change()
        efa['sma200'] = efa['close'].rolling(200).mean()
        os.makedirs('data_cache', exist_ok=True)
        with open(efa_cache, 'wb') as f:
            pickle.dump(efa, f)

    # ── Grid parameters ──
    leverage_values = [round(1.0 + i * 0.1, 1) for i in range(16)]  # 1.0 to 2.5
    margin_rates = [0.03, 0.045, 0.06]

    print(f"\n[3/4] Running grid search: {len(leverage_values)} leverage x {len(margin_rates)} margin = {len(leverage_values) * len(margin_rates)} runs")
    print(f"  LEVERAGE_MAX: {leverage_values[0]} -> {leverage_values[-1]} (step 0.1)")
    print(f"  MARGIN_RATE:  {[f'{r:.1%}' for r in margin_rates]}")

    # ── Run baseline first (1.0x, 6%) ──
    print(f"\n  Running baseline (1.0x, 6.0%)...")
    t0 = time.time()
    baseline = run_backtest_with_leverage(
        price_data, annual_universe, spy_data,
        cash_yield_daily=cash_yield_daily,
        leverage_max=1.0, margin_rate=0.06, silent=True
    )
    baseline_hydra = run_hydra_overlay(baseline['portfolio_values'], rattle, efa)
    t_baseline = time.time() - t0
    print(f"  Baseline done in {t_baseline:.0f}s")

    base_cagr = baseline_hydra['cagr']
    base_maxdd = baseline_hydra['maxdd']
    base_sharpe = baseline_hydra['sharpe']

    print(f"\n  BASELINE (HYDRA complete @ 1.0x leverage):")
    print(f"    CAGR:     {base_cagr:.2%}")
    print(f"    Max DD:   {base_maxdd:.2%}")
    print(f"    Sharpe:   {base_sharpe:.3f}")
    print(f"    Sortino:  {baseline_hydra['sortino']:.3f}")
    print(f"    Final:    ${baseline_hydra['final']:,.0f}")

    # ── Grid search ──
    results = []
    total_runs = len(leverage_values) * len(margin_rates)
    run_count = 0
    est_total = t_baseline * total_runs

    print(f"\n  Estimated total time: ~{est_total / 60:.0f} minutes")
    print(f"  {'_' * 70}")

    for lev_max in leverage_values:
        for margin in margin_rates:
            run_count += 1

            # Skip baseline (already computed)
            if lev_max == 1.0 and margin == 0.06:
                results.append({
                    'leverage_max': lev_max,
                    'margin_rate': margin,
                    'compass_cagr': baseline['cagr'],
                    'compass_maxdd': baseline['maxdd'],
                    'compass_sharpe': baseline['sharpe'],
                    'hydra_cagr': baseline_hydra['cagr'],
                    'hydra_maxdd': baseline_hydra['maxdd'],
                    'hydra_sharpe': baseline_hydra['sharpe'],
                    'hydra_sortino': baseline_hydra['sortino'],
                    'hydra_calmar': baseline_hydra['calmar'],
                    'hydra_vol': baseline_hydra['vol'],
                    'hydra_final': baseline_hydra['final'],
                    'meets_constraints': True,
                })
                continue

            # Skip 1.0x with other margin rates (margin irrelevant at 1.0x)
            if lev_max == 1.0:
                results.append({
                    'leverage_max': lev_max,
                    'margin_rate': margin,
                    'compass_cagr': baseline['cagr'],
                    'compass_maxdd': baseline['maxdd'],
                    'compass_sharpe': baseline['sharpe'],
                    'hydra_cagr': baseline_hydra['cagr'],
                    'hydra_maxdd': baseline_hydra['maxdd'],
                    'hydra_sharpe': baseline_hydra['sharpe'],
                    'hydra_sortino': baseline_hydra['sortino'],
                    'hydra_calmar': baseline_hydra['calmar'],
                    'hydra_vol': baseline_hydra['vol'],
                    'hydra_final': baseline_hydra['final'],
                    'meets_constraints': True,
                })
                continue

            t_start = time.time()
            compass = run_backtest_with_leverage(
                price_data, annual_universe, spy_data,
                cash_yield_daily=cash_yield_daily,
                leverage_max=lev_max, margin_rate=margin, silent=True
            )
            hydra = run_hydra_overlay(compass['portfolio_values'], rattle, efa)
            t_run = time.time() - t_start

            meets = (hydra['maxdd'] >= base_maxdd and hydra['sharpe'] >= base_sharpe)

            results.append({
                'leverage_max': lev_max,
                'margin_rate': margin,
                'compass_cagr': compass['cagr'],
                'compass_maxdd': compass['maxdd'],
                'compass_sharpe': compass['sharpe'],
                'hydra_cagr': hydra['cagr'],
                'hydra_maxdd': hydra['maxdd'],
                'hydra_sharpe': hydra['sharpe'],
                'hydra_sortino': hydra['sortino'],
                'hydra_calmar': hydra['calmar'],
                'hydra_vol': hydra['vol'],
                'hydra_final': hydra['final'],
                'meets_constraints': meets,
            })

            flag = "PASS" if meets else "FAIL"
            print(f"  [{run_count:2d}/{total_runs}] Lev={lev_max:.1f}x Margin={margin:.1%} -> "
                  f"CAGR={hydra['cagr']:.2%} DD={hydra['maxdd']:.2%} Sharpe={hydra['sharpe']:.3f} "
                  f"[{flag}] ({t_run:.0f}s)")

    # ── Results ──
    results_df = pd.DataFrame(results)

    print(f"\n\n{'=' * 80}")
    print("[4/4] RESULTS — DYNAMIC LEVERAGE OPTIMIZER")
    print(f"{'=' * 80}")

    # Constraints summary
    print(f"\n  Baseline constraints:")
    print(f"    Max DD  >= {base_maxdd:.2%} (cannot be worse)")
    print(f"    Sharpe  >= {base_sharpe:.3f} (cannot be worse)")

    # Full results table by margin rate
    for margin in margin_rates:
        subset = results_df[results_df['margin_rate'] == margin].copy()

        print(f"\n  {'_' * 70}")
        print(f"  MARGIN RATE: {margin:.1%}")
        print(f"  {'_' * 70}")
        print(f"  {'Lev':>5} {'CAGR':>8} {'MaxDD':>8} {'Sharpe':>8} {'Sortino':>8} {'Calmar':>8} {'Vol':>8} {'Final':>14} {'OK?':>5}")
        print(f"  {'_' * 70}")

        for _, row in subset.iterrows():
            flag = "PASS" if row['meets_constraints'] else "FAIL"
            marker = " <-- BASE" if row['leverage_max'] == 1.0 else ""
            print(f"  {row['leverage_max']:>4.1f}x {row['hydra_cagr']:>7.2%} {row['hydra_maxdd']:>7.2%} "
                  f"{row['hydra_sharpe']:>8.3f} {row['hydra_sortino']:>8.3f} {row['hydra_calmar']:>8.3f} "
                  f"{row['hydra_vol']:>7.2%} ${row['hydra_final']:>12,.0f} {flag:>5}{marker}")

    # Find optimal for each margin rate
    print(f"\n\n{'=' * 80}")
    print("OPTIMAL LEVERAGE BY MARGIN RATE")
    print(f"{'=' * 80}")

    best_overall = None
    for margin in margin_rates:
        subset = results_df[
            (results_df['margin_rate'] == margin) &
            (results_df['meets_constraints'] == True)
        ]
        if len(subset) == 0:
            print(f"\n  Margin {margin:.1%}: NO feasible leverage found")
            continue

        best = subset.loc[subset['hydra_cagr'].idxmax()]
        delta_cagr = best['hydra_cagr'] - base_cagr
        delta_dd = best['hydra_maxdd'] - base_maxdd

        print(f"\n  Margin {margin:.1%}: OPTIMAL = {best['leverage_max']:.1f}x")
        print(f"    CAGR:     {best['hydra_cagr']:.2%} (delta {delta_cagr:+.2%})")
        print(f"    Max DD:   {best['hydra_maxdd']:.2%} (delta {delta_dd:+.2%})")
        print(f"    Sharpe:   {best['hydra_sharpe']:.3f}")
        print(f"    Sortino:  {best['hydra_sortino']:.3f}")
        print(f"    Calmar:   {best['hydra_calmar']:.3f}")
        print(f"    Final:    ${best['hydra_final']:,.0f}")

        if best_overall is None or best['hydra_cagr'] > best_overall['hydra_cagr']:
            best_overall = best

    if best_overall is not None:
        print(f"\n  {'=' * 60}")
        print(f"  BEST OVERALL: {best_overall['leverage_max']:.1f}x @ {best_overall['margin_rate']:.1%} margin")
        print(f"    CAGR:   {best_overall['hydra_cagr']:.2%} (baseline: {base_cagr:.2%})")
        print(f"    MaxDD:  {best_overall['hydra_maxdd']:.2%} (baseline: {base_maxdd:.2%})")
        print(f"    Sharpe: {best_overall['hydra_sharpe']:.3f} (baseline: {base_sharpe:.3f})")
        print(f"  {'=' * 60}")

    # Save results
    os.makedirs('backtests', exist_ok=True)
    results_df.to_csv('backtests/leverage_optimizer_grid.csv', index=False)
    print(f"\nSaved: backtests/leverage_optimizer_grid.csv")

    # Save best daily curve
    if best_overall is not None and best_overall['leverage_max'] > 1.0:
        print(f"\nRe-running best ({best_overall['leverage_max']:.1f}x @ {best_overall['margin_rate']:.1%}) for daily output...")
        best_compass = run_backtest_with_leverage(
            price_data, annual_universe, spy_data,
            cash_yield_daily=cash_yield_daily,
            leverage_max=best_overall['leverage_max'],
            margin_rate=best_overall['margin_rate'],
            silent=True
        )
        best_hydra = run_hydra_overlay(best_compass['portfolio_values'], rattle, efa)
        best_hydra['pv'].to_csv('backtests/leverage_optimizer_best_daily.csv')
        print(f"Saved: backtests/leverage_optimizer_best_daily.csv")

        # Annual returns comparison
        print(f"\n--- Annual Returns: Baseline vs Optimal ({best_overall['leverage_max']:.1f}x) ---")
        print(f"{'Year':<8} {'Baseline':>12} {'Optimal':>12} {'Delta':>10}")
        print("-" * 44)
        base_annual = baseline_hydra.get('annual', pd.Series(dtype=float))
        best_annual = best_hydra.get('annual', pd.Series(dtype=float))
        for year_dt in base_annual.index:
            y = year_dt.year
            b = base_annual.loc[year_dt]
            o = best_annual.loc[year_dt] if year_dt in best_annual.index else 0
            print(f"{y:<8} {b:>11.1%} {o:>11.1%} {o - b:>+9.1%}")


if __name__ == '__main__':
    main()
