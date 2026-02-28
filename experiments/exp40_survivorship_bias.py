#!/usr/bin/env python3
"""
Experiment #40: Quantify Survivorship Bias in COMPASS v8.2
===========================================================
Downloads REAL historical S&P 500 constituents from fja05680/sp500 repo,
downloads prices for delisted stocks via Stooq + yfinance fallback,
and runs the EXACT COMPASS v8.2 backtest with the point-in-time universe.

Compares vs production backtest to quantify survivorship bias.

This script is INFORMATIONAL ONLY — does NOT modify production code.

Usage:  python experiments/exp40_survivorship_bias.py
"""

import os
import sys
import time
import io
import pickle
import requests
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Set
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# COMPASS v8.2 PARAMETERS (EXACT COPY — DO NOT MODIFY)
# =============================================================================
INITIAL_CAPITAL = 100_000
TOP_N = 40
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
MIN_MOMENTUM_STOCKS = 20
HOLD_DAYS = 5
NUM_POSITIONS = 5
NUM_POSITIONS_RISK_OFF = 2
POSITION_STOP_LOSS = -0.08
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03
PORTFOLIO_STOP_LOSS = -0.15
REGIME_SMA_PERIOD = 200
REGIME_CONFIRM_DAYS = 3
TARGET_VOL = 0.15
LEVERAGE_MIN = 0.3
LEVERAGE_MAX = 1.0
VOL_LOOKBACK = 20
MIN_AGE_DAYS = 63
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.035
CASH_YIELD_SOURCE = 'AAA'
RECOVERY_STAGE_1_DAYS = 63
RECOVERY_STAGE_2_DAYS = 126

START_DATE = '2000-01-01'
END_DATE = '2027-01-01'

# Current BROAD_POOL (for comparison)
BROAD_POOL = [
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AVGO', 'ADBE', 'CRM', 'AMD',
    'INTC', 'CSCO', 'IBM', 'TXN', 'QCOM', 'ORCL', 'ACN', 'NOW', 'INTU',
    'AMAT', 'MU', 'LRCX', 'SNPS', 'CDNS', 'KLAC', 'MRVL',
    'BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'AXP', 'BLK',
    'SCHW', 'C', 'USB', 'PNC', 'TFC', 'CB', 'MMC', 'AIG',
    'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
    'AMGN', 'BMY', 'MDT', 'ISRG', 'SYK', 'GILD', 'REGN', 'VRTX', 'BIIB',
    'AMZN', 'TSLA', 'WMT', 'HD', 'PG', 'COST', 'KO', 'PEP', 'NKE',
    'MCD', 'DIS', 'SBUX', 'TGT', 'LOW', 'CL', 'KMB', 'GIS', 'EL',
    'MO', 'PM',
    'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'OXY', 'MPC', 'PSX', 'VLO',
    'GE', 'CAT', 'BA', 'HON', 'UNP', 'RTX', 'LMT', 'DE', 'UPS', 'FDX',
    'MMM', 'GD', 'NOC', 'EMR',
    'NEE', 'DUK', 'SO', 'D', 'AEP',
    'VZ', 'T', 'TMUS', 'CMCSA',
]

# Notable delisted S&P 500 stocks (ticker mappings for Stooq/yfinance)
# Some delisted tickers get reused — we need to handle date ranges carefully
DELISTED_TICKER_NOTES = {
    'ENE': 'Enron (bankrupt 2001)',
    'WCOM': 'WorldCom (bankrupt 2002, became MCI)',
    'LEH': 'Lehman Brothers (bankrupt 2008)',
    'BSC': 'Bear Stearns (acquired 2008)',
    'WM': 'Washington Mutual (bankrupt 2008) — ticker reused by Waste Mgmt',
    'CFC': 'Countrywide Financial (acquired 2008)',
    'MER': 'Merrill Lynch (acquired 2009)',
    'WB': 'Wachovia (acquired 2008)',
    'ABI': 'Anheuser-Busch (acquired 2008)',
    'SGP': 'Schering-Plough (acquired 2009)',
    'WYE': 'Wyeth (acquired 2009)',
    'GM': 'General Motors old (bankrupt 2009) — ticker reused',
    'APC': 'Anadarko Petroleum (acquired 2019)',
    'CELG': 'Celgene (acquired 2020)',
    'RTN': 'Raytheon (merged 2020, became RTX)',
    'DOW': 'Dow Inc (spun off 2019)',
    'CTXS': 'Citrix Systems (acquired 2022)',
    'TWTR': 'Twitter (acquired 2022)',
    'ATVI': 'Activision Blizzard (acquired 2023)',
}


