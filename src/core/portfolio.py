"""
Gestión de Portafolio y Rebalanceo
Maneja las posiciones, allocación y rebalanceo del portafolio
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict


@dataclass
class Trade:
    """Representa una operación de trading"""
    symbol: str
    side: str  # 'BUY' o 'SELL'
    shares: int
    price: float
    timestamp: datetime
    reason: str
    commission: float = 0.0
    
    @property
    def value(self) -> float:
        return self.shares * self.price
    
    @property
    def net_value(self) -> float:
        return self.value + (self.commission if self.side == 'BUY' else -self.commission)


@dataclass
class Position:
    """Posición detallada con información de riesgo"""
    symbol: str
    sector: str
    entry_price: float
    current_price: float
    shares: int
    entry_date: datetime
    weight: float = 0.0
    beta: float = 1.0
    
    # Niveles de riesgo
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    highest_price: float = 0.0
    
    @property
    def market_value(self) -> float:
        return self.current_price * self.shares
    
    @property
    def cost_basis(self) -> float:
        return self.entry_price * self.shares
    
    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.cost_basis
    
    @property
    def unrealized_pnl_pct(self) -> float:
        return (self.current_price - self.entry_price) / self.entry_price if self.entry_price > 0 else 0
    
    @property
    def is_profitable(self) -> bool:
        return self.unrealized_pnl > 0


class Portfolio:
    """
    Gestiona el estado del portafolio de inversión
    """
    
    def __init__(self, initial_capital: float, cash_buffer: float = 0.05):
        self.initial_capital = initial_capital
        self.cash_buffer = cash_buffer
        self.cash = initial_capital
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.history: List[Dict] = []
        self.last_update = datetime.now()
        
    @property
    def total_value(self) -> float:
        """Valor total del portafolio (cash + posiciones)"""
        return self.cash + sum(p.market_value for p in self.positions.values())
    
    @property
    def invested_value(self) -> float:
        """Valor invertido en posiciones"""
        return sum(p.market_value for p in self.positions.values())
    
    @property
    def available_cash(self) -> float:
        """Efectivo disponible para nuevas posiciones (respetando buffer)"""
        return max(0, self.cash - (self.total_value * self.cash_buffer))
    
    @property
    def num_positions(self) -> int:
        return len(self.positions)
    
    def get_position_weights(self) -> Dict[str, float]:
        """Calcula los pesos actuales de las posiciones"""
        total = self.total_value
        if total == 0:
            return {}
        return {symbol: pos.market_value / total for symbol, pos in self.positions.items()}
    
    def get_sector_exposure(self) -> Dict[str, float]:
        """Calcula la exposición por sector"""
        sector_values = defaultdict(float)
        total = self.total_value
        
        if total == 0:
            return {}
        
        for pos in self.positions.values():
            sector_values[pos.sector] += pos.market_value / total
        
        return dict(sector_values)
    
    def add_position(
        self,
        symbol: str,
        sector: str,
        shares: int,
        price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        beta: float = 1.0
    ) -> None:
        """Añade una nueva posición al portafolio"""
        cost = shares * price
        commission = cost * 0.001  # 0.1% comisión
        total_cost = cost + commission
        
        if total_cost > self.cash:
            raise ValueError(f"Fondos insuficientes. Requerido: {total_cost}, Disponible: {self.cash}")
        
        position = Position(
            symbol=symbol,
            sector=sector,
            entry_price=price,
            current_price=price,
            shares=shares,
            entry_date=datetime.now(),
            stop_loss_price=stop_loss,
            take_profit_price=take_profit,
            highest_price=price,
            beta=beta
        )
        
        self.positions[symbol] = position
        self.cash -= total_cost
        
        # Registrar trade
        trade = Trade(
            symbol=symbol,
            side='BUY',
            shares=shares,
            price=price,
            timestamp=datetime.now(),
            reason='NEW_POSITION',
            commission=commission
        )
        self.trades.append(trade)
        self._update_weights()
    
    def close_position(self, symbol: str, price: float, reason: str) -> float:
        """Cierra una posición existente"""
        if symbol not in self.positions:
            return 0.0
        
        position = self.positions[symbol]
        proceeds = position.shares * price
        commission = proceeds * 0.001
        net_proceeds = proceeds - commission
        
        # Actualizar cash
        self.cash += net_proceeds
        
        # Registrar trade
        trade = Trade(
            symbol=symbol,
            side='SELL',
            shares=position.shares,
            price=price,
            timestamp=datetime.now(),
            reason=reason,
            commission=commission
        )
        self.trades.append(trade)
        
        # Remover posición
        del self.positions[symbol]
        self._update_weights()
        
        return net_proceeds
    
    def partial_close(self, symbol: str, shares: int, price: float, reason: str) -> float:
        """Cierra parcialmente una posición"""
        if symbol not in self.positions:
            return 0.0
        
        position = self.positions[symbol]
        shares = min(shares, position.shares)
        
        proceeds = shares * price
        commission = proceeds * 0.001
        net_proceeds = proceeds - commission
        
        # Actualizar posición
        position.shares -= shares
        self.cash += net_proceeds
        
        # Registrar trade
        trade = Trade(
            symbol=symbol,
            side='SELL',
            shares=shares,
            price=price,
            timestamp=datetime.now(),
            reason=reason,
            commission=commission
        )
        self.trades.append(trade)
        
        if position.shares == 0:
            del self.positions[symbol]
        
        self._update_weights()
        return net_proceeds
    
    def update_prices(self, prices: Dict[str, float]) -> None:
        """Actualiza los precios de las posiciones"""
        for symbol, price in prices.items():
            if symbol in self.positions:
                pos = self.positions[symbol]
                pos.current_price = price
                pos.highest_price = max(pos.highest_price, price)
        
        self._update_weights()
        self.last_update = datetime.now()
    
    def _update_weights(self) -> None:
        """Actualiza los pesos de todas las posiciones"""
        total = self.total_value
        if total > 0:
            for pos in self.positions.values():
                pos.weight = pos.market_value / total
    
    def get_performance_metrics(self) -> Dict[str, float]:
        """Calcula métricas de rendimiento"""
        total_value = self.total_value
        total_return = (total_value - self.initial_capital) / self.initial_capital
        
        # Métricas de trades
        closed_trades = [t for t in self.trades if t.side == 'SELL']
        winning_trades = [t for t in closed_trades if t.price > self.positions.get(t.symbol, Position(t.symbol, '', t.price, t.price, 0, datetime.now())).entry_price]
        
        win_rate = len(winning_trades) / len(closed_trades) if closed_trades else 0
        
        return {
            'total_value': total_value,
            'total_return': total_return,
            'cash': self.cash,
            'invested': self.invested_value,
            'num_positions': self.num_positions,
            'win_rate': win_rate,
            'total_trades': len(closed_trades)
        }
    
    def snapshot(self) -> Dict:
        """Crea un snapshot del estado actual"""
        snapshot = {
            'timestamp': datetime.now(),
            'total_value': self.total_value,
            'cash': self.cash,
            'positions': {
                symbol: {
                    'sector': pos.sector,
                    'shares': pos.shares,
                    'entry_price': pos.entry_price,
                    'current_price': pos.current_price,
                    'market_value': pos.market_value,
                    'unrealized_pnl': pos.unrealized_pnl,
                    'unrealized_pnl_pct': pos.unrealized_pnl_pct,
                    'weight': pos.weight,
                    'stop_loss': pos.stop_loss_price,
                    'take_profit': pos.take_profit_price
                }
                for symbol, pos in self.positions.items()
            },
            'sector_exposure': self.get_sector_exposure(),
            'metrics': self.get_performance_metrics()
        }
        self.history.append(snapshot)
        return snapshot


class RebalancingEngine:
    """
    Motor de rebalanceo de portafolio
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.frequency = config.get('frequency', 'monthly')
        self.threshold = config.get('threshold', 0.05)
        self.max_turnover = config.get('max_turnover', 0.50)
        self.tax_efficient = config.get('tax_efficient', True)
        
        self.last_rebalance = None
        self.rebalance_count = 0
    
    def should_rebalance(
        self,
        portfolio: Portfolio,
        target_weights: Dict[str, float],
        current_date: Optional[datetime] = None
    ) -> bool:
        """
        Determina si es momento de rebalancear
        
        Args:
            portfolio: Portafolio actual
            target_weights: Pesos objetivo
            current_date: Fecha actual
            
        Returns:
            True si se debe rebalancear
        """
        current_date = current_date or datetime.now()
        
        # Verificar frecuencia
        if self.last_rebalance:
            if self.frequency == 'daily':
                min_interval = timedelta(days=1)
            elif self.frequency == 'weekly':
                min_interval = timedelta(weeks=1)
            elif self.frequency == 'monthly':
                min_interval = timedelta(days=30)
            elif self.frequency == 'quarterly':
                min_interval = timedelta(days=90)
            else:  # threshold-based
                min_interval = timedelta(days=1)
            
            if current_date - self.last_rebalance < min_interval and self.frequency != 'threshold':
                return False
        
        # Verificar desviación de pesos
        current_weights = portfolio.get_position_weights()
        
        max_drift = 0
        all_symbols = set(target_weights.keys()) | set(current_weights.keys())
        
        for symbol in all_symbols:
            target = target_weights.get(symbol, 0)
            current = current_weights.get(symbol, 0)
            drift = abs(target - current)
            max_drift = max(max_drift, drift)
        
        return max_drift > self.threshold
    
    def generate_rebalance_trades(
        self,
        portfolio: Portfolio,
        target_weights: Dict[str, float],
        current_prices: Dict[str, float]
    ) -> List[Dict]:
        """
        Genera las órdenes necesarias para rebalancear
        
        Args:
            portfolio: Portafolio actual
            target_weights: Pesos objetivo
            current_prices: Precios actuales
            
        Returns:
            Lista de órdenes de trading
        """
        trades = []
        total_value = portfolio.total_value
        current_weights = portfolio.get_position_weights()
        
        # Símbolos a procesar
        all_symbols = set(target_weights.keys()) | set(current_weights.keys()) | set(portfolio.positions.keys())
        
        for symbol in all_symbols:
            target_weight = target_weights.get(symbol, 0)
            current_weight = current_weights.get(symbol, 0)
            
            target_value = total_value * target_weight
            current_value = total_value * current_weight
            
            price = current_prices.get(symbol)
            if not price or price <= 0:
                continue
            
            if target_weight > current_weight:
                # Necesitamos comprar
                value_to_buy = target_value - current_value
                shares_to_buy = int(value_to_buy / price)
                
                if shares_to_buy > 0:
                    trades.append({
                        'symbol': symbol,
                        'action': 'BUY',
                        'shares': shares_to_buy,
                        'price': price,
                        'value': shares_to_buy * price,
                        'reason': 'REBALANCE'
                    })
            
            elif target_weight < current_weight:
                # Necesitamos vender
                if symbol in portfolio.positions:
                    position = portfolio.positions[symbol]
                    value_to_sell = current_value - target_value
                    shares_to_sell = min(int(value_to_sell / price), position.shares)
                    
                    if shares_to_sell > 0:
                        # Considerar eficiencia fiscal
                        if self.tax_efficient and position.unrealized_pnl < 0:
                            # Evitar realizar pérdidas si es posible
                            reason = 'REBALANCE_TAX_EFFICIENT'
                        else:
                            reason = 'REBALANCE'
                        
                        trades.append({
                            'symbol': symbol,
                            'action': 'SELL',
                            'shares': shares_to_sell,
                            'price': price,
                            'value': shares_to_sell * price,
                            'reason': reason
                        })
        
        # Verificar turnover
        total_trades_value = sum(t['value'] for t in trades)
        turnover = total_trades_value / total_value if total_value > 0 else 0
        
        if turnover > self.max_turnover:
            # Reducir trades proporcionalmente
            scale_factor = self.max_turnover / turnover
            for trade in trades:
                trade['shares'] = int(trade['shares'] * scale_factor)
                trade['value'] = trade['shares'] * trade['price']
        
        self.last_rebalance = datetime.now()
        self.rebalance_count += 1
        
        return [t for t in trades if t['shares'] > 0]
    
    def calculate_optimal_weights(
        self,
        symbols: List[str],
        returns_data: pd.DataFrame,
        method: str = 'risk_parity'
    ) -> Dict[str, float]:
        """
        Calcula pesos óptimos para el portafolio
        
        Args:
            symbols: Lista de símbolos
            returns_data: DataFrame de retornos históricos
            method: Método de optimización ('equal', 'risk_parity', 'min_variance')
            
        Returns:
            Diccionario de pesos óptimos
        """
        valid_symbols = [s for s in symbols if s in returns_data.columns]
        
        if len(valid_symbols) == 0:
            return {}
        
        if method == 'equal':
            weight = 1.0 / len(valid_symbols)
            return {s: weight for s in valid_symbols}
        
        elif method == 'risk_parity':
            # Risk parity: pesos inversamente proporcionales a la volatilidad
            volatilities = returns_data[valid_symbols].std() * np.sqrt(252)
            inverse_vol = 1 / volatilities
            weights = inverse_vol / inverse_vol.sum()
            return {s: weights[s] for s in valid_symbols}
        
        elif method == 'min_variance':
            # Simplificación: usar volatilidad inversa
            volatilities = returns_data[valid_symbols].std()
            inverse_vol = 1 / volatilities
            weights = inverse_vol / inverse_vol.sum()
            return {s: weights[s] for s in valid_symbols}
        
        else:
            return {s: 1.0 / len(valid_symbols) for s in valid_symbols}
