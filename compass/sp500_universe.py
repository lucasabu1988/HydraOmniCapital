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
