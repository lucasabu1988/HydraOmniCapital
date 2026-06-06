"""
OmniCapital v6 - Sweep de parámetros de antigüedad
Testea diferentes MIN_TENURE_DAYS para encontrar el óptimo
"""

import pandas as pd
import numpy as np
import pickle
import os
from typing import Dict, List
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARÁMETROS FIJOS
# ============================================================================

HOLD_MINUTES = 666
NUM_POSITIONS = 5
INITIAL_CAPITAL = 100_000
RANDOM_SEED = 42
MIN_SYMBOLS_THRESHOLD = 30
COMMISSION_PER_SHARE = 0.001

# Universo de 40 blue-chips
UNIVERSE = [
    'AAPL', 'MSFT', 'AMZN', 'NVDA', 'GOOGL', 'META', 'TSLA', 'AVGO',
    'BRK-B', 'JPM', 'V', 'JNJ', 'WMT', 'MA', 'PG', 'UNH', 'HD', 'CVX',
    'MRK', 'PEP', 'KO', 'ABBV', 'BAC', 'COST', 'TMO', 'MCD', 'DIS',
    'ABT', 'WFC', 'ACN', 'VZ', 'DHR', 'ADBE', 'CRM', 'TXN', 'NKE',
    'NEE', 'AMD', 'PM', 'XOM'
]

# Valores de antigüedad a testear
TENURE_OPTIONS = [0, 63, 126, 189, 252, 378, 504]


class TenureBacktester:
    """Backtester con antigüedad configurable"""
    
    def __init__(self, price_data: Dict[str, pd.DataFrame], min_tenure_days: int):
        self.price_data = price_data
        self.symbols = list(price_data.keys())
        self.min_tenure_days = min_tenure_days
        
        # Calcular fechas de inicio
        self.symbol_start_dates = {}
        for symbol, df in price_data.items():
            if not df.empty:
                self.symbol_start_dates[symbol] = df.index[0]
        
        # Construir fechas de trading
        all_dates = set()
        for df in price_data.values():
            all_dates.update(df.index)
        self.all_dates = sorted(list(all_dates))
    
    def get_eligible(self, date: pd.Timestamp) -> List[str]:
        """Retorna símbolos elegibles para la fecha"""
        eligible = []
        for symbol in self.symbols:
            if symbol not in self.price_data:
                continue
            if date not in self.price_data[symbol].index:
                continue
            if symbol not in self.symbol_start_dates:
                continue
            
            first_date = self.symbol_start_dates[symbol]
            tenure_days = (date - first_date).days
            
            if tenure_days >= self.min_tenure_days:
                eligible.append(symbol)
        return eligible
    
    def run(self) -> Dict:
        """Ejecuta backtest"""
        import random
        
        capital = INITIAL_CAPITAL
        positions = {}
        trades = []
        daily_values = []
        
        first_trade_date = None
        trades_count = 0
        
        for i, date in enumerate(self.all_dates):
            # Verificar salidas
            for symbol in list(positions.keys()):
                pos = positions[symbol]
                entry_date = pos['entry_date']
                hold_days = (date - entry_date).days
                minutes_held = hold_days * 390
                
                if minutes_held >= HOLD_MINUTES:
                    if symbol in self.price_data and date in self.price_data[symbol].index:
                        exit_price = self.price_data[symbol].loc[date, 'Close']
                        shares = pos['shares']
                        gross_value = shares * exit_price
                        commission = shares * COMMISSION_PER_SHARE
                        net_value = gross_value - commission
                        
                        pnl = net_value - (shares * pos['entry_price'])
                        
                        trades.append({
                            'symbol': symbol,
                            'entry_date': entry_date,
                            'exit_date': date,
                            'pnl': pnl
                        })
                        trades_count += 1
                        
                        capital += net_value
                        del positions[symbol]
            
            # Abrir nuevas posiciones
            eligible = self.get_eligible(date)
            
            if len(eligible) >= MIN_SYMBOLS_THRESHOLD:
                random.seed(RANDOM_SEED + date.toordinal())
                n_select = min(NUM_POSITIONS, len(eligible))
                selected = random.sample(eligible, n_select)
                
                available_slots = NUM_POSITIONS - len(positions)
                if available_slots > 0 and capital > 1000:
                    capital_per_position = capital / available_slots
                    
                    for symbol in selected:
                        if symbol not in positions and capital > 1000:
                            price = self.price_data[symbol].loc[date, 'Close']
                            shares = (capital_per_position / price) // 1
                            
                            if shares > 0:
                                commission = shares * COMMISSION_PER_SHARE
                                cost = shares * price + commission
                                
                                if cost <= capital:
                                    positions[symbol] = {
                                        'shares': shares,
                                        'entry_date': date,
                                        'entry_price': price
                                    }
                                    capital -= cost
                                    
                                    if first_trade_date is None:
                                        first_trade_date = date
            
            # Valorar portfolio
            portfolio_value = capital
            for symbol, pos in positions.items():
                if symbol in self.price_data and date in self.price_data[symbol].index:
                    price = self.price_data[symbol].loc[date, 'Close']
                    portfolio_value += pos['shares'] * price
            
            daily_values.append({
                'date': date,
                'value': portfolio_value,
                'eligible': len(eligible)
            })
        
        # Calcular métricas
        daily_df = pd.DataFrame(daily_values)
        final_value = daily_values[-1]['value']
        
        total_return = (final_value - INITIAL_CAPITAL) / INITIAL_CAPITAL
        years = len(daily_df) / 252
        cagr = (final_value / INITIAL_CAPITAL) ** (1/years) - 1
        
        daily_df['peak'] = daily_df['value'].cummax()
        daily_df['drawdown'] = (daily_df['value'] - daily_df['peak']) / daily_df['peak']
        max_dd = daily_df['drawdown'].min()
        
        daily_df['returns'] = daily_df['value'].pct_change()
        volatility = daily_df['returns'].std() * np.sqrt(252)
        sharpe = cagr / volatility if volatility > 0 else 0
        
        trades_df = pd.DataFrame(trades) if trades else pd.DataFrame()
        win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
        
        return {
            'min_tenure_days': self.min_tenure_days,
            'final_value': final_value,
            'cagr': cagr,
            'total_return': total_return,
            'max_drawdown': max_dd,
            'sharpe': sharpe,
            'volatility': volatility,
            'trades': len(trades_df),
            'win_rate': win_rate,
            'first_trade': first_trade_date,
            'daily': daily_df
        }


