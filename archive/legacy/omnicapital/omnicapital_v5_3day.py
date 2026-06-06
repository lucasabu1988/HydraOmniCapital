"""
AlphaMax OmniCapital v5.0
3-Day Hold Strategy - Ultra Simple

Copyright (c) 2026 Investment Capital Firm
All Rights Reserved.

Official Release: OmniCapital v5.0
Strategy: Buy and Sell after exactly 3 days
Universe: 40 Blue-Chip S&P 500 Equities

Author: Investment Capital Firm
Version: 5.0.0
Date: February 2026

REGLAS ULTRA-SIMPLES:
1. Cada día, seleccionar los 5 stocks con mayor momentum de 5 días
2. Comprar al open del día siguiente
3. Vender exactamente a los 3 días (72 horas después)
4. Sin stops, sin targets, sin filtros
5. 100% mecánico, 0% discreción
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from src.data.data_provider import YFinanceProvider


def get_sp500_top40():
    """Retorna 40 mayores acciones"""
    return [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
        'JPM', 'V', 'JNJ', 'UNH', 'XOM', 'WMT', 'PG', 'MA', 'HD', 'CVX',
        'MRK', 'ABBV', 'PEP', 'KO', 'PFE', 'AVGO', 'COST', 'TMO', 'DIS',
        'ABT', 'ADBE', 'BAC', 'ACN', 'WFC', 'CRM', 'VZ', 'DHR', 'NKE',
        'TXN', 'PM', 'NEE', 'AMD'
    ]


class ThreeDayStrategy:
    """
    Estrategia ultra-simple: comprar y vender a los 3 días.
    
    REGLAS:
    1. Seleccionar top 5 por momentum 5 días
    2. Comprar inmediatamente
    3. Vender exactamente a los 3 días
    4. Repetir
    """
    
    def __init__(self):
        self.lookback = 5  # 5 días momentum
        self.top_n = 5     # 5 stocks
        self.hold_days = 3 # Vender a los 3 días
        
    def select_stocks(self, prices):
        """Seleccionar top 5 por momentum 5 días"""
        if len(prices) < self.lookback + 1:
            return []
        
        momentum_scores = {}
        
        for symbol in prices.columns:
            try:
                series = prices[symbol].dropna()
                if len(series) < self.lookback + 1:
                    continue
                
                # Momentum = (precio hoy / precio 5 días atrás) - 1
                momentum = (series.iloc[-1] / series.iloc[-self.lookback - 1]) - 1
                momentum_scores[symbol] = momentum
                
            except:
                continue
        
        if not momentum_scores:
            return []
        
        # Top 5
        sorted_stocks = sorted(momentum_scores.items(), key=lambda x: x[1], reverse=True)
        return [symbol for symbol, _ in sorted_stocks[:self.top_n]]


def run_omnicapital_v5(start_date, end_date, initial_capital=100000):
    """
    Backtest ultra-simple: comprar y vender a los 3 días.
    """
    print("=" * 95)
    print("ALPHAMAX OMNICAPITAL v5.0")
    print("3-Day Hold Strategy - Ultra Simple")
    print("=" * 95)
    print(f"Periodo: {start_date.date()} a {end_date.date()}")
    print(f"Capital Inicial: ${initial_capital:,.2f}")
    print(f"Estrategia: Comprar -> Esperar 3 días -> Vender")
    print("=" * 95)
    
    symbols = get_sp500_top40()
    print(f"\nUniverso: {len(symbols)} acciones")
    
    provider = YFinanceProvider()
    print("\nDescargando datos...")
    prices = provider.get_historical_prices(symbols, start_date=start_date, end_date=end_date)
    
    if prices.empty:
        print("Error: No se pudieron descargar datos")
        return
    
    print(f"Datos: {prices.shape[0]} días x {prices.shape[1]} símbolos")
    
    # Inicializar estrategia
    strategy = ThreeDayStrategy()
    
    print(f"\nReglas:")
    print(f"  - Selección: Top {strategy.top_n} por momentum {strategy.lookback} días")
    print(f"  - Hold: Exactamente {strategy.hold_days} días")
    print(f"  - Sin stops, sin targets, sin filtros")
    
    # Estado
    cash = initial_capital
    positions = {}  # {symbol: {shares, entry_date, entry_price}}
    portfolio_values = []
    trades = []
    
    available_dates = prices.index
    
    print("\n" + "=" * 95)
    print("EJECUTANDO BACKTEST - 3 DAY STRATEGY")
    print("=" * 95)
    
    for i, current_date in enumerate(available_dates):
        # Calcular valor del portafolio
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in prices.columns and not pd.isna(prices.loc[current_date, symbol]):
                current_price = prices.loc[current_date, symbol]
                portfolio_value += pos['shares'] * current_price
        
        # === VENDER POSICIONES CON 3 DÍAS ===
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            days_held = (current_date - pos['entry_date']).days
            
            if days_held >= strategy.hold_days:
                # VENDER
                if symbol in prices.columns and not pd.isna(prices.loc[current_date, symbol]):
                    current_price = prices.loc[current_date, symbol]
                    proceeds = pos['shares'] * current_price * 0.999
                    cash += proceeds
                    
                    pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
                    
                    trades.append({
                        'date': current_date,
                        'symbol': symbol,
                        'action': 'SELL_3DAY',
                        'shares': pos['shares'],
                        'price': current_price,
                        'proceeds': proceeds,
                        'pnl_pct': pnl_pct,
                        'days_held': days_held
                    })
                    
                    del positions[symbol]
        
        # === COMPRAR NUEVAS POSICIONES ===
        # Seleccionar stocks
        if i >= strategy.lookback + 1:
            hist_prices = prices.iloc[:i+1]
            selected = strategy.select_stocks(hist_prices)
            
            # Calcular cash por posición
            if len(selected) > 0 and cash > initial_capital * 0.1:
                cash_per_stock = (cash * 0.95) / len(selected)
                
                for symbol in selected:
                    if symbol in positions:
                        continue  # Ya tenemos esta posición
                    
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
                            positions[symbol] = {
                                'shares': shares,
                                'entry_date': current_date,
                                'entry_price': current_price
                            }
                            
                            trades.append({
                                'date': current_date,
                                'symbol': symbol,
                                'action': 'BUY',
                                'shares': shares,
                                'price': current_price,
                                'cost': cost
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
    print("OMNICAPITAL v5.0 - RESULTADOS")
    print("=" * 95)
    
    df_results = pd.DataFrame(portfolio_values)
    
    if df_results.empty:
        print("Error: No se generaron resultados")
        return
    
    final_value = df_results['portfolio_value'].iloc[-1]
    total_return = (final_value - initial_capital) / initial_capital
    years = len(df_results) / 252
    
    # Métricas
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
        print(f"   Años:                 {years:>15.1f}")
        print(f"   Retorno Anualizado:   {(1+total_return)**(1/years)-1:>15.2%}")
    
    print(f"\n>> RIESGO")
    print(f"   Volatilidad:          {volatility:>15.2%}")
    print(f"   Max Drawdown:         {max_drawdown:>15.2%}")
    print(f"   Sharpe Ratio:         {sharpe:>15.2f}")
    
    print(f"\n>> ACTIVIDAD")
    print(f"   Total Trades:         {len(trades):>15}")
    
    if trades:
        df_trades = pd.DataFrame(trades)
        buys = len(df_trades[df_trades['action'] == 'BUY'])
        sells = len(df_trades[df_trades['action'] == 'SELL_3DAY'])
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
    
    # Evolución
    print(f"\n>> EVOLUCION")
    print("-" * 60)
    sample = df_results.iloc[::max(1, len(df_results)//10)]
    for _, row in sample.iterrows():
        print(f"{row['date'].date()} | ${row['portfolio_value']:>13,.2f} | {row['num_positions']:2} pos")
    
    # Guardar
    df_results.to_csv('backtests/backtest_v5_3day_results.csv', index=False)
    if trades:
        pd.DataFrame(trades).to_csv('backtests/trades_v5_3day.csv', index=False)
    
    print(f"\n>> Archivos guardados:")
    print(f"   - backtests/backtest_v5_3day_results.csv")
    print(f"   - backtests/trades_v5_3day.csv")
    
    return df_results, trades


if __name__ == '__main__':
    end_date = datetime.now()
    start_date = datetime(2000, 1, 1)
    
    print(f"Backtest: {start_date.date()} a {end_date.date()}")
    results, trades = run_omnicapital_v5(start_date, end_date)