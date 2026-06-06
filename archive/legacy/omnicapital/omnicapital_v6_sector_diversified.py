"""
OmniCapital v6 - Sector Diversified
Las 5 posiciones deben ser de sectores completamente distintos.
"""

import pandas as pd
import numpy as np
import pickle
from datetime import timedelta
import random
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARÁMETROS
# ============================================================================

HOLD_MINUTES = 1200  # 20 horas = ~2 overnights (optimizado)
NUM_POSITIONS = 5
INITIAL_CAPITAL = 100_000
RANDOM_SEED = 42
COMMISSION_PER_SHARE = 0.001
MIN_AGE_DAYS = 63

print("=" * 70)
print("OMNICAPITAL v6 - SECTOR DIVERSIFIED")
print("=" * 70)
print(f"\nRegla: Las {NUM_POSITIONS} posiciones deben ser de sectores distintos")
print(f"Hold time: {HOLD_MINUTES} minutos ({HOLD_MINUTES/60:.1f} horas)")
print()


# ============================================================================
# CLASIFICACIÓN POR SECTORES
# ============================================================================

SECTOR_MAP = {
    # Tecnología
    'AAPL': 'Tech', 'MSFT': 'Tech', 'AMZN': 'Tech', 'NVDA': 'Tech', 'GOOGL': 'Tech',
    'META': 'Tech', 'ADBE': 'Tech', 'CRM': 'Tech', 'CSCO': 'Tech', 'INTC': 'Tech',
    'AMD': 'Tech', 'TXN': 'Tech', 'AVGO': 'Tech', 'IBM': 'Tech', 'ORCL': 'Tech',
    'QCOM': 'Tech', 'ACN': 'Tech',
    # Financieros
    'JPM': 'Financials', 'BAC': 'Financials', 'V': 'Financials', 'MA': 'Financials',
    'WFC': 'Financials', 'GS': 'Financials', 'AXP': 'Financials', 'BRK-B': 'Financials',
    # Salud
    'JNJ': 'Health', 'UNH': 'Health', 'PFE': 'Health', 'MRK': 'Health', 'ABT': 'Health',
    'TMO': 'Health', 'DHR': 'Health', 'MDT': 'Health', 'AMGN': 'Health', 'GILD': 'Health',
    'BMY': 'Health', 'LLY': 'Health', 'BIIB': 'Health', 'ABBV': 'Health',
    # Consumo Defensivo
    'WMT': 'Cons_Def', 'PG': 'Cons_Def', 'KO': 'Cons_Def', 'PEP': 'Cons_Def',
    'COST': 'Cons_Def', 'KMB': 'Cons_Def', 'CL': 'Cons_Def', 'MO': 'Cons_Def',
    'PM': 'Cons_Def', 'WBA': 'Cons_Def',
    # Consumo Cíclico
    'HD': 'Cons_Cyc', 'DIS': 'Cons_Cyc', 'NKE': 'Cons_Cyc', 'MCD': 'Cons_Cyc',
    'AMZN': 'Cons_Cyc', 'TSLA': 'Cons_Cyc', 'BA': 'Cons_Cyc', 'CAT': 'Cons_Cyc',
    # Industriales
    'GE': 'Industrials', 'HON': 'Industrials', 'MMM': 'Industrials', 'UPS': 'Industrials',
    'FDX': 'Industrials', 'UNP': 'Industrials', 'RTX': 'Industrials', 'LMT': 'Industrials',
    'SLB': 'Industrials', 'OXY': 'Industrials', 'COP': 'Industrials',
    # Energía
    'XOM': 'Energy', 'CVX': 'Energy', 'NEE': 'Energy',
    # Telecom
    'VZ': 'Telecom', 'T': 'Telecom',
    # Materiales
    'DD': 'Materials', 'AA': 'Materials'
}


def load_data():
    cache_file = 'data_cache/dynamic_universe_2000-01-01_2026-02-09.pkl'
    with open(cache_file, 'rb') as f:
        return pickle.load(f)


