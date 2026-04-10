"""
Motor de Estrategias Múltiples (Multi-Strategy Engine)

Combina múltiples estrategias usando:
- Ensemble voting
- Regime detection
- Dynamic allocation entre estrategias
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import dataclass

from .base import BaseStrategy, StrategySignal, Allocation


@dataclass
class StrategyPerformance:
    """Performance de una estrategia"""
    strategy_name: str
    total_return: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    volatility: float
    score: float  # Composite score


class MultiStrategyEngine:
    """
    Motor que combina múltiples estrategias de trading.
    
    Features:
    - Ensemble de señales de múltiples estrategias
    - Detección de régimen de mercado
    - Asignación dinámica de capital entre estrategias
    - Risk management a nivel de estrategia
    
    Config:
        strategies: Lista de instancias de estrategias
        ensemble_method: 'voting', 'weighted', 'regime_based'
        strategy_weights: Pesos iniciales de cada estrategia
        rebalance_frequency: Frecuencia de rebalanceo
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.strategies: Dict[str, BaseStrategy] = {}
        self.ensemble_method = config.get('ensemble_method', 'weighted')
        self.strategy_weights = config.get('strategy_weights', {})
        self.rebalance_frequency = config.get('rebalance_frequency', 'monthly')
        
        # Estado
        self.performance_history: Dict[str, List[StrategyPerformance]] = {}
        self.current_regime: str = 'unknown'
        self.last_rebalance: Optional[datetime] = None
        
    def add_strategy(self, name: str, strategy: BaseStrategy, weight: float = 1.0):
        """Añade una estrategia al motor"""
        self.strategies[name] = strategy
        if name not in self.strategy_weights:
            self.strategy_weights[name] = weight
        self.performance_history[name] = []
    
    def generate_composite_signals(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None,
        market_regime: Optional[str] = None
    ) -> List[StrategySignal]:
        """
        Genera señales compuestas de todas las estrategias.
        
        Args:
            prices: DataFrame de precios
            fundamentals: Datos fundamentales
            market_regime: Régimen de mercado detectado (opcional)
            
        Returns:
            Lista de señales compuestas
        """
        all_signals: Dict[str, List[StrategySignal]] = {}
        
        # Generar señales de cada estrategia
        for name, strategy in self.strategies.items():
            try:
                signals = strategy.generate_signals(prices, fundamentals)
                all_signals[name] = signals
            except Exception as e:
                print(f"Error en estrategia {name}: {e}")
                all_signals[name] = []
        
        # Combinar señales según método
        if self.ensemble_method == 'voting':
            return self._ensemble_voting(all_signals, prices)
        elif self.ensemble_method == 'weighted':
            return self._ensemble_weighted(all_signals, prices)
        elif self.ensemble_method == 'regime_based':
            return self._ensemble_regime_based(all_signals, prices, market_regime)
        else:
            return self._ensemble_simple(all_signals)
    
    def _ensemble_voting(
        self,
        all_signals: Dict[str, List[StrategySignal]],
        prices: pd.DataFrame
    ) -> List[StrategySignal]:
        """
        Ensemble por votación mayoritaria.
        Una señal se genera si la mayoría de estrategias están de acuerdo.
        """
        # Agrupar señales por símbolo
        symbol_votes: Dict[str, Dict[str, List[float]]] = {}
        
        for strategy_name, signals in all_signals.items():
            for signal in signals:
                symbol = signal.symbol
                if symbol not in symbol_votes:
                    symbol_votes[symbol] = {'BUY': [], 'SELL': [], 'HOLD': []}
                symbol_votes[symbol][signal.action].append(
                    signal.strength * self.strategy_weights.get(strategy_name, 1.0)
                )
        
        # Generar señales compuestas
        composite_signals = []
        
        for symbol, votes in symbol_votes.items():
            total_buy = sum(votes['BUY'])
            total_sell = sum(votes['SELL'])
            
            if total_buy > total_sell and len(votes['BUY']) >= len(self.strategies) / 3:
                action = 'BUY'
                strength = min(1.0, total_buy / sum(self.strategy_weights.values()))
            elif total_sell > total_buy and len(votes['SELL']) >= len(self.strategies) / 3:
                action = 'SELL'
                strength = min(1.0, total_sell / sum(self.strategy_weights.values()))
            else:
                continue
            
            composite_signals.append(StrategySignal(
                symbol=symbol,
                action=action,
                strength=strength,
                timestamp=prices.index[-1],
                strategy_name='MultiStrategy_Ensemble',
                metadata={
                    'buy_votes': len(votes['BUY']),
                    'sell_votes': len(votes['SELL']),
                    'buy_strength': total_buy,
                    'sell_strength': total_sell
                }
            ))
        
        return composite_signals
    
    def _ensemble_weighted(
        self,
        all_signals: Dict[str, List[StrategySignal]],
        prices: pd.DataFrame
    ) -> List[StrategySignal]:
        """
        Ensemble ponderado por pesos de estrategias.
        """
        symbol_scores: Dict[str, float] = {}
        symbol_metadata: Dict[str, Dict] = {}
        
        for strategy_name, signals in all_signals.items():
            weight = self.strategy_weights.get(strategy_name, 1.0)
            
            for signal in signals:
                symbol = signal.symbol
                
                if symbol not in symbol_scores:
                    symbol_scores[symbol] = 0
                    symbol_metadata[symbol] = {'strategies': []}
                
                # +1 para BUY, -1 para SELL
                direction = 1 if signal.action == 'BUY' else -1
                symbol_scores[symbol] += direction * signal.strength * weight
                symbol_metadata[symbol]['strategies'].append(strategy_name)
        
        # Generar señales
        composite_signals = []
        
        for symbol, score in symbol_scores.items():
            if abs(score) < 0.3:  # Umbral mínimo
                continue
            
            action = 'BUY' if score > 0 else 'SELL'
            strength = min(1.0, abs(score))
            
            composite_signals.append(StrategySignal(
                symbol=symbol,
                action=action,
                strength=strength,
                timestamp=prices.index[-1],
                strategy_name='MultiStrategy_Weighted',
                metadata={
                    'composite_score': score,
                    'contributing_strategies': symbol_metadata[symbol]['strategies']
                }
            ))
        
        return composite_signals
    
    def _ensemble_regime_based(
        self,
        all_signals: Dict[str, List[StrategySignal]],
        prices: pd.DataFrame,
        market_regime: Optional[str] = None
    ) -> List[StrategySignal]:
        """
        Ensemble basado en régimen de mercado.
        Ajusta pesos según el régimen detectado.
        """
        if market_regime is None:
            market_regime = self._detect_market_regime(prices)
        
        # Pesos por régimen
        regime_weights = {
            'bull': {
                'DualMomentumStrategy': 1.5,
                'FactorInvestingStrategy': 1.2,
                'TurtleStrategy': 1.3,
                'MeanReversionStrategy': 0.5,
                'PairsTradingStrategy': 0.8
            },
            'bear': {
                'RiskParityStrategy': 1.5,
                'MinimumVarianceStrategy': 1.4,
                'MeanReversionStrategy': 1.2,
                'DualMomentumStrategy': 0.5,
                'TurtleStrategy': 0.8
            },
            'range': {
                'MeanReversionStrategy': 1.5,
                'PairsTradingStrategy': 1.3,
                'RiskParityStrategy': 1.1,
                'TurtleStrategy': 0.6,
                'DualMomentumStrategy': 0.8
            },
            'volatile': {
                'RiskParityStrategy': 1.4,
                'MinimumVarianceStrategy': 1.3,
                'InverseVolatilityStrategy': 1.2,
                'TurtleStrategy': 0.7,
                'DualMomentumStrategy': 0.6
            }
        }
        
        # Aplicar pesos del régimen
        adjusted_weights = self.strategy_weights.copy()
        if market_regime in regime_weights:
            for strategy_name, weight in regime_weights[market_regime].items():
                if strategy_name in adjusted_weights:
                    adjusted_weights[strategy_name] *= weight
        
        # Normalizar pesos
        total = sum(adjusted_weights.values())
        if total > 0:
            adjusted_weights = {k: v/total for k, v in adjusted_weights.items()}
        
        # Usar ensemble ponderado con pesos ajustados
        original_weights = self.strategy_weights
        self.strategy_weights = adjusted_weights
        signals = self._ensemble_weighted(all_signals, prices)
        self.strategy_weights = original_weights
        
        # Agregar metadata del régimen
        for signal in signals:
            signal.metadata['market_regime'] = market_regime
        
        return signals
    
    def _ensemble_simple(
        self,
        all_signals: Dict[str, List[StrategySignal]]
    ) -> List[StrategySignal]:
        """Simplemente concatena todas las señales"""
        signals = []
        for strategy_signals in all_signals.values():
            signals.extend(strategy_signals)
        return signals
    
    def _detect_market_regime(self, prices: pd.DataFrame) -> str:
        """
        Detecta el régimen actual del mercado.
        
        Retorna: 'bull', 'bear', 'range', 'volatile'
        """
        if 'SPY' in prices.columns:
            benchmark = prices['SPY']
        else:
            benchmark = prices.iloc[:, 0]
        
        # Calcular métricas
        returns = benchmark.pct_change().dropna()
        
        if len(returns) < 50:
            return 'unknown'
        
        # Tendencia (SMA 50 vs SMA 200)
        sma_50 = benchmark.tail(50).mean()
        sma_200 = benchmark.tail(200).mean() if len(benchmark) >= 200 else sma_50
        
        # Volatilidad (anualizada)
        vol = returns.tail(50).std() * np.sqrt(252)
        
        # Momentum (3 meses)
        momentum = (benchmark.iloc[-1] / benchmark.iloc[-min(63, len(benchmark))]) - 1
        
        # Clasificar
        if momentum > 0.05 and sma_50 > sma_200 and vol < 0.20:
            return 'bull'
        elif momentum < -0.05 and sma_50 < sma_200:
            return 'bear'
        elif vol > 0.25:
            return 'volatile'
        else:
            return 'range'
    
    def update_strategy_weights(self, performance_window: int = 63):
        """
        Actualiza pesos de estrategias basado en performance reciente.
        
        Usa un approach de momentum de performance.
        """
        # Calcular score de cada estrategia
        strategy_scores = {}
        
        for name, history in self.performance_history.items():
            if len(history) < 5:
                strategy_scores[name] = 1.0
                continue
            
            recent = history[-5:]
            avg_return = np.mean([p.total_return for p in recent])
            avg_sharpe = np.mean([p.sharpe_ratio for p in recent])
            avg_drawdown = np.mean([p.max_drawdown for p in recent])
            
            # Score compuesto
            score = (avg_return * 0.4 + avg_sharpe * 0.4 - abs(avg_drawdown) * 0.2)
            strategy_scores[name] = max(0.1, score + 1)  # Evitar negativos
        
        # Normalizar a pesos
        total = sum(strategy_scores.values())
        if total > 0:
            self.strategy_weights = {k: v/total for k, v in strategy_scores.items()}
    
    def get_strategy_summary(self) -> Dict[str, Any]:
        """Genera resumen de todas las estrategias"""
        summary = {
            'strategies': list(self.strategies.keys()),
            'weights': self.strategy_weights,
            'ensemble_method': self.ensemble_method,
            'current_regime': self.current_regime,
            'performance': {}
        }
        
        for name, history in self.performance_history.items():
            if history:
                latest = history[-1]
                summary['performance'][name] = {
                    'total_return': latest.total_return,
                    'sharpe_ratio': latest.sharpe_ratio,
                    'max_drawdown': latest.max_drawdown,
                    'score': latest.score
                }
        
        return summary