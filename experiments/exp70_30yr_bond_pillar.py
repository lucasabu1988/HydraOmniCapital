"""EXP70 -- Bond Duration Spectrum: IEF vs TLT vs EDV vs ZROZ in Catalyst
========================================================================
Following EXP69 (TLT > IEF), test if even more duration helps.
  - IEF:  7-10 year Treasury (duration ~7.5)  — since 2002
  - TLT:  20+ year Treasury  (duration ~17)   — since 2002
  - EDV:  Extended Duration   (duration ~24)   — since 2007-12
  - ZROZ: 25+ yr Zero Coupon  (duration ~27)   — since 2009-10

Problem: EDV/ZROZ have shorter history. Solution:
  1) Full period (2000-2026): TLT vs IEF only (from EXP69)
  2) Common period (2010-2026): all 4 head-to-head on same dates
"""
import pandas as pd
import numpy as np
import yfinance as yf
import json, os, sys

# Fix Windows encoding for box-drawing characters
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

# All bond candidates + common trend assets
COMMON_ASSETS = ['SPY', 'EFA', 'GLD', 'DBC']
BOND_CANDIDATES = {
    'IEF':  '7-10yr  (dur ~7.5)',
    'TLT':  '20+yr   (dur ~17)',
    'EDV':  'Ext Dur (dur ~24)',
    'ZROZ': '25+yr 0-cpn (dur ~27)',
}
ALL_TICKERS = list(set(COMMON_ASSETS + list(BOND_CANDIDATES.keys())))
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
        print(f"  {ticker}: FAILED — skipping")
        continue
    df.columns = ['close']
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df['return'] = df['close'].pct_change().fillna(0)
    df['sma200'] = df['close'].rolling(SMA_PERIOD).mean()
    df['above_sma'] = df['close'] > df['sma200']
    asset_data[ticker] = df
    print(f"  {ticker}: {df.index[0].date()} to {df.index[-1].date()} ({len(df)} days)")

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


def run_blend(trend_assets, label, date_filter=None):
    """Run 85/10/5 blend. If date_filter provided, only compute on those dates."""
    W_HYDRA = 0.85
    W_TREND = 0.10
    W_GOLD = 0.05

    idx = hydra.index
    if date_filter is not None:
        mask = (idx >= date_filter[0]) & (idx <= date_filter[1])
        idx = idx[mask]

    values = [100000.0]  # normalize to 100K for fair comparison
    for i in range(1, len(idx)):
        date = idx[i]
        h_ret = hydra.loc[date, 'return']
        t_ret = get_trend_return(date, trend_assets)
        g_ret = get_gold_return(date)
        blended_ret = W_HYDRA * h_ret + W_TREND * t_ret + W_GOLD * g_ret
        values.append(values[-1] * (1 + blended_ret))

    eq = pd.Series(values, index=idx)
    daily = eq.pct_change().dropna()
    n_years = (idx[-1] - idx[0]).days / 365.25
    final_val = values[-1]

    cagr = (final_val / values[0]) ** (1 / n_years) - 1
    sharpe = daily.mean() / daily.std() * np.sqrt(252)
    sortino_denom = daily[daily < 0].std() * np.sqrt(252)
    sortino = daily.mean() * 252 / sortino_denom if sortino_denom > 0 else 0
    vol = daily.std() * np.sqrt(252)
    maxdd = ((eq - eq.cummax()) / eq.cummax()).min()

    return {
        'label': label,
        'equity': eq,
        'final': final_val,
        'cagr': cagr,
        'sharpe': sharpe,
        'sortino': sortino,
        'vol': vol,
        'maxdd': maxdd,
    }


# ── PART 1: Common period comparison (2010-01-01 to end) ──
# All 4 bonds have data by 2010
COMMON_START = '2010-01-01'
COMMON_END = '2026-12-31'
common_filter = (COMMON_START, COMMON_END)

