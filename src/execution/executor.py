"""
Ejecutor de Órdenes
Maneja la ejecución de trades con stop loss y take profit
"""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    """Representa una orden de trading"""
    symbol: str
    side: OrderSide
    order_type: OrderType
    shares: int
    price: Optional[float] = None  # Para limit orders
    stop_price: Optional[float] = None  # Para stop orders
    status: OrderStatus = OrderStatus.PENDING
    filled_shares: int = 0
    filled_price: Optional[float] = None
    created_at: datetime = None
    filled_at: Optional[datetime] = None
    order_id: str = None
    
    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()
    
    @property
    def is_filled(self) -> bool:
        return self.status == OrderStatus.FILLED
    
    @property
    def remaining_shares(self) -> int:
        return self.shares - self.filled_shares
    
    @property
    def fill_percentage(self) -> float:
        return self.filled_shares / self.shares if self.shares > 0 else 0


@dataclass
class ExitRule:
    """Regla de salida para una posición"""
    rule_type: str  # 'stop_loss', 'take_profit', 'trailing_stop'
    price: float
    percentage: float = 1.0  # Porcentaje de posición a cerrar
    is_trailing: bool = False
    trailing_distance: Optional[float] = None


class TradeExecutor:
    """
    Ejecuta órdenes y maneja reglas de salida
    """
    
    def __init__(self, commission_rate: float = 0.001):
        self.commission_rate = commission_rate
        self.orders: List[Order] = []
        self.exit_rules: Dict[str, List[ExitRule]] = {}
        self.trade_history: List[Dict] = []
    
    def create_market_order(
        self,
        symbol: str,
        side: OrderSide,
        shares: int
    ) -> Order:
        """Crea una orden de mercado"""
        order = Order(
            symbol=symbol,
            side=side,
            order_type=OrderType.MARKET,
            shares=shares
        )
        self.orders.append(order)
        return order
    
    def create_limit_order(
        self,
        symbol: str,
        side: OrderSide,
        shares: int,
        price: float
    ) -> Order:
        """Crea una orden limit"""
        order = Order(
            symbol=symbol,
            side=side,
            order_type=OrderType.LIMIT,
            shares=shares,
            price=price
        )
        self.orders.append(order)
        return order
    
    def create_stop_order(
        self,
        symbol: str,
        side: OrderSide,
        shares: int,
        stop_price: float
    ) -> Order:
        """Crea una orden stop"""
        order = Order(
            symbol=symbol,
            side=side,
            order_type=OrderType.STOP,
            shares=shares,
            stop_price=stop_price
        )
        self.orders.append(order)
        return order
    
    def fill_order(self, order: Order, price: float, shares: Optional[int] = None) -> None:
        """
        Ejecuta una orden
        
        Args:
            order: Orden a ejecutar
            price: Precio de ejecución
            shares: Cantidad ejecutada (default: todas)
        """
        shares = shares or order.remaining_shares
        shares = min(shares, order.remaining_shares)
        
        if shares <= 0:
            return
        
        order.filled_shares += shares
        order.filled_price = price
        order.filled_at = datetime.now()
        
        if order.filled_shares >= order.shares:
            order.status = OrderStatus.FILLED
        else:
            order.status = OrderStatus.PARTIALLY_FILLED
        
        # Registrar trade
        self.trade_history.append({
            'order_id': order.order_id,
            'symbol': order.symbol,
            'side': order.side.value,
            'shares': shares,
            'price': price,
            'commission': shares * price * self.commission_rate,
            'timestamp': order.filled_at
        })
    
    def cancel_order(self, order: Order) -> None:
        """Cancela una orden pendiente"""
        if order.status == OrderStatus.PENDING:
            order.status = OrderStatus.CANCELLED
    
    def set_exit_rules(
        self,
        symbol: str,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        trailing_stop: Optional[float] = None
    ) -> None:
        """
        Establece reglas de salida para una posición
        
        Args:
            symbol: Símbolo de la posición
            stop_loss: Precio de stop loss
            take_profit: Precio de take profit
            trailing_stop: Distancia para trailing stop
        """
        rules = []
        
        if stop_loss:
            rules.append(ExitRule(
                rule_type='stop_loss',
                price=stop_loss,
                percentage=1.0
            ))
        
        if take_profit:
            # Take profit parcial según configuración
            levels = [
                (0.50, 0.30),  # A 50% del target, cerrar 30%
                (0.75, 0.30),  # A 75% del target, cerrar 30%
                (1.00, 0.40),  # A 100% del target, cerrar 40%
            ]
            
            for level_pct, close_pct in levels:
                price = stop_loss + (take_profit - stop_loss) * level_pct if stop_loss else take_profit * 0.9
                rules.append(ExitRule(
                    rule_type=f'take_profit_{int(level_pct*100)}',
                    price=price,
                    percentage=close_pct
                ))
        
        if trailing_stop:
            rules.append(ExitRule(
                rule_type='trailing_stop',
                price=0,  # Se actualizará dinámicamente
                percentage=1.0,
                is_trailing=True,
                trailing_distance=trailing_stop
            ))
        
        self.exit_rules[symbol] = rules
    
    def check_exit_rules(
        self,
        symbol: str,
        current_price: float,
        entry_price: float,
        highest_price: float
    ) -> List[ExitRule]:
        """
        Verifica si se deben ejecutar reglas de salida
        
        Args:
            symbol: Símbolo de la posición
            current_price: Precio actual
            entry_price: Precio de entrada
            highest_price: Precio más alto alcanzado
            
        Returns:
            Lista de reglas que se deben ejecutar
        """
        triggered_rules = []
        rules = self.exit_rules.get(symbol, [])
        
        for rule in rules:
            if rule.rule_type == 'stop_loss':
                if current_price <= rule.price:
                    triggered_rules.append(rule)
            
            elif rule.rule_type.startswith('take_profit'):
                if current_price >= rule.price:
                    triggered_rules.append(rule)
            
            elif rule.rule_type == 'trailing_stop' and rule.is_trailing:
                # Actualizar trailing stop
                trailing_price = highest_price - rule.trailing_distance
                if rule.price == 0:
                    rule.price = trailing_price
                else:
                    rule.price = max(rule.price, trailing_price)
                
                if current_price <= rule.price:
                    triggered_rules.append(rule)
        
        return triggered_rules
    
    def update_trailing_stop(
        self,
        symbol: str,
        highest_price: float,
        atr_multiplier: float = 2.0,
        atr_value: float = 0.0
    ) -> Optional[float]:
        """
        Actualiza el trailing stop dinámicamente
        
        Args:
            symbol: Símbolo
            highest_price: Precio más alto
            atr_multiplier: Multiplicador de ATR
            atr_value: Valor del ATR
            
        Returns:
            Nuevo precio de stop o None
        """
        rules = self.exit_rules.get(symbol, [])
        
        for rule in rules:
            if rule.rule_type == 'trailing_stop' and rule.is_trailing:
                new_stop = highest_price - (atr_value * atr_multiplier)
                
                if rule.price == 0:
                    rule.price = new_stop
                else:
                    rule.price = max(rule.price, new_stop)
                
                return rule.price
        
        return None
    
    def execute_stop_loss(
        self,
        symbol: str,
        shares: int,
        current_price: float
    ) -> Order:
        """Ejecuta stop loss para una posición"""
        order = self.create_market_order(
            symbol=symbol,
            side=OrderSide.SELL,
            shares=shares
        )
        self.fill_order(order, current_price)
        return order
    
    def execute_take_profit(
        self,
        symbol: str,
        shares: int,
        current_price: float,
        level: str = 'full'
    ) -> Order:
        """Ejecuta take profit parcial o total"""
        order = self.create_market_order(
            symbol=symbol,
            side=OrderSide.SELL,
            shares=shares
        )
        self.fill_order(order, current_price)
        return order
    
    def get_open_orders(self, symbol: Optional[str] = None) -> List[Order]:
        """Obtiene órdenes abiertas"""
        open_orders = [
            o for o in self.orders
            if o.status in [OrderStatus.PENDING, OrderStatus.PARTIALLY_FILLED]
        ]
        
        if symbol:
            open_orders = [o for o in open_orders if o.symbol == symbol]
        
        return open_orders
    
    def calculate_position_exposure(
        self,
        position_value: float,
        total_portfolio_value: float
    ) -> float:
        """Calcula la exposición de una posición"""
        return position_value / total_portfolio_value if total_portfolio_value > 0 else 0
    
    def estimate_slippage(
        self,
        shares: int,
        avg_volume: float,
        volatility: float
    ) -> float:
        """
        Estima el slippage esperado
        
        Args:
            shares: Cantidad de acciones
            avg_volume: Volumen promedio
            volatility: Volatilidad anualizada
            
        Returns:
            Estimación de slippage como porcentaje
        """
        # Fórmula simplificada de slippage
        volume_impact = shares / avg_volume if avg_volume > 0 else 0
        base_slippage = 0.0005  # 5 bps base
        
        return base_slippage + (volume_impact * 0.001) + (volatility * 0.0001)