def get_tradeable(price_data, date, first_date):
    """Retorna símbolos tradeables con su sector"""
    tradeable = []
    for symbol, df in price_data.items():
        if date not in df.index:
            continue
        symbol_first = df.index[0]
        days = (date - symbol_first).days
        if date <= first_date + timedelta(days=30) or days >= MIN_AGE_DAYS:
            if symbol in SECTOR_MAP:  # Solo símbolos con sector asignado
                tradeable.append((symbol, SECTOR_MAP[symbol]))
    return tradeable


def select_sector_diversified(available, needed, seed):
    """
    Selecciona símbolos asegurando diversificación por sector.
    Cada selección debe ser de un sector distinto.
    """
    random.seed(seed)
    
    # Agrupar por sector
    by_sector = {}
    for symbol, sector in available:
        if sector not in by_sector:
            by_sector[sector] = []
        by_sector[sector].append(symbol)
    
    selected = []
    used_sectors = set()
    
    # Intentar seleccionar uno de cada sector hasta completar 'needed'
    attempts = 0
    while len(selected) < needed and attempts < 100:
        attempts += 1
        
        # Sectores disponibles (que no hemos usado y tienen símbolos)
        available_sectors = [s for s in by_sector.keys() if s not in used_sectors]
        
        if not available_sectors:
            break
        
        # Elegir sector aleatorio
        sector = random.choice(available_sectors)
        
        # Elegir símbolo aleatorio de ese sector
        symbol = random.choice(by_sector[sector])
        
        selected.append(symbol)
        used_sectors.add(sector)
    
    return selected


def minutes_held(entry_date, current_date):
    return (current_date - entry_date).days * 390


def run_backtest(price_data):
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    first_date = all_dates[0]
    
    cash = INITIAL_CAPITAL
    positions = {}  # symbol -> {'shares', 'entry_date', 'entry_price', 'sector'}
    portfolio_values = []
    trades = []
    
    for i, date in enumerate(all_dates):
        # Obtener símbolos tradeables con sector
        tradeable_with_sector = get_tradeable(price_data, date, first_date)
        tradeable_symbols = [s for s, _ in tradeable_with_sector]
        
        # Calcular valor
        portfolio_value = cash
        for sym, pos in list(positions.items()):
            if sym in price_data and date in price_data[sym].index:
                portfolio_value += pos['shares'] * price_data[sym].loc[date, 'Close']
        
        # Cerrar expiradas
        for sym in list(positions.keys()):
            if minutes_held(positions[sym]['entry_date'], date) >= HOLD_MINUTES:
                if sym in price_data and date in price_data[sym].index:
                    price = price_data[sym].loc[date, 'Close']
                    shares = positions[sym]['shares']
                    proceeds = shares * price
                    commission = shares * COMMISSION_PER_SHARE
                    cash += proceeds - commission
                    
                    entry = positions[sym]['entry_price']
                    trades.append({'pnl': (price - entry) * shares - commission})
                del positions[sym]
        
        # Cerrar no tradeables
        for sym in list(positions.keys()):
            if sym not in tradeable_symbols:
                if sym in price_data and date in price_data[sym].index:
                    cash += positions[sym]['shares'] * price_data[sym].loc[date, 'Close']
                del positions[sym]
        
        # Abrir nuevas posiciones con diversificación sectorial
        needed = NUM_POSITIONS - len(positions)
        
        if needed > 0 and cash > 1000:
            # Símbolos disponibles que no están en posiciones
            available = [(s, sec) for s, sec in tradeable_with_sector if s not in positions]
            
            # Sectores ya usados en posiciones actuales
            used_sectors = {positions[s]['sector'] for s in positions}
            
            # Filtrar disponibles para evitar sectores usados
            available_filtered = [(s, sec) for s, sec in available if sec not in used_sectors]
            
            if len(available_filtered) >= needed:
                selected = select_sector_diversified(available_filtered, needed, 
                                                     RANDOM_SEED + date.toordinal())
                
                position_value = (portfolio_value * 0.95) / NUM_POSITIONS
                
                for sym in selected:
                    if sym in price_data and date in price_data[sym].index:
                        price = price_data[sym].loc[date, 'Close']
                        shares = position_value / price
                        cost = shares * price
                        comm = shares * COMMISSION_PER_SHARE
                        
                        if cost + comm <= cash * 0.95:
                            positions[sym] = {
                                'entry_price': price,
                                'shares': shares,
                                'entry_date': date,
                                'sector': SECTOR_MAP[sym]
                            }
                            cash -= cost + comm
        
        # Sectores en portfolio
        sectors_in_port = [positions[s]['sector'] for s in positions]
        
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'positions': len(positions),
            'sectors': sectors_in_port
        })
        
        if i % 252 == 0 and i > 0:
            year = i // 252
            uniq_sectors = len(set(sectors_in_port)) if sectors_in_port else 0
            print(f"  Año {year}: ${portfolio_value:,.0f} | Pos: {len(positions)}/5 | "
                  f"Sectores: {uniq_sectors}/5 | Tradeable: {len(tradeable_symbols)}")
    
    return portfolio_values, trades


