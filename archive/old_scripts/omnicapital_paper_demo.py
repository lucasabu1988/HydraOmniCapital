"""
OmniCapital v6 - Paper Trading Demo
Simulacion de trading para demostracion sin dependencia de mercado abierto
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
        logging.FileHandler(f'omnicapital_demo_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURACION v6 (NO MODIFICAR)
# =============================================================================

CONFIG = {
    'HOLD_MINUTES': 1200,
    'NUM_POSITIONS': 5,
    'PORTFOLIO_STOP_LOSS': -0.20,
    'LEVERAGE': 2.0,
    'MIN_AGE_DAYS': 63,
    'RANDOM_SEED': 42,
    'COMMISSION_PER_SHARE': 0.001,
    'RECOVERY_THRESHOLD': 0.95,
    'MARKET_OPEN': time(9, 30),
    'MARKET_CLOSE': time(16, 0),
    'INITIAL_CAPITAL': 100000,
    'BROKER_TYPE': 'PAPER_DEMO',
    'DATA_SOURCE': 'SIMULATED',
    'MAX_POSITION_SIZE_PCT': 0.25,
    'MIN_CASH_BUFFER': 0.05,
}

# Universo de 10 stocks para demo
UNIVERSE = ['AAPL', 'MSFT', 'AMZN', 'NVDA', 'GOOGL', 'META', 'TSLA', 'JPM', 'V', 'JNJ']

# Precios simulados (base para generar movimientos)
BASE_PRICES = {
    'AAPL': 185.0, 'MSFT': 420.0, 'AMZN': 175.0, 'NVDA': 875.0, 'GOOGL': 165.0,
    'META': 495.0, 'TSLA': 190.0, 'JPM': 195.0, 'V': 280.0, 'JNJ': 155.0
}


class SimulatedDataFeed:
    """Data feed simulado para demo"""
    
    def __init__(self):
        self.prices = BASE_PRICES.copy()
        self.last_update = datetime.now()
        
    def get_price(self, symbol: str) -> Optional[float]:
        """Genera precio con movimiento aleatorio"""
        if symbol not in self.prices:
            return None
        
        # Simular movimiento de precio (0.5% max)
        base = self.prices[symbol]
        change = random.uniform(-0.005, 0.005)
        price = base * (1 + change)
        self.prices[symbol] = price  # Actualizar base
        return price
    
    def get_prices(self, symbols: List[str]) -> Dict[str, float]:
        """Obtiene multiples precios"""
        return {s: self.get_price(s) for s in symbols if self.get_price(s)}


class PaperBroker:
    """Broker de papel para demo"""
    
    def __init__(self, initial_cash: float = 100000, commission: float = 0.001):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.commission = commission
        self.positions: Dict[str, dict] = {}
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
            total_shares = pos['shares'] + shares
            total_cost = pos['shares'] * pos['avg_cost'] + shares * price
            pos['shares'] = total_shares
            pos['avg_cost'] = total_cost / total_shares
        else:
            self.positions[symbol] = {
                'symbol': symbol,
                'shares': shares,
                'avg_cost': price,
                'entry_time': datetime.now(),
            }
        
        self.cash -= total
        self._order_id += 1
        
        logger.info(f"BUY {symbol}: {shares:.2f} @ ${price:.2f} | Cost: ${total:.2f}")
        
        self.trade_history.append({
            'id': self._order_id,
            'time': datetime.now(),
            'symbol': symbol,
            'action': 'BUY',
            'shares': shares,
            'price': price,
            'commission': commission,
        })
        
        return True
    
    def sell(self, symbol: str, shares: float, price: float) -> bool:
        """Ejecuta venta"""
        if symbol not in self.positions:
            return False
        
        pos = self.positions[symbol]
        if shares > pos['shares']:
            shares = pos['shares']
        
        proceeds = shares * price
        commission = shares * self.commission
        pnl = (price - pos['avg_cost']) * shares
        
        pos['shares'] -= shares
        if pos['shares'] <= 0:
            del self.positions[symbol]
        
        self.cash += proceeds - commission
        self._order_id += 1
        
        logger.info(f"SELL {symbol}: {shares:.2f} @ ${price:.2f} | P&L: ${pnl:.2f}")
        
        self.trade_history.append({
            'id': self._order_id,
            'time': datetime.now(),
            'symbol': symbol,
            'action': 'SELL',
            'shares': shares,
            'price': price,
            'commission': commission,
            'pnl': pnl,
        })
        
        return True
    
    def get_portfolio_value(self, prices: Dict[str, float]) -> float:
        """Calcula valor del portfolio"""
        value = self.cash
        for symbol, pos in self.positions.items():
            price = prices.get(symbol, pos['avg_cost'])
            value += pos['shares'] * price
        return value


class OmniCapitalDemo:
    """Sistema de trading demo"""
    
    def __init__(self, config: dict):
        self.config = config
        self.data_feed = SimulatedDataFeed()
        self.broker = PaperBroker(
            initial_cash=config['INITIAL_CAPITAL'],
            commission=config['COMMISSION_PER_SHARE']
        )
        
        self.peak_value = config['INITIAL_CAPITAL']
        self.in_protection = False
        self.current_leverage = config['LEVERAGE']
        self.stop_events = []
        self.iteration = 0
        
        logger.info("="*60)
        logger.info("OMNICAPITAL v6 - PAPER TRADING DEMO")
        logger.info("="*60)
        logger.info(f"Hold time: {config['HOLD_MINUTES']} min ({config['HOLD_MINUTES']/60:.1f}h)")
        logger.info(f"Stop loss: {config['PORTFOLIO_STOP_LOSS']:.0%}")
        logger.info(f"Leverage: {config['LEVERAGE']:.1f}:1")
        logger.info(f"Positions: {config['NUM_POSITIONS']}")
        
    def check_stop_loss(self, prices: Dict[str, float]) -> bool:
        """Verifica stop loss"""
        portfolio_value = self.broker.get_portfolio_value(prices)
        
        # Actualizar peak
        if portfolio_value > self.peak_value:
            self.peak_value = portfolio_value
            if self.in_protection and portfolio_value >= self.peak_value * self.config['RECOVERY_THRESHOLD']:
                self.in_protection = False
                self.current_leverage = self.config['LEVERAGE']
                logger.info(f"RECUPERACION: Saliendo de proteccion. Leverage: {self.current_leverage}:1")
        
        drawdown = (portfolio_value - self.peak_value) / self.peak_value if self.peak_value > 0 else 0
        
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
                self.broker.sell(symbol, pos['shares'], price)
        
        self.in_protection = True
        self.current_leverage = 1.0
        self.stop_events.append({
            'time': datetime.now(),
            'portfolio_value': self.broker.get_portfolio_value(prices),
            'peak': self.peak_value
        })
        
        logger.info(f"PROTECCION ACTIVADA: Leverage reducido a 1:1")
    
    def check_expired_positions(self, prices: Dict[str, float]):
        """Cierra posiciones expiradas"""
        now = datetime.now()
        
        for symbol in list(self.broker.positions.keys()):
            pos = self.broker.positions[symbol]
            minutes_held = (now - pos['entry_time']).total_seconds() / 60
            
            if minutes_held >= self.config['HOLD_MINUTES']:
                price = prices.get(symbol)
                if price:
                    self.broker.sell(symbol, pos['shares'], price)
    
    def select_symbols(self, available: List[str], n: int) -> List[str]:
        """Selecciona n simbolos aleatoriamente"""
        current = set(self.broker.positions.keys())
        candidates = [s for s in available if s not in current]
        
        if len(candidates) < n:
            return candidates
        
        random.seed(self.config['RANDOM_SEED'] + self.iteration)
        return random.sample(candidates, n)
    
    def rebalance(self, prices: Dict[str, float]):
        """Rebalancea portfolio"""
        # Cerrar expiradas
        self.check_expired_positions(prices)
        
        slots = self.config['NUM_POSITIONS'] - len(self.broker.positions)
        if slots <= 0 or self.in_protection:
            return
        
        # Seleccionar nuevos
        available = [s for s in UNIVERSE if s in prices and s not in self.broker.positions]
        selected = self.select_symbols(available, slots)
        
        if not selected:
            return
        
        # Calcular tamaño de posicion
        portfolio_value = self.broker.get_portfolio_value(prices)
        effective_cash = self.broker.cash * self.current_leverage
        position_value = effective_cash * (1 - self.config['MIN_CASH_BUFFER']) / self.config['NUM_POSITIONS']
        
        # Abrir posiciones
        for symbol in selected:
            price = prices.get(symbol)
            if not price or price <= 0:
                continue
            
            shares = position_value / price
            if self.broker.buy(symbol, shares, price):
                self.broker.positions[symbol]['entry_time'] = datetime.now()
    
    def log_status(self, prices: Dict[str, float]):
        """Log del estado"""
        portfolio_value = self.broker.get_portfolio_value(prices)
        drawdown = (portfolio_value - self.peak_value) / self.peak_value if self.peak_value > 0 else 0
        
        positions_str = ", ".join([f"{s}({p['shares']:.0f})" for s, p in self.broker.positions.items()])
        
        logger.info(f"PORTFOLIO: ${portfolio_value:,.2f} | "
                   f"DD: {drawdown:.2%} | "
                   f"Pos: {len(self.broker.positions)}/{self.config['NUM_POSITIONS']} | "
                   f"Cash: ${self.broker.cash:,.2f} | "
                   f"Lev: {self.current_leverage:.1f}x | "
                   f"Prot: {self.in_protection} | "
                   f"[{positions_str}]")
    
    def run_demo(self, iterations: int = 20, interval_seconds: float = 1):
        """Ejecuta demo de trading"""
        logger.info("Iniciando demo de trading...")
        logger.info(f"Simulando {iterations} ciclos de trading")
        logger.info("="*60)
        
        self.broker.connect()
        
        for i in range(iterations):
            self.iteration = i
            
            # Obtener precios
            prices = self.data_feed.get_prices(UNIVERSE)
            
            # 1. Verificar stop loss
            if self.check_stop_loss(prices):
                pass  # Si se activo stop, no abrir nuevas
            
            # 2. Rebalancear
            self.rebalance(prices)
            
            # 3. Log status (cada 5 iteraciones)
            if i % 5 == 0 or i == iterations - 1:
                self.log_status(prices)
            
            # Simular espera
            import time
            time.sleep(interval_seconds)
        
        # Reporte final
        self.generate_report(prices)
    
    def generate_report(self, prices: Dict[str, float]):
        """Genera reporte final"""
        final_value = self.broker.get_portfolio_value(prices)
        initial = self.config['INITIAL_CAPITAL']
        total_return = (final_value - initial) / initial
        
        logger.info("="*60)
        logger.info("DEMO COMPLETADO - REPORTE FINAL")
        logger.info("="*60)
        logger.info(f"Capital inicial:  ${initial:,.2f}")
        logger.info(f"Capital final:    ${final_value:,.2f}")
        logger.info(f"Return:           {total_return:.2%}")
        logger.info(f"Peak value:       ${self.peak_value:,.2f}")
        logger.info(f"Max drawdown:     {(final_value - self.peak_value) / self.peak_value:.2%}")
        logger.info(f"Trades:           {len(self.broker.trade_history)}")
        logger.info(f"Stop events:      {len(self.stop_events)}")
        logger.info(f"Posiciones finales: {len(self.broker.positions)}")
        
        if self.broker.positions:
            logger.info("Posiciones abiertas:")
            for symbol, pos in self.broker.positions.items():
                current_price = prices.get(symbol, pos['avg_cost'])
                pnl = (current_price - pos['avg_cost']) * pos['shares']
                logger.info(f"  {symbol}: {pos['shares']:.2f} @ ${pos['avg_cost']:.2f} (P&L: ${pnl:.2f})")
        
        # Guardar estado
        state = {
            'timestamp': datetime.now().isoformat(),
            'initial_capital': initial,
            'final_value': final_value,
            'return': total_return,
            'peak_value': self.peak_value,
            'stop_events': len(self.stop_events),
            'trades': len(self.broker.trade_history),
            'positions': {s: {'shares': p['shares'], 'avg_cost': p['avg_cost']} 
                         for s, p in self.broker.positions.items()}
        }
        
        with open('demo_state.json', 'w') as f:
            json.dump(state, f, indent=2, default=str)
        
        logger.info("Estado guardado: demo_state.json")


def main():
    trader = OmniCapitalDemo(CONFIG)
    trader.run_demo(iterations=30, interval_seconds=0.5)


if __name__ == "__main__":
    main()
