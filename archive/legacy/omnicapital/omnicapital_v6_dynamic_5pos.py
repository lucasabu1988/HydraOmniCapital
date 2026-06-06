"""
OmniCapital v6 - Dynamic Universe con 5 posiciones
Universo extendido de blue-chips por epoca, siempre 5 posiciones.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import random
import pickle
import os
from collections import Counter
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARÁMETROS
# ============================================================================

HOLD_MINUTES = 666
NUM_POSITIONS = 5  # SIEMPRE 5 posiciones (optimo)
INITIAL_CAPITAL = 100_000
RANDOM_SEED = 42
COMMISSION_PER_SHARE = 0.001

START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

print("=" * 70)
print("OMNICAPITAL v6 - DYNAMIC UNIVERSE (5 POSICIONES)")
print("=" * 70)
print(f"\nParámetros:")
print(f"  - Hold time: {HOLD_MINUTES} minutos (~{HOLD_MINUTES/60:.1f} horas)")
print(f"  - Posiciones: {NUM_POSITIONS} (optimo)")
print(f"  - Capital inicial: ${INITIAL_CAPITAL:,.0f}")
print(f"  - Universo: Dinámico extendido (65+ blue-chips)")
print()


def download_extended_data():
    """Descarga universo extendido de blue-chips"""
    cache_file = 'data_cache/dynamic_universe_2000-01-01_2026-02-09.pkl'
    
    if os.path.exists(cache_file):
        print(f"[Cache] Cargando: {cache_file}")
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    
    # Universo extendido: 65+ blue-chips de diferentes épocas
    all_symbols = list(set([
        # Original 40
        'AAPL', 'MSFT', 'AMZN', 'NVDA', 'GOOGL', 'META', 'TSLA', 'AVGO',
        'BRK-B', 'JPM', 'V', 'JNJ', 'WMT', 'MA', 'PG', 'UNH', 'HD', 'CVX',
        'MRK', 'PEP', 'KO', 'ABBV', 'BAC', 'COST', 'TMO', 'DIS',
        'ABT', 'WFC', 'ACN', 'VZ', 'DHR', 'ADBE', 'CRM', 'TXN', 'NKE',
        'NEE', 'AMD', 'PM', 'XOM',
        # Extras pre-2000 (para rotación en épocas tempranas)
        'INTC', 'CSCO', 'IBM', 'GE', 'CAT', 'BA', 'MMM', 'AXP', 'GS',
        'MO', 'KMB', 'CL', 'MDT', 'SLB', 'UNP', 'HON', 'FDX', 'UPS',
        'LMT', 'RTX', 'OXY', 'AMGN', 'LLY', 'BMY', 'BIIB', 'GILD',
        # Adicionales
        'WBA', 'COP', 'EOG', 'PSX', 'VLO', 'MPC', 'ETN', 'ITW', 'EMR'
    ]))
    
    print(f"[Download] Descargando {len(all_symbols)} símbolos...")
    
    data = {}
    for symbol in all_symbols:
        try:
            df = yf.download(symbol, start=START_DATE, end=END_DATE, progress=False)
            if not df.empty and len(df) > 100:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                data[symbol] = df
        except:
            pass
    
    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)
    
    print(f"[Download] {len(data)} símbolos válidos guardados")
    return data


def get_available_symbols(price_data, date, min_history_days=21):
    """Retorna símbolos disponibles para una fecha"""
    available = []
    for symbol, df in price_data.items():
        if date not in df.index:
            continue
        first_date = df.index[0]
        days_since_start = (date - first_date).days
        if days_since_start >= min_history_days:
            available.append(symbol)
    return available


def run_backtest(price_data):
    """Ejecuta backtest con universo dinámico"""
    
    print("\n" + "=" * 70)
    print("INICIANDO BACKTEST")
    print("=" * 70)
    
    # Fechas
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    
    print(f"Total fechas: {len(all_dates)}")
    print(f"Rango: {all_dates[0].strftime('%Y-%m-%d')} a {all_dates[-1].strftime('%Y-%m-%d')}")
    
    hold_days = max(1, HOLD_MINUTES // (6.5 * 60))
    cash = INITIAL_CAPITAL
    positions = {}  # symbol -> {'shares', 'entry_date', 'exit_date'}
    portfolio_values = []
    trades = []
    
    for i, date in enumerate(all_dates):
        # Obtener símbolos disponibles
        available = get_available_symbols(price_data, date)
        
        # Calcular valor del portfolio
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price
        
        # Cerrar posiciones que ya no están disponibles (delisting/rotación)
        for symbol in list(positions.keys()):
            if symbol not in available:
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    proceeds = positions[symbol]['shares'] * exit_price
                    cash += proceeds
                del positions[symbol]
        
        # Cerrar posiciones expiradas
        for symbol in list(positions.keys()):
            if date >= positions[symbol]['exit_date']:
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    shares = positions[symbol]['shares']
                    proceeds = shares * exit_price
                    commission = shares * COMMISSION_PER_SHARE
                    cash += proceeds - commission
                    
                    entry_price = positions[symbol]['entry_price']
                    pnl = (exit_price - entry_price) * shares - commission
                    trades.append({'pnl': pnl, 'return': pnl / (entry_price * shares)})
                del positions[symbol]
        
        # Abrir nuevas posiciones para alcanzar 5
        needed = NUM_POSITIONS - len(positions)
        
        if needed > 0 and cash > 1000 and len(available) >= needed:
            # Símbolos disponibles que no están en posiciones
            available_for_entry = [s for s in available if s not in positions]
            
            if len(available_for_entry) >= needed:
                # Selección aleatoria
                random.seed(RANDOM_SEED + date.toordinal())
                selected = random.sample(available_for_entry, needed)
                
                # Tamaño de posición basado en valor actual del portfolio
                position_value = (portfolio_value * 0.95) / NUM_POSITIONS
                
                for symbol in selected:
                    if symbol in price_data and date in price_data[symbol].index:
                        entry_price = price_data[symbol].loc[date, 'Close']
                        shares = position_value / entry_price
                        
                        cost = shares * entry_price
                        commission = shares * COMMISSION_PER_SHARE
                        
                        if cost + commission <= cash * 0.95:
                            positions[symbol] = {
                                'entry_price': entry_price,
                                'shares': shares,
                                'entry_date': date,
                                'exit_date': date + timedelta(days=hold_days)
                            }
                            cash -= cost + commission
        
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'available': len(available)
        })
        
        if i % 252 == 0 and i > 0:
            year = i // 252
            print(f"  Año {year}: ${portfolio_value:,.0f} | Pos: {len(positions)}/5 | Disp: {len(available)}")
    
    return portfolio_values, trades


def calculate_metrics(portfolio_values, trades):
    """Calcula métricas"""
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
    drawdown = (df['value'] - rolling_max) / rolling_max
    max_dd = drawdown.min()
    
    sharpe = cagr / volatility if volatility > 0 else 0
    
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    
    return {
        'initial': initial,
        'final': final,
        'total_return': total_return,
        'cagr': cagr,
        'volatility': volatility,
        'max_drawdown': max_dd,
        'sharpe': sharpe,
        'win_rate': win_rate,
        'trades': len(trades_df),
        'df': df
    }


# ============================================================================
# EJECUCIÓN
# ============================================================================

if __name__ == "__main__":
    price_data = download_extended_data()
    
    portfolio_values, trades = run_backtest(price_data)
    metrics = calculate_metrics(portfolio_values, trades)
    
    print("\n" + "=" * 70)
    print("RESULTADOS - DYNAMIC UNIVERSE (5 POSICIONES)")
    print("=" * 70)
    print(f"\nCapital inicial:     ${metrics['initial']:>15,.0f}")
    print(f"Capital final:       ${metrics['final']:>15,.2f}")
    print(f"Retorno total:       {metrics['total_return']:>15.2%}")
    print(f"CAGR:                {metrics['cagr']:>15.2%}")
    print(f"Volatilidad anual:   {metrics['volatility']:>15.2%}")
    print(f"Sharpe ratio:        {metrics['sharpe']:>15.2f}")
    print(f"Max drawdown:        {metrics['max_drawdown']:>15.2%}")
    print(f"\nTrades:              {metrics['trades']:>15,}")
    print(f"Win rate:            {metrics['win_rate']:>15.2%}")
    
    # Guardar
    with open('results_v6_dynamic_5pos.pkl', 'wb') as f:
        pickle.dump({'metrics': metrics, 'portfolio_values': portfolio_values}, f)
    
    print(f"\nGuardado en: results_v6_dynamic_5pos.pkl")
