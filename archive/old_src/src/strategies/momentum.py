"""
Estrategias de Momentum Avanzadas

Basadas en:
- Antonacci, G. (2014). Dual Momentum Investing
- Moskowitz, T.J. & Grinblatt, M. (1999). Do Industries Explain Momentum?
- Asness, C.S. (1997). The Interaction of Value and Momentum
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime

from .base import BaseStrategy, StrategySignal, Allocation


class DualMomentumStrategy(BaseStrategy):
    """
    Estrategia de Dual Momentum de Gary Antonacci.
    
    Combina:
    1. Relative Momentum: Comparar performance vs otros activos
    2. Absolute Momentum: Comparar performance vs Treasury Bills (tasa libre de riesgo)
    
    Config:
        lookback_months: Período de lookback para momentum (default: 12)
        risk_free_rate: Tasa libre de riesgo anual (default: 0.02)
        top_n: Número de activos a seleccionar (default: 5)
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.lookback_months = config.get('lookback_months', 12)
        self.risk_free_rate = config.get('risk_free_rate', 0.02)
        self.top_n = config.get('top_n', 5)
        self.abs_threshold = config.get('abs_threshold', 0.0)  # Umbral de momentum absoluto
        
    def generate_signals(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None,
        current_portfolio: Optional[Dict] = None
    ) -> List[StrategySignal]:
        """
        Genera señales usando Dual Momentum.
        
        Lógica:
        1. Calcular momentum relativo (ranking por retorno)
        2. Calcular momentum absoluto (vs risk-free rate)
        3. Seleccionar top N con momentum absoluto positivo
        """
        signals = []
        
        # Período de lookback en días (aproximado)
        lookback_days = self.lookback_months * 21
        
        if len(prices) < lookback_days:
            return signals
        
        # Calcular retornos del período
        momentum = self.calculate_momentum(prices, lookback_days)
        
        # Momentum absoluto: comparar con risk-free rate
        rf_return = self.risk_free_rate * (lookback_days / 252)
        
        # Filtrar solo activos con momentum absoluto positivo
        positive_momentum = momentum[momentum > (self.abs_threshold + rf_return)]
        
        if len(positive_momentum) == 0:
            return signals
        
        # Ranking por momentum relativo
        ranked = positive_momentum.sort_values(ascending=False)
        
        # Generar señales para top N
        for i, (symbol, mom_value) in enumerate(ranked.head(self.top_n).items()):
            # Strength basado en ranking y magnitud del momentum
            rank_score = 1.0 - (i / self.top_n)
            mom_score = min(1.0, mom_value / 0.5)  # Normalizar
            strength = (rank_score + mom_score) / 2
            
            signal = StrategySignal(
                symbol=symbol,
                action='BUY',
                strength=strength,
                timestamp=prices.index[-1],
                strategy_name=self.name,
                metadata={
                    'momentum_12m': mom_value,
                    'rank': i + 1,
                    'relative_momentum': True,
                    'absolute_momentum': mom_value > rf_return
                }
            )
            signals.append(signal)
            self.record_signal(signal)
        
        return signals
    
    def calculate_allocations(
        self,
        prices: pd.DataFrame,
        signals: List[StrategySignal],
        risk_budget: Optional[float] = None
    ) -> Dict[str, Allocation]:
        """
        Asigna pesos basados en momentum relativo.
        Más momentum = mayor peso.
        """
        if not signals:
            return {}
        
        allocations = {}
        total_momentum = sum(s.metadata['momentum_12m'] for s in signals)
        
        for signal in signals:
            # Peso proporcional al momentum
            if total_momentum > 0:
                weight = signal.metadata['momentum_12m'] / total_momentum
            else:
                weight = 1.0 / len(signals)
            
            # Ajustar por strength de la señal
            weight = weight * signal.strength
            
            allocations[signal.symbol] = Allocation(
                symbol=signal.symbol,
                weight=weight,
                expected_return=signal.metadata['momentum_12m'],
                expected_risk=self.calculate_volatility(prices[[signal.symbol]]).iloc[0],
                confidence=signal.strength
            )
        
        # Normalizar para que sumen 1
        total_weight = sum(a.weight for a in allocations.values())
        if total_weight > 0:
            for alloc in allocations.values():
                alloc.weight /= total_weight
        
        self.record_allocations(allocations)
        return allocations


