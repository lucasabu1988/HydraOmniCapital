"""
Meta-Layer Adapter - Versión Potente con Special Modes (Task 2.4)

Incluye los 4 modos especiales con comportamientos cualitativamente diferentes:
- CRISIS_ACUTE
- POST_CRISIS_RECOVERY
- STRONG_BROAD_MOMENTUM
- ELEVATED_VOL_DEFENSIVE
"""
import numpy as np
from dataclasses import dataclass
from typing import List


@dataclass
class MetaAdjustment:
    regime_score: float
    regime_type: str
    special_modes: List[str]
    recovery_boost: float
    overall_aggression: float
    bias_compass: float
    bias_rattlesnake: float
    bias_catalyst: float
    risk_flags: List[str]
    rationale: str


class LightweightMetaLayer:
    """Versión potente del Meta-Layer para el screener local."""

    def __init__(self):
        self.strong_regime_threshold = 0.62
        self.weak_regime_threshold = 0.38
        self.max_recovery_boost = 1.12

    def compute_adjustment(
        self,
        regime_score: float,
        recent_drawdown: float = 0.0,
        spy_20d_return: float = 0.0,
        spy_60d_return: float = 0.0,
        volatility_level: float = 0.5,
    ) -> MetaAdjustment:

        risk_flags = []
        rationale_parts = []
        special_modes = []

        # === Régimen Base ===
        if regime_score >= self.strong_regime_threshold:
            regime_type = "STRONG"
            base_aggression = 1.10
            bias_compass = 1.18
            bias_rattlesnake = 0.82
            bias_catalyst = 0.75
        elif regime_score >= 0.50:
            regime_type = "MODERATE"
            base_aggression = 1.04
            bias_compass = 1.08
            bias_rattlesnake = 0.95
            bias_catalyst = 0.90
        elif regime_score >= self.weak_regime_threshold:
            regime_type = "CAUTIOUS"
            base_aggression = 0.93
            bias_compass = 0.85
            bias_rattlesnake = 1.12
            bias_catalyst = 1.05
        else:
            regime_type = "WEAK"
            base_aggression = 0.82
            bias_compass = 0.70
            bias_rattlesnake = 1.20
            bias_catalyst = 0.95

        # === Special Modes ===
        # 1. CRISIS_ACUTE
        if recent_drawdown >= 0.12 or (regime_score < 0.25 and volatility_level > 0.70):
            base_aggression *= 0.82
            bias_compass *= 0.75
            special_modes.append("CRISIS_ACUTE")
            risk_flags.append("CRISIS_HARD_DEFENSE")
            rationale_parts.append("SPECIAL: Crisis Acute")

        # 2. POST_CRISIS_RECOVERY
        has_good_recovery = spy_20d_return > 0.025 and spy_60d_return > -0.08
        if recent_drawdown >= 0.06 and has_good_recovery and regime_score > 0.35:
            recovery_boost = min(1.0 + (recent_drawdown - 0.06) * 1.5, self.max_recovery_boost)
            base_aggression *= recovery_boost
            special_modes.append("POST_CRISIS_RECOVERY")
            risk_flags.append("RECOVERY_ACCEL")
            rationale_parts.append(f"SPECIAL: Recovery {recovery_boost:.2f}x")

        # 3. STRONG_BROAD_MOMENTUM
        if regime_score >= 0.68 and volatility_level < 0.55 and recent_drawdown < 0.06:
            base_aggression *= 1.06
            bias_compass *= 1.22
            bias_catalyst *= 0.65
            special_modes.append("STRONG_BROAD_MOMENTUM")
            risk_flags.append("MOMENTUM_OVERRIDE")
            rationale_parts.append("SPECIAL: Strong Momentum")

        # 4. ELEVATED_VOL_DEFENSIVE
        if volatility_level > 0.68:
            base_aggression *= 0.91
            bias_rattlesnake *= 1.15
            special_modes.append("ELEVATED_VOL_DEFENSIVE")
            risk_flags.append("VOL_MR_FRIENDLY")
            rationale_parts.append("SPECIAL: High Vol MR bias")

        overall_aggression = base_aggression
        rationale = " | ".join(rationale_parts) if rationale_parts else "Neutral"

        return MetaAdjustment(
            regime_score=regime_score,
            regime_type=regime_type,
            special_modes=special_modes,
            recovery_boost=1.0,
            overall_aggression=round(overall_aggression, 3),
            bias_compass=round(bias_compass, 3),
            bias_rattlesnake=round(bias_rattlesnake, 3),
            bias_catalyst=round(bias_catalyst, 3),
            risk_flags=list(set(risk_flags)),
            rationale=rationale
        )


def apply_meta_to_candidates(candidates_df, meta):
    df = candidates_df.copy()
    base = df['momentum'] * meta.overall_aggression

    if meta.regime_type == "STRONG" or "STRONG_BROAD_MOMENTUM" in meta.special_modes:
        final = base * (meta.bias_compass ** 0.7)
    elif meta.regime_type in ["WEAK", "CAUTIOUS"] or "ELEVATED_VOL_DEFENSIVE" in meta.special_modes:
        final = base * (meta.bias_rattlesnake ** 0.5) * 0.96
    else:
        final = base

    df['meta_score'] = final.round(4)
    df['meta_regime'] = meta.regime_score
    df['meta_regime_type'] = meta.regime_type
    df['meta_special_modes'] = ", ".join(meta.special_modes) if meta.special_modes else ""
    df['meta_aggression'] = meta.overall_aggression
    df['meta_rationale'] = meta.rationale

    df = df.sort_values('meta_score', ascending=False).reset_index(drop=True)
    df['rank'] = range(1, len(df) + 1)
    return df