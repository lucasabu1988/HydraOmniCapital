"""
AlphaMax Investment Algorithm - Main Entry Point
Algoritmo de inversión en equities con maximización de retornos

Uso:
    python src/main.py --mode live      # Trading en vivo
    python src/main.py --mode backtest  # Backtest histórico
    python src/main.py --mode analyze   # Análisis de mercado
"""

import argparse
import yaml
import json
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Añadir src al path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.engine import TradingEngine


def setup_directories():
    """Crea directorios necesarios"""
    directories = ['logs', 'data', 'reports', 'backtests']
    for directory in directories:
        Path(directory).mkdir(exist_ok=True)


def run_live_trading(config_path: str, symbols: list = None):
    """
    Ejecuta trading en vivo/simulado
    
    Args:
        config_path: Ruta al archivo de configuración
        symbols: Lista opcional de símbolos
    """
    print("=" * 80)
    print("ALPHA MAX INVESTMENT ALGORITHM")
    print("Modo: Trading")
    print("=" * 80)
    
    # Inicializar motor
    engine = TradingEngine(config_path)
    
    # Configurar universo
    if symbols:
        engine.initialize_universe(symbols)
    else:
        engine.initialize_universe()
    
    # Ejecutar iteración
    snapshot = engine.run_iteration()
    
    # Guardar reporte
    report = engine.generate_report()
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    with open(f'reports/trading_report_{timestamp}.json', 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    # Mostrar resumen
    print("\n" + "=" * 80)
    print("RESUMEN DE EJECUCIÓN")
    print("=" * 80)
    print(f"Valor del Portafolio: ${snapshot['total_value']:,.2f}")
    print(f"Efectivo: ${snapshot['cash']:,.2f}")
    print(f"Posiciones Activas: {len(snapshot['positions'])}")
    print(f"\nExposición por Sector:")
    for sector, exposure in snapshot['sector_exposure'].items():
        print(f"  {sector}: {exposure:.1%}")
    
    if snapshot['positions']:
        print(f"\nPosiciones Abiertas:")
        for symbol, pos in snapshot['positions'].items():
            print(f"  {symbol}: {pos['shares']} acciones | "
                  f"P&L: {pos['unrealized_pnl_pct']:+.2%} | "
                  f"Peso: {pos['weight']:.1%}")
    
    print(f"\nReporte guardado en: reports/trading_report_{timestamp}.json")
    
    return engine


def run_backtest(
    config_path: str,
    start_date: str,
    end_date: str,
    symbols: list = None
):
    """
    Ejecuta backtest de la estrategia
    
    Args:
        config_path: Ruta al archivo de configuración
        start_date: Fecha de inicio (YYYY-MM-DD)
        end_date: Fecha de fin (YYYY-MM-DD)
        symbols: Lista opcional de símbolos
    """
    print("=" * 80)
    print("ALPHA MAX INVESTMENT ALGORITHM")
    print("Modo: Backtest")
    print("=" * 80)
    
    # Parsear fechas
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    
    # Inicializar motor
    engine = TradingEngine(config_path)
    
    # Configurar universo
    if symbols:
        engine.initialize_universe(symbols)
    else:
        engine.initialize_universe()
    
    # Ejecutar backtest
    results = engine.run_backtest(start, end, rebalance_frequency='W')
    
    # Calcular métricas
    total_return = (results['total_value'].iloc[-1] / results['total_value'].iloc[0]) - 1
    sharpe_ratio = results['returns'].mean() / results['returns'].std() * (252 ** 0.5) if results['returns'].std() != 0 else 0
    
    # Calcular drawdown
    rolling_max = results['total_value'].expanding().max()
    drawdown = (results['total_value'] - rolling_max) / rolling_max
    max_drawdown = drawdown.min()
    
    # Guardar resultados
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    results.to_csv(f'backtests/backtest_results_{timestamp}.csv', index=False)
    
    # Mostrar resultados
    print("\n" + "=" * 80)
    print("RESULTADOS DEL BACKTEST")
    print("=" * 80)
    print(f"Período: {start_date} a {end_date}")
    print(f"Capital Inicial: ${results['total_value'].iloc[0]:,.2f}")
    print(f"Capital Final: ${results['total_value'].iloc[-1]:,.2f}")
    print(f"Retorno Total: {total_return:.2%}")
    if len(results) > 0:
        print(f"Retorno Anualizado: {(1 + total_return) ** (252 / len(results)) - 1:.2%}")
    else:
        print("Retorno Anualizado: N/A (sin resultados)")
    print(f"Sharpe Ratio: {sharpe_ratio:.2f}")
    print(f"Max Drawdown: {max_drawdown:.2%}")
    print(f"Volatilidad: {results['returns'].std() * (252 ** 0.5):.2%}")
    
    print(f"\nResultados guardados en: backtests/backtest_results_{timestamp}.csv")
    
    return results


def run_market_analysis(config_path: str, symbols: list = None):
    """
    Ejecuta análisis de mercado sin trading
    
    Args:
        config_path: Ruta al archivo de configuración
        symbols: Lista opcional de símbolos
    """
    print("=" * 80)
    print("ALPHA MAX INVESTMENT ALGORITHM")
    print("Modo: Análisis de Mercado")
    print("=" * 80)
    
    # Inicializar motor
    engine = TradingEngine(config_path)
    
    # Configurar universo
    if symbols:
        engine.initialize_universe(symbols)
    else:
        engine.initialize_universe()
    
    # Cargar datos
    engine.load_data(lookback_days=90)
    
    # Escanear oportunidades
    opportunities = engine.scan_opportunities()
    
    # Mostrar resultados
    print("\n" + "=" * 80)
    print("TOP 10 OPORTUNIDADES")
    print("=" * 80)
    
    for i, opp in enumerate(opportunities[:10], 1):
        signal = opp['signal']
        print(f"\n{i}. {signal.symbol}")
        print(f"   Acción: {signal.action}")
        print(f"   Confianza: {signal.confidence:.1%}")
        print(f"   Score Técnico: {signal.technical_score:.2f}")
        print(f"   Score Fundamental: {signal.fundamental_score:.2f}")
        print(f"   Precio Actual: ${opp['current_price']:.2f}")
    
    # Guardar análisis
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    analysis_data = [
        {
            'symbol': opp['signal'].symbol,
            'action': opp['signal'].action,
            'confidence': opp['signal'].confidence,
            'technical_score': opp['signal'].technical_score,
            'fundamental_score': opp['signal'].fundamental_score,
            'current_price': opp['current_price']
        }
        for opp in opportunities
    ]
    
    df_analysis = pd.DataFrame(analysis_data)
    df_analysis.to_csv(f'reports/market_analysis_{timestamp}.csv', index=False)
    
    print(f"\nAnálisis guardado en: reports/market_analysis_{timestamp}.csv")
    
    return opportunities


def main():
    parser = argparse.ArgumentParser(
        description='AlphaMax Investment Algorithm',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Trading con configuración por defecto
  python src/main.py --mode live
  
  # Backtest de 2 años
  python src/main.py --mode backtest --start-date 2022-01-01 --end-date 2024-01-01
  
  # Análisis de símbolos específicos
  python src/main.py --mode analyze --symbols AAPL MSFT GOOGL AMZN
        """
    )
    
    parser.add_argument(
        '--mode',
        choices=['live', 'backtest', 'analyze'],
        default='analyze',
        help='Modo de ejecución (default: analyze)'
    )
    
    parser.add_argument(
        '--config',
        default='config/strategy.yaml',
        help='Ruta al archivo de configuración'
    )
    
    parser.add_argument(
        '--start-date',
        default=(datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d'),
        help='Fecha de inicio para backtest (YYYY-MM-DD)'
    )
    
    parser.add_argument(
        '--end-date',
        default=datetime.now().strftime('%Y-%m-%d'),
        help='Fecha de fin para backtest (YYYY-MM-DD)'
    )
    
    parser.add_argument(
        '--symbols',
        nargs='+',
        help='Lista de símbolos para trading/análisis'
    )
    
    args = parser.parse_args()
    
    # Crear directorios
    setup_directories()
    
    # Ejecutar modo
    if args.mode == 'live':
        run_live_trading(args.config, args.symbols)
    elif args.mode == 'backtest':
        run_backtest(args.config, args.start_date, args.end_date, args.symbols)
    elif args.mode == 'analyze':
        run_market_analysis(args.config, args.symbols)


if __name__ == '__main__':
    main()
