"""
OmniCapital v6 - Dynamic Universe
Siempre mantiene 40 posiciones, rotando símbolos según disponibilidad temporal.
Cuando un símbolo no tiene datos, se reemplaza por otro blue-chip disponible.
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

HOLD_MINUTES = 666  # ~11.1 horas
NUM_POSITIONS = 40  # SIEMPRE 40 posiciones
INITIAL_CAPITAL = 100_000
RANDOM_SEED = 42
COMMISSION_PER_SHARE = 0.001

# Fechas del backtest
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

# ============================================================================
# UNIVERSO DINÁMICO - Blue chips organizados por época de disponibilidad
# ============================================================================

# Universo base: 40 blue-chips que existen desde 2000 o antes
UNIVERSE_BASE = [
    'AAPL', 'MSFT', 'AMZN', 'NVDA', 'AMD', 'TXN', 'ADBE',  # Tecnología
    'JPM', 'BAC', 'BRK-B', 'WFC',  # Financieros
    'JNJ', 'PFE', 'MRK', 'UNH', 'ABT', 'TMO', 'DHR',  # Salud
    'KO', 'PEP', 'PG', 'WMT', 'HD', 'COST', 'DIS', 'NKE',  # Consumo
    'XOM', 'CVX', 'NEE',  # Energía
    'VZ',  # Telecom
    'ACN', 'ABT', 'DHR', 'TMO'  # Otros
]

# Símbolos que entran en diferentes épocas (para rotación)
EPoca_SYMBOLS = {
    2000: ['AAPL', 'MSFT', 'AMZN', 'NVDA', 'AMD', 'TXN', 'ADBE', 'JPM', 'BAC', 
           'BRK-B', 'WFC', 'JNJ', 'PFE', 'MRK', 'UNH', 'ABT', 'TMO', 'DHR', 'KO', 
           'PEP', 'PG', 'WMT', 'HD', 'COST', 'DIS', 'NKE', 'XOM', 'CVX', 'NEE', 'VZ',
           'ACN', 'INTC', 'CSCO', 'IBM', 'GE', 'CAT', 'BA', 'MMM', 'AXP', 'GS'],
    2004: ['CRM', 'GOOGL'],  # IPOs 2004
    2006: ['MA'],  # IPO 2006
    2008: ['V', 'PM'],  # IPOs 2008
    2009: ['AVGO'],  # IPO 2009
    2010: ['TSLA'],  # IPO 2010
    2012: ['META'],  # IPO 2012
    2013: ['ABBV'],  # Spin-off 2013
}

# Símbolos que salen o dejan de estar disponibles
# (en una implementación real, esto podría incluir delistings, mergers, etc.)

print("=" * 70)
print("OMNICAPITAL v6 - DYNAMIC UNIVERSE (40 POSICIONES)")
print("=" * 70)
print(f"\nParámetros:")
print(f"  - Hold time: {HOLD_MINUTES} minutos (~{HOLD_MINUTES/60:.1f} horas)")
print(f"  - Posiciones: {NUM_POSITIONS} (SIEMPRE)")
print(f"  - Capital inicial: ${INITIAL_CAPITAL:,.0f}")
print(f"  - Universo: Dinámico por época")
print()


def download_data():
    """Descarga datos extendidos para universo dinámico"""
    cache_file = 'data_cache/dynamic_universe_2000-01-01_2026-02-09.pkl'
    
    if os.path.exists(cache_file):
        print(f"[Cache] Cargando: {cache_file}")
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    
    # Universo extendido para rotación
    all_symbols = list(set([
        'AAPL', 'MSFT', 'AMZN', 'NVDA', 'GOOGL', 'META', 'TSLA', 'AVGO',
        'BRK-B', 'JPM', 'V', 'JNJ', 'WMT', 'MA', 'PG', 'UNH', 'HD', 'CVX',
        'MRK', 'PEP', 'KO', 'ABBV', 'BAC', 'COST', 'TMO', 'DIS',
        'ABT', 'WFC', 'ACN', 'VZ', 'DHR', 'ADBE', 'CRM', 'TXN', 'NKE',
        'NEE', 'AMD', 'PM', 'XOM',
        # Extras para rotación
        'INTC', 'CSCO', 'IBM', 'GE', 'CAT', 'BA', 'MMM', 'AXP', 'GS',
        'WBA', 'FDX', 'UPS', 'LMT', 'RTX', 'UNP', 'HON', 'MO', 'KMB',
        'CL', 'MDT', 'GILD', 'BIIB', 'AMGN', 'LLY', 'BMY', 'SLB', 'OXY'
    ]))
    
    print(f"[Download] Descargando {len(all_symbols)} símbolos...")
    
    data = {}
    for symbol in all_symbols:
        try:
            df = yf.download(symbol, start=START_DATE, end=END_DATE, progress=False)
            if not df.empty and len(df) > 100:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                data[symbol] = df
                print(f"  OK {symbol}: {len(df)} dias ({df.index[0].strftime('%Y-%m-%d')} a {df.index[-1].strftime('%Y-%m-%d')})")
        except Exception as e:
            print(f"  FAIL {symbol}: {e}")
    
    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)
    
    print(f"\n[Download] {len(data)} símbolos válidos guardados")
    return data


def get_available_symbols_for_date(price_data, date, min_history_days=63):
    """
    Retorna todos los símbolos disponibles para una fecha específica.
    Un símbolo está disponible si:
    1. Tiene datos para la fecha
    2. Ha cotizado al menos min_history_days desde su primer día (evitar IPO reciente)
    """
    available = []
    
    for symbol, df in price_data.items():
        if date not in df.index:
            continue
        
        # Verificar antigüedad mínima (evitar IPOs de menos de 3 meses)
        first_date = df.index[0]
        days_since_start = (date - first_date).days
        
        if days_since_start >= min_history_days:
            available.append(symbol)
    
    return available


def select_portfolio_universe(available_symbols, date, target_count=40, seed=42):
    """
    Selecciona 40 símbolos del universo disponible.
    Prioriza blue-chips establecidos, pero incluye nuevos si es necesario.
    """
    if len(available_symbols) < target_count:
        return available_symbols  # No hay suficientes, usar todos
    
    # Semilla determinística basada en fecha
    random.seed(seed + date.toordinal())
    
    # Priorizar símbolos que han estado disponibles más tiempo
    # (esto se logra ordenando por antigüedad implícita en el orden de available)
    # Por ahora, selección aleatoria estratificada
    
    selected = random.sample(available_symbols, target_count)
    return selected


def run_dynamic_backtest(price_data):
    """Ejecuta backtest con universo dinámico de 40 posiciones"""
    
    print("\n" + "=" * 70)
    print("INICIANDO BACKTEST DINÁMICO")
    print("=" * 70)
    
    # Construir conjunto de fechas
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    
    print(f"Total fechas: {len(all_dates)}")
    print(f"Rango: {all_dates[0].strftime('%Y-%m-%d')} a {all_dates[-1].strftime('%Y-%m-%d')}")
    
    # Parámetros
    hold_days = max(1, HOLD_MINUTES // (6.5 * 60))
    cash = INITIAL_CAPITAL
    positions = {}  # symbol -> {'shares': float, 'entry_date': date, 'exit_date': date}
    portfolio_values = []
    rotation_log = []  # Para tracking de rotaciones
    
    for i, date in enumerate(all_dates):
        # Obtener universo disponible para esta fecha
        available = get_available_symbols_for_date(price_data, date)
        
        # Seleccionar 40 símbolos para el portfolio
        target_universe = select_portfolio_universe(available, date, NUM_POSITIONS, RANDOM_SEED)
        
        # Calcular valor del portfolio
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price
        
        # Cerrar posiciones que ya no están en el universo objetivo
        for symbol in list(positions.keys()):
            if symbol not in target_universe:
                # Forzar cierre (rotación)
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    proceeds = positions[symbol]['shares'] * exit_price
                    cash += proceeds
                    
                    rotation_log.append({
                        'date': date,
                        'action': 'ROTATE_OUT',
                        'symbol': symbol,
                        'value': proceeds
                    })
                del positions[symbol]
        
        # Cerrar posiciones expiradas (hold time)
        for symbol in list(positions.keys()):
            if date >= positions[symbol]['exit_date']:
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    proceeds = positions[symbol]['shares'] * exit_price
                    cash += proceeds
                del positions[symbol]
        
        # Abrir nuevas posiciones para alcanzar 40
        needed = NUM_POSITIONS - len(positions)
        
        if needed > 0 and cash > 1000:
            # Símbolos disponibles que no están en posiciones
            available_for_entry = [s for s in target_universe if s not in positions]
            
            if len(available_for_entry) >= needed:
                # Seleccionar aleatoriamente
                random.seed(RANDOM_SEED + date.toordinal())
                selected = random.sample(available_for_entry, needed)
                
                # Calcular tamaño de posición
                position_value = (portfolio_value * 0.98) / NUM_POSITIONS
                
                for symbol in selected:
                    if symbol in price_data and date in price_data[symbol].index:
                        entry_price = price_data[symbol].loc[date, 'Close']
                        shares = position_value / entry_price
                        
                        cost = shares * entry_price
                        if cost <= cash * 0.95:
                            positions[symbol] = {
                                'entry_price': entry_price,
                                'shares': shares,
                                'entry_date': date,
                                'exit_date': date + timedelta(days=hold_days)
                            }
                            cash -= cost
                            
                            rotation_log.append({
                                'date': date,
                                'action': 'ENTER',
                                'symbol': symbol,
                                'value': cost
                            })
        
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'universe_size': len(target_universe),
            'available': len(available)
        })
        
        if i % 252 == 0 and i > 0:
            year = i // 252
            print(f"  Año {year}: ${portfolio_value:,.0f} | Posiciones: {len(positions)}/40 | "
                  f"Universo: {len(target_universe)} | Disponibles: {len(available)}")
    
    return portfolio_values, rotation_log


def calculate_metrics(portfolio_values):
    """Calcula métricas de performance"""
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
    
    return {
        'initial': initial,
        'final': final,
        'total_return': total_return,
        'cagr': cagr,
        'volatility': volatility,
        'max_drawdown': max_dd,
        'sharpe': sharpe,
        'df': df
    }


# ============================================================================
# EJECUCIÓN
# ============================================================================

if __name__ == "__main__":
    # Descargar datos
    price_data = download_data()
    
    # Ejecutar backtest
    portfolio_values, rotation_log = run_dynamic_backtest(price_data)
    
    # Calcular métricas
    metrics = calculate_metrics(portfolio_values)
    
    # Resultados
    print("\n" + "=" * 70)
    print("RESULTADOS - DYNAMIC UNIVERSE (40 POSICIONES)")
    print("=" * 70)
    print(f"\nCapital inicial:     ${metrics['initial']:>15,.0f}")
    print(f"Capital final:       ${metrics['final']:>15,.2f}")
    print(f"Retorno total:       {metrics['total_return']:>15.2%}")
    print(f"CAGR:                {metrics['cagr']:>15.2%}")
    print(f"Volatilidad anual:   {metrics['volatility']:>15.2%}")
    print(f"Sharpe ratio:        {metrics['sharpe']:>15.2f}")
    print(f"Max drawdown:        {metrics['max_drawdown']:>15.2%}")
    
    # Análisis de rotaciones
    rotations = pd.DataFrame(rotation_log)
    if len(rotations) > 0:
        enters = len(rotations[rotations['action'] == 'ENTER'])
        rotates_out = len(rotations[rotations['action'] == 'ROTATE_OUT'])
        print(f"\nRotaciones:")
        print(f"  Entradas:          {enters:>15,}")
        print(f"  Rotaciones out:    {rotates_out:>15,}")
    
    # Guardar resultados
    output_file = 'results_v6_dynamic_universe.pkl'
    with open(output_file, 'wb') as f:
        pickle.dump({
            'metrics': metrics,
            'portfolio_values': portfolio_values,
            'rotation_log': rotation_log
        }, f)
    
    print(f"\nResultados guardados en: {output_file}")
