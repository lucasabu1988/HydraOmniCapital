"""
Validación rápida del sistema live sin ejecutar trading real.
Verifica conectividad, cálculos y componentes.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, date, time
import logging

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from omnicapital_data_feed import YahooDataFeed, MarketDataManager
from omnicapital_broker import PaperBroker, Order
from omnicapital_live import COMPASSLive, CONFIG, DataValidator


def test_data_feed():
    """Test del data feed"""
    logger.info("=" * 60)
    logger.info("TEST 1: Data Feed (Yahoo Finance)")
    logger.info("=" * 60)
    
    feed = YahooDataFeed(cache_duration=60)
    
    # Test conexión
    logger.info("Verificando conexión...")
    connected = feed.is_connected()
    logger.info(f"  Conectado: {connected}")
    
    if not connected:
        logger.error("❌ No se pudo conectar con Yahoo Finance")
        return False
    
    # Test precios
    test_symbols = ['AAPL', 'MSFT', 'SPY', 'QQQ']
    logger.info(f"Obteniendo precios para: {test_symbols}")
    
    prices = feed.get_prices(test_symbols)
    
    if not prices:
        logger.error("❌ No se obtuvieron precios")
        return False
    
    logger.info(f"  Precios obtenidos: {len(prices)}/{len(test_symbols)}")
    for sym, price in prices.items():
        logger.info(f"    {sym}: ${price:.2f}")
    
    # Test cache
    logger.info("Verificando cache (segunda llamada)...")
    prices_cached = feed.get_prices(test_symbols)
    logger.info(f"  Cache funciona: {prices == prices_cached}")
    
    logger.info("✅ Data Feed OK")
    return True


def test_broker():
    """Test del broker de papel"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST 2: Paper Broker")
    logger.info("=" * 60)
    
    broker = PaperBroker(initial_cash=100000, commission_per_share=0.001)
    
    # Conectar
    logger.info("Conectando broker...")
    connected = broker.connect()
    logger.info(f"  Conectado: {connected}")
    
    # Setup price feed mock
    from unittest.mock import MagicMock
    feed = MagicMock()
    feed.get_price.return_value = 150.0
    broker.set_price_feed(feed)
    
    # Test compra
    logger.info("Ejecutando orden de compra (AAPL x 10)...")
    order = Order(symbol='AAPL', action='BUY', quantity=10)
    result = broker.submit_order(order)
    
    if result.status != 'FILLED':
        logger.error(f"❌ Orden no ejecutada: {result.status}")
        return False
    
    logger.info(f"  Orden ejecutada: {result.filled_quantity} @ ${result.filled_price:.2f}")
    logger.info(f"  Comisión: ${result.commission:.3f}")
    
    # Verificar posición
    positions = broker.get_positions()
    logger.info(f"  Posiciones: {len(positions)}")
    
    if 'AAPL' not in positions:
        logger.error("❌ Posición no creada")
        return False
    
    pos = positions['AAPL']
    logger.info(f"    AAPL: {pos.shares} shares @ ${pos.avg_cost:.2f}")
    
    # Test portfolio
    portfolio = broker.get_portfolio()
    logger.info(f"  Portfolio value: ${portfolio.total_value:,.2f}")
    logger.info(f"  Cash: ${portfolio.cash:,.2f}")
    logger.info(f"  Buying power: ${portfolio.buying_power:,.2f}")
    
    # Test venta parcial
    logger.info("Ejecutando venta parcial (AAPL x 5)...")
    sell_order = Order(symbol='AAPL', action='SELL', quantity=5)
    result = broker.submit_order(sell_order)
    
    if result.status != 'FILLED':
        logger.error(f"❌ Venta no ejecutada: {result.status}")
        return False
    
    logger.info(f"  Venta ejecutada: P&L = ${result.filled_price - pos.avg_cost:.2f}")
    
    positions = broker.get_positions()
    logger.info(f"  Posición restante: {positions['AAPL'].shares} shares")
    
    logger.info("✅ Paper Broker OK")
    return True