# =============================================================================
# STEP 1: DOWNLOAD HISTORICAL S&P 500 CONSTITUENTS (DAILY SNAPSHOTS)
# =============================================================================

def download_sp500_snapshots() -> pd.DataFrame:
    """
    Download daily S&P 500 membership snapshots from fja05680/sp500 repo.
    Format: date, tickers (comma-separated list of all members on that date).
    Returns raw DataFrame with columns: date, tickers.
    """
    cache_file = 'data_cache/sp500_snapshots.csv'

    if os.path.exists(cache_file):
        print("[Cache] Loading S&P 500 daily snapshots...")
        df = pd.read_csv(cache_file, parse_dates=['date'])
        print(f"  {len(df)} snapshot dates loaded")
        return df

    print("[Download] Fetching S&P 500 daily snapshots from GitHub...")

    # Try GitHub API to find the actual filename
    raw = None
    try:
        api_url = 'https://api.github.com/repos/fja05680/sp500/contents'
        r = requests.get(api_url, timeout=30)
        files = r.json()
        csv_files = [f['name'] for f in files if f['name'].endswith('.csv') and 'Historical' in f['name']]
        if csv_files:
            fname = csv_files[0]
            dl_url = f'https://raw.githubusercontent.com/fja05680/sp500/master/{requests.utils.quote(fname)}'
            r = requests.get(dl_url, timeout=30)
            r.raise_for_status()
            raw = pd.read_csv(io.StringIO(r.text))
            print(f"  Downloaded: {fname} ({len(raw)} rows)")
    except Exception as e:
        print(f"  GitHub API failed: {e}")

    if raw is None:
        raise RuntimeError("Cannot download S&P 500 constituent history")

    # Columns are: date, tickers
    raw['date'] = pd.to_datetime(raw['date'])
    raw = raw.sort_values('date').reset_index(drop=True)

    os.makedirs('data_cache', exist_ok=True)
    raw.to_csv(cache_file, index=False)

    print(f"  Date range: {raw['date'].min().strftime('%Y-%m-%d')} to {raw['date'].max().strftime('%Y-%m-%d')}")

    # Count unique tickers across all snapshots
    all_tickers = set()
    for tickers_str in raw['tickers']:
        all_tickers.update(t.strip() for t in str(tickers_str).split(','))
    print(f"  Total unique tickers across all snapshots: {len(all_tickers)}")

    return raw


def build_membership_from_snapshots(snapshots: pd.DataFrame) -> Dict[str, List[Tuple]]:
    """
    Build membership periods from daily snapshots.
    Returns dict: ticker -> [(first_seen_date, last_seen_date), ...]
    """
    # Parse each snapshot into a set of tickers
    snapshot_dates = []
    snapshot_members = []
    for _, row in snapshots.iterrows():
        dt = row['date']
        tickers = set(t.strip() for t in str(row['tickers']).split(',') if t.strip())
        snapshot_dates.append(dt)
        snapshot_members.append(tickers)

    # Track membership periods
    # For each ticker, find contiguous date ranges where it appears
    all_tickers = set()
    for members in snapshot_members:
        all_tickers.update(members)

    membership = {}
    for ticker in all_tickers:
        periods = []
        in_period = False
        period_start = None

        for i, (dt, members) in enumerate(zip(snapshot_dates, snapshot_members)):
            if ticker in members:
                if not in_period:
                    period_start = dt
                    in_period = True
            else:
                if in_period:
                    periods.append((period_start, dt))
                    in_period = False

        # If still in a period at the end, it's still active
        if in_period:
            periods.append((period_start, None))

        membership[ticker] = periods

    return membership


def get_sp500_members_on_date_from_snapshots(snapshots: pd.DataFrame, date: pd.Timestamp) -> Set[str]:
    """
    Return set of tickers that were S&P 500 members on a given date.
    Uses the nearest snapshot on or before the given date.
    """
    # Find the most recent snapshot <= date
    valid = snapshots[snapshots['date'] <= date]
    if valid.empty:
        return set()
    latest = valid.iloc[-1]
    return set(t.strip() for t in str(latest['tickers']).split(',') if t.strip())


def identify_missing_tickers_from_snapshots(snapshots: pd.DataFrame) -> List[str]:
    """Find tickers that were historically in S&P 500 but NOT in current BROAD_POOL"""
    all_historical = set()
    for tickers_str in snapshots['tickers']:
        all_historical.update(t.strip() for t in str(tickers_str).split(',') if t.strip())
    current = set(BROAD_POOL)
    missing = all_historical - current
    return sorted(missing)


