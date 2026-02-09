import pandas as pd
import numpy as np

# Análisis de trades de v7
v7_trades = pd.read_csv('backtests/trades_v7_hybrid_666.csv')
v6_trades = pd.read_csv('backtests/trades_v6_exact_666.csv')

print('=== ANÁLISIS DE TRADES V7 (HYBRID) ===')
sells_v7 = v7_trades[v7_trades['action'] == 'SELL']
print(f'Total operaciones: {len(sells_v7)}')
win_rate_v7 = (sells_v7['pnl_pct'] > 0).mean()
print(f'Win rate: {win_rate_v7:.2%}')
avg_pnl = sells_v7['pnl_pct'].mean()
print(f'P/L promedio: {avg_pnl:.2%}')

wins_v7 = sells_v7[sells_v7['pnl_pct'] > 0]['pnl_pct']
losses_v7 = sells_v7[sells_v7['pnl_pct'] < 0]['pnl_pct']
print(f'Ganancia promedio: {wins_v7.mean():.2%}')
print(f'Pérdida promedio: {losses_v7.mean():.2%}')

# Análisis por año de v7
v7_results = pd.read_csv('backtests/backtest_v7_hybrid_666_results.csv')
v7_results['date'] = pd.to_datetime(v7_results['date'])
v7_results['year'] = v7_results['date'].dt.year

yearly = v7_results.groupby('year').agg({
    'portfolio_value': ['first', 'last']
}).reset_index()
yearly.columns = ['year', 'start', 'end']
yearly['return'] = (yearly['end'] / yearly['start']) - 1

print(f'\nAños con pérdida: {(yearly["return"] < 0).sum()}')
print(f'Peor año: {yearly.loc[yearly["return"].idxmin(), "year"]} ({yearly["return"].min():.2%})')
print(f'Mejor año: {yearly.loc[yearly["return"].idxmax(), "year"]} ({yearly["return"].max():.2%})')

print('\n=== ANÁLISIS DE TRADES V6 (RANDOM) ===')
sells_v6 = v6_trades[v6_trades['action'] == 'SELL']
print(f'Total operaciones: {len(sells_v6)}')
win_rate_v6 = (sells_v6['pnl_pct'] > 0).mean()
print(f'Win rate: {win_rate_v6:.2%}')
avg_pnl6 = sells_v6['pnl_pct'].mean()
print(f'P/L promedio: {avg_pnl6:.2%}')

wins_v6 = sells_v6[sells_v6['pnl_pct'] > 0]['pnl_pct']
losses_v6 = sells_v6[sells_v6['pnl_pct'] < 0]['pnl_pct']
print(f'Ganancia promedio: {wins_v6.mean():.2%}')
print(f'Pérdida promedio: {losses_v6.mean():.2%}')

print('\n=== COMPARACIÓN ===')
print(f'V7 Hybrid: {len(sells_v7)} ops, {win_rate_v7:.1%} WR, {len(sells_v7)/26:.0f} ops/año, 10 posiciones')
print(f'V6 Random: {len(sells_v6)} ops, {win_rate_v6:.1%} WR, {len(sells_v6)/26:.0f} ops/año, 5 posiciones')

# Análisis de drawdowns
print('\n=== ANÁLISIS DE DRAWDOWNS V7 ===')
v7_results['returns'] = v7_results['portfolio_value'].pct_change()
v7_results['peak'] = v7_results['portfolio_value'].expanding().max()
v7_results['dd'] = (v7_results['portfolio_value'] - v7_results['peak']) / v7_results['peak']

# Encontrar períodos de drawdown significativos
severe_dd = v7_results[v7_results['dd'] < -0.30]
if len(severe_dd) > 0:
    print(f'Días con DD > 30%: {len(severe_dd)}')
    print(f'Períodos severos:')
    for year in [2008, 2009, 2020, 2022]:
        year_data = v7_results[v7_results['year'] == year]
        if len(year_data) > 0:
            min_dd = year_data['dd'].min()
            print(f'  {year}: {min_dd:.2%}')
