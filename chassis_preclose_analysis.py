"""
Chassis Pre-Close Analysis — Same-Day MOC Execution
====================================================
Tests whether computing the momentum signal BEFORE market close
(~15:30 ET) and submitting MOC orders for same-day execution at
Close[T] can recover the -2.92% CAGR execution gap.

5 variants tested:
  A: Close[T] signal + Close[T] exec + 0bps  = ideal (current backtest)
  B: Close[T] signal + Close[T+1] exec + 2bps = current MOC (realistic baseline)
  C: Close[T-1] signal + Close[T] exec + 2bps = pre-close conservative
  D: 0.85*Close+0.15*Open signal + Close[T] exec + 2bps = pre-close blend
  E: Close[T-1] signal + Close[T] exec + 0bps = pre-close ideal (no slippage)

Key insight: momentum lookback is 90 days. Using Close[T-1] instead of
Close[T] for the signal changes the ranking by <1 day out of 90, but
execution moves from T+1 back to T — recovering the overnight gap.
"""

import pandas as pd
import numpy as np
import os
from datetime import timedelta
from typing import Dict, List
from scipy.stats import spearmanr
import warnings
import time as time_module
warnings.filterwarnings('ignore')

# ============================================================================
# MOTOR PARAMETERS (LOCKED — identical to COMPASS v8.2 production)
# ============================================================================
TOP_N = 40
MIN_AGE_DAYS = 63
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3
NUM_POSITIONS = 5
NUM_POSITIONS_RISK_OFF = 2
HOLD_DAYS = 5
POSITION_STOP_LOSS = -0.08
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03
PORTFOLIO_STOP_LOSS = -0.15
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126
TARGET_VOL = 0.15
LEVERAGE_MIN = 0.3
LEVERAGE_MAX = 1.0          # Production: no leverage
VOL_LOOKBACK = 20
INITIAL_CAPITAL = 100_000
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.035     # T-bill proxy

# Pre-close blend weight (85% of intraday move is done by 15:30)
PRECLOSE_BLEND_WEIGHT = 0.85


# ============================================================================
# DATA (Parquet cache — same as other chassis scripts)
# ============================================================================

def load_data():
    cache_dir = 'data_cache_parquet'
    from chassis_execution_analysis import BROAD_POOL
    data = {}
    for symbol in BROAD_POOL:
        pq = os.path.join(cache_dir, f'{symbol}.parquet')
        if os.path.exists(pq):
            df = pd.read_parquet(pq)
            if len(df) > 100:
                data[symbol] = df
    spy = pd.read_parquet(os.path.join(cache_dir, 'SPY.parquet'))
    return data, spy


def build_matrices(price_data, spy_data):
    all_dates = sorted(spy_data.index.tolist())
    symbols = sorted(price_data.keys())
    close_data = {}
    open_data = {}
    volume_data = {}
    for s in symbols:
        df = price_data[s]
        close_data[s] = df['Close'].reindex(all_dates)
        open_data[s] = df['Open'].reindex(all_dates)
        volume_data[s] = df['Volume'].reindex(all_dates)
    close_m = pd.DataFrame(close_data, index=all_dates)
    open_m = pd.DataFrame(open_data, index=all_dates)
    vol_m = pd.DataFrame(volume_data, index=all_dates)
    spy_close = spy_data['Close'].reindex(all_dates)
    return all_dates, close_m, open_m, vol_m, spy_close


def compute_regime(spy_close):
    sma200 = spy_close.rolling(REGIME_SMA_PERIOD).mean()
    raw = spy_close > sma200
    regime = pd.Series(index=spy_close.index, dtype=bool)
    regime.iloc[:REGIME_SMA_PERIOD] = True
    current = True
    consec = 0
    last = True
    for i in range(REGIME_SMA_PERIOD, len(raw)):
        r = raw.iloc[i]
        if pd.isna(r):
            regime.iloc[i] = current
            continue
        if r == last:
            consec += 1
        else:
            consec = 1
            last = r
        if r != current and consec >= REGIME_CONFIRM_DAYS:
            current = r
        regime.iloc[i] = current
    return regime


