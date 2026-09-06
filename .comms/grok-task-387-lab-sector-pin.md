# TASK-387 — Pin the lab's inputs so backtest headlines are reproducible (done by Claude, 2026-09-06)

On main, freeze-safe (lab, `data/pit.py`, a new differential tool, tests).

## What went wrong, exactly

The TASK-386 parity runs on the two branches gave 6.96 / 0.73 / -17.8 while TASK-350/369 had recorded
7.10 / 0.75 / -17.8 for the same engine. First hypothesis (sector cache drift) was wrong. The differential
`experiments/engine_diff.py` — two engine versions loaded in one process, same panel, same ranking, stop at
the first differing order — showed main's engine, the wiring branch's engine and the N-sleeve engine
**identical for 300 OOS steps (2005-2011)**. The runs differed because they ran in git worktrees, and
`data_cache/` is gitignored: the worktrees had **no `sector_cache.json`** (every ticker fell to
`SECTOR_BUCKETS` / "Other", so the sector cap hardly bound) and fetched a **fresh `sp500_pit.json`** from
Wikipedia that is not byte-identical to the cached payload (membership). Same code, degraded inputs, and
nothing in the run said so.

## What landed

- `data/pit.py`: `sectors_at(date=None)` -> (ticker -> sector, snapshot date) from the latest PIT sectors
  snapshot on/before the date, pointers resolved.
- `experiments/redesign_lab.py`: `resolve_sector_map(columns, sectors="pit"|"live"|dict, sectors_date)`;
  `load_panel(oos, sectors="pit", sectors_date=None)` uses the **PIT snapshot by default**, never the live
  cache for missing names (`SECTOR_BUCKETS`, then "Other"), records `P.SECTOR_SOURCE = {source,
  snapshot_date, n_mapped, n_fallback}` and `P.PIT_META = {updated, cache_version, source_wiki,
  source_github}` of the membership payload, prints both, and **warns loudly** when the map is not the pinned
  snapshot or is mostly fallback (the exact failure above).
- `experiments/engine_backtest.py`: `--sectors {pit,live}` (default pit), `--sectors-date YYYYMMDD`; the run
  JSON carries `sector_snapshot` and `pit_payload`, so a headline can be tied to its inputs.
- `experiments/engine_diff.py`: the differential driver (kept; it is the fastest way to answer "did the
  engine change or did the inputs change").
- Tests (`test_lab_sector_pin.py`, 5): `sectors_at` picks latest on/before and resolves pointers; the pinned
  map is deterministic and dated, unknown names never touch the live cache; a different snapshot date gives
  a different, labelled map; `live` is labelled and uses the lookup; a missing snapshot falls back with the
  `live-fallback` label.

## Numbers

| run (same engine code) | sector source | PIT payload | headline |
|---|---|---|---|
| main, 2026-09-06 00:50 (TASK-369) | live cache (2897 names) | cached `sp500_pit.json` | 7.10 / 0.75 / -17.8 |
| main, 2026-09-06 afternoon, `--sectors live` | live cache | cached | 7.10 / 0.75 / -17.8 |
| worktree branches (384/386) | **no cache -> buckets/Other** | **fresh Wikipedia fetch** | 6.96 / 0.73 / -17.8 |
| main, `--sectors pit` (pinned) | PIT snapshot 20260905 (mapped 669, fallback 540) | cached, updated 2026-09-05T15:25:25.702755 | **7.1 / 0.75 / -17.8** |

## Rule from now on

A lab headline is only comparable with another when both runs report the same `sector_snapshot` and
`pit_payload.updated`. Worktrees must junction `data_cache/` (as the lab caches already are) or run with
`--sectors pit` after `snapshot_universe.py --seed`.
