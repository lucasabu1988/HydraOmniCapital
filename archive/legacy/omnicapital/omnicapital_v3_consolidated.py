"""
AlphaMax OmniCapital v3.0
Consolidated Single-Strategy Investment Algorithm

Copyright (c) 2026 Investment Capital Firm
All Rights Reserved.

Official Release: OmniCapital v3.0
Strategy: Consolidated Single-Strategy with 100% Capital Deployment
Universe: 40 Blue-Chip S&P 500 Equities

Author: Investment Capital Firm
Version: 3.0.0
Date: February 2026

Características v3.0:
- Estrategia consolidada única (Value + Quality + Momentum + Risk Parity)
- Value-First siempre activo como base
- Uso del 100% del capital en todo momento (0% cash buffer)
- Rebalanceo semanal completo
- Sin fallback, una sola estrategia gobierna todo
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import yaml

from src.data.data_provider import YFinanceProvider
from src.strategies.consolidated import ConsolidatedStrategy


def get_sp500_top40():
    """Retorna 40 mayores acciones para más diversificación"""
    return [
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
        'JPM', 'V', 'JNJ', 'UNH', 'XOM', 'WMT', 'PG', 'MA', 'HD', 'CVX',
        'MRK', 'ABBV', 'PEP', 'KO', 'PFE', 'AVGO', 'COST', 'TMO', 'DIS',
        'ABT', 'ADBE', 'BAC', 'ACN', 'WFC', 'CRM', 'VZ', 'DHR', 'NKE',
        'TXN', 'PM', 'NEE', 'AMD'
    ]


def run_omnicapital_v3(start_date, end_date, initial_capital=1000000):
    """
    Backtest usando estrategia consolidada única con 100% capital deployment.
    """
    print("=" * 95)
    print("ALPHAMAX OMNICAPITAL v3.0")
    print("Consolidated Single-Strategy Investment Algorithm")
    print("=" * 95)
    print(f"Periodo: {start_date.date()} a {end_date.date()}")
    print(f"Capital Inicial: ${initial_capital:,.2f}")
    print(f"Estrategia: Consolidada Única | 100% Capital Deployed | 0% Cash Buffer")
    print(f"Componentes: Value + Quality + Momentum + Risk Parity")
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
                'roa': info.get('returnOnAssets'),
                'sector': info.get('sector', 'Unknown'),
                'market_cap': info.get('marketCap', 0),
                'profit_margin': info.get('profitMargins', 0),
                'debt_to_equity': info.get('debtToEquity', 0)
            }
        except:
            fundamentals[symbol] = {'sector': 'Unknown', 'market_cap': 0}
    
    # Inicializar estrategia consolidada
    print("\nInicializando estrategia consolidada...")
    strategy = ConsolidatedStrategy({
        'name': 'OmniCapital_v3_Consolidated',
        'max_positions': 40,
        'target_cash': 0.0,  # 0% cash - usar todo el capital
        'value_weight': 0.50,
        'quality_weight': 0.25,
        'momentum_weight': 0.25,
        'min_value_score': 50,
        'use_trend_filter': True,
        'rebalance_full': True,
        'lookback_days': 252
    })
    
    print(f"Configuración:")
    print(f"  - Max posiciones: {strategy.max_positions}")
    print(f"  - Target cash: {strategy.target_cash_pct:.0%}")
    print(f"  - Value weight: {strategy.value_weight:.0%}")
    print(f"  - Quality weight: {strategy.quality_weight:.0%}")
    print(f"  - Momentum weight: {strategy.momentum_weight:.0%}")
    print(f"  - Min value score: {strategy.min_value_score}")
    
    # Portafolio
    cash = initial_capital
    positions = {}  # {symbol: {shares, entry_price, highest_price, sector, avg_cost}}
    portfolio_values = []
    trades = []
    
    # Rebalanceo semanal
    available_dates = prices.index
    rebalance_dates = pd.date_range(start=available_dates[0], end=available_dates[-1], freq='W-FRI')
    
    print("\n" + "=" * 95)
    print("EJECUTANDO BACKTEST - 100% CAPITAL DEPLOYMENT")
    print("=" * 95)
    
    for i, date in enumerate(rebalance_dates):
        closest_idx = available_dates.get_indexer([date], method='nearest')[0]
        if closest_idx < 0 or closest_idx >= len(available_dates):
            continue
        
        current_date = available_dates[closest_idx]
        
        # Calcular valor del portafolio
        portfolio_value = cash
        current_prices = {}
        
        for symbol, pos in list(positions.items()):
            if symbol in prices.columns and not pd.isna(prices.loc[current_date, symbol]):
                current_price = prices.loc[current_date, symbol]
                current_prices[symbol] = current_price
                portfolio_value += pos['shares'] * current_price
                
                # Actualizar highest price para trailing stop
                if current_price > pos['highest_price']:
                    pos['highest_price'] = current_price
        
        # Calcular deployed percentage
        invested_value = portfolio_value - cash
        deployed_pct = invested_value / portfolio_value if portfolio_value > 0 else 0
        
        portfolio_values.append({
            'date': current_date,
            'portfolio_value': portfolio_value,
            'cash': cash,
            'num_positions': len(positions),
            'deployed_pct': deployed_pct
        })
        
        if i % 13 == 0:
            print(f"[{current_date.date()}] Valor: ${portfolio_value:>12,.2f} | "
                  f"Pos: {len(positions):2} | Cash: ${cash:>10,.2f} | Deployed: {deployed_pct*100:5.1f}%")
        
        # === GESTIÓN DE POSICIONES EXISTENTES ===
        for symbol in list(positions.keys()):
            if symbol not in prices.columns:
                continue
            
            current_price = prices.loc[current_date, symbol]
            pos = positions[symbol]
            
            # Calcular P/L actual
            current_gain = (current_price - pos['avg_cost']) / pos['avg_cost']
            
            # Trailing Stop (5%)
            stop_price = pos['highest_price'] * 0.95
            
            if current_price <= stop_price:
                # Vender todo por stop loss
                proceeds = pos['shares'] * current_price * 0.999
                cash += proceeds
                pnl_pct = (current_price - pos['avg_cost']) / pos['avg_cost']
                
                trades.append({
                    'date': current_date,
                    'symbol': symbol,
                    'action': 'SELL_STOP',
                    'shares': pos['shares'],
                    'price': current_price,
                    'pnl_pct': pnl_pct,
                    'reason': 'STOP_LOSS'
                })
                del positions[symbol]
                continue
            
            # Take Profit Escalonado
            if current_gain >= 0.50:
                # Vender todo a +50%
                proceeds = pos['shares'] * current_price * 0.999
                cash += proceeds
                trades.append({
                    'date': current_date,
                    'symbol': symbol,
                    'action': 'SELL_ALL',
                    'shares': pos['shares'],
                    'price': current_price,
                    'pnl_pct': current_gain,
                    'reason': 'TP_50%'
                })
                del positions[symbol]
            
            elif current_gain >= 0.35 and not pos.get('tp_35_done'):
                # Vender 40% a +35%
                shares_to_sell = int(pos['shares'] * 0.40)
                if shares_to_sell > 0:
                    proceeds = shares_to_sell * current_price * 0.999
                    cash += proceeds
                    pos['shares'] -= shares_to_sell
                    pos['tp_35_done'] = True
                    trades.append({
                        'date': current_date,
                        'symbol': symbol,
                        'action': 'SELL_40',
                        'shares': shares_to_sell,
                        'price': current_price,
                        'pnl_pct': current_gain,
                        'reason': 'TP_35%'
                    })
            
            elif current_gain >= 0.20 and not pos.get('tp_20_done'):
                # Vender 30% a +20%
                shares_to_sell = int(pos['shares'] * 0.30)
                if shares_to_sell > 0:
                    proceeds = shares_to_sell * current_price * 0.999
                    cash += proceeds
                    pos['shares'] -= shares_to_sell
                    pos['tp_20_done'] = True
                    trades.append({
                        'date': current_date,
                        'symbol': symbol,
                        'action': 'SELL_30',
                        'shares': shares_to_sell,
                        'price': current_price,
                        'pnl_pct': current_gain,
                        'reason': 'TP_20%'
                    })
        
        # === REBALANCEO SEMANAL COMPLETO ===
        if i % 1 == 0:  # Cada semana
            # Preparar datos para la estrategia
            lookback = min(strategy.lookback_days, closest_idx)
            hist_prices = prices.iloc[max(0, closest_idx-lookback):closest_idx+1]
            
            # Preparar estado actual del portafolio
            current_portfolio = {
                'positions': positions,
                'cash': cash,
                'portfolio_value': portfolio_value
            }
            
            # Generar señales de la estrategia consolidada
            signals = strategy.generate_signals(hist_prices, fundamentals, current_portfolio)
            
            # Calcular allocaciones objetivo
            allocations = strategy.calculate_allocations(hist_prices, signals)
            
            # Calcular target cash y pesos
            target_cash = portfolio_value * strategy.target_cash_pct  # Debería ser 0
            investable_cash = cash - target_cash
            
            # === AJUSTAR POSICIONES ===
            # Primero, vender posiciones que ya no están en las allocaciones
            for symbol in list(positions.keys()):
                if symbol not in allocations:
                    # Vender posición completa
                    current_price = prices.loc[current_date, symbol]
                    pos = positions[symbol]
                    proceeds = pos['shares'] * current_price * 0.999
                    cash += proceeds
                    pnl_pct = (current_price - pos['avg_cost']) / pos['avg_cost']
                    
                    trades.append({
                        'date': current_date,
                        'symbol': symbol,
                        'action': 'SELL_REBALANCE',
                        'shares': pos['shares'],
                        'price': current_price,
                        'pnl_pct': pnl_pct,
                        'reason': 'REBALANCE_EXIT'
                    })
                    del positions[symbol]
            
            # Calcular valor objetivo por posición
            target_values = {}
            for symbol, alloc in allocations.items():
                target_values[symbol] = portfolio_value * alloc.weight
            
            # Segundo, ajustar posiciones existentes
            for symbol, target_value in target_values.items():
                if symbol not in prices.columns:
                    continue
                
                current_price = prices.loc[current_date, symbol]
                if pd.isna(current_price) or current_price <= 0:
                    continue
                
                target_shares = int(target_value / current_price)
                
                if symbol in positions:
                    # Ajustar posición existente
                    pos = positions[symbol]
                    current_shares = pos['shares']
                    diff_shares = target_shares - current_shares
                    
                    if diff_shares > 0:
                        # Comprar más
                        cost = diff_shares * current_price * 1.001
                        if cost <= cash:
                            cash -= cost
                            # Actualizar costo promedio
                            total_cost = pos['avg_cost'] * current_shares + current_price * diff_shares
                            pos['shares'] = target_shares
                            pos['avg_cost'] = total_cost / target_shares
                            
                            trades.append({
                                'date': current_date,
                                'symbol': symbol,
                                'action': 'BUY_ADD',
                                'shares': diff_shares,
                                'price': current_price,
                                'reason': 'REBALANCE_ADD'
                            })
                    elif diff_shares < 0:
                        # Vender parcialmente
                        shares_to_sell = abs(diff_shares)
                        if shares_to_sell >= current_shares:
                            shares_to_sell = current_shares
                        
                        proceeds = shares_to_sell * current_price * 0.999
                        cash += proceeds
                        pos['shares'] -= shares_to_sell
                        
                        if pos['shares'] <= 0:
                            del positions[symbol]
                        
                        trades.append({
                            'date': current_date,
                            'symbol': symbol,
                            'action': 'SELL_REDUCE',
                            'shares': shares_to_sell,
                            'price': current_price,
                            'reason': 'REBALANCE_REDUCE'
                        })
                else:
                    # Nueva posición
                    if target_shares > 0 and investable_cash > 0:
                        cost = target_shares * current_price * 1.001
                        
                        if cost <= investable_cash and cost <= cash:
                            cash -= cost
                            sector = fundamentals.get(symbol, {}).get('sector', 'Unknown')
                            
                            positions[symbol] = {
                                'shares': target_shares,
                                'entry_price': current_price,
                                'avg_cost': current_price,
                                'highest_price': current_price,
                                'sector': sector,
                                'tp_20_done': False,
                                'tp_35_done': False
                            }
                            
                            # Obtener metadata de la señal
                            signal_meta = {}
                            for signal in signals:
                                if signal.symbol == symbol:
                                    signal_meta = signal.metadata
                                    break
                            
                            trades.append({
                                'date': current_date,
                                'symbol': symbol,
                                'action': 'BUY',
                                'shares': target_shares,
                                'price': current_price,
                                'reason': 'CONSOLIDATED_STRATEGY',
                                'total_score': signal_meta.get('total_score', 0),
                                'value_score': signal_meta.get('value_score', 0),
                                'quality_score': signal_meta.get('quality_score', 0),
                                'momentum_score': signal_meta.get('momentum_score', 0)
                            })
            
            # === USAR TODO EL CASH RESTANTE ===
            # Si aún queda cash, distribuir entre las posiciones existentes
            if cash > portfolio_value * 0.02:  # Más de 2% en cash
                # Encontrar las mejores posiciones para agregar
                existing_symbols = list(positions.keys())
                if existing_symbols:
                    additional_cash_per_symbol = cash * 0.95 / len(existing_symbols)
                    
                    for symbol in existing_symbols:
                        if symbol not in prices.columns:
                            continue
                        
                        current_price = prices.loc[current_date, symbol]
                        if pd.isna(current_price) or current_price <= 0:
                            continue
                        
                        additional_shares = int(additional_cash_per_symbol / current_price)
                        
                        if additional_shares > 0:
                            cost = additional_shares * current_price * 1.001
                            if cost <= cash:
                                cash -= cost
                                pos = positions[symbol]
                                
                                # Actualizar costo promedio
                                total_cost = pos['avg_cost'] * pos['shares'] + current_price * additional_shares
                                pos['shares'] += additional_shares
                                pos['avg_cost'] = total_cost / pos['shares']
                                
                                trades.append({
                                    'date': current_date,
                                    'symbol': symbol,
                                    'action': 'BUY_FULL_DEPLOY',
                                    'shares': additional_shares,
                                    'price': current_price,
                                    'reason': 'FULL_CAPITAL_DEPLOYMENT'
                                })
    
    # === RESULTADOS ===
    print("\n" + "=" * 95)
    print("OMNICAPITAL v3.0 - RESULTADOS OFICIALES")
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
    avg_cash = df_results['cash'].mean()
    
    print(f"\n>> CAPITAL")
    print(f"   Inicial:              ${initial_capital:>15,.2f}")
    print(f"   Final:                ${final_value:>15,.2f}")
    print(f"   Retorno Total:        {total_return:>15.2%}")
    print(f"   Retorno Anualizado:   {(1+total_return)**(365/(end_date-start_date).days)-1:>15.2%}")
    
    print(f"\n>> RIESGO")
    print(f"   Volatilidad:          {volatility:>15.2%}")
    print(f"   Max Drawdown:         {max_drawdown:>15.2%}")
    print(f"   Sharpe Ratio:         {sharpe_ratio:>15.2f}")
    print(f"   Calmar Ratio:         {calmar_ratio:>15.2f}")
    
    print(f"\n>> ACTIVIDAD")
    print(f"   Capital Deployado:    {avg_deployed:>15.1f}% (promedio)")
    print(f"   Cash Promedio:        ${avg_cash:>14,.2f}")
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
    print(f"\n>> EVOLUCION DEL PORTAFOLIO")
    print("-" * 95)
    print("Fecha          | Valor           | Pos | Cash            | Deployed | Variación")
    print("-" * 95)
    
    sample_points = df_results.iloc[::max(1, len(df_results)//15)]
    prev_value = initial_capital
    
    for _, row in sample_points.iterrows():
        change = (row['portfolio_value'] - prev_value) / prev_value
        change_str = f"{change:+.2%}" if change != 0 else "-"
        print(f"{row['date'].date()} | ${row['portfolio_value']:>13,.2f} | {row['num_positions']:2} | "
              f"${row['cash']:>13,.2f} | {row['deployed_pct']*100:5.1f}% | {change_str:>8}")
        prev_value = row['portfolio_value']
    
    # Comparación con buy & hold SPY
    print(f"\n>> COMPARACION CON BUY & HOLD S&P 500")
    if 'SPY' in prices.columns:
        spy_start = prices['SPY'].dropna().iloc[0]
        spy_end = prices['SPY'].dropna().iloc[-1]
        spy_return = (spy_end - spy_start) / spy_start
        spy_annual = (1 + spy_return) ** (365 / (end_date - start_date).days) - 1
        
        print(f"   S&P 500 (SPY) Retorno Total:     {spy_return:>10.2%}")
        print(f"   S&P 500 (SPY) Anualizado:        {spy_annual:>10.2%}")
        print(f"   OmniCapital Retorno Total:       {total_return:>10.2%}")
        print(f"   OmniCapital Anualizado:          {(1+total_return)**(365/(end_date-start_date).days)-1:>10.2%}")
        
        outperformance = total_return - spy_return
        print(f"   OUTPERFORMANCE:                  {outperformance:>10.2%}")
    
    # Análisis de scores
    if trades:
        buy_trades = [t for t in trades if 'BUY' in t['action']]
        if buy_trades and 'total_score' in buy_trades[0]:
            avg_total_score = np.mean([t.get('total_score', 0) for t in buy_trades])
            avg_value_score = np.mean([t.get('value_score', 0) for t in buy_trades])
            avg_quality_score = np.mean([t.get('quality_score', 0) for t in buy_trades])
            avg_momentum_score = np.mean([t.get('momentum_score', 0) for t in buy_trades])
            
            print(f"\n>> SCORES PROMEDIO DE ENTRADA")
            print(f"   Total Score:          {avg_total_score:>15.1f}")
            print(f"   Value Score:          {avg_value_score:>15.1f}")
            print(f"   Quality Score:        {avg_quality_score:>15.1f}")
            print(f"   Momentum Score:       {avg_momentum_score:>15.1f}")
    
    # Guardar resultados
    df_results.to_csv('backtests/backtest_v3_consolidated_results.csv', index=False)
    if trades:
        pd.DataFrame(trades).to_csv('backtests/trades_v3_consolidated.csv', index=False)
    
    print(f"\n>> Resultados guardados:")
    print(f"   - backtests/backtest_v3_consolidated_results.csv")
    print(f"   - backtests/trades_v3_consolidated.csv")
    
    return df_results, trades


if __name__ == '__main__':
    # Mayor tiempo posible (máximo datos históricos disponibles)
    # Yahoo Finance típicamente tiene datos desde 1970 para algunos tickers
    # pero para S&P 500 moderno usamos desde 1990 o máximo disponible
    end_date = datetime.now()
    start_date = datetime(1990, 1, 1)  # Máximo histórico disponible
    
    print(f"Ejecutando backtest de máximo período histórico...")
    print(f"Fecha inicio solicitada: {start_date.date()}")
    print(f"Fecha fin: {end_date.date()}")
    print(f"Duración máxima: ~35 años")
    print()
    
    results, trades = run_omnicapital_v3(start_date, end_date)