def compute_top40(close_m, vol_m, all_dates):
    years = sorted(set(d.year for d in all_dates))
    annual = {}
    for year in years:
        mask = np.array([d.year == year - 1 for d in all_dates])
        if mask.sum() < 20:
            continue
        dv = (close_m.iloc[mask] * vol_m.iloc[mask]).mean().dropna()
        top = dv.nlargest(min(TOP_N, len(dv))).index.tolist()
        annual[year] = top
    return annual


# ============================================================================
# SIGNAL MATRICES
# ============================================================================

def build_signal_matrices(close_m, open_m):
    """Build signal price matrices for pre-close analysis.

    Returns dict of {name: DataFrame}:
    - 'close_t': Close[T] — ideal signal (sees today's close)
    - 'close_t_minus_1': Close[T-1] — conservative (yesterday's close only)
    - 'preclose_blend': 0.85*Close[T] + 0.15*Open[T] — approximate 15:30 price
    """
    return {
        'close_t': close_m,
        'close_t_minus_1': close_m.shift(1),
        'preclose_blend': PRECLOSE_BLEND_WEIGHT * close_m + (1 - PRECLOSE_BLEND_WEIGHT) * open_m,
    }


# ============================================================================
# RANKING AGREEMENT ANALYSIS
# ============================================================================

def compute_ranking_agreement(close_m, signal_matrices, all_dates, annual_universe):
    """Compare top-5 stock selection across signal variants.

    For each rebalance-eligible day, compute momentum scores under each
    signal variant and measure how often the top-5 selection matches.
    """
    symbols_list = close_m.columns.tolist()
    first_date = all_dates[0]

    sig_close = signal_matrices['close_t']
    sig_shifted = signal_matrices['close_t_minus_1']
    sig_blend = signal_matrices['preclose_blend']

    exact_match_shifted = 0
    exact_match_blend = 0
    jaccard_shifted_list = []
    jaccard_blend_list = []
    spearman_shifted_list = []
    spearman_blend_list = []
    total_days = 0

    for i, date in enumerate(all_dates):
        if i < MOMENTUM_LOOKBACK + MOMENTUM_SKIP + 1:
            continue

        # Only check on potential rebalance days (every HOLD_DAYS)
        if i % HOLD_DAYS != 0:
            continue

        # Get tradeable universe
        eligible = set(annual_universe.get(date.year, []))
        tradeable = []
        for s in eligible:
            if s not in symbols_list:
                continue
            cv = close_m.iloc[i][s]
            if pd.isna(cv):
                continue
            fv = close_m[s].first_valid_index()
            if fv is None:
                continue
            if date <= first_date + timedelta(days=30) or (date - fv).days >= MIN_AGE_DAYS:
                tradeable.append(s)

        if len(tradeable) < 5:
            continue

        # Compute scores under each signal variant
        def compute_scores(sig_m):
            scores = {}
            for s in tradeable:
                c0 = sig_m.iloc[i][s] if s in sig_m.columns else np.nan
                c5 = sig_m.iloc[i - MOMENTUM_SKIP][s] if s in sig_m.columns else np.nan
                c90 = sig_m.iloc[i - MOMENTUM_LOOKBACK][s] if s in sig_m.columns else np.nan
                if pd.isna(c0) or pd.isna(c5) or pd.isna(c90) or c90 <= 0 or c5 <= 0:
                    continue
                scores[s] = (c5 / c90 - 1) - (c0 / c5 - 1)
            return scores

        scores_close = compute_scores(sig_close)
        scores_shifted = compute_scores(sig_shifted)
        scores_blend = compute_scores(sig_blend)

        if len(scores_close) < 5 or len(scores_shifted) < 5 or len(scores_blend) < 5:
            continue

        # Top 5 for each
        top5_close = set(s for s, _ in sorted(scores_close.items(), key=lambda x: -x[1])[:5])
        top5_shifted = set(s for s, _ in sorted(scores_shifted.items(), key=lambda x: -x[1])[:5])
        top5_blend = set(s for s, _ in sorted(scores_blend.items(), key=lambda x: -x[1])[:5])

        total_days += 1

        # Exact match
        if top5_shifted == top5_close:
            exact_match_shifted += 1
        if top5_blend == top5_close:
            exact_match_blend += 1

        # Jaccard similarity
        j_shifted = len(top5_shifted & top5_close) / len(top5_shifted | top5_close)
        j_blend = len(top5_blend & top5_close) / len(top5_blend | top5_close)
        jaccard_shifted_list.append(j_shifted)
        jaccard_blend_list.append(j_blend)

        # Spearman correlation (on common symbols)
        common_shifted = sorted(set(scores_close.keys()) & set(scores_shifted.keys()))
        common_blend = sorted(set(scores_close.keys()) & set(scores_blend.keys()))

        if len(common_shifted) >= 5:
            vals_c = [scores_close[s] for s in common_shifted]
            vals_s = [scores_shifted[s] for s in common_shifted]
            rho, _ = spearmanr(vals_c, vals_s)
            if not np.isnan(rho):
                spearman_shifted_list.append(rho)

        if len(common_blend) >= 5:
            vals_c = [scores_close[s] for s in common_blend]
            vals_b = [scores_blend[s] for s in common_blend]
            rho, _ = spearmanr(vals_c, vals_b)
            if not np.isnan(rho):
                spearman_blend_list.append(rho)

    return {
        'total_days': total_days,
        'shifted': {
            'exact_match_pct': exact_match_shifted / total_days * 100 if total_days > 0 else 0,
            'avg_jaccard': np.mean(jaccard_shifted_list) if jaccard_shifted_list else 0,
            'avg_spearman': np.mean(spearman_shifted_list) if spearman_shifted_list else 0,
        },
        'blend': {
            'exact_match_pct': exact_match_blend / total_days * 100 if total_days > 0 else 0,
            'avg_jaccard': np.mean(jaccard_blend_list) if jaccard_blend_list else 0,
            'avg_spearman': np.mean(spearman_blend_list) if spearman_blend_list else 0,
        },
    }


