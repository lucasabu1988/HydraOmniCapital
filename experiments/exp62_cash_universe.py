#!/usr/bin/env python3
"""
Experiment #62: Cash-Rich Universe Selection
=============================================
Instead of a hardcoded 113-stock pool or dollar-volume top-113:
  1) Each year (2009-2026), get ACTUAL S&P 500 members (point-in-time)
  2) Fetch cash + STI and revenue from SEC EDGAR XBRL
  3) Rank -> top 113 by cash/revenue RATIO (normalizes for company size)
  4) From those 113, top 40 by dollar volume (same as production)
  5) COMPASS v8.2 algorithm runs on those 40

Hypothesis: Cash/revenue ratio filters for financial strength without
the bank deposit bias that absolute cash rankings create. A tech company
with $50B cash on $100B revenue (0.5x) is more "cash-rich" than a bank
with $300B in customer deposits on $100B revenue (3.0x).

Data source: SEC EDGAR Company Facts API (free, no API key)
Period: 2009-2026 (XBRL became mandatory for large accelerated filers in 2009)

Baseline comparison:
  - Production (hardcoded 113, dollar-vol top-40): 18.56% CAGR (survivorship bias)
  - Exp40 survivorship-corrected (PIT 500, dollar-vol top-40): 13.37% CAGR
  - Exp61 (PIT 500, top-113 by dollar-vol, top-40 by momentum): see exp61

Kill criteria: CAGR < 10% or MaxDD > -35%
"""

import os
import sys
import json
import time
import pickle
import numpy as np
import pandas as pd
import yfinance as yf
import requests
from datetime import timedelta
from typing import Dict, List, Optional, Set, Tuple
import warnings
warnings.filterwarnings('ignore')

# =============================================================================
# COMPASS v8.2 PARAMETERS (EXACT COPY — DO NOT MODIFY)
# =============================================================================
INITIAL_CAPITAL = 100_000
TOP_N = 40
BROAD_N = 113
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

START_DATE = '2009-01-01'
END_DATE = '2027-01-01'
SEED = 666

np.random.seed(SEED)

SEC_EDGAR_CACHE = 'data_cache/sec_edgar_cash.json'
SEC_EDGAR_REVENUE_CACHE = 'data_cache/sec_edgar_revenue.json'
SEC_CIK_CACHE = 'data_cache/sec_cik_mapping.json'
SEC_HEADERS = {'User-Agent': 'OmniCapital research@omnicapital.com'}
SEC_RATE_LIMIT = 0.12  # seconds between requests (< 10 req/sec)

# XBRL field names for cash + short-term investments, in priority order
CASH_FIELDS = [
    'CashCashEquivalentsAndShortTermInvestments',
    'CashAndShortTermInvestments',
    'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents',
    'CashAndCashEquivalentsAtCarryingValue',
    'Cash',
]

# XBRL field names for revenue, in priority order
REVENUE_FIELDS = [
    'Revenues',
    'RevenueFromContractWithCustomerExcludingAssessedTax',
    'SalesRevenueNet',
    'SalesRevenueGoodsNet',
    'SalesRevenueServicesNet',
]

# XBRL field names for net income, in priority order
NET_INCOME_FIELDS = [
    'NetIncomeLoss',
    'ProfitLoss',
    'NetIncomeLossAvailableToCommonStockholdersBasic',
]

SEC_EDGAR_NETINCOME_CACHE = 'data_cache/sec_edgar_netincome.json'


# =============================================================================
# SEC EDGAR DATA DOWNLOAD
# =============================================================================

