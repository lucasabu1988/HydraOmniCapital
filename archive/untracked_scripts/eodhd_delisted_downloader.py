#!/usr/bin/env python3
"""
eodhd_delisted_downloader.py
=============================
Download EOD price history for delisted S&P 500 tickers from EODHD.

EODHD free tier: 20 API calls/day.  This script budgets 1 call for the
ticker list (shared with check_eodhd_coverage.py) and 19 calls per day for
price downloads.  State is persisted to `data_sources/eodhd/download_state.json`
so the script can be run daily and resumes exactly where it left off.

Usage:
    python scripts/eodhd_delisted_downloader.py --token YOUR_API_KEY
    EODHD_API_KEY=your_key python scripts/eodhd_delisted_downloader.py

    # Dry-run: show plan without downloading
    python scripts/eodhd_delisted_downloader.py --token KEY --dry-run

    # Override calls-per-day (e.g. paid tier)
    python scripts/eodhd_delisted_downloader.py --token KEY --calls-per-day 500

    # Force re-download of already-completed tickers
    python scripts/eodhd_delisted_downloader.py --token KEY --redownload

Output:
    data_sources/eodhd/<TICKER>.parquet   — OHLCV data, snappy-compressed
    data_sources/eodhd/download_state.json — resume state
    data_sources/eodhd/eodhd_covered_missing.json — cross-reference (from check script)
    data_sources/eodhd/quality_report.json — per-ticker data quality

Data quality filter applied (mirrors exp40_survivorship_bias.py):
    - Days with |daily return| > 80% are dropped (corrupted Stooq-style data)
    - Minimum 10 trading rows required to save a file
"""

import os
import sys
import time
import json
import logging
import argparse
import math
from datetime import datetime, date
from pathlib import Path
from typing import Optional

import requests
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_CACHE = PROJECT_ROOT / 'data_cache'
EODHD_DIR = PROJECT_ROOT / 'data_sources' / 'eodhd'
STATE_FILE = EODHD_DIR / 'download_state.json'
QUALITY_REPORT_FILE = EODHD_DIR / 'quality_report.json'
COVERED_LIST_FILE = EODHD_DIR / 'eodhd_covered_missing.json'

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
EODHD_BASE_URL = 'https://eodhd.com/api'
FREE_TIER_CALLS_PER_DAY = 20
# Reserve 1 call per day for ticker-list refresh; price downloads get the rest
PRICE_CALLS_PER_DAY_FREE = FREE_TIER_CALLS_PER_DAY - 1

BACKTEST_START = '2000-01-01'
BACKTEST_END = '2026-12-31'

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2.0   # seconds; doubles on each retry
REQUEST_TIMEOUT = 45        # seconds

# Data quality thresholds (matches exp40_survivorship_bias.py)
MAX_DAILY_RETURN = 0.80     # flag rows with |return| > 80% as corrupted
MIN_ROWS_TO_SAVE = 10       # discard tickers with fewer rows after filtering

# ---------------------------------------------------------------------------
# Current BROAD_POOL (same as production — do not modify)
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
    'PANW', 'NFLX', 'COF',
    'SPY',
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state() -> dict:
    """Load persistent download state. Creates empty state if file missing."""
    if STATE_FILE.exists():
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    return {
        'completed': {},      # ticker -> {rows, date_range, file_path, downloaded_at}
        'failed': {},         # ticker -> {reason, last_attempt}
        'skipped': {},        # ticker -> {reason}  (e.g. no data / below threshold)
        'calls_today': 0,
        'calls_date': '',     # ISO date string YYYY-MM-DD
        'target_tickers': [], # ordered list of tickers to download
        'created_at': datetime.now().isoformat(),
        'last_run': '',
    }


def save_state(state: dict) -> None:
    """Persist download state to JSON."""
    state['last_run'] = datetime.now().isoformat()
    EODHD_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def reset_daily_counter_if_needed(state: dict) -> dict:
    """
    Reset the calls_today counter if we're on a new calendar day.
    EODHD's free tier resets at midnight UTC.
    """
    today_str = date.today().isoformat()
    if state['calls_date'] != today_str:
        if state['calls_date']:
            logger.info(
                "New day detected (%s). Resetting daily call counter "
                "(was %d yesterday).",
                today_str, state['calls_today']
            )
        state['calls_today'] = 0
        state['calls_date'] = today_str
    return state


