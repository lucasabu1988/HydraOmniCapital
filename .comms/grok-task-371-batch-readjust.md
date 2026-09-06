# TASK-371 — Batch the bar-store readjust refetch

Live path not flipped (`USE_BAR_STORE` still False). Cached fetch only.

## What landed

- `fetch_prices_and_volume_cached`: collect overlap mismatches first, then one
  `provider.fetch(mismatches, start, end)` (the provider's own batching), then
  `replace_ticker` per name. `report["readjusted"]` is the same list as before.
- `store.runs` table: date, tickers_requested, tail, readjusted, seconds.
  `stats()["readjusted_last_run"]` is the last row's count.
- `store_cli.py --verify N`: N random stored tickers vs a fresh provider fetch;
  prints max relative/abs adj-close diff (evidence for TASK-370).

## Tests

`test_readjust_three_tickers_one_batched_fetch`: bump AAA/BBB/CCC → exactly one
extra full-period `fetch` of the three names together; `readjusted_last_run == 3`.
12 passed in `test_bar_store.py`.