def load_cik_mapping() -> Dict[str, str]:
    if os.path.exists(SEC_CIK_CACHE):
        with open(SEC_CIK_CACHE, 'r') as f:
            return json.load(f)

    print("[SEC EDGAR] Downloading CIK mapping...")
    url = 'https://www.sec.gov/files/company_tickers.json'
    r = requests.get(url, headers=SEC_HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()

    # Map ticker -> CIK (zero-padded to 10 digits)
    mapping = {}
    for entry in data.values():
        ticker = entry['ticker'].upper().replace('.', '-')
        cik = str(entry['cik_str']).zfill(10)
        if ticker not in mapping:
            mapping[ticker] = cik

    os.makedirs(os.path.dirname(SEC_CIK_CACHE), exist_ok=True)
    with open(SEC_CIK_CACHE, 'w') as f:
        json.dump(mapping, f, indent=2)
    print(f"  Mapped {len(mapping)} tickers to CIKs")
    return mapping


def _extract_annual_cash(facts: dict) -> Dict[int, float]:
    """Extract annual cash + STI from SEC EDGAR company facts."""
    us_gaap = facts.get('facts', {}).get('us-gaap', {})

    for field_name in CASH_FIELDS:
        if field_name not in us_gaap:
            continue

        units = us_gaap[field_name].get('units', {})
        usd_entries = units.get('USD', [])
        if not usd_entries:
            continue

        # Filter for annual 10-K filings only
        annual = [e for e in usd_entries if e.get('form') == '10-K']
        if not annual:
            continue

        # Deduplicate by fiscal year end date, keep latest filing
        by_end = {}
        for entry in annual:
            end_date = entry.get('end', '')
            val = entry.get('val', 0)
            if end_date and val and val > 0:
                year = int(end_date[:4])
                # Use the most recent filing for each year
                if year not in by_end or entry.get('filed', '') > by_end[year][1]:
                    by_end[year] = (val, entry.get('filed', ''))

        if by_end:
            return {year: val for year, (val, _) in by_end.items()}

    return {}


def download_sec_edgar_cash(tickers: List[str], cik_mapping: Dict[str, str]) -> Dict[str, Dict[int, float]]:
    """Download cash data from SEC EDGAR for all tickers. Returns {ticker: {year: cash_value}}."""

    # Load cache
    if os.path.exists(SEC_EDGAR_CACHE):
        with open(SEC_EDGAR_CACHE, 'r') as f:
            cache = json.load(f)
        # Convert string keys back to int
        cache = {t: {int(y): v for y, v in years.items()} for t, years in cache.items()}
    else:
        cache = {}

    # Find tickers that need downloading
    to_download = [t for t in tickers if t not in cache]
    if not to_download:
        print(f"[SEC EDGAR] All {len(tickers)} tickers cached")
        return {t: cache.get(t, {}) for t in tickers}

    print(f"[SEC EDGAR] Downloading cash data for {len(to_download)} tickers "
          f"({len(cache)} already cached)...")

    success = 0
    no_cik = 0
    errors = 0
    no_data = 0

    for i, ticker in enumerate(to_download):
        if i > 0 and i % 50 == 0:
            print(f"  Progress: {i}/{len(to_download)} ({success} success, {no_cik} no CIK, "
                  f"{no_data} no data, {errors} errors)")
            # Save intermediate cache
            _save_edgar_cache(cache)

        cik = cik_mapping.get(ticker)
        if not cik:
            no_cik += 1
            cache[ticker] = {}
            continue

        try:
            url = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
            time.sleep(SEC_RATE_LIMIT)
            r = requests.get(url, headers=SEC_HEADERS, timeout=15)
            if r.status_code == 404:
                cache[ticker] = {}
                no_data += 1
                continue
            r.raise_for_status()

            cash_by_year = _extract_annual_cash(r.json())
            cache[ticker] = cash_by_year
            if cash_by_year:
                success += 1
            else:
                no_data += 1
        except Exception as e:
            errors += 1
            cache[ticker] = {}

    _save_edgar_cache(cache)
    print(f"  Done: {success} success, {no_cik} no CIK, {no_data} no cash data, {errors} errors")
    return {t: cache.get(t, {}) for t in tickers}


def _save_edgar_cache(cache: dict, path: str = SEC_EDGAR_CACHE):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    serializable = {t: {str(y): v for y, v in years.items()} for t, years in cache.items()}
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(serializable, f)
    os.replace(tmp, path)


def _extract_annual_revenue(facts: dict) -> Dict[int, float]:
    """Extract annual revenue from SEC EDGAR company facts."""
    us_gaap = facts.get('facts', {}).get('us-gaap', {})

    for field_name in REVENUE_FIELDS:
        if field_name not in us_gaap:
            continue

        units = us_gaap[field_name].get('units', {})
        usd_entries = units.get('USD', [])
        if not usd_entries:
            continue

        # Filter for annual 10-K filings, with duration > 300 days (full year, not quarterly)
        annual = [e for e in usd_entries
                  if e.get('form') == '10-K'
                  and e.get('val', 0) > 0]
        if not annual:
            continue

        by_end = {}
        for entry in annual:
            end_date = entry.get('end', '')
            start_date = entry.get('start', '')
            val = entry.get('val', 0)
            # Filter for full-year periods (> 300 days)
            if start_date and end_date:
                try:
                    from datetime import datetime as dt
                    s = dt.strptime(start_date, '%Y-%m-%d')
                    e = dt.strptime(end_date, '%Y-%m-%d')
                    duration = (e - s).days
                    if duration < 300:
                        continue
                except Exception:
                    pass
            year = int(end_date[:4])
            if year not in by_end or entry.get('filed', '') > by_end[year][1]:
                by_end[year] = (val, entry.get('filed', ''))

        if by_end:
            return {year: val for year, (val, _) in by_end.items()}

    return {}


def download_sec_edgar_revenue(tickers: List[str], cik_mapping: Dict[str, str]) -> Dict[str, Dict[int, float]]:
    """Download revenue data from SEC EDGAR. Returns {ticker: {year: revenue}}."""

    if os.path.exists(SEC_EDGAR_REVENUE_CACHE):
        with open(SEC_EDGAR_REVENUE_CACHE, 'r') as f:
            cache = json.load(f)
        cache = {t: {int(y): v for y, v in years.items()} for t, years in cache.items()}
    else:
        cache = {}

    to_download = [t for t in tickers if t not in cache]
    if not to_download:
        print(f"[SEC EDGAR] All {len(tickers)} tickers revenue cached")
        return {t: cache.get(t, {}) for t in tickers}

    print(f"[SEC EDGAR] Downloading revenue for {len(to_download)} tickers "
          f"({len(cache)} already cached)...")

    success = 0
    no_cik = 0
    errors = 0
    no_data = 0

    for i, ticker in enumerate(to_download):
        if i > 0 and i % 50 == 0:
            print(f"  Revenue progress: {i}/{len(to_download)} ({success} success)")
            _save_edgar_cache(cache, SEC_EDGAR_REVENUE_CACHE)

        cik = cik_mapping.get(ticker)
        if not cik:
            no_cik += 1
            cache[ticker] = {}
            continue

        try:
            url = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
            time.sleep(SEC_RATE_LIMIT)
            r = requests.get(url, headers=SEC_HEADERS, timeout=15)
            if r.status_code == 404:
                cache[ticker] = {}
                no_data += 1
                continue
            r.raise_for_status()

            rev_by_year = _extract_annual_revenue(r.json())
            cache[ticker] = rev_by_year
            if rev_by_year:
                success += 1
            else:
                no_data += 1
        except Exception:
            errors += 1
            cache[ticker] = {}

    _save_edgar_cache(cache, SEC_EDGAR_REVENUE_CACHE)
    print(f"  Done: {success} success, {no_cik} no CIK, {no_data} no revenue, {errors} errors")
    return {t: cache.get(t, {}) for t in tickers}


def _extract_annual_netincome(facts: dict) -> Dict[int, float]:
    """Extract annual net income from SEC EDGAR company facts."""
    us_gaap = facts.get('facts', {}).get('us-gaap', {})

    for field_name in NET_INCOME_FIELDS:
        if field_name not in us_gaap:
            continue

        units = us_gaap[field_name].get('units', {})
        usd_entries = units.get('USD', [])
        if not usd_entries:
            continue

        annual = [e for e in usd_entries if e.get('form') == '10-K']
        if not annual:
            continue

        by_end = {}
        for entry in annual:
            end_date = entry.get('end', '')
            start_date = entry.get('start', '')
            val = entry.get('val')
            if not end_date or val is None:
                continue
            # Filter for full-year periods
            if start_date and end_date:
                try:
                    from datetime import datetime as dt
                    s = dt.strptime(start_date, '%Y-%m-%d')
                    e = dt.strptime(end_date, '%Y-%m-%d')
                    if (e - s).days < 300:
                        continue
                except Exception:
                    pass
            year = int(end_date[:4])
            if year not in by_end or entry.get('filed', '') > by_end[year][1]:
                by_end[year] = (val, entry.get('filed', ''))

        if by_end:
            return {year: val for year, (val, _) in by_end.items()}

    return {}


def download_sec_edgar_netincome(tickers: List[str], cik_mapping: Dict[str, str]) -> Dict[str, Dict[int, float]]:
    """Download net income data from SEC EDGAR. Returns {ticker: {year: net_income}}."""

    if os.path.exists(SEC_EDGAR_NETINCOME_CACHE):
        with open(SEC_EDGAR_NETINCOME_CACHE, 'r') as f:
            cache = json.load(f)
        cache = {t: {int(y): v for y, v in years.items()} for t, years in cache.items()}
    else:
        cache = {}

    to_download = [t for t in tickers if t not in cache]
    if not to_download:
        print(f"[SEC EDGAR] All {len(tickers)} tickers net income cached")
        return {t: cache.get(t, {}) for t in tickers}

    print(f"[SEC EDGAR] Downloading net income for {len(to_download)} tickers "
          f"({len(cache)} already cached)...")

    success = 0
    no_cik = 0
    errors = 0
    no_data = 0

    for i, ticker in enumerate(to_download):
        if i > 0 and i % 50 == 0:
            print(f"  Net income progress: {i}/{len(to_download)} ({success} success)")
            _save_edgar_cache(cache, SEC_EDGAR_NETINCOME_CACHE)

        cik = cik_mapping.get(ticker)
        if not cik:
            no_cik += 1
            cache[ticker] = {}
            continue

        try:
            url = f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json'
            time.sleep(SEC_RATE_LIMIT)
            r = requests.get(url, headers=SEC_HEADERS, timeout=15)
            if r.status_code == 404:
                cache[ticker] = {}
                no_data += 1
                continue
            r.raise_for_status()

            ni_by_year = _extract_annual_netincome(r.json())
            cache[ticker] = ni_by_year
            if ni_by_year:
                success += 1
            else:
                no_data += 1
        except Exception:
            errors += 1
            cache[ticker] = {}

    _save_edgar_cache(cache, SEC_EDGAR_NETINCOME_CACHE)
    print(f"  Done: {success} success, {no_cik} no CIK, {no_data} no data, {errors} errors")
    return {t: cache.get(t, {}) for t in tickers}


# =============================================================================
# DATA LOADING (reuses exp61 cached data)
# =============================================================================

def load_sp500_snapshots() -> pd.DataFrame:
    cache_file = 'data_cache/sp500_snapshots.csv'
    if not os.path.exists(cache_file):
        print("ERROR: sp500_snapshots.csv not found. Run exp40 first.")
        sys.exit(1)
    print("[Cache] Loading S&P 500 daily snapshots...")
    return pd.read_csv(cache_file, parse_dates=['date'])


def load_universe_prices() -> Dict[str, pd.DataFrame]:
    merged_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              'data_sources', 'merged_universe')
    if os.path.exists(merged_dir):
        print(f"[merged_universe] Loading from {merged_dir}...")
        data = {}
        corrupted = 0
        for f in os.listdir(merged_dir):
            if not f.endswith('.parquet'):
                continue
            ticker = f.replace('.parquet', '')
            try:
                df = pd.read_parquet(os.path.join(merged_dir, f))
                if len(df) < 10 or 'Close' not in df.columns:
                    continue
                if df.index.tz is not None:
                    df.index = df.index.tz_localize(None)
                df = df[df.index >= START_DATE]
                if len(df) < 10:
                    continue
                if df['Close'].max() > 5000:
                    corrupted += 1; continue
                if (df['Close'] < 0.01).sum() > 5:
                    corrupted += 1; continue
                returns = df['Close'].pct_change().abs()
                bad = returns > 0.80
                if bad.sum() / len(df) > 0.02:
                    corrupted += 1; continue
                if bad.sum() > 0:
                    bad.iloc[0] = False
                    df = df[~bad]
                if len(df) < 10:
                    continue
                data[ticker] = df
            except Exception:
                pass
        print(f"  Loaded {len(data)} tickers ({corrupted} corrupted removed)")
        return data

    print("ERROR: No merged_universe found. Run merge_survivorship_data.py first.")
    sys.exit(1)


