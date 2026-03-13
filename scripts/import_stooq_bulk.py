#!/usr/bin/env python3
"""
Stooq Bulk US Daily Data — Download, Analyze, and Import
=========================================================
Downloads the Stooq bulk US daily OHLCV data (~333 MB zip), unzips it,
analyzes the file structure, cross-references against missing S&P 500 tickers,
checks for data quality issues (corrupted delisted stocks), and saves clean
data to data_cache_parquet/ for use in exp40 and future Russell 2000 work.

Usage:
    python scripts/import_stooq_bulk.py

Output:
    data_sources/stooq_bulk/d_us_txt.zip   -- raw download
    data_sources/stooq_bulk/data/           -- extracted files
    data_sources/stooq_bulk/report.txt      -- data quality report
    data_cache_parquet/<TICKER>.parquet     -- clean data for missing tickers

Steps:
    1. Download d_us_txt.zip from Stooq
    2. Unzip and explore structure
    3. Search for critical bankruptcy tickers
    4. Cross-reference against 475 missing S&P 500 tickers
    5. Quality-check delisted tickers (price jumps, ticker reuse)
    6. Export clean data as parquet
"""

import os
import io
import sys
import time
import zipfile
import urllib.request
import urllib.error
import shutil
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pandas as pd
import numpy as np

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STOOQ_DIR = PROJECT_ROOT / 'data_sources' / 'stooq_bulk'
ZIP_PATH = STOOQ_DIR / 'd_us_txt.zip'
EXTRACT_DIR = STOOQ_DIR / 'data'
REPORT_PATH = STOOQ_DIR / 'report.txt'
PARQUET_DIR = PROJECT_ROOT / 'data_cache_parquet'
SP500_SNAPSHOTS = PROJECT_ROOT / 'data_cache' / 'sp500_snapshots.csv'

# ---------------------------------------------------------------------------
# BROAD_POOL: current S&P 500 tickers already in our parquet cache
# ---------------------------------------------------------------------------
BROAD_POOL = {
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
    'PANW', 'NFLX', 'COF', 'SPY',
}

# Known bankruptcy / crisis tickers — highest priority to find
CRITICAL_TICKERS = {
    'ENE': ('Enron', '2001-12-02'),
    'WCOM': ('WorldCom', '2002-07-21'),
    'LEH': ('Lehman Brothers', '2008-09-15'),
    'BSC': ('Bear Stearns', '2008-05-30'),
    'WM': ('Washington Mutual', '2008-09-26'),  # CAUTION: reused by Waste Management
    'WB': ('Wachovia', '2008-12-31'),
    'MER': ('Merrill Lynch', '2009-01-01'),
    'CFC': ('Countrywide Financial', '2008-07-01'),
    'ABI': ('Anheuser-Busch', '2008-11-18'),
    'GM': ('General Motors old', '2009-06-01'),  # CAUTION: ticker reused
    'C': ('Citigroup — kept in pool', None),       # NOT missing, in BROAD_POOL
}

# ---------------------------------------------------------------------------
# Max single-day return threshold for corruption detection
# ---------------------------------------------------------------------------
MAX_DAILY_RETURN = 0.80  # >80% = corrupted (matches exp40 sanitize logic)

# ---------------------------------------------------------------------------
# Stooq download URLs to try in order
# ---------------------------------------------------------------------------
DOWNLOAD_URLS = [
    'https://stooq.com/db/d/?b=d_us_txt',
    'https://stooq.com/db/h/d_us_txt.zip',
]


# ===========================================================================
# STEP 1: DOWNLOAD
# ===========================================================================

