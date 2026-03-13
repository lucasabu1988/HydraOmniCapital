"""
Generate accurate fund comparison data for the HYDRA dashboard.

Downloads real ETF/fund daily prices from yfinance, computes annual returns,
growth of $100K, crisis performance, and summary metrics.

Output: backtests/fund_comparison_data.json
"""

import json
import os
import sys
import numpy as np
import pandas as pd

# ── yfinance import ──────────────────────────────────────────────────────────
try:
    import yfinance as yf
    _HAS_YF = True
except ImportError:
    _HAS_YF = False
    print("WARNING: yfinance not installed. Using cached data only.")

# ── Paths ────────────────────────────────────────────────────────────────────
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKTESTS_DIR = os.path.join(PROJECT_ROOT, 'backtests')
OUTPUT_JSON = os.path.join(BACKTESTS_DIR, 'fund_comparison_data.json')

# ── Fund definitions ─────────────────────────────────────────────────────────
# Each fund: ticker, display name, type, inception year, expense ratio, AUM, description
FUNDS = [
    {
        'ticker': 'HYDRA_NET',
        'name': 'HYDRA (Net)',
        'type': 'Backtest (Net)',
        'inception': 2000,
        'expense_ratio': 1.00,  # 1.0% annual execution costs
        'aum': None,
        'description': 'HYDRA neto despues de 1.0% costos anuales de ejecucion',
        'description_en': 'HYDRA net after 1.0% annual execution costs',
        'highlight': True,
        'source': 'csv_net',
    },
    {
        'ticker': 'SPY',
        'name': 'S&P 500 (SPY)',
        'type': 'Benchmark',
        'inception': 2000,
        'expense_ratio': 0.09,
        'aum': '$570B',
        'description': 'Benchmark pasivo — el mercado general',
        'description_en': 'Passive benchmark — the broad market',
        'highlight': False,
        'source': 'yfinance',
    },
    {
        'ticker': 'AMOMX',
        'name': 'AQR Momentum (AMOMX)',
        'type': 'Mutual Fund',
        'inception': 2009,
        'expense_ratio': 0.35,
        'aum': '$5.2B',
        'description': 'AQR Large Cap Momentum — el fondo momentum mas reconocido del mundo',
        'description_en': 'AQR Large Cap Momentum — world\'s most recognized momentum fund',
        'highlight': False,
        'source': 'yfinance',
    },
    {
        'ticker': 'MTUM',
        'name': 'iShares MTUM',
        'type': 'ETF',
        'inception': 2013,
        'expense_ratio': 0.15,
        'aum': '$10.8B',
        'description': 'iShares MSCI USA Momentum Factor ETF — el ETF momentum mas grande',
        'description_en': 'iShares MSCI USA Momentum Factor ETF — largest momentum ETF',
        'highlight': False,
        'source': 'yfinance',
    },
    {
        'ticker': 'QQQ',
        'name': 'Nasdaq 100 (QQQ)',
        'type': 'Benchmark',
        'inception': 2000,
        'expense_ratio': 0.20,
        'aum': '$310B',
        'description': 'Invesco QQQ — proxy de crecimiento/tech concentrado',
        'description_en': 'Invesco QQQ — concentrated growth/tech proxy',
        'highlight': False,
        'source': 'yfinance',
    },
    {
        'ticker': 'BRK-B',
        'name': 'Berkshire Hathaway (BRK.B)',
        'type': 'Reference',
        'inception': 2000,
        'expense_ratio': None,
        'aum': '$1.1T',
        'description': 'Warren Buffett — el mejor inversor activo como referencia',
        'description_en': 'Warren Buffett — best active investor as reference',
        'highlight': False,
        'source': 'yfinance',
    },
]

# ── Crisis periods ───────────────────────────────────────────────────────────
CRISIS_PERIODS = [
    {'id': 'dotcom', 'name': 'Dot-com Crash', 'period': '2000-2002',
     'start': '2000-03-24', 'end': '2002-10-09'},
    {'id': 'gfc', 'name': 'Crisis Financiera', 'period': '2007-2009',
     'start': '2007-10-09', 'end': '2009-03-09'},
    {'id': 'covid', 'name': 'COVID-19', 'period': 'Feb-Mar 2020',
     'start': '2020-02-19', 'end': '2020-03-23'},
    {'id': 'rate_hike', 'name': 'Suba de Tasas', 'period': '2022',
     'start': '2022-01-03', 'end': '2022-10-12'},
    {'id': 'tariff', 'name': 'Guerra Arancelaria', 'period': '2025 YTD',
     'start': '2025-02-19', 'end': '2025-12-31'},
]


