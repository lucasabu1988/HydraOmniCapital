"""
Simulación de trading live sin conexión a internet.
Usa precios generados sintéticamente para validar todo el flujo.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, time, timedelta
from unittest.mock import MagicMock, patch
import random
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from omnicapital_live import OmniCapitalLive, CONFIG, UNIVERSE


class MockDataFeed:
    """Data feed simulado para testing offline"""
    
    def __init__(self, initial_prices=None):
        self.prices = initial_prices or {}
        self._price_history = {}
        self._drift = 0.0001  # Drift diario 0.01%
        self._volatility = 0.002  # Volatilidad 0.2% por ciclo
        
        # Inicializar precios si no existen
        for symbol in UNIVERSE.keys():
            if symbol not in self.prices:
                # Precio base aleatorio entre $50 y $500
                self.prices[symbol] = random.uniform(50, 500)
                self._price_history[symbol] = [self.prices[symbol]]
    
    def get_price(self, symbol: str):
        """Obtiene precio con movimiento aleatorio"""
        if symbol not in self.prices:
            return None
        
        # Simular movimiento de precio
        current = self.prices[symbol]
        change = random.gauss(self._drift, self._volatility)
        new_price = current * (1 + change)
        
        # Limitar cambio máximo
        new_price = max(current * 0.95, min(current * 1.05, new_price))
        
        self.prices[symbol] = new_price
        self._price_history[symbol].append(new_price)
        
        return new_price
    
    def get_prices(self, symbols):
        """Obtiene múltiples precios"""
        return {s: self.get_price(s) for s in symbols if s in self.prices}
    
    def is_connected(self):
        return True


def simulate_trading_session(duration_minutes=30, interval_seconds=5):
    """
    Simula una sesión de trading completa.
    
    Args:
        duration_minutes: Duración de la simulación en minutos
        interval_seconds: Intervalo entre ciclos (simulado)
    """
    logger.info("=" * 70)
    logger.info("OMNICAPITAL v6 - SIMULACIÓN DE TRADING LIVE")
    logger.info("=" * 70)
    logger.info(f"Duración: {duration_minutes} minutos simulados")
    logger.info(f"Intervalo: {interval_seconds} segundos")
    logger.info("")
    
    # Crear configuración de test
    config = CONFIG.copy()
    config['PAPER_INITIAL_CASH'] = 100000
    config['HOLD_MINUTES'] = 5  # Reducido para simulación rápida
    config['PORTFOLIO_STOP_LOSS'] = -0.10  # 10% para simulación
    
    # Crear trader
    trader = OmniCapitalLive(config)
    trader.broker.connect()
    
    # Reemplazar data feed con mock
    mock_feed = MockDataFeed()
    trader.data_feed = mock_feed
    trader.broker.set_price_feed(mock_feed)
    
    # Simular precios iniciales
    initial_prices = {s: mock_feed.get_price(s) for s in list(UNIVERSE.keys())[:10]}
    logger.info("Precios iniciales:")
    for sym, price in list(initial_prices.items())[:5]:
        logger.info(f"  {sym}: ${price:.2f}")
    
    # Forzar mercado abierto
    with patch.object(trader, 'is_market_open', return_value=True):
        # Simular ciclos
        num_cycles = (duration_minutes * 60) // interval_seconds
        
        logger.info("")
        logger.info(f"Iniciando simulación ({num_cycles} ciclos)...")
        logger.info("")
        
        for cycle in range(num_cycles):
            # Ejecutar ciclo
            success = trader.run_once()
            
            if not success:
                logger.warning(f"Ciclo {cycle} falló")
            
            # Log cada 5 ciclos
            if cycle % 5 == 0:
                portfolio = trader.broker.get_portfolio()
                positions = trader.broker.get_positions()
                
                logger.info(f"Ciclo {cycle:3d}: "
                           f"Portfolio: ${portfolio.total_value:,.2f} | "
                           f"Posiciones: {len(positions)} | "
                           f"Cash: ${portfolio.cash:,.2f}")
            
            # Simular paso del tiempo
            # (En simulación no esperamos realmente)
    
    # Resultados finales
    logger.info("")
    logger.info("=" * 70)
    logger.info("RESULTADOS FINALES")
    logger.info("=" * 70)
    
    portfolio = trader.broker.get_portfolio()
    positions = trader.broker.get_positions()
    
    logger.info(f"Portfolio final: ${portfolio.total_value:,.2f}")
    logger.info(f"Cash: ${portfolio.cash:,.2f}")
    logger.info(f"Posiciones abiertas: {len(positions)}")
    logger.info(f"Peak value: ${trader.peak_value:,.2f}")
    logger.info(f"En protección: {trader.in_protection}")
    logger.info(f"Leverage actual: {trader.current_leverage}x")
    
    # Calcular métricas
    total_return = (portfolio.total_value - config['PAPER_INITIAL_CASH']) / config['PAPER_INITIAL_CASH']
    max_drawdown = (trader.peak_value - min(portfolio.total_value, trader.peak_value)) / trader.peak_value if trader.peak_value > 0 else 0
    
    logger.info(f"Retorno total: {total_return:.2%}")
    logger.info(f"Max drawdown: {max_drawdown:.2%}")
    
    # Listar posiciones
    if positions:
        logger.info("")
        logger.info("Posiciones:")
        for sym, pos in positions.items():
            pnl_pct = (pos.market_price - pos.avg_cost) / pos.avg_cost * 100
            logger.info(f"  {sym}: {pos.shares:.2f} shares @ ${pos.avg_cost:.2f} "
                       f"(actual: ${pos.market_price:.2f}, P&L: {pnl_pct:+.2f}%)")
    
    # Listar trades
    if trader.broker.order_history:
        logger.info("")
        logger.info(f"Trades ejecutados: {len(trader.broker.order_history)}")
        
        buys = [o for o in trader.broker.order_history if o.action == 'BUY']
        sells = [o for o in trader.broker.order_history if o.action == 'SELL']
        
        logger.info(f"  Compras: {len(buys)}")
        logger.info(f"  Ventas: {len(sells)}")
        
        # Calcular P&L realizado
        realized_pnl = sum(o.get('pnl', 0) for o in trader.broker.order_history if o.action == 'SELL')
        logger.info(f"  P&L realizado: ${realized_pnl:,.2f}")
    
    # Guardar estado
    trader.save_state()
    logger.info("")
    logger.info("Estado guardado.")
    
    return {
        'final_value': portfolio.total_value,
        'total_return': total_return,
        'max_drawdown': max_drawdown,
        'num_positions': len(positions),
        'num_trades': len(trader.broker.order_history),
        'in_protection': trader.in_protection
    }


def simulate_stop_loss_scenario():
    """Simula escenario donde se activa el stop loss"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("SIMULACIÓN: ACTIVACIÓN DE STOP LOSS")
    logger.info("=" * 70)
    
    config = CONFIG.copy()
    config['PAPER_INITIAL_CASH'] = 100000
    config['PORTFOLIO_STOP_LOSS'] = -0.05  # 5% para simulación rápida
    
    trader = OmniCapitalLive(config)
    trader.broker.connect()
    
    # Mock feed con precios controlados
    mock_feed = MockDataFeed()
    trader.data_feed = mock_feed
    trader.broker.set_price_feed(mock_feed)
    
    # Abrir posiciones iniciales
    logger.info("Abriendo posiciones iniciales...")
    with patch.object(trader, 'is_market_open', return_value=True):
        for _ in range(3):
            trader.run_once()
    
    initial_value = trader.broker.get_portfolio().total_value
    logger.info(f"Valor inicial: ${initial_value:,.2f}")
    
    # Simular caída de precios (crash)
    logger.info("")
    logger.info("Simulando caída de mercado (-10%)...")
    for symbol in mock_feed.prices:
        mock_feed.prices[symbol] *= 0.90  # Caída del 10%
    
    # Ejecutar ciclo (debe activar stop loss)
    with patch.object(trader, 'is_market_open', return_value=True):
        trader.run_once()
    
    final_value = trader.broker.get_portfolio().total_value
    logger.info(f"Valor final: ${final_value:,.2f}")
    logger.info(f"En protección: {trader.in_protection}")
    logger.info(f"Leverage: {trader.current_leverage}x")
    
    # Verificar
    if trader.in_protection:
        logger.info("✅ Stop loss activado correctamente")
    else:
        logger.error("❌ Stop loss no se activó")
    
    if trader.current_leverage == 1.0:
        logger.info("✅ Leverage reducido a 1x")
    else:
        logger.error("❌ Leverage no se redujo")
    
    return trader.in_protection


