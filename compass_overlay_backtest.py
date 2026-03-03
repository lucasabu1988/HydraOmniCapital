"""
COMPASS v8.4 — Overlay Backtest Runner
=========================================
A/B comparison: Base v8.4 vs v8.4 + Monetary Overlays.
Imports the locked algorithm without modification, duplicates run_backtest()
with 4 overlay hooks (credit filter, cash yield, position floor, capital scalar).

Walk-forward: 2000-2019 (development) vs 2020-2026 (out-of-sample).
"""

import pandas as pd
import numpy as np
import os
import sys
import io
import time
import warnings
from typing import Dict, List, Optional, Tuple

warnings.filterwarnings('ignore')

# =============================================================================
# IMPORT ALL PARAMETERS AND FUNCTIONS FROM PRODUCTION ENGINE
# Suppress module-level prints during import
# =============================================================================
_stdout = sys.stdout
sys.stdout = io.StringIO()
try:
    from omnicapital_v84_compass import (
        # Parameters
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
        # Functions
        download_broad_pool, download_spy, download_cash_yield,
        compute_annual_top40, compute_regime_score, regime_score_to_positions,
        compute_momentum_scores, compute_volatility_weights,
        compute_smooth_leverage, compute_dynamic_leverage,
        compute_adaptive_stop, compute_entry_vol,
        filter_by_sector_concentration, compute_quality_filter,
        get_tradeable_symbols, get_spy_trend_data,
        should_renew_position, calculate_metrics,
        run_backtest,
    )
finally:
    sys.stdout = _stdout

# Local overlay modules
from compass_fred_data import download_all_overlay_data, validate_fred_coverage
from compass_overlays import (
    BankingStressOverlay, M2MomentumIndicator, FOMCSurpriseSignal,
    FedEmergencySignal, CashOptimization, CreditSectorPreFilter,
    compute_overlay_signals, OVERLAY_FLOOR,
)


# =============================================================================
# V-RECOVERY MOMENTUM BOOST
# =============================================================================

V_RECOVERY_10D_STRONG = 0.08
V_RECOVERY_10D_MODERATE = 0.05
V_RECOVERY_20D_SUSTAINED = 0.10

V_RECOVERY_BOOST_STRONG = 0.20
V_RECOVERY_BOOST_SUSTAINED = 0.15
V_RECOVERY_BOOST_MODERATE = 0.10


def compute_v_recovery_boost(spy_ret_10d: float, spy_ret_20d: float,
                              in_protection: bool) -> float:
    """Compute regime score boost based on SPY short-term momentum.

    Only active during protection mode (drawdown > -10%).
    Returns a value to ADD to regime_score (0.0 to 0.20).
    """
    if not in_protection:
        return 0.0

    if spy_ret_10d >= V_RECOVERY_10D_STRONG:
        return V_RECOVERY_BOOST_STRONG
    elif spy_ret_20d >= V_RECOVERY_20D_SUSTAINED:
        return V_RECOVERY_BOOST_SUSTAINED
    elif spy_ret_10d >= V_RECOVERY_10D_MODERATE:
        return V_RECOVERY_BOOST_MODERATE
    else:
        return 0.0


# =============================================================================
# OVERLAY-ENHANCED BACKTEST
# =============================================================================

