"""
OmniCapital v6 - S&P 500 Top 65 Market Cap
Universo dinámico: las 65 acciones con mayor capitalización del S&P 500 en cada año.
Rebalanceo anual del universo según ranking de market cap.
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

START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

print("=" * 70)
print("OMNICAPITAL v6 - S&P 500 TOP 65 MARKET CAP")
print("=" * 70)
print(f"\nParámetros:")
print(f"  - Hold time: {HOLD_MINUTES} minutos (~{HOLD_MINUTES/60:.1f} horas)")
print(f"  - Posiciones: {NUM_POSITIONS}")
print(f"  - Capital inicial: ${INITIAL_CAPITAL:,.0f}")
print(f"  - Universo: Top 65 S&P 500 por market cap (rebalanceo anual)")
print()


def download_sp500_data():
    """Descarga datos del universo S&P 500 extendido"""
    cache_file = 'data_cache/dynamic_universe_2000-01-01_2026-02-09.pkl'
    
    if os.path.exists(cache_file):
        print(f"[Cache] Cargando datos...")
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    else:
        raise FileNotFoundError(f"No se encontró: {cache_file}")


def get_sp500_historical_components():
    """
    Retorna los componentes históricos del S&P 500 por año.
    Como no tenemos datos históricos exactos de composición,
    usamos una aproximación basada en:
    1. Símbolos que existían en cada año
    2. Market cap estimado por precio * volumen
    """
    # Aproximación: usar los 65 símbolos con mayor precio * volumen promedio del año
    # En una implementación real, se usaría data de S&P Dow Jones Indices
    
    # Lista aproximada de grandes empresas por época (basado en supervivencia y tamaño)
    historical_large_caps = {
        # Pre-2000 (dot-com era)
        2000: ['GE', 'MSFT', 'XOM', 'WMT', 'CSCO', 'INTC', 'AAPL', 'IBM', 'PFE', 'JNJ',
               'KO', 'MRK', 'PG', 'BAC', 'AXP', 'CVX', 'DIS', 'HD', 'JPM', 'VZ',
               'WFC', 'CAT', 'BA', 'MMM', 'DD', 'AA', 'IP', 'AA', 'HON', 'UTX',
               'MO', 'CL', 'KMB', 'PEP', 'WBA', 'SLB', 'OXY', 'COP', 'HAL', 'BHI',
               'UNP', 'NSC', 'FDX', 'UPS', 'LMT', 'RTN', 'NOC', 'GD', 'LUV', 'DAL',
               'T', 'VZ', 'SBC', 'QCOM', 'ORCL', 'SUNW', 'DELL', 'HPQ', 'IBM', 'INTC'],
        # 2000s (post dot-com, pre-crisis)
        2004: ['XOM', 'GE', 'MSFT', 'C', 'WMT', 'PFE', 'JNJ', 'BAC', 'AAPL', 'IBM',
               'CVX', 'JPM', 'PG', 'GOOGL', 'CSCO', 'INTC', 'VZ', 'KO', 'PEP', 'MRK',
               'WFC', 'DIS', 'HD', 'AXP', 'BA', 'CAT', 'MMM', 'MO', 'CL', 'KMB',
               'SLB', 'OXY', 'COP', 'UNP', 'FDX', 'UPS', 'LMT', 'T', 'VZ', 'QCOM'],
        # Post-crisis 2008
        2008: ['XOM', 'WMT', 'MSFT', 'JNJ', 'PG', 'IBM', 'JPM', 'KO', 'CVX', 'PFE',
               'BAC', 'AAPL', 'GOOGL', 'VZ', 'WFC', 'CSCO', 'PEP', 'MRK', 'INTC', 'DIS',
               'HD', 'V', 'MA', 'PM', 'AXP', 'BA', 'CAT', 'MMM', 'UNH', 'MDT',
               'SLB', 'OXY', 'COP', 'UNP', 'FDX', 'UPS', 'LMT', 'T', 'QCOM', 'ORCL'],
        # 2010s (recovery)
        2012: ['AAPL', 'XOM', 'MSFT', 'IBM', 'GOOGL', 'JNJ', 'GE', 'WMT', 'CVX', 'PG',
               'KO', 'PFE', 'VZ', 'T', 'JPM', 'WFC', 'BAC', 'MRK', 'INTC', 'CSCO',
               'PEP', 'DIS', 'HD', 'V', 'MA', 'PM', 'UNH', 'MDT', 'ABT', 'BMY',
               'SLB', 'OXY', 'COP', 'UNP', 'FDX', 'UPS', 'LMT', 'QCOM', 'ORCL', 'AMZN'],
        # 2020s (tech dominance)
        2020: ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'FB', 'BRK-B', 'TSLA', 'JNJ', 'JPM', 'V',
               'PG', 'UNH', 'HD', 'MA', 'NVDA', 'DIS', 'BAC', 'ADBE', 'PYPL', 'CMCSA',
               'XOM', 'VZ', 'NFLX', 'INTC', 'PFE', 'T', 'MRK', 'PEP', 'KO', 'ABT',
               'CVX', 'WMT', 'CSCO', 'CRM', 'ACN', 'ABBV', 'AVGO', 'TMO', 'COST', 'DHR'],
    }
    
    return historical_large_caps


def estimate_market_cap_ranking(price_data, year, top_n=65):
    """
    Estima el ranking de market cap para un año específico.
    Usa precio * volumen como proxy de market cap relativo.
    """
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"
    
    scores = {}
    
    for symbol, df in price_data.items():
        # Filtrar datos del año
        year_data = df[(df.index >= start_date) & (df.index <= end_date)]
        
        if len(year_data) < 50:  # Necesitamos suficientes datos
            continue
        
        # Calcular score: precio promedio * volumen promedio
        avg_price = year_data['Close'].mean()
        avg_volume = year_data['Volume'].mean() if 'Volume' in year_data.columns else 1000000
        
        # Si no hay volumen, usar solo precio como proxy
        score = avg_price * (avg_volume ** 0.5)  # Raíz cuadrada para suavizar
        scores[symbol] = score
    
    # Ordenar por score y tomar top N
    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_symbols = [s[0] for s in ranked[:top_n]]
    
    return top_symbols


def build_annual_universe(price_data, rebalance_month=1, rebalance_day=2):
    """
    Construye el universo anual basado en top 65 market cap estimado.
    Rebalanceo el día especificado de cada año.
    """
    print("Construyendo universo anual (Top 65 S&P 500)...")
    
    annual_universe = {}
    years = range(2000, 2027)
    
    for year in years:
        rebalance_date = f"{year}-{rebalance_month:02d}-{rebalance_day:02d}"
        
        # Usar datos del año anterior para estimar market cap
        analysis_year = year - 1 if year > 2000 else year
        
        top_symbols = estimate_market_cap_ranking(price_data, analysis_year, 65)
        
        annual_universe[year] = {
            'rebalance_date': pd.Timestamp(rebalance_date),
            'symbols': top_symbols
        }
        
        print(f"  {year}: {len(top_symbols)} símbolos (ej: {', '.join(top_symbols[:5])})")
    
    return annual_universe


def get_tradeable_symbols(price_data, date, annual_universe):
    """
    Retorna símbolos tradeables en una fecha específica.
    Usa el universo del año correspondiente.
    """
    year = date.year
    
    # Obtener universo del año
    if year not in annual_universe:
        return []
    
    year_universe = annual_universe[year]['symbols']
    
    # Filtrar por disponibilidad de datos en esta fecha
    tradeable = []
    for symbol in year_universe:
        if symbol in price_data and date in price_data[symbol].index:
            tradeable.append(symbol)
    
    return tradeable


def run_backtest(price_data, annual_universe):
    """Ejecuta backtest con universo S&P 500 Top 65"""
    
    print("\n" + "=" * 70)
    print("INICIANDO BACKTEST (S&P 500 Top 65)")
    print("=" * 70)
    
    # Fechas
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    
    print(f"Total fechas: {len(all_dates)}")
    print(f"Rango: {all_dates[0].strftime('%Y-%m-%d')} a {all_dates[-1].strftime('%Y-%m-%d')}")
    
    hold_days = max(1, HOLD_MINUTES // (6.5 * 60))
    cash = INITIAL_CAPITAL
    positions = {}
    portfolio_values = []
    trades = []
    current_universe = []
    
    for i, date in enumerate(all_dates):
        # Verificar si es fecha de rebalanceo anual
        year = date.year
        if year in annual_universe:
            rebalance_date = annual_universe[year]['rebalance_date']
            if date == rebalance_date or (i > 0 and date > rebalance_date and all_dates[i-1] < rebalance_date):
                old_universe = set(current_universe)
                current_universe = annual_universe[year]['symbols']
                print(f"\n  [Rebalanceo {year}] Universo: {len(current_universe)} símbolos")
                print(f"    Salen: {old_universe - set(current_universe)}")
                print(f"    Entran: {set(current_universe) - old_universe}")
        
        # Obtener símbolos tradeables
        tradeable = get_tradeable_symbols(price_data, date, annual_universe)
        
        # Calcular valor del portfolio
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price
        
        # Cerrar posiciones que ya no están en el universo
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
                                'exit_date': date + timedelta(days=hold_days)
                            }
                            cash -= cost + commission
        
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'tradeable': len(tradeable)
        })
        
        if i % 252 == 0 and i > 0:
            year = i // 252
            print(f"  Año {year}: ${portfolio_value:,.0f} | Pos: {len(positions)}/5 | Tradeable: {len(tradeable)}")
    
    return portfolio_values, trades


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
    price_data = download_sp500_data()
    
    # Construir universo anual
    annual_universe = build_annual_universe(price_data)
    
    # Ejecutar backtest
    portfolio_values, trades = run_backtest(price_data, annual_universe)
    metrics = calculate_metrics(portfolio_values, trades)
    
    print("\n" + "=" * 70)
    print("RESULTADOS - S&P 500 TOP 65 MARKET CAP")
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
    
    # Guardar
    with open('results_v6_sp500_top65.pkl', 'wb') as f:
        pickle.dump({
            'metrics': metrics,
            'portfolio_values': portfolio_values,
            'annual_universe': annual_universe
        }, f)
    
    print(f"\nGuardado en: results_v6_sp500_top65.pkl")
