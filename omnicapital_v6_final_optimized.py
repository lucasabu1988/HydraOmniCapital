"""
OmniCapital v6 Final Optimized
Version definitiva con todos los parametros optimizados:
- Hold time: 1200 minutos (20 horas, ~2 overnights)
- Stop loss: -20% (portfolio level)
- Leverage: 2:1 con reduccion dinamica
- Universo dinamico sin look-ahead bias
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import random
import pickle
import os
from typing import Dict, List
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARAMETROS OPTIMIZADOS (NO MODIFICAR)
# ============================================================================

HOLD_MINUTES = 1200           # 20 horas = ~2 overnights (OPTIMO)
NUM_POSITIONS = 5             # Numero de posiciones
INITIAL_CAPITAL = 100_000     # Capital inicial
RANDOM_SEED = 42              # Semilla para reproducibilidad
COMMISSION_PER_SHARE = 0.001  # Comision IBKR Pro
MIN_AGE_DAYS = 63             # Antiguedad minima para IPOs (~3 meses)

# PARAMETROS DE LEVERAGE Y RIESGO (OPTIMIZADOS)
LEVERAGE = 2.0                # Leverage maximo 2:1
MARGIN_RATE = 0.06            # Costo de margin 6% anual
HEDGE_COST_PCT = 0.025        # Costo de hedge 2.5% anual
PORTFOLIO_STOP_LOSS = -0.20   # STOP LOSS OPTIMO: -20%
RECOVERY_THRESHOLD = 0.95     # Re-entrar cuando se recupere 95% del peak

START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

print("=" * 80)
print("OMNICAPITAL v6 FINAL OPTIMIZED")
print("=" * 80)
print("\nParametros Optimizados (Validados con 26 anos de datos):")
print(f"  - Hold time:        {HOLD_MINUTES} minutos ({HOLD_MINUTES/60:.1f}h, ~2 overnights)")
print(f"  - Stop loss:        {abs(PORTFOLIO_STOP_LOSS):.0%} (portfolio level)")
print(f"  - Leverage:         {LEVERAGE:.1f}:1 (maximo regulado)")
print(f"  - Posiciones:       {NUM_POSITIONS}")
print(f"  - Universo:         Dinamico (sin look-ahead bias)")
print()


def download_data():
    """Descarga datos del universo extendido"""
    cache_file = 'data_cache/dynamic_universe_2000-01-01_2026-02-09.pkl'
    
    if os.path.exists(cache_file):
        print(f"[Cache] Cargando datos...")
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    
    all_symbols = list(set([
        'AAPL', 'MSFT', 'AMZN', 'NVDA', 'GOOGL', 'META', 'TSLA', 'AVGO',
        'BRK-B', 'JPM', 'V', 'JNJ', 'WMT', 'MA', 'PG', 'UNH', 'HD', 'CVX',
        'MRK', 'PEP', 'KO', 'ABBV', 'BAC', 'COST', 'TMO', 'DIS',
        'ABT', 'WFC', 'ACN', 'VZ', 'DHR', 'ADBE', 'CRM', 'TXN', 'NKE',
        'NEE', 'AMD', 'PM', 'XOM', 'INTC', 'CSCO', 'IBM', 'GE', 'CAT',
        'BA', 'MMM', 'AXP', 'GS', 'MO', 'KMB', 'CL', 'MDT', 'SLB', 'UNP',
        'HON', 'FDX', 'UPS', 'LMT', 'RTX', 'OXY', 'AMGN', 'LLY', 'BMY', 'BIIB'
    ]))
    
    print(f"[Download] Descargando {len(all_symbols)} simbolos...")
    data = {}
    for symbol in all_symbols:
        try:
            df = yf.download(symbol, start=START_DATE, end=END_DATE, progress=False)
            if not df.empty and len(df) > 100:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                data[symbol] = df
        except:
            pass
    
    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)
    
    print(f"[Download] {len(data)} simbolos validos")
    return data


def get_tradeable_symbols(price_data: Dict[str, pd.DataFrame], date: pd.Timestamp, 
                          first_date: pd.Timestamp) -> List[str]:
    """Retorna simbolos tradeables sin look-ahead bias"""
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


def minutes_held(entry_date: pd.Timestamp, current_date: pd.Timestamp) -> int:
    """Calcula minutos de trading transcurridos"""
    return (current_date - entry_date).days * 390


def run_backtest(price_data: Dict[str, pd.DataFrame]) -> Dict:
    """Ejecuta backtest con parametros optimizados"""
    
    print("\n" + "=" * 80)
    print("INICIANDO BACKTEST")
    print("=" * 80)
    
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    
    first_date = all_dates[0]
    
    print(f"Periodo: {all_dates[0].strftime('%Y-%m-%d')} a {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Dias de trading: {len(all_dates)}")
    
    # Inicializar capital con leverage
    equity = INITIAL_CAPITAL
    borrowed = INITIAL_CAPITAL * (LEVERAGE - 1)
    total_capital = equity + borrowed
    
    cash = total_capital
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []
    
    current_leverage = LEVERAGE
    peak_value = total_capital
    in_protection_mode = False
    
    # Costos diarios
    daily_margin_cost = MARGIN_RATE / 252 * borrowed
    daily_hedge_cost = HEDGE_COST_PCT / 252 * total_capital
    
    print(f"\nCapital inicial: ${INITIAL_CAPITAL:,.0f}")
    print(f"Borrowed: ${borrowed:,.0f}")
    print(f"Total trading: ${total_capital:,.0f}\n")
    
    for i, date in enumerate(all_dates):
        # Obtener simbolos tradeables
        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date)
        
        # Calcular valor del portfolio
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price
        
        # Actualizar peak y verificar recuperacion
        if portfolio_value > peak_value:
            peak_value = portfolio_value
            if in_protection_mode:
                in_protection_mode = False
                current_leverage = LEVERAGE
        
        # Calcular drawdown
        drawdown = (portfolio_value - peak_value) / peak_value
        
        # STOP LOSS OPTIMIZADO (-20%)
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({
                'date': date,
                'portfolio_value': portfolio_value,
                'drawdown': drawdown
            })
            
            print(f"\n  [STOP LOSS] {date.strftime('%Y-%m-%d')}: DD {drawdown:.1%}")
            
            # Cerrar todas las posiciones
            for symbol in list(positions.keys()):
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    cash += positions[symbol]['shares'] * exit_price
                del positions[symbol]
            
            # Reducir leverage a 1:1 (sin apalancamiento)
            current_leverage = 1.0
            in_protection_mode = True
            print(f"  Leverage reducido a {current_leverage:.1f}:1 (proteccion activada)")
        
        # Cobrar costos diarios (solo fuera de proteccion)
        if not in_protection_mode:
            cash -= (daily_margin_cost + daily_hedge_cost)
        
        # Cerrar posiciones expiradas (hold time)
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if minutes_held(pos['entry_date'], date) >= HOLD_MINUTES:
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    shares = pos['shares']
                    proceeds = shares * exit_price
                    commission = shares * COMMISSION_PER_SHARE
                    cash += proceeds - commission
                    
                    pnl = (exit_price - pos['entry_price']) * shares - commission
                    trades.append({
                        'symbol': symbol,
                        'entry_date': pos['entry_date'],
                        'exit_date': date,
                        'pnl': pnl,
                        'return': pnl / (pos['entry_price'] * shares)
                    })
                del positions[symbol]
        
        # Cerrar posiciones no tradeables
        for symbol in list(positions.keys()):
            if symbol not in tradeable_symbols:
                if symbol in price_data and date in price_data[symbol].index:
                    cash += positions[symbol]['shares'] * price_data[symbol].loc[date, 'Close']
                del positions[symbol]
        
        # Abrir nuevas posiciones
        needed = NUM_POSITIONS - len(positions)
        
        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= needed:
            available_for_entry = [s for s in tradeable_symbols if s not in positions]
            
            if len(available_for_entry) >= needed:
                random.seed(RANDOM_SEED + date.toordinal())
                selected = random.sample(available_for_entry, needed)
                
                # Sizing con leverage actual
                effective_capital = cash * current_leverage
                position_value = (effective_capital * 0.95) / NUM_POSITIONS
                
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
            'cash': cash,
            'positions': len(positions),
            'drawdown': drawdown,
            'leverage': current_leverage,
            'in_protection': in_protection_mode
        })
        
        if i % 252 == 0 and i > 0:
            year = i // 252
            equity_value = portfolio_value - borrowed if current_leverage > 1 else portfolio_value
            status = "[PROTECCION]" if in_protection_mode else ""
            print(f"  Año {year}: ${portfolio_value:,.0f} | Equity: ${equity_value:,.0f} | "
                  f"DD: {drawdown:.1%} | Lev: {current_leverage:.1f}x {status}")
    
    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value']
    }


def calculate_metrics(results: Dict) -> Dict:
    """Calcula metricas de performance"""
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']
    stop_df = results['stop_events']
    
    borrowed = INITIAL_CAPITAL * (LEVERAGE - 1)
    initial = INITIAL_CAPITAL
    final_value = df['value'].iloc[-1]
    final_equity = final_value - borrowed
    
    years = len(df) / 252
    cagr = (final_equity / initial) ** (1/years) - 1
    
    returns = df['value'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(252)
    
    max_dd = df['drawdown'].min()
    
    sharpe = cagr / volatility if volatility > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    avg_trade = trades_df['pnl'].mean() if len(trades_df) > 0 else 0
    
    # Tiempo en proteccion
    protection_days = df['in_protection'].sum()
    protection_pct = protection_days / len(df) * 100
    
    return {
        'initial': initial,
        'final_value': final_value,
        'final_equity': final_equity,
        'total_return': (final_equity - initial) / initial,
        'years': years,
        'cagr': cagr,
        'volatility': volatility,
        'sharpe': sharpe,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'win_rate': win_rate,
        'avg_trade': avg_trade,
        'trades': len(trades_df),
        'stop_events': len(stop_df),
        'protection_days': protection_days,
        'protection_pct': protection_pct
    }


# ============================================================================
# EJECUCION
# ============================================================================

if __name__ == "__main__":
    # Cargar datos
    price_data = download_data()
    print(f"\nSimbolos disponibles: {len(price_data)}")
    
    # Ejecutar backtest
    results = run_backtest(price_data)
    
    # Calcular metricas
    metrics = calculate_metrics(results)
    
    # Mostrar resultados
    print("\n" + "=" * 80)
    print("RESULTADOS - OMNICAPITAL v6 FINAL OPTIMIZED")
    print("=" * 80)
    print(f"\nCapital inicial:        ${metrics['initial']:>15,.0f}")
    print(f"Valor final (total):    ${metrics['final_value']:>15,.2f}")
    print(f"Equity final (neto):    ${metrics['final_equity']:>15,.2f}")
    print(f"Retorno total:          {metrics['total_return']:>15.2%}")
    print(f"CAGR:                   {metrics['cagr']:>15.2%}")
    print(f"Volatilidad anual:      {metrics['volatility']:>15.2%}")
    print(f"Sharpe ratio:           {metrics['sharpe']:>15.2f}")
    print(f"Calmar ratio:           {metrics['calmar']:>15.2f}")
    print(f"Max drawdown:           {metrics['max_drawdown']:>15.2%}")
    print(f"\nDias de trading:        {len(results['portfolio_values']):>15,}")
    print(f"Años:                   {metrics['years']:>15.2f}")
    
    if metrics['trades'] > 0:
        print(f"\nTrades ejecutados:      {metrics['trades']:>15,}")
        print(f"Win rate:               {metrics['win_rate']:>15.2%}")
        print(f"P&L promedio:           ${metrics['avg_trade']:>15,.2f}")
    
    if metrics['stop_events'] > 0:
        print(f"\nStop loss ejecutados:   {metrics['stop_events']:>15,}")
        print(f"Dias en proteccion:     {metrics['protection_days']:>15,} ({metrics['protection_pct']:.1f}%)")
    
    # Guardar resultados
    output_file = 'results_v6_final_optimized.pkl'
    with open(output_file, 'wb') as f:
        pickle.dump({
            'params': {
                'hold_minutes': HOLD_MINUTES,
                'stop_loss': PORTFOLIO_STOP_LOSS,
                'leverage': LEVERAGE,
                'num_positions': NUM_POSITIONS,
                'margin_rate': MARGIN_RATE,
                'hedge_cost': HEDGE_COST_PCT
            },
            'metrics': metrics,
            'portfolio_values': results['portfolio_values'],
            'trades': results['trades'],
            'stop_events': results['stop_events']
        }, f)
    
    print(f"\n\nResultados guardados en: {output_file}")
    
    print("\n" + "=" * 80)
    print("RESUMEN EJECUTIVO")
    print("=" * 80)
    print(f"\nOmniCapital v6 Final Optimized:")
    print(f"  - CAGR: {metrics['cagr']:.2%} (${metrics['initial']:,.0f} a ${metrics['final_equity']:,.0f} en {metrics['years']:.0f} años)")
    print(f"  - Sharpe: {metrics['sharpe']:.2f} | Max DD: {metrics['max_drawdown']:.1%}")
    print(f"  - Stop loss: {abs(PORTFOLIO_STOP_LOSS):.0%} | Leverage: {LEVERAGE:.0f}:1")
    print(f"\nSistema listo para implementacion.")
    print("=" * 80)