def calculate_metrics(portfolio_values, trades):
    df = pd.DataFrame(portfolio_values).set_index('date')
    
    initial, final = df['value'].iloc[0], df['value'].iloc[-1]
    years = len(df) / 252
    cagr = (final / initial) ** (1/years) - 1
    
    returns = df['value'].pct_change().dropna()
    vol = returns.std() * np.sqrt(252)
    
    rolling_max = df['value'].expanding().max()
    max_dd = ((df['value'] - rolling_max) / rolling_max).min()
    
    sharpe = cagr / vol if vol > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    
    # Análisis de diversificación sectorial
    all_sectors = []
    for pv in portfolio_values:
        all_sectors.extend(pv['sectors'])
    sector_counts = pd.Series(all_sectors).value_counts()
    
    return {
        'cagr': cagr, 'final': final, 'sharpe': sharpe, 'calmar': calmar,
        'max_drawdown': max_dd, 'win_rate': win_rate, 'trades': len(trades_df),
        'sector_counts': sector_counts
    }


print("Cargando datos...")
price_data = load_data()
print(f"{len(price_data)} símbolos\n")

portfolio_values, trades = run_backtest(price_data)
metrics = calculate_metrics(portfolio_values, trades)

print("\n" + "=" * 70)
print("RESULTADOS - SECTOR DIVERSIFIED")
print("=" * 70)
print(f"\nCapital inicial:     ${INITIAL_CAPITAL:>15,.0f}")
print(f"Capital final:       ${metrics['final']:>15,.2f}")
print(f"CAGR:                {metrics['cagr']:>15.2%}")
print(f"Sharpe:              {metrics['sharpe']:>15.2f}")
print(f"Max DD:              {metrics['max_drawdown']:>15.2%}")
print(f"Win rate:            {metrics['win_rate']:>15.2%}")
print(f"Trades:              {metrics['trades']:>15,}")

print("\n" + "=" * 70)
print("DISTRIBUCIÓN POR SECTORES (en todas las posiciones)")
print("=" * 70)
for sector, count in metrics['sector_counts'].items():
    pct = count / metrics['sector_counts'].sum() * 100
    print(f"  {sector:<15} {count:>6,} ({pct:>5.1f}%)")

print("\n" + "=" * 70)
print("COMPARATIVA")
print("=" * 70)
print(f"{'Versión':<30} {'CAGR':<10} {'Sharpe':<10}")
print("-" * 50)
print(f"{'Sin sector (aleatorio puro)':<30} {'15.11%':<10} {'0.73':<10}")
print(f"{'Sector diversified':<30} {f"{metrics['cagr']:.2%}":<10} {f"{metrics['sharpe']:.2f}":<10}")

with open('results_v6_sector_diversified.pkl', 'wb') as f:
    pickle.dump({'metrics': metrics, 'portfolio_values': portfolio_values}, f)

print(f"\nGuardado en: results_v6_sector_diversified.pkl")
