"""
AlphaMax OmniCapital v4.0
MicroManagement Monthly Strategy

Copyright (c) 2026 Investment Capital Firm
All Rights Reserved.

Official Release: OmniCapital v4.0
Strategy: MicroManagement with Clear Monthly Rules
Universe: 40 Blue-Chip S&P 500 Equities

Author: Investment Capital Firm
Version: 4.0.0
Date: February 2026

Características v4.0:
- Trading mensual mecánico (último día de mes = rebalanceo)
- Reglas de entrada claras: Momentum + Filtro de Tendencia
- Targets definidos: +5% profit target, -3% stop loss
- Position sizing fijo por trade (2.5% riesgo)
- Time exit obligatorio: fin de mes
- Sin discreción, 100% mecánico

Basado en:
- Gary Antonacci Dual Momentum (momentum rules)
- Larry Connors RSI Mean Reversion (entry timing)
- Alpha Architect Position Sizing (risk management)
- Meb Faber Tactical Allocation (monthly rebalancing)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import calendar

from src.data.data_provider import YFinanceProvider


def get_sp500_top40():
    """Retorna 40 mayores acciones para diversificación"""
    return [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
        'JPM', 'V', 'JNJ', 'UNH', 'XOM', 'WMT', 'PG', 'MA', 'HD', 'CVX',
        'MRK', 'ABBV', 'PEP', 'KO', 'PFE', 'AVGO', 'COST', 'TMO', 'DIS',
        'ABT', 'ADBE', 'BAC', 'ACN', 'WFC', 'CRM', 'VZ', 'DHR', 'NKE',
        'TXN', 'PM', 'NEE', 'AMD'
    ]


class MicroManagementStrategy:
    """
    Estrategia de MicroManagement Mensual con reglas mecánicas claras.
    
    REGLAS DE ENTRADA (Primer día hábil del mes):
    1. Calcular momentum de 3 meses para cada stock
    2. Seleccionar top 10 con mayor momentum
    3. Filtro: Solo si precio > SMA_20 (tendencia alcista corto plazo)
    4. Filtro: Solo si volumen > SMA_20_volumen (confirmación)
    
    POSITION SIZING:
    - Riesgo por trade: 2.5% del capital
    - Máximo 10 posiciones (25% riesgo total máximo)
    - Equal weight entre seleccionadas
    
    REGLAS DE SALIDA (Monitoreo diario):
    1. Profit Target: +5% desde entrada → Vender 50% de posición
    2. Profit Target 2: +10% desde entrada → Vender 100%
    3. Stop Loss: -3% desde entrada → Vender 100%
    4. Trailing Stop: -5% desde máximo alcanzado → Vender 100%
    5. Time Exit: Último día del mes → Vender todo y reevaluar
    
    GESTIÓN DE RIESGO:
    - Máximo 10 posiciones simultáneas
    - Cash liberado se mantiene hasta próximo mes
    - Rebalanceo completo mensual
    """
    
    def __init__(self, config=None):
        self.config = config or {}
        
        # Parámetros de entrada
        self.lookback_months = self.config.get('lookback_months', 3)
        self.top_n = self.config.get('top_n', 10)
        self.sma_period = self.config.get('sma_period', 20)
        
        # Parámetros de salida
        self.profit_target_1 = self.config.get('profit_target_1', 0.05)  # +5%
        self.profit_target_2 = self.config.get('profit_target_2', 0.10)  # +10%
        self.stop_loss = self.config.get('stop_loss', -0.03)  # -3%
        self.trailing_stop = self.config.get('trailing_stop', -0.05)  # -5%
        
        # Position sizing
        self.risk_per_trade = self.config.get('risk_per_trade', 0.025)  # 2.5%
        self.max_positions = self.config.get('max_positions', 10)
        
    def select_stocks(self, prices, volumes, current_date):
        """
        Selecciona stocks para el mes basado en momentum.
        
        Returns:
            List[str]: Símbolos seleccionados (top N)
        """
        if len(prices) < self.sma_period + 5:
            return []
        
        momentum_scores = {}
        
        for symbol in prices.columns:
            try:
                price_series = prices[symbol].dropna()
                volume_series = volumes[symbol].dropna() if symbol in volumes.columns else None
                
                if len(price_series) < self.lookback_months * 21:
                    continue
                
                # Calcular momentum de 3 meses
                current_price = price_series.iloc[-1]
                past_price = price_series.iloc[-self.lookback_months * 21]
                momentum = (current_price / past_price) - 1
                
                # Filtro de tendencia: Precio > SMA_20
                sma_20 = price_series.tail(self.sma_period).mean()
                if current_price <= sma_20:
                    continue
                
                # Filtro de volumen: Volumen > SMA_20
                if volume_series is not None and len(volume_series) >= self.sma_period:
                    current_volume = volume_series.iloc[-1]
                    avg_volume = volume_series.tail(self.sma_period).mean()
                    if current_volume <= avg_volume:
                        continue
                
                momentum_scores[symbol] = momentum
                
            except Exception:
                continue
        
        # Seleccionar top N
        if not momentum_scores:
            return []
        
        sorted_stocks = sorted(momentum_scores.items(), key=lambda x: x[1], reverse=True)
        selected = [symbol for symbol, _ in sorted_stocks[:self.top_n]]
        
        return selected
    
    def calculate_position_size(self, capital, entry_price, stop_price):
        """
        Calcula tamaño de posición basado en riesgo fijo.
        
        Formula: Position Size = (Capital × Risk%) / (Entry - Stop)
        """
        risk_amount = capital * self.risk_per_trade
        risk_per_share = entry_price - stop_price
        
        if risk_per_share <= 0:
            return 0
        
        shares = int(risk_amount / risk_per_share)
        return shares
    
    def check_exits(self, position, current_price, current_date, last_day_of_month):
        """
        Verifica si se debe salir de una posición.
        
        Returns:
            tuple: (should_exit, exit_reason, exit_percentage)
        """
        entry_price = position['entry_price']
        highest_price = position['highest_price']
        
        # Actualizar máximo
        if current_price > highest_price:
            position['highest_price'] = current_price
            highest_price = current_price
        
        # Calcular ganancia/pérdida actual
        gain_pct = (current_price - entry_price) / entry_price
        
        # 1. Profit Target 2: +10%
        if gain_pct >= self.profit_target_2:
            return True, 'PROFIT_TARGET_2', 1.0
        
        # 2. Profit Target 1: +5% (vender 50%)
        if gain_pct >= self.profit_target_1 and not position.get('pt_1_hit'):
            position['pt_1_hit'] = True
            return True, 'PROFIT_TARGET_1', 0.5
        
        # 3. Stop Loss: -3%
        if gain_pct <= self.stop_loss:
            return True, 'STOP_LOSS', 1.0
        
        # 4. Trailing Stop: -5% desde máximo
        trailing_stop_price = highest_price * (1 + self.trailing_stop)
        if current_price <= trailing_stop_price and gain_pct > 0:
            return True, 'TRAILING_STOP', 1.0
        
        # 5. Time Exit: Último día del mes
        if last_day_of_month:
            return True, 'TIME_EXIT', 1.0
        
        return False, None, 0.0


def run_omnicapital_v4(start_date, end_date, initial_capital=100000):
    """
    Backtest usando estrategia de MicroManagement mensual.
    """
    print("=" * 95)
    print("ALPHAMAX OMNICAPITAL v4.0")
    print("MicroManagement Monthly Strategy")
    print("=" * 95)
    print(f"Periodo: {start_date.date()} a {end_date.date()}")
    print(f"Capital Inicial: ${initial_capital:,.2f}")
    print(f"Estrategia: MicroManagement | Reglas Mecánicas | Mensual")
    print("=" * 95)
    
    symbols = get_sp500_top40()
    print(f"\nUniverso: {len(symbols)} acciones del S&P 500")
    
    provider = YFinanceProvider()
    print("\nDescargando datos históricos...")
    prices = provider.get_historical_prices(symbols, start_date=start_date, end_date=end_date)
    
    if prices.empty:
        print("Error: No se pudieron descargar datos")
        return
    
    print(f"Datos descargados: {prices.shape[0]} días x {prices.shape[1]} símbolos")
    
    # Descargar volúmenes
    print("Descargando datos de volumen...")
    volumes = pd.DataFrame()
    for symbol in symbols:
        try:
            ticker = provider.get_ticker(symbol)
            hist = ticker.history(start=start_date, end=end_date)
            if not hist.empty:
                volumes[symbol] = hist['Volume']
        except:
            pass
    
    # Inicializar estrategia
    print("\nInicializando estrategia MicroManagement...")
    strategy = MicroManagementStrategy({
        'lookback_months': 3,
        'top_n': 10,
        'sma_period': 20,
        'profit_target_1': 0.05,
        'profit_target_2': 0.10,
        'stop_loss': -0.03,
        'trailing_stop': -0.05,
        'risk_per_trade': 0.025,
        'max_positions': 10
    })
    
    print(f"\nConfiguración:")
    print(f"  - Momentum lookback: {strategy.lookback_months} meses")
    print(f"  - Top N selección: {strategy.top_n}")
    print(f"  - Profit Target 1: +{strategy.profit_target_1*100:.0f}% (vender 50%)")
    print(f"  - Profit Target 2: +{strategy.profit_target_2*100:.0f}% (vender 100%)")
    print(f"  - Stop Loss: {strategy.stop_loss*100:.0f}%")
    print(f"  - Trailing Stop: {strategy.trailing_stop*100:.0f}% desde máximo")
    print(f"  - Riesgo por trade: {strategy.risk_per_trade*100:.1f}%")
    print(f"  - Máximo posiciones: {strategy.max_positions}")
    
    # Portafolio
    cash = initial_capital
    positions = {}  # {symbol: {shares, entry_price, highest_price, entry_date, pt_1_hit}}
    portfolio_values = []
    trades = []
    monthly_selections = []
    
    available_dates = prices.index
    
    print("\n" + "=" * 95)
    print("EJECUTANDO BACKTEST - MICROMANAGEMENT")
    print("=" * 95)
    
    current_month = None
    selected_stocks = []
    
    for i, current_date in enumerate(available_dates):
        # Detectar cambio de mes
        month_changed = (current_month is None or current_date.month != current_month)
        current_month = current_date.month
        
        # Detectar último día del mes
        last_day_of_month = False
        if i < len(available_dates) - 1:
            next_date = available_dates[i + 1]
            last_day_of_month = (next_date.month != current_date.month)
        else:
            last_day_of_month = True
        
        # Calcular valor del portafolio
        portfolio_value = cash
        for symbol, pos in positions.items():
            if symbol in prices.columns and not pd.isna(prices.loc[current_date, symbol]):
                current_price = prices.loc[current_date, symbol]
                portfolio_value += pos['shares'] * current_price
        
        # === SELECCIÓN MENSUAL ===
        if month_changed and i >= strategy.lookback_months * 21:
            lookback_start = max(0, i - strategy.lookback_months * 21 - strategy.sma_period)
            hist_prices = prices.iloc[lookback_start:i+1]
            hist_volumes = volumes.iloc[lookback_start:i+1] if not volumes.empty else pd.DataFrame()
            
            selected_stocks = strategy.select_stocks(hist_prices, hist_volumes, current_date)
            
            monthly_selections.append({
                'date': current_date,
                'selected': selected_stocks,
                'num_selected': len(selected_stocks)
            })
            
            if len(selected_stocks) > 0:
                print(f"\n[{current_date.date()}] Nuevo mes - Seleccionados: {selected_stocks}")
        
        # === ENTRADAS (solo si hay selección y es principio de mes) ===
        if month_changed and len(selected_stocks) > 0:
            # Calcular cash disponible por posición
            available_cash = cash * 0.95  # 95% del cash
            cash_per_stock = available_cash / min(len(selected_stocks), strategy.max_positions)
            
            for symbol in selected_stocks:
                if symbol in positions:
                    continue  # Ya tenemos posición
                
                if len(positions) >= strategy.max_positions:
                    break
                
                if symbol not in prices.columns:
                    continue
                
                current_price = prices.loc[current_date, symbol]
                if pd.isna(current_price) or current_price <= 0:
                    continue
                
                # Calcular stop loss (3% debajo de entrada)
                stop_price = current_price * (1 + strategy.stop_loss)
                
                # Calcular tamaño de posición basado en riesgo
                shares = strategy.calculate_position_size(portfolio_value, current_price, stop_price)
                
                # Limitar por cash disponible
                max_shares_by_cash = int(cash_per_stock / (current_price * 1.001))
                shares = min(shares, max_shares_by_cash)
                
                if shares > 0:
                    cost = shares * current_price * 1.001
                    if cost <= cash:
                        cash -= cost
                        positions[symbol] = {
                            'shares': shares,
                            'entry_price': current_price,
                            'highest_price': current_price,
                            'entry_date': current_date,
                            'pt_1_hit': False
                        }
                        
                        trades.append({
                            'date': current_date,
                            'symbol': symbol,
                            'action': 'BUY',
                            'shares': shares,
                            'price': current_price,
                            'cost': cost,
                            'stop_price': stop_price
                        })
                        
                        print(f"  BUY {symbol}: {shares} shares @ ${current_price:.2f} "
                              f"(Stop: ${stop_price:.2f})")
        
        # === GESTIÓN DE SALIDAS (monitoreo diario) ===
        for symbol in list(positions.keys()):
            if symbol not in prices.columns:
                continue
            
            current_price = prices.loc[current_date, symbol]
            if pd.isna(current_price):
                continue
            
            pos = positions[symbol]
            should_exit, exit_reason, exit_pct = strategy.check_exits(
                pos, current_price, current_date, last_day_of_month
            )
            
            if should_exit:
                shares_to_sell = int(pos['shares'] * exit_pct)
                if shares_to_sell <= 0:
                    shares_to_sell = pos['shares']
                
                proceeds = shares_to_sell * current_price * 0.999
                cash += proceeds
                
                pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
                
                trades.append({
                    'date': current_date,
                    'symbol': symbol,
                    'action': f'SELL_{exit_reason}',
                    'shares': shares_to_sell,
                    'price': current_price,
                    'proceeds': proceeds,
                    'pnl_pct': pnl_pct
                })
                
                if exit_pct >= 1.0 or shares_to_sell >= pos['shares']:
                    del positions[symbol]
                else:
                    pos['shares'] -= shares_to_sell
                
                if last_day_of_month:
                    print(f"  [{current_date.date()}] SELL {symbol}: {exit_reason} "
                          f"@ ${current_price:.2f} (P/L: {pnl_pct:+.2f}%)")
        
        # === REGISTRAR VALOR DEL PORTAFOLIO ===
        portfolio_values.append({
            'date': current_date,
            'portfolio_value': portfolio_value,
            'cash': cash,
            'num_positions': len(positions),
            'deployed_pct': (portfolio_value - cash) / portfolio_value if portfolio_value > 0 else 0
        })
    
    # === RESULTADOS ===
    print("\n" + "=" * 95)
    print("OMNICAPITAL v4.0 - RESULTADOS OFICIALES")
    print("=" * 95)
    
    df_results = pd.DataFrame(portfolio_values)
    
    if df_results.empty:
        print("Error: No se generaron resultados")
        return
    
    final_value = df_results['portfolio_value'].iloc[-1]
    total_return = (final_value - initial_capital) / initial_capital
    
    # Métricas
    df_results['returns'] = df_results['portfolio_value'].pct_change()
    volatility = df_results['returns'].std() * np.sqrt(252)
    
    # Drawdown
    rolling_max = df_results['portfolio_value'].expanding().max()
    drawdown = (df_results['portfolio_value'] - rolling_max) / rolling_max
    max_drawdown = drawdown.min()
    
    # Sharpe y Calmar
    excess_returns = df_results['returns'].mean() * 252 - 0.02
    sharpe_ratio = excess_returns / (df_results['returns'].std() * np.sqrt(252)) if df_results['returns'].std() > 0 else 0
    calmar_ratio = (total_return / abs(max_drawdown)) if max_drawdown != 0 else 0
    
    # Métricas de actividad
    avg_deployed = df_results['deployed_pct'].mean() * 100
    
    print(f"\n>> CAPITAL")
    print(f"   Inicial:              ${initial_capital:>15,.2f}")
    print(f"   Final:                ${final_value:>15,.2f}")
    print(f"   Profit/Loss:          ${final_value - initial_capital:>+15,.2f}")
    print(f"   Retorno Total:        {total_return:>15.2%}")
    print(f"   Retorno Anualizado:   {(1+total_return)**(365/(end_date-start_date).days)-1:>15.2%}")
    
    print(f"\n>> RIESGO")
    print(f"   Volatilidad:          {volatility:>15.2%}")
    print(f"   Max Drawdown:         {max_drawdown:>15.2%}")
    print(f"   Sharpe Ratio:         {sharpe_ratio:>15.2f}")
    print(f"   Calmar Ratio:         {calmar_ratio:>15.2f}")
    
    print(f"\n>> ACTIVIDAD")
    print(f"   Capital Deployed:    {avg_deployed:>15.1f}% (promedio)")
    print(f"   Total Trades:         {len(trades):>15}")
    
    if trades:
        df_trades = pd.DataFrame(trades)
        buys = df_trades[df_trades['action'] == 'BUY']
        sells = df_trades[df_trades['action'].str.contains('SELL')]
        
        print(f"   Compras:              {len(buys):>15}")
        print(f"   Ventas:               {len(sells):>15}")
        
        # Análisis por tipo de salida
        for exit_type in ['PROFIT_TARGET_1', 'PROFIT_TARGET_2', 'STOP_LOSS', 'TRAILING_STOP', 'TIME_EXIT']:
            count = len(df_trades[df_trades['action'].str.contains(exit_type)])
            if count > 0:
                print(f"   - {exit_type:20}: {count:>5}")
        
        if 'pnl_pct' in df_trades.columns:
            valid_pnls = df_trades[df_trades['pnl_pct'].notna()]
            if len(valid_pnls) > 0:
                win_rate = (valid_pnls['pnl_pct'] > 0).mean()
                avg_win = valid_pnls[valid_pnls['pnl_pct'] > 0]['pnl_pct'].mean() if (valid_pnls['pnl_pct'] > 0).any() else 0
                avg_loss = valid_pnls[valid_pnls['pnl_pct'] < 0]['pnl_pct'].mean() if (valid_pnls['pnl_pct'] < 0).any() else 0
                
                print(f"\n>> PERFORMANCE")
                print(f"   Win Rate:             {win_rate:>15.1%}")
                print(f"   Ganancia Promedio:    {avg_win:>15.2%}")
                print(f"   Pérdida Promedio:     {avg_loss:>15.2%}")
                print(f"   Ratio G/P:            {abs(avg_win/avg_loss):>15.2f}")
    
    # Evolución mensual
    print(f"\n>> EVOLUCION MENSUAL")
    print("-" * 95)
    print("Fecha          | Valor           | Pos | Deployed | Variación")
    print("-" * 95)
    
    sample_points = df_results.iloc[::max(1, len(df_results)//20)]
    prev_value = initial_capital
    
    for _, row in sample_points.iterrows():
        change = (row['portfolio_value'] - prev_value) / prev_value
        change_str = f"{change:+.2%}" if change != 0 else "-"
        print(f"{row['date'].date()} | ${row['portfolio_value']:>13,.2f} | {row['num_positions']:2} | "
              f"{row['deployed_pct']*100:5.1f}% | {change_str:>8}")
        prev_value = row['portfolio_value']
    
    # Guardar resultados
    df_results.to_csv('backtests/backtest_v4_micromanagement_results.csv', index=False)
    if trades:
        pd.DataFrame(trades).to_csv('backtests/trades_v4_micromanagement.csv', index=False)
    
    print(f"\n>> Resultados guardados:")
    print(f"   - backtests/backtest_v4_micromanagement_results.csv")
    print(f"   - backtests/trades_v4_micromanagement.csv")
    
    return df_results, trades


if __name__ == '__main__':
    # Mayor tiempo posible
    end_date = datetime.now()
    start_date = datetime(2000, 1, 1)  # Datos desde 2000 (máximo disponible para volumen)
    
    print(f"Ejecutando backtest desde {start_date.date()}...")
    
    results, trades = run_omnicapital_v4(start_date, end_date)