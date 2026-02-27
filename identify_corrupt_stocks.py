"""
Script to identify stocks with corrupt/anomalous price data
"""
import pandas as pd
import numpy as np
import pickle

print("Loading expanded pool data...")
with open('data_cache/survivorship_bias_pool.pkl', 'rb') as f:
    data = pickle.load(f)

print(f"Loaded {len(data)} stocks")

# Check for anomalies in 2011 (when the explosion happened)
target_period_start = pd.Timestamp('2011-01-01')
target_period_end = pd.Timestamp('2011-12-31')

print(f"\nAnalyzing stocks for anomalies in {target_period_start.year}...")
print("=" * 80)

anomalous_stocks = []

for symbol, df in data.items():
    try:
        # Filter to 2011
        mask = (df.index >= target_period_start) & (df.index <= target_period_end)
        df_2011 = df.loc[mask]

        if len(df_2011) < 10:
            continue

        # Check for extreme price changes
        returns = df_2011['Close'].pct_change().dropna()

        if len(returns) == 0:
            continue

        # Flag stocks with:
        # 1. Single-day returns > 1000%
        # 2. Volatility > 500% annualized
        # 3. Price jumps > 10000%

        max_single_day_return = returns.max()
        min_single_day_return = returns.min()
        volatility = returns.std() * np.sqrt(252)

        max_price = df_2011['Close'].max()
        min_price = df_2011['Close'].min()
        price_range_ratio = max_price / min_price if min_price > 0 else 0

        is_anomalous = False
        reasons = []

        if max_single_day_return > 10:  # 1000%+
            is_anomalous = True
            reasons.append(f"Single-day gain: {max_single_day_return*100:.0f}%")

        if min_single_day_return < -0.95:  # -95%+
            is_anomalous = True
            reasons.append(f"Single-day loss: {min_single_day_return*100:.0f}%")

        if volatility > 5:  # 500%+ annualized
            is_anomalous = True
            reasons.append(f"Volatility: {volatility*100:.0f}%")

        if price_range_ratio > 100:  # 100x price variation
            is_anomalous = True
            reasons.append(f"Price range: {price_range_ratio:.0f}x")

        if is_anomalous:
            anomalous_stocks.append({
                'symbol': symbol,
                'reasons': ', '.join(reasons),
                'max_single_day': f"{max_single_day_return*100:.1f}%",
                'volatility': f"{volatility*100:.0f}%",
                'price_range': f"{price_range_ratio:.1f}x",
                'data_points': len(df_2011),
                'first_date': df_2011.index[0],
                'last_date': df_2011.index[-1],
                'first_price': df_2011['Close'].iloc[0],
                'last_price': df_2011['Close'].iloc[-1]
            })

    except Exception as e:
        print(f"Error analyzing {symbol}: {e}")
        continue

# Sort by most anomalous
anomalous_stocks.sort(key=lambda x: float(x['max_single_day'].replace('%', '')), reverse=True)

print(f"\nFound {len(anomalous_stocks)} anomalous stocks in 2011:\n")
print(f"{'Symbol':<10} {'Max Single Day':<15} {'Volatility':<15} {'Price Range':<15} {'Reasons'}")
print("=" * 80)

for stock in anomalous_stocks[:20]:  # Show top 20
    print(f"{stock['symbol']:<10} {stock['max_single_day']:<15} {stock['volatility']:<15} {stock['price_range']:<15} {stock['reasons'][:40]}")

# Save full list
df_anomalous = pd.DataFrame(anomalous_stocks)
df_anomalous.to_csv('backtests/anomalous_stocks_2011.csv', index=False)

print(f"\n[SAVED] Full list saved to backtests/anomalous_stocks_2011.csv")

# Also check the broader period
print("\n" + "=" * 80)
print("Checking for anomalies across entire dataset (2000-2026)...")
print("=" * 80)

all_anomalous = []

for symbol, df in data.items():
    try:
        if len(df) < 100:
            continue

        returns = df['Close'].pct_change().dropna()

        if len(returns) == 0:
            continue

        max_single_day_return = returns.max()

        if max_single_day_return > 5:  # 500%+
            all_anomalous.append({
                'symbol': symbol,
                'max_single_day': f"{max_single_day_return*100:.1f}%",
                'date': returns.idxmax(),
                'price_before': df['Close'].loc[returns.idxmax()] / (1 + max_single_day_return),
                'price_after': df['Close'].loc[returns.idxmax()]
            })

    except Exception:
        continue

all_anomalous.sort(key=lambda x: float(x['max_single_day'].replace('%', '')), reverse=True)

print(f"\nFound {len(all_anomalous)} stocks with extreme single-day gains (>500%):\n")
print(f"{'Symbol':<10} {'Max Day Gain':<15} {'Date':<12} {'Price Before':<15} {'Price After'}")
print("=" * 80)

for stock in all_anomalous[:30]:
    print(f"{stock['symbol']:<10} {stock['max_single_day']:<15} {str(stock['date'])[:10]:<12} ${stock['price_before']:<14.2f} ${stock['price_after']:.2f}")

print("\n" + "=" * 80)
print("RECOMMENDATION:")
print("=" * 80)
print("Remove or filter these stocks before running backtest:")
print(f"  - {len(anomalous_stocks)} stocks with 2011 anomalies")
print(f"  - {len(all_anomalous)} stocks with extreme single-day gains")
print("\nThese are likely:")
print("  1. Delisted stocks with unadjusted reverse splits")
print("  2. Corporate actions not properly adjusted by data provider")
print("  3. Data corruption from yfinance")
