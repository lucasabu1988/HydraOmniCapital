"""
Experiment #62: Survivorship-Corrected Backtest with Merged Universe (924 tickers)
==================================================================================
Uses the EXACT COMPASS v8.2 production algorithm (imported, not copied).
Loads pre-downloaded data from data_sources/merged_universe/ (924 parquet files).
Builds point-in-time S&P 500 annual top-40 from fja05680/sp500 snapshots.

Usage: python experiments/exp62_survivorship_merged.py
"""
import os
import sys
import io
import numpy as np
import pandas as pd
import requests
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from omnicapital_v8_compass import (
    run_backtest, calculate_metrics, download_spy, download_cash_yield,
    BROAD_POOL, TOP_N, INITIAL_CAPITAL
)

MERGED_DIR = os.path.join(BASE_DIR, 'data_sources', 'merged_universe')
SNAPSHOT_CACHE = os.path.join(BASE_DIR, 'data_cache', 'sp500_snapshots.csv')


def load_merged_universe():
    print(f"Loading merged universe from {MERGED_DIR}...")
    data = {}
    corrupted = []
    files = [f for f in os.listdir(MERGED_DIR) if f.endswith('.parquet')]
    for f in files:
        ticker = f.replace('.parquet', '')
        try:
            df = pd.read_parquet(os.path.join(MERGED_DIR, f))
            if len(df) < 10 or 'Close' not in df.columns:
                continue
            # Ensure timezone-naive datetime index
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            # Trim to 2000+ (match production backtest period)
            df = df[df.index >= '2000-01-01']
            if len(df) < 10:
                continue
            # Sanitize corrupted data
            # 1. Max price filter: no S&P 500 stock exceeds $5000/share
            if df['Close'].max() > 5000:
                corrupted.append((ticker, f'max price ${df["Close"].max():,.0f}'))
                continue
            # 2. Near-zero prices (mixed ticker data)
            near_zero = (df['Close'] < 0.01).sum()
            if near_zero > 5:
                corrupted.append((ticker, f'{near_zero} near-zero prices'))
                continue
            # 3. Daily return filter
            returns = df['Close'].pct_change().abs()
            bad_rows = returns > 0.80
            if bad_rows.sum() > 0:
                if bad_rows.sum() / len(df) > 0.02:
                    corrupted.append((ticker, f'{bad_rows.sum()} bad returns ({bad_rows.sum()/len(df)*100:.1f}%)'))
                    continue
                bad_rows.iloc[0] = False
                df = df[~bad_rows]
            if len(df) < 10:
                continue
            data[ticker] = df
        except Exception:
            pass
    print(f"  Loaded {len(data)} tickers from merged universe")
    if corrupted:
        print(f"  Removed {len(corrupted)} corrupted tickers:")
        for t, reason in corrupted[:20]:
            print(f"    {t}: {reason}")
    return data


def load_sp500_snapshots():
    if os.path.exists(SNAPSHOT_CACHE):
        print("[Cache] Loading S&P 500 daily snapshots...")
        df = pd.read_csv(SNAPSHOT_CACHE, parse_dates=['date'])
        print(f"  {len(df)} snapshot dates loaded")
        return df

    print("[Download] Fetching S&P 500 daily snapshots from GitHub...")
    api_url = 'https://api.github.com/repos/fja05680/sp500/contents'
    r = requests.get(api_url, timeout=30)
    files = r.json()
    csv_files = [f['name'] for f in files if f['name'].endswith('.csv') and 'Historical' in f['name']]
    if not csv_files:
        raise RuntimeError("Cannot find S&P 500 constituent CSV on GitHub")

    fname = csv_files[0]
    dl_url = f'https://raw.githubusercontent.com/fja05680/sp500/master/{requests.utils.quote(fname)}'
    r = requests.get(dl_url, timeout=30)
    r.raise_for_status()
    raw = pd.read_csv(io.StringIO(r.text))
    raw['date'] = pd.to_datetime(raw['date'])
    raw = raw.sort_values('date').reset_index(drop=True)

    os.makedirs(os.path.dirname(SNAPSHOT_CACHE), exist_ok=True)
    raw.to_csv(SNAPSHOT_CACHE, index=False)
    print(f"  Downloaded: {fname} ({len(raw)} rows)")
    return raw


def get_sp500_members_on_date(snapshots, date):
    valid = snapshots[snapshots['date'] <= date]
    if valid.empty:
        return set()
    latest = valid.iloc[-1]
    return set(t.strip() for t in str(latest['tickers']).split(',') if t.strip())