def download_zip(force: bool = False) -> bool:
    """
    Download d_us_txt.zip from Stooq.
    Returns True if file is ready (downloaded or already cached).
    """
    STOOQ_DIR.mkdir(parents=True, exist_ok=True)

    if ZIP_PATH.exists() and not force:
        size_mb = ZIP_PATH.stat().st_size / 1_048_576
        print(f"[Cache] Zip already exists: {ZIP_PATH} ({size_mb:.1f} MB)")
        return True

    print("[Download] Attempting to download Stooq US bulk data...")
    print("  This file is ~333 MB. Estimated time: 2-10 minutes depending on connection.")

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/122.0.0.0 Safari/537.36'
        ),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://stooq.com/db/h/',
    }

    for url in DOWNLOAD_URLS:
        print(f"  Trying: {url}")
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=120) as response:
                total = int(response.headers.get('Content-Length', 0))
                downloaded = 0
                chunk_size = 65536  # 64 KB
                last_print = time.time()

                with open(ZIP_PATH, 'wb') as f:
                    while True:
                        chunk = response.read(chunk_size)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        now = time.time()
                        if now - last_print > 10:
                            if total:
                                pct = downloaded / total * 100
                                print(f"    {downloaded / 1_048_576:.1f} / {total / 1_048_576:.1f} MB ({pct:.1f}%)")
                            else:
                                print(f"    {downloaded / 1_048_576:.1f} MB downloaded...")
                            last_print = now

            size_mb = ZIP_PATH.stat().st_size / 1_048_576
            print(f"  Download complete: {size_mb:.1f} MB -> {ZIP_PATH}")
            return True

        except urllib.error.HTTPError as e:
            print(f"  HTTP {e.code}: {e.reason} for {url}")
        except urllib.error.URLError as e:
            print(f"  URL error: {e.reason} for {url}")
        except Exception as e:
            print(f"  Error: {e} for {url}")
            if ZIP_PATH.exists():
                ZIP_PATH.unlink()  # remove partial download

    print("\n[FAIL] All download URLs failed.")
    print("  Manual download instructions:")
    print("  1. Go to https://stooq.com/db/h/")
    print("  2. Find 'US Stocks - daily' and click the download link")
    print(f"  3. Save the zip file to: {ZIP_PATH}")
    return False


# ===========================================================================
# STEP 2: UNZIP AND EXPLORE STRUCTURE
# ===========================================================================

def extract_zip() -> bool:
    """Extract the zip to EXTRACT_DIR. Skip if already done."""
    if EXTRACT_DIR.exists() and any(EXTRACT_DIR.rglob('*.txt')):
        txt_count = sum(1 for _ in EXTRACT_DIR.rglob('*.txt'))
        print(f"[Cache] Already extracted: {txt_count} .txt files in {EXTRACT_DIR}")
        return True

    if not ZIP_PATH.exists():
        print(f"[ERROR] Zip not found: {ZIP_PATH}")
        return False

    print(f"[Extract] Extracting {ZIP_PATH} -> {EXTRACT_DIR} ...")
    EXTRACT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(ZIP_PATH, 'r') as zf:
            members = zf.namelist()
            print(f"  Zip contains {len(members)} files")
            # Show top-level structure
            top_dirs = set()
            for m in members[:200]:
                parts = Path(m).parts
                if len(parts) > 1:
                    top_dirs.add(parts[0])
            print(f"  Top-level directories: {sorted(top_dirs)[:10]}")

            zf.extractall(EXTRACT_DIR)
        print(f"  Extraction complete.")
        return True
    except zipfile.BadZipFile as e:
        print(f"[ERROR] Bad zip file: {e}")
        print(f"  The zip may be incomplete. Try re-downloading.")
        return False
    except Exception as e:
        print(f"[ERROR] Extraction failed: {e}")
        return False


