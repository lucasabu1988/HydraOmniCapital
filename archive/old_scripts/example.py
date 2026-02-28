"""
Ejemplo de uso del AlphaMax Investment Algorithm
Este script demuestra cómo usar el algoritmo paso a paso
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from src.core.engine import TradingEngine


def demo_analyze_market():
    """
    Demo: Analizar el mercado y mostrar las mejores oportunidades
    """
    print("=" * 80)
    print("DEMO: Análisis de Mercado")
    print("=" * 80)
    
    # Inicializar el motor
    engine = TradingEngine("config/strategy.yaml")
    
    # Definir universo pequeño para el demo (en producción usarías el S&P 500 completo)
    symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'JPM', 'V', 'JNJ']
    
    print(f"\n1. Inicializando universo con {len(symbols)} símbolos...")
    engine.initialize_universe(symbols)
    
    print("\n2. Cargando datos de mercado...")
    engine.load_data(lookback_days=90)
    
    print(f"\n3. Universo filtrado: {len(engine.universe)} símbolos válidos")
    print(f"   Régimen de mercado: {engine.market_regime}")
    
    print("\n4. Escaneando oportunidades...")
    opportunities = engine.scan_opportunities()
    
    print(f"\n5. Top 5 Oportunidades Encontradas:")
    print("-" * 80)
    
    for i, opp in enumerate(opportunities[:5], 1):
        signal = opp['signal']
        print(f"\n{i}. {signal.symbol}")
        print(f"   Acción Recomendada: {signal.action}")
        print(f"   Confianza: {signal.confidence:.1%}")
        print(f"   Score Técnico: {signal.technical_score:.2f}/1.0")
        print(f"   Score Fundamental: {signal.fundamental_score:.2f}/1.0")
        print(f"   Precio Actual: ${opp['current_price']:.2f}")
        
        if opp['fundamental']:
            fund = opp['fundamental']
            print(f"   P/E Ratio: {fund.pe_ratio:.2f}" if fund.pe_ratio else "   P/E Ratio: N/A")
            print(f"   ROE: {fund.roe:.1%}" if fund.roe else "   ROE: N/A")
    
    return engine, opportunities


def demo_portfolio_simulation():
    """
    Demo: Simular operaciones de portafolio
    """
    print("\n" + "=" * 80)
    print("DEMO: Simulación de Portafolio")
    print("=" * 80)
    
    engine = TradingEngine("config/strategy.yaml")
    symbols = ['AAPL', 'MSFT', 'GOOGL', 'NVDA']
    
    engine.initialize_universe(symbols)
    engine.load_data(lookback_days=90)
    
    print(f"\nCapital Inicial: ${engine.portfolio.initial_capital:,.2f}")
    print(f"Efectivo Inicial: ${engine.portfolio.cash:,.2f}")
    
    # Escanear oportunidades
    opportunities = engine.scan_opportunities()
    
    print(f"\nAbriendo posiciones iniciales...")
    
    # Abrir algunas posiciones de ejemplo
    positions_opened = 0
    for opp in opportunities[:3]:
        if positions_opened >= 3:
            break
            
        signal = opp['signal']
        position_params = engine.evaluate_new_position(
            signal.symbol,
            opp['current_price'],
            opp['fundamental']
        )
        
        if position_params:
            engine.open_position(position_params)
            positions_opened += 1
            print(f"   ✓ {signal.symbol}: {position_params['shares']} acciones @ ${position_params['entry_price']:.2f}")
            print(f"     Stop Loss: ${position_params['stop_loss']:.2f}")
            print(f"     Take Profit: ${position_params['take_profit']:.2f}")
    
    # Mostrar estado del portafolio
    print(f"\nEstado del Portafolio:")
    print("-" * 80)
    
    snapshot = engine.portfolio.snapshot()
    print(f"Valor Total: ${snapshot['total_value']:,.2f}")
    print(f"Efectivo: ${snapshot['cash']:,.2f}")
    print(f"Invertido: ${snapshot['metrics']['invested']:,.2f}")
    print(f"Posiciones Abiertas: {len(snapshot['positions'])}")
    
    if snapshot['positions']:
        print(f"\nDetalle de Posiciones:")
        for symbol, pos in snapshot['positions'].items():
            print(f"   {symbol}: {pos['shares']} acciones | "
                  f"P&L: {pos['unrealized_pnl_pct']:+.2%} | "
                  f"Peso: {pos['weight']:.1%}")
    
    print(f"\nExposición por Sector:")
    for sector, exposure in snapshot['sector_exposure'].items():
        print(f"   {sector}: {exposure:.1%}")
    
    return engine


def demo_risk_management():
    """
    Demo: Mostrar características de gestión de riesgo
    """
    print("\n" + "=" * 80)
    print("DEMO: Gestión de Riesgo")
    print("=" * 80)
    
    engine = TradingEngine("config/strategy.yaml")
    
    print("\n1. Parámetros de Riesgo Configurados:")
    print("-" * 80)
    
    risk_config = engine.config['risk_management']
    print(f"   Stop Loss Method: {risk_config['stop_loss']['method']}")
    print(f"   ATR Multiplier: {risk_config['stop_loss']['atr_multiplier']}")
    print(f"   Trailing Stop: {risk_config['stop_loss']['trailing']}")
    print(f"   Risk/Reward Ratio: {risk_config['take_profit']['risk_reward_ratio']}")
    print(f"   Partial Exit: {risk_config['take_profit']['partial_exit']['enabled']}")
    
    print("\n2. Niveles de Take Profit Parcial:")
    print("-" * 80)
    for level in risk_config['take_profit']['partial_exit']['levels']:
        print(f"   A {level['percent']:.0%} del target: cerrar {level['close']:.0%} de la posición")
    
    print("\n3. Límites de Posición:")
    print("-" * 80)
    capital_config = engine.config['capital']
    print(f"   Máximo número de posiciones: {capital_config['max_portfolio_positions']}")
    print(f"   Tamaño máximo por posición: {capital_config['max_position_size']:.0%}")
    print(f"   Exposición máxima por sector: {capital_config['max_sector_exposure']:.0%}")
    print(f"   Buffer de efectivo: {capital_config['cash_buffer']:.0%}")
    
    print("\n4. Objetivos de Retorno:")
    print("-" * 80)
    objectives = engine.config['objectives']
    print(f"   Retorno anual objetivo: {objectives['target_annual_return']:.0%}")
    print(f"   Máximo drawdown permitido: {objectives['max_drawdown']:.0%}")
    print(f"   Sharpe ratio mínimo: {objectives['sharpe_ratio_min']}")
    print(f"   Volatilidad objetivo: {objectives['volatility_target']:.0%}")


def print_usage_examples():
    """
    Imprime ejemplos de uso de la línea de comandos
    """
    print("\n" + "=" * 80)
    print("EJEMPLOS DE USO CON LINEA DE COMANDOS")
    print("=" * 80)
    
    print("""
