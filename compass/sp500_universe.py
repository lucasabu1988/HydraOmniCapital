"""
Dynamic S&P 500 constituent fetcher for COMPASS live engine.

Fetches current S&P 500 members from GitHub (fja05680/sp500) or Wikipedia,
caches locally, with 4-layer fallback: GitHub -> Wikipedia -> cached -> hardcoded.
"""

import io
import json
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

logger = logging.getLogger(__name__)

CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                          'data_cache', 'sp500_constituents.json')
GITHUB_API_URL = 'https://api.github.com/repos/fja05680/sp500/contents'
WIKIPEDIA_URL = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'

MIN_CONSTITUENTS = 400
MAX_CONSTITUENTS = 600


def _normalize_tickers(tickers: List[str]) -> List[str]:
    seen = set()
    result = []
    for t in tickers:
        t = t.strip().upper().replace('.', '-')
        if t and t not in seen:
            seen.add(t)
            result.append(t)
    return result


def _validate_count(tickers: List[str]) -> bool:
    return MIN_CONSTITUENTS <= len(tickers) <= MAX_CONSTITUENTS


def load_cached() -> Optional[Dict]:
    try:
        with open(CACHE_FILE, 'r') as f:
            data = json.load(f)
        if 'tickers' in data and isinstance(data['tickers'], list):
            return data
        return None
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def save_cache(tickers: List[str], source: str) -> None:
    try:
        os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
        data = {
            'date': datetime.now().strftime('%Y-%m-%d'),
            'source': source,
            'tickers': tickers,
            'count': len(tickers),
        }
        with open(CACHE_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Cached {len(tickers)} S&P 500 constituents (source: {source})")
    except OSError as e:
        logger.warning(f"Failed to save constituent cache: {e}")


def fetch_from_github() -> List[str]:
    logger.info("Fetching S&P 500 constituents from GitHub (fja05680/sp500)...")

    # Step 1: Use GitHub API to discover the CSV filename dynamically
    resp = requests.get(GITHUB_API_URL, timeout=30)
    resp.raise_for_status()
    files = resp.json()
    csv_files = [f for f in files if f['name'].endswith('.csv') and 'Historical' in f['name']]
    if not csv_files:
        raise ValueError("No historical CSV found in fja05680/sp500 repo")

    # Step 2: Download the CSV via raw URL
    download_url = csv_files[0]['download_url']
    resp = requests.get(download_url, timeout=60)
    resp.raise_for_status()

    # Step 3: Parse with pd.read_csv (proven approach from exp40)
    df = pd.read_csv(io.StringIO(resp.text))
    if 'tickers' not in df.columns:
        raise ValueError(f"'tickers' column not found. Columns: {list(df.columns)}")

    # Last row = most recent composition
    df = df.sort_values('date').reset_index(drop=True)
    ticker_str = str(df.iloc[-1]['tickers'])
    tickers = [t.strip() for t in ticker_str.split(',') if t.strip()]
    logger.info(f"GitHub: parsed {len(tickers)} tickers from latest snapshot")
    return tickers


def fetch_from_wikipedia() -> List[str]:
    logger.info("Fetching S&P 500 constituents from Wikipedia...")
    tables = pd.read_html(WIKIPEDIA_URL)
    if not tables:
        raise ValueError("No tables found on Wikipedia S&P 500 page")

    df = tables[0]
    if 'Symbol' not in df.columns:
        raise ValueError(f"'Symbol' column not found. Columns: {list(df.columns)}")

    tickers = df['Symbol'].dropna().tolist()
    logger.info(f"Wikipedia: parsed {len(tickers)} tickers")
    return tickers
