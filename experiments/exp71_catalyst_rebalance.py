"""EXP71 -- Catalyst Pillar Rebalance: Add ZROZ + Reduce Gold
=============================================================
Current Catalyst (15% of portfolio):
  - 10% trend: TLT, GLD, DBC (equal-weight above SMA200)
  - 5% permanent gold (GLD always held)

Question: Can we add ZROZ to trend basket and/or reduce permanent gold?

Variants tested (all within 15% total budget):
  A) BASELINE:  10% trend(TLT,GLD,DBC) + 5% gold
  B) +ZROZ:     10% trend(TLT,ZROZ,GLD,DBC) + 5% gold
  C) +ZROZ -gold: 12.5% trend(TLT,ZROZ,GLD,DBC) + 2.5% gold
  D) +ZROZ no-gold: 15% trend(TLT,ZROZ,GLD,DBC) + 0% gold
  E) Bonds only: 10% trend(TLT,ZROZ) + 5% gold
  F) Bonds+gold: 12.5% trend(TLT,ZROZ,GLD) + 2.5% gold
"""
import pandas as pd
import numpy as np
import yfinance as yf
import json, os, sys

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bt_dir = os.path.join(base_dir, 'backtests')

# Load HYDRA base
hydra = pd.read_csv(os.path.join(bt_dir, 'hydra_clean_daily.csv'), parse_dates=['date'])
hydra.set_index('date', inplace=True)
hydra.index = pd.to_datetime(hydra.index).tz_localize(None)
hydra['return'] = hydra['value'].pct_change().fillna(0)
print(f"HYDRA: {hydra.index[0].date()} to {hydra.index[-1].date()} ({len(hydra)} days)")

# Download all needed assets
ALL_TICKERS = ['SPY', 'EFA', 'TLT', 'ZROZ', 'GLD', 'DBC']
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
    if len(df) == 0:
        print(f"  {ticker}: FAILED")
        continue
    df.columns = ['close']
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df['return'] = df['close'].pct_change().fillna(0)
    df['sma200'] = df['close'].rolling(SMA_PERIOD).mean()
    df['above_sma'] = df['close'] > df['sma200']
    asset_data[ticker] = df
    print(f"  {ticker}: {df.index[0].date()} to {df.index[-1].date()}")

# Gold futures for pre-GLD
print("Downloading GC=F...")
gcf = yf.download('GC=F', start='1999-01-01', end='2026-03-25', progress=False)
if isinstance(gcf.columns, pd.MultiIndex):
    gcf.columns = gcf.columns.get_level_values(0)
gcf = gcf[['Close']].dropna()
gcf.columns = ['close']
gcf.index = pd.to_datetime(gcf.index).tz_localize(None)
gcf['return'] = gcf['close'].pct_change().fillna(0)
print(f"  GC=F: {gcf.index[0].date()} to {gcf.index[-1].date()}")

# Full trend universe always includes SPY+EFA (managed by other pillars in live,
# but in EXP68 backtest they're included in the trend calc)
BASE_TREND = ['SPY', 'EFA']


def get_trend_return(date, trend_assets):
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
    gld = asset_data.get('GLD')
    if gld is not None and date in gld.index:
        return gld.loc[date, 'return']
    if date in gcf.index:
        return gcf.loc[date, 'return']
    return 0.0


# Variant definitions: (trend_assets beyond SPY+EFA, trend_weight, gold_weight, label)
VARIANTS = {
    'A': {
        'trend_extra': ['TLT', 'GLD', 'DBC'],
        'w_trend': 0.10,
        'w_gold': 0.05,
        'label': 'BASELINE: 10% trend(TLT,GLD,DBC) + 5% gold',
        'short': 'A) Baseline',
    },
    'B': {
        'trend_extra': ['TLT', 'ZROZ', 'GLD', 'DBC'],
        'w_trend': 0.10,
        'w_gold': 0.05,
        'label': '+ZROZ: 10% trend(TLT,ZROZ,GLD,DBC) + 5% gold',
        'short': 'B) +ZROZ',
    },
    'C': {
        'trend_extra': ['TLT', 'ZROZ', 'GLD', 'DBC'],
        'w_trend': 0.125,
        'w_gold': 0.025,
        'label': '+ZROZ -gold: 12.5% trend + 2.5% gold',
        'short': 'C) +ZROZ -gold',
    },
    'D': {
        'trend_extra': ['TLT', 'ZROZ', 'GLD', 'DBC'],
        'w_trend': 0.15,
        'w_gold': 0.00,
        'label': '+ZROZ no-gold: 15% trend + 0% gold',
        'short': 'D) +ZROZ 0gold',
    },
    'E': {
        'trend_extra': ['TLT', 'ZROZ'],
        'w_trend': 0.10,
        'w_gold': 0.05,
        'label': 'Bonds only: 10% trend(TLT,ZROZ) + 5% gold',
        'short': 'E) Bonds only',
    },
    'F': {
        'trend_extra': ['TLT', 'ZROZ', 'GLD'],
        'w_trend': 0.125,
        'w_gold': 0.025,
        'label': 'Bonds+gold: 12.5% trend(TLT,ZROZ,GLD) + 2.5% gold',
        'short': 'F) Bonds+GLD',
    },
}

