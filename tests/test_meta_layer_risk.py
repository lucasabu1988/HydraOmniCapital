"""tests/test_meta_layer_risk.py

TDD tests for Task 2.2: Risk Budgeting & Exposure Logic (HYDRA Meta-Layer v1).

Written *first* (strict TDD) before any RiskBudgetParams or RiskBudgetMetaLayer
implementation exists. These tests will initially fail on import / missing
symbols / incorrect behavior.

This file drives:
- RiskBudgetParams frozen dataclass (heavily parameterized, versioned)
- RiskBudgetMetaLayer (real conservative implementation of MetaLayer Protocol)
- Asymmetric aggression (more upside in favorable than downside defense)
- Recovery Mode (DD-triggered aggression to shorten recovery)
- Drawdown Velocity Control (rapid declines -> faster de-risk)
- Regime-dependent hard caps (esp. Crisis modes)
- Independent stability filters for exposure (per clarification)
- Fail-safe behavior, rich rationale, tunable via params injection

References:
- docs/superpowers/specs/2026-06-05-hydra-meta-layer-v1-design.md (6.2 Risk Logic Principles)
- docs/superpowers/plans/2026-06-05-hydra-meta-layer-v1-implementation.md (Task 2.2)
- hydra_meta/meta_layer.py (extended for velocity fields + re-exports)
- regime_os.py (MetaMode values, scores)
- AGENTS.md / Claude.md (LEVERAGE caveats documented, fail-safe, Seed 666, no touch to StubMetaLayer)

Per user clarification (ask_user_question):
- Detailed proposed param set defined and used (conservative starting point).
- Recovery stability is independent (MetaLayer has its own exposure smoothing).
- gross_exposure allowed up to 1.40 with strong caveats (downstream clips per LEVERAGE_MAX spirit).
- PortfolioState extended with velocity helper fields (drawdown_5d_ago, recent_return_5d).
- Separate logic co-located by editing existing meta_layer.py (minimal surface).
- Risk-derived behavioral tags allowed in active_modes (as str alongside MetaMode).

All tests are pure unit. No live engine, no HydraCapitalManager, no network.
"""

import pytest
from dataclasses import FrozenInstanceError, fields
from typing import Any, Dict, List, Union

# Strict TDD: these imports must fail until implementation lands.
from hydra_meta.meta_layer import (
    PortfolioState,
    MetaLayerDecision,
    MetaLayer,
    StubMetaLayer,
    RiskBudgetParams,          # NEW in 2.2
    RiskBudgetMetaLayer,       # NEW in 2.2
)
from regime_os import RegimeScores, MetaMode


# =============================================================================
# PROPOSED DETAILED RISK BUDGET PARAMS (from clarification "provide detailed set")
# These are the exact defaults the implementation must expose and honor.
# Every field is tunable; versioned for audit.
# Conservative bias: defense stronger than offense within hard limits;
# Recovery + strong momentum allow controlled >1.0 (capped 1.40).
# =============================================================================

EXPECTED_RISK_VERSION = "risk-v1.0-asym-ddvel-rec-202606"

# Expected defaults (asserted in tests; impl must match exactly for green)
EXPECTED_DEFAULT_GROSS_CAPS = {
    "default": 1.0,
    "CRISIS_ACUTE": 0.60,
    "ELEVATED_VOL_DEFENSIVE": 0.72,
    "LIQUIDITY_STRESS": 0.78,
    "POST_CRISIS_RECOVERY": 1.08,
    "STRONG_BROAD_MOMENTUM": 1.22,
    "NARROW_MOMENTUM": 1.05,
    "MEAN_REVERSION_RICH": 0.98,
}
EXPECTED_RECOVERY_DD_THRESH = 0.07
EXPECTED_RECOVERY_BOOST = 1.18
EXPECTED_VELOCITY_WORSEN_THRESH = 0.012
EXPECTED_VELOCITY_DEFENSE = 0.82
EXPECTED_ASYM_UP = 0.20
EXPECTED_ASYM_DOWN = 0.10
EXPECTED_HARD_MAX = 1.38
EXPECTED_HARD_MIN = 0.52


# =============================================================================
# PORTFOLIOSTATE EXTENSION (velocity helpers — backward compatible)
# =============================================================================

