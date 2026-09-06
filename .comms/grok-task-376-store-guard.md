# TASK-376 — Never delete what you cannot replace

Cached path only. Live fetch still does not open the store.

## What landed

- `BarStore.replace_ticker`: count unique dates in the incoming frame; if
  `< min_bars` (default 10 = overlap) return 0 and **do not DELETE**. Empty
  frames and 3-bar Yahoo dribbles keep the stored history.
- Cached readjust: `n = replace_ticker(...)`; `n == 0` ->
  `report["failed_tickers"]` + `report["failed_reasons"][t] = "readjust_empty"`
  (not `readjusted`).
- Cached full fetch of missing names: tickers requested but absent from the
  provider frame go to `failed_tickers` with reason `fetch_empty`. Partial
  batches no longer look like a successful hole.

## Tests

- `test_replace_ticker_refuses_empty_or_short_frame`
- `test_readjust_empty_name_keeps_stored_rows`: AAA/BBB/CCC mismatch; CCC
  missing from the full-period batch -> CCC bars unchanged, AAA/BBB replaced
- `test_partial_full_fetch_marks_absent_names`

Existing drop-and-write test now uses 15 bars (>= overlap).
