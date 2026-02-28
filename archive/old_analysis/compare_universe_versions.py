"""
Comparacion: OmniCapital v6 Standard (40 stocks) vs Universal (~500 stocks)
"""

import pandas as pd
import numpy as np
from datetime import datetime


def calculate_metrics(df_results, initial_capital=100000):
    """Calcula metricas de performance"""
    if df_results.empty:
        return {}
    
    final_value = df_results['portfolio_value'].iloc[-1]
    total_return = (final_value - initial_capital) / initial_capital
    years = len(df_results) / 252
    
    df_results['returns'] = df_results['portfolio_value'].pct_change()
    volatility = df_results['returns'].std() * np.sqrt(252)
    
    rolling_max = df_results['portfolio_value'].expanding().max()
    drawdown = (df_results['portfolio_value'] - rolling_max) / rolling_max
    max_drawdown = drawdown.min()
    
    sharpe = (df_results['returns'].mean() * 252 - 0.02) / (df_results['returns'].std() * np.sqrt(252)) if df_results['returns'].std() > 0 else 0
    
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
    
    return {
        'cagr': cagr,
        'volatility': volatility,
        'max_drawdown': max_drawdown,
        'sharpe': sharpe,
        'final_value': final_value,
        'total_return': total_return
    }


def compare_versions():
    """Compara las versiones Standard vs Universal"""
    print("=" * 95)
    print("COMPARACION: OMNICAPITAL v6 STANDARD vs UNIVERSAL")
    print("=" * 95)
    
    # Cargar resultados standard
    try:
        df_standard = pd.read_csv('backtests/backtest_v6_random_666_results.csv')
        df_standard['date'] = pd.to_datetime(df_standard['date'])
        metrics_std = calculate_metrics(df_standard)
        print("\n✓ Resultados Standard cargados")
    except Exception as e:
        print(f"\n✗ Error cargando resultados Standard: {e}")
        metrics_std = None
    
    # Cargar resultados universal
    try:
        df_universal = pd.read_csv('backtests/backtest_v6_random_666_universal_results.csv')
        df_universal['date'] = pd.to_datetime(df_universal['date'])
        metrics_univ = calculate_metrics(df_universal)
        print("✓ Resultados Universal cargados")
    except Exception as e:
        print(f"✗ Error cargando resultados Universal: {e}")
        metrics_univ = None
    
    if metrics_std and metrics_univ:
        print("\n" + "=" * 95)
        print("RESULTADOS COMPARATIVOS")
        print("=" * 95)
        print(f"\n{'Metrica':<25} {'Standard (40)':>20} {'Universal (~500)':>20} {'Diferencia':>20}")
        print("-" * 95)
        
        metrics = ['cagr', 'volatility', 'max_drawdown', 'sharpe', 'total_return']
        for metric in metrics:
            std_val = metrics_std.get(metric, 0)
            univ_val = metrics_univ.get(metric, 0)
            diff = univ_val - std_val
            
            if metric in ['cagr', 'volatility', 'max_drawdown', 'total_return']:
                print(f"{metric:<25} {std_val:>19.2%} {univ_val:>19.2%} {diff:>+19.2%}")
            else:
                print(f"{metric:<25} {std_val:>19.2f} {univ_val:>19.2f} {diff:>+19.2f}")
        
        print("\n" + "=" * 95)
        print("ANALISIS")
        print("=" * 95)
        
        if metrics_univ['cagr'] > metrics_std['cagr']:
            print("\n✓ Universal supera en CAGR")
            print(f"  Mejora: +{(metrics_univ['cagr'] - metrics_std['cagr'])*100:.2f} puntos porcentuales")
        else:
            print("\n✗ Universal tiene menor CAGR")
            print(f"  Diferencia: {(metrics_univ['cagr'] - metrics_std['cagr'])*100:.2f} puntos porcentuales")
        
        if abs(metrics_univ['max_drawdown']) < abs(metrics_std['max_drawdown']):
            print("\n✓ Universal tiene menor drawdown (mejor)")
        else:
            print("\n✗ Universal tiene mayor drawdown")
        
        if metrics_univ['sharpe'] > metrics_std['sharpe']:
            print("\n✓ Universal tiene mejor Sharpe ratio")
        else:
            print("\n✗ Universal tiene peor Sharpe ratio")
        
        print("\n" + "=" * 95)
        print("CONCLUSION")
        print("=" * 95)
        
        if metrics_univ['cagr'] > metrics_std['cagr'] and metrics_univ['sharpe'] > metrics_std['sharpe']:
            print("\n>>> El universo ampliado (~500) SUPERIOR al estandar (40)")
            print("    La mayor diversificacion reduce el riesgo idiosincratico.")
        elif metrics_univ['cagr'] > metrics_std['cagr']:
            print("\n>>> El universo ampliado tiene MAYOR RETORNO pero peor riesgo-ajustado")
        else:
            print("\n>>> El universo estandar (40) es SUPERIOR al ampliado (~500)")
            print("    Posibles razones:")
            print("    - Los 40 blue-chips capturan mejor el overnight premium")
            print("    - Mayor liquidez en los blue-chips")
            print("    - Los 500 incluyen valores de menor calidad")
    
    elif metrics_std:
        print("\n>> Solo disponibles resultados Standard")
        print(f"   CAGR: {metrics_std['cagr']:.2%}")
        print(f"   Sharpe: {metrics_std['sharpe']:.2f}")
        print("\n   Ejecuta primero: python omnicapital_v6_random_666_universal.py")
    
    elif metrics_univ:
        print("\n>> Solo disponibles resultados Universal")
        print(f"   CAGR: {metrics_univ['cagr']:.2%}")
        print(f"   Sharpe: {metrics_univ['sharpe']:.2f}")
    
    else:
        print("\n>> No hay resultados disponibles.")
        print("   Ejecuta primero los backtests:")
        print("   - python omnicapital_v6_random_666.py")
        print("   - python omnicapital_v6_random_666_universal.py")


if __name__ == '__main__':
    compare_versions()