def load_hydra_daily():
    """Load HYDRA daily portfolio values from CSV."""
    # Try multiple possible CSV files
    candidates = [
        os.path.join(BACKTESTS_DIR, 'hydra_corrected_daily.csv'),
        os.path.join(BACKTESTS_DIR, 'v8_compass_daily.csv'),
        os.path.join(BACKTESTS_DIR, 'v84_compass_daily.csv'),
        os.path.join(BACKTESTS_DIR, 'v84_overlay_daily.csv'),
    ]
    for path in candidates:
        if os.path.exists(path):
            df = pd.read_csv(path, parse_dates=['date'])
            val_col = 'portfolio_value' if 'portfolio_value' in df.columns else 'value'
            df = df[['date', val_col]].copy()
            df.columns = ['date', 'value']
            df = df.sort_values('date').reset_index(drop=True)
            print(f"  Loaded HYDRA from {os.path.basename(path)}: {len(df)} rows, "
                  f"{df['date'].iloc[0].strftime('%Y-%m-%d')} to {df['date'].iloc[-1].strftime('%Y-%m-%d')}")
            return df
    print("  ERROR: No HYDRA daily CSV found!")
    return None


def download_fund_prices(ticker, start='1999-12-31', end='2026-03-15'):
    """Download daily adjusted close prices from yfinance."""
    if not _HAS_YF:
        return None
    try:
        data = yf.download(ticker, start=start, end=end, auto_adjust=True, progress=False)
        if data.empty:
            print(f"  WARNING: No data for {ticker}")
            return None
        # Handle multi-level columns from yfinance
        if isinstance(data.columns, pd.MultiIndex):
            data = data.droplevel(1, axis=1)
        df = data[['Close']].reset_index()
        df.columns = ['date', 'value']
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').dropna().reset_index(drop=True)
        print(f"  Downloaded {ticker}: {len(df)} rows, "
              f"{df['date'].iloc[0].strftime('%Y-%m-%d')} to {df['date'].iloc[-1].strftime('%Y-%m-%d')}")
        return df
    except Exception as e:
        print(f"  ERROR downloading {ticker}: {e}")
        return None


def compute_annual_returns(df):
    """Compute calendar-year returns from daily prices."""
    if df is None or df.empty:
        return {}
    df = df.copy()
    df['year'] = df['date'].dt.year
    annual = {}
    for year, grp in df.groupby('year'):
        start_val = float(grp['value'].iloc[0])
        end_val = float(grp['value'].iloc[-1])
        if start_val > 0 and len(grp) > 20:  # need at least ~1 month of data
            ret = ((end_val / start_val) - 1) * 100
            annual[int(year)] = round(ret, 2)
    return annual


def compute_crisis_return(df, start_date, end_date):
    """Compute peak-to-trough return during a crisis period."""
    if df is None or df.empty:
        return None
    mask = (df['date'] >= start_date) & (df['date'] <= end_date)
    crisis_df = df[mask]
    if len(crisis_df) < 2:
        return None
    start_val = float(crisis_df['value'].iloc[0])
    min_val = float(crisis_df['value'].min())
    if start_val > 0:
        return round(((min_val / start_val) - 1) * 100, 1)
    return None


def compute_metrics(df, annual_returns):
    """Compute CAGR, Sharpe, max drawdown, volatility, cumulative return."""
    if df is None or df.empty:
        return {}

    values = df['value'].values
    first_val = float(values[0])
    last_val = float(values[-1])
    days = (df['date'].iloc[-1] - df['date'].iloc[0]).days
    years = days / 365.25

    # CAGR
    cagr = (pow(last_val / first_val, 1 / years) - 1) * 100 if years > 0 and first_val > 0 else 0

    # Daily returns for Sharpe and volatility
    daily_rets = pd.Series(values).pct_change().dropna()
    ann_vol = float(daily_rets.std() * np.sqrt(252) * 100)
    ann_mean = float(daily_rets.mean() * 252 * 100)
    sharpe = ann_mean / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    peak = np.maximum.accumulate(values)
    dd = (values - peak) / peak * 100
    max_dd = float(dd.min())

    # Cumulative return
    cumulative = ((last_val / first_val) - 1) * 100

    return {
        'cagr': round(cagr, 2),
        'sharpe': round(sharpe, 2),
        'max_dd': round(max_dd, 1),
        'volatility': round(ann_vol, 1),
        'cumulative': round(cumulative, 0),
        'years': round(years, 1),
    }


def build_growth_series(df, start_year=2000):
    """Build monthly growth of $100K series for the chart."""
    if df is None or df.empty:
        return {}
    df = df.copy()
    # Filter from start_year
    df = df[df['date'].dt.year >= start_year].reset_index(drop=True)
    if df.empty:
        return {}

    first_val = float(df['value'].iloc[0])
    scale = 100000.0 / first_val

    # Resample to month-end for chart (less data points)
    df = df.set_index('date')
    monthly = df.resample('ME').last()
    monthly = monthly.dropna()

    series = {}
    for date, row in monthly.iterrows():
        key = date.strftime('%Y-%m')
        series[key] = round(float(row['value']) * scale, 0)

    return series


