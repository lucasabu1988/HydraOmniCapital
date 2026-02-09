"""
Gestión de Riesgo por Posición
Maneja stop loss, take profit y sizing de posiciones
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from enum import Enum


class StopLossMethod(Enum):
    FIXED = "fixed"
    ATR = "atr"
    VOLATILITY = "volatility"


class TakeProfitMethod(Enum):
    FIXED = "fixed"
    RISK_REWARD = "risk_reward"


@dataclass
class Position:
    """Representa una posición en el portafolio"""
    symbol: str
    entry_price: float
    current_price: float
    shares: int
    entry_date: pd.Timestamp
    sector: str
    
    @property
    def market_value(self) -> float:
        return self.current_price * self.shares
    
    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.entry_price) * self.shares
    
    @property
    def unrealized_pnl_pct(self) -> float:
        return (self.current_price - self.entry_price) / self.entry_price


@dataclass
class RiskParameters:
    """Parámetros de riesgo para una posición"""
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    position_size_pct: float = 0.0
    risk_amount: float = 0.0


class PositionRiskManager:
    """
    Gestiona el riesgo a nivel de posición individual.
    Implementa stop loss, take profit y cálculo de tamaño de posición.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.stop_loss_config = config.get('stop_loss', {})
        self.take_profit_config = config.get('take_profit', {})
        self.position_config = config.get('position_sizing', {})
        
    def calculate_atr(self, prices: pd.Series, period: int = 14) -> float:
        """
        Calcula el Average True Range (ATR)
        
        Args:
            prices: Serie de precios de cierre
            period: Período para el cálculo
            
        Returns:
            Valor del ATR
        """
        if len(prices) < period + 1:
            return prices.std()
            
        # Calcular True Range
        high_low = prices.diff().abs()
        high_close = (prices - prices.shift(1)).abs()
        
        tr = pd.concat([high_low, high_close], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean().iloc[-1]
        
        return atr if not np.isnan(atr) else prices.std()
    
    def calculate_stop_loss(
        self,
        entry_price: float,
        prices: pd.Series,
        method: Optional[str] = None
    ) -> float:
        """
        Calcula el nivel de stop loss
        
        Args:
            entry_price: Precio de entrada
            prices: Serie de precios históricos
            method: Método de cálculo (fixed, atr, volatility)
            
        Returns:
            Precio del stop loss
        """
        method = method or self.stop_loss_config.get('method', 'fixed')
        
        if method == 'fixed':
            pct = self.stop_loss_config.get('fixed_percentage', 0.05)
            return entry_price * (1 - pct)
            
        elif method == 'atr':
            atr = self.calculate_atr(prices)
            multiplier = self.stop_loss_config.get('atr_multiplier', 2.0)
            return entry_price - (atr * multiplier)
            
        elif method == 'volatility':
            volatility = prices.pct_change().std() * np.sqrt(252)
            return entry_price * (1 - volatility * 1.5)
            
        else:
            raise ValueError(f"Método de stop loss desconocido: {method}")
    
    def calculate_take_profit(
        self,
        entry_price: float,
        stop_loss_price: float,
        method: Optional[str] = None
    ) -> float:
        """
        Calcula el nivel de take profit
        
        Args:
            entry_price: Precio de entrada
            stop_loss_price: Precio del stop loss
            method: Método de cálculo (fixed, risk_reward)
            
        Returns:
            Precio del take profit
        """
        method = method or self.take_profit_config.get('method', 'risk_reward')
        
        if method == 'fixed':
            pct = self.take_profit_config.get('fixed_percentage', 0.15)
            return entry_price * (1 + pct)
            
        elif method == 'risk_reward':
            ratio = self.take_profit_config.get('risk_reward_ratio', 3.0)
            risk = entry_price - stop_loss_price
            return entry_price + (risk * ratio)
            
        else:
            raise ValueError(f"Método de take profit desconocido: {method}")
    
    def calculate_position_size(
        self,
        capital: float,
        entry_price: float,
        stop_loss_price: float,
        win_rate: float = 0.55,
        avg_win_loss_ratio: float = 2.0
    ) -> Dict[str, float]:
        """
        Calcula el tamaño óptimo de la posición usando Kelly Criterion
        
        Args:
            capital: Capital total disponible
            entry_price: Precio de entrada
            stop_loss_price: Precio del stop loss
            win_rate: Probabilidad de ganancia (default 55%)
            avg_win_loss_ratio: Ratio promedio ganancia/pérdida
            
        Returns:
            Diccionario con tamaño de posición y métricas
        """
        method = self.position_config.get('method', 'kelly_criterion')
        
        if method == 'fixed':
            position_pct = 0.05  # 5% fijo
            
        elif method == 'kelly_criterion':
            # Fórmula de Kelly: f* = (p*b - q) / b
            # p = probabilidad de ganar, q = probabilidad de perder, b = ratio ganancia/pérdida
            p = win_rate
            q = 1 - p
            b = avg_win_loss_ratio
            
            kelly_pct = (p * b - q) / b if b != 0 else 0
            kelly_fraction = self.position_config.get('kelly_fraction', 0.25)
            position_pct = max(0, kelly_pct * kelly_fraction)
            
        elif method == 'volatility_target':
            # Tamaño basado en volatilidad objetivo
            position_pct = 0.05  # Simplificado
        else:
            position_pct = 0.05
            
        # Limitar tamaño máximo y mínimo
        max_size = self.config.get('max_position_size', 0.10)
        min_size = self.config.get('min_position_size', 0.02)
        position_pct = min(max_size, max(min_size, position_pct))
        
        # Calcular shares
        risk_per_share = entry_price - stop_loss_price
        max_position_value = capital * position_pct
        shares = int(max_position_value / entry_price)
        
        # Calcular riesgo total
        risk_amount = shares * risk_per_share
        risk_pct = risk_amount / capital
        
        return {
            'position_pct': position_pct,
            'shares': shares,
            'position_value': shares * entry_price,
            'risk_amount': risk_amount,
            'risk_pct': risk_pct,
            'risk_per_share': risk_per_share
        }
    
    def check_exit_signals(self, position: Position, current_price: float) -> Dict[str, Any]:
        """
        Verifica si se deben ejecutar señales de salida
        
        Args:
            position: Objeto Position
            current_price: Precio actual
            
        Returns:
            Diccionario con señales de salida
        """
        signals = {
            'should_exit': False,
            'reason': None,
            'exit_price': None,
            'exit_pct': 0.0
        }
        
        # Verificar stop loss
        if hasattr(position, 'stop_loss_price') and position.stop_loss_price:
            if current_price <= position.stop_loss_price:
                signals['should_exit'] = True
                signals['reason'] = 'STOP_LOSS'
                signals['exit_price'] = position.stop_loss_price
                signals['exit_pct'] = 1.0
                return signals
        
        # Verificar take profit parcial
        partial_config = self.take_profit_config.get('partial_exit', {})
        if partial_config.get('enabled', False):
            entry_price = position.entry_price
            take_profit_price = getattr(position, 'take_profit_price', entry_price * 1.15)
            
            progress = (current_price - entry_price) / (take_profit_price - entry_price)
            
            levels = partial_config.get('levels', [])
            for level in levels:
                if progress >= level['percent']:
                    signals['should_exit'] = True
                    signals['reason'] = f'TAKE_PROFIT_PARTIAL_{int(level["percent"]*100)}'
                    signals['exit_price'] = current_price
                    signals['exit_pct'] = level['close']
                    return signals
        
        return signals
    
    def update_trailing_stop(
        self,
        position: Position,
        current_price: float,
        highest_price: float
    ) -> float:
        """
        Actualiza el trailing stop loss
        
        Args:
            position: Objeto Position
            current_price: Precio actual
            highest_price: Precio más alto alcanzado
            
        Returns:
            Nuevo precio de stop loss
        """
        if not self.stop_loss_config.get('trailing', False):
            return getattr(position, 'stop_loss_price', 0)
        
        # Trailing stop basado en ATR o porcentaje
        method = self.stop_loss_config.get('method', 'fixed')
        
        if method == 'atr':
            # Implementación simplificada
            trailing_pct = 0.10  # 10% debajo del máximo
        else:
            trailing_pct = self.stop_loss_config.get('fixed_percentage', 0.05)
        
        new_stop = highest_price * (1 - trailing_pct)
        current_stop = getattr(position, 'stop_loss_price', 0)
        
        # Solo subir el stop, nunca bajarlo
        return max(new_stop, current_stop) if current_stop and current_stop > 0 else new_stop
