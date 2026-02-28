"""
Ejemplo de uso del sistema Multi-Strategy OmniCapital v2.0

Este script demuestra cómo usar las nuevas estrategias avanzadas
de forma individual o combinada.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# Importar estrategias
from src.strategies.momentum import DualMomentumStrategy, RelativeStrengthStrategy
from src.strategies.factor import FactorInvestingStrategy
from src.strategies.risk_parity import RiskParityStrategy, MinimumVarianceStrategy
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.trend_following import TurtleStrategy, DonchianStrategy
from src.strategies.multi_strategy_engine import MultiStrategyEngine

# Importar data provider
from src.data.data_provider import YFinanceProvider


def example_single_strategy():
    """Ejemplo: Usar una sola estrategia"""
    print("=" * 80)
    print("EJEMPLO 1: Estrategia Individual - Dual Momentum")
    print("=" * 80)
    
    # Crear estrategia
    strategy = DualMomentumStrategy({
        'name': 'DualMomentum_Example',
        'lookback_months': 12,
        'top_n': 5,
        'risk_free_rate': 0.02
    })
    
    # Obtener datos
    provider = YFinanceProvider()
    symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'SPY']
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    
    print(f"\nDescargando datos para: {symbols}")
    prices = provider.get_historical_prices(symbols, start_date, end_date)
    
    if prices.empty:
        print("No se pudieron obtener datos")
        return
    
    print(f"Datos descargados: {prices.shape[0]} días x {prices.shape[1]} símbolos")
    
    # Generar señales
    print("\nGenerando señales...")
    signals = strategy.generate_signals(prices)
    
    print(f"\nSeñales generadas: {len(signals)}")
    for signal in signals:
        print(f"  {signal.symbol}: {signal.action} (strength: {signal.strength:.2f})")
        print(f"    Metadata: {signal.metadata}")
    
    # Calcular allocaciones
    allocations = strategy.calculate_allocations(prices, signals)
    
    print(f"\nAllocaciones calculadas:")
    for symbol, alloc in allocations.items():
        print(f"  {symbol}: {alloc.weight:.2%} (confianza: {alloc.confidence:.2f})")
    
    # Performance summary
    summary = strategy.get_performance_summary()
    print(f"\nResumen de performance:")
    for key, value in summary.items():
        print(f"  {key}: {value}")


def example_multi_strategy():
    """Ejemplo: Combinar múltiples estrategias"""
    print("\n" + "=" * 80)
    print("EJEMPLO 2: Multi-Strategy Engine")
    print("=" * 80)
    
    # Crear motor multi-estrategia
    engine = MultiStrategyEngine({
        'ensemble_method': 'weighted',
        'rebalance_frequency': 'monthly'
    })
    
    # Añadir estrategias
    engine.add_strategy('dual_momentum', DualMomentumStrategy({
        'lookback_months': 12,
        'top_n': 5,
        'name': 'DualMomentum'
    }), weight=1.0)
    
    engine.add_strategy('relative_strength', RelativeStrengthStrategy({
        'lookback_months': [3, 6, 12],
        'top_n': 5,
        'name': 'RelativeStrength'
    }), weight=0.8)
    
    engine.add_strategy('factor', FactorInvestingStrategy({
        'top_n': 5,
        'name': 'FactorInvesting'
    }), weight=1.2)
    
    engine.add_strategy('turtle', TurtleStrategy({
        'entry_period': 20,
        'name': 'TurtleTrading'
    }), weight=0.7)
    
    print(f"\nEstrategias cargadas: {list(engine.strategies.keys())}")
    print(f"Pesos: {engine.strategy_weights}")
    
    # Obtener datos
    provider = YFinanceProvider()
    symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'JPM', 'V', 'JNJ']
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365*2)
    
    print(f"\nDescargando datos...")
    prices = provider.get_historical_prices(symbols, start_date, end_date)
    
    if prices.empty:
        print("No se pudieron obtener datos")
        return
    
    # Obtener fundamentales
    print("Obteniendo fundamentales...")
    fundamentals = {}
    for symbol in symbols:
        try:
            info = provider.get_ticker_info(symbol)
            fundamentals[symbol] = {
                'pe_ratio': info.get('trailing_pe'),
                'pb_ratio': info.get('pb_ratio'),
                'roe': info.get('returnOnEquity'),
                'sector': info.get('sector', 'Unknown'),
                'market_cap': info.get('marketCap', 0)
            }
        except:
            pass
    
    # Generar señales compuestas
    print("\nGenerando señales compuestas...")
    composite_signals = engine.generate_composite_signals(prices, fundamentals)
    
    print(f"\nSeñales compuestas: {len(composite_signals)}")
    for signal in sorted(composite_signals, key=lambda x: x.strength, reverse=True)[:10]:
        print(f"  {signal.symbol}: {signal.action} (strength: {signal.strength:.2f})")
        if 'contributing_strategies' in signal.metadata:
            print(f"    Estrategias: {signal.metadata['contributing_strategies']}")
    
    # Detectar régimen
    regime = engine._detect_market_regime(prices)
    print(f"\nRégimen de mercado detectado: {regime}")
    
    # Summary
    summary = engine.get_strategy_summary()
    print(f"\nResumen del motor:")
    print(f"  Método de ensemble: {summary['ensemble_method']}")
    print(f"  Estrategias: {summary['strategies']}")


def example_risk_parity():
    """Ejemplo: Risk Parity y optimización"""
    print("\n" + "=" * 80)
    print("EJEMPLO 3: Risk Parity y Minimum Variance")
    print("=" * 80)
    
    # Obtener datos
    provider = YFinanceProvider()
    symbols = ['SPY', 'QQQ', 'IWM', 'VTI', 'VXUS', 'BND', 'GLD', 'VNQ']
    
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365)
    
    print(f"\nDescargando datos para ETF portfolio...")
    prices = provider.get_historical_prices(symbols, start_date, end_date)
    
    if prices.empty or len(prices) < 50:
        print("Datos insuficientes")
        return
    
    # Risk Parity
    print("\n--- Risk Parity Strategy ---")
    rp_strategy = RiskParityStrategy({
        'vol_target': 0.10,
        'max_weight': 0.30,
        'min_weight': 0.02
    })
    
    rp_allocations = rp_strategy.calculate_allocations(prices, [])
    
    print("Allocaciones Risk Parity:")
    for symbol, alloc in sorted(rp_allocations.items(), key=lambda x: x[1].weight, reverse=True):
        print(f"  {symbol}: {alloc.weight:.2%} (riesgo esperado: {alloc.expected_risk:.2%})")
    
    # Minimum Variance
    print("\n--- Minimum Variance Strategy ---")
    mv_strategy = MinimumVarianceStrategy({
        'long_only': True,
        'max_weight': 0.30
    })
    
    mv_allocations = mv_strategy.calculate_allocations(prices, [])
    
    print("Allocaciones Minimum Variance:")
    for symbol, alloc in sorted(mv_allocations.items(), key=lambda x: x[1].weight, reverse=True):
        print(f"  {symbol}: {alloc.weight:.2%} (riesgo esperado: {alloc.expected_risk:.2%})")
    
    # Comparar volatilidades
    returns = prices.pct_change().dropna()
    
    if rp_allocations and mv_allocations:
        rp_weights = np.array([rp_allocations[s].weight for s in returns.columns if s in rp_allocations])
        mv_weights = np.array([mv_allocations[s].weight for s in returns.columns if s in mv_allocations])
        
        if len(rp_weights) == len(returns.columns) and len(mv_weights) == len(returns.columns):
            cov = returns.cov().values * 252
            
            rp_vol = np.sqrt(np.dot(rp_weights, np.dot(cov, rp_weights)))
            mv_vol = np.sqrt(np.dot(mv_weights, np.dot(cov, mv_weights)))
            
            print(f"\nVolatilidad anualizada estimada:")
            print(f"  Risk Parity: {rp_vol:.2%}")
            print(f"  Min Variance: {mv_vol:.2%}")


def example_regime_detection():
    """Ejemplo: Detección de régimen de mercado"""
    print("\n" + "=" * 80)
    print("EJEMPLO 4: Regime Detection")
    print("=" * 80)
    
    provider = YFinanceProvider()
    
    # Descargar SPY para análisis de mercado
    print("\nDescargando datos de SPY...")
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365*3)
    
    prices = provider.get_historical_prices(['SPY'], start_date, end_date)
    
    if prices.empty:
        print("No se pudieron obtener datos")
        return
    
    # Simular detección en diferentes puntos del tiempo
    print("\nDetección de régimen en diferentes fechas:")
    print("-" * 60)
    
    engine = MultiStrategyEngine({})
    
    # Tomar muestras cada 6 meses
    sample_dates = prices.index[::126]  # Aproximadamente cada 6 meses
    
    for date in sample_dates[-6:]:  # Últimos 3 años
        prices_up_to_date = prices.loc[:date]
        regime = engine._detect_market_regime(prices_up_to_date)
        
        spy_price = prices.loc[date, 'SPY']
        spy_sma50 = prices_up_to_date['SPY'].tail(50).mean()
        
        print(f"{date.date()}: {regime.upper():10} | SPY: ${spy_price:.2f} | vs SMA50: {'+' if spy_price > spy_sma50 else ''}{((spy_price/spy_sma50)-1)*100:.1f}%")


if __name__ == '__main__':
    print("\n" + "=" * 80)
    print("OMNICAPITAL v2.0 - EJEMPLOS DE ESTRATEGIAS AVANZADAS")
    print("=" * 80)
    
    try:
        # Ejecutar ejemplos
        example_single_strategy()
    except Exception as e:
        print(f"\nError en ejemplo 1: {e}")
    
    try:
        example_multi_strategy()
    except Exception as e:
        print(f"\nError en ejemplo 2: {e}")
    
    try:
        example_risk_parity()
    except Exception as e:
        print(f"\nError en ejemplo 3: {e}")
    
    try:
        example_regime_detection()
    except Exception as e:
        print(f"\nError en ejemplo 4: {e}")
    
    print("\n" + "=" * 80)
    print("Ejemplos completados!")
    print("=" * 80)