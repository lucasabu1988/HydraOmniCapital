"""
OMNICAPITAL v8.0 - CORE EDITION
Version optimizada con todas las mejoras principales
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
import os
import warnings
warnings.filterwarnings('ignore')

# Configuracion
INITIAL_CAPITAL = 100_000
DAILY_POSITIONS = 10
MAX_POSITIONS = 100
MAX_VOLATILITY_FILTER = 0.80  # Permitir mas volatilidad
MAX_MOMENTUM_FILTER = -0.50     # Permitir momentum mas negativo
MIN_PRICE_FILTER = 5.0          # Permitir precios mas bajos
DAILY_MINUTES = 390

# Hold periods
HOLD_PERIODS = {
    'overnight': 390,
    'short': 666,      # Default - buen balance
    'medium': 999,     # Reducido de 1332
    'long': 1332,      # Reducido de 1998
}

# Seasonality weights (por hora desde apertura)
SEASONALITY_WEIGHTS = [5, 15, 20, 15, 15, 20, 10]

# Regime multipliers
REGIME_THRESHOLDS = [0.15, 0.25, 0.35]
REGIME_MULTIPLIERS = [1.0, 0.75, 0.50, 0.0]

UNIVERSE = [
    'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'NVDA', 'TSLA', 'AVGO', 'WMT', 'JPM',
    'V', 'MA', 'UNH', 'HD', 'PG', 'BAC', 'KO', 'PEP', 'MRK', 'ABBV',
    'PFE', 'JNJ', 'CVX', 'XOM', 'TMO', 'ABT', 'CRM', 'ADBE', 'ACN', 'COST',
    'NKE', 'DIS', 'VZ', 'WFC', 'TXN', 'DHR', 'PM', 'NEE', 'AMD', 'BRK-B'
]

def get_scalar(value):
    if hasattr(value, 'iloc'):
        return float(value.iloc[0])
    return float(value)

def calculate_volatility(data, symbol, date_str, lookback=20):
    try:
        symbol_data = data.get(symbol, {})
        dates = sorted(symbol_data.keys())
        if date_str not in dates:
            return 0.20
        idx = dates.index(date_str)
        if idx < lookback:
            return 0.20
        prices = [symbol_data[dates[i]]['close'] for i in range(idx - lookback, idx)]
        returns = np.diff(prices) / prices[:-1]
        if len(returns) < 5:
            return 0.20
        vol = np.std(returns) * np.sqrt(252)
        return max(0.05, min(vol, 1.0))
    except:
        return 0.20

def calculate_momentum(data, symbol, date_str, lookback=20):
    try:
        symbol_data = data.get(symbol, {})
        dates = sorted(symbol_data.keys())
        if date_str not in dates:
            return 0.0
        idx = dates.index(date_str)
        if idx < lookback:
            return 0.0
        current = symbol_data[dates[idx]]['close']
        past = symbol_data[dates[idx - lookback]]['close']
        return (current - past) / past
    except:
        return 0.0

def smart_random_selection(data, date_str, n_positions=5):
    """Filtrar lo peor, seleccionar aleatoriamente del resto"""
    candidates = []
    
    for symbol in UNIVERSE:
        if symbol not in data or date_str not in data[symbol]:
            continue
        
        vol = calculate_volatility(data, symbol, date_str, 20)
        mom = calculate_momentum(data, symbol, date_str, 20)
        price = data[symbol][date_str]['close']
        
        # Filtros
        if vol > MAX_VOLATILITY_FILTER:
            continue
        if mom < MAX_MOMENTUM_FILTER:
            continue
        if price < MIN_PRICE_FILTER:
            continue
        
        candidates.append(symbol)
    
    n = min(n_positions, len(candidates))
    if n == 0:
        return []
    
    return random.sample(candidates, n)

def get_seasonality_entry_minute():
    """Seleccionar minuto basado en seasonality"""
    weights = SEASONALITY_WEIGHTS
    hours = list(range(len(weights)))
    selected_hour = random.choices(hours, weights=weights, k=1)[0]
    
    if selected_hour == 5:
        minute = random.randint(0, 89)
    elif selected_hour == 6:
        minute = 270 + random.randint(0, 29)
    else:
        minute = selected_hour * 60 + random.randint(0, 59)
    
    return min(minute, DAILY_MINUTES - 1)

def get_regime_multiplier(portfolio_vol):
    """Obtener multiplicador segun regimen de volatilidad"""
    for i, threshold in enumerate(REGIME_THRESHOLDS):
        if portfolio_vol < threshold:
            return REGIME_MULTIPLIERS[i]
    return REGIME_MULTIPLIERS[-1]

def select_hold_period(data, symbol, date_str):
    """Seleccionar periodo de hold segun volatilidad"""
    vol = calculate_volatility(data, symbol, date_str, 20)
    
    if vol < 0.20:
        return HOLD_PERIODS['long']
    elif vol < 0.30:
        return HOLD_PERIODS['medium']
    elif vol < 0.40:
        return HOLD_PERIODS['short']
    else:
        return HOLD_PERIODS['overnight']

def simulate_intraday_price(open_p, high, low, close, minute):
    """Simular precio intradia"""
    progress = minute / DAILY_MINUTES
    base = open_p + (close - open_p) * progress
    
    if high > low:
        np.random.seed(int(base * 10000) % 2**32)
        noise = np.random.uniform(-0.3, 0.3)
        variation = (high - low) * noise
        price = base + variation
        return max(low, min(high, price))
    return base

def download_data(start, end):
    """Descargar datos"""
    print("Descargando datos...")
    data = {}
    
    for symbol in UNIVERSE:
        try:
            df = yf.download(symbol, start=start, end=end, progress=False)
            if len(df) > 100:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                data[symbol] = {}
                for idx, row in df.iterrows():
                    date_str = idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx)[:10]
                    data[symbol][date_str] = {
                        'open': get_scalar(row['Open']),
                        'high': get_scalar(row['High']),
                        'low': get_scalar(row['Low']),
                        'close': get_scalar(row['Close'])
                    }
        except:
            pass
    
    print(f"  Datos: {len(data)} simbolos")
    return data

def run_backtest(start_date='2000-01-01', end_date='2026-02-09'):
    """Ejecutar backtest v8.0"""
    
    print("=" * 80)
    print("OMNICAPITAL v8.0 - CORE EDITION")
    print("=" * 80)
    print("Mejoras implementadas:")
    print("  [OK] Smart Random Selection")
    print("  [OK] Continuous Entry (5 posiciones/dia)")
    print("  [OK] Intraday Seasonality")
    print("  [OK] Volatility Regime")
    print("  [OK] Multi-Horizon Hold")
    print("=" * 80)
    
    random.seed(888)
    np.random.seed(888)
    
    # Descargar datos
    data = download_data(start_date, end_date)
    
    # Fechas de trading
    all_dates = sorted(set().union(*[set(d.keys()) for d in data.values()]))
    all_dates = [d for d in all_dates if start_date <= d <= end_date]
    
    print(f"Dias de trading: {len(all_dates)}")
    print("=" * 80)
    
    # Estado
    cash = INITIAL_CAPITAL
    positions = []
    trades = []
    portfolio_values = []
    
    for i, date_str in enumerate(all_dates):
        date = datetime.strptime(date_str, '%Y-%m-%d')
        
        # Calcular valor del portafolio para volatilidad
        positions_value = 0
        for pos in positions:
            if pos['symbol'] in data and date_str in data[pos['symbol']]:
                positions_value += pos['shares'] * data[pos['symbol']][date_str]['close']
        
        portfolio_value = cash + positions_value
        
        # Calcular volatilidad del portafolio (simplificado)
        portfolio_vol = 0.20  # Default
        if len(portfolio_values) >= 20:
            recent_values = [p['portfolio_value'] for p in portfolio_values[-20:]]
            returns = np.diff(recent_values) / recent_values[:-1]
            portfolio_vol = np.std(returns) * np.sqrt(252) if len(returns) > 1 else 0.20
        
        regime_mult = get_regime_multiplier(portfolio_vol)
        
        # Cerrar posiciones que expiran
        positions_to_close = [p for p in positions if p['exit_date'] == date_str]
        
        for pos in positions_to_close:
            if pos['symbol'] in data and date_str in data[pos['symbol']]:
                day_data = data[pos['symbol']][date_str]
                exit_price = simulate_intraday_price(
                    day_data['open'], day_data['high'],
                    day_data['low'], day_data['close'],
                    pos['exit_minute']
                )
                
                proceeds = pos['shares'] * exit_price
                pnl = proceeds - (pos['shares'] * pos['entry_price'])
                pnl_pct = (exit_price - pos['entry_price']) / pos['entry_price']
                
                cash += proceeds
                
                trades.append({
                    'date': date_str,
                    'symbol': pos['symbol'],
                    'action': 'SELL',
                    'price': exit_price,
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'hold_minutes': pos['hold_minutes']
                })
        
        positions = [p for p in positions if p['exit_date'] != date_str]
        
        # Abrir nuevas posiciones
        if len(positions) < MAX_POSITIONS and regime_mult > 0:
            selected = smart_random_selection(data, date_str, DAILY_POSITIONS)
            
            if selected:
                capital_for_new = cash * 0.95 * regime_mult
                capital_per_position = capital_for_new / len(selected)
                
                for symbol in selected:
                    if symbol not in data or date_str not in data[symbol]:
                        continue
                    
                    day_data = data[symbol][date_str]
                    entry_price = day_data['open']
                    
                    if entry_price <= 0:
                        continue
                    
                    shares = capital_per_position / entry_price
                    cost = shares * entry_price
                    
                    if cost > cash or cost < 1000:
                        continue
                    
                    entry_minute = get_seasonality_entry_minute()
                    hold_minutes = select_hold_period(data, symbol, date_str)
                    
                    total_minutes = entry_minute + hold_minutes
                    days_later = total_minutes // DAILY_MINUTES
                    exit_minute = total_minutes % DAILY_MINUTES
                    
                    exit_date = date
                    days_counted = 0
                    while days_counted < days_later:
                        exit_date += timedelta(days=1)
                        if exit_date.weekday() < 5:
                            days_counted += 1
                    
                    positions.append({
                        'symbol': symbol,
                        'entry_date': date_str,
                        'exit_date': exit_date.strftime('%Y-%m-%d'),
                        'entry_price': entry_price,
                        'shares': shares,
                        'entry_minute': entry_minute,
                        'exit_minute': exit_minute,
                        'hold_minutes': hold_minutes
                    })
                    
                    cash -= cost
                    
                    trades.append({
                        'date': date_str,
                        'symbol': symbol,
                        'action': 'BUY',
                        'price': entry_price,
                        'hold_minutes': hold_minutes
                    })
        
        # Recalcular valor
        positions_value = sum(
            pos['shares'] * data[pos['symbol']][date_str]['close']
            for pos in positions
            if pos['symbol'] in data and date_str in data[pos['symbol']]
        )
        portfolio_value = cash + positions_value
        
        portfolio_values.append({
            'date': date_str,
            'portfolio_value': portfolio_value,
            'cash': cash,
            'positions_count': len(positions),
            'regime_mult': regime_mult
        })
        
        if i % 252 == 0 or i == len(all_dates) - 1:
            print(f"[{date_str}] Valor: ${portfolio_value:>12,.2f} | "
                  f"Pos: {len(positions):>2} | Regime: {regime_mult:.0%}")
    
    # Resultados
    print_results(portfolio_values, trades)
    save_results(portfolio_values, trades)

def print_results(portfolio_values, trades):
    df = pd.DataFrame(portfolio_values)
    df['date'] = pd.to_datetime(df['date'])
    
    initial = INITIAL_CAPITAL
    final = df['portfolio_value'].iloc[-1]
    total_return = (final - initial) / initial
    years = len(df) / 252
    
    print("\n" + "=" * 80)
    print("RESULTADOS FINALES - OMNICAPITAL v8.0 CORE")
    print("=" * 80)
    
    print(f"\n>> CAPITAL")
    print(f"   Inicial:              ${initial:>15,.2f}")
    print(f"   Final:                ${final:>15,.2f}")
    print(f"   P/L Total:            ${final - initial:>+15,.2f}")
    print(f"   Retorno Total:        {total_return:>+15.2%}")
    
    if years > 0:
        cagr = (1 + total_return) ** (1 / years) - 1
        print(f"   Anos:                 {years:>15.1f}")
        print(f"   CAGR:                 {cagr:>+15.2%}")
    
    df['returns'] = df['portfolio_value'].pct_change()
    volatility = df['returns'].std() * np.sqrt(252)
    
    rolling_max = df['portfolio_value'].expanding().max()
    drawdown = (df['portfolio_value'] - rolling_max) / rolling_max
    max_dd = drawdown.min()
    
    sharpe = (df['returns'].mean() * 252 - 0.02) / volatility if volatility > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    
    print(f"\n>> RIESGO")
    print(f"   Volatilidad:          {volatility:>15.2%}")
    print(f"   Maximo Drawdown:      {max_dd:>15.2%}")
    print(f"   Sharpe Ratio:         {sharpe:>15.2f}")
    print(f"   Calmar Ratio:         {calmar:>15.2f}")
    
    trades_df = pd.DataFrame(trades)
    sells = trades_df[trades_df['action'] == 'SELL']
    
    if len(sells) > 0:
        win_rate = (sells['pnl_pct'] > 0).mean()
        avg_pnl = sells['pnl_pct'].mean()
        wins = sells[sells['pnl_pct'] > 0]['pnl_pct']
        losses = sells[sells['pnl_pct'] < 0]['pnl_pct']
        
        print(f"\n>> TRADING")
        print(f"   Total Operaciones:    {len(sells):>15}")
        print(f"   Win Rate:             {win_rate:>15.1%}")
        print(f"   P/L Promedio:         {avg_pnl:>+15.2%}")
        if len(wins) > 0:
            print(f"   Ganancia Promedio:    {wins.mean():>+15.2%}")
        if len(losses) > 0:
            print(f"   Perdida Promedio:     {losses.mean():>+15.2%}")
        if len(losses) > 0 and losses.sum() != 0:
            pf = abs(wins.sum() / losses.sum()) if len(wins) > 0 else 0
            print(f"   Profit Factor:        {pf:>15.2f}")
    
    print("=" * 80)

def save_results(portfolio_values, trades):
    os.makedirs('backtests', exist_ok=True)
    pd.DataFrame(portfolio_values).to_csv('backtests/backtest_v8_core_results.csv', index=False)
    pd.DataFrame(trades).to_csv('backtests/trades_v8_core.csv', index=False)
    print("\nResultados guardados en backtests/")

if __name__ == "__main__":
    print("\n>>> OMNICAPITAL v8.0 - CORE EDITION <<<")
    run_backtest()
