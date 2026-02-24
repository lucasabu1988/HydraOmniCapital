"""
OmniCapital v8.2 - Broker Integration Module
Integracion con brokers para ejecucion de ordenes.
Incluye order timeout, fill circuit breaker y retry logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional
import logging

# Fill price circuit breaker: max deviation from reference price
MAX_FILL_DEVIATION = 0.02  # 2%

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
    submitted_at: Optional[datetime] = None  # When order was submitted to broker

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()

    def is_stale(self, max_age_seconds: int = 300) -> bool:
        """Check if order has been pending/submitted too long"""
        if self.submitted_at and self.status in ('PENDING', 'SUBMITTED'):
            age = (datetime.now() - self.submitted_at).total_seconds()
            return age > max_age_seconds
        return False


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


# ======================================================================
# Execution Strategy Framework (Chassis Improvement)
# ======================================================================
# Selects HOW orders are executed (TWAP, VWAP, Passive, etc.)
# The WHAT (which stocks, when, how many) comes from the locked COMPASS algorithm.
# Activated only when execution_strategy is set in COMPASSLive config.
# Default (None) = current MOC behavior preserved exactly.
# ======================================================================

class ExecutionStrategy(ABC):
    """Base class for execution algorithms."""

    def __init__(self):
        self.fills = []       # History of fills for stats
        self.name = 'base'

    @abstractmethod
    def execute(self, broker: 'Broker', order: Order, market_data: dict) -> Order:
        """Execute an order using this strategy.

        Args:
            broker: connected Broker instance
            order: the Order to execute
            market_data: dict with keys: price, volume, adv, spread_est

        Returns:
            Filled Order with execution stats
        """
        pass

    def get_stats(self) -> dict:
        """Return execution performance statistics."""
        if not self.fills:
            return {'strategy': self.name, 'total_fills': 0}
        avg_slip = sum(f.get('slippage_bps', 0) for f in self.fills) / len(self.fills)
        return {
            'strategy': self.name,
            'total_fills': len(self.fills),
            'avg_slippage_bps': round(avg_slip, 2),
        }

    def _record_fill(self, order: Order, arrival_price: float):
        """Record fill stats for a completed order."""
        if order.filled_price and arrival_price > 0:
            if order.action == 'BUY':
                slip_bps = (order.filled_price - arrival_price) / arrival_price * 10000
            else:
                slip_bps = (arrival_price - order.filled_price) / arrival_price * 10000
            self.fills.append({
                'symbol': order.symbol,
                'action': order.action,
                'slippage_bps': slip_bps,
                'filled_price': order.filled_price,
                'arrival_price': arrival_price,
                'timestamp': datetime.now(),
            })


class MOCStrategy(ExecutionStrategy):
    """Market-on-Close: submit single MOC order before 15:50 ET deadline.
    This extracts the current behavior into a strategy object.
    """

    def __init__(self):
        super().__init__()
        self.name = 'MOC'

    def execute(self, broker, order, market_data):
        arrival_price = market_data.get('price', 0)
        result = broker.submit_order(order)
        self._record_fill(result, arrival_price)
        return result


class TWAPStrategy(ExecutionStrategy):
    """Time-Weighted Average Price: split into N child orders over 15 minutes.

    In PaperBroker: simulates N fills with small random timing offsets.
    In IBKRBroker: will submit N real child orders at interval_seconds apart.
    """

    def __init__(self, n_slices: int = 5, interval_seconds: int = 180):
        super().__init__()
        self.name = 'TWAP'
        self.n_slices = n_slices
        self.interval_seconds = interval_seconds

    def execute(self, broker, order, market_data):
        import time
        arrival_price = market_data.get('price', 0)
        child_qty = order.quantity / self.n_slices
        child_fills = []

        for i in range(self.n_slices):
            child_order = Order(
                symbol=order.symbol,
                action=order.action,
                quantity=child_qty,
                order_type='MARKET',
            )
            result = broker.submit_order(child_order)
            if result.filled_price:
                child_fills.append((result.filled_price, child_qty))

            # Wait between children (skip last wait)
            if i < self.n_slices - 1 and hasattr(broker, '_is_live') and broker._is_live:
                time.sleep(self.interval_seconds)

        # Compute TWAP fill price
        if child_fills:
            total_qty = sum(q for _, q in child_fills)
            twap_price = sum(p * q for p, q in child_fills) / total_qty
            order.filled_price = twap_price
            order.filled_quantity = total_qty
            order.status = 'FILLED'
            order.commission = sum(0.001 * q for _, q in child_fills)

        self._record_fill(order, arrival_price)
        return order


class VWAPStrategy(ExecutionStrategy):
    """Volume-Weighted Average Price: weight child orders by volume profile.

    Uses U-shaped end-of-day volume curve: heavier at window open and close.
    """

    def __init__(self, n_slices: int = 5, volume_weights: list = None):
        super().__init__()
        self.name = 'VWAP'
        self.n_slices = n_slices
        self.volume_weights = volume_weights or [0.30, 0.20, 0.15, 0.15, 0.20]

    def execute(self, broker, order, market_data):
        import time
        arrival_price = market_data.get('price', 0)
        child_fills = []

        for i in range(self.n_slices):
            child_qty = order.quantity * self.volume_weights[i]
            child_order = Order(
                symbol=order.symbol,
                action=order.action,
                quantity=child_qty,
                order_type='MARKET',
            )
            result = broker.submit_order(child_order)
            if result.filled_price:
                child_fills.append((result.filled_price, child_qty))

            if i < self.n_slices - 1 and hasattr(broker, '_is_live') and broker._is_live:
                time.sleep(180)

        if child_fills:
            total_qty = sum(q for _, q in child_fills)
            vwap_price = sum(p * q for p, q in child_fills) / total_qty
            order.filled_price = vwap_price
            order.filled_quantity = total_qty
            order.status = 'FILLED'
            order.commission = sum(0.001 * q for _, q in child_fills)

        self._record_fill(order, arrival_price)
        return order


class PassiveLimitStrategy(ExecutionStrategy):
    """Passive limit order at mid-price, fallback to MOC if unfilled.

    Places limit at bid (for buys) or ask (for sells) to capture spread.
    If not filled within max_wait_seconds, falls back to MOC.
    """

    def __init__(self, spread_capture_pct: float = 0.5,
                 max_wait_seconds: int = 600, moc_fallback: bool = True):
        super().__init__()
        self.name = 'PASSIVE'
        self.spread_capture_pct = spread_capture_pct
        self.max_wait_seconds = max_wait_seconds
        self.moc_fallback = moc_fallback

    def execute(self, broker, order, market_data):
        arrival_price = market_data.get('price', 0)
        spread_est = market_data.get('spread_est', 0.001)  # estimated spread

        # Set limit price: capture portion of spread
        offset = spread_est * self.spread_capture_pct
        if order.action == 'BUY':
            limit_price = arrival_price * (1 - offset)
        else:
            limit_price = arrival_price * (1 + offset)

        limit_order = Order(
            symbol=order.symbol,
            action=order.action,
            quantity=order.quantity,
            order_type='LIMIT',
            limit_price=limit_price,
        )

        result = broker.submit_order(limit_order)

        # If not filled and fallback enabled, send MOC
        if result.status != 'FILLED' and self.moc_fallback:
            moc_order = Order(
                symbol=order.symbol,
                action=order.action,
                quantity=order.quantity,
                order_type='MARKET',
            )
            result = broker.submit_order(moc_order)

        self._record_fill(result, arrival_price)
        return result


class SmartOrderRouter:
    """Selects execution strategy based on order size relative to ADV.

    Rules:
        <0.1% ADV → PassiveLimitStrategy (maximize spread capture)
        <1.0% ADV → TWAPStrategy (time-average to reduce timing risk)
        >=1.0% ADV → VWAPStrategy (volume-weighted for deeper liquidity)
    """

    def __init__(self, default_strategy: str = 'MOC'):
        self.default_strategy = default_strategy
        self._strategy_cache = {}

    def select_strategy(self, order: Order, market_data: dict) -> ExecutionStrategy:
        """Select optimal execution strategy based on order characteristics."""
        adv = market_data.get('adv', 1e9)
        price = market_data.get('price', 100)
        order_value = order.quantity * price

        if adv <= 0:
            return MOCStrategy()

        participation_rate = order_value / adv

        if participation_rate < 0.001:  # <0.1% ADV
            return PassiveLimitStrategy()
        elif participation_rate < 0.01:  # <1% ADV
            return TWAPStrategy()
        else:  # >=1% ADV
            return VWAPStrategy()


class PaperBroker(Broker):
    """Broker de papel para testing sin riesgo real"""

    def __init__(self, initial_cash: float = 100000,
                 commission_per_share: float = 0.001,
                 fill_delay: int = 1,
                 max_fill_deviation: float = MAX_FILL_DEVIATION):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.commission_per_share = commission_per_share
        self.fill_delay = fill_delay  # segundos para simular delay de ejecucion
        self.max_fill_deviation = max_fill_deviation

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

    def validate_fill_price(self, symbol: str, fill_price: float,
                            reference_price: float,
                            max_deviation: float = None) -> bool:
        """Verify fill price is within acceptable range of reference.
        Circuit breaker: rejects fills that deviate too much from expected price."""
        if max_deviation is None:
            max_deviation = self.max_fill_deviation
        if reference_price <= 0:
            return False
        deviation = abs(fill_price - reference_price) / reference_price
        if deviation > max_deviation:
            logger.error(f"Fill price circuit breaker: {symbol} "
                        f"fill=${fill_price:.2f} vs ref=${reference_price:.2f} "
                        f"({deviation:.2%} deviation > {max_deviation:.1%} max)")
            return False
        return True

    def check_stale_orders(self, max_age: int = 300) -> List[Order]:
        """Cancel and return orders that exceeded max age (stale orders)"""
        stale = []
        for oid, order in list(self.orders.items()):
            if order.is_stale(max_age):
                order.status = 'CANCELLED'
                stale.append(order)
                logger.warning(f"Stale order cancelled: {oid} "
                             f"({order.symbol} {order.action} {order.quantity:.1f})")
        return stale

    def submit_order(self, order: Order) -> Order:
        """Envia orden y la ejecuta inmediatamente (paper)"""
        if not self._connected:
            raise ConnectionError("Broker no conectado")

        self._order_counter += 1
        order.order_id = f"PAPER_{self._order_counter}"
        order.status = 'SUBMITTED'
        order.submitted_at = datetime.now()

        # Obtener precio de ejecucion
        fill_price = self._get_fill_price(order.symbol, order.action)

        if not fill_price:
            order.status = 'ERROR'
            logger.error(f"No se pudo obtener precio para {order.symbol}")
            return order

        # Circuit breaker: validate fill price vs reference
        reference_price = self.price_feed.get_price(order.symbol) if self.price_feed else None
        if reference_price and not self.validate_fill_price(
                order.symbol, fill_price, reference_price):
            order.status = 'ERROR'
            logger.error(f"Fill rejected by circuit breaker: {order.symbol}")
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
    
    def submit_order(self, order: Order, max_retries: int = 2,
                     retry_wait: float = 5.0) -> Order:
        """Envia orden a IBKR con retry logic y fill validation"""
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
        order.submitted_at = datetime.now()

        # Retry loop: wait for fill with retries
        for attempt in range(max_retries + 1):
            self.ib.sleep(retry_wait)

            if trade.orderStatus.status == 'Filled':
                order.status = 'FILLED'
                order.filled_quantity = trade.orderStatus.filled
                order.filled_price = trade.orderStatus.avgFillPrice
                order.commission = sum(c.commission for c in trade.commissions)

                # Circuit breaker: validate fill price
                ticker = self.ib.reqMktData(contract)
                self.ib.sleep(1)
                ref_price = ticker.last or ticker.close
                if ref_price and ref_price > 0:
                    deviation = abs(order.filled_price - ref_price) / ref_price
                    if deviation > MAX_FILL_DEVIATION:
                        logger.error(f"IBKR fill price circuit breaker: {order.symbol} "
                                    f"fill=${order.filled_price:.2f} vs ref=${ref_price:.2f} "
                                    f"({deviation:.2%} deviation)")
                        # Order already filled -- log warning but don't reject
                        # In production this would trigger immediate exit

                logger.info(f"IBKR order filled (attempt {attempt+1}): "
                           f"{order.action} {order.quantity} {order.symbol} "
                           f"@ ${order.filled_price:.2f}")
                break
            elif attempt < max_retries:
                logger.info(f"IBKR order not filled yet, retry {attempt+1}/{max_retries}...")
        else:
            # Not filled after all retries
            if trade.orderStatus.status != 'Filled':
                logger.warning(f"IBKR order not filled after {max_retries+1} attempts, "
                             f"cancelling: {order.symbol}")
                self.ib.cancelOrder(trade.order)
                order.status = 'CANCELLED'

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
