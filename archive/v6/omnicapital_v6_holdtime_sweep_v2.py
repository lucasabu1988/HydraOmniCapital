"""
OmniCapital v6 - Sweep de Hold Time (v2)
Testea diferentes duraciones de hold para encontrar el optimo.
Version corregida con tracking por minutos.
"""

import pandas as pd
import numpy as np
import pickle
from datetime import timedelta
import random
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARÁMETROS FIJOS
# ============================================================================

NUM_POSITIONS = 5
INITIAL_CAPITAL = 100_000
RANDOM_SEED = 42
COMMISSION_PER_SHARE = 0.001
MIN_AGE_DAYS = 63

# Valores de hold time a testear (en minutos)
HOLD_TIMES = [333, 390, 480, 666, 780, 999, 1200]

print("=" * 70)
print("OMNICAPITAL v6 - HOLD TIME SWEEP v2")
print("=" * 70)
print(f"\nTesteando {len(HOLD_TIMES)} valores de hold time...")
print(f"Rango: {min(HOLD_TIMES)} a {max(HOLD_TIMES)} minutos")
print()


def load_data():
    cache_file = 'data_cache/dynamic_universe_2000-01-01_2026-02-09.pkl'
    with open(cache_file, 'rb') as f:
        return pickle.load(f)


def get_tradeable_symbols(price_data, date, first_date):
    """Retorna simbolos tradeables"""
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


def minutes_between(date1, date2, price_data):
    """Estima minutos de trading entre dos fechas"""
    # Aproximacion: 390 minutos por dia habil
    days_diff = (date2 - date1).days
    return days_diff * 390


def run_backtest(price_data, hold_minutes):
    """Ejecuta backtest con hold time especifico"""
    
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    
    first_date = all_dates[0]
    
    cash = INITIAL_CAPITAL
    positions = {}  # symbol -> {'shares', 'entry_date', 'entry_price', 'hold_minutes'}
    portfolio_values = []
    trades = []
    
    for i, date in enumerate(all_dates):
        tradeable = get_tradeable_symbols(price_data, date, first_date)
        
        # Calcular valor del portfolio
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price
        
        # Cerrar posiciones expiradas (check por minutos)
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            minutes_held = minutes_between(pos['entry_date'], date, price_data)
            
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
        
        # Cerrar posiciones que ya no son tradeables
        for symbol in list(positions.keys()):
            if symbol not in tradeable:
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    cash += positions[symbol]['shares'] * exit_price
                del positions[symbol]
        
        # Abrir nuevas posiciones
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
                                'entry_date': date,
                                'hold_minutes': hold_minutes
                            }
                            cash -= cost + commission
        
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions)
        })
    
    # Calcular metricas
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
    
    return {
        'hold_minutes': hold_minutes,
        'hold_hours': hold_minutes / 60,
        'cagr': cagr,
        'final': final,
        'sharpe': sharpe,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'win_rate': win_rate,
        'trades': len(trades_df),
        'volatility': volatility
    }


# ============================================================================
# SWEEP
# ============================================================================

print("Cargando datos...")
price_data = load_data()
print(f"Datos cargados: {len(price_data)} simbolos\n")

results = []
for hold_minutes in HOLD_TIMES:
    print(f"Testeando HOLD_MINUTES = {hold_minutes} (~{hold_minutes/60:.1f} horas)...")
    
    result = run_backtest(price_data, hold_minutes)
    results.append(result)
    
    print(f"  CAGR: {result['cagr']:.2%} | Final: ${result['final']:,.0f} | "
          f"Sharpe: {result['sharpe']:.2f} | Max DD: {result['max_drawdown']:.1%} | "
          f"Trades: {result['trades']:,}")

# Tabla
print("\n" + "=" * 100)
print("RESULTADOS - HOLD TIME SWEEP")
print("=" * 100)
print(f"{'Hold (min)':<12} {'Hold (h)':<10} {'CAGR':<10} {'Final':<15} {'Sharpe':<8} {'Calmar':<8} {'Max DD':<10} {'Trades':<10}")
print("-" * 100)

for r in results:
    print(f"{r['hold_minutes']:<12} {r['hold_hours']:<10.1f} {r['cagr']:<10.2%} "
          f"${r['final']:<14,.0f} {r['sharpe']:<8.2f} {r['calmar']:<8.2f} "
          f"{r['max_drawdown']:<10.1%} {r['trades']:<10,}")

# Optimos
best_cagr = max(results, key=lambda x: x['cagr'])
best_sharpe = max(results, key=lambda x: x['sharpe'])
best_calmar = max(results, key=lambda x: x['calmar'])

print("\n" + "=" * 100)
print("OPTIMOS")
print("=" * 100)
print(f"MEJOR CAGR:   {best_cagr['hold_minutes']} min ({best_cagr['hold_hours']:.1f}h) = {best_cagr['cagr']:.2%}")
print(f"MEJOR SHARPE: {best_sharpe['hold_minutes']} min ({best_sharpe['hold_hours']:.1f}h) = {best_sharpe['sharpe']:.2f}")
print(f"MEJOR CALMAR: {best_calmar['hold_minutes']} min ({best_calmar['hold_hours']:.1f}h) = {best_calmar['calmar']:.2f}")

# Comparar 666
result_666 = [r for r in results if r['hold_minutes'] == 666]
if result_666:
    r = result_666[0]
    cagr_rank = sorted([x['cagr'] for x in results], reverse=True).index(r['cagr']) + 1
    sharpe_rank = sorted([x['sharpe'] for x in results], reverse=True).index(r['sharpe']) + 1
    print(f"\n666 minutos:  CAGR = {r['cagr']:.2%} (Rank #{cagr_rank}), Sharpe = {r['sharpe']:.2f} (Rank #{sharpe_rank})")

# Guardar
with open('results_holdtime_sweep_v2.pkl', 'wb') as f:
    pickle.dump(results, f)

print(f"\nGuardado en: results_holdtime_sweep_v2.pkl")
