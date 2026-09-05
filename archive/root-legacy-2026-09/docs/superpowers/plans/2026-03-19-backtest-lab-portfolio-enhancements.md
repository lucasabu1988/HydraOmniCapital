# Backtest Lab: Portfolio Construction Enhancements — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `backtest_lab.py` that runs COMPASS v84 with 4 portfolio construction enhancements and compares metrics side-by-side.

**Architecture:** Single new file imports `omnicapital_v84_compass` as a module, patches specific attributes/functions per experiment, runs `run_backtest()`, restores originals. The v84 file is NEVER modified.

**Tech Stack:** Python 3.14, numpy, pandas, scipy (Ledoit-Wolf via manual impl or sklearn.covariance)

**Spec:** `docs/superpowers/specs/2026-03-19-backtest-lab-portfolio-enhancements-design.md`

---

## File Structure

| File | Responsibility |
|------|---------------|
| `backtest_lab.py` (CREATE) | Experiment runner: patching, execution, comparison |
| `tests/test_backtest_lab.py` (CREATE) | Unit tests for new functions (correlation filter, risk parity, comparison) |
| `backtests/lab_results/` (CREATE dir) | Output CSVs and comparison tables |

**NOT modified:** `omnicapital_v84_compass.py`, `omnicapital_live.py`, any `state/` files.

---

### Task 1: Scaffold `backtest_lab.py` with baseline runner

**Files:**
- Create: `backtest_lab.py`
- Create: `tests/test_backtest_lab.py`
- Create: `backtests/lab_results/` (directory)

- [ ] **Step 1: Create output directory**

```bash
mkdir -p backtests/lab_results
```

- [ ] **Step 2: Write test for the patching mechanism**

```python
# tests/test_backtest_lab.py
import pytest

def test_patch_and_restore():
    """Verify module attributes are restored after experiment."""
    import omnicapital_v84_compass as v84
    original_top_n = v84.TOP_N  # should be 40

    from backtest_lab import run_experiment
    # Dry-run with a simple patch (don't actually run backtest - too slow)
    # Instead test the patch/restore mechanism
    from backtest_lab import _patch_module, _restore_module

    patches = {'TOP_N': 80}
    originals = _patch_module(v84, patches)
    assert v84.TOP_N == 80
    _restore_module(v84, originals)
    assert v84.TOP_N == original_top_n


def test_safety_assertion():
    """Verify lab refuses to touch live state files."""
    from backtest_lab import SAFETY_CHECK
    assert SAFETY_CHECK is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_backtest_lab.py -v`
Expected: FAIL (backtest_lab not found)

- [ ] **Step 4: Write `backtest_lab.py` scaffold**

```python
# backtest_lab.py
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
    """Apply patches to module, return originals for restore."""
    originals = {}
    for attr, new_val in patches.items():
        originals[attr] = getattr(module, attr)
        setattr(module, attr, new_val)
    return originals


def _restore_module(module, originals: dict):
    """Restore original module attributes."""
    for attr, orig_val in originals.items():
        setattr(module, attr, orig_val)


def run_experiment(name: str, patches: dict = None, cached_data: dict = None):
    """Run a single experiment with optional module patches.

    cached_data: pre-downloaded data dict with keys 'price_data', 'spy_data',
    'cash_yield'. If None, downloads fresh (only for first run).
    """
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
    """Download data once, reuse across all experiments."""
    print("Downloading data (one-time)...")
    price_data = v84.download_broad_pool()
    spy_data = v84.download_spy()
    cash_yield = v84.download_cash_yield()
    return {'price_data': price_data, 'spy_data': spy_data, 'cash_yield': cash_yield}


# ─── Comparison ─────────────────────────────────────────────

def compare_results(experiments: list):
    """Print side-by-side comparison table."""
    rows = []
    for exp in experiments:
        m = exp['metrics']
        rows.append({
            'Variant': exp['name'],
            'CAGR': m.get('cagr', 0),
            'MaxDD': m.get('max_drawdown', 0),
            'Sharpe': m.get('sharpe', 0),
            'Sortino': m.get('sortino', 0),
            'Calmar': m.get('calmar', 0),
            'Trades': m.get('total_trades', 0),
            'Win%': m.get('win_rate', 0),
            'Avg Lev': m.get('avg_leverage', 1.0),
        })

    df = pd.DataFrame(rows)
    print("\n" + "="*80)
    print("  BACKTEST LAB — COMPARISON TABLE")
    print("="*80)
    print(df.to_string(index=False, float_format='{:.2f}'.format))

    # Save to CSV
    outpath = RESULTS_DIR / 'comparison.csv'
    df.to_csv(outpath, index=False)
    print(f"\n  Saved to {outpath}")
    return df


# ─── Main ───────────────────────────────────────────────────

if __name__ == '__main__':
    experiments = []
    data = download_all_data()

    # Baseline
    experiments.append(run_experiment('BASELINE', cached_data=data))

    # Compare
    compare_results(experiments)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_backtest_lab.py -v`