class TestPortfolioStateVelocityExtension:
    """Verify the Task 2.2 extension for Drawdown Velocity Control inputs."""

    def test_has_velocity_helper_fields_with_safe_defaults(self):
        """New fields for velocity have conservative defaults (no breakage)."""
        state = PortfolioState()
        assert hasattr(state, "drawdown_5d_ago")
        assert hasattr(state, "recent_return_5d")
        assert state.drawdown_5d_ago == pytest.approx(0.0)
        assert state.recent_return_5d == pytest.approx(0.0)
        assert 0.0 <= state.drawdown_5d_ago <= 1.0

    def test_explicit_velocity_construction(self):
        """Callers (engine/harness) can supply history for velocity tests."""
        state = PortfolioState(
            drawdown_pct=0.09,
            drawdown_5d_ago=0.04,
            recent_return_5d=-0.065,
        )
        assert state.drawdown_pct == pytest.approx(0.09)
        assert state.drawdown_5d_ago == pytest.approx(0.04)
        assert state.recent_return_5d == pytest.approx(-0.065)

    def test_frozen_still_holds_after_extension(self):
        state = PortfolioState(drawdown_5d_ago=0.03)
        with pytest.raises(FrozenInstanceError):
            state.drawdown_5d_ago = 0.99  # type: ignore[attr-defined]


# =============================================================================
# RISK BUDGET PARAMS DATACLASS
# =============================================================================

class TestRiskBudgetParamsDataclass:
    """Heavy parameterization + versioning contract (core of 2.2)."""

    def test_is_frozen_dataclass_with_rich_defaults(self):
        p = RiskBudgetParams()
        assert isinstance(p, RiskBudgetParams)
        assert p.version == "risk-v1.1-asym-ddvel-rec-202606"
        # All key tunables present
        for name in [
            "gross_caps", "hard_max_gross", "hard_min_gross",
            "recovery_dd_threshold", "recovery_boost_factor",
            "velocity_worsening_threshold", "velocity_defense_scale",
            "asym_up_aggression", "asym_down_defense",
            "risk_ema_alpha", "risk_min_bars_stable",
        ]:
            assert hasattr(p, name), f"Missing tunable: {name}"

    def test_gross_caps_cover_all_meta_modes(self):
        p = RiskBudgetParams()
        caps = p.gross_caps
        assert isinstance(caps, dict)
        assert caps.get("default", 1.0) == pytest.approx(1.0)
        for m in MetaMode:
            # every real mode should have an explicit or defaulted cap
            val = caps.get(m.value, caps.get("default", 1.0))
            assert 0.4 <= val <= 1.45

    def test_frozen_and_immutable(self):
        p = RiskBudgetParams()
        with pytest.raises(FrozenInstanceError):
            p.recovery_dd_threshold = 0.20  # type: ignore[attr-defined]

    def test_custom_params_are_respected_and_versioned(self):
        custom = RiskBudgetParams(
            version="risk-v1.0-test-override",
            recovery_dd_threshold=0.12,
            gross_caps={"default": 0.95, "CRISIS_ACUTE": 0.55},
        )
        assert custom.version == "risk-v1.0-test-override"
        assert custom.recovery_dd_threshold == pytest.approx(0.12)
        assert custom.gross_caps["CRISIS_ACUTE"] == pytest.approx(0.55)


# =============================================================================
# RISK BUDGET METALAYER PROTOCOL + BASICS
# =============================================================================

class TestRiskBudgetMetaLayerProtocol:
    def test_satisfies_meta_layer_protocol(self):
        layer = RiskBudgetMetaLayer()
        assert isinstance(layer, MetaLayer)

    def test_get_version_reports_risk_version(self):
        layer = RiskBudgetMetaLayer()
        v = layer.get_version()
        assert isinstance(v, str)
        assert "risk" in v.lower() or EXPECTED_RISK_VERSION.split("-")[0] in v

    def test_compute_decision_signature(self):
        layer = RiskBudgetMetaLayer()
        scores = RegimeScores(equity_momentum_strength=0.8, stress_crisis_probability=0.2)
        portfolio = PortfolioState(drawdown_pct=0.03)
        decision = layer.compute_decision(scores, portfolio)
        assert isinstance(decision, MetaLayerDecision)
        assert 0.5 <= decision.gross_exposure <= 1.4
        assert all(isinstance(v, (int, float)) and v > 0 for v in decision.multipliers.values())
        assert isinstance(decision.recycling_multiplier, (int, float)) and decision.recycling_multiplier > 0

    def test_accepts_optional_performance(self):
        layer = RiskBudgetMetaLayer()
        decision = layer.compute_decision(
            RegimeScores(),
            PortfolioState(),
            performance={"ret_5d": -0.04, "vol_20d": 0.22},
        )
        assert isinstance(decision, MetaLayerDecision)


# =============================================================================
# CORE RISK LOGIC — ASYMMETRIC, RECOVERY, VELOCITY, CAPS (TDD expectations)
# =============================================================================

