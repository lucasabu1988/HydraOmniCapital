"""
OmniCapital v6 - Hybrid Optimized
Combina:
1. Momentum Filter (SMA20 > SMA50)
2. Weekend Effect (priorizar entradas viernes)
3. Hold time optimo: 1200 minutos
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

# Parámetros de optimización
MOMENTUM_ENABLED = True  # Filtro de momentum SMA20 > SMA50
WEEKEND_BOOST = True     # Boost en viernes
WEEKEND_MULTIPLIER = 1.5  # 1.5x sizing los viernes

print("=" * 70)
print("OMNICAPITAL v6 - HYBRID OPTIMIZED")
print("=" * 70)
print(f"\nOptimizaciones aplicadas:")
print(f"  1. Momentum Filter (SMA20 > SMA50): {'ON' if MOMENTUM_ENABLED else 'OFF'}")
print(f"  2. Weekend Effect (viernes {WEEKEND_MULTIPLIER}x sizing): {'ON' if WEEKEND_BOOST else 'OFF'}")
print(f"  3. Hold time: {HOLD_MINUTES} minutos ({HOLD_MINUTES/60:.1f} horas)")
print()


def load_data():
    cache_file = 'data_cache/dynamic_universe_2000-01-01_2026-02-09.pkl'
    with open(cache_file, 'rb') as f:
        return pickle.load(f)


def calculate_sma(df, window):
    """Calcula Simple Moving Average"""
    return df['Close'].rolling(window=window).mean()


def get_tradeable(price_data, date, first_date, with_momentum=False):
    """Retorna símbolos tradeables, opcionalmente con filtro de momentum"""
    tradeable = []
    
    for symbol, df in price_data.items():
        if date not in df.index:
            continue
        
        symbol_first = df.index[0]
        days = (date - symbol_first).days
        
        # Check antigüedad
        if not (date <= first_date + timedelta(days=30) or days >= MIN_AGE_DAYS):
            continue
        
        # Check momentum (opcional)
        if with_momentum:
            # Calcular SMAs hasta la fecha actual
            hist_data = df[df.index <= date]
            if len(hist_data) < 50:
                continue
            
            sma20 = hist_data['Close'].rolling(20).mean().iloc[-1]
            sma50 = hist_data['Close'].rolling(50).mean().iloc[-1]
            
            if pd.isna(sma20) or pd.isna(sma50):
                continue
            
            # Solo incluir si SMA20 > SMA50 (tendencia alcista)
            if sma20 <= sma50:
                continue
        
        tradeable.append(symbol)
    
    return tradeable


def minutes_held(entry_date, current_date):
    return (current_date - entry_date).days * 390


def run_backtest(price_data):
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    first_date = all_dates[0]
    
    cash = INITIAL_CAPITAL
    positions = {}  # symbol -> {'shares', 'entry_date', 'entry_price', 'is_weekend_boost'}
    portfolio_values = []
    trades = []
    
    stats = {
        'momentum_filtered': 0,
        'weekend_trades': 0,
        'normal_trades': 0
    }
    
    for i, date in enumerate(all_dates):
        # Obtener símbolos tradeables con momentum filter
        tradeable = get_tradeable(price_data, date, first_date, with_momentum=MOMENTUM_ENABLED)
        
        # Calcular valor del portfolio
        portfolio_value = cash
        for sym, pos in list(positions.items()):
            if sym in price_data and date in price_data[sym].index:
                portfolio_value += pos['shares'] * price_data[sym].loc[date, 'Close']
        
        # Cerrar posiciones expiradas
        for sym in list(positions.keys()):
            if minutes_held(positions[sym]['entry_date'], date) >= HOLD_MINUTES:
                if sym in price_data and date in price_data[sym].index:
                    price = price_data[sym].loc[date, 'Close']
                    shares = positions[sym]['shares']
                    proceeds = shares * price
                    commission = shares * COMMISSION_PER_SHARE
                    cash += proceeds - commission
                    
                    entry = positions[sym]['entry_price']
                    pnl = (price - entry) * shares - commission
                    trades.append({'pnl': pnl, 'weekend_boost': positions[sym].get('is_weekend_boost', False)})
                del positions[sym]
        
        # Cerrar no tradeables
        for sym in list(positions.keys()):
            if sym not in tradeable:
                if sym in price_data and date in price_data[sym].index:
                    cash += positions[sym]['shares'] * price_data[sym].loc[date, 'Close']
                del positions[sym]
        
        # Abrir nuevas posiciones
        needed = NUM_POSITIONS - len(positions)
        
        if needed > 0 and cash > 1000 and len(tradeable) >= needed:
            available_for_entry = [s for s in tradeable if s not in positions]
            
            if len(available_for_entry) >= needed:
                random.seed(RANDOM_SEED + date.toordinal())
                selected = random.sample(available_for_entry, needed)
                
                # Determinar sizing base
                is_friday = (date.weekday() == 4) and WEEKEND_BOOST
                position_multiplier = WEEKEND_MULTIPLIER if is_friday else 1.0
                
                position_value = (portfolio_value * 0.95) / NUM_POSITIONS * position_multiplier
                
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
                                'is_weekend_boost': is_friday
                            }
                            cash -= cost + comm
                            
                            if is_friday:
                                stats['weekend_trades'] += 1
                            else:
                                stats['normal_trades'] += 1
        
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions)
        })
        
        if i % 252 == 0 and i > 0:
            year = i // 252
            print(f"  Año {year}: ${portfolio_value:,.0f} | Pos: {len(positions)}/5 | Tradeable: {len(tradeable)}")
    
    return portfolio_values, trades, stats


def calculate_metrics(portfolio_values, trades, stats):
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
    
    # Análisis de weekend boost
    weekend_trades = trades_df[trades_df['weekend_boost'] == True] if len(trades_df) > 0 else pd.DataFrame()
    normal_trades = trades_df[trades_df['weekend_boost'] == False] if len(trades_df) > 0 else pd.DataFrame()
    
    return {
        'cagr': cagr, 'final': final, 'sharpe': sharpe, 'calmar': calmar,
        'max_drawdown': max_dd, 'win_rate': win_rate, 'trades': len(trades_df),
        'weekend_win_rate': (weekend_trades['pnl'] > 0).mean() if len(weekend_trades) > 0 else 0,
        'normal_win_rate': (normal_trades['pnl'] > 0).mean() if len(normal_trades) > 0 else 0,
        'stats': stats
    }


print("Cargando datos...")
price_data = load_data()
print(f"{len(price_data)} símbolos\n")

print("Ejecutando backtest con optimizaciones...")
portfolio_values, trades, stats = run_backtest(price_data)
metrics = calculate_metrics(portfolio_values, trades, stats)

print("\n" + "=" * 70)
print("RESULTADOS - HYBRID OPTIMIZED")
print("=" * 70)
print(f"\nCapital inicial:     ${INITIAL_CAPITAL:>15,.0f}")
print(f"Capital final:       ${metrics['final']:>15,.2f}")
print(f"CAGR:                {metrics['cagr']:>15.2%}")
print(f"Sharpe:              {metrics['sharpe']:>15.2f}")
print(f"Calmar:              {metrics['calmar']:>15.2f}")
print(f"Max DD:              {metrics['max_drawdown']:>15.2%}")
print(f"Win rate:            {metrics['win_rate']:>15.2%}")
print(f"Trades:              {metrics['trades']:>15,}")

print("\n" + "=" * 70)
print("ANÁLISIS DE OPTIMIZACIONES")
print("=" * 70)
print(f"\nTrades normales:     {metrics['stats']['normal_trades']:,}")
print(f"Trades weekend:      {metrics['stats']['weekend_trades']:,}")
print(f"Win rate normal:     {metrics['normal_win_rate']:>15.2%}")
print(f"Win rate weekend:    {metrics['weekend_win_rate']:>15.2%}")

print("\n" + "=" * 70)
print("COMPARATIVA")
print("=" * 70)
print(f"\n{'Versión':<35} {'CAGR':<12} {'Sharpe':<10} {'Mejora':<10}")
print("-" * 70)
print(f"{'Base (1200min aleatorio)':<35} {'15.11%':<12} {'0.73':<10} {'-':<10}")
print(f"{'Hybrid Optimized (esta)':<35} {f"{metrics['cagr']:.2%}":<12} {f"{metrics['sharpe']:.2f}":<10} "
      f"{f"{metrics['cagr']-0.1511:.2%}":<10}")

with open('results_v6_hybrid_optimized.pkl', 'wb') as f:
    pickle.dump({'metrics': metrics, 'portfolio_values': portfolio_values}, f)

print(f"\n\nGuardado en: results_v6_hybrid_optimized.pkl")
