"""
╔══════════════════════════════════════════════════════════════════════════════╗
║           OMNICAPITAL v6.0 - RANDOM EXACT 666 MINUTES (FAST)                  ║
║                                                                              ║
║  Estrategia completamente aleatoria con hold EXACTO de 666 minutos            ║
║  Versión optimizada usando simulación vectorizada                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
import os
import warnings
warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════════

UNIVERSE = [
    'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'NVDA', 'TSLA', 'AVGO', 'WMT', 'JPM',
    'V', 'MA', 'UNH', 'HD', 'PG', 'BAC', 'KO', 'PEP', 'MRK', 'ABBV',
    'PFE', 'JNJ', 'CVX', 'XOM', 'TMO', 'ABT', 'CRM', 'ADBE', 'ACN', 'COST',
    'NKE', 'DIS', 'VZ', 'WFC', 'TXN', 'DHR', 'PM', 'NEE', 'AMD', 'BRK-B'
]

INITIAL_CAPITAL = 100_000
POSITIONS_PER_DAY = 5
HOLD_MINUTES = 666
DAILY_MINUTES = 390  # 6.5 horas de trading

def download_data(symbols, start, end):
    """Descarga datos para todos los símbolos"""
    print("Descargando datos...")
    data = {}
    for symbol in symbols:
        try:
            df = yf.download(symbol, start=start, end=end, progress=False)
            if len(df) > 100:
                # Aplanar columnas multi-índice si existen
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                data[symbol] = df
        except Exception as e:
            pass
    print(f"Datos descargados: {len(data)} símbolos")
    return data

def get_scalar(value):
    """Extrae valor escalar de Series o scalar"""
    if hasattr(value, 'iloc'):
        return float(value.iloc[0])
    return float(value)

def simulate_intraday_price(open_p, high, low, close, minute_of_day):
    """
    Simula precio intradía usando interpolación Open-Close con variación
    basada en el rango High-Low.
    """
    progress = minute_of_day / DAILY_MINUTES
    
    # Precio base: interpolación Open-Close
    base = open_p + (close - open_p) * progress
    
    # Añadir variación aleatoria dentro del rango del día
    if high > low:
        np.random.seed(int(base * 10000) % 2**32)
        noise = np.random.uniform(-0.3, 0.3)
        variation = (high - low) * noise
        price = base + variation
        # Limitar al rango del día
        return max(low, min(high, price))
    return base

def run_backtest(start_date='2000-01-01', end_date='2026-02-09'):
    """Ejecuta backtest con hold exacto de 666 minutos"""
    
    print("=" * 80)
    print("OMNICAPITAL v6.0 - RANDOM EXACT 666 MINUTES (FAST)")
    print("=" * 80)
    print(f"Periodo: {start_date} a {end_date}")
    print(f"Capital: ${INITIAL_CAPITAL:,.2f}")
    print(f"Hold: {HOLD_MINUTES} minutos exactos ({HOLD_MINUTES/60:.1f} horas)")
    print(f"Posiciones: {POSITIONS_PER_DAY} aleatorias/día")
    print("=" * 80)
    
    # Descargar datos
    data = download_data(UNIVERSE, start_date, end_date)
    if len(data) < 10:
        print("Error: Datos insuficientes")
        return
    
    # Crear matriz de precios unificada
    print("\nProcesando datos...")
    price_data = {}
    for symbol, df in data.items():
        df_dict = {}
        for idx, row in df.iterrows():
            date_str = idx.strftime('%Y-%m-%d') if hasattr(idx, 'strftime') else str(idx)[:10]
            df_dict[date_str] = {
                'open': get_scalar(row['Open']),
                'high': get_scalar(row['High']),
                'low': get_scalar(row['Low']),
                'close': get_scalar(row['Close'])
            }
        price_data[symbol] = df_dict
    
    # Obtener todas las fechas de trading
    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    all_dates = [d for d in all_dates if d >= start_date and d <= end_date]
    
    print(f"Días de trading: {len(all_dates)}")
    print("=" * 80)
    
    # Estado del portafolio
    cash = INITIAL_CAPITAL
    positions = []  # Lista de posiciones activas
    trades = []
    portfolio_values = []
    
    # Random seed fijo para reproducibilidad
    random.seed(666)
    np.random.seed(666)
    
    # Procesar cada día
    for i, date_str in enumerate(all_dates):
        date = datetime.strptime(date_str, '%Y-%m-%d')
        
        # Símbolos disponibles este día
        available = [s for s in price_data.keys() if date_str in price_data[s]]
        
        if len(available) < POSITIONS_PER_DAY:
            continue
        
        # 1. CERRAR POSICIONES QUE EXPIRAN HOY
        positions_to_close = [p for p in positions if p['exit_date'] == date_str]
        
        for pos in positions_to_close:
            symbol = pos['symbol']
            if symbol in available:
                # Calcular precio de salida en el minuto exacto
                day_data = price_data[symbol][date_str]
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
                    'symbol': symbol,
                    'action': 'SELL',
                    'price': exit_price,
                    'shares': pos['shares'],
                    'pnl': pnl,
                    'pnl_pct': pnl_pct,
                    'hold_minutes': HOLD_MINUTES
                })
        
        # Remover posiciones cerradas
        positions = [p for p in positions if p['exit_date'] != date_str]
        
        # 2. ABRIR NUEVAS POSICIONES ALEATORIAS
        # Capital para nuevas posiciones (95% del cash disponible)
        capital_for_new = cash * 0.95
        capital_per_pos = capital_for_new / POSITIONS_PER_DAY
        
        # Seleccionar símbolos aleatorios
        selected = random.sample(available, POSITIONS_PER_DAY)
        
        for symbol in selected:
            day_data = price_data[symbol][date_str]
            entry_price = day_data['open']
            
            if entry_price <= 0:
                continue
            
            shares = capital_per_pos / entry_price
            cost = shares * entry_price
            
            if cost > cash:
                continue
            
            # Minuto de entrada aleatorio (0-389)
            entry_minute = random.randint(0, DAILY_MINUTES - 1)
            
            # Calcular fecha de salida
            total_minutes = entry_minute + HOLD_MINUTES
            days_later = total_minutes // DAILY_MINUTES
            exit_minute = total_minutes % DAILY_MINUTES
            
            # Encontrar fecha de salida (saltando fines de semana)
            exit_date = date
            days_counted = 0
            while days_counted < days_later:
                exit_date += timedelta(days=1)
                if exit_date.weekday() < 5:
                    days_counted += 1
            
            exit_date_str = exit_date.strftime('%Y-%m-%d')
            
            # Crear posición
            positions.append({
                'symbol': symbol,
                'entry_date': date_str,
                'exit_date': exit_date_str,
                'entry_price': entry_price,
                'shares': shares,
                'entry_minute': entry_minute,
                'exit_minute': exit_minute
            })
            
            cash -= cost
            
            trades.append({
                'date': date_str,
                'symbol': symbol,
                'action': 'BUY',
                'price': entry_price,
                'shares': shares,
                'scheduled_exit': exit_date_str,
                'exit_minute': exit_minute
            })
        
        # 3. CALCULAR VALOR DEL PORTAFOLIO
        positions_value = 0
        for pos in positions:
            symbol = pos['symbol']
            if symbol in available:
                # Usar Close como aproximación del valor actual
                positions_value += pos['shares'] * price_data[symbol][date_str]['close']
        
        total_value = cash + positions_value
        portfolio_values.append({
            'date': date_str,
            'portfolio_value': total_value,
            'cash': cash,
            'positions_value': positions_value,
            'positions_count': len(positions)
        })
        
        # Mostrar progreso cada 252 días (~1 año)
        if i % 252 == 0 or i == len(all_dates) - 1:
            print(f"[{date_str}] Valor: ${total_value:>12,.2f} | "
                  f"Pos: {len(positions):>2} | Cash: ${cash:>10,.2f}")
    
    # RESULTADOS FINALES
    print_results(portfolio_values, trades)
    save_results(portfolio_values, trades)

def print_results(portfolio_values, trades):
    """Imprime resultados"""
    if not portfolio_values:
        return
    
    df = pd.DataFrame(portfolio_values)
    df['date'] = pd.to_datetime(df['date'])
    
    initial = INITIAL_CAPITAL
    final = df['portfolio_value'].iloc[-1]
    total_return = (final - initial) / initial
    years = len(df) / 252
    
    print("\n" + "=" * 80)
    print("RESULTADOS FINALES - EXACT 666 MINUTES")
    print("=" * 80)
    
    print(f"\n>> CAPITAL")
    print(f"   Inicial:              ${initial:>15,.2f}")
    print(f"   Final:                ${final:>15,.2f}")
    print(f"   P/L Total:            ${final - initial:>+15,.2f}")
    print(f"   Retorno Total:        {total_return:>+15.2%}")
    if years > 0:
        ann_return = (1 + total_return) ** (1 / years) - 1
        print(f"   Años:                 {years:>15.1f}")
        print(f"   Retorno Anualizado:   {ann_return:>+15.2%}")
    
    # Riesgo
    df['returns'] = df['portfolio_value'].pct_change()
    volatility = df['returns'].std() * np.sqrt(252)
    rolling_max = df['portfolio_value'].expanding().max()
    drawdown = (df['portfolio_value'] - rolling_max) / rolling_max
    max_dd = drawdown.min()
    
    print(f"\n>> RIESGO")
    print(f"   Volatilidad:          {volatility:>15.2%}")
    print(f"   Máximo Drawdown:      {max_dd:>15.2%}")
    
    # Trading
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
            print(f"   Pérdida Promedio:     {losses.mean():>+15.2%}")
        if len(losses) > 0 and losses.sum() != 0:
            pf = abs(wins.sum() / losses.sum()) if len(wins) > 0 else 0
            print(f"   Profit Factor:        {pf:>15.2f}")
    
    print("=" * 80)

def save_results(portfolio_values, trades):
    """Guarda resultados"""
    os.makedirs('backtests', exist_ok=True)
    
    pd.DataFrame(portfolio_values).to_csv(
        'backtests/backtest_v6_exact_666_results.csv', index=False
    )
    pd.DataFrame(trades).to_csv(
        'backtests/trades_v6_exact_666.csv', index=False
    )
    print("\nResultados guardados en backtests/")

if __name__ == "__main__":
    run_backtest()