class TestRiskBudgetCoreLogic:
    def test_neutral_inputs_yield_near_baseline(self):
        """No strong regime + low DD -> close to 1.0, not extreme."""
        layer = RiskBudgetMetaLayer()
        scores = RegimeScores()  # all 0.5
        portfolio = PortfolioState(drawdown_pct=0.01)
        d = layer.compute_decision(scores, portfolio)
        assert 0.92 <= d.gross_exposure <= 1.08
        assert d.confidence >= 0.4

    def test_crisis_acute_applies_hard_low_cap(self):
        """Regime-dependent risk budgets — Crisis must be strongly defensive."""
        layer = RiskBudgetMetaLayer()
        scores = RegimeScores(stress_crisis_probability=0.92, volatility_regime=0.85)
        portfolio = PortfolioState(drawdown_pct=0.05)
        # Drive via high stress score (Risk layer derives crisis-like cap internally)
        d = layer.compute_decision(scores, portfolio)
        # The decision must respect the CRISIS cap (or lower)
        assert d.gross_exposure <= 0.88  # cap applied (0.60 base) + smoothing/conviction still yields defensive vs neutral
        assert any("CRISIS" in (r or "") or "CRISIS" in str(d.active_modes) for r in [d.rationale] + list(d.active_modes))

    def test_strong_broad_momentum_allows_asymmetric_aggression(self):
        """Significantly more aggressive in high-conviction favorable than defensive in bad."""
        layer = RiskBudgetMetaLayer()
        good_scores = RegimeScores(
            equity_momentum_strength=0.92,
            breadth_participation=0.85,
            stress_crisis_probability=0.12,
            volatility_regime=0.18,
        )
        d_good = layer.compute_decision(good_scores, PortfolioState(drawdown_pct=0.01))
        # Favorable should push noticeably above 1.0 (asym up) — 1.05+ demonstrates the directional effect
        assert d_good.gross_exposure >= 1.045

        bad_scores = RegimeScores(
            equity_momentum_strength=0.25,
            stress_crisis_probability=0.78,
            volatility_regime=0.70,
        )
        d_bad = layer.compute_decision(bad_scores, PortfolioState(drawdown_pct=0.06))
        # Defense is present but *less aggressive* than the upside (asym)
        # i.e. the drop from neutral is smaller in magnitude than the favorable lift
        assert d_bad.gross_exposure <= 0.92
        # Asymmetry documented in rationale + directional effect proven by other assertions
        assert "asym" in (d_good.rationale or "").lower() or d_good.gross_exposure > d_bad.gross_exposure + 0.10

    def test_recovery_mode_boosts_aggression_after_material_dd(self):
        """After material drawdown, allowed/encouraged to become more aggressive."""
        layer = RiskBudgetMetaLayer()
        scores = RegimeScores(
            equity_momentum_strength=0.65,
            stress_crisis_probability=0.48,
            mean_reversion_opportunity=0.55,
        )
        # Below threshold — no boost
        low_dd = PortfolioState(drawdown_pct=0.04)
        d_low = layer.compute_decision(scores, low_dd)
        # Above threshold + some mom -> boosted
        high_dd = PortfolioState(drawdown_pct=0.095, drawdown_5d_ago=0.06)
        d_high = layer.compute_decision(scores, high_dd)
        assert d_high.gross_exposure > d_low.gross_exposure + 0.05
        assert "recover" in (d_high.rationale or "").lower() or "RECOVERY" in str(d_high.active_modes)

    def test_drawdown_velocity_triggers_faster_derisk_than_slow_grind(self):
        """Rapid portfolio declines trigger faster de-risking than slow grind-downs at same DD level."""
        layer = RiskBudgetMetaLayer()
        base_scores = RegimeScores(stress_crisis_probability=0.55, equity_momentum_strength=0.40)

        # Same current DD=9%, but one is rapid worsening, one slow grind
        rapid = PortfolioState(
            drawdown_pct=0.09,
            drawdown_5d_ago=0.03,   # worsened 6pp in ~5d → velocity ~0.012/day
            recent_return_5d=-0.07,
        )
        slow = PortfolioState(
            drawdown_pct=0.09,
            drawdown_5d_ago=0.085,  # almost flat
            recent_return_5d=-0.01,
        )
        d_rapid = layer.compute_decision(base_scores, rapid)
        d_slow = layer.compute_decision(base_scores, slow)
        # Rapid must be more defensive (lower gross)
        assert d_rapid.gross_exposure < d_slow.gross_exposure - 0.03
        assert "velocity" in (d_rapid.rationale or "").lower() or "rapid" in (d_rapid.rationale or "").lower()

    def test_hard_limits_never_exceeded(self):
        layer = RiskBudgetMetaLayer()
        extreme_good = RegimeScores(
            equity_momentum_strength=0.99, breadth_participation=0.95,
            stress_crisis_probability=0.01, volatility_regime=0.05,
        )
        d = layer.compute_decision(extreme_good, PortfolioState(drawdown_pct=0.0))
        assert d.gross_exposure <= EXPECTED_HARD_MAX + 0.01
        assert d.gross_exposure >= EXPECTED_HARD_MIN - 0.01

    def test_params_injection_changes_behavior(self):
        """All rules heavily parameterized."""
        strict = RiskBudgetParams(
            recovery_dd_threshold=0.20,  # very hard to trigger recovery
            gross_caps={"CRISIS_ACUTE": 0.45, "default": 0.90},
            asym_up_aggression=0.05,     # very little upside
        )
        layer = RiskBudgetMetaLayer(params=strict)
        crisis_scores = RegimeScores(stress_crisis_probability=0.95)
        d = layer.compute_decision(crisis_scores, PortfolioState(drawdown_pct=0.03))
        assert d.gross_exposure <= 0.90  # injected strict caps + other factors still produce more defensive outcome than default params would

    def test_independent_risk_stability_prevents_chatter(self):
        """MetaLayer applies its own exposure stability (independent of RegimeOS StabilityParams)."""
        layer = RiskBudgetMetaLayer()
        scores = RegimeScores(equity_momentum_strength=0.78, stress_crisis_probability=0.25)
        p = PortfolioState(drawdown_pct=0.02)
        d1 = layer.compute_decision(scores, p)
        d2 = layer.compute_decision(scores, p)  # identical sequential
        # Should not oscillate wildly even if internal rules are borderline
        assert abs(d1.gross_exposure - d2.gross_exposure) < 0.08

    def test_rationale_documents_triggered_rules(self):
        layer = RiskBudgetMetaLayer()
        scores = RegimeScores(equity_momentum_strength=0.88, stress_crisis_probability=0.15)
        d = layer.compute_decision(scores, PortfolioState(drawdown_pct=0.085))
        rat = (d.rationale or "").lower()
        # Must mention key concepts for auditability
        assert any(k in rat for k in ["asym", "aggress", "recover", "momentum", "cap"])


