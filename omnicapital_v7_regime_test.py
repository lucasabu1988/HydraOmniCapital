"""
OmniCapital v7 - Regime-Based Leverage Test
Test de leverage adaptativo basado en VIX
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# CONFIGURACION
# =============================================================================

CONFIG = {
    'START_DATE': '2000-01-03',
    'END_DATE': '2026-02-06',
    'INITIAL_CAPITAL': 100000,
    
    # Parametros base (v6)
    'HOLD_MINUTES': 1200,
    'NUM_POSITIONS': 5,
    'STOP_LOSS_PCT': -0.20,
    'BASE_LEVERAGE': 2.0,
    'MIN_AGE_DAYS': 63,
    'RANDOM_SEED': 42,
    
    # Costos
    'COMMISSION_PER_SHARE': 0.001,
    'SLIPPAGE_PCT': 0.001,
    'BORROW_RATE_ANNUAL': 0.06,
    
    # Regimenes de VIX (nuevo en v7)
    'VIX_THRESHOLDS': {
        'low': 15,      # VIX < 15: mercado calmado
        'medium': 25,   # VIX 15-25: normal
        'high': 35,     # VIX 25-35: volatil
    },
    'LEVERAGE_BY_REGIME': {
        'low': 2.5,     # Mas leverage en calma
        'normal': 2.0,  # Leverage base
        'high': 1.5,    # Menos leverage en volatilidad
        'crisis': 1.0,  # Sin leverage en crisis
    },
    'MIN_DAYS_IN_REGIME': 3,  # Minimo dias antes de cambiar
}

# Universo S&P 500 large-caps
UNIVERSE = [
    'AAPL', 'MSFT', 'AMZN', 'NVDA', 'GOOGL', 'META', 'TSLA', 'AVGO',
    'BRK-B', 'JPM', 'V', 'JNJ', 'WMT', 'MA', 'PG', 'UNH', 'HD', 'CVX',
    'MRK', 'PEP', 'KO', 'ABBV', 'BAC', 'COST', 'TMO', 'DIS',
    'ABT', 'WFC', 'ACN', 'VZ', 'DHR', 'ADBE', 'CRM', 'TXN', 'NKE',
    'NEE', 'AMD', 'PM', 'XOM', 'INTC', 'CSCO', 'IBM', 'GE', 'CAT',
    'BA', 'MMM', 'AXP', 'GS', 'MO', 'KMB', 'CL', 'MDT', 'SLB', 'UNP',
    'HON', 'FDX', 'UPS', 'LMT', 'RTX', 'OXY', 'AMGN', 'LLY', 'BMY', 'BIIB'
]


# =============================================================================
# CARGA DE DATOS
# =============================================================================

def load_data():
    """Carga datos de precios y VIX"""
    print("Cargando datos...")
    
    # Intentar cargar cache
    import os
    cache_file = 'data_cache/dynamic_universe_2000-01-01_2026-02-09.pkl'
    
    if os.path.exists(cache_file):
        df = pd.read_pickle(cache_file)
        print(f"Cache cargado: {len(df)} filas, {len([c for c in df.columns if c not in ['SPY', 'VIX']])} stocks")
    else:
        raise FileNotFoundError(f"No se encontro cache: {cache_file}")
    
    # Verificar VIX
    if 'VIX' not in df.columns:
        print("Descargando VIX...")
        vix = yf.download('^VIX', start='1999-01-01', end='2026-02-10', progress=False)
        df['VIX'] = vix['Close']
    
    # Forward fill VIX (solo hay datos en dias de mercado)
    df['VIX'] = df['VIX'].ffill()
    
    return df


def get_vix_regime(vix_value, current_regime, days_in_regime):
    """
    Determina el regimen basado en VIX con hysteresis
    """
    if pd.isna(vix_value):
        return current_regime
    
    # Umbrales
    low = CONFIG['VIX_THRESHOLDS']['low']
    medium = CONFIG['VIX_THRESHOLDS']['medium']
    high = CONFIG['VIX_THRESHOLDS']['high']
    
    # Determinar nuevo regimen
    if vix_value < low:
        new_regime = 'low'
    elif vix_value < medium:
        new_regime = 'normal'
    elif vix_value < high:
        new_regime = 'high'
    else:
        new_regime = 'crisis'
    
    # Hysteresis: requerir minimo dias en regimen
    if new_regime != current_regime and days_in_regime < CONFIG['MIN_DAYS_IN_REGIME']:
        return current_regime
    
    return new_regime


# =============================================================================
# BACKTEST ENGINE
# =============================================================================

def run_backtest_regime(df, use_regime=True, verbose=True):
    """
    Ejecuta backtest con leverage adaptativo
    
    Parameters:
    -----------
    df : DataFrame con precios y VIX
    use_regime : bool
        True = usar leverage adaptativo (v7)
        False = usar leverage fijo 2.0 (v6)
    """
    
    # Filtrar fechas
    df = df[df.index >= CONFIG['START_DATE']].copy()
    df = df[df.index <= CONFIG['END_DATE']]
    
    # Identificar columnas de stocks
    stock_cols = [c for c in df.columns if c not in ['SPY', 'VIX']]
    
    # Estado del portfolio
    cash = CONFIG['INITIAL_CAPITAL']
    positions = {}  # symbol -> {shares, entry_price, entry_date}
    portfolio_values = []
    trades = []
    
    # Tracking de regimen
    current_regime = 'normal'
    days_in_regime = 0
    regime_history = []
    leverage_history = []
    
    # Tracking de stop loss
    peak_value = CONFIG['INITIAL_CAPITAL']
    in_protection = False
    protection_events = []
    
    if verbose:
        mode = "REGIMEN ADAPTATIVO" if use_regime else "LEVERAGE FIJO (v6)"
        print(f"\n{'='*60}")
        print(f"BACKTEST: {mode}")
        print(f"{'='*60}")
    
    for i, (date, row) in enumerate(df.iterrows()):
        # Obtener VIX y determinar regimen
        vix = row.get('VIX', np.nan)
        
        if use_regime and not pd.isna(vix):
            new_regime = get_vix_regime(vix, current_regime, days_in_regime)
            if new_regime == current_regime:
                days_in_regime += 1
            else:
                current_regime = new_regime
                days_in_regime = 1
            
            leverage = CONFIG['LEVERAGE_BY_REGIME'][current_regime]
        else:
            leverage = CONFIG['BASE_LEVERAGE']
            current_regime = 'fixed'
        
        regime_history.append(current_regime)
        leverage_history.append(leverage)
        
        # Calcular valor del portfolio
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            price = row.get(symbol, np.nan)
            if not pd.isna(price):
                portfolio_value += pos['shares'] * price
        
        # Actualizar peak
        if portfolio_value > peak_value:
            peak_value = portfolio_value
            if in_protection and portfolio_value >= peak_value * 0.95:
                in_protection = False
                if verbose:
                    print(f"\n[{date.strftime('%Y-%m-%d')}] RECUPERACION - Saliendo de proteccion")
        
        # Calcular drawdown
        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0
        
        # Verificar stop loss
        if drawdown <= CONFIG['STOP_LOSS_PCT'] and not in_protection:
            if verbose:
                print(f"\n[{date.strftime('%Y-%m-%d')}] STOP LOSS ACTIVADO: DD={drawdown:.2%}")
            
            # Cerrar todas las posiciones
            for symbol, pos in list(positions.items()):
                price = row.get(symbol, np.nan)
                if not pd.isna(price):
                    proceeds = pos['shares'] * price * (1 - CONFIG['SLIPPAGE_PCT'])
                    commission = pos['shares'] * CONFIG['COMMISSION_PER_SHARE']
                    cash += proceeds - commission
                    
                    trades.append({
                        'date': date,
                        'symbol': symbol,
                        'action': 'SELL_STOP',
                        'shares': pos['shares'],
                        'price': price,
                    })
            
            positions = {}
            in_protection = True
            protection_events.append({
                'date': date,
                'portfolio_value': portfolio_value,
                'drawdown': drawdown
            })
            
            if verbose:
                print(f"  Posiciones cerradas. Leverage reducido a 1.0x")
        
        # Si estamos en proteccion, no abrir nuevas posiciones
        if in_protection:
            leverage = 1.0
        
        # Cerrar posiciones expiradas
        for symbol, pos in list(positions.items()):
            minutes_held = (date - pos['entry_date']).total_seconds() / 60
            
            if minutes_held >= CONFIG['HOLD_MINUTES']:
                price = row.get(symbol, np.nan)
                if not pd.isna(price):
                    proceeds = pos['shares'] * price * (1 - CONFIG['SLIPPAGE_PCT'])
                    commission = pos['shares'] * CONFIG['COMMISSION_PER_SHARE']
                    cash += proceeds - commission
                    
                    pnl = (price - pos['entry_price']) * pos['shares'] - commission
                    
                    trades.append({
                        'date': date,
                        'symbol': symbol,
                        'action': 'SELL_EXPIRED',
                        'shares': pos['shares'],
                        'price': price,
                        'pnl': pnl,
                    })
                    
                    del positions[symbol]
        
        # Abrir nuevas posiciones
        current_positions = set(positions.keys())
        slots_available = CONFIG['NUM_POSITIONS'] - len(positions)
        
        if slots_available > 0 and not in_protection:
            # Encontrar stocks disponibles
            available = []
            for symbol in stock_cols:
                price = row.get(symbol, np.nan)
                if not pd.isna(price) and price > 0 and symbol not in current_positions:
                    # Verificar antiguedad minima (simplificado)
                    available.append(symbol)
            
            if len(available) >= slots_available:
                random.seed(CONFIG['RANDOM_SEED'] + i)
                selected = random.sample(available, slots_available)
                
                # Calcular tamaño de posicion
                effective_cash = cash * leverage
                position_value = effective_cash * 0.95 / CONFIG['NUM_POSITIONS']
                
                for symbol in selected:
                    price = row.get(symbol, np.nan)
                    if pd.isna(price) or price <= 0:
                        continue
                    
                    shares = position_value / price
                    cost = shares * price * (1 + CONFIG['SLIPPAGE_PCT'])
                    commission = shares * CONFIG['COMMISSION_PER_SHARE']
                    total_cost = cost + commission
                    
                    if total_cost <= cash * 0.95:
                        cash -= total_cost
                        positions[symbol] = {
                            'shares': shares,
                            'entry_price': price,
                            'entry_date': date,
                        }
                        
                        trades.append({
                            'date': date,
                            'symbol': symbol,
                            'action': 'BUY',
                            'shares': shares,
                            'price': price,
                        })
        
        # Calcular costos de margin
        borrowed = max(0, portfolio_value - cash)
        daily_borrow_cost = borrowed * (CONFIG['BORROW_RATE_ANNUAL'] / 252)
        cash -= daily_borrow_cost
        
        # Registrar valor
        portfolio_values.append({
            'date': date,
            'portfolio_value': portfolio_value,
            'cash': cash,
            'positions_value': portfolio_value - cash,
            'drawdown': drawdown,
            'regime': current_regime,
            'leverage': leverage,
            'vix': vix,
        })
    
    # Convertir a DataFrame
    portfolio_df = pd.DataFrame(portfolio_values)
    portfolio_df.set_index('date', inplace=True)
    
    return portfolio_df, trades, protection_events, regime_history


def analyze_results(portfolio_df, trades, protection_events, label):
    """Analiza resultados del backtest"""
    
    print(f"\n{'='*60}")
    print(f"RESULTADOS: {label}")
    print(f"{'='*60}")
    
    # Metricas basicas
    initial = CONFIG['INITIAL_CAPITAL']
    final = portfolio_df['portfolio_value'].iloc[-1]
    total_return = (final - initial) / initial
    
    # CAGR
    years = (portfolio_df.index[-1] - portfolio_df.index[0]).days / 365.25
    cagr = (final / initial) ** (1/years) - 1
    
    # Drawdown
    portfolio_df['peak'] = portfolio_df['portfolio_value'].cummax()
    portfolio_df['drawdown'] = (portfolio_df['portfolio_value'] - portfolio_df['peak']) / portfolio_df['peak']
    max_dd = portfolio_df['drawdown'].min()
    
    # Sharpe (aproximado)
    returns = portfolio_df['portfolio_value'].pct_change().dropna()
    sharpe = returns.mean() / returns.std() * np.sqrt(252)
    
    # Volatilidad
    vol = returns.std() * np.sqrt(252)
    
    # Regimen stats
    regime_counts = portfolio_df['regime'].value_counts()
    leverage_avg = portfolio_df['leverage'].mean()
    
    print(f"\nMetricas Principales:")
    print(f"  Initial Capital:    ${initial:,.2f}")
    print(f"  Final Equity:       ${final:,.2f}")
    print(f"  Total Return:       {total_return:.2%}")
    print(f"  CAGR:               {cagr:.2%}")
    print(f"  Max Drawdown:       {max_dd:.2%}")
    print(f"  Sharpe Ratio:       {sharpe:.2f}")
    print(f"  Volatility:         {vol:.2%}")
    
    print(f"\nRegimen Analysis:")
    for regime, count in regime_counts.items():
        pct = count / len(portfolio_df) * 100
        print(f"  {regime:12}: {count:5} dias ({pct:5.1f}%)")
    print(f"  Leverage promedio:  {leverage_avg:.2f}x")
    
    print(f"\nStop Loss Events: {len(protection_events)}")
    for event in protection_events:
        print(f"  {event['date'].strftime('%Y-%m-%d')}: DD={event['drawdown']:.2%}")
    
    return {
        'cagr': cagr,
        'max_dd': max_dd,
        'sharpe': sharpe,
        'vol': vol,
        'final_equity': final,
        'protection_events': len(protection_events),
        'leverage_avg': leverage_avg,
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Ejecuta comparacion v6 vs v7"""
    
    # Cargar datos
    df = load_data()
    
    # Test 1: v6 (leverage fijo 2.0)
    print("\n" + "="*60)
    print("TEST 1: v6 - LEVERAGE FIJO 2.0")
    print("="*60)
    portfolio_v6, trades_v6, stops_v6, regime_v6 = run_backtest_regime(
        df, use_regime=False, verbose=True
    )
    metrics_v6 = analyze_results(portfolio_v6, trades_v6, stops_v6, "v6 (Leverage Fijo)")
    
    # Test 2: v7 (leverage adaptativo)
    print("\n" + "="*60)
    print("TEST 2: v7 - LEVERAGE ADAPTATIVO POR REGIMEN")
    print("="*60)
    portfolio_v7, trades_v7, stops_v7, regime_v7 = run_backtest_regime(
        df, use_regime=True, verbose=True
    )
    metrics_v7 = analyze_results(portfolio_v7, trades_v7, stops_v7, "v7 (Regimen Adaptativo)")
    
    # Comparacion
    print("\n" + "="*60)
    print("COMPARACION v6 vs v7")
    print("="*60)
    print(f"\n{'Metrica':<20} {'v6':>12} {'v7':>12} {'Diff':>12}")
    print("-" * 60)
    
    for metric in ['cagr', 'max_dd', 'sharpe', 'vol', 'leverage_avg']:
        v6_val = metrics_v6[metric]
        v7_val = metrics_v7[metric]
        diff = v7_val - v6_val
        
        if metric in ['cagr', 'max_dd', 'vol']:
            print(f"{metric:<20} {v6_val:>11.2%} {v7_val:>11.2%} {diff:>+11.2%}")
        else:
            print(f"{metric:<20} {v6_val:>11.2f} {v7_val:>11.2f} {diff:>+11.2f}")
    
    print(f"\n{'Final Equity':<20} ${metrics_v6['final_equity']:>10,.0f} ${metrics_v7['final_equity']:>10,.0f}")
    print(f"{'Stop Events':<20} {metrics_v6['protection_events']:>11} {metrics_v7['protection_events']:>11}")
    
    # Veredicto
    print("\n" + "="*60)
    print("VEREDICTO")
    print("="*60)
    
    improvement = metrics_v7['cagr'] - metrics_v6['cagr']
    
    if improvement > 0.005:  # +0.5% CAGR
        print(f"✓ v7 MEJORA v6 en {improvement:.2%} CAGR")
        print("  RECOMENDACION: Implementar regimen adaptativo")
    elif improvement > -0.005:  # +/- 0.5%
        print(f"≈ v7 es NEUTRAL vs v6 ({improvement:+.2%} CAGR)")
        print("  RECOMENDACION: Mantener v6 (simplicidad > complejidad)")
    else:
        print(f"✗ v7 EMPEORA v6 en {improvement:.2%} CAGR")
        print("  RECOMENDACION: Descartar, mantener v6")
    
    # Guardar resultados
    results = {
        'v6': metrics_v6,
        'v7': metrics_v7,
        'improvement': improvement,
    }
    
    import json
    with open('omnicapital_v7_regime_test_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\nResultados guardados en: omnicapital_v7_regime_test_results.json")
    
    return results


if __name__ == "__main__":
    results = main()