# =============================================================================
# STEP 2: DOWNLOAD PRICES FOR MISSING/DELISTED STOCKS
# =============================================================================

def stooq_ticker(ticker: str) -> str:
    """Convert standard ticker to Stooq format"""
    return f"{ticker.lower()}.us"


def download_stooq_stock(ticker: str, start: str = '20000101', end: str = '20261231',
                          max_retries: int = 3) -> Optional[pd.DataFrame]:
    """Download a single stock from Stooq"""
    stooq_sym = stooq_ticker(ticker)
    url = f'https://stooq.com/q/d/l/?s={stooq_sym}&d1={start}&d2={end}&i=d'

    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (COMPASS Exp40)'}, timeout=30)
            if r.status_code != 200:
                time.sleep(1)
                continue

            text = r.text.strip()
            if not text or 'No data' in text or len(text) < 50:
                return None

            df = pd.read_csv(io.StringIO(text), parse_dates=['Date'], index_col='Date')
            df = df.sort_index()

            if 'Close' not in df.columns or len(df) < 10:
                return None

            for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            df = df.dropna(subset=['Close'])
            return df

        except Exception:
            time.sleep(1)

    return None


def download_yfinance_stock(ticker: str) -> Optional[pd.DataFrame]:
    """Download a single stock from yfinance"""
    try:
        df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False)
        if df.empty or len(df) < 10:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return df
    except Exception:
        return None


def download_expanded_pool(missing_tickers: List[str],
                           snapshots: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """
    Download prices for all tickers needed:
    1. Current BROAD_POOL from yfinance (standard)
    2. Missing/delisted tickers from Stooq first, yfinance fallback
    """
    cache_file = 'data_cache/exp40_expanded_pool.pkl'

    if os.path.exists(cache_file):
        print("[Cache] Loading expanded pool data...")
        try:
            with open(cache_file, 'rb') as f:
                data = pickle.load(f)
            print(f"  {len(data)} symbols loaded from cache")
            return data
        except Exception:
            print("[Cache] Failed to load, re-downloading...")

    data = {}
    failed = []

    # 1. Download current BROAD_POOL from yfinance
    print(f"\n[yfinance] Downloading {len(BROAD_POOL)} BROAD_POOL symbols...")
    for i, symbol in enumerate(BROAD_POOL):
        df = download_yfinance_stock(symbol)
        if df is not None and len(df) > 100:
            data[symbol] = df
        else:
            failed.append(symbol)
        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(BROAD_POOL)}] Downloaded {len(data)} | Failed {len(failed)}")

    print(f"  BROAD_POOL: {len(data)} ok, {len(failed)} failed")

    # 2. Download missing tickers (Stooq first, yfinance fallback)
    # Filter to tickers that appeared in snapshots from 2000 onwards
    post_2000 = snapshots[snapshots['date'] >= '2000-01-01']
    post_2000_tickers = set()
    for tickers_str in post_2000['tickers']:
        post_2000_tickers.update(t.strip() for t in str(tickers_str).split(',') if t.strip())

    relevant_missing = [t for t in missing_tickers if t in post_2000_tickers]

    print(f"\n[Missing] {len(relevant_missing)} tickers were in S&P 500 during 2000-2026 but not in BROAD_POOL")

    stooq_ok = 0
    yf_ok = 0
    no_data = []

    for i, ticker in enumerate(relevant_missing):
        if ticker in data:
            continue

        # Try Stooq first
        df = download_stooq_stock(ticker)
        if df is not None and len(df) >= 10:
            data[ticker] = df
            stooq_ok += 1
        else:
            # Try yfinance
            df = download_yfinance_stock(ticker)
            if df is not None and len(df) >= 10:
                data[ticker] = df
                yf_ok += 1
            else:
                no_data.append(ticker)

        if (i + 1) % 25 == 0:
            print(f"  [{i+1}/{len(relevant_missing)}] Stooq: {stooq_ok} | yfinance: {yf_ok} | No data: {len(no_data)}")

        time.sleep(0.3)  # Be polite to Stooq

    print(f"\n  Missing tickers result:")
    print(f"    Stooq success:   {stooq_ok}")
    print(f"    yfinance success: {yf_ok}")
    print(f"    No data:         {len(no_data)}")
    if no_data:
        print(f"    No data tickers: {no_data[:30]}{'...' if len(no_data) > 30 else ''}")

    print(f"\n  TOTAL expanded pool: {len(data)} symbols")

    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)

    return data


