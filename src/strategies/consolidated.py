"""
Estrategia Consolidada Única - OmniCapital v3.0

Integra en una sola estrategia:
- Value-First como base permanente (selección de stocks)
- Multi-Factor Scoring (Value, Quality, Momentum)
- Risk Parity (sizing basado en volatilidad)
- Trend Following (timing de entrada)
- Mean Reversion (timing de salida parcial)

Características:
- Usa 100% del capital en todo momento
- Value-First siempre activo
- Rebalanceo semanal completo
- Sin cash buffer
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
from scipy.optimize import minimize
import warnings

from .base import BaseStrategy, StrategySignal, Allocation


class ConsolidatedStrategy(BaseStrategy):
    """
    Estrategia consolidada única que integra múltiples factores.
    
    Fase 1: Selección (Value-First + Multi-Factor)
    - Score de valoración (P/E, P/B, EV/EBITDA, ROE)
    - Quality factor (ROE, ROA, margen)
    - Momentum factor (12M - 1M)
    
    Fase 2: Timing (Trend Following)
    - Solo entra en tendencia alcista
    - Filtro de SMA 50 > SMA 200
    
    Fase 3: Sizing (Risk Parity)
    - Pesos inversamente proporcionales a volatilidad
    - Máximo 40 posiciones
    
    Fase 4: Gestión de Salida (Escalonada)
    - Trailing stop 5%
    - Take profit 20%/35%/50%
    - Rebalanceo semanal completo (sin cash)
    
    Config:
        max_positions: Máximo número de posiciones (default: 40)
        target_cash: Objetivo de cash (default: 0.0 = 0%)
        value_weight: Peso del score de valoración (default: 0.50)
        quality_weight: Peso del quality factor (default: 0.25)
        momentum_weight: Peso del momentum factor (default: 0.25)
        min_value_score: Score mínimo de valoración (default: 50)
        use_trend_filter: Usar filtro de tendencia (default: True)
        rebalance_full: Rebalanceo completo semanal (default: True)
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.max_positions = config.get('max_positions', 40)
        self.target_cash_pct = config.get('target_cash', 0.0)  # 0% cash
        self.value_weight = config.get('value_weight', 0.50)
        self.quality_weight = config.get('quality_weight', 0.25)
        self.momentum_weight = config.get('momentum_weight', 0.25)
        self.min_value_score = config.get('min_value_score', 50)
        self.use_trend_filter = config.get('use_trend_filter', True)
        self.rebalance_full = config.get('rebalance_full', True)
        self.lookback_days = config.get('lookback_days', 252)
        
        # Tracking
        self.last_rebalance_date: Optional[datetime] = None
        self.current_allocations: Dict[str, Allocation] = {}
        
    def generate_signals(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None,
        current_portfolio: Optional[Dict] = None
    ) -> List[StrategySignal]:
        """
        Genera señales usando la estrategia consolidada.
        
        Proceso:
        1. Calcular composite score para todos los stocks
        2. Filtrar por score mínimo y tendencia
        3. Seleccionar top N
        4. Calcular allocaciones óptimas (risk parity)
        5. Generar señales de rebalanceo
        """
        signals = []
        
        if len(prices) < 50:
            return signals
        
        current_date = prices.index[-1]
        
        # 1. Calcular composite scores
        composite_scores = self._calculate_composite_scores(prices, fundamentals)
        
        if composite_scores.empty:
            return signals
        
        # 2. Filtrar por score mínimo
        qualified = composite_scores[composite_scores['total_score'] >= self.min_value_score]
        
        # 3. Filtrar por tendencia (si está activado)
        if self.use_trend_filter:
            qualified = self._apply_trend_filter(qualified, prices)
        
        if len(qualified) == 0:
            return signals
        
        # 4. Seleccionar top N
        top_stocks = qualified.nlargest(self.max_positions, 'total_score')
        
        # 5. Calcular allocaciones (risk parity)
        allocations = self._calculate_risk_parity_allocations(top_stocks, prices)
        
        # 6. Generar señales de rebalanceo
        current_positions = current_portfolio.get('positions', {}) if current_portfolio else {}
        
        # Señales de venta para posiciones que ya no califican
        for symbol in current_positions:
            if symbol not in allocations:
                signal = StrategySignal(
                    symbol=symbol,
                    action='SELL',
                    strength=1.0,
                    timestamp=current_date,
                    strategy_name=self.name,
                    metadata={'reason': 'REBALANCE_EXIT'}
                )
                signals.append(signal)
                self.record_signal(signal)
        
        # Señales de compra/ajuste para posiciones objetivo
        for symbol, alloc in allocations.items():
            if symbol in current_positions:
                # Ajustar posición existente
                action = 'ADJUST'
            else:
                # Nueva posición
                action = 'BUY'
            
            signal = StrategySignal(
                symbol=symbol,
                action=action,
                strength=min(1.0, alloc.confidence),
                timestamp=current_date,
                strategy_name=self.name,
                metadata={
                    'target_weight': alloc.weight,
                    'total_score': top_stocks.loc[symbol, 'total_score'],
                    'value_score': top_stocks.loc[symbol, 'value_score'],
                    'quality_score': top_stocks.loc[symbol, 'quality_score'],
                    'momentum_score': top_stocks.loc[symbol, 'momentum_score'],
                    'expected_risk': alloc.expected_risk
                },
                target_weight=alloc.weight
            )
            signals.append(signal)
            self.record_signal(signal)
        
        self.current_allocations = allocations
        self.last_rebalance_date = current_date
        
        return signals
    
    def _calculate_composite_scores(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict]
    ) -> pd.DataFrame:
        """
        Calcula composite scores combinando Value, Quality y Momentum.
        """
        scores = pd.DataFrame(index=prices.columns)
        
        # VALUE SCORE (0-100)
        if fundamentals:
            value_scores = pd.Series(index=prices.columns, dtype=float)
            for symbol in prices.columns:
                if symbol in fundamentals:
                    f = fundamentals[symbol]
                    score = self._calculate_value_score(
                        f.get('pe_ratio'),
                        f.get('pb_ratio'),
                        f.get('ps_ratio'),
                        f.get('ev_ebitda'),
                        f.get('roe')
                    )
                    value_scores[symbol] = score
            scores['value_score'] = value_scores.fillna(50)
        else:
            scores['value_score'] = 50
        
        # QUALITY SCORE (0-100)
        if fundamentals:
            quality_scores = pd.Series(index=prices.columns, dtype=float)
            for symbol in prices.columns:
                if symbol in fundamentals:
                    f = fundamentals[symbol]
                    score = 0
                    roe = f.get('roe', 0) or 0
                    roa = f.get('roa', 0) or 0
                    margin = f.get('profit_margin', 0) or 0
                    
                    if roe > 0.20: score += 40
                    elif roe > 0.15: score += 30
                    elif roe > 0.10: score += 20
                    
                    if roa > 0.10: score += 30
                    elif roa > 0.05: score += 15
                    
                    if margin > 0.20: score += 30
                    elif margin > 0.10: score += 15
                    
                    quality_scores[symbol] = min(100, score)
            scores['quality_score'] = quality_scores.fillna(50)
        else:
            scores['quality_score'] = 50
        
        # MOMENTUM SCORE (0-100)
        if len(prices) > 252:
            momentum_12m = (prices.iloc[-1] / prices.iloc[-252]) - 1
            momentum_1m = (prices.iloc[-1] / prices.iloc[-21]) - 1
            momentum_score = (momentum_12m - momentum_1m) * 100  # Convertir a score
            momentum_score = momentum_score.clip(-50, 50) + 50  # Normalizar a 0-100
            scores['momentum_score'] = momentum_score
        else:
            scores['momentum_score'] = 50
        
        # COMPOSITE SCORE
        scores['total_score'] = (
            scores['value_score'] * self.value_weight +
            scores['quality_score'] * self.quality_weight +
            scores['momentum_score'] * self.momentum_weight
        )
        
        return scores
    
    def _calculate_value_score(
        self,
        pe_ratio: Optional[float],
        pb_ratio: Optional[float],
        ps_ratio: Optional[float],
        ev_ebitda: Optional[float],
        roe: Optional[float]
    ) -> float:
        """Calcula score de valoración (0-100)."""
        score = 50
        
        if pe_ratio and pe_ratio > 0:
            if pe_ratio < 12: score += 20
            elif pe_ratio < 18: score += 12
            elif pe_ratio < 25: score += 5
            elif pe_ratio > 40: score -= 15
        
        if pb_ratio and pb_ratio > 0:
            if pb_ratio < 1.5: score += 18
            elif pb_ratio < 2.5: score += 10
            elif pb_ratio > 5: score -= 12
        
        if ps_ratio and ps_ratio > 0:
            if ps_ratio < 2: score += 12
            elif ps_ratio > 8: score -= 8
        
        if ev_ebitda and ev_ebitda > 0:
            if ev_ebitda < 10: score += 15
            elif ev_ebitda < 15: score += 8
            elif ev_ebitda > 25: score -= 10
        
        if roe and roe > 0.20: score += 10
        elif roe and roe > 0.15: score += 5
        
        return max(0, min(100, score))
    
    def _apply_trend_filter(
        self,
        stocks: pd.DataFrame,
        prices: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Aplica filtro de tendencia: solo stocks en tendencia alcista.
        """
        trending = []
        
        for symbol in stocks.index:
            if symbol not in prices.columns:
                continue
            
            price_series = prices[symbol].dropna()
            if len(price_series) < 200:
                continue
            
            sma_50 = price_series.tail(50).mean()
            sma_200 = price_series.tail(200).mean()
            
            if sma_50 > sma_200:  # Tendencia alcista
                trending.append(symbol)
        
        return stocks.loc[trending] if trending else stocks
    
    def _calculate_risk_parity_allocations(
        self,
        stocks: pd.DataFrame,
        prices: pd.DataFrame
    ) -> Dict[str, Allocation]:
        """
        Calcula allocaciones usando risk parity (inverse volatility).
        """
        allocations = {}
        symbols = list(stocks.index)
        
        if len(symbols) == 0:
            return allocations
        
        # Calcular volatilidades
        vols = pd.Series(index=symbols, dtype=float)
        for symbol in symbols:
            if symbol in prices.columns:
                returns = prices[symbol].pct_change().dropna().tail(63)
                if len(returns) > 20:
                    vols[symbol] = returns.std() * np.sqrt(252)
        
        vols = vols.dropna()
        
        if len(vols) == 0:
            # Equal weight fallback
            weight = 1.0 / len(symbols)
            for symbol in symbols:
                allocations[symbol] = Allocation(
                    symbol=symbol,
                    weight=weight,
                    expected_return=0.0,
                    expected_risk=0.20,
                    confidence=stocks.loc[symbol, 'total_score'] / 100
                )
            return allocations
        
        # Inverse volatility weighting
        inverse_vols = 1 / vols
        total_inverse = inverse_vols.sum()
        
        for symbol in vols.index:
            weight = (inverse_vols[symbol] / total_inverse) * (1 - self.target_cash_pct)
            confidence = stocks.loc[symbol, 'total_score'] / 100
            
            allocations[symbol] = Allocation(
                symbol=symbol,
                weight=weight,
                expected_return=0.0,
                expected_risk=vols[symbol],
                confidence=confidence
            )
        
        return allocations
    
    def calculate_allocations(
        self,
        prices: pd.DataFrame,
        signals: List[StrategySignal],
        risk_budget: Optional[float] = None
    ) -> Dict[str, Allocation]:
        """
        Retorna las allocaciones calculadas en generate_signals.
        """
        return self.current_allocations
    
    def get_portfolio_target(self, portfolio_value: float) -> Tuple[float, Dict[str, float]]:
        """
        Retorna el objetivo de cash y allocaciones por símbolo.
        
        Returns:
            (target_cash, target_weights)
        """
        target_cash = portfolio_value * self.target_cash_pct
        target_weights = {symbol: alloc.weight for symbol, alloc in self.current_allocations.items()}
        
        return target_cash, target_weights