def explore_structure() -> Dict:
    """
    Walk extracted directory to understand structure.
    Returns summary dict with exchange dirs, file counts, sample paths.
    """
    print("\n[Structure] Analyzing extracted file structure...")

    structure = {
        'exchange_dirs': [],
        'total_files': 0,
        'sample_files': [],
        'format_sample': None,
    }

    if not EXTRACT_DIR.exists():
        print("  Extract directory not found.")
        return structure

    # Walk top-level
    top_items = sorted(EXTRACT_DIR.iterdir())
    print(f"  Top-level items ({len(top_items)}):")
    for item in top_items[:20]:
        if item.is_dir():
            sub_count = sum(1 for _ in item.rglob('*') if _.is_file())
            print(f"    DIR  {item.name}/  ({sub_count} files)")
            structure['exchange_dirs'].append({'name': item.name, 'files': sub_count})
        else:
            print(f"    FILE {item.name}  ({item.stat().st_size:,} bytes)")

    # Count total .txt files
    all_txt = list(EXTRACT_DIR.rglob('*.txt'))
    structure['total_files'] = len(all_txt)
    print(f"\n  Total .txt files: {len(all_txt):,}")

    # Sample a few paths
    samples = all_txt[:5]
    structure['sample_files'] = [str(p.relative_to(EXTRACT_DIR)) for p in samples]
    print(f"  Sample paths:")
    for s in structure['sample_files']:
        print(f"    {s}")

    # Read one sample file to understand format
    if all_txt:
        sample_path = all_txt[0]
        try:
            with open(sample_path, 'r', encoding='utf-8', errors='replace') as f:
                first_lines = [f.readline() for _ in range(5)]
            structure['format_sample'] = ''.join(first_lines)
            print(f"\n  Sample file content ({sample_path.name}):")
            for line in first_lines:
                print(f"    {line.rstrip()}")
        except Exception as e:
            print(f"  Could not read sample: {e}")

    return structure


def build_ticker_index() -> Dict[str, Path]:
    """
    Build a dict: ticker (uppercase) -> file path
    Stooq stores files as <ticker>.us.txt (lowercase)
    """
    print("\n[Index] Building ticker -> file path index...")
    index = {}
    for txt_file in EXTRACT_DIR.rglob('*.txt'):
        name = txt_file.stem.upper()  # e.g. 'ENE.US' -> 'ENE.US'
        # Strip .US suffix if present
        if name.endswith('.US'):
            name = name[:-3]
        index[name] = txt_file
    print(f"  Index built: {len(index):,} tickers found in Stooq bulk data")
    return index


# ===========================================================================
# STEP 3: LOAD A SINGLE TICKER FROM BULK FILES
# ===========================================================================

def load_stooq_bulk_ticker(ticker: str, index: Dict[str, Path]) -> Optional[pd.DataFrame]:
    """
    Load OHLCV data for a single ticker from the bulk extract.
    Returns DataFrame with columns [Open, High, Low, Close, Volume] and DatetimeIndex.
    Returns None if not found or unreadable.
    """
    path = index.get(ticker.upper())
    if path is None:
        return None

    try:
        df = pd.read_csv(path, parse_dates=['<DATE>'] if '<DATE>' in open(path).readline() else [0])
        # Stooq bulk format: <TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>,<OPENINT>
        # or: Date,Open,High,Low,Close,Volume
        # Normalize column names
        df.columns = [c.strip('<>').strip() for c in df.columns]

        col_map = {}
        for col in df.columns:
            col_upper = col.upper()
            if col_upper in ('DATE', 'DATE'):
                col_map[col] = 'Date'
            elif col_upper == 'OPEN':
                col_map[col] = 'Open'
            elif col_upper == 'HIGH':
                col_map[col] = 'High'
            elif col_upper == 'LOW':
                col_map[col] = 'Low'
            elif col_upper in ('CLOSE', 'CLOSEADJ'):
                col_map[col] = 'Close'
            elif col_upper in ('VOL', 'VOLUME'):
                col_map[col] = 'Volume'
        df = df.rename(columns=col_map)

        if 'Date' not in df.columns:
            # Try first column as date
            df = df.rename(columns={df.columns[0]: 'Date'})

        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df = df.dropna(subset=['Date'])
        df = df.set_index('Date').sort_index()

        required = ['Open', 'High', 'Low', 'Close', 'Volume']
        missing_cols = [c for c in required if c not in df.columns]
        if missing_cols:
            # Try to fill from what we have
            for c in missing_cols:
                if c == 'Volume':
                    df['Volume'] = 0
                elif c in ('Open', 'High', 'Low') and 'Close' in df.columns:
                    df[c] = df['Close']

        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        df = df[required].dropna(subset=['Close'])

        if len(df) < 5:
            return None

        return df

    except Exception as e:
        return None


