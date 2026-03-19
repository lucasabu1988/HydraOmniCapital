"""
HYDRA Backtest Lab — Portfolio Construction Experiments
=======================================================
Runs COMPASS v84 baseline + experimental variants.
NEVER modifies omnicapital_v84_compass.py or live engine.
"""
import os
import sys
import time
import numpy as np
import pandas as pd
from pathlib import Path

# Safety: refuse to run if imported by live engine
SAFETY_CHECK = True
assert 'omnicapital_live' not in sys.modules, \
    "backtest_lab must NEVER be imported by the live engine"

import omnicapital_v84_compass as v84

RESULTS_DIR = Path('backtests/lab_results')
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

SEED = 666


# ─── Patching helpers ───────────────────────────────────────

def _patch_module(module, patches: dict) -> dict:
    originals = {}
    for attr, new_val in patches.items():
        originals[attr] = getattr(module, attr)
        setattr(module, attr, new_val)
    return originals


def _restore_module(module, originals: dict):
    for attr, orig_val in originals.items():
        setattr(module, attr, orig_val)


def run_experiment(name: str, patches: dict = None, cached_data: dict = None):
    patches = patches or {}
    originals = _patch_module(v84, patches)
    try:
        np.random.seed(SEED)
        print(f"\n{'='*60}")
        print(f"  EXPERIMENT: {name}")
        print(f"  Patches: {list(patches.keys()) if patches else 'none (baseline)'}")
        print(f"{'='*60}\n")

        t0 = time.time()
        if cached_data:
            price_data = cached_data['price_data']
            spy_data = cached_data['spy_data']
            cash_yield = cached_data['cash_yield']
        else:
            price_data = v84.download_broad_pool()
            spy_data = v84.download_spy()
            cash_yield = v84.download_cash_yield()
        annual_universe = v84.compute_annual_top40(price_data)
        results = v84.run_backtest(price_data, annual_universe, spy_data, cash_yield)
        metrics = v84.calculate_metrics(results)
        elapsed = time.time() - t0

        print(f"\n  {name} completed in {elapsed:.1f}s")
        return {
            'name': name,
            'metrics': metrics,
            'results': results,
            'elapsed': elapsed,
        }
    finally:
        _restore_module(v84, originals)


# ─── Data cache ─────────────────────────────────────────────

def download_all_data():
    print("Downloading data (one-time)...")
    price_data = v84.download_broad_pool()
    spy_data = v84.download_spy()
    cash_yield = v84.download_cash_yield()
    return {'price_data': price_data, 'spy_data': spy_data, 'cash_yield': cash_yield}


# ─── Experiment 1: Correlation-Aware Selection ──────────────

CORR_PENALTY = 0.5
CORR_LOOKBACK = 60

# Mutable date tracker — updated by patched compute_momentum_scores
_current_sim_date = [None]


def make_momentum_scores_date_tracker():
    _original_fn = v84.compute_momentum_scores

    def wrapped(price_data, universe, date, *args, **kwargs):
        _current_sim_date[0] = date
        return _original_fn(price_data, universe, date, *args, **kwargs)

    return wrapped


def correlation_aware_filter(candidates, already_selected, price_data, date, lookback=CORR_LOOKBACK):
    """
    Greedy sequential correlation filter.
    Penalizes candidates correlated with already-selected positions.
    Returns: list of (symbol, adjusted_score) tuples, re-ranked.
    """
    if not candidates:
        return []

    if not already_selected:
        return candidates

    adjusted = []
    for sym, score in candidates:
        if sym not in price_data or not already_selected:
            adjusted.append((sym, score))
            continue

        corrs = []
        sym_df = price_data[sym]
        if date is not None:
            sym_close = sym_df['Close'].loc[:date]
        else:
            sym_close = sym_df['Close']
        sym_returns = sym_close.pct_change().dropna().tail(lookback)

        for sel_sym in already_selected:
            if sel_sym not in price_data:
                continue
            sel_df = price_data[sel_sym]
            if date is not None:
                sel_close = sel_df['Close'].loc[:date]
            else:
                sel_close = sel_df['Close']
            sel_returns = sel_close.pct_change().dropna().tail(lookback)

            common = sym_returns.index.intersection(sel_returns.index)
            if len(common) < 20:
                continue
            corr = sym_returns.loc[common].corr(sel_returns.loc[common])
            if not np.isnan(corr):
                corrs.append(corr)

        if corrs:
            avg_corr = np.mean(corrs)
            adj_score = score * (1 - avg_corr * CORR_PENALTY)
        else:
            adj_score = score

        adjusted.append((sym, adj_score))

    adjusted.sort(key=lambda x: x[1], reverse=True)
    return adjusted


