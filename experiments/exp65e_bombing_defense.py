"""EXP65e -- US Bombing -> Top 5 Defense Stocks Backtest"""
import pandas as pd
import numpy as np
import yfinance as yf
import json, os

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

hydra = pd.read_csv(os.path.join(base_dir, 'backtests/hydra_clean_daily.csv'), parse_dates=['date'])
hydra.set_index('date', inplace=True)
hydra.index = pd.to_datetime(hydra.index).tz_localize(None)
hydra['return'] = hydra['value'].pct_change().fillna(0)

# Top 5 defense by market cap per era
DEFENSE_BY_ERA = {
    2001: ['LMT', 'BA', 'NOC', 'GD', 'LHX'],
    2003: ['LMT', 'BA', 'NOC', 'GD', 'LHX'],
    2008: ['LMT', 'BA', 'NOC', 'GD', 'LHX'],
    2011: ['LMT', 'BA', 'NOC', 'GD', 'LHX'],
    2014: ['LMT', 'BA', 'NOC', 'GD', 'LHX'],
    2017: ['LMT', 'BA', 'NOC', 'GD', 'LHX'],
    2018: ['LMT', 'BA', 'NOC', 'GD', 'LHX'],
    2020: ['LMT', 'RTX', 'NOC', 'GD', 'BA'],
    2021: ['LMT', 'RTX', 'NOC', 'GD', 'BA'],
    2024: ['LMT', 'RTX', 'NOC', 'GD', 'BA'],
}

BOMBING_EVENTS = [
    {'date': '2001-10-07', 'target': 'Afghanistan', 'year': 2001},
    {'date': '2003-03-20', 'target': 'Iraq', 'year': 2003},
    {'date': '2008-01-29', 'target': 'Pakistan', 'year': 2008},
    {'date': '2011-03-19', 'target': 'Libya', 'year': 2011},
    {'date': '2014-09-23', 'target': 'Syria/Iraq', 'year': 2014},
    {'date': '2017-04-07', 'target': 'Syria', 'year': 2017},
    {'date': '2018-04-14', 'target': 'Syria', 'year': 2018},
    {'date': '2020-01-03', 'target': 'Iraq', 'year': 2020},
    {'date': '2021-02-25', 'target': 'Syria', 'year': 2021},
    {'date': '2021-08-29', 'target': 'Afghanistan', 'year': 2021},
    {'date': '2024-01-12', 'target': 'Yemen', 'year': 2024},
    {'date': '2024-02-03', 'target': 'Yemen/Iraq/Syria', 'year': 2024},
]
HOLD_DAYS = 42

