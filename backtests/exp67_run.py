"""
EXP67: Correlation & Portfolio Analysis — HYDRA vs Alternative Asset Classes
"""

import pandas as pd
import numpy as np
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

# ── Load HYDRA ──────────────────────────────────────────────────────────────
hydra = pd.read_csv(r'C:\Users\caslu\Desktop\NuevoProyecto\backtests\hydra_clean_daily.csv',
                     parse_dates=['date'], index_col='date')
hydra.columns = ['hydra_value']
hydra['hydra_ret'] = hydra['hydra_value'].pct_change()

# ── Identify HYDRA drawdown periods ────────────────────────────────────────
running_max = hydra['hydra_value'].cummax()
drawdown = (hydra['hydra_value'] - running_max) / running_max
hydra['in_drawdown'] = drawdown < -0.02  # in drawdown when >2% below peak

# ── HYDRA standalone stats ─────────────────────────────────────────────────
hydra_annual_ret = hydra['hydra_ret'].mean() * 252
hydra_annual_vol = hydra['hydra_ret'].std() * np.sqrt(252)
hydra_sharpe = hydra_annual_ret / hydra_annual_vol
hydra_max_dd = drawdown.min()

print(f"HYDRA standalone: Sharpe={hydra_sharpe:.3f}, Annual={hydra_annual_ret:.1%}, MaxDD={hydra_max_dd:.1%}")
print(f"HYDRA drawdown days: {hydra['in_drawdown'].sum()} / {len(hydra)}")
print()

# ── ETFs to analyze ────────────────────────────────────────────────────────
tickers = {
    'GLD':  'Gold',
    'TLT':  '30Y Treasuries',
    'IEF':  '10Y Treasuries',
    'DBC':  'Broad Commodities',
    'VNQ':  'REITs',
    'HYG':  'High Yield Bonds',
    'DBMF': 'Managed Futures (iM)',
    'KMLM': 'KFA Mount Lucas MF',
    'CTA':  'Simplify MF',
    'BTAL': 'Anti-Beta L/S',
    'QAI':  'Hedge Fund Replication',
    'BIL':  'T-Bills',
    'USFR': 'Floating Rate T-Bills',
    'TIP':  'TIPS Inflation Prot',
    'PDBC': 'Commodities Alt',
    'GSG':  'iShares Commodities',
}

# ── Download all ETFs ──────────────────────────────────────────────────────
print("Downloading ETF data...")
all_data = {}
for ticker in tickers:
    try:
        df = yf.download(ticker, start='2004-01-01', end='2026-03-15', progress=False, auto_adjust=True)
        if df is not None and len(df) > 100:
            # Handle both single and multi-level columns
            if isinstance(df.columns, pd.MultiIndex):
                close = df['Close'].iloc[:, 0]
            else:
                close = df['Close']
            all_data[ticker] = close
            print(f"  {ticker}: {len(close)} days ({close.index[0].strftime('%Y-%m-%d')} to {close.index[-0].strftime('%Y-%m-%d')})")
        else:
            print(f"  {ticker}: SKIPPED (insufficient data)")
    except Exception as e:
        print(f"  {ticker}: ERROR - {e}")

print(f"\nSuccessfully downloaded {len(all_data)} / {len(tickers)} ETFs\n")

# ── Analysis ───────────────────────────────────────────────────────────────
results = []

