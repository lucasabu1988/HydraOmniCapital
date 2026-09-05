"""
Test: Universe rotation frequency
Baseline (annual) vs semi-annual vs quarterly vs monthly
"""
import pandas as pd
import numpy as np
import pickle
import os
from datetime import timedelta
import warnings
warnings.filterwarnings('ignore')

# Import parametric engine
import omnicapital_vortex_v3_sweep as v3

# ============================================================================
# CUSTOM UNIVERSE ROTATION BY FREQUENCY
# ============================================================================

def compute_universe_by_freq(price_data, freq_months, top_n=40):
    """
    Compute top-N universe by dollar volume, recalculated every freq_months.
    Uses trailing 252 trading days (1 year) of data for ranking regardless of frequency.
    """
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))

    # Build a daily universe map: date -> list of eligible symbols
    # Recalculate at each rotation point
    daily_universe = {}
    last_rotation = None
    last_rotation_idx = None
    current_top = []

    for day_idx, date in enumerate(all_dates):
        # Determine if we need to rotate
        need_rotation = False
        if last_rotation is None:
            need_rotation = True
        elif freq_months == 0:  # Daily
            need_rotation = True
        elif freq_months < 0:  # Every N trading days (negative = trading days)
            need_rotation = (day_idx - last_rotation_idx) >= abs(freq_months)
        elif freq_months == 1:
            need_rotation = date.month != last_rotation.month or date.year != last_rotation.year
        elif freq_months == 3:
            curr_q = (date.month - 1) // 3
            last_q = (last_rotation.month - 1) // 3
            need_rotation = curr_q != last_q or date.year != last_rotation.year
        elif freq_months == 6:
            curr_h = (date.month - 1) // 6
            last_h = (last_rotation.month - 1) // 6
            need_rotation = curr_h != last_h or date.year != last_rotation.year
        elif freq_months == 12:
            need_rotation = date.year != last_rotation.year

        if need_rotation:
            # Rank by trailing ~252 days of dollar volume
            scores = {}
            for symbol, df in price_data.items():
                if date not in df.index:
                    continue
                idx = df.index.get_loc(date)
                start_idx = max(0, idx - 252)
                window = df.iloc[start_idx:idx]
                if len(window) < 60:  # Need at least ~3 months of data
                    continue
                dollar_vol = (window['Close'] * window['Volume']).mean()
                scores[symbol] = dollar_vol

            ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
            current_top = [s for s, _ in ranked[:top_n]]
            last_rotation = date
            last_rotation_idx = day_idx

        daily_universe[date] = current_top

    return daily_universe


def run_backtest_with_daily_universe(price_data, daily_universe, spy_data, regime,
                                     all_dates, first_date, params):
    """
    Modified parametric backtest that uses a daily universe map
    instead of annual_universe dict.
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

    MIN_AGE_DAYS = 63
    VOL_LOOKBACK = 20
    INITIAL_CAPITAL = 100_000
    MARGIN_RATE = 0.06
    COMMISSION_PER_SHARE = 0.001
    POSITION_STOP_LOSS = -0.08
    PORTFOLIO_STOP_LOSS = -0.15
    RECOVERY_STAGE_1_DAYS = 63
    RECOVERY_STAGE_2_DAYS = 126

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
        # Get tradeable from daily universe
        eligible = set(daily_universe.get(date, []))
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

            available_scores = {s: sc for s, sc in scores.items() if s not in positions}

            if len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]

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

    # Metrics
    pv_series = pd.Series(portfolio_values, index=all_dates)
    final = pv_series.iloc[-1]
    years = len(pv_series) / 252
    cagr = (final / INITIAL_CAPITAL) ** (1/years) - 1
    rets = pv_series.pct_change().dropna()
    vol = rets.std() * np.sqrt(252)
    sharpe = cagr / vol if vol > 0 else 0
    dd_series = pd.Series(daily_drawdowns, index=all_dates)
    max_dd = dd_series.min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    down_rets = rets[rets < 0]
    down_vol = down_rets.std() * np.sqrt(252) if len(down_rets) > 0 else vol
    sortino = cagr / down_vol if down_vol > 0 else 0

    # Count rotation exits
    rot_exits = sum(1 for t in trades if t['reason'] == 'universe_rotation')

    return {
        'final': final, 'cagr': cagr, 'sharpe': sharpe, 'sortino': sortino,
        'max_dd': max_dd, 'calmar': calmar, 'trades': len(trades),
        'stops': stop_events, 'rotation_exits': rot_exits,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 75)
    print("TEST: UNIVERSE ROTATION FREQUENCY")
    print("How often should we recalculate the top-40 eligible stocks?")
    print("=" * 75)

    # Load data
    price_data = v3.download_broad_pool()
    spy_data = v3.download_spy()
    regime = v3.compute_regime(spy_data)

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    params = {
        'momentum_lookback': 90,
        'momentum_skip': 5,
        'hold_days': 5,
        'num_positions': 5,
        'target_vol': 0.15,
    }

    freqs = [
        (-6, "Every 6 days"),
        (12, "Annual *"),
    ]

    print(f"\nBuilding universes and running backtests...")
    print(f"{'Frequency':<16} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>8} {'Final':>14} {'Trades':>7} {'Rot.Exits':>10}")
    print("-" * 75)

    for freq_months, label in freqs:
        # Build universe
        daily_univ = compute_universe_by_freq(price_data, freq_months)

        # Run backtest
        r = run_backtest_with_daily_universe(
            price_data, daily_univ, spy_data, regime, all_dates, first_date, params
        )

        print(f"{label:<16} {r['cagr']:>7.2%} {r['sharpe']:>8.3f} "
              f"{r['max_dd']:>7.1%} ${r['final']:>12,.0f} {r['trades']:>7} {r['rotation_exits']:>10}")

    print("\n  * = COMPASS v8.2 baseline (annual rotation)")
    print("\n  Note: All configs use trailing 252-day dollar volume for ranking.")
    print("  More frequent rotation = faster reaction to liquidity shifts,")
    print("  but also more 'universe_rotation' forced exits.")
