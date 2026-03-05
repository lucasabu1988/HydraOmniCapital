"""
COMPASS v8.4 SP500 Survivorship-Bias-Free Backtest (1996-present)
=================================================================
Uses point-in-time S&P 500 constituent data from sp500_snapshots.csv
to eliminate survivorship bias. The v84 algorithm is imported unchanged;
only the universe-selection layer is swapped.

Key differences from v84 baseline:
  - Universe: point-in-time SP500 members (~500/date) instead of hardcoded 113
  - Start date: 1996-01-02 (vs 2000-01-01)
  - Sector map: dynamic from yfinance info, cached in JSON
  - ~1000-1500 unique tickers across full history (vs 113)
"""

import pandas as pd
import numpy as np
import yfinance as yf
import os
import sys
import json
import pickle
import time
from datetime import datetime
from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

# Import v84 functions (algorithm unchanged)
import omnicapital_v84_compass as v84

# ============================================================================
# CONSTANTS
# ============================================================================

START_DATE = '1995-01-01'  # Need 1 year lookback for first year's dollar volume
END_DATE = '2027-01-01'
BACKTEST_START = '1997-01-02'  # First year with full ranking data (1996 used for lookback)
CONSTITUENTS_FILE = 'data_cache/sp500_snapshots.csv'
SECTOR_CACHE_FILE = 'data_cache/sp500_sector_map.json'
PRICE_CACHE_FILE = 'data_cache/sp500_universe_prices.pkl'

# Known ticker renames (old -> new for yfinance)
TICKER_RENAMES = {
    'FB': 'META',
    'GOOG': 'GOOGL',
    'BRK.B': 'BRK-B',
    'BF.B': 'BF-B',
}

# yfinance sector -> COMPASS sector mapping
YFINANCE_SECTOR_MAP = {
    'Technology': 'Technology',
    'Information Technology': 'Technology',
    'Communication Services': 'Telecom',
    'Telecommunications': 'Telecom',
    'Financial Services': 'Financials',
    'Financials': 'Financials',
    'Healthcare': 'Healthcare',
    'Health Care': 'Healthcare',
    'Consumer Cyclical': 'Consumer',
    'Consumer Defensive': 'Consumer',
    'Consumer Discretionary': 'Consumer',
    'Consumer Staples': 'Consumer',
    'Energy': 'Energy',
    'Industrials': 'Industrials',
    'Utilities': 'Utilities',
    'Real Estate': 'Utilities',
    'Basic Materials': 'Industrials',
    'Materials': 'Industrials',
}

print("=" * 80)
print("COMPASS v8.4 SP500 — Survivorship-Bias-Free Backtest (1996-present)")
print("=" * 80)


# ============================================================================
# STEP 1: Parse SP500 constituents
# ============================================================================

def load_constituents():
    print(f"\n[Constituents] Loading from {CONSTITUENTS_FILE}...")

    df = pd.read_csv(CONSTITUENTS_FILE)
    constituents = {}

    for _, row in df.iterrows():
        date_str = str(row['date'])
        tickers_raw = str(row['tickers']).split(',')
        tickers = set()
        for t in tickers_raw:
            t = t.strip()
            if not t:
                continue
            # Apply renames
            t = TICKER_RENAMES.get(t, t)
            # Skip tickers with dots (yfinance issues) except known ones
            if '.' in t and t not in ('BRK-B', 'BF-B'):
                continue
            tickers.add(t)
        constituents[date_str] = tickers

    dates_sorted = sorted(constituents.keys())
    print(f"  {len(dates_sorted)} snapshots from {dates_sorted[0]} to {dates_sorted[-1]}")

    all_tickers = set()
    for tickers in constituents.values():
        all_tickers.update(tickers)
    print(f"  {len(all_tickers)} unique tickers across all snapshots")

    return constituents


def get_constituents_for_date(constituents, date):
    if isinstance(date, (pd.Timestamp, datetime)):
        date_str = date.strftime('%Y-%m-%d')
    else:
        date_str = str(date)

    dates_sorted = sorted(constituents.keys())
    best = None
    for d in dates_sorted:
        if d <= date_str:
            best = d
        else:
            break

    if best is None:
        return set()
    return constituents[best]


# ============================================================================
# STEP 2: Extract all unique tickers
# ============================================================================

def get_all_unique_tickers(constituents):
    all_tickers = set()
    for tickers in constituents.values():
        all_tickers.update(tickers)
    return sorted(list(all_tickers))


# ============================================================================
# STEP 3: Download price data for all tickers
# ============================================================================

