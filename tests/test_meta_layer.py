"""tests/test_meta_layer.py

TDD tests for the Meta-Layer Decision Engine Interface (Task 2.1 / Phase 2).

These tests were written *before* any implementation of hydra_meta/meta_layer.py,
per strict TDD discipline and the approved implementation plan.

They codify the exact public contract (dataclasses + Protocol) that
the minimal StubMetaLayer (and all future implementations) must satisfy.

References:
- docs/superpowers/specs/2026-06-05-hydra-meta-layer-v1-design.md (Section 6)
- docs/superpowers/plans/2026-06-05-hydra-meta-layer-v1-implementation.md (Task 2.1)
- regime_os.py (RegimeScores, MetaMode, Protocol patterns)
- AGENTS.md / Claude.md (fail-safe, Seed 666, HydraCapitalManager compatibility,
  no modification of locked COMPASS v8.4, conservative defaults)

All tests are pure unit (no external data, network, live engine, or HydraCapitalManager
instances — only the public surface of the new module).

The interface is intentionally minimal for Task 2.1 (contract only).
Real decision logic, risk budgeting, and mode-specific behavior land in Tasks 2.2+.
"""

import pytest
from datetime import date
from dataclasses import FrozenInstanceError
from typing import Any, Dict, Optional

# These imports MUST fail until hydra_meta/meta_layer.py exists and exports the symbols.
# (Strict TDD — red phase expected on first run.)
from hydra_meta.meta_layer import (
    PortfolioState,
    MetaLayerDecision,
    MetaLayer,
    StubMetaLayer,
)
from regime_os import RegimeScores, MetaMode


# =============================================================================
# PORTFOLIO STATE DATACLASS CONTRACT (input to Meta-Layer)
# =============================================================================

class TestPortfolioStateDataclass:
    """Verify the frozen dataclass shape for current portfolio snapshot input."""

    def test_is_frozen_dataclass_with_reasonable_defaults(self):
        """Defaults represent a plausible neutral starting portfolio."""
        state = PortfolioState()
        assert isinstance(state, PortfolioState)
        assert isinstance(state.total_equity, float)
        assert isinstance(state.cash, float)
        assert isinstance(state.pillar_allocations, dict)
        assert isinstance(state.current_gross_exposure, float)
        assert isinstance(state.drawdown_pct, float)

        # Neutral-ish defaults (reasonable for tests/stub)
        assert state.total_equity > 0
        assert state.cash >= 0
        assert "COMPASS" in state.pillar_allocations
        assert "Rattlesnake" in state.pillar_allocations
        assert "Catalyst" in state.pillar_allocations
        assert "EFA" in state.pillar_allocations
        assert 0.0 <= state.current_gross_exposure <= 2.0
        assert 0.0 <= state.drawdown_pct <= 1.0

    def test_explicit_construction(self):
        """Accepts explicit values; callers (later live engine) can populate from HydraCapitalManager."""
        allocations = {"COMPASS": 42500.0, "Rattlesnake": 30000.0, "Catalyst": 15000.0, "EFA": 0.0}
        state = PortfolioState(
            total_equity=100000.0,
            cash=12500.0,
            pillar_allocations=allocations,
            current_gross_exposure=0.85,
            drawdown_pct=0.12,
        )
        assert state.total_equity == pytest.approx(100000.0)
        assert state.cash == pytest.approx(12500.0)
        assert state.pillar_allocations["COMPASS"] == pytest.approx(42500.0)
        assert state.current_gross_exposure == pytest.approx(0.85)
        assert state.drawdown_pct == pytest.approx(0.12)

    def test_frozen_immutable(self):
        """PortfolioState must be immutable (frozen=True) for safety in decision pipelines."""
        state = PortfolioState()
        with pytest.raises(FrozenInstanceError):
            state.total_equity = 999999.0  # type: ignore[attr-defined]

    def test_pillar_allocations_keys_are_standard(self):
        """The four pillars match project naming (COMPASS + Rattlesnake + Catalyst + EFA)."""
        state = PortfolioState()
        keys = set(state.pillar_allocations.keys())
        assert keys == {"COMPASS", "Rattlesnake", "Catalyst", "EFA"}