def sanitize_price_data(data: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """
    Remove stocks with corrupted price data (common in Stooq delisted data).
    Filters out stocks that have daily returns > ±80% (impossible for S&P 500 stocks).
    """
    clean = {}
    removed = []

    for symbol, df in data.items():
        if 'Close' not in df.columns or len(df) < 10:
            removed.append((symbol, 'too_short'))
            continue

        returns = df['Close'].pct_change().dropna()
        max_ret = returns.abs().max()

        if max_ret > 0.80:  # >80% daily move = corrupted data
            removed.append((symbol, f'max_daily_return={max_ret:.1%}'))
            continue

        clean[symbol] = df

    if removed:
        print(f"\n  [SANITY] Removed {len(removed)} stocks with corrupted data:")
        for sym, reason in removed[:20]:
            print(f"    {sym:8s}: {reason}")
        if len(removed) > 20:
            print(f"    ... and {len(removed) - 20} more")

    print(f"  [SANITY] Clean pool: {len(clean)} symbols (removed {len(removed)})")
    return clean


# =============================================================================
# STEP 3: POINT-IN-TIME ANNUAL TOP-40
# =============================================================================

def compute_annual_top40_pit(price_data: Dict[str, pd.DataFrame],
                              snapshots: pd.DataFrame) -> Dict[int, List[str]]:
    """
    Point-in-time annual top-40 selection.
    For each year, only consider stocks that were S&P 500 members AT THAT TIME.
    Then rank by dollar volume (same as production).
    """
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}

    for year in years:
        # Point-in-time: who was in S&P 500 on Jan 1 of this year?
        ref_date = pd.Timestamp(f'{year}-01-01')
        sp500_members = get_sp500_members_on_date_from_snapshots(snapshots, ref_date)

        # Ranking period: prior year
        if year == years[0]:
            ranking_end = pd.Timestamp(f'{year}-02-01')
            ranking_start = pd.Timestamp(f'{year-1}-01-01')
        else:
            ranking_end = pd.Timestamp(f'{year}-01-01')
            ranking_start = pd.Timestamp(f'{year-1}-01-01')

        scores = {}
        for symbol in sp500_members:
            if symbol not in price_data:
                continue
            df = price_data[symbol]

            # Handle timezone-naive vs timezone-aware
            idx = df.index
            if idx.tz is not None:
                rs = ranking_start.tz_localize(idx.tz)
                re_ = ranking_end.tz_localize(idx.tz)
            else:
                rs = ranking_start
                re_ = ranking_end

            mask = (idx >= rs) & (idx < re_)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dollar_vol = (window['Close'] * window['Volume']).mean()
            scores[symbol] = dollar_vol

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_n = [s for s, _ in ranked[:TOP_N]]
        annual_universe[year] = top_n

        # Compare with what would have been selected from BROAD_POOL only
        broad_only = [s for s in top_n if s in BROAD_POOL]
        historical_only = [s for s in top_n if s not in BROAD_POOL]

        print(f"  {year}: S&P500 members={len(sp500_members)}, "
              f"with data={len(scores)}, Top-{TOP_N} selected | "
              f"{len(broad_only)} current + {len(historical_only)} historical")
        if historical_only:
            print(f"         Historical stocks in top-40: {historical_only}")

    return annual_universe


# =============================================================================
# COMPASS v8.2 BACKTEST (EXACT COPY)
# =============================================================================

def compute_regime(spy_data: pd.DataFrame) -> pd.Series:
    spy_close = spy_data['Close']
    sma200 = spy_close.rolling(REGIME_SMA_PERIOD).mean()
    raw_signal = spy_close > sma200

    regime = pd.Series(index=spy_close.index, dtype=bool)
    regime.iloc[:REGIME_SMA_PERIOD] = True

    current_regime = True
    consecutive_count = 0
    last_raw = True

    for i in range(REGIME_SMA_PERIOD, len(raw_signal)):
        raw = raw_signal.iloc[i]
        if pd.isna(raw):
            regime.iloc[i] = current_regime
            continue
        if raw == last_raw:
            consecutive_count += 1
        else:
            consecutive_count = 1
            last_raw = raw
        if raw != current_regime and consecutive_count >= REGIME_CONFIRM_DAYS:
            current_regime = raw
        regime.iloc[i] = current_regime

    return regime


