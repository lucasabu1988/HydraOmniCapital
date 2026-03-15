"""EXP66 -- Major Disasters -> Construction/Steel Stocks (1 year hold)"""
import pandas as pd
import numpy as np
import yfinance as yf
import json, os

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

hydra = pd.read_csv(os.path.join(base_dir, 'backtests/hydra_clean_daily.csv'), parse_dates=['date'])
hydra.set_index('date', inplace=True)
hydra.index = pd.to_datetime(hydra.index).tz_localize(None)
hydra['return'] = hydra['value'].pct_change().fillna(0)

# Major world disasters 2000-2025 (natural + man-made, massive reconstruction)
DISASTERS = [
    {'date': '2001-09-11', 'event': '9/11 World Trade Center', 'location': 'USA'},
    {'date': '2004-12-26', 'event': 'Indian Ocean Tsunami', 'location': 'SE Asia'},
    {'date': '2005-08-29', 'event': 'Hurricane Katrina', 'location': 'USA'},
    {'date': '2008-05-12', 'event': 'Sichuan Earthquake 8.0', 'location': 'China'},
    {'date': '2010-01-12', 'event': 'Haiti Earthquake 7.0', 'location': 'Haiti'},
    {'date': '2010-04-20', 'event': 'Deepwater Horizon Oil Spill', 'location': 'USA'},
    {'date': '2011-03-11', 'event': 'Tohoku Earthquake + Fukushima', 'location': 'Japan'},
    {'date': '2015-04-25', 'event': 'Nepal Earthquake 7.8', 'location': 'Nepal'},
    {'date': '2017-08-25', 'event': 'Hurricane Harvey', 'location': 'USA'},
    {'date': '2017-09-20', 'event': 'Hurricane Maria', 'location': 'Puerto Rico'},
    {'date': '2018-09-28', 'event': 'Sulawesi Earthquake + Tsunami', 'location': 'Indonesia'},
    {'date': '2020-08-04', 'event': 'Beirut Port Explosion', 'location': 'Lebanon'},
    {'date': '2021-08-14', 'event': 'Haiti Earthquake 7.2', 'location': 'Haiti'},
    {'date': '2023-02-06', 'event': 'Turkey-Syria Earthquake 7.8', 'location': 'Turkey/Syria'},
    {'date': '2024-01-01', 'event': 'Noto Earthquake 7.6', 'location': 'Japan'},
]

HOLD_DAYS = 252  # ~1 year of trading days

# Top cement & steel/iron companies (global, US-listed)
# Cement: VMC (Vulcan Materials), MLM (Martin Marietta), CX (Cemex), EXP (Eagle Materials)
# Steel/Iron: NUE (Nucor), STLD (Steel Dynamics), X (US Steel), CLF (Cleveland-Cliffs), MT (ArcelorMittal)
CONSTRUCTION_STOCKS = {
    'early': ['VMC', 'MLM', 'NUE', 'X', 'CX'],        # 2000-2010
    'mid':   ['VMC', 'MLM', 'NUE', 'STLD', 'CX'],     # 2010-2018
    'late':  ['VMC', 'MLM', 'NUE', 'STLD', 'CLF'],     # 2018-2026
}

def get_stocks_for_year(year):
    if year < 2010:
        return CONSTRUCTION_STOCKS['early']
    elif year < 2018:
        return CONSTRUCTION_STOCKS['mid']
    else:
        return CONSTRUCTION_STOCKS['late']

