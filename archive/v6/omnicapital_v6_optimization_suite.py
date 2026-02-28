"""
OMNICAPITAL v6 - OPTIMIZATION SUITE
=====================================
Análisis y optimización de la estrategia Random 666
Basado en los mejores resultados: 17.55% CAGR

Áreas de optimización:
1. Sensibilidad del hold time (600-720 min)
2. Número óptimo de posiciones (3-7)
3. Seeds aleatorios
4. Horario de entrada
5. Filtros de volatilidad
6. Rotación parcial
"""

import yfinance as yf
import pandas as pd
import numpy as np
import random
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
import warnings
warnings.filterwarnings('ignore')

# Configuración
INITIAL_CAPITAL = 100000
UNIVERSE_40 = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
    'JPM', 'V', 'JNJ', 'UNH', 'XOM', 'WMT', 'PG', 'MA', 'HD', 'CVX',
    'MRK', 'ABBV', 'PEP', 'KO', 'PFE', 'AVGO', 'COST', 'TMO', 'DIS',
    'ABT', 'ADBE', 'BAC', 'ACN', 'WFC', 'CRM', 'VZ', 'DHR', 'NKE',
    'TXN', 'PM', 'NEE', 'AMD'
]

class DataCache:
    """Cache de datos para evitar descargas repetidas"""
    def __init__(self, cache_dir='data_cache'):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        self.data = {}
    
    def get(self, symbols, start, end):
        key = f"{start}_{end}"
        cache_file = os.path.join(self.cache_dir, f"cache_{key}.pkl")
        
        if os.path.exists(cache_file):
            return pd.read_pickle(cache_file)
        
        # Descargar datos
        all_data = {}
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                df = ticker.history(start=start, end=end, auto_adjust=True)
                if len(df) > 252:
                    all_data[symbol] = df
            except:
                continue
        
        # Guardar cache
        pd.to_pickle(all_data, cache_file)
        return all_data


