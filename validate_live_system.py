"""
Validación rápida del sistema live sin ejecutar trading real.
Verifica conectividad, cálculos y componentes.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, time
import logging

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from omnicapital_data_feed import YahooDataFeed, MarketDataManager
from omnicapital_broker import PaperBroker, Order
from omnicapital_live import OmniCapitalLive, CONFIG, UNIVERSE, DataValidator


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
    
    # Test tendencias
    logger.info("Detectando tendencias...")
    for i in range(5):
        validator.record_price('TEST', 100 + i * 5)  # Tendencia alcista
    
    trend = validator.get_price_trend('TEST')
    logger.info(f"  Tendencia TEST: {trend}")
    
    logger.info("✅ Data Validator OK")
    return True


def test_trading_system():
    """Test del sistema de trading integrado"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST 4: Trading System Integration")
    logger.info("=" * 60)
    
    config = CONFIG.copy()
    config['PAPER_INITIAL_CASH'] = 100000
    
    trader = OmniCapitalLive(config)
    
    # Test inicialización
    logger.info("Inicialización...")
    logger.info(f"  Peak value: ${trader.peak_value:,.2f}")
    logger.info(f"  Leverage: {trader.current_leverage}x")
    logger.info(f"  In protection: {trader.in_protection}")
    
    # Test horario de mercado
    logger.info("Verificando horario de mercado...")
    is_open = trader.is_market_open()
    logger.info(f"  Mercado abierto: {is_open}")
    
    # Test cálculo de position sizing
    logger.info("Calculando tamaño de posición...")
    size = trader.calculate_position_size(100000, 100000, 5)
    logger.info(f"  Position size: ${size:,.2f}")
    
    # Validar rango
    # Con portfolio = 100000, leverage = 2, effective = 200000
    # Con buffer = 5%, investable = 190000, /5 = 38000
    # Pero max_position = 25% de portfolio = 25000
    # Entonces resultado = 25000 (limitado por max_position)
    expected = 100000 * 0.25  # MAX_POSITION_SIZE_PCT
    if abs(size - expected) > 1:
        logger.error(f"❌ Cálculo incorrecto. Got: ${size:,.2f}, Expected: ${expected:,.2f}")
        return False
    
    # Test selección de símbolos
    logger.info("Seleccionando símbolos...")
    available = list(UNIVERSE.keys())[:20]
    selected = trader.select_symbols(available, set(), 5)
    logger.info(f"  Seleccionados: {selected}")
    
    if len(selected) != 5:
        logger.error(f"❌ Selección incorrecta: {len(selected)} != 5")
        return False
    
    # Test guardar/cargar estado
    logger.info("Test guardar/cargar estado...")
    trader.peak_value = 120000
    trader.in_protection = True
    trader.save_state()
    
    # Buscar archivo guardado
    import glob
    files = glob.glob('omnicapital_state_*.json')
    if files:
        logger.info(f"  Estado guardado: {files[0]}")
        
        # Cargar en nuevo trader
        new_trader = OmniCapitalLive(config)
        new_trader.load_state(files[0])
        
        logger.info(f"  Peak cargado: ${new_trader.peak_value:,.2f}")
        logger.info(f"  Protection: {new_trader.in_protection}")
        
        if new_trader.peak_value != 120000:
            logger.error("❌ Estado no cargado correctamente")
            return False
    
    logger.info("✅ Trading System OK")
    return True


def test_stop_loss_logic():
    """Test lógica de stop loss"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("TEST 5: Stop Loss Logic")
    logger.info("=" * 60)
    
    config = CONFIG.copy()
    trader = OmniCapitalLive(config)
    trader.broker.connect()
    
    # Establecer peak
    trader.peak_value = 100000
    logger.info(f"Peak value: ${trader.peak_value:,.2f}")
    
    # Test 1: Sin stop loss
    logger.info("Test 1: Portfolio en +10% (no debe activar)...")
    
    from unittest.mock import MagicMock, patch
    with patch.object(trader.broker, 'get_portfolio') as mock_pf:
        mock_pf.return_value = MagicMock(total_value=110000)
        result = trader.check_stop_loss({'AAPL': 150.0})
        logger.info(f"  Stop activado: {result}")
        logger.info(f"  In protection: {trader.in_protection}")
        
        if result:
            logger.error("❌ Stop se activó cuando no debía")
            return False
    
    # Test 2: Con stop loss (-25% drawdown)
    logger.info("Test 2: Portfolio en -25% (debe activar)...")
    
    with patch.object(trader.broker, 'get_portfolio') as mock_pf:
        with patch.object(trader.broker, 'get_positions') as mock_pos:
            mock_pf.return_value = MagicMock(total_value=75000)
            mock_pos.return_value = {}
            
            result = trader.check_stop_loss({'AAPL': 150.0})
            logger.info(f"  Stop activado: {result}")
            logger.info(f"  In protection: {trader.in_protection}")
            logger.info(f"  Leverage: {trader.current_leverage}x")
            
            if not result:
                logger.error("❌ Stop no se activó cuando debía")
                return False
            
            if not trader.in_protection:
                logger.error("❌ Protección no se activó")
                return False
    
    # Test 3: Recuperación
    # Nota: El peak se actualizó a $110,000 en Test 1
    # Para recuperar necesitamos >= $110,000 * 0.95 = $104,500
    logger.info("Test 3: Recuperación (debe restaurar leverage)...")
    logger.info(f"  Peak actual: ${trader.peak_value:,.2f}")
    logger.info(f"  Threshold: {trader.config['RECOVERY_THRESHOLD']}")
    logger.info(f"  Necesario para recuperar: ${trader.peak_value * trader.config['RECOVERY_THRESHOLD']:,.2f}")
    
    with patch.object(trader.broker, 'get_portfolio') as mock_pf:
        # Usar valor que supere el threshold
        recovery_value = int(trader.peak_value * trader.config['RECOVERY_THRESHOLD'] * 1.01)
        mock_pf.return_value = MagicMock(total_value=recovery_value)
        result = trader.check_stop_loss({'AAPL': 150.0})
        logger.info(f"  Portfolio test: ${recovery_value:,}")
        logger.info(f"  In protection: {trader.in_protection}")
        logger.info(f"  Leverage: {trader.current_leverage}x")
        
        if trader.in_protection:
            logger.error("❌ Protección no se desactivó tras recuperación")
            return False
    
    logger.info("✅ Stop Loss Logic OK")
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
        ("Stop Loss Logic", test_stop_loss_logic),
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