# Download all tickers
all_tickers = sorted(set(t for stocks in CONSTRUCTION_STOCKS.values() for t in stocks))
print(f"Downloading {len(all_tickers)} construction/steel stocks: {all_tickers}")
stock_data = {}
for ticker in all_tickers:
    try:
        df = yf.download(ticker, start='1999-12-01', end='2026-03-15', progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[['Close']].dropna()
        df.columns = ['close']
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df['return'] = df['close'].pct_change().fillna(0)
        stock_data[ticker] = df
        print(f"  {ticker}: {df.index[0].date()} to {df.index[-1].date()}")
    except Exception as e:
        print(f"  {ticker}: FAILED - {e}")


def get_construction_return(date, year):
    stocks = get_stocks_for_year(year)
    returns = []
    for t in stocks:
        if t in stock_data and date in stock_data[t].index:
            returns.append(stock_data[t].loc[date, 'return'])
    return np.mean(returns) if returns else 0


# Build construction mode mask
in_construction = pd.Series(False, index=hydra.index)
active_year = pd.Series(0, index=hydra.index)

for event in DISASTERS:
    start = pd.Timestamp(event['date'])
    valid = hydra.index[hydra.index >= start]
    if len(valid) == 0:
        continue
    si = hydra.index.get_loc(valid[0])
    ei = min(si + HOLD_DAYS, len(hydra) - 1)
    in_construction[hydra.index[si:ei + 1]] = True
    active_year[hydra.index[si:ei + 1]] = pd.Timestamp(event['date']).year

# Build combined curve
combined = [hydra['value'].iloc[0]]
for i in range(1, len(hydra)):
    d = hydra.index[i]
    if in_construction.iloc[i]:
        r = get_construction_return(d, active_year.iloc[i])
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

constr_days = in_construction.sum()

print()
print("=" * 70)
print("EXP66 -- DISASTERS -> CEMENT + STEEL STOCKS (1 YEAR HOLD)")
print("=" * 70)
print(f"Period: {hydra.index[0].date()} to {hydra.index[-1].date()} ({n_years:.1f} years)")
print(f"Disaster events: {len(DISASTERS)}")
print(f"Days in construction: {constr_days} / {len(hydra)} ({constr_days / len(hydra) * 100:.1f}%)")
print()
print(f"{'Metric':<25} {'HYDRA Base':>15} {'HYDRA + Constr':>15} {'Delta':>10}")
print("-" * 70)
print(f"{'Final Value':<25} ${h_final:>14,.0f} ${c_final:>14,.0f} ${c_final - h_final:>9,.0f}")
print(f"{'CAGR':<25} {h_cagr * 100:>14.2f}% {c_cagr * 100:>14.2f}% {(c_cagr - h_cagr) * 100:>9.2f}%")
print(f"{'Sharpe':<25} {h_sharpe:>15.3f} {c_sharpe:>15.3f} {c_sharpe - h_sharpe:>10.3f}")
print(f"{'Max Drawdown':<25} {h_dd * 100:>14.2f}% {c_dd * 100:>14.2f}% {(c_dd - h_dd) * 100:>9.2f}%")

print(f"\nEvent-by-Event (1 year hold):")
print(f"{'Date':<12} {'Event':<30} {'Stocks':<22} {'Constr':>8} {'HYDRA':>8} {'Delta':>8}")
print("-" * 95)
wins = 0
events_out = []
for event in DISASTERS:
    start = pd.Timestamp(event['date'])
    valid = hydra.index[hydra.index >= start]
    if len(valid) == 0:
        continue
    si = hydra.index.get_loc(valid[0])
    ei = min(si + HOLD_DAYS, len(hydra) - 1)
    year = pd.Timestamp(event['date']).year
    stocks = get_stocks_for_year(year)
    period = hydra.index[si:ei + 1]
    cr = [get_construction_return(d, year) for d in period]
    constr_ret = np.prod([1 + r for r in cr]) - 1
    hydra_ret = hydra['value'].iloc[ei] / hydra['value'].iloc[si] - 1
    delta = constr_ret - hydra_ret
    if delta > 0:
        wins += 1
    event_short = event['event'][:28]
    stocks_str = ','.join(stocks)
    print(f"{event['date']:<12} {event_short:<30} {stocks_str:<22} {constr_ret * 100:>7.1f}% {hydra_ret * 100:>7.1f}% {delta * 100:>7.1f}%")
    events_out.append({
        'date': event['date'], 'event': event['event'], 'location': event['location'],
        'stocks': stocks,
        'construction_return': round(constr_ret * 100, 2),
        'hydra_return': round(hydra_ret * 100, 2),
        'delta': round(delta * 100, 2),
    })

print(f"\nConstruction wins: {wins}/{len(events_out)} ({wins / len(events_out) * 100:.0f}%)")

bt_dir = os.path.join(base_dir, 'backtests')
pd.DataFrame({'date': hydra.index, 'hydra_value': hydra['value'].values, 'combined_value': combined}).to_csv(
    os.path.join(bt_dir, 'exp66_disaster_construction_daily.csv'), index=False)
with open(os.path.join(bt_dir, 'exp66_disaster_construction_summary.json'), 'w') as f:
    json.dump({
        'experiment': 'EXP66 -- Disasters -> Cement + Steel Stocks (1yr hold)',
        'hydra': {'cagr': round(h_cagr * 100, 2), 'sharpe': round(h_sharpe, 3), 'max_dd': round(h_dd * 100, 2), 'final': round(h_final, 2)},
        'combined': {'cagr': round(c_cagr * 100, 2), 'sharpe': round(c_sharpe, 3), 'max_dd': round(c_dd * 100, 2), 'final': round(c_final, 2)},
        'events': events_out,
    }, f, indent=2)
print("Saved.")
