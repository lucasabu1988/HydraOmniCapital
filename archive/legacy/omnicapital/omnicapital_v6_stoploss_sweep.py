"""
OmniCapital v6 - Stop Loss Sweep
Encuentra el nivel optimo de stop loss para la estrategia con leverage.
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

HOLD_MINUTES = 1200
NUM_POSITIONS = 5
INITIAL_CAPITAL = 100_000
RANDOM_SEED = 42
COMMISSION_PER_SHARE = 0.001
MIN_AGE_DAYS = 63

LEVERAGE = 2.0
MARGIN_RATE = 0.06
HEDGE_COST_PCT = 0.025

# Niveles de stop loss a testear
STOP_LOSS_LEVELS = [-0.10, -0.15, -0.20, -0.25, -0.30]

print("=" * 80)
print("OMNICAPITAL v6 - STOP LOSS OPTIMIZATION")
print("=" * 80)
print(f"\nTesteando {len(STOP_LOSS_LEVELS)} niveles de stop loss...")
print(f"Leverage: {LEVERAGE:.1f}:1 | Hold: {HOLD_MINUTES} min")
print()


def load_data():
    cache_file = 'data_cache/dynamic_universe_2000-01-01_2026-02-09.pkl'
    with open(cache_file, 'rb') as f:
        return pickle.load(f)


def get_tradeable(price_data, date, first_date):
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


def run_backtest_with_stop(price_data, stop_loss_pct):
    """Backtest con stop loss especifico"""
    
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    first_date = all_dates[0]
    
    equity = INITIAL_CAPITAL
    borrowed = INITIAL_CAPITAL * (LEVERAGE - 1)
    total_capital = equity + borrowed
    
    cash = total_capital
    positions = {}
    portfolio_values = []
    trades = []
    
    current_leverage = LEVERAGE
    peak_value = total_capital
    in_protection = False
    stop_count = 0
    
    daily_margin_cost = MARGIN_RATE / 252 * borrowed
    daily_hedge_cost = HEDGE_COST_PCT / 252 * total_capital
    
    for i, date in enumerate(all_dates):
        tradeable = get_tradeable(price_data, date, first_date)
        
        # Valor portfolio
        portfolio_value = cash
        for sym, pos in list(positions.items()):
            if sym in price_data and date in price_data[sym].index:
                portfolio_value += pos['shares'] * price_data[sym].loc[date, 'Close']
        
        # Actualizar peak
        if portfolio_value > peak_value:
            peak_value = portfolio_value
            if in_protection and portfolio_value > peak_value * 0.95:  # Recuperacion 5%
                in_protection = False
                current_leverage = LEVERAGE  # Restaurar leverage
        
        drawdown = (portfolio_value - peak_value) / peak_value
        
        # STOP LOSS
        if drawdown <= stop_loss_pct and not in_protection:
            stop_count += 1
            
            # Cerrar todo
            for sym in list(positions.keys()):
                if sym in price_data and date in price_data[sym].index:
                    price = price_data[sym].loc[date, 'Close']
                    cash += positions[sym]['shares'] * price
                del positions[sym]
            
            current_leverage = 1.0
            in_protection = True
        
        # Costos diarios
        if not in_protection:
            cash -= (daily_margin_cost + daily_hedge_cost)
        
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
                    pnl = (price - entry) * shares - commission
                    trades.append({'pnl': pnl})
                del positions[sym]
        
        # Cerrar no tradeables
        for sym in list(positions.keys()):
            if sym not in tradeable:
                if sym in price_data and date in price_data[sym].index:
                    cash += positions[sym]['shares'] * price_data[sym].loc[date, 'Close']
                del positions[sym]
        
        # Abrir nuevas
        needed = NUM_POSITIONS - len(positions)
        
        if needed > 0 and cash > 1000 and len(tradeable) >= needed:
            available_for_entry = [s for s in tradeable if s not in positions]
            
            if len(available_for_entry) >= needed:
                random.seed(RANDOM_SEED + date.toordinal())
                selected = random.sample(available_for_entry, needed)
                
                effective_capital = cash * current_leverage
                position_value = (effective_capital * 0.95) / NUM_POSITIONS
                
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
            'drawdown': drawdown,
            'leverage': current_leverage
        })
    
    return portfolio_values, trades, stop_count


def calculate_metrics(portfolio_values, trades, stop_count, stop_pct):
    df = pd.DataFrame(portfolio_values).set_index('date')
    
    borrowed = INITIAL_CAPITAL * (LEVERAGE - 1)
    final_equity = df['value'].iloc[-1] - borrowed
    
    years = len(df) / 252
    cagr = (final_equity / INITIAL_CAPITAL) ** (1/years) - 1
    
    returns = df['value'].pct_change().dropna()
    vol = returns.std() * np.sqrt(252)
    
    max_dd = df['drawdown'].min()
    sharpe = cagr / vol if vol > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    
    return {
        'stop_loss': stop_pct,
        'cagr': cagr,
        'final_equity': final_equity,
        'sharpe': sharpe,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'win_rate': win_rate,
        'trades': len(trades_df),
        'stop_triggers': stop_count
    }


print("Cargando datos...")
price_data = load_data()
print(f"{len(price_data)} símbolos\n")

results = []
for stop_pct in STOP_LOSS_LEVELS:
    print(f"Testeando STOP LOSS = {stop_pct:.0%}...")
    
    portfolio_values, trades, stop_count = run_backtest_with_stop(price_data, stop_pct)
    metrics = calculate_metrics(portfolio_values, trades, stop_count, stop_pct)
    results.append(metrics)
    
    print(f"  CAGR: {metrics['cagr']:.2%} | Final: ${metrics['final_equity']:,.0f} | "
          f"Sharpe: {metrics['sharpe']:.2f} | Stops: {metrics['stop_triggers']} | "
          f"Max DD: {metrics['max_drawdown']:.1%}")

# Tabla comparativa
print("\n" + "=" * 100)
print("RESULTADOS - STOP LOSS SWEEP")
print("=" * 100)
print(f"{'Stop Loss':<12} {'CAGR':<10} {'Final':<15} {'Sharpe':<8} {'Calmar':<8} {'Max DD':<10} {'Stops':<8} {'Trades'}")
print("-" * 100)

for r in results:
    print(f"{r['stop_loss']:<12.0%} {r['cagr']:<10.2%} ${r['final_equity']:<14,.0f} "
          f"{r['sharpe']:<8.2f} {r['calmar']:<8.2f} {r['max_drawdown']:<10.1%} "
          f"{r['stop_triggers']:<8} {r['trades']:<10,}")

# Encontrar optimos
best_cagr = max(results, key=lambda x: x['cagr'])
best_sharpe = max(results, key=lambda x: x['sharpe'])
best_calmar = max(results, key=lambda x: x['calmar'])

print("\n" + "=" * 100)
print("ÓPTIMOS")
print("=" * 100)
print(f"\nMEJOR CAGR:     Stop {best_cagr['stop_loss']:.0%} = {best_cagr['cagr']:.2%}")
print(f"MEJOR SHARPE:   Stop {best_sharpe['stop_loss']:.0%} = {best_sharpe['sharpe']:.2f}")
print(f"MEJOR CALMAR:   Stop {best_calmar['stop_loss']:.0%} = {best_calmar['calmar']:.2f}")

# Analisis
print("\n" + "=" * 100)
print("ANÁLISIS")
print("=" * 100)
print("\nStop loss muy ajustado (10%):")
print("  - Más triggers de stop (whipsaws)")
print("  - Sale temprano en drawdowns menores")
print("  - Puede perder recuperaciones")
print("\nStop loss muy amplio (30%):")
print("  - Menos protección")
print("  - Mayor drawdown máximo")
print("  - Menos triggers pero más dolorosos")
print("\nStop loss óptimo (~15-20%):")
print("  - Balance entre protección y permanencia")
print("  - Evita whipsaws pero protege en crisis")

with open('results_stoploss_sweep.pkl', 'wb') as f:
    pickle.dump(results, f)

print(f"\n\nGuardado en: results_stoploss_sweep.pkl")

# Recomendacion
print("\n" + "=" * 100)
print("RECOMENDACIÓN FINAL")
print("=" * 100)

# Ponderar CAGR (40%), Sharpe (30%), Calmar (30%)
for r in results:
    r['score'] = (r['cagr'] / best_cagr['cagr']) * 0.4 + \
                 (r['sharpe'] / best_sharpe['sharpe']) * 0.3 + \
                 (r['calmar'] / best_calmar['calmar']) * 0.3

best_overall = max(results, key=lambda x: x['score'])

print(f"\nSTOP LOSS ÓPTIMO: {best_overall['stop_loss']:.0%}")
print(f"  CAGR: {best_overall['cagr']:.2%}")
print(f"  Sharpe: {best_overall['sharpe']:.2f}")
print(f"  Max DD: {best_overall['max_drawdown']:.1%}")
print(f"  Stops ejecutados: {best_overall['stop_triggers']}")
