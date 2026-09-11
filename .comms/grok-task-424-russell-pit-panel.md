# TASK-424 — Russell PIT panel written, coverage.json as it came out

**From:** Grok
**Date:** 2026-09-11
**Strict:** yes (`--no-strict` not used)
**Source:** EODHD All World, membership from the free record
**Out:** `hydra_screener_local/experiments/_sweep_cache_russell/` (gitignored)

The first serial CLI sat 8h on one HTTPS connection at ~32s/name (A: 5456 bars);
6547 × 32s is ~58h, not the 2–3h in the task. Restarted with a gitignored harness
(`experiments/_lab_scratch/task424_run.py`) that prefetches with 16 workers then
calls the same `build()`: 6346 cached, 201 empty/fail, 27 min total. No panel
code changed. No valla moved.

Honest window is **2010-2026**: the membership record starts June 2010.
`first` below is 2005-01-03 because prices were requested from `PANEL_START`;
`members_first_day` is 0 for that reason (no members on the first price bar).

## coverage.json (verbatim)

```json
{
  "member_cells": 12245227,
  "priced_member_cells": 11098507,
  "cell_coverage": 0.9064,
  "names": 6050,
  "delisted_names": 2822,
  "delisted_share": 0.4664,
  "delisted_with_prices": 2822,
  "first": "2005-01-03",
  "last": "2026-09-10",
  "members_first_day": 0,
  "members_last_day": 3362
}
```

Guards (strict, none moved): cell coverage 90.64% ≥ 80%; delisted share 46.64% ≥ 20%;
delisted_with_prices 2822 / 2822; identity_problems empty after TASK-423's membership-tail
cut. Cache files: `close.pkl`, `close_raw.pkl`, `open.pkl`, `volume.pkl`,
`membership.pkl`, `coverage.json`.
