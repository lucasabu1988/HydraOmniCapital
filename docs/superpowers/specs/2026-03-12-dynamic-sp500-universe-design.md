# Design: Dynamic S&P 500 Universe for Live Engine

**Date**: 2026-03-12
**Status**: Approved
**Scope**: Live engine only (`omnicapital_live.py`). Backtest engine unchanged.

## Problem

`BROAD_POOL` in `omnicapital_live.py` is a hardcoded list of 113 S&P 500 stocks. When the S&P 500 index adds or removes constituents (IPOs, mergers, delistings), the live engine never picks up the changes. This requires manual code edits to keep the universe current.

## Solution

Replace the hardcoded `BROAD_POOL` dependency in the live engine's `refresh_universe()` with a cached constituent file that auto-refreshes annually from two external sources, with a 4-layer fallback chain.

## Architecture

```
Annual refresh (triggered on first trading cycle of the new year):
  1. Try fja05680 GitHub repo (raw CSV of daily S&P 500 members)
  2. If fails -> try Wikipedia scrape (pd.read_html)
  3. If fails -> use cached file (last known good)
  4. If no cache exists -> fall back to hardcoded BROAD_POOL
  5. Validate: fetched list must have 400-600 tickers, else treat as failure
  6. Save successful result to data_cache/sp500_constituents.json
  7. Feed full ~503 list into compute_annual_top40() -> top 40 by dollar volume
```

**Retry logic**: If the engine falls back to layers 3 or 4 (cached/hardcoded), it sets `self._universe_source = 'fallback'` and retries the fetch on subsequent daily cycles for up to 7 days. Once a fresh fetch succeeds (layer 1 or 2), retries stop for the rest of the year.

## Components

### New file: `compass/sp500_universe.py`

Module responsible for fetching and caching S&P 500 constituent lists.

**Functions:**

- `fetch_from_github() -> List[str]`
  - Uses the GitHub API to list files: `https://api.github.com/repos/fja05680/sp500/contents/S%26P%20500%20Historical%20Components%20%26%20Changes`
  - Finds the most recent dated CSV file from the directory listing
  - Downloads raw content via `https://raw.githubusercontent.com/fja05680/sp500/master/S%26P%20500%20Historical%20Components%20%26%20Changes/<filename>`
  - CSV format: `date` column + comma-separated ticker list per row. Parse the last row to get the most recent composition.
  - Uses `requests` library (already available via yfinance dependency)
  - Returns list of ~503 tickers

- `fetch_from_wikipedia() -> List[str]`
  - Uses `pd.read_html('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')`
  - Extracts the 'Symbol' column from the first table (index 0)
  - Returns list of ~503 tickers

- `load_cached() -> Optional[Dict]`
  - Reads `data_cache/sp500_constituents.json`
  - Returns dict with `date`, `source`, `tickers`, `count`
  - Returns None if file doesn't exist or is invalid JSON

- `save_cache(tickers: List[str], source: str) -> None`
  - Saves to `data_cache/sp500_constituents.json` with timestamp and source metadata
  - Uses `json.dump` with `indent=2`

- `_normalize_tickers(tickers: List[str]) -> List[str]`
  - Strips whitespace, uppercases, replaces `.` with `-` (BRK.B -> BRK-B)
  - Deduplicates

- `_validate_count(tickers: List[str]) -> bool`
  - Returns True if 400 <= len(tickers) <= 600
  - Prevents corrupted fetches from narrowing or polluting the universe

- `refresh_constituents(fallback_pool: List[str]) -> Tuple[List[str], str]`
  - Orchestrator function called by the live engine
  - Try GitHub -> Wikipedia -> cached -> fallback_pool
  - Each layer: fetch, normalize, validate count. If validation fails, treat as failure and fall to next layer
  - Logs which source was used at INFO level, failures at WARNING
  - All fetches wrapped in `try/except Exception` — never raises
  - Returns `(tickers, source)` tuple — source is one of: `'github'`, `'wikipedia'`, `'cached'`, `'fallback'`

### Modified: `omnicapital_live.py`

**`refresh_universe()` method** (~10 lines changed):

```python
def refresh_universe(self):
    current_year = self.get_et_now().year
    needs_refresh = self.universe_year != current_year
    # Retry if previous attempt fell back to cached/hardcoded
    if not needs_refresh and getattr(self, '_universe_source', '') == 'fallback':
        days_into_year = (self.get_et_now() - datetime(current_year, 1, 1)).days
        needs_refresh = days_into_year <= 7  # retry for first 7 days

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

**`_log_config()` method** (1 line updated):

```python
# Change from:
logger.info(f"Universe: {len(BROAD_POOL)} broad pool -> top {config['TOP_N']}")
# To:
logger.info(f"Universe: dynamic S&P 500 -> top {config['TOP_N']}")
```

- `BROAD_POOL` constant remains in the file as the ultimate fallback
- `_universe_source` added to state save/restore for persistence across restarts

### Cache file: `data_cache/sp500_constituents.json`

Created automatically on first successful fetch. Location: `data_cache/` (alongside other runtime cache files, not `config/` which is for static configuration).

```json
{
  "date": "2026-01-02",
  "source": "github",
  "tickers": ["AAPL", "MSFT", "GOOGL", "..."],
  "count": 503
}
```

## Error Handling

4-layer fallback chain (never crashes):

| Layer | Source | Failure mode |
|-------|--------|-------------|
| 1 | fja05680 GitHub | Network error, repo down, format change, count validation fail |
| 2 | Wikipedia scrape | Network error, HTML structure change, count validation fail |
| 3 | Cached JSON file | File missing, corrupt JSON, stale (but still valid) |
| 4 | Hardcoded BROAD_POOL | Never fails (compile-time constant) |

- Every fetch wrapped in `try/except Exception`
- Each failure logs a WARNING with the error
- The successful source logs at INFO level
- Count validation (400-600) catches corrupted fetches before they enter the pipeline
- Retry logic ensures transient failures on Jan 2 don't lock in stale data for the full year
- The engine always gets a valid ticker list

## Ticker Normalization

- Wikipedia uses `.` separator (e.g., `BRK.B`), yfinance uses `-` (e.g., `BRK-B`)
- GitHub repo may use either format depending on the snapshot
- `_normalize_tickers()` handles: replace `.` with `-`, strip whitespace, uppercase, deduplicate
- Applied to every source (GitHub, Wikipedia, cached) for consistency

## What Stays Unchanged

- `compute_annual_top40()` — still ranks by dollar volume, picks top 40
- All signal logic — momentum scoring, regime filter, stops, trailing (algorithm locked)
- Backtest engine (`omnicapital_v84_compass.py`) — keeps hardcoded 113 for reproducibility
- Refresh cadence — still annual, triggered by year change in `refresh_universe()`
- The output is still 40 stocks — only the input funnel widens from 113 to ~503

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| GitHub repo stops updating | Wikipedia fallback + cached file |
| Wikipedia HTML changes | GitHub primary + cached file |
| Corrupted fetch (wrong table, format change) | Count validation (400-600 range) |
| More yfinance calls (503 vs 113) | Happens once per year, acceptable |
| New tickers have no price data | `compute_annual_top40` already skips stocks with < 20 days data |
| Ticker format differences | `_normalize_tickers()` applied to all sources |
| All sources fail on first attempt | 7-day retry window, then falls back gracefully |

## Scope

- ~150 lines new code in `compass/sp500_universe.py`
- ~10 lines changed in `omnicapital_live.py`
- 1 new JSON file auto-created in `data_cache/`
- No new dependencies — uses `requests` (already available via yfinance) and `pandas`
