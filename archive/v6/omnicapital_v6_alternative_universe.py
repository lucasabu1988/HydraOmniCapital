"""
OMNICAPITAL v6 - ALTERNATIVE UNIVERSE TEST
============================================
Prueba con 40 blue-chips diferentes al universo original

Universo Original (17.55% CAGR):
AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, BRK-B, JPM, V, JNJ, UNH, 
XOM, WMT, PG, MA, HD, CVX, MRK, ABBV, PEP, KO, PFE, AVGO, COST, TMO, 
DIS, ABT, ADBE, BAC, ACN, WFC, CRM, VZ, DHR, NKE, TXN, PM, NEE, AMD

Universo Alternativo:
Seleccionados por: Market Cap >$100B, liquidez, sectores diversos
"""

import yfinance as yf
import pandas as pd
import numpy as np
import random
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# UNIVERSOS DE PRUEBA
# =============================================================================

# Universo ORIGINAL (control)
UNIVERSE_ORIGINAL = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
    'JPM', 'V', 'JNJ', 'UNH', 'XOM', 'WMT', 'PG', 'MA', 'HD', 'CVX',
    'MRK', 'ABBV', 'PEP', 'KO', 'PFE', 'AVGO', 'COST', 'TMO', 'DIS',
    'ABT', 'ADBE', 'BAC', 'ACN', 'WFC', 'CRM', 'VZ', 'DHR', 'NKE',
    'TXN', 'PM', 'NEE', 'AMD'
]

# Universo ALTERNATIVO 1: Más diversificado sectorial
UNIVERSE_ALT_1 = [
    # Tech (8)
    'INTC', 'CSCO', 'ORCL', 'IBM', 'QCOM', 'AMAT', 'MU', 'LRCX',
    # Healthcare (6)
    'LLY', 'PGR', 'CI', 'HUM', 'BMY', 'GILD',
    # Financials (6)
    'GS', 'MS', 'BLK', 'AXP', 'C', 'SPGI',
    # Consumer (6)
    'MCD', 'SBUX', 'TJX', 'LOW', 'TGT', 'EL',
    # Energy & Materials (4)
    'COP', 'EOG', 'SLB', 'LIN',
    # Industrials (4)
    'HON', 'UNP', 'RTX', 'LMT',
    # Utilities & REITs (4)
    'SO', 'DUK', 'PLD', 'AMT',
    # Telecom & Media (2)
    'CMCSA', 'NFLX'
]

# Universo ALTERNATIVO 2: Más value/contrarian
UNIVERSE_ALT_2 = [
    # Value plays (10)
    'F', 'GM', 'GE', 'BA', 'CAT', 'DE', 'UPS', 'FDX', 'CSX', 'NSC',
    # Healthcare value (6)
    'CVS', 'CI', 'HUM', 'MO', 'MDT', 'SYK',
    # Financials value (6)
    'USB', 'PNC', 'TFC', 'COF', 'SCHW', 'BK',
    # Consumer value (6)
    'DG', 'DLTR', 'ROST', 'BURL', 'YUM', 'DPZ',
    # Tech value (6)
    'HPQ', 'DELL', 'INTU', 'ADP', 'SNOW', 'ZM',
    # Dividend aristocrats (6)
    'KMB', 'CL', 'GIS', 'K', 'SJM', 'HSY'
]

# Universo ALTERNATIVO 3: Más growth/momentum
UNIVERSE_ALT_3 = [
    # High growth (10)
    'NFLX', 'CRM', 'NOW', 'SNOW', 'ZM', 'UBER', 'LYFT', 'ABNB', 'SQ', 'PYPL',
    # Biotech growth (6)
    'REGN', 'VRTX', 'BIIB', 'GILD', 'AMGN', 'MRNA',
    # Tech growth (8)
    'SHOP', 'CRWD', 'OKTA', 'DDOG', 'NET', 'FSLY', 'TWLO', 'PLTR',
    # Clean energy/Green (6)
    'ENPH', 'SEDG', 'FSLR', 'NEE', 'BEP', 'ICLN',
    # EV/Auto growth (6)
    'RIVN', 'LCID', 'FSR', 'NIO', 'XPEV', 'LI',
    # Fintech (4)
    'SOFI', 'HOOD', 'AFRM', 'UPST'
]

# Universo ALTERNATIVO 4: Mega-caps only (>$300B)
UNIVERSE_ALT_4 = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
    'JPM', 'V', 'JNJ', 'UNH', 'XOM', 'WMT', 'PG', 'MA', 'HD', 'CVX',
    'MRK', 'ABBV', 'PEP', 'KO', 'PFE', 'AVGO', 'COST', 'TMO', 'LLY',
    'NFLX', 'ADBE', 'BAC', 'CRM', 'ACN', 'TBC', 'VZ', 'DIS', 'NKE',
    'ABT', 'WFC', 'TXN', 'PM'
]

