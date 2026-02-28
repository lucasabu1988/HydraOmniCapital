"""
OMNICAPITAL v6 FINAL - RANDOM 666 (FIXED)
==========================================
Version corregida con calculo de valor apropiado
Resultado esperado: ~17.5% CAGR
"""

import yfinance as yf
import pandas as pd
import numpy as np
import random
import json
import os
from datetime import datetime, timedelta
from collections import Counter
import warnings
warnings.filterwarnings('ignore')

# Configuracion
INITIAL_CAPITAL = 100_000
NUM_POSITIONS = 5
HOLD_MINUTES = 666
RANDOM_SEED = 42
MIN_SYMBOLS_FOR_TRADING = 30

UNIVERSE_40 = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
    'JPM', 'V', 'JNJ', 'UNH', 'XOM', 'WMT', 'PG', 'MA', 'HD', 'CVX',
    'MRK', 'ABBV', 'PEP', 'KO', 'PFE', 'AVGO', 'COST', 'TMO', 'DIS',
    'ABT', 'ADBE', 'BAC', 'ACN', 'WFC', 'CRM', 'VZ', 'DHR', 'NKE',
    'TXN', 'PM', 'NEE', 'AMD'
]


def download_data(symbols, start, end):
    """Descarga datos con cache"""
    cache_file = f'data_cache/fixed_{start}_{end}.pkl'
    
    if os.path.exists(cache_file):
        print("[Cache] Cargando datos...")
        return pd.read_pickle(cache_file)
    
    print(f"[Download] Descargando {len(symbols)} simbolos...")
    data = {}
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            df = ticker.history(start=start, end=end, auto_adjust=True)
            if len(df) > 100:
                data[symbol] = df
        except:
            pass
    
    os.makedirs('data_cache', exist_ok=True)
    pd.to_pickle(data, cache_file)
    print(f"[Download] {len(data)} simbolos validos")
    return data


def get_trading_dates(price_data, min_symbols=30):
    """Obtiene fechas donde al menos min_symbols tienen datos"""
    date_counts = Counter()
    for df in price_data.values():
        for date in df.index:
            date_counts[date] += 1
    
    valid_dates = [date for date, count in date_counts.items() if count >= min_symbols]
    return sorted(valid_dates)


def run_backtest(price_data, dates, seed=42):
    """Ejecuta backtest Random 666"""
    
    random.seed(seed)
    np.random.seed(seed)
    
    hold_days = max(1, HOLD_MINUTES // (6.5 * 60))
    cash = INITIAL_CAPITAL
    positions = {}
    portfolio_values = []
    
    for i, date in enumerate(dates):
        # Simbolos disponibles para esta fecha
        available_symbols = {s: df for s, df in price_data.items() if date in df.index}
        
        # Calcular valor del portafolio
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in available_symbols:
                price = available_symbols[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price
        
        # Cerrar posiciones expiradas
        for symbol in list(positions.keys()):
            if date >= positions[symbol]['exit_date']:
                if symbol in available_symbols:
                    exit_price = available_symbols[symbol].loc[date, 'Close']
                    proceeds = positions[symbol]['shares'] * exit_price
                    cash += proceeds
                del positions[symbol]
        
        # Abrir nuevas posiciones
        available_for_entry = [s for s in available_symbols.keys() if s not in positions]
        needed = NUM_POSITIONS - len(positions)
        
        if needed > 0 and len(available_for_entry) >= needed:
            selected = random.sample(available_for_entry, needed)
            
            for symbol in selected:
                entry_price = available_symbols[symbol].loc[date, 'Close']
                position_value = (portfolio_value * 0.95) / NUM_POSITIONS
                
                if position_value > cash * 0.95:
                    continue
                
                shares = position_value / entry_price
                positions[symbol] = {
                    'entry_price': entry_price,
                    'shares': shares,
                    'exit_date': date + timedelta(days=hold_days)
                }
                cash -= position_value
        
        portfolio_values.append({'date': date, 'value': portfolio_value})
        
        if i % 252 == 0 and i > 0:
            print(f"  Año {i//252}: ${portfolio_value:,.0f}")
    
    return portfolio_values


def calculate_metrics(portfolio_values):
    """Calcula metricas"""
    df = pd.DataFrame(portfolio_values)
    df.set_index('date', inplace=True)
    
    initial = df['value'].iloc[0]
    final = df['value'].iloc[-1]
    total_return = (final - initial) / initial
    
    years = len(df) / 252
    cagr = (final / initial) ** (1/years) - 1
    
    returns = df['value'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(252)
    
    rolling_max = df['value'].expanding().max()
    max_dd = ((df['value'] - rolling_max) / rolling_max).min()
    
    sharpe = (returns.mean() * 252 - 0.02) / (returns.std() * np.sqrt(252))
    
    return {
        'initial': initial,
        'final': final,
        'total_return': total_return,
        'cagr': cagr,
        'volatility': volatility,
        'max_dd': max_dd,
        'sharpe': sharpe,
        'years': years
    }


def main():
    print("=" * 70)
    print("OMNICAPITAL v6 FINAL - RANDOM 666 (FIXED)")
    print("=" * 70)
    
    # Descargar datos
    price_data = download_data(UNIVERSE_40, '2000-01-01', '2026-02-09')
    
    # Obtener fechas validas
    dates = get_trading_dates(price_data, MIN_SYMBOLS_FOR_TRADING)
    print(f"[Dates] {len(dates)} fechas con >= {MIN_SYMBOLS_FOR_TRADING} simbolos")
    print(f"[Dates] {dates[0].date()} a {dates[-1].date()}")
    
    # Ejecutar backtest
    print("\n[Backtest] Ejecutando...")
    portfolio_values = run_backtest(price_data, dates, RANDOM_SEED)
    
    # Calcular metricas
    m = calculate_metrics(portfolio_values)
    
    # Reporte
    print("\n" + "=" * 70)
    print("RESULTADOS")
    print("=" * 70)
    print(f"Periodo: {m['years']:.1f} años")
    print(f"Capital inicial: ${m['initial']:,.0f}")
    print(f"Capital final: ${m['final']:,.0f}")
    print(f"Retorno total: {m['total_return']:.2%}")
    print(f"CAGR: {m['cagr']:.2%}")
    print(f"Volatilidad: {m['volatility']:.2%}")
    print(f"Max Drawdown: {m['max_dd']:.2%}")
    print(f"Sharpe: {m['sharpe']:.2f}")
    
    print("\n" + "=" * 70)
    print("COMPARACION")
    print("=" * 70)
    print(f"  Version original (reportada): 17.55% CAGR")
    print(f"  Version actual:               {m['cagr']:.2%} CAGR")
    print("=" * 70)


if __name__ == "__main__":
    main()
