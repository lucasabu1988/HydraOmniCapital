# COMPASS v8.3 Complete Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform COMPASS v8.2 (13.90% CAGR) into v8.3 by fixing 3 critical bugs, applying validated parameter improvements, adding risk-adjusted momentum, and implementing 4 structural algorithmic changes (Smooth DD Scaling, Sigmoid Regime, Exit Renewal, Quality Filter).

**Architecture:** Incremental experiments over v8.2 base. Each step creates a self-contained experiment file (exp48-exp53) that copies the full engine and applies changes cumulatively. Each experiment is runnable independently and produces a comparison report against baseline. The final winner promotes to `omnicapital_v83_compass.py`.

**Tech Stack:** Python 3.11+, pandas, numpy, yfinance. No new dependencies. Data cached in data_cache/ directory using the project's existing serialization format.

**Key source files:**
- Engine: `omnicapital_v8_compass.py` (918 lines)
- Patches: `compass_v83_patches.py` (808 lines, all 4 patches with integration notes)
- Data: `data_cache/broad_pool_2000-01-01_2027-01-01.pkl` (cached price data)
- SPY: `data_cache/SPY_2000-01-01_2027-01-01.csv`

---

## Task 1: Bug Fixes on Base Engine

**Files:**
- Modify: `omnicapital_v8_compass.py:504-514` (recovery skip), `:529-545` (capital vanish), `:659` (MIN_MOMENTUM guard)

**Step 1: Fix Bug A -- Capital vanishes when stop loss fires without price data**

In `omnicapital_v8_compass.py`, the `del positions[symbol]` on line 545 executes even when price data is missing (the `if` block on line 530 is False). Capital disappears from simulation.

Change lines 529-545: indent `del positions[symbol]` to be INSIDE the `if` block (add 4 spaces).

**Step 2: Fix Bug B -- Recovery stages can skip from Stage 1 to Full Recovery**

In `omnicapital_v8_compass.py`, line 508: change `if` to `elif`.

**Step 3: Fix Bug C -- MIN_MOMENTUM_STOCKS never enforced**

In `omnicapital_v8_compass.py`, line 659: change from
`if len(available_scores) >= needed:` to
`if len(scores) >= MIN_MOMENTUM_STOCKS and len(available_scores) >= needed:`

**Step 4: Verify fixes don't break syntax**

Run: `cd "C:/Users/caslu/Desktop/NuevoProyecto" && python -c "import omnicapital_v8_compass; print('Import OK')"`

**Step 5: Commit**

```bash
cd "C:/Users/caslu/Desktop/NuevoProyecto"
git add omnicapital_v8_compass.py
git commit -m "fix: 3 critical bugs in COMPASS v8.2 backtest engine

- Bug A: del positions now inside if-block (prevents capital vanish)
- Bug B: elif prevents recovery stage skip-through
- Bug C: MIN_MOMENTUM_STOCKS guard added before trading"
```

---

## Task 2: exp48 -- Validated Parameters (MOM=105d + Wide Trailing)

**Files:**
- Create: `exp48_params_validated.py`

**Step 1: Create exp48 by copying base engine and applying parameter changes**

Copy `omnicapital_v8_compass.py` to `exp48_params_validated.py` and change 3 parameters:

- Line 34: `MOMENTUM_LOOKBACK = 105` (was 90)
- Line 51: `TRAILING_ACTIVATION = 0.08` (was 0.05)
- Line 52: `TRAILING_STOP_PCT = 0.05` (was 0.03)

Update print header to say `"OMNICAPITAL v8.3 Step 1 - Validated Parameters"`.

**Step 2: Run exp48 backtest**

Run: `cd "C:/Users/caslu/Desktop/NuevoProyecto" && python exp48_params_validated.py`

Expected: CAGR approximately 15.4% (matching exp45b measured result).

**Step 3: Commit**

```bash
git add exp48_params_validated.py
git commit -m "feat(exp48): validated parameters MOM=105d + WTrail 0.08/0.05

Expected CAGR ~15.4% based on exp45b measurement."
```

---

## Task 3: exp49 -- Risk-Adjusted Momentum Signal

**Files:**
- Create: `exp49_risk_adj_momentum.py` (copy from exp48, modify `compute_momentum_scores`)

**Step 1: Create exp49 from exp48 and modify the momentum signal**

Copy `exp48_params_validated.py` to `exp49_risk_adj_momentum.py`.

Replace the `compute_momentum_scores` function with a version that divides raw_score by 63-day realized vol (Barroso-Santa-Clara 2015):