1. Análisis de mercado completo (S&P 500):
   
   python src/main.py --mode analyze

2. Análisis de símbolos específicos:
   
   python src/main.py --mode analyze --symbols AAPL MSFT GOOGL AMZN NVDA

3. Trading en vivo/simulado:
   
   python src/main.py --mode live

4. Backtest de 2 años:
   
   python src/main.py --mode backtest --start-date 2022-01-01 --end-date 2024-01-01

5. Backtest con universo personalizado:
   
   python src/main.py --mode backtest \\
       --start-date 2022-01-01 \\
       --end-date 2024-01-01 \\
       --symbols AAPL MSFT GOOGL AMZN META TSLA NVDA
    """)


if __name__ == '__main__':
    print("\n" + "=" * 80)
    print("ALPHAMAX INVESTMENT ALGORITHM - DEMOSTRACIÓN")
    print("Algoritmo financiero para maximización de retornos")
    print("=" * 80)
    
    try:
        # Demo 1: Análisis de mercado
        engine, opportunities = demo_analyze_market()
        
        # Demo 2: Simulación de portafolio
        # engine_portfolio = demo_portfolio_simulation()
        
        # Demo 3: Gestión de riesgo
        demo_risk_management()
        
        # Ejemplos de uso
        print_usage_examples()
        
        print("\n" + "=" * 80)
        print("Demostración completada exitosamente!")
        print("=" * 80)
        print("\nPara ejecutar el algoritmo completo, usa:")
        print("  python src/main.py --mode analyze")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Error durante la demostración: {e}")
        import traceback
        traceback.print_exc()
