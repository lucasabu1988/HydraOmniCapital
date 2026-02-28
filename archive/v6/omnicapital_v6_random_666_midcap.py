"""
AlphaMax OmniCapital v6.0 - MidCap Edition
Random Selection + 666 Minutes Hold Strategy - Including MidCaps

Universe: 80 stocks (40 blue-chips + 40 mid-caps)
- 40 Blue-chips: Top S&P 500 (>$100B)
- 40 Mid-caps: Quality mid-caps ($50B-$100B)

Author: Investment Capital Firm
Version: 6.0.0-MidCap
Date: February 2026
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random

from src.data.data_provider import YFinanceProvider


def get_sp500_with_midcaps():
    """
    Retorna universo de 80 valores:
    - 40 Blue-chips elite (top S&P 500)
    - 40 Mid-caps de calidad ($50B-$100B)
    """
    # 40 Blue-chips elite (los originales que funcionan)
    blue_chips = [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
        'JPM', 'V', 'JNJ', 'UNH', 'XOM', 'WMT', 'PG', 'MA', 'HD', 'CVX',
        'MRK', 'ABBV', 'PEP', 'KO', 'PFE', 'AVGO', 'COST', 'TMO', 'DIS',
        'ABT', 'ADBE', 'BAC', 'ACN', 'WFC', 'CRM', 'VZ', 'DHR', 'NKE',
        'TXN', 'PM', 'NEE', 'AMD'
    ]
    
    # 40 Mid-caps de calidad ($50B-$100B aprox)
    mid_caps = [
        'SPGI', 'UPS', 'UNP', 'IBM', 'QCOM', 'GS', 'CAT', 'SBUX', 'DE', 'LMT',
        'GILD', 'BLK', 'MDT', 'CVS', 'T', 'AMT', 'AXP', 'MS', 'CI', 'ISRG',
        'VRTX', 'SLB', 'C', 'BA', 'PLD', 'NOW', 'MO', 'EL', 'REGN', 'GE',
        'SO', 'HUM', 'NFLX', 'BK', 'DUK', 'TJX', 'CME', 'APD', 'ZTS', 'CL'
    ]
    
    return blue_chips + mid_caps


class Random666MidCapStrategy:
    """
    Estrategia aleatoria con hold maximo de 666 minutos.
    Universo: 80 valores (40 blue-chips + 40 mid-caps).
    """
    
    def __init__(self, seed=42):
        self.top_n = 5          # 5 stocks
        self.max_minutes = 666  # 11.1 horas maximo
        self.random = random.Random(seed)
        
    def select_stocks(self, universe):
        """Seleccionar 5 stocks COMPLETAMENTE ALEATORIOS"""
        if len(universe) < self.top_n:
            return universe
        return self.random.sample(universe, self.top_n)


def run_omnicapital_v6_midcap(start_date, end_date, initial_capital=100000):
    """
    Backtest aleatorio con hold maximo de 666 minutos.
    Universo: 80 valores (blue-chips + mid-caps).
    """
    print("=" * 95)
    print("ALPHAMAX OMNICAPITAL v6.0 - MIDCAP EDITION")
    print("Random Selection + 666 Minutes Hold - 80 Stocks (40 Blue + 40 Mid)")
    print("=" * 95)
    print(f"Periodo: {start_date.date()} a {end_date.date()}")
    print(f"Capital Inicial: ${initial_capital:,.2f}")
    print("=" * 95)
    
    symbols = get_sp500_with_midcaps()
    print(f"\nUniverso: {len(symbols)} acciones")
    print(f"  - 40 Blue-chips (>$100B)")
    print(f"  - 40 Mid-caps ($50B-$100B)")
    print(f"Seleccion: 5 ALEATORIOS cada dia")
    print(f"Hold: Maximo {666} minutos (11.1 horas)")
    
    provider = YFinanceProvider()
    print("\nDescargando datos...")
    prices = provider.get_historical_prices(symbols, start_date=start_date, end_date=end_date)
    
    if prices.empty:
        print("Error: No se pudieron descargar datos")
        return
    
    # Filtrar columnas con datos validos (>50% de datos no nulos)
    valid_columns = prices.columns[prices.notna().mean() > 0.5]
    prices = prices[valid_columns]
    
    print(f"Datos validos: {prices.shape[0]} dias x {prices.shape[1]} simbolos")
    print(f"Descartados: {len(symbols) - prices.shape[1]} simbolos con datos insuficientes")
    
    # Inicializar estrategia
    strategy = Random666MidCapStrategy(seed=42)
    
    # Estado
    cash = initial_capital
    positions = {}
    portfolio_values = []
    trades = []
    
    available_dates = prices.index
    
    print("\n" + "=" * 95)
    print("EJECUTANDO BACKTEST - RANDOM 666 MIDCAP")
    print("=" * 95)
    
    for i, current_date in enumerate(available_dates):
        # Calcular valor del portafolio
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in prices.columns and not pd.isna(prices.loc[current_date, symbol]):
                current_price = prices.loc[current_date, symbol]
                portfolio_value += pos['shares'] * current_price
        
        # === VENDER POSICIONES CON >= 666 MINUTOS ===
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            minutes_held = (current_date - pos['entry_datetime']).total_seconds() / 60
            
            if minutes_held >= strategy.max_minutes or current_date >= pos['exit_datetime']:
                if symbol in prices.columns and not pd.isna(prices.loc[current_date, symbol]):
                    current_price = prices.loc[current_date, symbol]
                    proceeds = pos['shares'] * current_price * 0.999
                    cash += proceeds
                    
                    pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
                    
                    trades.append({
                        'date': current_date,
                        'symbol': symbol,
                        'action': 'SELL_666',
                        'shares': pos['shares'],
                        'price': current_price,
                        'proceeds': proceeds,
                        'pnl_pct': pnl_pct,
                        'minutes_held': minutes_held
                    })
                    
                    del positions[symbol]
        
        # === COMPRAR NUEVAS POSICIONES ===
        is_new_day = (i == 0 or current_date.date() != available_dates[i-1].date())
        
        if is_new_day and cash > initial_capital * 0.1:
            available_symbols = [s for s in prices.columns if s not in positions]
            if len(available_symbols) >= strategy.top_n:
                selected = strategy.select_stocks(available_symbols)
                
                print(f"\n[{current_date.date()}] Random pick: {selected}")
                
                cash_per_stock = (cash * 0.95) / len(selected)
                
                for symbol in selected:
                    if symbol in positions:
                        continue
                    
                    if symbol not in prices.columns:
                        continue
                    
                    current_price = prices.loc[current_date, symbol]
                    if pd.isna(current_price) or current_price <= 0:
                        continue
                    
                    shares = int(cash_per_stock / (current_price * 1.001))
                    
                    if shares > 0:
                        cost = shares * current_price * 1.001
                        if cost <= cash:
                            cash -= cost
                            
                            exit_datetime = current_date + timedelta(minutes=666)
                            
                            positions[symbol] = {
                                'shares': shares,
                                'entry_datetime': current_date,
                                'entry_price': current_price,
                                'exit_datetime': exit_datetime
                            }
                            
                            trades.append({
                                'date': current_date,
                                'symbol': symbol,
                                'action': 'BUY_RANDOM',
                                'shares': shares,
                                'price': current_price,
                                'cost': cost,
                                'planned_exit': exit_datetime
                            })
        
        # Registrar valor
        portfolio_values.append({
            'date': current_date,
            'portfolio_value': portfolio_value,
            'cash': cash,
            'num_positions': len(positions)
        })
        
        # Mostrar progreso cada 6 meses
        if i % 126 == 0 and i > 0:
            print(f"[{current_date.date()}] Valor: ${portfolio_value:>12,.2f} | "
                  f"Pos: {len(positions):2} | Cash: ${cash:>10,.2f}")
    
    # === RESULTADOS ===
    print("\n" + "=" * 95)
    print("OMNICAPITAL v6.0 MIDCAP - RESULTADOS (RANDOM 666)")
    print("=" * 95)
    
    df_results = pd.DataFrame(portfolio_values)
    
    if df_results.empty:
        print("Error: No se generaron resultados")
        return
    
    final_value = df_results['portfolio_value'].iloc[-1]
    total_return = (final_value - initial_capital) / initial_capital
    years = len(df_results) / 252
    
    # Metricas
    df_results['returns'] = df_results['portfolio_value'].pct_change()
    volatility = df_results['returns'].std() * np.sqrt(252)
    
    rolling_max = df_results['portfolio_value'].expanding().max()
    drawdown = (df_results['portfolio_value'] - rolling_max) / rolling_max
    max_drawdown = drawdown.min()
    
    sharpe = (df_results['returns'].mean() * 252 - 0.02) / (df_results['returns'].std() * np.sqrt(252)) if df_results['returns'].std() > 0 else 0
    
    print(f"\n>> CAPITAL")
    print(f"   Inicial:              ${initial_capital:>15,.2f}")
    print(f"   Final:                ${final_value:>15,.2f}")
    print(f"   P/L ($):              ${final_value - initial_capital:>+15,.2f}")
    print(f"   Retorno Total:        {total_return:>15.2%}")
    if years > 0:
        print(f"   Anos:                 {years:>15.1f}")
        print(f"   CAGR:                 {(1+total_return)**(1/years)-1:>15.2%}")
    
    print(f"\n>> RIESGO")
    print(f"   Volatilidad:          {volatility:>15.2%}")
    print(f"   Max Drawdown:         {max_drawdown:>15.2%}")
    print(f"   Sharpe Ratio:         {sharpe:>15.2f}")
    
    print(f"\n>> ACTIVIDAD")
    print(f"   Total Trades:         {len(trades):>15}")
    
    if trades:
        df_trades = pd.DataFrame(trades)
        buys = len(df_trades[df_trades['action'] == 'BUY_RANDOM'])
        sells = len(df_trades[df_trades['action'] == 'SELL_666'])
        print(f"   Compras:              {buys:>15}")
        print(f"   Ventas:               {sells:>15}")
        
        if 'pnl_pct' in df_trades.columns:
            valid_pnls = df_trades[df_trades['pnl_pct'].notna()]
            if len(valid_pnls) > 0:
                win_rate = (valid_pnls['pnl_pct'] > 0).mean()
                avg_pnl = valid_pnls['pnl_pct'].mean()
                
                print(f"\n>> PERFORMANCE")
                print(f"   Win Rate:             {win_rate:>15.1%}")
                print(f"   P/L Promedio:         {avg_pnl:>15.2%}")
    
    # Comparacion
    print(f"\n>> COMPARACION")
    print("-" * 60)
    print(f"   Version              Universo      CAGR Esperado")
    print(f"   Standard             40 stocks     17.55%")
    print(f"   MidCap               80 stocks     ?")
    print(f"   Extended             150 stocks    -8.46%")
    
    # Evolucion
    print(f"\n>> EVOLUCION")
    print("-" * 60)
    sample = df_results.iloc[::max(1, len(df_results)//10)]
    for _, row in sample.iterrows():
        print(f"{row['date'].date()} | ${row['portfolio_value']:>13,.2f} | {row['num_positions']:2} pos")
    
    # Guardar
    df_results.to_csv('backtests/backtest_v6_random_666_midcap_results.csv', index=False)
    if trades:
        pd.DataFrame(trades).to_csv('backtests/trades_v6_random_666_midcap.csv', index=False)
    
    print(f"\n>> Archivos guardados:")
    print(f"   - backtests/backtest_v6_random_666_midcap_results.csv")
    print(f"   - backtests/trades_v6_random_666_midcap.csv")
    
    return df_results, trades


if __name__ == '__main__':
    end_date = datetime.now()
    start_date = datetime(2000, 1, 1)
    
    print(f"Backtest: {start_date.date()} a {end_date.date()}")
    print(f"\n>>> ESTRATEGIA: RANDOM 666 + MIDCAPS <<<")
    print(f">>> UNIVERSO: 80 VALORES (40 BLUE + 40 MID) <<<")
    print()
    
    results, trades = run_omnicapital_v6_midcap(start_date, end_date)
