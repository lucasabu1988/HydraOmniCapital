"""
COMPASS v8.4 — Conditional Hold Period Backtest
=================================================
A/B comparison: Fixed 5d hold vs Regime-conditional hold.
Sweeps all valid monotonic configs (bull >= mild_bull >= mild_bear >= bear).
Based on overlay-enhanced backtest (includes all 5 overlay hooks).

Walk-forward: 2000-2019 (development) vs 2020-2026 (out-of-sample).
Kill criteria: CAGR delta > -0.50%, MaxDD delta < +2.0pp, OOS Sharpe > -0.02.
"""

import pandas as pd
import numpy as np
import os
import sys
import io
import time
import warnings
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

warnings.filterwarnings('ignore')

# =============================================================================
# IMPORT ALL PARAMETERS AND FUNCTIONS FROM PRODUCTION ENGINE
# =============================================================================
_stdout = sys.stdout
sys.stdout = io.StringIO()
try:
    from omnicapital_v84_compass import (
        TOP_N, MIN_AGE_DAYS, MOMENTUM_LOOKBACK, MOMENTUM_SKIP,
        MIN_MOMENTUM_STOCKS, NUM_POSITIONS, NUM_POSITIONS_RISK_OFF,
        HOLD_DAYS, POSITION_STOP_LOSS,
        TRAILING_ACTIVATION, TRAILING_STOP_PCT, TRAILING_VOL_BASELINE,
        HOLD_DAYS_MAX, RENEWAL_PROFIT_MIN, MOMENTUM_RENEWAL_THRESHOLD,
        QUALITY_VOL_MAX, QUALITY_VOL_LOOKBACK, QUALITY_MAX_SINGLE_DAY,
        TARGET_VOL, LEVERAGE_MAX, VOL_LOOKBACK,
        INITIAL_CAPITAL, MARGIN_RATE, COMMISSION_PER_SHARE,
        CASH_YIELD_RATE, CRASH_LEVERAGE, CRASH_COOLDOWN,
        DD_SCALE_TIER1, DD_SCALE_TIER2, DD_SCALE_TIER3,
        LEV_FULL, LEV_MID, LEV_FLOOR,
        BULL_OVERRIDE_THRESHOLD, BULL_OVERRIDE_MIN_SCORE,
        STOP_DAILY_VOL_MULT, STOP_FLOOR, STOP_CEILING,
        MAX_PER_SECTOR, SECTOR_MAP, BROAD_POOL,
        START_DATE, END_DATE,
        download_broad_pool, download_spy, download_cash_yield,
        compute_annual_top40, compute_regime_score, regime_score_to_positions,
        compute_momentum_scores, compute_volatility_weights,
        compute_smooth_leverage, compute_dynamic_leverage,
        compute_adaptive_stop, compute_entry_vol,
        filter_by_sector_concentration, compute_quality_filter,
        get_tradeable_symbols, get_spy_trend_data,
        should_renew_position, calculate_metrics,
    )
finally:
    sys.stdout = _stdout

from compass_fred_data import download_all_overlay_data, validate_fred_coverage
from compass_overlays import (
    BankingStressOverlay, M2MomentumIndicator, FOMCSurpriseSignal,
    FedEmergencySignal, CashOptimization, CreditSectorPreFilter,
    compute_overlay_signals, OVERLAY_FLOOR,
)


# =============================================================================
# CONDITIONAL HOLD HELPER
# =============================================================================

def get_hold_days_for_regime(regime_score: float,
                              hold_days_by_regime: dict,
                              default: int = HOLD_DAYS,
                              max_hold: int = HOLD_DAYS_MAX) -> int:
    """Determine hold period based on regime score at position entry.

    Uses same bucket thresholds as regime_score_to_positions:
      >= 0.65: bull
      >= 0.50: mild_bull
      >= 0.35: mild_bear
      <  0.35: bear
    """
    if regime_score >= 0.65:
        hold = hold_days_by_regime.get('bull', default)
    elif regime_score >= 0.50:
        hold = hold_days_by_regime.get('mild_bull', default)
    elif regime_score >= 0.35:
        hold = hold_days_by_regime.get('mild_bear', default)
    else:
        hold = hold_days_by_regime.get('bear', default)
    return max(1, min(hold, max_hold))


