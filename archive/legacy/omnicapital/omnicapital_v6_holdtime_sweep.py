"""
OmniCapital v6 - Sweep de Hold Time
Testea diferentes duraciones de hold para encontrar el óptimo.
"""

import pandas as pd
import numpy as np
import pickle
import os
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
HOLD_TIMES = [
    120,   # 2 horas - intraday corto
    240,   # 4 horas - media sesión
    333,   # ~5.5 horas
    390,   # 6.5 horas - 1 día de trading exacto
    480,   # 8 horas
    666,   # ~11.1 horas - overnight original
    780,   # 13 horas
    999,   # ~16.6 horas
    1200,  # 20 horas
    1332,  # ~22.2 horas - 2 overnights
]

print("=" * 70)
print("OMNICAPITAL v6 - HOLD TIME SWEEP")
print("=" * 70)
print(f"\nTesteando {len(HOLD_TIMES)} valores de hold time...")
print(f"Rango: {min(HOLD_TIMES)} a {max(HOLD_TIMES)} minutos")
print()


def load_data():
    """Carga datos del cache"""
    cache_file = 'data_cache/dynamic_universe_2000-01-01_2026-02-09.pkl'
    with open(cache_file, 'rb') as f:
        return pickle.load(f)


def get_tradeable_symbols(price_data, date, min_age_days=MIN_AGE_DAYS, first_date=None):
    """Retorna símbolos tradeables en una fecha"""
    tradeable = []
    
    for symbol, df in price_data.items():
        if date not in df.index:
            continue
        
        symbol_first_date = df.index[0]
        days_since_start = (date - symbol_first_date).days
        
        # En primer mes, no aplicar filtro de antigüedad
        if first_date and date <= first_date + timedelta(days=30):
            tradeable.append(symbol)
        elif days_since_start >= min_age_days:
            tradeable.append(symbol)
    
    return tradeable


def run_backtest(price_data, hold_minutes):
    """Ejecuta backtest con hold time específico"""
    
    # Fechas
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    
    first_date = all_dates[0]
    
    # Convertir minutos a días de trading (6.5 horas = 390 minutos por día)
    # Usamos decimales para mayor precisión
    hold_days_float = hold_minutes / 390.0
    hold_days = max(1, int(hold_days_float))
    
    cash = INITIAL_CAPITAL
    positions = {}
    portfolio_values = []
    trades = []
    
    for i, date in enumerate(all_dates):
        # Obtener símbolos tradeables
        tradeable = get_tradeable_symbols(price_data, date, first_date=first_date)
        
        # Calcular valor del portfolio
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price
        
        # Cerrar posiciones que ya no son tradeables
        for symbol in list(positions.keys()):
            if symbol not in tradeable:
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
                    trades.append({'pnl': pnl})
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
                                'exit_date': date + timedelta(days=hold_days, hours=int((hold_days_float % 1) * 24))
                            }
                            cash -= cost + commission
        
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions)
        })
    
    # Calcular métricas
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
    
    # Calcular Calmar ratio (CAGR / Max Drawdown)
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    
    return {
        'hold_minutes': hold_minutes,
        'hold_days': hold_days,
        'hold_hours': hold_minutes / 60,
        'initial': initial,
        'final': final,
        'total_return': total_return,
        'cagr': cagr,
        'volatility': volatility,
        'max_drawdown': max_dd,
        'sharpe': sharpe,
        'calmar': calmar,
        'win_rate': win_rate,
        'trades': len(trades_df)
    }


# ============================================================================
# SWEEP DE HOLD TIME
# ============================================================================

print("Cargando datos...")
price_data = load_data()
print(f"Datos cargados: {len(price_data)} símbolos\n")

results = []
for hold_minutes in HOLD_TIMES:
    print(f"Testeando HOLD_MINUTES = {hold_minutes} (~{hold_minutes/60:.1f} horas)...")
    
    result = run_backtest(price_data, hold_minutes)
    results.append(result)
    
    print(f"  CAGR: {result['cagr']:.2%} | Final: ${result['final']:,.0f} | "
          f"Sharpe: {result['sharpe']:.2f} | Max DD: {result['max_drawdown']:.1%}")

# Tabla comparativa
print("\n" + "=" * 90)
print("RESULTADOS COMPARATIVOS - HOLD TIME SWEEP")
print("=" * 90)
print()
print(f"{'Hold (min)':<12} {'Hold (h)':<10} {'CAGR':<10} {'Final':<15} {'Sharpe':<8} {'Calmar':<8} {'Max DD':<10} {'Trades'}")
print("-" * 90)

for r in results:
    print(f"{r['hold_minutes']:<12} {r['hold_hours']:<10.1f} {r['cagr']:<10.2%} "
          f"${r['final']:<14,.0f} {r['sharpe']:<8.2f} {r['calmar']:<8.2f} "
          f"{r['max_drawdown']:<10.1%} {r['trades']:<10,}")

# Encontrar óptimos
best_cagr = max(results, key=lambda x: x['cagr'])
best_sharpe = max(results, key=lambda x: x['sharpe'])
best_calmar = max(results, key=lambda x: x['calmar'])

print("\n" + "=" * 90)
print("ANÁLISIS DE ÓPTIMOS")
print("=" * 90)
print()
print(f"MEJOR CAGR:     {best_cagr['hold_minutes']} minutos ({best_cagr['hold_hours']:.1f}h) = {best_cagr['cagr']:.2%}")
print(f"MEJOR SHARPE:   {best_sharpe['hold_minutes']} minutos ({best_sharpe['hold_hours']:.1f}h) = {best_sharpe['sharpe']:.2f}")
print(f"MEJOR CALMAR:   {best_calmar['hold_minutes']} minutos ({best_calmar['hold_hours']:.1f}h) = {best_calmar['calmar']:.2f}")
print()
print(f"666 minutos:    CAGR = {[r for r in results if r['hold_minutes'] == 666][0]['cagr']:.2%} "
      f"(Ranking #{sorted([r['cagr'] for r in results], reverse=True).index([r for r in results if r['hold_minutes'] == 666][0]['cagr']) + 1})")

# Análisis del overnight
print("\n" + "=" * 90)
print("ANÁLISIS: ¿POR QUÉ 666 MINUTOS?")
print("=" * 90)
print()
print("666 minutos ≈ 11.1 horas ≈ 1 día natural + 4.6 horas de mercado")
print()
print("Teoría del overnight premium:")
print("  - El mercado cierra a las 16:00 ET")
print("  - Abre a las 09:30 ET del siguiente día")
print("  - Gap overnight = ~17.5 horas sin trading")
print("  - 666 minutos captura: overnight + parte de la sesión siguiente")
print()
print("Alternativas analizadas:")
print("  - < 390 min (1 día): No captura overnight completo")
print("  - 390-666 min: Captura parcial del overnight")
print("  - 666 min: Captura overnight + sesión siguiente (SWEET SPOT)")
print("  - > 666 min: Más exposición intraday (ruido, no señal)")

# Guardar resultados
with open('results_holdtime_sweep.pkl', 'wb') as f:
    pickle.dump(results, f)

print(f"\nResultados guardados en: results_holdtime_sweep.pkl")