def compute_momentum_scores(price_data, tradeable, date, all_dates, date_idx):
    scores = {}
    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        needed = MOMENTUM_LOOKBACK + MOMENTUM_SKIP
        try:
            sym_idx = df.index.get_loc(date)
        except KeyError:
            continue
        if sym_idx < needed:
            continue
        close_today = df['Close'].iloc[sym_idx]
        close_skip = df['Close'].iloc[sym_idx - MOMENTUM_SKIP]
        close_lookback = df['Close'].iloc[sym_idx - MOMENTUM_LOOKBACK]
        if close_lookback <= 0 or close_skip <= 0 or close_today <= 0:
            continue
        momentum_90d = (close_skip / close_lookback) - 1.0
        skip_5d = (close_today / close_skip) - 1.0
        score = momentum_90d - skip_5d
        scores[symbol] = score
    return scores


def compute_volatility_weights(price_data, selected, date):
    vols = {}
    for symbol in selected:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        sym_idx = df.index.get_loc(date)
        if sym_idx < VOL_LOOKBACK + 1:
            continue
        returns = df['Close'].iloc[sym_idx - VOL_LOOKBACK:sym_idx + 1].pct_change().dropna()
        if len(returns) < VOL_LOOKBACK - 2:
            continue
        vol = returns.std() * np.sqrt(252)
        if vol > 0.01:
            vols[symbol] = vol
    if not vols:
        return {s: 1.0 / len(selected) for s in selected}
    raw_weights = {s: 1.0 / v for s, v in vols.items()}
    total = sum(raw_weights.values())
    return {s: w / total for s, w in raw_weights.items()}


def compute_dynamic_leverage(spy_data, date):
    if date not in spy_data.index:
        return 1.0
    idx = spy_data.index.get_loc(date)
    if idx < VOL_LOOKBACK + 1:
        return 1.0
    returns = spy_data['Close'].iloc[idx - VOL_LOOKBACK:idx + 1].pct_change().dropna()
    if len(returns) < VOL_LOOKBACK - 2:
        return 1.0
    realized_vol = returns.std() * np.sqrt(252)
    if realized_vol < 0.01:
        return LEVERAGE_MAX
    leverage = TARGET_VOL / realized_vol
    return max(LEVERAGE_MIN, min(LEVERAGE_MAX, leverage))


def get_tradeable_symbols(price_data, date, first_date, annual_universe):
    eligible = set(annual_universe.get(date.year, []))
    tradeable = []
    for symbol in eligible:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        symbol_first_date = df.index[0]
        days_since_start = (date - symbol_first_date).days
        if date <= first_date + timedelta(days=30):
            tradeable.append(symbol)
        elif days_since_start >= MIN_AGE_DAYS:
            tradeable.append(symbol)
    return tradeable


def download_spy() -> pd.DataFrame:
    cache_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        print("[Cache] Loading SPY data...")
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    print("[Download] Downloading SPY...")
    df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def download_cash_yield() -> Optional[pd.Series]:
    cache_file = 'data_cache/moody_aaa_yield.csv'
    if os.path.exists(cache_file):
        print("[Cache] Loading Moody's Aaa yield data...")
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        daily = df['yield_pct'].resample('D').ffill()
        return daily
    print("[Download] Downloading Moody's Aaa yield from FRED...")
    try:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA&cosd=1999-01-01&coed=2026-12-31'
        df = pd.read_csv(url, parse_dates=['observation_date'], index_col='observation_date')
        df.columns = ['yield_pct']
        os.makedirs('data_cache', exist_ok=True)
        df.to_csv(cache_file)
        daily = df['yield_pct'].resample('D').ffill()
        return daily
    except Exception as e:
        print(f"  FRED failed: {e}. Using fixed {CASH_YIELD_RATE:.1%}")
        return None


