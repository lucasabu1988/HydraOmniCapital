"""
Identify corrupt stocks in Experiment 41 that caused portfolio explosion
"""
import pandas as pd
import numpy as np

# Load the daily equity curve
df = pd.read_csv('backtests/exp41_corrected_daily.csv', parse_dates=['date'])
df = df.sort_values('date')

# Calculate daily returns
df['daily_return'] = df['value'].pct_change()
df['daily_gain'] = df['value'].diff()

# Show the explosion period
print("=" * 80)
print("IDENTIFYING EXPLOSION EVENT")
print("=" * 80)
print()

# Find massive jumps
df_anomaly = df[df['daily_return'] > 1.0].copy()  # More than 100% daily return
print(f"Days with >100% return: {len(df_anomaly)}")
print()

if len(df_anomaly) > 0:
    print("Top 10 explosive days:")
    print(df_anomaly.nlargest(10, 'daily_return')[['date', 'value', 'daily_return', 'daily_gain']])
    print()

    # Get the first major explosion (sort by index instead of date)
    df_anomaly_sorted = df_anomaly.sort_index()
    first_explosion = df_anomaly_sorted.iloc[0]
    explosion_idx = df_anomaly_sorted.index[0]
    print(f"First explosion date: {first_explosion['date']}")
    print(f"Portfolio value before: ${df.iloc[explosion_idx - 1]['value']:,.2f}")
    print(f"Portfolio value after: ${first_explosion['value']:,.2f}")
    print(f"Daily return: {first_explosion['daily_return']:.2%}")
    print()

# Load trades to find which stocks were active during explosion
trades = pd.read_csv('backtests/exp41_corrected_trades.csv', parse_dates=['entry_date', 'exit_date'])

# Find trades that were open during the explosion period (2014-2015)
trades_2014 = trades[
    (trades['entry_date'] >= '2014-06-01') &
    (trades['entry_date'] <= '2015-04-01')
].copy()

print("=" * 80)
print("TRADES DURING EXPLOSION PERIOD (Jun 2014 - Apr 2015)")
print("=" * 80)
print()

# Calculate absolute PnL per symbol
symbol_pnl = trades_2014.groupby('symbol').agg({
    'pnl': ['sum', 'count', 'mean', 'max', 'min'],
    'return': ['mean', 'max', 'min']
}).reset_index()
symbol_pnl.columns = ['symbol', 'total_pnl', 'trades', 'avg_pnl', 'max_pnl', 'min_pnl',
                       'avg_return', 'max_return', 'min_return']
symbol_pnl = symbol_pnl.sort_values('total_pnl', ascending=False)

print("Top 20 symbols by PnL during explosion period:")
print(symbol_pnl.head(20).to_string(index=False))
print()

# Find trades with extreme returns
extreme_trades = trades_2014[
    (trades_2014['return'].abs() > 1.0)  # >100% return on a single trade
].sort_values('return', ascending=False)

if len(extreme_trades) > 0:
    print("=" * 80)
    print("TRADES WITH EXTREME RETURNS (>100%)")
    print("=" * 80)
    print()
    print(extreme_trades[['symbol', 'entry_date', 'exit_date', 'return', 'pnl']].to_string(index=False))
    print()

    print("Symbols with corrupt data:")
    corrupt_symbols = extreme_trades['symbol'].unique()
    print(", ".join(corrupt_symbols))
    print()
    print(f"Total corrupt symbols found: {len(corrupt_symbols)}")
else:
    print("No extreme returns found in trades. Checking price data directly...")

# Check if the original database has the issue
print()
print("=" * 80)
print("RECOMMENDATION")
print("=" * 80)
print()
print("The filter_anomalous_stocks() function with max_single_day_return=5.0")
print("was not aggressive enough. Recommend using max_single_day_return=1.0")
print("to filter stocks with >100% daily returns (reverse splits, bad data).")
