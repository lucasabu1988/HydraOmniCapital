# TASK-318 — Sector control redesign (design note)

**From:** Grok
**Date:** 2026-09-05
**Status:** implementing after this note (Lucas ordered 314-318 done). Claude: review at leisure.

## Defect (already measured)

`SECTOR_BUCKETS` maps ~80 names. Production ~3000. Unmapped → `"Other"`. `MAX_PER_SECTOR=8` then 15%-penalises everything ranked >8 **inside its bucket**. On S&P 500 that is 87% of names. Real GICS sectors alone still penalise 82%. The cap is applied to the **scored universe**, not to the recommended pool, so "9th of 45 in Technology" is treated as over-concentration.

## What we will not do

Fix only the sector map. That is the trap.

## Two commits

### 1. Real sector cache (`data/sectors.py`)

- Daily JSON cache under `data_cache/sector_cache.json` (same fallback rules as TASK-201: stale cache beats nothing, log on fallback, never crash a run).
- Source: yfinance `Ticker.info["sector"]` for tickers missing from cache or cache older than 7 days.
- Lookup order: cache → `SECTOR_BUCKETS` → `"Other"`.
- Refresh is called from `apply_sector_concentration_control` (declared file). A fetch failure leaves the previous cache in place.

### 2. Cap the candidate pool + calibrate MAX_PER_SECTOR=3

- Compute `dynamic_count` **before** sector control.
- Apply sector rank + 15% penalty **only** to the current top `dynamic_count` names, then re-sort the full frame.
- Names outside that pool keep their composite_score; they can enter the list only if a penalised name falls out of the top N after re-sort.
- `MAX_PER_SECTOR`: **3**. Once the pool is 14–28 names, 8 is almost never binding. v8.4 / `CLAUDE.md` already documents "max 3 per sector" as the live-engine limit. With ~11 GICS sectors a cap of 3 on a 14–28 list still allows a theme to lead (up to ~3/14 ≈ 21%) without recreating the 72% Semis+Software episode.

Soft penalty is kept (not a hard exclude) so a fourth strong name can still survive if its raw score is high enough after 15% haircut.

## Measurement before close

- Harness variant `sector pool cap max=3 + GICS` in `experiments/backtest_variant_sweep.py` (`sector_on_pool=True`, `max_per_sector=3`, `use_real_sectors=True`).
- Baseline stays current behaviour (buckets + full-universe cap=8).
- One-day recommended-set diff from the sweep cache (last eligible date).

---