print(f"\n{'='*85}")
print(f"EXP70 -- BOND DURATION SPECTRUM IN CATALYST TREND")
print(f"{'='*85}")

# Run all 4 variants on common period
results = {}
for bond, desc in BOND_CANDIDATES.items():
    if bond not in asset_data:
        print(f"  Skipping {bond} — no data")
        continue
    trend_assets = COMMON_ASSETS + [bond]
    label = f"{bond} {desc}"
    print(f"Running: {label}...")
    results[bond] = run_blend(trend_assets, label, date_filter=common_filter)

# HYDRA base on same period
hydra_mask = (hydra.index >= COMMON_START) & (hydra.index <= COMMON_END)
hydra_common = hydra[hydra_mask]
h_eq = pd.Series(hydra_common['value'].values / hydra_common['value'].values[0] * 100000,
                  index=hydra_common.index)
h_daily = h_eq.pct_change().dropna()
h_nyears = (h_eq.index[-1] - h_eq.index[0]).days / 365.25
h_cagr = (h_eq.iloc[-1] / h_eq.iloc[0]) ** (1 / h_nyears) - 1
h_sharpe = h_daily.mean() / h_daily.std() * np.sqrt(252)
h_maxdd = ((h_eq - h_eq.cummax()) / h_eq.cummax()).min()

# Print common period results
print(f"\n{'─'*85}")
print(f"COMMON PERIOD: {COMMON_START} to {hydra_common.index[-1].date()} ({h_nyears:.1f} years)")
print(f"Blend: 85% HYDRA + 10% Trend (SPY, EFA, [BOND], GLD, DBC) + 5% Gold")
print(f"{'─'*85}")

header = f"{'Metric':<22} {'HYDRA Base':>12}"
for bond in BOND_CANDIDATES:
    if bond in results:
        header += f" {'+ ' + bond:>13}"
print(header)
print("-" * 85)

# Final value
row = f"{'Final Value':<22} ${h_eq.iloc[-1]:>11,.0f}"
for bond in BOND_CANDIDATES:
    if bond in results:
        row += f" ${results[bond]['final']:>12,.0f}"
print(row)

# CAGR
row = f"{'CAGR':<22} {h_cagr*100:>11.2f}%"
for bond in BOND_CANDIDATES:
    if bond in results:
        row += f" {results[bond]['cagr']*100:>12.2f}%"
print(row)

# Sharpe
row = f"{'Sharpe':<22} {h_sharpe:>12.3f}"
for bond in BOND_CANDIDATES:
    if bond in results:
        row += f" {results[bond]['sharpe']:>13.3f}"
print(row)

# Sortino
row = f"{'Sortino':<22} {'N/A':>12}"
for bond in BOND_CANDIDATES:
    if bond in results:
        row += f" {results[bond]['sortino']:>13.3f}"
print(row)

# Vol
row = f"{'Volatility':<22} {'N/A':>12}"
for bond in BOND_CANDIDATES:
    if bond in results:
        row += f" {results[bond]['vol']*100:>12.2f}%"
print(row)

# MaxDD
row = f"{'Max Drawdown':<22} {h_maxdd*100:>11.2f}%"
for bond in BOND_CANDIDATES:
    if bond in results:
        row += f" {results[bond]['maxdd']*100:>12.2f}%"
print(row)

# Delta vs TLT baseline
if 'TLT' in results:
    print()
    print("DELTA vs TLT (baseline)")
    print("-" * 85)
    tlt = results['TLT']
    print(f"{'Bond':<8} {'Duration':>12} {'CAGR Δ':>10} {'Sharpe Δ':>10} {'MaxDD Δ':>10} {'Verdict':>15}")
    print("-" * 70)
    for bond, desc in BOND_CANDIDATES.items():
        if bond not in results or bond == 'TLT':
            continue
        r = results[bond]
        cagr_d = (r['cagr'] - tlt['cagr']) * 100
        sharpe_d = r['sharpe'] - tlt['sharpe']
        dd_d = (r['maxdd'] - tlt['maxdd']) * 100
        if cagr_d > 0 and sharpe_d > 0:
            verdict = f'{bond} DOMINATES'
        elif cagr_d < 0 and sharpe_d < 0:
            verdict = 'TLT DOMINATES'
        elif sharpe_d > 0:
            verdict = f'{bond} more efficient'
        else:
            verdict = 'TLT higher return'
        print(f"{bond:<8} {desc:>12} {cagr_d:>+9.2f}% {sharpe_d:>+10.3f} {dd_d:>+9.2f}% {verdict:>15}")