# ---------------------------------------------------------------------------
# EODHD API helpers
# ---------------------------------------------------------------------------

def fetch_eodhd_delisted_list(api_token: str) -> list:
    """
    Fetch full EODHD US delisted ticker list.
    Cached to data_sources/eodhd/eodhd_us_delisted_list.json.
    Consumes 1 API call if not cached.
    """
    cache_file = EODHD_DIR / 'eodhd_us_delisted_list.json'
    EODHD_DIR.mkdir(parents=True, exist_ok=True)

    if cache_file.exists():
        with open(cache_file, 'r') as f:
            records = json.load(f)
        logger.info("Loaded %d EODHD delisted records from cache.", len(records))
        return records

    url = f'{EODHD_BASE_URL}/exchange-symbol-list/US'
    params = {'api_token': api_token, 'delisted': '1', 'fmt': 'json'}

    logger.info("Fetching EODHD delisted list (1 API call)...")
    resp = _get_with_retry(url, params)
    if resp is None:
        logger.error("Failed to fetch EODHD delisted list after retries.")
        sys.exit(1)

    try:
        records = resp.json()
    except ValueError:
        logger.error("Non-JSON response from EODHD: %s", resp.text[:300])
        sys.exit(1)

    with open(cache_file, 'w') as f:
        json.dump(records, f, indent=2)

    logger.info("EODHD delisted list: %d records, cached to %s", len(records), cache_file)
    return records


def fetch_eodhd_prices(ticker: str, api_token: str,
                        from_date: str = BACKTEST_START,
                        to_date: str = BACKTEST_END) -> Optional[pd.DataFrame]:
    """
    Fetch daily OHLCV price history for one ticker from EODHD.
    Returns None if the ticker has no data or the request fails.

    EODHD format: ticker must be 'TICKER.US' for US exchange.
    """
    eodhd_symbol = f'{ticker}.US'
    url = f'{EODHD_BASE_URL}/eod/{eodhd_symbol}'
    params = {
        'api_token': api_token,
        'from': from_date,
        'to': to_date,
        'fmt': 'json',
        'period': 'd',
    }

    resp = _get_with_retry(url, params)
    if resp is None:
        return None

    try:
        data = resp.json()
    except ValueError:
        logger.warning("[%s] Non-JSON EODHD response: %s", ticker, resp.text[:200])
        return None

    if not isinstance(data, list) or len(data) == 0:
        return None

    df = pd.DataFrame(data)

    # Normalise column names to OHLCV standard
    col_map = {
        'date': 'Date',
        'open': 'Open',
        'high': 'High',
        'low': 'Low',
        'close': 'Close',
        'adjusted_close': 'Adj Close',
        'volume': 'Volume',
    }
    df = df.rename(columns=col_map)

    required = {'Date', 'Open', 'High', 'Low', 'Close', 'Volume'}
    missing_cols = required - set(df.columns)
    if missing_cols:
        logger.warning("[%s] Missing columns %s in EODHD response", ticker, missing_cols)
        return None

    df['Date'] = pd.to_datetime(df['Date'])
    df = df.set_index('Date').sort_index()

    # Cast numeric columns
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')

    df = df[['Open', 'High', 'Low', 'Close', 'Volume']]
    df = df.dropna(subset=['Close'])

    return df