class RelativeStrengthStrategy(BaseStrategy):
    """
    Estrategia de Relative Strength (RS).
    
    Selecciona activos con mayor relative strength vs un benchmark.
    Similar a ETFs como MTUM (iShares MSCI USA Momentum Factor).
    
    Config:
        lookback_months: Períodos para calcular RS (default: [3, 6, 12])
        weights: Pesos para cada período (default: [0.4, 0.3, 0.3])
        top_n: Número de activos a seleccionar (default: 10)
        benchmark: Símbolo del benchmark (default: 'SPY')
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.lookback_months = config.get('lookback_months', [3, 6, 12])
        self.weights = config.get('weights', [0.4, 0.3, 0.3])
        self.top_n = config.get('top_n', 10)
        self.benchmark = config.get('benchmark', 'SPY')
        
    def generate_signals(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None,
        current_portfolio: Optional[Dict] = None
    ) -> List[StrategySignal]:
        """
        Genera señales basadas en Relative Strength ponderado.
        """
        signals = []
        
        # Verificar que tenemos el benchmark
        if self.benchmark not in prices.columns:
            return signals
        
        # Calcular RS score ponderado
        rs_scores = pd.Series(0.0, index=prices.columns)
        
        for months, weight in zip(self.lookback_months, self.weights):
            days = months * 21
            if len(prices) >= days:
                # Retorno del activo
                asset_return = (prices.iloc[-1] / prices.iloc[-days]) - 1
                # Retorno del benchmark
                bench_return = (prices[self.benchmark].iloc[-1] / 
                               prices[self.benchmark].iloc[-days]) - 1
                
                # Relative strength = exceso de retorno vs benchmark
                rs = asset_return - bench_return
                rs_scores += rs * weight
        
        # Ranking por RS
        ranked = rs_scores.sort_values(ascending=False)
        
        # Generar señales para top N
        for i, (symbol, rs_value) in enumerate(ranked.head(self.top_n).items()):
            if symbol == self.benchmark:
                continue
                
            strength = min(1.0, max(0.0, 0.5 + rs_value))
            
            signal = StrategySignal(
                symbol=symbol,
                action='BUY',
                strength=strength,
                timestamp=prices.index[-1],
                strategy_name=self.name,
                metadata={
                    'rs_score': rs_value,
                    'rank': i + 1
                }
            )
            signals.append(signal)
            self.record_signal(signal)
        
        return signals
    
    def calculate_allocations(
        self,
        prices: pd.DataFrame,
        signals: List[StrategySignal],
        risk_budget: Optional[float] = None
    ) -> Dict[str, Allocation]:
        """
        Equal weight con ajuste por volatilidad (risk parity simplificado).
        """
        if not signals:
            return {}
        
        allocations = {}
        symbols = [s.symbol for s in signals]
        
        # Calcular volatilidades
        vols = self.calculate_volatility(prices[symbols])
        inverse_vols = 1 / vols
        
        for signal in signals:
            symbol = signal.symbol
            # Peso inverso a la volatilidad
            weight = (inverse_vols[symbol] / inverse_vols.sum()) * signal.strength
            
            allocations[symbol] = Allocation(
                symbol=symbol,
                weight=weight,
                expected_return=signal.metadata['rs_score'],
                expected_risk=vols[symbol],
                confidence=signal.strength
            )
        
        # Normalizar
        total_weight = sum(a.weight for a in allocations.values())
        if total_weight > 0:
            for alloc in allocations.values():
                alloc.weight /= total_weight
        
        self.record_allocations(allocations)
        return allocations


class TimeSeriesMomentumStrategy(BaseStrategy):
    """
    Estrategia de Time Series Momentum (TSMOM).
    
    Basada en:
    Moskowitz, T.J., Grinblatt, M., & Pedersen, L.H. (2012)
    "Time Series Momentum"
    
    Va largo en activos con momentum positivo,
    corto en activos con momentum negativo.
    
    Config:
        lookback_months: Período de lookback (default: 12)
        vol_target: Volatilidad objetivo anualizada (default: 0.10)
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.lookback_months = config.get('lookback_months', 12)
        self.vol_target = config.get('vol_target', 0.10)
        self.max_leverage = config.get('max_leverage', 2.0)
        
    def generate_signals(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None,
        current_portfolio: Optional[Dict] = None
    ) -> List[StrategySignal]:
        """
        Genera señales long/short basadas en signo del momentum.
        """
        signals = []
        lookback_days = self.lookback_months * 21
        
        if len(prices) < lookback_days:
            return signals
        
        # Calcular momentum
        momentum = self.calculate_momentum(prices, lookback_days)
        
        # Calcular volatilidades para sizing
        vols = self.calculate_volatility(prices)
        
        for symbol in prices.columns:
            mom = momentum[symbol]
            vol = vols[symbol]
            
            if pd.isna(mom) or pd.isna(vol) or vol == 0:
                continue
            
            # Señal basada en signo del momentum
            if mom > 0:
                action = 'BUY'
                strength = min(1.0, abs(mom) / 0.3)
            else:
                action = 'SELL'
                strength = min(1.0, abs(mom) / 0.3)
            
            # Volatility scaling
            vol_scale = self.vol_target / vol if vol > 0 else 1.0
            vol_scale = min(vol_scale, self.max_leverage)
            
            signal = StrategySignal(
                symbol=symbol,
                action=action,
                strength=strength,
                timestamp=prices.index[-1],
                strategy_name=self.name,
                metadata={
                    'momentum': mom,
                    'volatility': vol,
                    'vol_scale': vol_scale
                },
                target_weight=vol_scale * (1 if action == 'BUY' else -1)
            )
            signals.append(signal)
            self.record_signal(signal)
        
        return signals