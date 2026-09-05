# Dynamic S&P 500 Universe Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded 113-stock BROAD_POOL in the live engine with auto-refreshing S&P 500 constituents from GitHub + Wikipedia, cached locally with a 4-layer fallback.

**Architecture:** New module `compass/sp500_universe.py` handles fetching, caching, and validating S&P 500 constituents. The live engine's `refresh_universe()` calls it instead of using the hardcoded list. Fallback chain: GitHub repo -> Wikipedia -> cached JSON -> hardcoded BROAD_POOL.

**Tech Stack:** Python 3.14, requests, pandas, json. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-03-12-dynamic-sp500-universe-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `compass/sp500_universe.py` | Create | Fetch, normalize, validate, cache S&P 500 constituents |
| `tests/test_sp500_universe.py` | Create | Unit tests for all fetch/cache/validate logic |
| `omnicapital_live.py` | Modify (lines 1000-1009, 857, 2517-2518, 2657-2659) | Use dynamic constituents in `refresh_universe()`, persist `_universe_source` |
| `data_cache/sp500_constituents.json` | Auto-created | Runtime cache of latest constituent list |

---

## Task 1: Core module — normalize and validate helpers

**Files:**
- Create: `compass/sp500_universe.py`
- Create: `tests/test_sp500_universe.py`

- [ ] **Step 1: Write failing tests for `_normalize_tickers` and `_validate_count`**

```python
# tests/test_sp500_universe.py
import pytest
from compass.sp500_universe import _normalize_tickers, _validate_count


class TestNormalizeTickers:
    def test_dot_to_dash(self):
        assert 'BRK-B' in _normalize_tickers(['BRK.B'])

    def test_uppercase(self):
        assert 'AAPL' in _normalize_tickers(['aapl'])

    def test_strip_whitespace(self):
        assert 'MSFT' in _normalize_tickers([' MSFT '])

    def test_deduplicate(self):
        result = _normalize_tickers(['AAPL', 'AAPL', 'aapl'])
        assert result.count('AAPL') == 1

    def test_empty_list(self):
        assert _normalize_tickers([]) == []

    def test_mixed(self):
        result = _normalize_tickers([' brk.b ', 'AAPL', 'aapl', 'MSFT'])
        assert sorted(result) == ['AAPL', 'BRK-B', 'MSFT']


class TestValidateCount:
    def test_valid_503(self):
        assert _validate_count(['X'] * 503) is True

    def test_valid_400(self):
        assert _validate_count(['X'] * 400) is True

    def test_valid_600(self):
        assert _validate_count(['X'] * 600) is True

    def test_too_few(self):
        assert _validate_count(['X'] * 399) is False

    def test_too_many(self):
        assert _validate_count(['X'] * 601) is False

    def test_empty(self):
        assert _validate_count([]) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sp500_universe.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'compass.sp500_universe'`

- [ ] **Step 3: Create `compass/sp500_universe.py` with helpers**

```python
# compass/sp500_universe.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sp500_universe.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add compass/sp500_universe.py tests/test_sp500_universe.py
git commit -m "feat: add sp500_universe module — normalize and validate helpers"
```

---

## Task 2: Cache load/save

**Files:**
- Modify: `compass/sp500_universe.py`
- Modify: `tests/test_sp500_universe.py`

- [ ] **Step 1: Write failing tests for `load_cached` and `save_cache`**

```python
# Add to tests/test_sp500_universe.py
import json
import os
import tempfile
from unittest.mock import patch
from compass.sp500_universe import load_cached, save_cache, CACHE_FILE


class TestCacheOperations:
    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.tmp_cache = os.path.join(self.tmp_dir, 'sp500_constituents.json')

    def teardown_method(self):
        if os.path.exists(self.tmp_cache):
            os.remove(self.tmp_cache)
        os.rmdir(self.tmp_dir)

    def test_save_and_load(self):
        tickers = ['AAPL', 'MSFT', 'GOOGL']
        with patch('compass.sp500_universe.CACHE_FILE', self.tmp_cache):
            save_cache(tickers, 'github')
            result = load_cached()
        assert result is not None
        assert result['tickers'] == tickers
        assert result['source'] == 'github'
        assert result['count'] == 3
        assert 'date' in result

    def test_load_missing_file(self):
        with patch('compass.sp500_universe.CACHE_FILE', '/nonexistent/path.json'):
            result = load_cached()
        assert result is None

    def test_load_corrupt_json(self):
        with open(self.tmp_cache, 'w') as f:
            f.write('not valid json{{{')
        with patch('compass.sp500_universe.CACHE_FILE', self.tmp_cache):
            result = load_cached()
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sp500_universe.py::TestCacheOperations -v`
Expected: FAIL — `ImportError: cannot import name 'load_cached'`

