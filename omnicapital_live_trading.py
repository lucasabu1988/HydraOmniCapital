"""
OmniCapital v6 - Live Trading Implementation
Sistema de trading automatizado para ejecucion en tiempo real.
Compatible con Interactive Brokers (IBKR) API.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta, time
import random
import logging
import json
import os
from typing import Dict, List, Optional
import warnings
warnings.filterwarnings('ignore')

# Configuracion de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('omnicapital_live.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURACION DEL SISTEMA (NO MODIFICAR)
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
    
    # Trading hours (ET)
    'MARKET_OPEN': time(9, 30),
    'MARKET_CLOSE': time(16, 0),
    
    # Capital
    'INITIAL_CAPITAL': 100000,
    
    # Data source
    'DATA_SOURCE': 'IBKR',  # 'IBKR', 'YAHOO', 'ALPACA'
    
    # Risk management
    'MAX_POSITION_SIZE_PCT': 0.25,  # Max 25% en una posicion
    'MIN_CASH_BUFFER': 0.05,  # 5% cash minimo
}

# Universo de trading (S&P 500 large-caps)
UNIVERSE = [
    'AAPL', 'MSFT', 'AMZN', 'NVDA', 'GOOGL', 'META', 'TSLA', 'AVGO',
    'BRK-B', 'JPM', 'V', 'JNJ', 'WMT', 'MA', 'PG', 'UNH', 'HD', 'CVX',
    'MRK', 'PEP', 'KO', 'ABBV', 'BAC', 'COST', 'TMO', 'DIS',
    'ABT', 'WFC', 'ACN', 'VZ', 'DHR', 'ADBE', 'CRM', 'TXN', 'NKE',
    'NEE', 'AMD', 'PM', 'XOM', 'INTC', 'CSCO', 'IBM', 'GE', 'CAT',
    'BA', 'MMM', 'AXP', 'GS', 'MO', 'KMB', 'CL', 'MDT', 'SLB', 'UNP',
    'HON', 'FDX', 'UPS', 'LMT', 'RTX', 'OXY', 'AMGN', 'LLY', 'BMY', 'BIIB'
]


class OmniCapitalTrader:
    """Trader principal del sistema OmniCapital v6"""
    
    def __init__(self, config: Dict, paper_trading: bool = True):
        self.config = config
        self.paper_trading = paper_trading
        self.positions = {}  # symbol -> Position
        self.cash = 0
        self.portfolio_value = 0
        self.peak_value = 0
        self.in_protection = False
        self.current_leverage = config['LEVERAGE']
        self.trade_history = []
        
        # Estado del mercado
        self.market_data = {}
        self.last_update = None
        
        logger.info(f"OmniCapital v6 Trader inicializado")
        logger.info(f"Paper trading: {paper_trading}")
        logger.info(f"Leverage: {self.current_leverage:.1f}:1")
        
    def connect_broker(self):
        """Conecta con el broker (IBKR, Alpaca, etc.)"""
        logger.info(f"Conectando con broker: {self.config['DATA_SOURCE']}")
        
        # TODO: Implementar conexion real con API del broker
        # from ib_insync import IB, Stock, MarketOrder
        # self.ib = IB()
        # self.ib.connect('127.0.0.1', 7497, clientId=1)
        
        logger.info("Conexion establecida (simulada)")
        return True
    
    def get_portfolio_value(self) -> float:
        """Calcula valor actual del portfolio"""
        value = self.cash
        for symbol, pos in self.positions.items():
            current_price = self.get_current_price(symbol)
            if current_price:
                value += pos['shares'] * current_price
        return value
    
    def get_current_price(self, symbol: str) -> Optional[float]:
        """Obtiene precio actual del mercado"""
        # TODO: Implementar con API real
        # return self.ib.reqMktData(Stock(symbol, 'SMART', 'USD')).last
        
        # Simulacion: retornar precio de data feed
        if symbol in self.market_data:
            return self.market_data[symbol].get('last', None)
        return None
    
    def check_stop_loss(self) -> bool:
        """Verifica si se activa stop loss"""
        self.portfolio_value = self.get_portfolio_value()
        
        # Actualizar peak
        if self.portfolio_value > self.peak_value:
            self.peak_value = self.portfolio_value
            if self.in_protection:
                # Verificar recuperacion
                if self.portfolio_value >= self.peak_value * self.config['RECOVERY_THRESHOLD']:
                    self.in_protection = False
                    self.current_leverage = self.config['LEVERAGE']
                    logger.info(f"Recuperacion detectada. Leverage restaurado a {self.current_leverage}:1")
        
        # Calcular drawdown
        drawdown = (self.portfolio_value - self.peak_value) / self.peak_value if self.peak_value > 0 else 0
        
        # Verificar stop loss
        if drawdown <= self.config['PORTFOLIO_STOP_LOSS'] and not self.in_protection:
            logger.warning(f"STOP LOSS ACTIVADO: DD {drawdown:.2%}")
            self.execute_stop_loss()
            return True
        
        return False
    
    def execute_stop_loss(self):
        """Ejecuta stop loss: cierra todo y reduce leverage"""
        logger.info("Ejecutando stop loss...")
        
        # Cerrar todas las posiciones
        for symbol in list(self.positions.keys()):
            self.close_position(symbol, reason='STOP_LOSS')
        
        # Reducir leverage
        self.current_leverage = 1.0
        self.in_protection = True
        
        logger.info(f"Todas las posiciones cerradas. Leverage reducido a {self.current_leverage}:1")
        
        # Guardar estado
        self.save_state()
    
    def close_position(self, symbol: str, reason: str = 'EXPIRED'):
        """Cierra una posicion"""
        if symbol not in self.positions:
            return
        
        pos = self.positions[symbol]
        current_price = self.get_current_price(symbol)
        
        if not current_price:
            logger.error(f"No se pudo obtener precio para {symbol}")
            return
        
        # Calcular P&L
        shares = pos['shares']
        proceeds = shares * current_price
        commission = shares * self.config['COMMISSION_PER_SHARE']
        pnl = (current_price - pos['entry_price']) * shares - commission
        
        # Ejecutar orden de venta
        logger.info(f"CERRANDO {symbol}: {shares:.2f} @ ${current_price:.2f} | P&L: ${pnl:.2f} | Reason: {reason}")
        
        # TODO: Orden real con broker
        # order = MarketOrder('SELL', shares)
        # trade = self.ib.placeOrder(Stock(symbol, 'SMART', 'USD'), order)
        
        # Actualizar cash
        self.cash += proceeds - commission
        
        # Registrar trade
        self.trade_history.append({
            'symbol': symbol,
            'entry_date': pos['entry_date'],
            'exit_date': datetime.now(),
            'entry_price': pos['entry_price'],
            'exit_price': current_price,
            'shares': shares,
            'pnl': pnl,
            'reason': reason
        })
        
        del self.positions[symbol]
    
    def open_position(self, symbol: str):
        """Abre una nueva posicion"""
        if len(self.positions) >= self.config['NUM_POSITIONS']:
            return
        
        if symbol in self.positions:
            return
        
        current_price = self.get_current_price(symbol)
        if not current_price:
            return
        
        # Calcular tamaño de posicion
        portfolio_value = self.get_portfolio_value()
        effective_capital = self.cash * self.current_leverage
        position_value = (effective_capital * (1 - self.config['MIN_CASH_BUFFER'])) / self.config['NUM_POSITIONS']
        
        shares = position_value / current_price
        cost = shares * current_price
        commission = shares * self.config['COMMISSION_PER_SHARE']
        total_cost = cost + commission
        
        if total_cost > self.cash * (1 - self.config['MIN_CASH_BUFFER']):
            logger.warning(f"Cash insuficiente para {symbol}")
            return
        
        # Ejecutar orden de compra
        logger.info(f"ABRIENDO {symbol}: {shares:.2f} @ ${current_price:.2f} | Cost: ${total_cost:.2f}")
        
        # TODO: Orden real con broker
        # order = MarketOrder('BUY', shares)
        # trade = self.ib.placeOrder(Stock(symbol, 'SMART', 'USD'), order)
        
        # Actualizar estado
        self.positions[symbol] = {
            'symbol': symbol,
            'shares': shares,
            'entry_price': current_price,
            'entry_date': datetime.now(),
            'entry_portfolio_value': portfolio_value
        }
        
        self.cash -= total_cost
    
    def select_symbols(self, available: List[str]) -> List[str]:
        """Selecciona simbolos aleatoriamente"""
        needed = self.config['NUM_POSITIONS'] - len(self.positions)
        
        if needed <= 0:
            return []
        
        available = [s for s in available if s not in self.positions]
        
        if len(available) < needed:
            return available
        
        random.seed(self.config['RANDOM_SEED'] + datetime.now().toordinal())
        return random.sample(available, needed)
    
    def check_expired_positions(self):
        """Cierra posiciones que cumplieron hold time"""
        now = datetime.now()
        
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            minutes_held = (now - pos['entry_date']).total_seconds() / 60
            
            if minutes_held >= self.config['HOLD_MINUTES']:
                self.close_position(symbol, reason='EXPIRED')
    
    def get_tradeable_symbols(self) -> List[str]:
        """Retorna simbolos tradeables del universo"""
        tradeable = []
        
        for symbol in UNIVERSE:
            # Verificar disponibilidad de datos
            price = self.get_current_price(symbol)
            if price and price > 0:
                # TODO: Verificar antiguedad minima (63 dias)
                # Por ahora, asumimos que todos son elegibles
                tradeable.append(symbol)
        
        return tradeable
    
    def trading_loop(self):
        """Loop principal de trading"""
        logger.info("Iniciando trading loop...")
        
        while True:
            try:
                now = datetime.now()
                
                # Verificar horario de mercado
                if not self.is_market_open():
                    logger.debug("Mercado cerrado. Esperando...")
                    self.sleep_until_market_open()
                    continue
                
                # Actualizar datos de mercado
                self.update_market_data()
                
                # 1. Verificar stop loss
                if self.check_stop_loss():
                    continue  # Si se activo stop, no abrir nuevas posiciones
                
                # 2. Cerrar posiciones expiradas
                self.check_expired_positions()
                
                # 3. Abrir nuevas posiciones
                tradeable = self.get_tradeable_symbols()
                selected = self.select_symbols(tradeable)
                
                for symbol in selected:
                    self.open_position(symbol)
                
                # 4. Log de estado
                if now.minute % 5 == 0:  # Cada 5 minutos
                    self.log_status()
                
                # Esperar hasta proxima iteracion
                self.sleep(60)  # 1 minuto
                
            except Exception as e:
                logger.error(f"Error en trading loop: {e}", exc_info=True)
                self.sleep(60)
    
    def is_market_open(self) -> bool:
        """Verifica si el mercado esta abierto"""
        now = datetime.now()
        
        # Verificar dia de semana
        if now.weekday() >= 5:  # Sabado o domingo
            return False
        
        # Verificar horario
        current_time = now.time()
        return self.config['MARKET_OPEN'] <= current_time <= self.config['MARKET_CLOSE']
    
    def sleep_until_market_open(self):
        """Duerme hasta la apertura del mercado"""
        # TODO: Implementar
        import time
        time.sleep(60)
    
    def sleep(self, seconds: int):
        """Duerme N segundos"""
        import time
        time.sleep(seconds)
    
    def update_market_data(self):
        """Actualiza datos de mercado"""
        # TODO: Implementar con API real
        pass
    
    def log_status(self):
        """Log del estado actual"""
        portfolio_value = self.get_portfolio_value()
        drawdown = (portfolio_value - self.peak_value) / self.peak_value if self.peak_value > 0 else 0
        
        logger.info(f"STATUS | Portfolio: ${portfolio_value:,.2f} | "
                   f"DD: {drawdown:.2%} | Positions: {len(self.positions)} | "
                   f"Leverage: {self.current_leverage:.1f}x | "
                   f"Protection: {self.in_protection}")
    
    def save_state(self):
        """Guarda estado del sistema"""
        state = {
            'positions': self.positions,
            'cash': self.cash,
            'peak_value': self.peak_value,
            'in_protection': self.in_protection,
            'current_leverage': self.current_leverage,
            'timestamp': datetime.now().isoformat()
        }
        
        with open('omnicapital_state.json', 'w') as f:
            json.dump(state, f, indent=2, default=str)
        
        logger.info("Estado guardado")
    
    def load_state(self):
        """Carga estado previo del sistema"""
        if os.path.exists('omnicapital_state.json'):
            with open('omnicapital_state.json', 'r') as f:
                state = json.load(f)
            
            self.positions = state.get('positions', {})
            self.cash = state.get('cash', self.config['INITIAL_CAPITAL'])
            self.peak_value = state.get('peak_value', self.config['INITIAL_CAPITAL'])
            self.in_protection = state.get('in_protection', False)
            self.current_leverage = state.get('current_leverage', self.config['LEVERAGE'])
            
            logger.info("Estado cargado desde archivo")


def main():
    """Funcion principal"""
    logger.info("=" * 80)
    logger.info("OMNICAPITAL v6 - LIVE TRADING")
    logger.info("=" * 80)
    
    # Crear trader
    trader = OmniCapitalTrader(CONFIG, paper_trading=True)
    
    # Conectar con broker
    if not trader.connect_broker():
        logger.error("No se pudo conectar con broker")
        return
    
    # Cargar estado previo
    trader.load_state()
    
    # Iniciar trading
    try:
        trader.trading_loop()
    except KeyboardInterrupt:
        logger.info("Trading detenido por usuario")
        trader.save_state()
    except Exception as e:
        logger.error(f"Error fatal: {e}", exc_info=True)
        trader.save_state()


if __name__ == "__main__":
    main()