def make_correlation_filter_wrapper(price_data_cache):
    """
    Returns a function matching v84.filter_by_sector_concentration signature.
    Input: ranked = List[Tuple[str, float]], positions = Dict
    Output: List[str]  (symbol names only)
    """
    _original_sector_filter = v84.filter_by_sector_concentration

    def wrapped_filter(ranked, positions, *args, **kwargs):
        # Step 1: Call original sector filter → List[str]
        sector_filtered = _original_sector_filter(ranked, positions, *args, **kwargs)

        # Step 2: Look up momentum scores from ranked for the filtered symbols
        score_lookup = dict(ranked)
        candidates_with_scores = [(sym, score_lookup.get(sym, 0.0)) for sym in sector_filtered]

        # Step 3: Get already-held position symbols
        already_held = list(positions.keys()) if isinstance(positions, dict) else []

        if not already_held or not price_data_cache:
            return sector_filtered

        # Step 4: Apply correlation filter
        date = _current_sim_date[0]
        adjusted = correlation_aware_filter(
            candidates_with_scores, already_held, price_data_cache, date
        )

        # Step 5: Convert back to List[str]
        return [sym for sym, _ in adjusted]

    return wrapped_filter


# ─── Experiment 2: Risk Parity Sizing ───────────────────────

RISK_PARITY_LOOKBACK = 60
RISK_PARITY_MAX_ITER = 1000
RISK_PARITY_EPS = 1e-8
POSITION_CAP = 0.40


def _ledoit_wolf_shrink(returns_matrix):
    T, N = returns_matrix.shape
    if T < 2 or N < 1:
        return np.eye(N)

    sample_cov = np.cov(returns_matrix, rowvar=False)
    if N == 1:
        return sample_cov.reshape(1, 1)

    mu = np.trace(sample_cov) / N
    target = mu * np.eye(N)

    delta = sample_cov - target
    delta_sq_sum = np.sum(delta ** 2)

    X = returns_matrix - returns_matrix.mean(axis=0)
    sum_sq = 0
    for t in range(T):
        x = X[t:t+1].T @ X[t:t+1]
        sum_sq += np.sum((x - sample_cov) ** 2)
    pi_hat = sum_sq / T

    shrinkage = max(0, min(1, pi_hat / (T * delta_sq_sum))) if delta_sq_sum > 0 else 1.0

    return (1 - shrinkage) * sample_cov + shrinkage * target


def compute_risk_parity_weights(price_data, selected, date, lookback=RISK_PARITY_LOOKBACK):
    """
    Equal risk contribution weights via iterative method.
    Falls back to inverse-vol if cov matrix is degenerate.
    """
    N = len(selected)
    if N <= 1:
        return {s: 1.0 for s in selected}

    # Build returns matrix (point-in-time)
    returns = {}
    for sym in selected:
        if sym not in price_data:
            return {s: 1.0 / N for s in selected}
        df = price_data[sym]
        close = df['Close'].loc[:date] if date is not None else df['Close']
        r = close.pct_change().dropna().tail(lookback)
        returns[sym] = r

    # Align on common dates
    common_idx = returns[selected[0]].index
    for sym in selected[1:]:
        common_idx = common_idx.intersection(returns[sym].index)

    if len(common_idx) < 20:
        return {s: 1.0 / N for s in selected}

    ret_matrix = np.column_stack([returns[s].loc[common_idx].values for s in selected])

    # Shrunk covariance
    cov = _ledoit_wolf_shrink(ret_matrix)

    # Check for degenerate matrix
    if np.any(np.diag(cov) <= 0) or np.linalg.matrix_rank(cov) < N:
        vols = np.sqrt(np.maximum(np.diag(cov), 0))
        vols = np.where(vols > 0, vols, 1.0)
        raw = 1.0 / vols
        return dict(zip(selected, raw / raw.sum()))

    # Iterative risk parity (Spinu 2013 simplified)
    w = np.ones(N) / N
    for _ in range(RISK_PARITY_MAX_ITER):
        sigma_w = cov @ w
        mrc = w * sigma_w
        total_risk = w @ sigma_w
        rc = mrc / total_risk

        target_rc = np.ones(N) / N
        adjustment = target_rc / np.where(rc > 1e-12, rc, 1e-12)
        w_new = w * adjustment
        w_new = w_new / w_new.sum()

        if np.max(np.abs(w_new - w)) < RISK_PARITY_EPS:
            w = w_new
            break
        w = w_new

    w = np.maximum(w, 0)
    w = np.minimum(w, POSITION_CAP)
    w = w / w.sum()

    return dict(zip(selected, w))


