"""
AlphaMax OmniCapital v2.0
Multi-Strategy Investment Algorithm

Copyright (c) 2026 Investment Capital Firm
All Rights Reserved.

Official Release: OmniCapital v2.0
Strategy: Multi-Strategy Ensemble with Regime Detection
Universe: 40 Blue-Chip S&P 500 Equities

Author: Investment Capital Firm
Version: 2.0.0
Date: February 2026

Nuevas Características v2.0:
- Ensemble de múltiples estrategias cuantitativas
- Detección automática de régimen de mercado
- Risk Parity y Minimum Variance
- Factor Investing (Value, Quality, Momentum, Low Vol)
- Trend Following (Turtle, Donchian)
- Mean Reversion (Bollinger + RSI)
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

# Importar nuevas estrategias
try:
    from src.strategies.momentum import DualMomentumStrategy, RelativeStrengthStrategy
    from src.strategies.factor import FactorInvestingStrategy, QualityFactorStrategy
    from src.strategies.risk_parity import RiskParityStrategy, MinimumVarianceStrategy, InverseVolatilityStrategy
    from src.strategies.mean_reversion import MeanReversionStrategy
    from src.strategies.trend_following import TurtleStrategy, DonchianStrategy, MovingAverageTrendStrategy
    from src.strategies.multi_strategy_engine import MultiStrategyEngine
    STRATEGIES_AVAILABLE = True
except ImportError as e:
    print(f"Warning: No se pudieron importar estrategias avanzadas: {e}")
    STRATEGIES_AVAILABLE = False


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


def detect_market_regime(prices_df, benchmark='SPY'):
    """
    Detecta el régimen actual del mercado.
    
    Returns:
        str: 'bull', 'bear', 'range', 'volatile'
    """
    if benchmark not in prices_df.columns:
        benchmark = prices_df.columns[0]
    
    benchmark_prices = prices_df[benchmark].dropna()
    
    if len(benchmark_prices) < 50:
        return 'unknown'
    
    # Calcular métricas
    returns = benchmark_prices.pct_change().dropna()
    
    # Tendencia
    sma_50 = benchmark_prices.tail(50).mean()
    sma_200 = benchmark_prices.tail(200).mean() if len(benchmark_prices) >= 200 else sma_50
    
    # Volatilidad
    vol = returns.tail(50).std() * np.sqrt(252)
    
    # Momentum (3 meses)
    momentum = (benchmark_prices.iloc[-1] / benchmark_prices.iloc[-min(63, len(benchmark_prices))]) - 1
    
    # Clasificar
    if momentum > 0.05 and sma_50 > sma_200 and vol < 0.20:
        return 'bull'
    elif momentum < -0.05 and sma_50 < sma_200:
        return 'bear'
    elif vol > 0.25:
        return 'volatile'
    else:
        return 'range'


def run_omnicapital_v2(start_date, end_date, initial_capital=1000000, use_multi_strategy=True):
    """
    Backtest usando estrategias múltiples avanzadas.
    """
    print("=" * 95)
    print("ALPHAMAX OMNICAPITAL v2.0")
    print("Multi-Strategy Ensemble Investment Algorithm")
    print("=" * 95)
    print(f"Periodo: {start_date.date()} a {end_date.date()}")
    print(f"Capital Inicial: ${initial_capital:,.2f}")
    print(f"Estrategia: Multi-Strategy Ensemble | Regime Detection | Risk Management")
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
    
    # Inicializar motor multi-estrategia si está disponible
    multi_engine = None
    if use_multi_strategy and STRATEGIES_AVAILABLE:
        print("\nInicializando motor multi-estrategia...")
        multi_engine = MultiStrategyEngine({
            'ensemble_method': 'regime_based',
            'rebalance_frequency': 'monthly'
        })
        
        # Añadir estrategias
        multi_engine.add_strategy('dual_momentum', DualMomentumStrategy({
            'lookback_months': 12,
            'top_n': 10,
            'name': 'DualMomentum'
        }), weight=1.0)
        
        multi_engine.add_strategy('relative_strength', RelativeStrengthStrategy({
            'lookback_months': [3, 6, 12],
            'weights': [0.4, 0.3, 0.3],
            'top_n': 15,
            'name': 'RelativeStrength'
        }), weight=1.0)
        
        multi_engine.add_strategy('factor_investing', FactorInvestingStrategy({
            'factor_weights': {'value': 0.25, 'quality': 0.25, 'momentum': 0.25, 'low_vol': 0.15, 'size': 0.10},
            'top_n': 20,
            'name': 'FactorInvesting'
        }), weight=1.2)
        
        multi_engine.add_strategy('risk_parity', RiskParityStrategy({
            'vol_target': 0.10,
            'max_weight': 0.15,
            'name': 'RiskParity'
        }), weight=1.0)
        
        multi_engine.add_strategy('minimum_variance', MinimumVarianceStrategy({
            'long_only': True,
            'max_weight': 0.20,
            'name': 'MinVariance'
        }), weight=0.9)
        
        multi_engine.add_strategy('turtle', TurtleStrategy({
            'entry_period': 20,
            'exit_period': 10,
            'name': 'TurtleTrading'
        }), weight=0.8)
        
        multi_engine.add_strategy('donchian', DonchianStrategy({
            'channel_period': 20,
            'name': 'DonchianChannels'
        }), weight=0.8)
        
        multi_engine.add_strategy('mean_reversion', MeanReversionStrategy({
            'bb_period': 20,
            'rsi_period': 14,
            'name': 'MeanReversion'
        }), weight=0.6)
        
        print(f"Estrategias cargadas: {list(multi_engine.strategies.keys())}")
    
    # Portafolio
    cash = initial_capital
    positions = {}
    portfolio_values = []
    trades = []
    regime_history = []
    
    # Rebalanceo semanal
    available_dates = prices.index
    rebalance_dates = pd.date_range(start=available_dates[0], end=available_dates[-1], freq='W-FRI')
    
    print("\n" + "=" * 95)
    print("EJECUTANDO BACKTEST - MULTI-STRATEGY ENSEMBLE")
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
        
        # Detectar régimen de mercado
        prices_up_to_date = prices.loc[:current_date]
        current_regime = detect_market_regime(prices_up_to_date)
        regime_history.append({'date': current_date, 'regime': current_regime})
        
        portfolio_values.append({
            'date': current_date,
            'portfolio_value': portfolio_value,
            'cash': cash,
            'num_positions': len(positions),
            'deployed_pct': (portfolio_value - cash) / portfolio_value if portfolio_value > 0 else 0,
            'regime': current_regime
        })
        
        if i % 13 == 0:
            deployed = (portfolio_value - cash) / portfolio_value * 100 if portfolio_value > 0 else 0
            print(f"[{current_date.date()}] Valor: ${portfolio_value:>12,.2f} | "
                  f"Pos: {len(positions):2} | Deployed: {deployed:5.1f}% | Regime: {current_regime}")
        
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
                proceeds = pos['shares'] * current_price * 0.999
                cash += proceeds
                trades.append({
                    'date': current_date, 'symbol': symbol, 'action': 'SELL_ALL',
                    'shares': pos['shares'], 'price': current_price, 'reason': 'TP_50%'
                })
                del positions[symbol]
        
        # === GENERAR SEÑALES CON MULTI-STRATEGY ===
        if multi_engine and i % 4 == 0:  # Rebalanceo mensual aproximado
            try:
                # Obtener datos históricos para las estrategias
                lookback = min(252, closest_idx)
                hist_prices = prices.iloc[max(0, closest_idx-lookback):closest_idx+1]
                
                # Generar señales compuestas
                composite_signals = multi_engine.generate_composite_signals(
                    hist_prices,
                    fundamentals,
                    current_regime
                )
                
                # Procesar señales
                target_cash_pct = 0.05
                target_cash = portfolio_value * target_cash_pct
                excess_cash = cash - target_cash
                
                buy_signals = [s for s in composite_signals if s.action == 'BUY']
                
                # Ordenar por strength
                buy_signals.sort(key=lambda x: x.strength, reverse=True)
                
                for signal in buy_signals[:10]:  # Máximo 10 nuevas posiciones
                    symbol = signal.symbol
                    
                    if symbol in positions or symbol not in prices.columns:
                        continue
                    
                    if cash <= target_cash or len(positions) >= 40:
                        break
                    
                    current_price = prices.loc[current_date, symbol]
                    if pd.isna(current_price) or current_price <= 0:
                        continue
                    
                    # Verificar sector
                    sector = fundamentals.get(symbol, {}).get('sector', 'Unknown')
                    sector_count = sum(1 for p in positions.values() if p.get('sector') == sector)
                    if sector_count >= 5:
                        continue
                    
                    # Calcular tamaño basado en confidence de la señal
                    base_position = excess_cash * 0.15  # 15% del exceso de cash
                    position_value = base_position * signal.strength
                    position_value = min(position_value, cash * 0.95)
                    
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
                                    'tp_35_done': False,
                                    'strategy_signals': signal.metadata.get('contributing_strategies', [])
                                }
                                trades.append({
                                    'date': current_date, 'symbol': symbol, 'action': 'BUY',
                                    'shares': shares, 'price': current_price,
                                    'score': signal.strength,
                                    'strategies': signal.metadata.get('contributing_strategies', [])
                                })
            except Exception as e:
                print(f"Error en multi-strategy: {e}")
        
        # === FALLBACK: Compras de valoración si hay mucho cash ===
        cash_pct = cash / portfolio_value if portfolio_value > 0 else 1
        if cash_pct > 0.30 and len(positions) < 20:
            # Calcular scores de valoración
            value_scores = {}
            for symbol in prices.columns:
                if symbol in positions or symbol not in fundamentals:
                    continue
                f = fundamentals[symbol]
                score = calculate_value_score(
                    f.get('pe_ratio'),
                    f.get('pb_ratio'),
                    f.get('ps_ratio'),
                    f.get('ev_ebitda'),
                    f.get('roe')
                )
                value_scores[symbol] = {'score': score, 'sector': f.get('sector', 'Unknown')}
            
            # Comprar top valoración
            sorted_values = sorted(value_scores.items(), key=lambda x: x[1]['score'], reverse=True)
            for symbol, data in sorted_values[:10]:
                if cash <= target_cash or len(positions) >= 40:
                    break
                
                current_price = prices.loc[current_date, symbol]
                if pd.isna(current_price):
                    continue
                
                position_value = min(cash * 0.08, 15000)
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
                            'date': current_date, 'symbol': symbol, 'action': 'BUY_FALLBACK',
                            'shares': shares, 'price': current_price,
                            'score': data['score']
                        })
    
    # === RESULTADOS ===
    print("\n" + "=" * 95)
    print("OMNICAPITAL v2.0 - RESULTADOS OFICIALES")
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
    
    # Distribución de regímenes
    regime_counts = df_results['regime'].value_counts()
    
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
    print(f"   Total Trades:         {len(trades):>15}")
    
    print(f"\n>> RÉGIMENES DE MERCADO")
    for regime, count in regime_counts.items():
        pct = count / len(df_results) * 100
        print(f"   {regime.capitalize():12}          {pct:>14.1f}%")
    
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
    print("Fecha          | Valor           | Pos | Deployed | Regime    | Variación")
    print("-" * 95)
    
    sample_points = df_results.iloc[::max(1, len(df_results)//15)]
    prev_value = initial_capital
    
    for _, row in sample_points.iterrows():
        change = (row['portfolio_value'] - prev_value) / prev_value
        change_str = f"{change:+.2%}" if change != 0 else "-"
        print(f"{row['date'].date()} | ${row['portfolio_value']:>13,.2f} | {row['num_positions']:2} | "
              f"{row['deployed_pct']*100:5.1f}% | {row['regime']:9} | {change_str:>8}")
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
    
    # Guardar resultados
    df_results.to_csv('backtests/backtest_v2_multistrategy_results.csv', index=False)
    if trades:
        pd.DataFrame(trades).to_csv('backtests/trades_v2_multistrategy.csv', index=False)
    
    # Guardar historial de regímenes
    pd.DataFrame(regime_history).to_csv('backtests/regime_history.csv', index=False)
    
    print(f"\n>> Resultados guardados:")
    print(f"   - backtests/backtest_v2_multistrategy_results.csv")
    print(f"   - backtests/trades_v2_multistrategy.csv")
    print(f"   - backtests/regime_history.csv")
    
    return df_results, trades


if __name__ == '__main__':
    # Período de 10 años
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365*10)
    
    results, trades = run_omnicapital_v2(start_date, end_date)