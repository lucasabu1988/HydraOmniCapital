# Multi-Lookback Momentum Ensemble — Design Doc

## Summary

Replace COMPASS's single-lookback momentum signal (90d) with an ensemble of 4 lookback windows (21d, 63d, 126d, 252d), blended via rank averaging. Validated on 750-stock survivorship-free pool over 2000-2026.

## Results (EXP56)

| Metric | Baseline (raw 90d) | Multi-Lookback | Delta |
|--------|-------------------|----------------|-------|
| CAGR | 12.27% | 13.12% | +0.85% |
| MaxDD | -32.10% | -28.95% | +3.15% |
| Sharpe | 0.82 | 0.87 | +0.05 |
| Final ($100K) | $2,050K | $2,498K | +$448K |
| Win Rate | 53.84% | 54.43% | +0.59% |
| Worst Year | -24.61% | -22.72% | +1.89% |

Improves CAGR, MaxDD, and Sharpe simultaneously — breaks the Pareto frontier.

## What Changes

### Signal only — everything else stays locked

**Before:** `score = raw_momentum_90d / realized_vol_63d`

**After:**
1. For each lookback in [21, 63, 126, 252]:
   - Compute `raw_momentum = (close_skip / close_lookback) - 1.0`
   - Risk-adjust: `score = raw_momentum / ann_vol`
2. Convert each lookback's scores to percentile ranks within the universe
3. Final score = mean of available ranks (stocks need all 4 lookbacks to be ranked)

### Parameters

```python
MULTI_LOOKBACKS = [21, 63, 126, 252]  # 1mo, 3mo, 6mo, 12mo
MOMENTUM_SKIP = 5                      # unchanged
```

### Files to modify

- `omnicapital_v85_compass.py` — new backtest engine with multi-lookback
- `omnicapital_live.py` — update `compute_momentum_scores()` for live trading
- `compass_dashboard.py` — no changes needed (signal is internal)

### What stays the same

- Regime filter (sigmoid + bull override)
- Adaptive stops (vol-scaled)
- Trailing stops
- Sector concentration limits
- DD scaling tiers
- Vol targeting
- Exit renewal logic
- Inverse-vol position sizing
- Quality filter

## Data Requirements

- Pool: 750+ stocks (expanded pool with survivorship correction)
- Data filter: exclude stocks with any daily return > 500% (corrupted corporate actions)
- Minimum history: 252 + 5 = 257 trading days for a stock to get a score

## Experiments Conducted

| Experiment | CAGR | MaxDD | Sharpe | Verdict |
|-----------|------|-------|--------|---------|
| EXP55: 100% residual momentum (113 stocks) | 9.53% | -39.68% | 0.68 | FAIL |
| EXP55: 100% residual momentum (774 stocks) | 10.69% | -35.06% | 0.69 | FAIL |
| EXP55: 70/30 blend raw+residual (774 stocks) | 10.82% | -30.28% | 0.69 | FAIL |
| EXP55: Baseline raw 90d (750 clean stocks) | 12.27% | -32.10% | 0.82 | BASELINE |
| **EXP56: Multi-lookback ensemble (750 clean)** | **13.12%** | **-28.95%** | **0.87** | **WIN** |

## Risk Assessment

- **Low risk**: Only the signal scoring changes. All risk management (stops, DD scaling, regime) unchanged.
- **No leverage change**: Still LEVERAGE_MAX = 1.0
- **Computation**: ~2-3 seconds for 750 stocks x 4 lookbacks. No performance concern.
- **Backward compatible**: Existing state files don't need migration.

## Implementation Plan

1. Create `omnicapital_v85_compass.py` with multi-lookback scoring
2. Run full backtest validation on clean 750-stock pool
3. Update live engine `compute_momentum_scores()` in `omnicapital_live.py`
4. Add data quality filter (>500% daily return) to live data pipeline
5. Sync to `compass/` for cloud deployment