# Universo ALTERNATIVO 5: Dividend Kings + Growth
UNIVERSE_ALT_5 = [
    # Dividend Kings (10)
    'KO', 'PG', 'JNJ', 'PEP', 'WMT', 'ABT', 'MO', 'CL', 'KMB', 'MCD',
    # Tech dividend growers (6)
    'MSFT', 'AAPL', 'AVGO', 'CSCO', 'QCOM', 'TXN',
    # Financial dividend (6)
    'JPM', 'BAC', 'WFC', 'GS', 'MS', 'BLK',
    # Healthcare dividend (6)
    'PFE', 'MRK', 'ABBV', 'BMY', 'GILD', 'AMGN',
    # Industrial/Energy dividend (6)
    'XOM', 'CVX', 'HON', 'CAT', 'UPS', 'RTX',
    # Consumer dividend (6)
    'HD', 'LOW', 'TGT', 'COST', 'NKE', 'SBUX'
]


class DataCache:
    """Cache de datos"""
    def __init__(self, cache_dir='data_cache'):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
    
    def get(self, symbols, start, end, universe_name="default"):
        cache_key = f"{universe_name}_{start}_{end}"
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.pkl")
        
        if os.path.exists(cache_file):
            return pd.read_pickle(cache_file)
        
        all_data = {}
        valid_symbols = []
        invalid_symbols = []
        
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                df = ticker.history(start=start, end=end, auto_adjust=True)
                if len(df) > 252:
                    all_data[symbol] = df
                    valid_symbols.append(symbol)
                else:
                    invalid_symbols.append(f"{symbol} (insuficiente)")
            except Exception as e:
                invalid_symbols.append(f"{symbol} ({str(e)})")
                continue
        
        print(f"  Validos: {len(valid_symbols)}, Invalidos: {len(invalid_symbols)}")
        if invalid_symbols:
            print(f"  Descartados: {invalid_symbols[:5]}...")
        
        pd.to_pickle(all_data, cache_file)
        return all_data


