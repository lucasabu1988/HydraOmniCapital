"""
Backtest Simplificado del AlphaMax Investment Algorithm
Este script ejecuta un backtest básico sin la complejidad del motor completo
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import yaml

from src.data.data_provider import YFinanceProvider
from src.signals.technical import TechnicalSignals, SignalType
from src.signals.fundamental import FundamentalSignals, FundamentalMetrics
from src.signals.composite import CompositeSignalGenerator


def run_simple_backtest(symbols, start_date, end_date, initial_capital=1000000):
    """
    Ejecuta un backtest simplificado
    
    Args:
        symbols: Lista de símbolos
        start_date: Fecha de inicio
        end_date: Fecha de fin
        initial_capital: Capital inicial
    """
    print("=" * 80)
    print("ALPHAMAX INVESTMENT ALGORITHM - BACKTEST SIMPLIFICADO")
    print("=" * 80)
    print(f"Período: {start_date.date()} a {end_date.date()}")
    print(f"Capital Inicial: ${initial_capital:,.2f}")
    print(f"Universo: {', '.join(symbols)}")
    print("=" * 80)
    
    # Inicializar proveedor de datos
    provider = YFinanceProvider()
    
    # Cargar configuración
    with open("config/strategy.yaml", 'r') as f:
        config = yaml.safe_load(f)
    
    # Inicializar generadores de señales
    tech_signals = TechnicalSignals(config['signals'])
    fund_signals = FundamentalSignals(config['signals'])
    
    # Descargar datos históricos
    print("\nDescargando datos históricos...")
    prices = provider.get_historical_prices(symbols, start_date=start_date, end_date=end_date)
    
    if prices.empty:
        print("Error: No se pudieron descargar datos")
        return
    
    print(f"Datos descargados: {prices.shape[0]} días x {prices.shape[1]} símbolos")
    
    # Portafolio
    cash = initial_capital
    positions = {}  # {symbol: {'shares': X, 'entry_price': Y}}
    portfolio_values = []
    trades = []
    
    # Rebalanceo semanal - usar las fechas disponibles en los precios
    available_dates = prices.index
    rebalance_dates = pd.date_range(start=available_dates[0], end=available_dates[-1], freq='W')
    
    print("\nEjecutando backtest...")
    print("-" * 80)
    
    for i, date in enumerate(rebalance_dates):
        # Encontrar la fecha más cercana en los datos
        closest_date = available_dates[available_dates >= date]
        if len(closest_date) == 0:
            continue
        date = closest_date[0]
        
        # Calcular valor actual del portafolio
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in prices.columns and not pd.isna(prices.loc[date, symbol]):
                current_price = prices.loc[date, symbol]
                portfolio_value += pos['shares'] * current_price
        
        portfolio_values.append({
            'date': date,
            'portfolio_value': portfolio_value,
            'cash': cash,
            'num_positions': len(positions)
        })
        
        # Mostrar progreso cada 26 semanas (6 meses)
        if i % 26 == 0:
            print(f"Fecha: {date.date()} | Valor: ${portfolio_value:,.2f} | "
                  f"Posiciones: {len(positions)} | Cash: ${cash:,.2f}")
        
        # Generar señales para cada símbolo
        for symbol in symbols:
            if symbol not in prices.columns:
                continue
            
            symbol_prices = prices[symbol].dropna()
            if len(symbol_prices) < 50:
                continue
            
            current_price = symbol_prices.iloc[-1]
            
            # Verificar si tenemos posición
            if symbol in positions:
                # Verificar stop loss simple del 5%
                entry_price = positions[symbol]['entry_price']
                if current_price <= entry_price * 0.95:  # Stop loss 5%
                    # Vender
                    proceeds = positions[symbol]['shares'] * current_price * 0.999  # comisión
                    cash += proceeds
                    trades.append({
                        'date': date,
                        'symbol': symbol,
                        'action': 'SELL',
                        'shares': positions[symbol]['shares'],
                        'price': current_price,
                        'reason': 'STOP_LOSS'
                    })
                    del positions[symbol]
                continue
            
            # Generar señal técnica
            analysis = tech_signals.analyze_all_signals(symbol, symbol_prices)
            
            # Solo comprar si hay señal de compra fuerte
            if analysis['final_signal'] == SignalType.BUY and analysis['final_strength'] > 0.6:
                # Calcular tamaño de posición (10% del portafolio por posición)
                position_value = min(portfolio_value * 0.10, cash * 0.95)
                
                if position_value > 1000:  # Mínimo $1000
                    shares = int(position_value / current_price)
                    if shares > 0:
                        cost = shares * current_price * 1.001  # comisión
                        if cost <= cash:
                            cash -= cost
                            positions[symbol] = {
                                'shares': shares,
                                'entry_price': current_price
                            }
                            trades.append({
                                'date': date,
                                'symbol': symbol,
                                'action': 'BUY',
                                'shares': shares,
                                'price': current_price
                            })
    
    # Resultados finales
    print("\n" + "=" * 80)
    print("RESULTADOS DEL BACKTEST")
    print("=" * 80)
    
    df_results = pd.DataFrame(portfolio_values)
    
    if df_results.empty:
        print("Error: No se generaron resultados")
        return pd.DataFrame(), trades
    
    final_value = df_results['portfolio_value'].iloc[-1]
    total_return = (final_value - initial_capital) / initial_capital
    
    # Calcular métricas
    df_results['returns'] = df_results['portfolio_value'].pct_change()
    volatility = df_results['returns'].std() * np.sqrt(52)  # Anualizado
    
    # Calcular drawdown
    rolling_max = df_results['portfolio_value'].expanding().max()
    drawdown = (df_results['portfolio_value'] - rolling_max) / rolling_max
    max_drawdown = drawdown.min()
    
    # Sharpe ratio (asumiendo risk-free rate del 2%)
    excess_returns = df_results['returns'].mean() * 52 - 0.02
    sharpe_ratio = excess_returns / (df_results['returns'].std() * np.sqrt(52)) if df_results['returns'].std() > 0 else 0
    
    print(f"\nCapital Inicial:     ${initial_capital:>15,.2f}")
    print(f"Capital Final:       ${final_value:>15,.2f}")
    print(f"Retorno Total:       {total_return:>15.2%}")
    print(f"Retorno Anualizado:  {(1+total_return)**(365/(end_date-start_date).days)-1:>15.2%}")
    print(f"Volatilidad:         {volatility:>15.2%}")
    print(f"Max Drawdown:        {max_drawdown:>15.2%}")
    print(f"Sharpe Ratio:        {sharpe_ratio:>15.2f}")
    
    print(f"\nTotal de Trades: {len(trades)}")
    
    # Calcular win rate
    if len(trades) > 0:
        df_trades = pd.DataFrame(trades)
        sells = df_trades[df_trades['action'] == 'SELL']
        print(f"Trades de Salida: {len(sells)}")
    
    # Gráfico simple de evolución
    print("\n" + "-" * 80)
    print("EVOLUCIÓN DEL PORTAFOLIO (últimos 10 puntos)")
    print("-" * 80)
    
    for _, row in df_results.tail(10).iterrows():
        bar_len = int(row['portfolio_value'] / final_value * 50)
        bar = "█" * bar_len
        print(f"{row['date'].date()} | ${row['portfolio_value']:>12,.2f} | {bar}")
    
    # Guardar resultados
    df_results.to_csv('backtests/backtest_simple_results.csv', index=False)
    print(f"\nResultados guardados en: backtests/backtest_simple_results.csv")
    
    return df_results, trades


if __name__ == '__main__':
    # Configuración
    symbols = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'JPM', 'V', 'JNJ']
    
    # 10 años de backtest
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365*10)
    
    # Ejecutar
    results, trades = run_simple_backtest(symbols, start_date, end_date)
