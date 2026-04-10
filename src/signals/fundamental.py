"""
Señales Fundamentales
Análisis de datos fundamentales para generar señales de inversión
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from enum import Enum


class FundamentalScore(Enum):
    STRONG_BUY = 5
    BUY = 4
    NEUTRAL = 3
    SELL = 2
    STRONG_SELL = 1


@dataclass
class FundamentalMetrics:
    """Métricas fundamentales de una empresa"""
    symbol: str
    sector: str = 'Unknown'
    
    # Valoración
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    pb_ratio: Optional[float] = None
    ps_ratio: Optional[float] = None
    ev_ebitda: Optional[float] = None
    
    # Rentabilidad
    roe: Optional[float] = None
    roa: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    profit_margin: Optional[float] = None
    
    # Salud financiera
    debt_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    quick_ratio: Optional[float] = None
    interest_coverage: Optional[float] = None
    
    # Crecimiento
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None
    
    # Dividendos
    dividend_yield: Optional[float] = None
    payout_ratio: Optional[float] = None
    
    # Eficiencia
    asset_turnover: Optional[float] = None
    inventory_turnover: Optional[float] = None


class FundamentalSignals:
    """
    Genera señales basadas en análisis fundamental
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.value_config = next((e for e in config.get('entry', []) if e.get('name') == 'value'), {})
        self.quality_config = next((e for e in config.get('entry', []) if e.get('name') == 'quality'), {})
    
    def calculate_value_score(self, metrics: FundamentalMetrics) -> float:
        """
        Calcula score de valor basado en múltiples métricas
        
        Args:
            metrics: Métricas fundamentales
            
        Returns:
            Score entre 0 y 1
        """
        scores = []
        
        # P/E Ratio (menor es mejor)
        if metrics.pe_ratio and metrics.pe_ratio > 0:
            if metrics.pe_ratio < 10:
                scores.append(1.0)
            elif metrics.pe_ratio < 15:
                scores.append(0.8)
            elif metrics.pe_ratio < 20:
                scores.append(0.6)
            elif metrics.pe_ratio < 30:
                scores.append(0.4)
            else:
                scores.append(0.2)
        
        # P/B Ratio (menor es mejor)
        if metrics.pb_ratio and metrics.pb_ratio > 0:
            if metrics.pb_ratio < 1:
                scores.append(1.0)
            elif metrics.pb_ratio < 2:
                scores.append(0.8)
            elif metrics.pb_ratio < 3:
                scores.append(0.6)
            else:
                scores.append(0.3)
        
        # EV/EBITDA (menor es mejor)
        if metrics.ev_ebitda and metrics.ev_ebitda > 0:
            if metrics.ev_ebitda < 8:
                scores.append(1.0)
            elif metrics.ev_ebitda < 12:
                scores.append(0.8)
            elif metrics.ev_ebitda < 16:
                scores.append(0.6)
            else:
                scores.append(0.3)
        
        return np.mean(scores) if scores else 0.5
    
    def calculate_quality_score(self, metrics: FundamentalMetrics) -> float:
        """
        Calcula score de calidad basado en métricas de rentabilidad y salud
        
        Args:
            metrics: Métricas fundamentales
            
        Returns:
            Score entre 0 y 1
        """
        scores = []
        
        # ROE (mayor es mejor)
        min_roe = self.quality_config.get('min_roe', 0.15)
        if metrics.roe:
            if metrics.roe >= 0.20:
                scores.append(1.0)
            elif metrics.roe >= min_roe:
                scores.append(0.8)
            elif metrics.roe >= 0.10:
                scores.append(0.5)
            else:
                scores.append(0.2)
        
        # ROA (mayor es mejor)
        if metrics.roa:
            if metrics.roa >= 0.10:
                scores.append(1.0)
            elif metrics.roa >= 0.05:
                scores.append(0.7)
            else:
                scores.append(0.3)
        
        # Margen operativo
        if metrics.operating_margin:
            if metrics.operating_margin >= 0.20:
                scores.append(1.0)
            elif metrics.operating_margin >= 0.10:
                scores.append(0.7)
            else:
                scores.append(0.3)
        
        # Debt/Equity (menor es mejor)
        if metrics.debt_equity is not None:
            if metrics.debt_equity < 0.3:
                scores.append(1.0)
            elif metrics.debt_equity < 0.5:
                scores.append(0.8)
            elif metrics.debt_equity < 1.0:
                scores.append(0.5)
            else:
                scores.append(0.2)
        
        # Current Ratio (mayor es mejor, pero no excesivo)
        if metrics.current_ratio:
            if 1.5 <= metrics.current_ratio <= 3.0:
                scores.append(1.0)
            elif metrics.current_ratio >= 1.0:
                scores.append(0.7)
            else:
                scores.append(0.3)
        
        return np.mean(scores) if scores else 0.5
    
    def calculate_growth_score(self, metrics: FundamentalMetrics) -> float:
        """
        Calcula score de crecimiento
        
        Args:
            metrics: Métricas fundamentales
            
        Returns:
            Score entre 0 y 1
        """
        scores = []
        
        # Crecimiento de ingresos
        if metrics.revenue_growth:
            if metrics.revenue_growth >= 0.20:
                scores.append(1.0)
            elif metrics.revenue_growth >= 0.10:
                scores.append(0.8)
            elif metrics.revenue_growth >= 0.05:
                scores.append(0.5)
            else:
                scores.append(0.2)
        
        # Crecimiento de ganancias
        if metrics.earnings_growth:
            if metrics.earnings_growth >= 0.25:
                scores.append(1.0)
            elif metrics.earnings_growth >= 0.15:
                scores.append(0.8)
            elif metrics.earnings_growth >= 0.05:
                scores.append(0.5)
            else:
                scores.append(0.2)
        
        return np.mean(scores) if scores else 0.5
    
    def calculate_dividend_score(self, metrics: FundamentalMetrics) -> float:
        """
        Calcula score de dividendos
        
        Args:
            metrics: Métricas fundamentales
            
        Returns:
            Score entre 0 y 1
        """
        scores = []
        
        # Dividend Yield
        if metrics.dividend_yield:
            if 0.02 <= metrics.dividend_yield <= 0.05:
                scores.append(1.0)
            elif metrics.dividend_yield < 0.02:
                scores.append(0.5)
            else:
                scores.append(0.3)  # Very high yield can be risky
        
        # Payout Ratio (sostenible)
        if metrics.payout_ratio:
            if 0.30 <= metrics.payout_ratio <= 0.60:
                scores.append(1.0)
            elif metrics.payout_ratio < 0.30:
                scores.append(0.7)
            elif metrics.payout_ratio <= 0.80:
                scores.append(0.5)
            else:
                scores.append(0.2)  # Too high, may not be sustainable
        
        return np.mean(scores) if scores else 0.5
    
    def generate_fundamental_signal(
        self,
        metrics: FundamentalMetrics
    ) -> Dict[str, Any]:
        """
        Genera señal fundamental compuesta
        
        Args:
            metrics: Métricas fundamentales
            
        Returns:
            Diccionario con análisis y señal
        """
        # Calcular scores individuales
        value_score = self.calculate_value_score(metrics)
        quality_score = self.calculate_quality_score(metrics)
        growth_score = self.calculate_growth_score(metrics)
        dividend_score = self.calculate_dividend_score(metrics)
        
        # Pesos desde configuración
        value_weight = self.value_config.get('weight', 0.25)
        quality_weight = self.quality_config.get('weight', 0.25)
        growth_weight = 0.25
        dividend_weight = 0.25
        
        # Score ponderado
        composite_score = (
            value_score * value_weight +
            quality_score * quality_weight +
            growth_score * growth_weight +
            dividend_score * dividend_weight
        )
        
        # Determinar señal
        if composite_score >= 0.80:
            signal = FundamentalScore.STRONG_BUY
        elif composite_score >= 0.65:
            signal = FundamentalScore.BUY
        elif composite_score >= 0.45:
            signal = FundamentalScore.NEUTRAL
        elif composite_score >= 0.30:
            signal = FundamentalScore.SELL
        else:
            signal = FundamentalScore.STRONG_SELL
        
        return {
            'symbol': metrics.symbol,
            'composite_score': composite_score,
            'signal': signal,
            'scores': {
                'value': value_score,
                'quality': quality_score,
                'growth': growth_score,
                'dividend': dividend_score
            },
            'metrics': {
                'pe_ratio': metrics.pe_ratio,
                'pb_ratio': metrics.pb_ratio,
                'roe': metrics.roe,
                'debt_equity': metrics.debt_equity,
                'revenue_growth': metrics.revenue_growth
            }
        }
    
    def screen_universe(
        self,
        metrics_list: List[FundamentalMetrics],
        min_score: float = 0.60
    ) -> List[str]:
        """
        Filtra universo de inversión basado en criterios fundamentales
        
        Args:
            metrics_list: Lista de métricas fundamentales
            min_score: Score mínimo para incluir
            
        Returns:
            Lista de símbolos que pasan el filtro
        """
        qualified = []
        
        for metrics in metrics_list:
            result = self.generate_fundamental_signal(metrics)
            if result['composite_score'] >= min_score:
                if result['signal'] in [FundamentalScore.BUY, FundamentalScore.STRONG_BUY]:
                    qualified.append(metrics.symbol)
        
        return qualified
    
    def detect_deterioration(
        self,
        current: FundamentalMetrics,
        previous: FundamentalMetrics
    ) -> bool:
        """
        Detecta deterioro fundamental
        
        Args:
            current: Métricas actuales
            previous: Métricas anteriores
            
        Returns:
            True si hay deterioro significativo
        """
        deterioration_signals = 0
        
        # ROE decreciente
        if current.roe and previous.roe and current.roe < previous.roe * 0.9:
            deterioration_signals += 1
        
        # Márgenes decrecientes
        if current.operating_margin and previous.operating_margin:
            if current.operating_margin < previous.operating_margin * 0.9:
                deterioration_signals += 1
        
        # Deuda creciente
        if current.debt_equity and previous.debt_equity:
            if current.debt_equity > previous.debt_equity * 1.2:
                deterioration_signals += 1
        
        # Crecimiento de ingresos decreciente
        if current.revenue_growth and previous.revenue_growth:
            if current.revenue_growth < previous.revenue_growth * 0.5:
                deterioration_signals += 1
        
        return deterioration_signals >= 2
