"""
╔══════════════════════════════════════════════════════════════════════════════╗
║           OMNICAPITAL v6.0 - RANDOM EXACT 666 MINUTES                         ║
║                                                                              ║
║  Estrategia completamente aleatoria con hold EXACTO de 666 minutos            ║
║  - Selección aleatoria de 5 activos cada día                                  ║
║  - Entrada: Aleatorio durante el día (simulado)                               ║
║  - Salida: EXACTAMENTE 666 minutos después                                    ║
║  - Sin stops, sin targets, sin excepciones                                    ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import random
from typing import Dict, List, Tuple
import os
import warnings
warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════════════════════════════════════════
# UNIVERSO DE ACTIVOS
# ═══════════════════════════════════════════════════════════════════════════════

UNIVERSE = [
    'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'NVDA', 'TSLA', 'AVGO', 'WMT', 'JPM',
    'V', 'MA', 'UNH', 'HD', 'PG', 'BAC', 'KO', 'PEP', 'MRK', 'ABBV',
    'PFE', 'JNJ', 'CVX', 'XOM', 'TMO', 'ABT', 'CRM', 'ADBE', 'ACN', 'COST',
    'NKE', 'DIS', 'VZ', 'WFC', 'TXN', 'DHR', 'PM', 'NEE', 'AMD', 'BRK-B'
]

# ═══════════════════════════════════════════════════════════════════════════════
# PARÁMETROS
# ═══════════════════════════════════════════════════════════════════════════════

INITIAL_CAPITAL = 100_000
POSITIONS_COUNT = 5  # Número de posiciones aleatorias por día
HOLD_MINUTES = 666   # Tiempo exacto de hold en minutos
DAILY_TRADING_HOURS = 6.5  # Horas de trading (9:30 - 16:00)
MINUTES_PER_DAY = DAILY_TRADING_HOURS * 60  # 390 minutos

# Simulación de entrada/salida intradía
# Como no tenemos datos intradía, simulamos usando:
# - Open como referencia de entrada
# - Close como referencia de salida
# - Para holds que cruzan días, usamos proporciones del día siguiente

# ═══════════════════════════════════════════════════════════════════════════════
# CLASES
# ═══════════════════════════════════════════════════════════════════════════════

class Position:
    """Representa una posición con timer exacto de 666 minutos"""
    
    def __init__(self, symbol: str, entry_date: datetime, entry_price: float, 
                 shares: float, entry_minute: int = 0):
        self.symbol = symbol
        self.entry_date = entry_date
        self.entry_price = entry_price
        self.shares = shares
        self.entry_minute = entry_minute  # Minuto del día de entrada (0-389)
        
        # Calcular fecha/hora exacta de salida
        self.exit_minute_total = entry_minute + HOLD_MINUTES
        self.exit_days_later = self.exit_minute_total // MINUTES_PER_DAY
        self.exit_minute_of_day = self.exit_minute_total % MINUTES_PER_DAY
        
        # Fecha exacta de salida
        current = entry_date
        days_added = 0
        while days_added < self.exit_days_later:
            current += timedelta(days=1)
            if current.weekday() < 5:  # Solo días hábiles
                days_added += 1
        
        self.exit_date = current
        self.exit_price = None
        self.pnl = None
        self.pnl_pct = None
        self.closed = False
    
    def calculate_exit_price(self, data: pd.DataFrame, date: datetime) -> float:
        """
        Calcula el precio de salida basado en el minuto exacto de salida.
        
        Como no tenemos datos intradía, usamos interpolación entre Open y Close
        del día de salida para estimar el precio en el minuto específico.
        """
        try:
            date_str = date.strftime('%Y-%m-%d')
            if date_str not in data.index:
                return None
            
            day_data = data.loc[date_str]
            # Extraer valores escalares
            day_open = float(day_data['Open'].iloc[0]) if hasattr(day_data['Open'], 'iloc') else float(day_data['Open'])
            day_high = float(day_data['High'].iloc[0]) if hasattr(day_data['High'], 'iloc') else float(day_data['High'])
            day_low = float(day_data['Low'].iloc[0]) if hasattr(day_data['Low'], 'iloc') else float(day_data['Low'])
            day_close = float(day_data['Close'].iloc[0]) if hasattr(day_data['Close'], 'iloc') else float(day_data['Close'])
            
            # Proporción del día transcurrida (0.0 al 1.0)
            day_progress = self.exit_minute_of_day / MINUTES_PER_DAY
            
            # Modelo de precio intradía simplificado:
            # Usamos una interpolación que considera la volatilidad típica
            # El precio tiende a moverse de Open hacia Close durante el día
            
            # Método 1: Interpolación lineal Open-Close con ruido aleatorio realista
            base_price = day_open + (day_close - day_open) * day_progress
            
            # Añadir variación basada en el rango High-Low
            # Simula que el precio puede oscilar dentro del rango del día
            if day_high > day_low:
                # Factor aleatorio pero determinístico basado en el símbolo y fecha
                np.random.seed(hash(self.symbol + date_str) % 2**32)
                random_factor = np.random.uniform(-0.3, 0.3)
                volatility_range = (day_high - day_low) * random_factor
                exit_price = base_price + volatility_range
            else:
                exit_price = base_price
            
            # Asegurar que está dentro del rango del día
            exit_price = max(day_low, min(day_high, exit_price))
            
            return exit_price
            
        except Exception:
            # Fallback: usar Close del día
            try:
                return data.loc[date.strftime('%Y-%m-%d'), 'Close']
            except:
                return None
    
    def close_position(self, data: pd.DataFrame, actual_date: datetime) -> Tuple[float, float]:
        """Cierra la posición y calcula P&L"""
        if self.closed:
            return self.pnl, self.pnl_pct
        
        exit_price = self.calculate_exit_price(data, actual_date)
        if exit_price is None:
            return None, None
        
        self.exit_price = exit_price
        self.pnl = (exit_price - self.entry_price) * self.shares
        self.pnl_pct = (exit_price - self.entry_price) / self.entry_price
        self.closed = True
        
        return self.pnl, self.pnl_pct


class Exact666Strategy:
    """Estrategia con hold exacto de 666 minutos"""
    
    def __init__(self, capital: float = INITIAL_CAPITAL):
        self.initial_capital = capital
        self.cash = capital
        self.positions: List[Position] = []
        self.closed_positions: List[Position] = []
        self.portfolio_values = []
        self.trades = []
        self.random_seed = 666  # Seed fija para reproducibilidad
        
    def get_portfolio_value(self, current_data: Dict[str, pd.DataFrame], date: datetime) -> float:
        """Calcula valor total del portafolio"""
        positions_value = 0
        for pos in self.positions:
            if not pos.closed:
                try:
                    row = current_data[pos.symbol].loc[date.strftime('%Y-%m-%d')]
                    price = float(row['Close'].iloc[0]) if hasattr(row['Close'], 'iloc') else float(row['Close'])
                    positions_value += pos.shares * price
                except:
                    pass
        return float(self.cash) + positions_value
    
    def select_random_entry_minute(self, symbol: str, date: str) -> int:
        """Selecciona minuto de entrada aleatorio (0-389)"""
        # Seed determinístico pero diferente para cada símbolo/fecha
        seed = hash(f"{symbol}_{date}_{self.random_seed}") % 2**32
        np.random.seed(seed)
        # Distribución que favorece horas de mayor liquidez
        # 9:30-10:30 (0-60) y 14:00-16:00 (270-389) tienen más peso
        if np.random.random() < 0.6:
            # 60% de probabilidad en horas de apertura o cierre
            if np.random.random() < 0.5:
                return np.random.randint(0, 61)  # Primera hora
            else:
                return np.random.randint(270, 390)  # Última hora y media
        else:
            return np.random.randint(0, 390)  # Cualquier hora
    
    def generate_signals(self, date: datetime, available_symbols: List[str]) -> List[str]:
        """Genera señales aleatorias"""
        if len(available_symbols) < POSITIONS_COUNT:
            return []
        
        # Seed determinístico
        seed = hash(f"{date.strftime('%Y-%m-%d')}_{self.random_seed}") % 2**32
        random.seed(seed)
        np.random.seed(seed)
        
        return random.sample(available_symbols, POSITIONS_COUNT)
    
    def calculate_position_size(self, capital_per_position: float, price: float) -> float:
        """Calcula tamaño de posición"""
        if price <= 0:
            return 0
        return capital_per_position / price
    
    def run_backtest(self, start_date: str, end_date: str):
        """Ejecuta el backtest"""
        print("=" * 80)
        print("ALPHAMAX OMNICAPITAL v6.0")
        print("Random Selection + EXACT 666 Minutes Hold")
        print("=" * 80)
        print(f"Periodo: {start_date} a {end_date}")
        print(f"Capital Inicial: ${self.initial_capital:,.2f}")
        print(f"Hold Exacto: {HOLD_MINUTES} minutos ({HOLD_MINUTES/60:.1f} horas)")
        print(f"Posiciones: {POSITIONS_COUNT} aleatorias por día")
        print("=" * 80)
        
        # Descargar datos
        print("\nDescargando datos...")
        all_data = {}
        for symbol in UNIVERSE:
            try:
                df = yf.download(symbol, start=start_date, end=end_date, progress=False)
                if len(df) > 0:
                    all_data[symbol] = df
            except:
                pass
        
        if len(all_data) < 10:
            print("Error: Datos insuficientes")
            return
        
        # Crear calendario de trading
        all_dates = pd.date_range(start=start_date, end=end_date, freq='B')
        
        print(f"\nEjecutando backtest con {len(all_dates)} días...")
        print("=" * 80)
        
        for i, date in enumerate(all_dates):
            date_str = date.strftime('%Y-%m-%d')
            
            # Verificar qué símbolos tienen datos para este día
            available_symbols = []
            current_prices = {}
            
            for symbol, data in all_data.items():
                if date_str in data.index:
                    available_symbols.append(symbol)
                    row = data.loc[date_str]
                    # Extraer valores escalares
                    current_prices[symbol] = {
                        'open': float(row['Open'].iloc[0]) if hasattr(row['Open'], 'iloc') else float(row['Open']),
                        'high': float(row['High'].iloc[0]) if hasattr(row['High'], 'iloc') else float(row['High']),
                        'low': float(row['Low'].iloc[0]) if hasattr(row['Low'], 'iloc') else float(row['Low']),
                        'close': float(row['Close'].iloc[0]) if hasattr(row['Close'], 'iloc') else float(row['Close'])
                    }
            
            if len(available_symbols) < POSITIONS_COUNT:
                continue
            
            # 1. CERRAR POSICIONES QUE EXPIRAN HOY
            positions_to_close = [p for p in self.positions if p.exit_date.date() == date.date()]
            
            for pos in positions_to_close:
                if pos.symbol in available_symbols:
                    pnl, pnl_pct = pos.close_position(all_data[pos.symbol], date)
                    if pnl is not None:
                        proceeds = pos.shares * pos.exit_price
                        self.cash += proceeds
                        self.closed_positions.append(pos)
                        
                        self.trades.append({
                            'date': date_str,
                            'symbol': pos.symbol,
                            'action': 'SELL_EXACT_666',
                            'entry_date': pos.entry_date.strftime('%Y-%m-%d'),
                            'entry_price': pos.entry_price,
                            'exit_price': pos.exit_price,
                            'shares': pos.shares,
                            'pnl': pnl,
                            'pnl_pct': pnl_pct,
                            'hold_minutes': HOLD_MINUTES,
                            'entry_minute': pos.entry_minute,
                            'exit_minute': pos.exit_minute_of_day
                        })
            
            # Remover posiciones cerradas
            self.positions = [p for p in self.positions if not p.closed]
            
            # 2. ABRIR NUEVAS POSICIONES ALEATORIAS
            # Capital disponible para nuevas posiciones
            capital_for_new = self.cash * 0.95  # Mantener 5% cash
            capital_per_position = capital_for_new / POSITIONS_COUNT
            
            selected_symbols = self.generate_signals(date, available_symbols)
            
            for symbol in selected_symbols:
                if symbol not in current_prices:
                    continue
                
                price = current_prices[symbol]['open']
                shares = self.calculate_position_size(capital_per_position, price)
                
                if shares > 0 and self.cash >= shares * price:
                    entry_minute = self.select_random_entry_minute(symbol, date_str)
                    
                    pos = Position(
                        symbol=symbol,
                        entry_date=date,
                        entry_price=price,
                        shares=shares,
                        entry_minute=entry_minute
                    )
                    
                    self.positions.append(pos)
                    self.cash -= shares * price
                    
                    self.trades.append({
                        'date': date_str,
                        'symbol': symbol,
                        'action': 'BUY_RANDOM',
                        'price': price,
                        'shares': shares,
                        'entry_minute': entry_minute,
                        'scheduled_exit': pos.exit_date.strftime('%Y-%m-%d'),
                        'exit_minute': pos.exit_minute_of_day
                    })
            
            # 3. REGISTRAR VALOR DEL PORTAFOLIO
            portfolio_value = self.get_portfolio_value(all_data, date)
            self.portfolio_values.append({
                'date': date_str,
                'portfolio_value': portfolio_value,
                'cash': self.cash,
                'positions_count': len(self.positions),
                'closed_count': len(self.closed_positions)
            })
            
            # Mostrar progreso
            if i % 252 == 0 or i == len(all_dates) - 1:
                print(f"[{date_str}] Valor: ${portfolio_value:>12,.2f} | "
                      f"Pos: {len(self.positions):>2} | Cash: ${self.cash:>10,.2f}")
        
        # RESULTADOS FINALES
        self.print_results()
        self.save_results()
    
    def print_results(self):
        """Imprime resultados del backtest"""
        if not self.portfolio_values:
            return
        
        df = pd.DataFrame(self.portfolio_values)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        
        initial = self.initial_capital
        final = df['portfolio_value'].iloc[-1]
        total_return = (final - initial) / initial
        
        years = len(df) / 252
        
        print("\n" + "=" * 80)
        print("RESULTADOS FINALES - EXACT 666 MINUTES")
        print("=" * 80)
        
        print(f"\n>> CAPITAL")
        print(f"   Inicial:              ${initial:>15,.2f}")
        print(f"   Final:                ${final:>15,.2f}")
        print(f"   P/L ($):              ${final - initial:>+15,.2f}")
        print(f"   Retorno Total:        {total_return:>+15.2%}")
        
        if years > 0:
            annualized = (1 + total_return) ** (1 / years) - 1
            print(f"   Años:                 {years:>15.1f}")
            print(f"   Retorno Anualizado:   {annualized:>+15.2%}")
        
        # Métricas de riesgo
        df['returns'] = df['portfolio_value'].pct_change()
        volatility = df['returns'].std() * np.sqrt(252)
        
        rolling_max = df['portfolio_value'].expanding().max()
        drawdown = (df['portfolio_value'] - rolling_max) / rolling_max
        max_dd = drawdown.min()
        
        print(f"\n>> RIESGO")
        print(f"   Volatilidad Anual:    {volatility:>15.2%}")
        print(f"   Máximo Drawdown:      {max_dd:>15.2%}")
        
        # Métricas de trading
        trades_df = pd.DataFrame(self.trades)
        if len(trades_df) > 0:
            sells = trades_df[trades_df['action'] == 'SELL_EXACT_666']
            if len(sells) > 0:
                win_rate = (sells['pnl_pct'] > 0).mean()
                avg_pnl = sells['pnl_pct'].mean()
                avg_win = sells[sells['pnl_pct'] > 0]['pnl_pct'].mean() if len(sells[sells['pnl_pct'] > 0]) > 0 else 0
                avg_loss = sells[sells['pnl_pct'] < 0]['pnl_pct'].mean() if len(sells[sells['pnl_pct'] < 0]) > 0 else 0
                
                print(f"\n>> TRADING")
                print(f"   Total Operaciones:    {len(sells):>15}")
                print(f"   Win Rate:             {win_rate:>15.1%}")
                print(f"   P/L Promedio:         {avg_pnl:>+15.2%}")
                print(f"   Ganancia Promedio:    {avg_win:>+15.2%}")
                print(f"   Pérdida Promedio:     {avg_loss:>+15.2%}")
                
                profit_factor = abs(sells[sells['pnl_pct'] > 0]['pnl_pct'].sum() / 
                                  sells[sells['pnl_pct'] < 0]['pnl_pct'].sum()) if sells[sells['pnl_pct'] < 0]['pnl_pct'].sum() != 0 else float('inf')
                print(f"   Profit Factor:        {profit_factor:>15.2f}")
        
        print("=" * 80)
    
    def save_results(self):
        """Guarda resultados"""
        os.makedirs('backtests', exist_ok=True)
        
        # Portfolio values
        df = pd.DataFrame(self.portfolio_values)
        df.to_csv('backtests/backtest_v6_exact_666_results.csv', index=False)
        
        # Trades
        trades_df = pd.DataFrame(self.trades)
        trades_df.to_csv('backtests/trades_v6_exact_666.csv', index=False)
        
        print(f"\nResultados guardados en backtests/")


# ═══════════════════════════════════════════════════════════════════════════════
# EJECUCIÓN
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n" + "=" * 80)
    print(">>> ESTRATEGIA: SELECCIÓN ALEATORIA + HOLD EXACTO 666 MINUTOS <<<")
    print("=" * 80)
    
    strategy = Exact666Strategy()
    strategy.run_backtest('2000-01-01', '2026-02-09')
