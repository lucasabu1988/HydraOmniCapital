#!/usr/bin/env python3
"""
check_eodhd_coverage.py
=======================
Uses exactly 2 EODHD API calls to assess how many of our 475 missing S&P 500
tickers are available in EODHD's delisted database.

Usage:
    python scripts/check_eodhd_coverage.py --token YOUR_API_KEY
    EODHD_API_KEY=your_key python scripts/check_eodhd_coverage.py

API calls consumed: 1 (delisted ticker list only).
The cross-reference is pure local computation.

This script is intentionally conservative — only 1 actual API call is made,
leaving 19 of your 20 daily free-tier calls for the main downloader.
"""

import os
import sys
import logging
import argparse
import json
from pathlib import Path

import requests
import pandas as pd

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_CACHE = PROJECT_ROOT / 'data_cache'
DATA_CACHE_PARQUET = PROJECT_ROOT / 'data_cache_parquet'
EODHD_DIR = PROJECT_ROOT / 'data_sources' / 'eodhd'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger(__name__)


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


# ---------------------------------------------------------------------------
# Step 1: Load missing tickers from local S&P 500 snapshot data
# ---------------------------------------------------------------------------

def load_missing_tickers() -> list:
    """
    Identify tickers that appeared in historical S&P 500 snapshots but are
    not in the current BROAD_POOL. Uses cached sp500_snapshots.csv produced
    by exp40_survivorship_bias.py.

    Returns list of missing tickers, sorted alphabetically.
    """
    snapshots_csv = DATA_CACHE / 'sp500_snapshots.csv'

    if not snapshots_csv.exists():
        logger.error(
            "sp500_snapshots.csv not found at %s. "
            "Run experiments/exp40_survivorship_bias.py first to build the cache.",
            snapshots_csv
        )
        sys.exit(1)

    logger.info("Loading S&P 500 snapshots from %s", snapshots_csv)
    snapshots = pd.read_csv(snapshots_csv, parse_dates=['date'])
    logger.info("  %d snapshot dates loaded (range: %s to %s)",
                len(snapshots),
                snapshots['date'].min().strftime('%Y-%m-%d'),
                snapshots['date'].max().strftime('%Y-%m-%d'))

    # Collect all unique historical tickers
    all_historical: set = set()
    for tickers_str in snapshots['tickers']:
        all_historical.update(
            t.strip() for t in str(tickers_str).split(',') if t.strip()
        )

    # Focus on tickers that appeared from 2000 onward (backtest start)
    post_2000 = snapshots[snapshots['date'] >= '2000-01-01']
    post_2000_tickers: set = set()
    for tickers_str in post_2000['tickers']:
        post_2000_tickers.update(
            t.strip() for t in str(tickers_str).split(',') if t.strip()
        )

    missing = sorted(post_2000_tickers - BROAD_POOL)

    logger.info("  Historical unique tickers (all time): %d", len(all_historical))
    logger.info("  Historical unique tickers (2000+): %d", len(post_2000_tickers))
    logger.info("  Already in BROAD_POOL: %d", len(BROAD_POOL))
    logger.info("  Missing (not in BROAD_POOL): %d", len(missing))

    return missing


# ---------------------------------------------------------------------------
# Step 2: Fetch EODHD delisted ticker list (1 API call)
# ---------------------------------------------------------------------------

def fetch_eodhd_delisted_list(api_token: str) -> list:
    """
    Fetch the full list of delisted US exchange tickers from EODHD.
    Uses 1 API call.

    Returns list of ticker strings (e.g. ['ENRN', 'LEHM', ...]).
    """
    # Cache locally so this 1 call is not repeated unnecessarily
    cache_file = EODHD_DIR / 'eodhd_us_delisted_list.json'
    EODHD_DIR.mkdir(parents=True, exist_ok=True)

    if cache_file.exists():
        logger.info("Loading EODHD delisted list from local cache: %s", cache_file)
        with open(cache_file, 'r') as f:
            records = json.load(f)
        logger.info("  %d delisted records loaded from cache", len(records))
        return [r.get('Code', '') for r in records if r.get('Code')]

    url = 'https://eodhd.com/api/exchange-symbol-list/US'
    params = {
        'api_token': api_token,
        'delisted': '1',
        'fmt': 'json',
    }

    logger.info("Fetching EODHD delisted US ticker list (1 API call)...")
    try:
        resp = requests.get(url, params=params, timeout=60)
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if resp.status_code == 402:
            logger.error(
                "EODHD returned HTTP 402 (Payment Required). "
                "The free tier may require registration. Check your token."
            )
        else:
            logger.error("EODHD HTTP error: %s", e)
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        logger.error("Network error fetching EODHD list: %s", e)
        sys.exit(1)

    try:
        records = resp.json()
    except ValueError as e:
        logger.error("EODHD returned non-JSON response: %s", resp.text[:500])
        sys.exit(1)

    if not isinstance(records, list):
        logger.error("Unexpected EODHD response format: %s", str(records)[:200])
        sys.exit(1)

    logger.info("  EODHD returned %d delisted records", len(records))

    # Save to cache so we don't burn another call tomorrow
    with open(cache_file, 'w') as f:
        json.dump(records, f, indent=2)
    logger.info("  Cached to %s", cache_file)

    return [r.get('Code', '') for r in records if r.get('Code')]


# ---------------------------------------------------------------------------
# Step 3: Cross-reference and report
# ---------------------------------------------------------------------------

