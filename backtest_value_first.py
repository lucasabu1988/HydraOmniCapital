"""
AlphaMax Value-First Backtest
Backtest con filtro de valoración primario y mayor actividad
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import yaml

from src.data.data_provider import YFinanceProvider
from src.signals.technical import TechnicalSignals, SignalType
from src.signals.fundamental import FundamentalSignals, FundamentalMetrics


def get_sp500_top30():
    """Retorna las 30 mayores acciones del S&P 500"""
    return [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
        'JPM', 'V', 'JNJ', 'UNH', 'XOM', 'WMT', 'PG', 'MA', 'HD', 'CVX',
        'MRK', 'ABBV', 'PEP', 'KO', 'PFE', 'AVGO', 'COST', 'TMO', 'DIS',
        'ABT', 'ADBE', 'BAC'
    ]


def calculate_value_score(pe_ratio, pb_ratio, ps_ratio, ev_ebitda):
    """
    Calcula un score de valoración (0-100)
    Menor P/E, P/B, P/S, EV/EBITDA = Mayor score
    """
    score = 50  # Base
    
    # P/E Score (mejor si < 15)
    if pe_ratio and pe_ratio > 0:
        if pe_ratio < 10:
            score += 25
        elif pe_ratio < 15:
            score += 15
        elif pe_ratio < 20:
            score += 5
        elif pe_ratio > 30:
            score -= 20
    
    # P/B Score (mejor si < 2)
    if pb_ratio and pb_ratio > 0:
        if pb_ratio < 1:
            score += 20
        elif pb_ratio < 2:
            score += 10
        elif pb_ratio > 4:
            score -= 15
    
    # P/S Score (mejor si < 2)
    if ps_ratio and ps_ratio > 0:
        if ps_ratio < 1:
            score += 15
        elif ps_ratio < 2:
            score += 5
        elif ps_ratio > 5:
            score -= 10
    
    # EV/EBITDA Score (mejor si < 10)
    if ev_ebitda and ev_ebitda > 0:
        if ev_ebitda < 8:
            score += 15
        elif ev_ebitda < 12:
            score += 5
        elif ev_ebitda > 20:
            score -= 10
    
    return max(0, min(100, score))


def run_value_first_backtest(start_date, end_date, initial_capital=1000000):
    """
    Backtest con enfoque en valoración primaria
    """
    print("=" * 90)
    print("ALPHAMAX VALUE-FIRST BACKTEST")
    print("=" * 90)
    print(f"Periodo: {start_date.date()} a {end_date.date()}")
    print(f"Capital Inicial: ${initial_capital:,.2f}")
    print(f"Estrategia: Filtro de Valoración (40%) + Técnico (45%) + Calidad (15%)")
    print(f"Umbral Confianza: 50% | Max Posiciones: 30 | Max Drawdown: 15%")
    print("=" * 90)
    
    # Símbolos
    symbols = get_sp500_top30()
    print(f"\nUniverso: {len(symbols)} acciones principales del S&P 500")
    
    # Descargar datos
    provider = YFinanceProvider()
    print("\nDescargando datos históricos...")
    prices = provider.get_historical_prices(symbols, start_date=start_date, end_date=end_date)
    
    if prices.empty:
        print("Error: No se pudieron descargar datos")
        return
    
    print(f"Datos descargados: {prices.shape[0]} días x {prices.shape[1]} símbolos")
    
    # Obtener datos fundamentales actuales para filtrado
    print("\nObteniendo datos fundamentales...")
    fundamentals = {}
    for symbol in symbols:
        try:
            info = provider.get_ticker_info(symbol)
            fundamentals[symbol] = {
                'pe_ratio': info.get('trailing_pe'),
                'forward_pe': info.get('forward_pe'),
                'pb_ratio': info.get('pb_ratio'),
                'ps_ratio': info.get('priceToSalesTrailing12Months'),
                'ev_ebitda': info.get('enterpriseToEbitda'),
                'roe': info.get('returnOnEquity'),
                'debt_equity': info.get('debtToEquity'),
                'sector': info.get('sector', 'Unknown')
            }
        except:
            fundamentals[symbol] = {}
    
    # Calcular score de valoración para cada acción
    print("\nScore de Valoración (Top 10 más subvaluadas):")
    print("-" * 90)
    value_scores = {}
    for symbol in symbols:
        f = fundamentals.get(symbol, {})
        score = calculate_value_score(
            f.get('pe_ratio'),
            f.get('pb_ratio'),
            f.get('ps_ratio'),
            f.get('ev_ebitda')
        )
        value_scores[symbol] = score
    
    # Mostrar top 10
    sorted_by_value = sorted(value_scores.items(), key=lambda x: x[1], reverse=True)
    for i, (symbol, score) in enumerate(sorted_by_value[:10], 1):
        f = fundamentals.get(symbol, {})
        print(f"{i:2}. {symbol:5} | Score: {score:3.0f} | "
              f"P/E: {f.get('pe_ratio') or 'N/A':>6} | "
              f"P/B: {f.get('pb_ratio') or 'N/A':>5} | "
              f"Sector: {f.get('sector', 'Unknown')[:15]:15}")
    
    # Portafolio
    cash = initial_capital
    positions = {}  # {symbol: {'shares': X, 'entry_price': Y, 'highest_price': Z}}
    portfolio_values = []
    trades = []
    
    # Configurar señales técnicas
    tech_config = {
        'entry': [
            {'name': 'momentum', 'weight': 0.25, 'lookback': 90, 'min_momentum': 0.03},
            {'name': 'trend', 'weight': 0.20, 'short_ma': 10, 'long_ma': 30}
        ]
    }
    tech_signals = TechnicalSignals(tech_config)
    
    # Fechas de rebalanceo (quincenal para más actividad)
    available_dates = prices.index
    rebalance_dates = pd.date_range(start=available_dates[0], end=available_dates[-1], freq='W-FRI')
    
    print("\n" + "=" * 90)
    print("EJECUTANDO BACKTEST")
    print("=" * 90)
    
    for i, date in enumerate(rebalance_dates):
        # Encontrar fecha más cercana
        closest_idx = available_dates.get_indexer([date], method='nearest')[0]
        if closest_idx < 0 or closest_idx >= len(available_dates):
            continue
        
        current_date = available_dates[closest_idx]
        
        # Calcular valor del portafolio
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in prices.columns and not pd.isna(prices.loc[current_date, symbol]):
                current_price = prices.loc[current_date, symbol]
                portfolio_value += pos['shares'] * current_price
                # Actualizar highest_price
                if current_price > pos['highest_price']:
                    pos['highest_price'] = current_price
        
        portfolio_values.append({
            'date': current_date,
            'portfolio_value': portfolio_value,
            'cash': cash,
            'num_positions': len(positions)
        })
        
        # Mostrar progreso cada 13 semanas (3 meses)
        if i % 13 == 0:
            print(f"[{current_date.date()}] Valor: ${portfolio_value:>12,.2f} | "
                  f"Pos: {len(positions):2} | Cash: ${cash:>10,.2f}")
        
        # === GESTIÓN DE POSICIONES EXISTENTES ===
        for symbol in list(positions.keys()):
            if symbol not in prices.columns:
                continue
            
            current_price = prices.loc[current_date, symbol]
            pos = positions[symbol]
            
            # Trailing Stop Loss (5% debajo del máximo)
            stop_price = pos['highest_price'] * 0.95
            
            if current_price <= stop_price:
                # Vender
                proceeds = pos['shares'] * current_price * 0.999
                cash += proceeds
                pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
                trades.append({
                    'date': current_date,
                    'symbol': symbol,
                    'action': 'SELL',
                    'shares': pos['shares'],
                    'price': current_price,
                    'pnl_pct': pnl_pct,
                    'reason': 'TRAILING_STOP'
                })
                del positions[symbol]
                continue
            
            # Take Profit parcial (si subió 15%)
            if current_price >= pos['entry_price'] * 1.15:
                # Vender 50%
                shares_to_sell = pos['shares'] // 2
                if shares_to_sell > 0:
                    proceeds = shares_to_sell * current_price * 0.999
                    cash += proceeds
                    pos['shares'] -= shares_to_sell
                    trades.append({
                        'date': current_date,
                        'symbol': symbol,
                        'action': 'SELL_PARTIAL',
                        'shares': shares_to_sell,
                        'price': current_price,
                        'reason': 'TAKE_PROFIT'
                    })
        
        # === BUSCAR NUEVAS OPORTUNIDADES ===
        if len(positions) >= 30:  # Máximo 30 posiciones
            continue
        
        # Filtrar por valoración primero (score > 60)
        candidates = []
        for symbol in symbols:
            if symbol in positions:
                continue
            if symbol not in prices.columns:
                continue
            
            # Filtro 1: Valoración
            value_score = value_scores.get(symbol, 0)
            if value_score < 60:  # Solo acciones con buena valoración
                continue
            
            # Filtro 2: Datos suficientes
            symbol_prices = prices[symbol].dropna()
            if len(symbol_prices) < 30:
                continue
            
            current_price = symbol_prices.iloc[closest_idx]
            if pd.isna(current_price) or current_price <= 0:
                continue
            
            # Filtro 3: Señal técnica (momentum o tendencia)
            analysis = tech_signals.analyze_all_signals(symbol, symbol_prices)
            
            # Combinar scores
            tech_score = analysis['final_strength'] * 100 if analysis['final_signal'] == SignalType.BUY else 0
            combined_score = value_score * 0.6 + tech_score * 0.4  # 60% valoración, 40% técnico
            
            if combined_score >= 50:  # Umbral reducido
                candidates.append({
                    'symbol': symbol,
                    'value_score': value_score,
                    'tech_score': tech_score,
                    'combined_score': combined_score,
                    'current_price': current_price,
                    'sector': fundamentals.get(symbol, {}).get('sector', 'Unknown')
                })
        
        # Ordenar por score combinado y tomar top 3
        candidates.sort(key=lambda x: x['combined_score'], reverse=True)
        
        for candidate in candidates[:3]:
            if len(positions) >= 30:
                break
            
            symbol = candidate['symbol']
            current_price = candidate['current_price']
            
            # Verificar diversificación por sector
            sector = candidate['sector']
            sector_exposure = sum(1 for p in positions.values() if p.get('sector') == sector)
            if sector_exposure >= 5:  # Máximo 5 acciones por sector
                continue
            
            # Tamaño de posición (diversificado)
            position_value = min(portfolio_value * 0.05, cash * 0.95)  # 5% por posición
            
            if position_value > 2000:  # Mínimo $2000
                shares = int(position_value / current_price)
                if shares > 0:
                    cost = shares * current_price * 1.001
                    if cost <= cash:
                        cash -= cost
                        positions[symbol] = {
                            'shares': shares,
                            'entry_price': current_price,
                            'highest_price': current_price,
                            'sector': sector,
                            'entry_date': current_date
                        }
                        trades.append({
                            'date': current_date,
                            'symbol': symbol,
                            'action': 'BUY',
                            'shares': shares,
                            'price': current_price,
                            'value_score': candidate['value_score'],
                            'tech_score': candidate['tech_score']
                        })
    
    # === RESULTADOS ===
    print("\n" + "=" * 90)
    print("RESULTADOS DEL BACKTEST")
    print("=" * 90)
    
    df_results = pd.DataFrame(portfolio_values)
    
    if df_results.empty:
        print("Error: No se generaron resultados")
        return
    
    final_value = df_results['portfolio_value'].iloc[-1]
    total_return = (final_value - initial_capital) / initial_capital
    
    # Métricas
    df_results['returns'] = df_results['portfolio_value'].pct_change()
    volatility = df_results['returns'].std() * np.sqrt(52)
    
    # Drawdown
    rolling_max = df_results['portfolio_value'].expanding().max()
    drawdown = (df_results['portfolio_value'] - rolling_max) / rolling_max
    max_drawdown = drawdown.min()
    
    # Sharpe
    excess_returns = df_results['returns'].mean() * 52 - 0.02
    sharpe_ratio = excess_returns / (df_results['returns'].std() * np.sqrt(52)) if df_results['returns'].std() > 0 else 0
    
    # Calmar
    calmar_ratio = (total_return / abs(max_drawdown)) if max_drawdown != 0 else 0
    
    print(f"\nCapital Inicial:        ${initial_capital:>15,.2f}")
    print(f"Capital Final:          ${final_value:>15,.2f}")
    print(f"Retorno Total:          {total_return:>15.2%}")
    print(f"Retorno Anualizado:     {(1+total_return)**(365/(end_date-start_date).days)-1:>15.2%}")
    print(f"Volatilidad Anual:      {volatility:>15.2%}")
    print(f"Max Drawdown:           {max_drawdown:>15.2%}")
    print(f"Sharpe Ratio:           {sharpe_ratio:>15.2f}")
    print(f"Calmar Ratio:           {calmar_ratio:>15.2f}")
    
    # Trades
    print(f"\n--- ACTIVIDAD DE TRADING ---")
    print(f"Total de Trades:        {len(trades):>15}")
    
    if trades:
        df_trades = pd.DataFrame(trades)
        buys = df_trades[df_trades['action'] == 'BUY']
        sells = df_trades[df_trades['action'].isin(['SELL', 'SELL_PARTIAL'])]
        
        print(f"Compras:                {len(buys):>15}")
        print(f"Ventas:                 {len(sells):>15}")
        
        if 'pnl_pct' in df_trades.columns:
            winning_trades = df_trades[df_trades['pnl_pct'] > 0]
            win_rate = len(winning_trades) / len(sells) if len(sells) > 0 else 0
            avg_win = winning_trades['pnl_pct'].mean() if len(winning_trades) > 0 else 0
            losing_trades = df_trades[df_trades['pnl_pct'] < 0]
            avg_loss = losing_trades['pnl_pct'].mean() if len(losing_trades) > 0 else 0
            
            print(f"Win Rate:               {win_rate:>15.1%}")
            print(f"Ganancia Promedio:      {avg_win:>15.2%}")
            print(f"Pérdida Promedio:       {avg_loss:>15.2%}")
    
    # Evolución
    print("\n--- EVOLUCIÓN DEL PORTAFOLIO ---")
    print("Fecha          | Valor          | Pos | Variación")
    print("-" * 60)
    
    sample_points = df_results.iloc[::max(1, len(df_results)//20)]  # 20 puntos
    prev_value = initial_capital
    
    for _, row in sample_points.iterrows():
        change = (row['portfolio_value'] - prev_value) / prev_value
        change_str = f"{change:+.2%}" if change != 0 else "-"
        print(f"{row['date'].date()} | ${row['portfolio_value']:>12,.2f} | {row['num_positions']:2} | {change_str:>8}")
        prev_value = row['portfolio_value']
    
    # Guardar
    df_results.to_csv('backtests/backtest_value_first_results.csv', index=False)
    if trades:
        pd.DataFrame(trades).to_csv('backtests/trades_value_first.csv', index=False)
    
    print(f"\nResultados guardados en:")
    print(f"  - backtests/backtest_value_first_results.csv")
    print(f"  - backtests/trades_value_first.csv")
    
    return df_results, trades


if __name__ == '__main__':
    # Período: 10 años (2016-2026)
    # Incluye años alcistas (2020-2021) y bajistas (2018, 2022)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365*10)
    
    results, trades = run_value_first_backtest(start_date, end_date)
