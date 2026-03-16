"""
OmniCapital v8.2 - Broker Integration Module
Integracion con brokers para ejecucion de ordenes.
Incluye order timeout, fill circuit breaker y retry logic.
"""

from abc import ABC, abstractmethod
import asyncio
from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo
import json
import logging
import os
import threading
import time as time_module

# Fill price circuit breaker: max deviation from reference price
MAX_FILL_DEVIATION = 0.02  # 2%

logger = logging.getLogger(__name__)


@dataclass
class Order:
    """Representa una orden de trading"""
    symbol: str
    action: str  # 'BUY' o 'SELL'
    quantity: float
    order_type: str = 'MARKET'  # 'MARKET', 'LIMIT', 'MOC'
    limit_price: Optional[float] = None
    order_id: Optional[str] = None
    status: str = 'PENDING'  # 'PENDING', 'SUBMITTED', 'PARTIAL_FILL', 'FILLED', 'CANCELLED', 'ERROR'
    filled_quantity: float = 0
    filled_price: Optional[float] = None
    commission: float = 0
    timestamp: datetime = None
    submitted_at: Optional[datetime] = None  # When order was submitted to broker
    decision_price: Optional[float] = None   # Price when signal was generated (for IS tracking)
    is_bps: Optional[float] = None           # Implementation Shortfall in basis points

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


# ======================================================================
# IBKR Commission Model & Connection Management
# ======================================================================

class IBKRCommissionModel:
    """IBKR US Tiered commission model for equities.

    Tiered pricing (default for accounts under $100K):
    - $0.0035/share, min $0.35/order, max 1% of trade value
    - Plus exchange/regulatory fees (~$0.0003/share)
    """

    COST_PER_SHARE = 0.0035
    EXCHANGE_FEES_PER_SHARE = 0.0003
    MIN_PER_ORDER = 0.35
    MAX_PCT_OF_TRADE = 0.01  # 1% of trade value

    @classmethod
    def calculate(cls, shares: float, price: float) -> float:
        base = shares * cls.COST_PER_SHARE
        exchange = shares * cls.EXCHANGE_FEES_PER_SHARE
        total = base + exchange
        total = max(total, cls.MIN_PER_ORDER)
        total = min(total, shares * price * cls.MAX_PCT_OF_TRADE)
        return round(total, 4)


class ConnectionState(Enum):
    DISCONNECTED = 'DISCONNECTED'
    CONNECTING = 'CONNECTING'
    CONNECTED = 'CONNECTED'
    RECONNECTING = 'RECONNECTING'
    DEGRADED = 'DEGRADED'
    FAILED = 'FAILED'