# ===========================================================================
# STEP 4: DATA QUALITY CHECKS
# ===========================================================================

def check_data_quality(ticker: str, df: pd.DataFrame,
                        known_delisting_date: Optional[str] = None) -> Dict:
    """
    Run data quality checks on a single ticker's OHLCV DataFrame.
    Returns a dict with quality flags and metrics.
    """
    report = {
        'ticker': ticker,
        'rows': len(df),
        'date_start': str(df.index.min().date()) if len(df) > 0 else 'N/A',
        'date_end': str(df.index.max().date()) if len(df) > 0 else 'N/A',
        'issues': [],
        'max_daily_return': None,
        'corrupt': False,
        'ticker_reuse_suspected': False,
        'data_after_delisting': False,
    }

    if len(df) < 5:
        report['issues'].append('too_few_rows')
        report['corrupt'] = True
        return report

    # 1. Max single-day return
    returns = df['Close'].pct_change().dropna()
    max_ret = returns.abs().max()
    report['max_daily_return'] = float(max_ret)

    if max_ret > MAX_DAILY_RETURN:
        report['issues'].append(f'max_daily_return={max_ret:.1%}')
        report['corrupt'] = True

    # 2. Gaps: >30 calendar days between consecutive trading days
    if len(df) > 1:
        day_gaps = df.index.to_series().diff().dt.days.dropna()
        large_gaps = day_gaps[day_gaps > 30]
        if len(large_gaps) > 0:
            report['issues'].append(f'large_gaps={len(large_gaps)} (max={int(large_gaps.max())}d)')

    # 3. Zero volume days
    if 'Volume' in df.columns:
        zero_vol_days = (df['Volume'] == 0).sum()
        if zero_vol_days > len(df) * 0.10:  # >10% of days
            report['issues'].append(f'zero_volume={zero_vol_days}_days')

    # 4. Negative prices
    if (df['Close'] <= 0).any():
        report['issues'].append('negative_or_zero_close')
        report['corrupt'] = True

    # 5. Data after known delisting date (ticker reuse)
    if known_delisting_date:
        delist_dt = pd.to_datetime(known_delisting_date)
        post_delist = df[df.index > delist_dt + pd.Timedelta(days=90)]
        if len(post_delist) > 10:
            report['data_after_delisting'] = True
            report['ticker_reuse_suspected'] = True
            report['issues'].append(
                f'data_continues_{len(post_delist)}_rows_after_delisting_{known_delisting_date}'
            )

    # 6. Volume spike detection (sudden 10x spike then return to normal)
    if 'Volume' in df.columns and len(df) > 20:
        vol_median = df['Volume'].median()
        if vol_median > 0:
            vol_ratio = df['Volume'] / vol_median
            spikes = (vol_ratio > 50).sum()
            if spikes > 0:
                report['issues'].append(f'volume_spikes_50x={spikes}')

    # 7. Price level sanity for known-bankrupt tickers
    # If it's a bankruptcy ticker, price should go to near zero
    # A ticker reuse would show price recovering to normal levels
    price_at_end = df['Close'].iloc[-min(20, len(df)):]  # last 20 rows
    price_at_start = df['Close'].iloc[:min(20, len(df))]  # first 20 rows
    if price_at_start.mean() > 0:
        end_to_start_ratio = price_at_end.mean() / price_at_start.mean()
        report['end_to_start_ratio'] = float(end_to_start_ratio)

    return report


def truncate_at_delisting(df: pd.DataFrame, delisting_date: str,
                           buffer_days: int = 30) -> pd.DataFrame:
    """
    Truncate a DataFrame at delisting_date + buffer_days.
    Used to remove reused ticker data after the original company delisted.
    """
    cutoff = pd.to_datetime(delisting_date) + pd.Timedelta(days=buffer_days)
    return df[df.index <= cutoff]


# ===========================================================================
# STEP 5: CROSS-REFERENCE WITH MISSING S&P 500 TICKERS
# ===========================================================================

