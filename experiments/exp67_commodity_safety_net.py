"""EXP67 -- Commodity Safety Net: switch to commodities when HYDRA is flat/negative for 1 month"""
import pandas as pd
import numpy as np
import yfinance as yf
import json, os

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

hydra = pd.read_csv(os.path.join(base_dir, 'backtests/hydra_clean_daily.csv'), parse_dates=['date'])
hydra.set_index('date', inplace=True)
hydra.index = pd.to_datetime(hydra.index).tz_localize(None)
hydra['return'] = hydra['value'].pct_change().fillna(0)

# Rolling 21-day (1 month) return
hydra['rolling_21d'] = hydra['value'].pct_change(21)

# Commodity pool: diversified basket
# DBC (broad commodities), GLD (gold), USO (oil), SLV (silver), DBA (agriculture)
# Before ETFs existed (pre-2006), use futures: GC=F, CL=F, SI=F
COMMODITY_ETFS = ['DBC', 'GLD', 'USO', 'SLV', 'DBA']
COMMODITY_FUTURES = ['GC=F', 'CL=F', 'SI=F', 'HG=F', 'ZC=F']  # gold, oil, silver, copper, corn

HOLD_DAYS = 21  # 1 month in commodities

print("Downloading commodity ETFs...")
comm_data = {}
for ticker in COMMODITY_ETFS + COMMODITY_FUTURES:
    try:
        df = yf.download(ticker, start='1999-12-01', end='2026-03-15', progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[['Close']].dropna()
        df.columns = ['close']
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df['return'] = df['close'].pct_change().fillna(0)
        comm_data[ticker] = df
        print(f"  {ticker}: {df.index[0].date()} to {df.index[-1].date()}")
    except Exception as e:
        print(f"  {ticker}: FAILED - {e}")


def get_commodity_return(date):
    """Equal-weight commodity basket return. Use ETFs if available, else futures."""
    returns = []
    # Try ETFs first
    for t in COMMODITY_ETFS:
        if t in comm_data and date in comm_data[t].index:
            returns.append(comm_data[t].loc[date, 'return'])
    # If no ETF data (pre-2006), use futures
    if not returns:
        for t in COMMODITY_FUTURES:
            if t in comm_data and date in comm_data[t].index:
                returns.append(comm_data[t].loc[date, 'return'])
    return np.mean(returns) if returns else 0


# Build the switching logic
# Rule: if HYDRA 21-day return <= 0, switch to commodities for 21 trading days
# After 21 days, check again. If HYDRA still negative, stay in commodities.
in_commodity = pd.Series(False, index=hydra.index)
commodity_start = None
commodity_days_left = 0
switch_events = []

for i in range(21, len(hydra)):
    date = hydra.index[i]

    if commodity_days_left > 0:
        # Currently in commodity mode
        in_commodity.iloc[i] = True
        commodity_days_left -= 1
        continue

    # Check if HYDRA has been flat/negative for 1 month
    rolling_ret = hydra['rolling_21d'].iloc[i]
    if rolling_ret is not None and rolling_ret <= 0:
        # Switch to commodities for 1 month
        in_commodity.iloc[i] = True
        commodity_days_left = HOLD_DAYS - 1  # -1 because today counts
        switch_events.append({
            'date': str(date.date()),
            'hydra_21d_return': round(rolling_ret * 100, 2),
        })

# Build combined curve
combined = [hydra['value'].iloc[0]]
for i in range(1, len(hydra)):
    d = hydra.index[i]
    if in_commodity.iloc[i]:
        r = get_commodity_return(d)
    else:
        r = hydra['return'].iloc[i]
    combined.append(combined[-1] * (1 + r))

# Metrics
n_years = (hydra.index[-1] - hydra.index[0]).days / 365.25
h_final = hydra['value'].iloc[-1]
c_final = combined[-1]
h_start = hydra['value'].iloc[0]
h_cagr = (h_final / h_start) ** (1 / n_years) - 1
c_cagr = (c_final / h_start) ** (1 / n_years) - 1
cs = pd.Series(combined, index=hydra.index)
h_sharpe = hydra['value'].pct_change().dropna().pipe(lambda x: x.mean() / x.std() * np.sqrt(252))
c_sharpe = cs.pct_change().dropna().pipe(lambda x: x.mean() / x.std() * np.sqrt(252))
h_dd = ((hydra['value'] - hydra['value'].cummax()) / hydra['value'].cummax()).min()
c_dd = ((cs - cs.cummax()) / cs.cummax()).min()

comm_days = in_commodity.sum()
n_switches = len(switch_events)

print()
print("=" * 70)
print("EXP67 -- COMMODITY SAFETY NET")
print("Rule: HYDRA 21d return <= 0 -> switch to commodity basket for 21 days")
print("=" * 70)
print(f"Period: {hydra.index[0].date()} to {hydra.index[-1].date()} ({n_years:.1f} years)")
print(f"Switches to commodities: {n_switches}")
print(f"Days in commodities: {comm_days} / {len(hydra)} ({comm_days / len(hydra) * 100:.1f}%)")
print()
print(f"{'Metric':<25} {'HYDRA Base':>15} {'HYDRA + Comm':>15} {'Delta':>10}")
print("-" * 70)
print(f"{'Final Value':<25} ${h_final:>14,.0f} ${c_final:>14,.0f} ${c_final - h_final:>9,.0f}")
print(f"{'CAGR':<25} {h_cagr * 100:>14.2f}% {c_cagr * 100:>14.2f}% {(c_cagr - h_cagr) * 100:>9.2f}%")
print(f"{'Sharpe':<25} {h_sharpe:>15.3f} {c_sharpe:>15.3f} {c_sharpe - h_sharpe:>10.3f}")
print(f"{'Max Drawdown':<25} {h_dd * 100:>14.2f}% {c_dd * 100:>14.2f}% {(c_dd - h_dd) * 100:>9.2f}%")
print(f"{'Total Return':<25} {(h_final / h_start - 1) * 100:>13.1f}% {(c_final / h_start - 1) * 100:>14.1f}%")

# Show yearly breakdown
print(f"\nYearly Switches:")
yearly = {}
for e in switch_events:
    y = e['date'][:4]
    yearly[y] = yearly.get(y, 0) + 1
for y in sorted(yearly):
    print(f"  {y}: {yearly[y]} switches")

# Show first/last 10 switch events
print(f"\nFirst 10 switches:")
for e in switch_events[:10]:
    print(f"  {e['date']}  HYDRA 21d: {e['hydra_21d_return']}%")
if len(switch_events) > 10:
    print(f"\nLast 10 switches:")
    for e in switch_events[-10:]:
        print(f"  {e['date']}  HYDRA 21d: {e['hydra_21d_return']}%")

bt_dir = os.path.join(base_dir, 'backtests')
pd.DataFrame({
    'date': hydra.index,
    'hydra_value': hydra['value'].values,
    'combined_value': combined,
    'in_commodity': in_commodity.values,
}).to_csv(os.path.join(bt_dir, 'exp67_commodity_safety_daily.csv'), index=False)

with open(os.path.join(bt_dir, 'exp67_commodity_safety_summary.json'), 'w') as f:
    json.dump({
        'experiment': 'EXP67 -- Commodity Safety Net',
        'rule': 'HYDRA 21d return <= 0 -> commodity basket 21 days',
        'hydra': {'cagr': round(h_cagr * 100, 2), 'sharpe': round(h_sharpe, 3), 'max_dd': round(h_dd * 100, 2), 'final': round(h_final, 2)},
        'combined': {'cagr': round(c_cagr * 100, 2), 'sharpe': round(c_sharpe, 3), 'max_dd': round(c_dd * 100, 2), 'final': round(c_final, 2)},
        'n_switches': n_switches,
        'pct_in_commodities': round(comm_days / len(hydra) * 100, 1),
        'yearly_switches': yearly,
    }, f, indent=2)
print("\nSaved.")