def load_data():
    cache_file = 'data_cache/fixed_2000-01-01_2026-02-09.pkl'
    with open(cache_file, 'rb') as f:
        return pickle.load(f)


# ============================================================================
# SWEEP DE ANTIGÜEDAD
# ============================================================================

print("=" * 80)
print("OMNICAPITAL v6 - SWEEP DE ANTIGÜEDAD (EXISTENCE TENURE)")
print("=" * 80)
print()

price_data = load_data()

results = []
for tenure_days in TENURE_OPTIONS:
    print(f"\nTesteando MIN_TENURE_DAYS = {tenure_days}...")
    
    backtester = TenureBacktester(price_data, tenure_days)
    result = backtester.run()
    results.append(result)
    
    tenure_label = f"{tenure_days}d ({tenure_days/252:.1f}a)" if tenure_days > 0 else "0d (sin filtro)"
    print(f"  CAGR: {result['cagr']:.2%} | Final: ${result['final_value']:,.0f} | "
          f"Trades: {result['trades']:,} | Primer trade: {result['first_trade']}")

# Tabla comparativa
print("\n" + "=" * 80)
print("RESULTADOS COMPARATIVOS")
print("=" * 80)
print()
print(f"{'Antigüedad':<15} {'CAGR':<10} {'Final':<15} {'Max DD':<10} {'Sharpe':<8} {'Trades':<10} {'1er Trade'}")
print("-" * 80)

for r in results:
    tenure_label = f"{r['min_tenure_days']}d" if r['min_tenure_days'] > 0 else "0d (base)"
    first_trade_str = r['first_trade'].strftime('%Y-%m-%d') if r['first_trade'] else 'N/A'
    print(f"{tenure_label:<15} {r['cagr']:<10.2%} ${r['final_value']:<14,.0f} "
          f"{r['max_drawdown']:<10.1%} {r['sharpe']:<8.2f} {r['trades']:<10,} {first_trade_str}")

# Encontrar óptimo
best = max(results, key=lambda x: x['cagr'])
print("\n" + "=" * 80)
print(f"ÓPTIMO: MIN_TENURE_DAYS = {best['min_tenure_days']} días")
print(f"  CAGR: {best['cagr']:.2%}")
print(f"  Valor final: ${best['final_value']:,.2f}")
print("=" * 80)

# Análisis del impacto
print("\n" + "=" * 80)
print("ANÁLISIS DE IMPACTO DE ANTIGÜEDAD")
print("=" * 80)
print()

base_cagr = results[0]['cagr']  # Sin filtro de antigüedad
for r in results[1:]:
    impacto = r['cagr'] - base_cagr
    print(f"Antigüedad {r['min_tenure_days']}d: {impacto:+.2%} vs base (sin filtro)")

# Guardar resultados
with open('results_tenure_sweep.pkl', 'wb') as f:
    pickle.dump(results, f)

print("\nResultados guardados en: results_tenure_sweep.pkl")