def apply_net_cost(df, annual_cost_pct=2.5):
    """Create a net-of-costs version of daily portfolio values."""
    if df is None or df.empty:
        return None
    df = df.copy()
    first_date = df['date'].iloc[0]
    days_elapsed = (df['date'] - first_date).dt.days.values
    years_elapsed = days_elapsed / 365.25
    daily_cost_factor = (1 - annual_cost_pct / 100) ** years_elapsed
    # Adjust: net = gross * (cost_factor_at_t / cost_factor_at_0)
    # Since cost_factor at t=0 is 1.0, this simplifies
    df['value'] = df['value'] * daily_cost_factor
    return df


def main():
    print("=" * 60)
    print("FUND COMPARISON DATA GENERATOR")
    print("=" * 60)

    all_daily = {}
    fund_results = []

    # ── Step 1: Load/download all price data ─────────────────────────────
    print("\n── Loading price data ──")

    hydra_df = load_hydra_daily()
    if hydra_df is not None:
        all_daily['HYDRA'] = hydra_df
        all_daily['HYDRA_NET'] = apply_net_cost(hydra_df, 1.0)

    yf_tickers = [f['ticker'] for f in FUNDS if f['source'] == 'yfinance']
    for ticker in yf_tickers:
        df = download_fund_prices(ticker)
        if df is not None:
            all_daily[ticker] = df

    # ── Step 2: Compute metrics for each fund ────────────────────────────
    print("\n── Computing metrics ──")

    for fund_def in FUNDS:
        ticker = fund_def['ticker']
        df = all_daily.get(ticker)

        if df is None:
            print(f"  SKIP {ticker}: no data")
            continue

        annual_returns = compute_annual_returns(df)
        metrics = compute_metrics(df, annual_returns)
        growth = build_growth_series(df, start_year=2000)

        # Crisis returns
        crisis_returns = {}
        for crisis in CRISIS_PERIODS:
            cr = compute_crisis_return(df, crisis['start'], crisis['end'])
            if cr is not None:
                crisis_returns[crisis['id']] = {
                    'period': crisis['period'],
                    'return': cr,
                }

        fund_entry = {
            'id': ticker.lower().replace('-', '_'),
            'name': fund_def['name'],
            'type': fund_def['type'],
            'inception': fund_def['inception'],
            'description': fund_def['description'],
            'description_en': fund_def['description_en'],
            'cagr': metrics.get('cagr', 0),
            'sharpe': metrics.get('sharpe', 0),
            'max_dd': metrics.get('max_dd', 0),
            'volatility': metrics.get('volatility', 0),
            'cumulative': metrics.get('cumulative', 0),
            'expense_ratio': fund_def['expense_ratio'],
            'aum': fund_def['aum'],
            'highlight': fund_def['highlight'],
            'annual_returns': annual_returns,
            'crisis_returns': crisis_returns,
            'growth_100k': growth,
        }
        fund_results.append(fund_entry)

        print(f"  {ticker}: CAGR={metrics.get('cagr', '?')}%, "
              f"Sharpe={metrics.get('sharpe', '?')}, "
              f"MaxDD={metrics.get('max_dd', '?')}%, "
              f"Years={len(annual_returns)}")

    # ── Step 3: Build output ─────────────────────────────────────────────
    output = {
        'generated': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'),
        'funds': fund_results,
        'crisis_periods': [
            {'id': c['id'], 'name': c['name'], 'period': c['period']}
            for c in CRISIS_PERIODS
        ],
        'notes': [
            'HYDRA Net: backtest 2000-2026 minus 1.0% annual execution costs (MOC slippage + commissions)',
            'All ETF/fund returns are TOTAL RETURNS (dividends reinvested) from yfinance adjusted close prices',
            'Crisis returns: peak-to-trough drawdown during each crisis period',
            'AQR AMOMX: inception Jul 2009 — AQR Large Cap Momentum Style Fund',
            'iShares MTUM: inception Apr 2013 — MSCI USA Momentum Factor',
            'QQQ: inception 1999 — Nasdaq 100, growth/tech benchmark (not pure momentum)',
            'BRK.B: Berkshire Hathaway — best active investor reference (not momentum)',
            'HYDRA es un backtest; fondos reales tienen retornos realizados — no son directamente comparables',
            f'Data generated: {pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")}',
        ],
    }

    # ── Step 4: Save ─────────────────────────────────────────────────────
    os.makedirs(BACKTESTS_DIR, exist_ok=True)
    with open(OUTPUT_JSON, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n── Saved to {OUTPUT_JSON} ({os.path.getsize(OUTPUT_JSON) / 1024:.1f} KB) ──")

    # Print summary table
    print("\n" + "=" * 90)
    print(f"{'Fund':<35} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>8} {'Vol':>8} {'Since':>6}")
    print("-" * 90)
    for f in fund_results:
        print(f"{f['name']:<35} {f['cagr']:>7.1f}% {f['sharpe']:>7.2f} {f['max_dd']:>7.1f}% {f['volatility']:>7.1f}% {f['inception']:>6}")
    print("=" * 90)


if __name__ == '__main__':
    main()
