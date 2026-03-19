# Backtest Lab: Portfolio Construction Enhancements

**Date**: 2026-03-19
**Status**: Approved
**Goal**: Improve CAGR, MaxDD, and Sharpe of COMPASS v8.4 through portfolio construction changes only — no signal logic modifications.

## Constraint

- `omnicapital_v84_compass.py` is **NEVER modified**. It remains the immutable baseline.
- All experiments run in a new file `backtest_lab.py` that imports from v84.
- The live engine (`omnicapital_live.py`) is never touched.
- No experiment results leak into production code. `backtest_lab.py` includes an assertion that it never modifies live state files.
- **Leverage experiments are backtest-only**. CLAUDE.md says `LEVERAGE_MAX = 1.0` for production. Experiment 4 tests higher leverage in simulation only to quantify the theoretical CAGR gain.

## Architecture

```
omnicapital_v84_compass.py    (IMMUTABLE — signal generation + baseline backtest)
        │
        │  import as module
        ▼
backtest_lab.py               (NEW — experiment runner)
        │
        ├── run_baseline()           → runs unmodified v84 as control
        ├── run_correlation_filter() → experiment 1
        ├── run_risk_parity()        → experiment 2
        ├── run_universe_80()        → experiment 3
        ├── run_vol_targeting()      → experiment 4
        ├── run_combined()           → all enhancements together
        └── compare_results()        → side-by-side metrics table
```

### Patching Mechanism

`backtest_lab.py` uses **module-level attribute patching**. Python resolves function names in `run_backtest()` through the module's `__dict__` at call time, so patching works:

```python
import omnicapital_v84_compass as v84

# Save originals
_orig_weights = v84.compute_volatility_weights
_orig_filter = v84.filter_by_sector_concentration
_orig_top_n = v84.TOP_N

def run_experiment(patches: dict):
    """Apply patches, run backtest, restore originals."""
    originals = {}
    for attr, new_val in patches.items():
        originals[attr] = getattr(v84, attr)
        setattr(v84, attr, new_val)
    try:
        # Re-download data if universe changed (TOP_N patched)
        price_data = v84.download_broad_pool()
        spy_data = v84.download_spy()
        cash_yield = v84.download_cash_yield()
        annual_universe = v84.compute_annual_top40(price_data)
        results = v84.run_backtest(price_data, annual_universe, spy_data, cash_yield)
        metrics = v84.calculate_metrics(results)
        return results, metrics
    finally:
        for attr, orig_val in originals.items():
            setattr(v84, attr, orig_val)
```

**Key detail**: Constants like `TOP_N` must be patched BEFORE calling `compute_annual_top40()`, which reads `TOP_N` from module scope at runtime. The `run_experiment()` wrapper guarantees this ordering.

## Experiment 1: Correlation-Aware Selection

**What changes**: After momentum ranking + sector filter, add a correlation penalty.

**Current flow** (v84):
```
momentum_scores → rank descending → sector filter (max 3/sector) → top N
```

**New flow**:
```
momentum_scores → rank descending → sector filter → correlation filter → top N
```

**Correlation filter logic**:
```python
def correlation_aware_filter(candidates, current_positions, price_data, date, lookback=60):
    """
    Greedy sequential filter. For each candidate in rank order:
    1. Compute avg pairwise correlation with already-SELECTED positions
       (not existing positions — we build the new portfolio from scratch each cycle)
    2. Penalize: adjusted_score = momentum_score * (1 - avg_corr * CORR_PENALTY)
    3. If adjusted_score still ranks in top N, accept the candidate.

    CORR_PENALTY = 0.5 (tunable)
    Lookback = 60 trading days for rolling correlation

    Note: This is a greedy approach — the first candidate always gets zero penalty
    (no positions to correlate against yet). This is acceptable because the highest-
    momentum stock SHOULD be selected regardless. The filter's value is in preventing
    the 2nd-5th picks from clustering with the 1st.

    Negative correlations (inversely correlated stocks) will BOOST the adjusted score,
    which is intentional — anti-correlated positions improve diversification.
    """
```

**Implementation**: Replace `v84.filter_by_sector_concentration` with a wrapper that calls the original sector filter first, then applies the correlation penalty on the filtered candidates.