# Common period: ZROZ starts Nov 2009, use 2010+
COMMON_START = '2010-01-01'
COMMON_END = '2026-12-31'


def run_variant(key, date_filter=None):
    v = VARIANTS[key]
    trend_assets = BASE_TREND + v['trend_extra']
    w_hydra = 1.0 - v['w_trend'] - v['w_gold']
    w_trend = v['w_trend']
    w_gold = v['w_gold']

    idx = hydra.index
    if date_filter:
        mask = (idx >= date_filter[0]) & (idx <= date_filter[1])
        idx = idx[mask]

    values = [100000.0]
    for i in range(1, len(idx)):
        date = idx[i]
        h_ret = hydra.loc[date, 'return']
        t_ret = get_trend_return(date, trend_assets)
        g_ret = get_gold_return(date) if w_gold > 0 else 0.0
        blended = w_hydra * h_ret + w_trend * t_ret + w_gold * g_ret
        values.append(values[-1] * (1 + blended))

    eq = pd.Series(values, index=idx)
    daily = eq.pct_change().dropna()
    n_years = (idx[-1] - idx[0]).days / 365.25

    cagr = (values[-1] / values[0]) ** (1 / n_years) - 1
    sharpe = daily.mean() / daily.std() * np.sqrt(252)
    sortino_d = daily[daily < 0].std() * np.sqrt(252)
    sortino = daily.mean() * 252 / sortino_d if sortino_d > 0 else 0
    vol = daily.std() * np.sqrt(252)
    maxdd = ((eq - eq.cummax()) / eq.cummax()).min()
    underwater = (eq - eq.cummax()) / eq.cummax()

    return {
        'key': key,
        'equity': eq,
        'final': values[-1],
        'cagr': cagr,
        'sharpe': sharpe,
        'sortino': sortino,
        'vol': vol,
        'maxdd': maxdd,
        'dd5_days': int((underwater < -0.05).sum()),
        'dd10_days': int((underwater < -0.10).sum()),
    }


# Run all variants
print(f"\nRunning {len(VARIANTS)} variants on {COMMON_START} to HYDRA end...")
results = {}
for key in VARIANTS:
    print(f"  {VARIANTS[key]['short']}...")
    results[key] = run_variant(key, date_filter=(COMMON_START, COMMON_END))

# HYDRA base for reference
hydra_mask = (hydra.index >= COMMON_START) & (hydra.index <= COMMON_END)
hydra_c = hydra[hydra_mask]
h_eq = pd.Series(hydra_c['value'].values / hydra_c['value'].values[0] * 100000, index=hydra_c.index)
h_daily = h_eq.pct_change().dropna()
h_ny = (h_eq.index[-1] - h_eq.index[0]).days / 365.25
h_cagr = (h_eq.iloc[-1] / h_eq.iloc[0]) ** (1 / h_ny) - 1
h_sharpe = h_daily.mean() / h_daily.std() * np.sqrt(252)
h_maxdd = ((h_eq - h_eq.cummax()) / h_eq.cummax()).min()

# ── RESULTS ──
print()
print("=" * 100)
print("EXP71 -- CATALYST PILLAR REBALANCE: ADD ZROZ + REDUCE GOLD?")
print("=" * 100)
print(f"Period: {COMMON_START} to {hydra_c.index[-1].date()} ({h_ny:.1f} years)")
print(f"Total Catalyst budget: 15% of portfolio")
print()