def get_sp500_members_on_date(snapshots: pd.DataFrame, date: pd.Timestamp) -> Set[str]:
    valid = snapshots[snapshots['date'] <= date]
    if valid.empty:
        return set()
    latest = valid.iloc[-1]
    return set(t.strip() for t in str(latest['tickers']).split(',') if t.strip())


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


# =============================================================================
# UNIVERSE SELECTION — THE KEY CHANGE (cash-based Stage 1)
# =============================================================================

def compute_cash_universe(price_data: Dict[str, pd.DataFrame],
                          snapshots: pd.DataFrame,
                          cash_data: Dict[str, Dict[int, float]],
                          revenue_data: Dict[str, Dict[int, float]]) -> Dict[int, List[str]]:
    """
    Two-stage annual universe selection (cash/revenue variant):
      Stage 1: From S&P 500 members (point-in-time), pick top 113 by cash/revenue ratio
      Stage 2: From those 113, pick top 40 by dollar volume (same as production)
    """
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    all_dates = [d for d in all_dates if d >= pd.Timestamp(START_DATE)]
    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}

    for year in years:
        ref_date = pd.Timestamp(f'{year}-01-01')
        sp500_members = get_sp500_members_on_date(snapshots, ref_date)

        ratio_scores = {}
        no_data_count = 0
        for symbol in sp500_members:
            if symbol not in price_data:
                continue
            ticker_cash = cash_data.get(symbol, {})
            ticker_rev = revenue_data.get(symbol, {})
            cash_val = ticker_cash.get(year - 1) or ticker_cash.get(year - 2)
            rev_val = ticker_rev.get(year - 1) or ticker_rev.get(year - 2)
            if cash_val and cash_val > 0 and rev_val and rev_val > 0:
                ratio_scores[symbol] = cash_val / rev_val
            else:
                no_data_count += 1

        ranked_by_ratio = sorted(ratio_scores.items(), key=lambda x: x[1], reverse=True)
        broad_113 = [s for s, _ in ranked_by_ratio[:BROAD_N]]

        ranking_end = pd.Timestamp(f'{year}-01-01')
        ranking_start = pd.Timestamp(f'{year - 1}-01-01')

        dv_scores = {}
        for symbol in broad_113:
            if symbol not in price_data:
                continue
            df = price_data[symbol]
            idx = df.index
            rs = ranking_start
            re_ = ranking_end
            if idx.tz is not None:
                rs = ranking_start.tz_localize(idx.tz)
                re_ = ranking_end.tz_localize(idx.tz)
            mask = (idx >= rs) & (idx < re_)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dollar_vol = (window['Close'] * window['Volume']).mean()
            dv_scores[symbol] = dollar_vol

        ranked_by_dv = sorted(dv_scores.items(), key=lambda x: x[1], reverse=True)
        top_40 = [s for s, _ in ranked_by_dv[:TOP_N]]
        annual_universe[year] = top_40

        top5 = ', '.join(f"{s}({v:.2f}x)" for s, v in ranked_by_ratio[:5])
        if year > years[0]:
            prev = set(annual_universe.get(year - 1, []))
            curr = set(top_40)
            added = curr - prev
            removed = prev - curr
            print(f"  {year}: S&P500={len(sp500_members)}, ratio_data={len(ratio_scores)}, "
                  f"no_data={no_data_count}, Broad-{BROAD_N}={len(broad_113)}, "
                  f"Top-{TOP_N} by $vol | +{len(added)} -{len(removed)}")
        else:
            print(f"  {year}: S&P500={len(sp500_members)}, ratio_data={len(ratio_scores)}, "
                  f"no_data={no_data_count}, Broad-{BROAD_N}={len(broad_113)}, "
                  f"Top-{TOP_N} by $vol (initial)")
        print(f"         Top-5 cash/rev: {top5}")

    return annual_universe


