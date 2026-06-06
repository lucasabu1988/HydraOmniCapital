"""
OmniCapital v6 - Optimizacion de Hold Time
Sweep detallado para encontrar el hold time optimo.
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

NUM_POSITIONS = 5
INITIAL_CAPITAL = 100_000
RANDOM_SEED = 42
COMMISSION_PER_SHARE = 0.001
MIN_AGE_DAYS = 63

# Sweep detallado alrededor del óptimo y valores extendidos
HOLD_TIMES = [
    # Rango 480-999 (1 overnight)
    480, 540, 600, 666, 720, 780, 840, 900, 960, 999,
    # Rango 1000-1500 (2 overnights)
    1050, 1110, 1170, 1200, 1230, 1260, 1320, 1380, 1440, 1500,
    # Rango 1500-2400 (3+ overnights)
    1560, 1620, 1680, 1800, 1950, 2100, 2340, 2520, 2700, 2880
]

print("=" * 80)
print("OMNICAPITAL v6 - OPTIMIZACION DE HOLD TIME")
print("=" * 80)
print(f"\nTesteando {len(HOLD_TIMES)} valores de hold time...")
print(f"Rango: {min(HOLD_TIMES)} a {max(HOLD_TIMES)} minutos ({min(HOLD_TIMES)/60:.1f}h a {max(HOLD_TIMES)/60:.1f}h)")
print()


def load_data():
    cache_file = 'data_cache/dynamic_universe_2000-01-01_2026-02-09.pkl'
    with open(cache_file, 'rb') as f:
        return pickle.load(f)


def get_tradeable_symbols(price_data, date, first_date):
    tradeable = []
    for symbol, df in price_data.items():
        if date not in df.index:
            continue
        symbol_first_date = df.index[0]
        days_since_start = (date - symbol_first_date).days
        if date <= first_date + timedelta(days=30):
            tradeable.append(symbol)
        elif days_since_start >= MIN_AGE_DAYS:
            tradeable.append(symbol)
    return tradeable


def minutes_between(date1, date2):
    """Estima minutos de trading entre dos fechas (390 min/dia)"""
    days_diff = (date2 - date1).days
    return days_diff * 390


def run_backtest(price_data, hold_minutes):
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    
    first_date = all_dates[0]
    cash = INITIAL_CAPITAL
    positions = {}
    portfolio_values = []
    trades = []
    
    for i, date in enumerate(all_dates):
        tradeable = get_tradeable_symbols(price_data, date, first_date)
        
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price
        
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            minutes_held = minutes_between(pos['entry_date'], date)
            
            if minutes_held >= hold_minutes:
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    shares = pos['shares']
                    proceeds = shares * exit_price
                    commission = shares * COMMISSION_PER_SHARE
                    cash += proceeds - commission
                    
                    pnl = (exit_price - pos['entry_price']) * shares - commission
                    trades.append({'pnl': pnl})
                del positions[symbol]
        
        for symbol in list(positions.keys()):
            if symbol not in tradeable:
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    cash += positions[symbol]['shares'] * exit_price
                del positions[symbol]
        
        needed = NUM_POSITIONS - len(positions)
        
        if needed > 0 and cash > 1000 and len(tradeable) >= needed:
            available_for_entry = [s for s in tradeable if s not in positions]
            
            if len(available_for_entry) >= needed:
                random.seed(RANDOM_SEED + date.toordinal())
                selected = random.sample(available_for_entry, needed)
                
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
                                'entry_date': date
                            }
                            cash -= cost + commission
        
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'positions': len(positions)
        })
    
    df = pd.DataFrame(portfolio_values)
    df.set_index('date', inplace=True)
    
    initial = df['value'].iloc[0]
    final = df['value'].iloc[-1]
    years = len(df) / 252
    cagr = (final / initial) ** (1/years) - 1
    
    returns = df['value'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(252)
    
    rolling_max = df['value'].expanding().max()
    max_dd = ((df['value'] - rolling_max) / rolling_max).min()
    
    sharpe = cagr / volatility if volatility > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    
    avg_return = trades_df['pnl'].mean() if len(trades_df) > 0 else 0
    
    return {
        'hold_minutes': hold_minutes,
        'hold_hours': hold_minutes / 60,
        'hold_days': hold_minutes / 390,
        'cagr': cagr,
        'final': final,
        'sharpe': sharpe,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'win_rate': win_rate,
        'avg_trade_return': avg_return,
        'trades': len(trades_df)
    }


# ============================================================================
# OPTIMIZACION
# ============================================================================

print("Cargando datos...")
price_data = load_data()
print(f"Datos cargados: {len(price_data)} simbolos\n")

results = []
for hold_minutes in HOLD_TIMES:
    print(f"Testeando {hold_minutes} min ({hold_minutes/60:.1f}h, {hold_minutes/390:.1f}d)...")
    
    result = run_backtest(price_data, hold_minutes)
    results.append(result)
    
    print(f"  CAGR: {result['cagr']:.2%} | Final: ${result['final']:,.0f} | "
          f"Sharpe: {result['sharpe']:.2f} | Trades: {result['trades']:,}")

# Ordenar por CAGR
results_by_cagr = sorted(results, key=lambda x: x['cagr'], reverse=True)

print("\n" + "=" * 110)
print("RESULTADOS COMPLETOS - ORDENADOS POR CAGR")
print("=" * 110)
print(f"{'Rank':<6} {'Hold (min)':<12} {'Hold (h)':<10} {'Hold (d)':<10} {'CAGR':<10} {'Final':<15} {'Sharpe':<8} {'Max DD':<10} {'Trades':<10}")
print("-" * 110)

for i, r in enumerate(results_by_cagr[:15], 1):
    print(f"{i:<6} {r['hold_minutes']:<12} {r['hold_hours']:<10.1f} {r['hold_days']:<10.1f} "
          f"{r['cagr']:<10.2%} ${r['final']:<14,.0f} {r['sharpe']:<8.2f} "
          f"{r['max_drawdown']:<10.1%} {r['trades']:<10,}")

# Top 3 por métrica
print("\n" + "=" * 110)
print("TOP 3 POR METRICA")
print("=" * 110)

best_cagr = sorted(results, key=lambda x: x['cagr'], reverse=True)[:3]
best_sharpe = sorted(results, key=lambda x: x['sharpe'], reverse=True)[:3]
best_calmar = sorted(results, key=lambda x: x['calmar'], reverse=True)[:3]

print("\nMEJOR CAGR:")
for i, r in enumerate(best_cagr, 1):
    print(f"  {i}. {r['hold_minutes']} min ({r['hold_hours']:.1f}h) = {r['cagr']:.2%}")

print("\nMEJOR SHARPE:")
for i, r in enumerate(best_sharpe, 1):
    print(f"  {i}. {r['hold_minutes']} min ({r['hold_hours']:.1f}h) = {r['sharpe']:.2f}")

print("\nMEJOR CALMAR:")
for i, r in enumerate(best_calmar, 1):
    print(f"  {i}. {r['hold_minutes']} min ({r['hold_hours']:.1f}h) = {r['calmar']:.2f}")

# Analisis de overnights
print("\n" + "=" * 110)
print("ANALISIS POR NUMERO DE OVERNIGHTS")
print("=" * 110)

overnight_groups = {
    '1 overnight (~390-780 min)': [],
    '2 overnights (~780-1170 min)': [],
    '3 overnights (~1170-1560 min)': [],
    '4+ overnights (>1560 min)': []
}

for r in results:
    if r['hold_minutes'] < 780:
        overnight_groups['1 overnight (~390-780 min)'].append(r)
    elif r['hold_minutes'] < 1170:
        overnight_groups['2 overnights (~780-1170 min)'].append(r)
    elif r['hold_minutes'] < 1560:
        overnight_groups['3 overnights (~1170-1560 min)'].append(r)
    else:
        overnight_groups['4+ overnights (>1560 min)'].append(r)

for group_name, group_results in overnight_groups.items():
    if group_results:
        best = max(group_results, key=lambda x: x['cagr'])
        print(f"\n{group_name}:")
        print(f"  Mejor: {best['hold_minutes']} min = {best['cagr']:.2%} CAGR")

# Guardar
with open('results_holdtime_optimization.pkl', 'wb') as f:
    pickle.dump(results, f)

print(f"\n\nGuardado en: results_holdtime_optimization.pkl")

# Recomendacion final
print("\n" + "=" * 110)
print("RECOMENDACION FINAL")
print("=" * 110)

overall_best = results_by_cagr[0]
print(f"\nHOLD TIME OPTIMO: {overall_best['hold_minutes']} minutos ({overall_best['hold_hours']:.1f} horas, {overall_best['hold_days']:.1f} dias)")
print(f"  CAGR: {overall_best['cagr']:.2%}")
print(f"  Sharpe: {overall_best['sharpe']:.2f}")
print(f"  Max Drawdown: {overall_best['max_drawdown']:.1%}")
print(f"  Trades totales: {overall_best['trades']:,}")
print(f"  Win rate: {overall_best['win_rate']:.1%}")
print(f"  Retorno promedio por trade: ${overall_best['avg_trade_return']:.2f}")
