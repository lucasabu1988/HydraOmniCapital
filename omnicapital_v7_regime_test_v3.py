"""
OmniCapital v7 - Regime-Based Leverage Test v3
Test de leverage adaptativo basado en VIX
"""

import pandas as pd
import numpy as np
from datetime import datetime
import random
import yfinance as yf
import warnings
import os
import json
warnings.filterwarnings('ignore')

# =============================================================================
# CONFIGURACION
# =============================================================================

CONFIG = {
    'START_DATE': '2000-01-03',
    'END_DATE': '2026-02-06',
    'INITIAL_CAPITAL': 100000,
    'HOLD_MINUTES': 1200,
    'NUM_POSITIONS': 5,
    'STOP_LOSS_PCT': -0.20,
    'BASE_LEVERAGE': 2.0,
    'RANDOM_SEED': 42,
    'COMMISSION_PER_SHARE': 0.001,
    'SLIPPAGE_PCT': 0.001,
    'BORROW_RATE_ANNUAL': 0.06,
    'VIX_THRESHOLDS': {'low': 15, 'medium': 25, 'high': 35},
    'LEVERAGE_BY_REGIME': {'low': 2.5, 'normal': 2.0, 'high': 1.5, 'crisis': 1.0},
}

UNIVERSE = ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'TSLA', 'NVDA', 'JPM', 'V', 'JNJ']


def load_data():
    """Carga datos de stocks y VIX"""
    print("Cargando datos...")
    
    # Cargar stocks desde CSV
    data_dir = 'data_cache'
    all_prices = {}
    
    for symbol in UNIVERSE:
        file_path = f'{data_dir}/{symbol}_2000-01-01_2026-02-09.csv'
        if os.path.exists(file_path):
            df = pd.read_csv(file_path, index_col=0)
            # Convertir indice a datetime y hacer tz-naive
            df.index = pd.to_datetime(df.index, utc=True).tz_convert(None)
            all_prices[symbol] = df['Close']
    
    prices_df = pd.DataFrame(all_prices)
    
    # Descargar VIX y SPY
    print("Descargando VIX y SPY...")
    vix_data = yf.download('^VIX', start='2000-01-01', end='2026-02-10', progress=False)
    spy_data = yf.download('SPY', start='2000-01-01', end='2026-02-10', progress=False)
    
    # Agregar VIX y SPY (ya son tz-naive)
    prices_df['VIX'] = vix_data['Close']
    prices_df['SPY'] = spy_data['Close']
    prices_df['VIX'] = prices_df['VIX'].ffill()
    
    # Filtrar fechas
    start_dt = pd.Timestamp('2000-01-03')
    end_dt = pd.Timestamp('2026-02-06')
    prices_df = prices_df[(prices_df.index >= start_dt) & (prices_df.index <= end_dt)]
    
    print(f"Datos cargados: {len(prices_df)} dias, {len(UNIVERSE)} stocks")
    return prices_df


def get_regime_leverage(vix):
    """Determina leverage basado en VIX"""
    if pd.isna(vix):
        return CONFIG['BASE_LEVERAGE'], 'normal'
    
    if vix < CONFIG['VIX_THRESHOLDS']['low']:
        return CONFIG['LEVERAGE_BY_REGIME']['low'], 'low'
    elif vix < CONFIG['VIX_THRESHOLDS']['medium']:
        return CONFIG['LEVERAGE_BY_REGIME']['normal'], 'normal'
    elif vix < CONFIG['VIX_THRESHOLDS']['high']:
        return CONFIG['LEVERAGE_BY_REGIME']['high'], 'high'
    else:
        return CONFIG['LEVERAGE_BY_REGIME']['crisis'], 'crisis'