Expected: PASS (both tests)

- [ ] **Step 6: Commit**

```bash
git add backtest_lab.py tests/test_backtest_lab.py
git commit -m "feat: scaffold backtest_lab.py with patching mechanism and baseline runner"
```

---

### Task 2: Experiment 3 — Universe Expansion (40 → 80)

Simplest experiment. Just patches `TOP_N`. Validates the framework works end-to-end.

**Files:**
- Modify: `backtest_lab.py`
- Modify: `tests/test_backtest_lab.py`

- [ ] **Step 1: Write test for universe experiment**

```python
# tests/test_backtest_lab.py (append)
def test_universe_80_patches_top_n():
    """Universe experiment patches TOP_N to 80."""
    import omnicapital_v84_compass as v84
    from backtest_lab import _patch_module, _restore_module

    patches = {'TOP_N': 80}
    originals = _patch_module(v84, patches)
    assert v84.TOP_N == 80
    _restore_module(v84, originals)
    assert v84.TOP_N == 40
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_backtest_lab.py::test_universe_80_patches_top_n -v`

- [ ] **Step 3: Add universe experiment to main block**

In `backtest_lab.py`, add to the `if __name__ == '__main__':` block after baseline:

```python
    # Experiment 3: Universe 80
    experiments.append(run_experiment('UNIVERSE_80', {'TOP_N': 80}, cached_data=data))
```

- [ ] **Step 4: Commit**

```bash
git add backtest_lab.py tests/test_backtest_lab.py
git commit -m "feat: add universe expansion experiment (TOP_N=80)"
```

---

### Task 3: Experiment 1 — Correlation-Aware Selection

**Files:**
- Modify: `backtest_lab.py`
- Modify: `tests/test_backtest_lab.py`

- [ ] **Step 1: Write test for correlation filter**

```python
# tests/test_backtest_lab.py (append)
def test_correlation_filter_reduces_correlated_picks():
    """Highly correlated candidates should be penalized."""
    import numpy as np
    import pandas as pd
    from backtest_lab import correlation_aware_filter

    # Create fake price data: A and B are perfectly correlated, C is uncorrelated
    dates = pd.date_range('2020-01-01', periods=60, freq='B')
    base = np.cumsum(np.random.RandomState(666).randn(60)) + 100
    noise = np.cumsum(np.random.RandomState(42).randn(60)) + 100

    price_data = {
        'A': pd.DataFrame({'Close': base}, index=dates),
        'B': pd.DataFrame({'Close': base * 1.01 + 0.5}, index=dates),  # ~1.0 corr with A
        'C': pd.DataFrame({'Close': noise}, index=dates),               # uncorrelated
    }

    # Candidates ranked by momentum: B > C (A is already selected)
    candidates = [('B', 1.0), ('C', 0.95)]  # B has higher momentum
    already_selected = ['A']

    result = correlation_aware_filter(
        candidates, already_selected, price_data, dates[-1], lookback=60
    )

    # C should rank higher than B after penalty (B is correlated with A)
    symbols = [s for s, _ in result]
    assert symbols[0] == 'C', f"Expected C first (uncorrelated), got {symbols[0]}"


def test_correlation_filter_empty_positions():
    """First candidate should get zero penalty (no positions to correlate against)."""
    import pandas as pd
    import numpy as np
    from backtest_lab import correlation_aware_filter

    dates = pd.date_range('2020-01-01', periods=60, freq='B')
    price_data = {
        'A': pd.DataFrame({'Close': np.random.RandomState(1).randn(60).cumsum() + 100}, index=dates),
    }
    candidates = [('A', 1.0)]
    result = correlation_aware_filter(candidates, [], price_data, dates[-1], lookback=60)
    assert len(result) == 1
    assert result[0][1] == 1.0  # unpenalized score
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_backtest_lab.py::test_correlation_filter_reduces_correlated_picks -v`
Expected: FAIL (correlation_aware_filter not found)

