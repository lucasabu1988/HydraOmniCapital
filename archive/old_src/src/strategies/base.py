"""
Clase base para estrategias de trading
Define la interfaz común para todas las estrategias
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import pandas as pd
import numpy as np


@dataclass
class StrategySignal:
    """Señal generada por una estrategia"""
    symbol: str
    action: str  # 'BUY', 'SELL', 'HOLD'
    strength: float  # 0.0 a 1.0
    timestamp: datetime
    strategy_name: str
    metadata: Dict[str, Any] = None
    target_weight: Optional[float] = None  # Para estrategias de allocación


@dataclass
class Allocation:
    """Allocación objetivo de una estrategia"""
    symbol: str
    weight: float
    expected_return: float
    expected_risk: float
    confidence: float


class BaseStrategy(ABC):
    """
    Clase base abstracta para todas las estrategias de trading.
    
    Toda estrategia debe implementar:
    - generate_signals(): Generar señales de trading
    - calculate_allocations(): Calcular allocaciones objetivo (opcional)
    - get_required_data(): Especificar datos necesarios
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.name = config.get('name', self.__class__.__name__)
        self.description = config.get('description', '')
        self.lookback_period = config.get('lookback_period', 252)
        self.rebalance_frequency = config.get('rebalance_frequency', 'monthly')
        
        # Estado interno
        self.signals_history: List[StrategySignal] = []
        self.allocations_history: List[Dict[str, Allocation]] = []
        self.last_rebalance: Optional[datetime] = None
        
    @abstractmethod
    def generate_signals(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None,
        current_portfolio: Optional[Dict] = None
    ) -> List[StrategySignal]:
        """
        Genera señales de trading basadas en los datos proporcionados.
        
        Args:
            prices: DataFrame con precios históricos
            fundamentals: Datos fundamentales opcionales
            current_portfolio: Estado actual del portafolio
            
        Returns:
            Lista de señales de trading
        """
        pass
    
    def calculate_allocations(
        self,
        prices: pd.DataFrame,
        signals: List[StrategySignal],
        risk_budget: Optional[float] = None
    ) -> Dict[str, Allocation]:
        """
        Calcula allocaciones objetivo basadas en las señales.
        
        Args:
            prices: DataFrame con precios históricos
            signals: Señales generadas
            risk_budget: Presupuesto de riesgo opcional
            
        Returns:
            Diccionario de allocaciones por símbolo
        """
        # Implementación por defecto: equal weight para señales BUY
        buy_signals = [s for s in signals if s.action == 'BUY']
        
        if not buy_signals:
            return {}
        
        weight = 1.0 / len(buy_signals)
        allocations = {}
        
        for signal in buy_signals:
            allocations[signal.symbol] = Allocation(
                symbol=signal.symbol,
                weight=weight,
                expected_return=0.0,
                expected_risk=0.0,
                confidence=signal.strength
            )
        
        return allocations
    
    def get_required_data(self) -> Dict[str, Any]:
        """
        Especifica los datos requeridos por la estrategia.
        
        Returns:
            Diccionario con requerimientos de datos
        """
        return {
            'prices': True,
            'volumes': False,
            'fundamentals': False,
            'market_data': False,
            'lookback_days': self.lookback_period
        }
    
    def should_rebalance(self, current_date: datetime) -> bool:
        """
        Determina si es momento de rebalancear según la frecuencia configurada.
        
        Args:
            current_date: Fecha actual
            
        Returns:
            True si se debe rebalancear
        """
        if self.last_rebalance is None:
            return True
        
        delta = current_date - self.last_rebalance
        
        if self.rebalance_frequency == 'daily':
            return delta.days >= 1
        elif self.rebalance_frequency == 'weekly':
            return delta.days >= 7
        elif self.rebalance_frequency == 'monthly':
            return delta.days >= 30
        elif self.rebalance_frequency == 'quarterly':
            return delta.days >= 90
        
        return False
    
    def calculate_returns(self, prices: pd.DataFrame) -> pd.DataFrame:
        """Calcula retornos logarítmicos"""
        return np.log(prices / prices.shift(1)).dropna()
    
    def calculate_volatility(self, prices: pd.DataFrame, annualize: bool = True) -> pd.Series:
        """Calcula volatilidad histórica"""
        returns = self.calculate_returns(prices)
        vol = returns.std()
        
        if annualize:
            vol = vol * np.sqrt(252)
        
        return vol
    
    def calculate_momentum(self, prices: pd.DataFrame, lookback: int = 252) -> pd.Series:
        """Calcula momentum como retorno total del período"""
        return (prices.iloc[-1] / prices.iloc[-min(lookback, len(prices))]) - 1
    
    def filter_liquid_stocks(
        self,
        prices: pd.DataFrame,
        volumes: Optional[pd.DataFrame] = None,
        min_price: float = 5.0,
        min_volume: Optional[float] = None
    ) -> List[str]:
        """
        Filtra stocks por liquidez.
        
        Args:
            prices: DataFrame de precios
            volumes: DataFrame de volúmenes opcional
            min_price: Precio mínimo
            min_volume: Volumen mínimo promedio
            
        Returns:
            Lista de símbolos que pasan el filtro
        """
        valid_symbols = []
        
        for col in prices.columns:
            recent_prices = prices[col].dropna().tail(20)
            
            if len(recent_prices) < 10:
                continue
            
            if recent_prices.mean() < min_price:
                continue
            
            if volumes is not None and min_volume is not None:
                if col in volumes.columns:
                    avg_volume = volumes[col].dropna().tail(20).mean()
                    if avg_volume < min_volume:
                        continue
            
            valid_symbols.append(col)
        
        return valid_symbols
    
    def record_signal(self, signal: StrategySignal):
        """Registra una señal en el historial"""
        self.signals_history.append(signal)
    
    def record_allocations(self, allocations: Dict[str, Allocation]):
        """Registra allocaciones en el historial"""
        self.allocations_history.append(allocations)
        self.last_rebalance = datetime.now()
    
    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Genera un resumen de performance de la estrategia.
        
        Returns:
            Diccionario con métricas de performance
        """
        if not self.signals_history:
            return {
                'total_signals': 0,
                'win_rate': 0.0,
                'avg_strength': 0.0
            }
        
        buy_signals = [s for s in self.signals_history if s.action == 'BUY']
        sell_signals = [s for s in self.signals_history if s.action == 'SELL']
        
        return {
            'total_signals': len(self.signals_history),
            'buy_signals': len(buy_signals),
            'sell_signals': len(sell_signals),
            'avg_strength': np.mean([s.strength for s in self.signals_history]),
            'rebalances': len(self.allocations_history)
        }