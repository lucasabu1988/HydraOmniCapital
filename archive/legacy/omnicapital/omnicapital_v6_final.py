"""
OMNICAPITAL v6 FINAL - RANDOM 666
==================================
Version definitiva con los 40 blue-chips originales
Mejor resultado: 17.55% CAGR (2000-2026)

Estrategia: Seleccion aleatoria de 5 stocks cada dia, hold 666 minutos
Universo: 40 blue-chips elite del S&P 500
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

# =============================================================================
# CONFIGURACION
# =============================================================================

INITIAL_CAPITAL = 100_000
NUM_POSITIONS = 5
HOLD_MINUTES = 666
RANDOM_SEED = 42

# Los 40 blue-chips originales - NO MODIFICAR
UNIVERSE_40 = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
    'JPM', 'V', 'JNJ', 'UNH', 'XOM', 'WMT', 'PG', 'MA', 'HD', 'CVX',
    'MRK', 'ABBV', 'PEP', 'KO', 'PFE', 'AVGO', 'COST', 'TMO', 'DIS',
    'ABT', 'ADBE', 'BAC', 'ACN', 'WFC', 'CRM', 'VZ', 'DHR', 'NKE',
    'TXN', 'PM', 'NEE', 'AMD'
]

# =============================================================================
# DATA MANAGER
# =============================================================================

class DataManager:
    """Gestiona descarga y cache de datos"""
    
    def __init__(self, cache_dir: str = 'data_cache'):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
    
    def download(self, symbols: List[str], start: str, end: str) -> Dict[str, pd.DataFrame]:
        """Descarga datos con cache"""
        cache_file = os.path.join(self.cache_dir, f'v6_final_{start}_{end}.pkl')
        
        if os.path.exists(cache_file):
            print(f"[Cache] Cargando datos...")
            return pd.read_pickle(cache_file)
        
        print(f"[Download] Descargando {len(symbols)} simbolos...")
        data = {}
        
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                df = ticker.history(start=start, end=end, auto_adjust=True)
                if len(df) > 252:
                    data[symbol] = df
                    print(f"  [OK] {symbol}: {len(df)} dias")
                else:
                    print(f"  [SKIP] {symbol}: datos insuficientes")
            except Exception as e:
                print(f"  [ERR] {symbol}: {e}")
        
        pd.to_pickle(data, cache_file)
        print(f"[Download] Completado: {len(data)} simbolos validos")
        return data


# =============================================================================
# ESTRATEGIA RANDOM 666
# =============================================================================

class Random666Strategy:
    """
    Estrategia Random 666:
    - Selecciona NUM_POSITIONS aleatorios cada dia
    - Mantiene posiciones por HOLD_MINUTES
    - Rotacion diaria completa
    """
    
    def __init__(self, price_data: Dict[str, pd.DataFrame], seed: int = RANDOM_SEED):
        self.price_data = price_data
        self.dates = self._get_trading_dates()
        self.hold_days = max(1, HOLD_MINUTES // (6.5 * 60))  # 6.5 horas por dia
        
        random.seed(seed)
        np.random.seed(seed)
        
        print(f"[Strategy] Fechas: {self.dates[0].date()} a {self.dates[-1].date()}")
        print(f"[Strategy] Dias de trading: {len(self.dates)}")
        print(f"[Strategy] Hold: {HOLD_MINUTES} min = ~{self.hold_days} dias")
    
    def _get_trading_dates(self) -> List[datetime]:
        """Obtiene fechas donde al menos 30 simbolos tienen datos"""
        from collections import Counter
        
        # Contar cuantos simbolos tienen datos para cada fecha
        date_counts = Counter()
        for df in self.price_data.values():
            for date in df.index:
                date_counts[date] += 1
        
        # Usar fechas donde al menos 30 simbolos tienen datos
        valid_dates = [date for date, count in date_counts.items() if count >= 30]
        return sorted(valid_dates)
    
    def run(self) -> Dict:
        """Ejecuta backtest"""
        
        cash = INITIAL_CAPITAL
        positions = {}  # symbol -> {entry_date, entry_price, shares, exit_date}
        portfolio_values = []
        trades = []
        
        for i, date in enumerate(self.dates):
            # Calcular valor del portafolio
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
                    
                    trades.append({
                        'exit_date': date,
                        'pnl': pnl,
                        'return_pct': pnl / entry_cost if entry_cost > 0 else 0
                    })
                    del positions[symbol]
            
            # Abrir nuevas posiciones
            available = [s for s in self.price_data.keys() if s not in positions]
            needed = NUM_POSITIONS - len(positions)
            
            if needed > 0 and len(available) >= needed:
                selected = random.sample(available, needed)
                
                for symbol in selected:
                    if date in self.price_data[symbol].index:
                        entry_price = self.price_data[symbol].loc[date, 'Close']
                        position_value = (portfolio_value * 0.95) / NUM_POSITIONS
                        
                        if position_value > cash * 0.95:
                            continue
                        
                        shares = position_value / entry_price
                        
                        positions[symbol] = {
                            'entry_date': date,
                            'entry_price': entry_price,
                            'shares': shares,
                            'exit_date': date + timedelta(days=self.hold_days)
                        }
                        cash -= position_value
            
            portfolio_values.append({
                'date': date,
                'value': portfolio_value,
                'cash': cash,
                'positions': len(positions)
            })
            
            # Progreso anual
            if i % 252 == 0 and i > 0:
                years = i // 252
                print(f"  Año {years}: ${portfolio_value:,.0f}")
        
        return self._calculate_metrics(portfolio_values, trades)
    
    def _calculate_metrics(self, portfolio_values: List[Dict], trades: List[Dict]) -> Dict:
        """Calcula metricas de rendimiento"""
        
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
        drawdown = (df['value'] - rolling_max) / rolling_max
        max_dd = drawdown.min()
        
        sharpe = (returns.mean() * 252 - 0.02) / (returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
        calmar = cagr / abs(max_dd) if max_dd != 0 else 0
        
        winning_trades = [t for t in trades if t['pnl'] > 0]
        hit_rate = len(winning_trades) / len(trades) if trades else 0
        
        return {
            'config': {
                'initial_capital': INITIAL_CAPITAL,
                'num_positions': NUM_POSITIONS,
                'hold_minutes': HOLD_MINUTES,
                'random_seed': RANDOM_SEED,
                'universe': UNIVERSE_40
            },
            'metrics': {
                'initial_value': initial,
                'final_value': final,
                'total_return': total_return,
                'cagr': cagr,
                'volatility': volatility,
                'max_drawdown': max_dd,
                'sharpe_ratio': sharpe,
                'calmar_ratio': calmar,
                'hit_rate': hit_rate,
                'total_trades': len(trades),
                'winning_trades': len(winning_trades),
                'losing_trades': len(trades) - len(winning_trades)
            },
            'daily_data': df
        }


# =============================================================================
# REPORTE
# =============================================================================

def print_report(results: Dict):
    """Imprime reporte de resultados"""
    
    cfg = results['config']
    m = results['metrics']
    
    print("\n" + "=" * 70)
    print("OMNICAPITAL v6 FINAL - RESULTADOS")
    print("=" * 70)
    
    print("\n[CONFIGURACION]")
    print(f"  Capital inicial: ${cfg['initial_capital']:,}")
    print(f"  Posiciones: {cfg['num_positions']}")
    print(f"  Hold time: {cfg['hold_minutes']} minutos")
    print(f"  Random seed: {cfg['random_seed']}")
    print(f"  Universo: {len(cfg['universe'])} blue-chips")
    
    print("\n[METRICAS PRINCIPALES]")
    print(f"  Capital final:     ${m['final_value']:>15,.2f}")
    print(f"  Retorno total:     {m['total_return']:>15.2%}")
    print(f"  CAGR:              {m['cagr']:>15.2%}")
    print(f"  Volatilidad:       {m['volatility']:>15.2%}")
    print(f"  Max Drawdown:      {m['max_drawdown']:>15.2%}")
    print(f"  Sharpe Ratio:      {m['sharpe_ratio']:>15.2f}")
    print(f"  Calmar Ratio:      {m['calmar_ratio']:>15.2f}")
    
    print("\n[ESTADISTICAS DE TRADING]")
    print(f"  Hit Rate:          {m['hit_rate']:>15.2%}")
    print(f"  Total trades:      {m['total_trades']:>15,}")
    print(f"  Trades ganadores:  {m['winning_trades']:>15,}")
    print(f"  Trades perdedores: {m['losing_trades']:>15,}")
    
    print("\n" + "=" * 70)
    print("COMPARACION HISTORICA")
    print("=" * 70)
    print("  Version                    CAGR        Max DD      Sharpe")
    print("-" * 70)
    print(f"  v6 FINAL (original)        {m['cagr']:>6.2%}      {m['max_drawdown']:>7.2%}      {m['sharpe_ratio']:>5.2f}")
    print("  v6 ALT 1 (diversificado)   15.67%      -63.04%      0.67")
    print("  v7 (Manifiesto)            -0.04%      -90.00%      -0.42")
    print("  v8 (Core)                   9.63%      -35.00%      0.55")
    print("=" * 70)
    
    if m['cagr'] > 0.15:
        print("\n[OK] EXCELENTE: CAGR > 15%")
    elif m['cagr'] > 0.10:
        print("\n[OK] BUENO: CAGR > 10%")
    else:
        print("\n[⚠] REVISAR: CAGR < 10%")


def save_results(results: Dict):
    """Guarda resultados"""
    
    os.makedirs('backtests', exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # JSON
    json_data = {
        'config': results['config'],
        'metrics': {k: float(v) if isinstance(v, (np.floating, np.integer)) else v 
                   for k, v in results['metrics'].items()}
    }
    
    with open(f'backtests/v6_final_{timestamp}.json', 'w') as f:
        json.dump(json_data, f, indent=2)
    
    # CSV datos diarios
    results['daily_data'].to_csv(f'backtests/v6_final_{timestamp}_daily.csv')
    
    print(f"\n[Guardado] backtests/v6_final_{timestamp}.*")


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Funcion principal"""
    
    print("=" * 70)
    print("OMNICAPITAL v6 FINAL - RANDOM 666")
    print("=" * 70)
    print(f"Periodo: 2000-01-01 a 2026-02-09")
    print(f"Universo: {len(UNIVERSE_40)} blue-chips originales")
    print(f"Estrategia: {NUM_POSITIONS} aleatorios, hold {HOLD_MINUTES} min")
    print("=" * 70)
    
    # Descargar datos
    data_manager = DataManager()
    price_data = data_manager.download(UNIVERSE_40, '2000-01-01', '2026-02-09')
    
    if len(price_data) < 10:
        print("[ERROR] Datos insuficientes")
        return
    
    # Ejecutar backtest
    print("\n[Backtest] Ejecutando...")
    strategy = Random666Strategy(price_data)
    results = strategy.run()
    
    # Reporte
    print_report(results)
    
    # Guardar
    save_results(results)
    
    print("\n[OK] Completado!")


if __name__ == "__main__":
    main()
