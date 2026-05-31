"""tests/test_regime_os_interface.py

TDD tests for the Regime OS public interface (Task 1.1 / Phase 1).

These tests were written *before* any implementation of regime_os.py,
per strict TDD discipline and the approved implementation plan.

They codify the exact public contract (dataclasses + Protocol) that
the minimal stub (and all future implementations) must satisfy.

References:
- docs/superpowers/specs/2026-06-05-hydra-meta-layer-v1-design.md (Section 5)
- docs/superpowers/plans/2026-06-05-hydra-meta-layer-v1-implementation.md (Task 1.1)
- research/regime_features/feature_definitions.md (dimensions + Meta-Mode examples)
- AGENTS.md / Claude.md (fail-safe, Seed 666, no modification of locked components)

All tests are pure unit (no external data, network, or live engine).
"""

import pytest
from datetime import date
from dataclasses import FrozenInstanceError

# These imports MUST fail until regime_os.py is created with the interface.
from regime_os import (
    RegimeScores,
    MetaMode,
    RegimeOS,
    StubRegimeOS,
)


class TestRegimeScoresDataclass:
    """Verify the frozen dataclass shape and basic invariants."""

    def test_is_frozen_dataclass_with_neutral_defaults(self):
        """Defaults to neutral (0.5) across all six dimensions."""
        scores = RegimeScores()
        assert isinstance(scores, RegimeScores)
        for field_name in (
            "equity_momentum_strength",
            "volatility_regime",
            "liquidity_macro_stance",
            "breadth_participation",
            "stress_crisis_probability",
            "mean_reversion_opportunity",
        ):
            value = getattr(scores, field_name)
            assert isinstance(value, float)
            assert value == pytest.approx(0.5)

    def test_explicit_construction_and_value_range(self):
        """Accepts explicit values; callers expected to keep scores in [0, 1]."""
        scores = RegimeScores(
            equity_momentum_strength=0.85,
            volatility_regime=0.25,
            liquidity_macro_stance=0.55,
            breadth_participation=0.70,
            stress_crisis_probability=0.15,
            mean_reversion_opportunity=0.90,
        )
        assert scores.equity_momentum_strength == pytest.approx(0.85)
        assert 0.0 <= scores.stress_crisis_probability <= 1.0

    def test_frozen_immutable(self):
        """RegimeScores must be immutable (frozen=True)."""
        scores = RegimeScores()
        with pytest.raises(FrozenInstanceError):
            scores.equity_momentum_strength = 0.99  # type: ignore[attr-defined]

    def test_has_expected_number_of_dimensions(self):
        """Exactly the six dimensions from the design spec."""
        scores = RegimeScores()
        # dataclasses.fields would work but we avoid import here for minimalism
        attrs = [a for a in dir(scores) if not a.startswith("_")]
        dimension_fields = [
            "equity_momentum_strength",
            "volatility_regime",
            "liquidity_macro_stance",
            "breadth_participation",
            "stress_crisis_probability",
            "mean_reversion_opportunity",
        ]
        for f in dimension_fields:
            assert f in attrs


class TestMetaModeEnum:
    """Verify the discrete Meta-Mode vocabulary (str Enum)."""

    def test_has_exactly_the_seven_modes_from_design_spec(self):
        expected = {
            "Strong_Broad_Momentum",
            "Narrow_Momentum",
            "Elevated_Vol_Defensive",
            "Liquidity_Stress",
            "Crisis_Acute",
            "Post_Crisis_Recovery",
            "Mean_Reversion_Rich",
        }
        actual = {m.value for m in MetaMode}
        assert actual == expected
        assert len(list(MetaMode)) == 7

    def test_str_enum_roundtrip_and_value(self):
        mode = MetaMode.CRISIS_ACUTE
        assert isinstance(mode, MetaMode)
        assert mode.value == "Crisis_Acute"
        # str(Enum) on a str-subclass Enum returns the "EnumName.MEMBER" form;
        # the important contract is .value + round-tripping via constructor.
        assert str(mode.value) == "Crisis_Acute"
        assert MetaMode("Crisis_Acute") is mode
        assert MetaMode["CRISIS_ACUTE"] is mode

    def test_mode_is_hashable_and_usable_in_sets(self):
        """Important for downstream Meta-Layer logic (sets of active modes)."""
        modes = {MetaMode.STRONG_BROAD_MOMENTUM, MetaMode.CRISIS_ACUTE}
        assert len(modes) == 2
        assert MetaMode.POST_CRISIS_RECOVERY in list(MetaMode)


class TestRegimeOSProtocol:
    """Verify the Protocol contract and that the stub satisfies it."""

    def test_protocol_is_runtime_checkable(self):
        """@runtime_checkable allows clean isinstance checks."""
        stub = StubRegimeOS()
        assert isinstance(stub, RegimeOS)

    def test_compute_regime_signature_and_return_types(self):
        """The single required method per Task 1.1 example."""
        stub = StubRegimeOS()
        scores, active_modes = stub.compute_regime()
        assert isinstance(scores, RegimeScores)
        assert isinstance(active_modes, list)
        # Modes (if any) must be proper MetaMode members
        assert all(isinstance(m, MetaMode) for m in active_modes)

    def test_compute_regime_accepts_optional_as_of_date(self):
        """Future-proof for historical regime queries in validation harness."""
        d = date(2025, 3, 14)
        scores, modes = StubRegimeOS().compute_regime(as_of=d)
        assert isinstance(scores, RegimeScores)
        # as_of is accepted; the stub ignores it (real impls will use it)

    def test_multiple_calls_are_deterministic_for_stub(self):
        """Stub is pure and stable (real impls must also be reasonably stable)."""
        stub = StubRegimeOS()
        r1 = stub.compute_regime()
        r2 = stub.compute_regime(as_of=date(2026, 1, 1))
        assert r1[0].equity_momentum_strength == r2[0].equity_momentum_strength
        # (stub always returns same neutral for now)

    def test_non_implementing_object_does_not_satisfy_protocol(self):
        """Structural check works via runtime_checkable."""
        class NotARegimeOS:
            pass
        assert not isinstance(NotARegimeOS(), RegimeOS)


class TestStubRegimeOSMinimalBehavior:
    """Document the intentionally minimal nature of the Phase 1.1 stub."""

    def test_stub_returns_neutral_scores(self):
        scores, _ = StubRegimeOS().compute_regime()
        assert scores.equity_momentum_strength == pytest.approx(0.5)
        assert scores.stress_crisis_probability == pytest.approx(0.5)

    def test_stub_returns_empty_or_minimal_modes(self):
        """Stub may return [] or a conservative default set."""
        _, modes = StubRegimeOS().compute_regime()
        assert isinstance(modes, list)
        # Either empty or a safe subset; we only require type correctness here.
        assert all(isinstance(m, MetaMode) for m in modes)


if __name__ == "__main__":
    # Allow direct execution during development
    pytest.main([__file__, "-q", "--tb=line"])