- [ ] **Step 3: Implement `load_cached` and `save_cache`**

Add to `compass/sp500_universe.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sp500_universe.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add compass/sp500_universe.py tests/test_sp500_universe.py
git commit -m "feat: add cache load/save for S&P 500 constituents"
```

---

## Task 3: GitHub fetcher

**Files:**
- Modify: `compass/sp500_universe.py`
- Modify: `tests/test_sp500_universe.py`

- [ ] **Step 1: Write failing tests for `fetch_from_github`**

The fja05680 repo has a directory listing via the GitHub API. We find the CSV file dynamically, download it, parse with `pd.read_csv`, and extract the latest snapshot's tickers. This mirrors the proven approach from `experiments/exp40_survivorship_bias.py`.

```python
# Add to tests/test_sp500_universe.py
from compass.sp500_universe import fetch_from_github


class TestFetchFromGitHub:
    def test_returns_list(self):
        """Integration test — requires network. Skip in CI."""
        try:
            result = fetch_from_github()
            assert isinstance(result, list)
            assert len(result) > 400
            assert 'AAPL' in result
        except Exception:
            pytest.skip("GitHub fetch failed (network issue)")

    def test_parses_csv_format(self):
        """Test CSV parsing logic with mock data."""
        mock_csv = (
            "date,tickers\n"
            "2025-12-31,\"AAPL,MSFT,GOOGL,AMZN\"\n"
            "2026-01-02,\"AAPL,MSFT,GOOGL,AMZN,NVDA\"\n"
        )
        # Mock the API directory listing
        mock_api_response = type('Response', (), {
            'status_code': 200,
            'raise_for_status': lambda self: None,
            'json': lambda self: [
                {'name': 'S&P 500 Historical Components & Changes.csv', 'download_url': 'https://raw.example.com/data.csv'}
            ],
        })()
        # Mock the CSV download
        mock_csv_response = type('Response', (), {
            'status_code': 200,
            'raise_for_status': lambda self: None,
            'text': mock_csv,
        })()
        with patch('compass.sp500_universe.requests.get', side_effect=[mock_api_response, mock_csv_response]):
            result = fetch_from_github()
        assert result == ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA']
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sp500_universe.py::TestFetchFromGitHub::test_parses_csv_format -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_from_github'`

- [ ] **Step 3: Implement `fetch_from_github`**

Add to `compass/sp500_universe.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sp500_universe.py::TestFetchFromGitHub -v`
Expected: `test_parses_csv_format` PASS, `test_returns_list` PASS or SKIP

- [ ] **Step 5: Commit**

```bash
git add compass/sp500_universe.py tests/test_sp500_universe.py
git commit -m "feat: add GitHub fetcher for S&P 500 constituents"
```

---

## Task 4: Wikipedia fetcher

**Files:**
- Modify: `compass/sp500_universe.py`
- Modify: `tests/test_sp500_universe.py`

- [ ] **Step 1: Write failing tests for `fetch_from_wikipedia`**

```python
# Add to tests/test_sp500_universe.py
from compass.sp500_universe import fetch_from_wikipedia


class TestFetchFromWikipedia:
    def test_returns_list(self):
        """Integration test — requires network."""
        try:
            result = fetch_from_wikipedia()
            assert isinstance(result, list)
            assert len(result) > 400
            assert 'AAPL' in result
        except Exception:
            pytest.skip("Wikipedia fetch failed (network issue)")

    def test_parses_html_table(self):
        """Test parsing logic with mock DataFrame."""
        mock_df = pd.DataFrame({'Symbol': ['AAPL', 'BRK.B', 'MSFT']})
        with patch('compass.sp500_universe.pd.read_html', return_value=[mock_df]):
            result = fetch_from_wikipedia()
        assert result == ['AAPL', 'BRK.B', 'MSFT']
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sp500_universe.py::TestFetchFromWikipedia::test_parses_html_table -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_from_wikipedia'`

