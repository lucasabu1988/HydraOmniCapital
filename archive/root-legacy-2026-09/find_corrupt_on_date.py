"""
Find which stocks had corrupt price data on 2011-01-04
"""
import sqlite3
import pandas as pd
from datetime import datetime, timedelta

# Connect to database
conn = sqlite3.connect('stock_data.db')

# Get the date range around the explosion
check_date = '2011-01-04'
prev_date = '2011-01-03'

print("=" * 80)
print(f"CHECKING PRICE DATA ON {check_date}")
print("=" * 80)
print()

# Query all stocks that had data on both dates
query = """
SELECT
    symbol,
    date,
    close,
    LAG(close) OVER (PARTITION BY symbol ORDER BY date) as prev_close,
    (close / LAG(close) OVER (PARTITION BY symbol ORDER BY date) - 1) * 100 as pct_change
FROM stock_prices
WHERE date BETWEEN '2010-12-31' AND '2011-01-06'
ORDER BY symbol, date
"""

df = pd.read_sql_query(query, conn)

# Filter to just the explosive date
df_explosive = df[df['date'] == check_date].copy()
df_explosive = df_explosive[df_explosive['prev_close'].notna()]
df_explosive = df_explosive[df_explosive['pct_change'].abs() > 100]  # More than 100% change

print(f"Stocks with >100% price change on {check_date}:")
print()

if len(df_explosive) > 0:
    df_explosive_sorted = df_explosive.sort_values('pct_change', ascending=False)
    print(df_explosive_sorted[['symbol', 'prev_close', 'close', 'pct_change']].to_string(index=False))
    print()
    print(f"Total corrupt stocks: {len(df_explosive)}")
    print()
    print("Corrupt symbols:")
    corrupt_symbols = df_explosive['symbol'].tolist()
    print(", ".join(corrupt_symbols))
else:
    print("No stocks with >100% change found.")
    print()
    print("Checking for any large moves (>50%):")
    df_large = df[df['date'] == check_date].copy()
    df_large = df_large[df_large['prev_close'].notna()]
    df_large = df_large[df_large['pct_change'].abs() > 50]

    if len(df_large) > 0:
        df_large_sorted = df_large.sort_values('pct_change', ascending=False)
        print(df_large_sorted[['symbol', 'prev_close', 'close', 'pct_change']].head(10).to_string(index=False))

conn.close()

print()
print("=" * 80)
print("RECOMMENDATION")
print("=" * 80)
print()
print("Add these symbols to the corrupt stocks list and re-run the backtest.")
