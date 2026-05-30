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

References now also include Task 2.2 tests and clarifications.
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
    version: str = "risk-v1.1-asym-ddvel-rec-202606"
    """Semantic version of this parameter set. Bumped on any material change
    to thresholds, caps, or rule weights. Appears in MetaLayerDecision.version
    and get_version() for the producing implementation.
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
    base_recycle_mult_favorable: float = 1.12
    """Recycling intensity when conditions are strongly favorable."""
    base_recycle_mult_defensive: float = 0.78
    """Recycling intensity when conditions are defensive/stressful."""


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
    ) -> MetaLayerDecision:
        """Produce a high-level allocation and risk directive.

        Args:
            scores: The latest RegimeScores + active MetaModes from the
                    upstream Regime OS (Phase 1). Never None.
            portfolio: Current portfolio snapshot (see PortfolioState).
                       Callers must not pass mutated objects.
            performance: Optional recent performance metrics (e.g.
                         {"ret_5d": -0.02, "sharpe_20d": 0.8, ...}).
                         May be None or a partial dict. Implementations must
                         degrade gracefully.

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
    ) -> MetaLayerDecision:
        """Return the fixed neutral conservative decision (ignores inputs)."""
        # Intentionally no logic, no use of inputs, no randomness.
        # All paths lead to the same safe default.
        try:
            # Even on completely malformed inputs we still succeed.
            _ = scores  # touch to satisfy linters; value unused
            _ = portfolio
            _ = performance
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
            confidence=0.5,
            as_of=None,
            version="1.0",
            rationale="StubMetaLayer neutral default (Task 2.1 interface only; real decision logic in Tasks 2.2+)",
        )

    def get_version(self) -> str:
        """Return the stub version identifier."""
        return "0.1-stub"


# =============================================================================
# RISK BUDGET IMPLEMENTATION (Task 2.2)
# =============================================================================

class RiskBudgetMetaLayer:
    """Concrete implementation of the MetaLayer Protocol for Task 2.2.

    Provides the approved asymmetric risk budgeting, Recovery Mode, and
    Drawdown Velocity Control using the heavily parameterized RiskBudgetParams.

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

    def get_version(self) -> str:
        """Return implementation + params version for auditability."""
        return f"0.2-risk-{self.params.version}"

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

    def compute_decision(
        self,
        scores: RegimeScores,
        portfolio: PortfolioState,
        performance: Optional[Dict[str, Any]] = None,
    ) -> MetaLayerDecision:
        """Core Task 2.2 risk logic — fully parameterized and fail-safe."""
        p = self.params
        try:
            # Touch inputs for safety (never trust caller data)
            if scores is None:
                scores = RegimeScores()
            if portfolio is None:
                portfolio = PortfolioState()
            if performance is None:
                performance = {}

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

            # 7. Simple pillar/recycling modulation (starters for 2.3; conservative)
            recycle_mult = p.base_recycle_mult_favorable if conviction > 0.55 else p.base_recycle_mult_defensive
            mults = {
                "COMPASS": 1.0,
                "Rattlesnake": 1.05 if (scores.mean_reversion_opportunity > 0.55) else 0.95,
                "Catalyst": 0.85 if stress > 0.60 else 1.0,
                "EFA": 0.80 if stress > 0.55 else 1.0,
            }

            # 8. Active modes / risk tags (support str tags per clarification)
            tags: List[Union[MetaMode, str]] = []
            if "RECOVERY" in " ".join(rationale_parts).upper():
                tags.append("RECOVERY_AGGRESSION")
            if velocity >= p.velocity_worsening_threshold:
                tags.append("VELOCITY_DERISK")
            if stress > 0.78:
                tags.append("CRISIS_DEFENSE")

            # 9. Confidence (higher when scores extreme + stable)
            conf = 0.45 + 0.35 * abs(conviction - 0.5) * 2 + 0.20 * (1.0 - min(1.0, velocity * 30))
            conf = max(0.25, min(0.92, conf))

            rationale = "; ".join(rationale_parts) or "Neutral risk budget (no special rule dominant)"
            rationale += f" | cap={base_cap:.2f} vel={velocity:.3f} conv={conviction:.2f}"

            return MetaLayerDecision(
                gross_exposure=round(target, 4),
                multipliers=mults,
                recycling_multiplier=round(recycle_mult, 3),
                active_modes=tags,
                confidence=round(conf, 3),
                as_of=None,
                version=self.params.version,
                rationale=f"RiskBudgetMetaLayer {self.params.version}: {rationale}",
            )

        except Exception as exc:
            # Absolute fail-safe: never let risk layer crash the engine
            return MetaLayerDecision(
                gross_exposure=0.95,
                multipliers={"COMPASS": 1.0, "Rattlesnake": 1.0, "Catalyst": 1.0, "EFA": 1.0},
                recycling_multiplier=0.90,
                active_modes=[],
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