- [ ] **Step 3: Implement `fetch_from_wikipedia`**

Add to `compass/sp500_universe.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sp500_universe.py::TestFetchFromWikipedia -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add compass/sp500_universe.py tests/test_sp500_universe.py
git commit -m "feat: add Wikipedia fetcher for S&P 500 constituents"
```

---

## Task 5: Orchestrator — `refresh_constituents`

**Files:**
- Modify: `compass/sp500_universe.py`
- Modify: `tests/test_sp500_universe.py`

- [ ] **Step 1: Write failing tests for `refresh_constituents`**

```python
# Add to tests/test_sp500_universe.py
from compass.sp500_universe import refresh_constituents


FAKE_500 = [f'TICK{i}' for i in range(503)]
FALLBACK = ['AAPL', 'MSFT']


class TestRefreshConstituents:
    def test_github_success(self):
        with patch('compass.sp500_universe.fetch_from_github', return_value=FAKE_500):
            tickers, source = refresh_constituents(FALLBACK)
        assert len(tickers) == 503
        assert source == 'github'

    def test_github_fails_wikipedia_succeeds(self):
        with patch('compass.sp500_universe.fetch_from_github', side_effect=Exception("down")), \
             patch('compass.sp500_universe.fetch_from_wikipedia', return_value=FAKE_500):
            tickers, source = refresh_constituents(FALLBACK)
        assert len(tickers) == 503
        assert source == 'wikipedia'

    def test_both_fail_uses_cache(self):
        cached = {'tickers': FAKE_500, 'source': 'github', 'date': '2025-01-01', 'count': 503}
        with patch('compass.sp500_universe.fetch_from_github', side_effect=Exception("down")), \
             patch('compass.sp500_universe.fetch_from_wikipedia', side_effect=Exception("down")), \
             patch('compass.sp500_universe.load_cached', return_value=cached):
            tickers, source = refresh_constituents(FALLBACK)
        assert len(tickers) == 503
        assert source == 'cached'

    def test_all_fail_uses_fallback(self):
        with patch('compass.sp500_universe.fetch_from_github', side_effect=Exception("down")), \
             patch('compass.sp500_universe.fetch_from_wikipedia', side_effect=Exception("down")), \
             patch('compass.sp500_universe.load_cached', return_value=None):
            tickers, source = refresh_constituents(FALLBACK)
        assert tickers == FALLBACK
        assert source == 'fallback'

    def test_validation_rejects_too_few(self):
        small_list = ['AAPL', 'MSFT']
        with patch('compass.sp500_universe.fetch_from_github', return_value=small_list), \
             patch('compass.sp500_universe.fetch_from_wikipedia', return_value=FAKE_500):
            tickers, source = refresh_constituents(FALLBACK)
        assert source == 'wikipedia'  # GitHub rejected by validation

    def test_normalizes_tickers(self):
        raw = [f'tick.{i}' for i in range(503)]  # lowercase + dots
        with patch('compass.sp500_universe.fetch_from_github', return_value=raw):
            tickers, source = refresh_constituents(FALLBACK)
        assert all(t == t.upper() for t in tickers)
        assert all('.' not in t for t in tickers)

    def test_saves_cache_on_fresh_fetch(self):
        with patch('compass.sp500_universe.fetch_from_github', return_value=FAKE_500), \
             patch('compass.sp500_universe.save_cache') as mock_save:
            refresh_constituents(FALLBACK)
        mock_save.assert_called_once()
        args = mock_save.call_args[0]
        assert len(args[0]) == 503
        assert args[1] == 'github'

    def test_does_not_save_cache_on_fallback(self):
        with patch('compass.sp500_universe.fetch_from_github', side_effect=Exception("down")), \
             patch('compass.sp500_universe.fetch_from_wikipedia', side_effect=Exception("down")), \
             patch('compass.sp500_universe.load_cached', return_value=None), \
             patch('compass.sp500_universe.save_cache') as mock_save:
            refresh_constituents(FALLBACK)
        mock_save.assert_not_called()

    def test_does_not_save_cache_on_cached(self):
        cached = {'tickers': FAKE_500, 'source': 'github', 'date': '2025-01-01', 'count': 503}
        with patch('compass.sp500_universe.fetch_from_github', side_effect=Exception("down")), \
             patch('compass.sp500_universe.fetch_from_wikipedia', side_effect=Exception("down")), \
             patch('compass.sp500_universe.load_cached', return_value=cached), \
             patch('compass.sp500_universe.save_cache') as mock_save:
            refresh_constituents(FALLBACK)
        mock_save.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sp500_universe.py::TestRefreshConstituents -v`