- [ ] **Step 3: Implement `correlation_aware_filter`**

In `backtest_lab.py`, add:

```python
CORR_PENALTY = 0.5
CORR_LOOKBACK = 60

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

    # Build returns matrix for the lookback window
    end_idx = None
    for sym in list(dict(candidates).keys()) + list(already_selected):
        if sym in price_data:
            df = price_data[sym]
            if hasattr(df.index, 'get_loc'):
                try:
                    loc = df.index.get_indexer([date], method='ffill')[0]
                    if end_idx is None or loc < end_idx:
                        end_idx = loc
                except:
                    pass

    adjusted = []
    for sym, score in candidates:
        if sym not in price_data or not already_selected:
            adjusted.append((sym, score))
            continue

        # Compute avg correlation with already_selected positions
        corrs = []
        sym_df = price_data[sym]
        # Point-in-time: only use data up to 'date' to avoid lookahead bias
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

            # Align on common dates
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

    # Re-rank by adjusted score
    adjusted.sort(key=lambda x: x[1], reverse=True)
    return adjusted
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_backtest_lab.py -k "correlation" -v`
Expected: PASS

- [ ] **Step 5: Write test for the wrapper integration**

```python
# tests/test_backtest_lab.py (append)
def test_correlation_wrapper_returns_list_of_strings():
    """Wrapper must return List[str] to match v84's filter_by_sector_concentration."""
    import numpy as np
    import pandas as pd
    from backtest_lab import make_correlation_filter_wrapper

    dates = pd.date_range('2020-01-01', periods=60, freq='B')
    base = np.cumsum(np.random.RandomState(666).randn(60)) + 100
    noise = np.cumsum(np.random.RandomState(42).randn(60)) + 100
    price_data = {
        'A': pd.DataFrame({'Close': base}, index=dates),
        'B': pd.DataFrame({'Close': base * 1.01}, index=dates),
        'C': pd.DataFrame({'Close': noise}, index=dates),
    }

    # Simulate: ranked is List[Tuple[str, float]], positions is dict
    ranked = [('A', 1.0), ('B', 0.9), ('C', 0.8)]
    positions = {'A': {'shares': 10}}  # A already held

    # Fake sector filter that just returns symbol names
    wrapper = make_correlation_filter_wrapper(price_data)
    result = wrapper(ranked, positions)

    # Must return List[str], not List[Tuple]
    assert all(isinstance(s, str) for s in result)
```

- [ ] **Step 6: Create wrapper that integrates with v84's filter**

**Critical**: v84's `filter_by_sector_concentration` returns `List[str]` (not tuples).
The wrapper must: (a) call original filter → get `List[str]`, (b) look up scores from `ranked`,
(c) convert to `List[Tuple]` for correlation filter, (d) convert back to `List[str]`.

**Date issue**: The filter call site in v84 does NOT pass a date. We use a mutable `_current_date`
reference updated by patching `compute_momentum_scores` (which IS called with the current date).

In `backtest_lab.py`, add:

