"""
Generador de Señales Compuestas
Combina señales técnicas y fundamentales para generar decisiones finales
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime

from .technical import TechnicalSignals, SignalType
from .fundamental import FundamentalSignals, FundamentalMetrics, FundamentalScore


@dataclass
class CompositeSignal:
    """Señal compuesta final"""
    symbol: str
    action: str  # 'BUY', 'SELL', 'HOLD'
    confidence: float  # 0.0 a 1.0
    technical_score: float
    fundamental_score: float
    risk_score: float
    timestamp: datetime
    reasoning: Dict[str, Any]


class CompositeSignalGenerator:
    """
    Genera señales de trading combinando múltiples factores
    """
    
    def __init__(
        self,
        technical_config: Dict[str, Any],
        fundamental_config: Dict[str, Any],
        weights: Optional[Dict[str, float]] = None
    ):
        self.technical_signals = TechnicalSignals(technical_config)
        self.fundamental_signals = FundamentalSignals(fundamental_config)
        
        # Pesos por defecto
        self.weights = weights or {
            'technical': 0.35,
            'fundamental': 0.35,
            'risk': 0.20,
            'momentum': 0.10
        }
    
    def generate_signal(
        self,
        symbol: str,
        prices: pd.Series,
        metrics: Optional[FundamentalMetrics] = None,
        market_regime: str = 'neutral'
    ) -> CompositeSignal:
        """
        Genera señal compuesta para un activo
        
        Args:
            symbol: Símbolo del activo
            prices: Serie de precios históricos
            metrics: Métricas fundamentales (opcional)
            market_regime: Régimen de mercado actual
            
        Returns:
            CompositeSignal con decisión final
        """
        # Análisis técnico
        tech_analysis = self.technical_signals.analyze_all_signals(symbol, prices)
        technical_score = self._normalize_technical_score(tech_analysis)
        
        # Análisis fundamental
        if metrics:
            fund_result = self.fundamental_signals.generate_fundamental_signal(metrics)
            fundamental_score = fund_result['composite_score']
        else:
            fundamental_score = 0.5
            fund_result = {}
        
        # Calcular score de riesgo (basado en volatilidad)
        risk_score = self._calculate_risk_score(prices)
        
        # Ajustar pesos según régimen de mercado
        adjusted_weights = self._adjust_weights_for_regime(market_regime)
        
        # Score compuesto
        composite_score = (
            technical_score * adjusted_weights['technical'] +
            fundamental_score * adjusted_weights['fundamental'] +
            risk_score * adjusted_weights['risk']
        )
        
        # Determinar acción
        action, confidence = self._determine_action(
            composite_score,
            technical_score,
            fundamental_score,
            tech_analysis
        )
        
        return CompositeSignal(
            symbol=symbol,
            action=action,
            confidence=confidence,
            technical_score=technical_score,
            fundamental_score=fundamental_score,
            risk_score=risk_score,
            timestamp=datetime.now(),
            reasoning={
                'technical_analysis': tech_analysis,
                'fundamental_analysis': fund_result,
                'composite_score': composite_score,
                'weights_used': adjusted_weights,
                'market_regime': market_regime
            }
        )
    
    def _normalize_technical_score(self, tech_analysis: Dict[str, Any]) -> float:
        """Normaliza el score técnico a escala 0-1"""
        final_signal = tech_analysis.get('final_signal', SignalType.HOLD)
        strength = tech_analysis.get('final_strength', 0.0)
        
        if final_signal == SignalType.BUY:
            return 0.5 + (strength * 0.5)  # 0.5 a 1.0
        elif final_signal == SignalType.SELL:
            return 0.5 - (strength * 0.5)  # 0.0 a 0.5
        else:
            return 0.5
    
    def _calculate_risk_score(self, prices: pd.Series) -> float:
        """
        Calcula score de riesgo basado en volatilidad
        Mayor volatilidad = menor score
        """
        returns = prices.pct_change().dropna()
        if len(returns) < 20:
            return 0.5
        
        volatility = returns.std() * np.sqrt(252)
        
        # Normalizar: volatilidad baja = score alto
        if volatility < 0.15:
            return 0.9
        elif volatility < 0.25:
            return 0.7
        elif volatility < 0.35:
            return 0.5
        elif volatility < 0.50:
            return 0.3
        else:
            return 0.1
    
    def _adjust_weights_for_regime(self, regime: str) -> Dict[str, float]:
        """Ajusta pesos según el régimen de mercado"""
        weights = self.weights.copy()
        
        if regime == 'bull':
            # En mercado alcista, dar más peso a momentum técnico
            weights['technical'] = 0.45
            weights['fundamental'] = 0.30
            weights['risk'] = 0.15
            weights['momentum'] = 0.10
        elif regime == 'bear':
            # En mercado bajista, dar más peso a calidad fundamental y riesgo
            weights['technical'] = 0.25
            weights['fundamental'] = 0.40
            weights['risk'] = 0.25
            weights['momentum'] = 0.10
        elif regime == 'volatile':
            # En volatilidad alta, priorizar gestión de riesgo
            weights['technical'] = 0.25
            weights['fundamental'] = 0.25
            weights['risk'] = 0.40
            weights['momentum'] = 0.10
        
        return weights
    
    def _determine_action(
        self,
        composite_score: float,
        technical_score: float,
        fundamental_score: float,
        tech_analysis: Dict[str, Any]
    ) -> tuple:
        """Determina la acción final y su confianza"""
        
        # Thresholds para decisión
        strong_buy_threshold = 0.75
        buy_threshold = 0.60
        sell_threshold = 0.40
        strong_sell_threshold = 0.25
        
        # Verificar alineación de señales
        signals_aligned = (
            (technical_score > 0.6 and fundamental_score > 0.6) or
            (technical_score < 0.4 and fundamental_score < 0.4)
        )
        
        if composite_score >= strong_buy_threshold:
            action = 'BUY'
            confidence = min(1.0, composite_score + (0.1 if signals_aligned else 0))
        elif composite_score >= buy_threshold:
            action = 'BUY'
            confidence = composite_score
        elif composite_score <= strong_sell_threshold:
            action = 'SELL'
            confidence = min(1.0, (1 - composite_score) + (0.1 if signals_aligned else 0))
        elif composite_score <= sell_threshold:
            action = 'SELL'
            confidence = 1 - composite_score
        else:
            action = 'HOLD'
            confidence = 0.5
        
        return action, confidence
    
    def rank_opportunities(
        self,
        signals: List[CompositeSignal],
        min_confidence: float = 0.60
    ) -> List[CompositeSignal]:
        """
        Rankea oportunidades de inversión
        
        Args:
            signals: Lista de señales
            min_confidence: Confianza mínima
            
        Returns:
            Lista ordenada de mejores oportunidades
        """
        # Filtrar solo compras con confianza suficiente
        buy_signals = [
            s for s in signals
            if s.action == 'BUY' and s.confidence >= min_confidence
        ]
        
        # Ordenar por score compuesto
        ranked = sorted(
            buy_signals,
            key=lambda x: (
                x.confidence * 0.4 +
                x.fundamental_score * 0.35 +
                x.technical_score * 0.25
            ),
            reverse=True
        )
        
        return ranked
    
    def generate_portfolio_signals(
        self,
        price_data: Dict[str, pd.Series],
        fundamental_data: Optional[Dict[str, FundamentalMetrics]] = None,
        market_regime: str = 'neutral'
    ) -> List[CompositeSignal]:
        """
        Genera señales para todo el universo
        
        Args:
            price_data: Diccionario de series de precios
            fundamental_data: Diccionario de métricas fundamentales
            market_regime: Régimen de mercado
            
        Returns:
            Lista de señales compuestas
        """
        signals = []
        
        for symbol, prices in price_data.items():
            metrics = fundamental_data.get(symbol) if fundamental_data else None
            
            signal = self.generate_signal(
                symbol=symbol,
                prices=prices,
                metrics=metrics,
                market_regime=market_regime
            )
            signals.append(signal)
        
        return signals
