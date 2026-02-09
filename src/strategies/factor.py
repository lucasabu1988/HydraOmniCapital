"""
Estrategias de Factor Investing

Basadas en:
- Fama, E.F. & French, K.R. (1993, 2015) - 3-Factor y 5-Factor models
- Asness, C.S. (1998) - Value and Momentum
- Novy-Marx, R. (2013) - The Other Side of Value
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional
from datetime import datetime

from .base import BaseStrategy, StrategySignal, Allocation


class FactorInvestingStrategy(BaseStrategy):
    """
    Estrategia de Factor Investing Multi-Factor.
    
    Combina factores:
    - Value (P/E, P/B, EV/EBITDA)
    - Quality (ROE, ROA, Estabilidad de earnings)
    - Momentum (12M - 1M)
    - Low Volatility (volatilidad histórica)
    - Size (Market Cap)
    
    Config:
        factors: Dict con pesos de cada factor
        top_n: Número de stocks a seleccionar
        sector_neutral: Si hacer ranking sector-neutral
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        
        # Pesos por defecto de los factores
        self.factor_weights = config.get('factor_weights', {
            'value': 0.25,
            'quality': 0.25,
            'momentum': 0.25,
            'low_vol': 0.15,
            'size': 0.10
        })
        
        self.top_n = config.get('top_n', 20)
        self.sector_neutral = config.get('sector_neutral', True)
        self.min_market_cap = config.get('min_market_cap', 1e9)  # $1B
        
    def generate_signals(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None,
        current_portfolio: Optional[Dict] = None
    ) -> List[StrategySignal]:
        """
        Genera señales basadas en composite factor score.
        """
        signals = []
        
        if fundamentals is None:
            return signals
        
        # Calcular scores para cada factor
        factor_scores = self._calculate_factor_scores(prices, fundamentals)
        
        if factor_scores.empty:
            return signals
        
        # Calcular composite score ponderado
        composite_score = pd.Series(0.0, index=factor_scores.index)
        for factor, weight in self.factor_weights.items():
            if factor in factor_scores.columns:
                composite_score += factor_scores[factor] * weight
        
        # Ranking por composite score
        ranked = composite_score.sort_values(ascending=False)
        
        # Generar señales para top N
        for i, (symbol, score) in enumerate(ranked.head(self.top_n).items()):
            strength = min(1.0, max(0.0, (score + 3) / 6))  # Normalizar a 0-1
            
            # Metadata con breakdown por factor
            metadata = {'composite_score': score, 'rank': i + 1}
            for factor in self.factor_weights.keys():
                if factor in factor_scores.columns:
                    metadata[f'{factor}_score'] = factor_scores.loc[symbol, factor]
            
            signal = StrategySignal(
                symbol=symbol,
                action='BUY',
                strength=strength,
                timestamp=prices.index[-1],
                strategy_name=self.name,
                metadata=metadata
            )
            signals.append(signal)
            self.record_signal(signal)
        
        return signals
    
    def _calculate_factor_scores(
        self,
        prices: pd.DataFrame,
        fundamentals: Dict
    ) -> pd.DataFrame:
        """
        Calcula z-scores para cada factor.
        """
        scores = pd.DataFrame(index=prices.columns)
        
        # 1. VALUE FACTOR
        value_scores = pd.Series(index=prices.columns, dtype=float)
        for symbol in prices.columns:
            if symbol in fundamentals:
                f = fundamentals[symbol]
                # Composite value score
                pe = f.get('pe_ratio', np.nan)
                pb = f.get('pb_ratio', np.nan)
                ps = f.get('ps_ratio', np.nan)
                ev_ebitda = f.get('ev_ebitda', np.nan)
                
                # Invertir ratios (menor = mejor valor)
                value_components = []
                if not pd.isna(pe) and pe > 0:
                    value_components.append(1 / pe)
                if not pd.isna(pb) and pb > 0:
                    value_components.append(1 / pb)
                if not pd.isna(ps) and ps > 0:
                    value_components.append(1 / ps)
                if not pd.isna(ev_ebitda) and ev_ebitda > 0:
                    value_components.append(1 / ev_ebitda)
                
                if value_components:
                    value_scores[symbol] = np.mean(value_components)
        
        if not value_scores.isna().all():
            scores['value'] = self._zscore(value_scores)
        
        # 2. QUALITY FACTOR
        quality_scores = pd.Series(index=prices.columns, dtype=float)
        for symbol in prices.columns:
            if symbol in fundamentals:
                f = fundamentals[symbol]
                roe = f.get('roe', np.nan)
                roa = f.get('roa', np.nan)
                
                quality_components = []
                if not pd.isna(roe):
                    quality_components.append(roe)
                if not pd.isna(roa):
                    quality_components.append(roa)
                
                if quality_components:
                    quality_scores[symbol] = np.mean(quality_components)
        
        if not quality_scores.isna().all():
            scores['quality'] = self._zscore(quality_scores)
        
        # 3. MOMENTUM FACTOR (12M - 1M)
        if len(prices) > 252:
            momentum_12m = (prices.iloc[-1] / prices.iloc[-252]) - 1
            momentum_1m = (prices.iloc[-1] / prices.iloc[-21]) - 1
            momentum_score = momentum_12m - momentum_1m  # Excluir último mes
            scores['momentum'] = self._zscore(momentum_score)
        
        # 4. LOW VOLATILITY FACTOR
        if len(prices) > 63:  # 3 meses
            returns = prices.pct_change().dropna()
            vol_score = -returns.tail(63).std() * np.sqrt(252)  # Negativo = menor vol mejor
            scores['low_vol'] = self._zscore(vol_score)
        
        # 5. SIZE FACTOR (Small cap premium, negativo = preferir small caps)
        market_caps = pd.Series(index=prices.columns, dtype=float)
        for symbol in prices.columns:
            if symbol in fundamentals:
                mc = fundamentals[symbol].get('market_cap', np.nan)
                if not pd.isna(mc) and mc > 0:
                    market_caps[symbol] = -np.log(mc)  # Negativo y log = preferir menor market cap
        
        if not market_caps.isna().all():
            scores['size'] = self._zscore(market_caps)
        
        return scores.fillna(0)
    
    def _zscore(self, series: pd.Series) -> pd.Series:
        """Calcula z-score, manejando NaN y desviación cero"""
        mean = series.mean()
        std = series.std()
        if std == 0 or pd.isna(std):
            return pd.Series(0, index=series.index)
        return (series - mean) / std
    
    def calculate_allocations(
        self,
        prices: pd.DataFrame,
        signals: List[StrategySignal],
        risk_budget: Optional[float] = None
    ) -> Dict[str, Allocation]:
        """
        Asigna pesos basados en composite score y volatilidad.
        """
        if not signals:
            return {}
        
        allocations = {}
        symbols = [s.symbol for s in signals]
        
        # Calcular volatilidades para risk parity
        vols = self.calculate_volatility(prices[symbols])
        inverse_vols = 1 / vols.replace(0, np.nan)
        
        total_score = sum(s.metadata['composite_score'] for s in signals)
        
        for signal in signals:
            symbol = signal.symbol
            
            # Peso basado en score
            if total_score > 0:
                score_weight = signal.metadata['composite_score'] / total_score
            else:
                score_weight = 1.0 / len(signals)
            
            # Ajuste por volatilidad (risk parity)
            vol_weight = (inverse_vols.get(symbol, 1) / inverse_vols.sum())
            
            # Peso final combinado
            weight = (score_weight * 0.6 + vol_weight * 0.4) * signal.strength
            
            allocations[symbol] = Allocation(
                symbol=symbol,
                weight=weight,
                expected_return=signal.metadata['composite_score'] * 0.05,  # Estimación simple
                expected_risk=vols.get(symbol, 0.20),
                confidence=signal.strength
            )
        
        # Normalizar
        total_weight = sum(a.weight for a in allocations.values())
        if total_weight > 0:
            for alloc in allocations.values():
                alloc.weight /= total_weight
        
        self.record_allocations(allocations)
        return allocations