def load_sp500_missing_tickers() -> Tuple[Set[str], Set[str]]:
    """
    Load sp500_snapshots.csv and find:
    - all_historical: all unique tickers that appeared since 2000
    - missing: historical tickers NOT in current BROAD_POOL
    Returns (all_historical, missing)
    """
    if not SP500_SNAPSHOTS.exists():
        print(f"[WARN] sp500_snapshots.csv not found: {SP500_SNAPSHOTS}")
        print("  Run exp40_survivorship_bias.py first to generate it.")
        return set(), set()

    print(f"\n[S&P 500] Loading historical snapshots from {SP500_SNAPSHOTS.name}...")
    df = pd.read_csv(SP500_SNAPSHOTS, parse_dates=['date'])
    print(f"  Loaded {len(df)} snapshot dates: {df['date'].min().date()} to {df['date'].max().date()}")

    # Filter to 2000 onwards
    df_post2000 = df[df['date'] >= '2000-01-01']

    all_historical = set()
    for tickers_str in df_post2000['tickers']:
        all_historical.update(t.strip() for t in str(tickers_str).split(',') if t.strip())

    print(f"  Unique tickers in S&P 500 since 2000: {len(all_historical)}")

    # Find tickers already in our parquet cache
    parquet_tickers = set()
    if PARQUET_DIR.exists():
        for p in PARQUET_DIR.glob('*.parquet'):
            parquet_tickers.add(p.stem)
    print(f"  Tickers in data_cache_parquet/: {len(parquet_tickers)}")

    # Missing = historical S&P 500 members not yet downloaded
    missing = all_historical - BROAD_POOL - parquet_tickers
    print(f"  Missing tickers (in S&P 500 history but not in cache): {len(missing)}")

    return all_historical, missing


def find_missing_in_stooq(missing: Set[str], index: Dict[str, Path]) -> Dict[str, bool]:
    """
    Check which missing tickers exist in the Stooq bulk index.
    Returns dict: ticker -> True if found in Stooq.
    """
    coverage = {}
    for ticker in sorted(missing):
        coverage[ticker] = ticker.upper() in index
    found = sum(1 for v in coverage.values() if v)
    print(f"\n[Coverage] {found}/{len(missing)} missing S&P 500 tickers found in Stooq bulk data")
    return coverage


# ===========================================================================
# STEP 6: IMPORT CLEAN DATA TO PARQUET
# ===========================================================================

def import_tickers_to_parquet(tickers_to_import: List[str],
                               index: Dict[str, Path],
                               quality_reports: List[Dict],
                               dry_run: bool = False) -> Dict:
    """
    Load, quality-check, and save clean data for each ticker to parquet.
    Skips tickers with corrupt data.
    Returns summary stats.
    """
    PARQUET_DIR.mkdir(parents=True, exist_ok=True)

    stats = {
        'attempted': len(tickers_to_import),
        'imported': 0,
        'skipped_corrupt': 0,
        'skipped_not_found': 0,
        'skipped_existing': 0,
        'ticker_reuse_truncated': 0,
        'failed': [],
        'imported_list': [],
    }

    print(f"\n[Import] Processing {len(tickers_to_import)} tickers...")
    if dry_run:
        print("  DRY RUN — no files will be written")

    for i, ticker in enumerate(tickers_to_import):
        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(tickers_to_import)}] imported={stats['imported']} "
                  f"corrupt={stats['skipped_corrupt']} not_found={stats['skipped_not_found']}")

        # Skip if already exists in parquet cache
        out_path = PARQUET_DIR / f'{ticker}.parquet'
        if out_path.exists():
            stats['skipped_existing'] += 1
            continue

        # Load from bulk
        df = load_stooq_bulk_ticker(ticker, index)
        if df is None:
            stats['skipped_not_found'] += 1
            stats['failed'].append((ticker, 'not_found_in_bulk'))
            continue

        # Quality check
        delisting_date = CRITICAL_TICKERS.get(ticker, (None, None))[1]
        qr = check_data_quality(ticker, df, delisting_date)
        quality_reports.append(qr)

        if qr['corrupt']:
            stats['skipped_corrupt'] += 1
            stats['failed'].append((ticker, 'corrupt: ' + '; '.join(qr['issues'])))
            continue

        # Truncate reused tickers at delisting date
        if qr['ticker_reuse_suspected'] and delisting_date:
            df = truncate_at_delisting(df, delisting_date)
            stats['ticker_reuse_truncated'] += 1
            print(f"  [Truncated] {ticker}: data cut at {delisting_date} (ticker reuse detected)")

        # Save to parquet
        if not dry_run:
            df.to_parquet(out_path, compression='snappy')

        stats['imported'] += 1
        stats['imported_list'].append(ticker)

    return stats


