"""
Experiment 41: Extended Backtest 1996-2026 (30 years)
======================================================

This script extends the COMPASS v8.2 backtest validation window from 26 years
(2000-2026) to 30 years (1996-2026) using point-in-time historical constituents.

Objective:
- Validate strategy across additional 4 years (late 1990s)
- Increase statistical significance of performance metrics
- Test robustness across 30 years including tech bubble formation

Key Periods Added:
- 1996-1999: Late tech bubble formation
- 1997: Asian financial crisis
- 1998: LTCM collapse, Russian debt crisis
- 1999: Dotcom mania peak

Why 1996 (not 1990)?
- Historical S&P 500 constituents data (GitHub) starts 1996-01-02
- For 1990-1996, would need Norgate Data (~$500/year) or CRSP (academic)
- 30 years is still excellent validation (+4 years vs current 26)

Data Sources:
- Historical constituents: Cached from Exp40 (GitHub, 1996-2025)
- Stock prices: yfinance (1996-2026, survivorship-bias free)
- SPY: yfinance (1993-2026)
- Cash yield: Simplified 4% (FRED limited pre-1997)

Output:
- backtests/exp41_extended_1996_daily.csv: 30-year equity curve
- backtests/exp41_extended_1996_trades.csv: All trades
- backtests/exp41_comparison.txt: 30yr vs 26yr comparison
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
from typing import Dict, List, Tuple, Optional, Set
import warnings
import requests
from io import StringIO
import time

warnings.filterwarnings('ignore')

# ============================================================================
# PARAMETERS (EXACT COPY FROM COMPASS v8.2)
# ============================================================================

# Universe
TOP_N = 40
MIN_AGE_DAYS = 63

# Signal
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
MIN_MOMENTUM_STOCKS = 20

# Regime
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3

# Positions
NUM_POSITIONS = 5
NUM_POSITIONS_RISK_OFF = 2
HOLD_DAYS = 5

# Position-level risk
POSITION_STOP_LOSS = -0.08
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03

# Portfolio-level risk
PORTFOLIO_STOP_LOSS = -0.15

# Recovery stages
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126

# Leverage & Vol targeting
TARGET_VOL = 0.15
LEVERAGE_MIN = 0.3
LEVERAGE_MAX = 1.0
VOL_LOOKBACK = 20

# Costs
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.035
CASH_YIELD_SOURCE = 'AAA'

# Data
START_DATE = '1996-01-02'  # Earliest available in constituents cache
END_DATE = '2027-01-01'

print("=" * 80)
print("EXPERIMENT 41: EXTENDED BACKTEST 1996-2026 (30 YEARS)")
print("=" * 80)
print(f"\nObjective: Extend COMPASS v8.2 validation window from 26 years to 30 years")
print(f"Method: Run bias-corrected backtest using historical point-in-time constituents")
print(f"Period: {START_DATE} to {END_DATE} (30 years)")
print(f"Added: 1996-2000 period (late tech bubble formation)")
print(f"Note: Constituents data available from 1996 onwards")
print()

# ============================================================================
# TICKER MAPPING FOR PROBLEMATIC CASES
# ============================================================================

# Mapping for tickers that were reused or have special cases
TICKER_MAPPING = {
    # Lehman Brothers (bankrupt 2008)
    'LEH': {'stooq': 'LEH.US', 'delisted_date': '2008-09-15', 'reason': 'Bankruptcy'},

    # Enron (bankrupt 2001)
    'ENE': {'stooq': 'ENE.US', 'delisted_date': '2001-11-28', 'reason': 'Bankruptcy'},

    # Bear Stearns (acquired 2008)
    'BSC': {'stooq': 'BSC.US', 'delisted_date': '2008-05-30', 'reason': 'Acquired by JPM'},

    # Washington Mutual (bankrupt 2008) - ticker WM was later reused by Waste Management
    'WM_OLD': {'stooq': 'WM.US', 'delisted_date': '2008-09-26', 'reason': 'Bankruptcy',
               'note': 'WM ticker reused by Waste Management'},

    # Countrywide Financial (acquired 2008)
    'CFC': {'stooq': 'CFC.US', 'delisted_date': '2008-07-01', 'reason': 'Acquired by BAC'},

    # WorldCom (bankrupt 2002)
    'WCOM': {'stooq': 'WCOM.US', 'delisted_date': '2002-07-21', 'reason': 'Bankruptcy'},

    # General Motors old (bankrupt 2009) - ticker GM reused by new GM
    'GM_OLD': {'stooq': 'GM.US', 'delisted_date': '2009-06-01', 'reason': 'Bankruptcy',
               'note': 'GM ticker reused by new company'},

    # Chrysler
    'C_OLD': {'stooq': 'C.US', 'delisted_date': '2007-08-03', 'reason': 'Acquired',
              'note': 'C ticker later reused by Citigroup'},

    # AIG (survived but heavily diluted)
    'AIG': {'note': 'Extreme dilution 2008-2009, reverse split 1:20 in 2009'},

    # Citigroup (survived but heavily diluted)
    'C': {'note': 'Reverse split 1:10 in 2011'},

    # More financial crisis casualties
    'WB': {'stooq': 'WB.US', 'delisted_date': '2008-10-03', 'reason': 'Acquired by WFC'},
    'WM': {'stooq': 'WM.US', 'delisted_date': '2008-09-26', 'reason': 'Bankruptcy'},
    'MEL': {'stooq': 'MEL.US', 'delisted_date': '2009-01-01', 'reason': 'Acquired'},
    'MER': {'stooq': 'MER.US', 'delisted_date': '2009-01-01', 'reason': 'Acquired by BAC'},
}

# Known delisted S&P 500 stocks (will be expanded with real data)
KNOWN_DELISTED_STOCKS = list(TICKER_MAPPING.keys())

print(f"Known problematic tickers: {len(TICKER_MAPPING)}")
print(f"  Bankruptcies: {sum(1 for v in TICKER_MAPPING.values() if v.get('reason') == 'Bankruptcy')}")
print(f"  Acquisitions: {sum(1 for v in TICKER_MAPPING.values() if v.get('reason', '').startswith('Acquired'))}")
print()

# ============================================================================
# DATA DOWNLOAD FUNCTIONS
# ============================================================================

def download_sp500_constituents_history() -> pd.DataFrame:
    """
    Download historical S&P 500 constituents from multiple sources.

    Primary source: fja05680/sp500 GitHub repo
    Fallback: scrape from various sources

    Returns DataFrame with columns: date, ticker, action (added/removed)
    """
    cache_file = 'data_cache/sp500_constituents_history.pkl'

    if os.path.exists(cache_file):
        print("[Cache] Loading S&P 500 constituents history...")
        with open(cache_file, 'rb') as f:
            df = pickle.load(f)
        print(f"  Loaded {len(df)} constituent change events")
        print(f"  Date range: {df['date'].min()} to {df['date'].max()}")
        return df

    print("[Download] Downloading S&P 500 historical constituents...")

    # Try multiple sources (updated 2025)
    sources = [
        {
            'name': 'hanshof/sp500_constituents',
            'url': 'https://raw.githubusercontent.com/hanshof/sp500_constituents/main/sp_500_historical_components.csv',
            'parser': 'parse_hanshof'
        },
        {
            'name': 'fja05680/sp500 (direct CSV)',
            'url': 'https://raw.githubusercontent.com/fja05680/sp500/master/S%26P%20500%20Historical%20Components%20%26%20Changes.csv',
            'parser': 'parse_fja05680'
        },
        {
            'name': 'datasets/s-and-p-500-companies',
            'url': 'https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv',
            'parser': 'parse_datasets'
        }
    ]

    for source in sources:
        try:
            print(f"  Trying {source['name']}...")
            if source['parser'] == 'parse_hanshof':
                df = parse_sp500_hanshof(source['url'])
            elif source['parser'] == 'parse_fja05680':
                df = parse_sp500_fja05680(source['url'])
            elif source['parser'] == 'parse_datasets':
                df = parse_sp500_datasets(source['url'])

            if df is not None and not df.empty:
                print(f"  [OK] Success! Got {len(df)} constituent events")
                os.makedirs('data_cache', exist_ok=True)
                with open(cache_file, 'wb') as f:
                    pickle.dump(df, f)
                return df
        except Exception as e:
            print(f"  [FAIL] Failed: {e}")

    print("[ERROR] Could not download S&P 500 constituent history from any source")
    print("  Falling back to current BROAD_POOL (WARNING: This will NOT correct survivorship bias)")
    return None


def parse_sp500_hanshof(url: str) -> pd.DataFrame:
    """
    Parse S&P 500 data from hanshof/sp500_constituents GitHub repo.

    Format: CSV with two columns:
    - date: trading date
    - tickers: comma-separated string of all tickers in S&P 500 that date
    """
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    # Read CSV (date, tickers columns)
    df = pd.read_csv(StringIO(response.text), parse_dates=['date'])

    print(f"    Loaded {len(df)} trading dates")
    print(f"    Date range: {df['date'].min()} to {df['date'].max()}")

    # Convert to long format (date, ticker, in_sp500)
    records = []
    for idx, row in df.iterrows():
        date = row['date']
        tickers_str = row['tickers']

        if pd.isna(tickers_str):
            continue

        # Split comma-separated tickers
        tickers = [t.strip() for t in str(tickers_str).split(',')]

        for ticker in tickers:
            if ticker:  # Skip empty strings
                records.append({
                    'date': date,
                    'ticker': ticker,
                    'in_sp500': True
                })

        if (idx + 1) % 1000 == 0:
            print(f"      Processed {idx+1}/{len(df)} dates...")

    if not records:
        return None

    result = pd.DataFrame(records)
    result = result.sort_values(['ticker', 'date'])

    print(f"    Parsed {len(result)} (date, ticker) pairs")
    print(f"    Unique tickers: {result['ticker'].nunique()}")

    # Identify additions and removals for each ticker
    changes = []
    all_tickers = result['ticker'].unique()

    for i, ticker in enumerate(all_tickers):
        ticker_data = result[result['ticker'] == ticker].sort_values('date')
        dates = ticker_data['date'].tolist()

        if not dates:
            continue

        # First appearance = addition
        changes.append({'date': dates[0], 'ticker': ticker, 'action': 'added'})

        # Check for gaps (removal and re-addition)
        for j in range(1, len(dates)):
            gap_days = (dates[j] - dates[j-1]).days
            if gap_days > 60:  # More than 60 days gap = was removed
                changes.append({'date': dates[j-1], 'ticker': ticker, 'action': 'removed'})
                changes.append({'date': dates[j], 'ticker': ticker, 'action': 'added'})

        # Last date = potential removal (if more than 1 year ago)
        if dates[-1] < pd.Timestamp.now() - timedelta(days=365):
            changes.append({'date': dates[-1], 'ticker': ticker, 'action': 'removed'})

        if (i + 1) % 100 == 0:
            print(f"      Analyzed {i+1}/{len(all_tickers)} tickers...")

    changes_df = pd.DataFrame(changes)
    print(f"    Identified {len(changes_df)} constituent events ({changes_df['ticker'].nunique()} unique tickers)")

    return changes_df


def parse_sp500_fja05680(url: str) -> pd.DataFrame:
    """Parse S&P 500 data from fja05680 GitHub repo"""
    response = requests.get(url)
    response.raise_for_status()

    # The CSV has dates as column headers and tickers as rows
    # Each cell is 1 if the stock was in S&P 500 that day, NaN otherwise
    df = pd.read_csv(StringIO(response.text), index_col=0)

    # Convert to long format: date, ticker, in_sp500
    records = []
    for ticker in df.index:
        for date_str in df.columns:
            if pd.notna(df.loc[ticker, date_str]):
                records.append({
                    'date': pd.to_datetime(date_str),
                    'ticker': ticker,
                    'in_sp500': True
                })

    result = pd.DataFrame(records)
    result = result.sort_values('date')

    # Identify additions and removals
    changes = []
    for ticker in result['ticker'].unique():
        ticker_data = result[result['ticker'] == ticker].sort_values('date')
        dates = ticker_data['date'].tolist()

        # First appearance = addition
        changes.append({'date': dates[0], 'ticker': ticker, 'action': 'added'})

        # Check for gaps (removal and re-addition)
        for i in range(1, len(dates)):
            gap_days = (dates[i] - dates[i-1]).days
            if gap_days > 30:  # More than 30 days gap = was removed and re-added
                changes.append({'date': dates[i-1], 'ticker': ticker, 'action': 'removed'})
                changes.append({'date': dates[i], 'ticker': ticker, 'action': 'added'})

    changes_df = pd.DataFrame(changes)
    return changes_df


def parse_sp500_datasets(url: str) -> pd.DataFrame:
    """Parse current S&P 500 constituents from datasets/s-and-p-500-companies"""
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    df = pd.read_csv(StringIO(response.text))

    # This only gives us current constituents, not historical
    # Assume they were added today (better than nothing for fallback)
    result = pd.DataFrame({
        'date': pd.Timestamp.now(),
        'ticker': df['Symbol'] if 'Symbol' in df.columns else df['ticker'],
        'action': 'current'
    })

    print(f"    Current constituents only: {len(result)} tickers")
    return result


def parse_sp500_wikipedia(url: str) -> pd.DataFrame:
    """Parse current and recent changes from Wikipedia"""
    # This only gives us recent changes, not full history
    # Better than nothing as a fallback
    tables = pd.read_html(url)

    # Table 0: Current constituents
    current = tables[0]
    current = current.rename(columns={'Symbol': 'ticker'})

    # Table 1: Recent changes
    if len(tables) > 1:
        changes = tables[1]
        # Parse changes into additions/removals
        # (Wikipedia format varies, needs robust parsing)
        pass

    # For now, just return current constituents with today's date
    result = pd.DataFrame({
        'date': pd.Timestamp.now(),
        'ticker': current['ticker'],
        'action': 'current'
    })

    return result


def build_point_in_time_universe(constituents_df: pd.DataFrame,
                                 start_date: str,
                                 end_date: str) -> Dict[int, Set[str]]:
    """
    Build point-in-time universe for each year.

    For each year, return the set of tickers that were in S&P 500 at any point
    during that year (or the year before for ranking purposes).
    """
    if constituents_df is None:
        print("[WARNING] No constituent data, using current BROAD_POOL")
        from omnicapital_v8_compass import BROAD_POOL
        # Assume they were all there the whole time (wrong, but no alternative)
        years = range(pd.to_datetime(start_date).year, pd.to_datetime(end_date).year + 1)
        return {year: set(BROAD_POOL) for year in years}

    print("\n[Building] Point-in-time universe by year...")

    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)

    universe_by_year = {}

    for year in range(start_dt.year, end_dt.year + 1):
        year_start = pd.Timestamp(f'{year}-01-01')
        year_end = pd.Timestamp(f'{year}-12-31')

        # Get all tickers that were in S&P 500 at any point during this year
        mask = (constituents_df['date'] >= year_start - timedelta(days=365)) & \
               (constituents_df['date'] <= year_end)

        year_tickers = set(constituents_df.loc[mask, 'ticker'].unique())
        universe_by_year[year] = year_tickers

        print(f"  {year}: {len(year_tickers)} tickers")

    return universe_by_year


def download_price_data_multi_source(ticker: str,
                                     start_date: str,
                                     end_date: str,
                                     is_delisted: bool = False) -> Optional[pd.DataFrame]:
    """
    Download price data from multiple sources with fallback.

    Priority:
    1. yfinance (works for most current and some delisted)
    2. Stooq (good for delisted US stocks)
    3. Alpha Vantage (requires API key, last resort)
    """
    sources = ['yfinance', 'stooq', 'alpha_vantage']

    for source in sources:
        try:
            if source == 'yfinance':
                df = download_yfinance(ticker, start_date, end_date)
            elif source == 'stooq':
                df = download_stooq(ticker, start_date, end_date)
            elif source == 'alpha_vantage':
                df = download_alpha_vantage(ticker, start_date, end_date)
            else:
                continue

            if df is not None and not df.empty and len(df) > 10:
                return df
        except Exception:
            continue

    return None


def download_yfinance(ticker: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """Download from yfinance using period='max' for better historical coverage"""
    try:
        # Use period='max' to get all available history (works better for old data)
        stock = yf.Ticker(ticker)
        df = stock.history(period='max')

        if not df.empty:
            # Filter to requested date range
            df = df[(df.index >= start_date) & (df.index <= end_date)]
            if not df.empty:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                return df
    except:
        pass
    return None


def download_stooq(ticker: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """
    Download from Stooq (stooq.com).

    Stooq format: ticker.US for US stocks
    URL format: https://stooq.com/q/d/l/?s=TICKER.US&i=d
    """
    # Map ticker to Stooq format
    stooq_ticker = ticker if '.' in ticker else f'{ticker}.US'

    url = f'https://stooq.com/q/d/l/?s={stooq_ticker}&i=d'

    response = requests.get(url, timeout=10)
    response.raise_for_status()

    # Stooq CSV format: Date,Open,High,Low,Close,Volume
    df = pd.read_csv(StringIO(response.text), parse_dates=['Date'], index_col='Date')

    # Convert column names to match yfinance format
    df = df.rename(columns={
        'Open': 'Open',
        'High': 'High',
        'Low': 'Low',
        'Close': 'Close',
        'Volume': 'Volume'
    })

    # Filter date range
    df = df.loc[(df.index >= start_date) & (df.index <= end_date)]

    return df if not df.empty else None


def download_alpha_vantage(ticker: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """
    Download from Alpha Vantage (requires API key).

    Note: Free tier has rate limits (5 calls/min, 500 calls/day)
    Set environment variable: ALPHA_VANTAGE_API_KEY
    """
    api_key = os.environ.get('ALPHA_VANTAGE_API_KEY')
    if not api_key:
        return None

    url = f'https://www.alphavantage.co/query'
    params = {
        'function': 'TIME_SERIES_DAILY_ADJUSTED',
        'symbol': ticker,
        'outputsize': 'full',
        'apikey': api_key,
        'datatype': 'csv'
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()

    df = pd.read_csv(StringIO(response.text), parse_dates=['timestamp'], index_col='timestamp')
    df = df.rename(columns={
        'open': 'Open',
        'high': 'High',
        'low': 'Low',
        'adjusted_close': 'Close',  # Use adjusted close
        'volume': 'Volume'
    })

    # Filter date range
    df = df.loc[(df.index >= start_date) & (df.index <= end_date)]

    # Alpha Vantage returns newest first, reverse it
    df = df.sort_index()

    return df if not df.empty else None


def filter_anomalous_stocks(data: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """
    Filter out stocks with anomalous price movements that indicate data corruption.

    Removes stocks with:
    - Single-day returns > 100%  (Changed from 500% after Exp41 data corruption)
    - Extreme volatility (> 200% annualized)  (Tightened from 300%)
    """
    print("\n[Filter] Checking for anomalous price data...")

    filtered_data = {}
    removed_stocks = []

    for symbol, df in data.items():
        try:
            if len(df) < 20:
                continue

            returns = df['Close'].pct_change(fill_method=None).dropna()

            if len(returns) == 0:
                continue

            max_single_day = returns.max()
            volatility = returns.std() * np.sqrt(252)

            # Filter criteria
            is_valid = True
            reason = None

            if max_single_day > 1.0:  # 100%+ single day (tightened after Exp41 corruption)
                is_valid = False
                reason = f"Extreme gain: {max_single_day*100:.0f}%"
            elif volatility > 2.0:  # 200%+ annualized vol (tightened from 300%)
                is_valid = False
                reason = f"Extreme vol: {volatility*100:.0f}%"

            if is_valid:
                filtered_data[symbol] = df
            else:
                removed_stocks.append((symbol, reason))

        except Exception:
            # Skip stocks with errors
            continue

    print(f"  Filtered: {len(filtered_data)} stocks kept, {len(removed_stocks)} removed")

    if removed_stocks:
        print(f"  Removed stocks (showing first 10):")
        for symbol, reason in removed_stocks[:10]:
            print(f"    {symbol}: {reason}")
        if len(removed_stocks) > 10:
            print(f"    ... and {len(removed_stocks) - 10} more")

    return filtered_data


def download_expanded_pool(pit_universe: Dict[int, Set[str]]) -> Dict[str, pd.DataFrame]:
    """
    Download price data for all stocks in the point-in-time universe.

    This includes both current and delisted stocks.
    Uses multi-source download with caching.
    """
    cache_file = 'data_cache/survivorship_bias_pool.pkl'

    if os.path.exists(cache_file):
        print("[Cache] Loading expanded pool data...")
        with open(cache_file, 'rb') as f:
            data = pickle.load(f)
        print(f"  Loaded data for {len(data)} symbols")

        # Filter anomalous data
        data = filter_anomalous_stocks(data)

        return data

    print("\n[Download] Downloading expanded pool (current + delisted stocks)...")

    # Get unique tickers across all years
    all_tickers = set()
    for year_tickers in pit_universe.values():
        all_tickers.update(year_tickers)

    print(f"  Total unique tickers: {len(all_tickers)}")

    # Import current BROAD_POOL to identify delisted stocks
    from omnicapital_v8_compass import BROAD_POOL
    current_tickers = set(BROAD_POOL)
    delisted_tickers = all_tickers - current_tickers

    print(f"  Current tickers: {len(current_tickers)}")
    print(f"  Delisted tickers: {len(delisted_tickers)}")

    data = {}
    failed = []
    failed_delisted = []

    # Download current stocks (should be fast, from cache)
    print("\n  Downloading current stocks...")
    for i, ticker in enumerate(sorted(current_tickers)):
        try:
            df = download_price_data_multi_source(ticker, START_DATE, END_DATE, is_delisted=False)
            if df is not None and not df.empty:
                data[ticker] = df
            else:
                failed.append(ticker)

            if (i + 1) % 20 == 0:
                print(f"    [{i+1}/{len(current_tickers)}] Current: {len([t for t in data if t in current_tickers])} success")
        except Exception:
            failed.append(ticker)

    # Download delisted stocks (slower, may fail for many)
    print("\n  Downloading delisted stocks (this may take a while)...")
    for i, ticker in enumerate(sorted(delisted_tickers)):
        try:
            df = download_price_data_multi_source(ticker, START_DATE, END_DATE, is_delisted=True)
            if df is not None and not df.empty:
                data[ticker] = df
            else:
                failed_delisted.append(ticker)

            if (i + 1) % 10 == 0:
                print(f"    [{i+1}/{len(delisted_tickers)}] Delisted: {len([t for t in data if t in delisted_tickers])} success, {len(failed_delisted)} failed")

            # Rate limiting for Stooq/Alpha Vantage (reduced for faster execution)
            time.sleep(0.1)
        except Exception:
            failed_delisted.append(ticker)

    print(f"\n[Download] Complete:")
    print(f"  Total downloaded: {len(data)} symbols")
    print(f"  Current stocks failed: {len(failed)}")
    print(f"  Delisted stocks failed: {len(failed_delisted)}")

    if failed:
        print(f"  Failed current: {failed[:10]}{'...' if len(failed) > 10 else ''}")
    if failed_delisted:
        print(f"  Failed delisted: {failed_delisted[:20]}{'...' if len(failed_delisted) > 20 else ''}")

    # Calculate coverage
    total_symbols = len(all_tickers)
    coverage = len(data) / total_symbols * 100
    print(f"\n  Coverage: {coverage:.1f}% ({len(data)}/{total_symbols})")

    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)

    return data


# ============================================================================
# IMPORT COMPASS FUNCTIONS (reuse exact logic)
# ============================================================================

# Import all functions from COMPASS v8.2
import sys
sys.path.insert(0, 'C:\\Users\\caslu\\Desktop\\NuevoProyecto')

print("[Import] Importing COMPASS v8.2 functions...")
try:
    from omnicapital_v8_compass import (
        compute_regime,
        compute_momentum_scores,
        compute_volatility_weights,
        compute_dynamic_leverage,
        download_spy,
        download_cash_yield,
        run_backtest,
        get_tradeable_symbols,
        download_broad_pool,
        compute_annual_top40
    )
    print("  [OK] Successfully imported COMPASS functions")
except Exception as e:
    print(f"  [FAIL] Failed to import: {e}")
    print("  Will reimplement functions inline...")


def compute_annual_top40_corrected(price_data: Dict[str, pd.DataFrame]) -> Dict[int, List[str]]:
    """
    For each year, compute top-40 by avg daily dollar volume (prior year data).
    Corrected version that handles timezone-aware and timezone-naive datetimes.
    """
    # Get all unique dates
    all_dates = set()
    for df in price_data.values():
        # Normalize to timezone-naive
        if hasattr(df.index, 'tz') and df.index.tz is not None:
            all_dates.update(df.index.tz_localize(None))
        else:
            all_dates.update(df.index)

    all_dates = sorted(list(all_dates))
    if not all_dates:
        return {}

    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}

    for year in years:
        if year == years[0]:
            ranking_end = pd.Timestamp(f'{year}-02-01')
            ranking_start = pd.Timestamp(f'{year-1}-01-01')
        else:
            ranking_end = pd.Timestamp(f'{year}-01-01')
            ranking_start = pd.Timestamp(f'{year-1}-01-01')

        scores = {}
        for symbol, df in price_data.items():
            # Normalize index to timezone-naive
            if hasattr(df.index, 'tz') and df.index.tz is not None:
                df_normalized = df.copy()
                df_normalized.index = df_normalized.index.tz_localize(None)
            else:
                df_normalized = df

            mask = (df_normalized.index >= ranking_start) & (df_normalized.index < ranking_end)
            window = df_normalized.loc[mask]
            if len(window) < 20:
                continue

            # Ensure we get a scalar value
            try:
                # Handle multi-level columns if present
                if isinstance(window.columns, pd.MultiIndex):
                    close_col = [c for c in window.columns if 'Close' in str(c)][0]
                    vol_col = [c for c in window.columns if 'Volume' in str(c)][0]
                    close_data = window[close_col]
                    vol_data = window[vol_col]
                else:
                    close_data = window['Close']
                    vol_data = window['Volume']

                # Flatten if needed
                if isinstance(close_data, pd.DataFrame):
                    close_data = close_data.iloc[:, 0]
                if isinstance(vol_data, pd.DataFrame):
                    vol_data = vol_data.iloc[:, 0]

                dollar_vol_series = close_data * vol_data
                dollar_vol_mean = dollar_vol_series.mean()

                # Convert to scalar
                if isinstance(dollar_vol_mean, pd.Series):
                    dollar_vol_mean = dollar_vol_mean.iloc[0]

                dollar_vol = float(dollar_vol_mean)

                if not np.isnan(dollar_vol) and dollar_vol > 0:
                    scores[symbol] = dollar_vol
            except Exception as e:
                # Skip stocks with problematic data
                continue

        if not scores:
            print(f"  {year}: No valid stocks for ranking")
            annual_universe[year] = []
            continue

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_n = [s for s, _ in ranked[:TOP_N]]
        annual_universe[year] = top_n

        if year > years[0] and year - 1 in annual_universe:
            prev = set(annual_universe[year - 1])
            curr = set(top_n)
            added = curr - prev
            removed = prev - curr
            if added or removed:
                print(f"  {year}: Top-{TOP_N} | +{len(added)} added, -{len(removed)} removed")
        else:
            print(f"  {year}: Initial top-{TOP_N} = {len(top_n)} stocks")

    return annual_universe


def compare_and_quantify_bias(results_original: Dict, results_corrected: Dict):
    """
    Compare original vs corrected backtest results and quantify survivorship bias.
    """
    print("\n" + "=" * 80)
    print("SURVIVORSHIP BIAS ANALYSIS")
    print("=" * 80)

    # Extract key metrics from both backtests
    # portfolio_values is already a DataFrame
    original_equity = results_original['portfolio_values']
    corrected_equity = results_corrected['portfolio_values']

    # Calculate metrics (access by column name 'value' not 'portfolio_value')
    original_final = original_equity.iloc[-1]['value']
    corrected_final = corrected_equity.iloc[-1]['value']

    original_return = (original_final / INITIAL_CAPITAL - 1) * 100
    corrected_return = (corrected_final / INITIAL_CAPITAL - 1) * 100

    # Calculate CAGR
    years_original = len(original_equity) / 252
    years_corrected = len(corrected_equity) / 252

    original_cagr = (pow(original_final / INITIAL_CAPITAL, 1 / years_original) - 1) * 100
    corrected_cagr = (pow(corrected_final / INITIAL_CAPITAL, 1 / years_corrected) - 1) * 100

    # Survivorship bias = difference in CAGR
    survivorship_bias = original_cagr - corrected_cagr

    # Calculate other metrics
    def calc_sharpe(equity_df):
        returns = equity_df['value'].pct_change(fill_method=None).dropna()
        if len(returns) == 0:
            return 0
        return (returns.mean() * 252) / (returns.std() * np.sqrt(252))

    def calc_max_dd(equity_df):
        values = equity_df['value']
        cummax = values.cummax()
        dd = (values - cummax) / cummax
        return dd.min() * 100

    original_sharpe = calc_sharpe(original_equity)
    corrected_sharpe = calc_sharpe(corrected_equity)

    original_max_dd = calc_max_dd(original_equity)
    corrected_max_dd = calc_max_dd(corrected_equity)

    # Count trades
    original_trades = len(results_original['trades'])
    corrected_trades = len(results_corrected['trades'])

    # Print comparison
    print("\n" + "-" * 80)
    print("COMPARISON: ORIGINAL vs CORRECTED (Point-in-Time)")
    print("-" * 80)
    print(f"\n{'Metric':<30} {'Original':<20} {'Corrected':<20} {'Difference':<15}")
    print("-" * 80)
    print(f"{'Final Portfolio Value':<30} ${original_final:>18,.0f} ${corrected_final:>18,.0f} ${corrected_final - original_final:>13,.0f}")
    print(f"{'Total Return':<30} {original_return:>18.2f}% {corrected_return:>18.2f}% {corrected_return - original_return:>13.2f}%")
    print(f"{'CAGR':<30} {original_cagr:>18.2f}% {corrected_cagr:>18.2f}% {corrected_cagr - original_cagr:>13.2f}%")
    print(f"{'Sharpe Ratio':<30} {original_sharpe:>18.3f} {corrected_sharpe:>18.3f} {corrected_sharpe - original_sharpe:>13.3f}")
    print(f"{'Max Drawdown':<30} {original_max_dd:>18.2f}% {corrected_max_dd:>18.2f}% {corrected_max_dd - original_max_dd:>13.2f}%")
    print(f"{'Number of Trades':<30} {original_trades:>18,} {corrected_trades:>18,} {corrected_trades - original_trades:>13,}")
    print(f"{'Years Simulated':<30} {years_original:>18.2f} {years_corrected:>18.2f} {years_corrected - years_original:>13.2f}")
    print("-" * 80)

    print(f"\n{'=' * 80}")
    print(f"  SURVIVORSHIP BIAS QUANTIFIED: {survivorship_bias:+.2f}% CAGR")
    print(f"{'=' * 80}")

    if survivorship_bias > 0:
        print(f"\n  The original backtest (using only current S&P 500 stocks) overestimated")
        print(f"  performance by {survivorship_bias:.2f}% CAGR due to survivorship bias.")
        print(f"\n  Original CAGR: {original_cagr:.2f}%")
        print(f"  Bias-corrected CAGR: {corrected_cagr:.2f}%")
    else:
        print(f"\n  Surprisingly, the corrected backtest performed BETTER by {-survivorship_bias:.2f}% CAGR.")
        print(f"  This suggests the strategy benefited from including failed stocks (possibly shorts).")

    # Save detailed comparison to file
    os.makedirs('backtests', exist_ok=True)

    with open('backtests/exp41_comparison.txt', 'w') as f:
        f.write("=" * 80 + "\n")
        f.write("EXPERIMENT 41: EXTENDED BACKTEST 1990-2026\n")
        f.write("COMPASS v8.2 Strategy Analysis\n")
        f.write("=" * 80 + "\n\n")

        f.write("OBJECTIVE\n")
        f.write("-" * 80 + "\n")
        f.write("Quantify the survivorship bias in COMPASS v8.2 backtest by comparing:\n")
        f.write("  - Original: Using only current S&P 500 stocks (survivorship bias present)\n")
        f.write("  - Corrected: Using historical point-in-time S&P 500 universe (bias removed)\n\n")

        f.write("DATA COVERAGE\n")
        f.write("-" * 80 + "\n")
        f.write(f"Original universe: {len(results_original.get('universe_stats', {}))} stocks\n")
        f.write(f"Corrected universe: {len(results_corrected.get('universe_stats', {}))} stocks\n")
        f.write(f"Period: {START_DATE} to {END_DATE}\n\n")

        f.write("RESULTS\n")
        f.write("-" * 80 + "\n")
        f.write(f"{'Metric':<30} {'Original':<20} {'Corrected':<20} {'Difference':<15}\n")
        f.write("-" * 80 + "\n")
        f.write(f"{'Final Value':<30} ${original_final:>18,.0f} ${corrected_final:>18,.0f} ${corrected_final - original_final:>13,.0f}\n")
        f.write(f"{'CAGR':<30} {original_cagr:>18.2f}% {corrected_cagr:>18.2f}% {corrected_cagr - original_cagr:>13.2f}%\n")
        f.write(f"{'Sharpe Ratio':<30} {original_sharpe:>18.3f} {corrected_sharpe:>18.3f} {corrected_sharpe - original_sharpe:>13.3f}\n")
        f.write(f"{'Max Drawdown':<30} {original_max_dd:>18.2f}% {corrected_max_dd:>18.2f}% {corrected_max_dd - original_max_dd:>13.2f}%\n")
        f.write(f"{'Trades':<30} {original_trades:>18,} {corrected_trades:>18,} {corrected_trades - original_trades:>13,}\n")
        f.write("-" * 80 + "\n\n")

        f.write("SURVIVORSHIP BIAS\n")
        f.write("-" * 80 + "\n")
        f.write(f"Bias magnitude: {survivorship_bias:+.2f}% CAGR\n")
        f.write(f"Bias percentage: {(survivorship_bias / original_cagr * 100):+.1f}% of original CAGR\n\n")

        if survivorship_bias > 0:
            f.write("INTERPRETATION:\n")
            f.write(f"The original backtest overestimated performance by {survivorship_bias:.2f}% per year.\n")
            f.write("This is because it only included stocks that survived to present day,\n")
            f.write("excluding failed companies that would have caused losses.\n")
        else:
            f.write("INTERPRETATION:\n")
            f.write(f"The corrected backtest performed better by {-survivorship_bias:.2f}% per year.\n")
            f.write("This unusual result may indicate the strategy's signals actually\n")
            f.write("avoided failed stocks effectively, or the data has gaps.\n")

    # Save equity curves
    original_equity.to_csv('backtests/exp41_original_daily.csv', index=False)
    corrected_equity.to_csv('backtests/exp41_corrected_daily.csv', index=False)

    # Save trade logs
    pd.DataFrame(results_original['trades']).to_csv('backtests/exp41_original_trades.csv', index=False)
    pd.DataFrame(results_corrected['trades']).to_csv('backtests/exp41_corrected_trades.csv', index=False)

    print("\n[SAVED] Results saved to backtests/ directory:")
    print("  - exp41_comparison.txt (detailed comparison)")
    print("  - exp41_original_daily.csv (original equity curve)")
    print("  - exp41_corrected_daily.csv (corrected equity curve)")
    print("  - exp41_original_trades.csv (original trades)")
    print("  - exp41_corrected_trades.csv (corrected trades)")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main execution function"""

    print("\n" + "=" * 80)
    print("STEP 1: DOWNLOAD S&P 500 HISTORICAL CONSTITUENTS")
    print("=" * 80)

    constituents_df = download_sp500_constituents_history()

    print("\n" + "=" * 80)
    print("STEP 2: BUILD POINT-IN-TIME UNIVERSE")
    print("=" * 80)

    pit_universe = build_point_in_time_universe(constituents_df, START_DATE, END_DATE)

    print("\n" + "=" * 80)
    print("STEP 3: DOWNLOAD EXPANDED PRICE DATA")
    print("=" * 80)

    expanded_data = download_expanded_pool(pit_universe)

    print("\n" + "=" * 80)
    print("STEP 4: DOWNLOAD SPY AND CASH YIELD DATA")
    print("=" * 80)

    spy_data = download_spy()
    cash_yield = download_cash_yield()

    print("\n" + "=" * 80)
    print("STEP 5: RUN CORRECTED BACKTEST (Point-in-Time Universe)")
    print("=" * 80)

    # Compute annual top-40 using point-in-time universe
    # This is the KEY difference: we use the expanded pool with delisted stocks
    print("\nComputing annual top-40 rotation (point-in-time universe)...")
    annual_universe_corrected = compute_annual_top40_corrected(expanded_data)

    # Run backtest with corrected universe
    print("\n[INFO] Running COMPASS v8.2 backtest with CORRECTED universe (includes delisted stocks)...")
    results_corrected = run_backtest(expanded_data, annual_universe_corrected, spy_data, cash_yield)

    print("\n" + "=" * 80)
    print("STEP 6: RUN ORIGINAL BACKTEST (Current BROAD_POOL)")
    print("=" * 80)

    # Download original BROAD_POOL data and run backtest
    print("\n[INFO] Running COMPASS v8.2 backtest with ORIGINAL universe (current BROAD_POOL only)...")
    original_data = download_broad_pool()
    annual_universe_original = compute_annual_top40(original_data)
    results_original = run_backtest(original_data, annual_universe_original, spy_data, cash_yield)

    print("\n" + "=" * 80)
    print("STEP 7: COMPARE RESULTS AND QUANTIFY SURVIVORSHIP BIAS")
    print("=" * 80)

    compare_and_quantify_bias(results_original, results_corrected)

    print("\n" + "=" * 80)
    print("EXPERIMENT 41 COMPLETE")
    print("=" * 80)

    print("\nNext steps:")
    print("1. Review backtests/exp41_comparison.txt for detailed metrics")
    print("2. Check backtests/exp41_survivorship_analysis.csv for delisted stock impact")
    print("3. Review backtests/exp41_survivorship_daily.csv for equity curve")


if __name__ == '__main__':
    main()
