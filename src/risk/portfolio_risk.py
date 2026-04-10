"""
Gestión de Riesgo a Nivel de Portafolio
Maneja exposición por sector, correlación y límites globales
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class PortfolioMetrics:
    """Métricas de riesgo del portafolio"""
    total_value: float
    cash: float
    positions_value: float
    num_positions: int
    sector_exposure: Dict[str, float]
    portfolio_beta: float
    volatility: float
    var_95: float  # Value at Risk 95%
    expected_shortfall: float
    max_drawdown: float
    current_drawdown: float
    sharpe_ratio: float


class PortfolioRiskManager:
    """
    Gestiona el riesgo a nivel de portafolio completo.
    Controla exposiciones, correlaciones y límites globales.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.max_positions = config.get('max_portfolio_positions', 20)
        self.max_sector_exposure = config.get('max_sector_exposure', 0.30)
        self.max_drawdown_limit = config.get('objectives', {}).get('max_drawdown', 0.15)
        self.volatility_target = config.get('objectives', {}).get('volatility_target', 0.20)
        
        # Historial para cálculos
        self.equity_curve: List[float] = []
        self.peak_value: float = 0.0
        
    def calculate_portfolio_metrics(
        self,
        positions: Dict[str, Any],
        cash: float,
        price_history: pd.DataFrame
    ) -> PortfolioMetrics:
        """
        Calcula métricas de riesgo del portafolio
        
        Args:
            positions: Diccionario de posiciones
            cash: Efectivo disponible
            price_history: DataFrame con precios históricos
            
        Returns:
            PortfolioMetrics con todas las métricas
        """
        positions_value = sum(p.market_value for p in positions.values())
        total_value = positions_value + cash
        
        # Exposición por sector
        sector_exposure = self._calculate_sector_exposure(positions, total_value)
        
        # Calcular volatilidad del portafolio
        portfolio_returns = self._calculate_portfolio_returns(positions, price_history)
        volatility = portfolio_returns.std() * np.sqrt(252) if len(portfolio_returns) > 0 else 0
        
        # Value at Risk (VaR) paramétrico
        var_95 = self._calculate_var(portfolio_returns, confidence=0.95)
        
        # Expected Shortfall (CVaR)
        expected_shortfall = self._calculate_expected_shortfall(portfolio_returns, confidence=0.95)
        
        # Drawdown
        self.equity_curve.append(total_value)
        self.peak_value = max(self.peak_value, total_value)
        current_drawdown = (self.peak_value - total_value) / self.peak_value if self.peak_value > 0 else 0
        max_drawdown = self._calculate_max_drawdown()
        
        # Sharpe Ratio (asumiendo risk-free rate del 2%)
        sharpe_ratio = self._calculate_sharpe_ratio(portfolio_returns)
        
        # Beta del portafolio (simplificado)
        portfolio_beta = self._calculate_portfolio_beta(positions)
        
        return PortfolioMetrics(
            total_value=total_value,
            cash=cash,
            positions_value=positions_value,
            num_positions=len(positions),
            sector_exposure=sector_exposure,
            portfolio_beta=portfolio_beta,
            volatility=volatility,
            var_95=var_95,
            expected_shortfall=expected_shortfall,
            max_drawdown=max_drawdown,
            current_drawdown=current_drawdown,
            sharpe_ratio=sharpe_ratio
        )
    
    def _calculate_sector_exposure(
        self,
        positions: Dict[str, Any],
        total_value: float
    ) -> Dict[str, float]:
        """Calcula la exposición por sector"""
        sector_values: Dict[str, float] = {}
        
        for symbol, pos in positions.items():
            sector = pos.sector
            value = pos.market_value
            sector_values[sector] = sector_values.get(sector, 0) + value
        
        # Convertir a porcentajes
        if total_value > 0:
            return {sector: value / total_value for sector, value in sector_values.items()}
        return {}
    
    def _calculate_portfolio_returns(
        self,
        positions: Dict[str, Any],
        price_history: pd.DataFrame
    ) -> pd.Series:
        """Calcula los retornos del portafolio"""
        if len(positions) == 0 or price_history.empty:
            return pd.Series()
        
        # Calcular retornos ponderados por posición
        portfolio_returns = pd.Series(0.0, index=price_history.index)
        total_weight = 0
        
        for symbol, pos in positions.items():
            if symbol in price_history.columns:
                weight = pos.weight
                returns = price_history[symbol].pct_change().fillna(0)
                portfolio_returns += returns * weight
                total_weight += weight
        
        if total_weight > 0:
            portfolio_returns = portfolio_returns / total_weight
        
        return portfolio_returns
    
    def _calculate_var(self, returns: pd.Series, confidence: float = 0.95) -> float:
        """Calcula Value at Risk paramétrico"""
        if len(returns) == 0:
            return 0.0
        
        mean = returns.mean()
        std = returns.std()
        z_score = 1.645 if confidence == 0.95 else 2.326  # 95% o 99%
        
        return mean - z_score * std
    
    def _calculate_expected_shortfall(
        self,
        returns: pd.Series,
        confidence: float = 0.95
    ) -> float:
        """Calcula Expected Shortfall (Conditional VaR)"""
        if len(returns) == 0:
            return 0.0
        
        var_threshold = self._calculate_var(returns, confidence)
        return returns[returns <= var_threshold].mean()
    
    def _calculate_max_drawdown(self) -> float:
        """Calcula el máximo drawdown histórico"""
        if len(self.equity_curve) < 2:
            return 0.0
        
        equity_series = pd.Series(self.equity_curve)
        rolling_max = equity_series.expanding().max()
        drawdown = (equity_series - rolling_max) / rolling_max
        return drawdown.min()
    
    def _calculate_sharpe_ratio(
        self,
        returns: pd.Series,
        risk_free_rate: float = 0.02
    ) -> float:
        """Calcula el Sharpe Ratio"""
        if len(returns) == 0 or returns.std() == 0:
            return 0.0
        
        excess_returns = returns.mean() * 252 - risk_free_rate
        return excess_returns / (returns.std() * np.sqrt(252))
    
    def _calculate_portfolio_beta(self, positions: Dict[str, Any]) -> float:
        """Calcula la beta ponderada del portafolio"""
        total_beta = 0
        total_weight = 0
        
        for symbol, pos in positions.items():
            beta = pos.beta
            weight = pos.weight
            total_beta += beta * weight
            total_weight += weight
        
        return total_beta / total_weight if total_weight > 0 else 1.0
    
    def check_risk_limits(self, metrics: PortfolioMetrics) -> Dict[str, Any]:
        """
        Verifica si el portafolio cumple con los límites de riesgo
        
        Args:
            metrics: PortfolioMetrics calculado
            
        Returns:
            Diccionario con violaciones y acciones recomendadas
        """
        violations = []
        actions = []
        
        # Verificar drawdown
        if metrics.current_drawdown > self.max_drawdown_limit:
            violations.append(f"Drawdown actual ({metrics.current_drawdown:.2%}) excede límite ({self.max_drawdown_limit:.2%})")
            actions.append("REDUCE_EXPOSURE")
        
        # Verificar volatilidad
        if metrics.volatility > self.volatility_target:
            violations.append(f"Volatilidad ({metrics.volatility:.2%}) excede objetivo ({self.volatility_target:.2%})")
            actions.append("HEDGE_VOLATILITY")
        
        # Verificar exposición por sector
        for sector, exposure in metrics.sector_exposure.items():
            if exposure > self.max_sector_exposure:
                violations.append(f"Exposición {sector} ({exposure:.2%}) excede límite ({self.max_sector_exposure:.2%})")
                actions.append(f"REDUCE_SECTOR_{sector}")
        
        # Verificar número de posiciones
        if metrics.num_positions > self.max_positions:
            violations.append(f"Número de posiciones ({metrics.num_positions}) excede máximo ({self.max_positions})")
            actions.append("CONSOLIDATE_POSITIONS")
        
        # Verificar concentración
        max_position = max(metrics.sector_exposure.values()) if metrics.sector_exposure else 0
        if max_position > 0.25:  # Alerta si una posición > 25%
            actions.append("REBALANCE_CONCENTRATION")
        
        return {
            'is_compliant': len(violations) == 0,
            'violations': violations,
            'recommended_actions': actions,
            'risk_score': self._calculate_risk_score(metrics)
        }
    
    def _calculate_risk_score(self, metrics: PortfolioMetrics) -> float:
        """
        Calcula un score de riesgo compuesto (0-100)
        Más bajo es mejor
        """
        score = 50  # Base neutra
        
        # Penalizar drawdown
        score += max(0, (metrics.current_drawdown / self.max_drawdown_limit) * 20)
        
        # Penalizar volatilidad
        score += max(0, ((metrics.volatility - self.volatility_target) / self.volatility_target) * 15)
        
        # Penalizar concentración
        if metrics.sector_exposure:
            max_exposure = max(metrics.sector_exposure.values())
            score += max(0, (max_exposure - 0.20) * 50)
        
        # Bonificar Sharpe ratio
        score -= min(20, metrics.sharpe_ratio * 5)
        
        return max(0, min(100, score))
    
    def get_position_limit(self, sector: str, current_exposure: Dict[str, float]) -> float:
        """
        Calcula el límite de tamaño para una nueva posición
        
        Args:
            sector: Sector de la nueva posición
            current_exposure: Exposición actual por sector
            
        Returns:
            Tamaño máximo permitido para la nueva posición
        """
        current_sector_pct = current_exposure.get(sector, 0)
        available_exposure = self.max_sector_exposure - current_sector_pct
        
        # Límite por posición individual
        max_position = self.config.get('max_position_size', 0.10)
        
        return min(available_exposure, max_position)
    
    def should_rebalance(
        self,
        target_weights: Dict[str, float],
        current_weights: Dict[str, float],
        threshold: float = None
    ) -> bool:
        """
        Determina si se debe rebalancear el portafolio
        
        Args:
            target_weights: Pesos objetivo
            current_weights: Pesos actuales
            threshold: Umbral de desviación (default del config)
            
        Returns:
            True si se debe rebalancear
        """
        if threshold is None:
            threshold = self.config.get('rebalancing', {}).get('threshold', 0.05)
        
        # Calcular drift máximo
        max_drift = 0
        all_symbols = set(target_weights.keys()) | set(current_weights.keys())
        
        for symbol in all_symbols:
            target = target_weights.get(symbol, 0)
            current = current_weights.get(symbol, 0)
            drift = abs(target - current)
            max_drift = max(max_drift, drift)
        
        return max_drift > threshold
