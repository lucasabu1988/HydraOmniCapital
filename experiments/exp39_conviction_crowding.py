"""
Experiment #39: Conviction Tilt (C) + Crowding Filter (H) + Combined (C+H)
===========================================================================
Tests proposals from external analysis document against COMPASS v8.2 baseline.

Proposal C — Conviction Tilt:
  - Keep top-N selection, but apply z-score-based conviction multiplier to inv-vol weights
  - Higher momentum z-score → more weight (up to cap)
  - Hypothesis: concentrate more capital on highest-conviction picks

Proposal H — Crowding Risk Filter:
  - Penalize stocks with extreme short-term gap + vol explosion when momentum z-score
    is already very extended (>2σ)
  - Hypothesis: avoid buying terminal momentum peaks

Variants run:
  1. BASELINE (exact v8.2 production)
  2. CONVICTION TILT only (proposal C)
  3. CROWDING FILTER only (proposal H)
  4. COMBINED C+H

All use identical data, regime, universe. Only position sizing / entry filter changes.
"""

import pandas as pd
import numpy as np
import os
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import data functions and parameters from production
from omnicapital_v8_compass import (
    download_broad_pool, download_spy, download_cash_yield,
    compute_annual_top40, compute_regime, compute_momentum_scores,
    compute_volatility_weights, compute_dynamic_leverage,
    get_tradeable_symbols,
    # Parameters
    INITIAL_CAPITAL, TOP_N, MIN_AGE_DAYS, MOMENTUM_LOOKBACK, MOMENTUM_SKIP,
    MIN_MOMENTUM_STOCKS, REGIME_SMA_PERIOD, REGIME_CONFIRM_DAYS,
    NUM_POSITIONS, NUM_POSITIONS_RISK_OFF, HOLD_DAYS,
    POSITION_STOP_LOSS, TRAILING_ACTIVATION, TRAILING_STOP_PCT,
    PORTFOLIO_STOP_LOSS, RECOVERY_STAGE_1_DAYS, RECOVERY_STAGE_2_DAYS,
    TARGET_VOL, LEVERAGE_MIN, LEVERAGE_MAX, VOL_LOOKBACK,
    MARGIN_RATE, COMMISSION_PER_SHARE, CASH_YIELD_RATE,
    START_DATE, END_DATE, BROAD_POOL,
)

# ============================================================================
# EXPERIMENT PARAMETERS
# ============================================================================

# Conviction Tilt (Proposal C)
CONVICTION_ZSCORE_FLOOR = 0.0    # Minimum z-score multiplier (no penalty below mean)
CONVICTION_ZSCORE_CAP = 2.5      # Cap z-score to avoid extreme concentration
CONVICTION_MAX_WEIGHT = 0.35     # Max weight per position (vs 0.40 baseline cap)

# Crowding Filter (Proposal H)
CROWDING_GAP_THRESHOLD = 0.04    # 4% overnight gap = suspicious
CROWDING_VOL_MULT = 2.0          # Vol > 2x 20d average = vol explosion
CROWDING_ZSCORE_THRESHOLD = 2.0  # Only filter when momentum z-score > 2σ


# ============================================================================
# MODIFIED WEIGHT/FILTER FUNCTIONS
# ============================================================================

def compute_conviction_weights(price_data, selected, date, momentum_scores):
    """
    Proposal C: Conviction-tilted inverse-vol weights.
    Base = inv-vol weight. Multiplier = normalized momentum z-score.
    """
    # Get base inv-vol weights
    base_weights = compute_volatility_weights(price_data, selected, date)

    # Compute z-scores of momentum across all scored stocks (not just selected)
    if len(momentum_scores) < 3:
        return base_weights

    all_scores = np.array(list(momentum_scores.values()))
    mean_score = np.mean(all_scores)
    std_score = np.std(all_scores)

    if std_score < 1e-8:
        return base_weights

    # Apply conviction tilt
    tilted = {}
    for symbol in selected:
        base_w = base_weights.get(symbol, 1.0 / len(selected))
        raw_score = momentum_scores.get(symbol, mean_score)
        z = (raw_score - mean_score) / std_score

        # Clamp z-score
        z = max(CONVICTION_ZSCORE_FLOOR, min(z, CONVICTION_ZSCORE_CAP))

        # Multiplier: 1.0 at z=0, scales linearly up to 1 + z*0.3
        multiplier = 1.0 + z * 0.3
        tilted[symbol] = base_w * multiplier

    # Re-normalize
    total = sum(tilted.values())
    if total > 0:
        tilted = {s: w / total for s, w in tilted.items()}

    return tilted