def compute_annual_top40_pit(price_data, snapshots):
    """Point-in-time annual top-40: only stocks in S&P 500 AT THAT TIME."""
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}
    for year in years:
        ref_date = pd.Timestamp(f'{year}-01-01')
        sp500_members = get_sp500_members_on_date(snapshots, ref_date)

        ranking_end = pd.Timestamp(f'{year}-01-01')
        ranking_start = pd.Timestamp(f'{year-1}-01-01')

        scores = {}
        for symbol in sp500_members:
            if symbol not in price_data:
                continue
            df = price_data[symbol]
            mask = (df.index >= ranking_start) & (df.index < ranking_end)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dollar_vol = (window['Close'] * window['Volume']).mean()
            scores[symbol] = dollar_vol

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_n = [s for s, _ in ranked[:TOP_N]]
        annual_universe[year] = top_n

        broad_only = [s for s in top_n if s in BROAD_POOL]
        historical_only = [s for s in top_n if s not in BROAD_POOL]
        print(f"  {year}: S&P500={len(sp500_members)}, with data={len(scores)}, "
              f"Top-{TOP_N} | {len(broad_only)} current + {len(historical_only)} historical")
        if historical_only:
            print(f"         Historical: {historical_only}")

    return annual_universe


if __name__ == "__main__":
    print("=" * 80)
    print("EXPERIMENT #62: SURVIVORSHIP-CORRECTED BACKTEST (MERGED UNIVERSE)")
    print("=" * 80)
    print(f"Algorithm: COMPASS v8.2 (LOCKED, imported from omnicapital_v8_compass.py)")
    print(f"Data: merged_universe/ (924 tickers from yfinance + tiingo + production)")
    print()

    # Step 1: Load data
    print("--- STEP 1: Load Data ---")
    price_data = load_merged_universe()

    # Also load production data (SPY already in merged, but need it separately)
    spy_data = download_spy()
    if spy_data.index.tz is not None:
        spy_data.index = spy_data.index.tz_localize(None)
    print(f"SPY: {len(spy_data)} trading days")

    cash_yield_daily = download_cash_yield()

    # Step 2: Load S&P 500 snapshots
    print("\n--- STEP 2: S&P 500 Snapshots ---")
    snapshots = load_sp500_snapshots()

    all_historical = set()
    for tickers_str in snapshots['tickers']:
        all_historical.update(t.strip() for t in str(tickers_str).split(',') if t.strip())
    print(f"  Total unique historical S&P 500 tickers: {len(all_historical)}")

    have_data = all_historical & set(price_data.keys())
    missing = all_historical - set(price_data.keys())
    print(f"  Have data for: {len(have_data)}/{len(all_historical)} ({len(have_data)/len(all_historical)*100:.1f}%)")
    print(f"  Still missing: {len(missing)}")

    # Step 3: Point-in-time universe
    print("\n--- STEP 3: Point-in-Time Annual Top-40 ---")
    pit_universe = compute_annual_top40_pit(price_data, snapshots)

    # Step 4: Run survivorship-corrected backtest
    print("\n--- STEP 4: Survivorship-Corrected Backtest ---")
    pit_results = run_backtest(price_data, pit_universe, spy_data, cash_yield_daily)
    pit_metrics = calculate_metrics(pit_results)

    # Step 5: Also run baseline (BROAD_POOL only) for direct comparison
    print("\n--- STEP 5: Baseline Backtest (BROAD_POOL only) ---")
    from omnicapital_v8_compass import compute_annual_top40

    # Filter price_data to only BROAD_POOL + what's needed
    broad_data = {k: v for k, v in price_data.items() if k in BROAD_POOL}
    # Download any missing BROAD_POOL tickers
    import yfinance as yf
    for ticker in BROAD_POOL:
        if ticker not in broad_data:
            try:
                df = yf.download(ticker, start='2000-01-01', end='2027-01-01', progress=False)
                if not df.empty:
                    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                    if df.index.tz is not None:
                        df.index = df.index.tz_localize(None)
                    broad_data[ticker] = df
            except Exception:
                pass

    broad_universe = compute_annual_top40(broad_data)
    broad_results = run_backtest(broad_data, broad_universe, spy_data, cash_yield_daily)
    broad_metrics = calculate_metrics(broad_results)

    # Step 6: Compare
    print("\n" + "=" * 80)
    print("RESULTS: SURVIVORSHIP BIAS QUANTIFICATION")
    print("=" * 80)

    print(f"\n{'Metric':<25} {'Baseline (BROAD_POOL)':>22} {'Corrected (924 PIT)':>22} {'Delta':>15}")
    print("-" * 87)
    print(f"{'CAGR':<25} {broad_metrics['cagr']:>21.2%} {pit_metrics['cagr']:>21.2%} {pit_metrics['cagr']-broad_metrics['cagr']:>+14.2%}")
    print(f"{'Sharpe':<25} {broad_metrics['sharpe']:>22.2f} {pit_metrics['sharpe']:>22.2f} {pit_metrics['sharpe']-broad_metrics['sharpe']:>+15.2f}")
    print(f"{'Max Drawdown':<25} {broad_metrics['max_drawdown']:>21.1%} {pit_metrics['max_drawdown']:>21.1%} {pit_metrics['max_drawdown']-broad_metrics['max_drawdown']:>+14.1%}")
    print(f"{'Final Value':<25} ${broad_metrics['final_value']:>20,.0f} ${pit_metrics['final_value']:>20,.0f}")
    print(f"{'Trades':<25} {broad_metrics['trades']:>22,} {pit_metrics['trades']:>22,} {pit_metrics['trades']-broad_metrics['trades']:>+15,}")
    print(f"{'Win Rate':<25} {broad_metrics['win_rate']:>21.1%} {pit_metrics['win_rate']:>21.1%}")
    print(f"{'Volatility':<25} {broad_metrics['volatility']:>21.1%} {pit_metrics['volatility']:>21.1%}")
    print(f"{'Stop Events':<25} {broad_metrics['stop_events']:>22} {pit_metrics['stop_events']:>22}")
    print(f"{'Protection Days':<25} {broad_metrics['protection_days']:>22.0f} {pit_metrics['protection_days']:>22.0f}")

    bias = broad_metrics['cagr'] - pit_metrics['cagr']
    print(f"\n*** SURVIVORSHIP BIAS = {bias:+.2%} CAGR ***")
    print(f"    (Positive = baseline was inflated by survivorship bias)")
    print(f"    Coverage: {len(have_data)}/{len(all_historical)} historical tickers ({len(have_data)/len(all_historical)*100:.1f}%)")

    # Historical stock impact
    print(f"\n--- Historical Stock Impact ---")
    hist_trades = pit_results.get('historical_stock_trades', [])
    if hist_trades:
        ht_df = pd.DataFrame(hist_trades)
        print(f"  Trades in historical (non-BROAD_POOL) stocks: {len(ht_df)}")
        print(f"  Total P&L from historical stocks: ${ht_df['pnl'].sum():,.2f}")
        print(f"  Win rate: {(ht_df['pnl'] > 0).mean():.1%}")
        print(f"  Avg return per trade: {ht_df['return'].mean():.2%}")

        by_symbol = ht_df.groupby('symbol').agg(
            trades=('pnl', 'count'),
            total_pnl=('pnl', 'sum'),
            avg_return=('return', 'mean')
        ).sort_values('total_pnl')
        print(f"\n  Top historical stocks by P&L impact:")
        for sym, row in by_symbol.head(20).iterrows():
            print(f"    {sym:8s}: {row['trades']:3.0f} trades, P&L ${row['total_pnl']:>10,.2f}, avg ret {row['avg_return']:>+7.2%}")
    else:
        print("  No historical stocks entered the portfolio")

    # Save outputs
    os.makedirs(os.path.join(BASE_DIR, 'backtests'), exist_ok=True)
    pit_results['portfolio_values'].to_csv(
        os.path.join(BASE_DIR, 'backtests', 'exp62_survivorship_daily.csv'), index=False)
    broad_results['portfolio_values'].to_csv(
        os.path.join(BASE_DIR, 'backtests', 'exp62_baseline_daily.csv'), index=False)
    if len(pit_results['trades']) > 0:
        pit_results['trades'].to_csv(
            os.path.join(BASE_DIR, 'backtests', 'exp62_survivorship_trades.csv'), index=False)

    print(f"\n--- Output Files ---")
    print(f"  backtests/exp62_survivorship_daily.csv")
    print(f"  backtests/exp62_baseline_daily.csv")
    print(f"  backtests/exp62_survivorship_trades.csv")
    print(f"\n{'='*80}")
    print(f"EXPERIMENT #62 COMPLETE")
    print(f"Survivorship Bias: {bias:+.2%} CAGR")
    print(f"{'='*80}")
