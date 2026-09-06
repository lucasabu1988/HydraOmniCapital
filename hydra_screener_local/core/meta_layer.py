"""
Meta-Layer + Pillar Multipliers

Implements section 4.4 of HYDRA_ALGORITHM_SPEC.md (v1.2)

See SPEC:
- 4.4.1 Base Regime Biases (table with exact values)
- 4.4.2 Special Modes (exact triggers and multiplier adjustments)
- 4.4.3 Pillar Multipliers (COMPASS, Rattlesnake, Catalyst, EFA + clamping [0.60, 1.45])

This is the reference implementation of the MetaAdjustment logic.
"""
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
    pillar_multipliers: dict          # NEW: {"COMPASS": 1.15, "Rattlesnake": 0.90, "Catalyst": 0.65, "EFA": 0.80}
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
        recovery_boost = 1.0

        # === Régimen Base === (exact values from SPEC 4.4.1 table)
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

        # === Special Modes === (exact triggers and effects from SPEC 4.4.2)
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

        # === Pillar Multipliers (la parte más potente) === (SPEC 4.4.3)
        # Exact base values per regime + special mode adjustments + clamp [0.60, 1.45]
        multipliers = {
            "COMPASS": 1.0,
            "Rattlesnake": 1.0,
            "Catalyst": 1.0,
            "EFA": 1.0
        }

        # Base multipliers por régimen (exact from SPEC table 4.4.1)
        if regime_type == "STRONG":
            multipliers["COMPASS"] = 1.15
            multipliers["Rattlesnake"] = 0.85
            multipliers["Catalyst"] = 0.70
            multipliers["EFA"] = 0.75
        elif regime_type == "MODERATE":
            multipliers["COMPASS"] = 1.05
            multipliers["Rattlesnake"] = 0.95
            multipliers["Catalyst"] = 0.90
            multipliers["EFA"] = 0.92
        elif regime_type == "CAUTIOUS":
            multipliers["COMPASS"] = 0.88
            multipliers["Rattlesnake"] = 1.12
            multipliers["Catalyst"] = 0.95
            multipliers["EFA"] = 0.98
        else:  # WEAK
            multipliers["COMPASS"] = 0.75
            multipliers["Rattlesnake"] = 1.18
            multipliers["Catalyst"] = 0.85
            multipliers["EFA"] = 0.90

        # Ajustes por Special Modes (exact from SPEC 4.4.2)
        for mode in special_modes:
            if mode == "STRONG_BROAD_MOMENTUM":
                multipliers["COMPASS"] *= 1.18
                multipliers["Catalyst"] *= 0.60
                multipliers["EFA"] *= 0.65
            elif mode == "POST_CRISIS_RECOVERY":
                multipliers["COMPASS"] *= 1.08
                multipliers["Rattlesnake"] *= 0.95
            elif mode == "ELEVATED_VOL_DEFENSIVE":
                multipliers["Rattlesnake"] *= 1.15
                multipliers["COMPASS"] *= 0.92
            elif mode == "CRISIS_ACUTE":
                multipliers["COMPASS"] *= 0.80
                multipliers["Rattlesnake"] *= 0.95
                multipliers["Catalyst"] *= 0.75
                multipliers["EFA"] *= 0.80

        # Clamp final (mantener conservador) - SPEC 4.4.3
        for k in multipliers:
            multipliers[k] = round(max(0.60, min(1.45, multipliers[k])), 3)

        return MetaAdjustment(
            regime_score=regime_score,
            regime_type=regime_type,
            special_modes=special_modes,
            recovery_boost=round(recovery_boost, 3),
            overall_aggression=round(overall_aggression, 3),
            bias_compass=round(bias_compass, 3),
            bias_rattlesnake=round(bias_rattlesnake, 3),
            bias_catalyst=round(bias_catalyst, 3),
            pillar_multipliers=multipliers,
            risk_flags=list(set(risk_flags)),
            rationale=rationale
        )


def apply_meta_to_candidates(candidates_df, meta):
    """
    Aplica los ajustes de la Meta-Layer sobre el momentum.

    See SPEC 4.5 "Composite Score Assembly" and 4.4.

    IMPORTANTE (documentado 2026-09-05): `overall_aggression` y `pillar_factor` son el
    MISMO escalar positivo para todos los tickers del día. Un escalar positivo común no
    altera un orden, así que esta función NO cambia el ranking transversal — solo la
    escala de los scores. Verificado: Spearman = 1.000 entre el meta_score de un régimen
    STRONG y el de un WEAK.

    Lo que sí depende de la Meta-Layer es `dynamic_count` (vía aggression y compass_mult)
    y el flag de régimen, ambos en signals.generate_daily_candidates.

    Si algún día se quiere un tilt de estilo real (que el régimen reordene el universo),
    tiene que entrar aquí como peso POR TICKER, no como factor global. Se probó y no
    mejoró: ver SPEC 4.4 y .comms/claude-algo-deep-dive-2026-09-05.md.
    """
    df = candidates_df.copy()
    # Use 'momentum' (after rename in signals.py for SPEC column contract)
    # Fall back to 'momentum_score' for backward compatibility in direct calls
    mom_col = 'momentum' if 'momentum' in df.columns else 'momentum_score'
    base = df[mom_col] * meta.overall_aggression

    # === USO ACTIVO DE PILLAR MULTIPLIERS ===
    # Este screener es momentum-driven → el multiplicador de COMPASS es el más relevante.
    compass_mult = meta.pillar_multipliers.get("COMPASS", 1.0)

    if meta.regime_type == "STRONG" or "STRONG_BROAD_MOMENTUM" in meta.special_modes:
        pillar_factor = (compass_mult ** 0.85) * (meta.bias_compass ** 0.5)
    elif meta.regime_type in ["WEAK", "CAUTIOUS"] or "ELEVATED_VOL_DEFENSIVE" in meta.special_modes:
        pillar_factor = (compass_mult ** 0.6) * (meta.bias_rattlesnake ** 0.4) * 0.94
    else:
        pillar_factor = compass_mult ** 0.7

    final = base * pillar_factor

    df['meta_score'] = final.round(4)
    df['meta_regime'] = meta.regime_score
    df['meta_regime_type'] = meta.regime_type
    df['meta_special_modes'] = ", ".join(meta.special_modes) if meta.special_modes else ""
    df['meta_aggression'] = meta.overall_aggression
    df['compass_mult'] = round(compass_mult, 3)
    df['pillar_multipliers'] = str(meta.pillar_multipliers)
    df['meta_rationale'] = meta.rationale

    # Clean aliases for downstream consumers (display, screener main, history)
    df['aggression'] = meta.overall_aggression
    df['recovery_boost'] = meta.recovery_boost
    df['regime'] = meta.regime_score
    df['special_modes'] = df['meta_special_modes']

    df = df.sort_values('meta_score', ascending=False).reset_index(drop=True)
    df['rank'] = range(1, len(df) + 1)
    return df