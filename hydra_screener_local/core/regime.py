"""
Rich Regime Scoring (5 sub-dimensions)

Implements section 4.3 of HYDRA_ALGORITHM_SPEC.md (v1.2)

Exact weights and formulas from the formal spec:
- Trend 30%
- Momentum 25%
- Volatility 20%
- Drawdown Velocity 15%
- Breadth Proxy 10%

Returns RegimeScores dataclass with overall + subscores.
This is the reference implementation.
"""
import pandas as pd
import numpy as np
from dataclasses import dataclass
from typing import Dict


@dataclass
class RegimeScores:
    """Versión ligera pero útil de los scores de régimen."""
    overall: float
    trend: float
    volatility: float
    momentum: float
    drawdown_velocity: float
    breadth_proxy: float


def compute_rich_regime_scores(
    spy: pd.Series,
    prices: pd.DataFrame = None,   # precios de todo el universo (para breadth)
    lookback: int = 200
) -> RegimeScores:
    """
    Calcula un conjunto más completo de métricas de régimen.
    """
    if len(spy) < lookback:
        return RegimeScores(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)

    current = float(spy.iloc[-1])

    # SPEC 4.3 - Exact sub-scores and weights from the formal spec
    # 1. Trend (30% weight)
    sma200 = float(spy.rolling(lookback).mean().iloc[-1])
    trend_strength = 1.0 if current > sma200 else 0.0
    
    # Pendiente de 20 días normalizada
    ret_20 = (current / float(spy.iloc[-20]) - 1) if len(spy) >= 20 else 0
    trend_strength = (trend_strength * 0.6) + (np.clip(ret_20 + 0.04, -0.1, 0.15) / 0.15 * 0.4)

    # 2. Volatility Regime (20% weight)
    vol_20 = float(spy.pct_change().rolling(20).std().iloc[-1]) * np.sqrt(252)
    vol_200 = float(spy.pct_change().rolling(lookback).std().iloc[-1]) * np.sqrt(252)
    vol_ratio = vol_20 / max(vol_200, 0.01)
    volatility_score = np.clip(1 - (vol_ratio - 0.8) / 1.2, 0, 1)  # menor = mejor (menos vol)

    # 3. Momentum Strength (25% weight)
    ret_60 = (current / float(spy.iloc[-60]) - 1) if len(spy) >= 60 else 0
    momentum_score = np.clip((ret_20 * 0.6 + ret_60 * 0.4 + 0.05) / 0.20, 0, 1)

    # 4. Drawdown Velocity (15% weight)
    rolling_max = float(spy.rolling(60).max().iloc[-1])
    current_dd = max(0.0, (rolling_max - current) / rolling_max)
    dd_20d_ago = max(0.0, (rolling_max - float(spy.iloc[-20])) / rolling_max) if len(spy) >= 20 else current_dd
    velocity = max(0.0, current_dd - dd_20d_ago) / 20.0   # velocidad promedio por día
    velocity_score = 1.0 - np.clip(velocity * 40, 0, 1)    # alta velocidad = peor

    # 5. Breadth Proxy (10% weight, optional)
    breadth_score = 0.5
    if prices is not None and len(prices.columns) > 30:
        try:
            above_sma50 = (prices.iloc[-1] > prices.rolling(50).mean().iloc[-1]).mean()
            above_sma200 = (prices.iloc[-1] > prices.rolling(200).mean().iloc[-1]).mean()
            breadth_score = (above_sma50 * 0.4 + above_sma200 * 0.6)
        except:
            breadth_score = 0.5

    # Score general (ponderado) - exact weights from SPEC 4.3
    overall = (
        trend_strength * 0.30 +
        momentum_score * 0.25 +
        volatility_score * 0.20 +
        velocity_score * 0.15 +
        breadth_score * 0.10
    )

    return RegimeScores(
        overall=round(float(np.clip(overall, 0, 1)), 3),
        trend=round(float(trend_strength), 3),
        volatility=round(float(volatility_score), 3),
        momentum=round(float(momentum_score), 3),
        drawdown_velocity=round(float(velocity_score), 3),
        breadth_proxy=round(float(breadth_score), 3)
    )