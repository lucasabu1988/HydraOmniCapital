"""
Meta-Layer Adapter para el Screener Local (versión ligera pero fiel).

Esta versión es una adaptación práctica del RiskBudgetMetaLayer + Recovery Adaptation
para uso en screening diario (no necesita estado secuencial completo como el live engine).

Proporciona:
- Ajuste de scores según régimen
- Lógica conservadora de Recovery (Task 3.2)
- Multiplicadores de "agresión" recomendados
"""
import numpy as np
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class MetaAdjustment:
    regime_score: float
    recovery_boost: float          # 1.0 = neutral, >1.0 = más agresivo en recuperación
    overall_aggression: float      # Multiplicador general recomendado
    bias_compass: float            # >1.0 = favorecer momentum
    bias_rattlesnake: float        # >1.0 = favorecer mean-reversion
    risk_flags: list[str]
    rationale: str


class LightweightMetaLayer:
    """
    Versión ligera del Meta-Layer optimizada para screening.
    Conservadora por diseño (igual que la versión completa).
    """

    def __init__(self):
        # Parámetros conservadores (basados en la versión completa)
        self.recovery_dd_threshold = 0.08      # Activar recovery si DD > 8%
        self.recovery_momentum_min = 0.30      # Necesita cierto momentum de recuperación
        self.max_recovery_boost = 1.10         # Tope muy conservador (como Task 3.2)
        self.base_aggression = 1.0

    def compute_adjustment(
        self,
        regime_score: float,
        recent_drawdown: float = 0.0,
        spy_20d_return: float = 0.0,
        volatility_regime: float = 0.5,
    ) -> MetaAdjustment:
        """
        Calcula ajustes recomendados basados en la lógica Meta-Layer.

        Args:
            regime_score: 0-1 (de nuestro regime scorer)
            recent_drawdown: drawdown actual del mercado (0.0 a 1.0)
            spy_20d_return: retorno de SPY últimos 20 días (para detectar recuperación)
            volatility_regime: proxy de volatilidad actual (0.3 calm, 0.7+ high)
        """
        risk_flags = []
        rationale_parts = []

        # === 1. Recovery Logic (Task 3.2 style - muy conservadora) ===
        recovery_boost = 1.0

        is_in_drawdown = recent_drawdown >= self.recovery_dd_threshold
        has_recovery_momentum = spy_20d_return > 0.03  # al menos +3% en 20d

        if is_in_drawdown and has_recovery_momentum and regime_score > 0.40:
            # Solo boost muy moderado
            recovery_boost = min(1.0 + (recent_drawdown - 0.08) * 1.2, self.max_recovery_boost)
            risk_flags.append("POST_CRISIS_RECOVERY")
            rationale_parts.append(f"Recovery mode active (boost {recovery_boost:.2f}x)")

        # === 2. Regime-based aggression ===
        if regime_score >= 0.65:
            base_aggression = 1.08
            bias_compass = 1.15
            bias_rattlesnake = 0.85
            rationale_parts.append("Strong regime → favor momentum")
        elif regime_score >= 0.50:
            base_aggression = 1.03
            bias_compass = 1.05
            bias_rattlesnake = 0.95
            rationale_parts.append("Moderate regime")
        elif regime_score >= 0.35:
            base_aggression = 0.95
            bias_compass = 0.90
            bias_rattlesnake = 1.10
            risk_flags.append("ELEVATED_VOL_DEFENSIVE")
            rationale_parts.append("Cautious regime → slight mean-reversion bias")
        else:
            base_aggression = 0.85
            bias_compass = 0.75
            bias_rattlesnake = 1.15
            risk_flags.append("WEAK_REGIME")
            rationale_parts.append("Weak regime → defensive stance")

        # === 3. Volatility overlay ===
        if volatility_regime > 0.65:
            base_aggression *= 0.92
            bias_rattlesnake *= 1.08
            risk_flags.append("HIGH_VOL")
            rationale_parts.append("High vol → extra defensive")

        overall_aggression = base_aggression * recovery_boost

        rationale = " | ".join(rationale_parts) if rationale_parts else "Neutral conditions"

        return MetaAdjustment(
            regime_score=regime_score,
            recovery_boost=recovery_boost,
            overall_aggression=round(overall_aggression, 3),
            bias_compass=round(bias_compass, 3),
            bias_rattlesnake=round(bias_rattlesnake, 3),
            risk_flags=risk_flags,
            rationale=rationale
        )


def apply_meta_to_candidates(
    candidates_df: pd.DataFrame,
    meta: MetaAdjustment
) -> pd.DataFrame:
    """
    Aplica los ajustes de la Meta-Layer al ranking de candidatos.
    """
    df = candidates_df.copy()

    # Ajuste de score final
    df['meta_adjusted_score'] = df['momentum_score'] * meta.overall_aggression

    # Bonus/penalty según bias
    # (Aquí podríamos clasificar acciones, pero por ahora usamos score general)
    df['final_score'] = df['meta_adjusted_score']

    # Añadir información de meta
    df['meta_regime'] = meta.regime_score
    df['meta_recovery_boost'] = meta.recovery_boost
    df['meta_aggression'] = meta.overall_aggression
    df['meta_rationale'] = meta.rationale

    # Re-rankear
    df = df.sort_values('final_score', ascending=False).reset_index(drop=True)
    df['final_rank'] = range(1, len(df) + 1)

    return df