def run_backtest_overlay(price_data: Dict[str, pd.DataFrame],
                         annual_universe: Dict[int, List[str]],
                         spy_data: pd.DataFrame,
                         cash_yield_daily: Optional[pd.Series],
                         fred_data: dict,
                         overlay_config: Optional[dict] = None) -> Dict:
    """Run COMPASS backtest with monetary overlay hooks.

    This is a copy of run_backtest() with 4 injection points:
    1. Credit sector pre-filter (after get_tradeable_symbols)
    2. Cash yield override (DTB3 instead of Aaa)
    3. Position floor (Fed emergency minimum positions)
    4. Capital scalar (overlay_scalar * effective_capital)

    overlay_config: dict to enable/disable individual overlays.
        Default: all enabled. Pass {'bso': False} to disable BSO, etc.
    """

    config = {
        'bso': True, 'm2': True, 'fomc': True,
        'fed_emergency': True, 'cash_opt': True, 'credit_filter': True,
    }
    if overlay_config:
        config.update(overlay_config)

    print("\n" + "=" * 80)
    active = [k for k, v in config.items() if v]
    print(f"RUNNING COMPASS BACKTEST + OVERLAYS ({', '.join(active)})")
    print("=" * 80)

    # Initialize overlay objects
    overlays = {}
    if config['bso']:
        overlays['bso'] = BankingStressOverlay(fred_data)
    if config['m2']:
        overlays['m2'] = M2MomentumIndicator(fred_data)
    if config['fomc']:
        overlays['fomc'] = FOMCSurpriseSignal(fred_data)
    if config['fed_emergency']:
        overlays['fed_emergency'] = FedEmergencySignal(fred_data)
    if config['cash_opt']:
        overlays['cash_opt'] = CashOptimization(fred_data)

    credit_prefilter = None
    if config['credit_filter']:
        credit_prefilter = CreditSectorPreFilter(fred_data, SECTOR_MAP)

    # Get all trading dates
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")

    # Portfolio state
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

        # === OVERLAY HOOK 1: Credit sector pre-filter ===
        if credit_prefilter is not None:
            tradeable_symbols = credit_prefilter.filter_universe(tradeable_symbols, date)

        # --- Calculate portfolio value ---
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        if portfolio_value > peak_value:
            peak_value = portfolio_value

        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # Regime
        regime_score_raw = compute_regime_score(spy_data, date)

        # Leverage (compute BEFORE boost so we know if we're in protection)
        dd_leverage_val, crash_cooldown = compute_smooth_leverage(
            drawdown, portfolio_values, max(i - 1, 0), crash_cooldown
        )
        vol_leverage = compute_dynamic_leverage(spy_data, date)
        current_leverage = max(min(dd_leverage_val, vol_leverage), LEV_FLOOR)

        # V-Recovery Momentum Boost: accelerate re-entry when SPY shows strong momentum
        in_protection = dd_leverage_val < LEV_FULL
        v_recovery_boost = 0.0
        if in_protection and date in spy_data.index and i >= 20:
            spy_closes = spy_data.loc[:date, 'Close']
            if len(spy_closes) >= 21:
                spy_ret_10d = (spy_closes.iloc[-1] / spy_closes.iloc[-11]) - 1.0
                spy_ret_20d = (spy_closes.iloc[-1] / spy_closes.iloc[-21]) - 1.0
                v_recovery_boost = compute_v_recovery_boost(spy_ret_10d, spy_ret_20d, in_protection)

        regime_score = min(1.0, regime_score_raw + v_recovery_boost)
        is_risk_on = regime_score >= 0.50
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # Max positions from regime score (with boost applied)
        spy_trend = get_spy_trend_data(spy_data, date)
        if spy_trend is not None:
            spy_close_now, sma200_now = spy_trend
            max_positions = regime_score_to_positions(regime_score,
                                                      spy_close=spy_close_now,
                                                      sma200=sma200_now)
        else:
            max_positions = regime_score_to_positions(regime_score)

        # === OVERLAY HOOK 3: Position floor (Fed emergency) ===
        overlay_result = compute_overlay_signals(overlays, date, credit_prefilter)
        overlay_scalar = overlay_result['capital_scalar']
        position_floor = overlay_result.get('position_floor')
        cash_rate_override = overlay_result.get('cash_rate_override')

        # Conditional damping: full overlay signal when no DD-scaling (early warning),
        # heavily damped when DD-scaling already active (avoid double-counting).
        OVERLAY_DAMPING = 0.25  # Use 25% of overlay signal when DD-scaling active
        if dd_leverage_val < LEV_FULL:
            damped_scalar = 1.0 - OVERLAY_DAMPING * (1.0 - overlay_scalar)
        else:
            damped_scalar = overlay_scalar

        if position_floor is not None:
            max_positions = max(max_positions, position_floor)

        # --- Daily costs ---
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # === OVERLAY HOOK 2: Cash yield override (DTB3 vs Aaa) ===
        if cash > 0:
            if cash_rate_override is not None:
                daily_rate = cash_rate_override
            elif cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

        # Quality filter
        quality_symbols = compute_quality_filter(price_data, tradeable_symbols, date)

        # Momentum scores
        current_scores = compute_momentum_scores(price_data, quality_symbols, date, all_dates, i)

        # --- Close positions ---
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue

            current_price = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            # 1. Hold time check
            days_held = i - pos['entry_idx']
            total_days_held = i - pos['original_entry_idx']
            if days_held >= HOLD_DAYS:
                if should_renew_position(symbol, pos, current_price,
                                        total_days_held, current_scores):
                    pos['entry_idx'] = i
                else:
                    exit_reason = 'hold_expired'

            # 2. Position stop loss
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
                    'return': pnl / (pos['entry_price'] * shares)
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

                # === OVERLAY HOOK 4: Capital scalar (conditional damping) ===
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

        # --- Record daily snapshot (with overlay columns) ---
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
            # Overlay columns
            'overlay_scalar': overlay_scalar,
            'damped_scalar': damped_scalar,
            'bso_scalar': overlay_result['per_overlay_scalars'].get('bso', 1.0),
            'm2_scalar': overlay_result['per_overlay_scalars'].get('m2', 1.0),
            'fomc_scalar': overlay_result['per_overlay_scalars'].get('fomc', 1.0),
            'fed_emergency': 1 if position_floor is not None else 0,
            'cash_rate_daily': cash_rate_override if cash_rate_override else 0.0,
            'v_recovery_boost': v_recovery_boost,
        })

        # Annual progress log
        if i % 252 == 0 and i > 0:
            year_num = i // 252
            regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
            prot_str = f" [DD_SCALE {dd_leverage_val:.0%}]" if dd_leverage_val < LEV_FULL else ""
            ovl_str = f" | OVL: {damped_scalar:.2f}"
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | DD: {drawdown:.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_str}{prot_str}{ovl_str} | "
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
# A/B COMPARISON
# =============================================================================