def apply_crowding_filter(price_data, candidates, date, momentum_scores):
    """
    Proposal H: Filter out stocks showing crowding risk.
    Crowding = extreme gap + vol explosion + already extended momentum z-score.
    Returns filtered list of candidates (may be shorter).
    """
    if len(momentum_scores) < 5:
        return candidates

    all_scores = np.array(list(momentum_scores.values()))
    mean_score = np.mean(all_scores)
    std_score = np.std(all_scores)

    if std_score < 1e-8:
        return candidates

    filtered = []
    for symbol in candidates:
        # Check momentum z-score
        raw_score = momentum_scores.get(symbol, mean_score)
        z = (raw_score - mean_score) / std_score

        if z <= CROWDING_ZSCORE_THRESHOLD:
            # Not extended enough to worry about crowding
            filtered.append(symbol)
            continue

        # Check for gap and vol explosion
        if symbol not in price_data or date not in price_data[symbol].index:
            filtered.append(symbol)
            continue

        df = price_data[symbol]
        sym_idx = df.index.get_loc(date)

        if sym_idx < VOL_LOOKBACK + 2:
            filtered.append(symbol)
            continue

        # Overnight gap (today open vs yesterday close)
        today_open = df['Open'].iloc[sym_idx]
        yest_close = df['Close'].iloc[sym_idx - 1]
        if yest_close > 0:
            gap = abs(today_open - yest_close) / yest_close
        else:
            gap = 0

        # Vol explosion: today's range vs 20d avg range
        today_range = (df['High'].iloc[sym_idx] - df['Low'].iloc[sym_idx])
        avg_range = (df['High'].iloc[sym_idx - VOL_LOOKBACK:sym_idx] -
                     df['Low'].iloc[sym_idx - VOL_LOOKBACK:sym_idx]).mean()

        if avg_range > 0:
            vol_ratio = today_range / avg_range
        else:
            vol_ratio = 1.0

        # Crowding detected: extended momentum + gap + vol explosion
        is_crowded = (gap >= CROWDING_GAP_THRESHOLD and
                      vol_ratio >= CROWDING_VOL_MULT)

        if is_crowded:
            # Skip this stock
            continue
        else:
            filtered.append(symbol)

    return filtered


# ============================================================================
# BACKTEST ENGINE (parameterized for variants)
# ============================================================================

def run_variant(price_data, annual_universe, spy_data, cash_yield_daily,
                variant_name, use_conviction=False, use_crowding=False):
    """
    Run COMPASS backtest with optional conviction tilt and/or crowding filter.
    Everything else is identical to production v8.2.
    """
    print(f"\n{'='*80}")
    print(f"RUNNING: {variant_name}")
    print(f"  Conviction tilt: {'ON' if use_conviction else 'OFF'}")
    print(f"  Crowding filter: {'ON' if use_crowding else 'OFF'}")
    print(f"{'='*80}")

    # Get all trading dates
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    # Compute regime
    regime = compute_regime(spy_data)

    # Portfolio state
    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []
    crowding_blocks = 0  # Track how many times crowding filter blocked an entry

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

        # --- Close positions (IDENTICAL to production) ---
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
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'exit_reason': exit_reason,
                    'pnl': pnl,
                    'return': pnl / (pos['entry_price'] * shares)
                })
                del positions[symbol]

        # --- Open new positions (THIS IS WHERE VARIANTS DIFFER) ---
        needed = max_positions - len(positions)

        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            scores = compute_momentum_scores(price_data, tradeable_symbols, date, all_dates, i)
            available_scores = {s: sc for s, sc in scores.items() if s not in positions}

            if len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]

                # === PROPOSAL H: Crowding filter (applied BEFORE weighting) ===
                if use_crowding:
                    original_count = len(selected)
                    selected = apply_crowding_filter(price_data, selected, date, scores)
                    blocked = original_count - len(selected)
                    crowding_blocks += blocked

                    # If crowding removed some, try to fill from next-ranked
                    if len(selected) < needed:
                        extras_needed = needed - len(selected)
                        already = set(selected) | set(positions.keys())
                        remaining = [(s, sc) for s, sc in ranked if s not in already]
                        extras = [s for s, _ in remaining[:extras_needed]]
                        # Also filter extras for crowding
                        extras = apply_crowding_filter(price_data, extras, date, scores)
                        selected.extend(extras)

                if not selected:
                    portfolio_values.append({
                        'date': date, 'value': portfolio_value, 'cash': cash,
                        'positions': len(positions), 'drawdown': drawdown,
                        'leverage': current_leverage, 'in_protection': in_protection_mode,
                        'risk_on': is_risk_on, 'universe_size': len(tradeable_symbols)
                    })
                    continue

                # === PROPOSAL C: Conviction tilt weights ===
                if use_conviction:
                    weights = compute_conviction_weights(price_data, selected, date, scores)
                else:
                    weights = compute_volatility_weights(price_data, selected, date)

                # Effective capital with leverage
                effective_capital = cash * current_leverage * 0.95

                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue

                    entry_price = price_data[symbol].loc[date, 'Close']
                    if entry_price <= 0:
                        continue

                    weight = weights.get(symbol, 1.0 / len(selected))

                    # Cap per position
                    if use_conviction:
                        max_per_position = cash * CONVICTION_MAX_WEIGHT
                    else:
                        max_per_position = cash * 0.40

                    position_value = effective_capital * weight
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

    # Build results
    pv_df = pd.DataFrame(portfolio_values)
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    stop_df = pd.DataFrame(stop_events) if stop_events else pd.DataFrame()

    final_val = pv_df['value'].iloc[-1] if len(pv_df) > 0 else INITIAL_CAPITAL

    return {
        'variant': variant_name,
        'portfolio_values': pv_df,
        'trades': trades_df,
        'stop_events': stop_df,
        'final_value': final_val,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
        'crowding_blocks': crowding_blocks,
    }


