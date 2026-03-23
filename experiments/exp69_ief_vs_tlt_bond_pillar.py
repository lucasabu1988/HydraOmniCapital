"""EXP69 -- Bond Pillar: IEF (7-10yr) vs TLT (20+yr) in Catalyst Trend
=====================================================================
Hypothesis: IEF (10-year Treasury) is more representative of bond momentum
than TLT (20+ year). Lower duration = less volatility, smoother signals,
potentially better risk-adjusted contribution.

Method: Run the same 85/10/5 blend from EXP68 twice:
  A) TLT baseline (original)
  B) IEF replacement
Compare CAGR, Sharpe, MaxDD, and contribution analysis.
"""
import pandas as pd
import numpy as np
import yfinance as yf
import json, os

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bt_dir = os.path.join(base_dir, 'backtests')

# Load HYDRA base
hydra = pd.read_csv(os.path.join(bt_dir, 'hydra_clean_daily.csv'), parse_dates=['date'])
hydra.set_index('date', inplace=True)
hydra.index = pd.to_datetime(hydra.index).tz_localize(None)
hydra['return'] = hydra['value'].pct_change().fillna(0)
print(f"HYDRA: {hydra.index[0].date()} to {hydra.index[-1].date()} ({len(hydra)} days)")

# Trend assets — two variants
COMMON_ASSETS = ['SPY', 'EFA', 'GLD', 'DBC']
VARIANT_A_BOND = 'TLT'  # baseline (20+ year)
VARIANT_B_BOND = 'IEF'  # challenger (7-10 year)
ALL_TICKERS = list(set(COMMON_ASSETS + [VARIANT_A_BOND, VARIANT_B_BOND]))
SMA_PERIOD = 200