# =============================================================================
# META LAYER DECISION DATACLASS CONTRACT (output)
# =============================================================================

class TestMetaLayerDecisionDataclass:
    """Verify the frozen, well-documented output contract for Task 2.1."""

    def test_is_frozen_dataclass_with_neutral_defaults(self):
        """Neutral / conservative defaults for the stub (safe starting point)."""
        decision = MetaLayerDecision()
        assert isinstance(decision, MetaLayerDecision)
        assert decision.gross_exposure == pytest.approx(1.0)
        assert isinstance(decision.multipliers, dict)
        assert decision.recycling_multiplier == pytest.approx(1.0)
        assert isinstance(decision.active_modes, list)
        assert decision.confidence == pytest.approx(0.5)
        # Metadata for future-proofing (per clarification)
        assert decision.version == "1.0"
        assert decision.as_of is None or isinstance(decision.as_of, date)
        assert decision.rationale is None or isinstance(decision.rationale, str)

    def test_explicit_construction_and_pillar_keys(self):
        """Supports explicit conservative or aggressive decisions; multipliers cover all pillars."""
        decision = MetaLayerDecision(
            gross_exposure=0.75,
            multipliers={"COMPASS": 0.9, "Rattlesnake": 1.1, "Catalyst": 0.5, "EFA": 0.8},
            recycling_multiplier=0.6,
            active_modes=[MetaMode.CRISIS_ACUTE],
            confidence=0.85,
            as_of=date(2026, 5, 30),
            version="1.0",
            rationale="High stress detected; defensive posture",
        )
        assert decision.gross_exposure == pytest.approx(0.75)
        assert decision.multipliers["Catalyst"] == pytest.approx(0.5)
        assert len(decision.active_modes) == 1
        assert decision.active_modes[0] == MetaMode.CRISIS_ACUTE
        assert decision.confidence == pytest.approx(0.85)
        assert decision.as_of == date(2026, 5, 30)
        assert "defensive" in (decision.rationale or "").lower()

    def test_frozen_immutable(self):
        """MetaLayerDecision must be immutable."""
        decision = MetaLayerDecision()
        with pytest.raises(FrozenInstanceError):
            decision.gross_exposure = 1.4  # type: ignore[attr-defined]

    def test_multipliers_dict_contract(self):
        """Multipliers must be a dict with exactly the four expected pillar keys (extensible later)."""
        decision = MetaLayerDecision(
            multipliers={"COMPASS": 1.0, "Rattlesnake": 1.0, "Catalyst": 1.0, "EFA": 1.0}
        )
        assert set(decision.multipliers.keys()) == {"COMPASS", "Rattlesnake", "Catalyst", "EFA"}
        for v in decision.multipliers.values():
            assert isinstance(v, (int, float))

    def test_active_modes_are_meta_modes(self):
        """active_modes must contain only MetaMode members (or be empty)."""
        decision = MetaLayerDecision(active_modes=[MetaMode.STRONG_BROAD_MOMENTUM, MetaMode.MEAN_REVERSION_RICH])
        assert all(isinstance(m, MetaMode) for m in decision.active_modes)


# =============================================================================
# META LAYER PROTOCOL CONTRACT
# =============================================================================