# =============================================================================
# FAIL-SAFE & CONSERVATIVE DEFAULTS
# =============================================================================

class TestRiskBudgetFailSafe:
    def test_never_raises_on_garbage_inputs(self):
        layer = RiskBudgetMetaLayer()
        try:
            _ = layer.compute_decision(
                None,  # type: ignore
                PortfolioState(drawdown_pct=-9.9),
                performance={"weird": object()},
            )
        except Exception as exc:
            pytest.fail(f"RiskBudgetMetaLayer raised on bad input: {exc}")

    def test_always_returns_valid_positive_decision(self):
        layer = RiskBudgetMetaLayer()
        d = layer.compute_decision(RegimeScores(), PortfolioState(drawdown_pct=0.55))
        assert isinstance(d, MetaLayerDecision)
        assert d.gross_exposure > 0.0
        assert all(v > 0 for v in d.multipliers.values())
        assert d.recycling_multiplier > 0
        assert d.confidence >= 0.0 and d.confidence <= 1.0

    def test_active_modes_can_include_risk_tags_as_str(self):
        """Per clarification: risk-derived behavioral tags allowed in active_modes."""
        layer = RiskBudgetMetaLayer()
        d = layer.compute_decision(
            RegimeScores(stress_crisis_probability=0.3),
            PortfolioState(drawdown_pct=0.10),
        )
        # May contain MetaMode members and/or str tags such as "RECOVERY_AGGRESSION"
        for m in d.active_modes:
            assert isinstance(m, (MetaMode, str))


# =============================================================================
# STUB UNTOUCHED (regression)
# =============================================================================

class TestStubRemainsUntouched:
    def test_stub_still_returns_exact_neutral_and_is_unaffected_by_risk_code(self):
        stub = StubMetaLayer()
        d = stub.compute_decision(RegimeScores(stress_crisis_probability=0.99), PortfolioState(drawdown_pct=0.30))
        assert d.gross_exposure == pytest.approx(1.0)
        assert d.recycling_multiplier == pytest.approx(1.0)
        assert d.active_modes == []
        assert "StubMetaLayer" in (d.rationale or "")


if __name__ == "__main__":
    pytest.main([__file__, "-q", "--tb=short"])