```python
# Mutable date tracker — updated by patched compute_momentum_scores
_current_sim_date = [None]

def make_momentum_scores_date_tracker():
    """Wraps v84.compute_momentum_scores to capture the current simulation date."""
    _original_fn = v84.compute_momentum_scores

    def wrapped(price_data, universe, date, *args, **kwargs):
        _current_sim_date[0] = date
        return _original_fn(price_data, universe, date, *args, **kwargs)

    return wrapped


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
        score_lookup = dict(ranked)  # {symbol: score}
        candidates_with_scores = [(sym, score_lookup.get(sym, 0.0)) for sym in sector_filtered]

        # Step 3: Get already-held position symbols
        already_held = list(positions.keys()) if isinstance(positions, dict) else []

        if not already_held or not price_data_cache:
            return sector_filtered

        # Step 4: Apply correlation filter → List[Tuple[str, float]]
        date = _current_sim_date[0]
        adjusted = correlation_aware_filter(
            candidates_with_scores, already_held, price_data_cache, date
        )

        # Step 5: Convert back to List[str]
        return [sym for sym, _ in adjusted]

    return wrapped_filter
```

- [ ] **Step 7: Add correlation experiment to main block**

```python
    # Experiment 1: Correlation filter
    corr_patches = {
        'compute_momentum_scores': make_momentum_scores_date_tracker(),
        'filter_by_sector_concentration': make_correlation_filter_wrapper(data['price_data']),
    }
    experiments.append(run_experiment('CORR_FILTER', corr_patches, cached_data=data))
```

- [ ] **Step 7: Commit**

```bash
git add backtest_lab.py tests/test_backtest_lab.py
git commit -m "feat: add correlation-aware selection filter (experiment 1)"
```

---

### Task 4: Experiment 2 — Risk Parity Sizing

**Files:**
- Modify: `backtest_lab.py`
- Modify: `tests/test_backtest_lab.py`

- [ ] **Step 1: Write test for risk parity weights**

```python
# tests/test_backtest_lab.py (append)
def test_risk_parity_weights_sum_to_one():
    """Risk parity weights must sum to 1.0."""
    import numpy as np
    import pandas as pd
    from backtest_lab import compute_risk_parity_weights

    dates = pd.date_range('2020-01-01', periods=120, freq='B')
    rs = np.random.RandomState(666)
    price_data = {}
    for sym in ['A', 'B', 'C']:
        price_data[sym] = pd.DataFrame(
            {'Close': 100 + rs.randn(120).cumsum()},
            index=dates
        )

    weights = compute_risk_parity_weights(price_data, ['A', 'B', 'C'], dates[-1])
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_risk_parity_correlated_stocks_get_less():
    """Highly correlated stocks should get lower weight than uncorrelated."""
    import numpy as np
    import pandas as pd
    from backtest_lab import compute_risk_parity_weights

    dates = pd.date_range('2020-01-01', periods=120, freq='B')
    rs = np.random.RandomState(666)
    base = rs.randn(120).cumsum()

    price_data = {
        'CORR1': pd.DataFrame({'Close': 100 + base}, index=dates),
        'CORR2': pd.DataFrame({'Close': 100 + base + rs.randn(120) * 0.1}, index=dates),
        'INDEP': pd.DataFrame({'Close': 100 + rs.randn(120).cumsum()}, index=dates),
    }

    weights = compute_risk_parity_weights(price_data, ['CORR1', 'CORR2', 'INDEP'], dates[-1])

    # INDEP should get more weight than each of CORR1, CORR2
    assert weights['INDEP'] > weights['CORR1']
    assert weights['INDEP'] > weights['CORR2']


def test_risk_parity_fallback_on_singular():
    """Fallback to inverse-vol when cov matrix is degenerate."""
    import numpy as np
    import pandas as pd
    from backtest_lab import compute_risk_parity_weights

    dates = pd.date_range('2020-01-01', periods=10, freq='B')  # too few observations
    price_data = {
        'A': pd.DataFrame({'Close': [100]*10}, index=dates),  # zero vol
        'B': pd.DataFrame({'Close': [100]*10}, index=dates),
    }

    weights = compute_risk_parity_weights(price_data, ['A', 'B'], dates[-1])
    # Should fallback to equal weight for zero-vol degenerate case
    assert len(weights) == 2
    assert all(w >= 0 for w in weights.values())
    assert abs(sum(weights.values()) - 1.0) < 1e-6
    # Equal weight expected for identical zero-vol stocks
    assert abs(weights['A'] - 0.5) < 0.1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_backtest_lab.py -k "risk_parity" -v`