def run_backtest(price_data, annual_universe, spy_data, cash_yield_daily=None, label=""):
    """Run COMPASS backtest — EXACT copy of production logic"""

    print(f"\n{'='*80}")
    print(f"RUNNING COMPASS BACKTEST [{label}]")
    print(f"{'='*80}")

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    regime = compute_regime(spy_data)

    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")

    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []

    peak_value = float(INITIAL_CAPITAL)
    in_protection_mode = False
    protection_stage = 0
    stop_loss_day_index = None
    post_stop_base = None

    risk_on_days = 0
    risk_off_days = 0
    current_year = None

    # Track which historical (non-BROAD_POOL) stocks entered the portfolio
    historical_stock_trades = []

    for i, date in enumerate(all_dates):
        if date.year != current_year:
            current_year = date.year

        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        if portfolio_value > peak_value and not in_protection_mode:
            peak_value = portfolio_value

        if in_protection_mode and stop_loss_day_index is not None:
            days_since_stop = i - stop_loss_day_index
            is_regime_on = True
            if date in regime.index:
                is_regime_on = bool(regime.loc[date])
            if protection_stage == 1 and days_since_stop >= RECOVERY_STAGE_1_DAYS and is_regime_on:
                protection_stage = 2
            if protection_stage == 2 and days_since_stop >= RECOVERY_STAGE_2_DAYS and is_regime_on:
                in_protection_mode = False
                protection_stage = 0
                peak_value = portfolio_value
                stop_loss_day_index = None
                post_stop_base = None

        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        if drawdown <= PORTFOLIO_STOP_LOSS and not in_protection_mode:
            stop_events.append({'date': date, 'portfolio_value': portfolio_value, 'drawdown': drawdown})
            for symbol in list(positions.keys()):
                if symbol in price_data and date in price_data[symbol].index:
                    exit_price = price_data[symbol].loc[date, 'Close']
                    pos = positions[symbol]
                    proceeds = pos['shares'] * exit_price
                    commission = pos['shares'] * COMMISSION_PER_SHARE
                    cash += proceeds - commission
                    pnl = (exit_price - pos['entry_price']) * pos['shares'] - commission
                    trades.append({
                        'symbol': symbol, 'entry_date': pos['entry_date'],
                        'exit_date': date, 'exit_reason': 'portfolio_stop',
                        'pnl': pnl, 'return': pnl / (pos['entry_price'] * pos['shares'])
                    })
                del positions[symbol]
            in_protection_mode = True
            protection_stage = 1
            stop_loss_day_index = i
            post_stop_base = cash

        is_risk_on = True
        if date in regime.index:
            is_risk_on = bool(regime.loc[date])
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        if in_protection_mode:
            if protection_stage == 1:
                max_positions = 2
                current_leverage = 0.3
            else:
                max_positions = 3
                current_leverage = 1.0
        elif not is_risk_on:
            max_positions = NUM_POSITIONS_RISK_OFF
            current_leverage = 1.0
        else:
            max_positions = NUM_POSITIONS
            current_leverage = compute_dynamic_leverage(spy_data, date)

        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        if cash > 0:
            if cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue
            current_price = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            days_held = i - pos['entry_idx']
            if days_held >= HOLD_DAYS:
                exit_reason = 'hold_expired'

            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            if pos_return <= POSITION_STOP_LOSS:
                exit_reason = 'position_stop'

            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                trailing_level = pos['high_price'] * (1 - TRAILING_STOP_PCT)
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'

            if exit_reason is None and len(positions) > max_positions:
                pos_returns = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        cp = price_data[s].loc[date, 'Close']
                        pos_returns[s] = (cp - p['entry_price']) / p['entry_price']
                worst = min(pos_returns, key=pos_returns.get)
                if symbol == worst:
                    exit_reason = 'regime_reduce'

            if exit_reason:
                shares = pos['shares']
                proceeds = shares * current_price
                commission = shares * COMMISSION_PER_SHARE
                cash += proceeds - commission
                pnl = (current_price - pos['entry_price']) * shares - commission
                trade_record = {
                    'symbol': symbol, 'entry_date': pos['entry_date'],
                    'exit_date': date, 'exit_reason': exit_reason,
                    'pnl': pnl, 'return': pnl / (pos['entry_price'] * shares)
                }
                trades.append(trade_record)
                if symbol not in BROAD_POOL:
                    historical_stock_trades.append(trade_record)
                del positions[symbol]

        needed = max_positions - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            scores = compute_momentum_scores(price_data, tradeable_symbols, date, all_dates, i)
            available_scores = {s: sc for s, sc in scores.items() if s not in positions}
            if len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                selected = [s for s, _ in ranked[:needed]]
                weights = compute_volatility_weights(price_data, selected, date)
                effective_capital = cash * current_leverage * 0.95
                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue
                    entry_price = price_data[symbol].loc[date, 'Close']
                    if entry_price <= 0:
                        continue
                    weight = weights.get(symbol, 1.0 / len(selected))
                    position_value = effective_capital * weight
                    max_per_position = cash * 0.40
                    position_value = min(position_value, max_per_position)
                    shares = position_value / entry_price
                    cost = shares * entry_price
                    commission = shares * COMMISSION_PER_SHARE
                    if cost + commission <= cash * 0.90:
                        positions[symbol] = {
                            'entry_price': entry_price, 'shares': shares,
                            'entry_date': date, 'entry_idx': i,
                            'high_price': entry_price,
                        }
                        cash -= cost + commission

        portfolio_values.append({
            'date': date, 'value': portfolio_value, 'cash': cash,
            'positions': len(positions), 'drawdown': drawdown,
            'leverage': current_leverage, 'in_protection': in_protection_mode,
            'risk_on': is_risk_on, 'universe_size': len(tradeable_symbols)
        })

        if i % 252 == 0 and i > 0:
            year_num = i // 252
            regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
            prot_str = f" [PROTECTION S{protection_stage}]" if in_protection_mode else ""
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | DD: {drawdown:.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_str}{prot_str} | "
                  f"Pos: {len(positions)}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'annual_universe': annual_universe,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
        'historical_stock_trades': historical_stock_trades,
    }


