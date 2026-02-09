"""
Estrategias de Risk Parity y Optimización de Riesgo

Basadas en:
- Qian, E. (2005) - Risk Parity Portfolios
- Maillard, S., Roncalli, T., & Teïletche, J. (2010)
- Choueifaty, Y. & Coignard, Y. (2008) - Maximum Diversification
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Any, Optional, Tuple
from scipy.optimize import minimize
import warnings

from .base import BaseStrategy, StrategySignal, Allocation


class RiskParityStrategy(BaseStrategy):
    """
    Estrategia de Risk Parity.
    
    Asigna pesos de forma que cada activo contribuya
    igualmente al riesgo total del portafolio.
    
    Risk Contribution_i = w_i * (Cw)_i / sqrt(w'Cw)
    Donde C es la matriz de covarianza
    
    Config:
        risk_budget: Presupuesto de riesgo por activo (default: equal)
        vol_target: Volatilidad objetivo del portafolio
        max_weight: Peso máximo por activo
        min_weight: Peso mínimo por activo
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.risk_budget = config.get('risk_budget', None)  # None = equal
        self.vol_target = config.get('vol_target', 0.10)
        self.max_weight = config.get('max_weight', 0.20)
        self.min_weight = config.get('min_weight', 0.01)
        self.lookback_days = config.get('lookback_days', 252)
        
    def generate_signals(
        self,
        prices: pd.DataFrame,
        fundamentals: Optional[Dict] = None,
        current_portfolio: Optional[Dict] = None
    ) -> List[StrategySignal]:
        """
        Genera señales para todos los activos disponibles.
        """
        signals = []
        
        # Calcular allocaciones óptimas
        allocations = self.calculate_allocations(prices, [])
        
        for symbol, alloc in allocations.items():
            signal = StrategySignal(
                symbol=symbol,
                action='BUY',
                strength=alloc.confidence,
                timestamp=prices.index[-1],
                strategy_name=self.name,
                metadata={
                    'target_weight': alloc.weight,
                    'expected_risk': alloc.expected_risk
                },
                target_weight=alloc.weight
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
        Optimiza pesos para igualar risk contributions.
        """
        if len(prices) < self.lookback_days:
            return {}
        
        # Calcular retornos y matriz de covarianza
        returns = self.calculate_returns(prices.tail(self.lookback_days))
        
        # Filtrar activos con datos suficientes
        valid_symbols = returns.columns[returns.count() > self.lookback_days * 0.8]
        returns = returns[valid_symbols].dropna()
        
        if len(valid_symbols) < 2:
            return {}
        
        cov_matrix = returns.cov().values * 252  # Anualizada
        n = len(valid_symbols)
        
        # Risk budget (igual por defecto)
        if self.risk_budget is None:
            risk_budget = np.ones(n) / n
        else:
            risk_budget = np.array(self.risk_budget)
            risk_budget = risk_budget / risk_budget.sum()
        
        # Función objetivo: minimizar diferencia entre risk contributions
        def risk_parity_objective(w):
            portfolio_vol = np.sqrt(np.dot(w, np.dot(cov_matrix, w)))
            if portfolio_vol == 0:
                return 1e10
            
            marginal_risk = np.dot(cov_matrix, w) / portfolio_vol
            risk_contrib = w * marginal_risk
            
            # Diferencia entre risk contrib actual y target
            target_risk_contrib = portfolio_vol * risk_budget
            diff = risk_contrib - target_risk_contrib
            
            return np.sum(diff ** 2)
        
        # Optimización con restricciones
        constraints = [
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}  # Suma de pesos = 1
        ]
        
        bounds = [(self.min_weight, self.max_weight) for _ in range(n)]
        
        # Initial guess: inverse volatility
        vols = np.sqrt(np.diag(cov_matrix))
        x0 = (1 / vols) / np.sum(1 / vols)
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = minimize(
                risk_parity_objective,
                x0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints,
                options={'maxiter': 1000}
            )
        
        if not result.success:
            # Fallback a inverse volatility
            weights = x0
        else:
            weights = result.x
        
        # Crear allocaciones
        allocations = {}
        portfolio_vol = np.sqrt(np.dot(weights, np.dot(cov_matrix, weights)))
        
        for i, symbol in enumerate(valid_symbols):
            allocations[symbol] = Allocation(
                symbol=symbol,
                weight=weights[i],
                expected_return=returns[symbol].mean() * 252,
                expected_risk=np.sqrt(cov_matrix[i, i]),
                confidence=1.0
            )
        
        self.record_allocations(allocations)
        return allocations


class InverseVolatilityStrategy(BaseStrategy):
    """
    Estrategia de Inverse Volatility Weighting.
    
    Simplificación de Risk Parity que asume correlaciones cero.
    Peso proporcional a 1/volatilidad.
    
    Config:
        lookback_days: Período para calcular volatilidad
        vol_target: Volatilidad objetivo (para leverage)
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.lookback_days = config.get('lookback_days', 63)  # 3 meses
        self.vol_target = config.get('vol_target', None)
        
    def calculate_allocations(
        self,
        prices: pd.DataFrame,
        signals: List[StrategySignal],
        risk_budget: Optional[float] = None
    ) -> Dict[str, Allocation]:
        """
        Asigna pesos inversamente proporcionales a la volatilidad.
        """
        if len(prices) < self.lookback_days:
            return {}
        
        # Calcular volatilidades
        returns = self.calculate_returns(prices.tail(self.lookback_days))
        vols = returns.std() * np.sqrt(252)
        
        # Filtrar activos con datos válidos
        valid_vols = vols[vols > 0].dropna()
        
        if len(valid_vols) == 0:
            return {}
        
        # Pesos inversos a la volatilidad
        inverse_vols = 1 / valid_vols
        weights = inverse_vols / inverse_vols.sum()
        
        # Aplicar leverage si hay volatilidad objetivo
        if self.vol_target is not None:
            # Calcular volatilidad del portafolio
            cov_matrix = returns[valid_vols.index].cov() * 252
            portfolio_vol = np.sqrt(np.dot(weights, np.dot(cov_matrix, weights)))
            
            if portfolio_vol > 0:
                leverage = self.vol_target / portfolio_vol
                weights = weights * leverage
        
        # Crear allocaciones
        allocations = {}
        for symbol in valid_vols.index:
            allocations[symbol] = Allocation(
                symbol=symbol,
                weight=weights[symbol],
                expected_return=returns[symbol].mean() * 252,
                expected_risk=valid_vols[symbol],
                confidence=1.0
            )
        
        self.record_allocations(allocations)
        return allocations


class MinimumVarianceStrategy(BaseStrategy):
    """
    Estrategia de Minimum Variance Portfolio.
    
    Encuentra los pesos que minimizan la varianza del portafolio.
    
    min w'Cw
    s.t. sum(w) = 1
         w >= 0 (opcional: long only)
    
    Config:
        long_only: Si requerir pesos positivos
        max_weight: Peso máximo por activo
        lookback_days: Período histórico
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.long_only = config.get('long_only', True)
        self.max_weight = config.get('max_weight', 0.20)
        self.lookback_days = config.get('lookback_days', 252)
        
    def calculate_allocations(
        self,
        prices: pd.DataFrame,
        signals: List[StrategySignal],
        risk_budget: Optional[float] = None
    ) -> Dict[str, Allocation]:
        """
        Optimiza para mínima varianza.
        """
        if len(prices) < self.lookback_days:
            return {}
        
        returns = self.calculate_returns(prices.tail(self.lookback_days))
        valid_symbols = returns.columns[returns.count() > self.lookback_days * 0.8]
        returns = returns[valid_symbols].dropna()
        
        if len(valid_symbols) < 2:
            return {}
        
        cov_matrix = returns.cov().values * 252
        n = len(valid_symbols)
        
        # Función objetivo: varianza del portafolio
        def portfolio_variance(w):
            return np.dot(w, np.dot(cov_matrix, w))
        
        # Restricciones
        constraints = [
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
        ]
        
        # Bounds
        if self.long_only:
            bounds = [(0, self.max_weight) for _ in range(n)]
        else:
            bounds = [(-self.max_weight, self.max_weight) for _ in range(n)]
        
        # Initial guess: equal weight
        x0 = np.ones(n) / n
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = minimize(
                portfolio_variance,
                x0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints,
                options={'maxiter': 1000}
            )
        
        if not result.success:
            return {}
        
        weights = result.x
        
        # Crear allocaciones
        allocations = {}
        min_var = portfolio_variance(weights)
        
        for i, symbol in enumerate(valid_symbols):
            allocations[symbol] = Allocation(
                symbol=symbol,
                weight=weights[i],
                expected_return=returns[symbol].mean() * 252,
                expected_risk=np.sqrt(cov_matrix[i, i]),
                confidence=1.0
            )
        
        self.record_allocations(allocations)
        return allocations


class MaximumDiversificationStrategy(BaseStrategy):
    """
    Estrategia de Maximum Diversification.
    
    Maximiza el ratio de diversificación:
    D(w) = (w'σ) / sqrt(w'Cw)
    
    Donde σ es el vector de volatilidades.
    
    Config:
        lookback_days: Período histórico
        max_weight: Peso máximo por activo
    """
    
    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.lookback_days = config.get('lookback_days', 252)
        self.max_weight = config.get('max_weight', 0.25)
        
    def calculate_allocations(
        self,
        prices: pd.DataFrame,
        signals: List[StrategySignal],
        risk_budget: Optional[float] = None
    ) -> Dict[str, Allocation]:
        """
        Maximiza el ratio de diversificación.
        """
        if len(prices) < self.lookback_days:
            return {}
        
        returns = self.calculate_returns(prices.tail(self.lookback_days))
        valid_symbols = returns.columns[returns.count() > self.lookback_days * 0.8]
        returns = returns[valid_symbols].dropna()
        
        if len(valid_symbols) < 2:
            return {}
        
        cov_matrix = returns.cov().values * 252
        vols = np.sqrt(np.diag(cov_matrix))
        n = len(valid_symbols)
        
        # Función objetivo: negative diversification ratio (para minimizar)
        def neg_diversification_ratio(w):
            portfolio_vol = np.sqrt(np.dot(w, np.dot(cov_matrix, w)))
            weighted_vols = np.dot(w, vols)
            
            if portfolio_vol == 0:
                return 0
            
            return -weighted_vols / portfolio_vol
        
        # Restricciones
        constraints = [
            {'type': 'eq', 'fun': lambda w: np.sum(w) - 1}
        ]
        
        bounds = [(0, self.max_weight) for _ in range(n)]
        x0 = np.ones(n) / n
        
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = minimize(
                neg_diversification_ratio,
                x0,
                method='SLSQP',
                bounds=bounds,
                constraints=constraints,
                options={'maxiter': 1000}
            )
        
        if not result.success:
            return {}
        
        weights = result.x
        
        # Crear allocaciones
        allocations = {}
        for i, symbol in enumerate(valid_symbols):
            allocations[symbol] = Allocation(
                symbol=symbol,
                weight=weights[i],
                expected_return=returns[symbol].mean() * 252,
                expected_risk=vols[i],
                confidence=1.0
            )
        
        self.record_allocations(allocations)
        return allocations