def compute_mcap_universe(price_data: Dict[str, pd.DataFrame],
                          snapshots: pd.DataFrame) -> Dict[int, List[str]]:
    """
    Two-stage annual universe selection (market cap variant):
      Stage 1: From S&P 500 members (point-in-time), pick top 113 by dollar volume
               (proxy for market cap — highly correlated for large-caps)
      Stage 2: From those 113, pick top 40 by dollar volume
    """
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    all_dates = [d for d in all_dates if d >= pd.Timestamp(START_DATE)]
    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}

    for year in years:
        ref_date = pd.Timestamp(f'{year}-01-01')
        sp500_members = get_sp500_members_on_date(snapshots, ref_date)

        ranking_end = pd.Timestamp(f'{year}-01-01')
        ranking_start = pd.Timestamp(f'{year - 1}-01-01')

        # ── Stage 1: Top 113 by dollar volume (market cap proxy) ──
        dv_scores = {}
        for symbol in sp500_members:
            if symbol not in price_data:
                continue
            df = price_data[symbol]
            idx = df.index
            rs = ranking_start
            re_ = ranking_end
            if idx.tz is not None:
                rs = ranking_start.tz_localize(idx.tz)
                re_ = ranking_end.tz_localize(idx.tz)
            mask = (idx >= rs) & (idx < re_)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dollar_vol = (window['Close'] * window['Volume']).mean()
            dv_scores[symbol] = dollar_vol

        ranked_all = sorted(dv_scores.items(), key=lambda x: x[1], reverse=True)
        broad_113 = [s for s, _ in ranked_all[:BROAD_N]]

        # ── Stage 2: Top 40 by dollar volume (same ranking, just top slice) ──
        top_40 = broad_113[:TOP_N]
        annual_universe[year] = top_40

        top5 = ', '.join(f"{s}(${v/1e6:.0f}M)" for s, v in ranked_all[:5])
        if year > years[0]:
            prev = set(annual_universe.get(year - 1, []))
            curr = set(top_40)
            added = curr - prev
            removed = prev - curr
            print(f"  {year}: S&P500={len(sp500_members)}, data={len(dv_scores)}, "
                  f"Broad-{BROAD_N}={len(broad_113)}, Top-{TOP_N} | "
                  f"+{len(added)} -{len(removed)}")
        else:
            print(f"  {year}: S&P500={len(sp500_members)}, data={len(dv_scores)}, "
                  f"Broad-{BROAD_N}={len(broad_113)}, Top-{TOP_N} (initial)")
        print(f"         Top-5 $vol: {top5}")

    return annual_universe