def compare_results(base_metrics: dict, overlay_metrics: dict, label: str = "FULL"):
    print(f"\n{'=' * 70}")
    print(f"  A/B COMPARISON: Base v8.4 vs Overlay-Enhanced ({label})")
    print(f"{'=' * 70}")

    rows = [
        ('CAGR',       'cagr',          '{:.2%}'),
        ('Total Ret',  'total_return',   '{:.1%}'),
        ('MaxDD',      'max_drawdown',   '{:.2%}'),
        ('Sharpe',     'sharpe',         '{:.3f}'),
        ('Sortino',    'sortino',        '{:.3f}'),
        ('Calmar',     'calmar',         '{:.3f}'),
        ('Win Rate',   'win_rate',       '{:.1%}'),
        ('Trades',     'trades',         '{:.0f}'),
    ]

    print(f"\n  {'Metric':<12} {'Base v8.4':>12} {'+ Overlays':>12} {'Delta':>12}")
    print(f"  {'-'*12} {'-'*12} {'-'*12} {'-'*12}")

    for label_str, key, fmt in rows:
        base_val = base_metrics.get(key, 0)
        ovl_val = overlay_metrics.get(key, 0)
        if base_val is None:
            base_val = 0
        if ovl_val is None:
            ovl_val = 0
        delta = ovl_val - base_val
        sign = '+' if delta >= 0 else ''
        print(f"  {label_str:<12} {fmt.format(base_val):>12} {fmt.format(ovl_val):>12} {sign}{fmt.format(delta):>11}")

    print()


def check_kill_criteria(base_metrics: dict, overlay_metrics: dict) -> bool:
    """Check if overlay results violate kill criteria. Returns True if PASS."""
    print("\n--- Kill Criteria Check ---")
    passed = True

    # 1. CAGR shouldn't drop > 50bps
    cagr_delta = overlay_metrics.get('cagr', 0) - base_metrics.get('cagr', 0)
    if cagr_delta < -0.005:
        print(f"  FAIL: CAGR dropped {cagr_delta:.2%} (limit: -0.50%)")
        passed = False
    else:
        print(f"  PASS: CAGR delta {cagr_delta:+.2%}")

    # 2. MaxDD shouldn't worsen > 200bps
    base_dd = abs(base_metrics.get('max_drawdown', 0))
    ovl_dd = abs(overlay_metrics.get('max_drawdown', 0))
    dd_change = ovl_dd - base_dd
    if dd_change > 0.02:
        print(f"  FAIL: MaxDD worsened by {dd_change:.2%} (limit: +2.00%)")
        passed = False
    else:
        print(f"  PASS: MaxDD delta {dd_change:+.2%}")

    # 3. Sharpe shouldn't decrease
    sharpe_delta = overlay_metrics.get('sharpe', 0) - base_metrics.get('sharpe', 0)
    if sharpe_delta < 0:
        print(f"  WARN: Sharpe decreased {sharpe_delta:+.3f}")
    else:
        print(f"  PASS: Sharpe delta {sharpe_delta:+.3f}")

    print(f"\n  Overall: {'PASS' if passed else 'FAIL'}")
    return passed


