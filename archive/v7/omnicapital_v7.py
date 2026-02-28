"""
╔══════════════════════════════════════════════════════════════════════════════╗
║           OMNICAPITAL v7.0 - HYBRID VALUE+666                                ║
║                                                                              ║
║  Híbrido: Selección Value+Quality+Momentum + Hold EXACTO 666 minutos          ║
║  - Selección basada en fundamentales (50% Value, 25% Quality, 25% Momentum)   ║
║  - Hold exacto: 666 minutos (11.1 horas)                                      ║
║  - Position sizing: Risk Parity basado en volatilidad                        ║
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
POSITIONS_COUNT = 10  # Más posiciones que v6.0 por la mejor selección
HOLD_MINUTES = 666
DAILY_MINUTES = 390

# Pesos para scoring (igual que v3.0)
VALUE_WEIGHT = 0.50
QUALITY_WEIGHT = 0.25
MOMENTUM_WEIGHT = 0.25

# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES AUXILIARES
# ═══════════════════════════════════════════════════════════════════════════════

def get_scalar(value):
    """Extrae valor escalar de Series o scalar"""
    if hasattr(value, 'iloc'):
        return float(value.iloc[0])
    return float(value)

def simulate_intraday_price(open_p, high, low, close, minute_of_day):
    """Simula precio intradía"""
    progress = minute_of_day / DAILY_MINUTES
    base = open_p + (close - open_p) * progress
    if high > low:
        np.random.seed(int(base * 10000) % 2**32)
        noise = np.random.uniform(-0.3, 0.3)
        variation = (high - low) * noise
        price = base + variation
        return max(low, min(high, price))
    return base

# ═══════════════════════════════════════════════════════════════════════════════
# CÁLCULO DE SCORES (de v3.0)
# ═══════════════════════════════════════════════════════════════════════════════

def calculate_value_score(data, financials):
    """Score de valor basado en múltiplos"""
    scores = {}
    for symbol in data.keys():
        try:
            info = financials.get(symbol, {})
            
            # Obtener múltiplos
            pe = info.get('trailingPE', info.get('forwardPE', 20))
            pb = info.get('priceToBook', 2)
            ps = info.get('priceToSalesTrailing12Months', 2)
            
            # Evitar valores negativos o extremos
            pe = max(0.1, min(pe, 100))
            pb = max(0.1, min(pb, 20))
            ps = max(0.1, min(ps, 20))
            
            # Score: menor múltiplo = mejor (invertido)
            pe_score = max(0, (30 - pe) / 30)
            pb_score = max(0, (5 - pb) / 5)
            ps_score = max(0, (5 - ps) / 5)
            
            scores[symbol] = (pe_score * 0.5 + pb_score * 0.3 + ps_score * 0.2)
        except:
            scores[symbol] = 0.5
    return scores

def calculate_quality_score(data, financials):
    """Score de calidad basado en ROE y estabilidad"""
    scores = {}
    for symbol in data.keys():
        try:
            info = financials.get(symbol, {})
            
            # ROE
            roe = info.get('returnOnEquity', 0.1)
            if isinstance(roe, str):
                roe = 0.1
            roe = max(-0.5, min(roe, 1.0))
            
            # Margen de beneficio
            margin = info.get('profitMargins', 0.1)
            if isinstance(margin, str):
                margin = 0.1
            margin = max(-0.5, min(margin, 1.0))
            
            # Score
            roe_score = max(0, roe)
            margin_score = max(0, margin)
            
            scores[symbol] = (roe_score * 0.6 + margin_score * 0.4)
        except:
            scores[symbol] = 0.5
    return scores

def calculate_momentum_score(data):
    """Score de momentum basado en retornos recientes"""
    scores = {}
    for symbol, df in data.items():
        try:
            if len(df) < 60:
                scores[symbol] = 0.5
                continue
            
            # Calcular retornos
            closes = df['Close'].values.flatten()
            
            # 1 mes
            ret_1m = (closes[-1] - closes[-20]) / closes[-20] if len(closes) >= 20 else 0
            # 3 meses
            ret_3m = (closes[-1] - closes[-60]) / closes[-60] if len(closes) >= 60 else 0
            
            # Score: momentum moderado es mejor que extremo
            momentum_raw = (ret_1m * 0.4 + ret_3m * 0.6)
            
            # Normalizar a 0-1 (momentum de -20% a +40% mapeado a 0-1)
            scores[symbol] = max(0, min(1, (momentum_raw + 0.2) / 0.6))
        except:
            scores[symbol] = 0.5
    return scores

def calculate_volatility(data, symbol, lookback=20):
    """Calcula volatilidad anualizada"""
    try:
        df = data[symbol]
        if len(df) < lookback:
            return 0.20
        
        closes = df['Close'].values.flatten()
        returns = np.diff(closes[-lookback:]) / closes[-lookback:-1]
        vol = np.std(returns) * np.sqrt(252)
        return max(0.05, min(vol, 1.0))
    except:
        return 0.20

def calculate_composite_score(value_scores, quality_scores, momentum_scores):
    """Calcula score compuesto ponderado"""
    composite = {}
    all_symbols = set(value_scores.keys()) | set(quality_scores.keys()) | set(momentum_scores.keys())
    
    for symbol in all_symbols:
        v = value_scores.get(symbol, 0.5)
        q = quality_scores.get(symbol, 0.5)
        m = momentum_scores.get(symbol, 0.5)
        
        composite[symbol] = (
            v * VALUE_WEIGHT +
            q * QUALITY_WEIGHT +
            m * MOMENTUM_WEIGHT
        )
    
    return composite

def risk_parity_sizing(symbols, data, target_vol=0.10):
    """Calcula tamaños basados inversamente en volatilidad"""
    vols = {}
    for symbol in symbols:
        vols[symbol] = calculate_volatility(data, symbol)
    
    # Inverso de volatilidad
    inv_vols = {s: 1/v for s, v in vols.items()}
    total_inv = sum(inv_vols.values())
    
    if total_inv == 0:
        return {s: 1/len(symbols) for s in symbols}
    
    # Normalizar a porcentajes que sumen 1
    weights = {s: inv_vols[s]/total_inv for s in symbols}
    return weights

# ═══════════════════════════════════════════════════════════════════════════════
# BACKTEST PRINCIPAL
# ═══════════════════════════════════════════════════════════════════════════════

def download_data(symbols, start, end):
    """Descarga datos"""
    print("Descargando datos de precios...")
    data = {}
    for symbol in symbols:
        try:
            df = yf.download(symbol, start=start, end=end, progress=False)
            if len(df) > 100:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                data[symbol] = df
        except:
            pass
    print(f"  Precios: {len(data)} símbolos")
    return data

def download_financials(symbols):
    """Descarga datos fundamentales"""
    print("Descargando datos fundamentales...")
    financials = {}
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            financials[symbol] = info
        except:
            financials[symbol] = {}
    return financials

def run_backtest(start_date='2000-01-01', end_date='2026-02-09'):
    """Ejecuta backtest híbrido"""
    
    print("=" * 80)
    print("OMNICAPITAL v7.0 - HYBRID VALUE+666")
    print("=" * 80)
    print(f"Selección: Value({VALUE_WEIGHT*100:.0f}%) + Quality({QUALITY_WEIGHT*100:.0f}%) + Momentum({MOMENTUM_WEIGHT*100:.0f}%)")
    print(f"Hold: {HOLD_MINUTES} minutos exactos")
    print(f"Position Sizing: Risk Parity (inverse volatility)")
    print("=" * 80)
    
    # Descargar datos
    data = download_data(UNIVERSE, start_date, end_date)
    financials = download_financials(UNIVERSE)
    
    if len(data) < 10:
        print("Error: Datos insuficientes")
        return
    
    # Crear matriz de precios
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
    
    # Fechas de trading
    all_dates = sorted(set().union(*[set(d.keys()) for d in price_data.values()]))
    all_dates = [d for d in all_dates if d >= start_date and d <= end_date]
    
    print(f"Días de trading: {len(all_dates)}")
    print("=" * 80)
    
    # Estado
    cash = INITIAL_CAPITAL
    positions = []
    trades = []
    portfolio_values = []
    
    # Rebalanceo mensual (cada ~21 días)
    REBALANCE_DAYS = 21
    last_rebalance = -REBALANCE_DAYS
    current_selection = []
    current_weights = {}
    
    # Scores cache (recalcular cada mes)
    value_scores = {}
    quality_scores = {}
    momentum_scores = {}
    composite_scores = {}
    
    for i, date_str in enumerate(all_dates):
        date = datetime.strptime(date_str, '%Y-%m-%d')
        
        # Símbolos disponibles
        available = [s for s in price_data.keys() if date_str in price_data[s]]
        
        # ═══════════════════════════════════════════════════════════════════
        # REBALANCEO MENSUAL: Recalcular selección
        # ═══════════════════════════════════════════════════════════════════
        if i - last_rebalance >= REBALANCE_DAYS and len(available) >= POSITIONS_COUNT:
            last_rebalance = i
            
            # Calcular scores con datos hasta la fecha
            current_data = {s: data[s][:date_str] for s in available if s in data}
            current_financials = {s: financials.get(s, {}) for s in available}
            
            value_scores = calculate_value_score(current_data, current_financials)
            quality_scores = calculate_quality_score(current_data, current_financials)
            momentum_scores = calculate_momentum_score(current_data)
            composite_scores = calculate_composite_score(value_scores, quality_scores, momentum_scores)
            
            # Seleccionar top N por score compuesto
            sorted_symbols = sorted(composite_scores.items(), key=lambda x: x[1], reverse=True)
            current_selection = [s for s, _ in sorted_symbols[:POSITIONS_COUNT]]
            
            # Calcular weights por Risk Parity
            current_weights = risk_parity_sizing(current_selection, data)
            
            if i % 252 == 0:
                print(f"\n[{date_str}] REBALANCEO - Top seleccionados:")
                for j, sym in enumerate(current_selection[:5]):
                    score = composite_scores.get(sym, 0)
                    print(f"  {j+1}. {sym}: Score={score:.3f}, Weight={current_weights.get(sym, 0):.2%}")
        
        if len(available) < POSITIONS_COUNT:
            continue
        
        # ═══════════════════════════════════════════════════════════════════
        # CERRAR POSICIONES QUE EXPIRAN
        # ═══════════════════════════════════════════════════════════════════
        positions_to_close = [p for p in positions if p['exit_date'] == date_str]
        
        for pos in positions_to_close:
            symbol = pos['symbol']
            if symbol in available:
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
                    'hold_minutes': HOLD_MINUTES,
                    'strategy': 'hybrid_666'
                })
        
        positions = [p for p in positions if p['exit_date'] != date_str]
        
        # ═══════════════════════════════════════════════════════════════════
        # ABRIR NUEVAS POSICIONES (solo símbolos seleccionados)
        # ═══════════════════════════════════════════════════════════════════
        # Capital disponible para nuevas posiciones
        capital_for_new = cash * 0.95
        
        # Solo abrir posiciones en símbolos seleccionados que no tengamos ya
        held_symbols = {p['symbol'] for p in positions}
        symbols_to_open = [s for s in current_selection if s in available and s not in held_symbols]
        
        for symbol in symbols_to_open:
            if symbol not in current_weights:
                continue
                
            day_data = price_data[symbol][date_str]
            entry_price = day_data['open']
            
            if entry_price <= 0:
                continue
            
            # Tamaño basado en weight de Risk Parity
            weight = current_weights[symbol]
            position_value = capital_for_new * weight
            shares = position_value / entry_price
            cost = shares * entry_price
            
            if cost > cash or cost < 100:  # Mínimo $100 por posición
                continue
            
            # Minuto de entrada aleatorio
            entry_minute = random.randint(0, DAILY_MINUTES - 1)
            
            # Calcular fecha de salida
            total_minutes = entry_minute + HOLD_MINUTES
            days_later = total_minutes // DAILY_MINUTES
            exit_minute = total_minutes % DAILY_MINUTES
            
            exit_date = date
            days_counted = 0
            while days_counted < days_later:
                exit_date += timedelta(days=1)
                if exit_date.weekday() < 5:
                    days_counted += 1
            
            exit_date_str = exit_date.strftime('%Y-%m-%d')
            
            positions.append({
                'symbol': symbol,
                'entry_date': date_str,
                'exit_date': exit_date_str,
                'entry_price': entry_price,
                'shares': shares,
                'entry_minute': entry_minute,
                'exit_minute': exit_minute,
                'weight': weight
            })
            
            cash -= cost
            
            trades.append({
                'date': date_str,
                'symbol': symbol,
                'action': 'BUY',
                'price': entry_price,
                'shares': shares,
                'weight': weight,
                'scheduled_exit': exit_date_str
            })
        
        # ═══════════════════════════════════════════════════════════════════
        # REGISTRAR VALOR DEL PORTAFOLIO
        # ═══════════════════════════════════════════════════════════════════
        positions_value = 0
        for pos in positions:
            symbol = pos['symbol']
            if symbol in available:
                positions_value += pos['shares'] * price_data[symbol][date_str]['close']
        
        total_value = cash + positions_value
        portfolio_values.append({
            'date': date_str,
            'portfolio_value': total_value,
            'cash': cash,
            'positions_value': positions_value,
            'positions_count': len(positions)
        })
        
        # Progreso
        if i % 252 == 0 or i == len(all_dates) - 1:
            print(f"[{date_str}] Valor: ${total_value:>12,.2f} | "
                  f"Pos: {len(positions):>2} | Cash: ${cash:>10,.2f}")
    
    # RESULTADOS
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
    print("RESULTADOS FINALES - HYBRID VALUE+666")
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
    
    # Sharpe (asumiendo rf=2%)
    sharpe = ((df['returns'].mean() * 252) - 0.02) / (df['returns'].std() * np.sqrt(252)) if df['returns'].std() > 0 else 0
    
    print(f"\n>> RIESGO")
    print(f"   Volatilidad:          {volatility:>15.2%}")
    print(f"   Máximo Drawdown:      {max_dd:>15.2%}")
    print(f"   Sharpe Ratio:         {sharpe:>15.2f}")
    
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
        'backtests/backtest_v7_hybrid_666_results.csv', index=False
    )
    pd.DataFrame(trades).to_csv(
        'backtests/trades_v7_hybrid_666.csv', index=False
    )
    print("\nResultados guardados en backtests/")

if __name__ == "__main__":
    run_backtest()
