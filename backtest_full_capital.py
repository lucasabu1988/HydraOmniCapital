"""
AlphaMax Full Capital Deployment Backtest
Backtest usando 100% del capital disponible
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


def get_sp500_top40():
    """Retorna 40 mayores acciones para más diversificación"""
    return [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
        'JPM', 'V', 'JNJ', 'UNH', 'XOM', 'WMT', 'PG', 'MA', 'HD', 'CVX',
        'MRK', 'ABBV', 'PEP', 'KO', 'PFE', 'AVGO', 'COST', 'TMO', 'DIS',
        'ABT', 'ADBE', 'BAC', 'ACN', 'WFC', 'CRM', 'VZ', 'DHR', 'NKE',
        'TXN', 'PM', 'NEE', 'AMD'
    ]


def calculate_value_score(pe_ratio, pb_ratio, ps_ratio, ev_ebitda, roe):
    """
    Calcula un score de valoración mejorado (0-100)
    """
    score = 50
    
    # P/E Score
    if pe_ratio and pe_ratio > 0:
        if pe_ratio < 12:
            score += 20
        elif pe_ratio < 18:
            score += 12
        elif pe_ratio < 25:
            score += 5
        elif pe_ratio > 40:
            score -= 15
    
    # P/B Score
    if pb_ratio and pb_ratio > 0:
        if pb_ratio < 1.5:
            score += 18
        elif pb_ratio < 2.5:
            score += 10
        elif pb_ratio > 5:
            score -= 12
    
    # P/S Score
    if ps_ratio and ps_ratio > 0:
        if ps_ratio < 2:
            score += 12
        elif ps_ratio > 8:
            score -= 8
    
    # EV/EBITDA Score
    if ev_ebitda and ev_ebitda > 0:
        if ev_ebitda < 10:
            score += 15
        elif ev_ebitda < 15:
            score += 8
        elif ev_ebitda > 25:
            score -= 10
    
    # ROE Bonus
    if roe and roe > 0.20:
        score += 10
    elif roe and roe > 0.15:
        score += 5
    
    return max(0, min(100, score))


def run_full_capital_backtest(start_date, end_date, initial_capital=1000000):
    """
    Backtest usando 100% del capital
    """
    print("=" * 95)
    print("ALPHAMAX FULL CAPITAL DEPLOYMENT BACKTEST")
    print("=" * 95)
    print(f"Periodo: {start_date.date()} a {end_date.date()}")
    print(f"Capital Inicial: ${initial_capital:,.2f}")
    print(f"Estrategia: 100% Capital Deployed | Max 40 Posiciones | Diversificación Total")
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
    
    # Obtener fundamentales
    print("\nObteniendo datos fundamentales...")
    fundamentals = {}
    for symbol in prices.columns:
        try:
            info = provider.get_ticker_info(symbol)
            fundamentals[symbol] = {
                'pe_ratio': info.get('trailing_pe'),
                'pb_ratio': info.get('pb_ratio'),
                'ps_ratio': info.get('priceToSalesTrailing12Months'),
                'ev_ebitda': info.get('enterpriseToEbitda'),
                'roe': info.get('returnOnEquity'),
                'sector': info.get('sector', 'Unknown'),
                'market_cap': info.get('marketCap', 0)
            }
        except:
            fundamentals[symbol] = {'sector': 'Unknown', 'market_cap': 0}
    
    # Calcular scores
    print("\nAnálisis de Valoración:")
    print("-" * 95)
    value_scores = {}
    for symbol in prices.columns:
        f = fundamentals.get(symbol, {})
        score = calculate_value_score(
            f.get('pe_ratio'),
            f.get('pb_ratio'),
            f.get('ps_ratio'),
            f.get('ev_ebitda'),
            f.get('roe')
        )
        value_scores[symbol] = {
            'score': score,
            'sector': f.get('sector', 'Unknown'),
            'market_cap': f.get('market_cap', 0)
        }
    
    # Mostrar top 15
    sorted_values = sorted(value_scores.items(), key=lambda x: x[1]['score'], reverse=True)
    for i, (symbol, data) in enumerate(sorted_values[:15], 1):
        f = fundamentals.get(symbol, {})
        print(f"{i:2}. {symbol:5} | Score: {data['score']:3.0f} | "
              f"P/E: {str(f.get('pe_ratio'))[:6]:>6} | "
              f"P/B: {str(f.get('pb_ratio'))[:5]:>5} | "
              f"Sector: {data['sector'][:18]:18}")
    
    # Portafolio - Usar 100% del capital
    cash = initial_capital
    positions = {}  # {symbol: {shares, entry_price, highest_price, sector, target_weight}}
    portfolio_values = []
    trades = []
    
    tech_config = {
        'entry': [
            {'name': 'momentum', 'weight': 0.30, 'lookback': 60, 'min_momentum': 0.02},
            {'name': 'trend', 'weight': 0.20, 'short_ma': 10, 'long_ma': 25}
        ]
    }
    tech_signals = TechnicalSignals(tech_config)
    
    # Rebalanceo semanal
    available_dates = prices.index
    rebalance_dates = pd.date_range(start=available_dates[0], end=available_dates[-1], freq='W-FRI')
    
    print("\n" + "=" * 95)
    print("EJECUTANDO BACKTEST - FULL CAPITAL DEPLOYMENT")
    print("=" * 95)
    
    for i, date in enumerate(rebalance_dates):
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
                if current_price > pos['highest_price']:
                    pos['highest_price'] = current_price
        
        portfolio_values.append({
            'date': current_date,
            'portfolio_value': portfolio_value,
            'cash': cash,
            'num_positions': len(positions),
            'deployed_pct': (portfolio_value - cash) / portfolio_value if portfolio_value > 0 else 0
        })
        
        if i % 13 == 0:
            deployed = (portfolio_value - cash) / portfolio_value * 100 if portfolio_value > 0 else 0
            print(f"[{current_date.date()}] Valor: ${portfolio_value:>12,.2f} | "
                  f"Pos: {len(positions):2} | Deployed: {deployed:5.1f}%")
        
        # === GESTIÓN DE POSICIONES ===
        for symbol in list(positions.keys()):
            if symbol not in prices.columns:
                continue
            
            current_price = prices.loc[current_date, symbol]
            pos = positions[symbol]
            
            # Trailing Stop (5%)
            stop_price = pos['highest_price'] * 0.95
            
            if current_price <= stop_price:
                proceeds = pos['shares'] * current_price * 0.999
                cash += proceeds
                pnl_pct = (current_price - pos['entry_price']) / pos['entry_price']
                trades.append({
                    'date': current_date, 'symbol': symbol, 'action': 'SELL',
                    'shares': pos['shares'], 'price': current_price,
                    'pnl_pct': pnl_pct, 'reason': 'STOP_LOSS'
                })
                del positions[symbol]
                continue
            
            # Take Profit escalonado
            gain_pct = (current_price - pos['entry_price']) / pos['entry_price']
            
            if gain_pct >= 0.20 and not pos.get('tp_20_done'):
                # Vender 30% a +20%
                shares_to_sell = int(pos['shares'] * 0.30)
                if shares_to_sell > 0:
                    proceeds = shares_to_sell * current_price * 0.999
                    cash += proceeds
                    pos['shares'] -= shares_to_sell
                    pos['tp_20_done'] = True
                    trades.append({
                        'date': current_date, 'symbol': symbol, 'action': 'SELL_30',
                        'shares': shares_to_sell, 'price': current_price, 'reason': 'TP_20%'
                    })
            
            elif gain_pct >= 0.35 and not pos.get('tp_35_done'):
                # Vender 40% a +35%
                shares_to_sell = int(pos['shares'] * 0.40)
                if shares_to_sell > 0:
                    proceeds = shares_to_sell * current_price * 0.999
                    cash += proceeds
                    pos['shares'] -= shares_to_sell
                    pos['tp_35_done'] = True
                    trades.append({
                        'date': current_date, 'symbol': symbol, 'action': 'SELL_40',
                        'shares': shares_to_sell, 'price': current_price, 'reason': 'TP_35%'
                    })
            
            elif gain_pct >= 0.50:
                # Vender resto a +50%
                proceeds = pos['shares'] * current_price * 0.999
                cash += proceeds
                trades.append({
                    'date': current_date, 'symbol': symbol, 'action': 'SELL_ALL',
                    'shares': pos['shares'], 'price': current_price, 'reason': 'TP_50%'
                })
                del positions[symbol]
        
        # === REBALANCEO Y NUEVAS POSICIONES ===
        # Calcular cash disponible (objetivo: mantener < 5% en cash)
        target_cash_pct = 0.05
        target_cash = portfolio_value * target_cash_pct
        excess_cash = cash - target_cash
        
        # Si tenemos mucho cash, invertir más
        if excess_cash > portfolio_value * 0.10 and len(positions) < 40:
            # Buscar oportunidades
            candidates = []
            
            for symbol in prices.columns:
                if symbol in positions:
                    continue
                
                symbol_prices = prices[symbol].dropna()
                if len(symbol_prices) < 30:
                    continue
                
                current_price = symbol_prices.iloc[closest_idx]
                if pd.isna(current_price) or current_price <= 0:
                    continue
                
                # Score de valoración
                value_data = value_scores.get(symbol, {'score': 0, 'sector': 'Unknown'})
                value_score = value_data['score']
                
                if value_score < 55:  # Umbral mínimo de valoración
                    continue
                
                # Señal técnica
                analysis = tech_signals.analyze_all_signals(symbol, symbol_prices)
                tech_score = analysis['final_strength'] * 100 if analysis['final_signal'] == SignalType.BUY else 0
                
                combined_score = value_score * 0.6 + tech_score * 0.4
                
                if combined_score >= 45:  # Umbral reducido
                    candidates.append({
                        'symbol': symbol,
                        'score': combined_score,
                        'current_price': current_price,
                        'sector': value_data['sector']
                    })
            
            # Ordenar y seleccionar
            candidates.sort(key=lambda x: x['score'], reverse=True)
            
            for candidate in candidates[:5]:  # Hasta 5 nuevas posiciones por rebalanceo
                if cash <= target_cash or len(positions) >= 40:
                    break
                
                symbol = candidate['symbol']
                current_price = candidate['current_price']
                
                # Verificar sector (max 5 por sector)
                sector = candidate['sector']
                sector_count = sum(1 for p in positions.values() if p.get('sector') == sector)
                if sector_count >= 5:
                    continue
                
                # Calcular tamaño: usar excess_cash distribuido
                position_value = min(excess_cash * 0.25, cash * 0.95)
                
                if position_value > 3000:
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
                                'tp_20_done': False,
                                'tp_35_done': False
                            }
                            trades.append({
                                'date': current_date, 'symbol': symbol, 'action': 'BUY',
                                'shares': shares, 'price': current_price,
                                'score': candidate['score']
                            })
        
        # Si aún tenemos mucho cash y poca exposición, forzar compras de valoración
        cash_pct = cash / portfolio_value if portfolio_value > 0 else 1
        if cash_pct > 0.30 and len(positions) < 20:
            # Comprar top valoración sin esperar señal técnica
            for symbol, data in sorted_values[:10]:
                if symbol in positions or symbol not in prices.columns:
                    continue
                if cash <= target_cash or len(positions) >= 40:
                    break
                
                current_price = prices[symbol].iloc[closest_idx]
                if pd.isna(current_price):
                    continue
                
                position_value = min(cash * 0.08, 15000)  # 8% del cash o $15k
                shares = int(position_value / current_price)
                
                if shares > 0:
                    cost = shares * current_price * 1.001
                    if cost <= cash:
                        cash -= cost
                        positions[symbol] = {
                            'shares': shares,
                            'entry_price': current_price,
                            'highest_price': current_price,
                            'sector': data['sector'],
                            'tp_20_done': False,
                            'tp_35_done': False
                        }
                        trades.append({
                            'date': current_date, 'symbol': symbol, 'action': 'BUY_FORZADO',
                            'shares': shares, 'price': current_price,
                            'score': data['score']
                        })
    
    # === RESULTADOS ===
    print("\n" + "=" * 95)
    print("RESULTADOS DEL BACKTEST - FULL CAPITAL")
    print("=" * 95)
    
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
    
    # Sharpe y Calmar
    excess_returns = df_results['returns'].mean() * 52 - 0.02
    sharpe_ratio = excess_returns / (df_results['returns'].std() * np.sqrt(52)) if df_results['returns'].std() > 0 else 0
    calmar_ratio = (total_return / abs(max_drawdown)) if max_drawdown != 0 else 0
    
    # Capital deployado promedio
    avg_deployed = df_results['deployed_pct'].mean() * 100
    
    print(f"\n💰 CAPITAL")
    print(f"   Inicial:              ${initial_capital:>15,.2f}")
    print(f"   Final:                ${final_value:>15,.2f}")
    print(f"   Retorno Total:        {total_return:>15.2%}")
    print(f"   Retorno Anualizado:   {(1+total_return)**(365/(end_date-start_date).days)-1:>15.2%}")
    
    print(f"\n📊 RIESGO")
    print(f"   Volatilidad:          {volatility:>15.2%}")
    print(f"   Max Drawdown:         {max_drawdown:>15.2%}")
    print(f"   Sharpe Ratio:         {sharpe_ratio:>15.2f}")
    print(f"   Calmar Ratio:         {calmar_ratio:>15.2f}")
    
    print(f"\n🚀 ACTIVIDAD")
    print(f"   Capital Deployado:    {avg_deployed:>15.1f}% (promedio)")
    print(f"   Total Trades:         {len(trades):>15}")
    
    if trades:
        df_trades = pd.DataFrame(trades)
        buys = df_trades[df_trades['action'].str.contains('BUY')]
        sells = df_trades[df_trades['action'].str.contains('SELL')]
        
        print(f"   Compras:              {len(buys):>15}")
        print(f"   Ventas:               {len(sells):>15}")
        
        if 'pnl_pct' in df_trades.columns:
            valid_pnls = df_trades[df_trades['pnl_pct'].notna()]
            if len(valid_pnls) > 0:
                win_rate = (valid_pnls['pnl_pct'] > 0).mean()
                avg_win = valid_pnls[valid_pnls['pnl_pct'] > 0]['pnl_pct'].mean() if (valid_pnls['pnl_pct'] > 0).any() else 0
                avg_loss = valid_pnls[valid_pnls['pnl_pct'] < 0]['pnl_pct'].mean() if (valid_pnls['pnl_pct'] < 0).any() else 0
                
                print(f"   Win Rate:             {win_rate:>15.1%}")
                print(f"   Ganancia Promedio:    {avg_win:>15.2%}")
                print(f"   Pérdida Promedio:     {avg_loss:>15.2%}")
    
    # Evolución
    print(f"\n📈 EVOLUCIÓN DEL PORTAFOLIO")
    print("-" * 95)
    print("Fecha          | Valor           | Pos | Deployed | Variación")
    print("-" * 95)
    
    sample_points = df_results.iloc[::max(1, len(df_results)//15)]
    prev_value = initial_capital
    
    for _, row in sample_points.iterrows():
        change = (row['portfolio_value'] - prev_value) / prev_value
        change_str = f"{change:+.2%}" if change != 0 else "-"
        print(f"{row['date'].date()} | ${row['portfolio_value']:>13,.2f} | {row['num_positions']:2} | "
              f"{row['deployed_pct']*100:5.1f}% | {change_str:>8}")
        prev_value = row['portfolio_value']
    
    # Comparación con buy & hold SPY
    print(f"\n🎯 COMPARACIÓN CON BUY & HOLD S&P 500")
    if 'SPY' in prices.columns:
        spy_start = prices['SPY'].dropna().iloc[0]
        spy_end = prices['SPY'].dropna().iloc[-1]
        spy_return = (spy_end - spy_start) / spy_start
        spy_annual = (1 + spy_return) ** (365 / (end_date - start_date).days) - 1
        
        print(f"   S&P 500 (SPY) Retorno Total:     {spy_return:>10.2%}")
        print(f"   S&P 500 (SPY) Anualizado:        {spy_annual:>10.2%}")
        print(f"   AlphaMax Retorno Total:          {total_return:>10.2%}")
        print(f"   AlphaMax Anualizado:             {(1+total_return)**(365/(end_date-start_date).days)-1:>10.2%}")
        
        outperformance = total_return - spy_return
        print(f"   OUTPERFORMANCE:                  {outperformance:>10.2%}")
    
    # Guardar resultados
    df_results.to_csv('backtests/backtest_full_capital_results.csv', index=False)
    if trades:
        pd.DataFrame(trades).to_csv('backtests/trades_full_capital.csv', index=False)
    
    print(f"\n💾 Resultados guardados:")
    print(f"   - backtests/backtest_full_capital_results.csv")
    print(f"   - backtests/trades_full_capital.csv")
    
    return df_results, trades


if __name__ == '__main__':
    # Período de 10 años
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365*10)
    
    results, trades = run_full_capital_backtest(start_date, end_date)