def compute_netmargin_universe(price_data: Dict[str, pd.DataFrame],
                               snapshots: pd.DataFrame,
                               netincome_data: Dict[str, Dict[int, float]],
                               revenue_data: Dict[str, Dict[int, float]]) -> Dict[int, List[str]]:
    """
    Two-stage annual universe selection (net margin variant):
      Stage 1: From S&P 500 members (PIT), pick top 113 by net margin (net income / revenue)
      Stage 2: From those 113, pick top 40 by dollar volume
    """
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    all_dates = [d for d in all_dates if d >= pd.Timestamp(START_DATE)]
    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}

    for year in years:
        ref_date = pd.Timestamp(f'{year}-01-01')
        sp500_members = get_sp500_members_on_date(snapshots, ref_date)

        # ── Stage 1: Top 113 by net margin ──
        margin_scores = {}
        no_data_count = 0
        for symbol in sp500_members:
            if symbol not in price_data:
                continue
            ticker_ni = netincome_data.get(symbol, {})
            ticker_rev = revenue_data.get(symbol, {})
            ni_val = ticker_ni.get(year - 1) or ticker_ni.get(year - 2)
            rev_val = ticker_rev.get(year - 1) or ticker_rev.get(year - 2)
            if ni_val is not None and rev_val and rev_val > 0:
                margin = ni_val / rev_val
                # Only include profitable companies (positive net margin)
                if margin > 0:
                    margin_scores[symbol] = margin
                else:
                    no_data_count += 1
            else:
                no_data_count += 1

        ranked_by_margin = sorted(margin_scores.items(), key=lambda x: x[1], reverse=True)
        broad_113 = [s for s, _ in ranked_by_margin[:BROAD_N]]

        # ── Stage 2: Top 40 by dollar volume ──
        ranking_end = pd.Timestamp(f'{year}-01-01')
        ranking_start = pd.Timestamp(f'{year - 1}-01-01')

        dv_scores = {}
        for symbol in broad_113:
            if symbol not in price_data:
                continue
            df = price_data[symbol]
            idx = df.index
            rs = ranking_start
            re_ = ranking_end
            if idx.tz is not None:
                rs = ranking_start.tz_localize(idx.tz)
                re_ = ranking_end.tz_localize(idx.tz)
            mask = (idx >= rs) & (idx < re_)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dollar_vol = (window['Close'] * window['Volume']).mean()
            dv_scores[symbol] = dollar_vol

        ranked_by_dv = sorted(dv_scores.items(), key=lambda x: x[1], reverse=True)
        top_40 = [s for s, _ in ranked_by_dv[:TOP_N]]
        annual_universe[year] = top_40

        top5 = ', '.join(f"{s}({v:.0%})" for s, v in ranked_by_margin[:5])
        if year > years[0]:
            prev = set(annual_universe.get(year - 1, []))
            curr = set(top_40)
            added = curr - prev
            removed = prev - curr
            print(f"  {year}: S&P500={len(sp500_members)}, margin_data={len(margin_scores)}, "
                  f"no_data={no_data_count}, Broad-{BROAD_N}={len(broad_113)}, "
                  f"Top-{TOP_N} by $vol | +{len(added)} -{len(removed)}")
        else:
            print(f"  {year}: S&P500={len(sp500_members)}, margin_data={len(margin_scores)}, "
                  f"no_data={no_data_count}, Broad-{BROAD_N}={len(broad_113)}, "
                  f"Top-{TOP_N} by $vol (initial)")
        print(f"         Top-5 net margin: {top5}")

    return annual_universe


# =============================================================================
# COMPASS v8.2 BACKTEST (EXACT COPY from exp61 — DO NOT MODIFY)
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


def run_backtest(price_data, annual_universe, spy_data, cash_yield_daily=None, label=""):
    print(f"\n{'='*80}")
    print(f"RUNNING COMPASS BACKTEST [{label}]")
    print(f"{'='*80}")

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    # Filter to START_DATE
    all_dates = [d for d in all_dates if d >= pd.Timestamp(START_DATE)]
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
                trades.append({
                    'symbol': symbol, 'entry_date': pos['entry_date'],
                    'exit_date': date, 'exit_reason': exit_reason,
                    'pnl': pnl, 'return': pnl / (pos['entry_price'] * shares)
                })
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
    sortino_denom = returns[returns < 0].std() * np.sqrt(252)
    sortino = cagr / sortino_denom if sortino_denom > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0
    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    avg_trade = trades_df['pnl'].mean() if len(trades_df) > 0 else 0
    protection_days = df['in_protection'].sum()
    protection_pct = protection_days / len(df) * 100

    pv = df['value']
    annual = pv.resample('YE').last().pct_change().dropna()

    return {
        'final_value': final_value,
        'cagr': cagr,
        'volatility': volatility,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'trades': len(trades_df),
        'win_rate': win_rate,
        'avg_trade': avg_trade,
        'stop_events': len(stop_df),
        'protection_days': protection_days,
        'protection_pct': protection_pct,
        'years': years,
        'annual_returns': annual,
    }


# =============================================================================
# HYDRA + EFA COMBINATION (from exp61)
# =============================================================================

