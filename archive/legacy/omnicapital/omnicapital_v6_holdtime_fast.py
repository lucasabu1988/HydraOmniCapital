"""
OmniCapital v6 - Optimizacion de Hold Time (Fast)
Sweep enfocado en rangos clave.
"""

import pandas as pd
import numpy as np
import pickle
from datetime import timedelta
import random
import warnings
warnings.filterwarnings('ignore')

NUM_POSITIONS = 5
INITIAL_CAPITAL = 100_000
RANDOM_SEED = 42
COMMISSION_PER_SHARE = 0.001
MIN_AGE_DAYS = 63

# Sweep enfocado
HOLD_TIMES = [390, 480, 570, 666, 780, 900, 1050, 1200, 1350, 1500, 1800, 2100, 2400]

print("=" * 90)
print("OMNICAPITAL v6 - HOLD TIME OPTIMIZATION (FAST)")
print("=" * 90)
print()


def load_data():
    cache_file = 'data_cache/dynamic_universe_2000-01-01_2026-02-09.pkl'
    with open(cache_file, 'rb') as f:
        return pickle.load(f)


def get_tradeable(price_data, date, first_date):
    tradeable = []
    for symbol, df in price_data.items():
        if date not in df.index:
            continue
        first = df.index[0]
        days = (date - first).days
        if date <= first_date + timedelta(days=30) or days >= MIN_AGE_DAYS:
            tradeable.append(symbol)
    return tradeable


def run_backtest(price_data, hold_minutes):
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    first_date = all_dates[0]
    
    cash = INITIAL_CAPITAL
    positions = {}
    values = []
    trades = []
    
    for date in all_dates:
        tradeable = get_tradeable(price_data, date, first_date)
        
        # Valor portfolio
        portval = cash
        for sym, pos in list(positions.items()):
            if sym in price_data and date in price_data[sym].index:
                portval += pos['shares'] * price_data[sym].loc[date, 'Close']
        
        # Cerrar expiradas
        for sym in list(positions.keys()):
            days_held = (date - positions[sym]['entry_date']).days
            if days_held * 390 >= hold_minutes:
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
            if sym not in tradeable:
                if sym in price_data and date in price_data[sym].index:
                    cash += positions[sym]['shares'] * price_data[sym].loc[date, 'Close']
                del positions[sym]
        
        # Abrir nuevas
        needed = NUM_POSITIONS - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable) >= needed:
            available = [s for s in tradeable if s not in positions]
            if len(available) >= needed:
                random.seed(RANDOM_SEED + date.toordinal())
                selected = random.sample(available, needed)
                pos_val = (portval * 0.95) / NUM_POSITIONS
                
                for sym in selected:
                    if sym in price_data and date in price_data[sym].index:
                        price = price_data[sym].loc[date, 'Close']
                        shares = pos_val / price
                        cost = shares * price
                        comm = shares * COMMISSION_PER_SHARE
                        if cost + comm <= cash * 0.95:
                            positions[sym] = {'entry_price': price, 'shares': shares, 'entry_date': date}
                            cash -= cost + comm
        
        values.append({'date': date, 'value': portval})
    
    # Metricas
    df = pd.DataFrame(values).set_index('date')
    initial, final = df['value'].iloc[0], df['value'].iloc[-1]
    years = len(df) / 252
    cagr = (final / initial) ** (1/years) - 1
    vol = df['value'].pct_change().std() * np.sqrt(252)
    max_dd = ((df['value'] - df['value'].expanding().max()) / df['value'].expanding().max()).min()
    sharpe = cagr / vol if vol > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    
    return {
        'hold_minutes': hold_minutes,
        'hold_hours': hold_minutes / 60,
        'cagr': cagr, 'final': final, 'sharpe': sharpe,
        'calmar': calmar, 'max_drawdown': max_dd,
        'win_rate': win_rate, 'trades': len(trades_df)
    }


print("Cargando datos...")
price_data = load_data()
print(f"{len(price_data)} simbolos\n")

results = []
for hm in HOLD_TIMES:
    print(f"Testing {hm} min ({hm/60:.1f}h)...", end=" ")
    r = run_backtest(price_data, hm)
    results.append(r)
    print(f"CAGR: {r['cagr']:.2%}, Sharpe: {r['sharpe']:.2f}")

# Tabla
print("\n" + "=" * 90)
print("RESULTADOS")
print("=" * 90)
print(f"{'Hold':<8} {'Hours':<8} {'CAGR':<10} {'Final':<14} {'Sharpe':<8} {'Calmar':<8} {'MaxDD':<10} {'Trades':<10}")
print("-" * 90)

for r in sorted(results, key=lambda x: x['cagr'], reverse=True):
    print(f"{r['hold_minutes']:<8} {r['hold_hours']:<8.1f} {r['cagr']:<10.2%} ${r['final']:<13,.0f} "
          f"{r['sharpe']:<8.2f} {r['calmar']:<8.2f} {r['max_drawdown']:<10.1%} {r['trades']:<10,}")

# Mejor
best = max(results, key=lambda x: x['cagr'])
print("\n" + "=" * 90)
print(f"OPTIMO: {best['hold_minutes']} minutos ({best['hold_hours']:.1f} horas)")
print(f"  CAGR: {best['cagr']:.2%}")
print(f"  Sharpe: {best['sharpe']:.2f}")
print(f"  Max Drawdown: {best['max_drawdown']:.1%}")
print("=" * 90)

# Guardar
with open('results_holdtime_fast.pkl', 'wb') as f:
    pickle.dump(results, f)
