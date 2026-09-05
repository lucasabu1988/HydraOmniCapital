"""
Test: Behavioral Finance Overlays on COMPASS v8.2
===================================================
Tests 5 variants based on academic behavioral finance anomalies:

A) BASELINE    — Pure momentum (COMPASS v8.2 params)
B) 52WK_HIGH   — Blend momentum rank with 52-week-high nearness (Anchoring, George & Hwang 2004)
C) LOTTERY_FLT — Filter out top-10% MAX stocks (Skewness preference, Bali et al. 2011)
D) RISK_ADJ    — Rank by return/volatility instead of raw return (Loss aversion, Novy-Marx 2012)
E) COMBINED    — All three behavioral overlays together

All variants use identical COMPASS v8.2 engine (regime, stops, leverage, hold, etc.)
Only the stock SELECTION scoring changes.
"""

import pandas as pd
import numpy as np
import importlib
import omnicapital_vortex_v3_sweep as v3
importlib.reload(v3)
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# CONSTANTS (matching COMPASS v8.2 exactly)
# ============================================================================
INITIAL_CAPITAL = 100_000
VOL_LOOKBACK = 20
MIN_AGE_DAYS = 63
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001
POSITION_STOP_LOSS = -0.08
PORTFOLIO_STOP_LOSS = -0.15
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126

# COMPASS v8.2 params
PARAMS = {
    'momentum_lookback': 90,
    'momentum_skip': 5,
    'hold_days': 5,
    'num_positions': 5,
    'num_positions_roff': 2,
    'target_vol': 0.15,
    'trailing_activation': 0.05,
    'trailing_stop_pct': 0.03,
    'leverage_min': 0.3,
    'leverage_max': 2.0,
}


def compute_scores(price_data, tradeable, date, all_dates_idx, variant='baseline'):
    """
    Compute stock selection scores based on variant.
    Returns dict: symbol -> score (higher = better)
    """
    momentum_lookback = PARAMS['momentum_lookback']
    momentum_skip = PARAMS['momentum_skip']

    # Step 1: Compute raw momentum for all tradeable
    raw_scores = {}
    stock_data = {}  # Cache per-stock data for behavioral calculations

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
        raw_mom = mom - skip_ret

        # Cache extra data needed by behavioral variants
        stock_data[symbol] = {
            'sym_idx': sym_idx,
            'close': ct,
            'raw_mom': raw_mom,
        }
        raw_scores[symbol] = raw_mom

    if not raw_scores:
        return {}

    # === VARIANT A: BASELINE (pure momentum) ===
    if variant == 'baseline':
        return raw_scores

    # Precompute behavioral metrics for each stock
    nearness = {}     # 52-week high proximity
    max_ret = {}      # MAX: highest single-day return in past 21 days
    risk_adj = {}     # Risk-adjusted momentum: return / vol

    for symbol, sdata in stock_data.items():
        df = price_data[symbol]
        sym_idx = sdata['sym_idx']

        # 52-week high nearness (need 252 trading days)
        if sym_idx >= 252:
            high_252 = df['High'].iloc[sym_idx - 252:sym_idx + 1].max()
            if high_252 > 0:
                nearness[symbol] = sdata['close'] / high_252

        # MAX: highest single-day return in past 21 days
        if sym_idx >= 22:
            daily_rets = df['Close'].iloc[sym_idx - 21:sym_idx + 1].pct_change().dropna()
            if len(daily_rets) >= 15:
                max_ret[symbol] = daily_rets.max()

        # Risk-adjusted momentum: 90d return / 90d volatility
        if sym_idx >= 91:
            rets_90d = df['Close'].iloc[sym_idx - 90:sym_idx + 1].pct_change().dropna()
            if len(rets_90d) >= 60:
                vol_90d = rets_90d.std() * np.sqrt(252)
                if vol_90d > 0.01:
                    total_ret = (sdata['close'] / df['Close'].iloc[sym_idx - 90]) - 1.0
                    risk_adj[symbol] = total_ret / vol_90d

    # === VARIANT B: 52-WEEK HIGH BLEND ===
    if variant == '52wk_high':
        if not nearness:
            return raw_scores
        # Rank-blend: 50% momentum rank + 50% nearness rank
        mom_ranked = _rank_dict(raw_scores)
        near_ranked = _rank_dict(nearness)
        blended = {}
        for s in raw_scores:
            m_rank = mom_ranked.get(s, 0)
            n_rank = near_ranked.get(s, 0)
            blended[s] = 0.5 * m_rank + 0.5 * n_rank
        return blended

    # === VARIANT C: LOTTERY FILTER ===
    if variant == 'lottery_filter':
        if not max_ret:
            return raw_scores
        # Remove top 10% by MAX (highest single-day return = lottery stocks)
        threshold = np.percentile(list(max_ret.values()), 90)
        filtered = {}
        for s, score in raw_scores.items():
            if s in max_ret and max_ret[s] >= threshold:
                continue  # Skip lottery stocks
            filtered[s] = score
        return filtered if filtered else raw_scores

    # === VARIANT D: RISK-ADJUSTED MOMENTUM ===
    if variant == 'risk_adj_mom':
        if not risk_adj:
            return raw_scores
        # Use risk-adjusted momentum for stocks that have it, raw for others
        scores = {}
        for s in raw_scores:
            if s in risk_adj:
                scores[s] = risk_adj[s]
            else:
                scores[s] = raw_scores[s]
        return scores

    # === VARIANT E: COMBINED (all three) ===
    if variant == 'combined':
        # 1. Filter out lottery stocks first
        eligible = set(raw_scores.keys())
        if max_ret:
            threshold = np.percentile(list(max_ret.values()), 90)
            eligible = {s for s in eligible if s not in max_ret or max_ret[s] < threshold}

        if not eligible:
            eligible = set(raw_scores.keys())

        # 2. Risk-adjusted momentum scores for eligible
        ra_scores = {}
        for s in eligible:
            if s in risk_adj:
                ra_scores[s] = risk_adj[s]
            else:
                ra_scores[s] = raw_scores[s]

        # 3. Blend with 52-week high nearness
        if nearness:
            ra_ranked = _rank_dict(ra_scores)
            near_ranked = _rank_dict({s: nearness[s] for s in eligible if s in nearness})
            blended = {}
            for s in eligible:
                r_rank = ra_ranked.get(s, 0)
                n_rank = near_ranked.get(s, 0)
                blended[s] = 0.5 * r_rank + 0.5 * n_rank
            return blended
        else:
            return ra_scores

    return raw_scores