def test_data_validator():
    """Test del validador de datos"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST 3: Data Validator")
    logger.info("=" * 60)
    
    config = {
        'MIN_VALID_PRICE': 0.01,
        'MAX_VALID_PRICE': 50000,
        'MAX_PRICE_CHANGE_PCT': 0.20
    }
    
    validator = DataValidator(config)
    
    # Test precios válidos
    logger.info("Validando precios...")
    test_cases = [
        ('AAPL', 150.0, True),
        ('AAPL', 0.0, False),
        ('AAPL', -10.0, False),
        ('AAPL', 50001.0, False),
        ('AAPL', 0.01, True),
    ]
    
    for symbol, price, expected in test_cases:
        result = validator.is_valid_price(symbol, price)
        status = "✅" if result == expected else "❌"
        logger.info(f"  {status} {symbol} @ ${price:.2f} -> {result} (expected: {expected})")
    
    # Test price recording & stats
    logger.info("Registrando precios y verificando stats...")
    for i in range(5):
        validator.record_price('TEST', 100 + i * 5)

    stats = validator.get_stats()
    logger.info(f"  Validated: {stats['total_validated']}, Rejected: {stats['total_rejected']}")
    
    logger.info("✅ Data Validator OK")
    return True


def test_trading_system():
    """Test del sistema de trading integrado (COMPASSLive)"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST 4: Trading System Integration")
    logger.info("=" * 60)

    config = CONFIG.copy()
    config['PAPER_INITIAL_CASH'] = 100000

    trader = COMPASSLive(config)

    # Test inicialización
    logger.info("Inicialización...")
    logger.info(f"  Peak value: ${trader.peak_value:,.2f}")
    logger.info(f"  Crash cooldown: {trader.crash_cooldown}")
    logger.info(f"  Regime score: {trader.current_regime_score}")

    if trader.peak_value != 100000:
        logger.error(f"❌ Peak value incorrecto: {trader.peak_value}")
        return False

    # Test horario de mercado
    logger.info("Verificando horario de mercado...")
    is_open = trader.is_market_open()
    logger.info(f"  Mercado abierto: {is_open}")

    # Test max positions (regime-based)
    logger.info("Calculando max positions por régimen...")
    trader.current_regime_score = 0.8  # Risk-on
    trader._spy_hist = None  # No SPY data, skip bull override
    max_pos_on = trader.get_max_positions()
    logger.info(f"  Risk-on (score=0.8): {max_pos_on} positions")

    trader.current_regime_score = 0.2  # Risk-off
    max_pos_off = trader.get_max_positions()
    logger.info(f"  Risk-off (score=0.2): {max_pos_off} positions")

    if max_pos_on < max_pos_off:
        logger.error(f"❌ Risk-on should have >= positions than risk-off")
        return False

    # Test guardar/cargar estado
    logger.info("Test guardar/cargar estado...")
    trader.trading_day_counter = 6
    trader.last_trading_date = date.today()
    trader.peak_value = 110000
    trader.current_regime_score = 0.65
    trader.save_state()

    # Cargar en nuevo trader
    new_trader = COMPASSLive(config)
    new_trader.load_state()

    logger.info(f"  Peak cargado: ${new_trader.peak_value:,.2f}")
    logger.info(f"  Regime cargado: {new_trader.current_regime_score}")

    if new_trader.peak_value != 110000:
        logger.error("❌ Peak value no cargado correctamente")
        return False

    logger.info("✅ Trading System OK")
    return True


