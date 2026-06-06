"""
OmniCapital v6 - Fixed Stocks Test
Las mismas 5 acciones tradeadas repetidamente con la regla de 1200 minutos.
Compara buy-and-hold vs rotación dinámica.
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

HOLD_MINUTES = 1200  # 20 horas
NUM_POSITIONS = 5
INITIAL_CAPITAL = 100_000
RANDOM_SEED = 42
COMMISSION_PER_SHARE = 0.001
MIN_AGE_DAYS = 63

# 5 acciones fijas seleccionadas (diversificadas por sector)
FIXED_STOCKS = ['AAPL', 'MSFT', 'JPM', 'JNJ', 'XOM']  # Tech, Tech, Financials, Health, Energy

print("=" * 70)
print("OMNICAPITAL v6 - FIXED STOCKS TEST")
print("=" * 70)
print(f"\nLas 5 acciones fijas: {', '.join(FIXED_STOCKS)}")
print(f"Hold time: {HOLD_MINUTES} minutos ({HOLD_MINUTES/60:.1f} horas)")
print(f"\nTesteando: Rotación continua en las mismas 5 acciones")
print()


def load_data():
    cache_file = 'data_cache/dynamic_universe_2000-01-01_2026-02-09.pkl'
    with open(cache_file, 'rb') as f:
        return pickle.load(f)


def get_tradeable(price_data, date, first_date):
    """Retorna símbolos tradeables"""
    tradeable = []
    for symbol, df in price_data.items():
        if date not in df.index:
            continue
        symbol_first = df.index[0]
        days = (date - symbol_first).days
        if date <= first_date + timedelta(days=30) or days >= MIN_AGE_DAYS:
            tradeable.append(symbol)
    return tradeable


def minutes_held(entry_date, current_date):
    return (current_date - entry_date).days * 390


def run_backtest_fixed(price_data, fixed_stocks):
    """Backtest con acciones fijas"""
    
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    first_date = all_dates[0]
    
    cash = INITIAL_CAPITAL
    positions = {}  # symbol -> {'shares', 'entry_date', 'entry_price'}
    portfolio_values = []
    trades = []
    
    print(f"Tradeando solo: {', '.join(fixed_stocks)}")
    
    for i, date in enumerate(all_dates):
        # Solo considerar las 5 acciones fijas si están disponibles
        available_fixed = [s for s in fixed_stocks if s in price_data and date in price_data[s].index]
        
        # Verificar antigüedad para cada acción fija
        tradeable_fixed = []
        for s in available_fixed:
            symbol_first = price_data[s].index[0]
            days = (date - symbol_first).days
            if date <= first_date + timedelta(days=30) or days >= MIN_AGE_DAYS:
                tradeable_fixed.append(s)
        
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
                    trades.append({'pnl': (price - entry) * shares - commission, 'symbol': sym})
                del positions[sym]
        
        # Cerrar si ya no es tradeable (delisting, etc.)
        for sym in list(positions.keys()):
            if sym not in tradeable_fixed:
                if sym in price_data and date in price_data[sym].index:
                    cash += positions[sym]['shares'] * price_data[sym].loc[date, 'Close']
                del positions[sym]
        
        # Abrir nuevas posiciones en las acciones fijas disponibles
        needed = NUM_POSITIONS - len(positions)
        
        if needed > 0 and cash > 1000:
            # Solo de las acciones fijas que no están en posiciones
            available_for_entry = [s for s in tradeable_fixed if s not in positions]
            
            if len(available_for_entry) >= needed:
                # Selección aleatoria de las disponibles
                random.seed(RANDOM_SEED + date.toordinal())
                selected = random.sample(available_for_entry, needed)
                
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
                                'entry_date': date
                            }
                            cash -= cost + comm
        
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'available_fixed': len(tradeable_fixed)
        })
        
        if i % 252 == 0 and i > 0:
            year = i // 252
            print(f"  Año {year}: ${portfolio_value:,.0f} | Pos: {len(positions)}/5 | "
                  f"Disponibles: {len(tradeable_fixed)}/5")
    
    return portfolio_values, trades


def run_backtest_buy_and_hold(price_data, fixed_stocks):
    """Buy and hold simple de las 5 acciones"""
    
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    first_date = all_dates[0]
    
    # Encontrar primera fecha donde todas las acciones están disponibles
    start_idx = 0
    for i, date in enumerate(all_dates):
        available = [s for s in fixed_stocks 
                     if s in price_data 
                     and date in price_data[s].index
                     and (date - price_data[s].index[0]).days >= MIN_AGE_DAYS]
        if len(available) == len(fixed_stocks):
            start_idx = i
            break
    
    start_date = all_dates[start_idx]
    print(f"\nBuy & Hold iniciando: {start_date.strftime('%Y-%m-%d')}")
    
    # Calcular posiciones iniciales
    capital_per_stock = INITIAL_CAPITAL / len(fixed_stocks)
    shares = {}
    total_cost = 0
    
    for sym in fixed_stocks:
        if sym in price_data and start_date in price_data[sym].index:
            price = price_data[sym].loc[start_date, 'Close']
            shares[sym] = capital_per_stock / price
            total_cost += capital_per_stock
    
    print(f"Compradas {len(shares)} acciones con ${total_cost:,.0f}")
    
    # Valorizar a lo largo del tiempo
    portfolio_values = []
    
    for date in all_dates[start_idx:]:
        portfolio_value = 0
        for sym, share_count in shares.items():
            if sym in price_data and date in price_data[sym].index:
                portfolio_value += share_count * price_data[sym].loc[date, 'Close']
        
        portfolio_values.append({'date': date, 'value': portfolio_value})
    
    return portfolio_values


def calculate_metrics(portfolio_values, trades=None):
    df = pd.DataFrame(portfolio_values).set_index('date')
    
    initial, final = df['value'].iloc[0], df['value'].iloc[-1]
    years = len(df) / 252
    cagr = (final / initial) ** (1/years) - 1
    
    returns = df['value'].pct_change().dropna()
    vol = returns.std() * np.sqrt(252)
    
    rolling_max = df['value'].expanding().max()
    max_dd = ((df['value'] - rolling_max) / rolling_max).min()
    
    sharpe = cagr / vol if vol > 0 else 0
    
    win_rate = 0
    if trades and len(trades) > 0:
        trades_df = pd.DataFrame(trades)
        win_rate = (trades_df['pnl'] > 0).mean()
    
    return {
        'cagr': cagr, 'final': final, 'sharpe': sharpe,
        'max_drawdown': max_dd, 'win_rate': win_rate,
        'trades': len(trades) if trades else 0
    }


print("Cargando datos...")
price_data = load_data()
print(f"{len(price_data)} símbolos\n")

# Test 1: Rotación continua en las mismas 5 acciones
print("=" * 70)
print("TEST 1: ROTACIÓN CONTINUA EN 5 ACCIONES FIJAS")
print("=" * 70)
portfolio_values_rot, trades_rot = run_backtest_fixed(price_data, FIXED_STOCKS)
metrics_rot = calculate_metrics(portfolio_values_rot, trades_rot)

# Test 2: Buy and hold simple
print("\n" + "=" * 70)
print("TEST 2: BUY & HOLD SIMPLE")
print("=" * 70)
portfolio_values_bh = run_backtest_buy_and_hold(price_data, FIXED_STOCKS)
metrics_bh = calculate_metrics(portfolio_values_bh)

# Resultados
print("\n" + "=" * 70)
print("RESULTADOS COMPARATIVOS")
print("=" * 70)
print(f"\n{'Estrategia':<35} {'CAGR':<12} {'Final':<15} {'Sharpe':<10} {'Max DD':<10}")
print("-" * 80)
print(f"{'Rotación 1200min (5 fijas)':<35} {metrics_rot['cagr']:<12.2%} ${metrics_rot['final']:<14,.0f} "
      f"{metrics_rot['sharpe']:<10.2f} {metrics_rot['max_drawdown']:<10.1%}")
print(f"{'Buy & Hold (5 fijas)':<35} {metrics_bh['cagr']:<12.2%} ${metrics_bh['final']:<14,.0f} "
      f"{metrics_bh['sharpe']:<10.2f} {metrics_bh['max_drawdown']:<10.1%}")

print("\n" + "=" * 70)
print("COMPARATIVA CON VERSIÓN ALEATORIA")
print("=" * 70)
print(f"\n{'Estrategia':<35} {'CAGR':<12} {'Sharpe':<10}")
print("-" * 60)
print(f"{'Aleatorio puro (universo dinámico)':<35} {'15.11%':<12} {'0.73':<10}")
print(f"{'Rotación 5 fijas':<35} {f"{metrics_rot['cagr']:.2%}":<12} {f"{metrics_rot['sharpe']:.2f}":<10}")
print(f"{'Buy & Hold 5 fijas':<35} {f"{metrics_bh['cagr']:.2%}":<12} {f"{metrics_bh['sharpe']:.2f}":<10}")

# Análisis por acción
print("\n" + "=" * 70)
print("ANÁLISIS POR ACCIÓN (en rotación)")
print("=" * 70)
if trades_rot:
    trades_df = pd.DataFrame(trades_rot)
    for sym in FIXED_STOCKS:
        sym_trades = trades_df[trades_df['symbol'] == sym]
        if len(sym_trades) > 0:
            win_rate = (sym_trades['pnl'] > 0).mean()
            avg_pnl = sym_trades['pnl'].mean()
            print(f"  {sym}: {len(sym_trades)} trades, Win rate: {win_rate:.1%}, Avg P&L: ${avg_pnl:.2f}")

with open('results_v6_fixed_stocks.pkl', 'wb') as f:
    pickle.dump({
        'fixed_stocks': FIXED_STOCKS,
        'metrics_rotation': metrics_rot,
        'metrics_buyhold': metrics_bh,
        'portfolio_values_rotation': portfolio_values_rot,
        'portfolio_values_buyhold': portfolio_values_bh
    }, f)

print(f"\n\nGuardado en: results_v6_fixed_stocks.pkl")