def calc_metrics(results):
    """Calculate key metrics from variant results."""
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']

    initial = INITIAL_CAPITAL
    final_value = df['value'].iloc[-1]
    years = len(df) / 252

    cagr = (final_value / initial) ** (1 / years) - 1
    returns = df['value'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(252)
    max_dd = df['drawdown'].min()
    sharpe = cagr / volatility if volatility > 0 else 0

    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else volatility
    sortino = cagr / downside_vol if downside_vol > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    n_trades = len(trades_df)

    protection_days = df['in_protection'].sum()
    protection_pct = protection_days / len(df) * 100

    # Annual returns
    df_annual = df['value'].resample('YE').last()
    annual_returns = df_annual.pct_change().dropna()
    best_year = annual_returns.max() if len(annual_returns) > 0 else 0
    worst_year = annual_returns.min() if len(annual_returns) > 0 else 0

    # Subperiod consistency: split into 5-year chunks
    chunk_size = 252 * 5
    n_chunks = len(df) // chunk_size
    chunk_cagrs = []
    for c in range(n_chunks):
        start_idx = c * chunk_size
        end_idx = min((c + 1) * chunk_size, len(df))
        chunk = df['value'].iloc[start_idx:end_idx]
        if len(chunk) > 50:
            chunk_years = len(chunk) / 252
            chunk_cagr = (chunk.iloc[-1] / chunk.iloc[0]) ** (1 / chunk_years) - 1
            chunk_cagrs.append(chunk_cagr)

    return {
        'variant': results['variant'],
        'final_value': final_value,
        'cagr': cagr,
        'volatility': volatility,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'win_rate': win_rate,
        'trades': n_trades,
        'stop_events': len(results['stop_events']),
        'protection_days': protection_days,
        'protection_pct': protection_pct,
        'best_year': best_year,
        'worst_year': worst_year,
        'crowding_blocks': results.get('crowding_blocks', 0),
        'chunk_cagrs': chunk_cagrs,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    t0 = time.time()

    print("=" * 80)
    print("EXPERIMENT #39: CONVICTION TILT (C) + CROWDING FILTER (H)")
    print("=" * 80)
    print(f"\nConviction tilt params:")
    print(f"  Z-score floor: {CONVICTION_ZSCORE_FLOOR}, cap: {CONVICTION_ZSCORE_CAP}")
    print(f"  Max weight/position: {CONVICTION_MAX_WEIGHT:.0%}")
    print(f"  Multiplier formula: 1.0 + z * 0.3")
    print(f"\nCrowding filter params:")
    print(f"  Gap threshold: {CROWDING_GAP_THRESHOLD:.0%}")
    print(f"  Vol multiplier: {CROWDING_VOL_MULT:.1f}x")
    print(f"  Z-score threshold: {CROWDING_ZSCORE_THRESHOLD:.1f} std")

    # ---- Load data (shared across all variants) ----
    print("\n--- Loading data ---")
    price_data = download_broad_pool()
    spy_data = download_spy()
    cash_yield_daily = download_cash_yield()
    annual_universe = compute_annual_top40(price_data)

    # ---- Run 4 variants ----
    variants = [
        ("BASELINE (v8.2)", False, False),
        ("CONVICTION TILT (C)", True, False),
        ("CROWDING FILTER (H)", False, True),
        ("COMBINED C+H", True, True),
    ]

    all_results = []
    all_metrics = []

    for name, conv, crowd in variants:
        res = run_variant(price_data, annual_universe, spy_data, cash_yield_daily,
                          name, use_conviction=conv, use_crowding=crowd)
        m = calc_metrics(res)
        all_results.append(res)
        all_metrics.append(m)

    # ---- Comparison table ----
    print("\n" + "=" * 100)
    print("EXPERIMENT #39 RESULTS — CONVICTION TILT (C) + CROWDING FILTER (H)")
    print("=" * 100)

    baseline = all_metrics[0]

    header = f"{'Metric':<22}"
    for m in all_metrics:
        header += f" {m['variant']:>18}"
    print(header)
    print("-" * (22 + 19 * len(all_metrics)))

    rows = [
        ('Final Value', 'final_value', '${:>15,.0f}'),
        ('CAGR', 'cagr', '{:>17.2%}'),
        ('Volatility', 'volatility', '{:>17.2%}'),
        ('Sharpe', 'sharpe', '{:>17.2f}'),
        ('Sortino', 'sortino', '{:>17.2f}'),
        ('Calmar', 'calmar', '{:>17.2f}'),
        ('Max Drawdown', 'max_drawdown', '{:>17.2%}'),
        ('Win Rate', 'win_rate', '{:>17.2%}'),
        ('Trades', 'trades', '{:>17,}'),
        ('Stop Events', 'stop_events', '{:>17,}'),
        ('Protection Days', 'protection_days', '{:>17,}'),
        ('Protection %', 'protection_pct', '{:>16.1f}%'),
        ('Best Year', 'best_year', '{:>17.2%}'),
        ('Worst Year', 'worst_year', '{:>17.2%}'),
        ('Crowding Blocks', 'crowding_blocks', '{:>17,}'),
    ]

    for label, key, fmt in rows:
        row = f"{label:<22}"
        for m in all_metrics:
            val = m[key]
            row += f" {fmt.format(val)}"
        print(row)

    # ---- Delta vs baseline ----
    print(f"\n{'--- Delta vs Baseline ---':^{22 + 19 * len(all_metrics)}}")
    delta_rows = [
        ('CAGR delta', 'cagr'),
        ('Sharpe delta', 'sharpe'),
        ('MaxDD delta', 'max_drawdown'),
    ]
    for label, key in delta_rows:
        row = f"{label:<22}"
        for m in all_metrics:
            delta = m[key] - baseline[key]
            if key == 'max_drawdown':
                # Positive delta = worse DD (deeper)
                row += f" {delta:>+17.2%}"
            elif key == 'sharpe':
                row += f" {delta:>+17.3f}"
            else:
                row += f" {delta:>+17.2%}"
        print(row)

    # ---- Subperiod consistency ----
    print(f"\n{'--- 5-Year Subperiod CAGRs ---':^{22 + 19 * len(all_metrics)}}")
    max_chunks = max(len(m['chunk_cagrs']) for m in all_metrics)
    for c in range(max_chunks):
        row = f"{'Period ' + str(c+1):<22}"
        for m in all_metrics:
            if c < len(m['chunk_cagrs']):
                row += f" {m['chunk_cagrs'][c]:>17.2%}"
            else:
                row += f" {'N/A':>17}"
        print(row)

    # ---- VERDICT ----
    print("\n" + "=" * 100)
    print("VERDICT")
    print("=" * 100)

    for m in all_metrics[1:]:  # Skip baseline
        cagr_delta = m['cagr'] - baseline['cagr']
        sharpe_delta = m['sharpe'] - baseline['sharpe']
        dd_delta = m['max_drawdown'] - baseline['max_drawdown']

        passed = (cagr_delta > 0 and sharpe_delta >= -0.02 and dd_delta >= -0.03)

        status = "APPROVED" if passed else "FAILED"
        print(f"\n  {m['variant']}:")
        print(f"    CAGR:   {m['cagr']:.2%} ({cagr_delta:+.2%})")
        print(f"    Sharpe: {m['sharpe']:.3f} ({sharpe_delta:+.3f})")
        print(f"    MaxDD:  {m['max_drawdown']:.2%} ({dd_delta:+.2%})")
        if m['crowding_blocks'] > 0:
            print(f"    Crowding blocks: {m['crowding_blocks']:,}")
        print(f"    >>> {status}")

    elapsed = time.time() - t0
    print(f"\nTotal runtime: {elapsed:.1f}s")

    # ---- Save daily CSVs ----
    os.makedirs('backtests', exist_ok=True)
    for res in all_results:
        safe_name = res['variant'].lower().replace(' ', '_').replace('(', '').replace(')', '').replace('+', 'plus')
        res['portfolio_values'].to_csv(f'backtests/exp39_{safe_name}_daily.csv', index=False)

    print("\nDaily CSVs saved to backtests/exp39_*.csv")
    print("\n" + "=" * 100)
    print("EXPERIMENT #39 COMPLETE")
    print("=" * 100)