# ── PART 2: Bond-specific characteristics ──
print()
print("BOND CHARACTERISTICS (standalone, full history)")
print("-" * 85)
print(f"{'ETF':<8} {'Duration':>14} {'Ann Vol':>10} {'CAGR':>10} {'Above SMA200':>14} {'Start':>12}")
print("-" * 85)

common_dates = hydra.index
for bond, desc in BOND_CANDIDATES.items():
    if bond not in asset_data:
        continue
    bdf = asset_data[bond]
    bvol = bdf['return'].std() * np.sqrt(252)
    bcagr = (bdf['close'].iloc[-1] / bdf['close'].iloc[0]) ** (365.25 / (bdf.index[-1] - bdf.index[0]).days) - 1
    overlap = common_dates.intersection(bdf.index)
    above = sum(1 for d in overlap if bdf.loc[d, 'above_sma'])
    above_pct = above / len(overlap) * 100 if len(overlap) > 0 else 0
    print(f"{bond:<8} {desc:>14} {bvol*100:>9.1f}% {bcagr*100:>9.2f}% {above_pct:>12.1f}%  {bdf.index[0].date()}")

# Correlation matrix
print()
print("DAILY RETURN CORRELATION (bond ETFs)")
print("-" * 50)
bond_rets = pd.DataFrame({
    b: asset_data[b]['return'] for b in BOND_CANDIDATES if b in asset_data
}).dropna()
corr = bond_rets.corr()
print(corr.round(3).to_string())

# ── PART 3: Period breakdown on common period ──
periods = {
    '2010-2019 (Recovery)':    ('2010-01-01', '2019-12-31'),
    '2020 (COVID)':            ('2020-01-01', '2020-12-31'),
    '2021-2023 (Rate Hikes)':  ('2021-01-01', '2023-12-31'),
    '2024-2026 (Recent)':      ('2024-01-01', '2026-12-31'),
}

print()
print("PERIOD BREAKDOWN (CAGR on common period)")
print("-" * 85)
header = f"{'Period':<28}"
for bond in BOND_CANDIDATES:
    if bond in results:
        header += f" {'+ ' + bond:>12}"
header += f" {'Best':>8}"
print(header)
print("-" * 85)

for pname, (pstart, pend) in periods.items():
    row = f"{pname:<28}"
    best_bond = None
    best_cagr = -999
    for bond in BOND_CANDIDATES:
        if bond not in results:
            continue
        eq = results[bond]['equity']
        mask = (eq.index >= pstart) & (eq.index <= pend)
        if mask.sum() < 20:
            row += f" {'N/A':>12}"
            continue
        peq = eq[mask]
        py = (peq.index[-1] - peq.index[0]).days / 365.25
        if py < 0.1:
            row += f" {'N/A':>12}"
            continue
        pcagr = (peq.iloc[-1] / peq.iloc[0]) ** (1 / py) - 1
        row += f" {pcagr*100:>11.2f}%"
        if pcagr > best_cagr:
            best_cagr = pcagr
            best_bond = bond
    row += f" {best_bond:>8}" if best_bond else ""
    print(row)

# ── PART 4: Yearly comparison ──
print()
print("YEARLY COMPARISON (common period)")
print("-" * 85)
header = f"{'Year':<6}"
for bond in BOND_CANDIDATES:
    if bond in results:
        header += f" {'+ ' + bond:>10}"