for ticker, name in tickers.items():
    if ticker not in all_data:
        continue

    # Align dates
    alt_prices = all_data[ticker].to_frame('alt_price')
    alt_prices.index = alt_prices.index.tz_localize(None)  # remove tz if present

    merged = hydra[['hydra_ret', 'hydra_value', 'in_drawdown']].join(alt_prices, how='inner').dropna()
    merged['alt_ret'] = merged['alt_price'].pct_change()
    merged = merged.dropna()

    if len(merged) < 100:
        print(f"  {ticker}: SKIPPED (only {len(merged)} overlapping days)")
        continue

    overlap_start = merged.index[0].strftime('%Y-%m-%d')
    overlap_end = merged.index[-1].strftime('%Y-%m-%d')
    n_days = len(merged)

    # 1. Correlation with HYDRA daily returns
    corr_full = merged['hydra_ret'].corr(merged['alt_ret'])

    # 2. Correlation during HYDRA drawdown periods
    dd_data = merged[merged['in_drawdown']]
    corr_drawdown = dd_data['hydra_ret'].corr(dd_data['alt_ret']) if len(dd_data) > 30 else np.nan

    # 3. Standalone Sharpe ratio of the alternative
    alt_annual_ret = merged['alt_ret'].mean() * 252
    alt_annual_vol = merged['alt_ret'].std() * np.sqrt(252)
    alt_sharpe = alt_annual_ret / alt_annual_vol if alt_annual_vol > 0 else 0

    # Alt max drawdown
    alt_cumret = (1 + merged['alt_ret']).cumprod()
    alt_running_max = alt_cumret.cummax()
    alt_max_dd = ((alt_cumret - alt_running_max) / alt_running_max).min()

    # 4. Hypothetical 85% HYDRA + 15% Alternative blend
    blend_ret = 0.85 * merged['hydra_ret'] + 0.15 * merged['alt_ret']
    blend_annual_ret = blend_ret.mean() * 252
    blend_annual_vol = blend_ret.std() * np.sqrt(252)
    blend_sharpe = blend_annual_ret / blend_annual_vol if blend_annual_vol > 0 else 0

    # Pure HYDRA stats over same period
    hydra_period_ret = merged['hydra_ret'].mean() * 252
    hydra_period_vol = merged['hydra_ret'].std() * np.sqrt(252)
    hydra_period_sharpe = hydra_period_ret / hydra_period_vol if hydra_period_vol > 0 else 0

    # 5. Max drawdown comparison (blend vs pure HYDRA over same period)
    hydra_cumret = (1 + merged['hydra_ret']).cumprod()
    hydra_running_max = hydra_cumret.cummax()
    hydra_period_max_dd = ((hydra_cumret - hydra_running_max) / hydra_running_max).min()

    blend_cumret = (1 + blend_ret).cumprod()
    blend_running_max = blend_cumret.cummax()
    blend_max_dd = ((blend_cumret - blend_running_max) / blend_running_max).min()

    dd_reduction = hydra_period_max_dd - blend_max_dd  # positive = blend is better
    dd_reduction_pct = (dd_reduction / abs(hydra_period_max_dd)) * 100 if hydra_period_max_dd != 0 else 0

    sharpe_improvement = blend_sharpe - hydra_period_sharpe

    # Composite score: weighted ranking metric
    # Higher = better diversifier
    composite = (
        -corr_full * 0.2 +           # lower correlation is better
        -corr_drawdown * 0.3 +        # lower drawdown correlation is critical
        sharpe_improvement * 2.0 +    # Sharpe improvement matters most
        dd_reduction_pct / 100 * 0.3  # DD reduction bonus
    ) if not np.isnan(corr_drawdown) else 0

    row = {
        'ticker': ticker,
        'name': name,
        'overlap_start': overlap_start,
        'overlap_end': overlap_end,
        'n_overlap_days': n_days,
        'corr_full': round(corr_full, 4),
        'corr_drawdown': round(corr_drawdown, 4) if not np.isnan(corr_drawdown) else 'N/A',
        'alt_sharpe': round(alt_sharpe, 3),
        'alt_annual_ret': round(alt_annual_ret, 4),
        'alt_annual_vol': round(alt_annual_vol, 4),
        'alt_max_dd': round(alt_max_dd, 4),
        'hydra_period_sharpe': round(hydra_period_sharpe, 3),
        'blend_sharpe_85_15': round(blend_sharpe, 3),
        'sharpe_improvement': round(sharpe_improvement, 4),
        'hydra_period_max_dd': round(hydra_period_max_dd, 4),
        'blend_max_dd': round(blend_max_dd, 4),
        'dd_reduction_abs': round(dd_reduction, 4),
        'dd_reduction_pct': round(dd_reduction_pct, 2),
        'composite_score': round(composite, 4),
    }
    results.append(row)

    dd_corr_display = f"{corr_drawdown:+.3f}" if not np.isnan(corr_drawdown) else 'N/A'
    print(f"  {ticker:5s} ({name:25s}): corr={corr_full:+.3f}  dd_corr={dd_corr_display:>6s}  "
          f"alt_sharpe={alt_sharpe:.2f}  blend_sharpe={blend_sharpe:.3f}  "
          f"sharpe_delta={sharpe_improvement:+.4f}  dd_reduction={dd_reduction_pct:+.1f}%")