Expected: FAIL — `ImportError: cannot import name 'refresh_constituents'`

- [ ] **Step 3: Implement `refresh_constituents`**

Add to `compass/sp500_universe.py`:

```python
def refresh_constituents(fallback_pool: List[str]) -> Tuple[List[str], str]:
    # Layer 1: GitHub
    try:
        raw = fetch_from_github()
        tickers = _normalize_tickers(raw)
        if _validate_count(tickers):
            save_cache(tickers, 'github')
            return tickers, 'github'
        logger.warning(f"GitHub returned {len(tickers)} tickers (expected {MIN_CONSTITUENTS}-{MAX_CONSTITUENTS}), trying Wikipedia")
    except Exception as e:
        logger.warning(f"GitHub fetch failed: {e}")

    # Layer 2: Wikipedia
    try:
        raw = fetch_from_wikipedia()
        tickers = _normalize_tickers(raw)
        if _validate_count(tickers):
            save_cache(tickers, 'wikipedia')
            return tickers, 'wikipedia'
        logger.warning(f"Wikipedia returned {len(tickers)} tickers (expected {MIN_CONSTITUENTS}-{MAX_CONSTITUENTS}), trying cache")
    except Exception as e:
        logger.warning(f"Wikipedia fetch failed: {e}")

    # Layer 3: Cached file (still normalize + validate for safety)
    cached = load_cached()
    if cached and cached.get('tickers'):
        tickers = _normalize_tickers(cached['tickers'])
        if _validate_count(tickers):
            logger.info(f"Using cached constituents from {cached.get('date', 'unknown')} ({len(tickers)} tickers)")
            return tickers, 'cached'
        logger.warning(f"Cached file has {len(tickers)} tickers (invalid count), falling back")

    # Layer 4: Hardcoded fallback
    logger.warning(f"All sources failed. Using hardcoded fallback ({len(fallback_pool)} tickers)")
    return list(fallback_pool), 'fallback'
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sp500_universe.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add compass/sp500_universe.py tests/test_sp500_universe.py
git commit -m "feat: add refresh_constituents orchestrator with 4-layer fallback"
```

---

## Task 6: Integrate into live engine

**Files:**
- Modify: `omnicapital_live.py` (lines 857, 1000-1009, 2517-2518, 2657-2659)

- [ ] **Step 1: Modify `refresh_universe()` at line 1000**

Replace the current `refresh_universe` method (lines 1000-1009):

```python
def refresh_universe(self):
    """Refresh top-N universe if new year (dynamic S&P 500 constituents)"""
    current_year = self.get_et_now().year
    needs_refresh = self.universe_year != current_year
    # Retry if previous attempt fell back to cached/hardcoded
    if not needs_refresh and getattr(self, '_universe_source', '') == 'fallback':
        days_into_year = (self.get_et_now() - datetime(current_year, 1, 1)).days
        needs_refresh = days_into_year <= 7

    if needs_refresh:
        logger.info(f"Computing {current_year} universe...")
        from compass.sp500_universe import refresh_constituents
        broad_pool, source = refresh_constituents(fallback_pool=BROAD_POOL)
        self._universe_source = source if source in ('github', 'wikipedia') else 'fallback'
        self.current_universe = compute_annual_top40(
            broad_pool, self.config['TOP_N']
        )
        self.universe_year = current_year
        logger.info(f"Universe updated: {len(self.current_universe)} stocks from {len(broad_pool)} constituents (source: {source})")
```