# Download all defense tickers
all_tickers = sorted(set(t for stocks in DEFENSE_BY_ERA.values() for t in stocks))
print(f"Downloading {len(all_tickers)} defense stocks: {all_tickers}")
defense_data = {}
for ticker in all_tickers:
    try:
        df = yf.download(ticker, start='1999-12-01', end='2026-03-15', progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[['Close']].dropna()
        df.columns = ['close']
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df['return'] = df['close'].pct_change().fillna(0)
        defense_data[ticker] = df
        print(f"  {ticker}: {df.index[0].date()} to {df.index[-1].date()}")
    except Exception as e:
        print(f"  {ticker}: FAILED - {e}")


def get_defense_return(date, year):
    stocks = DEFENSE_BY_ERA.get(year, DEFENSE_BY_ERA[2024])
    returns = []
    for t in stocks:
        if t in defense_data and date in defense_data[t].index:
            returns.append(defense_data[t].loc[date, 'return'])
    return np.mean(returns) if returns else 0


# Build defense mode mask
in_defense = pd.Series(False, index=hydra.index)
active_year = pd.Series(0, index=hydra.index)

for event in BOMBING_EVENTS:
    start = pd.Timestamp(event['date'])
    valid = hydra.index[hydra.index >= start]
    if len(valid) == 0:
        continue
    si = hydra.index.get_loc(valid[0])
    ei = min(si + HOLD_DAYS, len(hydra) - 1)
    in_defense[hydra.index[si:ei + 1]] = True
    active_year[hydra.index[si:ei + 1]] = event['year']

# Build combined curve
combined = [hydra['value'].iloc[0]]
for i in range(1, len(hydra)):
    d = hydra.index[i]
    if in_defense.iloc[i]:
        r = get_defense_return(d, active_year.iloc[i])
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

print()
print("=" * 70)
print("EXP65e -- US BOMBING -> TOP 5 DEFENSE STOCKS BACKTEST")
print("=" * 70)
print(f"Period: {hydra.index[0].date()} to {hydra.index[-1].date()} ({n_years:.1f} years)")
print(f"Days in defense: {in_defense.sum()} / {len(hydra)} ({in_defense.sum() / len(hydra) * 100:.1f}%)")
print()
print(f"{'Metric':<25} {'HYDRA Base':>15} {'HYDRA + Def':>15} {'Delta':>10}")
print("-" * 70)
print(f"{'Final Value':<25} ${h_final:>14,.0f} ${c_final:>14,.0f} ${c_final - h_final:>9,.0f}")
print(f"{'CAGR':<25} {h_cagr * 100:>14.2f}% {c_cagr * 100:>14.2f}% {(c_cagr - h_cagr) * 100:>9.2f}%")
print(f"{'Sharpe':<25} {h_sharpe:>15.3f} {c_sharpe:>15.3f} {c_sharpe - h_sharpe:>10.3f}")
print(f"{'Max Drawdown':<25} {h_dd * 100:>14.2f}% {c_dd * 100:>14.2f}% {(c_dd - h_dd) * 100:>9.2f}%")

print(f"\nEvent-by-Event:")
print(f"{'Date':<12} {'Target':<15} {'Stocks':<25} {'Def Ret':>9} {'HYDRA':>9} {'Delta':>9}")
print("-" * 80)
wins = 0
events_out = []
for event in BOMBING_EVENTS:
    start = pd.Timestamp(event['date'])
    valid = hydra.index[hydra.index >= start]
    if len(valid) == 0:
        continue
    si = hydra.index.get_loc(valid[0])
    ei = min(si + HOLD_DAYS, len(hydra) - 1)
    period = hydra.index[si:ei + 1]
    stocks = DEFENSE_BY_ERA.get(event['year'], DEFENSE_BY_ERA[2024])
    dr = [get_defense_return(d, event['year']) for d in period]
    def_ret = np.prod([1 + r for r in dr]) - 1
    hydra_ret = hydra['value'].iloc[ei] / hydra['value'].iloc[si] - 1
    delta = def_ret - hydra_ret
    if delta > 0:
        wins += 1
    stocks_str = ','.join(stocks)
    print(f"{event['date']:<12} {event['target']:<15} {stocks_str:<25} {def_ret * 100:>8.2f}% {hydra_ret * 100:>8.2f}% {delta * 100:>8.2f}%")
    events_out.append({
        'date': event['date'], 'target': event['target'], 'stocks': stocks,
        'defense_return': round(def_ret * 100, 2),
        'hydra_return': round(hydra_ret * 100, 2),
        'delta': round(delta * 100, 2),
    })

print(f"\nDefense wins: {wins}/{len(events_out)} ({wins / len(events_out) * 100:.0f}%)")

bt_dir = os.path.join(base_dir, 'backtests')
pd.DataFrame({'date': hydra.index, 'hydra_value': hydra['value'].values, 'combined_value': combined}).to_csv(
    os.path.join(bt_dir, 'exp65e_bombing_defense_daily.csv'), index=False)
with open(os.path.join(bt_dir, 'exp65e_bombing_defense_summary.json'), 'w') as f:
    json.dump({
        'experiment': 'EXP65e -- US Bombing -> Top 5 Defense Stocks',
        'hydra': {'cagr': round(h_cagr * 100, 2), 'sharpe': round(h_sharpe, 3), 'max_dd': round(h_dd * 100, 2), 'final': round(h_final, 2)},
        'combined': {'cagr': round(c_cagr * 100, 2), 'sharpe': round(c_sharpe, 3), 'max_dd': round(c_dd * 100, 2), 'final': round(c_final, 2)},
        'events': events_out,
    }, f, indent=2)
print("Saved.")
