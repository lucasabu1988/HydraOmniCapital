"""
OmniCapital v6 - Live Trading System (Complete)
Sistema completo de trading en tiempo real.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
import random
import logging
import json
import os
import sys
from typing import Dict, List, Optional, Set
import warnings
warnings.filterwarnings('ignore')

# Configuracion de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'omnicapital_live_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURACION DEL SISTEMA
# ============================================================================

CONFIG = {
    'HOLD_MINUTES': 1200,
    'NUM_POSITIONS': 5,
    'PORTFOLIO_STOP_LOSS': -0.20,
    'LEVERAGE': 2.0,
    'MIN_AGE_DAYS': 63,
    'RANDOM_SEED': 42,
    'COMMISSION_PER_SHARE': 0.001,
    'RECOVERY_THRESHOLD': 0.95,
    
    # Horario mercado (ET)
    'MARKET_OPEN': time(9, 30),
    'MARKET_CLOSE': time(16, 0),
    
    # Capital
    'INITIAL_CAPITAL': 100000,
    
    # Broker
    'BROKER_TYPE': 'PAPER',  # 'PAPER', 'IBKR', 'ALPACA'
    'PAPER_INITIAL_CASH': 100000,
    
    # Data feed
    'DATA_FEED': 'YAHOO',  # 'YAHOO', 'IBKR'
    'PRICE_UPDATE_INTERVAL': 60,  # segundos
    
    # Risk management
    'MAX_POSITION_SIZE_PCT': 0.25,
    'MIN_CASH_BUFFER': 0.05,
}

# Universo S&P 500 large-caps
UNIVERSE = [
    'AAPL', 'MSFT', 'AMZN', 'NVDA', 'GOOGL', 'META', 'TSLA', 'AVGO',
    'BRK-B', 'JPM', 'V', 'JNJ', 'WMT', 'MA', 'PG', 'UNH', 'HD', 'CVX',
    'MRK', 'PEP', 'KO', 'ABBV', 'BAC', 'COST', 'TMO', 'DIS',
    'ABT', 'WFC', 'ACN', 'VZ', 'DHR', 'ADBE', 'CRM', 'TXN', 'NKE',
    'NEE', 'AMD', 'PM', 'XOM', 'INTC', 'CSCO', 'IBM', 'GE', 'CAT',
    'BA', 'MMM', 'AXP', 'GS', 'MO', 'KMB', 'CL', 'MDT', 'SLB', 'UNP',
    'HON', 'FDX', 'UPS', 'LMT', 'RTX', 'OXY', 'AMGN', 'LLY', 'BMY', 'BIIB'
]


# ============================================================================
# DATA FEED
# ============================================================================

class YahooDataFeed:
    """Feed de datos usando Yahoo Finance"""
    
    def __init__(self, cache_duration: int = 60):
        self.cache_duration = cache_duration
        self._cache = {}
        self._cache_time = {}
        
    def get_price(self, symbol: str) -> Optional[float]:
        """Obtiene precio con cache"""
        import yfinance as yf
        
        now = datetime.now()
        
        # Verificar cache
        if symbol in self._cache:
            cache_age = (now - self._cache_time[symbol]).total_seconds()
            if cache_age < self.cache_duration:
                return self._cache[symbol]
        
        # Obtener nuevo dato
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info
            price = info.get('last_price', None)
            
            if price and price > 0:
                self._cache[symbol] = price
                self._cache_time[symbol] = now
                return price
        except Exception as e:
            logger.debug(f"Error obteniendo {symbol}: {e}")
        
        return self._cache.get(symbol, None)
    
    def get_prices(self, symbols: List[str]) -> Dict[str, float]:
        """Obtiene multiples precios"""
        prices = {}
        for symbol in symbols:
            price = self.get_price(symbol)
            if price:
                prices[symbol] = price
        return prices


# ============================================================================
# BROKER
# ============================================================================

from dataclasses import dataclass
from typing import Dict

@dataclass
class Position:
    symbol: str
    shares: float
    avg_cost: float
    entry_time: datetime
    market_price: Optional[float] = None
    market_value: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    
    def update_price(self, price: float):
        self.market_price = price
        self.market_value = self.shares * price
        self.unrealized_pnl = (price - self.avg_cost) * self.shares


class PaperBroker:
    """Broker de papel para testing"""
    
    def __init__(self, initial_cash: float = 100000, commission: float = 0.001):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.commission = commission
        self.positions: Dict[str, Position] = {}
        self.trade_history = []
        self._order_id = 0
        
    def connect(self):
        logger.info(f"Paper broker conectado. Cash: ${self.cash:,.2f}")
        return True
    
    def buy(self, symbol: str, shares: float, price: float) -> bool:
        """Ejecuta compra"""
        cost = shares * price
        commission = shares * self.commission
        total = cost + commission
        
        if total > self.cash:
            logger.warning(f"Fondos insuficientes para {symbol}: ${self.cash:.2f} < ${total:.2f}")
            return False
        
        # Actualizar posicion
        if symbol in self.positions:
            pos = self.positions[symbol]
            total_shares = pos.shares + shares
            total_cost = pos.shares * pos.avg_cost + shares * price
            pos.shares = total_shares
            pos.avg_cost = total_cost / total_shares
        else:
            self.positions[symbol] = Position(
                symbol=symbol,
                shares=shares,
                avg_cost=price,
                entry_time=datetime.now()
            )
        
        self.cash -= total
        self._order_id += 1
        
        logger.info(f"BUY {symbol}: {shares:.2f} @ ${price:.2f} | Cost: ${total:.2f}")
        
        self.trade_history.append({
            'id': self._order_id,
            'symbol': symbol,
            'action': 'BUY',
            'shares': shares,
            'price': price,
            'commission': commission,
            'time': datetime.now()
        })
        
        return True
    
    def sell(self, symbol: str, shares: float, price: float) -> bool:
        """Ejecuta venta"""
        if symbol not in self.positions:
            logger.warning(f"No hay posicion de {symbol}")
            return False
        
        pos = self.positions[symbol]
        if shares > pos.shares:
            logger.warning(f"Cantidad insuficiente: {pos.shares:.2f} < {shares:.2f}")
            return False
        
        proceeds = shares * price
        commission = shares * self.commission
        pnl = (price - pos.avg_cost) * shares
        
        # Actualizar posicion
        pos.shares -= shares
        if pos.shares <= 0:
            del self.positions[symbol]
        else:
            pos.update_price(price)
        
        self.cash += proceeds - commission
        self._order_id += 1
        
        logger.info(f"SELL {symbol}: {shares:.2f} @ ${price:.2f} | P&L: ${pnl:.2f}")
        
        self.trade_history.append({
            'id': self._order_id,
            'symbol': symbol,
            'action': 'SELL',
            'shares': shares,
            'price': price,
            'commission': commission,
            'pnl': pnl,
            'time': datetime.now()
        })
        
        return True
    
    def get_portfolio_value(self, prices: Dict[str, float]) -> float:
        """Calcula valor del portfolio"""
        value = self.cash
        for symbol, pos in self.positions.items():
            price = prices.get(symbol, pos.avg_cost)
            value += pos.shares * price
        return value
    
    def update_positions(self, prices: Dict[str, float]):
        """Actualiza precios de posiciones"""
        for symbol, pos in self.positions.items():
            if symbol in prices:
                pos.update_price(prices[symbol])


# ============================================================================
# TRADING SYSTEM
# ============================================================================

class OmniCapitalLive:
    """Sistema de trading en vivo OmniCapital v6"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.data_feed = YahooDataFeed()
        self.broker = PaperBroker(
            initial_cash=config['PAPER_INITIAL_CASH'],
            commission=config['COMMISSION_PER_SHARE']
        )
        
        # Estado
        self.peak_value = config['PAPER_INITIAL_CASH']
        self.in_protection = False
        self.current_leverage = config['LEVERAGE']
        self.last_rebalance = None
        self.position_entry_times = {}  # symbol -> entry_time
        
        # Tracking
        self.daily_stats = []
        self.stop_events = []
        
        logger.info("=" * 60)
        logger.info("OMNICAPITAL v6 - LIVE TRADING")
        logger.info("=" * 60)
        logger.info(f"Hold time: {config['HOLD_MINUTES']} min ({config['HOLD_MINUTES']/60:.1f}h)")
        logger.info(f"Stop loss: {config['PORTFOLIO_STOP_LOSS']:.0%}")
        logger.info(f"Leverage: {config['LEVERAGE']:.1f}:1")
        logger.info(f"Positions: {config['NUM_POSITIONS']}")
        
    def is_market_open(self) -> bool:
        """Verifica si mercado esta abierto"""
        now = datetime.now()
        
        # Fin de semana
        if now.weekday() >= 5:
            return False
        
        # Horario
        current_time = now.time()
        return self.config['MARKET_OPEN'] <= current_time <= self.config['MARKET_CLOSE']
    
    def get_tradeable_symbols(self) -> List[str]:
        """Obtiene simbolos con datos disponibles"""
        prices = self.data_feed.get_prices(UNIVERSE)
        return list(prices.keys())
    
    def select_symbols(self, available: List[str], exclude: Set[str], n: int) -> List[str]:
        """Selecciona n simbolos aleatoriamente"""
        candidates = [s for s in available if s not in exclude]
        
        if len(candidates) < n:
            return candidates
        
        random.seed(self.config['RANDOM_SEED'] + datetime.now().toordinal())
        return random.sample(candidates, n)
    
    def check_stop_loss(self, prices: Dict[str, float]) -> bool:
        """Verifica y ejecuta stop loss si es necesario"""
        portfolio_value = self.broker.get_portfolio_value(prices)
        
        # Actualizar peak
        if portfolio_value > self.peak_value:
            self.peak_value = portfolio_value
            
            # Verificar recuperacion
            if self.in_protection:
                if portfolio_value >= self.peak_value * self.config['RECOVERY_THRESHOLD']:
                    self.in_protection = False
                    self.current_leverage = self.config['LEVERAGE']
                    logger.info(f"RECUPERACION: Leverage restaurado a {self.current_leverage}:1")
        
        # Calcular drawdown
        drawdown = (portfolio_value - self.peak_value) / self.peak_value if self.peak_value > 0 else 0
        
        # Verificar stop loss
        if drawdown <= self.config['PORTFOLIO_STOP_LOSS'] and not self.in_protection:
            logger.warning(f"STOP LOSS ACTIVADO: Drawdown {drawdown:.2%}")
            self.execute_stop_loss(prices)
            return True
        
        return False
    
    def execute_stop_loss(self, prices: Dict[str, float]):
        """Ejecuta stop loss"""
        logger.info("Cerrando todas las posiciones...")
        
        for symbol in list(self.broker.positions.keys()):
            price = prices.get(symbol)
            if price:
                pos = self.broker.positions[symbol]
                self.broker.sell(symbol, pos.shares, price)
        
        # Activar proteccion
        self.in_protection = True
        self.current_leverage = 1.0
        
        # Registrar evento
        self.stop_events.append({
            'date': datetime.now(),
            'portfolio_value': self.broker.get_portfolio_value(prices),
            'peak_value': self.peak_value
        })
        
        logger.info(f"PROTECCION ACTIVADA: Leverage reducido a 1:1")
    
    def check_expired_positions(self, prices: Dict[str, float]):
        """Cierra posiciones que cumplieron hold time"""
        now = datetime.now()
        
        for symbol in list(self.broker.positions.keys()):
            entry_time = self.position_entry_times.get(symbol)
            if not entry_time:
                continue
            
            minutes_held = (now - entry_time).total_seconds() / 60
            
            if minutes_held >= self.config['HOLD_MINUTES']:
                pos = self.broker.positions[symbol]
                price = prices.get(symbol)
                if price:
                    self.broker.sell(symbol, pos.shares, price)
                    del self.position_entry_times[symbol]
    
    def rebalance(self, prices: Dict[str, float]):
        """Rebalancea portfolio"""
        current_positions = set(self.broker.positions.keys())
        target_count = self.config['NUM_POSITIONS']
        
        # Cerrar posiciones expiradas
        self.check_expired_positions(prices)
        
        # Calcular slots disponibles
        slots_available = target_count - len(self.broker.positions)
        
        if slots_available <= 0:
            return
        
        # Seleccionar nuevos simbolos
        tradeable = self.get_tradeable_symbols()
        current_symbols = set(self.broker.positions.keys())
        new_symbols = self.select_symbols(tradeable, current_symbols, slots_available)
        
        if not new_symbols:
            return
        
        # Calcular tamaño de posicion
        portfolio_value = self.broker.get_portfolio_value(prices)
        effective_capital = self.broker.cash * self.current_leverage
        position_value = effective_capital * (1 - self.config['MIN_CASH_BUFFER']) / target_count
        
        # Abrir nuevas posiciones
        for symbol in new_symbols:
            price = prices.get(symbol)
            if not price or price <= 0:
                continue
            
            shares = position_value / price
            
            if self.broker.buy(symbol, shares, price):
                self.position_entry_times[symbol] = datetime.now()
    
    def log_status(self, prices: Dict[str, float]):
        """Log del estado actual"""
        portfolio_value = self.broker.get_portfolio_value(prices)
        drawdown = (portfolio_value - self.peak_value) / self.peak_value if self.peak_value > 0 else 0
        
        positions_str = ", ".join([
            f"{s}({p.shares:.0f})" 
            for s, p in self.broker.positions.items()
        ])
        
        logger.info(f"PORTFOLIO: ${portfolio_value:,.2f} | "
                   f"DD: {drawdown:.2%} | "
                   f"Pos: {len(self.broker.positions)}/{self.config['NUM_POSITIONS']} | "
                   f"Cash: ${self.broker.cash:,.2f} | "
                   f"Lev: {self.current_leverage:.1f}x | "
                   f"Prot: {self.in_protection} | "
                   f"[{positions_str}]")
    
    def save_state(self):
        """Guarda estado del sistema"""
        state = {
            'timestamp': datetime.now().isoformat(),
            'cash': self.broker.cash,
            'positions': {
                s: {
                    'shares': p.shares,
                    'avg_cost': p.avg_cost,
                    'entry_time': self.position_entry_times.get(s, p.entry_time).isoformat()
                }
                for s, p in self.broker.positions.items()
            },
            'peak_value': self.peak_value,
            'in_protection': self.in_protection,
            'current_leverage': self.current_leverage,
            'stop_events': [
                {**e, 'date': e['date'].isoformat()} 
                for e in self.stop_events
            ]
        }
        
        filename = f'omnicapital_state_{datetime.now().strftime("%Y%m%d")}.json'
        with open(filename, 'w') as f:
            json.dump(state, f, indent=2)
        
        logger.info(f"Estado guardado: {filename}")
    
    def load_state(self, filename: str = None):
        """Carga estado previo"""
        if filename is None:
            # Buscar archivo mas reciente
            import glob
            files = glob.glob('omnicapital_state_*.json')
            if not files:
                return
            filename = max(files, key=os.path.getctime)
        
        if not os.path.exists(filename):
            return
        
        try:
            with open(filename, 'r') as f:
                state = json.load(f)
            
            self.broker.cash = state.get('cash', self.config['PAPER_INITIAL_CASH'])
            self.peak_value = state.get('peak_value', self.config['PAPER_INITIAL_CASH'])
            self.in_protection = state.get('in_protection', False)
            self.current_leverage = state.get('current_leverage', self.config['LEVERAGE'])
            
            # Restaurar posiciones
            for symbol, data in state.get('positions', {}).items():
                self.broker.positions[symbol] = Position(
                    symbol=symbol,
                    shares=data['shares'],
                    avg_cost=data['avg_cost'],
                    entry_time=datetime.fromisoformat(data['entry_time'])
                )
                self.position_entry_times[symbol] = datetime.fromisoformat(data['entry_time'])
            
            logger.info(f"Estado cargado desde {filename}")
            logger.info(f"Cash: ${self.broker.cash:,.2f} | Posiciones: {len(self.broker.positions)}")
            
        except Exception as e:
            logger.error(f"Error cargando estado: {e}")
    
    def run_once(self):
        """Ejecuta un ciclo de trading"""
        # Verificar horario
        if not self.is_market_open():
            logger.debug("Mercado cerrado")
            return False
        
        # Obtener precios
        prices = self.data_feed.get_prices(UNIVERSE + list(self.broker.positions.keys()))
        
        if not prices:
            logger.warning("No se pudieron obtener precios")
            return False
        
        # Actualizar posiciones
        self.broker.update_positions(prices)
        
        # 1. Verificar stop loss
        if self.check_stop_loss(prices):
            self.save_state()
            return True
        
        # 2. Rebalancear
        self.rebalance(prices)
        
        # 3. Log status
        self.log_status(prices)
        
        return True
    
    def run(self, interval: int = 60, save_interval: int = 300):
        """Loop principal de trading"""
        logger.info("Iniciando trading loop...")
        
        last_save = datetime.now()
        
        try:
            while True:
                try:
                    self.run_once()
                    
                    # Guardar estado periodicamente
                    if (datetime.now() - last_save).total_seconds() >= save_interval:
                        self.save_state()
                        last_save = datetime.now()
                    
                    # Esperar
                    import time
                    time.sleep(interval)
                    
                except Exception as e:
                    logger.error(f"Error en loop: {e}", exc_info=True)
                    time.sleep(10)
                    
        except KeyboardInterrupt:
            logger.info("Trading detenido por usuario")
            self.save_state()


def main():
    """Funcion principal"""
    trader = OmniCapitalLive(CONFIG)
    
    # Cargar estado previo
    trader.load_state()
    
    # Conectar broker
    trader.broker.connect()
    
    # Iniciar trading
    trader.run(interval=60, save_interval=300)


if __name__ == "__main__":
    main()
