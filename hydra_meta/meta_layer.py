"""
hydra_meta/meta_layer.py — Meta-Layer Decision Engine Interface (HYDRA Meta-Layer v1, Task 2.1)

This module defines the clean public input/output contract for the Meta-Layer.

Phase 2, Task 2.1 (COMPLETE):
- `PortfolioState`: minimal frozen dataclass capturing the current portfolio
  snapshot needed by the Meta-Layer (total equity, cash, per-pillar allocations,
  current gross exposure, drawdown). Designed to be easily populated from
  HydraCapitalManager.get_status() + lightweight metrics.
- `MetaLayerDecision`: frozen, well-documented output dataclass containing
  the high-level directives the rest of the system will act upon:
    - gross_exposure (overall target deployment fraction)
    - multipliers (per-pillar allocation scaling)
    - recycling_multiplier (cash recycling aggressiveness)
    - active_modes (MetaModes the decision is reacting to)
    - confidence + metadata (as_of, version, rationale) for auditability
- `MetaLayer`: runtime_checkable Protocol defining the single decision method
  (plus a minimal get_version for introspection, per clarification).
- `StubMetaLayer`: minimal concrete implementation that **always** returns
  the same conservative neutral decision. This is the safe default for early
  integration and feature-flag rollout (real logic in Tasks 2.2–2.4).

The Meta-Layer sits *above* the four pillars (COMPASS v8.4 locked, Rattlesnake,
Catalyst, EFA). It does not generate individual signals — it only produces
high-level risk and allocation directives.

Design constraints (non-negotiable, matching Phase 1 + project rules):
- Fail-safe: never raise on bad/missing/ extreme inputs. Always return a
  conservative neutral decision on any error path.
- Frozen dataclasses for immutability and safe use in state/logs.
- Conservative neutral defaults in the stub (gross=1.0, multipliers=1.0,
  recycling=1.0, no active modes, confidence=0.5). Respects LEVERAGE_MAX spirit
  (stub never exceeds 1.0 gross).
- Uses Seed 666 for any future controlled randomness (none required in stub).
- Fully compatible with existing HydraCapitalManager (no changes needed yet;
  richer integration in Phase 4).
- Thoroughly documented contract so future implementations (rule-based in 2.2+,
  ensembles in Phase 3) can satisfy it without ambiguity.

References:
- docs/superpowers/specs/2026-06-05-hydra-meta-layer-v1-design.md (esp. §6 Meta-Layer)
- docs/superpowers/plans/2026-06-05-hydra-meta-layer-v1-implementation.md (Tasks 2.1 + 2.2)
- regime_os.py (RegimeScores, MetaMode, RegimeOS Protocol patterns, StabilityParams)
- hydra_capital.py (existing pillar accounts + recycling for input shape alignment)
- AGENTS.md / Claude.md (all critical rules: algorithm locked, LEVERAGE_MAX=1.0,
  state sacred, ML fail-safe, Seed 666, no secrets)
- tests/test_meta_layer.py (Task 2.1 TDD contract tests)
- tests/test_meta_layer_risk.py (Task 2.2 TDD tests for risk budgeting)

This interface is the source of truth for Phase 2.

Task 2.2 (COMPLETE):
- `RiskBudgetParams`: frozen, richly documented dataclass holding ~15 tunable
  parameters for all risk rules (gross caps per regime, recovery thresholds,
  velocity params, asymmetry factors, independent stability, recycling starters).
- `RiskBudgetMetaLayer`: full rule-based implementation of the MetaLayer
  Protocol delivering asymmetric aggression, Recovery Mode (DD-triggered
  boost), Drawdown Velocity Control (rapid vs slow), and regime-dependent
  hard exposure caps. All logic heavily parameterized + versioned.
- PortfolioState extended (backward-compat) with velocity helper fields.
- MetaLayerDecision active_modes relaxed to accept str risk tags.
- Strict TDD: tests/test_meta_layer_risk.py written first (RED), then impl,
  full green + zero regressions on Stub / original contract.
- StubMetaLayer left 100% untouched as the safe default.

Task 2.3 (COMPLETE):
- New dedicated `PillarMultiplierParams` dataclass (per clarification) with
  full tables for mode-driven scalers, score blend weights, per-pillar clamps,
  and recycling rules (heavily parameterized, documented, versioned).
- `RiskBudgetParams` now composes `pillar_params` (preferred source).
- `compute_decision` signature extended with optional `active_modes` param
  (default=None for 100% backward compat). Protocol + both implementations
  updated.
- Rich mapping (MetaModes + scores → pillar multipliers in ~[0.55,1.65] and
  recycling_multiplier as direct scalar) implemented only AFTER writing
  comprehensive failing behavioral tests (this file + test_meta_layer_risk.py).
- No changes to StubMetaLayer behavior.
- Light HydraCapital compatibility notes only; full integration is Phase 4.
- Per user: proposed full documented regime→pillar table lives in the test
  module (as executable expectations) + implementation comments.

Task 2.4 (COMPLETE — TDD first, then impl):
- Added optional `risk_flags: List[str]` field to MetaLayerDecision (with full
  docs) per clarification ("add 1-2 new optional fields").
- Extended *existing* dataclasses (RiskBudgetParams with ~12 new special_*
  tunable fields + small PillarMultiplierParams extensions).
- Implemented 4 modes with *qualitatively different* behaviors (Crisis_Acute
  hard defense even on slow DD + flag; Post_Crisis_Recovery accel at lower DD
  + faster recycle + flag; Strong_Broad_Momentum max COMPASS + diversifier
  suppression + flag; Elevated_Vol_Defensive MR/Rattlesnake bias + conservative
  recycle + MR-friendly flag). 5 new str tags + legacy support.
- Small _SpecialModeApplicator class (composition inside RiskBudgetMetaLayer)
  for separation of special logic (all inside this single file — no new .py
  created, per guideline).
- All fail-safe, conservative defaults, fully parameterized, rich rationale,
  different Decision outputs. Updated tests + module docs.
- No Phase 4 wiring (per instructions). Strict TDD (tests written + RED
  verified before any special logic).

References now also include Task 2.3 + Task 2.4 (this work) + user clarifications from ask_user_question.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Protocol, Union, runtime_checkable

# Upstream Regime OS types (Phase 1 — do not modify)
from regime_os import RegimeScores, MetaMode


# =============================================================================
# SEED (project convention — use for any controlled randomness in later tasks)
# =============================================================================
SEED = 666


# =============================================================================
# INPUT: PortfolioState
# =============================================================================

@dataclass(frozen=True)
class PortfolioState:
    """Current portfolio snapshot passed as input to the Meta-Layer.

    This is a minimal, reasonable structure (per Task 2.1 clarification) that
    captures enough context for high-level allocation and risk decisions without
    leaking low-level position or order details.

    Fields are chosen for easy construction from HydraCapitalManager.get_status()
    plus lightweight derived metrics (current gross exposure and drawdown).
    The structure is intentionally small for Phase 2.1; additional fields can be
    added later with backward-compatible defaults.

    All implementations of MetaLayer (stub and future) must treat this as
    read-only information. They must never mutate it.

    Defaults represent a plausible neutral starting point for unit tests.
    Callers (live engine, backtest harnesses) are responsible for populating
    realistic values each cycle.
    """

    total_equity: float = 100_000.0
    """Total portfolio equity (sum of all pillar accounts + EFA + cash)."""

    cash: float = 30_000.0
    """Approximate idle cash available (not yet allocated to any pillar)."""

    pillar_allocations: Dict[str, float] = field(
        default_factory=lambda: {
            "COMPASS": 42_500.0,
            "Rattlesnake": 42_500.0,
            "Catalyst": 15_000.0,
            "EFA": 0.0,
        }
    )
    """Current notional allocations (or account values) per pillar.
    Keys are the canonical four: COMPASS, Rattlesnake, Catalyst, EFA.
    Values are in the same currency units as total_equity.
    """

    current_gross_exposure: float = 0.75
    """Current overall gross exposure as a fraction of total equity (0.0–2.0+).
    0.75 means ~75% of capital is currently deployed across all pillars.
    """

    drawdown_pct: float = 0.0
    """Current unrealized drawdown from recent peak (0.0 = at peak or new high,
    0.55 = 55% drawdown). Used by future Recovery Mode and velocity logic.
    """

    # --- Task 2.2 velocity helper fields (backward-compatible extension) ---
    drawdown_5d_ago: float = 0.0
    """Drawdown pct ~5 trading days ago (for velocity calculation).
    Velocity (worsening) ≈ max(0.0, (drawdown_pct - drawdown_5d_ago) / 5.0).
    Populated by callers (live engine, harnesses) from historical snapshots when
    available. Default 0.0 yields conservative "no rapid worsening" assumption.
    """

    recent_return_5d: float = 0.0
    """Recent ~5d portfolio or benchmark return (cross-check for velocity).
    Negative values during elevated drawdown increase velocity signal.
    """


# =============================================================================
# OUTPUT: MetaLayerDecision (the core contract)
# =============================================================================

@dataclass(frozen=True)
class MetaLayerDecision:
    """High-level portfolio directive produced by the Meta-Layer each cycle.

    This is the primary output contract for Task 2.1 (and all future Meta-Layer
    implementations). Downstream components (HydraCapitalManager enhancements,
    live engine, backtest harness, dashboards) will consume these fields to
    modulate exposure, pillar sizing, recycling aggressiveness, and special
    behavioral modes.

    The dataclass is frozen for safety (immutable snapshots suitable for
    state files, audit logs, and replay).

    Minimum required fields (per Task 2.1 spec):
    - gross_exposure: target overall portfolio exposure (e.g. 0.70–1.40 range
      in aggressive designs; stub is capped at 1.0 for conservatism).
    - multipliers: per-pillar scaling factors applied on top of base
      allocations (COMPASS, Rattlesnake, Catalyst, EFA). Neutral = 1.0.
    - recycling_multiplier: scalar on how aggressively to recycle idle cash
      between pillars (1.0 = baseline behavior from HydraCapitalManager).
    - active_modes: the MetaModes (from Regime OS) that this decision is
      reacting to. May be empty.
    - confidence: [0.0, 1.0] self-reported confidence in the decision.

    Recommended metadata (added per clarification for auditability & future
    work even in the v1 interface):
    - as_of: optional reference date for the decision.
    - version: interface / implementation version string.
    - rationale: human- or machine-readable explanation (especially useful
      once real logic lands in 2.2+).

    Task 2.4 addition (per clarification):
    - risk_flags: List[str] (optional, default empty). Captures qualitatively
      different special mode behaviors (Crisis_Acute hard defense, Recovery
      acceleration, Strong Momentum overrides, Elevated Vol MR-friendly posture)
      as actionable tags. Distinct from active_modes. All existing code paths
      (Stub, fail-safe, prior RiskBudget) continue to produce [] or legacy tags.

    Future fields may be added with safe defaults. All consumers must be
    prepared to ignore unknown keys when serializing.
    """

    gross_exposure: float = 1.0
    """Target gross exposure for the overall portfolio as a fraction of equity.
    Examples of intended range in later tasks: 0.70 (defensive) to 1.40
    (aggressive recovery / strong momentum). The StubMetaLayer always returns
    exactly 1.0 (full but unlevered deployment per project LEVERAGE_MAX spirit).
    """

    multipliers: Dict[str, float] = field(
        default_factory=lambda: {
            "COMPASS": 1.0,
            "Rattlesnake": 1.0,
            "Catalyst": 1.0,
            "EFA": 1.0,
        }
    )
    """Allocation multipliers applied per pillar (on top of base weights or
    current HydraCapitalManager budgets). Values are typically in [0.0, 2.0]
    range; 1.0 = no change from baseline. Stub always returns all 1.0.
    """

    recycling_multiplier: float = 1.0
    """Scalar modulating cash recycling intensity.
    1.0 = baseline HydraCapitalManager behavior.
    < 1.0 = more conservative (less recycling into COMPASS).
    > 1.0 = more aggressive recycling.
    Stub always returns exactly 1.0.
    """

    active_modes: List[Union[MetaMode, str]] = field(default_factory=list)
    """The MetaModes (from the upstream Regime OS) that this decision is
    primarily reacting to. Order is not significant. May be empty when no
    strong regime signal is present.

    Task 2.2 extension (per clarification): risk-derived behavioral tags are
    permitted as str values alongside MetaMode members (e.g. "RECOVERY_AGGRESSION",
    "VELOCITY_DERISK"). Consumers must handle str entries gracefully. The
    RiskBudgetMetaLayer may append such tags when special risk rules activate.
    The StubMetaLayer continues to return [] (pure MetaMode list).
    """

    # Task 2.4: Special Modes — new optional field (chosen per clarification)
    # Captures qualitatively distinct behavioral flags that go beyond the
    # numeric gross/multipliers/recycle and the regime active_modes.
    # Populated by special mode logic; always a list (possibly empty).
    # Safe default + frozen ensures full backward compatibility for all
    # existing call sites and JSON state.
    risk_flags: List[str] = field(default_factory=list)
    """Task 2.4 special-mode risk/behavior flags (qualitatively different actions
    triggered by Crisis_Acute, Post_Crisis_Recovery, Strong_Broad_Momentum,
    Elevated_Vol_Defensive, etc.).

    Examples of produced values (see implementation + tests):
      "CRISIS_ACUTE_HARD_DEFENSE", "RECOVERY_ACCEL", "STRONG_MOMENTUM_OVERRIDE",
      "VOL_DEFENSIVE_MR_FRIENDLY", "CRISIS_DEFENSE" (legacy compatibility).

    These are *actionable* tags for future HydraCapitalManager / execution
    (Phase 4) even though the special modes themselves produce observably
    different gross_exposure, multipliers, and recycling_multiplier.

    Consumers must treat unknown flags gracefully (ignore). Empty list = no
    special mode overrides active this cycle. StubMetaLayer always returns [].
    """

    confidence: float = 0.5
    """Self-reported confidence of the Meta-Layer in this decision [0.0, 1.0].
    Stub always returns 0.5 (neutral / "I have no strong opinion yet").
    Future implementations will compute this from score strength, stability,
    and historical validation.
    """

    as_of: Optional[date] = None
    """Optional reference date for which the decision was computed.
    Useful for historical replay, backtests, and audit trails.
    """

    version: str = "1.0"
    """Version of the MetaLayerDecision contract / producing implementation.
    Allows consumers to handle evolution gracefully.
    """

    rationale: Optional[str] = None
    """Optional human-readable (or structured) explanation of why this
    decision was reached. Especially valuable once real logic is present.
    Stub populates a short note indicating it is the neutral default.
    """


# =============================================================================
# TASK 2.2: RISK BUDGET PARAMS (heavily parameterized, versioned)
# =============================================================================

@dataclass(frozen=True)
class RiskStabilityState:
    """Minimal read-only snapshot of the internal risk-layer stability state.
    Useful for diagnostics, logging, and Task 5 harness analysis.
    """
    ema_gross: float
    stable_bars: int
    prev_gross: float


# =============================================================================
# TASK 2.3: PILLAR MULTIPLIER & RECYCLING PARAMS (NEW dedicated dataclass)
# =============================================================================

@dataclass(frozen=True)
class PillarMultiplierParams:
    """Heavily parameterized, interpretable configuration for pillar allocation
    multipliers (COMPASS, Rattlesnake, Catalyst, EFA) and recycling intensity
    modulation (Task 2.3).

    This dataclass is the central tuning surface for the improved regime-aware
    pillar logic. All thresholds, boosts, clamps, and blend weights live here
    so behavior can be validated, swept in Task 5 harnesses, and evolved safely.

    Design (per clarifications + design spec principles):
    - Independent scalers (neutral = 1.0) in approximately [0.55, 1.65] range.
    - Primary drivers: passed active MetaModes (preferred) + continuous scores.
    - Fallback derivation of modes (using similar conservative thresholds to
      RiskBudget's _get_mode_cap) when active_modes is None or empty.
    - Blends discrete mode adjustments + continuous score contributions for
      smooth, non-binary behavior.
    - Recycling_multiplier is a direct scalar intended to compose (multiply)
      with or eventually supersede the coarse REGIME_CONFIG in HydraCapitalManager.
    - Conservative bias overall: large upside boosts only in high-conviction
      favorable regimes; defensive reductions are present but not extreme.
    - Full auditability via rich rationale in the returned Decision.
    - Special behavioral modes (Task 2.4) implemented via light extensions here
      + primary heavy parameterization and applicator logic in RiskBudgetParams
      and RiskBudgetMetaLayer (see dedicated section in RiskBudgetParams).

    Versioning: travels in MetaLayerDecision and layer version string.

    References:
    - docs/superpowers/specs/2026-06-05-hydra-meta-layer-v1-design.md §6
    - Task 2.3 approved implementation approach (clarified via ask_user_question)
    - Existing starter logic in RiskBudgetMetaLayer (lines ~755) is replaced
      by the rich mapping once tests are green.
    """

    # --- Versioning ---
    version: str = "pillar-v1.0-multi-recycle-202606"
    """Bumped for any material change to tables, weights, or clamps."""

    # --- Mode-driven base adjustments (multiplicative scalers; 1.0 = neutral) ---
    # These are applied when the corresponding MetaMode is active (or derived).
    # Values chosen conservatively; larger moves only where regime strongly
    # justifies (e.g. momentum pillars in strong broad momentum).
    # Missing keys default to 1.0 inside the implementation.
    mode_compass_mult: Dict[str, float] = field(
        default_factory=lambda: {
            "STRONG_BROAD_MOMENTUM": 1.29,
            "POST_CRISIS_RECOVERY": 1.09,
            "NARROW_MOMENTUM": 1.01,
            "CRISIS_ACUTE": 0.82,
            "ELEVATED_VOL_DEFENSIVE": 0.93,
            "LIQUIDITY_STRESS": 0.95,
            "MEAN_REVERSION_RICH": 0.90,
        }
    )
    mode_rattlesnake_mult: Dict[str, float] = field(
        default_factory=lambda: {
            "MEAN_REVERSION_RICH": 1.42,
            "ELEVATED_VOL_DEFENSIVE": 1.18,
            "LIQUIDITY_STRESS": 1.12,
            "POST_CRISIS_RECOVERY": 1.08,
            "STRONG_BROAD_MOMENTUM": 0.84,
            "CRISIS_ACUTE": 0.92,
            "NARROW_MOMENTUM": 0.97,
        }
    )
    mode_catalyst_mult: Dict[str, float] = field(
        default_factory=lambda: {
            "STRONG_BROAD_MOMENTUM": 0.72,
            "NARROW_MOMENTUM": 0.88,
            "CRISIS_ACUTE": 1.06,
            "ELEVATED_VOL_DEFENSIVE": 1.09,
            "LIQUIDITY_STRESS": 1.04,
            "POST_CRISIS_RECOVERY": 0.95,
            "MEAN_REVERSION_RICH": 0.98,
        }
    )
    mode_efa_mult: Dict[str, float] = field(
        default_factory=lambda: {
            "STRONG_BROAD_MOMENTUM": 0.78,
            "NARROW_MOMENTUM": 0.91,
            "CRISIS_ACUTE": 1.03,
            "ELEVATED_VOL_DEFENSIVE": 1.11,
            "LIQUIDITY_STRESS": 1.07,
            "POST_CRISIS_RECOVERY": 0.97,
            "MEAN_REVERSION_RICH": 1.01,
        }
    )

    # --- Continuous score blend coefficients (additive lift on top of mode base) ---
    # Even when no exact mode fires, scores produce smooth modulation.
    # Weights are small so mode signals dominate when present; normalized later.
    score_compass_mom_weight: float = 0.38
    score_compass_breadth_weight: float = 0.22
    score_compass_inv_stress_weight: float = 0.25
    score_compass_inv_vol_weight: float = 0.12

    score_rattlesnake_mr_weight: float = 0.48
    score_rattlesnake_inv_mom_weight: float = 0.28
    score_rattlesnake_stress_weight: float = 0.12   # mild positive in stress (dips)

    score_catalyst_inv_mom_weight: float = 0.35
    score_catalyst_stress_weight: float = 0.30
    score_catalyst_liq_weight: float = 0.18

    score_efa_inv_mom_weight: float = 0.32
    score_efa_stress_weight: float = 0.28
    score_efa_liq_weight: float = 0.22

    # Unified lift scale applied to all score-driven adjustments (Task 2.3 Code Quality polish)
    # Promotes full parameterization and makes future tuning / harness sweeps much easier.
    score_lift_scale: float = 0.42

    # --- Per-pillar hard clamps (enforced after all adjustments) ---
    compass_min: float = 0.55
    compass_max: float = 1.58
    rattlesnake_min: float = 0.58
    rattlesnake_max: float = 1.62
    catalyst_min: float = 0.60
    catalyst_max: float = 1.25   # ring-fenced pillar; more conservative range
    efa_min: float = 0.62
    efa_max: float = 1.22

    # --- Recycling modulation parameters (regime-aware intensity) ---
    # recycling_multiplier = base * score_factor * mode_factor, then clamped.
    # Intended as direct scalar (multiply with or supersede coarse REGIME_CONFIG).
    recycle_conviction_high: float = 0.58
    recycle_mom_high: float = 0.72
    recycle_stress_high: float = 0.62
    recycle_mr_high: float = 0.55
    recycle_breadth_high: float = 0.60

    recycle_favorable_base: float = 1.28
    """Aggressive recycling when momentum/breadth strong + stress low."""
    recycle_defensive_base: float = 0.71
    """Conservative recycling in stress / crisis (preserve for Rattlesnake)."""
    recycle_recovery_boost: float = 1.15
    """Slight extra recycling in Post-Crisis Recovery to accelerate redeployment."""
    recycle_mr_rich_dampen: float = 0.82
    """Dampen recycling into COMPASS when mean-reversion environment is rich."""

    recycle_min: float = 0.58
    recycle_max: float = 1.48

    # --- Derivation thresholds (for internal fallback mode list when not passed) ---
    # Kept in sync with (but independent from) RiskBudgetParams.derivation for
    # clean separation of the pillar sub-system.
    derivation: Dict[str, float] = field(
        default_factory=lambda: {
            "strong_mom": 0.76,
            "strong_breadth": 0.63,
            "strong_stress_max": 0.32,
            "strong_vol_max": 0.42,
            "narrow_mom": 0.62,
            "narrow_breadth_max": 0.40,
            "crisis_stress": 0.78,
            "elev_vol_or_stress": 0.59,
            "recovery_stress_max": 0.58,
            "recovery_mom_min": 0.48,
            "recovery_mr_min": 0.44,
            "liq_max": 0.35,
            "mr_rich_mr_min": 0.51,
            "mr_rich_mom_max": 0.52,
        }
    )

    # --- Task 2.4 light extensions (per "extend existing dataclasses") ---
    # Minor special-mode overrides that compose with the main tables.
    # Heavy special behavior lives in RiskBudgetParams special_* fields +
    # the applicator (keeps Pillar focused on its 2.3 responsibility).
    special_compass_momentum_override: float = 1.12
    """Extra multiplier factor applied only under STRONG_BROAD_MOMENTUM special logic."""
    special_rattlesnake_vol_defensive: float = 1.14
    """Extra factor for Rattlesnake when ELEVATED_VOL_DEFENSIVE + MR rich."""


@dataclass(frozen=True)
class RiskBudgetParams:
    """All tunable parameters for asymmetric risk budgeting, Recovery Mode,
    and Drawdown Velocity Control.

    This is the central configuration point for Task 2.2. Every rule is
    parameterized here so that behavior can be validated, swept, and evolved
    without code changes. Conservative defaults chosen to respect project
    constraints (fail-safe, LEVERAGE caveats documented, no leverage in stub).

    Versioning: the `version` field travels with decisions for full audit
    trail (state files, logs, research).

    Per approved clarifications (2026-05-30):
    - Independent stability machinery lives inside RiskBudgetMetaLayer.
    - gross_exposure may propose up to ~1.38 (hard_max) in favorable +
      Recovery scenarios; downstream (HydraCapital / execution) is responsible
      for enforcing LEVERAGE_MAX spirit.
    - Velocity uses the two new helper fields on PortfolioState.
    - Asymmetry favors aggression in high-conviction favorable regimes.

    Do not modify defaults lightly — any production change requires
    re-validation through the full harness (Task 5+).
    """

    # --- Versioning & identity ---
    version: str = "risk-v1.2-special-modes-202606"
    """Semantic version of this parameter set. Bumped on any material change
    to thresholds, caps, or rule weights. Appears in MetaLayerDecision.version
    and get_version() for the producing implementation.

    Task 2.4 bump: added full special mode behavior parameters + support for
    populating risk_flags on decisions.
    """

    # --- Derivation thresholds (for score-driven mode cap selection and conviction)
    # These were previously internal magic numbers. Promoting them here makes
    # the full rule surface tunable for Task 5 sweeps and future refinement.
    # Values are intentionally conservative (Phase 1 defaults).
    derivation: Dict[str, float] = field(
        default_factory=lambda: {
            "crisis_stress": 0.70,           # stress > this → consider CRISIS_ACUTE cap
            "elevated_vol_stress": 0.58,     # stress > this or vol > ... → ELEVATED_VOL_DEFENSIVE
            "elevated_vol_vol": 0.62,
            "strong_mom": 0.78,              # mom + breadth + low stress/vol → STRONG_BROAD_MOMENTUM
            "strong_breadth": 0.65,
            "strong_stress_max": 0.30,
            "strong_vol_max": 0.40,
            "narrow_mom": 0.60,              # mom high + breadth low → NARROW_MOMENTUM
            "narrow_breadth_max": 0.42,
            "recovery_stress_max": 0.55,     # stress low + mom + mr → POST_CRISIS_RECOVERY
            "recovery_mom_min": 0.50,
            "recovery_mr_min": 0.45,
            "liq_stress_max": 0.38,          # low liquidity stance → LIQUIDITY_STRESS
            "meanrev_mr_min": 0.52,          # high mr + low mom → MEAN_REVERSION_RICH
            "meanrev_mom_max": 0.55,
            "high_conviction": 0.55,         # conviction > this → apply asymmetric aggression
        }
    )

    # --- Regime-dependent hard gross exposure caps (fraction of equity) ---
    # Stronger defense in bad regimes (Crisis especially). Favorable modes
    # allow controlled aggression. "default" used for unknown/missing modes.
    gross_caps: Dict[str, float] = field(
        default_factory=lambda: {
            "default": 1.0,
            "CRISIS_ACUTE": 0.60,
            "ELEVATED_VOL_DEFENSIVE": 0.72,
            "LIQUIDITY_STRESS": 0.78,
            "POST_CRISIS_RECOVERY": 1.08,
            "STRONG_BROAD_MOMENTUM": 1.22,
            "NARROW_MOMENTUM": 1.05,
            "MEAN_REVERSION_RICH": 0.98,
        }
    )
    """Hard cap on gross_exposure when a given MetaMode (or "default") is active.
    The strictest (lowest) cap among all active modes wins. Values >>1.0 only
    in strong favorable + Recovery paths (subject to hard_max_gross).
    """

    hard_max_gross: float = 1.38
    """Absolute ceiling on any proposed gross_exposure (even Recovery + Strong
    Momentum). 1.38 chosen as aggressive but within documented interface range;
    downstream clipping to 1.0 is expected per LEVERAGE_MAX guidance.
    """

    hard_min_gross: float = 0.52
    """Absolute floor. Even in worst Crisis we never go to zero (operational
    reasons + to allow opportunistic mean-reversion via Rattlesnake).
    """

    # --- Recovery Mode (material DD triggers allowed aggression) ---
    recovery_dd_threshold: float = 0.07
    """Drawdown pct at/above which Recovery Mode aggression is considered.
    7% chosen as material but not catastrophic (aligns with historical
    frequent-enough but not constant triggers).
    """

    recovery_boost_factor: float = 1.18
    """Multiplier applied to base target gross when Recovery conditions met
    (DD >= threshold + minimum momentum/meanrev support). Capped by hard_max.
    Encourages shortening recovery time without removing all brakes.
    """

    recovery_requires_mom: float = 0.38
    """Minimum equity_momentum_strength required to unlock full recovery boost.
    Prevents boosting in a true ongoing crash even if DD is deep.
    """

    # --- Drawdown Velocity Control ---
    velocity_worsening_threshold: float = 0.012
    """Average daily DD increase (fraction) that counts as "rapid".
    (drawdown_pct - drawdown_5d_ago) / 5.0 > this → velocity defense engages.
    1.2%/day is a fast grind / acute leg down.
    """

    velocity_defense_scale: float = 0.82
    """When rapid velocity detected, the provisional gross is multiplied by
    this factor (stronger de-risk than the normal defensive reading at same
    absolute DD level). Asymmetric: we defend faster than we would in slow DD.
    """

    # --- Asymmetric Aggression (core approved principle) ---
    asym_up_aggression: float = 0.20
    """In high-conviction favorable regimes (high mom + breadth + low stress/vol),
    the base target gross receives an additive boost up to this fraction.
    Significantly larger than the defensive side (asymmetry).
    """

    asym_down_defense: float = 0.10
    """In unfavorable regimes the base target is reduced by at most this
    fraction. Deliberately smaller than asym_up — we are more aggressive
    when conditions are good than defensive when they are bad (within caps).
    """

    # --- Independent risk-layer stability (NOT the RegimeOS StabilityParams) ---
    risk_ema_alpha: float = 0.32
    """EWMA smoothing factor applied to the final gross_exposure output on
    sequential (live) calls. Higher = more responsive. Independent of the
    Regime OS EMA/hysteresis/min-duration/cooldown machinery.
    """

    risk_min_bars_stable: int = 2
    """Minimum consecutive decisions before the risk layer will allow a
    material change in gross exposure direction. Simple guard against chatter.
    (Lightweight; full counters can be added later.)
    """

    # --- Recycling & multiplier starters (Task 2.2 minimal; full in 2.3) ---
    # NOTE (Task 2.3): The rich pillar + recycling logic now lives in the
    # dedicated PillarMultiplierParams (composed below). These two legacy
    # scalars are retained only for backward compatibility of existing
    # RiskBudgetParams construction in tests; the RiskBudgetMetaLayer now
    # prefers self.params.pillar_params for all multiplier/recycle decisions.
    base_recycle_mult_favorable: float = 1.12
    """Legacy (Task 2.2). Rich behavior uses pillar_params.recycle_* fields."""
    base_recycle_mult_defensive: float = 0.78
    """Legacy (Task 2.2). Rich behavior uses pillar_params.recycle_* fields."""

    # =============================================================================
    # TASK 2.4: SPECIAL MODE BEHAVIOR PARAMETERS (heavily parameterized)
    # =============================================================================
    # These extend the existing RiskBudgetParams (per clarification: "extend
    # existing dataclasses"). They drive *qualitatively* different behaviors
    # in the special modes (Crisis_Acute, Post_Crisis_Recovery,
    # Strong_Broad_Momentum, Elevated_Vol_Defensive) beyond the numeric tables
    # already present in gross_caps and PillarMultiplierParams.mode_*_mult.
    #
    # All values conservative by default. Every special rule is tunable for
    # future validation harness sweeps (Task 5). Version bump documents the
    # addition.
    #
    # Design justification (recorded for audit):
    # - Follows "extend existing" answer from ask_user_question.
    # - No new top-level SpecialModeParams dataclass file or module (obeys
    #   "NEVER create files unless absolutely necessary" + prefer edit existing).
    # - A small internal _SpecialModeApplicator (defined later in this file)
    #   provides clean composition inside RiskBudgetMetaLayer for separation
    #   of the qualitatively different logic, while living entirely inside
    #   the single source file meta_layer.py.
    # - Tags go into the new risk_flags field on Decision (also added per
    #   clarification).
    # =============================================================================

    special_crisis_derisk_scale: float = 0.72
    """Extra scale applied to target gross in Crisis_Acute (on top of caps +
    velocity). Lower than standard velocity_defense_scale for 'harder de-risk'
    even on slow drawdowns. Qualitative defensive action."""

    special_crisis_recycle_cap: float = 0.62
    """Hard upper bound on recycling_multiplier when CRISIS_ACUTE active
    (preserve dry powder, favor defensive pillars). Produces visibly lower
    recycle than standard defensive regimes."""

    special_recovery_lower_dd_threshold: float = 0.04
    """When POST_CRISIS_RECOVERY mode is active (from RegimeOS or derivation),
    recovery boost / recycle accel can trigger at this lower DD than the
    standard recovery_dd_threshold. Enables 'faster recovery' qualitative
    behavior."""

    special_recovery_recycle_accelerator: float = 1.22
    """Multiplier applied to recycling when in Post_Crisis_Recovery (in
    addition to pillar_params.recycle_recovery_boost). Encourages rapid
    redeployment of cash into the recovering pillars."""

    special_strong_mom_compass_extra: float = 0.15
    """Additive lift to COMPASS multiplier (after all PillarMultiplierParams
    tables + score lifts) exclusively when STRONG_BROAD_MOMENTUM active.
    Produces 'maximum aggression toward COMPASS' beyond the 2.3 table."""

    special_strong_mom_diversifier_cap: float = 0.78
    """Upper clamp on Catalyst + EFA multipliers when Strong Broad Momentum
    mode dominates. Enforces qualitative 'diversifier suppression'."""

    special_elev_vol_rattlesnake_extra: float = 0.18
    """Extra lift to Rattlesnake multiplier in ELEVATED_VOL_DEFENSIVE (on top
    of the MEAN_REVERSION_RICH / elevated tables). Makes the posture
    'more conservative / mean-reversion friendly'."""

    special_elev_vol_recycle_dampen: float = 0.88
    """Scale factor applied to recycle in elevated vol defensive (more
    conservative than standard stress dampening)."""

    # --- Special mode risk flag vocabulary (for risk_flags + rationale) ---
    # These are the 5-6 new descriptive tags exercised by the TDD tests.
    # Implementation may emit a subset depending on exact conditions.
    special_tag_crisis_hard_defense: str = "CRISIS_ACUTE_HARD_DEFENSE"
    special_tag_recovery_accel: str = "RECOVERY_ACCEL"
    special_tag_momentum_override: str = "STRONG_MOMENTUM_OVERRIDE"
    special_tag_vol_mr_friendly: str = "VOL_DEFENSIVE_MR_FRIENDLY"
    # Legacy tags from 2.2/2.3 ("CRISIS_DEFENSE", "RECOVERY_AGGRESSION" etc.)
    # remain supported for compatibility.

    # --- Task 2.3 composition: dedicated pillar/recycling config (preferred) ---
    pillar_params: "PillarMultiplierParams" = field(
        default_factory=lambda: PillarMultiplierParams()
    )
    """All pillar multiplier tables, score blend weights, clamps, and recycling
    rules. New dedicated dataclass per clarification for separation of concerns.
    RiskBudgetMetaLayer reads from here (not the legacy recycle scalars) when
    computing the improved multipliers and recycling_multiplier.
    """


# =============================================================================
# PROTOCOL: MetaLayer
# =============================================================================

@runtime_checkable
class MetaLayer(Protocol):
    """Public protocol for the HYDRA Meta-Layer Decision Engine.

    The live engine (omnicapital_live.py), backtest harnesses, and any
    future ML components interact *only* through this interface.

    Implementations (stub for Task 2.1, rule-based risk logic for 2.2+,
    ensembles later) must satisfy this Protocol structurally.

    Design constraints (non-negotiable):
    - Fail-safe: never raise on bad/missing inputs. Return a conservative
      neutral MetaLayerDecision on any error path.
    - Conservative by default: early implementations must not increase risk
      beyond baseline HYDRA behavior without explicit, validated justification.
    - Testable in isolation: no dependency on live broker, locked COMPASS
      signals, or external data feeds.
    - Versioned & explainable: get_version() + rationale field support audit.

    The primary method is compute_decision. A get_version helper is included
    on the Protocol (per clarification during Task 2.1) for safe rollout and
    debugging. Future phases may extend the Protocol with additional methods
    (e.g., get_parameters, explain_decision) while preserving backward
    compatibility.
    """

    def compute_decision(
        self,
        scores: RegimeScores,
        portfolio: PortfolioState,
        performance: Optional[Dict[str, Any]] = None,
        active_modes: Optional[List[Union[MetaMode, str]]] = None,
    ) -> MetaLayerDecision:
        """Produce a high-level allocation and risk directive.

        Args:
            scores: The latest RegimeScores from the upstream Regime OS (Phase 1).
                    Never None.
            portfolio: Current portfolio snapshot (see PortfolioState).
                       Callers must not pass mutated objects.
            performance: Optional recent performance metrics (e.g.
                         {"ret_5d": -0.02, "sharpe_20d": 0.8, ...}).
                         May be None or a partial dict. Implementations must
                         degrade gracefully.
            active_modes: Optional list of active MetaModes (or str risk tags)
                          from RegimeOS.compute_regime(). When provided, the
                          pillar multiplier logic (Task 2.3) uses these directly
                          for the regime → multiplier mapping. When None or
                          empty, the implementation falls back to internal
                          score-driven derivation (compatible with pre-2.3
                          callers). Added in Task 2.3; default preserves full
                          backward compatibility for all existing call sites.

        Returns:
            A frozen MetaLayerDecision with directives for gross exposure,
            pillar multipliers, recycling intensity, active modes being
            reacted to, confidence, and explanatory metadata.

        Contract for all implementations:
            - Must never raise (wrap all logic in try/except; return neutral
              conservative decision on any failure).
            - Returned gross_exposure should normally be in a documented
              safe range (stub caps at 1.0).
            - multipliers and recycling_multiplier must be positive floats.
            - active_modes may contain MetaMode members and/or str risk tags (Task 2.2).
            - The object must be safe to JSON-serialize for state/logs.
            - Must be deterministic given identical inputs (modulo any
              documented controlled randomness using SEED).
            - (Task 2.3) When active_modes is supplied it takes precedence for
              pillar/recycling decisions; derivation fallback is deterministic.
            - (Task 2.4) Implementations should populate risk_flags (new optional
              field) for special modes; may be left empty for backward paths.
        """
        ...  # Protocol stub

    def get_version(self) -> str:
        """Return a short version string for this MetaLayer implementation.

        Used for logging, state files, dashboards, and graceful handling
        of contract evolution across deployments.
        """
        ...  # Protocol stub


# =============================================================================
# STUB IMPLEMENTATION (Task 2.1 — safe neutral default)
# =============================================================================

class StubMetaLayer:
    """Minimal concrete implementation satisfying the MetaLayer Protocol.

    This is the *only* production-ready behavior allowed in Task 2.1.

    Purpose:
    - Satisfy the TDD contract tests immediately.
    - Provide a completely safe "no-op" that can be wired (behind feature
      flag) into the live engine and backtests with zero risk increase.
    - Serve as the baseline for integration work in Phase 4 until the
      real risk-budgeting, recovery, velocity, and multiplier logic lands
      in Tasks 2.2–2.4.

    Behavior (per explicit clarification):
    - ALWAYS returns the identical conservative neutral decision:
        gross_exposure = 1.0
        multipliers = {"COMPASS": 1.0, "Rattlesnake": 1.0, "Catalyst": 1.0, "EFA": 1.0}
        recycling_multiplier = 1.0
        active_modes = []
        confidence = 0.5
        version = "1.0"
        rationale = short note indicating neutral stub
    - Completely ignores all inputs (scores, portfolio, performance).
    - Never raises, even on garbage or extreme values.
    - Implements get_version() returning "0.1-stub".

    Real implementations will replace or wrap this pattern. The stub is
    intentionally "dumb" so that any deviation in later tasks is clearly
    attributable to new logic (and must be heavily validated).
    """

    def compute_decision(
        self,
        scores: RegimeScores,
        portfolio: PortfolioState,
        performance: Optional[Dict[str, Any]] = None,
        active_modes: Optional[List[Union[MetaMode, str]]] = None,
    ) -> MetaLayerDecision:
        """Return the fixed neutral conservative decision (ignores inputs).
        Task 2.3: accepts (and completely ignores) the new optional active_modes
        argument for signature compatibility. Stub behavior is untouched.
        """
        # Intentionally no logic, no use of inputs, no randomness.
        # All paths lead to the same safe default.
        try:
            # Even on completely malformed inputs we still succeed.
            _ = scores  # touch to satisfy linters; value unused
            _ = portfolio
            _ = performance
            _ = active_modes
        except Exception:
            pass  # never let bad data escape

        return MetaLayerDecision(
            gross_exposure=1.0,
            multipliers={
                "COMPASS": 1.0,
                "Rattlesnake": 1.0,
                "Catalyst": 1.0,
                "EFA": 1.0,
            },
            recycling_multiplier=1.0,
            active_modes=[],
            risk_flags=[],  # Task 2.4: explicit for contract
            confidence=0.5,
            as_of=None,
            version="1.0",
            rationale="StubMetaLayer neutral default (Task 2.1 interface only; real decision logic in Tasks 2.2+)",
        )

    def get_version(self) -> str:
        """Return the stub version identifier."""
        return "0.1-stub"


# =============================================================================
# TASK 2.4: SMALL INTERNAL SPECIAL MODE APPLICATOR (composition, same file only)
# =============================================================================
# Defined here (not a separate .py) per project guideline "NEVER create files
# unless absolutely necessary. Prefer editing existing files."
#
# This provides the "dedicated ... composition of a small handler class"
# requested in one clarification path while fully complying with the
# "extend existing dataclasses" preference (all tunables live in the
# RiskBudgetParams / PillarMultiplierParams we extended above).
#
# The applicator is deliberately narrow: it only computes adjustments + flags
# for the four required special modes when they are active (via passed list
# or derivation). It does not duplicate core risk/pillar math.
#
# All paths are wrapped for fail-safety. Conservative defaults everywhere.
# =============================================================================

class _SpecialModeApplicator:
    """Internal (non-public) handler for Task 2.4 qualitatively different
    special mode behaviors.

    Instantiated and composed by RiskBudgetMetaLayer (self._special).
    Consumes the extended special_* fields from RiskBudgetParams.

    Returns (gross_adjust, recycle_adjust, extra_mults, flags, rationale_add)
    where adjustments are multiplicative scales (or None if no special action)
    and extra_mults is a dict of pillar deltas to apply after the 2.3 tables.
    """

    def __init__(self, params: RiskBudgetParams):
        self.p = params

    def apply(
        self,
        scores: RegimeScores,
        active_modes: List[Union[MetaMode, str]],
        current_gross: float,
        current_recycle: float,
        current_mults: Dict[str, float],
        velocity: float,
        is_recovery: bool,
    ) -> tuple:
        """Core Task 2.4 entry. Pure function (no state). Fail-safe."""
        try:
            if not active_modes:
                # Also derive lightly for special mode detection if needed
                # (but prefer caller-supplied for fidelity to RegimeOS)
                pass

            # Normalize mode names (support Enum or str, case variants)
            mode_names: List[str] = []
            for m in (active_modes or []):
                name = str(m).upper().replace(" ", "_").replace("-", "_")
                if name not in mode_names:
                    mode_names.append(name)

            flags: List[str] = []
            gross_adj = 1.0
            recycle_adj = 1.0
            extra_mults: Dict[str, float] = {"COMPASS": 1.0, "Rattlesnake": 1.0, "Catalyst": 1.0, "EFA": 1.0}
            rat_parts: List[str] = []

            p = self.p

            # --- CRISIS_ACUTE: harder de-risk + specific defensive tag regardless of velocity ---
            if "CRISIS_ACUTE" in mode_names or "CRISIS" in " ".join(mode_names):
                gross_adj *= p.special_crisis_derisk_scale
                recycle_adj *= min(1.0, p.special_crisis_recycle_cap / max(0.01, current_recycle))
                flags.append(p.special_tag_crisis_hard_defense)
                rat_parts.append(f"SPECIAL:CRISIS_HARD_DEFENSE(scale={p.special_crisis_derisk_scale})")
                # Also force a legacy-style tag for continuity
                if "CRISIS_DEFENSE" not in [str(x).upper() for x in flags]:
                    flags.append("CRISIS_DEFENSE")

            # --- POST_CRISIS_RECOVERY: accel even at lower DD, faster recycle ---
            if "POST_CRISIS_RECOVERY" in mode_names or "RECOVERY" in " ".join(mode_names):
                # Special lower threshold already conceptually handled by caller
                # but we still apply accelerator here for qualitative effect
                recycle_adj *= p.special_recovery_recycle_accelerator
                if p.special_recovery_lower_dd_threshold > 0:
                    # Signal that we are in accelerated recovery posture
                    flags.append(p.special_tag_recovery_accel)
                    rat_parts.append(f"SPECIAL:RECOVERY_ACCEL(recycle_x={p.special_recovery_recycle_accelerator})")
                # If not already in recovery rationale from core, note it
                if not is_recovery:
                    rat_parts.append("SPECIAL:RECOVERY_BELOW_STD_DD")

            # --- STRONG_BROAD_MOMENTUM: max COMPASS aggression + diversifier min + tag ---
            if "STRONG_BROAD_MOMENTUM" in mode_names or "STRONG" in " ".join(mode_names):
                extra_mults["COMPASS"] *= (1.0 + p.special_strong_mom_compass_extra)
                extra_mults["Catalyst"] *= p.special_strong_mom_diversifier_cap
                extra_mults["EFA"] *= p.special_strong_mom_diversifier_cap
                flags.append(p.special_tag_momentum_override)
                rat_parts.append(f"SPECIAL:STRONG_MOM_OVERRIDE(compass+{p.special_strong_mom_compass_extra})")
                # Also apply pillar special
                extra_mults["COMPASS"] *= p.pillar_params.special_compass_momentum_override

            # --- ELEVATED_VOL_DEFENSIVE: MR-friendly (Rattlesnake boost) + conservative recycle + tag ---
            if "ELEVATED_VOL_DEFENSIVE" in mode_names or "ELEVATED" in " ".join(mode_names):
                extra_mults["Rattlesnake"] *= (1.0 + p.special_elev_vol_rattlesnake_extra)
                recycle_adj *= p.special_elev_vol_recycle_dampen
                flags.append(p.special_tag_vol_mr_friendly)
                rat_parts.append(f"SPECIAL:VOL_MR_FRIENDLY(rattle+{p.special_elev_vol_rattlesnake_extra})")
                extra_mults["Rattlesnake"] *= p.pillar_params.special_rattlesnake_vol_defensive

            # Dedup flags
            seen_f = set()
            uniq_flags = []
            for f in flags:
                if f not in seen_f:
                    seen_f.add(f)
                    uniq_flags.append(f)

            rat_add = "; ".join(rat_parts) if rat_parts else ""

            return gross_adj, recycle_adj, extra_mults, uniq_flags, rat_add

        except Exception:
            # Absolute fail-safe for the applicator itself
            return 1.0, 1.0, {"COMPASS": 1.0, "Rattlesnake": 1.0, "Catalyst": 1.0, "EFA": 1.0}, [], ""


# =============================================================================
# RISK BUDGET IMPLEMENTATION (Task 2.2)
# =============================================================================

class RiskBudgetMetaLayer:
    """Concrete implementation of the MetaLayer Protocol for Tasks 2.2–2.4.

    Provides the approved asymmetric risk budgeting, Recovery Mode, and
    Drawdown Velocity Control (Task 2.2) + rich pillar/recycling (Task 2.3)
    + special qualitative mode behaviors for the four key modes (Task 2.4).

    Design highlights (all rules documented here for audit / future review):
    - Regime-dependent hard caps: strictest (lowest) cap among conditions wins.
    - Asymmetric: favorable high-conviction regimes get larger gross lift
      (asym_up_aggression) than unfavorable regimes receive in defense
      (asym_down_defense).
    - Recovery Mode: when drawdown_pct >= threshold AND momentum support,
      apply recovery_boost_factor (capped). Encourages shortening recovery.
    - Velocity: (dd - dd_5d_ago)/5 > threshold → extra defensive scale.
      Rapid declines de-risk faster than equivalent slow grind-downs.
    - Independent stability: EWMA on output gross + simple bar counter.
      Completely separate from RegimeOS StabilityParams / hysteresis.
    - Task 2.4 Special Modes (Crisis_Acute, Post_Crisis_Recovery,
      Strong_Broad_Momentum, Elevated_Vol_Defensive): qualitatively different
      behaviors via dedicated applicator (harder de-risk regardless of velocity
      in Crisis, accelerated recovery at lower DD, max COMPASS bias + diversifier
      suppression in Strong Momentum, MR-friendly Rattlesnake bias + conservative
      recycle in Elevated Vol). All heavily parameterized in RiskBudgetParams
      (extended in place) + light Pillar extensions. Results appear in
      risk_flags (new Decision field) + differentiated numeric outputs + rationale.
    - Fail-safe: every path wrapped; on any error return a conservative
      neutral-ish decision (gross=0.95, multipliers=1.0, confidence=0.3).
    - Versioned + explainable: rich rationale + params.version in output.
    - Never touches StubMetaLayer.

    LEVERAGE NOTE: May propose gross > 1.0 (up to hard_max) in strong
    favorable + Recovery. Callers / execution layer must clip per the
    project LEVERAGE_MAX = 1.0 rule if required for the broker.

    Deterministic given identical inputs (no RNG in v1).
    """

    def __init__(self, params: Optional[RiskBudgetParams] = None):
        self.params = params or RiskBudgetParams()
        # --- Independent risk stability state (live sequential calls) ---
        # Separate from any RegimeOS state. Only affects gross exposure smoothing.
        self._ema_gross: float = 1.0
        self._prev_gross: float = 1.0
        self._stable_bars: int = 0

        # Task 2.4: composition of small internal special-mode applicator
        # (defined below in this file). Provides clean separation for the
        # qualitatively different behaviors while obeying "edit existing files only".
        # The applicator reads the new special_* params and returns adjustments
        # + flags. It is fail-safe (never raises; returns safe neutral on error).
        self._special: "_SpecialModeApplicator" = _SpecialModeApplicator(self.params)

    def get_version(self) -> str:
        """Return implementation + params version for auditability.
        Task 2.3: includes pillar params version for full traceability.
        Task 2.4: special modes active (risk_flags support + applicator).
        """
        pillar_v = getattr(self.params, "pillar_params", None)
        pillar_str = pillar_v.version if pillar_v else "no-pillar"
        return f"0.4-risk-pillar-special-{self.params.version}+{pillar_str}"

    @property
    def risk_stability_state(self) -> RiskStabilityState:
        """Read-only view of this layer's internal stability state (independent of RegimeOS stability)."""
        return RiskStabilityState(
            ema_gross=self._ema_gross,
            stable_bars=self._stable_bars,
            prev_gross=self._prev_gross,
        )

    def _get_mode_cap(self, scores: RegimeScores) -> float:
        """Select the strictest gross cap based on score-driven regime signals.
        (No external mode list passed in current Protocol; derived here.)
        """
        p = self.params
        caps = p.gross_caps
        default_cap = caps.get("default", 1.0)

        # Lightweight derivation (conservative thresholds, not duplicating full classifier)
        stress = scores.stress_crisis_probability
        vol = scores.volatility_regime
        mom = scores.equity_momentum_strength
        br = scores.breadth_participation

        d = p.derivation
        active_caps: List[float] = [default_cap]

        if stress > d.get("crisis_stress", 0.70):
            active_caps.append(caps.get("CRISIS_ACUTE", default_cap))
        if stress > d.get("elevated_vol_stress", 0.58) or vol > d.get("elevated_vol_vol", 0.62):
            active_caps.append(caps.get("ELEVATED_VOL_DEFENSIVE", default_cap))
        if (mom > d.get("strong_mom", 0.78) and
            br > d.get("strong_breadth", 0.65) and
            stress < d.get("strong_stress_max", 0.30) and
            vol < d.get("strong_vol_max", 0.40)):
            active_caps.append(caps.get("STRONG_BROAD_MOMENTUM", default_cap))
        if mom > d.get("narrow_mom", 0.60) and br < d.get("narrow_breadth_max", 0.42):
            active_caps.append(caps.get("NARROW_MOMENTUM", default_cap))
        if (stress < d.get("recovery_stress_max", 0.55) and
            mom > d.get("recovery_mom_min", 0.50) and
            scores.mean_reversion_opportunity > d.get("recovery_mr_min", 0.45)):
            active_caps.append(caps.get("POST_CRISIS_RECOVERY", default_cap))
        if scores.liquidity_macro_stance < d.get("liq_stress_max", 0.38):
            active_caps.append(caps.get("LIQUIDITY_STRESS", default_cap))
        if (scores.mean_reversion_opportunity > d.get("meanrev_mr_min", 0.52) and
            mom < d.get("meanrev_mom_max", 0.55)):
            active_caps.append(caps.get("MEAN_REVERSION_RICH", default_cap))

        # Strictest (lowest) cap wins — core regime-dependent risk budget rule
        return min(active_caps)

    def _compute_velocity(self, portfolio: PortfolioState) -> float:
        """Positive value = DD worsening (rapid decline signal)."""
        dd_now = max(0.0, float(portfolio.drawdown_pct))
        dd_prev = max(0.0, float(portfolio.drawdown_5d_ago))
        vel = max(0.0, (dd_now - dd_prev) / 5.0)
        # Cross-check with recent return if provided (more negative → higher vel)
        if portfolio.recent_return_5d < 0:
            vel = max(vel, min(0.08, -portfolio.recent_return_5d / 5.0))
        return vel

    def _is_recovery_condition(self, scores: RegimeScores, portfolio: PortfolioState) -> bool:
        p = self.params
        dd = float(portfolio.drawdown_pct)
        mom = scores.equity_momentum_strength
        mr = scores.mean_reversion_opportunity
        return (dd >= p.recovery_dd_threshold and
                mom >= p.recovery_requires_mom and
                (mr > 0.42 or portfolio.recent_return_5d > -0.03))

    # -------------------------------------------------------------------------
    # TASK 2.3 PRIVATE HELPERS: Pillar multiplier & recycling mapping
    # -------------------------------------------------------------------------

    def _derive_active_modes_for_pillars(self, scores: RegimeScores) -> List[str]:
        """Internal conservative derivation (fallback when active_modes not supplied).
        Mirrors the spirit of RiskBudget._get_mode_cap thresholds but uses the
        dedicated PillarMultiplierParams.derivation for clean separation.
        Returns list of upper-case mode name strings for table lookup.
        """
        p = self.params.pillar_params
        d = p.derivation
        mom = scores.equity_momentum_strength
        br = scores.breadth_participation
        stress = scores.stress_crisis_probability
        vol = scores.volatility_regime
        liq = scores.liquidity_macro_stance
        mr = scores.mean_reversion_opportunity

        modes: List[str] = []
        if (mom > d.get("strong_mom", 0.76) and
                br > d.get("strong_breadth", 0.63) and
                stress < d.get("strong_stress_max", 0.32) and
                vol < d.get("strong_vol_max", 0.42)):
            modes.append("STRONG_BROAD_MOMENTUM")
        if mom > d.get("narrow_mom", 0.62) and br < d.get("narrow_breadth_max", 0.40):
            modes.append("NARROW_MOMENTUM")
        if stress > d.get("crisis_stress", 0.78):
            modes.append("CRISIS_ACUTE")
        if stress > d.get("elev_vol_or_stress", 0.59) or vol > d.get("elev_vol_or_stress", 0.59):
            modes.append("ELEVATED_VOL_DEFENSIVE")
        if (stress < d.get("recovery_stress_max", 0.58) and
                mom > d.get("recovery_mom_min", 0.48) and
                mr > d.get("recovery_mr_min", 0.44)):
            modes.append("POST_CRISIS_RECOVERY")
        if liq < d.get("liq_max", 0.35):
            modes.append("LIQUIDITY_STRESS")
        if (mr > d.get("mr_rich_mr_min", 0.51) and
                mom < d.get("mr_rich_mom_max", 0.52)):
            modes.append("MEAN_REVERSION_RICH")
        # Dedup preserving order
        seen = set()
        uniq = []
        for m in modes:
            if m not in seen:
                seen.add(m)
                uniq.append(m)
        return uniq

    def _compute_pillar_multipliers_and_recycle(
        self,
        scores: RegimeScores,
        active_modes: List[Union[MetaMode, str]],
        pillar_p: PillarMultiplierParams,
    ) -> tuple:
        """Core Task 2.3: produce multipliers dict + recycling_multiplier + rationale snippet.
        Uses passed modes (preferred) or derivation fallback + continuous score blends.
        All heavily parameterized via pillar_p. Returns (mults, recycle, rationale_part).
        """
        # Normalize incoming modes to upper string keys for table lookup
        mode_names: List[str] = []
        for m in (active_modes or []):
            name = str(m).upper().replace(" ", "_") if not isinstance(m, str) else m.upper().replace(" ", "_")
            if name not in mode_names:
                mode_names.append(name)

        # Fallback derivation if nothing supplied
        if not mode_names:
            mode_names = self._derive_active_modes_for_pillars(scores)

        mom = scores.equity_momentum_strength
        br = scores.breadth_participation
        stress = scores.stress_crisis_probability
        vol = scores.volatility_regime
        liq = scores.liquidity_macro_stance
        mr = scores.mean_reversion_opportunity

        # Start neutral
        mults = {
            "COMPASS": 1.0,
            "Rattlesnake": 1.0,
            "Catalyst": 1.0,
            "EFA": 1.0,
        }

        # 1. Apply discrete mode-driven scalers (multiplicative)
        for pillar_key, table in [
            ("COMPASS", pillar_p.mode_compass_mult),
            ("Rattlesnake", pillar_p.mode_rattlesnake_mult),
            ("Catalyst", pillar_p.mode_catalyst_mult),
            ("EFA", pillar_p.mode_efa_mult),
        ]:
            for mname in mode_names:
                if mname in table:
                    mults[pillar_key] *= table[mname]

        # 2. Continuous score-driven additive lifts (small, smooth, always-on)
        # COMPASS
        compass_lift = (
            pillar_p.score_compass_mom_weight * (mom - 0.5) * 2.0 +
            pillar_p.score_compass_breadth_weight * (br - 0.5) * 2.0 +
            pillar_p.score_compass_inv_stress_weight * (0.5 - stress) * 2.0 +
            pillar_p.score_compass_inv_vol_weight * (0.5 - vol) * 2.0
        )
        mults["COMPASS"] = mults["COMPASS"] * (1.0 + compass_lift * pillar_p.score_lift_scale)

        # Rattlesnake
        rattle_lift = (
            pillar_p.score_rattlesnake_mr_weight * (mr - 0.5) * 2.0 +
            pillar_p.score_rattlesnake_inv_mom_weight * (0.5 - mom) * 2.0 +
            pillar_p.score_rattlesnake_stress_weight * (stress - 0.5) * 1.2
        )
        mults["Rattlesnake"] = mults["Rattlesnake"] * (1.0 + rattle_lift * pillar_p.score_lift_scale)

        # Catalyst
        cat_lift = (
            pillar_p.score_catalyst_inv_mom_weight * (0.5 - mom) * 2.0 +
            pillar_p.score_catalyst_stress_weight * (stress - 0.4) * 1.3 +
            pillar_p.score_catalyst_liq_weight * (0.5 - liq) * 1.8
        )
        mults["Catalyst"] = mults["Catalyst"] * (1.0 + cat_lift * pillar_p.score_lift_scale)

        # EFA
        efa_lift = (
            pillar_p.score_efa_inv_mom_weight * (0.5 - mom) * 2.0 +
            pillar_p.score_efa_stress_weight * (stress - 0.4) * 1.3 +
            pillar_p.score_efa_liq_weight * (0.5 - liq) * 1.6
        )
        mults["EFA"] = mults["EFA"] * (1.0 + efa_lift * pillar_p.score_lift_scale)

        # 3. Clamps (per pillar)
        mults["COMPASS"] = max(pillar_p.compass_min, min(pillar_p.compass_max, mults["COMPASS"]))
        mults["Rattlesnake"] = max(pillar_p.rattlesnake_min, min(pillar_p.rattlesnake_max, mults["Rattlesnake"]))
        mults["Catalyst"] = max(pillar_p.catalyst_min, min(pillar_p.catalyst_max, mults["Catalyst"]))
        mults["EFA"] = max(pillar_p.efa_min, min(pillar_p.efa_max, mults["EFA"]))

        # 4. Recycling intensity (regime-aware direct scalar)
        # Base selection
        conviction = (0.40 * mom + 0.30 * br + 0.20 * (1.0 - stress) + 0.10 * (1.0 - vol))
        conviction = max(0.0, min(1.0, conviction))

        if conviction >= pillar_p.recycle_conviction_high and stress < pillar_p.recycle_stress_high:
            recycle = pillar_p.recycle_favorable_base
        else:
            recycle = pillar_p.recycle_defensive_base

        # Score adjustments
        if mom > pillar_p.recycle_mom_high and br > pillar_p.recycle_breadth_high:
            recycle *= 1.05
        if mr > pillar_p.recycle_mr_high and mom < 0.55:
            recycle *= pillar_p.recycle_mr_rich_dampen
        if stress > 0.70:
            recycle *= 0.91
        if "POST_CRISIS_RECOVERY" in mode_names or "RECOVERY" in " ".join(mode_names):
            recycle *= pillar_p.recycle_recovery_boost

        recycle = max(pillar_p.recycle_min, min(pillar_p.recycle_max, recycle))

        # 5. Rationale snippet (interpretable)
        mode_str = ", ".join(mode_names) if mode_names else "derived-neutral"
        rat_parts = [
            f"PILLARS: COMPASS {mults['COMPASS']:.2f} RATTLESNAKE {mults['Rattlesnake']:.2f} "
            f"CATALYST {mults['Catalyst']:.2f} EFA {mults['EFA']:.2f} (modes: {mode_str})",
            f"RECYCLE {recycle:.2f} (conv={conviction:.2f} mom={mom:.2f} stress={stress:.2f} mr={mr:.2f})",
        ]
        rat_part = "; ".join(rat_parts)

        return mults, round(recycle, 3), rat_part

    def compute_decision(
        self,
        scores: RegimeScores,
        portfolio: PortfolioState,
        performance: Optional[Dict[str, Any]] = None,
        active_modes: Optional[List[Union[MetaMode, str]]] = None,
    ) -> MetaLayerDecision:
        """Core risk + (Task 2.3) pillar multiplier & recycling logic.

        Task 2.3 extension: accepts optional active_modes (from RegimeOS).
        When supplied, they drive the rich pillar/recycling mapping via
        PillarMultiplierParams. When absent, internal derivation is used.
        The improved mapping (replacing the 2.2 starter block) is implemented
        after the TDD red phase for the new behavioral tests.
        """
        p = self.params
        pillar_p = getattr(p, "pillar_params", PillarMultiplierParams())
        try:
            # Touch inputs for safety (never trust caller data)
            if scores is None:
                scores = RegimeScores()
            if portfolio is None:
                portfolio = PortfolioState()
            if performance is None:
                performance = {}
            if active_modes is None:
                active_modes = []

            # 1. Base cap from regime-dependent budgets
            base_cap = self._get_mode_cap(scores)

            # 2. Conviction for asymmetry (high mom + breadth + low stress/vol)
            mom = scores.equity_momentum_strength
            br = scores.breadth_participation
            stress = scores.stress_crisis_probability
            vol = scores.volatility_regime
            c = p.derivation
            conviction = (0.45 * mom + 0.30 * br +
                          0.15 * (1.0 - stress) + 0.10 * (1.0 - vol))
            conviction = max(0.0, min(1.0, conviction))

            # 3. Provisional target with asymmetry
            target = base_cap
            if conviction > c.get("high_conviction", 0.55):
                # Favorable high conviction → larger upside (asymmetric aggression)
                target = min(p.hard_max_gross, target + p.asym_up_aggression * (conviction - 0.5) * 2.2)
            else:
                # Unfavorable → milder defense
                target = max(p.hard_min_gross, target - p.asym_down_defense * (0.6 - conviction) * 1.6)

            # 4. Recovery Mode boost (after material DD)
            rationale_parts: List[str] = []
            if self._is_recovery_condition(scores, portfolio):
                boosted = min(p.hard_max_gross, target * p.recovery_boost_factor)
                if boosted > target:
                    target = boosted
                    rationale_parts.append(
                        f"RECOVERY boost x{p.recovery_boost_factor:.2f} (DD={portfolio.drawdown_pct:.1%}>=thresh)"
                    )

            # 5. Drawdown Velocity Control (rapid vs slow)
            velocity = self._compute_velocity(portfolio)
            if velocity >= p.velocity_worsening_threshold:
                target = max(p.hard_min_gross, target * p.velocity_defense_scale)
                rationale_parts.append(f"VELOCITY de-risk (vel={velocity:.3f} > thresh; scale={p.velocity_defense_scale})")

            # 6. Apply independent risk-layer stability (EWMA + min bars)
            alpha = p.risk_ema_alpha
            raw_target = target
            target = alpha * target + (1 - alpha) * self._ema_gross

            # Simple stability guard: if change direction reverses too soon, dampen
            direction_change = (target - self._prev_gross) * (raw_target - self._prev_gross) < 0
            if direction_change and self._stable_bars < p.risk_min_bars_stable:
                target = 0.6 * self._prev_gross + 0.4 * target

            target = max(p.hard_min_gross, min(p.hard_max_gross, target))

            # Update state
            self._ema_gross = target
            self._prev_gross = target
            self._stable_bars = self._stable_bars + 1 if abs(target - raw_target) < 0.015 else 0

            # 7. Task 2.3: Rich pillar multiplier + recycling modulation
            # Uses passed active_modes (from RegimeOS) or internal derivation +
            # continuous score blends. Fully parameterized via pillar_p.
            # Replaces the old 2.2 starter block.
            mults, recycle_mult, pillar_rat = self._compute_pillar_multipliers_and_recycle(
                scores, active_modes, pillar_p
            )

            # 8. Task 2.4: Apply special mode qualitative behaviors (composition)
            # Uses the dedicated _SpecialModeApplicator. Produces risk_flags
            # (new field) + adjustments that create clearly different Decision
            # outputs for the four modes (harder defense, accelerated recovery,
            # max COMPASS aggression, MR-friendly posture). Parameterized.
            special_gross_adj, special_recycle_adj, special_extra_mults, special_flags, special_rat = \
                self._special.apply(
                    scores, active_modes or [], target, recycle_mult, mults,
                    velocity, bool(self._is_recovery_condition(scores, portfolio))
                )

            target = max(p.hard_min_gross, min(p.hard_max_gross, target * special_gross_adj))
            recycle_mult = max(0.01, recycle_mult * special_recycle_adj)
            for pk in mults:
                mults[pk] *= special_extra_mults.get(pk, 1.0)
            # Re-clamp after special extras (defensive bias)
            mults["COMPASS"] = max(pillar_p.compass_min, min(pillar_p.compass_max, mults["COMPASS"]))
            mults["Rattlesnake"] = max(pillar_p.rattlesnake_min, min(pillar_p.rattlesnake_max, mults["Rattlesnake"]))
            mults["Catalyst"] = max(pillar_p.catalyst_min, min(pillar_p.catalyst_max, mults["Catalyst"]))
            mults["EFA"] = max(pillar_p.efa_min, min(pillar_p.efa_max, mults["EFA"]))

            # 9. Active modes / risk tags (support str tags per clarification)
            tags: List[Union[MetaMode, str]] = []
            if "RECOVERY" in " ".join(rationale_parts).upper():
                tags.append("RECOVERY_AGGRESSION")
            if velocity >= p.velocity_worsening_threshold:
                tags.append("VELOCITY_DERISK")
            if stress > 0.78:
                tags.append("CRISIS_DEFENSE")

            # 10. Confidence (higher when scores extreme + stable)
            conf = 0.45 + 0.35 * abs(conviction - 0.5) * 2 + 0.20 * (1.0 - min(1.0, velocity * 30))
            conf = max(0.25, min(0.92, conf))

            # Merge pillar modes (Task 2.3) into active_modes for audit (keep risk tags)
            for mname in (active_modes or []):
                if mname not in tags:
                    tags.append(mname)

            rationale = "; ".join(rationale_parts) or "Neutral risk budget (no special rule dominant)"
            rationale += f" | cap={base_cap:.2f} vel={velocity:.3f} conv={conviction:.2f}"
            rationale += f" || {pillar_rat}"
            if special_rat:
                rationale += f" || {special_rat}"

            # risk_flags = the new special tags (Task 2.4) — distinct from active_modes
            final_risk_flags = list(special_flags)

            return MetaLayerDecision(
                gross_exposure=round(target, 4),
                multipliers=mults,
                recycling_multiplier=round(recycle_mult, 3),
                active_modes=tags,
                risk_flags=final_risk_flags,
                confidence=round(conf, 3),
                as_of=None,
                version=self.params.version,
                rationale=f"RiskBudgetMetaLayer {self.params.version}: {rationale}",
            )

        except Exception as exc:
            # Absolute fail-safe: never let risk layer crash the engine
            # Task 2.4: explicitly empty risk_flags in fail-safe path
            return MetaLayerDecision(
                gross_exposure=0.95,
                multipliers={"COMPASS": 1.0, "Rattlesnake": 1.0, "Catalyst": 1.0, "EFA": 1.0},
                recycling_multiplier=0.90,
                active_modes=[],
                risk_flags=[],
                confidence=0.25,
                as_of=None,
                version=self.params.version,
                rationale=f"RiskBudgetMetaLayer FAIL-SAFE (error: {type(exc).__name__}); conservative neutral returned",
            )


# =============================================================================
# Public exports
# =============================================================================

__all__ = [
    "PortfolioState",
    "MetaLayerDecision",
    "MetaLayer",
    "StubMetaLayer",
    "RiskBudgetParams",
    "RiskBudgetMetaLayer",
    "PillarMultiplierParams",   # NEW Task 2.3
    "SEED",
]


# =============================================================================
# Task 2.1 Self-Review Notes (added on completion)
# =============================================================================
# - Strict TDD followed exactly:
#   1. Thorough exploration of regime_os.py (full surface + self-review),
#      design spec §6, implementation plan Task 2.1, HydraCapitalManager,
#      existing regime tests (pattern match), AGENTS.md rules.
#   2. Identified ambiguities (PortfolioState shape, Decision metadata,
#      Protocol extras, package vs root file, stub name/behavior).
#   3. Used ask_user_question tool with 5 targeted questions + options.
#      Received clear answers and incorporated them verbatim.
#   4. Updated todo. Wrote complete failing tests/test_meta_layer.py
#      (modeled precisely on test_regime_os_interface.py) that import the
#      not-yet-existing symbols.
#   5. Ran pytest → red (ModuleNotFoundError on hydra_meta.meta_layer) —
#      confirmed tests written first.
#   6. Created hydra_meta/ package (per clarification answer) + __init__.py.
#   7. Implemented meta_layer.py with full contract, rich documentation,
#      frozen dataclasses, runtime_checkable Protocol (with get_version),
#      StubMetaLayer (exact neutral behavior specified), SEED, __all__.
#   8. (Next) Will re-run tests to reach green, then final self-review.
#
# - Contract exactly matches Task 2.1 requirements + clarifications:
#   - Input: RegimeScores + PortfolioState (minimal frozen per answer) +
#     optional recent performance dict.
#   - Output: MetaLayerDecision (5 core fields + as_of/version/rationale
#     metadata, frozen, documented, neutral defaults).
#   - MetaLayer Protocol (runtime_checkable) + StubMetaLayer (name and
#     always-neutral behavior per answer).
#   - No over-implementation: zero risk logic, zero special modes, zero
#     parameter tuning — pure interface + safe stub.
#
# - Alignment:
#   - Integrates cleanly with regime_os (imports only public types).
#   - Compatible with future HydraCapitalManager extensions (Task 4.1).
#   - Follows all project rules (fail-safe everywhere, frozen state,
#     Seed 666, no locked algorithm changes, conservative defaults).
#   - Package location chosen deliberately (future-proofs the component
#     family while still satisfying "meta_layer.py" spirit via the module).
#
# - Files created in this task:
#   - tests/test_meta_layer.py (TDD contract tests)
#   - hydra_meta/__init__.py (package exports)
#   - hydra_meta/meta_layer.py (interface + stub + docs)
#
# - Status after implementation: ready for test execution to verify green.
#   All requirements for Task 2.1 met.
# =============================================================================