- [ ] **Step 3: Implement `compute_risk_parity_weights`**

In `backtest_lab.py`, add:

```python
RISK_PARITY_LOOKBACK = 60
RISK_PARITY_MAX_ITER = 1000
RISK_PARITY_EPS = 1e-8
POSITION_CAP = 0.40

def _ledoit_wolf_shrink(returns_matrix):
    """Simple Ledoit-Wolf shrinkage estimator for covariance."""
    T, N = returns_matrix.shape
    if T < 2 or N < 1:
        return np.eye(N)

    sample_cov = np.cov(returns_matrix, rowvar=False)
    if N == 1:
        return sample_cov.reshape(1, 1)

    # Shrinkage target: diagonal matrix with average variance
    mu = np.trace(sample_cov) / N
    target = mu * np.eye(N)

    # Optimal shrinkage intensity (simplified Ledoit-Wolf)
    delta = sample_cov - target
    delta_sq_sum = np.sum(delta ** 2)

    # Estimate optimal shrinkage
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

    # Build returns matrix (point-in-time: only data up to 'date')
    returns = {}
    for sym in selected:
        if sym not in price_data:
            return {s: 1.0 / N for s in selected}  # fallback
        df = price_data[sym]
        close = df['Close'].loc[:date] if date is not None else df['Close']
        r = close.pct_change().dropna().tail(lookback)
        returns[sym] = r

    # Align on common dates
    common_idx = returns[selected[0]].index
    for sym in selected[1:]:
        common_idx = common_idx.intersection(returns[sym].index)

    if len(common_idx) < 20:
        return {s: 1.0 / N for s in selected}  # fallback

    ret_matrix = np.column_stack([returns[s].loc[common_idx].values for s in selected])

    # Shrunk covariance
    cov = _ledoit_wolf_shrink(ret_matrix)

    # Check for degenerate matrix
    if np.any(np.diag(cov) <= 0) or np.linalg.matrix_rank(cov) < N:
        # Fallback: inverse-vol
        vols = np.sqrt(np.diag(cov))
        vols = np.where(vols > 0, vols, 1.0)
        raw = 1.0 / vols
        return dict(zip(selected, raw / raw.sum()))

    # Iterative risk parity (Spinu 2013 simplified)
    w = np.ones(N) / N
    for _ in range(RISK_PARITY_MAX_ITER):
        sigma_w = cov @ w
        mrc = w * sigma_w  # marginal risk contribution
        total_risk = w @ sigma_w
        rc = mrc / total_risk  # risk contribution fractions

        # Target: equal risk contribution = 1/N each
        target_rc = np.ones(N) / N

        # Update: scale weights inversely to their risk contribution
        adjustment = target_rc / np.where(rc > 1e-12, rc, 1e-12)
        w_new = w * adjustment
        w_new = w_new / w_new.sum()  # normalize

        if np.max(np.abs(w_new - w)) < RISK_PARITY_EPS:
            w = w_new
            break
        w = w_new

    # Enforce non-negative and cap
    w = np.maximum(w, 0)
    w = np.minimum(w, POSITION_CAP)
    w = w / w.sum()

    return dict(zip(selected, w))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_backtest_lab.py -k "risk_parity" -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Create wrapper matching v84's `compute_volatility_weights` signature**

In `backtest_lab.py`, check v84's signature: `compute_volatility_weights(price_data, selected, date)`. Our `compute_risk_parity_weights` has the same signature — it can directly replace it.

- [ ] **Step 6: Add risk parity experiment to main block**

```python
    # Experiment 2: Risk parity sizing
    experiments.append(run_experiment('RISK_PARITY', {
        'compute_volatility_weights': compute_risk_parity_weights,
    }, cached_data=data))