# =============================================================================
# OVERLAY + CONDITIONAL HOLD BACKTEST
# =============================================================================

def run_backtest_conditional_hold(price_data: Dict[str, pd.DataFrame],
                                   annual_universe: Dict[int, List[str]],
                                   spy_data: pd.DataFrame,
                                   cash_yield_daily: Optional[pd.Series],
                                   fred_data: dict,
                                   hold_config: Optional[dict] = None,
                                   quiet: bool = False) -> Dict:
    """Run COMPASS backtest with overlays + conditional hold period.

    Identical to run_backtest_overlay() except:
    - Position entry stores target_hold_days and entry_regime_score
    - Exit check uses pos['target_hold_days'] instead of fixed HOLD_DAYS

    hold_config: dict like {'bull': 7, 'mild_bull': 5, 'mild_bear': 4, 'bear': 3}
                 If None, uses fixed HOLD_DAYS (baseline).
    """

    # Initialize overlay objects
    overlays = {
        'bso': BankingStressOverlay(fred_data),
        'm2': M2MomentumIndicator(fred_data),
        'fomc': FOMCSurpriseSignal(fred_data),
        'fed_emergency': FedEmergencySignal(fred_data),
        'cash_opt': CashOptimization(fred_data),
    }
    credit_prefilter = CreditSectorPreFilter(fred_data, SECTOR_MAP)

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    if not quiet:
        config_str = str(hold_config) if hold_config else f"FIXED {HOLD_DAYS}d"
        print(f"  Hold config: {config_str}")

    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []
    peak_value = float(INITIAL_CAPITAL)
    crash_cooldown = 0
    risk_on_days = 0
    risk_off_days = 0
    current_year = None

    for i, date in enumerate(all_dates):
        if date.year != current_year:
            current_year = date.year

        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        # OVERLAY HOOK 1: Credit sector pre-filter
        tradeable_symbols = credit_prefilter.filter_universe(tradeable_symbols, date)

        # Portfolio value
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        if portfolio_value > peak_value:
            peak_value = portfolio_value

        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # Regime
        regime_score = compute_regime_score(spy_data, date)
        is_risk_on = regime_score >= 0.50
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # Leverage
        dd_leverage_val, crash_cooldown = compute_smooth_leverage(
            drawdown, portfolio_values, max(i - 1, 0), crash_cooldown
        )
        vol_leverage = compute_dynamic_leverage(spy_data, date)
        current_leverage = max(min(dd_leverage_val, vol_leverage), LEV_FLOOR)

        # Max positions
        spy_trend = get_spy_trend_data(spy_data, date)
        if spy_trend is not None:
            spy_close_now, sma200_now = spy_trend
            max_positions = regime_score_to_positions(regime_score,
                                                      spy_close=spy_close_now,
                                                      sma200=sma200_now)
        else:
            max_positions = regime_score_to_positions(regime_score)

        # OVERLAY HOOK 3: Position floor + overlay signals
        overlay_result = compute_overlay_signals(overlays, date, credit_prefilter)
        overlay_scalar = overlay_result['capital_scalar']
        position_floor = overlay_result.get('position_floor')
        cash_rate_override = overlay_result.get('cash_rate_override')

        OVERLAY_DAMPING = 0.25
        if dd_leverage_val < LEV_FULL:
            damped_scalar = 1.0 - OVERLAY_DAMPING * (1.0 - overlay_scalar)
        else:
            damped_scalar = overlay_scalar

        if position_floor is not None:
            max_positions = max(max_positions, position_floor)

        # Daily costs
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # OVERLAY HOOK 2: Cash yield
        if cash > 0:
            if cash_rate_override is not None:
                daily_rate = cash_rate_override
            elif cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

        # Quality filter + momentum scores
        quality_symbols = compute_quality_filter(price_data, tradeable_symbols, date)
        current_scores = compute_momentum_scores(price_data, quality_symbols, date, all_dates, i)

        # --- Close positions ---
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue

            current_price = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            # 1. Hold time check — CONDITIONAL HOLD MODIFICATION
            days_held = i - pos['entry_idx']
            total_days_held = i - pos['original_entry_idx']
            target_hold = pos.get('target_hold_days', HOLD_DAYS)
            if days_held >= target_hold:
                if should_renew_position(symbol, pos, current_price,
                                        total_days_held, current_scores):
                    pos['entry_idx'] = i
                else:
                    exit_reason = 'hold_expired'

            # 2. Adaptive stop
            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            adaptive_stop = compute_adaptive_stop(pos.get('entry_daily_vol', 0.016))
            if pos_return <= adaptive_stop:
                exit_reason = 'position_stop'

            # 3. Trailing stop
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                vol_ratio = pos.get('entry_vol', TRAILING_VOL_BASELINE) / TRAILING_VOL_BASELINE
                scaled_trailing = TRAILING_STOP_PCT * vol_ratio
                trailing_level = pos['high_price'] * (1 - scaled_trailing)
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            # 4. Universe rotation
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
                trades.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'exit_reason': exit_reason,
                    'pnl': pnl,
                    'return': pnl / (pos['entry_price'] * shares),
                    'target_hold_days': pos.get('target_hold_days', HOLD_DAYS),
                    'entry_regime_score': pos.get('entry_regime_score'),
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

                # OVERLAY HOOK 4: Capital scalar
                effective_capital = cash * current_leverage * 0.95 * damped_scalar

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

                        # CONDITIONAL HOLD: store target hold days per position
                        if hold_config is not None:
                            target_hold = get_hold_days_for_regime(regime_score, hold_config)
                        else:
                            target_hold = HOLD_DAYS

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
                            'target_hold_days': target_hold,
                            'entry_regime_score': regime_score,
                        }
                        cash -= cost + commission

        # Daily snapshot
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'drawdown': drawdown,
            'leverage': current_leverage,
            'in_protection': dd_leverage_val < LEV_FULL,
            'risk_on': is_risk_on,
            'regime_score': regime_score,
            'universe_size': len(tradeable_symbols),
            'overlay_scalar': overlay_scalar,
            'damped_scalar': damped_scalar,
            'bso_scalar': overlay_result['per_overlay_scalars'].get('bso', 1.0),
            'm2_scalar': overlay_result['per_overlay_scalars'].get('m2', 1.0),
            'fomc_scalar': overlay_result['per_overlay_scalars'].get('fomc', 1.0),
            'fed_emergency': 1 if position_floor is not None else 0,
            'cash_rate_daily': cash_rate_override if cash_rate_override else 0.0,
        })

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
# WALK-FORWARD SPLIT
# =============================================================================

