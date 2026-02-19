"""
OmniCapital v6 - Broker Integration Module
Integracion con brokers para ejecucion de ordenes.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class Order:
    """Representa una orden de trading"""
    symbol: str
    action: str  # 'BUY' o 'SELL'
    quantity: float
    order_type: str = 'MARKET'  # 'MARKET', 'LIMIT'
    limit_price: Optional[float] = None
    order_id: Optional[str] = None
    status: str = 'PENDING'  # 'PENDING', 'SUBMITTED', 'FILLED', 'CANCELLED', 'ERROR'
    filled_quantity: float = 0
    filled_price: Optional[float] = None
    commission: float = 0
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


@dataclass
class Position:
    """Representa una posicion"""
    symbol: str
    shares: float
    avg_cost: float
    market_price: Optional[float] = None
    market_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    realized_pnl: float = 0
    entry_time: datetime = None
    high_price: Optional[float] = None  # For COMPASS v8.2 trailing stop

    def __post_init__(self):
        if self.entry_time is None:
            self.entry_time = datetime.now()
        if self.high_price is None:
            self.high_price = self.avg_cost
        self.update_market_data(self.market_price or self.avg_cost)

    def update_market_data(self, price: float):
        """Actualiza datos de mercado"""
        self.market_price = price
        self.market_value = self.shares * price
        self.unrealized_pnl = (price - self.avg_cost) * self.shares
        # Track high watermark for trailing stop
        if self.high_price is None or price > self.high_price:
            self.high_price = price


@dataclass
class Portfolio:
    """Estado del portfolio"""
    cash: float
    positions: Dict[str, Position]
    total_value: float
    buying_power: float
    
    @property
    def gross_value(self) -> float:
        """Valor bruto (sin considerar deuda)"""
        positions_value = sum(p.market_value for p in self.positions.values())
        return self.cash + positions_value


class Broker(ABC):
    """Interfaz base para brokers"""
    
    @abstractmethod
    def connect(self) -> bool:
        """Conecta con el broker"""
        pass
    
    @abstractmethod
    def disconnect(self):
        """Desconecta del broker"""
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """Verifica conexion"""
        pass
    
    @abstractmethod
    def submit_order(self, order: Order) -> Order:
        """Envia una orden"""
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancela una orden"""
        pass
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> Order:
        """Obtiene estado de una orden"""
        pass
    
    @abstractmethod
    def get_positions(self) -> Dict[str, Position]:
        """Obtiene posiciones actuales"""
        pass
    
    @abstractmethod
    def get_portfolio(self) -> Portfolio:
        """Obtiene estado del portfolio"""
        pass
    
    @abstractmethod
    def get_account_info(self) -> Dict:
        """Obtiene informacion de la cuenta"""
        pass