def _rank_dict(d):
    """Convert a dict of values to percentile ranks (0 to 1)."""
    if not d:
        return {}
    items = sorted(d.items(), key=lambda x: x[1])
    n = len(items)
    return {s: (i + 1) / n for i, (s, _) in enumerate(items)}


def run_behavioral_backtest(price_data, annual_universe, spy_data, regime,
                            all_dates, first_date, variant='baseline'):
    """
    Run COMPASS v8.2 backtest with behavioral scoring variant.
    Everything identical to COMPASS except stock selection scoring.
    """
    from datetime import timedelta

    momentum_lookback = PARAMS['momentum_lookback']
    momentum_skip = PARAMS['momentum_skip']
    hold_days = PARAMS['hold_days']
    num_positions = PARAMS['num_positions']
    num_positions_roff = PARAMS['num_positions_roff']
    target_vol = PARAMS['target_vol']
    trailing_activation = PARAMS['trailing_activation']
    trailing_stop_pct = PARAMS['trailing_stop_pct']
    leverage_min = PARAMS['leverage_min']
    leverage_max = PARAMS['leverage_max']

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
        year = date.year
        tradeable = []
        if year in annual_universe:
            for symbol in annual_universe[year]:
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
                    rets = spy_data['Close'].iloc[idx - VOL_LOOKBACK:idx + 1].pct_change().dropna()
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

            if exit_reason:
                proceeds = pos['shares'] * cp
                commission = pos['shares'] * COMMISSION_PER_SHARE
                cash += proceeds - commission
                pnl_ret = (cp - pos['entry_price']) / pos['entry_price']
                trades.append({'ret': pnl_ret, 'reason': exit_reason})
                del positions[symbol]

        # Open new positions — THIS IS WHERE BEHAVIORAL VARIANTS DIFFER
        needed = max_pos - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable) >= 5:
            # Get scores using behavioral variant
            scores = compute_scores(price_data, tradeable, date, i, variant=variant)

            # Filter out stocks already in portfolio
            available_scores = {s: sc for s, sc in scores.items() if s not in positions}

            if len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]

                # Inverse vol weights (same as COMPASS)
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
                    r = df['Close'].iloc[si - VOL_LOOKBACK:si + 1].pct_change().dropna()
                    if len(r) < VOL_LOOKBACK - 2:
                        continue
                    v = r.std() * np.sqrt(252)
                    if v > 0.01:
                        vols[s] = v
                if not vols:
                    weights = {s: 1.0 / len(selected) for s in selected}
                else:
                    raw_w = {s: 1.0 / v for s, v in vols.items()}
                    total_w = sum(raw_w.values())
                    weights = {s: w / total_w for s, w in raw_w.items()}

                eff_capital = cash * leverage * 0.95
                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue
                    ep = price_data[symbol].loc[date, 'Close']
                    if ep <= 0:
                        continue
                    w = weights.get(symbol, 1.0 / len(selected))
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
    cagr = (final / INITIAL_CAPITAL) ** (1 / years) - 1
    rets = pv_series.pct_change().dropna()
    vol = rets.std() * np.sqrt(252)
    sharpe = cagr / vol if vol > 0 else 0
    dd_series = pd.Series(daily_drawdowns, index=all_dates)
    max_dd = dd_series.min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    down_rets = rets[rets < 0]
    down_vol = down_rets.std() * np.sqrt(252) if len(down_rets) > 0 else vol
    sortino = cagr / down_vol if down_vol > 0 else 0

    return {
        'final': final, 'cagr': cagr, 'sharpe': sharpe, 'sortino': sortino,
        'max_dd': max_dd, 'calmar': calmar, 'trades': len(trades),
        'stops': stop_events,
    }