def split_results_walkforward(results: dict, split_date: str = '2020-01-01'):
    df = results['portfolio_values']
    trades_df = results['trades']
    split = pd.Timestamp(split_date)

    dev_df = df[df['date'] < split].copy()
    oos_df = df[df['date'] >= split].copy()

    dev_trades = trades_df[trades_df['exit_date'] < split] if len(trades_df) > 0 else pd.DataFrame()
    oos_trades = trades_df[trades_df['exit_date'] >= split] if len(trades_df) > 0 else pd.DataFrame()

    dev_risk_on = dev_df['risk_on'].sum() if len(dev_df) > 0 else 0
    oos_risk_on = oos_df['risk_on'].sum() if len(oos_df) > 0 else 0

    dev_results = {
        'portfolio_values': dev_df,
        'trades': dev_trades,
        'stop_events': pd.DataFrame(),
        'final_value': dev_df.iloc[-1]['value'] if len(dev_df) > 0 else INITIAL_CAPITAL,
        'risk_on_days': dev_risk_on,
        'risk_off_days': len(dev_df) - dev_risk_on,
    }
    oos_results = {
        'portfolio_values': oos_df,
        'trades': oos_trades,
        'stop_events': pd.DataFrame(),
        'final_value': oos_df.iloc[-1]['value'] if len(oos_df) > 0 else INITIAL_CAPITAL,
        'risk_on_days': oos_risk_on,
        'risk_off_days': len(oos_df) - oos_risk_on,
    }

    return dev_results, oos_results


# =============================================================================
# SWEEP CONFIGS
# =============================================================================