def report_coverage(missing_tickers: list, eodhd_tickers: list) -> dict:
    """
    Cross-reference missing tickers against EODHD delisted list.
    Prints a detailed coverage report and returns summary dict.
    """
    eodhd_set = set(eodhd_tickers)
    missing_set = set(missing_tickers)

    covered = sorted(missing_set & eodhd_set)
    not_covered = sorted(missing_set - eodhd_set)

    coverage_pct = len(covered) / len(missing_set) * 100 if missing_set else 0

    # Classify covered tickers by likely delisting reason
    # (heuristic: known bankruptcies/failures vs acquisitions)
    known_bankruptcies = {
        'ENE', 'WCOM', 'LEH', 'BSC', 'WM', 'CFC', 'MER', 'WB', 'ABI',
        'SGP', 'WYE', 'GM', 'C', 'FNM', 'FRE', 'WB',
    }
    covered_bankruptcies = [t for t in covered if t in known_bankruptcies]

    print()
    print('=' * 65)
    print('EODHD COVERAGE REPORT FOR MISSING S&P 500 TICKERS')
    print('=' * 65)
    print(f'  Missing tickers (in S&P 500 2000+, not in BROAD_POOL): {len(missing_set):>4d}')
    print(f'  EODHD delisted US tickers (total):                     {len(eodhd_set):>4d}')
    print(f'  Covered by EODHD:                                      {len(covered):>4d}  ({coverage_pct:.1f}%)')
    print(f'  NOT covered by EODHD:                                  {len(not_covered):>4d}  ({100-coverage_pct:.1f}%)')
    print()
    print(f'  Covered high-profile names: {len(covered_bankruptcies)} known bankruptcies/failures')
    print()

    if covered:
        print('  COVERED tickers (first 50):')
        for i, t in enumerate(covered[:50]):
            suffix = ' *bankruptcy*' if t in known_bankruptcies else ''
            print(f'    {t:8s}{suffix}')
        if len(covered) > 50:
            print(f'    ... and {len(covered) - 50} more')

    print()
    if not_covered:
        print('  NOT COVERED tickers (first 50):')
        for t in not_covered[:50]:
            print(f'    {t}')
        if len(not_covered) > 50:
            print(f'    ... and {len(not_covered) - 50} more')

    print()
    print('  RECOMMENDATION:')
    if coverage_pct >= 70:
        print(f'    EODHD covers {coverage_pct:.0f}% of missing tickers.')
        print('    Run eodhd_delisted_downloader.py to fetch price data.')
        print('    At 20 calls/day, estimated completion: '
              f'~{len(covered) // 19 + 1} days (1 call/day reserved for list refresh).')
    elif coverage_pct >= 40:
        print(f'    Partial coverage ({coverage_pct:.0f}%). EODHD is worth running for covered tickers.')
        print('    Consider Norgate Data for the remaining gap.')
    else:
        print(f'    Low coverage ({coverage_pct:.0f}%). EODHD may not meaningfully reduce survivorship bias.')
        print('    Norgate Data ($500/yr) remains the recommended solution for full coverage.')

    print('=' * 65)

    return {
        'missing_total': len(missing_set),
        'eodhd_total': len(eodhd_set),
        'covered': len(covered),
        'not_covered': len(not_covered),
        'coverage_pct': round(coverage_pct, 1),
        'covered_tickers': covered,
        'not_covered_tickers': not_covered,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(
        description='Check EODHD coverage for missing S&P 500 historical tickers. '
                    'Consumes 1 API call (or 0 if cached).'
    )
    parser.add_argument(
        '--token',
        default=os.environ.get('EODHD_API_KEY', ''),
        help='EODHD API token. Also reads from EODHD_API_KEY env var.',
    )
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Force re-fetch EODHD list even if locally cached.',
    )
    parser.add_argument(
        '--save-report',
        metavar='PATH',
        default='',
        help='Save coverage results to this JSON file path.',
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.token:
        logger.error(
            "No EODHD API token provided. "
            "Set EODHD_API_KEY environment variable or pass --token YOUR_KEY"
        )
        sys.exit(1)

    # Remove cached list if --no-cache requested
    if args.no_cache:
        cache_file = EODHD_DIR / 'eodhd_us_delisted_list.json'
        if cache_file.exists():
            cache_file.unlink()
            logger.info("Cleared local EODHD list cache (--no-cache)")

    # Step 1: identify which tickers we're missing
    missing_tickers = load_missing_tickers()

    # Step 2: fetch EODHD delisted list (1 API call, cached after first run)
    eodhd_tickers = fetch_eodhd_delisted_list(args.token)

    # Step 3: report
    results = report_coverage(missing_tickers, eodhd_tickers)

    # Optionally save to JSON
    if args.save_report:
        report_path = Path(args.save_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info("Report saved to %s", report_path)

    # Save covered list for the downloader to consume
    covered_list_path = EODHD_DIR / 'eodhd_covered_missing.json'
    with open(covered_list_path, 'w') as f:
        json.dump(
            {
                'missing_tickers': missing_tickers,
                'covered_by_eodhd': results['covered_tickers'],
                'not_covered': results['not_covered_tickers'],
            },
            f, indent=2
        )
    logger.info(
        "Coverage list saved to %s — eodhd_delisted_downloader.py will use this.",
        covered_list_path
    )


if __name__ == '__main__':
    main()
