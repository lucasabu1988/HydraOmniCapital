"""
Módulo Core - Motor principal del algoritmo
"""

from .portfolio import Portfolio, RebalancingEngine
from .engine import TradingEngine

__all__ = ["Portfolio", "RebalancingEngine", "TradingEngine"]
