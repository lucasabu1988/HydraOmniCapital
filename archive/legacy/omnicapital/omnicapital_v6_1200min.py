"""
OMNICAPITAL v6 FINAL - 1200 MINUTOS
=====================================
Version definitiva con hold time de 1200 minutos.
Mejor resultado: 18.54% CAGR (2000-2026)

Estrategia: Seleccion aleatoria de 5 stocks cada dia, hold 1200 minutos
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
HOLD_MINUTES = 1200
RANDOM_SEED = 42

# Los 40 blue-chips originales - NO MODIFICAR
UNIVERSE_40 = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
    'JPM', 'V', 'JNJ', 'UNH', 'XOM', 'WMT', 'PG', 'MA', 'HD', 'CVX',
    'MRK', 'ABBV', 'PEP', 'KO', 'PFE', 'AVGO', 'COST', 'TMO', 'DIS',
    'ABT', 'ADBE', 'BAC', 'ACN', 'WFC', 'CRM', 'VZ', 'DHR', 'NKE',
    'TXN', 'PM', 'NEE', 'AMD'
]

# Universo activo
UNIVERSE = UNIVERSE_40

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
        cache_key = f'v6_{len(symbols)}stocks_{start}_{end}'
        cache_file = os.path.join(self.cache_dir, f'{cache_key}.pkl')

        if os.path.exists(cache_file):
            print(f"[Cache] Cargando datos...")
            try:
                return pd.read_pickle(cache_file)
            except Exception:
                print(f"[Cache] Cache corrupto, re-descargando...")
                os.remove(cache_file)

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
# ESTRATEGIA
# =============================================================================

class OmniCapitalStrategy:
    """
    OmniCapital v6 Final:
    - Selecciona NUM_POSITIONS aleatorios del universo filtrado
    - Mantiene posiciones por HOLD_MINUTES
    - Rotacion basada en expiracion de hold time
    """

    def __init__(self, price_data: Dict[str, pd.DataFrame], seed: int = RANDOM_SEED):
        self.price_data = price_data
        self.dates = self._get_trading_dates()
        self.hold_days = max(1, HOLD_MINUTES // (6.5 * 60))

        random.seed(seed)
        np.random.seed(seed)

        print(f"[Strategy] Fechas: {self.dates[0].date()} a {self.dates[-1].date()}")
        print(f"[Strategy] Dias de trading: {len(self.dates)}")
        print(f"[Strategy] Hold: {HOLD_MINUTES} min = ~{self.hold_days} dias de mercado")
        print(f"[Strategy] Universo: {len(self.price_data)} stocks")

    def _get_trading_dates(self) -> List[datetime]:
        """Obtiene fechas donde al menos el 50% del universo tiene datos"""
        from collections import Counter

        min_symbols = max(5, len(self.price_data) // 2)
        date_counts = Counter()
        for df in self.price_data.values():
            for date in df.index:
                date_counts[date] += 1

        valid_dates = [date for date, count in date_counts.items() if count >= min_symbols]
        return sorted(valid_dates)

    def run(self) -> Dict:
        """Ejecuta backtest"""

        cash = INITIAL_CAPITAL
        positions = {}
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
                    if date in self.price_data[symbol].index:
                        exit_price = self.price_data[symbol].loc[date, 'Close']
                    else:
                        available_dates = self.price_data[symbol].index
                        future_dates = available_dates[available_dates >= date]
                        if len(future_dates) > 0:
                            exit_price = self.price_data[symbol].loc[future_dates[0], 'Close']
                        else:
                            exit_price = positions[symbol]['entry_price']

                    proceeds = positions[symbol]['shares'] * exit_price
                    entry_cost = positions[symbol]['shares'] * positions[symbol]['entry_price']
                    pnl = proceeds - entry_cost
                    cash += proceeds

                    trades.append({
                        'symbol': symbol,
                        'entry_date': positions[symbol]['entry_date'],
                        'exit_date': date,
                        'entry_price': positions[symbol]['entry_price'],
                        'exit_price': exit_price,
                        'shares': positions[symbol]['shares'],
                        'pnl': pnl,
                        'return_pct': pnl / entry_cost if entry_cost > 0 else 0
                    })
                    del positions[symbol]

            # Abrir nuevas posiciones
            available = [s for s in self.price_data.keys()
                        if s not in positions
                        and date in self.price_data[s].index]
            needed = NUM_POSITIONS - len(positions)

            if needed > 0 and len(available) >= needed:
                selected = random.sample(available, needed)

                for symbol in selected:
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

            if i % 252 == 0 and i > 0:
                years = i // 252
                ret = (portfolio_value / INITIAL_CAPITAL - 1) * 100
                print(f"  Ano {years}: ${portfolio_value:,.0f} ({ret:+.1f}%)")

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
        losing_trades = [t for t in trades if t['pnl'] <= 0]

        avg_win = np.mean([t['return_pct'] for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t['return_pct'] for t in losing_trades]) if losing_trades else 0
        profit_factor = (sum(t['pnl'] for t in winning_trades) /
                        abs(sum(t['pnl'] for t in losing_trades))) if losing_trades and sum(t['pnl'] for t in losing_trades) != 0 else 0

        return {
            'config': {
                'initial_capital': INITIAL_CAPITAL,
                'num_positions': NUM_POSITIONS,
                'hold_minutes': HOLD_MINUTES,
                'hold_days_effective': int(self.hold_days),
                'random_seed': RANDOM_SEED,
                'universe_size': len(UNIVERSE),
                'universe': UNIVERSE,
                'filter_criteria': 'None - full 40 blue-chip universe'
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
                'hit_rate': len(winning_trades) / len(trades) if trades else 0,
                'total_trades': len(trades),
                'winning_trades': len(winning_trades),
                'losing_trades': len(losing_trades),
                'avg_win_pct': avg_win,
                'avg_loss_pct': avg_loss,
                'profit_factor': profit_factor
            },
            'daily_data': df,
            'trades': trades
        }


# =============================================================================
# REPORTE
# =============================================================================

def print_report(results: Dict):
    """Imprime reporte de resultados"""

    cfg = results['config']
    m = results['metrics']

    print("\n" + "=" * 70)
    print("OMNICAPITAL v6 FINAL - 1200 MINUTOS")
    print("=" * 70)

    print("\n[CONFIGURACION]")
    print(f"  Capital inicial:   ${cfg['initial_capital']:,}")
    print(f"  Posiciones:        {cfg['num_positions']}")
    print(f"  Hold time:         {cfg['hold_minutes']} minutos (~{cfg['hold_days_effective']} dias mercado)")
    print(f"  Random seed:       {cfg['random_seed']}")
    print(f"  Universo:          {cfg['universe_size']} blue-chips")

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
    print(f"  Avg Win:           {m['avg_win_pct']:>15.2%}")
    print(f"  Avg Loss:          {m['avg_loss_pct']:>15.2%}")
    print(f"  Profit Factor:     {m['profit_factor']:>15.2f}")

    print("\n" + "=" * 70)
    print("COMPARACION DE VERSIONES")
    print("=" * 70)
    print("  Version                         CAGR      Max DD    Sharpe  Stocks")
    print("-" * 70)
    print(f"  v6 1200min (ESTE)               {m['cagr']:>6.2%}    {m['max_drawdown']:>7.2%}     {m['sharpe_ratio']:>5.2f}      {cfg['universe_size']}")
    print("  v6 666min  40 stocks            12.87%    -54.23%      0.61      40")
    print("=" * 70)


def save_results(results: Dict):
    """Guarda resultados"""

    os.makedirs('backtests', exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_data = {
        'config': results['config'],
        'metrics': {k: float(v) if isinstance(v, (np.floating, np.integer)) else v
                   for k, v in results['metrics'].items()}
    }

    json_path = f'backtests/v6_1200min_{timestamp}.json'
    with open(json_path, 'w') as f:
        json.dump(json_data, f, indent=2)

    csv_path = f'backtests/v6_1200min_{timestamp}_daily.csv'
    results['daily_data'].to_csv(csv_path)

    if results.get('trades'):
        trades_df = pd.DataFrame(results['trades'])
        trades_path = f'backtests/v6_1200min_{timestamp}_trades.csv'
        trades_df.to_csv(trades_path, index=False)
        print(f"[Guardado] {trades_path}")

    print(f"[Guardado] {json_path}")
    print(f"[Guardado] {csv_path}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    """Funcion principal"""

    print("=" * 70)
    print("OMNICAPITAL v6 FINAL - 1200 MINUTOS")
    print("=" * 70)
    print(f"Periodo: 2000-01-01 a 2026-02-09")
    print(f"Universo: {len(UNIVERSE)} blue-chips originales")
    print(f"Estrategia: {NUM_POSITIONS} aleatorios, hold {HOLD_MINUTES} min")
    print(f"Hold efectivo: {max(1, HOLD_MINUTES // (6.5 * 60))} dias de mercado")
    print("=" * 70)

    data_manager = DataManager()
    price_data = data_manager.download(UNIVERSE, '2000-01-01', '2026-02-09')

    if len(price_data) < 5:
        print("[ERROR] Datos insuficientes")
        return

    print(f"\n[Backtest] Ejecutando con {len(price_data)} stocks, 1200 minutos...")
    strategy = OmniCapitalStrategy(price_data)
    results = strategy.run()

    print_report(results)
    save_results(results)

    print("\n[OK] Backtest completado!")


if __name__ == "__main__":
    main()