```python
def compute_momentum_scores(price_data, tradeable, date, all_dates, date_idx):
    scores = {}
    RISK_ADJ_VOL_WINDOW = 63

    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue

        needed = MOMENTUM_LOOKBACK + MOMENTUM_SKIP
        try:
            sym_idx = df.index.get_loc(date)
        except KeyError:
            continue

        if sym_idx < needed:
            continue

        close_today = df['Close'].iloc[sym_idx]
        close_skip = df['Close'].iloc[sym_idx - MOMENTUM_SKIP]
        close_lookback = df['Close'].iloc[sym_idx - MOMENTUM_LOOKBACK]

        if close_lookback <= 0 or close_skip <= 0 or close_today <= 0:
            continue

        momentum_raw = (close_skip / close_lookback) - 1.0
        skip_5d = (close_today / close_skip) - 1.0
        raw_score = momentum_raw - skip_5d

        # Risk adjustment: divide by realized vol
        vol_window = min(RISK_ADJ_VOL_WINDOW, sym_idx - 1)
        if vol_window >= 20:
            returns = df['Close'].iloc[sym_idx - vol_window:sym_idx + 1].pct_change().dropna()
            if len(returns) >= 15:
                ann_vol = float(returns.std() * (252 ** 0.5))
                if ann_vol > 0.01:
                    scores[symbol] = raw_score / ann_vol
                else:
                    scores[symbol] = raw_score
            else:
                scores[symbol] = raw_score
        else:
            scores[symbol] = raw_score

    return scores
```

Update print header to `"OMNICAPITAL v8.3 Step 2 - Risk-Adjusted Momentum"`.

**Step 2: Run exp49 backtest**

Run: `cd "C:/Users/caslu/Desktop/NuevoProyecto" && python exp49_risk_adj_momentum.py`

Expected: CAGR should improve over exp48. If CAGR drops more than -0.5%, REVERT and skip to Task 4.

**Step 3: Commit**

```bash
git add exp49_risk_adj_momentum.py
git commit -m "feat(exp49): risk-adjusted momentum signal (return/vol)

Barroso-Santa-Clara 2015 approach. Divides raw momentum by 63d realized vol."
```

---

## Task 4: exp50 -- Smooth Drawdown Scaling

**Files:**
- Create: `exp50_smooth_dd.py` (copy from exp49, apply PATCH 1 from compass_v83_patches.py)

**Step 1: Create exp50 from exp49 and apply Smooth DD Scaling**

Copy `exp49_risk_adj_momentum.py` to `exp50_smooth_dd.py`.

**1a. Replace parameters:** Remove PORTFOLIO_STOP_LOSS, RECOVERY_STAGE_1_DAYS, RECOVERY_STAGE_2_DAYS, LEVERAGE_MIN. Add:

```python
DD_SCALE_TIER1 = -0.05
DD_SCALE_TIER2 = -0.15
DD_SCALE_TIER3 = -0.25
LEV_FULL       = 1.0
LEV_MID        = 0.50
LEV_FLOOR      = 0.20
CRASH_VEL_5D   = -0.06
CRASH_VEL_10D  = -0.10
CRASH_LEVERAGE = 0.15
CRASH_COOLDOWN = 10
```

**1b. Add functions:** Copy `_dd_leverage()` and `compute_smooth_leverage()` from `compass_v83_patches.py` lines 73-183.

**1c. Fix LEVERAGE_MIN reference:** In `compute_dynamic_leverage`, change `LEVERAGE_MIN` to `LEV_FLOOR`.

**1d. Modify run_backtest():**
- Remove state variables: `in_protection_mode`, `protection_stage`, `stop_loss_day_index`, `post_stop_base`
- Add: `crash_cooldown = 0`
- Remove entire recovery check block (lines 495-514)
- Remove entire portfolio stop loss block (lines 519-550)
- Replace leverage/positions block (lines 561-574) with smooth leverage computation
- Update daily snapshot: `'in_protection': dd_leverage_val < LEV_FULL`

**Step 2: Run exp50 backtest**

Run: `cd "C:/Users/caslu/Desktop/NuevoProyecto" && python exp50_smooth_dd.py`

Expected: stop_events == 0, MaxDD < -55%, CAGR >= 15.0%.

**Step 3: Commit**

```bash
git add exp50_smooth_dd.py
git commit -m "feat(exp50): smooth drawdown scaling replaces binary portfolio stop

Piecewise-linear leverage reduction + crash velocity circuit breaker.
Eliminates protection mode and the double-hit problem."
```

---

## Task 5: exp51 -- Sigmoid Regime Filter

**Files:**
- Create: `exp51_regime_sigmoid.py` (copy from exp50, apply PATCH 2)

**Step 1: Create exp51 from exp50 and apply Sigmoid Regime**

Copy `exp50_smooth_dd.py` to `exp51_regime_sigmoid.py`.

**1a. Add functions:** Copy `_sigmoid()`, `compute_regime_score()`, `regime_score_to_positions()` from `compass_v83_patches.py` lines 275-431.

**1b. Remove** the old `compute_regime()` function.

**1c. Modify run_backtest():**
- Remove `regime = compute_regime(spy_data)` pre-computation
- Replace regime section with `compute_regime_score()` call per day
- Replace max_positions with `regime_score_to_positions(regime_score)`
- Add `'regime_score': regime_score` to daily snapshot

**Step 2: Run exp51 backtest**