def load_efa_data():
    cache_path = 'data_cache/efa_daily.pkl'
    if os.path.exists(cache_path):
        with open(cache_path, 'rb') as f:
            efa = pickle.load(f)
        print(f"  EFA loaded from cache: {efa.index[0].date()} to {efa.index[-1].date()}")
        return efa
    print("  Downloading EFA data from yfinance...")
    raw = yf.download('EFA', start='2001-01-01', end='2026-12-31', progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    efa = raw[['Close']].rename(columns={'Close': 'close'})
    efa['ret'] = efa['close'].pct_change()
    efa['sma200'] = efa['close'].rolling(200).mean()
    os.makedirs('data_cache', exist_ok=True)
    with open(cache_path, 'wb') as f:
        pickle.dump(efa, f)
    print(f"  EFA cached: {efa.index[0].date()} to {efa.index[-1].date()}")
    return efa


def run_hydra_efa(compass_daily, rattle_daily, efa, use_regime_filter=True):
    MAX_COMPASS_ALLOC = 0.75
    BASE_COMPASS_ALLOC = 0.50
    BASE_RATTLE_ALLOC = 0.50

    c_ret = compass_daily['value'].pct_change()
    r_ret = rattle_daily['value'].pct_change()
    r_exposure = rattle_daily['exposure']

    df = pd.DataFrame({
        'c_ret': c_ret,
        'r_ret': r_ret,
        'r_exposure': r_exposure,
    }).dropna()

    c_account = INITIAL_CAPITAL * BASE_COMPASS_ALLOC
    r_account = INITIAL_CAPITAL * BASE_RATTLE_ALLOC
    efa_value = 0.0

    portfolio_values = []

    for i in range(len(df)):
        date = df.index[i]
        r_exp = df['r_exposure'].iloc[i]
        total_value = c_account + r_account + efa_value

        r_idle = r_account * (1.0 - r_exp)
        max_c_account = total_value * MAX_COMPASS_ALLOC
        max_recyclable = max(0, max_c_account - c_account)
        recycle_amount = min(r_idle, max_recyclable)

        c_effective = c_account + recycle_amount
        r_effective = r_account - recycle_amount

        r_still_idle = r_effective * (1.0 - r_exp)
        idle_cash = r_still_idle

        efa_eligible = True
        if use_regime_filter and date in efa.index:
            sma = efa.loc[date, 'sma200']
            close = efa.loc[date, 'close']
            if pd.notna(sma) and close < sma:
                efa_eligible = False

        if date in efa.index and efa_eligible:
            target_efa = idle_cash
        else:
            target_efa = 0.0

        if target_efa > efa_value:
            buy_amount = target_efa - efa_value
            r_effective -= buy_amount
            efa_value += buy_amount
        elif target_efa < efa_value:
            sell_amount = efa_value - target_efa
            efa_value -= sell_amount
            r_effective += sell_amount

        c_ret_val = df['c_ret'].iloc[i]
        r_ret_val = df['r_ret'].iloc[i]

        if date in efa.index and efa_value > 0:
            efa_ret = efa.loc[date, 'ret']
            if pd.isna(efa_ret):
                efa_ret = 0.0
        else:
            efa_ret = 0.0

        c_account_new = c_effective * (1 + c_ret_val)
        r_account_new = r_effective * (1 + r_ret_val)
        efa_value_new = efa_value * (1 + efa_ret)

        recycled_after = recycle_amount * (1 + c_ret_val)
        c_account = c_account_new - recycled_after
        r_account = r_account_new + recycled_after
        efa_value = efa_value_new

        total_new = c_account + r_account + efa_value
        portfolio_values.append(total_new)

    pv = pd.Series(portfolio_values, index=df.index)
    return pv


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("EXPERIMENT #62: CASH-RICH UNIVERSE SELECTION")
    print("Top 113 by Cash/Revenue Ratio (SEC EDGAR) -> Top 40 by Dollar Volume")
    print(f"Period: {START_DATE} to {END_DATE}")
    print("=" * 80)
    print()

    # ── Load data ──
    print("--- Loading Data ---")
    snapshots = load_sp500_snapshots()
    price_data = load_universe_prices()
    spy_data = download_spy()
    cash_yield_daily = download_cash_yield()
    efa = load_efa_data()

    rattle_path = 'backtests/rattlesnake_daily.csv'
    if os.path.exists(rattle_path):
        rattle = pd.read_csv(rattle_path, index_col=0, parse_dates=True)
        print(f"  Rattlesnake daily: {rattle.index[0].date()} to {rattle.index[-1].date()}")
        has_rattle = True
    else:
        print("  WARNING: rattlesnake_daily.csv not found, skipping HYDRA+EFA")
        has_rattle = False

    print(f"\n  Universe: {len(price_data)} tickers with price data")

    # ── Download SEC EDGAR cash data ──
    print(f"\n--- Downloading SEC EDGAR Cash Data ---")
    cik_mapping = load_cik_mapping()

    # Collect all unique tickers from all S&P 500 snapshots (2009+)
    all_sp500_tickers = set()
    for _, row in snapshots.iterrows():
        if pd.Timestamp(row['date']) >= pd.Timestamp('2008-01-01'):
            tickers = set(t.strip() for t in str(row['tickers']).split(',') if t.strip())
            all_sp500_tickers.update(tickers)
    # Only download tickers that also have price data
    tickers_to_download = sorted(all_sp500_tickers & set(price_data.keys()))
    print(f"  S&P 500 tickers with price data: {len(tickers_to_download)}")

    cash_data = download_sec_edgar_cash(tickers_to_download, cik_mapping)
    tickers_with_cash = sum(1 for t, d in cash_data.items() if d)
    print(f"  Tickers with cash data: {tickers_with_cash}/{len(tickers_to_download)}")

    print(f"\n--- Downloading SEC EDGAR Revenue Data ---")
    revenue_data = download_sec_edgar_revenue(tickers_to_download, cik_mapping)
    tickers_with_rev = sum(1 for t, d in revenue_data.items() if d)
    print(f"  Tickers with revenue data: {tickers_with_rev}/{len(tickers_to_download)}")

    print(f"\n--- Downloading SEC EDGAR Net Income Data ---")
    netincome_data = download_sec_edgar_netincome(tickers_to_download, cik_mapping)
    tickers_with_ni = sum(1 for t, d in netincome_data.items() if d)
    print(f"  Tickers with net income data: {tickers_with_ni}/{len(tickers_to_download)}")

    # ==========================================================================
    # VARIANT A: Market Cap (dollar volume proxy) — no SEC data needed
    # ==========================================================================
    print(f"\n{'='*80}")
    print(f"  VARIANT A: MARKET CAP (Top-{BROAD_N} by $vol -> Top-{TOP_N} by $vol)")
    print(f"{'='*80}")
    mcap_universe = compute_mcap_universe(price_data, snapshots)

    mcap_results = run_backtest(price_data, mcap_universe, spy_data, cash_yield_daily,
                                label="EXP62A: Market Cap")
    mcap_metrics = calculate_metrics(mcap_results)

    os.makedirs('backtests', exist_ok=True)
    mcap_daily = mcap_results['portfolio_values'].set_index('date')
    mcap_daily.to_csv('backtests/exp62a_mcap_compass_daily.csv')

    mcap_hydra_cagr = mcap_hydra_sharpe = mcap_hydra_maxdd = None
    if has_rattle:
        print(f"\n--- HYDRA + EFA (Market Cap variant) ---")
        mcap_hydra_pv = run_hydra_efa(mcap_daily, rattle, efa, use_regime_filter=True)
        mcap_hydra_years = len(mcap_hydra_pv) / 252
        mcap_hydra_cagr = (mcap_hydra_pv.iloc[-1] / INITIAL_CAPITAL) ** (1 / mcap_hydra_years) - 1
        mcap_hydra_maxdd = (mcap_hydra_pv / mcap_hydra_pv.cummax() - 1).min()
        mcap_hydra_returns = mcap_hydra_pv.pct_change().dropna()
        mcap_hydra_sharpe = mcap_hydra_returns.mean() / mcap_hydra_returns.std() * np.sqrt(252)
        pd.DataFrame({'value': mcap_hydra_pv}).to_csv('backtests/exp62a_mcap_hydra_daily.csv')

    # ==========================================================================
    # VARIANT B: Cash/Revenue ratio — uses SEC EDGAR data
    # ==========================================================================
    print(f"\n{'='*80}")
    print(f"  VARIANT B: CASH/REVENUE (Top-{BROAD_N} by ratio -> Top-{TOP_N} by $vol)")
    print(f"{'='*80}")
    cash_universe = compute_cash_universe(price_data, snapshots, cash_data, revenue_data)

    cash_results = run_backtest(price_data, cash_universe, spy_data, cash_yield_daily,
                                label="EXP62B: Cash/Revenue")
    cash_metrics = calculate_metrics(cash_results)

    cash_daily = cash_results['portfolio_values'].set_index('date')
    cash_daily.to_csv('backtests/exp62b_cashrev_compass_daily.csv')

    cash_hydra_cagr = cash_hydra_sharpe = cash_hydra_maxdd = None
    if has_rattle:
        print(f"\n--- HYDRA + EFA (Cash/Revenue variant) ---")
        cash_hydra_pv = run_hydra_efa(cash_daily, rattle, efa, use_regime_filter=True)
        cash_hydra_years = len(cash_hydra_pv) / 252
        cash_hydra_cagr = (cash_hydra_pv.iloc[-1] / INITIAL_CAPITAL) ** (1 / cash_hydra_years) - 1
        cash_hydra_maxdd = (cash_hydra_pv / cash_hydra_pv.cummax() - 1).min()
        cash_hydra_returns = cash_hydra_pv.pct_change().dropna()
        cash_hydra_sharpe = cash_hydra_returns.mean() / cash_hydra_returns.std() * np.sqrt(252)
        pd.DataFrame({'value': cash_hydra_pv}).to_csv('backtests/exp62b_cashrev_hydra_daily.csv')

    # ==========================================================================
    # VARIANT C: Net Margin — uses SEC EDGAR net income + revenue
    # ==========================================================================
    print(f"\n{'='*80}")
    print(f"  VARIANT C: NET MARGIN (Top-{BROAD_N} by net margin -> Top-{TOP_N} by $vol)")
    print(f"{'='*80}")
    margin_universe = compute_netmargin_universe(price_data, snapshots, netincome_data, revenue_data)

    margin_results = run_backtest(price_data, margin_universe, spy_data, cash_yield_daily,
                                  label="EXP62C: Net Margin")
    margin_metrics = calculate_metrics(margin_results)

    margin_daily = margin_results['portfolio_values'].set_index('date')
    margin_daily.to_csv('backtests/exp62c_margin_compass_daily.csv')

    margin_hydra_cagr = margin_hydra_sharpe = margin_hydra_maxdd = None
    if has_rattle:
        print(f"\n--- HYDRA + EFA (Net Margin variant) ---")
        margin_hydra_pv = run_hydra_efa(margin_daily, rattle, efa, use_regime_filter=True)
        margin_hydra_years = len(margin_hydra_pv) / 252
        margin_hydra_cagr = (margin_hydra_pv.iloc[-1] / INITIAL_CAPITAL) ** (1 / margin_hydra_years) - 1
        margin_hydra_maxdd = (margin_hydra_pv / margin_hydra_pv.cummax() - 1).min()
        margin_hydra_returns = margin_hydra_pv.pct_change().dropna()
        margin_hydra_sharpe = margin_hydra_returns.mean() / margin_hydra_returns.std() * np.sqrt(252)
        pd.DataFrame({'value': margin_hydra_pv}).to_csv('backtests/exp62c_margin_hydra_daily.csv')

    # ==========================================================================
    # COMBINED RESULTS (A + B + C)
    # ==========================================================================
    print(f"\n\n{'=' * 105}")
    print(f"  EXPERIMENT #62 — COMBINED RESULTS")
    print(f"{'=' * 105}")
    print(f"  {'METRIC':<18} {'Production':>12} {'Exp40(PIT)':>12} {'A:MktCap':>12} {'B:Cash/Rev':>12} {'C:NetMargin':>12}")
    print(f"  {'-' * 84}")
    print(f"  {'Pool select':<18} {'hardcoded':>12} {'$vol':>12} {'$vol(PIT)':>12} {'cash/rev':>12} {'net margin':>12}")
    print(f"  {'Top-40 by':<18} {'$vol':>12} {'$vol':>12} {'$vol':>12} {'$vol':>12} {'$vol':>12}")
    print(f"  {'Period':<18} {'2000-2026':>12} {'2000-2026':>12} {'2009-2026':>12} {'2009-2026':>12} {'2009-2026':>12}")
    print(f"  {'-' * 84}")
    print(f"  {'CAGR':<18} {'18.56%':>12} {'13.37%':>12} {mcap_metrics['cagr']:>11.2%} {cash_metrics['cagr']:>11.2%} {margin_metrics['cagr']:>11.2%}")
    print(f"  {'Sharpe':<18} {'0.90':>12} {'0.64':>12} {mcap_metrics['sharpe']:>11.2f} {cash_metrics['sharpe']:>11.2f} {margin_metrics['sharpe']:>11.2f}")
    print(f"  {'Sortino':<18} {'--':>12} {'--':>12} {mcap_metrics['sortino']:>11.2f} {cash_metrics['sortino']:>11.2f} {margin_metrics['sortino']:>11.2f}")
    print(f"  {'Max DD':<18} {'-26.9%':>12} {'-44.2%':>12} {mcap_metrics['max_drawdown']:>11.2%} {cash_metrics['max_drawdown']:>11.2%} {margin_metrics['max_drawdown']:>11.2%}")
    print(f"  {'Win Rate':<18} {'--':>12} {'--':>12} {mcap_metrics['win_rate']:>11.2%} {cash_metrics['win_rate']:>11.2%} {margin_metrics['win_rate']:>11.2%}")
    print(f"  {'Trades':<18} {'--':>12} {'--':>12} {mcap_metrics['trades']:>11,} {cash_metrics['trades']:>11,} {margin_metrics['trades']:>11,}")
    print(f"  {'Final ($100K)':<18} {'$8.43M':>12} {'$1.34M':>12} ${mcap_metrics['final_value']/1e6:>10.2f}M ${cash_metrics['final_value']/1e6:>10.2f}M ${margin_metrics['final_value']/1e6:>10.2f}M")
    if has_rattle:
        print(f"  {'-' * 84}")
        print(f"  {'HYDRA CAGR':<18} {'--':>12} {'--':>12} {mcap_hydra_cagr:>11.2%} {cash_hydra_cagr:>11.2%} {margin_hydra_cagr:>11.2%}")
        print(f"  {'HYDRA Sharpe':<18} {'--':>12} {'--':>12} {mcap_hydra_sharpe:>11.2f} {cash_hydra_sharpe:>11.2f} {margin_hydra_sharpe:>11.2f}")
        print(f"  {'HYDRA MaxDD':<18} {'--':>12} {'--':>12} {mcap_hydra_maxdd:>11.2%} {cash_hydra_maxdd:>11.2%} {margin_hydra_maxdd:>11.2%}")
    print(f"{'=' * 105}")

    # ── Kill criteria ──
    print(f"\n  KILL CRITERIA:")
    for name, m in [('A:MktCap', mcap_metrics), ('B:Cash/Rev', cash_metrics), ('C:NetMargin', margin_metrics)]:
        cagr_ok = m['cagr'] >= 0.10
        dd_ok = m['max_drawdown'] >= -0.35
        status = 'PASS' if (cagr_ok and dd_ok) else 'FAIL'
        print(f"    {name}: {status} (CAGR={m['cagr']:.2%}, MaxDD={m['max_drawdown']:.2%})")

    # ── Annual returns side by side ──
    print(f"\n  ANNUAL RETURNS:")
    print(f"  {'Year':<6} {'A:MktCap':>10} {'B:Cash/Rev':>12} {'C:NetMargin':>13}")
    print(f"  {'-' * 43}")
    a_ann = mcap_metrics['annual_returns']
    b_ann = cash_metrics['annual_returns']
    c_ann = margin_metrics['annual_returns']
    all_years_set = sorted(set(a_ann.index.year) | set(b_ann.index.year) | set(c_ann.index.year))
    for yr in all_years_set:
        a_val = a_ann[a_ann.index.year == yr]
        b_val = b_ann[b_ann.index.year == yr]
        c_val = c_ann[c_ann.index.year == yr]
        a_str = f"{a_val.iloc[0]:>+7.2%}" if len(a_val) > 0 else f"{'--':>8}"
        b_str = f"{b_val.iloc[0]:>+7.2%}" if len(b_val) > 0 else f"{'--':>8}"
        c_str = f"{c_val.iloc[0]:>+7.2%}" if len(c_val) > 0 else f"{'--':>8}"
        print(f"  {yr:<6} {a_str:>10} {b_str:>12} {c_str:>13}")

    print(f"\nSaved: backtests/exp62a_mcap_compass_daily.csv")
    print(f"Saved: backtests/exp62b_cashrev_compass_daily.csv")
    print(f"Saved: backtests/exp62c_margin_compass_daily.csv")
    if has_rattle:
        print(f"Saved: backtests/exp62a_mcap_hydra_daily.csv")
        print(f"Saved: backtests/exp62b_cashrev_hydra_daily.csv")
        print(f"Saved: backtests/exp62c_margin_hydra_daily.csv")