class Random666Optimizer:
    """Suite de optimización para Random 666"""
    
    def __init__(self, price_data: Dict[str, pd.DataFrame]):
        self.price_data = price_data
        self.dates = self._get_trading_dates()
        
    def _get_trading_dates(self) -> List[datetime]:
        """Obtiene fechas comunes de trading"""
        all_dates = set()
        for df in self.price_data.values():
            all_dates.update(df.index)
        return sorted(list(all_dates))
    
    def run_single_backtest(self, 
                           hold_minutes: int = 666,
                           num_positions: int = 5,
                           seed: int = 42,
                           entry_hour: int = None,  # None = aleatorio
                           volatility_filter: bool = False,
                           partial_rotation: float = 1.0) -> Dict:
        """
        Ejecuta un backtest con parámetros específicos
        
        Args:
            hold_minutes: Tiempo de hold (600-720)
            num_positions: Número de posiciones (3-7)
            seed: Semilla aleatoria
            entry_hour: Hora fija de entrada (None = aleatoria)
            volatility_filter: Filtrar por volatilidad
            partial_rotation: % de posiciones a rotar (0.5 = 50%)
        """
        random.seed(seed)
        np.random.seed(seed)
        
        cash = INITIAL_CAPITAL
        positions = {}  # symbol -> {'entry_date', 'entry_price', 'shares', 'exit_date'}
        portfolio_values = []
        trades = []
        
        for i, date in enumerate(self.dates):
            # Calcular valor actual
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
                    pnl = proceeds - (positions[symbol]['shares'] * positions[symbol]['entry_price'])
                    cash += proceeds
                    trades.append({
                        'pnl': pnl,
                        'return': pnl / (positions[symbol]['shares'] * positions[symbol]['entry_price'])
                    })
                    del positions[symbol]
            
            # Nueva selección diaria
            available_slots = num_positions - len(positions)
            
            if available_slots > 0:
                # Seleccionar símbolos aleatorios
                available_symbols = [s for s in self.price_data.keys() if s not in positions]
                
                if len(available_symbols) >= available_slots:
                    # Rotación parcial: solo rotar un % de las posiciones
                    n_to_select = max(1, int(available_slots * partial_rotation))
                    n_to_select = min(n_to_select, len(available_symbols))
                    
                    selected = random.sample(available_symbols, n_to_select)
                    
                    for symbol in selected:
                        if date in self.price_data[symbol].index:
                            entry_price = self.price_data[symbol].loc[date, 'Close']
                            
                            # Filtro de volatilidad opcional
                            if volatility_filter:
                                prices = self.price_data[symbol]['Close']
                                if date in prices.index:
                                    idx = prices.index.get_loc(date)
                                    if idx >= 20:
                                        recent = prices.iloc[idx-20:idx]
                                        vol = recent.pct_change().std() * np.sqrt(252)
                                        if vol > 0.40:  # Skip si vol > 40%
                                            continue
                            
                            # Calcular shares
                            position_value = (portfolio_value * 0.95) / num_positions
                            if position_value > cash * 0.95:
                                continue
                            
                            shares = position_value / entry_price
                            
                            # Calcular fecha de salida basada en hold_minutes
                            # Simplificación: hold_minutes ≈ días
                            hold_days = max(1, hold_minutes // (6.5 * 60))  # 6.5 horas por día
                            
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
        
        # Calcular métricas
        df = pd.DataFrame(portfolio_values)
        df.set_index('date', inplace=True)
        
        initial = df['value'].iloc[0]
        final = df['value'].iloc[-1]
        total_return = (final - initial) / initial
        years = len(df) / 252
        cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
        
        returns = df['value'].pct_change().dropna()
        volatility = returns.std() * np.sqrt(252)
        
        rolling_max = df['value'].expanding().max()
        max_dd = ((df['value'] - rolling_max) / rolling_max).min()
        
        sharpe = (returns.mean() * 252 - 0.02) / (returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        
        # Hit rate
        winning_trades = [t for t in trades if t['pnl'] > 0]
        hit_rate = len(winning_trades) / len(trades) if trades else 0
        
        return {
            'hold_minutes': hold_minutes,
            'num_positions': num_positions,
            'seed': seed,
            'entry_hour': entry_hour,
            'volatility_filter': volatility_filter,
            'partial_rotation': partial_rotation,
            'cagr': cagr,
            'volatility': volatility,
            'max_drawdown': max_dd,
            'sharpe': sharpe,
            'hit_rate': hit_rate,
            'total_trades': len(trades),
            'final_value': final,
            'daily_data': df
        }
    
    def optimize_hold_time(self) -> pd.DataFrame:
        """Optimiza el tiempo de hold entre 600-720 minutos"""
        print("=" * 80)
        print("OPTIMIZACIÓN: HOLD TIME (600-720 minutos)")
        print("=" * 80)
        
        hold_times = [600, 630, 666, 690, 720]
        results = []
        
        for hold in hold_times:
            print(f"Testing hold={hold} min...", end=' ')
            result = self.run_single_backtest(hold_minutes=hold)
            results.append({
                'hold_minutes': hold,
                'cagr': result['cagr'],
                'sharpe': result['sharpe'],
                'max_dd': result['max_drawdown']
            })
            print(f"CAGR: {result['cagr']:.2%}")
        
        df = pd.DataFrame(results)
        print("\nResultados:")
        print(df.to_string(index=False))
        print(f"\nMejor hold time: {df.loc[df['cagr'].idxmax(), 'hold_minutes']:.0f} min")
        return df
    
    def optimize_num_positions(self) -> pd.DataFrame:
        """Optimiza el número de posiciones (3-7)"""
        print("\n" + "=" * 80)
        print("OPTIMIZACIÓN: NÚMERO DE POSICIONES (3-7)")
        print("=" * 80)
        
        num_positions_list = [3, 4, 5, 6, 7]
        results = []
        
        for n in num_positions_list:
            print(f"Testing num_positions={n}...", end=' ')
            result = self.run_single_backtest(num_positions=n)
            results.append({
                'num_positions': n,
                'cagr': result['cagr'],
                'sharpe': result['sharpe'],
                'max_dd': result['max_drawdown']
            })
            print(f"CAGR: {result['cagr']:.2%}")
        
        df = pd.DataFrame(results)
        print("\nResultados:")
        print(df.to_string(index=False))
        print(f"\nMejor número de posiciones: {df.loc[df['cagr'].idxmax(), 'num_positions']:.0f}")
        return df
    
    def optimize_random_seeds(self, n_seeds: int = 20) -> pd.DataFrame:
        """Prueba diferentes seeds aleatorios"""
        print("\n" + "=" * 80)
        print(f"OPTIMIZACIÓN: RANDOM SEEDS (n={n_seeds})")
        print("=" * 80)
        
        results = []
        for seed in range(n_seeds):
            print(f"Testing seed={seed}...", end=' ')
            result = self.run_single_backtest(seed=seed)
            results.append({
                'seed': seed,
                'cagr': result['cagr'],
                'sharpe': result['sharpe'],
                'max_dd': result['max_drawdown']
            })
            print(f"CAGR: {result['cagr']:.2%}")
        
        df = pd.DataFrame(results)
        df_sorted = df.sort_values('cagr', ascending=False)
        
        print("\nTop 5 seeds:")
        print(df_sorted.head().to_string(index=False))
        print(f"\nMejor seed: {df_sorted.iloc[0]['seed']:.0f} (CAGR: {df_sorted.iloc[0]['cagr']:.2%})")
        print(f"Peor seed: {df_sorted.iloc[-1]['seed']:.0f} (CAGR: {df_sorted.iloc[-1]['cagr']:.2%})")
        print(f"Media CAGR: {df['cagr'].mean():.2%} ± {df['cagr'].std():.2%}")
        return df
    
    def optimize_partial_rotation(self) -> pd.DataFrame:
        """Optimiza el porcentaje de rotación diaria"""
        print("\n" + "=" * 80)
        print("OPTIMIZACIÓN: ROTACIÓN PARCIAL")
        print("=" * 80)
        
        rotations = [0.3, 0.5, 0.7, 1.0]
        results = []
        
        for rot in rotations:
            print(f"Testing rotation={rot:.0%}...", end=' ')
            result = self.run_single_backtest(partial_rotation=rot)
            results.append({
                'rotation_pct': rot,
                'cagr': result['cagr'],
                'sharpe': result['sharpe'],
                'max_dd': result['max_drawdown'],
                'trades': result['total_trades']
            })
            print(f"CAGR: {result['cagr']:.2%}, Trades: {result['total_trades']}")
        
        df = pd.DataFrame(results)
        print("\nResultados:")
        print(df.to_string(index=False))
        return df
    
    def test_volatility_filter(self) -> pd.DataFrame:
        """Prueba el filtro de volatilidad"""
        print("\n" + "=" * 80)
        print("OPTIMIZACIÓN: FILTRO DE VOLATILIDAD")
        print("=" * 80)
        
        configs = [
            {'volatility_filter': False, 'name': 'Sin filtro'},
            {'volatility_filter': True, 'name': 'Con filtro (vol < 40%)'}
        ]
        
        results = []
        for config in configs:
            print(f"Testing {config['name']}...", end=' ')
            result = self.run_single_backtest(volatility_filter=config['volatility_filter'])
            results.append({
                'config': config['name'],
                'cagr': result['cagr'],
                'sharpe': result['sharpe'],
                'max_dd': result['max_drawdown'],
                'trades': result['total_trades']
            })
            print(f"CAGR: {result['cagr']:.2%}")
        
        df = pd.DataFrame(results)
        print("\nResultados:")
        print(df.to_string(index=False))
        return df
    
    def run_full_optimization(self):
        """Ejecuta todas las optimizaciones"""
        print("\n" + "=" * 80)
        print("OMNICAPITAL v6 - OPTIMIZATION SUITE")
        print("Random 666 Strategy Optimization")
        print("=" * 80)
        print(f"Universo: {len(self.price_data)} símbolos")
        print(f"Periodo: {self.dates[0].strftime('%Y-%m-%d')} a {self.dates[-1].strftime('%Y-%m-%d')}")
        print(f"Días de trading: {len(self.dates)}")
        print()
        
        results = {}
        
        # 1. Optimizar hold time
        results['hold_time'] = self.optimize_hold_time()
        
        # 2. Optimizar número de posiciones
        results['num_positions'] = self.optimize_num_positions()
        
        # 3. Optimizar seeds
        results['seeds'] = self.optimize_random_seeds(n_seeds=20)
        
        # 4. Rotación parcial
        results['rotation'] = self.optimize_partial_rotation()
        
        # 5. Filtro de volatilidad
        results['vol_filter'] = self.test_volatility_filter()
        
        # Guardar resultados
        os.makedirs('optimization_results', exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        for name, df in results.items():
            df.to_csv(f'optimization_results/{name}_{timestamp}.csv', index=False)
        
        # Resumen final
        print("\n" + "=" * 80)
        print("RESUMEN DE OPTIMIZACIÓN")
        print("=" * 80)
        
        best_hold = results['hold_time'].loc[results['hold_time']['cagr'].idxmax()]
        best_positions = results['num_positions'].loc[results['num_positions']['cagr'].idxmax()]
        best_seed = results['seeds'].loc[results['seeds']['cagr'].idxmax()]
        best_rotation = results['rotation'].loc[results['rotation']['cagr'].idxmax()]
        
        print(f"\nMejores parámetros encontrados:")
        print(f"  Hold time:        {best_hold['hold_minutes']:.0f} minutos (CAGR: {best_hold['cagr']:.2%})")
        print(f"  Num posiciones:   {best_positions['num_positions']:.0f} (CAGR: {best_positions['cagr']:.2%})")
        print(f"  Seed:             {best_seed['seed']:.0f} (CAGR: {best_seed['cagr']:.2%})")
        print(f"  Rotación:         {best_rotation['rotation_pct']:.0%} (CAGR: {best_rotation['cagr']:.2%})")
        
        # Test combinación óptima
        print("\n" + "=" * 80)
        print("TEST DE COMBINACIÓN ÓPTIMA")
        print("=" * 80)
        
        optimal = self.run_single_backtest(
            hold_minutes=int(best_hold['hold_minutes']),
            num_positions=int(best_positions['num_positions']),
            seed=int(best_seed['seed']),
            partial_rotation=best_rotation['rotation_pct']
        )
        
        print(f"\nResultado combinación óptima:")
        print(f"  CAGR:             {optimal['cagr']:.2%}")
        print(f"  Volatilidad:      {optimal['volatility']:.2%}")
        print(f"  Max Drawdown:     {optimal['max_drawdown']:.2%}")
        print(f"  Sharpe:           {optimal['sharpe']:.2f}")
        print(f"  Hit Rate:         {optimal['hit_rate']:.2%}")
        print(f"  Total Trades:     {optimal['total_trades']}")
        
        return results, optimal


def main():
    """Función principal"""
    print("=" * 80)
    print("OMNICAPITAL v6 - OPTIMIZATION SUITE")
    print("=" * 80)
    
    # Cargar datos
    cache = DataCache()
    print("\nCargando datos...")
    price_data = cache.get(UNIVERSE_40, '2000-01-01', '2026-02-09')
    print(f"Datos cargados: {len(price_data)} símbolos")
    
    # Crear optimizador
    optimizer = Random666Optimizer(price_data)
    
    # Ejecutar optimización completa
    results, optimal = optimizer.run_full_optimization()
    
    print("\n" + "=" * 80)
    print("OPTIMIZACIÓN COMPLETADA")
    print("=" * 80)
    print("\nResultados guardados en: optimization_results/")


if __name__ == "__main__":
    main()