# ============================================================================
# BACKTEST (parameterized signal + execution)
# ============================================================================

def run_variant(close_m, open_m, spy_close, all_dates, annual_universe,
                signal_m, exec_mode: str, slippage_bps: int, label: str):
    """Run one variant with decoupled signal and execution.

    signal_m: price matrix for momentum score computation
    exec_mode: 'close_t' (same day) or 'close_t1' (next day MOC)
    slippage_bps: slippage in basis points
    """
    print(f"\n  [{label}] Running...")

    regime = compute_regime(spy_close)
    first_date = all_dates[0]
    symbols_list = close_m.columns.tolist()
    slip_rate = slippage_bps / 10000.0

    def exec_price(i, symbol, direction):
        if exec_mode == 'close_t1' and i + 1 < len(close_m):
            raw = close_m.iloc[i + 1][symbol]
            if pd.isna(raw) or raw <= 0:
                raw = close_m.iloc[i][symbol]
        else:
            raw = close_m.iloc[i][symbol]
        if pd.isna(raw) or raw <= 0:
            return None
        if direction == 'buy':
            return raw * (1.0 + slip_rate)
        else:
            return raw * (1.0 - slip_rate)

    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []
    peak_value = float(INITIAL_CAPITAL)
    in_prot = False
    prot_stage = 0
    stop_day_idx = None

    for i, date in enumerate(all_dates):
        # Tradeable universe (always from close_m, not signal_m)
        eligible = set(annual_universe.get(date.year, []))
        tradeable = []
        for s in eligible:
            if s not in symbols_list:
                continue
            cv = close_m.iloc[i][s]
            if pd.isna(cv):
                continue
            fv = close_m[s].first_valid_index()
            if fv is None:
                continue
            if date <= first_date + timedelta(days=30) or (date - fv).days >= MIN_AGE_DAYS:
                tradeable.append(s)

        # Portfolio value (always at close_m prices)
        pv = cash
        for s, p in positions.items():
            cv = close_m.iloc[i][s]
            if not pd.isna(cv):
                pv += p['shares'] * cv

        if pv > peak_value and not in_prot:
            peak_value = pv

        # Recovery
        if in_prot and stop_day_idx is not None:
            ds = i - stop_day_idx
            ro = bool(regime.iloc[i]) if i < len(regime) else True
            if prot_stage == 1 and ds >= RECOVERY_STAGE_1_DAYS and ro:
                prot_stage = 2
            if prot_stage == 2 and ds >= RECOVERY_STAGE_2_DAYS and ro:
                in_prot = False
                prot_stage = 0
                peak_value = pv
                stop_day_idx = None

        dd = (pv - peak_value) / peak_value if peak_value > 0 else 0

        # Portfolio stop
        if dd <= PORTFOLIO_STOP_LOSS and not in_prot:
            stop_events.append(date)
            for s in list(positions.keys()):
                ep = exec_price(i, s, 'sell')
                p = positions[s]
                if ep is None:
                    cv = close_m.iloc[i][s]
                    ep = cv if not pd.isna(cv) else p['ep']
                cash += p['shares'] * ep - p['shares'] * COMMISSION_PER_SHARE
                pnl = (ep - p['ep']) * p['shares']
                trades.append({'pnl': pnl, 'ret': pnl / (p['ep'] * p['shares'])})
                del positions[s]
            in_prot = True
            prot_stage = 1
            stop_day_idx = i

        # Regime
        is_ro = bool(regime.iloc[i]) if i < len(regime) else True

        # Max pos & leverage
        if in_prot:
            max_pos = 2 if prot_stage == 1 else 3
            lev = 0.3 if prot_stage == 1 else 1.0
        elif not is_ro:
            max_pos = NUM_POSITIONS_RISK_OFF
            lev = 1.0
        else:
            max_pos = NUM_POSITIONS
            if i >= VOL_LOOKBACK + 1:
                rets = spy_close.iloc[i - VOL_LOOKBACK:i + 1].pct_change().dropna()
                if len(rets) >= VOL_LOOKBACK - 2:
                    rv = rets.std() * np.sqrt(252)
                    lev = max(LEVERAGE_MIN, min(LEVERAGE_MAX, TARGET_VOL / rv)) if rv > 0.01 else LEVERAGE_MAX
                else:
                    lev = 1.0
            else:
                lev = 1.0

        # Cash yield (T-bill on uninvested cash)
        if cash > 0:
            cash += cash * (CASH_YIELD_RATE / 252)

        # Exits (use close_m for stop checks, exec_price for execution)
        for s in list(positions.keys()):
            p = positions[s]
            cv = close_m.iloc[i][s]
            if pd.isna(cv):
                continue
            exit_r = None
            if i - p['eidx'] >= HOLD_DAYS:
                exit_r = 'hold'
            pr = (cv - p['ep']) / p['ep']
            if pr <= POSITION_STOP_LOSS:
                exit_r = 'pos_stop'
            if cv > p['high']:
                p['high'] = cv
            if p['high'] > p['ep'] * (1 + TRAILING_ACTIVATION):
                if cv <= p['high'] * (1 - TRAILING_STOP_PCT):
                    exit_r = 'trail'
            if s not in tradeable:
                exit_r = 'univ'
            if exit_r is None and len(positions) > max_pos:
                prs = {}
                for s2, p2 in positions.items():
                    cv2 = close_m.iloc[i][s2]
                    if not pd.isna(cv2):
                        prs[s2] = (cv2 - p2['ep']) / p2['ep']
                if prs and s == min(prs, key=prs.get):
                    exit_r = 'reduce'
            if exit_r:
                ep = exec_price(i, s, 'sell')
                if ep is None:
                    ep = cv
                cash += p['shares'] * ep - p['shares'] * COMMISSION_PER_SHARE
                pnl = (ep - p['ep']) * p['shares']
                trades.append({'pnl': pnl, 'ret': pnl / (p['ep'] * p['shares'])})
                del positions[s]

        # Entries — USES signal_m for momentum scores
        needed = max_pos - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable) >= 5:
            scores = {}
            for s in tradeable:
                if s not in symbols_list or i < MOMENTUM_LOOKBACK + MOMENTUM_SKIP:
                    continue
                # Signal prices from signal_m (decoupled from execution)
                c0 = signal_m.iloc[i][s] if s in signal_m.columns else np.nan
                c5 = signal_m.iloc[i - MOMENTUM_SKIP][s] if s in signal_m.columns else np.nan
                c90 = signal_m.iloc[i - MOMENTUM_LOOKBACK][s] if s in signal_m.columns else np.nan
                if pd.isna(c0) or pd.isna(c5) or pd.isna(c90) or c90 <= 0 or c5 <= 0:
                    continue
                scores[s] = (c5 / c90 - 1) - (c0 / c5 - 1)

            avail = {s: sc for s, sc in scores.items() if s not in positions}
            if len(avail) >= needed:
                sel = [s for s, _ in sorted(avail.items(), key=lambda x: -x[1])[:needed]]
                # Inverse vol weights (from close_m, not signal_m)
                vols = {}
                for s in sel:
                    if i < VOL_LOOKBACK + 1:
                        continue
                    r = close_m[s].iloc[i - VOL_LOOKBACK:i + 1].pct_change().dropna()
                    if len(r) >= VOL_LOOKBACK - 2:
                        v = r.std() * np.sqrt(252)
                        if v > 0.01:
                            vols[s] = v
                if vols:
                    rw = {s: 1.0 / v for s, v in vols.items()}
                    tw = sum(rw.values())
                    wts = {s: w / tw for s, w in rw.items()}
                else:
                    wts = {s: 1.0 / len(sel) for s in sel}

                eff_cap = cash * lev * 0.95
                for s in sel:
                    ep = exec_price(i, s, 'buy')
                    if ep is None:
                        continue
                    w = wts.get(s, 1.0 / len(sel))
                    pv_s = min(eff_cap * w, cash * 0.40)
                    sh = pv_s / ep
                    cost = sh * ep + sh * COMMISSION_PER_SHARE
                    if cost <= cash * 0.90:
                        positions[s] = {'ep': ep, 'shares': sh, 'eidx': i, 'high': ep}
                        cash -= cost

        portfolio_values.append(pv)

    # Metrics
    pv_series = pd.Series(portfolio_values, index=all_dates)
    final = pv_series.iloc[-1]
    years = len(pv_series) / 252
    cagr = (final / INITIAL_CAPITAL) ** (1 / years) - 1
    rets = pv_series.pct_change().dropna()
    vol = rets.std() * np.sqrt(252)
    sharpe = cagr / vol if vol > 0 else 0
    peak_s = pv_series.expanding().max()
    max_dd = ((pv_series - peak_s) / peak_s).min()
    trades_df = pd.DataFrame(trades)
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0

    return {
        'label': label,
        'final': final,
        'cagr': cagr,
        'sharpe': sharpe,
        'max_dd': max_dd,
        'vol': vol,
        'trades': len(trades_df),
        'win_rate': win_rate,
        'stops': len(stop_events),
        'pv_series': pv_series,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("CHASSIS PRE-CLOSE ANALYSIS -- Same-Day MOC Execution")
    print("=" * 80)
    print("Can we compute signal before close and execute same-day?")
    print(f"LEVERAGE_MAX = {LEVERAGE_MAX} (production, no leverage)")

    t0 = time_module.time()

    # Load data
    print("\n[1/5] Loading data (Parquet cache)...")
    price_data, spy_data = load_data()
    print(f"  Loaded {len(price_data)} symbols + SPY")

    print("[2/5] Building aligned matrices...")
    all_dates, close_m, open_m, vol_m, spy_close = build_matrices(price_data, spy_data)
    print(f"  Matrix: {len(all_dates)} dates x {len(close_m.columns)} symbols")

    print("[3/5] Computing annual Top-40...")
    annual = compute_top40(close_m, vol_m, all_dates)

    print("[4/5] Building signal matrices...")
    sig_matrices = build_signal_matrices(close_m, open_m)
    print(f"  Signal variants: {list(sig_matrices.keys())}")

    # Variant definitions
    # (signal_key, exec_mode, slippage_bps, label)
    variants = [
        ('close_t',         'close_t',  0,  "A: Close[T] sig > Close[T] + 0bps (ideal)"),
        ('close_t',         'close_t1', 2,  "B: Close[T] sig > Close[T+1] + 2bps (current MOC)"),
        ('close_t_minus_1', 'close_t',  2,  "C: Close[T-1] sig > Close[T] + 2bps (pre-close conservative)"),
        ('preclose_blend',  'close_t',  2,  "D: Blend sig > Close[T] + 2bps (pre-close blend)"),
        ('close_t_minus_1', 'close_t',  0,  "E: Close[T-1] sig > Close[T] + 0bps (pre-close ideal)"),
    ]

    print("\n[5/5] Running 5 backtest variants...")
    print("=" * 80)

    results = []
    for sig_key, exec_mode, slip, label in variants:
        r = run_variant(close_m, open_m, spy_close, all_dates, annual,
                        signal_m=sig_matrices[sig_key],
                        exec_mode=exec_mode,
                        slippage_bps=slip,
                        label=label)
        results.append(r)
        print(f"    -> CAGR: {r['cagr']:.2%} | Sharpe: {r['sharpe']:.3f} | "
              f"MaxDD: {r['max_dd']:.1%} | Final: ${r['final']:,.0f}")

    t_backtest = time_module.time() - t0

    # ======================================================================
    # RESULTS
    # ======================================================================
    print("\n" + "=" * 80)
    print("RESULTS SUMMARY -- Pre-Close Signal Analysis")
    print("=" * 80)

    print(f"\n  {'Variant':<50} {'CAGR':>7} {'Sharpe':>7} {'MaxDD':>7} {'Final':>14} {'Win%':>6} {'Trades':>7}")
    print(f"  {'-'*98}")
    for r in results:
        print(f"  {r['label']:<50} {r['cagr']:>6.2%} {r['sharpe']:>7.3f} "
              f"{r['max_dd']:>6.1%} ${r['final']:>12,.0f} {r['win_rate']:>5.1%} {r['trades']:>7}")

    # Delta vs B (current MOC realistic)
    B = results[1]
    print(f"\n  {'='*70}")
    print(f"  DELTA vs B (current MOC realistic: {B['cagr']:.2%} CAGR)")
    print(f"  {'='*70}")
    print(f"  {'Variant':<50} {'dCAGR':>8} {'dSharpe':>8} {'dMaxDD':>8}")
    print(f"  {'-'*76}")
    for r in results:
        if r['label'] == B['label']:
            continue
        print(f"  {r['label']:<50} {r['cagr']-B['cagr']:>+7.2%} {r['sharpe']-B['sharpe']:>+8.3f} "
              f"{r['max_dd']-B['max_dd']:>+7.1%}")

    # Recovery calculation
    A = results[0]
    print(f"\n  {'='*70}")
    print(f"  EXECUTION GAP RECOVERY")
    print(f"  {'='*70}")
    total_gap = A['cagr'] - B['cagr']
    print(f"  Total gap (A ideal - B realistic):  {total_gap:>+7.2%} CAGR")
    for r in results[2:]:
        recovered = r['cagr'] - B['cagr']
        pct_recovered = (recovered / total_gap * 100) if total_gap != 0 else 0
        print(f"  {r['label'][:45]:<45}  recovered {recovered:>+6.2%} ({pct_recovered:>5.1f}% of gap)")

    # ======================================================================
    # RANKING AGREEMENT ANALYSIS
    # ======================================================================
    print(f"\n{'='*80}")
    print("RANKING AGREEMENT ANALYSIS")
    print("=" * 80)
    print("How often does the top-5 selection match vs ideal Close[T] signal?")

    t_rank = time_module.time()
    agreement = compute_ranking_agreement(close_m, sig_matrices, all_dates, annual)
    t_rank = time_module.time() - t_rank

    print(f"\n  Rebalance days analyzed: {agreement['total_days']}")

    print(f"\n  Close[T-1] vs Close[T] (conservative pre-close):")
    s = agreement['shifted']
    print(f"    Exact top-5 match:         {s['exact_match_pct']:>6.1f}%")
    print(f"    Average Jaccard similarity: {s['avg_jaccard']:>6.3f}")
    print(f"    Average Spearman rho:       {s['avg_spearman']:>6.3f}")

    print(f"\n  Blend (0.85C+0.15O) vs Close[T] (blend pre-close):")
    b = agreement['blend']
    print(f"    Exact top-5 match:         {b['exact_match_pct']:>6.1f}%")
    print(f"    Average Jaccard similarity: {b['avg_jaccard']:>6.3f}")
    print(f"    Average Spearman rho:       {b['avg_spearman']:>6.3f}")

    # ======================================================================
    # CONCLUSION
    # ======================================================================
    best_preclose = max(results[2:], key=lambda r: r['cagr'])
    print(f"\n{'='*80}")
    print("CONCLUSION")
    print("=" * 80)
    print(f"  Current MOC (B):       {B['cagr']:.2%} CAGR | {B['sharpe']:.3f} Sharpe | {B['max_dd']:.1%} MaxDD")
    print(f"  Best pre-close ({best_preclose['label'][:1]}):    {best_preclose['cagr']:.2%} CAGR | "
          f"{best_preclose['sharpe']:.3f} Sharpe | {best_preclose['max_dd']:.1%} MaxDD")
    improvement = best_preclose['cagr'] - B['cagr']
    print(f"  Improvement:           {improvement:>+.2%} CAGR")

    if improvement > 0.005:  # > 0.5% CAGR improvement
        print(f"\n  [OK] PRE-CLOSE EXECUTION IS VIABLE")
        print(f"    Computing signal at 15:30 ET and submitting same-day MOC orders")
        print(f"    recovers {improvement:.2%} CAGR ({improvement/total_gap*100:.0f}% of the execution gap).")
    else:
        print(f"\n  [NO] PRE-CLOSE EXECUTION DOES NOT HELP MATERIALLY")

    t_total = time_module.time() - t0
    print(f"\n  Timing: backtests {t_backtest:.0f}s | ranking {t_rank:.0f}s | total {t_total:.0f}s")

    # Save CSV
    os.makedirs('backtests', exist_ok=True)
    comp = pd.DataFrame([{
        'variant': r['label'],
        'cagr_pct': round(r['cagr'] * 100, 2),
        'sharpe': round(r['sharpe'], 3),
        'max_dd_pct': round(r['max_dd'] * 100, 1),
        'final_value': round(r['final'], 0),
        'trades': r['trades'],
        'win_rate_pct': round(r['win_rate'] * 100, 1),
        'stops': r['stops'],
        'delta_cagr_vs_B': round((r['cagr'] - B['cagr']) * 100, 2),
    } for r in results])
    comp.to_csv('backtests/preclose_comparison.csv', index=False)
    print(f"\n  Saved: backtests/preclose_comparison.csv")

    print("\n" + "=" * 80)
    print("ANALYSIS COMPLETE")
    print("=" * 80)
