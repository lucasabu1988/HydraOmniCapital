# TASK-362 — Point-in-time universe and sector snapshots

Live path not hooked (`daily.py` after fetch waits for the freeze). Snapshots
live in `data_cache/pit/` (already gitignored via `data_cache/`).

## What landed

- `data/pit.py` — `write_universe_snapshot` / `write_sectors_snapshot` (pointer
  `same_as_YYYYMMDD` when content is unchanged); `membership(name, date)`,
  `changes(name, d1, d2)`, `history(name)` (skips pointer rows).
- `snapshot_universe.py --seed` reads local ticker CSVs (no network). The files
  are in `output/*_tickers.csv`, not `data_cache/` (the task named the latter;
  both locations are checked). Composes russell3000 and `all` as unions.
  Sectors from `data_cache/sector_cache.json`. `--universe` still calls
  `get_universe` (network) and is not used in tests.

## Seed run (this machine, 2026-09-05 mtimes)

```
sp500 503, nasdaq100 102, dow30 30, russell1000 1000, russell2000 2000,
russell3000 3000, all 3002, sectors 2897 mapped / 0 unknown
```

## Tests (`test_pit.py`, no network)

4 passed: pointer when the ticker set is unchanged; membership / changes /
history; sectors pointer; seed from a fake tree; CLI `--seed` on an empty dir.

## Left for the hook-up

- One call in `daily.py` after the fetch.
- `copy_state_off_disk` includes `data_cache/pit/`.