def download_sp500_universe(all_tickers):
    # Note: pickle used here for consistency with v84 caching pattern
    if os.path.exists(PRICE_CACHE_FILE):
        print(f"\n[Cache] Loading SP500 universe prices from {PRICE_CACHE_FILE}...")
        try:
            with open(PRICE_CACHE_FILE, 'rb') as f:
                data = pickle.load(f)
            print(f"  {len(data)} symbols loaded from cache")
            return data
        except Exception as e:
            print(f"  Cache load failed: {e}, re-downloading...")

    print(f"\n[Download] Downloading {len(all_tickers)} symbols...")
    print(f"  Date range: {START_DATE} to {END_DATE}")
    print(f"  This will take ~30-45 minutes on first run.")

    data = {}
    failed = []
    batch_size = 50

    for i in range(0, len(all_tickers), batch_size):
        batch = all_tickers[i:i + batch_size]
        batch_str = ' '.join(batch)

        try:
            df_batch = yf.download(batch_str, start=START_DATE, end=END_DATE,
                                   progress=False, group_by='ticker', threads=True)

            if len(batch) == 1:
                symbol = batch[0]
                if not df_batch.empty and len(df_batch) > 50:
                    df_batch.columns = [c[0] if isinstance(c, tuple) else c for c in df_batch.columns]
                    data[symbol] = df_batch.dropna(subset=['Close'])
            else:
                for symbol in batch:
                    try:
                        if symbol in df_batch.columns.get_level_values(0):
                            df_sym = df_batch[symbol].copy()
                            df_sym = df_sym.dropna(subset=['Close'])
                            if len(df_sym) > 50:
                                data[symbol] = df_sym
                            else:
                                failed.append(symbol)
                        else:
                            failed.append(symbol)
                    except Exception:
                        failed.append(symbol)

        except Exception as e:
            failed.extend(batch)
            print(f"  Batch {i//batch_size + 1} failed: {e}")

        downloaded = len(data)
        total_processed = i + len(batch)
        if total_processed % 200 == 0 or total_processed == len(all_tickers):
            print(f"  [{total_processed}/{len(all_tickers)}] {downloaded} valid, {len(failed)} failed")

        # Small delay to avoid rate limiting
        if i + batch_size < len(all_tickers):
            time.sleep(0.5)

    print(f"\n[Download] Complete: {len(data)} symbols valid, {len(failed)} failed")
    if failed and len(failed) <= 50:
        print(f"  Failed: {failed}")
    elif failed:
        print(f"  Failed: {len(failed)} symbols (mostly delisted)")

    os.makedirs('data_cache', exist_ok=True)
    with open(PRICE_CACHE_FILE, 'wb') as f:
        pickle.dump(data, f)
    print(f"  Cached to {PRICE_CACHE_FILE}")

    return data


# ============================================================================
# STEP 5: Dynamic sector map
# ============================================================================

def build_sector_map(all_tickers, price_data):
    if os.path.exists(SECTOR_CACHE_FILE):
        print(f"\n[Sectors] Loading from {SECTOR_CACHE_FILE}...")
        with open(SECTOR_CACHE_FILE, 'r') as f:
            sector_map = json.load(f)
        valid = {k: v for k, v in sector_map.items() if k in price_data}
        missing = [t for t in price_data if t not in sector_map]
        if missing:
            print(f"  {len(missing)} tickers missing sector info, looking up...")
            new_sectors = _lookup_sectors(missing)
            sector_map.update(new_sectors)
            with open(SECTOR_CACHE_FILE, 'w') as f:
                json.dump(sector_map, f, indent=2)
        print(f"  {len(valid)} tickers with sector data")
        return sector_map

    print(f"\n[Sectors] Building sector map for {len(price_data)} tickers...")
    # Start with v84's existing sector map
    sector_map = dict(v84.SECTOR_MAP)

    missing = [t for t in price_data if t not in sector_map]
    print(f"  {len(missing)} tickers need sector lookup...")

    new_sectors = _lookup_sectors(missing)
    sector_map.update(new_sectors)

    os.makedirs('data_cache', exist_ok=True)
    with open(SECTOR_CACHE_FILE, 'w') as f:
        json.dump(sector_map, f, indent=2)
    print(f"  Cached to {SECTOR_CACHE_FILE}")

    return sector_map