def simulate_recovery_scenario():
    """Simula escenario de recuperación tras stop loss"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("SIMULACIÓN: RECUPERACIÓN TRAS STOP LOSS")
    logger.info("=" * 70)
    
    config = CONFIG.copy()
    config['PAPER_INITIAL_CASH'] = 100000
    config['PORTFOLIO_STOP_LOSS'] = -0.05
    config['RECOVERY_THRESHOLD'] = 0.95
    
    trader = OmniCapitalLive(config)
    trader.broker.connect()
    
    # Establecer estado post-stop-loss
    trader.peak_value = 100000
    trader.in_protection = True
    trader.current_leverage = 1.0
    
    logger.info(f"Estado inicial: Protección={trader.in_protection}, "
                f"Leverage={trader.current_leverage}x, Peak=${trader.peak_value:,.2f}")
    
    # Mock portfolio por debajo del threshold
    with patch.object(trader.broker, 'get_portfolio') as mock_pf:
        # Primero por debajo del threshold
        mock_pf.return_value = MagicMock(total_value=94000)  # 94% del peak
        
        with patch.object(trader, 'is_market_open', return_value=True):
            trader.run_once()
        
        logger.info(f"Con portfolio $94,000: Protección={trader.in_protection}")
        
        # Ahora por encima del threshold
        mock_pf.return_value = MagicMock(total_value=96000)  # 96% del peak
        
        with patch.object(trader, 'is_market_open', return_value=True):
            trader.run_once()
        
        logger.info(f"Con portfolio $96,000: Protección={trader.in_protection}, "
                    f"Leverage={trader.current_leverage}x")
    
    if not trader.in_protection and trader.current_leverage == 2.0:
        logger.info("✅ Recuperación funcionó correctamente")
        return True
    else:
        logger.error("❌ Recuperación falló")
        return False


def main():
    """Ejecutar todas las simulaciones"""
    logger.info("\n" + "=" * 70)
    logger.info("OMNICAPITAL v6 - SUITE DE SIMULACIÓN")
    logger.info("=" * 70)
    logger.info(f"Fecha: {datetime.now()}")
    
    results = {}
    
    # Simulación 1: Sesión normal de trading
    try:
        results['normal_session'] = simulate_trading_session(
            duration_minutes=10,  # 10 minutos simulados
            interval_seconds=10
        )
    except Exception as e:
        logger.error(f"Error en simulación normal: {e}")
        results['normal_session'] = None
    
    # Simulación 2: Stop loss
    try:
        results['stop_loss'] = simulate_stop_loss_scenario()
    except Exception as e:
        logger.error(f"Error en simulación stop loss: {e}")
        results['stop_loss'] = False
    
    # Simulación 3: Recuperación
    try:
        results['recovery'] = simulate_recovery_scenario()
    except Exception as e:
        logger.error(f"Error en simulación recuperación: {e}")
        results['recovery'] = False
    
    # Resumen
    logger.info("")
    logger.info("=" * 70)
    logger.info("RESUMEN DE SIMULACIONES")
    logger.info("=" * 70)
    
    if results['normal_session']:
        r = results['normal_session']
        logger.info(f"Sesión normal:")
        logger.info(f"  Retorno: {r['total_return']:.2%}")
        logger.info(f"  Trades: {r['num_trades']}")
        logger.info(f"  Posiciones finales: {r['num_positions']}")
    
    logger.info(f"\nStop loss: {'✅ OK' if results['stop_loss'] else '❌ FAIL'}")
    logger.info(f"Recuperación: {'✅ OK' if results['recovery'] else '❌ FAIL'}")
    
    all_passed = (
        results['normal_session'] is not None and
        results['stop_loss'] and
        results['recovery']
    )
    
    logger.info("")
    if all_passed:
        logger.info("🎉 Todas las simulaciones pasaron. Sistema listo.")
    else:
        logger.warning("⚠️ Algunas simulaciones fallaron.")
    
    return all_passed


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