Run: `cd "C:/Users/caslu/Desktop/NuevoProyecto" && python exp51_regime_sigmoid.py`

Expected: Fewer regime transitions, CAGR >= 15.5% combined.

**Step 3: Commit**

```bash
git add exp51_regime_sigmoid.py
git commit -m "feat(exp51): continuous sigmoid regime filter

Score [0,1] from trend (60%) + volatility (40%).
Gradual position reduction: 5->4->3->2 instead of cliff 5->2."
```

---

## Task 6: exp52 -- Exit Renewal for Winners (WITH BUG FIX)

**Files:**
- Create: `exp52_exit_renewal.py` (copy from exp51, apply PATCH 3 with critical fix)

**Step 1: Create exp52 from exp51 and apply Exit Renewal**

Copy `exp51_regime_sigmoid.py` to `exp52_exit_renewal.py`.

**1a. Add conservative parameters:**
```python
HOLD_DAYS_MAX = 10
RENEWAL_PROFIT_MIN = 0.04
MOMENTUM_RENEWAL_THRESHOLD = 0.85
```

**1b. Add `should_renew_position` function** using `days_held_total` (from `original_entry_idx`) instead of `days_held` (from `entry_idx`). This is the CRITICAL BUG FIX -- the original patches reset `entry_idx` making `HOLD_DAYS_MAX` ineffective.

**1c. Restructure daily loop:**
- Move `compute_momentum_scores` BEFORE exit loop (compute once, reuse)
- Add `'original_entry_idx': i` to new position creation
- In exit logic: check renewal before hold_expired, using `original_entry_idx` for total days
- In new positions block: reuse `current_scores` instead of recalculating

**Step 2: Run exp52 backtest**

Run: `cd "C:/Users/caslu/Desktop/NuevoProyecto" && python exp52_exit_renewal.py`

Expected: Win rate improves >= 2pp, CAGR doesn't drop.

**Step 3: Commit**

```bash
git add exp52_exit_renewal.py
git commit -m "feat(exp52): exit renewal with HOLD_DAYS_MAX bug fix

Conservative params: MAX=10d, PROFIT_MIN=4%, THRESHOLD=85%.
Fixed original_entry_idx tracking to make HOLD_DAYS_MAX effective."
```

---

## Task 7: exp53 -- Quality Filter + Final Report

**Files:**
- Create: `exp53_quality_filter.py` (copy from exp52, apply PATCH 4 + comparison report)

**Step 1: Create exp53 from exp52 and apply Quality Filter**

Copy `exp52_exit_renewal.py` to `exp53_quality_filter.py`.

**1a. Add parameters and `compute_quality_filter` function** from `compass_v83_patches.py` lines 620-694.

**1b. Insert filter** in daily loop before score computation.

**1c. Add comparison report** to `__main__` block showing v8.3 vs v8.2 baseline.

**Step 2: Run exp53 full backtest**

Run: `cd "C:/Users/caslu/Desktop/NuevoProyecto" && python exp53_quality_filter.py`

Expected: With 113 stocks, results identical to exp52. The quality filter shows impact only with 744-stock pool.

**Step 3: Commit**

```bash
git add exp53_quality_filter.py
git commit -m "feat(exp53): quality filter + final v8.3 comparison report

COMPASS v8.3 complete with all improvements."
```

---

## Task 8: Promote Final Version

**Files:**
- Create: `omnicapital_v83_compass.py` (copy of exp53 with clean naming)
- Modify: `PROJECT_STATE.md`

**Step 1:** Copy exp53 to `omnicapital_v83_compass.py` with updated docstring.

**Step 2:** Update `PROJECT_STATE.md` with v8.3 results.

**Step 3: Commit**

```bash
git add omnicapital_v83_compass.py PROJECT_STATE.md
git commit -m "feat: promote COMPASS v8.3 as production candidate"
```

---

## Go/No-Go Gates

| After Task | Gate | Action if FAIL |
|------------|------|----------------|
| Task 2 (exp48) | CAGR >= 14.5% | Investigate -- params were measured at 15.42% |
| Task 3 (exp49) | CAGR >= exp48 - 0.5% | Skip risk-adj momentum, proceed with exp48 |
| Task 4 (exp50) | stop_events == 0, CAGR >= 15.0% | Try LEV_FLOOR=0.30, if worse revert |
| Task 5 (exp51) | CAGR >= 15.5% combined | Adjust sigmoid k or thresholds |
| Task 6 (exp52) | Win rate improves, CAGR stable | Revert to exp51 |
| Task 7 (exp53) | Same as exp52 with 113 stocks | Expected behavior |

## Acceptance Criteria (Final)

| Metric | Baseline v8.2 | Minimum | Target |
|--------|--------------|---------|--------|
| CAGR | 13.90% | 15.0% | 17.0% |
| MaxDD | -66.25% | -55.0% | -45.0% |
| Sharpe | 0.646 | 0.72 | 0.85 |
| Stop Events | 10 | <=3 | 0 |