# ── Sort by composite score and save ───────────────────────────────────────
results_df = pd.DataFrame(results)
results_df = results_df.sort_values('composite_score', ascending=False).reset_index(drop=True)
results_df.index = results_df.index + 1  # rank from 1
results_df.index.name = 'rank'

output_path = r'C:\Users\caslu\Desktop\NuevoProyecto\backtests\exp67_correlation_analysis.csv'
results_df.to_csv(output_path)
print(f"\n{'='*100}")
print(f"Results saved to {output_path}")
print(f"{'='*100}\n")

# ── Print Report ───────────────────────────────────────────────────────────
print("=" * 110)
print("EXP67: HYDRA PORTFOLIO DIVERSIFICATION ANALYSIS — RANKING BY COMPOSITE SCORE")
print("=" * 110)
print(f"\nHYDRA Standalone (full history): Sharpe={hydra_sharpe:.3f}, Annual Return={hydra_annual_ret:.1%}, Max DD={hydra_max_dd:.1%}\n")

print(f"{'Rank':<5} {'Ticker':<7} {'Name':<27} {'Corr':>6} {'DD Corr':>8} {'AltShp':>7} {'BlendShp':>9} {'ShpDelta':>9} {'DD Red%':>8} {'Score':>7}")
print("-" * 110)

for idx, row in results_df.iterrows():
    dd_corr_str = f"{row['corr_drawdown']:+.3f}" if row['corr_drawdown'] != 'N/A' else '  N/A'
    print(f"{idx:<5} {row['ticker']:<7} {row['name']:<27} {row['corr_full']:+.3f} {dd_corr_str:>8} "
          f"{row['alt_sharpe']:>7.2f} {row['blend_sharpe_85_15']:>9.3f} {row['sharpe_improvement']:>+9.4f} "
          f"{row['dd_reduction_pct']:>+7.1f}% {row['composite_score']:>7.3f}")

print("\n" + "=" * 110)
print("INTERPRETATION GUIDE:")
print("  Corr         = Correlation of daily returns with HYDRA (lower/negative = better diversifier)")
print("  DD Corr      = Correlation during HYDRA drawdown periods (negative = hedges when HYDRA falls)")
print("  AltShp       = Standalone Sharpe ratio of the alternative")
print("  BlendShp     = Sharpe of 85% HYDRA + 15% Alternative")
print("  ShpDelta     = Sharpe improvement vs pure HYDRA over same period")
print("  DD Red%      = Max drawdown reduction percentage (positive = blend has smaller drawdown)")
print("  Score        = Composite ranking score (higher = better diversifier for HYDRA)")
print("=" * 110)

# ── Top recommendations ───────────────────────────────────────────────────
print("\n" + "=" * 110)
print("TOP RECOMMENDATIONS")
print("=" * 110)
top3 = results_df.head(3)
for idx, row in top3.iterrows():
    print(f"\n  #{idx} {row['ticker']} ({row['name']})")
    print(f"     Correlation: {row['corr_full']:+.3f} (full) / {row['corr_drawdown'] if row['corr_drawdown'] != 'N/A' else 'N/A'} (drawdowns)")
    print(f"     Adding 15% improves Sharpe by {row['sharpe_improvement']:+.4f} (to {row['blend_sharpe_85_15']:.3f})")
    print(f"     Max drawdown reduction: {row['dd_reduction_pct']:+.1f}%")

# Worst diversifiers
print(f"\n  WORST DIVERSIFIERS (most correlated / least helpful):")
bottom2 = results_df.tail(2)
for idx, row in bottom2.iterrows():
    print(f"     {row['ticker']} ({row['name']}): corr={row['corr_full']:+.3f}, sharpe_delta={row['sharpe_improvement']:+.4f}")

print()
