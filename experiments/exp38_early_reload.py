"""
Experiment #38: Cash Deploy on Strong Cycle
=============================================
Rule: If by trading day 2 the portfolio has >= +3% gains,
deploy the idle cash (currently earning Aaa bond yield) to buy
5 ADDITIONAL stocks using the same momentum ranking from cycle start.

- The original 5 positions are KEPT (not sold)
- The 5 new positions use the next-best stocks in the ranking (6th-10th)
- All positions follow normal COMPASS exit rules (5d hold, stops, trailing)
- This temporarily raises positions from 5 to ~10

Hypothesis: When momentum is strong (3% in 2 days), broaden exposure to
capture the wave. ~20% of capital sits in cash earning Aaa yield — during
confirmed momentum bursts, deploy it into second-tier momentum picks.

Uses exact COMPASS v8.2 production engine with this single modification.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from datetime import timedelta
from typing import Dict, List, Optional
import warnings
warnings.filterwarnings('ignore')

from omnicapital_v8_compass import (
    BROAD_POOL, TOP_N, MIN_AGE_DAYS,
    MOMENTUM_LOOKBACK, MOMENTUM_SKIP, MIN_MOMENTUM_STOCKS,
    REGIME_SMA_PERIOD, REGIME_CONFIRM_DAYS,
    NUM_POSITIONS, NUM_POSITIONS_RISK_OFF, HOLD_DAYS,
    POSITION_STOP_LOSS, TRAILING_ACTIVATION, TRAILING_STOP_PCT,
    PORTFOLIO_STOP_LOSS,
    RECOVERY_STAGE_1_DAYS, RECOVERY_STAGE_2_DAYS,
    TARGET_VOL, LEVERAGE_MIN, LEVERAGE_MAX, VOL_LOOKBACK,
    INITIAL_CAPITAL, MARGIN_RATE, COMMISSION_PER_SHARE,
    CASH_YIELD_RATE,
    START_DATE, END_DATE,
    download_broad_pool, download_spy, download_cash_yield,
    compute_annual_top40, compute_regime,
    compute_momentum_scores, compute_volatility_weights,
    compute_dynamic_leverage, get_tradeable_symbols,
    calculate_metrics,
)

# ============================================================================
# EXPERIMENT PARAMETERS
# ============================================================================

DEPLOY_CHECK_DAY = 2            # Check on day 2 of cycle
DEPLOY_THRESHOLD = 0.03         # +3% portfolio gain triggers cash deploy
EXTRA_POSITIONS = 5             # Buy 5 additional stocks

print("=" * 80)
print("EXPERIMENT #38: CASH DEPLOY ON STRONG CYCLE")
print("=" * 80)
print(f"\nRule: If portfolio is up >= {DEPLOY_THRESHOLD:.0%} by day {DEPLOY_CHECK_DAY}, "
      f"buy {EXTRA_POSITIONS} additional stocks with idle cash")
print(f"Original positions: KEPT (not sold)")
print(f"New picks: Next-best from same momentum ranking (6th-10th)")
print(f"Base: COMPASS v8.2 (all other rules identical)")
print()


# ============================================================================
# MODIFIED BACKTEST
# ============================================================================

def run_exp38_backtest(price_data: Dict[str, pd.DataFrame],
                       annual_universe: Dict[int, List[str]],
                       spy_data: pd.DataFrame,
                       cash_yield_daily: Optional[pd.Series] = None) -> Dict:
    """Run COMPASS backtest with cash deployment on strong cycles."""

    print("\n" + "=" * 80)
    print("RUNNING EXP #38 BACKTEST")
    print("=" * 80)

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

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

    # --- Exp #38 tracking ---
    cycle_start_value = None        # Portfolio value when cycle positions were opened
    cycle_start_day_index = None    # Day index when current cycle started
    cycle_momentum_scores = None    # Momentum scores from cycle start (for extra picks)
    cash_deployed_this_cycle = False # Only deploy once per cycle
    deploy_count = 0                # How many times we deployed extra cash
    deploy_extra_bought = 0         # Total extra positions bought across all deploys

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

            if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and is_regime_on:
                in_protection_mode = False
                protection_stage = 0
                peak_value = portfolio_value
                stop_loss_day_index = None
                post_stop_base = None

        # --- Drawdown ---
        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # --- Portfolio stop loss ---
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({
                'date': date,
                'portfolio_value': portfolio_value,
                'drawdown': drawdown
            })

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
            cycle_start_value = None
            cycle_start_day_index = None
            cycle_momentum_scores = None
            cash_deployed_this_cycle = False

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

        # --- Daily costs ---
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # --- Cash yield ---
        if cash > 0:
            if cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

        # =====================================================================
        # EXP #38: DEPLOY CASH ON STRONG CYCLE
        # =====================================================================
        if (len(positions) > 0 and cycle_start_value is not None and
                cycle_start_day_index is not None and
                not cash_deployed_this_cycle and
                not in_protection_mode and is_risk_on):

            days_in_cycle = i - cycle_start_day_index

            if days_in_cycle == DEPLOY_CHECK_DAY:
                # Recalculate current portfolio value
                current_pv = cash
                for symbol, pos in positions.items():
                    if symbol in price_data and date in price_data[symbol].index:
                        price = price_data[symbol].loc[date, 'Close']
                        current_pv += pos['shares'] * price

                cycle_return = (current_pv - cycle_start_value) / cycle_start_value

                if cycle_return >= DEPLOY_THRESHOLD and cash > 1000:
                    # Deploy cash into extra positions
                    if cycle_momentum_scores is not None:
                        available = {s: sc for s, sc in cycle_momentum_scores.items()
                                     if s not in positions}

                        if len(available) >= EXTRA_POSITIONS:
                            ranked = sorted(available.items(), key=lambda x: x[1], reverse=True)
                            selected = [s for s, _ in ranked[:EXTRA_POSITIONS]]

                            weights = compute_volatility_weights(price_data, selected, date)
                            effective_capital = cash * current_leverage * 0.95

                            bought_count = 0
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

                                if cost + commission <= cash * 0.90 and cost > 100:
                                    positions[symbol] = {
                                        'entry_price': entry_price,
                                        'shares': shares,
                                        'entry_date': date,
                                        'entry_idx': i,
                                        'high_price': entry_price,
                                    }
                                    cash -= cost + commission
                                    bought_count += 1

                            if bought_count > 0:
                                deploy_count += 1
                                deploy_extra_bought += bought_count
                                cash_deployed_this_cycle = True

        # --- Close positions (normal COMPASS rules) ---
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue

            current_price = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            # 1. Hold time expired (5 trading days)
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

            # 4. Universe rotation
            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'

            # 5. Excess positions — only reduce for regime change, not from cash deploy
            if exit_reason is None and len(positions) > max_positions and not cash_deployed_this_cycle:
                pos_returns = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        cp = price_data[s].loc[date, 'Close']
                        pos_returns[s] = (cp - p['entry_price']) / p['entry_price']
                if pos_returns:
                    worst = min(pos_returns, key=pos_returns.get)
                    if symbol == worst:
                        exit_reason = 'regime_reduce'

            if exit_reason:
                shares = pos['shares']
                proceeds = shares * current_price
                commission_cost = shares * COMMISSION_PER_SHARE
                cash += proceeds - commission_cost
                pnl = (current_price - pos['entry_price']) * shares - commission_cost
                trades.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'exit_reason': exit_reason,
                    'pnl': pnl,
                    'return': pnl / (pos['entry_price'] * shares)
                })
                del positions[symbol]

        # --- Open new positions (normal COMPASS entry) ---
        needed = max_positions - len(positions)

        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            scores = compute_momentum_scores(price_data, tradeable_symbols, date, all_dates, i)
            available_scores = {s: sc for s, sc in scores.items() if s not in positions}

            if len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]

                weights = compute_volatility_weights(price_data, selected, date)
                effective_capital = cash * current_leverage * 0.95

                opened_any = False
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
                    commission_cost = shares * COMMISSION_PER_SHARE

                    if cost + commission_cost <= cash * 0.90:
                        positions[symbol] = {
                            'entry_price': entry_price,
                            'shares': shares,
                            'entry_date': date,
                            'entry_idx': i,
                            'high_price': entry_price,
                        }
                        cash -= cost + commission_cost
                        opened_any = True

                # Track cycle start whenever new positions are opened
                if opened_any:
                    new_pv = cash
                    for sym, p in positions.items():
                        if sym in price_data and date in price_data[sym].index:
                            new_pv += p['shares'] * price_data[sym].loc[date, 'Close']
                    cycle_start_value = new_pv
                    cycle_start_day_index = i
                    cycle_momentum_scores = scores
                    cash_deployed_this_cycle = False

        # If no positions, reset cycle tracking
        if len(positions) == 0:
            cycle_start_value = None
            cycle_start_day_index = None
            cycle_momentum_scores = None
            cash_deployed_this_cycle = False

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

        if i % 252 == 0 and i > 0:
            year_num = i // 252
            regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
            prot_str = f" [PROTECTION S{protection_stage}]" if in_protection_mode else ""
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | DD: {drawdown:.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_str}{prot_str} | "
                  f"Pos: {len(positions)}")

    print(f"\n  Cash deploys triggered: {deploy_count}")
    print(f"  Extra positions bought: {deploy_extra_bought}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'annual_universe': annual_universe,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
        'deploy_count': deploy_count,
        'deploy_extra_bought': deploy_extra_bought,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    price_data = download_broad_pool()
    print(f"\nSymbols available: {len(price_data)}")

    spy_data = download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    cash_yield_daily = download_cash_yield()

    annual_universe = compute_annual_top40(price_data)
    print(f"Annual universes computed: {len(annual_universe)} years")

    results = run_exp38_backtest(price_data, annual_universe, spy_data, cash_yield_daily)
    metrics = calculate_metrics(results)

    print("\n" + "=" * 80)
    print("EXP #38 RESULTS: CASH DEPLOY ON STRONG CYCLE")
    print("=" * 80)

    print(f"\n  Initial Capital:    ${metrics['initial']:,.0f}")
    print(f"  Final Value:        ${metrics['final_value']:,.0f}")
    print(f"  Total Return:       {metrics['total_return']:.1%}")
    print(f"  CAGR:               {metrics['cagr']:.2%}")
    print(f"  Sharpe:             {metrics['sharpe']:.2f}")
    print(f"  Sortino:            {metrics['sortino']:.2f}")
    print(f"  Max Drawdown:       {metrics['max_drawdown']:.2%}")
    print(f"  Volatility:         {metrics['volatility']:.2%}")
    print(f"  Calmar:             {metrics['calmar']:.2f}")
    print(f"\n  Trades:             {metrics['trades']}")
    print(f"  Win Rate:           {metrics['win_rate']:.1%}")
    print(f"  Avg Trade:          ${metrics['avg_trade']:,.2f}")
    print(f"  Avg Winner:         ${metrics['avg_winner']:,.2f}")
    print(f"  Avg Loser:          ${metrics['avg_loser']:,.2f}")
    print(f"\n  Stop Events:        {metrics['stop_events']}")
    print(f"  Protection Days:    {metrics['protection_days']} ({metrics['protection_pct']:.1f}%)")
    print(f"  Cash Deploys:       {results['deploy_count']} (bought {results['deploy_extra_bought']} extra positions)")

    print(f"\n  Exit Reasons:")
    for reason, count in sorted(metrics['exit_reasons'].items(), key=lambda x: -x[1]):
        print(f"    {reason}: {count}")

    # Comparison
    print("\n" + "=" * 80)
    print("COMPARISON vs BASELINE COMPASS v8.2")
    print("=" * 80)

    baseline_cagr = 0.1856
    baseline_sharpe = 0.90
    baseline_maxdd = -0.269
    baseline_final = 8_430_000

    delta_cagr = metrics['cagr'] - baseline_cagr

    print(f"\n  {'Metric':<20} {'Baseline':>12} {'Exp #38':>12} {'Delta':>12}")
    print(f"  {'-'*56}")
    print(f"  {'CAGR':<20} {baseline_cagr:>11.2%} {metrics['cagr']:>11.2%} {delta_cagr:>+11.2%}")
    print(f"  {'Sharpe':<20} {baseline_sharpe:>12.2f} {metrics['sharpe']:>12.2f} {metrics['sharpe']-baseline_sharpe:>+12.2f}")
    print(f"  {'Max DD':<20} {baseline_maxdd:>11.1%} {metrics['max_drawdown']:>11.1%} {metrics['max_drawdown']-baseline_maxdd:>+11.1%}")
    print(f"  {'Final Value':<20} ${baseline_final:>10,} ${metrics['final_value']:>10,.0f} ${metrics['final_value']-baseline_final:>+10,.0f}")

    if delta_cagr >= 0 and metrics['max_drawdown'] >= baseline_maxdd:
        verdict = "APPROVED"
    else:
        verdict = "FAILED"

    print(f"\n  VERDICT: {verdict}")
    if verdict == "FAILED":
        reasons = []
        if delta_cagr < 0:
            reasons.append(f"Lost {abs(delta_cagr):.2%} CAGR")
        if metrics['max_drawdown'] < baseline_maxdd:
            reasons.append(f"Worse MaxDD ({metrics['max_drawdown']:.1%} vs {baseline_maxdd:.1%})")
        print(f"  Reason: {' + '.join(reasons)}")

    print("\n" + "=" * 80)