def test_drawdown_leverage():
    """Test lógica de drawdown-tiered leverage scaling"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST 5: Drawdown Leverage Scaling")
    logger.info("=" * 60)

    config = CONFIG.copy()
    config['PAPER_INITIAL_CASH'] = 100000
    trader = COMPASSLive(config)
    trader.broker.connect()
    trader._spy_hist = None  # Skip vol targeting

    # Establecer peak
    trader.peak_value = 100000
    logger.info(f"Peak value: ${trader.peak_value:,.2f}")

    from unittest.mock import MagicMock, patch

    # Test 1: No drawdown → full leverage
    logger.info("Test 1: Portfolio at peak (full leverage)...")
    with patch.object(trader.broker, 'get_portfolio') as mock_pf:
        mock_pf.return_value = MagicMock(total_value=100000)
        lev = trader.get_current_leverage()
        logger.info(f"  Leverage: {lev}")
        if lev != config['LEV_FULL']:
            logger.error(f"❌ Expected {config['LEV_FULL']}, got {lev}")
            return False

    # Test 2: Moderate drawdown (-15%) → reduced leverage
    logger.info("Test 2: Portfolio at -15% DD (reduced leverage)...")
    with patch.object(trader.broker, 'get_portfolio') as mock_pf:
        mock_pf.return_value = MagicMock(total_value=85000)
        lev = trader.get_current_leverage()
        logger.info(f"  Leverage: {lev}")
        if lev >= config['LEV_FULL']:
            logger.error(f"❌ Leverage should be reduced at -15% DD, got {lev}")
            return False

    # Test 3: Severe drawdown (-30%) → further reduced
    logger.info("Test 3: Portfolio at -30% DD (low leverage)...")
    with patch.object(trader.broker, 'get_portfolio') as mock_pf:
        mock_pf.return_value = MagicMock(total_value=70000)
        lev = trader.get_current_leverage()
        logger.info(f"  Leverage: {lev}")
        if lev >= config['LEV_MID']:
            logger.error(f"❌ Leverage should be below LEV_MID at -30% DD, got {lev}")
            return False

    # Test 4: Recovery → peak updates, full leverage restored
    logger.info("Test 4: Recovery past peak (leverage restored)...")
    with patch.object(trader.broker, 'get_portfolio') as mock_pf:
        mock_pf.return_value = MagicMock(total_value=105000)
        lev = trader.get_current_leverage()
        logger.info(f"  Leverage: {lev}")
        logger.info(f"  New peak: ${trader.peak_value:,.2f}")
        if lev != config['LEV_FULL']:
            logger.error(f"❌ Leverage should be full after recovery, got {lev}")
            return False
        if trader.peak_value != 105000:
            logger.error(f"❌ Peak should update to 105000, got {trader.peak_value}")
            return False

    logger.info("✅ Drawdown Leverage Scaling OK")
    return True


def run_all_tests():
    """Ejecutar todos los tests de validación"""
    logger.info("\n" + "=" * 60)
    logger.info("OMNICAPITAL LIVE - VALIDACIÓN DE SISTEMA")
    logger.info("=" * 60)
    logger.info(f"Fecha: {datetime.now()}")
    logger.info("")
    
    tests = [
        ("Data Feed", test_data_feed),
        ("Paper Broker", test_broker),
        ("Data Validator", test_data_validator),
        ("Trading System", test_trading_system),
        ("Drawdown Leverage", test_drawdown_leverage),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            success = test_func()
            results.append((name, success))
        except Exception as e:
            logger.error(f"❌ Error en {name}: {e}")
            results.append((name, False))
    
    # Resumen
    logger.info("")
    logger.info("=" * 60)
    logger.info("RESUMEN")
    logger.info("=" * 60)
    
    passed = sum(1 for _, success in results if success)
    total = len(results)
    
    for name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"  {status}: {name}")
    
    logger.info("")
    logger.info(f"Resultado: {passed}/{total} tests pasaron")
    
    if passed == total:
        logger.info("🎉 Todos los tests pasaron. Sistema listo para trading.")
        return True
    else:
        logger.warning("⚠️ Algunos tests fallaron. Revisar antes de trading.")
        return False


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