class Random666Backtest:
    """Backtest de Random 666"""
    
    def __init__(self, price_data: Dict[str, pd.DataFrame], seed: int = 42):
        self.price_data = price_data
        self.dates = self._get_trading_dates()
        self.seed = seed
        random.seed(seed)
        np.random.seed(seed)
    
    def _get_trading_dates(self):
        all_dates = set()
        for df in self.price_data.values():
            all_dates.update(df.index)
        return sorted(list(all_dates))
    
    def run(self, num_positions: int = 5, hold_days: int = 1):
        cash = 100000
        positions = {}
        portfolio_values = []
        trades = []
        
        for date in self.dates:
            # Calcular valor
            portfolio_value = cash
            for symbol, pos in list(positions.items()):
                if symbol in self.price_data and date in self.price_data[symbol].index:
                    price = self.price_data[symbol].loc[date, 'Close']
                    portfolio_value += pos['shares'] * price
            
            # Cerrar posiciones expiradas
            for symbol in list(positions.keys()):
                if date >= positions[symbol]['exit_date']:
                    exit_price = self.price_data[symbol].loc[date, 'Close']
                    proceeds = positions[symbol]['shares'] * exit_price
                    entry_cost = positions[symbol]['shares'] * positions[symbol]['entry_price']
                    pnl = proceeds - entry_cost
                    cash += proceeds
                    trades.append({'pnl': pnl, 'return': pnl/entry_cost if entry_cost > 0 else 0})
                    del positions[symbol]
            
            # Abrir nuevas posiciones
            available = [s for s in self.price_data.keys() if s not in positions]
            needed = num_positions - len(positions)
            
            if needed > 0 and len(available) >= needed:
                selected = random.sample(available, needed)
                
                for symbol in selected:
                    if date in self.price_data[symbol].index:
                        entry_price = self.price_data[symbol].loc[date, 'Close']
                        position_value = (portfolio_value * 0.95) / num_positions
                        
                        if position_value > cash * 0.95:
                            continue
                        
                        shares = position_value / entry_price
                        positions[symbol] = {
                            'entry_date': date,
                            'entry_price': entry_price,
                            'shares': shares,
                            'exit_date': date + timedelta(days=hold_days)
                        }
                        cash -= position_value
            
            portfolio_values.append({
                'date': date,
                'value': portfolio_value,
                'cash': cash,
                'positions': len(positions)
            })
        
        return self._calculate_metrics(portfolio_values, trades)
    
    def _calculate_metrics(self, portfolio_values, trades):
        df = pd.DataFrame(portfolio_values)
        df.set_index('date', inplace=True)
        
        initial = df['value'].iloc[0]
        final = df['value'].iloc[-1]
        total_return = (final - initial) / initial
        years = len(df) / 252
        cagr = (1 + total_return) ** (1/years) - 1 if years > 0 else 0
        
        returns = df['value'].pct_change().dropna()
        volatility = returns.std() * np.sqrt(252)
        
        rolling_max = df['value'].expanding().max()
        max_dd = ((df['value'] - rolling_max) / rolling_max).min()
        
        sharpe = (returns.mean() * 252 - 0.02) / (returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        
        winning = [t for t in trades if t['pnl'] > 0]
        hit_rate = len(winning) / len(trades) if trades else 0
        
        return {
            'cagr': cagr,
            'volatility': volatility,
            'max_drawdown': max_dd,
            'sharpe': sharpe,
            'hit_rate': hit_rate,
            'total_trades': len(trades),
            'final_value': final,
            'total_return': total_return
        }


def test_universe(name: str, symbols: List[str], cache: DataCache):
    """Testea un universo específico"""
    print(f"\n{'='*60}")
    print(f"TEST: {name}")
    print(f"{'='*60}")
    print(f"Simbolos: {len(symbols)}")
    print(f"Descargando datos...")
    
    price_data = cache.get(symbols, '2000-01-01', '2026-02-09', universe_name=name.replace(' ', '_').replace(':', '').replace('/', '_'))
    
    if len(price_data) < 10:
        print(f"ERROR: Datos insuficientes ({len(price_data)} simbolos)")
        return None
    
    print(f"Ejecutando backtest...")
    backtest = Random666Backtest(price_data, seed=42)
    results = backtest.run(num_positions=5, hold_days=1)
    
    return results


def print_comparison(all_results: Dict):
    """Imprime comparación de universos"""
    print("\n" + "="*80)
    print("COMPARACION DE UNIVERSOS")
    print("="*80)
    print(f"{'Universo':<25} {'CAGR':>8} {'Max DD':>10} {'Sharpe':>8} {'Trades':>8} {'Stocks':>8}")
    print("-"*80)
    
    for name, results in all_results.items():
        if results:
            print(f"{name:<25} {results['cagr']:>7.2%} {results['max_drawdown']:>9.2%} {results['sharpe']:>7.2f} {results['total_trades']:>7,} {len(UNIVERSE_ORIGINAL) if 'Original' in name else 'N/A':>8}")
    print("="*80)


def main():
    """Función principal"""
    print("="*80)
    print("OMNICAPITAL v6 - ALTERNATIVE UNIVERSE TEST")
    print("="*80)
    
    cache = DataCache()
    all_results = {}
    
    # Test 1: Universo Original (control)
    all_results["1. ORIGINAL (Control)"] = test_universe(
        "ORIGINAL (Control)", UNIVERSE_ORIGINAL, cache
    )
    
    # Test 2: Alternativo 1 - Diversificado
    all_results["2. ALT 1: Diversificado"] = test_universe(
        "ALTERNATIVO 1: Diversificado Sectorial", UNIVERSE_ALT_1, cache
    )
    
    # Test 3: Alternativo 2 - Value
    all_results["3. ALT 2: Value"] = test_universe(
        "ALTERNATIVO 2: Value/Contrarian", UNIVERSE_ALT_2, cache
    )
    
    # Test 4: Alternativo 3 - Growth
    all_results["4. ALT 3: Growth"] = test_universe(
        "ALTERNATIVO 3: Growth/Momentum", UNIVERSE_ALT_3, cache
    )
    
    # Test 5: Alternativo 4 - Mega-caps
    all_results["5. ALT 4: Mega-caps"] = test_universe(
        "ALTERNATIVO 4: Mega-caps Only", UNIVERSE_ALT_4, cache
    )
    
    # Test 6: Alternativo 5 - Dividend
    all_results["6. ALT 5: Dividend"] = test_universe(
        "ALTERNATIVO 5: Dividend Kings", UNIVERSE_ALT_5, cache
    )
    
    # Comparación
    print_comparison(all_results)
    
    # Guardar resultados
    os.makedirs('universe_tests', exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    with open(f'universe_tests/comparison_{timestamp}.json', 'w') as f:
        json.dump({k: v for k, v in all_results.items() if v}, f, indent=2, default=str)
    
    print(f"\nResultados guardados en: universe_tests/comparison_{timestamp}.json")


if __name__ == "__main__":
    main()