class ConnectionManager:
    """Manages IBKR connection lifecycle: heartbeat, reconnection, state tracking.

    In mock mode, simulates connection behavior.
    In live mode, wraps ib_async connection with monitoring.
    """

    def __init__(self, host: str, port: int, client_id: int,
                 mock: bool = True,
                 reconnect_interval: float = 30.0,
                 max_reconnect_attempts: int = 10):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.mock = mock
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempts = max_reconnect_attempts

        self.state = ConnectionState.DISCONNECTED
        self.ib = None  # ib_async.IB instance (None in mock)
        self._reconnect_count = 0
        self._reconnect_thread = None
        self._stop_reconnect = threading.Event()

    def connect(self) -> bool:
        """Connect to TWS/Gateway. In mock mode, always succeeds."""
        self.state = ConnectionState.CONNECTING

        if self.mock:
            self.state = ConnectionState.CONNECTED
            logger.info("IBKR ConnectionManager: MOCK mode connected")
            return True

        try:
            from ib_async import IB
            self.ib = IB()
            self.ib.connect(self.host, self.port, clientId=self.client_id,
                            timeout=15)
            self.state = ConnectionState.CONNECTED
            self._reconnect_count = 0
            logger.info(f"IBKR ConnectionManager: connected to {self.host}:{self.port}")

            # Set disconnect callback for auto-reconnect
            self.ib.disconnectedEvent += self._on_disconnect
            return True
        except Exception as e:
            self.state = ConnectionState.FAILED
            logger.error(f"IBKR ConnectionManager: connection failed: {e}")
            return False

    def disconnect(self):
        """Clean disconnect."""
        self._stop_reconnect.set()
        if self._reconnect_thread and self._reconnect_thread.is_alive():
            self._reconnect_thread.join(timeout=5)

        if self.ib and not self.mock:
            try:
                self.ib.disconnect()
            except Exception:
                pass
        self.ib = None
        self.state = ConnectionState.DISCONNECTED
        logger.info("IBKR ConnectionManager: disconnected")

    def is_connected(self) -> bool:
        """Check connection status."""
        if self.mock:
            return self.state == ConnectionState.CONNECTED
        if self.ib is None:
            return False
        return self.ib.isConnected()

    def verify_paper_trading(self) -> bool:
        """Safety guard: verify we're connected to paper trading.
        Port 7497 = paper trading, port 7496 = live trading.
        In mock mode, rejects port 7496."""
        if self.port == 7496:
            logger.error("SAFETY: Port 7496 is LIVE trading. "
                         "Use port 7497 for paper trading.")
            return False
        return True

    def _on_disconnect(self):
        """Callback when ib_async loses connection. Starts reconnect loop."""
        if self.state == ConnectionState.DISCONNECTED:
            return  # Clean disconnect, don't reconnect
        logger.warning("IBKR connection lost — starting reconnect loop")
        self.state = ConnectionState.RECONNECTING
        self._stop_reconnect.clear()
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop, daemon=True)
        self._reconnect_thread.start()

    def _reconnect_loop(self):
        """Background thread: attempt reconnection periodically."""
        import time as _time
        while (self._reconnect_count < self.max_reconnect_attempts
               and not self._stop_reconnect.is_set()):
            self._reconnect_count += 1
            logger.info(f"IBKR reconnect attempt {self._reconnect_count}"
                        f"/{self.max_reconnect_attempts}...")
            try:
                from ib_async import IB
                self.ib = IB()
                self.ib.connect(self.host, self.port,
                                clientId=self.client_id, timeout=15)
                self.state = ConnectionState.CONNECTED
                self._reconnect_count = 0
                self.ib.disconnectedEvent += self._on_disconnect
                logger.info("IBKR reconnected successfully")
                return
            except Exception as e:
                logger.warning(f"Reconnect failed: {e}")
                self._stop_reconnect.wait(timeout=self.reconnect_interval)

        if self._reconnect_count >= self.max_reconnect_attempts:
            self.state = ConnectionState.FAILED
            logger.error(f"IBKR reconnect FAILED after "
                         f"{self.max_reconnect_attempts} attempts")


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
        """Get fill price using the current market price (no random slippage).

        Pre-close entries (15:30-15:50 ET) conceptually execute at close.
        Using the feed price directly (without random noise) ensures the
        portfolio tracks real closes and avoids cumulative drift vs benchmarks.
        """
        if self.price_feed:
            price = self.price_feed.get_price(symbol)
            if price:
                return price
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
            buying_power=self.cash  # Production stays cash-only: LEVERAGE_MAX = 1.0
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
    """Interactive Brokers integration with mock mode.

    Mock mode (mock=True):
        Simulates realistic IBKR behavior without TWS.
        - IBKR tiered commissions
        - MOC order support with deadline enforcement
        - Realistic slippage (~0.5bps for S&P 500 large-caps)
        - Connection state management
        - Position reconciliation

    Live mode (mock=False):
        Requires TWS/Gateway running. Uses ib_async.
        Same interface, same safety guards.

    Safety guards (both modes):
        - Paper trading account verification (port 7497 only)
        - MOC deadline enforcement (reject after 15:50 ET)
        - Maximum order size limits
        - Kill switch integration (STOP_TRADING file)
        - NO fallback to PaperBroker on disconnect
    """

    def __init__(self, host: str = '127.0.0.1', port: int = 7497,
                 client_id: int = 1, mock: bool = True,
                 max_order_value: float = 50_000,
                 price_feed=None):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.mock = mock
        self.max_order_value = max_order_value
        self.price_feed = price_feed

        # Connection management
        self.connection = ConnectionManager(
            host=host, port=port, client_id=client_id, mock=mock
        )

        # Order tracking
        self.orders: Dict[str, Order] = {}
        self.order_history: List[Order] = []
        self._order_counter = 0
        self._pending_orders: Dict[str, Order] = {}

        # Position tracking (mock mode)
        self._mock_positions: Dict[str, Position] = {}
        self._mock_cash: float = 0

        # Commission model
        self.commission_model = IBKRCommissionModel

        # Timezone for MOC deadline
        self._et_tz = ZoneInfo('America/New_York')

        # Audit log
        self._audit_log: List[dict] = []
        self._broker_state = 'disconnected'
        self._last_successful_call_at = None
        self._last_latency_seconds = None
        self._last_error = None
        self._last_positions_snapshot: Optional[Dict[str, Position]] = None
        self._last_portfolio_snapshot = None
        self._recovery_attempts = 3
        self._recovery_backoff_seconds = 1.0
        self._recovery_backoff_cap = 30.0
        self._recoverable_errors = (
            ConnectionError,
            TimeoutError,
            asyncio.TimeoutError,
        )

    # ---- COMPASSLive compatibility properties ----
    # COMPASSLive accesses self.broker.cash and self.broker.positions directly

    @property
    def cash(self):
        if self.mock:
            return self._mock_cash
        portfolio = self.get_portfolio()
        return portfolio.cash

    @cash.setter
    def cash(self, value):
        if self.mock:
            self._mock_cash = value

    @property
    def positions(self):
        if self.mock:
            return self._mock_positions
        return self.get_positions()

    @positions.setter
    def positions(self, value):
        if self.mock:
            self._mock_positions = value

    def _set_broker_state(self, new_state: str, reason: str = None):
        new_state = (new_state or 'disconnected').lower()
        old_state = self._broker_state
        self._broker_state = new_state
        if self.mock:
            mapped_state = {
                'connected': ConnectionState.CONNECTED,
                'reconnecting': ConnectionState.RECONNECTING,
                'degraded': ConnectionState.DEGRADED,
                'disconnected': ConnectionState.DISCONNECTED,
            }.get(new_state)
            if mapped_state is not None:
                self.connection.state = mapped_state
        if old_state != new_state:
            extra = f" ({reason})" if reason else ""
            logger.info(
                f"IBKR broker state transition: {old_state.upper()} -> {new_state.upper()}{extra}"
            )

    def _sleep_backoff(self, seconds: float):
        time_module.sleep(seconds)

    def _mark_call_success(self, latency_seconds: float):
        self._last_latency_seconds = latency_seconds
        self._last_successful_call_at = datetime.now()
        self._last_error = None
        if not self.mock and self._broker_state != 'connected':
            self._set_broker_state('connected', 'live call succeeded')

    def _require_live_ib(self):
        ib = self.connection.ib
        if ib is None or not self.connection.is_connected():
            raise ConnectionError("IBKR connection unavailable")
        return ib

    def _cache_positions_snapshot(self, positions: Dict[str, Position]) -> Dict[str, Position]:
        snapshot = {
            symbol: Position(
                symbol=pos.symbol,
                shares=pos.shares,
                avg_cost=pos.avg_cost,
                market_price=pos.market_price,
                market_value=pos.market_value,
                unrealized_pnl=pos.unrealized_pnl,
                realized_pnl=pos.realized_pnl,
                entry_time=pos.entry_time,
                high_price=pos.high_price,
            )
            for symbol, pos in positions.items()
        }
        self._last_positions_snapshot = snapshot
        return {
            symbol: Position(
                symbol=pos.symbol,
                shares=pos.shares,
                avg_cost=pos.avg_cost,
                market_price=pos.market_price,
                market_value=pos.market_value,
                unrealized_pnl=pos.unrealized_pnl,
                realized_pnl=pos.realized_pnl,
                entry_time=pos.entry_time,
                high_price=pos.high_price,
            )
            for symbol, pos in snapshot.items()
        }

    def _get_cached_positions(self) -> Optional[Dict[str, Position]]:
        if self._last_positions_snapshot is None:
            return None
        return {
            symbol: Position(
                symbol=pos.symbol,
                shares=pos.shares,
                avg_cost=pos.avg_cost,
                market_price=pos.market_price,
                market_value=pos.market_value,
                unrealized_pnl=pos.unrealized_pnl,
                realized_pnl=pos.realized_pnl,
                entry_time=pos.entry_time,
                high_price=pos.high_price,
            )
            for symbol, pos in self._last_positions_snapshot.items()
        }

    def _cache_portfolio_snapshot(self, portfolio: Portfolio) -> Portfolio:
        cached_positions = self._cache_positions_snapshot(portfolio.positions)
        self._last_portfolio_snapshot = Portfolio(
            cash=portfolio.cash,
            positions=cached_positions,
            total_value=portfolio.total_value,
            buying_power=portfolio.buying_power,
        )
        return Portfolio(
            cash=self._last_portfolio_snapshot.cash,
            positions=self._get_cached_positions(),
            total_value=self._last_portfolio_snapshot.total_value,
            buying_power=self._last_portfolio_snapshot.buying_power,
        )

    def _get_cached_portfolio(self):
        if self._last_portfolio_snapshot is None:
            return None
        return Portfolio(
            cash=self._last_portfolio_snapshot.cash,
            positions=self._get_cached_positions(),
            total_value=self._last_portfolio_snapshot.total_value,
            buying_power=self._last_portfolio_snapshot.buying_power,
        )

    def _recover_connection(self, operation: str, error: Exception) -> bool:
        self._last_error = str(error)
        for attempt in range(1, self._recovery_attempts + 1):
            delay = min(
                self._recovery_backoff_seconds * (2 ** (attempt - 1)),
                self._recovery_backoff_cap,
            )
            self._set_broker_state(
                'reconnecting',
                f"{operation} failed ({type(error).__name__}); retry {attempt}/{self._recovery_attempts}",
            )
            logger.warning(
                f"IBKR recoverable error during {operation}: {error}. "
                f"Reconnect attempt {attempt}/{self._recovery_attempts} in {delay:.1f}s"
            )
            self._sleep_backoff(delay)
            try:
                self.connection.disconnect()
            except Exception as disconnect_err:
                logger.debug(f"IBKR reconnect pre-disconnect failed: {disconnect_err}")
            try:
                if self.connection.connect():
                    self._set_broker_state('connected', f"{operation} recovered on attempt {attempt}")
                    return True
            except Exception as reconnect_err:
                self._last_error = str(reconnect_err)
                logger.warning(f"IBKR reconnect attempt {attempt} failed: {reconnect_err}")
        self._set_broker_state('degraded', f"{operation} unavailable after recovery attempts")
        logger.error(f"IBKR entering DEGRADED mode after {operation} recovery failed")
        return False

    def _call_with_recovery(self, operation: str, func,
                            read_only: bool = False,
                            allow_cached: bool = False,
                            cache_getter=None):
        if self.mock:
            start = time_module.perf_counter()
            result = func()
            self._mark_call_success(time_module.perf_counter() - start)
            return result

        if self._broker_state == 'degraded' and not read_only:
            raise RuntimeError("IBKR broker is in degraded mode (read-only)")

        last_error = None
        for attempt in range(self._recovery_attempts + 1):
            start = time_module.perf_counter()
            try:
                result = func()
                self._mark_call_success(time_module.perf_counter() - start)
                return result
            except self._recoverable_errors as err:
                last_error = err
                self._last_error = str(err)
                if attempt >= self._recovery_attempts:
                    break
                if not self._recover_connection(operation, err):
                    break

        if allow_cached and cache_getter is not None:
            cached = cache_getter()
            if cached is not None:
                logger.warning(f"IBKR returning cached result for {operation} while degraded")
                return cached

        if last_error is not None:
            raise last_error
        raise RuntimeError(f"IBKR {operation} failed without a recoverable error")

    def _live_fetch_positions(self) -> Dict[str, Position]:
        ib = self._require_live_ib()
        positions = {}
        for pos in ib.positions():
            positions[pos.contract.symbol] = Position(
                symbol=pos.contract.symbol,
                shares=pos.position,
                avg_cost=pos.avgCost
            )
        return positions

    def _live_fetch_portfolio(self) -> Portfolio:
        ib = self._require_live_ib()
        account = ib.accountSummary()
        cash = 0
        buying_power = 0
        for item in account:
            if item.tag == 'AvailableFunds':
                cash = float(item.value)
            elif item.tag == 'BuyingPower':
                buying_power = float(item.value)

        positions = self._live_fetch_positions()
        total = cash + sum(
            p.shares * (p.market_price or p.avg_cost)
            for p in positions.values()
        )
        return Portfolio(
            cash=cash,
            positions=positions,
            total_value=total,
            buying_power=buying_power,
        )

    # ---- Connection Methods ----

    def connect(self) -> bool:
        """Connect to IBKR. Verifies paper trading account."""
        if not self.connection.verify_paper_trading():
            logger.error("IBKR connect aborted: paper trading verification failed")
            self._set_broker_state('disconnected', 'paper trading verification failed')
            return False

        result = self.connection.connect()
        if result:
            mode = 'MOCK' if self.mock else 'LIVE (PAPER TRADING)'
            self._set_broker_state('connected', 'connect succeeded')
            logger.info(f"IBKR broker connected: {mode} | "
                        f"Port {self.port} | Max order ${self.max_order_value:,.0f}")
        else:
            self._set_broker_state('disconnected', 'connect failed')
        return result

    def disconnect(self):
        """Disconnect from IBKR."""
        self.connection.disconnect()
        self._set_broker_state('disconnected', 'disconnect requested')

    def is_connected(self) -> bool:
        return self.connection.is_connected()

    def set_price_feed(self, feed):
        """Set price feed for fill simulation (mock) and validation (live)."""
        self.price_feed = feed

    # ---- Safety Guards ----

    def _check_kill_switch(self) -> bool:
        """Returns True if STOP_TRADING file exists."""
        return os.path.exists('STOP_TRADING')

    def _check_moc_deadline(self) -> bool:
        """Returns True if PAST the MOC deadline (15:50 ET)."""
        now_et = datetime.now(self._et_tz)
        if now_et.weekday() >= 5:
            return True  # Weekend
        return now_et.time() > time(15, 50)

    def _validate_order_size(self, order: Order, price: float) -> bool:
        """Validate order value doesn't exceed max_order_value."""
        order_value = order.quantity * price
        if order_value > self.max_order_value:
            logger.error(f"Order size guard: {order.symbol} "
                         f"${order_value:,.0f} > ${self.max_order_value:,.0f} limit")
            return False
        return True

    def _get_reference_price(self, symbol: str) -> Optional[float]:
        """Get reference price from price feed."""
        if self.price_feed:
            return self.price_feed.get_price(symbol)
        return None

    # ---- Order Submission ----

    def submit_order(self, order: Order) -> Order:
        """Submit order to IBKR (mock or live).

        Flow:
        1. Safety checks (connection, kill switch, MOC deadline, order size)
        2. Assign order ID, set status to SUBMITTED
        3. Route to _submit_mock() or _submit_live()
        4. Log to audit trail
        """
        # Pre-submission guards
        if not self.mock and self._broker_state == 'degraded':
            order.status = 'ERROR'
            self._audit('submit_rejected', order, reason='degraded_mode')
            raise RuntimeError("IBKR broker is in degraded mode (read-only)")

        if self.mock and not self.is_connected():
            order.status = 'ERROR'
            self._audit('submit_rejected', order, reason='not_connected')
            raise ConnectionError("IBKR not connected")

        if self._check_kill_switch():
            order.status = 'ERROR'
            self._audit('submit_rejected', order, reason='kill_switch')
            raise RuntimeError("Kill switch active (STOP_TRADING file detected)")

        if order.order_type == 'MOC' and self._check_moc_deadline():
            order.status = 'ERROR'
            self._audit('submit_rejected', order, reason='moc_deadline_passed')
            logger.error(f"MOC deadline passed for {order.symbol}")
            return order

        # Get reference price for validation
        ref_price = self._get_reference_price(order.symbol)
        if ref_price and not self._validate_order_size(order, ref_price):
            order.status = 'ERROR'
            self._audit('submit_rejected', order, reason='order_size_exceeded')
            return order

        # Assign order ID
        self._order_counter += 1
        tag = 'MOCK' if self.mock else 'LIVE'
        order.order_id = f"IBKR_{tag}_{self._order_counter}"
        order.status = 'SUBMITTED'
        order.submitted_at = datetime.now()

        # Route to implementation
        if self.mock:
            result = self._submit_mock(order)
        else:
            result = self._submit_live(order)

        # Store and audit
        self.orders[result.order_id] = result
        self.order_history.append(result)
        self._audit('order_completed', result)

        return result

    def _submit_mock(self, order: Order) -> Order:
        """Mock IBKR execution with realistic behavior.

        - IBKR tiered commission model
        - ~0.5bps slippage for MOC orders (S&P 500 large-caps)
        - Fill price circuit breaker validation
        """
        fill_price = self._get_mock_fill_price(order)
        if fill_price is None:
            order.status = 'ERROR'
            logger.error(f"IBKR Mock: no price available for {order.symbol}")
            return order

        # Circuit breaker: validate fill price vs reference
        ref_price = self._get_reference_price(order.symbol)
        if ref_price and ref_price > 0:
            deviation = abs(fill_price - ref_price) / ref_price
            if deviation > MAX_FILL_DEVIATION:
                order.status = 'ERROR'
                logger.error(f"Fill circuit breaker: {order.symbol} "
                             f"fill=${fill_price:.2f} vs ref=${ref_price:.2f} "
                             f"({deviation:.2%} deviation)")
                return order

        # Calculate commission (IBKR tiered model)
        commission = self.commission_model.calculate(order.quantity, fill_price)

        # Execute against mock positions
        if order.action == 'BUY':
            total_cost = order.quantity * fill_price + commission
            if total_cost > self._mock_cash:
                order.status = 'ERROR'
                logger.error(f"Insufficient funds: ${self._mock_cash:,.2f} < "
                             f"${total_cost:,.2f}")
                return order

            if order.symbol in self._mock_positions:
                pos = self._mock_positions[order.symbol]
                total_shares = pos.shares + order.quantity
                total_cost_basis = (pos.shares * pos.avg_cost +
                                    order.quantity * fill_price)
                pos.shares = total_shares
                pos.avg_cost = total_cost_basis / total_shares
            else:
                self._mock_positions[order.symbol] = Position(
                    symbol=order.symbol,
                    shares=order.quantity,
                    avg_cost=fill_price
                )
            self._mock_cash -= total_cost

        elif order.action == 'SELL':
            if order.symbol not in self._mock_positions:
                order.status = 'ERROR'
                logger.error(f"No position in {order.symbol} to sell")
                return order
            pos = self._mock_positions[order.symbol]
            if order.quantity > pos.shares:
                order.status = 'ERROR'
                logger.error(f"Insufficient shares: {pos.shares:.2f} < "
                             f"{order.quantity:.2f}")
                return order
            realized_pnl = (fill_price - pos.avg_cost) * order.quantity
            pos.realized_pnl += realized_pnl
            pos.shares -= order.quantity
            if pos.shares <= 0:
                del self._mock_positions[order.symbol]
            self._mock_cash += order.quantity * fill_price - commission

        # Fill the order
        order.status = 'FILLED'
        order.filled_quantity = order.quantity
        order.filled_price = fill_price
        order.commission = commission

        logger.info(f"IBKR Mock fill: {order.action} {order.quantity:.1f} "
                    f"{order.symbol} @ ${fill_price:.2f} | "
                    f"Commission: ${commission:.4f}")
        return order

    def _submit_live(self, order: Order) -> Order:
        return self._call_with_recovery(
            'submit_order',
            lambda: self._submit_live_once(order),
            read_only=False,
        )

    def _submit_live_once(self, order: Order) -> Order:
        """Submit to real IBKR via ib_async.

        Supports MARKET, LIMIT, and MOC order types.
        Non-blocking: uses ib.sleep() instead of time.sleep().
        """
        from ib_async import Stock, MarketOrder, LimitOrder
        from ib_async import Order as IBOrder

        ib = self._require_live_ib()
        contract = Stock(order.symbol, 'SMART', 'USD')

        if order.order_type == 'MARKET':
            ib_order = MarketOrder(order.action, order.quantity)
        elif order.order_type == 'LIMIT':
            ib_order = LimitOrder(order.action, order.quantity,
                                  order.limit_price)
        elif order.order_type == 'MOC':
            ib_order = IBOrder()
            ib_order.action = order.action
            ib_order.totalQuantity = order.quantity
            ib_order.orderType = 'MOC'
        else:
            raise ValueError(f"Unsupported order type: {order.order_type}")

        trade = ib.placeOrder(contract, ib_order)

        # Wait for fill — MOC orders won't fill until close
        max_wait = 5 if order.order_type == 'MOC' else 30
        elapsed = 0

        while elapsed < max_wait:
            ib.sleep(1.0)
            elapsed += 1

            status = trade.orderStatus.status
            if status == 'Filled':
                order.status = 'FILLED'
                order.filled_quantity = trade.orderStatus.filled
                order.filled_price = trade.orderStatus.avgFillPrice
                commissions = trade.commissions or []
                order.commission = sum(
                    c.commission for c in commissions
                    if c.commission is not None
                )
                logger.info(f"IBKR LIVE fill: {order.action} "
                            f"{order.filled_quantity} {order.symbol} "
                            f"@ ${order.filled_price:.2f}")
                break
            elif status in ('Cancelled', 'ApiCancelled'):
                order.status = 'CANCELLED'
                logger.warning(f"IBKR order cancelled: {order.symbol}")
                break
            elif status == 'Inactive':
                order.status = 'ERROR'
                logger.error(f"IBKR order inactive: {order.symbol}")
                break

        # MOC submitted but not yet filled (expected: fills at close)
        if order.order_type == 'MOC' and order.status == 'SUBMITTED':
            logger.info(f"MOC order submitted for {order.symbol}, "
                        f"will fill at close")
            self._pending_orders[order.order_id] = order

        # Non-MOC still not filled: cancel
        if order.status == 'SUBMITTED' and order.order_type != 'MOC':
            logger.warning(f"Order not filled after {max_wait}s, "
                           f"cancelling: {order.symbol}")
            ib.cancelOrder(trade.order)
            order.status = 'CANCELLED'

        return order

    def _get_mock_fill_price(self, order: Order) -> Optional[float]:
        """Generate realistic mock fill price.

        For S&P 500 large-caps with MOC orders:
        - MOC: ~0.5bps slippage (fills at close)
        - MARKET: ~1bps adverse slippage
        - LIMIT: fills at limit if marketable
        """
        import random

        ref_price = self._get_reference_price(order.symbol)
        if ref_price is None:
            return None

        if order.order_type == 'MOC':
            slippage_bps = random.gauss(0, 0.5) / 10000
            return ref_price * (1 + slippage_bps)

        elif order.order_type == 'MARKET':
            if order.action == 'BUY':
                slippage_bps = abs(random.gauss(1.0, 0.5)) / 10000
            else:
                slippage_bps = -abs(random.gauss(1.0, 0.5)) / 10000
            return ref_price * (1 + slippage_bps)

        elif order.order_type == 'LIMIT':
            if order.limit_price:
                if order.action == 'BUY' and order.limit_price >= ref_price:
                    return order.limit_price
                elif order.action == 'SELL' and order.limit_price <= ref_price:
                    return order.limit_price
            return None  # Limit not hit

        return ref_price

    # ---- Order Management ----

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a pending order."""
        if self.mock:
            if order_id in self._pending_orders:
                self._pending_orders[order_id].status = 'CANCELLED'
                del self._pending_orders[order_id]
                self._audit('order_cancelled', self.orders.get(order_id))
                return True
            return False
        else:
            def cancel_live():
                ib = self._require_live_ib()
                for trade in ib.trades():
                    if str(trade.order.orderId) == order_id:
                        ib.cancelOrder(trade.order)
                        self._audit('order_cancelled',
                                    self.orders.get(order_id))
                        return True
                return False

            return self._call_with_recovery(
                'cancel_order',
                cancel_live,
                read_only=False,
            )

    def get_order_status(self, order_id: str) -> Optional[Order]:
        """Get order status."""
        return self.orders.get(order_id)

    def check_stale_orders(self, max_age: int = 300) -> List[Order]:
        """Cancel orders exceeding max age."""
        stale = []
        for oid, order in list(self._pending_orders.items()):
            if order.is_stale(max_age):
                order.status = 'CANCELLED'
                stale.append(order)
                del self._pending_orders[oid]
                self._audit('stale_order_cancelled', order)
                logger.warning(f"Stale order cancelled: {oid} "
                               f"({order.symbol})")
        return stale

    # ---- Position & Portfolio ----

    def get_positions(self) -> Dict[str, Position]:
        """Get current positions."""
        if self.mock:
            if self.price_feed:
                for symbol, pos in self._mock_positions.items():
                    price = self.price_feed.get_price(symbol)
                    if price:
                        pos.update_market_data(price)
            return self._mock_positions.copy()
        else:
            positions = self._call_with_recovery(
                'get_positions',
                self._live_fetch_positions,
                read_only=True,
                allow_cached=True,
                cache_getter=self._get_cached_positions,
            )
            return self._cache_positions_snapshot(positions)

    def get_portfolio(self) -> Portfolio:
        """Get portfolio state."""
        if self.mock:
            positions = self.get_positions()
            positions_value = sum(
                p.market_value or 0 for p in positions.values())
            total_value = self._mock_cash + positions_value
            return Portfolio(
                cash=self._mock_cash,
                positions=positions,
                total_value=total_value,
                buying_power=self._mock_cash  # No margin (LEVERAGE_MAX=1.0)
            )
        else:
            portfolio = self._call_with_recovery(
                'get_portfolio',
                self._live_fetch_portfolio,
                read_only=True,
                allow_cached=True,
                cache_getter=self._get_cached_portfolio,
            )
            return self._cache_portfolio_snapshot(portfolio)

    def get_account_info(self) -> Dict:
        """Get account information."""
        portfolio = self.get_portfolio()
        return {
            'cash': portfolio.cash,
            'total_value': portfolio.total_value,
            'buying_power': portfolio.buying_power,
            'num_positions': len(portfolio.positions),
            'broker_type': 'IBKR',
            'mock_mode': self.mock,
            'connection_state': self._broker_state.upper(),
        }

    def health_check(self) -> Dict:
        latency_ms = None
        if self._last_latency_seconds is not None:
            latency_ms = round(self._last_latency_seconds * 1000, 2)
        return {
            'state': self._broker_state,
            'connected': self.is_connected(),
            'latency_ms': latency_ms,
            'last_successful_call_at': (
                self._last_successful_call_at.isoformat()
                if self._last_successful_call_at else None
            ),
            'last_error': self._last_error,
        }

    # ---- Position Reconciliation ----

    def reconcile_positions(self, json_state: Dict[str, dict]) -> Dict:
        """Compare JSON state positions vs broker positions.

        Returns a reconciliation report. Does NOT auto-correct.
        Called at startup by COMPASSLive.load_state().

        Args:
            json_state: {symbol: {shares, avg_cost}} from saved state

        Returns:
            {symbol: {json_shares, broker_shares, status, discrepancy}}
            status: 'match', 'json_only', 'broker_only', 'quantity_mismatch'
        """
        broker_positions = self.get_positions()
        report = {}

        all_symbols = set(json_state.keys()) | set(broker_positions.keys())

        for symbol in sorted(all_symbols):
            json_data = json_state.get(symbol)
            broker_pos = broker_positions.get(symbol)

            entry = {
                'json_shares': json_data['shares'] if json_data else 0,
                'json_avg_cost': json_data.get('avg_cost', 0) if json_data else 0,
                'broker_shares': broker_pos.shares if broker_pos else 0,
                'broker_avg_cost': broker_pos.avg_cost if broker_pos else 0,
            }

            if json_data and not broker_pos:
                entry['status'] = 'json_only'
                entry['discrepancy'] = "Position in state but not broker"
                logger.warning(f"RECONCILE: {symbol} in JSON state "
                               f"but NOT in broker")
            elif broker_pos and not json_data:
                entry['status'] = 'broker_only'
                entry['discrepancy'] = "Position in broker but not state"
                logger.warning(f"RECONCILE: {symbol} in broker "
                               f"but NOT in JSON state")
            elif abs(json_data['shares'] - broker_pos.shares) > 0.01:
                entry['status'] = 'quantity_mismatch'
                entry['discrepancy'] = (
                    f"JSON={json_data['shares']:.2f} vs "
                    f"Broker={broker_pos.shares:.2f}")
                logger.warning(f"RECONCILE: {symbol} quantity mismatch: "
                               f"{entry['discrepancy']}")
            else:
                entry['status'] = 'match'
                entry['discrepancy'] = None

            report[symbol] = entry

        mismatches = [s for s, r in report.items()
                      if r['status'] != 'match']
        if mismatches:
            logger.warning(f"RECONCILIATION: {len(mismatches)} discrepancies: "
                           f"{mismatches}")
            logger.warning("Manual review required. "
                           "Positions NOT auto-corrected.")
        else:
            logger.info("RECONCILIATION: All positions match.")

        return report

    # ---- Audit Trail ----

    def _audit(self, event_type: str, order: Order = None, **kwargs):
        """Record event to audit log."""
        entry = {
            'timestamp': datetime.now().isoformat(),
            'event': event_type,
            'mock': self.mock,
        }
        if order:
            entry.update({
                'order_id': order.order_id,
                'symbol': order.symbol,
                'action': order.action,
                'quantity': order.quantity,
                'order_type': order.order_type,
                'status': order.status,
                'filled_price': order.filled_price,
                'filled_quantity': order.filled_quantity,
                'commission': order.commission,
            })
        entry.update(kwargs)
        self._audit_log.append(entry)

    def get_audit_log(self) -> List[dict]:
        """Return full audit trail."""
        return self._audit_log.copy()

    def save_audit_log(self, filepath: str = None):
        """Save audit log to JSON file."""
        if not self._audit_log:
            return
        if filepath is None:
            os.makedirs('logs', exist_ok=True)
            filepath = (f"logs/ibkr_audit_"
                        f"{datetime.now().strftime('%Y%m%d')}.json")
        with open(filepath, 'w') as f:
            json.dump(self._audit_log, f, indent=2, default=str)
        logger.info(f"Audit log saved: {filepath} "
                    f"({len(self._audit_log)} entries)")


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
