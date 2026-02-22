"""
OmniCapital v6 con reglas de antigüedad de existencia (Existence Tenure)
Solo tradea símbolos que llevan al menos MIN_TENURE_DAYS cotizando
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import random
import pickle
import os
from typing import Dict, List, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARÁMETROS CONFIGURABLES
# ============================================================================

HOLD_MINUTES = 666  # ~11.1 horas - captura overnight premium
NUM_POSITIONS = 5
INITIAL_CAPITAL = 100_000
RANDOM_SEED = 42
MIN_SYMBOLS_THRESHOLD = 30  # Mínimo de símbolos para operar un día
COMMISSION_PER_SHARE = 0.001  # IBKR Pro tiered

# NUEVO: Parámetros de antigüedad
MIN_TENURE_DAYS = 252  # Mínimo 1 año de historial para ser elegible
# Alternativas a testear: 126 (6 meses), 252 (1 año), 504 (2 años), 756 (3 años)

# Universo de 40 blue-chips
UNIVERSE = [
    'AAPL', 'MSFT', 'AMZN', 'NVDA', 'GOOGL', 'META', 'TSLA', 'AVGO',
    'BRK-B', 'JPM', 'V', 'JNJ', 'WMT', 'MA', 'PG', 'UNH', 'HD', 'CVX',
    'MRK', 'PEP', 'KO', 'ABBV', 'BAC', 'COST', 'TMO', 'MCD', 'DIS',
    'ABT', 'WFC', 'ACN', 'VZ', 'DHR', 'ADBE', 'CRM', 'TXN', 'NKE',
    'NEE', 'AMD', 'PM', 'XOM'
]

# Fechas del backtest
START_DATE = '2000-01-01'
END_DATE = '2026-02-09'

print("=" * 70)
print("OMNICAPITAL v6 - EXISTENCE TENURE RULES")
print("=" * 70)
print(f"\nParámetros:")
print(f"  - Hold time: {HOLD_MINUTES} minutos (~{HOLD_MINUTES/60:.1f} horas)")
print(f"  - Posiciones: {NUM_POSITIONS}")
print(f"  - Capital inicial: ${INITIAL_CAPITAL:,.0f}")
print(f"  - Min símbolos: {MIN_SYMBOLS_THRESHOLD}")
print(f"  - Min antigüedad: {MIN_TENURE_DAYS} días (~{MIN_TENURE_DAYS/252:.1f} años)")
print(f"  - Universo: {len(UNIVERSE)} símbolos")
print()


class TenureAwareBacktester:
    """Backtester con reglas de antigüedad de existencia"""
    
    def __init__(self, price_data: Dict[str, pd.DataFrame]):
        self.price_data = price_data
        self.symbols = list(price_data.keys())
        
        # Calcular fechas de inicio (primer día con datos) para cada símbolo
        self.symbol_start_dates = {}
        for symbol, df in price_data.items():
            if not df.empty:
                self.symbol_start_dates[symbol] = df.index[0]
        
        # Construir conjunto de fechas de trading
        all_dates = set()
        for df in price_data.values():
            all_dates.update(df.index)
        self.all_dates = sorted(list(all_dates))
        
        print(f"Fechas de trading: {len(self.all_dates)} días")
        print(f"Rango: {self.all_dates[0].strftime('%Y-%m-%d')} a {self.all_dates[-1].strftime('%Y-%m-%d')}")
        print()
        
        # Mostrar antigüedades
        print("Antigüedad de símbolos:")
        for symbol in sorted(self.symbol_start_dates.keys()):
            start = self.symbol_start_dates[symbol]
            days = (self.all_dates[-1] - start).days
            status = "OK-ELEGIBLE" if days >= MIN_TENURE_DAYS else "NUEVO"
            print(f"  {symbol}: {start.strftime('%Y-%m-%d')} ({days} días) {status}")
        print()
    
    def get_eligible_symbols(self, date: pd.Timestamp) -> List[str]:
        """
        Retorna símbolos que:
        1. Tienen datos para la fecha
        2. Han cotizado al menos MIN_TENURE_DAYS desde su primer día
        """
        eligible = []
        
        for symbol in self.symbols:
            # Check 1: Tiene datos para esta fecha?
            if symbol not in self.price_data:
                continue
            if date not in self.price_data[symbol].index:
                continue
            
            # Check 2: Tiene suficiente antigüedad?
            if symbol not in self.symbol_start_dates:
                continue
            
            first_date = self.symbol_start_dates[symbol]
            tenure_days = (date - first_date).days
            
            if tenure_days >= MIN_TENURE_DAYS:
                eligible.append(symbol)
        
        return eligible
    
    def run_backtest(self) -> Dict:
        """Ejecuta el backtest con reglas de antigüedad"""
        
        capital = INITIAL_CAPITAL
        positions = {}  # symbol -> {'shares': float, 'entry_date': date, 'entry_price': float}
        trades = []
        daily_values = []
        
        for i, date in enumerate(self.all_dates):
            if i % 1000 == 0:
                print(f"Procesando: {date.strftime('%Y-%m-%d')} (${capital:,.0f})")
            
            # Paso 1: Verificar salidas
            for symbol in list(positions.keys()):
                pos = positions[symbol]
                entry_date = pos['entry_date']
                hold_days = (date - entry_date).days
                
                # Calcular minutos transcurridos (aproximación: días * 390 minutos/día de trading)
                minutes_held = hold_days * 390
                
                if minutes_held >= HOLD_MINUTES:
                    # Cerrar posición
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
                            'shares': shares,
                            'entry_price': pos['entry_price'],
                            'exit_price': exit_price,
                            'pnl': pnl,
                            'return': pnl / (shares * pos['entry_price'])
                        })
                        
                        capital += net_value
                        del positions[symbol]
            
            # Paso 2: Abrir nuevas posiciones
            eligible = self.get_eligible_symbols(date)
            
            # Debug: mostrar disponibilidad en fechas clave
            if date.year in [2000, 2004, 2008, 2012, 2013] and date.month == 1 and date.day <= 5:
                print(f"  [{date.strftime('%Y-%m-%d')}] Elegibles: {len(eligible)}/40")
            
            if len(eligible) >= MIN_SYMBOLS_THRESHOLD:
                # Selección aleatoria
                random.seed(RANDOM_SEED + date.toordinal())
                n_select = min(NUM_POSITIONS, len(eligible))
                selected = random.sample(eligible, n_select)
                
                # Calcular capital por posición
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
            
            # Paso 3: Calcular valor del portfolio
            portfolio_value = capital
            for symbol, pos in positions.items():
                if symbol in self.price_data and date in self.price_data[symbol].index:
                    price = self.price_data[symbol].loc[date, 'Close']
                    portfolio_value += pos['shares'] * price
            
            daily_values.append({
                'date': date,
                'value': portfolio_value,
                'cash': capital,
                'positions': len(positions),
                'eligible': len(eligible)
            })
        
        return {
            'daily_values': pd.DataFrame(daily_values),
            'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
            'final_value': daily_values[-1]['value'] if daily_values else INITIAL_CAPITAL
        }


def load_data():
    """Carga datos del cache"""
    cache_file = 'data_cache/fixed_2000-01-01_2026-02-09.pkl'
    
    if os.path.exists(cache_file):
        print(f"Cargando cache: {cache_file}")
        with open(cache_file, 'rb') as f:
            return pickle.load(f)
    else:
        raise FileNotFoundError(f"No se encontró: {cache_file}")


# ============================================================================
# EJECUCIÓN
# ============================================================================

print("Cargando datos...")
price_data = load_data()

print(f"\nSímbolos cargados: {len(price_data)}")
print()

# Ejecutar backtest
backtester = TenureAwareBacktester(price_data)
results = backtester.run_backtest()

# Análisis de resultados
daily = results['daily_values']
final_value = results['final_value']
trades = results['trades']

# Calcular métricas
total_return = (final_value - INITIAL_CAPITAL) / INITIAL_CAPITAL
years = len(daily) / 252
cagr = (final_value / INITIAL_CAPITAL) ** (1/years) - 1

# Drawdown
daily['peak'] = daily['value'].cummax()
daily['drawdown'] = (daily['value'] - daily['peak']) / daily['peak']
max_dd = daily['drawdown'].min()

# Volatilidad y Sharpe
daily['returns'] = daily['value'].pct_change()
volatility = daily['returns'].std() * np.sqrt(252)
sharpe = cagr / volatility if volatility > 0 else 0

print("\n" + "=" * 70)
print("RESULTADOS - EXISTENCE TENURE")
print("=" * 70)
print(f"\nCapital inicial:     ${INITIAL_CAPITAL:>15,.0f}")
print(f"Capital final:       ${final_value:>15,.2f}")
print(f"Retorno total:       {total_return:>15.2%}")
print(f"CAGR:                {cagr:>15.2%}")
print(f"Volatilidad anual:   {volatility:>15.2%}")
print(f"Sharpe ratio:        {sharpe:>15.2f}")
print(f"Max drawdown:        {max_dd:>15.2%}")
print(f"\nDías de trading:     {len(daily):>15,}")
print(f"Años:                {years:>15.2f}")

if len(trades) > 0:
    print(f"\nTrades ejecutados:   {len(trades):>15,}")
    print(f"Win rate:            {(trades['pnl'] > 0).mean():>15.2%}")
    print(f"P&L promedio:        ${trades['pnl'].mean():>15,.2f}")
    print(f"Profit factor:       {(trades[trades['pnl'] > 0]['pnl'].sum() / abs(trades[trades['pnl'] < 0]['pnl'].sum())):>15.2f}")
else:
    print("\nNo se ejecutaron trades")

# Guardar resultados
output_file = f'results_v6_tenure_{MIN_TENURE_DAYS}d.pkl'
with open(output_file, 'wb') as f:
    pickle.dump({
        'params': {
            'hold_minutes': HOLD_MINUTES,
            'num_positions': NUM_POSITIONS,
            'min_tenure_days': MIN_TENURE_DAYS,
            'min_symbols': MIN_SYMBOLS_THRESHOLD
        },
        'daily_values': daily,
        'trades': trades,
        'metrics': {
            'cagr': cagr,
            'total_return': total_return,
            'max_drawdown': max_dd,
            'sharpe': sharpe,
            'volatility': volatility
        }
    }, f)

print(f"\nResultados guardados en: {output_file}")
