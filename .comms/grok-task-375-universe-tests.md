# TASK-375 — Universe fetch chain under test

Live path behaviour unchanged. `data/universe.py` gained `universe_report()`
(additive) and a `logger.warning` containing the word `fallback` when the
hardcoded S&P list is used — the warning preflight will look for.

## What landed

- `test_fixtures/universe/` — HTML/CSV fixtures, each < 18 KB (401-row S&P
  tables, 91-row Nasdaq, 30-row Dow, 801-row Russell, plus garbage).
- `test_universe_fetchers.py` — `requests.get` patched, no network.
  - each of the six S&P fetchers parses its fixture into 401 tickers
  - garbage from Slickcharts falls through to Barchart
  - all sources fail → `get_fallback_sp500_tickers()` **and** a WARNING
    containing `fallback` (caplog)
  - 7-day CSV cache is honoured; an 8-day-old file is refreshed
  - `get_universe("all")` is the union of the five getters
  - `universe_report()` returns
    `{universe, source_used, count, from_cache, fallback}`
- Coverage on `data/universe.py`: **66%** (was ~13%). Target was >= 60%.

## `universe_report`

Call it after a resolve. `fallback=True` / `source_used="fallback"` is the
Tuesday-run WARN for preflight (hook after the freeze). `from_cache` is the
7-day CSV mtime. `"all"` reports `source_used="union"`.

## Tests

15 passed in `test_universe_fetchers.py`. Existing `test_universe_robustness.py`
untouched.
