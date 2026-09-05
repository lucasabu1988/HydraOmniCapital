# Status Board

Each agent updates ONLY their own section. Read the other's section before starting work to avoid conflicts.

## Claude
**Updated:** 2026-09-06 00:40
**Working on:** TASK-320 done — reverted 62d201c and rebuilt sector control as a hard cap at
selection on real GICS sectors (MAX_PER_SECTOR 8 -> 5). Cap now binds in 100% of cycles; scoring
untouched; sector resolution moved upstream so scoring does no network I/O. Suite 6/7. Idle.
**Files I'm touching:** none (released config.py, core/filters.py, core/signals.py, screener.py,
data/sectors.py, test_spec_compliance.py, HYDRA_ALGORITHM_SPEC.md, experiments/)
**Blockers:** CI workflow push needs `gh auth refresh -s workflow` from Lucas

## Grok
**Updated:** 2026-09-05
**Working on:** idle — Claude landed TASK-320 (`06d3a58`) while I was waiting. Not claiming 321 unless the board still wants it after his commit.
**Files I'm touching:** none
**Blockers:** none. TASK-319 still Lucas.
