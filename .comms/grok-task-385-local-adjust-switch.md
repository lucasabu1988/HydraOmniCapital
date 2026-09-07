# TASK-385 — Bar store: derive the adjusted close locally, with the guards first (done by Claude, 2026-09-06)

On main, commit `3cb9ef6` (freeze-safe: store, provider, cached fetch, CLI; nothing on the live path).
Default is still `adjust="yahoo"`; the switch to `"local"` is Claude's after a week of clean checks.

## What landed

1. **Dividend source is bulk, not per ticker.** `yf.download(..., actions=True)` returns `Dividends` and
   `Stock Splits` in the same request as the closes, so the one-pass provider (TASK-378) now carries them
   at no extra round trip. The store keeps them in an `actions` table plus `actions_cov` (the date span
   each ticker was *asked* for — "asked and none" is coverage, an unknown name is not). This replaces the
   TASK-377 idea of `fetch_dividends` per ticker (3000 requests a day, and the MKC failure mode).
2. **Guards.** `data/dividends.py`: `report["no_dividends"]` (fetched, none, stamped) is distinct from
   `report["failed_tickers"]` (no stamp); `coverage(tickers)` -> fresh / stale / missing.
   `store_cli.py --verify N`: fresh Yahoo `Adj Close` vs the stored one **and** vs the locally derived
   series; exit 1 above `--verify-tol` (1e-5) with the names printed.
3. **Local path.** `fetch_prices_and_volume_cached(adjust="local")`: `close_raw x dividend factors`
   (`data/adjust.py`) for names whose actions coverage spans `[start, last bar]`; Yahoo `Adj Close`
   fallback for the rest, listed in `report["adjust_fallback"]`; the tail overlap is compared on the
   **raw** close, which only moves on a split, so the daily readjust of every dividend payer disappears.
   `store_cli.py --backfill-actions --period 20y` fills the table (chunks of 300 names).

## Evidence (2026-09-06)

Backfill: 3011 tickers, 2006-09-06 -> 2026-09-04, **102,490 dividend/split events, coverage for all
3011**, store 1.64 GB (from 1.22), ~25 min.

`store_cli.py --verify 50` (fresh Yahoo download of 50 random stored names over the full 20 years):
**verify ok, exit 0** — locally derived vs fresh `Adj Close` max relative diff **8.2e-7** (TD, 5031 bars),
most names 0 to 1e-6; stored-vs-fresh in the same range (Yahoo's own rounding). No name near the 1e-5
threshold.

## Tests

`test_bar_store.py` +3: provider extracts actions and the store records coverage ("asked, none" counts);
local path == yahoo path within 1e-6 on synthetic data with two dividends and no readjust after them,
uncovered name falls back and is reported; `--verify` fails on an injected 1e-3 error.
`test_dividends.py` +1: failed vs no-dividends vs fresh/missing coverage. Suite 46/0/0.

## Switch plan

Run `python store_cli.py --verify 50` each day for a week (the unattended ritual can do it once TASK-364
is merged). Zero failures -> `adjust="local"` becomes the default of the cached path in one line, and the
daily tail stops refetching dividend payers. Splits: Yahoo's raw close is already split-adjusted, so no
split factor is applied to Yahoo data; a raw provider would use `store.splits`.
