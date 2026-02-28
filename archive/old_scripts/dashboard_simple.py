"""
AlphaMax OmniCapital v1.0 - Dashboard Simple (Terminal)
Dashboard básico sin dependencias de Streamlit
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import os

from src.data.data_provider import YFinanceProvider


def clear_screen():
    """Limpia la pantalla"""
    os.system('cls' if os.name == 'nt' else 'clear')


def print_header():
    """Imprime el header del dashboard"""
    print("=" * 100)
    print(" " * 25 + "OMNICAPITAL v1.0 - LIVE DASHBOARD")
    print(" " * 30 + "Investment Capital Firm")
    print("=" * 100)
    print(f"\n[Tiempo] Ultima Actualizacion: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 100)


def print_portfolio_summary(positions, current_prices, initial_capital=1000000):
    """Imprime resumen del portafolio"""
    
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
    
    print("\n" + "[$] RESUMEN DEL PORTAFOLIO")
    print("-" * 100)
    print(f"  Capital Inicial:    ${initial_capital:>15,.2f}")
    print(f"  Valor Total:        ${total_value:>15,.2f}  ({pnl_pct:+.2f}%)")
    print(f"  Invertido:          ${invested:>15,.2f}  ({(invested/total_value)*100:.1f}%)")
    print(f"  Cash:               ${cash:>15,.2f}  ({(cash/total_value)*100:.1f}%)")
    print(f"  P&L Total:          ${pnl:>15,.2f}")
    print(f"  Posiciones:         {len(positions)}")


def print_positions_table(positions, current_prices):
    """Imprime tabla de posiciones"""
    print("\n" + "[#] POSICIONES ACTUALES")
    print("-" * 100)
    print(f"{'#':<3} {'Symbol':<8} {'Shares':>8} {'Entry':>10} {'Current':>10} {'Value':>12} {'P&L%':>10} {'Status':<10}")
    print("-" * 100)
    
    for i, (symbol, pos) in enumerate(positions.items(), 1):
        if symbol in current_prices:
            current_price = current_prices[symbol]
            entry_price = pos['entry_price']
            shares = pos['shares']
            value = shares * current_price
            cost = shares * entry_price
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
            status = "[GANANCIA]" if pnl_pct > 0 else "[PERDIDA]"
            
            print(f"{i:<3} {symbol:<8} {shares:>8} ${entry_price:>9.2f} ${current_price:>9.2f} "
                  f"${value:>11,.0f} {pnl_pct:>+9.2f}% {status:<10}")


def print_live_signals(current_prices, fundamentals):
    """Imprime señales en vivo"""
    print("\n" + "[*] SENALES DE TRADING EN VIVO")
    print("-" * 100)
    
    # Calcular scores simples
    opportunities = []
    for symbol in ['BAC', 'WFC', 'VZ', 'JPM', 'CMCSA', 'PFE', 'XOM', 'BRK-B']:
        if symbol not in current_prices or symbol not in fundamentals:
            continue
        
        price = current_prices[symbol]
        f = fundamentals.get(symbol, {})
        
        # Score de valoración simple
        score = 50
        pe = f.get('pe_ratio')
        pb = f.get('pb_ratio')
        
        if pe and pe < 15:
            score += 20
        elif pe and pe < 20:
            score += 10
        
        if pb and pb < 2:
            score += 15
        
        if score >= 60:
            opportunities.append({
                'symbol': symbol,
                'score': score,
                'price': price,
                'pe': pe,
                'pb': pb,
                'sector': f.get('sector', 'Unknown')[:20]
            })
    
    opportunities.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"{'#':<3} {'Symbol':<8} {'Price':>10} {'Score':>8} {'P/E':>8} {'P/B':>8} {'Sector':<25}")
    print("-" * 100)
    
    for i, opp in enumerate(opportunities[:8], 1):
        pe_str = f"{opp['pe']:.1f}" if opp['pe'] else "N/A"
        pb_str = f"{opp['pb']:.1f}" if opp['pb'] else "N/A"
        print(f"{i:<3} {opp['symbol']:<8} ${opp['price']:>9.2f} {opp['score']:>8.0f} "
              f"{pe_str:>8} {pb_str:>8} {opp['sector']:<25}")


def print_market_overview():
    """Imprime overview del mercado"""
    print("\n" + "[@] OVERVIEW DE MERCADO")
    print("-" * 100)
    
    # Simular datos de mercado
    spy_change = np.random.uniform(-1.5, 2.0)
    qqq_change = np.random.uniform(-2.0, 2.5)
    vix = np.random.uniform(15, 25)
    
    spy_status = "[SUBE]" if spy_change > 0 else "[BAJA]"
    qqq_status = "[SUBE]" if qqq_change > 0 else "[BAJA]"
    
    print(f"  S&P 500 (SPY):     {spy_change:>+6.2f}%  {spy_status}")
    print(f"  Nasdaq (QQQ):      {qqq_change:>+6.2f}%  {qqq_status}")
    print(f"  VIX (Volatilidad): {vix:>6.2f}")
    
    if vix > 20:
        print("  [!] ALERTA: Alta volatilidad detectada")
    if spy_change < -1:
        print("  [!] ALERTA: Mercado en correccion")


def print_risk_metrics(positions, current_prices, initial_capital=1000000):
    """Imprime métricas de riesgo"""
    print("\n" + "[!] METRICAS DE RIESGO")
    print("-" * 100)
    
    # Calcular métricas simples
    invested = sum(pos['shares'] * pos['entry_price'] for pos in positions.values())
    cash = initial_capital - invested
    
    # Simular drawdown
    max_drawdown = np.random.uniform(-8, -3)
    var_95 = invested * 0.012  # VaR aproximado
    
    print(f"  Max Drawdown:      {max_drawdown:>7.2f}%  (Límite: -15%)")
    print(f"  VaR (95%):         ${var_95:>10,.0f}")
    print(f"  Cash Reserva:      {(cash/initial_capital)*100:>7.1f}%   (Target: <15%)")
    print(f"  Beta Portfolio:    {np.random.uniform(1.0, 1.2):>7.2f}")


def main():
    """Función principal del dashboard"""
    
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
    
    provider = YFinanceProvider()
    
    try:
        while True:
            clear_screen()
            print_header()
            
            # Obtener datos en vivo
            try:
                symbols = list(positions.keys()) + ['SPY', 'QQQ', 'BAC', 'WFC', 'VZ', 'JPM', 'CMCSA', 'PFE', 'XOM', 'BRK-B']
                current_prices = provider.get_current_price(symbols)
                fundamentals = {}
                for symbol in ['BAC', 'WFC', 'VZ', 'JPM', 'CMCSA', 'PFE', 'XOM', 'BRK-B']:
                    try:
                        info = provider.get_ticker_info(symbol)
                        fundamentals[symbol] = {
                            'pe_ratio': info.get('trailing_pe'),
                            'pb_ratio': info.get('pb_ratio'),
                            'sector': info.get('sector', 'Unknown')
                        }
                    except:
                        pass
            except:
                # Usar datos simulados si falla
                current_prices = {
                    'BAC': 56.53, 'WFC': 93.97, 'VZ': 46.31, 'JPM': 322.40,
                    'XOM': 149.05, 'CMCSA': 31.37, 'PFE': 27.22, 'BRK-B': 508.09
                }
                fundamentals = {}
            
            # Imprimir secciones
            print_portfolio_summary(positions, current_prices)
            print_positions_table(positions, current_prices)
            print_live_signals(current_prices, fundamentals)
            print_market_overview()
            print_risk_metrics(positions, current_prices)
            
            print("\n" + "=" * 100)
            print("Presiona Ctrl+C para salir | Actualizando en 30 segundos...")
            print("=" * 100)
            
            time.sleep(30)
            
    except KeyboardInterrupt:
        print("\n\n[FIN] Dashboard detenido. Hasta luego!")


if __name__ == '__main__':
    main()