def run_backtest(prices_df, use_regime=True):
    """Ejecuta backtest"""
    
    cash = CONFIG['INITIAL_CAPITAL']
    positions = {}
    portfolio_values = []
    
    peak_value = CONFIG['INITIAL_CAPITAL']
    in_protection = False
    protection_events = []
    regime_stats = {'low': 0, 'normal': 0, 'high': 0, 'crisis': 0, 'fixed': 0}
    
    stock_cols = [c for c in prices_df.columns if c not in ['VIX', 'SPY']]
    
    for i, (date, row) in enumerate(prices_df.iterrows()):
        vix = row.get('VIX', np.nan)
        
        if use_regime:
            leverage, regime = get_regime_leverage(vix)
        else:
            leverage = CONFIG['BASE_LEVERAGE']
            regime = 'fixed'
        
        regime_stats[regime] += 1
        
        # Calcular valor del portfolio
        portfolio_value = cash
        for symbol, pos in positions.items():
            price = row.get(symbol, np.nan)
            if not pd.isna(price):
                portfolio_value += pos['shares'] * price
        
        # Actualizar peak
        if portfolio_value > peak_value:
            peak_value = portfolio_value
            if in_protection and portfolio_value >= peak_value * 0.95:
                in_protection = False
        
        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0
        
        # Stop loss
        if drawdown <= CONFIG['STOP_LOSS_PCT'] and not in_protection:
            for symbol, pos in list(positions.items()):
                price = row.get(symbol, np.nan)
                if not pd.isna(price):
                    proceeds = pos['shares'] * price * (1 - CONFIG['SLIPPAGE_PCT'])
                    commission = pos['shares'] * CONFIG['COMMISSION_PER_SHARE']
                    cash += proceeds - commission
            positions = {}
            in_protection = True
            protection_events.append({'date': date, 'dd': drawdown})
        
        if in_protection:
            leverage = 1.0
        
        # Cerrar expiradas
        for symbol, pos in list(positions.items()):
            minutes_held = (date - pos['entry_date']).total_seconds() / 60
            if minutes_held >= CONFIG['HOLD_MINUTES']:
                price = row.get(symbol, np.nan)
                if not pd.isna(price):
                    proceeds = pos['shares'] * price * (1 - CONFIG['SLIPPAGE_PCT'])
                    commission = pos['shares'] * CONFIG['COMMISSION_PER_SHARE']
                    cash += proceeds - commission
                    del positions[symbol]
        
        # Abrir nuevas
        slots = CONFIG['NUM_POSITIONS'] - len(positions)
        if slots > 0 and not in_protection:
            available = [s for s in stock_cols if not pd.isna(row.get(s)) and s not in positions]
            
            if len(available) >= slots:
                random.seed(CONFIG['RANDOM_SEED'] + i)
                selected = random.sample(available, slots)
                
                effective_cash = cash * leverage
                pos_value = effective_cash * 0.95 / CONFIG['NUM_POSITIONS']
                
                for symbol in selected:
                    price = row.get(symbol, np.nan)
                    if pd.isna(price) or price <= 0:
                        continue
                    
                    shares = pos_value / price
                    cost = shares * price * (1 + CONFIG['SLIPPAGE_PCT'])
                    commission = shares * CONFIG['COMMISSION_PER_SHARE']
                    
                    if cost + commission <= cash * 0.95:
                        cash -= cost + commission
                        positions[symbol] = {
                            'shares': shares,
                            'entry_price': price,
                            'entry_date': date,
                        }
        
        # Costos margin
        borrowed = max(0, portfolio_value - cash)
        daily_cost = borrowed * (CONFIG['BORROW_RATE_ANNUAL'] / 252)
        cash -= daily_cost
        
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'regime': regime,
            'leverage': leverage,
            'vix': vix,
            'drawdown': drawdown,
        })
    
    return pd.DataFrame(portfolio_values), protection_events, regime_stats


