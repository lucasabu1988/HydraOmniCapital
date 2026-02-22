"""
OmniCapital v6 - Look-Ahead Bias CORREGIDO
Solo tradea símbolos que existían en el momento de la decisión.
Los nuevos símbolos (IPOs) se incorporan cuando cumplen antigüedad mínima.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import random
import pickle
import os
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARÁMETROS
# ============================================================================

HOLD_MINUTES = 666
NUM_POSITIONS = 5
INITIAL_CAPITAL = 100_000
RANDOM_SEED = 42
COMMISSION_PER_SHARE = 0.001

# Antigüedad mínima para considerar un símbolo (evitar IPOs recientes)
MIN_AGE_DAYS = 63  # ~3 meses desde primer día de trading

START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

print("=" * 70)
print("OMNICAPITAL v6 - LOOK-AHEAD BIAS CORREGIDO")
print("=" * 70)
print(f"\nParámetros:")
print(f"  - Hold time: {HOLD_MINUTES} minutos (~{HOLD_MINUTES/60:.1f} horas)")
print(f"  - Posiciones: {NUM_POSITIONS}")
print(f"  - Capital inicial: ${INITIAL_CAPITAL:,.0f}")
print(f"  - Min antigüedad IPO: {MIN_AGE_DAYS} días (~3 meses)")
print(f"  - Universo: SOLO símbolos existentes en cada momento")
print()


def download_data():
    """Descarga datos del universo extendido"""
    cache_file = 'data_cache/dynamic_universe_2000-01-01_2026-02-09.pkl'
    
    if os.path.exists(cache_file):
        print(f"[Cache] Cargando datos...")
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    else:
        raise FileNotFoundError(f"No se encontró: {cache_file}. Ejecutar dynamic_universe primero.")


def get_tradeable_symbols(price_data, date, min_age_days=MIN_AGE_DAYS, first_date_override=None):
    """
    Retorna SOLO los símbolos que podríamos haber conocido en 'date'.
    Un símbolo es tradeable si:
        1. Ya cotizaba en 'date' (tiene datos)
        2. Lleva al menos 'min_age_days' desde su primer día (no es IPO reciente)
    
    Excepción: Si es la primera fecha del backtest, usa todos los disponibles
    para poder empezar a operar.
    """
    tradeable = []
    
    for symbol, df in price_data.items():
        # Check 1: ¿Tiene datos para esta fecha?
        if date not in df.index:
            continue
        
        # Check 2: ¿Cuándo empezó a cotizar?
        first_date = df.index[0]
        days_since_start = (date - first_date).days
        
        # Si es el primer día del backtest, no aplicar filtro de antigüedad
        # para poder empezar a operar inmediatamente
        if first_date_override and date <= first_date_override + timedelta(days=30):
            tradeable.append(symbol)
        elif days_since_start >= min_age_days:
            tradeable.append(symbol)
    
    return tradeable


def run_backtest(price_data):
    """Backtest SIN look-ahead bias"""
    
    print("\n" + "=" * 70)
    print("INICIANDO BACKTEST (Look-Ahead Corregido)")
    print("=" * 70)
    
    # Fechas de trading
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    
    print(f"Total fechas: {len(all_dates)}")
    print(f"Rango: {all_dates[0].strftime('%Y-%m-%d')} a {all_dates[-1].strftime('%Y-%m-%d')}")
    
    hold_days = max(1, HOLD_MINUTES // (6.5 * 60))
    cash = INITIAL_CAPITAL
    positions = {}  # symbol -> {'shares', 'entry_date', 'exit_date', 'entry_price'}
    portfolio_values = []
    trades = []
    
    # Tracking de evolución del universo
    universe_history = []
    
    first_date = all_dates[0]
    
    for i, date in enumerate(all_dates):
        # === CRÍTICO: Solo símbolos que existían en esta fecha ===
        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date_override=first_date)
        
        # Calcular valor del portfolio
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price
        
        # Cerrar posiciones que ya no son tradeables (delisting, etc.)
        for symbol in list(positions.keys()):
            if symbol not in tradeable_symbols:
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
        
        # Abrir nuevas posiciones para alcanzar 5
        needed = NUM_POSITIONS - len(positions)
        
        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= needed:
            # Símbolos disponibles que no están en posiciones
            available_for_entry = [s for s in tradeable_symbols if s not in positions]
            
            if len(available_for_entry) >= needed:
                # Selección aleatoria
                random.seed(RANDOM_SEED + date.toordinal())
                selected = random.sample(available_for_entry, needed)
                
                # Tamaño de posición
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
            'tradeable': len(tradeable_symbols)
        })
        
        # Guardar historia del universo (cada 252 días)
        if i % 252 == 0:
            universe_history.append({
                'date': date,
                'tradeable': len(tradeable_symbols),
                'symbols': tradeable_symbols.copy()
            })
        
        if i % 252 == 0 and i > 0:
            year = i // 252
            print(f"  Año {year}: ${portfolio_value:,.0f} | Pos: {len(positions)}/5 | Tradeable: {len(tradeable_symbols)}")
    
    return portfolio_values, trades, universe_history


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
    price_data = download_data()
    
    portfolio_values, trades, universe_history = run_backtest(price_data)
    metrics = calculate_metrics(portfolio_values, trades)
    
    print("\n" + "=" * 70)
    print("RESULTADOS - LOOK-AHEAD BIAS CORREGIDO")
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
    
    # Mostrar evolución del universo
    print("\n" + "=" * 70)
    print("EVOLUCIÓN DEL UNIVERSO TRADEABLE")
    print("=" * 70)
    print(f"{'Fecha':<12} {'Símbolos':<10} {'Notas'}")
    print("-" * 50)
    
    for uh in universe_history[:15]:  # Primeros 15 años
        date_str = uh['date'].strftime('%Y-%m-%d')
        count = uh['tradeable']
        
        # Detectar nuevos símbolos vs año anterior
        notes = ""
        if count >= 50:
            notes = "Universo maduro"
        elif count >= 40:
            notes = "Buena diversificación"
        elif count >= 30:
            notes = "Diversificación aceptable"
        else:
            notes = "Universo limitado"
        
        print(f"{date_str:<12} {count:<10} {notes}")
    
    # Guardar
    with open('results_v6_look_ahead_fixed.pkl', 'wb') as f:
        pickle.dump({
            'metrics': metrics,
            'portfolio_values': portfolio_values,
            'universe_history': universe_history
        }, f)
    
    print(f"\nGuardado en: results_v6_look_ahead_fixed.pkl")
    
    print("\n" + "=" * 70)
    print("NOTA IMPORTANTE")
    print("=" * 70)
    print("Este backtest NO tiene look-ahead bias.")
    print("Solo usa símbolos que existían en cada momento del tiempo.")
    print("Los nuevos símbolos (IPOs) se incorporan automáticamente")
    print("cuando cumplen la antigüedad mínima.")
    print("=" * 70)
