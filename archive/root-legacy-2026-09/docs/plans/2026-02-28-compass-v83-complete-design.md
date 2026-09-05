# COMPASS v8.3 Complete Implementation Design
**Date:** 2026-02-28
**Status:** APPROVED
**Baseline:** CAGR 13.90% | MaxDD -66.25% | Sharpe 0.646 | Calmar 0.21

---

## OBJECTIVE

Transform COMPASS v8.2 into v8.3 by:
1. Fixing 3 critical bugs in the backtest engine
2. Applying already-validated parameter improvements (+1.99% CAGR measured)
3. Adding risk-adjusted momentum signal (new, theoretically grounded)
4. Implementing the 4-phase v8.3 plan (Smooth DD, Regime Sigmoid, Exit Renewal, Quality Filter)
5. Validating out-of-sample

Target: 15-17% CAGR, MaxDD < -50%, Sharpe > 0.80

---

## ARCHITECTURE

Approach: Incremental experiments over v8.2, one file per step (exp48-exp53).
Each experiment is self-contained and comparable. The final winner promotes to `omnicapital_v83_compass.py`.

---

## EXECUTION ORDER (7 STEPS)

| Step | File | Change | Expected CAGR |
|------|------|--------|---------------|
| 0 | `omnicapital_v8_compass.py` | 3 critical bug fixes | 13.90% (no change) |
| 1 | `exp48_params_validated.py` | MOM=105d + WTrail 0.08/0.05 | ~15.4% |
| 2 | `exp49_risk_adj_momentum.py` | Signal: return/vol instead of raw return | ~16.0-17.0% |
| 3 | `exp50_smooth_dd.py` | Smooth DD Scaling (replace binary stop) | ~17.0-18.0% |
| 4 | `exp51_regime_sigmoid.py` | Continuous regime with sigmoid | ~17.5-18.5% |
| 5 | `exp52_exit_renewal.py` | Exit renewal for winners (bug-fixed) | ~17.8-19.0% |
| 6 | `exp53_quality_filter.py` | Quality filter + OOS validation | ~17.8-19.0% |

---

## STEP 0: CRITICAL BUG FIXES

### Bug A: Capital vanishes on stop loss when price data missing (lines 527-545)
`del positions[symbol]` executes even when the `if` block for price data is False.
Fix: Move `del` inside the `if` block.

### Bug B: Recovery stages skip (lines 504-514)
Two sequential `if` statements allow jumping from Stage 1 to Full Recovery in one iteration.
Fix: Change second `if` to `elif`.

### Bug C: MIN_MOMENTUM_STOCKS never enforced (line 659)
Parameter defined but never checked before trading.
Fix: Add `len(scores) >= MIN_MOMENTUM_STOCKS` guard.

---

## STEP 1: VALIDATED PARAMETERS (exp48)

Already measured in exp45b (COMBO_MOM105_WTRAIL = 15.42% CAGR):
```python
MOMENTUM_LOOKBACK = 105    # was 90
TRAILING_ACTIVATION = 0.08  # was 0.05
TRAILING_STOP_PCT = 0.05    # was 0.03
```

---

## STEP 2: RISK-ADJUSTED MOMENTUM (exp49)

Modify `compute_momentum_scores()`: divide raw return by 63-day realized volatility.
Based on Barroso-Santa-Clara (2015). LOW overfitting risk.

```python
raw_momentum = (close_skip / close_lookback) - 1.0
ann_vol = returns.std() * np.sqrt(252)
score = raw_momentum / ann_vol if ann_vol > 0.01 else raw_momentum
```

---

## STEP 3: SMOOTH DRAWDOWN SCALING (exp50)

Replace binary portfolio stop + recovery with continuous leverage scaling.

### Remove:
- PORTFOLIO_STOP_LOSS = -0.15
- RECOVERY_STAGE_1_DAYS = 63
- RECOVERY_STAGE_2_DAYS = 126
- LEVERAGE_MIN = 0.3
- All protection_mode variables and logic