print("Downloading assets...")
asset_data = {}
for ticker in ALL_TICKERS:
    for attempt in range(3):
        df = yf.download(ticker, start='1999-01-01', end='2026-03-25', progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[['Close']].dropna()
        if len(df) > 0:
            break
        print(f"  {ticker}: retry {attempt + 1}/3...")
    df.columns = ['close']
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df['return'] = df['close'].pct_change().fillna(0)
    df['sma200'] = df['close'].rolling(SMA_PERIOD).mean()
    df['above_sma'] = df['close'] > df['sma200']
    asset_data[ticker] = df
    print(f"  {ticker}: {df.index[0].date()} to {df.index[-1].date()}")

# Gold futures for pre-GLD period
print("Downloading GC=F for pre-GLD period...")
gcf = yf.download('GC=F', start='1999-01-01', end='2026-03-25', progress=False)
if isinstance(gcf.columns, pd.MultiIndex):
    gcf.columns = gcf.columns.get_level_values(0)
gcf = gcf[['Close']].dropna()
gcf.columns = ['close']
gcf.index = pd.to_datetime(gcf.index).tz_localize(None)
gcf['return'] = gcf['close'].pct_change().fillna(0)
print(f"  GC=F: {gcf.index[0].date()} to {gcf.index[-1].date()}")


def get_trend_return(date, trend_assets):
    """Equal-weight among trend assets above their SMA200."""
    qualifying = []
    for ticker in trend_assets:
        df = asset_data.get(ticker)
        if df is None or date not in df.index:
            continue
        if pd.isna(df.loc[date, 'sma200']):
            continue
        if df.loc[date, 'above_sma']:
            qualifying.append(df.loc[date, 'return'])
    return np.mean(qualifying) if qualifying else 0.0


def get_gold_return(date):
    """Gold return: GLD if available, else GC=F."""
    gld = asset_data.get('GLD')
    if gld is not None and date in gld.index:
        return gld.loc[date, 'return']
    if date in gcf.index:
        return gcf.loc[date, 'return']
    return 0.0


def run_blend(trend_assets, label):
    """Run 85/10/5 blend and return equity series + metrics."""
    W_HYDRA = 0.85
    W_TREND = 0.10
    W_GOLD = 0.05

    values = [hydra['value'].iloc[0]]
    for i in range(1, len(hydra)):
        date = hydra.index[i]
        h_ret = hydra['return'].iloc[i]
        t_ret = get_trend_return(date, trend_assets)
        g_ret = get_gold_return(date)
        blended_ret = W_HYDRA * h_ret + W_TREND * t_ret + W_GOLD * g_ret
        values.append(values[-1] * (1 + blended_ret))

    eq = pd.Series(values, index=hydra.index)
    daily = eq.pct_change().dropna()
    n_years = (hydra.index[-1] - hydra.index[0]).days / 365.25
    start_val = values[0]
    final_val = values[-1]

    cagr = (final_val / start_val) ** (1 / n_years) - 1
    sharpe = daily.mean() / daily.std() * np.sqrt(252)
    sortino_denom = daily[daily < 0].std() * np.sqrt(252)
    sortino = daily.mean() * 252 / sortino_denom if sortino_denom > 0 else 0
    vol = daily.std() * np.sqrt(252)
    maxdd = ((eq - eq.cummax()) / eq.cummax()).min()
    underwater = (eq - eq.cummax()) / eq.cummax()
    dd5_days = (underwater < -0.05).sum()
    dd10_days = (underwater < -0.10).sum()

    return {
        'label': label,
        'equity': eq,
        'daily': daily,
        'final': final_val,
        'cagr': cagr,
        'sharpe': sharpe,
        'sortino': sortino,
        'vol': vol,
        'maxdd': maxdd,
        'dd5_days': int(dd5_days),
        'dd10_days': int(dd10_days),
    }


# Run both variants
trend_a = COMMON_ASSETS + [VARIANT_A_BOND]  # with TLT
trend_b = COMMON_ASSETS + [VARIANT_B_BOND]  # with IEF

print("\nRunning Variant A (TLT)...")
res_tlt = run_blend(trend_a, 'TLT (20+ yr)')
print("Running Variant B (IEF)...")
res_ief = run_blend(trend_b, 'IEF (7-10 yr)')

# Also compute HYDRA standalone for reference
hydra_eq = pd.Series(hydra['value'].values, index=hydra.index)
hydra_daily = hydra_eq.pct_change().dropna()
n_years = (hydra.index[-1] - hydra.index[0]).days / 365.25
h_cagr = (hydra_eq.iloc[-1] / hydra_eq.iloc[0]) ** (1 / n_years) - 1
h_sharpe = hydra_daily.mean() / hydra_daily.std() * np.sqrt(252)
h_maxdd = ((hydra_eq - hydra_eq.cummax()) / hydra_eq.cummax()).min()

# Bond-specific analysis: when does IEF vs TLT differ?
tlt_df = asset_data[VARIANT_A_BOND]
ief_df = asset_data[VARIANT_B_BOND]

# Count days each is above SMA200 (within HYDRA date range)
common_dates = hydra.index.intersection(tlt_df.index).intersection(ief_df.index)
tlt_above = sum(1 for d in common_dates if d in tlt_df.index and tlt_df.loc[d, 'above_sma'])
ief_above = sum(1 for d in common_dates if d in ief_df.index and ief_df.loc[d, 'above_sma'])

# Correlation between TLT and IEF returns
merged = pd.DataFrame({
    'tlt': tlt_df['return'],
    'ief': ief_df['return'],
}).dropna()
bond_corr = merged['tlt'].corr(merged['ief'])

# Period analysis: pre/post GFC, COVID, 2022 rate hikes
periods = {
    '2002-2007 (Pre-GFC)':     ('2002-01-01', '2007-12-31'),
    '2008-2009 (GFC)':         ('2008-01-01', '2009-12-31'),
    '2010-2019 (Recovery)':    ('2010-01-01', '2019-12-31'),
    '2020 (COVID)':            ('2020-01-01', '2020-12-31'),
    '2021-2023 (Rate Hikes)':  ('2021-01-01', '2023-12-31'),
    '2024-2026 (Recent)':      ('2024-01-01', '2026-12-31'),
}

# Print results
print()
print("=" * 80)
print("EXP69 -- BOND PILLAR: IEF (7-10yr) vs TLT (20+yr) IN CATALYST TREND")
print("=" * 80)
print(f"Period: {hydra.index[0].date()} to {hydra.index[-1].date()} ({n_years:.1f} years)")
print(f"Blend: 85% HYDRA + 10% Trend (SPY, EFA, [BOND], GLD, DBC) + 5% Gold")
print(f"Trend rule: equal-weight assets above SMA200, cash if none")
print()

print(f"{'Metric':<25} {'HYDRA Base':>14} {'+ TLT (20+yr)':>14} {'+ IEF (7-10yr)':>14} {'IEF - TLT':>12}")
print("-" * 80)
print(f"{'Final Value':<25} ${hydra_eq.iloc[-1]:>13,.0f} ${res_tlt['final']:>13,.0f} ${res_ief['final']:>13,.0f} ${res_ief['final']-res_tlt['final']:>11,.0f}")
print(f"{'CAGR':<25} {h_cagr*100:>13.2f}% {res_tlt['cagr']*100:>13.2f}% {res_ief['cagr']*100:>13.2f}% {(res_ief['cagr']-res_tlt['cagr'])*100:>11.2f}%")
print(f"{'Sharpe':<25} {h_sharpe:>14.3f} {res_tlt['sharpe']:>14.3f} {res_ief['sharpe']:>14.3f} {res_ief['sharpe']-res_tlt['sharpe']:>12.3f}")
print(f"{'Sortino':<25} {'N/A':>14} {res_tlt['sortino']:>14.3f} {res_ief['sortino']:>14.3f} {res_ief['sortino']-res_tlt['sortino']:>12.3f}")
print(f"{'Volatility':<25} {'N/A':>14} {res_tlt['vol']*100:>13.2f}% {res_ief['vol']*100:>13.2f}% {(res_ief['vol']-res_tlt['vol'])*100:>11.2f}%")
print(f"{'Max Drawdown':<25} {h_maxdd*100:>13.2f}% {res_tlt['maxdd']*100:>13.2f}% {res_ief['maxdd']*100:>13.2f}% {(res_ief['maxdd']-res_tlt['maxdd'])*100:>11.2f}%")
print(f"{'Days in >5% DD':<25} {'N/A':>14} {res_tlt['dd5_days']:>14} {res_ief['dd5_days']:>14} {res_ief['dd5_days']-res_tlt['dd5_days']:>12}")
print(f"{'Days in >10% DD':<25} {'N/A':>14} {res_tlt['dd10_days']:>14} {res_ief['dd10_days']:>14} {res_ief['dd10_days']-res_tlt['dd10_days']:>12}")

# Bond characteristics
print()
print("BOND CHARACTERISTICS")
print("-" * 80)
print(f"{'TLT-IEF daily return correlation:':<45} {bond_corr:.3f}")
print(f"{'TLT days above SMA200 (in HYDRA range):':<45} {tlt_above}/{len(common_dates)} ({tlt_above/len(common_dates)*100:.1f}%)")
print(f"{'IEF days above SMA200 (in HYDRA range):':<45} {ief_above}/{len(common_dates)} ({ief_above/len(common_dates)*100:.1f}%)")
tlt_vol = tlt_df['return'].std() * np.sqrt(252)
ief_vol = ief_df['return'].std() * np.sqrt(252)
print(f"{'TLT annualized vol (full history):':<45} {tlt_vol*100:.2f}%")
print(f"{'IEF annualized vol (full history):':<45} {ief_vol*100:.2f}%")
tlt_cagr_standalone = (tlt_df['close'].iloc[-1] / tlt_df['close'].iloc[0]) ** (365.25 / (tlt_df.index[-1] - tlt_df.index[0]).days) - 1
ief_cagr_standalone = (ief_df['close'].iloc[-1] / ief_df['close'].iloc[0]) ** (365.25 / (ief_df.index[-1] - ief_df.index[0]).days) - 1
print(f"{'TLT standalone CAGR:':<45} {tlt_cagr_standalone*100:.2f}%")
print(f"{'IEF standalone CAGR:':<45} {ief_cagr_standalone*100:.2f}%")

# Period comparison
print()
print("PERIOD BREAKDOWN (blend CAGR)")
print("-" * 80)
print(f"{'Period':<30} {'+ TLT':>12} {'+ IEF':>12} {'Delta':>10} {'Winner':>10}")
print("-" * 80)
ief_wins = 0
for pname, (pstart, pend) in periods.items():
    mask = (hydra.index >= pstart) & (hydra.index <= pend)
    if mask.sum() < 20:
        continue
    tlt_period = res_tlt['equity'][mask]
    ief_period = res_ief['equity'][mask]
    p_years = (tlt_period.index[-1] - tlt_period.index[0]).days / 365.25
    if p_years < 0.1:
        continue
    tlt_pcagr = (tlt_period.iloc[-1] / tlt_period.iloc[0]) ** (1 / p_years) - 1
    ief_pcagr = (ief_period.iloc[-1] / ief_period.iloc[0]) ** (1 / p_years) - 1
    delta = ief_pcagr - tlt_pcagr
    winner = 'IEF' if delta > 0 else 'TLT'
    if delta > 0:
        ief_wins += 1
    print(f"{pname:<30} {tlt_pcagr*100:>11.2f}% {ief_pcagr*100:>11.2f}% {delta*100:>9.2f}% {winner:>10}")
print(f"\nIEF wins: {ief_wins}/{len([p for p in periods.values() if (hydra.index >= p[0]).sum() > 20])} periods")

# Yearly comparison
print()
print("YEARLY COMPARISON")
print("-" * 80)
tlt_yearly = res_tlt['equity'].resample('YE').last().pct_change().dropna() * 100
ief_yearly = res_ief['equity'].resample('YE').last().pct_change().dropna() * 100
yearly = pd.DataFrame({'tlt': tlt_yearly, 'ief': ief_yearly}).dropna()
yearly['delta'] = yearly['ief'] - yearly['tlt']
print(f"{'Year':<8} {'+ TLT':>10} {'+ IEF':>10} {'Delta':>10} {'Winner':>10}")
print("-" * 50)
ief_yr_wins = 0
for idx, row in yearly.iterrows():
    winner = 'IEF' if row['delta'] > 0 else 'TLT'
    if row['delta'] > 0:
        ief_yr_wins += 1
    print(f"{idx.year:<8} {row['tlt']:>9.1f}% {row['ief']:>9.1f}% {row['delta']:>9.2f}% {winner:>10}")
print(f"\nIEF wins: {ief_yr_wins}/{len(yearly)} years ({ief_yr_wins/len(yearly)*100:.0f}%)")

# Verdict
print()
print("=" * 80)
cagr_delta = (res_ief['cagr'] - res_tlt['cagr']) * 100
sharpe_delta = res_ief['sharpe'] - res_tlt['sharpe']
dd_delta = (res_ief['maxdd'] - res_tlt['maxdd']) * 100
print("VERDICT:")
print(f"  CAGR delta:   {cagr_delta:+.2f}% ({'IEF better' if cagr_delta > 0 else 'TLT better'})")
print(f"  Sharpe delta: {sharpe_delta:+.3f} ({'IEF better' if sharpe_delta > 0 else 'TLT better'})")
print(f"  MaxDD delta:  {dd_delta:+.2f}% ({'IEF better (less DD)' if dd_delta > 0 else 'TLT better (less DD)'})")
if cagr_delta > 0 and sharpe_delta > 0:
    print("  >> IEF DOMINATES: higher return + better risk-adjusted performance")
elif cagr_delta < 0 and sharpe_delta < 0:
    print("  >> TLT DOMINATES: higher return + better risk-adjusted performance")
elif sharpe_delta > 0:
    print("  >> IEF has better risk-adjusted returns despite lower CAGR")
else:
    print("  >> TLT has higher returns but IEF is more efficient")
print("=" * 80)

# Save results
results_out = pd.DataFrame({
    'date': hydra.index,
    'hydra_value': hydra['value'].values,
    'tlt_blend_value': res_tlt['equity'].values,
    'ief_blend_value': res_ief['equity'].values,
})
results_out.to_csv(os.path.join(bt_dir, 'exp69_ief_vs_tlt_daily.csv'), index=False)

summary = {
    'experiment': 'EXP69 -- Bond Pillar: IEF vs TLT in Catalyst Trend',
    'tlt': {
        'cagr': round(res_tlt['cagr'] * 100, 2),
        'sharpe': round(res_tlt['sharpe'], 3),
        'sortino': round(res_tlt['sortino'], 3),
        'max_dd': round(res_tlt['maxdd'] * 100, 2),
        'vol': round(res_tlt['vol'] * 100, 2),
        'final': round(res_tlt['final'], 2),
    },
    'ief': {
        'cagr': round(res_ief['cagr'] * 100, 2),
        'sharpe': round(res_ief['sharpe'], 3),
        'sortino': round(res_ief['sortino'], 3),
        'max_dd': round(res_ief['maxdd'] * 100, 2),
        'vol': round(res_ief['vol'] * 100, 2),
        'final': round(res_ief['final'], 2),
    },
    'delta': {
        'cagr': round(cagr_delta, 2),
        'sharpe': round(sharpe_delta, 3),
        'max_dd': round(dd_delta, 2),
    },
    'bond_stats': {
        'correlation': round(bond_corr, 3),
        'tlt_vol': round(tlt_vol * 100, 2),
        'ief_vol': round(ief_vol * 100, 2),
        'tlt_above_sma_pct': round(tlt_above / len(common_dates) * 100, 1),
        'ief_above_sma_pct': round(ief_above / len(common_dates) * 100, 1),
    },
}
with open(os.path.join(bt_dir, 'exp69_ief_vs_tlt_summary.json'), 'w') as f:
    json.dump(summary, f, indent=2)

print(f"\nSaved: exp69_ief_vs_tlt_daily.csv + exp69_ief_vs_tlt_summary.json")
