# HYDRA Meta-Layer v1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and rigorously validate HYDRA Meta-Layer v1 (advanced multi-dimensional Regime OS + dynamic risk-aware Meta-Layer) capable of delivering ~20-22% CAGR (+10% alpha) in long-horizon bias-controlled backtests while respecting all project constraints (COMPASS v8.4 locked, fail-safe design, existing HydraCapitalManager architecture).

**Architecture:** 
- New Regime OS producing rich multi-dimensional scores + Meta-Modes.
- New Meta-Layer that consumes regime information to control gross exposure, pillar multipliers, recycling intensity, and special behavioral modes.
- Extremely strong emphasis on validation, regularization, and graceful degradation.
- All changes are additive and feature-flagged; nothing touches locked COMPASS v8.4 logic.

**Tech Stack:**
- Python 3.14
- pandas, numpy, scikit-learn (light use), existing project data infrastructure
- New modules under root or `hydra_meta/` package
- Heavy use of the existing `hydra_backtest/` framework for validation
- Atomic JSON state writes (project standard)

---

## Phase 0: Foundations & Research Setup (COMPLETE)

### Task 0.1: Project Setup & Documentation

**Files:**
- Create: `docs/superpowers/plans/2026-06-05-hydra-meta-layer-v1-implementation.md` (this file)
- Modify: `docs/superpowers/specs/2026-06-05-hydra-meta-layer-v1-design.md` (add link to this plan)

- [ ] **Step 0.1.1: Create implementation tracking issue or note**
  Add a clear note at the top of the design spec pointing to this plan.

- [ ] **Step 0.1.2: Create directory for research artifacts**
  ```bash
  mkdir -p research/meta_layer_v1
  mkdir -p research/regime_features
  ```

- [ ] **Step 0.1.3: Add .gitignore entries if needed**
  Ensure `research/` and temporary backtest outputs are properly ignored or archived.

### Task 0.2: Regime Feature Research (Exploratory)

**Goal:** Identify the strongest, most stable regime-predictive features using only data available in the existing pipeline.

**Files:**
- Create: `research/regime_features/regime_feature_research.py`
- Create: `research/regime_features/feature_definitions.md`

- [ ] **Step 0.2.1: Write initial feature research script skeleton**
  ```python
  # research/regime_features/regime_feature_research.py
  import pandas as pd
  from datetime import datetime

  def load_sp500_data(start_date="2000-01-01"):
      """Load point-in-time S&P 500 price data using existing project infrastructure."""
      # TODO: Wire to existing data_cache / data pipeline
      pass

  def compute_basic_regime_features(df: pd.DataFrame) -> pd.DataFrame:
      """Compute initial candidate features."""
      # Momentum strength, volatility, breadth, etc.
      pass

  if __name__ == "__main__":
      print("Starting regime feature research...")
  ```

- [ ] **Step 0.2.2: Run the skeleton and confirm it can load data**
  ```bash
  python research/regime_features/regime_feature_research.py
  ```

- [ ] **Step 0.2.3: Document initial feature ideas**
  Create `feature_definitions.md` with at least 8-10 candidate features across the dimensions defined in the spec.

---

## Phase 1: Regime OS Core (Isolated & Testable) (COMPLETE)

### Task 1.1: Define Regime OS Interface

**Files:**
- Create: `regime_os.py` (new top-level module, or inside a `hydra_meta/` package — decision to be confirmed early)

- [ ] **Step 1.1.1: Write the public interface as a dataclass + protocol**
  Define `RegimeScores`, `MetaMode`, and `RegimeOS` protocol with clear docstrings.

- [ ] **Step 1.1.2: Write failing tests for the interface**
  `tests/test_regime_os_interface.py`

- [ ] **Step 1.1.3: Make the tests pass with a minimal stub implementation**

### Task 1.2: Implement Core Regime Score Calculators

- [ ] Implement each major dimension as a pure function (easy to test and backtest):
  - `compute_equity_momentum_score()`
  - `compute_volatility_regime_score()`
  - etc.

- [ ] Each function must have unit tests with synthetic data.

### Task 1.3: Build Meta-Mode Classifier

- [ ] Create logic that converts the vector of scores into active Meta-Modes.
- [ ] Support both hard rules and a simple regularized classifier (scikit-learn or custom).
- [ ] Heavy emphasis on stability (no rapid flipping).

### Task 1.4: Regime OS Validation Harness (Isolated)

