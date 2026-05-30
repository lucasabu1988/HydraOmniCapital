"""
regime_os.py — Regime OS Public Interface (HYDRA Meta-Layer v1, Phase 1)

This module defines the *clean public interface* for the future Regime
Operating System. It is intentionally logic-free (no score computation,
no feature engineering, no classifiers). Real implementations live in
later tasks (1.2+).

Location choice (root):
- Placed at repository root (alongside the predecessor `regime.py` and
  the majority of core engine modules).
- Justification (confirmed via clarification): (1) strictly minimal
  files for Task 1.1, (2) import consistency with existing regime code
  and test patterns, (3) no premature package/directory creation when
  only a single module exists in Phase 1 (meta_layer.py arrives in
  Phase 2 per plan), (4) trivial to promote into a `hydra_meta/`
  package later if the component count warrants it.
- Future modules (meta_layer.py, etc.) may adopt `hydra_meta/` when
  the structure justifies it.

Contract (per approved design & plan):
- `RegimeScores`: frozen dataclass with the six canonical continuous
  dimensions (inspired by design spec §5 and Phase 0
  research/regime_features/feature_definitions.md).
- `MetaMode`: str-based Enum of the discrete high-level behavioral
  regimes (examples from design spec).
- `RegimeOS`: typing.Protocol (runtime_checkable) exposing the single
  method the Meta-Layer and validation harnesses will call.

All implementations (stub, rule-based, ensemble, etc.) MUST:
- Be fail-safe (never crash callers; degrade gracefully).
- Return scores in [0.0, 1.0] range (documented per dimension).
- Prefer stability (avoid rapid mode flipping) — enforced in later tasks.
- Respect project rules: Seed 666 for any randomness, atomic state,
  no modifications to locked COMPASS v8.4.

References:
- docs/superpowers/specs/2026-06-05-hydra-meta-layer-v1-design.md
- docs/superpowers/plans/2026-06-05-hydra-meta-layer-v1-implementation.md
  (exact Task 1.1 steps)
- research/regime_features/feature_definitions.md (dimensions & features)
- regime.py (lightweight predecessor, May 2026)
- AGENTS.md / Claude.md

This interface is the source of truth for Task 1.1. It will be consumed
by the Meta-Layer (Phase 2) and the isolated validation harness (Task 1.4).
"""

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import List, Optional, Protocol, Tuple, runtime_checkable


@dataclass(frozen=True)
class RegimeScores:
    """Multi-dimensional continuous regime vector (output of Regime OS).

    All fields are normalized to [0.0, 1.0]:
      - 0.0 = weakest / least present / most defensive reading for the dimension
      - 1.0 = strongest / most present / most aggressive reading

    Semantics (see design spec §5 and feature_definitions.md for full
    motivation and candidate input features):

    - equity_momentum_strength: Persistence and magnitude of broad equity
      uptrend (SPY returns, distance from SMA200, etc.).
    - volatility_regime: Current volatility environment (realized vol,
      VIX level and z-score). High values = elevated fear / risk.
    - liquidity_macro_stance: Proxy for liquidity / monetary conditions
      (initially thin volume-based; will incorporate FRED series later).
    - breadth_participation: Health of rally participation (pct of names
      above moving averages, positive returns, etc.). Low = narrow / fragile.
    - stress_crisis_probability: Acute stress / crash probability signals
      (drawdown depth/velocity, short-term negative returns).
    - mean_reversion_opportunity: Environment richness for dip-buying /
      mean-reversion strategies (pct deep below MAs, etc.).

    The dataclass is frozen for safety (immutable regime snapshots).
    Additional fields (as_of, version, confidence, etc.) may be added in
    future versions with backward-compatible defaults.
    """

    equity_momentum_strength: float = 0.5
    volatility_regime: float = 0.5
    liquidity_macro_stance: float = 0.5
    breadth_participation: float = 0.5
    stress_crisis_probability: float = 0.5
    mean_reversion_opportunity: float = 0.5