**Expected impact**: MaxDD -2% to -4%, Sharpe +0.1 to +0.2, CAGR neutral.

**Rationale**: Sector limits are a crude proxy for diversification. Two tech stocks can have 0.3 correlation (AAPL vs ORCL) or 0.9 (NVDA vs AMD). Correlation captures actual co-movement.

## Experiment 2: Risk Parity Sizing

**What changes**: Replace `compute_volatility_weights()` with covariance-aware weights.

**Current** (v84 line 539):
```python
weight_i = (1 / vol_i) / sum(1 / vol_j)  # inverse-vol, ignores correlations
```

**New**:
```python
def compute_risk_parity_weights(price_data, selected, date, lookback=60):
    """
    Equal risk contribution: each position contributes equally
    to total portfolio variance.

    Solve: w_i * (Σw)_i = constant for all i
    Where (Σw)_i = marginal risk contribution of position i

    Implementation details:
    - Covariance estimator: Ledoit-Wolf shrinkage (sklearn.covariance)
      to handle the low observations-to-variables ratio (60 days / 5 stocks)
    - Method: iterative Spinu (2013), convergence epsilon=1e-8, max_iter=1000
    - Constraint: all weights >= 0 (long-only)
    - Fallback: if cov matrix is singular, non-convergence after max_iter,
      or any weight < 0, fall back to v84's inverse-vol weighting
    - Per-position cap: 40% (same as v84) applied after risk parity,
      with excess redistributed proportionally
    """
```

**Expected impact**: MaxDD -1% to -3%, Sharpe +0.05 to +0.15, CAGR neutral or slight negative.

**Rationale**: Inverse-vol assumes zero correlation between all positions. If NVDA and AMD both have 30% vol, they get equal weight — but they're 0.85 correlated, so the portfolio is over-concentrated in that risk factor. Risk parity corrects this.

## Experiment 3: Universe Expansion (40 → 80)

**What changes**: `TOP_N = 80` instead of 40.

**Current**: Top 40 by dollar volume from the 113-stock broad pool.
**New**: Top 80 by dollar volume.

**Implementation**: Patch `v84.TOP_N = 80` before running. The broad pool already has 113 stocks, so no data changes needed.

**Survivorship bias caveat**: Stocks ranked 41-80 by dollar volume are more mid-cap-ish and more susceptible to survivorship bias than the top 40 large-caps (which mostly survived regardless). Results from this experiment should be interpreted with extra caution. Consider a robustness check excluding 10 random stocks from positions 41-80.

**Expected impact**: CAGR +1% to +2%, MaxDD neutral, Sharpe +0.05 to +0.15.

**Rationale**: Momentum strategies benefit from larger cross-sections. Academic literature (Jegadeesh & Titman) shows cross-sectional momentum is stronger in larger universes due to greater return dispersion.

## Experiment 4: Vol-Targeting Leverage

**Discovery**: v84 ALREADY implements vol-targeting via `compute_dynamic_leverage()` (line 648). It computes `TARGET_VOL / realized_vol` but caps at `LEVERAGE_MAX = 1.0`. The DD scaling also already exists via `compute_dd_leverage()`. v84 uses `min(dd_leverage, vol_leverage)` to pick the more conservative of the two.

**What changes**: Patch 3 constants only:

```python
patches = {
    'LEVERAGE_MAX': 2.0,       # was 1.0 — allow leverage above 1x
    'TARGET_VOL': 0.12,        # was 0.15 — lower target = less aggressive base
    'MARGIN_RATE': 0.0514,     # was 0.06 — IBKR Pro actual rate (Mar 2026)
}
```

**v84's existing logic handles the rest**:
- `compute_dynamic_leverage()` returns `clip(TARGET_VOL / realized_vol, LEV_FLOOR, LEVERAGE_MAX)`
- `compute_dd_leverage()` scales down during drawdowns
- `current_leverage = min(dd_leverage, vol_leverage)` — the more conservative wins
- Margin costs already deducted daily on lines 937-939 using `MARGIN_RATE`

**No new leverage logic needed**. We keep v84's conservative `min()` approach (not multiplicative).

**Expected impact**: CAGR +3% to +5%, MaxDD similar or slightly worse, Sharpe +0.2 to +0.3.