def generate_sweep_configs():
    """Generate all valid monotonic hold configs (bull >= mild_bull >= mild_bear >= bear)."""
    configs = []
    for b in [5, 6, 7, 8]:
        for mb in [4, 5, 6]:
            for mbr in [3, 4, 5]:
                for br in [2, 3, 4]:
                    if b >= mb >= mbr >= br:
                        configs.append({
                            'bull': b, 'mild_bull': mb,
                            'mild_bear': mbr, 'bear': br,
                        })
    return configs


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    t0 = time.time()

    print("=" * 80)
    print("COMPASS v8.4 — CONDITIONAL HOLD PERIOD SWEEP")
    print("=" * 80)

    # 1. Download data
    print("\n[1/4] Downloading market data...")
    price_data = download_broad_pool()
    spy_data = download_spy()
    cash_yield_daily = download_cash_yield()
    annual_universe = compute_annual_top40(price_data)

    print("  Downloading FRED overlay data...")
    fred_data = download_all_overlay_data()
    validate_fred_coverage(fred_data)

    # 2. Run BASELINE (overlay with fixed 5d hold)
    print("\n[2/4] Running BASELINE (overlay + fixed 5d hold)...")
    baseline_results = run_backtest_conditional_hold(
        price_data, annual_universe, spy_data, cash_yield_daily, fred_data,
        hold_config=None, quiet=False,
    )
    baseline_metrics = calculate_metrics(baseline_results)

    print(f"\n  BASELINE: CAGR={baseline_metrics['cagr']:.2%} | "
          f"Sharpe={baseline_metrics['sharpe']:.3f} | "
          f"MaxDD={baseline_metrics['max_drawdown']:.2%} | "
          f"Trades={baseline_metrics['trades']}")

    # Walk-forward baseline
    base_dev, base_oos = split_results_walkforward(baseline_results)
    base_dev_m = calculate_metrics(base_dev)
    base_oos_m = calculate_metrics(base_oos)

    print(f"  IS  (2000-2019): CAGR={base_dev_m['cagr']:.2%} | Sharpe={base_dev_m['sharpe']:.3f} | MaxDD={base_dev_m['max_drawdown']:.2%}")
    print(f"  OOS (2020-2026): CAGR={base_oos_m['cagr']:.2%} | Sharpe={base_oos_m['sharpe']:.3f} | MaxDD={base_oos_m['max_drawdown']:.2%}")

    # 3. Sweep all configs
    configs = generate_sweep_configs()
    print(f"\n[3/4] Sweeping {len(configs)} configurations...")

    sweep_results = []
    for idx, cfg in enumerate(configs):
        label = f"b{cfg['bull']}/mb{cfg['mild_bull']}/mbr{cfg['mild_bear']}/br{cfg['bear']}"
        print(f"  [{idx+1}/{len(configs)}] {label}...", end="", flush=True)

        results = run_backtest_conditional_hold(
            price_data, annual_universe, spy_data, cash_yield_daily, fred_data,
            hold_config=cfg, quiet=True,
        )
        metrics = calculate_metrics(results)

        # Walk-forward
        dev_res, oos_res = split_results_walkforward(results)
        dev_m = calculate_metrics(dev_res)
        oos_m = calculate_metrics(oos_res)

        # Kill criteria
        cagr_delta = metrics['cagr'] - baseline_metrics['cagr']
        dd_delta = abs(metrics['max_drawdown']) - abs(baseline_metrics['max_drawdown'])
        oos_sharpe_delta = oos_m['sharpe'] - base_oos_m['sharpe']

        passes_kill = (cagr_delta > -0.005 and dd_delta < 0.02 and oos_sharpe_delta > -0.02)

        row = {
            'config': label,
            'bull': cfg['bull'], 'mild_bull': cfg['mild_bull'],
            'mild_bear': cfg['mild_bear'], 'bear': cfg['bear'],
            # Full period
            'cagr': metrics['cagr'],
            'sharpe': metrics['sharpe'],
            'sortino': metrics['sortino'],
            'max_dd': metrics['max_drawdown'],
            'trades': metrics['trades'],
            'win_rate': metrics['win_rate'],
            # Deltas vs baseline
            'cagr_delta': cagr_delta,
            'sharpe_delta': metrics['sharpe'] - baseline_metrics['sharpe'],
            'dd_delta': dd_delta,
            # IS
            'is_cagr': dev_m['cagr'],
            'is_sharpe': dev_m['sharpe'],
            'is_max_dd': dev_m['max_drawdown'],
            # OOS
            'oos_cagr': oos_m['cagr'],
            'oos_sharpe': oos_m['sharpe'],
            'oos_max_dd': oos_m['max_drawdown'],
            'oos_sharpe_delta': oos_sharpe_delta,
            # Kill criteria
            'passes_kill': passes_kill,
        }
        sweep_results.append(row)

        status = "PASS" if passes_kill else "FAIL"
        print(f" CAGR={metrics['cagr']:.2%} Sharpe={metrics['sharpe']:.3f} "
              f"MaxDD={metrics['max_drawdown']:.2%} [{status}]")

    # 4. Analyze and report
    print(f"\n[4/4] Analysis...")
    sweep_df = pd.DataFrame(sweep_results)

    # Save sweep results
    os.makedirs('backtests', exist_ok=True)
    sweep_df.to_csv('backtests/conditional_hold_sweep.csv', index=False)
    print(f"\nSaved: backtests/conditional_hold_sweep.csv ({len(sweep_df)} configs)")

    # Passing configs
    passing = sweep_df[sweep_df['passes_kill']].sort_values('sharpe', ascending=False)

    print(f"\n{'=' * 80}")
    print(f"RESULTS SUMMARY")
    print(f"{'=' * 80}")
    print(f"\nBaseline (fixed 5d): CAGR={baseline_metrics['cagr']:.2%} | "
          f"Sharpe={baseline_metrics['sharpe']:.3f} | MaxDD={baseline_metrics['max_drawdown']:.2%}")
    print(f"\nConfigs tested: {len(sweep_df)}")
    print(f"Configs passing kill criteria: {len(passing)}")

    if len(passing) > 0:
        print(f"\n--- TOP 5 BY SHARPE (passing kill criteria) ---")
        print(f"{'Config':<20} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>8} "
              f"{'OOS Sharpe':>10} {'CAGR Δ':>8} {'Trades':>7}")
        print(f"{'-'*20} {'-'*8} {'-'*8} {'-'*8} {'-'*10} {'-'*8} {'-'*7}")

        for _, r in passing.head(5).iterrows():
            print(f"{r['config']:<20} {r['cagr']:>7.2%} {r['sharpe']:>8.3f} "
                  f"{r['max_dd']:>7.2%} {r['oos_sharpe']:>10.3f} "
                  f"{r['cagr_delta']:>+7.2%} {r['trades']:>7.0f}")

        best = passing.iloc[0]
        print(f"\nBEST CONFIG: {best['config']}")
        print(f"  Full: CAGR={best['cagr']:.2%} Sharpe={best['sharpe']:.3f} MaxDD={best['max_dd']:.2%}")
        print(f"  IS:   CAGR={best['is_cagr']:.2%} Sharpe={best['is_sharpe']:.3f} MaxDD={best['is_max_dd']:.2%}")
        print(f"  OOS:  CAGR={best['oos_cagr']:.2%} Sharpe={best['oos_sharpe']:.3f} MaxDD={best['oos_max_dd']:.2%}")
        print(f"  Δ vs baseline: CAGR={best['cagr_delta']:+.2%} Sharpe={best['sharpe_delta']:+.3f}")
    else:
        print("\nNo configs passed kill criteria. Conditional hold does not improve the system.")

    # Also show worst configs for context
    failing = sweep_df[~sweep_df['passes_kill']].sort_values('cagr', ascending=True)
    if len(failing) > 0:
        print(f"\n--- WORST 3 CONFIGS (failed kill criteria) ---")
        for _, r in failing.head(3).iterrows():
            print(f"  {r['config']}: CAGR={r['cagr']:.2%} MaxDD={r['max_dd']:.2%} "
                  f"CAGR Δ={r['cagr_delta']:+.2%}")

    elapsed = time.time() - t0
    print(f"\nTotal time: {elapsed/60:.1f} minutes")
