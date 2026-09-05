# ML Data Quality Audit
**Date**: 2026-03-16
**Analyst**: Gemini
**Status**: Complete

## Executive Summary
This audit evaluates the data logged for the ML Phase 1 (5-7 trading days). While the logging structure is sound, several critical data gaps (null values in key signals) will severely impact the performance of Phase 2 (Predictive Phase) if not corrected immediately.

## Findings

### 1. Missing Momentum Signals — [CRITICAL]
- **Issue**: `momentum_score` and `momentum_rank` are `null` in 95% of the logged decisions in `decisions.jsonl`.
- **Impact**: Momentum is the primary factor of the HYDRA algorithm. If the ML system cannot see the underlying scores that led to a trade, it cannot differentiate between "marginal" and "high-conviction" signals. This renders Phase 2 training impossible.

### 2. Missing Contextual Data — [MEDIUM]
- **Issue**: SPY context data (`spy_price`, `spy_sma200`, `spy_10d_vol`) is `null` in several early decisions (March 5/6).
- **Cause**: Likely an initialization delay in the `MarketDataManager` when the decision is first logged.
- **Impact**: ML cannot learn regime-dependency without these baseline market features.

### 3. Sample Size Adequacy — [LOW-MEDIUM]
- **Current Stats**: 13 decisions, 4 completed trades, 9 daily snapshots.
- **Target**: 63 trading days (approx. 250 decisions) for Phase 2.
- **Observation**: Collection speed is adequate (approx. 2-3 decisions per day), but the 5-day cycle limits the "outcomes" (`outcomes.jsonl`) frequency.

### 4. Logic/Value Distribution — [LOW]
- **Regimes**: All decisions occurred in "mild_bull" regime.
- **Sectors**: Narrow diversity (Healthcare and Technology only).
- **Comment**: This is normal for a 7-day window but highlights the need for a longer collection phase to capture "risk-off" events.

## Recommendations
1. **Fix Signal Capture**: Update `omnicapital_live.py` (specifically the ML logging call) to ensure `momentum_score` and `momentum_rank` are passed from the COMPASS signal generator.
2. **Context Guard**: Add a 5-second retry or wait in `DecisionLogger` to ensure SPY data is populated before logging the JSON line.
3. **Daily Snapshot Audit**: Standardize the `daily_snapshots.jsonl` to include sector exposure percentages, which are currently missing.

## Milestone Status
- **Phase 1**: Collection in progress (11.1% complete toward 63-day goal).
- **Phase 2 Ready?**: **NO**. Blocked by missing momentum features.

## Data Sources
- `state/ml_learning/decisions.jsonl`
- `state/ml_learning/insights.json`
- `state/ml_learning/daily_snapshots.jsonl`
