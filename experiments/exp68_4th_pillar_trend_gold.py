"""EXP68 -- 4th Pillar: 85% HYDRA + 10% Cross-Asset Trend + 5% Gold"""
import pandas as pd
import numpy as np
import yfinance as yf
import json, os

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bt_dir = os.path.join(base_dir, 'backtests')

# Load HYDRA
hydra = pd.read_csv(os.path.join(bt_dir, 'hydra_clean_daily.csv'), parse_dates=['date'])
hydra.set_index('date', inplace=True)
hydra.index = pd.to_datetime(hydra.index).tz_localize(None)
hydra['return'] = hydra['value'].pct_change().fillna(0)
print(f"HYDRA: {hydra.index[0].date()} to {hydra.index[-1].date()} ({len(hydra)} days)")

# Download trend-following assets + gold
TREND_ASSETS = ['SPY', 'EFA', 'TLT', 'GLD', 'DBC']
SMA_PERIOD = 200

print("Downloading assets...")
asset_data = {}
for ticker in TREND_ASSETS:
    df = yf.download(ticker, start='1999-01-01', end='2026-03-15', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[['Close']].dropna()
    df.columns = ['close']
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df['return'] = df['close'].pct_change().fillna(0)
    df['sma200'] = df['close'].rolling(SMA_PERIOD).mean()
    df['above_sma'] = df['close'] > df['sma200']
    asset_data[ticker] = df
    print(f"  {ticker}: {df.index[0].date()} to {df.index[-1].date()}")

# For gold pillar, use GLD directly (already downloaded)
# For pre-GLD period (before Nov 2004), use GC=F (gold futures)
print("Downloading GC=F for pre-GLD period...")
gcf = yf.download('GC=F', start='1999-01-01', end='2026-03-15', progress=False)
if isinstance(gcf.columns, pd.MultiIndex):
    gcf.columns = gcf.columns.get_level_values(0)
gcf = gcf[['Close']].dropna()
gcf.columns = ['close']
gcf.index = pd.to_datetime(gcf.index).tz_localize(None)
gcf['return'] = gcf['close'].pct_change().fillna(0)
print(f"  GC=F: {gcf.index[0].date()} to {gcf.index[-1].date()}")

# For pre-ETF trend assets, use futures
# SPY exists from 1993, but TLT from 2002, DBC from 2006, EFA from 2001, GLD from 2004
# Use available assets only; equal-weight among those with data + above SMA200
# For pre-2002 bonds, use ^TNX inverse proxy or skip bonds


def get_trend_return(date):
    """Equal-weight among trend assets that are above their SMA200."""
    qualifying = []
    for ticker in TREND_ASSETS:
        df = asset_data[ticker]
        if date not in df.index:
            continue
        if pd.isna(df.loc[date, 'sma200']):
            continue
        if df.loc[date, 'above_sma']:
            qualifying.append(df.loc[date, 'return'])

    if qualifying:
        return np.mean(qualifying)
    # If nothing qualifies (all below SMA200), return 0 (cash/SHY equivalent)
    return 0.0


def get_gold_return(date):
    """Gold return: use GLD if available, else GC=F."""
    gld = asset_data.get('GLD')
    if gld is not None and date in gld.index:
        return gld.loc[date, 'return']
    if date in gcf.index:
        return gcf.loc[date, 'return']
    return 0.0


# Build combined portfolio: 85% HYDRA + 10% Trend + 5% Gold
# Rebalance daily (returns-based blend)
W_HYDRA = 0.85
W_TREND = 0.10
W_GOLD = 0.05

combined = [hydra['value'].iloc[0]]
hydra_only = [hydra['value'].iloc[0]]
trend_contrib = []
gold_contrib = []

for i in range(1, len(hydra)):
    date = hydra.index[i]
    h_ret = hydra['return'].iloc[i]
    t_ret = get_trend_return(date)
    g_ret = get_gold_return(date)

    blended_ret = W_HYDRA * h_ret + W_TREND * t_ret + W_GOLD * g_ret
    combined.append(combined[-1] * (1 + blended_ret))
    hydra_only.append(hydra_only[-1] * (1 + h_ret))
    trend_contrib.append(t_ret)
    gold_contrib.append(g_ret)

# Metrics
n_years = (hydra.index[-1] - hydra.index[0]).days / 365.25
h_start = hydra['value'].iloc[0]
h_final = hydra_only[-1]
c_final = combined[-1]

h_cagr = (h_final / h_start) ** (1 / n_years) - 1
c_cagr = (c_final / h_start) ** (1 / n_years) - 1

hs = pd.Series(hydra_only, index=hydra.index)
cs = pd.Series(combined, index=hydra.index)

h_daily = hs.pct_change().dropna()
c_daily = cs.pct_change().dropna()

h_sharpe = h_daily.mean() / h_daily.std() * np.sqrt(252)
c_sharpe = c_daily.mean() / c_daily.std() * np.sqrt(252)

h_dd = ((hs - hs.cummax()) / hs.cummax()).min()
c_dd = ((cs - cs.cummax()) / cs.cummax()).min()

# Annual volatility
h_vol = h_daily.std() * np.sqrt(252)
c_vol = c_daily.std() * np.sqrt(252)

# Correlation
corr = h_daily.corr(c_daily)

# Yearly comparison
results_df = pd.DataFrame({
    'date': hydra.index,
    'hydra_value': hydra_only,
    'combined_value': combined,
})
results_df.set_index('date', inplace=True)
results_df['hydra_year'] = results_df['hydra_value'].resample('YE').last().pct_change()
results_df['combined_year'] = results_df['combined_value'].resample('YE').last().pct_change()

yearly = pd.DataFrame({
    'hydra': results_df['hydra_value'].resample('YE').last().pct_change() * 100,
    'combined': results_df['combined_value'].resample('YE').last().pct_change() * 100,
})
yearly['delta'] = yearly['combined'] - yearly['hydra']
yearly = yearly.dropna()

# Drawdown periods analysis
h_peak = hs.cummax()
c_peak = cs.cummax()
h_underwater = (hs - h_peak) / h_peak
c_underwater = (cs - c_peak) / c_peak

# Count days in >5% drawdown
h_deep_dd_days = (h_underwater < -0.05).sum()
c_deep_dd_days = (c_underwater < -0.05).sum()

# Count days in >10% drawdown
h_10_dd_days = (h_underwater < -0.10).sum()
c_10_dd_days = (c_underwater < -0.10).sum()

print()
print("=" * 75)
print("EXP68 -- 4th PILLAR: 85% HYDRA + 10% CROSS-ASSET TREND + 5% GOLD")
print("=" * 75)
print(f"Period: {hydra.index[0].date()} to {hydra.index[-1].date()} ({n_years:.1f} years)")
print(f"Weights: HYDRA {W_HYDRA*100:.0f}% | Trend {W_TREND*100:.0f}% | Gold {W_GOLD*100:.0f}%")
print(f"Trend rule: equal-weight assets above SMA200 (SPY, EFA, TLT, GLD, DBC)")
print()
print(f"{'Metric':<30} {'HYDRA 100%':>15} {'85/10/5 Blend':>15} {'Delta':>10}")
print("-" * 75)
print(f"{'Final Value':<30} ${h_final:>14,.0f} ${c_final:>14,.0f} ${c_final-h_final:>9,.0f}")
print(f"{'CAGR':<30} {h_cagr*100:>14.2f}% {c_cagr*100:>14.2f}% {(c_cagr-h_cagr)*100:>9.2f}%")
print(f"{'Sharpe Ratio':<30} {h_sharpe:>15.3f} {c_sharpe:>15.3f} {c_sharpe-h_sharpe:>10.3f}")
print(f"{'Annual Volatility':<30} {h_vol*100:>14.2f}% {c_vol*100:>14.2f}% {(c_vol-h_vol)*100:>9.2f}%")
print(f"{'Max Drawdown':<30} {h_dd*100:>14.2f}% {c_dd*100:>14.2f}% {(c_dd-h_dd)*100:>9.2f}%")
print(f"{'Days in >5% DD':<30} {h_deep_dd_days:>15} {c_deep_dd_days:>15} {c_deep_dd_days-h_deep_dd_days:>10}")
print(f"{'Days in >10% DD':<30} {h_10_dd_days:>15} {c_10_dd_days:>15} {c_10_dd_days-h_10_dd_days:>10}")
print(f"{'Total Return':<30} {(h_final/h_start-1)*100:>13.1f}% {(c_final/h_start-1)*100:>14.1f}%")

print(f"\nYearly Comparison:")
print(f"{'Year':<8} {'HYDRA':>10} {'Blend':>10} {'Delta':>10} {'Winner':>10}")
print("-" * 50)
blend_wins = 0
for idx, row in yearly.iterrows():
    winner = 'Blend' if row['delta'] > 0 else 'HYDRA'
    if row['delta'] > 0:
        blend_wins += 1
    print(f"{idx.year:<8} {row['hydra']:>9.1f}% {row['combined']:>9.1f}% {row['delta']:>9.1f}% {winner:>10}")
print(f"\nBlend wins: {blend_wins}/{len(yearly)} years ({blend_wins/len(yearly)*100:.0f}%)")

# Save
results_out = pd.DataFrame({
    'date': hydra.index,
    'hydra_value': hydra_only,
    'combined_value': combined,
})
results_out.to_csv(os.path.join(bt_dir, 'exp68_4th_pillar_daily.csv'), index=False)

summary = {
    'experiment': 'EXP68 -- 85% HYDRA + 10% Cross-Asset Trend + 5% Gold',
    'weights': {'hydra': W_HYDRA, 'trend': W_TREND, 'gold': W_GOLD},
    'trend_assets': TREND_ASSETS,
    'trend_rule': 'Equal-weight assets above SMA200, cash if none qualify',
    'hydra': {
        'cagr': round(h_cagr * 100, 2),
        'sharpe': round(h_sharpe, 3),
        'max_dd': round(h_dd * 100, 2),
        'vol': round(h_vol * 100, 2),
        'final': round(h_final, 2),
    },
    'combined': {
        'cagr': round(c_cagr * 100, 2),
        'sharpe': round(c_sharpe, 3),
        'max_dd': round(c_dd * 100, 2),
        'vol': round(c_vol * 100, 2),
        'final': round(c_final, 2),
    },
    'improvement': {
        'cagr_delta': round((c_cagr - h_cagr) * 100, 2),
        'sharpe_delta': round(c_sharpe - h_sharpe, 3),
        'dd_reduction': round((c_dd - h_dd) * 100, 2),
        'vol_reduction': round((c_vol - h_vol) * 100, 2),
    },
}
with open(os.path.join(bt_dir, 'exp68_4th_pillar_summary.json'), 'w') as f:
    json.dump(summary, f, indent=2)

print(f"\nSaved: exp68_4th_pillar_daily.csv + exp68_4th_pillar_summary.json")
