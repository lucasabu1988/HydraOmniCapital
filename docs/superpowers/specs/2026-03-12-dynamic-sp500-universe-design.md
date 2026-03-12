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
Annual refresh (triggered by refresh_universe() on Jan 1):
  1. Try fja05680 GitHub repo (raw CSV of daily S&P 500 members)
  2. If fails -> try Wikipedia scrape (pd.read_html)
  3. If fails -> use cached file (last known good)
  4. If no cache exists -> fall back to hardcoded BROAD_POOL
  5. Save successful result to config/sp500_constituents.json
  6. Feed full ~503 list into compute_annual_top40() -> top 40 by dollar volume
```

## Components

### New file: `compass/sp500_universe.py`

Module responsible for fetching and caching S&P 500 constituent lists.

**Functions:**

- `fetch_from_github() -> List[str]`
  - Downloads latest snapshot from `fja05680/sp500` GitHub repo
  - Parses the most recent daily snapshot CSV to extract ticker list
  - URL: raw GitHub content of the latest dated file
  - Returns list of ~503 tickers

- `fetch_from_wikipedia() -> List[str]`
  - Uses `pd.read_html()` on the S&P 500 Wikipedia page
  - Extracts the 'Symbol' column from the constituents table
  - Returns list of ~503 tickers

- `load_cached() -> Optional[Dict]`
  - Reads `config/sp500_constituents.json`
  - Returns dict with `date`, `source`, `tickers`, `count`
  - Returns None if file doesn't exist or is invalid JSON

- `save_cache(tickers: List[str], source: str) -> None`
  - Saves to `config/sp500_constituents.json` with timestamp and source metadata
  - Uses `json.dump` with `indent=2`

- `refresh_constituents(fallback_pool: List[str]) -> List[str]`
  - Orchestrator function called by the live engine
  - Try GitHub -> Wikipedia -> cached -> fallback_pool
  - Logs which source was used at INFO level
  - All fetches wrapped in try/except — never raises
  - Returns list of tickers (always succeeds)

### Modified: `omnicapital_live.py`

**`refresh_universe()` method** (~5 lines changed):

```python
def refresh_universe(self):
    current_year = self.get_et_now().year
    if self.universe_year != current_year:
        logger.info(f"Computing {current_year} universe...")
        # Dynamic: fetch current S&P 500 constituents
        from compass.sp500_universe import refresh_constituents
        broad_pool = refresh_constituents(fallback_pool=BROAD_POOL)
        self.current_universe = compute_annual_top40(
            broad_pool, self.config['TOP_N']
        )
        self.universe_year = current_year
        logger.info(f"Universe updated: {len(self.current_universe)} stocks from {len(broad_pool)} constituents")
```

- `BROAD_POOL` constant remains in the file as the ultimate fallback
- No other changes to `omnicapital_live.py`

### New file: `config/sp500_constituents.json`

Created automatically on first successful fetch. Schema:

```json
{
  "date": "2026-01-02",
  "source": "github_fja05680",
  "tickers": ["AAPL", "MSFT", "GOOGL", "..."],
  "count": 503
}
```

## Error Handling

4-layer fallback chain (never crashes):

| Layer | Source | Failure mode |
|-------|--------|-------------|
| 1 | fja05680 GitHub | Network error, repo down, format change |
| 2 | Wikipedia scrape | Network error, HTML structure change |
| 3 | Cached JSON file | File missing or corrupt JSON |
| 4 | Hardcoded BROAD_POOL | Never fails (compile-time constant) |

- Every fetch wrapped in `try/except Exception`
- Each failure logs a WARNING with the error
- The successful source logs at INFO level
- The engine always gets a valid ticker list

## Ticker Normalization

- Wikipedia uses `.` separator (e.g., `BRK.B`), yfinance uses `-` (e.g., `BRK-B`)
- `refresh_constituents()` normalizes all tickers: replace `.` with `-`
- Strip whitespace, uppercase all tickers

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
| More yfinance calls (503 vs 113) | Happens once per year, acceptable |
| New tickers have no price data | `compute_annual_top40` already skips stocks with < 20 days data |
| Ticker format differences | Normalization in `refresh_constituents()` |

## Scope

- ~120 lines new code in `compass/sp500_universe.py`
- ~5 lines changed in `omnicapital_live.py`
- 1 new JSON file auto-created in `config/`
- No new dependencies (uses pandas, urllib/requests already available)
