"""
COMPASS Net Backtest — Pre-close Signal + MOC Execution
=========================================================
Uses the EXACT production engine (omnicapital_v8_compass.py) with TWO modifications:
1. Momentum signal computed using Close[T-1] instead of Close[T] (pre-close @ 15:30 ET)
2. All entries/exits have +2bps slippage applied (MOC execution cost)

Everything else is IDENTICAL: same data, same parameters, same logic.
This gives us the TRUE Net CAGR using the production engine.
"""

import pandas as pd
import numpy as np
import pickle
import os
import sys
from datetime import timedelta
from typing import Dict, List

import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# IMPORT ALL PARAMETERS AND FUNCTIONS FROM PRODUCTION ENGINE
# Suppress module-level prints during import
# =============================================================================
import io
_stdout = sys.stdout
sys.stdout = io.StringIO()
try:
    from omnicapital_v8_compass import (
        # Parameters
        TOP_N, MIN_AGE_DAYS, MOMENTUM_LOOKBACK, MOMENTUM_SKIP,
        MIN_MOMENTUM_STOCKS, REGIME_SMA_PERIOD, REGIME_CONFIRM_DAYS,
        NUM_POSITIONS, NUM_POSITIONS_RISK_OFF, HOLD_DAYS,
        POSITION_STOP_LOSS, TRAILING_ACTIVATION, TRAILING_STOP_PCT,
        PORTFOLIO_STOP_LOSS, RECOVERY_STAGE_1_DAYS, RECOVERY_STAGE_2_DAYS,
        TARGET_VOL, LEVERAGE_MIN, LEVERAGE_MAX, VOL_LOOKBACK,
        INITIAL_CAPITAL, MARGIN_RATE, COMMISSION_PER_SHARE, CASH_YIELD_RATE,
        START_DATE, END_DATE, BROAD_POOL,
        # Functions (unmodified)
        download_broad_pool, download_spy, compute_annual_top40,
        compute_regime, compute_volatility_weights, compute_dynamic_leverage,
        get_tradeable_symbols, calculate_metrics,
    )
finally:
    sys.stdout = _stdout

# =============================================================================
# NET-SPECIFIC PARAMETERS
# =============================================================================
SLIPPAGE_BPS = 2  # 2 basis points MOC execution cost
SLIPPAGE_MULT = 1 + SLIPPAGE_BPS / 10_000  # 1.0002 for entries (pay more)
SLIPPAGE_DIV = 1 - SLIPPAGE_BPS / 10_000   # 0.9998 for exits (receive less)


# =============================================================================
# MODIFIED: compute_momentum_scores_preclose
# ONLY CHANGE: uses Close[T-1] instead of Close[T] for signal computation
# =============================================================================

def compute_momentum_scores_preclose(price_data: Dict[str, pd.DataFrame],
                                     tradeable: List[str],
                                     date: pd.Timestamp,
                                     all_dates: List[pd.Timestamp],
                                     date_idx: int) -> Dict[str, float]:
    """
    IDENTICAL to production compute_momentum_scores EXCEPT:
    - close_today uses iloc[sym_idx - 1] (T-1) instead of iloc[sym_idx] (T)
    - close_skip uses iloc[sym_idx - 1 - MOMENTUM_SKIP] instead of iloc[sym_idx - MOMENTUM_SKIP]
    - close_lookback uses iloc[sym_idx - 1 - MOMENTUM_LOOKBACK] instead of iloc[sym_idx - MOMENTUM_LOOKBACK]
    This simulates computing the signal at 15:30 ET using yesterday's close.
    """
    scores = {}

    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue

        needed = MOMENTUM_LOOKBACK + MOMENTUM_SKIP + 1  # +1 because we look back one extra day
        try:
            sym_idx = df.index.get_loc(date)
        except KeyError:
            continue

        if sym_idx < needed:
            continue

        # PRE-CLOSE MODIFICATION: all lookbacks shifted by 1 day
        close_today = df['Close'].iloc[sym_idx - 1]          # T-1 (yesterday's close)
        close_skip = df['Close'].iloc[sym_idx - 1 - MOMENTUM_SKIP]      # T-1-5
        close_lookback = df['Close'].iloc[sym_idx - 1 - MOMENTUM_LOOKBACK]  # T-1-90

        if close_lookback <= 0 or close_skip <= 0 or close_today <= 0:
            continue

        momentum_90d = (close_skip / close_lookback) - 1.0
        skip_5d = (close_today / close_skip) - 1.0
        score = momentum_90d - skip_5d
        scores[symbol] = score

    return scores