**Rationale**: Low-vol periods are safe to lever up; high-vol periods auto-delever. Vol tends to rise BEFORE crashes (vol clustering), so the system naturally reduces exposure ahead of drawdowns.

## Experiment 5: Combined

All 4 enhancements together. Applied simultaneously via patching:

1. `TOP_N = 80` (universe expansion)
2. `filter_by_sector_concentration` → correlation-aware wrapper (diversification)
3. `compute_volatility_weights` → risk parity version (balanced risk)
4. `LEVERAGE_MAX = 2.0`, `TARGET_VOL = 0.12`, `MARGIN_RATE = 0.0514` (dynamic leverage)

**Parameter interaction note**: Risk parity sizing will likely reduce portfolio vol (by down-weighting correlated positions). This means vol-targeting will compute higher leverage to hit the target. The `min(dd_lev, vol_lev)` safeguard + `LEVERAGE_MAX = 2.0` cap prevent this from spiraling. However, `TARGET_VOL` may need adjustment if the combined portfolio vol is structurally lower. We log average leverage as a metric to monitor this.

## Output

Each experiment produces:
- Daily equity curve (DataFrame)
- Trade log (DataFrame)
- Metrics dict (CAGR, MaxDD, Sharpe, Sortino, Calmar, win rate, etc.)

Final output: comparison table saved to `backtests/lab_results/`.

```
╔════════════════════════╦═══════╦════════╦════════╦═════════╦══════════╦═════════╗
║ Variant                ║ CAGR  ║ MaxDD  ║ Sharpe ║ Calmar  ║ Turnover ║ Avg Lev ║
╠════════════════════════╬═══════╬════════╬════════╬═════════╬══════════╬═════════╣
║ BASELINE (v84)         ║   ?   ║   ?    ║   ?    ║    ?    ║    ?     ║  1.0x   ║
║ + Corr Filter          ║   ?   ║   ?    ║   ?    ║    ?    ║    ?     ║  1.0x   ║
║ + Risk Parity          ║   ?   ║   ?    ║   ?    ║    ?    ║    ?     ║  1.0x   ║
║ + Universe 80          ║   ?   ║   ?    ║   ?    ║    ?    ║    ?     ║  1.0x   ║
║ + Vol-Target Lev       ║   ?   ║   ?    ║   ?    ║    ?    ║    ?     ║   ?     ║
║ + ALL COMBINED         ║   ?   ║   ?    ║   ?    ║    ?    ║    ?     ║   ?     ║
╚════════════════════════╩═══════╩════════╩════════╩═════════╩══════════╩═════════╝
```

Sub-period breakdown (2000-2012 and 2013-2026) included for each variant.

## Success Criteria

An enhancement is considered successful if:
- Sharpe ratio improves by >= 0.05 vs baseline
- MaxDD does not worsen by more than 2%
- Results are consistent across both sub-periods (2000-2012 and 2013-2026)
- Turnover increase is < 50% vs baseline (to avoid excessive transaction costs)

## Implementation Order

1. Scaffold `backtest_lab.py` with `run_experiment()` wrapper + comparison framework
2. Implement Experiment 3 (universe 80) — just patch `TOP_N`, simplest test of the framework
3. Implement Experiment 1 (correlation filter) — new filter function wrapping existing one
4. Implement Experiment 2 (risk parity) — replacement weighting function with Ledoit-Wolf
5. Implement Experiment 4 (vol-targeting) — patch 3 constants
6. Implement Experiment 5 (combined) — all patches at once
7. Run all experiments, generate comparison table + sub-period analysis
8. Analyze results, identify best combination

## Risks

- **Overfitting**: Enhancements optimized on 2000-2026 may not generalize. Mitigated by sub-period analysis and avoiding parameter tuning (using principled defaults).
- **Survivorship bias**: The 113-stock broad pool may have amplified survivorship bias for stocks 41-80. Experiment 3 results should be interpreted conservatively.
- **Covariance estimation**: 60-day rolling cov matrix with 5 stocks is noisy (12:1 ratio). Mitigated by Ledoit-Wolf shrinkage + inverse-vol fallback.
- **Lookahead bias**: Correlation and covariance computed using only data available at decision time. No future data leaks.
- **Production leak**: `backtest_lab.py` includes assertions preventing modification of live state files or production code. Leverage experiments are simulation-only.