def analyze_overlay_activity(daily_df: pd.DataFrame):
    """Analyze how often overlays are active."""
    print("\n--- Overlay Activity Analysis ---")

    total_days = len(daily_df)
    if total_days == 0:
        print("  No data to analyze")
        return

    # Days with overlay_scalar < 1.0
    active_days = (daily_df['overlay_scalar'] < 0.999).sum()
    print(f"  Overlay active: {active_days}/{total_days} days ({active_days/total_days:.1%})")

    # Days with overlay_scalar < 0.80 (kill criterion: should be < 40%)
    heavy_days = (daily_df['overlay_scalar'] < 0.80).sum()
    pct_heavy = heavy_days / total_days
    status = "PASS" if pct_heavy < 0.40 else "FAIL"
    print(f"  Heavy restriction (<0.80): {heavy_days} days ({pct_heavy:.1%}) [{status}]")

    # BSO activity
    bso_active = (daily_df['bso_scalar'] < 0.999).sum()
    print(f"  BSO active: {bso_active} days ({bso_active/total_days:.1%})")

    # M2 activity
    m2_active = (daily_df['m2_scalar'] < 0.999).sum()
    print(f"  M2MI active: {m2_active} days ({m2_active/total_days:.1%})")

    # FOMC activity
    fomc_active = (daily_df['fomc_scalar'] < 0.999).sum()
    print(f"  FOMC active: {fomc_active} days ({fomc_active/total_days:.1%})")

    # Fed emergency
    fed_days = daily_df['fed_emergency'].sum()
    print(f"  Fed emergency: {fed_days} days ({fed_days/total_days:.1%})")

    # Average overlay scalar when active
    active_mask = daily_df['overlay_scalar'] < 0.999
    if active_mask.sum() > 0:
        avg_when_active = daily_df.loc[active_mask, 'overlay_scalar'].mean()
        print(f"  Avg scalar when active: {avg_when_active:.3f}")


# =============================================================================
# WALK-FORWARD SPLIT
# =============================================================================

def split_results_walkforward(results: dict, split_date: str = '2020-01-01'):
    """Split results into dev (before split) and OOS (after split)."""
    df = results['portfolio_values']
    trades_df = results['trades']

    split = pd.Timestamp(split_date)

    dev_df = df[df['date'] < split].copy()
    oos_df = df[df['date'] >= split].copy()

    dev_trades = trades_df[trades_df['exit_date'] < split] if len(trades_df) > 0 else pd.DataFrame()
    oos_trades = trades_df[trades_df['exit_date'] >= split] if len(trades_df) > 0 else pd.DataFrame()

    # Recalculate metrics for each period
    dev_risk_on = dev_df['risk_on'].sum() if len(dev_df) > 0 else 0
    dev_risk_off = len(dev_df) - dev_risk_on
    oos_risk_on = oos_df['risk_on'].sum() if len(oos_df) > 0 else 0
    oos_risk_off = len(oos_df) - oos_risk_on

    dev_results = {
        'portfolio_values': dev_df,
        'trades': dev_trades,
        'stop_events': pd.DataFrame(),
        'final_value': dev_df.iloc[-1]['value'] if len(dev_df) > 0 else INITIAL_CAPITAL,
        'risk_on_days': dev_risk_on,
        'risk_off_days': dev_risk_off,
    }
    oos_results = {
        'portfolio_values': oos_df,
        'trades': oos_trades,
        'stop_events': pd.DataFrame(),
        'final_value': oos_df.iloc[-1]['value'] if len(oos_df) > 0 else INITIAL_CAPITAL,
        'risk_on_days': oos_risk_on,
        'risk_off_days': oos_risk_off,
    }

    return dev_results, oos_results


# =============================================================================
# INDIVIDUAL OVERLAY ATTRIBUTION
# =============================================================================