# Main comparison table
baseline = results['A']
print(f"{'Variant':<22} {'CAGR':>8} {'Sharpe':>8} {'Sortino':>9} {'MaxDD':>9} {'Vol':>8} {'Final $':>12} {'vs Base':>9}")
print("-" * 100)
print(f"{'HYDRA (no catalyst)':<22} {h_cagr*100:>7.2f}% {h_sharpe:>8.3f} {'N/A':>9} {h_maxdd*100:>8.2f}% {'N/A':>8} ${h_eq.iloc[-1]:>11,.0f} {'':>9}")
for key in ['A', 'B', 'C', 'D', 'E', 'F']:
    r = results[key]
    v = VARIANTS[key]
    delta_cagr = (r['cagr'] - baseline['cagr']) * 100
    delta_str = f"{delta_cagr:+.2f}%" if key != 'A' else "---"
    print(f"{v['short']:<22} {r['cagr']*100:>7.2f}% {r['sharpe']:>8.3f} {r['sortino']:>9.3f} {r['maxdd']*100:>8.2f}% {r['vol']*100:>7.2f}% ${r['final']:>11,.0f} {delta_str:>9}")

# Delta table vs baseline
print()
print("DELTA vs BASELINE (A)")
print("-" * 100)
print(f"{'Variant':<22} {'CAGR':>9} {'Sharpe':>9} {'Sortino':>9} {'MaxDD':>9} {'DD>5% days':>11} {'DD>10% days':>12}")
print("-" * 100)
for key in ['B', 'C', 'D', 'E', 'F']:
    r = results[key]
    b = baseline
    v = VARIANTS[key]
    print(f"{v['short']:<22} "
          f"{(r['cagr']-b['cagr'])*100:>+8.2f}% "
          f"{r['sharpe']-b['sharpe']:>+9.3f} "
          f"{r['sortino']-b['sortino']:>+9.3f} "
          f"{(r['maxdd']-b['maxdd'])*100:>+8.2f}% "
          f"{r['dd5_days']-b['dd5_days']:>+11} "
          f"{r['dd10_days']-b['dd10_days']:>+12}")

# Gold contribution analysis
print()
print("GOLD CONTRIBUTION ANALYSIS")
print("-" * 100)
# Compare D (0% gold) vs A (5% gold) — how much does permanent gold add?
gold_cagr = (results['A']['cagr'] - results['D']['cagr']) * 100
gold_sharpe = results['A']['sharpe'] - results['D']['sharpe']
gold_dd = (results['A']['maxdd'] - results['D']['maxdd']) * 100
print(f"5% permanent gold contribution (A vs D with same trend assets):")
print(f"  CAGR impact:   {gold_cagr:+.2f}%")
print(f"  Sharpe impact: {gold_sharpe:+.3f}")
print(f"  MaxDD impact:  {gold_dd:+.2f}%")

# Compare B (5% gold) vs C (2.5% gold) vs D (0% gold) — gold scaling
print()
print(f"Gold scaling (with TLT+ZROZ+GLD+DBC trend basket):")
print(f"  {'Gold %':<10} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>8}")
for key, gpct in [('D', '0%'), ('C', '2.5%'), ('B', '5%')]:
    r = results[key]
    print(f"  {gpct:<10} {r['cagr']*100:>7.2f}% {r['sharpe']:>8.3f} {r['maxdd']*100:>7.2f}%")

# ZROZ contribution analysis
print()
print("ZROZ CONTRIBUTION ANALYSIS")
print("-" * 100)
zroz_cagr = (results['B']['cagr'] - results['A']['cagr']) * 100
zroz_sharpe = results['B']['sharpe'] - results['A']['sharpe']
zroz_dd = (results['B']['maxdd'] - results['A']['maxdd']) * 100
print(f"Adding ZROZ to trend basket (B vs A, same gold):")
print(f"  CAGR impact:   {zroz_cagr:+.2f}%")
print(f"  Sharpe impact: {zroz_sharpe:+.3f}")
print(f"  MaxDD impact:  {zroz_dd:+.2f}%")

# DBC contribution: compare E (no DBC) vs B (with DBC)
dbc_cagr = (results['B']['cagr'] - results['E']['cagr']) * 100
dbc_sharpe = results['B']['sharpe'] - results['E']['sharpe']
print(f"\nDBC in trend basket (B vs E):")
print(f"  CAGR impact:   {dbc_cagr:+.2f}%")
print(f"  Sharpe impact: {dbc_sharpe:+.3f}")

# Period breakdown
periods = {
    '2010-2019 (Recovery)':   ('2010-01-01', '2019-12-31'),
    '2020 (COVID)':           ('2020-01-01', '2020-12-31'),
    '2021-2023 (Rate Hikes)': ('2021-01-01', '2023-12-31'),
    '2024-2026 (Recent)':     ('2024-01-01', '2026-12-31'),
}

print()
print("PERIOD CAGR BREAKDOWN")
print("-" * 100)
header = f"{'Period':<28}"
for key in ['A', 'B', 'C', 'D', 'E', 'F']:
    header += f" {VARIANTS[key]['short'][-8:]:>10}"