# ============================================================================
# MAIN
# ============================================================================
if __name__ == "__main__":
    print("=" * 80)
    print("BEHAVIORAL FINANCE OVERLAYS TEST")
    print("Can investor behavior theory improve COMPASS v8.2 stock selection?")
    print("=" * 80)

    # Load data (reuse v3 sweep data loaders)
    print("\nLoading data...")
    price_data = v3.download_broad_pool()
    spy_data = v3.download_spy()
    annual_universe = v3.compute_annual_top40(price_data)
    regime = v3.compute_regime(spy_data)

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    variants = [
        ('baseline',       'A) Baseline *'),
        ('52wk_high',      'B) 52wk-High Blend'),
        ('lottery_filter',  'C) Lottery Filter'),
        ('risk_adj_mom',   'D) Risk-Adj Mom'),
        ('combined',       'E) Combined (B+C+D)'),
    ]

    print(f"\nRunning {len(variants)} backtests...")
    print(f"\n{'Variant':<24} {'CAGR':>8} {'Sharpe':>8} {'Sortino':>8} "
          f"{'MaxDD':>8} {'Calmar':>8} {'Final':>14} {'Trades':>7}")
    print("-" * 95)

    results = {}
    for variant_key, label in variants:
        r = run_behavioral_backtest(
            price_data, annual_universe, spy_data, regime,
            all_dates, first_date, variant=variant_key
        )
        results[variant_key] = r
        print(f"{label:<24} {r['cagr']:>7.2%} {r['sharpe']:>8.3f} {r['sortino']:>8.3f} "
              f"{r['max_dd']:>7.1%} {r['calmar']:>8.3f} ${r['final']:>12,.0f} {r['trades']:>7}")

    # Delta vs baseline
    base = results['baseline']
    print(f"\n{'Variant':<24} {'dCAGR':>8} {'dSharpe':>8} {'dSortino':>8} {'dMaxDD':>8}")
    print("-" * 60)
    for variant_key, label in variants:
        r = results[variant_key]
        dc = r['cagr'] - base['cagr']
        ds = r['sharpe'] - base['sharpe']
        dso = r['sortino'] - base['sortino']
        ddd = r['max_dd'] - base['max_dd']
        print(f"{label:<24} {dc:>+7.2%} {ds:>+8.3f} {dso:>+8.3f} {ddd:>+7.1%}")

    print(f"\n  * = COMPASS v8.2 baseline params (90/5/5, 5 pos, 15% vol target)")
    print(f"  Note: Absolute CAGR differs from production COMPASS due to engine simplifications.")
    print(f"  Delta between variants is what matters for comparison.")

    # Academic references
    print(f"\n  References:")
    print(f"  B) George & Hwang (2004) - 52-week high and momentum profits")
    print(f"  C) Bali, Cakici & Whitelaw (2011) - MAX effect (lottery stocks)")
    print(f"  D) Novy-Marx (2012) - Risk-adjusted momentum")