```

- [ ] **Step 7: Commit**

```bash
git add backtest_lab.py tests/test_backtest_lab.py
git commit -m "feat: add risk parity sizing experiment with Ledoit-Wolf shrinkage"
```

---

### Task 5: Experiment 4 — Vol-Targeting Leverage

**Files:**
- Modify: `backtest_lab.py`

- [ ] **Step 1: Add vol-targeting experiment to main block**

v84 already has vol-targeting logic capped at `LEVERAGE_MAX=1.0`. We just patch 3 constants:

```python
    # Experiment 4: Vol-targeting leverage
    experiments.append(run_experiment('VOL_TARGET_LEV', {
        'LEVERAGE_MAX': 2.0,
        'TARGET_VOL': 0.12,
        'MARGIN_RATE': 0.0514,
    }, cached_data=data))
```

- [ ] **Step 2: Commit**

```bash
git add backtest_lab.py
git commit -m "feat: add vol-targeting leverage experiment (LEVERAGE_MAX=2.0)"
```

---

### Task 6: Experiment 5 — Combined + Comparison

**Files:**
- Modify: `backtest_lab.py`

- [ ] **Step 1: Add combined experiment**

```python
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
```

- [ ] **Step 2: Add sub-period analysis**

In `backtest_lab.py`, add to `compare_results`:

```python
def compare_results(experiments: list):
    """Print side-by-side comparison table with sub-period breakdowns."""
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

    # Compute deltas vs baseline
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

    # Sub-period analysis (2000-2012 vs 2013-2026)
    print("\n" + "="*90)
    print("  SUB-PERIOD ANALYSIS")
    print("="*90)
    for exp in experiments:
        pv = exp['results'].get('portfolio_values')
        if pv is not None and isinstance(pv, pd.DataFrame) and 'date' in pv.columns:
            pv['date'] = pd.to_datetime(pv['date'])
            for label, start, end in [('2000-2012', '2000-01-01', '2012-12-31'),
                                       ('2013-2026', '2013-01-01', '2026-12-31')]:
                mask = (pv['date'] >= start) & (pv['date'] <= end)
                sub = pv.loc[mask, 'value']
                if len(sub) > 252:
                    total_ret = sub.iloc[-1] / sub.iloc[0]
                    years = len(sub) / 252
                    cagr = (total_ret ** (1 / years) - 1) * 100
                    dd = ((sub / sub.cummax()) - 1).min() * 100
                    print(f"  {exp['name']:20s} | {label} | CAGR: {cagr:+.2f}% | MaxDD: {dd:.2f}%")

    return df
```

- [ ] **Step 3: Run the full lab**

Run: `python backtest_lab.py`
Expected: Runs all 6 variants (baseline + 4 experiments + combined), prints comparison table, saves CSVs.

**Note**: This will take several minutes (6 full backtests over 26 years of data). Each run downloads price data from Yahoo Finance.

- [ ] **Step 4: Commit**

```bash
git add backtest_lab.py
git commit -m "feat: add combined experiment + sub-period comparison table"
```

---

### Task 7: Run Full Lab + Analyze Results

- [ ] **Step 1: Run the complete lab**

```bash
python backtest_lab.py 2>&1 | tee backtests/lab_results/run_log.txt
```

- [ ] **Step 2: Review comparison table**

Read `backtests/lab_results/comparison.csv` and analyze:
- Which experiments improved Sharpe by >= 0.05?
- Which experiments worsened MaxDD by > 2%?
- Which experiments passed both sub-period consistency tests?

- [ ] **Step 3: Commit results**

```bash
git add backtests/lab_results/
git commit -m "results: backtest lab initial run — 6 variants compared"
```

- [ ] **Step 4: Write summary analysis**

Add a summary section to `backtests/lab_results/ANALYSIS.md` with:
- Winner(s) by Sharpe improvement
- Any experiments that failed success criteria
- Recommended combination for further testing on full HYDRA