class QualityFactorStrategy(BaseStrategy):
    """
    Estrategia enfocada en Quality Factor.
    
    Basada en:
    - Novy-Marx, R. (2013) - Gross profitability
    - Fama-French RMW factor (Robust Minus Weak)
    
    Métricas de calidad:
    - ROE, ROA, ROC
    - Gross Profitability (GP/A)
    - Earnings stability (baja volatilidad de earnings)
    - Low accruals
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.top_n = config.get('top_n', 15)
        self.min_roe = config.get('min_roe', 0.15)
        
    def generate_signals(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None,
        current_portfolio: Optional[Dict] = None
    ) -> List[StrategySignal]:
        """
        Selecciona empresas de alta calidad.
        """
        signals = []
        
        if fundamentals is None:
            return signals
        
        quality_scores = pd.Series(index=prices.columns, dtype=float)
        
        for symbol in prices.columns:
            if symbol not in fundamentals:
                continue
            
            f = fundamentals[symbol]
            score = 0
            
            # ROE
            roe = f.get('roe', 0)
            if roe > self.min_roe:
                score += roe * 2
            elif roe > 0.10:
                score += roe
            
            # ROA
            roa = f.get('roa', 0)
            if roa > 0.08:
                score += roa
            
            # Profit margin
            margin = f.get('profit_margin', 0)
            if margin > 0.20:
                score += margin
            
            # Debt to Equity (menor es mejor)
            de = f.get('debt_to_equity', np.inf)
            if de < 0.5:
                score += 0.2
            elif de < 1.0:
                score += 0.1
            
            quality_scores[symbol] = score
        
        # Ranking
        ranked = quality_scores.sort_values(ascending=False)
        
        for i, (symbol, score) in enumerate(ranked.head(self.top_n).items()):
            strength = min(1.0, score / 2)
            
            signal = StrategySignal(
                symbol=symbol,
                action='BUY',
                strength=strength,
                timestamp=prices.index[-1],
                strategy_name=self.name,
                metadata={'quality_score': score, 'rank': i + 1}
            )
            signals.append(signal)
            self.record_signal(signal)
        
        return signals