class TestMetaLayerProtocol:
    """Verify the Protocol (runtime_checkable) and structural contract."""

    def test_protocol_is_runtime_checkable(self):
        """@runtime_checkable allows clean isinstance checks (like RegimeOS)."""
        stub = StubMetaLayer()
        assert isinstance(stub, MetaLayer)

    def test_compute_decision_signature_and_return_types(self):
        """The primary required method per Task 2.1 contract."""
        stub = StubMetaLayer()
        scores = RegimeScores()
        portfolio = PortfolioState()
        decision = stub.compute_decision(scores, portfolio)
        assert isinstance(decision, MetaLayerDecision)
        assert isinstance(decision.multipliers, dict)

    def test_compute_decision_accepts_optional_performance(self):
        """Supports optional recent performance dict for future logic (Task 2.2+)."""
        stub = StubMetaLayer()
        perf = {"ret_5d": -0.03, "max_dd_20d": 0.08}
        decision = stub.compute_decision(
            RegimeScores(stress_crisis_probability=0.9),
            PortfolioState(drawdown_pct=0.15),
            performance=perf,
        )
        assert isinstance(decision, MetaLayerDecision)

    def test_protocol_has_version_method(self):
        """Second method on the Protocol for versioning / introspection (per clarification)."""
        stub = StubMetaLayer()
        version = stub.get_version()
        assert isinstance(version, str)
        assert len(version) > 0

    def test_non_implementing_object_does_not_satisfy_protocol(self):
        """Structural check works via runtime_checkable."""
        class NotAMetaLayer:
            pass
        assert not isinstance(NotAMetaLayer(), MetaLayer)


# =============================================================================
# STUB METALAYER MINIMAL BEHAVIOR (Task 2.1 — conservative neutral)
# =============================================================================

class TestStubMetaLayerMinimalBehavior:
    """Document the intentionally minimal neutral/conservative nature of the Task 2.1 stub.

    Per clarification: always returns the same safe neutral decision regardless of inputs.
    This is the safe default until real logic (Tasks 2.2–2.4).
    """

    def test_stub_returns_fixed_neutral_decision(self):
        """Stub ignores inputs and returns the documented conservative neutral."""
        stub = StubMetaLayer()
        scores = RegimeScores(
            equity_momentum_strength=0.95,
            stress_crisis_probability=0.05,
        )
        portfolio = PortfolioState(total_equity=120000.0, drawdown_pct=0.0)
        decision = stub.compute_decision(scores, portfolio)

        # Fixed neutral / conservative values (per clarification)
        assert decision.gross_exposure == pytest.approx(1.0)
        assert decision.recycling_multiplier == pytest.approx(1.0)
        assert decision.confidence == pytest.approx(0.5)
        assert decision.active_modes == []
        for pillar in ("COMPASS", "Rattlesnake", "Catalyst", "EFA"):
            assert decision.multipliers[pillar] == pytest.approx(1.0)
        assert decision.version == "1.0"

    def test_stub_is_deterministic_and_fail_safe(self):
        """Multiple calls (even with bad inputs) produce identical safe output."""
        stub = StubMetaLayer()
        d1 = stub.compute_decision(RegimeScores(), PortfolioState())
        d2 = stub.compute_decision(
            RegimeScores(volatility_regime=0.99, stress_crisis_probability=0.99),
            PortfolioState(drawdown_pct=0.45),
            performance={"ret_1d": -0.15},
        )
        assert d1.gross_exposure == d2.gross_exposure
        assert d1.multipliers == d2.multipliers
        assert d1.active_modes == d2.active_modes

    def test_stub_satisfies_protocol_and_has_version(self):
        """Stub is a valid MetaLayer and reports a version string."""
        stub = StubMetaLayer()
        assert isinstance(stub, MetaLayer)
        assert isinstance(stub.get_version(), str)

    def test_stub_never_raises_on_extreme_inputs(self):
        """Fail-safe principle (core project rule)."""
        stub = StubMetaLayer()
        # Extreme stress + high drawdown + weird performance
        try:
            _ = stub.compute_decision(
                RegimeScores(stress_crisis_probability=1.0, volatility_regime=1.0),
                PortfolioState(total_equity=50000.0, drawdown_pct=0.55),
                performance={"ret_5d": -0.5, "foo": "bar"},
            )
        except Exception as exc:
            pytest.fail(f"StubMetaLayer raised unexpectedly: {exc}")


if __name__ == "__main__":
    # Allow direct execution during development (matches regime test pattern)
    pytest.main([__file__, "-q", "--tb=line"])