def run_attribution(price_data, annual_universe, spy_data, cash_yield_daily, fred_data):
    """Run each overlay individually to measure marginal contribution."""
    print("\n" + "=" * 80)
    print("OVERLAY ATTRIBUTION (individual contribution)")
    print("=" * 80)

    overlay_names = ['bso', 'm2', 'fomc', 'fed_emergency', 'cash_opt', 'credit_filter']
    results = {}

    for name in overlay_names:
        config = {k: False for k in overlay_names}
        config[name] = True
        print(f"\n--- Testing: {name} only ---")
        res = run_backtest_overlay(price_data, annual_universe, spy_data,
                                   cash_yield_daily, fred_data, overlay_config=config)
        metrics = calculate_metrics(res)
        results[name] = metrics
        print(f"  CAGR: {metrics['cagr']:.2%} | Sharpe: {metrics['sharpe']:.3f} | "
              f"MaxDD: {metrics['max_drawdown']:.2%}")

    return results


# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    t0 = time.time()

    print("=" * 80)
    print("COMPASS v8.4 OVERLAY BACKTEST")
    print("=" * 80)

    # 1. Download market data (reuses existing cache)
    print("\n[1/6] Downloading market data...")
    price_data = download_broad_pool()
    spy_data = download_spy()
    cash_yield_daily = download_cash_yield()
    annual_universe = compute_annual_top40(price_data)

    # 2. Download FRED overlay data
    print("\n[2/6] Downloading FRED overlay data...")
    fred_data = download_all_overlay_data()
    validate_fred_coverage(fred_data)

    # 3. Run BASE backtest (original v8.4)
    print("\n[3/6] Running BASE v8.4 backtest...")
    base_results = run_backtest(price_data, annual_universe, spy_data, cash_yield_daily)
    base_metrics = calculate_metrics(base_results)

    print(f"\n  Base v8.4: CAGR={base_metrics['cagr']:.2%} | "
          f"Sharpe={base_metrics['sharpe']:.3f} | "
          f"MaxDD={base_metrics['max_drawdown']:.2%}")

    # 4. Run OVERLAY-ENHANCED backtest
    print("\n[4/6] Running OVERLAY-ENHANCED backtest...")
    overlay_results = run_backtest_overlay(
        price_data, annual_universe, spy_data, cash_yield_daily, fred_data
    )
    overlay_metrics = calculate_metrics(overlay_results)

    print(f"\n  Overlay: CAGR={overlay_metrics['cagr']:.2%} | "
          f"Sharpe={overlay_metrics['sharpe']:.3f} | "
          f"MaxDD={overlay_metrics['max_drawdown']:.2%}")

    # 5. Full comparison
    compare_results(base_metrics, overlay_metrics, "FULL 2000-2026")
    kill_pass = check_kill_criteria(base_metrics, overlay_metrics)

    # Overlay activity analysis
    overlay_daily = overlay_results['portfolio_values']
    analyze_overlay_activity(overlay_daily)

    # 6. Walk-forward split
    print("\n[5/6] Walk-forward analysis...")
    base_dev, base_oos = split_results_walkforward(base_results)
    ovl_dev, ovl_oos = split_results_walkforward(overlay_results)

    base_dev_metrics = calculate_metrics(base_dev)
    base_oos_metrics = calculate_metrics(base_oos)
    ovl_dev_metrics = calculate_metrics(ovl_dev)
    ovl_oos_metrics = calculate_metrics(ovl_oos)

    compare_results(base_dev_metrics, ovl_dev_metrics, "DEV 2000-2019")
    compare_results(base_oos_metrics, ovl_oos_metrics, "OOS 2020-2026")

    # Attribution
    print("\n[6/6] Individual overlay attribution...")
    attribution = run_attribution(price_data, annual_universe, spy_data,
                                  cash_yield_daily, fred_data)

    # Save results
    os.makedirs('backtests', exist_ok=True)

    overlay_daily.to_csv('backtests/v84_overlay_daily.csv', index=False)
    print(f"\nSaved: backtests/v84_overlay_daily.csv ({len(overlay_daily)} rows)")

    if len(overlay_results['trades']) > 0:
        overlay_results['trades'].to_csv('backtests/v84_overlay_trades.csv', index=False)
        print(f"Saved: backtests/v84_overlay_trades.csv ({len(overlay_results['trades'])} rows)")

    elapsed = time.time() - t0
    print(f"\nTotal time: {elapsed/60:.1f} minutes")
    print("\nDone.")