class MetaMode(str, Enum):
    """Discrete high-level Meta-Modes produced by the Regime OS.

    A single market state can activate zero, one, or multiple (composite)
    modes. These modes (plus the continuous scores) drive Meta-Layer
    decisions: gross exposure targets, pillar multipliers, recycling
    intensity, and activation of special behavioral regimes.

    The initial vocabulary matches the examples in the design spec.
    New modes can be added safely; downstream code must handle unknown
    values gracefully (fail-safe principle).

    Values are human-readable strings for logging, state files, and UI.
    """

    STRONG_BROAD_MOMENTUM = "Strong_Broad_Momentum"
    NARROW_MOMENTUM = "Narrow_Momentum"
    ELEVATED_VOL_DEFENSIVE = "Elevated_Vol_Defensive"
    LIQUIDITY_STRESS = "Liquidity_Stress"
    CRISIS_ACUTE = "Crisis_Acute"
    POST_CRISIS_RECOVERY = "Post_Crisis_Recovery"
    MEAN_REVERSION_RICH = "Mean_Reversion_Rich"


@runtime_checkable
class RegimeOS(Protocol):
    """Public protocol for the HYDRA Regime Operating System.

    The Meta-Layer (Phase 2+), validation harnesses (Task 1.4), and any
    future ML components interact *only* through this interface.

    Implementations (stub for Task 1.1, pure rule-based for 1.2/1.3,
    ensemble later) must satisfy this Protocol structurally.

    Design constraints (non-negotiable):
    - Fail-safe: never raise on bad/missing inputs. Return conservative
      neutral scores + minimal defensive modes on error paths.
    - Stable: mode transitions should not chatter (hysteresis / filters
      implemented in concrete classes, not here).
    - Testable in isolation: no dependency on live broker, dashboards,
      or locked COMPASS logic.

    The single required method below is the example given in the
    implementation plan. Future phases may extend the Protocol with
    additional methods (e.g., feature vector export, confidence scores)
    while preserving backward compatibility for existing callers.
    """

    def compute_regime(
        self, as_of: Optional[date] = None
    ) -> Tuple[RegimeScores, List[MetaMode]]:
        """Compute the current regime assessment.

        Args:
            as_of: Optional reference date for historical / walk-forward
                   regime queries (used heavily in Task 1.4 validation
                   harness). Implementations may ignore for live daily use.

        Returns:
            (RegimeScores, list of active MetaMode)

            The list may be empty (no strong mode detected) or contain
            one or more modes. Order is not significant.

        Contract for all implementations:
            - Scores must have values in [0.0, 1.0].
            - Returned objects are safe to store in state JSON and logs.
            - Must be deterministic given the same inputs (modulo any
              documented controlled randomness with Seed 666).
        """
        ...  # Protocol stub


class StubRegimeOS:
    """Minimal concrete implementation satisfying the RegimeOS Protocol.

    This is the *only* code allowed in Task 1.1.3. It contains zero
    regime-detection logic, feature calculations, or rules.

    Purpose:
    - Allow the interface tests to pass immediately.
    - Provide a safe "no-op" object that can be wired (behind feature
      flag) into early integration points without side effects.
    - Serve as the baseline for the validation harness (Task 1.4) until
      real calculators land in Task 1.2.

    Behavior:
    - Always returns neutral scores (0.5 everywhere).
    - Always returns empty active modes list (most conservative default).

    Real implementations will replace or subclass this pattern.
    """

    def compute_regime(
        self, as_of: Optional[date] = None
    ) -> Tuple[RegimeScores, List[MetaMode]]:
        """Return the neutral conservative stub regime vector."""
        # Intentionally no logic, no use of as_of, no randomness.
        return (RegimeScores(), [])


# Public exports (explicit for clean `from regime_os import *` and docs)
__all__ = [
    "RegimeScores",
    "MetaMode",
    "RegimeOS",
    "StubRegimeOS",
]