def analyze(df, events, regime_stats, label):
    """Analiza resultados"""
    
    initial = CONFIG['INITIAL_CAPITAL']
    final = df['value'].iloc[-1]
    years = (df['date'].iloc[-1] - df['date'].iloc[0]).days / 365.25
    cagr = (final / initial) ** (1/years) - 1
    
    df['peak'] = df['value'].cummax()
    df['dd'] = (df['value'] - df['peak']) / df['peak']
    max_dd = df['dd'].min()
    
    returns = df['value'].pct_change().dropna()
    sharpe = returns.mean() / returns.std() * np.sqrt(252)
    vol = returns.std() * np.sqrt(252)
    avg_leverage = df['leverage'].mean()
    
    print(f"\n{'='*55}")
    print(f"RESULTADOS: {label}")
    print(f"{'='*55}")
    print(f"CAGR:           {cagr:>8.2%}")
    print(f"Max DD:         {max_dd:>8.2%}")
    print(f"Sharpe:         {sharpe:>8.2f}")
    print(f"Volatility:     {vol:>8.2%}")
    print(f"Final Equity:   ${final:>8,.0f}")
    print(f"Stop Events:    {len(events):>8}")
    print(f"Avg Leverage:   {avg_leverage:>8.2f}x")
    
    print(f"\nRegimen Distribution:")
    total = sum(regime_stats.values())
    for regime, count in sorted(regime_stats.items()):
        if count > 0:
            print(f"  {regime:10}: {count:5} days ({count/total*100:5.1f}%)")
    
    return {'cagr': cagr, 'max_dd': max_dd, 'sharpe': sharpe, 
            'vol': vol, 'final': final, 'events': len(events), 'avg_lev': avg_leverage}


def main():
    """Comparacion v6 vs v7"""
    
    prices_df = load_data()
    
    # Test v6
    print("\n" + "="*55)
    print("TEST 1: v6 (LEVERAGE FIJO 2.0)")
    print("="*55)
    df_v6, events_v6, stats_v6 = run_backtest(prices_df, use_regime=False)
    m_v6 = analyze(df_v6, events_v6, stats_v6, "v6 (Leverage Fijo)")
    
    # Test v7
    print("\n" + "="*55)
    print("TEST 2: v7 (LEVERAGE ADAPTATIVO)")
    print("="*55)
    df_v7, events_v7, stats_v7 = run_backtest(prices_df, use_regime=True)
    m_v7 = analyze(df_v7, events_v7, stats_v7, "v7 (Regimen Adaptativo)")
    
    # Comparacion
    print("\n" + "="*55)
    print("COMPARACION v6 vs v7")
    print("="*55)
    print(f"{'Metric':<15} {'v6':>10} {'v7':>10} {'Diff':>10}")
    print("-"*55)
    print(f"{'CAGR':<15} {m_v6['cagr']:>9.2%} {m_v7['cagr']:>9.2%} {m_v7['cagr']-m_v6['cagr']:>+9.2%}")
    print(f"{'Max DD':<15} {m_v6['max_dd']:>9.2%} {m_v7['max_dd']:>9.2%} {m_v7['max_dd']-m_v6['max_dd']:>+9.2%}")
    print(f"{'Sharpe':<15} {m_v6['sharpe']:>9.2f} {m_v7['sharpe']:>9.2f} {m_v7['sharpe']-m_v6['sharpe']:>+9.2f}")
    print(f"{'Final Equity':<15} ${m_v6['final']:>8,.0f} ${m_v7['final']:>8,.0f}")
    
    # Veredicto
    improvement = m_v7['cagr'] - m_v6['cagr']
    print(f"\n{'='*55}")
    if improvement > 0.005:
        print(f"[OK] v7 MEJORA v6 en {improvement:.2%} CAGR")
        print("  RECOMENDACION: Implementar regimen adaptativo")
    elif improvement > -0.005:
        print(f"[~] v7 es NEUTRAL ({improvement:+.2%} CAGR)")
        print("  RECOMENDACION: Mantener v6 (simplicidad > complejidad)")
    else:
        print(f"[X] v7 EMPEORA v6 en {improvement:.2%} CAGR")
        print("  RECOMENDACION: Descartar, mantener v6")
    
    # Guardar
    results = {'v6': m_v6, 'v7': m_v7, 'improvement': improvement}
    with open('v7_regime_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\nResultados guardados: v7_regime_results.json")
    return results


if __name__ == "__main__":
    results = main()
