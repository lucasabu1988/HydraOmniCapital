"""
hydra_meta/ensemble_regime_predictor.py — Ensemble Regime Predictor (HYDRA Meta-Layer v1, Task 3.1)

Optional, composable, heavily regularized ensemble that consumes RegimeScores
(and optional history) and emits *additional forward-looking signals*:
- forward_risk_signal (predicted stress / defensive pressure in the near term)
- aggression_suggestion (volatility-adjusted scalar hint for gross exposure bias)
- ensemble stability / confidence diagnostics

Design (per approved plan + user clarifications received 2026-05-30):
- VERY SMALL (effectively 4 internal heads) + HEAVILY REGULARIZED.
- Lightweight & interpretable only (no black boxes).
- Follows the exact established project pattern from compass_ml_learning.py:
  optional/lazy sklearn import with graceful pure-python fallback.
  When sklearn present: Ridge with high alpha for the linear components.
- Outputs are deliberately shrunk toward conservative neutral priors
  (risk ~0.50, aggression ~1.00) via explicit blend weights + tiny coefficients.
- Strict stability: internal smoothing + shrinkage → low sensitivity to input noise
  and low flip rates on sequential/walk-forward use.
- Fail-safe at every layer: any error, nan, missing data, or absent sklearn
  produces the safe neutral prediction. Never raises to callers.
- Completely isolated / optional: importing or using this module has ZERO effect
  on RegimeOS, BasicRegimeOS, MetaLayer, RiskBudgetMetaLayer, or any Phase 1/2
  contract. It can be deleted or never imported with no breakage (Task 3.1 scope).
- No production wiring in v1 (Phase 4 territory). Consumers in the future
  (MetaLayer enhancements) will treat the signals as optional extra features.

Seed 666 used for any controlled randomness (rare; most paths deterministic).

References:
- docs/superpowers/plans/2026-06-05-hydra-meta-layer-v1-implementation.md Task 3.1
- docs/superpowers/specs/2026-06-05-hydra-meta-layer-v1-design.md §6.3
- regime_os.py (RegimeScores is the sole primary input contract)
- hydra_meta/meta_layer.py (future consumer of forward signals; untouched)
- compass_ml_learning.py (sklearn optional + heavy reg pattern)
- AGENTS.md / Claude.md (ML fail-safe, Seed 666, conservative defaults)

Status: Task 3.1 implementation (strict TDD — tests written first).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable
import math

import numpy as np

# Upstream (Phase 1) — do not modify
from regime_os import RegimeScores

# =============================================================================
# SEED (project convention)
# =============================================================================
SEED = 666


# =============================================================================
# OUTPUT DATACLASS (rich contract per clarification)
# =============================================================================

@dataclass(frozen=True)
class EnsembleRegimePrediction:
    """Forward-looking regime signals produced by the small regularized ensemble.

    These are *additional* signals (not replacements for RegimeScores or MetaMode
    lists). Designed for optional future consumption by the Meta-Layer as extra
    features for risk budgeting, aggression modulation, or stability overlays.

    All numeric fields are in safe ranges and heavily regularized toward
    conservative neutral values by construction.

    Attributes:
        forward_risk_signal: [0.0, 1.0] — ensemble estimate of near-term defensive
            pressure / stress likelihood (higher = more caution warranted).
            Strong shrinkage keeps this from collapsing even on bullish inputs.
        aggression_suggestion: ~[0.75, 1.35] — hint for gross exposure bias.
            1.0 = neutral. Values >1.0 only modestly even in excellent regimes
            because of heavy prior blending.
        ensemble_confidence: [0.0, 1.0] — self-reported reliability of the
            ensemble (low when data sparse, high variance among heads, or error path).
        model_contributions: diagnostic breakdown (e.g. weights or partial
            predictions from each internal head) for audit / interpretability.
        prediction_stability: measure of agreement / low dispersion across the
            3-5 internal regularized heads (high = good for downstream trust).
        as_of: optional reference date (passed through from caller).
        version: interface + implementation version for evolution safety.
        rationale: human-readable explanation (especially on fallback paths).
    """
    forward_risk_signal: float = 0.50
    aggression_suggestion: float = 1.00
    ensemble_confidence: float = 0.30
    model_contributions: Dict[str, float] = field(default_factory=dict)
    prediction_stability: float = 0.90
    as_of: Optional[date] = None
    version: str = "ensemble-v0.1-regularized-202606"
    rationale: Optional[str] = "neutral conservative fallback (no data or error path)"


@runtime_checkable
class EnsembleRegimePredictor(Protocol):
    """Minimal structural protocol for future swappability (optional heads)."""

    def predict(
        self,
        scores: Optional[RegimeScores] = None,
        history: Optional[List[RegimeScores]] = None,
        as_of: Optional[date] = None,
    ) -> EnsembleRegimePrediction:
        ...


# =============================================================================
# IMPLEMENTATION: Small heavily regularized ensemble
# =============================================================================

class RegularizedEnsemblePredictor:
    """
    Tiny ensemble (4 internal heads) of heavily regularized lightweight models.

    Regularization techniques employed (all active simultaneously):
    - Explicit tiny coefficients on all linear terms (shrunk weights << 1.0).
    - Large explicit blend weight toward conservative neutral priors (0.70–0.78).
    - Optional sklearn Ridge with deliberately high alpha when available.
    - Internal EWMA smoothing on sequential predictions (live-path stability).
    - Clamping + variance damping across heads.
    - Fail-safe neutral prior on every error branch.

    The four heads (when sklearn absent or data insufficient):
      1. Shrunk linear risk head (mom positive, stress/vol negative — tiny betas)
      2. Variant shrunk linear (slightly different feature emphasis)
      3. Damped persistence / recent-average head (heavy EMA decay)
      4. Conservative heuristic rule head (mild adjustment only)
    Final output = mean(head predictions) blended 25-30% toward data-driven mean
    + 70-75% toward neutral prior. This is "heavy regularization" by design.

    When sklearn is available and sufficient history is supplied to a call,
    a Ridge (high alpha) is fit on-the-fly for one of the heads as a bonus
    regularized signal (still heavily shrunk in the blend).

    All paths are deterministic given identical inputs + Seed 666 (no hidden state
    leakage between independent instances).
    """

    VERSION = "ensemble-v0.1-regularized-202606"

    def __init__(self) -> None:
        self._rng = np.random.default_rng(SEED)
        self._has_sklearn = False
        self._Ridge = None
        self._try_load_sklearn()

        # Internal light state for sequential stability (live path only)
        self._ema_risk: float = 0.50
        self._ema_aggression: float = 1.00
        self._ema_alpha: float = 0.28   # additional smoothing (regularization)

        # Fixed tiny shrunk coefficients (pure-python path) — deliberately small
        # These are the "regularized model" weights.
        self._beta_risk = {
            "mom": 0.18,      # positive mom mildly lowers risk forecast
            "stress": 0.72,   # stress strongly raises risk
            "vol": 0.41,      # vol raises risk
            "breadth": -0.09, # mild
            "liq": -0.11,
            "mr": 0.04,
        }
        self._beta_aggr = {
            "mom": 0.22,
            "stress": -0.19,
            "vol": -0.14,
            "breadth": 0.07,
            "liq": 0.05,
            "mr": -0.03,
        }

        # Heavy shrinkage / prior blend factors (core of regularization)
        self._prior_weight_risk = 0.73
        self._prior_weight_aggr = 0.71
        self._neutral_risk = 0.50
        self._neutral_aggr = 1.00

    def _try_load_sklearn(self) -> None:
        """Lazy optional import following exact project ML convention."""
        try:
            from sklearn.linear_model import Ridge  # type: ignore
            self._Ridge = Ridge
            self._has_sklearn = True
        except Exception:
            self._has_sklearn = False
            self._Ridge = None

    def _reset_sequential_state(self) -> None:
        """For test isolation / error recovery."""
        self._ema_risk = 0.50
        self._ema_aggression = 1.00

    def _scores_to_vector(self, scores: RegimeScores) -> np.ndarray:
        """Safe extraction to fixed order vector."""
        return np.array([
            float(scores.equity_momentum_strength),
            float(scores.stress_crisis_probability),
            float(scores.volatility_regime),
            float(scores.breadth_participation),
            float(scores.liquidity_macro_stance),
            float(scores.mean_reversion_opportunity),
        ], dtype=float)

    def _clip(self, x: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, float(x)))

    def _safe_predict_linear(self, vec: np.ndarray, betas: Dict[str, float], center: float) -> float:
        """Tiny-coeff linear combo + center (pure python path)."""
        names = ["mom", "stress", "vol", "breadth", "liq", "mr"]
        val = center
        for i, n in enumerate(names):
            w = betas.get(n, 0.0)
            val += w * (vec[i] - 0.5)   # centered features for stability
        return val

    def _heuristic_head(self, vec: np.ndarray) -> tuple[float, float]:
        """Very conservative rule-based head (another regularized model)."""
        mom, stress, vol, br, liq, mr = vec
        # Risk only moves modestly
        risk = 0.50 + 0.55 * (stress - 0.50) + 0.28 * (vol - 0.50) - 0.12 * (mom - 0.50)
        # Aggression even more damped
        aggr = 1.00 + 0.19 * (mom - 0.50) - 0.16 * (stress - 0.50) - 0.09 * (vol - 0.50)
        return risk, aggr

    def _sklearn_ridge_head(self, history: Optional[List[RegimeScores]]) -> Optional[tuple[float, float]]:
        """Bonus regularized head using Ridge when sklearn + enough data present."""
        if not self._has_sklearn or not history or len(history) < 8:
            return None
        try:
            Ridge = self._Ridge
            # Build tiny synthetic design matrix from history (predict "next" stress proxy)
            X = []
            y_risk = []
            y_aggr = []
            for i in range(len(history) - 1):
                v = self._scores_to_vector(history[i])
                X.append(v)
                # Proxy targets: use next-bar stress/vol as crude forward risk label
                next_s = history[i + 1]
                y_risk.append(0.6 * next_s.stress_crisis_probability + 0.4 * next_s.volatility_regime)
                # Aggression proxy: inverse of stress + mom component
                y_aggr.append(1.00 + 0.25 * (next_s.equity_momentum_strength - 0.5) -
                              0.20 * (next_s.stress_crisis_probability - 0.5))
            if len(X) < 5:
                return None
            X_arr = np.array(X)
            # Heavy regularization
            ridge_r = Ridge(alpha=48.0, random_state=SEED)  # very high alpha
            ridge_a = Ridge(alpha=55.0, random_state=SEED)
            ridge_r.fit(X_arr, np.array(y_risk))
            ridge_a.fit(X_arr, np.array(y_aggr))
            last = X_arr[-1].reshape(1, -1)
            r = float(ridge_r.predict(last)[0])
            a = float(ridge_a.predict(last)[0])
            return r, a
        except Exception:
            return None

    def predict(
        self,
        scores: Optional[RegimeScores] = None,
        history: Optional[List[RegimeScores]] = None,
        as_of: Optional[date] = None,
    ) -> EnsembleRegimePrediction:
        """
        Primary inference entry point. Always returns a valid, conservative
        EnsembleRegimePrediction. Never raises.
        """
        try:
            if scores is None or not isinstance(scores, RegimeScores):
                # Pure fallback — no mutation of internal state
                return EnsembleRegimePrediction(
                    forward_risk_signal=0.50,
                    aggression_suggestion=1.00,
                    ensemble_confidence=0.28,
                    model_contributions={"fallback": 1.0},
                    prediction_stability=0.95,
                    as_of=as_of,
                    version=self.VERSION,
                    rationale="neutral conservative fallback (missing or invalid scores)",
                )

            vec = self._scores_to_vector(scores)

            # === Head 1 + 2: fixed shrunk linear heads (different emphasis) ===
            risk1 = self._safe_predict_linear(vec, self._beta_risk, 0.50)
            aggr1 = self._safe_predict_linear(vec, self._beta_aggr, 1.00)

            beta_risk2 = {k: v * 0.82 for k, v in self._beta_risk.items()}  # extra shrinkage variant
            beta_aggr2 = {k: v * 0.79 for k, v in self._beta_aggr.items()}
            risk2 = self._safe_predict_linear(vec, beta_risk2, 0.50)
            aggr2 = self._safe_predict_linear(vec, beta_aggr2, 1.00)

            # === Head 3: heuristic conservative rule head ===
            risk3, aggr3 = self._heuristic_head(vec)

            # === Head 4: sklearn Ridge (when possible) or damped persistence ===
            sk = self._sklearn_ridge_head(history)
            if sk is not None:
                risk4, aggr4 = sk
                head4_name = "ridge"
            else:
                # Damped persistence from ema or neutral
                risk4 = 0.35 * self._ema_risk + 0.65 * 0.50
                aggr4 = 0.35 * self._ema_aggression + 0.65 * 1.00
                head4_name = "persistence_damped"

            # Raw ensemble mean (4 heads)
            raw_risk = (risk1 + risk2 + risk3 + risk4) / 4.0
            raw_aggr = (aggr1 + aggr2 + aggr3 + aggr4) / 4.0

            # === Heavy explicit prior shrinkage (the dominant regularization) ===
            final_risk = (
                (1.0 - self._prior_weight_risk) * raw_risk +
                self._prior_weight_risk * self._neutral_risk
            )
            final_aggr = (
                (1.0 - self._prior_weight_aggr) * raw_aggr +
                self._prior_weight_aggr * self._neutral_aggr
            )

            # Additional live-path EWMA smoothing (extra stability layer)
            self._ema_risk = self._ema_alpha * final_risk + (1 - self._ema_alpha) * self._ema_risk
            self._ema_aggression = self._ema_alpha * final_aggr + (1 - self._ema_alpha) * self._ema_aggression

            # Use the smoothed values for output (sequential calls benefit)
            out_risk = self._clip(self._ema_risk, 0.0, 1.0)
            out_aggr = self._clip(self._ema_aggression, 0.70, 1.45)

            # Stability / confidence diagnostics
            head_risks = [risk1, risk2, risk3, risk4]
            head_aggrs = [aggr1, aggr2, aggr3, aggr4]
            risk_disp = float(np.std(head_risks))
            aggr_disp = float(np.std(head_aggrs))
            stability = self._clip(0.96 - (risk_disp + aggr_disp) * 1.8, 0.55, 0.98)

            conf = self._clip(0.42 + (stability - 0.80) * 1.1 - risk_disp * 2.0, 0.22, 0.88)

            contribs: Dict[str, float] = {
                "linear_shrunk_1": float(risk1),
                "linear_shrunk_2": float(risk2),
                "heuristic": float(risk3),
                head4_name: float(risk4),
                "prior_blend_risk": self._prior_weight_risk,
                "prior_blend_aggr": self._prior_weight_aggr,
            }

            rationale = (
                "regularized ensemble (4 heads + strong prior shrinkage + EWMA); "
                f"sklearn={'yes' if self._has_sklearn else 'no'}; "
                f"stability={stability:.2f}"
            )

            return EnsembleRegimePrediction(
                forward_risk_signal=out_risk,
                aggression_suggestion=out_aggr,
                ensemble_confidence=conf,
                model_contributions=contribs,
                prediction_stability=stability,
                as_of=as_of,
                version=self.VERSION,
                rationale=rationale,
            )

        except Exception:
            # Ultimate fail-safe — never let an error escape
            self._reset_sequential_state()
            return EnsembleRegimePrediction(
                forward_risk_signal=0.50,
                aggression_suggestion=1.00,
                ensemble_confidence=0.25,
                model_contributions={"error_fallback": 1.0},
                prediction_stability=0.98,
                as_of=as_of,
                version=self.VERSION,
                rationale="hard neutral fallback after unexpected error (fail-safe)",
            )


# Public exports
__all__ = [
    "SEED",
    "EnsembleRegimePrediction",
    "EnsembleRegimePredictor",  # Protocol
    "RegularizedEnsemblePredictor",
]