### Add:
```
DD Tier 1 = -5%   -> leverage 1.0x (full)
DD Tier 2 = -15%  -> leverage 0.50x (linear interpolation)
DD Tier 3 = -25%  -> leverage 0.20x floor
Crash velocity: -6% in 5d OR -10% in 10d -> 0.15x for 10 days
Hysteresis: +2% above threshold to ramp back up
```

### Functions:
- `_dd_leverage(drawdown)` - piecewise linear
- `compute_smooth_leverage(drawdown, portfolio_values, current_idx, crash_cooldown)`

---

## STEP 4: SIGMOID REGIME FILTER (exp51)

Replace binary `SPY > SMA200` with continuous score [0, 1].

### Components:
- Trend (60%): sigmoid(SPY/SMA200) + sigmoid(SMA50/SMA200) + sigmoid(20d momentum)
- Volatility (40%): inverted percentile rank of 10d realized vol in 252d distribution

### Position mapping:
- score >= 0.65 -> 5 positions (strong bull)
- score >= 0.50 -> 4 positions (mild bull)
- score >= 0.35 -> 3 positions (mild bear)
- score <  0.35 -> 2 positions (bear)

### Functions:
- `_sigmoid(x, k=15.0)`
- `compute_regime_score(spy_data, date)`
- `regime_score_to_positions(regime_score)`

---

## STEP 5: EXIT RENEWAL (exp52)

Allow winning positions to extend hold period, with CRITICAL bug fix.

### Bug Fix (original patches had entry_idx reset making HOLD_DAYS_MAX ineffective):
- Track `original_entry_idx` separately from `entry_idx`
- `total_days_held = current_idx - pos['original_entry_idx']`
- Only `entry_idx` resets on renewal; `original_entry_idx` is immutable

### Conservative parameters (per CAGR optimizer recommendation):
```python
HOLD_DAYS_MAX = 10               # was 15 in original patches
RENEWAL_PROFIT_MIN = 0.04        # was 0.02
MOMENTUM_RENEWAL_THRESHOLD = 0.85 # was 0.70
```

### Loop restructuring:
Move score computation BEFORE exit loop to reuse in both renewal checks and new position opening.

---

## STEP 6: QUALITY FILTER + OOS VALIDATION (exp53)

### Quality Filter:
- Exclude stocks with 63-day annualized vol > 60%
- Exclude stocks with single-day moves > 50% (data corruption)
- Fallback: if < 5 stocks pass, use unfiltered list

### Out-of-Sample Validation:
- Train: 2000-2015 (fix all parameters)
- Test: 2016-2026 (no modifications)
- Accept if CAGR gap < 3%

---

## ACCEPTANCE CRITERIA

| Metric | Baseline | Minimum | Target | Stretch |
|--------|----------|---------|--------|---------|
| CAGR | 13.90% | 15.0% | 17.0% | 19.0% |
| MaxDD | -66.25% | -55.0% | -45.0% | -35.0% |
| Sharpe | 0.646 | 0.72 | 0.85 | 1.00 |
| Calmar | 0.21 | 0.30 | 0.40 | 0.55 |
| Stop Events | 10 | <=3 | 0 | 0 |
| OOS Gap | N/A | <3% | <2% | <1% |

### Go/No-Go Gates:
- After Step 3: If CAGR < 15.0% -> STOP, investigate
- After Step 4: If CAGR < 15.5% -> STOP
- Any step worsens CAGR by > -0.5% -> REVERT immediately

---

## CONTINGENCY

If Smooth DD Scaling behaves like GRAD_PROT (all worse):
1. Try LEV_FLOOR = 0.30 instead of 0.20
2. If still worse, skip Step 3 and proceed with Steps 4-6 only
3. Fall back to parameter-only improvement (15.42% CAGR from Step 1)

If all structural changes fail:
- Production candidate = exp48 (params only) at 15.42% CAGR
- This is still a +1.5% improvement over baseline
