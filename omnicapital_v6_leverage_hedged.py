"""
OmniCapital v6 - Leveraged & Hedged
Version con leverage 2:1 y proteccion contra drawdowns.
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

HOLD_MINUTES = 1200  # 20 horas (optimizado)
NUM_POSITIONS = 5
INITIAL_CAPITAL = 100_000
RANDOM_SEED = 42
COMMISSION_PER_SHARE = 0.001
MIN_AGE_DAYS = 63

# PARAMETROS DE LEVERAGE Y HEDGE
LEVERAGE = 2.0                    # 2:1 (maximo regulado overnight)
MARGIN_RATE = 0.06                # 6% anual sobre capital prestado
HEDGE_COST_PCT = 0.025            # 2.5% anual por proteccion (puts OTM)
PORTFOLIO_STOP_LOSS = -0.20       # Stop loss en portfolio level (-20%)
REDUCE_LEVERAGE_AFTER_DD = True   # Reducir leverage despues de drawdown

print("=" * 70)
print("OMNICAPITAL v6 - LEVERAGED & HEDGED")
print("=" * 70)
print(f"\nConfiguracion:")
print(f"  - Leverage: {LEVERAGE:.1f}:1")
print(f"  - Costo de margin: {MARGIN_RATE:.1%} anual")
print(f"  - Costo de hedge: {HEDGE_COST_PCT:.1%} anual")
print(f"  - Portfolio stop loss: {PORTFOLIO_STOP_LOSS:.0%}")
print(f"  - Hold time: {HOLD_MINUTES} minutos")
print()
print("ADVERTENCIA: Leverage amplifica perdidas. Este es un modelo teorico.")
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


def run_backtest_leveraged(price_data):
    """Backtest con leverage y hedge"""
    
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    first_date = all_dates[0]
    
    # Capital propio + prestado
    equity = INITIAL_CAPITAL
    borrowed = INITIAL_CAPITAL * (LEVERAGE - 1)  # Para 2:1, prestamos 1x
    total_capital = equity + borrowed
    
    cash = total_capital
    positions = {}
    portfolio_values = []
    trades = []
    
    current_leverage = LEVERAGE
    peak_value = total_capital
    in_drawdown_protection = False
    
    daily_margin_cost = MARGIN_RATE / 252 * borrowed
    daily_hedge_cost = HEDGE_COST_PCT / 252 * total_capital
    
    print(f"Capital inicial: ${INITIAL_CAPITAL:,.0f}")
    print(f"Borrowed: ${borrowed:,.0f}")
    print(f"Total trading capital: ${total_capital:,.0f}\n")
    
    for i, date in enumerate(all_dates):
        tradeable = get_tradeable(price_data, date, first_date)
        
        # Calcular valor del portfolio (mark-to-market)
        portfolio_value = cash
        for sym, pos in list(positions.items()):
            if sym in price_data and date in price_data[sym].index:
                portfolio_value += pos['shares'] * price_data[sym].loc[date, 'Close']
        
        # Actualizar peak y calcular drawdown
        if portfolio_value > peak_value:
            peak_value = portfolio_value
            in_drawdown_protection = False  # Salir de proteccion
        
        drawdown = (portfolio_value - peak_value) / peak_value
        
        # STOP LOSS EN PORTFOLIO LEVEL
        if drawdown <= PORTFOLIO_STOP_LOSS and not in_drawdown_protection:
            print(f"\n  [STOP LOSS] {date.strftime('%Y-%m-%d')}: DD {drawdown:.1%}")
            print(f"  Cerrando todas las posiciones y reduciendo leverage...")
            
            # Cerrar todas las posiciones
            for sym in list(positions.keys()):
                if sym in price_data and date in price_data[sym].index:
                    price = price_data[sym].loc[date, 'Close']
                    cash += positions[sym]['shares'] * price
                del positions[sym]
            
            # Reducir leverage
            if REDUCE_LEVERAGE_AFTER_DD:
                current_leverage = 1.0  # Volver a 1:1 (sin leverage)
                borrowed = 0
                print(f"  Leverage reducido a {current_leverage:.1f}:1")
            
            in_drawdown_protection = True
        
        # Cobrar costos diarios (margin + hedge)
        if not in_drawdown_protection:
            daily_cost = daily_margin_cost + daily_hedge_cost
            cash -= daily_cost
        
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
                    trades.append({'pnl': pnl, 'leverage': current_leverage})
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
                
                # Sizing con leverage actual
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
            'cash': cash,
            'positions': len(positions),
            'drawdown': drawdown,
            'leverage': current_leverage
        })
        
        if i % 252 == 0 and i > 0:
            year = i // 252
            equity_value = portfolio_value - borrowed if borrowed > 0 else portfolio_value
            print(f"  Año {year}: ${portfolio_value:,.0f} | Equity: ${equity_value:,.0f} | "
                  f"DD: {drawdown:.1%} | Lev: {current_leverage:.1f}x")
    
    return portfolio_values, trades


def calculate_metrics(portfolio_values, trades):
    df = pd.DataFrame(portfolio_values).set_index('date')
    
    initial = INITIAL_CAPITAL * LEVERAGE  # Capital efectivo inicial
    final = df['value'].iloc[-1]
    
    # Calcular equity final (restando deuda)
    borrowed = INITIAL_CAPITAL * (LEVERAGE - 1)
    final_equity = final - borrowed if final > borrowed else 0
    
    years = len(df) / 252
    
    # CAGR basado en equity, no en valor total
    cagr = (final_equity / INITIAL_CAPITAL) ** (1/years) - 1
    
    returns = df['value'].pct_change().dropna()
    vol = returns.std() * np.sqrt(252)
    
    max_dd = df['drawdown'].min()
    
    sharpe = cagr / vol if vol > 0 else 0
    
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    
    # Contar reducciones de leverage
    leverage_changes = (df['leverage'] != df['leverage'].shift()).sum()
    
    return {
        'cagr': cagr,
        'final_value': final,
        'final_equity': final_equity,
        'volatility': vol,
        'sharpe': sharpe,
        'max_drawdown': max_dd,
        'win_rate': win_rate,
        'trades': len(trades_df),
        'leverage_changes': leverage_changes
    }


print("Cargando datos...")
price_data = load_data()
print(f"{len(price_data)} símbolos\n")

print("Ejecutando backtest con leverage y hedge...")
portfolio_values, trades = run_backtest_leveraged(price_data)
metrics = calculate_metrics(portfolio_values, trades)

print("\n" + "=" * 70)
print("RESULTADOS - LEVERAGED & HEDGED")
print("=" * 70)
print(f"\nCapital inicial:        ${INITIAL_CAPITAL:>15,.0f}")
print(f"Valor final (total):    ${metrics['final_value']:>15,.2f}")
print(f"Equity final (neto):    ${metrics['final_equity']:>15,.2f}")
print(f"CAGR (en equity):       {metrics['cagr']:>15.2%}")
print(f"Volatilidad anual:      {metrics['volatility']:>15.2%}")
print(f"Sharpe ratio:           {metrics['sharpe']:>15.2f}")
print(f"Max drawdown:           {metrics['max_drawdown']:>15.2%}")
print(f"Win rate:               {metrics['win_rate']:>15.2%}")
print(f"Trades:                 {metrics['trades']:>15,}")
print(f"Cambios de leverage:    {metrics['leverage_changes']:>15,}")

print("\n" + "=" * 70)
print("COMPARATIVA")
print("=" * 70)
print(f"\n{'Versión':<35} {'CAGR':<12} {'Max DD':<12} {'Sharpe':<10}")
print("-" * 70)
print(f"{'Base (sin leverage)':<35} {'15.11%':<12} {'-42.8%':<12} {'0.73':<10}")
print(f"{'Leveraged 2:1 + Hedged':<35} {f"{metrics['cagr']:.2%}":<12} {f"{metrics['max_drawdown']:.1%}":<12} {f"{metrics['sharpe']:.2f}":<10}")

print("\n" + "=" * 70)
print("ANALISIS DE COSTOS")
print("=" * 70)
print(f"\nCosto estimado de margin (6% anual):  ${INITIAL_CAPITAL * (LEVERAGE-1) * MARGIN_RATE * 26:,.0f}")
print(f"Costo estimado de hedge (2.5% anual): ${INITIAL_CAPITAL * LEVERAGE * HEDGE_COST_PCT * 26:,.0f}")
print(f"Costo total estimado (26 años):       ${INITIAL_CAPITAL * ((LEVERAGE-1)*MARGIN_RATE + LEVERAGE*HEDGE_COST_PCT) * 26:,.0f}")

with open('results_v6_leverage_hedged.pkl', 'wb') as f:
    pickle.dump({'metrics': metrics, 'portfolio_values': portfolio_values}, f)

print(f"\n\nGuardado en: results_v6_leverage_hedged.pkl")

print("\n" + "=" * 70)
print("ADVERTENCIA LEGAL")
print("=" * 70)
print("\nEste es un modelo teorico. En la practica:")
print("- El leverage requiere margin calls que pueden forzar liquidacion")
print("- Los costos de hedge (puts) pueden ser mayores en volatilidad alta")
print("- El stop loss de portfolio no garantiza ejecucion exacta")
print("- Resultados pasados no garantizan resultados futuros")
print("=" * 70)
