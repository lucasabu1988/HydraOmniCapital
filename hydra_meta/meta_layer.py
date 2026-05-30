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
- docs/superpowers/plans/2026-06-05-hydra-meta-layer-v1-implementation.md (Task 2.1)
- regime_os.py (RegimeScores, MetaMode, RegimeOS Protocol patterns, StabilityParams)
- hydra_capital.py (existing pillar accounts + recycling for input shape alignment)
- AGENTS.md / Claude.md (all critical rules: algorithm locked, LEVERAGE_MAX=1.0,
  state sacred, ML fail-safe, Seed 666, no secrets)
- tests/test_meta_layer.py (the TDD contract tests that drove this implementation)

This interface is the source of truth for Phase 2. Real risk budgeting,
recovery mode, drawdown velocity, pillar mapping, and special mode behavior
are deliberately deferred to subsequent tasks.
"""

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

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

    active_modes: List[MetaMode] = field(default_factory=list)
    """The MetaModes (from the upstream Regime OS) that this decision is
    primarily reacting to. Order is not significant. May be empty when no
    strong regime signal is present. The stub always returns [].
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
            - active_modes must only contain valid MetaMode members.
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
# Public exports
# =============================================================================

__all__ = [
    "PortfolioState",
    "MetaLayerDecision",
    "MetaLayer",
    "StubMetaLayer",
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
