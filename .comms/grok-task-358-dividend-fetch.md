# TASK-358 — dividend fetch: only the tickers that matter, once a day

`tickers_from_state` now returns:

- `V9["etf_universe"]`
- names with units in the book now
- names with a ledger fill whose `exec_date` is after `last_run_date`

A name sold months ago is not re-downloaded every morning.

`fetch_dividends` skips Yahoo when `updated_by_ticker[t]` is today's UTC date and
the cache already has that ticker; still returns the cached rows. Failures still
fall back to cache.

Tests: ticker set on a synthetic state; second call the same day does not
construct `yf.Ticker`.