class PaperBroker(Broker):
    """Broker de papel para testing sin riesgo real"""
    
    def __init__(self, initial_cash: float = 100000, 
                 commission_per_share: float = 0.001,
                 fill_delay: int = 1):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.commission_per_share = commission_per_share
        self.fill_delay = fill_delay  # segundos para simular delay de ejecucion
        
        self.positions: Dict[str, Position] = {}
        self.orders: Dict[str, Order] = {}
        self.order_history: List[Order] = []
        self._connected = False
        self._order_counter = 0
        
        # Para simular precios
        self.price_feed = None
        
    def connect(self) -> bool:
        """Conecta el broker de papel"""
        self._connected = True
        logger.info(f"Paper broker conectado. Cash inicial: ${self.cash:,.2f}")
        return True
    
    def disconnect(self):
        """Desconecta"""
        self._connected = False
        logger.info("Paper broker desconectado")
    
    def is_connected(self) -> bool:
        return self._connected
    
    def set_price_feed(self, feed):
        """Establece feed de precios para simulacion"""
        self.price_feed = feed
    
    def _get_fill_price(self, symbol: str, action: str) -> Optional[float]:
        """Obtiene precio de ejecucion"""
        if self.price_feed:
            price = self.price_feed.get_price(symbol)
            if price:
                # Simular slippage
                import random
                slippage = random.uniform(-0.001, 0.001)
                return price * (1 + slippage)
        return None
    
    def submit_order(self, order: Order) -> Order:
        """Envia orden y la ejecuta inmediatamente (paper)"""
        if not self._connected:
            raise ConnectionError("Broker no conectado")
        
        self._order_counter += 1
        order.order_id = f"PAPER_{self._order_counter}"
        order.status = 'SUBMITTED'
        
        # Obtener precio de ejecucion
        fill_price = self._get_fill_price(order.symbol, order.action)
        
        if not fill_price:
            order.status = 'ERROR'
            logger.error(f"No se pudo obtener precio para {order.symbol}")
            return order
        
        # Simular delay
        import time
        time.sleep(self.fill_delay)
        
        # Ejecutar orden
        commission = order.quantity * self.commission_per_share
        total_cost = order.quantity * fill_price + commission
        
        if order.action == 'BUY':
            if total_cost > self.cash:
                order.status = 'ERROR'
                logger.error(f"Fondos insuficientes: ${self.cash:.2f} < ${total_cost:.2f}")
                return order
            
            # Actualizar posicion
            if order.symbol in self.positions:
                pos = self.positions[order.symbol]
                total_shares = pos.shares + order.quantity
                total_cost_basis = pos.shares * pos.avg_cost + order.quantity * fill_price
                pos.shares = total_shares
                pos.avg_cost = total_cost_basis / total_shares
            else:
                self.positions[order.symbol] = Position(
                    symbol=order.symbol,
                    shares=order.quantity,
                    avg_cost=fill_price
                )
            
            self.cash -= total_cost
            
        elif order.action == 'SELL':
            if order.symbol not in self.positions:
                order.status = 'ERROR'
                logger.error(f"No hay posicion de {order.symbol} para vender")
                return order
            
            pos = self.positions[order.symbol]
            if order.quantity > pos.shares:
                order.status = 'ERROR'
                logger.error(f"Cantidad insuficiente: {pos.shares:.2f} < {order.quantity:.2f}")
                return order
            
            # Calcular P&L realizado
            realized_pnl = (fill_price - pos.avg_cost) * order.quantity
            pos.realized_pnl += realized_pnl
            
            # Actualizar posicion
            pos.shares -= order.quantity
            if pos.shares <= 0:
                del self.positions[order.symbol]
            
            proceeds = order.quantity * fill_price - commission
            self.cash += proceeds
        
        # Actualizar orden
        order.status = 'FILLED'
        order.filled_quantity = order.quantity
        order.filled_price = fill_price
        order.commission = commission
        
        self.orders[order.order_id] = order
        self.order_history.append(order)
        
        logger.info(f"Orden ejecutada: {order.action} {order.quantity} {order.symbol} "
                   f"@ ${fill_price:.2f} | P&L: ${realized_pnl:.2f}" if order.action == 'SELL' else "")
        
        return order
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancela una orden pendiente"""
        if order_id in self.orders:
            order = self.orders[order_id]
            if order.status == 'PENDING':
                order.status = 'CANCELLED'
                return True
        return False
    
    def get_order_status(self, order_id: str) -> Optional[Order]:
        """Obtiene estado de orden"""
        return self.orders.get(order_id, None)
    
    def get_positions(self) -> Dict[str, Position]:
        """Obtiene posiciones"""
        # Actualizar precios de mercado
        if self.price_feed:
            for symbol, pos in self.positions.items():
                price = self.price_feed.get_price(symbol)
                if price:
                    pos.update_market_data(price)
        return self.positions.copy()
    
    def get_portfolio(self) -> Portfolio:
        """Obtiene estado del portfolio"""
        positions = self.get_positions()
        positions_value = sum(p.market_value for p in positions.values())
        total_value = self.cash + positions_value
        
        return Portfolio(
            cash=self.cash,
            positions=positions,
            total_value=total_value,
            buying_power=self.cash * 2  # Simular 2:1 margin
        )
    
    def get_account_info(self) -> Dict:
        """Obtiene info de cuenta"""
        portfolio = self.get_portfolio()
        return {
            'cash': portfolio.cash,
            'total_value': portfolio.total_value,
            'buying_power': portfolio.buying_power,
            'num_positions': len(portfolio.positions),
            'unrealized_pnl': sum(p.unrealized_pnl for p in portfolio.positions.values()),
            'realized_pnl': sum(p.realized_pnl for p in portfolio.positions.values())
        }


class IBKRBroker(Broker):
    """Broker para Interactive Brokers"""
    
    def __init__(self, host: str = '127.0.0.1', port: int = 7497, 
                 client_id: int = 1, paper_trading: bool = True):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.paper_trading = paper_trading
        self.ib = None
        
    def connect(self) -> bool:
        """Conecta con IBKR"""
        try:
            from ib_insync import IB, Stock, MarketOrder
            self.ib = IB()
            self.ib.connect(self.host, self.port, clientId=self.client_id)
            logger.info(f"Conectado a IBKR ({'PAPER' if self.paper_trading else 'LIVE'})")
            return True
        except Exception as e:
            logger.error(f"Error conectando a IBKR: {e}")
            return False
    
    def disconnect(self):
        if self.ib:
            self.ib.disconnect()
            logger.info("Desconectado de IBKR")
    
    def is_connected(self) -> bool:
        return self.ib is not None and self.ib.isConnected()
    
    def submit_order(self, order: Order) -> Order:
        """Envia orden a IBKR"""
        from ib_insync import Stock, MarketOrder, LimitOrder
        
        contract = Stock(order.symbol, 'SMART', 'USD')
        
        if order.order_type == 'MARKET':
            ib_order = MarketOrder(order.action, order.quantity)
        elif order.order_type == 'LIMIT':
            ib_order = LimitOrder(order.action, order.quantity, order.limit_price)
        else:
            raise ValueError(f"Tipo de orden no soportado: {order.order_type}")
        
        trade = self.ib.placeOrder(contract, ib_order)
        
        order.order_id = str(trade.order.orderId)
        order.status = 'SUBMITTED'
        
        # Esperar fill
        self.ib.sleep(5)  # Esperar hasta 5 segundos
        
        if trade.orderStatus.status == 'Filled':
            order.status = 'FILLED'
            order.filled_quantity = trade.orderStatus.filled
            order.filled_price = trade.orderStatus.avgFillPrice
            order.commission = sum(c.commission for c in trade.commissions)
        
        return order
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancela orden"""
        for trade in self.ib.trades():
            if str(trade.order.orderId) == order_id:
                self.ib.cancelOrder(trade.order)
                return True
        return False
    
    def get_order_status(self, order_id: str) -> Optional[Order]:
        """Obtiene estado de orden"""
        for trade in self.ib.trades():
            if str(trade.order.orderId) == order_id:
                return Order(
                    symbol=trade.contract.symbol,
                    action=trade.order.action,
                    quantity=trade.order.totalQuantity,
                    order_id=order_id,
                    status=trade.orderStatus.status,
                    filled_quantity=trade.orderStatus.filled,
                    filled_price=trade.orderStatus.avgFillPrice
                )
        return None
    
    def get_positions(self) -> Dict[str, Position]:
        """Obtiene posiciones"""
        positions = {}
        for pos in self.ib.positions():
            positions[pos.contract.symbol] = Position(
                symbol=pos.contract.symbol,
                shares=pos.position,
                avg_cost=pos.avgCost
            )
        return positions
    
    def get_portfolio(self) -> Portfolio:
        """Obtiene portfolio"""
        account = self.ib.accountSummary()
        
        cash = 0
        buying_power = 0
        for item in account:
            if item.tag == 'AvailableFunds':
                cash = float(item.value)
            elif item.tag == 'BuyingPower':
                buying_power = float(item.value)
        
        positions = self.get_positions()
        
        # Calcular total value
        total = cash
        for pos in positions.values():
            ticker = self.ib.reqMktData(Stock(pos.symbol, 'SMART', 'USD'))
            self.ib.sleep(0.5)
            price = ticker.last or ticker.close
            if price:
                total += pos.shares * price
        
        return Portfolio(
            cash=cash,
            positions=positions,
            total_value=total,
            buying_power=buying_power
        )
    
    def get_account_info(self) -> Dict:
        """Obtiene info de cuenta"""
        portfolio = self.get_portfolio()
        return {
            'cash': portfolio.cash,
            'total_value': portfolio.total_value,
            'buying_power': portfolio.buying_power,
            'num_positions': len(portfolio.positions)
        }


if __name__ == "__main__":
    # Test del paper broker
    logging.basicConfig(level=logging.INFO)
    
    print("Probando Paper Broker...")
    broker = PaperBroker(initial_cash=100000)
    broker.connect()
    
    # Crear orden de compra
    order = Order(symbol='AAPL', action='BUY', quantity=10)
    result = broker.submit_order(order)
    
    print(f"\nOrden: {result}")
    print(f"\nPortfolio: {broker.get_portfolio()}")
    print(f"\nAccount Info: {broker.get_account_info()}")
