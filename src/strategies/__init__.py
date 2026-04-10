"""
Módulo de Estrategias de Trading Avanzadas

Este módulo contiene implementaciones de estrategias cuantitativas
basadas en investigación académica y práctica profesional.

Estrategias incluidas:
- momentum: Dual Momentum, Relative Strength, Time Series Momentum
- factor: Factor Investing (Value, Quality, Low Vol, Size, Momentum)
- risk_parity: Risk Parity, Inverse Volatility, Min Variance
- mean_reversion: Pairs Trading, Statistical Arbitrage, Mean Reversion
- trend_following: Donchian Channels, Turtle Trading, Trend Following
- ml: Machine Learning (Random Forest, XGBoost, LSTM)
"""

from .momentum import DualMomentumStrategy, RelativeStrengthStrategy
from .factor import FactorInvestingStrategy
from .risk_parity import RiskParityStrategy, MinimumVarianceStrategy
from .mean_reversion import PairsTradingStrategy, MeanReversionStrategy
from .trend_following import TurtleStrategy, DonchianStrategy

__all__ = [
    'DualMomentumStrategy',
    'RelativeStrengthStrategy', 
    'FactorInvestingStrategy',
    'RiskParityStrategy',
    'MinimumVarianceStrategy',
    'PairsTradingStrategy',
    'MeanReversionStrategy',
    'TurtleStrategy',
    'DonchianStrategy',
]