# ===========================================================================
# STEP 7: WRITE REPORT
# ===========================================================================

def write_report(structure: Dict, coverage: Dict, stats: Dict,
                 quality_reports: List[Dict], critical_findings: List[str]):
    """Write a human-readable data quality report."""
    STOOQ_DIR.mkdir(parents=True, exist_ok=True)
    lines = []

    lines.append("=" * 70)
    lines.append("STOOQ BULK US DAILY DATA — ANALYSIS REPORT")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("=" * 70)

    lines.append("\n--- FILE STRUCTURE ---")
    lines.append(f"Total .txt files in extract: {structure.get('total_files', 'N/A'):,}")
    lines.append(f"Exchange directories:")
    for d in structure.get('exchange_dirs', []):
        lines.append(f"  {d['name']:20s} {d['files']:,} files")
    lines.append(f"\nSample file paths:")
    for s in structure.get('sample_files', []):
        lines.append(f"  {s}")
    if structure.get('format_sample'):
        lines.append(f"\nFile format sample:")
        for line in structure['format_sample'].split('\n')[:3]:
            lines.append(f"  {line}")

    lines.append("\n--- CRITICAL BANKRUPTCY TICKERS ---")
    for finding in critical_findings:
        lines.append(f"  {finding}")

    lines.append("\n--- S&P 500 COVERAGE ---")
    if coverage:
        found_tickers = [t for t, v in coverage.items() if v]
        missing_tickers = [t for t, v in coverage.items() if not v]
        lines.append(f"  Missing S&P 500 tickers checked:  {len(coverage)}")
        lines.append(f"  Found in Stooq bulk:              {len(found_tickers)} ({len(found_tickers)/max(1,len(coverage))*100:.1f}%)")
        lines.append(f"  Not found in Stooq bulk:          {len(missing_tickers)}")
        lines.append(f"\n  Tickers NOT in Stooq (sample of first 50):")
        for t in sorted(missing_tickers)[:50]:
            lines.append(f"    {t}")
        if len(missing_tickers) > 50:
            lines.append(f"    ... and {len(missing_tickers) - 50} more")

    lines.append("\n--- IMPORT STATISTICS ---")
    lines.append(f"  Attempted:              {stats.get('attempted', 0)}")
    lines.append(f"  Imported to parquet:    {stats.get('imported', 0)}")
    lines.append(f"  Skipped (existing):     {stats.get('skipped_existing', 0)}")
    lines.append(f"  Skipped (corrupt):      {stats.get('skipped_corrupt', 0)}")
    lines.append(f"  Skipped (not found):    {stats.get('skipped_not_found', 0)}")
    lines.append(f"  Ticker reuse truncated: {stats.get('ticker_reuse_truncated', 0)}")

    if stats.get('failed'):
        lines.append(f"\n  Failed tickers (first 30):")
        for ticker, reason in stats['failed'][:30]:
            lines.append(f"    {ticker:8s}: {reason}")

    lines.append("\n--- DATA QUALITY DETAILS (CORRUPT/FLAGGED) ---")
    flagged = [qr for qr in quality_reports if qr.get('issues')]
    for qr in sorted(flagged, key=lambda x: x['ticker'])[:50]:
        lines.append(
            f"  {qr['ticker']:8s}  {qr['date_start']} to {qr['date_end']}  "
            f"rows={qr['rows']:6d}  "
            f"{'CORRUPT' if qr['corrupt'] else 'FLAGGED':8s}  "
            f"{'; '.join(qr['issues'])}"
        )

    lines.append("\n--- CONCLUSIONS ---")
    lines.append("  1. Stooq bulk data format: Stooq stores data as <ticker>.us.txt")
    lines.append("     columns: <TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>,<OPENINT>")
    lines.append("  2. Known data quality issue: delisted tickers may have mixed price")
    lines.append("     series from different companies sharing the same ticker symbol.")
    lines.append("     Filter applied: daily returns >80% flagged as corrupt.")
    lines.append("  3. Ticker reuse detection: data continuing >90 days after known")
    lines.append("     delisting date is flagged and truncated at delisting + 30 days.")
    lines.append("  4. Bankrupt stocks (Enron, Lehman, WorldCom, Bear Stearns) may have")
    lines.append("     partial or no data — Stooq is best-effort for delisted stocks.")
    lines.append("  5. For definitive survivorship bias correction, Norgate Data ($500/yr)")
    lines.append("     remains the only reliable source with complete bankrupt stock data.")

    report_text = '\n'.join(lines)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(report_text)

    print(f"\n[Report] Written to: {REPORT_PATH}")
    return report_text


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Import Stooq bulk US daily data')
    parser.add_argument('--force-download', action='store_true',
                        help='Re-download zip even if it already exists')
    parser.add_argument('--dry-run', action='store_true',
                        help='Analyze only — do not write parquet files')
    parser.add_argument('--skip-download', action='store_true',
                        help='Skip download step (assume zip is already present)')
    parser.add_argument('--critical-only', action='store_true',
                        help='Only check/import the critical bankruptcy tickers')
    args = parser.parse_args()

    print("=" * 70)
    print("STOOQ BULK US DAILY DATA IMPORTER")
    print(f"Project root: {PROJECT_ROOT}")
    print(f"Output dir:   {STOOQ_DIR}")
    print("=" * 70)

    # ------------------------------------------------------------------
    # Step 1: Download
    # ------------------------------------------------------------------
    if not args.skip_download:
        ok = download_zip(force=args.force_download)
        if not ok:
            print("\n[ABORT] Download failed. Use --skip-download if zip is already present.")
            sys.exit(1)
    else:
        if not ZIP_PATH.exists():
            print(f"[ERROR] --skip-download specified but zip not found: {ZIP_PATH}")
            sys.exit(1)
        print(f"[Skip] Download skipped. Using existing: {ZIP_PATH}")

    # ------------------------------------------------------------------
    # Step 2: Extract
    # ------------------------------------------------------------------
    ok = extract_zip()
    if not ok:
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 3: Explore structure
    # ------------------------------------------------------------------
    structure = explore_structure()

    # ------------------------------------------------------------------
    # Step 4: Build ticker index
    # ------------------------------------------------------------------
    index = build_ticker_index()

    # ------------------------------------------------------------------
    # Step 5: Check critical bankruptcy tickers
    # ------------------------------------------------------------------
    print("\n[Critical] Checking bankruptcy tickers...")
    critical_findings = []
    quality_reports = []

    for ticker, (company, delisting_date) in CRITICAL_TICKERS.items():
        if ticker in BROAD_POOL:
            msg = f"{ticker:8s}: IN BROAD_POOL (active, not a delisted ticker)"
            critical_findings.append(msg)
            print(f"  {msg}")
            continue

        in_index = ticker.upper() in index
        if not in_index:
            msg = f"{ticker:8s}: NOT FOUND in Stooq bulk  ({company})"
            critical_findings.append(msg)
            print(f"  {msg}")
            continue

        df = load_stooq_bulk_ticker(ticker, index)
        if df is None:
            msg = f"{ticker:8s}: Found in index but FAILED to load  ({company})"
            critical_findings.append(msg)
            print(f"  {msg}")
            continue

        qr = check_data_quality(ticker, df, delisting_date)
        quality_reports.append(qr)

        issues_str = '; '.join(qr['issues']) if qr['issues'] else 'none'
        status = 'CORRUPT' if qr['corrupt'] else ('REUSE?' if qr['ticker_reuse_suspected'] else 'OK')
        msg = (f"{ticker:8s}: {status:8s} | rows={qr['rows']:5d} | "
               f"{qr['date_start']} to {qr['date_end']} | "
               f"max_return={qr['max_daily_return']:.1%} | "
               f"issues: {issues_str}")
        critical_findings.append(msg)
        print(f"  {msg}")

        if delisting_date and qr['ticker_reuse_suspected']:
            print(f"    WARNING: {ticker} data continues after delisting ({delisting_date})")
            print(f"    Company: {company}. Ticker may be reused by another entity.")

    # If --critical-only, stop here
    if args.critical_only:
        coverage = {}
        stats = {'attempted': 0, 'imported': 0, 'skipped_corrupt': 0,
                 'skipped_not_found': 0, 'skipped_existing': 0,
                 'ticker_reuse_truncated': 0, 'failed': [], 'imported_list': []}
        report = write_report(structure, coverage, stats, quality_reports, critical_findings)
        print("\n" + "=" * 70)
        print(report)
        return

    # ------------------------------------------------------------------
    # Step 6: Cross-reference missing S&P 500 tickers
    # ------------------------------------------------------------------
    all_historical, missing = load_sp500_missing_tickers()
    coverage = find_missing_in_stooq(missing, index)

    found_in_stooq = [t for t, v in coverage.items() if v]
    print(f"\n  Tickers found in Stooq and not yet cached: {len(found_in_stooq)}")
    if found_in_stooq:
        print(f"  Sample: {sorted(found_in_stooq)[:30]}")

    # ------------------------------------------------------------------
    # Step 7: Import to parquet
    # ------------------------------------------------------------------
    tickers_to_import = sorted(found_in_stooq)

    # Always include critical tickers that are in the index and not in cache
    for ticker in CRITICAL_TICKERS:
        if ticker not in BROAD_POOL and ticker in index and ticker not in tickers_to_import:
            tickers_to_import.append(ticker)

    if tickers_to_import:
        stats = import_tickers_to_parquet(tickers_to_import, index,
                                           quality_reports, dry_run=args.dry_run)
    else:
        print("\n[Import] Nothing to import (all tickers already cached or not found).")
        stats = {'attempted': 0, 'imported': 0, 'skipped_corrupt': 0,
                 'skipped_not_found': 0, 'skipped_existing': 0,
                 'ticker_reuse_truncated': 0, 'failed': [], 'imported_list': []}

    # ------------------------------------------------------------------
    # Step 8: Write report
    # ------------------------------------------------------------------
    report = write_report(structure, coverage, stats, quality_reports, critical_findings)

    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  Stooq bulk tickers available:    {len(index):,}")
    print(f"  Missing S&P 500 tickers checked: {len(coverage)}")
    if coverage:
        found_n = sum(1 for v in coverage.values() if v)
        print(f"  Found in Stooq bulk:             {found_n} ({found_n/max(1,len(coverage))*100:.1f}%)")
    print(f"  Imported to parquet:             {stats['imported']}")
    print(f"  Corrupt / rejected:              {stats['skipped_corrupt']}")
    print(f"  Ticker reuse truncated:          {stats['ticker_reuse_truncated']}")
    print(f"\n  Report saved to: {REPORT_PATH}")
    if not args.dry_run and stats['imported'] > 0:
        print(f"  Parquet files saved to: {PARQUET_DIR}")

    # Save coverage JSON for programmatic use
    cov_path = STOOQ_DIR / 'coverage.json'
    with open(cov_path, 'w') as f:
        json.dump({
            'generated': datetime.now().isoformat(),
            'stooq_total_tickers': len(index),
            'missing_sp500_tickers': len(coverage),
            'found_in_stooq': found_n if coverage else 0,
            'coverage_pct': found_n / max(1, len(coverage)) * 100 if coverage else 0,
            'coverage_detail': {t: v for t, v in sorted(coverage.items())},
            'critical_tickers': critical_findings,
            'imported': stats['imported_list'],
        }, f, indent=2)
    print(f"  Coverage JSON:  {cov_path}")


if __name__ == '__main__':
    main()