def _lookup_sectors(tickers):
    sectors = {}
    for i, ticker in enumerate(tickers):
        try:
            info = yf.Ticker(ticker).info
            yf_sector = info.get('sector', '')
            compass_sector = YFINANCE_SECTOR_MAP.get(yf_sector, 'Unknown')
            sectors[ticker] = compass_sector
        except Exception:
            sectors[ticker] = 'Unknown'

        if (i + 1) % 100 == 0:
            print(f"    [{i+1}/{len(tickers)}] sectors looked up...")

    known = sum(1 for v in sectors.values() if v != 'Unknown')
    print(f"  Sector lookup: {known} identified, {len(sectors) - known} unknown")
    return sectors


# ============================================================================
# STEP 4: SP500-aware annual top-40
# ============================================================================

def compute_annual_top40_sp500(price_data, constituents):
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    years = sorted(set(d.year for d in all_dates))

    # Filter to years >= 1997 (1996 used as lookback for dollar volume ranking)
    years = [y for y in years if y >= 1997]

    annual_universe = {}
    print("\n--- Computing Annual Top-40 (SP500 Point-in-Time) ---")

    for year in years:
        jan1 = f'{year}-01-01'
        sp500_members = get_constituents_for_date(constituents, jan1)

        available = [t for t in sp500_members if t in price_data]

        ranking_end = pd.Timestamp(f'{year}-01-01',
                                    tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
        ranking_start = pd.Timestamp(f'{year-1}-01-01',
                                      tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)

        scores = {}
        for symbol in available:
            df = price_data[symbol]
            mask = (df.index >= ranking_start) & (df.index < ranking_end)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dollar_vol = (window['Close'] * window['Volume']).mean()
            scores[symbol] = dollar_vol

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_n = [s for s, _ in ranked[:v84.TOP_N]]
        annual_universe[year] = top_n

        if year > years[0] and year - 1 in annual_universe:
            prev = set(annual_universe[year - 1])
            curr = set(top_n)
            added = curr - prev
            removed = prev - curr
            print(f"  {year}: SP500={len(sp500_members)} avail={len(available)} ranked={len(scores)} "
                  f"Top-{v84.TOP_N} | +{len(added)} -{len(removed)}")
        else:
            print(f"  {year}: SP500={len(sp500_members)} avail={len(available)} ranked={len(scores)} "
                  f"Initial Top-{v84.TOP_N}")

    return annual_universe


# ============================================================================
# STEP 6: Download SPY with extended date range
# ============================================================================

def download_spy_extended():
    cache_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'

    if os.path.exists(cache_file):
        print(f"\n[Cache] Loading SPY data from {cache_file}...")
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        return df

    print("\n[Download] Downloading SPY (1995-present)...")
    df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    print(f"  {len(df)} trading days")
    return df


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    t_start = time.time()

    # 1. Load constituents
    constituents = load_constituents()

    # 2. Get all unique tickers
    all_tickers = get_all_unique_tickers(constituents)
    print(f"\n  Total unique tickers: {len(all_tickers)}")

    # 3. Download price data
    price_data = download_sp500_universe(all_tickers)
    print(f"\n  Symbols with valid price data: {len(price_data)}")

    # 4. Build dynamic sector map and inject into v84 module
    sector_map = build_sector_map(all_tickers, price_data)
    v84.SECTOR_MAP = sector_map  # Monkey-patch so filter_by_sector_concentration uses it
    print(f"  Sector map injected into v84 ({len(sector_map)} entries)")

    # Sector distribution
    sector_counts = defaultdict(int)
    for s in sector_map.values():
        sector_counts[s] += 1
    for sector, count in sorted(sector_counts.items(), key=lambda x: -x[1]):
        print(f"    {sector:15s}: {count:4d}")

    # 5. Download SPY (extended range)
    spy_data = download_spy_extended()
    print(f"  SPY data: {len(spy_data)} trading days")

    # 6. Download cash yield
    cash_yield_daily = v84.download_cash_yield()

    # 7. Compute SP500-aware annual top-40
    annual_universe = compute_annual_top40_sp500(price_data, constituents)

    # Survivorship bias verification
    print("\n--- Survivorship Bias Verification ---")
    notable_stocks = {
        'ENRNQ': 'Enron',
        'LEHMQ': 'Lehman Brothers',
        'WCOM': 'WorldCom',
        'AIG': 'AIG',
        'C': 'Citigroup',
        'GE': 'GE',
        'FNMA': 'Fannie Mae',
        'FMCC': 'Freddie Mac',
    }
    for ticker, name in notable_stocks.items():
        found_years = []
        for year, universe in sorted(annual_universe.items()):
            if ticker in universe:
                found_years.append(year)
        if found_years:
            print(f"  {name} ({ticker}): in Top-40 years {found_years}")
        else:
            in_constituents = any(ticker in tickers for tickers in constituents.values())
            has_data = ticker in price_data
            print(f"  {name} ({ticker}): not in Top-40 (in SP500={in_constituents}, has_data={has_data})")

    # 8. Run backtest
    results = v84.run_backtest(price_data, annual_universe, spy_data, cash_yield_daily)

    # 9. Calculate metrics
    metrics = v84.calculate_metrics(results)

    # 10. Print results
    print("\n" + "=" * 80)
    print("RESULTS - COMPASS v8.4 SP500 (Survivorship-Bias-Free)")
    print("=" * 80)

    print(f"\n--- Performance ---")
    print(f"Initial capital:        ${metrics['initial']:>15,.0f}")
    print(f"Final value:            ${metrics['final_value']:>15,.2f}")
    print(f"Total return:           {metrics['total_return']:>15.2%}")
    print(f"CAGR:                   {metrics['cagr']:>15.2%}")
    print(f"Volatility (annual):    {metrics['volatility']:>15.2%}")

    print(f"\n--- Risk-Adjusted ---")
    print(f"Sharpe ratio:           {metrics['sharpe']:>15.2f}")
    print(f"Sortino ratio:          {metrics['sortino']:>15.2f}")
    print(f"Calmar ratio:           {metrics['calmar']:>15.2f}")
    print(f"Max drawdown:           {metrics['max_drawdown']:>15.2%}")

    print(f"\n--- Trading ---")
    print(f"Trades executed:        {metrics['trades']:>15,}")
    print(f"Win rate:               {metrics['win_rate']:>15.2%}")
    print(f"Avg P&L per trade:      ${metrics['avg_trade']:>15,.2f}")
    print(f"Avg winner:             ${metrics['avg_winner']:>15,.2f}")
    print(f"Avg loser:              ${metrics['avg_loser']:>15,.2f}")

    print(f"\n--- Exit Reasons ---")
    for reason, count in sorted(metrics['exit_reasons'].items(), key=lambda x: -x[1]):
        print(f"  {reason:25s}: {count:>6,} ({count/metrics['trades']*100:.1f}%)")

    print(f"\n--- Risk Management ---")
    print(f"Stop loss events:       {metrics['stop_events']:>15,}")
    print(f"Days in protection:     {metrics['protection_days']:>15,} ({metrics['protection_pct']:.1f}%)")
    print(f"Risk-off days:          {metrics['risk_off_pct']:>14.1f}%")

    print(f"\n--- Annual Returns ---")
    if len(metrics['annual_returns']) > 0:
        print(f"Best year:              {metrics['best_year']:>15.2%}")
        print(f"Worst year:             {metrics['worst_year']:>15.2%}")
        print(f"Positive years:         {(metrics['annual_returns'] > 0).sum()}/{len(metrics['annual_returns'])}")

    # 11. Comparison with v84 baseline
    print("\n" + "=" * 80)
    print("COMPARISON vs v84 BASELINE (survivorship-biased)")
    print("=" * 80)
    print(f"{'Metric':<25} {'v84 Baseline':>12} {'v84 SP500':>12} {'Delta':>12}")
    print("-" * 65)
    v84_cagr = 0.1222
    v84_sharpe = 0.73
    v84_maxdd = -0.3199
    v84_trades = 8119
    print(f"{'CAGR':<25} {v84_cagr:>11.2%} {metrics['cagr']:>11.2%} {metrics['cagr']-v84_cagr:>+11.2%}")
    print(f"{'Sharpe':<25} {v84_sharpe:>12.2f} {metrics['sharpe']:>12.2f} {metrics['sharpe']-v84_sharpe:>+12.2f}")
    print(f"{'Max Drawdown':<25} {v84_maxdd:>11.1%} {metrics['max_drawdown']:>11.1%} {metrics['max_drawdown']-v84_maxdd:>+11.1%}")
    print(f"{'Trades':<25} {v84_trades:>12,} {metrics['trades']:>12,}")

    # 12. Save results
    os.makedirs('backtests', exist_ok=True)
    results['portfolio_values'].to_csv('backtests/v84_sp500_daily.csv', index=False)
    if len(results['trades']) > 0:
        results['trades'].to_csv('backtests/v84_sp500_trades.csv', index=False)

    elapsed = time.time() - t_start
    print(f"\nCompleted in {elapsed/60:.1f} minutes")
    print(f"Daily CSV: backtests/v84_sp500_daily.csv")
    print(f"Trades CSV: backtests/v84_sp500_trades.csv")