header += f" {'Best':>8}"
print(header)
print("-" * 100)
for pname, (ps, pe) in periods.items():
    row = f"{pname:<28}"
    best_key = None
    best_cagr = -999
    for key in ['A', 'B', 'C', 'D', 'E', 'F']:
        eq = results[key]['equity']
        mask = (eq.index >= ps) & (eq.index <= pe)
        if mask.sum() < 20:
            row += f" {'N/A':>10}"
            continue
        peq = eq[mask]
        py = (peq.index[-1] - peq.index[0]).days / 365.25
        if py < 0.1:
            row += f" {'N/A':>10}"
            continue
        pcagr = (peq.iloc[-1] / peq.iloc[0]) ** (1 / py) - 1
        row += f" {pcagr*100:>9.2f}%"
        if pcagr > best_cagr:
            best_cagr = pcagr
            best_key = key
    row += f" {best_key:>8}" if best_key else ""
    print(row)

# Yearly
print()
print("YEARLY WINNER")
print("-" * 100)
yearly_wins = {k: 0 for k in VARIANTS}
yearly_data = {}
for key in VARIANTS:
    yr = results[key]['equity'].resample('YE').last().pct_change().dropna() * 100
    yearly_data[key] = yr
all_years = sorted(set().union(*[set(yr.index) for yr in yearly_data.values()]))

header = f"{'Year':<6}"
for key in ['A', 'B', 'C', 'D', 'E', 'F']:
    header += f" {VARIANTS[key]['short'][-8:]:>10}"
header += f" {'Best':>6}"
print(header)
print("-" * 80)
for yr in all_years:
    row = f"{yr.year:<6}"
    best_k = None
    best_r = -999
    for key in ['A', 'B', 'C', 'D', 'E', 'F']:
        if yr in yearly_data[key].index:
            ret = yearly_data[key][yr]
            row += f" {ret:>9.1f}%"
            if ret > best_r:
                best_r = ret
                best_k = key
        else:
            row += f" {'N/A':>10}"
    if best_k:
        yearly_wins[best_k] += 1
    row += f" {best_k:>6}" if best_k else ""
    print(row)

print()
for key in ['A', 'B', 'C', 'D', 'E', 'F']:
    print(f"  {VARIANTS[key]['short']}: {yearly_wins[key]}/{len(all_years)} wins")

# ── VERDICT ──
print()
print("=" * 100)
print("VERDICT:")
ranked = sorted(results.items(), key=lambda x: x[1]['sharpe'], reverse=True)
for i, (key, r) in enumerate(ranked):
    marker = " <-- CURRENT" if key == 'A' else ""
    v = VARIANTS[key]
    print(f"  {i+1}. [{key}] {v['short']:<22} Sharpe={r['sharpe']:.3f}  CAGR={r['cagr']*100:.2f}%  MaxDD={r['maxdd']*100:.2f}%{marker}")

best_key = ranked[0][0]
best_r = ranked[0][1]
if best_key == 'A':
    print(f"\n  >> Current config remains best. No change needed.")
else:
    v = VARIANTS[best_key]
    delta_c = (best_r['cagr'] - baseline['cagr']) * 100
    delta_s = best_r['sharpe'] - baseline['sharpe']
    print(f"\n  >> WINNER: [{best_key}] {v['label']}")
    print(f"     CAGR {delta_c:+.2f}%, Sharpe {delta_s:+.3f} vs baseline")
    print(f"     Trend assets: {BASE_TREND + v['trend_extra']}")
    print(f"     Weights: {v['w_trend']*100:.1f}% trend + {v['w_gold']*100:.1f}% gold = 15%")
print("=" * 100)

# Save
summary = {
    'experiment': 'EXP71 -- Catalyst Pillar Rebalance',
    'period': f'{COMMON_START} to {hydra_c.index[-1].date()}',
    'variants': {},
}
for key, r in results.items():
    v = VARIANTS[key]
    summary['variants'][key] = {
        'label': v['label'],
        'trend_assets': BASE_TREND + v['trend_extra'],
        'w_trend': v['w_trend'],
        'w_gold': v['w_gold'],
        'cagr': round(r['cagr'] * 100, 2),
        'sharpe': round(r['sharpe'], 3),
        'sortino': round(r['sortino'], 3),
        'max_dd': round(r['maxdd'] * 100, 2),
        'vol': round(r['vol'] * 100, 2),
        'final': round(r['final'], 2),
    }
with open(os.path.join(bt_dir, 'exp71_catalyst_rebalance_summary.json'), 'w') as f:
    json.dump(summary, f, indent=2)
print(f"\nSaved: exp71_catalyst_rebalance_summary.json")
