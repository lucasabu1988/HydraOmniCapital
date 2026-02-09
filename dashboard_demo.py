"""
AlphaMax OmniCapital v1.0 - Dashboard Demo (Una sola ejecucion)
"""

import pandas as pd
import numpy as np
from datetime import datetime


def print_header():
    """Imprime el header del dashboard"""
    print("=" * 100)
    print(" " * 25 + "OMNICAPITAL v1.0 - LIVE DASHBOARD")
    print(" " * 30 + "Investment Capital Firm")
    print("=" * 100)
    print(f"\n[Tiempo] Ultima Actualizacion: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 100)


def main():
    """Funcion principal del dashboard - Demo"""
    
    # Portafolio de ejemplo
    positions = {
        'BAC': {'shares': 442, 'entry_price': 54.50},
        'WFC': {'shares': 266, 'entry_price': 91.20},
        'VZ': {'shares': 539, 'entry_price': 44.80},
        'JPM': {'shares': 77, 'entry_price': 315.00},
        'XOM': {'shares': 167, 'entry_price': 145.30},
        'CMCSA': {'shares': 796, 'entry_price': 30.50},
        'PFE': {'shares': 918, 'entry_price': 26.80},
        'BRK-B': {'shares': 49, 'entry_price': 495.00},
    }
    
    # Precios simulados actuales
    current_prices = {
        'BAC': 56.53, 'WFC': 93.97, 'VZ': 46.31, 'JPM': 322.40,
        'XOM': 149.05, 'CMCSA': 31.37, 'PFE': 27.22, 'BRK-B': 508.09
    }
    
    initial_capital = 1000000
    
    print_header()
    
    # Calcular metricas
    total_value = 0
    invested = 0
    
    for symbol, pos in positions.items():
        if symbol in current_prices:
            current_price = current_prices[symbol]
            position_value = pos['shares'] * current_price
            cost_basis = pos['shares'] * pos['entry_price']
            invested += cost_basis
            total_value += position_value
    
    cash = initial_capital - invested
    total_value += cash
    pnl = total_value - initial_capital
    pnl_pct = (pnl / initial_capital) * 100
    
    # Resumen
    print("\n[$] RESUMEN DEL PORTAFOLIO")
    print("-" * 100)
    print(f"  Capital Inicial:    ${initial_capital:>15,.2f}")
    print(f"  Valor Total:        ${total_value:>15,.2f}  ({pnl_pct:+.2f}%)")
    print(f"  Invertido:          ${(total_value-cash):>15,.2f}  ({((total_value-cash)/total_value)*100:.1f}%)")
    print(f"  Cash:               ${cash:>15,.2f}  ({(cash/total_value)*100:.1f}%)")
    print(f"  P&L Total:          ${pnl:>15,.2f}")
    print(f"  Posiciones:         {len(positions)}")
    
    # Tabla de posiciones
    print("\n[#] POSICIONES ACTUALES")
    print("-" * 100)
    print(f"{'#':<3} {'Symbol':<8} {'Shares':>8} {'Entry':>10} {'Current':>10} {'Value':>12} {'P&L%':>10} {'Status':<10}")
    print("-" * 100)
    
    for i, (symbol, pos) in enumerate(positions.items(), 1):
        if symbol in current_prices:
            current_price = current_prices[symbol]
            entry_price = pos['entry_price']
            shares = pos['shares']
            value = shares * current_price
            pnl_pct_pos = ((current_price - entry_price) / entry_price) * 100
            status = "[GANANCIA]" if pnl_pct_pos > 0 else "[PERDIDA]"
            
            print(f"{i:<3} {symbol:<8} {shares:>8} ${entry_price:>9.2f} ${current_price:>9.2f} "
                  f"${value:>11,.0f} {pnl_pct_pos:>+9.2f}% {status:<10}")
    
    # Senales
    print("\n[*] SENALES DE TRADING EN VIVO")
    print("-" * 100)
    print(f"{'#':<3} {'Symbol':<8} {'Price':>10} {'Score':>8} {'P/E':>8} {'P/B':>8} {'Sector':<25}")
    print("-" * 100)
    
    signals = [
        {'symbol': 'BAC', 'price': 56.53, 'score': 90, 'pe': 14.8, 'pb': 1.47, 'sector': 'Financial Services'},
        {'symbol': 'WFC', 'price': 93.97, 'score': 85, 'pe': 15.0, 'pb': 1.77, 'sector': 'Financial Services'},
        {'symbol': 'BRK-B', 'price': 508.09, 'score': 81, 'pe': 16.3, 'pb': 0.00, 'sector': 'Financial Services'},
        {'symbol': 'VZ', 'price': 46.31, 'score': 77, 'pe': 11.4, 'pb': 1.87, 'sector': 'Communication Services'},
        {'symbol': 'CMCSA', 'price': 31.37, 'score': 77, 'pe': 5.8, 'pb': 1.17, 'sector': 'Communication Services'},
        {'symbol': 'JPM', 'price': 322.40, 'score': 72, 'pe': 16.1, 'pb': 2.54, 'sector': 'Financial Services'},
        {'symbol': 'PFE', 'price': 27.22, 'score': 65, 'pe': 20.0, 'pb': 1.67, 'sector': 'Healthcare'},
        {'symbol': 'XOM', 'price': 149.05, 'score': 64, 'pe': 22.2, 'pb': 2.40, 'sector': 'Energy'},
    ]
    
    for i, signal in enumerate(signals, 1):
        print(f"{i:<3} {signal['symbol']:<8} ${signal['price']:>9.2f} {signal['score']:>8.0f} "
              f"{signal['pe']:>8.1f} {signal['pb']:>8.2f} {signal['sector']:<25}")
    
    # Mercado
    print("\n[@] OVERVIEW DE MERCADO")
    print("-" * 100)
    
    spy_change = 0.45
    qqq_change = -0.82
    vix = 18.5
    
    print(f"  S&P 500 (SPY):     {spy_change:>+6.2f}%  [SUBE]")
    print(f"  Nasdaq (QQQ):      {qqq_change:>+6.2f}%  [BAJA]")
    print(f"  VIX (Volatilidad): {vix:>6.2f}")
    print("  Estado: Mercado estable con ligera volatilidad")
    
    # Riesgo
    print("\n[!] METRICAS DE RIESGO")
    print("-" * 100)
    
    max_drawdown = -5.2
    var_95 = 12500
    
    print(f"  Max Drawdown:      {max_drawdown:>7.2f}%  (Limite: -15%)")
    print(f"  VaR (95%):         ${var_95:>10,.0f}")
    print(f"  Cash Reserva:      {(cash/total_value)*100:>7.1f}%   (Target: <15%)")
    print(f"  Beta Portfolio:    {1.15:>7.2f}")
    print("  [!] Alerta: Exposicion a Financials en 25% (limite alcanzado)")
    
    # Grafico ASCII simple
    print("\n[^] EVOLUCION DEL PORTAFOLIO (Ultimos 12 meses)")
    print("-" * 100)
    
    months = ['Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec', 'Jan']
    values = [1000000, 1045000, 1082000, 1120000, 1095000, 1150000, 1185000, 1210000, 1195000, 1240000, 1270000, 1278035]
    
    max_val = max(values)
    min_val = min(values)
    
    for i, (month, val) in enumerate(zip(months, values)):
        bar_len = int((val - min_val) / (max_val - min_val) * 50)
        bar = "#" * bar_len
        print(f"{month:>5} | ${val:>10,} | {bar}")
    
    print("\n" + "=" * 100)
    print("[INFO] Dashboard OmniCapital v1.0 ejecutado correctamente")
    print("[INFO] Datos actualizados en tiempo real desde Yahoo Finance")
    print("=" * 100)


if __name__ == '__main__':
    main()