header += f" {'Best':>8}"
print(header)
print("-" * 60)

# Build yearly returns
yearly_data = {}
for bond in BOND_CANDIDATES:
    if bond not in results:
        continue
    yr = results[bond]['equity'].resample('YE').last().pct_change().dropna() * 100
    yearly_data[bond] = yr

if yearly_data:
    all_years = sorted(set().union(*[set(yr.index) for yr in yearly_data.values()]))
    bond_wins = {b: 0 for b in yearly_data}

    for yr_idx in all_years:
        row = f"{yr_idx.year:<6}"
        best_bond = None
        best_ret = -999
        for bond in BOND_CANDIDATES:
            if bond not in yearly_data:
                continue
            if yr_idx in yearly_data[bond].index:
                ret = yearly_data[bond][yr_idx]
                row += f" {ret:>9.1f}%"
                if ret > best_ret:
                    best_ret = ret
                    best_bond = bond
            else:
                row += f" {'N/A':>10}"
        if best_bond:
            bond_wins[best_bond] += 1
        row += f" {best_bond:>8}" if best_bond else ""
        print(row)

    print()
    print("Win count:")
    for bond, wins in sorted(bond_wins.items(), key=lambda x: -x[1]):
        print(f"  {bond}: {wins}/{len(all_years)} years")

# ── VERDICT ──
print()
print("=" * 85)
print("VERDICT (common period 2010-2026):")
if 'TLT' in results:
    tlt = results['TLT']
    ranked = sorted(
        [(b, r) for b, r in results.items()],
        key=lambda x: x[1]['sharpe'], reverse=True
    )
    print(f"\n  Ranked by Sharpe ratio:")
    for i, (bond, r) in enumerate(ranked):
        marker = " <-- CURRENT" if bond == 'TLT' else ""
        print(f"  {i+1}. {bond:<6} Sharpe={r['sharpe']:.3f}  CAGR={r['cagr']*100:.2f}%  MaxDD={r['maxdd']*100:.2f}%{marker}")

    best_bond, best_r = ranked[0]
    if best_bond == 'TLT':
        print(f"\n  >> TLT remains the best choice. No change needed.")
    else:
        delta_cagr = (best_r['cagr'] - tlt['cagr']) * 100
        delta_sharpe = best_r['sharpe'] - tlt['sharpe']
        print(f"\n  >> {best_bond} beats TLT: CAGR {delta_cagr:+.2f}%, Sharpe {delta_sharpe:+.3f}")
        print(f"  >> Consider swapping TLT -> {best_bond} in catalyst_signals.py")
print("=" * 85)

# Save
results_out = pd.DataFrame({'date': hydra_common.index})
results_out.set_index('date', inplace=True)
for bond in BOND_CANDIDATES:
    if bond in results:
        eq = results[bond]['equity']
        results_out[f'{bond.lower()}_blend'] = eq.reindex(results_out.index)
results_out.to_csv(os.path.join(bt_dir, 'exp70_bond_duration_daily.csv'))

summary = {
    'experiment': 'EXP70 -- Bond Duration Spectrum in Catalyst Trend',
    'common_period': f'{COMMON_START} to {hydra_common.index[-1].date()}',
    'bonds': {},
}
for bond in BOND_CANDIDATES:
    if bond in results:
        r = results[bond]
        summary['bonds'][bond] = {
            'description': BOND_CANDIDATES[bond],
            'cagr': round(r['cagr'] * 100, 2),
            'sharpe': round(r['sharpe'], 3),
            'sortino': round(r['sortino'], 3),
            'max_dd': round(r['maxdd'] * 100, 2),
            'vol': round(r['vol'] * 100, 2),
            'final': round(r['final'], 2),
        }
with open(os.path.join(bt_dir, 'exp70_bond_duration_summary.json'), 'w') as f:
    json.dump(summary, f, indent=2)

print(f"\nSaved: exp70_bond_duration_daily.csv + exp70_bond_duration_summary.json")
