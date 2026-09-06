# TASK-361 — Local bar store (SQLite) + provider interface

Live path not edited (`portfolio_v9.py`, `daily.py`, `preflight.py`, `core/*`).
`config.py` gained one new constant; no existing value changed.

## What landed

- `data/store.py` — SQLite at `data_cache/bars.sqlite` (gitignored).
  Tables: `bars(ticker, date, close_adj, close_raw, volume, source, fetched_at)`
  PK `(ticker, date)`; `meta(ticker, first, last, updated_at)`.
  API: `upsert`, `closes(..., adjusted=True)`, `volumes`, `coverage`, `last_dates`,
  plus `replace_ticker` (readjust), `overlap_start`, `stats`, `vacuum`.
- `data/providers/base.py` — `BarProvider` protocol: `fetch(tickers, start, end)`
  → long frame `(ticker, date, close_adj, close_raw, volume)`. Dates inclusive.
- `data/providers/yfinance_provider.py` — two downloads per batch
  (`auto_adjust=True` / `False`), same batch size (75) and retry-once as
  `_fetch_closes`. Volume from the unadjusted download. Uses `_yf_download` +
  `_close_frame_from_yf` (sibling `_volume_frame_from_yf` because the existing
  helper only returns Close).
- `data/fetch.py` (additive):
  - `_yf_download` / `_volume_frame_from_yf` (helpers).
  - `_download_close_batch` still returns Close; optional `start`/`end` added,
    `period=` path unchanged (v9 fetch tests still pass).
  - `fetch_prices_and_volume_cached(tickers, period, report, provider=, store=, asof=)`:
    missing tickers → full period; stored tickers → `[last date - 10 bars, asof]`;
    overlap adj close relative diff > 1e-6 → refetch full period, `replace_ticker`,
    `report["readjusted"]`. Returns wide frames from the store.
  - `fetch_prices_and_volume` is still the live caller. It does not open the store.
- `config.USE_BAR_STORE = False` — production keeps downloading. Claude flips
  this after comparing a cached run against a direct run on the same day.
- `store_cli.py --backfill --period 20y --universe all`, `--stats`, `--vacuum`
  (`--db` for tests). Backfill calls the cached fetch regardless of the flag
  so the file can be populated before the flip.
- No new third-party dependency (`sqlite3` stdlib).

## Tests (`test_bar_store.py`, fake provider, no network)

11 passed: upsert round-trip adj/raw/volume; coverage + last_dates + overlap
start of 10 bars; replace_ticker; `USE_BAR_STORE is False`; cached frames ==
direct pivot of the fake provider; second call downloads only the tail
(start = 10th last bar); readjust of one overlap bar refetches that ticker's
full period and writes the new adj close; live `fetch_prices_and_volume` does
not construct `BarStore`; YFinanceProvider issues exactly two downloads
(adj/raw) with volume from raw; CLI `--stats/--vacuum` and `--backfill`
(universe + cached fetch patched).

`test_fetch_v9.py` still 7 passed (period=1y default, 2y forward, ETF/T-bill).

Suite: **35 passed, 2 skipped, exit 0**.

## Left for the hook-up (after "first settle verified")

- Flip `USE_BAR_STORE` (Claude, after a same-day cached vs direct compare).
- One-line dispatch in `fetch_prices_and_volume` (or the v9 caller) when the
  flag is True. Not done now: freeze + "nothing in production reads the store".
- `store_cli.py --backfill --period 20y --universe all` to seed `bars.sqlite`
  before the flip. Not run here (network).