- [ ] **Step 2: Update `_log_config()` at line 857**

Replace:
```python
logger.info(f"Universe: {len(BROAD_POOL)} broad pool -> top {config['TOP_N']}")
```
With:
```python
logger.info(f"Universe: dynamic S&P 500 -> top {config['TOP_N']}")
```

- [ ] **Step 3: Add `_universe_source` to state save (after line 2518)**

Add after the `'universe_year'` line in the state dict:
```python
'_universe_source': getattr(self, '_universe_source', ''),
```

- [ ] **Step 4: Add `_universe_source` to state restore (after line 2659)**

Add after the `self.universe_year` restore line:
```python
self._universe_source = state.get('_universe_source', '')
```

- [ ] **Step 5: Syntax check**

Run: `python -c "import py_compile; py_compile.compile('omnicapital_live.py')"`
Expected: No output (clean compile)

- [ ] **Step 6: Run existing tests to verify no regressions**

Run: `pytest tests/ -v --timeout=60`
Expected: All existing tests pass

- [ ] **Step 7: Commit**

```bash
git add omnicapital_live.py
git commit -m "feat: integrate dynamic S&P 500 universe into live engine"
```

---

## Task 7: Integration test

**Files:**
- Modify: `tests/test_sp500_universe.py`

- [ ] **Step 1: Write integration test for full refresh flow**

```python
# Add to tests/test_sp500_universe.py

class TestIntegration:
    def test_full_refresh_cycle(self):
        """Test the complete flow: fetch -> normalize -> validate -> cache -> return."""
        with patch('compass.sp500_universe.fetch_from_github', return_value=FAKE_500), \
             patch('compass.sp500_universe.save_cache') as mock_save:
            tickers1, source1 = refresh_constituents(['FALLBACK'])

        assert source1 == 'github'
        assert len(tickers1) == 503

        # Simulate second call using cache
        cached_data = {
            'date': '2026-01-02',
            'source': 'github',
            'tickers': tickers1,
            'count': len(tickers1),
        }
        with patch('compass.sp500_universe.fetch_from_github', side_effect=Exception("rate limited")), \
             patch('compass.sp500_universe.fetch_from_wikipedia', side_effect=Exception("down")), \
             patch('compass.sp500_universe.load_cached', return_value=cached_data):
            tickers2, source2 = refresh_constituents(['FALLBACK'])

        assert source2 == 'cached'
        assert tickers2 == tickers1
```

- [ ] **Step 2: Run all tests**

Run: `pytest tests/test_sp500_universe.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_sp500_universe.py
git commit -m "test: add integration test for S&P 500 universe refresh cycle"
```

---

## Task 8: Live network test (manual verification)

- [ ] **Step 1: Test GitHub fetch live**

Run: `python -c "from compass.sp500_universe import fetch_from_github; t = fetch_from_github(); print(f'{len(t)} tickers, first 5: {t[:5]}')"`
Expected: ~503 tickers, includes AAPL

- [ ] **Step 2: Test Wikipedia fetch live**

Run: `python -c "from compass.sp500_universe import fetch_from_wikipedia; t = fetch_from_wikipedia(); print(f'{len(t)} tickers, first 5: {t[:5]}')"`
Expected: ~503 tickers, includes AAPL

- [ ] **Step 3: Test full refresh with caching**

Run: `python -c "from compass.sp500_universe import refresh_constituents; t, s = refresh_constituents(['FALLBACK']); print(f'{len(t)} tickers from {s}')"`
Expected: ~503 tickers from github (or wikipedia). Check that `data_cache/sp500_constituents.json` was created.

- [ ] **Step 4: Verify cache file**

Run: `python -c "import json; d = json.load(open('data_cache/sp500_constituents.json')); print(f\"Date: {d['date']}, Source: {d['source']}, Count: {d['count']}\")"`
Expected: Today's date, source github or wikipedia, count ~503

- [ ] **Step 5: Commit any final adjustments**

```bash
git add data_cache/sp500_constituents.json
git commit -m "chore: verify live S&P 500 fetcher works end-to-end"
```