def _get_with_retry(url: str, params: dict) -> Optional[requests.Response]:
    """
    GET request with exponential backoff retry.
    Returns None if all retries are exhausted or a fatal HTTP error occurs.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)

            if resp.status_code == 200:
                return resp

            if resp.status_code == 404:
                # Ticker not found — not a transient error
                return None

            if resp.status_code == 402:
                logger.error(
                    "HTTP 402 (Payment Required) — daily API limit likely reached "
                    "or your token is invalid. Stop for today."
                )
                return None

            if resp.status_code == 429:
                wait = RETRY_BACKOFF_BASE ** attempt * 5
                logger.warning("HTTP 429 (rate limited). Waiting %.0fs...", wait)
                time.sleep(wait)
                continue

            logger.warning(
                "[Attempt %d/%d] HTTP %d for %s",
                attempt, MAX_RETRIES, resp.status_code, url
            )

        except requests.exceptions.Timeout:
            logger.warning("[Attempt %d/%d] Timeout for %s", attempt, MAX_RETRIES, url)
        except requests.exceptions.ConnectionError as e:
            logger.warning("[Attempt %d/%d] Connection error: %s", attempt, MAX_RETRIES, e)
        except requests.exceptions.RequestException as e:
            logger.warning("[Attempt %d/%d] Request error: %s", attempt, MAX_RETRIES, e)

        if attempt < MAX_RETRIES:
            wait = RETRY_BACKOFF_BASE ** attempt
            logger.info("Retrying in %.1fs...", wait)
            time.sleep(wait)

    return None


# ---------------------------------------------------------------------------
# Data quality checks
# ---------------------------------------------------------------------------

def apply_quality_filter(ticker: str, df: pd.DataFrame) -> tuple:
    """
    Apply data quality filters. Returns (clean_df, quality_info_dict).

    Filters applied:
    1. Drop rows where |daily return| > MAX_DAILY_RETURN (corrupted data,
       same issue seen in Stooq delisted data in exp40).
    2. Require at least MIN_ROWS_TO_SAVE rows after filtering.
    """
    original_rows = len(df)
    quality_info = {
        'original_rows': original_rows,
        'filtered_rows': 0,
        'dropped_rows': 0,
        'max_daily_return': None,
        'date_range': [],
        'passed': False,
        'rejection_reason': None,
    }

    if original_rows == 0:
        quality_info['rejection_reason'] = 'no_rows'
        return df, quality_info

    # Compute daily returns on Close
    returns = df['Close'].pct_change().abs()
    quality_info['max_daily_return'] = float(returns.max()) if not returns.empty else 0.0

    # Drop rows with extreme returns
    corrupted_mask = returns > MAX_DAILY_RETURN
    corrupted_count = int(corrupted_mask.sum())

    if corrupted_count > 0:
        logger.warning(
            "[%s] Dropping %d rows with |daily return| > %.0f%% "
            "(corrupted data, max was %.1f%%)",
            ticker, corrupted_count, MAX_DAILY_RETURN * 100,
            quality_info['max_daily_return'] * 100
        )
        df = df[~corrupted_mask].copy()

    # Re-check after filtering
    if len(df) < MIN_ROWS_TO_SAVE:
        quality_info['dropped_rows'] = corrupted_count
        quality_info['filtered_rows'] = len(df)
        quality_info['rejection_reason'] = (
            f'too_few_rows_after_filter ({len(df)} < {MIN_ROWS_TO_SAVE})'
        )
        return df, quality_info

    quality_info['filtered_rows'] = len(df)
    quality_info['dropped_rows'] = corrupted_count
    quality_info['date_range'] = [
        df.index.min().strftime('%Y-%m-%d'),
        df.index.max().strftime('%Y-%m-%d'),
    ]
    quality_info['passed'] = True

    return df, quality_info


# ---------------------------------------------------------------------------
# Target ticker resolution
# ---------------------------------------------------------------------------

def resolve_target_tickers(api_token: str, state: dict, calls_budget: int) -> list:
    """
    Determine the ordered list of tickers to download.

    Priority:
    1. If state has a target_tickers list already, use it (preserves original order).
    2. Otherwise: fetch EODHD delisted list + cross-reference missing tickers.

    Returns list of tickers not yet completed, in order.
    """
    if state['target_tickers']:
        targets = state['target_tickers']
        logger.info("Resuming: %d total target tickers from saved state.", len(targets))
    else:
        # Load missing tickers from sp500_snapshots.csv
        targets = _build_target_list(api_token, state, calls_budget)
        state['target_tickers'] = targets
        save_state(state)
        logger.info("Initialized target list: %d tickers.", len(targets))

    completed_set = set(state['completed'].keys())
    failed_set = set(state['failed'].keys())
    skipped_set = set(state['skipped'].keys())
    done_set = completed_set | failed_set | skipped_set

    remaining = [t for t in targets if t not in done_set]
    return remaining


def _build_target_list(api_token: str, state: dict, calls_budget: int) -> list:
    """
    Fetch EODHD delisted list and cross-reference against missing S&P 500 tickers.
    Uses 1 API call (or 0 if cached).
    """
    # Load missing tickers from local snapshot cache
    snapshots_csv = DATA_CACHE / 'sp500_snapshots.csv'
    if not snapshots_csv.exists():
        logger.error(
            "sp500_snapshots.csv not found. Run exp40_survivorship_bias.py first."
        )
        sys.exit(1)

    snapshots = pd.read_csv(snapshots_csv, parse_dates=['date'])
    post_2000 = snapshots[snapshots['date'] >= '2000-01-01']
    post_2000_tickers: set = set()
    for tickers_str in post_2000['tickers']:
        post_2000_tickers.update(
            t.strip() for t in str(tickers_str).split(',') if t.strip()
        )

    missing = sorted(post_2000_tickers - BROAD_POOL)
    logger.info("Missing tickers (in S&P 500 2000+, not in BROAD_POOL): %d", len(missing))

    # Fetch or load EODHD delisted list (1 call if not cached)
    covered_list_file = COVERED_LIST_FILE
    if covered_list_file.exists():
        # check_eodhd_coverage.py already ran — use its cross-reference
        with open(covered_list_file, 'r') as f:
            coverage_data = json.load(f)
        covered = coverage_data.get('covered_by_eodhd', [])
        logger.info(
            "Loaded pre-computed EODHD coverage: %d covered tickers.", len(covered)
        )
    else:
        # Need to build it ourselves (costs 1 API call)
        records = fetch_eodhd_delisted_list(api_token)
        state['calls_today'] += 1
        eodhd_codes = {r.get('Code', '') for r in records if r.get('Code')}
        covered = sorted(set(missing) & eodhd_codes)
        logger.info("EODHD covers %d of %d missing tickers.", len(covered), len(missing))

    return covered


# ---------------------------------------------------------------------------
# Quality report helpers
# ---------------------------------------------------------------------------

def load_quality_report() -> dict:
    if QUALITY_REPORT_FILE.exists():
        with open(QUALITY_REPORT_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_quality_report(report: dict) -> None:
    EODHD_DIR.mkdir(parents=True, exist_ok=True)
    with open(QUALITY_REPORT_FILE, 'w') as f:
        json.dump(report, f, indent=2)


# ---------------------------------------------------------------------------
# Main download loop
# ---------------------------------------------------------------------------

def run_download(api_token: str, calls_per_day: int, dry_run: bool,
                 redownload: bool) -> None:
    """
    Main download loop. Respects daily call budget and saves state after
    each successful download so the script can safely be interrupted.
    """
    EODHD_DIR.mkdir(parents=True, exist_ok=True)

    state = load_state()
    state = reset_daily_counter_if_needed(state)

    # On --redownload: clear completed set so they will be re-fetched
    if redownload:
        n_cleared = len(state['completed'])
        state['completed'] = {}
        logger.info("--redownload: cleared %d completed entries.", n_cleared)

    remaining_calls = calls_per_day - state['calls_today']

    if remaining_calls <= 0:
        logger.warning(
            "Daily call budget exhausted (%d/%d used today). "
            "Run again tomorrow.",
            state['calls_today'], calls_per_day
        )
        _print_progress(state)
        return

    logger.info(
        "Daily budget: %d calls/day | Used today: %d | Remaining: %d",
        calls_per_day, state['calls_today'], remaining_calls
    )

    # Resolve which tickers to download (uses 1 call if list not cached)
    remaining_targets = resolve_target_tickers(api_token, state, remaining_calls)

    if not remaining_targets:
        logger.info("All target tickers have been processed. Nothing to do.")
        _print_progress(state)
        return

    # Refresh remaining_calls after resolve (might have consumed 1 for list fetch)
    remaining_calls = calls_per_day - state['calls_today']
    tickers_this_session = remaining_targets[:remaining_calls]

    total_targets = len(state['target_tickers'])
    total_done = len(state['completed']) + len(state['failed']) + len(state['skipped'])
    total_remaining = len(remaining_targets)
    estimated_days_remaining = math.ceil(total_remaining / max(calls_per_day - 1, 1))

    print()
    print('=' * 65)
    print('EODHD DELISTED DOWNLOADER')
    print('=' * 65)
    print(f'  Target tickers total:     {total_targets}')
    print(f'  Completed:                {len(state["completed"])}')
    print(f'  Failed (retryable):       {len(state["failed"])}')
    print(f'  Skipped (no data):        {len(state["skipped"])}')
    print(f'  Remaining:                {total_remaining}')
    print(f'  This session (budget):    {len(tickers_this_session)}')
    print(f'  Estimated days to finish: ~{estimated_days_remaining}')
    print(f'  Output directory:         {EODHD_DIR}')
    if dry_run:
        print('  MODE: DRY-RUN (no downloads)')
    print('=' * 65)
    print()

    if dry_run:
        print('Tickers that would be downloaded this session:')
        for t in tickers_this_session:
            print(f'  {t}')
        return

    quality_report = load_quality_report()
    session_downloaded = 0
    session_failed = 0
    session_skipped = 0

    for i, ticker in enumerate(tickers_this_session):
        out_file = EODHD_DIR / f'{ticker}.parquet'

        logger.info(
            "[%d/%d] Downloading %s...",
            i + 1, len(tickers_this_session), ticker
        )

        df_raw = fetch_eodhd_prices(ticker, api_token)
        state['calls_today'] += 1

        if df_raw is None or df_raw.empty:
            state['skipped'][ticker] = {
                'reason': 'no_data_from_eodhd',
                'last_attempt': datetime.now().isoformat(),
            }
            quality_report[ticker] = {'passed': False, 'rejection_reason': 'no_data_from_eodhd'}
            session_skipped += 1
            logger.info("  %s: no data returned by EODHD — skipped.", ticker)
            save_state(state)
            save_quality_report(quality_report)
            # Small pause between requests
            time.sleep(0.5)
            continue

        # Apply data quality filter
        df_clean, q_info = apply_quality_filter(ticker, df_raw)
        quality_report[ticker] = q_info

        if not q_info['passed']:
            state['skipped'][ticker] = {
                'reason': q_info['rejection_reason'],
                'rows_before_filter': q_info['original_rows'],
                'rows_after_filter': q_info['filtered_rows'],
                'last_attempt': datetime.now().isoformat(),
            }
            session_skipped += 1
            logger.info(
                "  %s: skipped — %s (rows: %d -> %d)",
                ticker, q_info['rejection_reason'],
                q_info['original_rows'], q_info['filtered_rows']
            )
            save_state(state)
            save_quality_report(quality_report)
            time.sleep(0.5)
            continue

        # Save to parquet
        try:
            df_clean.to_parquet(out_file, compression='snappy')
            state['completed'][ticker] = {
                'rows': q_info['filtered_rows'],
                'date_range': q_info['date_range'],
                'file_path': str(out_file),
                'max_daily_return_pct': round(
                    (q_info.get('max_daily_return') or 0) * 100, 2
                ),
                'downloaded_at': datetime.now().isoformat(),
            }
            session_downloaded += 1
            logger.info(
                "  %s: saved %d rows (%s to %s) -> %s",
                ticker,
                q_info['filtered_rows'],
                q_info['date_range'][0],
                q_info['date_range'][1],
                out_file.name,
            )
        except Exception as e:
            state['failed'][ticker] = {
                'reason': f'parquet_write_error: {e}',
                'last_attempt': datetime.now().isoformat(),
            }
            session_failed += 1
            logger.error("  %s: failed to write parquet — %s", ticker, e)

        save_state(state)
        save_quality_report(quality_report)

        # Progress report every 5 tickers
        if (i + 1) % 5 == 0:
            _print_session_progress(
                i + 1, len(tickers_this_session),
                session_downloaded, session_skipped, session_failed,
                state['calls_today'], calls_per_day
            )

        # Polite pause between API calls (avoid triggering rate limiting)
        time.sleep(1.0)

    print()
    print('=' * 65)
    print('SESSION COMPLETE')
    print('=' * 65)
    _print_progress(state)

    # Final progress report
    new_remaining = len(state['target_tickers']) - (
        len(state['completed']) + len(state['failed']) + len(state['skipped'])
    )
    new_days = math.ceil(new_remaining / max(calls_per_day - 1, 1))
    print(f'  Remaining tickers:        {new_remaining}')
    print(f'  Estimated days to finish: ~{new_days}')
    print(f'  API calls used today:     {state["calls_today"]}/{calls_per_day}')
    print()


def _print_progress(state: dict) -> None:
    print()
    print('  Progress summary:')
    print(f'    Completed:  {len(state["completed"])} tickers')
    print(f'    Skipped:    {len(state["skipped"])} tickers (no data)')
    print(f'    Failed:     {len(state["failed"])} tickers (retryable)')
    print(f'    Calls today: {state["calls_today"]} (date: {state["calls_date"]})')

    if state['completed']:
        rows_total = sum(v.get('rows', 0) for v in state['completed'].values())
        print(f'    Total rows saved: {rows_total:,}')


def _print_session_progress(done: int, total: int, downloaded: int,
                              skipped: int, failed: int,
                              calls_used: int, calls_budget: int) -> None:
    pct = done / total * 100 if total else 0
    logger.info(
        "Progress: [%d/%d] %.0f%% | Downloaded: %d | Skipped: %d | Failed: %d | "
        "Calls: %d/%d",
        done, total, pct, downloaded, skipped, failed, calls_used, calls_budget
    )


# ---------------------------------------------------------------------------
# Utility: retry failed tickers
# ---------------------------------------------------------------------------

def retry_failed(state: dict) -> list:
    """
    Move failed tickers back to the pending queue by removing them from
    state['failed']. They will be re-attempted on the next run.
    Returns list of tickers that were reset.
    """
    failed_tickers = list(state['failed'].keys())
    for t in failed_tickers:
        del state['failed'][t]
    return failed_tickers


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            'Download EODHD price history for delisted S&P 500 tickers. '
            'Respects daily API call budget. Resumes across runs via state file.'
        )
    )
    parser.add_argument(
        '--token',
        default=os.environ.get('EODHD_API_KEY', ''),
        help='EODHD API token. Also reads from EODHD_API_KEY env var.',
    )
    parser.add_argument(
        '--calls-per-day',
        type=int,
        default=FREE_TIER_CALLS_PER_DAY,
        help=f'Maximum API calls per calendar day (default: {FREE_TIER_CALLS_PER_DAY} for free tier).',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show plan without making any downloads.',
    )
    parser.add_argument(
        '--redownload',
        action='store_true',
        help='Re-download tickers already marked as completed.',
    )
    parser.add_argument(
        '--retry-failed',
        action='store_true',
        help='Reset failed tickers so they will be retried this session.',
    )
    parser.add_argument(
        '--status',
        action='store_true',
        help='Print current download state and exit.',
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if args.status:
        state = load_state()
        _print_progress(state)
        total_targets = len(state['target_tickers'])
        done = len(state['completed']) + len(state['failed']) + len(state['skipped'])
        print(f'    Target tickers: {total_targets}')
        print(f'    Done:           {done}')
        print(f'    Remaining:      {max(0, total_targets - done)}')
        return

    if not args.token:
        logger.error(
            "No EODHD API token. Set EODHD_API_KEY env var or pass --token KEY."
        )
        sys.exit(1)

    state = load_state()
    state = reset_daily_counter_if_needed(state)

    if args.retry_failed:
        reset_tickers = retry_failed(state)
        save_state(state)
        logger.info("Reset %d failed tickers for retry: %s",
                    len(reset_tickers), reset_tickers[:10])

    run_download(
        api_token=args.token,
        calls_per_day=args.calls_per_day,
        dry_run=args.dry_run,
        redownload=args.redownload,
    )


if __name__ == '__main__':
    main()