# =============================================================================
# MODIFIED: run_backtest_net
# ONLY CHANGES:
# 1. Uses compute_momentum_scores_preclose for signal (Close[T-1])
# 2. Entry prices have +2bps slippage (buy higher)
# 3. Exit prices have -2bps slippage (sell lower)
# Everything else is BYTE-FOR-BYTE identical to production run_backtest
# =============================================================================

def run_backtest_net(price_data: Dict[str, pd.DataFrame],
                     annual_universe: Dict[int, List[str]],
                     spy_data: pd.DataFrame) -> Dict:
    """Run COMPASS Net backtest (pre-close signal + MOC slippage)"""

    print("\n" + "=" * 80)
    print("RUNNING COMPASS NET BACKTEST (Pre-close Signal + MOC Execution)")
    print(f"Signal: Close[T-1] | Execution: Close[T] + {SLIPPAGE_BPS}bps slippage")
    print("=" * 80)

    # Get all trading dates
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    # Compute regime
    print("\nComputing market regime (SPY vs SMA200)...")
    regime = compute_regime(spy_data)

    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")

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

        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        # --- Calculate portfolio value ---
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        # --- Update peak ---
        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        # --- Check recovery from protection mode ---
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
                    # NET CHANGE: apply slippage to exit price
                    raw_price = price_data[symbol].loc[date, 'Close']
                    exit_price = raw_price * SLIPPAGE_DIV  # sell lower
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

        # --- Determine max positions and leverage ---
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

        # --- Daily costs (margin on borrowed amount) ---
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # --- Cash yield (T-bill on uninvested cash) ---
        if cash > 0:
            cash += cash * (CASH_YIELD_RATE / 252)

        # --- Close positions ---
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue

            current_price = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            # 1. Hold time expired
            days_held = i - pos['entry_idx']
            if days_held >= HOLD_DAYS:
                exit_reason = 'hold_expired'

            # 2. Position stop loss (-8%)
            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            if pos_return <= POSITION_STOP_LOSS:
                exit_reason = 'position_stop'

            # 3. Trailing stop
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                trailing_level = pos['high_price'] * (1 - TRAILING_STOP_PCT)
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            # 4. Stock no longer in top-40
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
                # NET CHANGE: apply slippage to exit price
                raw_price = current_price
                exit_price = raw_price * SLIPPAGE_DIV  # sell lower
                proceeds = shares * exit_price
                commission = shares * COMMISSION_PER_SHARE
                cash += proceeds - commission
                pnl = (exit_price - pos['entry_price']) * shares - commission
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
            # NET CHANGE: Use pre-close momentum signal (Close[T-1])
            scores = compute_momentum_scores_preclose(price_data, tradeable_symbols, date, all_dates, i)

            available_scores = {s: sc for s, sc in scores.items() if s not in positions}

            if len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]

                weights = compute_volatility_weights(price_data, selected, date)

                effective_capital = cash * current_leverage * 0.95

                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue

                    raw_price = price_data[symbol].loc[date, 'Close']
                    # NET CHANGE: apply slippage to entry price (buy higher)
                    entry_price = raw_price * SLIPPAGE_MULT
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

        # --- Record daily snapshot ---
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

        # Annual progress log
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
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("COMPASS NET BACKTEST")
    print("Pre-close Signal (Close[T-1]) + MOC Execution (Close[T] + 2bps)")
    print("=" * 80)
    print(f"\nUsing EXACT production engine parameters:")
    print(f"  Momentum: {MOMENTUM_LOOKBACK}d lookback, {MOMENTUM_SKIP}d skip, {HOLD_DAYS}d hold")
    print(f"  Positions: {NUM_POSITIONS} (risk-on), {NUM_POSITIONS_RISK_OFF} (risk-off)")
    print(f"  Stops: {POSITION_STOP_LOSS:.0%} position, +{TRAILING_ACTIVATION:.0%}/{TRAILING_STOP_PCT:.0%} trailing, {PORTFOLIO_STOP_LOSS:.0%} portfolio")
    print(f"  Leverage: [{LEVERAGE_MIN}x, {LEVERAGE_MAX}x] | Vol target: {TARGET_VOL:.0%}")
    print(f"  Slippage: {SLIPPAGE_BPS}bps per trade (entry + exit)")
    print(f"  Cash yield: {CASH_YIELD_RATE:.1%}")

    # 1. Load SAME data as production engine
    price_data = download_broad_pool()
    print(f"\nSymbols available: {len(price_data)}")

    spy_data = download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    # 2. Compute annual top-40 (IDENTICAL to production)
    print("\n--- Computing Annual Top-40 ---")
    annual_universe = compute_annual_top40(price_data)

    # 3. Also run SIGNAL backtest for comparison (exact production engine)
    print("\n" + "=" * 80)
    print("STEP 1: Running SIGNAL backtest (production engine, no modifications)...")
    print("=" * 80)

    # Import the exact production run_backtest
    sys.stdout = io.StringIO()
    from omnicapital_v8_compass import run_backtest as run_backtest_signal
    sys.stdout = _stdout

    results_signal = run_backtest_signal(price_data, annual_universe, spy_data)
    metrics_signal = calculate_metrics(results_signal)

    print(f"\n  Signal CAGR: {metrics_signal['cagr']:.2%}")
    print(f"  Signal Sharpe: {metrics_signal['sharpe']:.2f}")
    print(f"  Signal MaxDD: {metrics_signal['max_drawdown']:.1%}")
    print(f"  Signal Final: ${metrics_signal['final_value']:,.0f}")

    # 4. Run NET backtest
    print("\n" + "=" * 80)
    print("STEP 2: Running NET backtest (pre-close signal + MOC slippage)...")
    print("=" * 80)

    results_net = run_backtest_net(price_data, annual_universe, spy_data)
    metrics_net = calculate_metrics(results_net)

    # 5. Print comparison
    print("\n" + "=" * 80)
    print("RESULTS — SIGNAL vs NET COMPARISON")
    print("=" * 80)

    print(f"\n{'Metric':<25} {'Signal (gross)':>18} {'Net (after costs)':>18} {'Delta':>12}")
    print("-" * 75)
    print(f"{'CAGR':<25} {metrics_signal['cagr']:>17.2%} {metrics_net['cagr']:>17.2%} {metrics_net['cagr']-metrics_signal['cagr']:>+11.2%}")
    print(f"{'Sharpe':<25} {metrics_signal['sharpe']:>18.3f} {metrics_net['sharpe']:>18.3f} {metrics_net['sharpe']-metrics_signal['sharpe']:>+12.3f}")
    print(f"{'Sortino':<25} {metrics_signal['sortino']:>18.3f} {metrics_net['sortino']:>18.3f} {metrics_net['sortino']-metrics_signal['sortino']:>+12.3f}")
    print(f"{'Max Drawdown':<25} {metrics_signal['max_drawdown']:>17.1%} {metrics_net['max_drawdown']:>17.1%} {metrics_net['max_drawdown']-metrics_signal['max_drawdown']:>+11.1%}")
    print(f"{'Calmar':<25} {metrics_signal['calmar']:>18.3f} {metrics_net['calmar']:>18.3f} {metrics_net['calmar']-metrics_signal['calmar']:>+12.3f}")
    print(f"{'Final Value':<25} ${metrics_signal['final_value']:>16,.0f} ${metrics_net['final_value']:>16,.0f}")
    print(f"{'Trades':<25} {metrics_signal['trades']:>18,} {metrics_net['trades']:>18,}")
    print(f"{'Win Rate':<25} {metrics_signal['win_rate']:>17.1%} {metrics_net['win_rate']:>17.1%}")
    print(f"{'Stop Events':<25} {metrics_signal['stop_events']:>18} {metrics_net['stop_events']:>18}")
    print(f"{'Protection Days':<25} {metrics_signal['protection_days']:>18} {metrics_net['protection_days']:>18}")

    cost_gap = metrics_signal['cagr'] - metrics_net['cagr']
    pct_recovered = (1 - cost_gap / metrics_signal['cagr']) * 100 if metrics_signal['cagr'] > 0 else 0
    print(f"\n--- Cost Analysis ---")
    print(f"Annual friction (Signal - Net): {cost_gap:.2%}")
    print(f"Net recovers {pct_recovered:.1f}% of Signal CAGR")
    print(f"$100K Signal -> ${metrics_signal['final_value']:,.0f}")
    print(f"$100K Net    -> ${metrics_net['final_value']:,.0f}")
    print(f"Dollar gap: ${metrics_signal['final_value'] - metrics_net['final_value']:,.0f}")

    # 6. Net-specific detailed metrics
    print(f"\n--- Net Backtest Detail ---")
    print(f"Initial capital:        ${metrics_net['initial']:>15,.0f}")
    print(f"Final value:            ${metrics_net['final_value']:>15,.2f}")
    print(f"Total return:           {metrics_net['total_return']:>15.2%}")
    print(f"CAGR:                   {metrics_net['cagr']:>15.2%}")
    print(f"Volatility (annual):    {metrics_net['volatility']:>15.2%}")
    print(f"Sharpe ratio:           {metrics_net['sharpe']:>15.2f}")
    print(f"Sortino ratio:          {metrics_net['sortino']:>15.2f}")
    print(f"Calmar ratio:           {metrics_net['calmar']:>15.2f}")
    print(f"Max drawdown:           {metrics_net['max_drawdown']:>15.2%}")

    print(f"\n--- Exit Reasons (Net) ---")
    for reason, count in sorted(metrics_net['exit_reasons'].items(), key=lambda x: -x[1]):
        print(f"  {reason:25s}: {count:>6,} ({count/metrics_net['trades']*100:.1f}%)")

    print(f"\n--- Annual Returns (Net) ---")
    if len(metrics_net['annual_returns']) > 0:
        print(f"Best year:              {metrics_net['best_year']:>15.2%}")
        print(f"Worst year:             {metrics_net['worst_year']:>15.2%}")
        print(f"Positive years:         {(metrics_net['annual_returns'] > 0).sum()}/{len(metrics_net['annual_returns'])}")

    # 7. Save results
    os.makedirs('backtests', exist_ok=True)

    # Save Net daily CSV (dashboard can use this directly)
    results_net['portfolio_values'].to_csv('backtests/v8_compass_net_daily.csv', index=False)
    if len(results_net['trades']) > 0:
        results_net['trades'].to_csv('backtests/v8_compass_net_trades.csv', index=False)

    # Save Signal daily CSV (re-save from this run for consistency)
    results_signal['portfolio_values'].to_csv('backtests/v8_compass_signal_daily.csv', index=False)

    # Save pickle with both
    output_file = 'results_v8_compass_net.pkl'
    with open(output_file, 'wb') as f:
        pickle.dump({
            'signal_metrics': metrics_signal,
            'net_metrics': metrics_net,
            'signal_portfolio': results_signal['portfolio_values'],
            'net_portfolio': results_net['portfolio_values'],
            'net_trades': results_net['trades'],
            'net_stops': results_net['stop_events'],
        }, f)

    print(f"\nResults saved:")
    print(f"  Net daily:   backtests/v8_compass_net_daily.csv")
    print(f"  Net trades:  backtests/v8_compass_net_trades.csv")
    print(f"  Signal daily: backtests/v8_compass_signal_daily.csv")
    print(f"  Pickle:      {output_file}")

    print("\n" + "=" * 80)
    print("COMPASS NET BACKTEST COMPLETE")
    print("=" * 80)