- [ ] Build a dedicated backtest-style harness that evaluates regime features purely on their ability to predict future market behavior (forward returns, volatility regimes, etc.).
- [ ] This harness must be completely independent of the trading strategies.

---

## Phase 2: Meta-Layer Core Logic (COMPLETE — Tasks 2.1-2.4)

### Task 2.1: Meta-Layer Decision Engine Interface

**Files:**
- Create: `meta_layer.py`

- [ ] Define clear input/output contract:
  - Input: RegimeScores + current portfolio state + recent performance
  - Output: `MetaLayerDecision` (gross_exposure, multipliers dict, recycling_multiplier, active_modes, confidence)

### Task 2.2: Risk Budgeting & Exposure Logic

- [ ] Implement the approved asymmetric risk logic.
- [ ] Implement Recovery Mode behavior.
- [ ] Implement Drawdown Velocity Control.
- [ ] All rules must be heavily parameterized and versioned.

### Task 2.3: Pillar Multiplier & Recycling Modulation

- [ ] Build the mapping from Meta-Modes + scores → allocation multipliers and recycling intensity.
- [ ] Must be compatible with the existing `HydraCapitalManager` API (extend it if needed).

### Task 2.4: Special Modes Implementation

- [ ] Implement at least the following modes with clearly different behavior:
  - Crisis_Acute
  - Post_Crisis_Recovery
  - Strong_Broad_Momentum
  - Elevated_Vol_Defensive

---

## Phase 3: Controlled ML / Adaptive Components (COMPLETE — 2026-05-31)

### Task 3.1: Ensemble Regime Predictor (Optional but Planned) (COMPLETE)

- [x] Only after Phase 1 and Phase 2 are solidly validated.
- [x] Start with a very small, heavily regularized ensemble (e.g., 3-5 simple models).
- [x] All models must pass strict stability and walk-forward tests before being allowed to influence live decisions.

### Task 3.2: Limited Online Adaptation (Very Conservative)

- [x] Design a narrow, safe online learning component (if any) — example: slowly adapting aggression parameters in Recovery Mode.
- [x] Must have strong guardrails and human override.

**Completed (2026-05-31, worktree):** Single scalar `recovery_aggression_boost` (multiplies existing `recovery_boost_factor` only). All inside `hydra_meta/meta_layer.py` (no new files). Disabled by default + manual_override knob + hard bounds [0.98,1.12] + slow step/inertia + decay on exit + full rationale + fail-safe neutral on error. 10 synthetic trajectory TDD tests (RED→GREEN). All prior meta tests (61+18) remain green. Version + docs updated. See Task 3.2 section in meta_layer.py header + controller for rationale.

**Self-review notes (per AGENTS/CLAUDE):** 
- Strict TDD followed (tests edited + RED verified before any source change to controller).
- Zero scope creep: only recovery aggression, zero touch to caps/pillars/COMPASS/Phase1 contracts.
- Followed "NEVER create files", "extend existing", "atomic if persisting (hooks only, not activated)", "ML fail-safe", "Seed 666 convention", "conservative neutral".
- All changes behind explicit versioned params.
- No dead code; minimal diff.
- Recommendation for Phase 5: add this component (with enabled=True) to the integrated harness and run full walk-forward + stress (2008/2020/2022) with sensitivity on bounds/step. Monitor adaptation frequency in shadow mode before any live enable.

---

## Phase 4: Integration with Existing HYDRA

### Task 4.1: Extend HydraCapitalManager

**Files:**
- Modify: `hydra_capital.py`

- [x] Add support for richer inputs from the new Meta-Layer (multipliers, mode-based behavior). **DONE** (2026-05-31)
- [x] Maintain full backward compatibility. **DONE**
- [x] Detailed prep document created.
- [x] Added `meta_decision: Optional[Dict] = None` to `compute_allocation(...)` + `update_accounts_after_day`.
- [x] Applies pillar multipliers + recycling_multiplier modulation.
- [x] Enhanced return dict with `meta_applied`, `applied_*` fields.
- [x] Updated `get_status(...)` to optionally surface last meta factors.
- [x] Updated docs + `to_dict` comments for Phase 4 persistence model.
- [x] Committed in worktree (see recent commits after 88253c0).

### Task 4.2: Wire Regime OS + Meta-Layer into omnicapital_live.py

**Files:**
- Modify: `omnicapital_live.py`