# ─── Comparison ─────────────────────────────────────────────

def compare_results(experiments: list):
    rows = []
    for exp in experiments:
        m = exp['metrics']
        rows.append({
            'Variant': exp['name'],
            'CAGR': round(m.get('cagr', 0) * 100, 2),
            'MaxDD': round(m.get('max_drawdown', 0) * 100, 2),
            'Sharpe': round(m.get('sharpe', 0), 2),
            'Sortino': round(m.get('sortino', 0), 2),
            'Calmar': round(m.get('calmar', 0), 2),
            'Trades': m.get('total_trades', 0),
            'Win%': round(m.get('win_rate', 0) * 100, 1),
            'Avg Lev': round(m.get('avg_leverage', 1.0), 2),
        })

    df = pd.DataFrame(rows)

    if len(rows) > 1:
        baseline = rows[0]
        for col in ['CAGR', 'MaxDD', 'Sharpe']:
            df[f'Δ{col}'] = df[col] - baseline[col]

    print("\n" + "="*90)
    print("  BACKTEST LAB — COMPARISON TABLE")
    print("="*90)
    print(df.to_string(index=False))

    outpath = RESULTS_DIR / 'comparison.csv'
    df.to_csv(outpath, index=False)
    print(f"\n  Saved to {outpath}")

    # Save individual equity curves
    for exp in experiments:
        pv = exp['results'].get('portfolio_values')
        if pv is not None and isinstance(pv, pd.DataFrame):
            name_slug = exp['name'].lower().replace(' ', '_')
            pv.to_csv(RESULTS_DIR / f'{name_slug}_daily.csv', index=False)

    # Sub-period analysis
    print("\n" + "="*90)
    print("  SUB-PERIOD ANALYSIS")
    print("="*90)
    for exp in experiments:
        pv = exp['results'].get('portfolio_values')
        if pv is not None and isinstance(pv, pd.DataFrame) and 'date' in pv.columns:
            pv_copy = pv.copy()
            pv_copy['date'] = pd.to_datetime(pv_copy['date'])
            for label, start, end in [('2000-2012', '2000-01-01', '2012-12-31'),
                                       ('2013-2026', '2013-01-01', '2026-12-31')]:
                mask = (pv_copy['date'] >= start) & (pv_copy['date'] <= end)
                sub = pv_copy.loc[mask, 'value']
                if len(sub) > 252:
                    total_ret = sub.iloc[-1] / sub.iloc[0]
                    years = len(sub) / 252
                    cagr = (total_ret ** (1 / years) - 1) * 100
                    dd = ((sub / sub.cummax()) - 1).min() * 100
                    print(f"  {exp['name']:20s} | {label} | CAGR: {cagr:+.2f}% | MaxDD: {dd:.2f}%")

    return df


# ─── Main ───────────────────────────────────────────────────

if __name__ == '__main__':
    experiments = []
    data = download_all_data()

    # Baseline
    experiments.append(run_experiment('BASELINE', cached_data=data))

    # Experiment 3: Universe 80
    experiments.append(run_experiment('UNIVERSE_80', {'TOP_N': 80}, cached_data=data))

    # Experiment 1: Correlation filter
    corr_patches = {
        'compute_momentum_scores': make_momentum_scores_date_tracker(),
        'filter_by_sector_concentration': make_correlation_filter_wrapper(data['price_data']),
    }
    experiments.append(run_experiment('CORR_FILTER', corr_patches, cached_data=data))

    # Experiment 2: Risk parity sizing
    experiments.append(run_experiment('RISK_PARITY', {
        'compute_volatility_weights': compute_risk_parity_weights,
    }, cached_data=data))

    # Experiment 4: Vol-targeting leverage
    experiments.append(run_experiment('VOL_TARGET_LEV', {
        'LEVERAGE_MAX': 2.0,
        'TARGET_VOL': 0.12,
        'MARGIN_RATE': 0.0514,
    }, cached_data=data))

    # Experiment 5: ALL COMBINED
    combined_patches = {
        'TOP_N': 80,
        'LEVERAGE_MAX': 2.0,
        'TARGET_VOL': 0.12,
        'MARGIN_RATE': 0.0514,
        'compute_momentum_scores': make_momentum_scores_date_tracker(),
        'filter_by_sector_concentration': make_correlation_filter_wrapper(data['price_data']),
        'compute_volatility_weights': compute_risk_parity_weights,
    }
    experiments.append(run_experiment('ALL_COMBINED', combined_patches, cached_data=data))

    # Compare all
    compare_results(experiments)