def calculate_metrics(results):
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']
    stop_df = results['stop_events']

    initial = INITIAL_CAPITAL
    final_value = df['value'].iloc[-1]
    years = len(df) / 252
    cagr = (final_value / initial) ** (1 / years) - 1

    returns = df['value'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(252)
    max_dd = df['drawdown'].min()
    sharpe = cagr / volatility if volatility > 0 else 0

    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0

    protection_days = df['in_protection'].sum()
    protection_pct = protection_days / len(df) * 100

    exit_reasons = trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in trades_df.columns and len(trades_df) > 0 else {}

    return {
        'final_value': final_value,
        'cagr': cagr,
        'volatility': volatility,
        'sharpe': sharpe,
        'max_drawdown': max_dd,
        'trades': len(trades_df),
        'win_rate': win_rate,
        'stop_events': len(stop_df),
        'protection_days': protection_days,
        'protection_pct': protection_pct,
        'exit_reasons': exit_reasons,
        'years': years,
    }


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("EXPERIMENT #40: QUANTIFY SURVIVORSHIP BIAS IN COMPASS v8.2")
    print("=" * 80)
    print(f"Using EXACT COMPASS v8.2 parameters (LOCKED)")
    print(f"Comparing: current BROAD_POOL (113 stocks) vs historical S&P 500 constituents")
    print()

    # =========================================================================
    # STEP 1: Download S&P 500 constituent history (daily snapshots)
    # =========================================================================
    print("\n--- STEP 1: S&P 500 Constituent History ---")
    snapshots = download_sp500_snapshots()

    # Count all unique historical tickers
    all_historical_tickers = set()
    for tickers_str in snapshots['tickers']:
        all_historical_tickers.update(t.strip() for t in str(tickers_str).split(',') if t.strip())
    print(f"  Total unique historical S&P 500 tickers: {len(all_historical_tickers)}")

    missing_tickers = identify_missing_tickers_from_snapshots(snapshots)
    print(f"  Tickers in S&P 500 history but NOT in BROAD_POOL: {len(missing_tickers)}")

    # Notable ones
    notable = [t for t in missing_tickers if t in DELISTED_TICKER_NOTES]
    if notable:
        print(f"\n  Notable delisted/acquired stocks:")
        for t in notable:
            print(f"    {t:6s}: {DELISTED_TICKER_NOTES[t]}")

    # =========================================================================
    # STEP 2: Download prices for expanded universe
    # =========================================================================
    print("\n--- STEP 2: Download Expanded Universe ---")
    expanded_data = download_expanded_pool(missing_tickers, snapshots)

    # Sanitize: remove stocks with corrupted price data
    expanded_data = sanitize_price_data(expanded_data)

    # Also need SPY and cash yield
    spy_data = download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    cash_yield_daily = download_cash_yield()

    # =========================================================================
    # STEP 3: Point-in-time annual top-40
    # =========================================================================
    print("\n--- STEP 3: Point-in-Time Annual Top-40 ---")
    pit_universe = compute_annual_top40_pit(expanded_data, snapshots)

    # =========================================================================
    # STEP 4: Run survivorship-corrected backtest
    # =========================================================================
    print("\n--- STEP 4: Survivorship-Corrected Backtest ---")
    pit_results = run_backtest(expanded_data, pit_universe, spy_data, cash_yield_daily,
                               label="SURVIVORSHIP-CORRECTED")
    pit_metrics = calculate_metrics(pit_results)

    # =========================================================================
    # STEP 5: Compare with production baseline
    # =========================================================================
    print("\n" + "=" * 80)
    print("RESULTS: SURVIVORSHIP BIAS QUANTIFICATION")
    print("=" * 80)

    # Production baseline metrics (from MEMORY.md)
    baseline = {
        'cagr': 0.1856,
        'sharpe': 0.90,
        'max_drawdown': -0.269,
        'final_value': 8_430_000,
    }

    print(f"\n{'Metric':<25} {'Baseline (BROAD_POOL)':>22} {'Corrected (PIT)':>22} {'Delta':>15}")
    print("-" * 87)
    print(f"{'CAGR':<25} {baseline['cagr']:>21.2%} {pit_metrics['cagr']:>21.2%} {pit_metrics['cagr']-baseline['cagr']:>+14.2%}")
    print(f"{'Sharpe':<25} {baseline['sharpe']:>22.2f} {pit_metrics['sharpe']:>22.2f} {pit_metrics['sharpe']-baseline['sharpe']:>+15.2f}")
    print(f"{'Max Drawdown':<25} {baseline['max_drawdown']:>21.1%} {pit_metrics['max_drawdown']:>21.1%} {pit_metrics['max_drawdown']-baseline['max_drawdown']:>+14.1%}")
    print(f"{'Final Value':<25} ${baseline['final_value']:>20,.0f} ${pit_metrics['final_value']:>20,.0f}")

    bias = baseline['cagr'] - pit_metrics['cagr']
    print(f"\n*** SURVIVORSHIP BIAS = {bias:+.2%} CAGR ***")
    print(f"    (Positive = bias inflated production results)")

    # =========================================================================
    # STEP 6: Analyze historical stock impact
    # =========================================================================
    print(f"\n--- Historical Stock Impact ---")
    hist_trades = pit_results.get('historical_stock_trades', [])
    if hist_trades:
        ht_df = pd.DataFrame(hist_trades)
        print(f"  Trades in historical (non-BROAD_POOL) stocks: {len(ht_df)}")
        print(f"  Total P&L from historical stocks: ${ht_df['pnl'].sum():,.2f}")
        print(f"  Win rate: {(ht_df['pnl'] > 0).mean():.1%}")
        print(f"  Avg return per trade: {ht_df['return'].mean():.2%}")

        # Which historical stocks had the biggest impact?
        by_symbol = ht_df.groupby('symbol').agg(
            trades=('pnl', 'count'),
            total_pnl=('pnl', 'sum'),
            avg_return=('return', 'mean')
        ).sort_values('total_pnl')

        print(f"\n  Historical stocks by total P&L impact:")
        for sym, row in by_symbol.iterrows():
            note = DELISTED_TICKER_NOTES.get(sym, '')
            print(f"    {sym:6s}: {row['trades']:3.0f} trades, P&L ${row['total_pnl']:>10,.2f}, "
                  f"avg ret {row['avg_return']:>+7.2%}  {note}")
    else:
        print("  No historical stocks entered the portfolio (all top-40 were current BROAD_POOL stocks)")

    # =========================================================================
    # STEP 7: Universe overlap analysis
    # =========================================================================
    print(f"\n--- Universe Overlap Analysis ---")
    total_overlap = 0
    total_years = 0
    for year in sorted(pit_universe.keys()):
        pit_set = set(pit_universe[year])
        broad_set = set(BROAD_POOL)
        overlap = pit_set & broad_set
        historical_in_top40 = pit_set - broad_set
        pct = len(overlap) / len(pit_set) * 100 if pit_set else 0
        total_overlap += pct
        total_years += 1
        if historical_in_top40:
            print(f"  {year}: {pct:.0f}% overlap | Historical: {sorted(historical_in_top40)}")

    if total_years > 0:
        avg_overlap = total_overlap / total_years
        print(f"\n  Average overlap with BROAD_POOL: {avg_overlap:.1f}%")

    # =========================================================================
    # SAVE OUTPUTS
    # =========================================================================
    os.makedirs('backtests', exist_ok=True)

    pit_results['portfolio_values'].to_csv('backtests/exp40_survivorship_daily.csv', index=False)
    if len(pit_results['trades']) > 0:
        pit_results['trades'].to_csv('backtests/exp40_survivorship_trades.csv', index=False)

    # Analysis CSV
    if hist_trades:
        pd.DataFrame(hist_trades).to_csv('backtests/exp40_survivorship_analysis.csv', index=False)

    print(f"\n--- Output Files ---")
    print(f"  backtests/exp40_survivorship_daily.csv")
    print(f"  backtests/exp40_survivorship_trades.csv")
    print(f"  backtests/exp40_survivorship_analysis.csv")

    print(f"\n{'='*80}")
    print(f"EXPERIMENT #40 COMPLETE")
    print(f"Survivorship Bias: {bias:+.2%} CAGR")
    print(f"{'='*80}")