- [ ] Add initialization of the new components (behind feature flag).
- [ ] Call them at the appropriate point in the daily cycle.
- [ ] Persist new state fields using atomic write pattern.
- [ ] **Exact locations identified** (live inspection 2026-05-31):
  - Init: ~line 971 (after HydraCapitalManager creation)
  - Allocation calls: multiple sites (~1955, 1976, 2200, etc.) — pass `meta_decision` when active
  - State save: `save_state()` after line 4684 (atomic write pattern must be followed exactly)
- [ ] Copy existing import guard pattern (`_hydra_available`, etc.)
- [ ] Recommended flag: `ENABLE_META_LAYER` env var (0 / 1 / shadow) + config fallback
- [ ] See prep doc §2.2 and §5 for concrete insertion points and pilot strategy (wire one call site first).

### Task 4.3: State & Logging

- [ ] Define new fields for `compass_state_latest.json`.
- [ ] Implement rich decision logging (what regime was seen, what decision was made, why).
- [ ] **Proposed schema** (see prep doc §4): nested `meta_layer` object with `last_decision`, `regime_scores`, `enabled`, `mode`, `version`, `confidence`, `rationale`, etc.
- [ ] Lightweight top-level fields for quick dashboard consumption optional.
- [ ] Only write meta fields when the layer was active in that cycle.
- [ ] Rich cycle log entries (new or extend existing `_append_audit_log` / cycle log).

### Task 4.4: Feature Flag & Safety Layer

- [x] Implement clean on/off switch for the entire Meta-Layer. (STARTED)
- [x] **Recommended flag**: `ENABLE_META_LAYER=0|1|shadow` (env var, default 0 = fully disabled). (implemented in first wiring slice)
- [ ] Shadow mode: compute + log everything, but force neutral multipliers (1.0) and recycling_mult=1.0.
- [ ] Full degradation matrix defined in prep doc §3.3.
- [ ] Runtime override knobs in state (manual gross exposure, manual recycling mult).
- [ ] All errors in meta path → neutral decision + disable for the cycle + logging (never crash engine).
- [x] Initial wiring skeleton committed (flag + guards + state placeholder + pilot site). See commit 5f3d969.

---

## Phase 5: Full Validation Pipeline

### Task 5.1: Integrated Backtest Harness

- [ ] Extend or create new harness inside `hydra_backtest/` that runs full HYDRA + new Meta-Layer.
- [ ] Must produce comparable results to current live engine behavior when Meta-Layer is disabled.

### Task 5.2: Execute the Full Validation Protocol

- Run the entire 4-layer validation process defined in the spec.
- Document all results in `research/meta_layer_v1/validation_report.md`.

### Task 5.3: Stress Testing & Sensitivity

- Specific deep dives into 2008, 2020, 2022, and any other difficult periods.

---

## Phase 6: Production Readiness & Deployment Prep

### Task 6.1: Monitoring & Observability

- Expose key regime scores and Meta-Layer decisions through existing API.
- Add basic alerting logic for anomalous behavior.

### Task 6.2: Documentation & Runbooks

- Update relevant READMEs and add a dedicated `docs/meta_layer_v1/` folder.
- Write a clear "How to disable the Meta-Layer in production" runbook.

### Task 6.3: Shadow / Paper Trading Deployment

- Deploy with Meta-Layer completely disabled first.
- Enable in shadow mode (decisions logged but not acted upon).
- Only after sufficient observation period, move to small controlled exposure.

---

## Phase 7: Iteration & Hardening

- Based on shadow/live results, plan targeted improvements (separate plan).

---

## Self-Review Checklist (to be completed after plan is written)

- [ ] Every requirement from the design spec has at least one corresponding task or phase.
- [ ] No "TBD", "implement later", or vague steps remain.
- [ ] All new modules have clear ownership and interfaces.
- [ ] Validation is front-loaded and non-negotiable.
- [ ] Fail-safe and rollback paths are explicitly planned.
- [ ] The plan respects the "COMPASS v8.4 is locked" constraint everywhere.

---

**Plan Status**: Initial version created. Ready for review and refinement before execution begins.

**Recommended Execution Approach**: Subagent-driven development (one focused subagent per major phase or major component, with human review between phases). This is a research-heavy project with high validation requirements — incremental, reviewable progress is strongly preferred over big-bang implementation.

---

**Next Action for Human:**
Please review this plan. Once approved, we will decide on execution mode (subagent-driven vs inline with checkpoints) and begin Phase 0 / Phase 1.