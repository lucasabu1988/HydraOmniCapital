# TASK-379 — Sector negative cache and empty overrides

Ranking is unchanged: the overrides file ships empty. Filling FISV/GOOGM/GOOGN/HOS/LION/NIQ
is Claude's after the freeze.

## What landed

- Failed `yf.Ticker.info` lookups are stored in `data_cache/sector_cache.json` as
  `{"sector": null, "failed_at": iso}` and are not retried for 7 days. String
  cache entries (`"AAPL": "Technology"`) still work.
- `data/sector_overrides.json` is tracked, empty except a `_comment` key.
  Lookup order: **override -> positive cache -> SECTOR_BUCKETS -> Other**.
- `sector_report()` returns `{cached, fetched, negative, override, unknown}`
  from the last `resolve_sectors` call.

## Tests (`test_sectors_cache.py`)

- a failure is not retried within 7 days
- an 8-day-old negative is retried and can succeed
- override wins over a cached sector
- empty overrides: cached names resolve as before; unknown -> Other

`test_warm_sectors.py` still green.
