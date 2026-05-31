"""
Meta-Layer Adapter para el Screener Local - Versión Potente.

Esta es una versión más completa y fiel al RiskBudgetMetaLayer original,
optimizada para screening diario pero con más poder de decisión.

Incluye:
- Mejor clasificación de régimen (más dimensiones)
- Lógica de Recovery más desarrollada (Task 3.2)
- Recomendaciones de bias por pilar (COMPASS vs Rattlesnake vs diversificadores)
- Ajustes más agresivos pero aún conservadores
"""
import numpy as np
from dataclasses import dataclass
from typing import List


@dataclass
class MetaAdjustment:
    regime_score: float
    regime_type: str                     # "STRONG", "MODERATE", "CAUTIOUS", "WEAK"
    recovery_boost: float                # 1.0 = neutral, >1.0 = modo recuperación
    overall_aggression: float
    bias_compass: float                  # Favor momentum
    bias_rattlesnake: float              # Favor mean-reversion
    bias_catalyst: float                 # Favor diversificadores macro
    risk_flags: List[str]
    rationale: str


class LightweightMetaLayer:
    """
    Versión más potente del Meta-Layer para el screener.
    Conservadora pero con más granularidad que la versión anterior.
    """

    def __init__(self):
        # Parámetros más cercanos a la versión completa
        self.recovery_dd_threshold = 0.07
        self.max_recovery_boost = 1.12
        self.strong_regime_threshold = 0.62
        self.weak_regime_threshold = 0.38

    def compute_adjustment(
        self,
        regime_score: float,
        recent_drawdown: float = 0.0,
        spy_20d_return: float = 0.0,
        spy_60d_return: float = 0.0,
        volatility_level: float = 0.5,   # 0.3 calm → 0.8+ stressed
    ) -> MetaAdjustment:
        """
        Versión más potente de compute_adjustment.
        """
        risk_flags = []
        rationale_parts = []

        # === 1. Clasificación más fina del régimen ===
        if regime_score >= self.strong_regime_threshold:
            regime_type = "STRONG"
            base_aggression = 1.10
            bias_compass = 1.18
            bias_rattlesnake = 0.82
            bias_catalyst = 0.75
            rationale_parts.append("Strong regime: Max COMPASS bias")
        elif regime_score >= 0.50:
            regime_type = "MODERATE"
            base_aggression = 1.04
            bias_compass = 1.08
            bias_rattlesnake = 0.95
            bias_catalyst = 0.90
            rationale_parts.append("Moderate regime")
        elif regime_score >= self.weak_regime_threshold:
            regime_type = "CAUTIOUS"
            base_aggression = 0.93
            bias_compass = 0.85
            bias_rattlesnake = 1.12
            bias_catalyst = 1.05
            risk_flags.append("ELEVATED_VOL_DEFENSIVE")
            rationale_parts.append("Cautious: Rattlesnake bias")
        else:
            regime_type = "WEAK"
            base_aggression = 0.82
            bias_compass = 0.70
            bias_rattlesnake = 1.20
            bias_catalyst = 0.95
            risk_flags.append("WEAK_REGIME")
            rationale_parts.append("Weak regime: Strong defensive stance")

        # === 2. Recovery Logic (más desarrollada) ===
        recovery_boost = 1.0
        is_in_drawdown = recent_drawdown >= self.recovery_dd_threshold
        has_good_recovery = spy_20d_return > 0.025 and spy_60d_return > -0.05

        if is_in_drawdown and has_good_recovery and regime_score > 0.38:
            depth_factor = min((recent_drawdown - 0.07) * 1.4, 0.12)
            recovery_boost = 1.0 + depth_factor
            recovery_boost = min(recovery_boost, self.max_recovery_boost)

            risk_flags.append("POST_CRISIS_RECOVERY")
            rationale_parts.append(f"Recovery active (+{ (recovery_boost-1)*100 :.0f}%)")

        # === 3. Volatility overlay ===
        if volatility_level > 0.68:
            base_aggression *= 0.90
            bias_rattlesnake *= 1.10
            bias_compass *= 0.92
            risk_flags.append("HIGH_VOL")
            rationale_parts.append("High volatility: extra defense")

        # === 4. Ajuste final ===
        overall_aggression = base_aggression * recovery_boost

        rationale = " | ".join(rationale_parts) if rationale_parts else "Neutral / Balanced"

        return MetaAdjustment(
            regime_score=regime_score,
            regime_type=regime_type,
            recovery_boost=round(recovery_boost, 3),
            overall_aggression=round(overall_aggression, 3),
            bias_compass=round(bias_compass, 3),
            bias_rattlesnake=round(bias_rattlesnake, 3),
            bias_catalyst=round(bias_catalyst, 3),
            risk_flags=risk_flags,
            rationale=rationale
        )


def apply_meta_to_candidates(
    candidates_df: pd.DataFrame,
    meta: MetaAdjustment
) -> pd.DataFrame:
    """
    Aplica los ajustes de la Meta-Layer de forma más potente.
    """
    df = candidates_df.copy()

    # Score base ajustado por agresión general
    base = df['momentum'] * meta.overall_aggression

    # Bonus adicional según bias (aproximado)
    # Como no tenemos clasificación por estrategia por ticker aún,
    # aplicamos un ajuste general pero más agresivo según el régimen.
    if meta.regime_type == "STRONG":
        # En régimen fuerte, premiamos más el momentum puro
        final = base * (meta.bias_compass ** 0.6)
    elif meta.regime_type == "WEAK":
        # En régimen débil, castigamos momentum agresivo
        final = base * (meta.bias_rattlesnake ** 0.4) * 0.95
    else:
        final = base

    df['meta_score'] = final.round(4)
    df['meta_regime'] = meta.regime_score
    df['meta_recovery_boost'] = meta.recovery_boost
    df['meta_aggression'] = meta.overall_aggression
    df['meta_regime_type'] = meta.regime_type
    df['meta_rationale'] = meta.rationale

    # Reordenar
    df = df.sort_values('meta_score', ascending=False).reset_index(drop=True)
    df['rank'] = range(1, len(df) + 1)

    return df