# Audit reproduction registry

Every structural fix on branch `structural-hardening-2026-09` is anchored to a
reproduction here. A reproduction is a permanent test that **failed on
`main @ ee9d45b7fc8ecf487333ab72af3d7e24e4bd8f0b`** and passes after the fix.

## How the before/after evidence is produced

The repository is green at every commit (AGENTS.md: the suite must exit 0 before a
task is marked done), so a reproduction is not committed in a failing state. The
"fails before" half is proved against the base commit in a throwaway worktree:

```bash
git worktree add --detach /tmp/base_wt ee9d45b
cp hydra_screener_local/core/ledger.py   /tmp/base_wt/hydra_screener_local/core/
cp hydra_screener_local/core/numbers.py  /tmp/base_wt/hydra_screener_local/core/
cp hydra_screener_local/test_ledger_*.py /tmp/base_wt/hydra_screener_local/
cd /tmp/base_wt/hydra_screener_local && python -m pytest test_ledger_*.py -q
# 36 failed, 28 passed      <- the reproductions
cd -                        && python -m pytest test_ledger_*.py -q
# 65 passed                 <- after the fix
```

`core/ledger.py` and `core/numbers.py` are copied in because they are *new modules*
the tests import, not the fix itself; the code under test (`core/fills.py`,
`dashboard_v9.py`, `core/journal.py`, ...) stays at the base commit.

## A note on the three audit JSON files

The brief names `ops_reproductions.json`, `repro_data_results.json` and
`repro_research.json` as the source of the reproduction set. **Those three files do
not exist in this repository.** Searched at `ee9d45b`, on `post-freeze-wiring` and
`n-sleeve-engine`, and across the full history of every ref:

```bash
git log --all --name-only | grep -iE 'ops_repro|repro_data|repro_research'   # no hits
```

The only near-matches are two archived design docs
(`archive/root-legacy-2026-09/docs/superpowers/{plans,specs}/2026-04-06-hydra-reproducible-backtest*.md`),
which are unrelated. The reproduction set below was therefore derived from the phase
specification in the brief, which names each defect precisely enough to reproduce.
If the three JSON files exist outside the repo, drop them in and the ids can be
cross-referenced.

## Registry

| id | phase | defect | reproduction | fixed in |
|---|---|---|---|---|
| R-100 | 1.3 | a repeated confirmation re-applied the fill | `test_ledger_integrity.py::test_r100_duplicate_confirmation_is_a_noop` | `fix: make fills idempotent and corrections balanced` |
| R-101 | 1.4 | **correcting an already-confirmed fill doubled the position** — the reversal was gated on `status == "filled"`, so 10 shares corrected to 5 left **15** in the book and cash 48.50 instead of 149.50 | `test_ledger_integrity.py::test_r101_*` (4 tests) | same |
| R-102 | 1.5 | a NaN price was accepted and set tranche cash to **NaN** | `test_ledger_integrity.py::test_r102_r106_*[NaN price]` | same |
| R-103 | 1.5 | negative units on a buy **created cash** (+50.00 out of nothing) | `...[negative units]` | same |
| R-104 | 1.5 | a price of 0.0 booked free shares | `...[zero price]` | same |
| R-105 | 1.5 | an infinite price set cash to **-inf** | `...[infinite price]` | same |
| R-106 | 1.5 | an unknown `side` appended a ledger row that moved nothing — silent corruption | `...[unknown side]` | same |
| R-107 | 1.2 | two fills sharing a natural key: the second replaced the first in the ledger while both moved the book, so the ledger no longer explained the units | `test_ledger_integrity.py::test_r107_*` | same |
| R-108 | 1.8 | **`confirmed` fills vanished from the dashboard** — `_lots_from_ledger` skipped `status != "filled"`, so cost basis, realised P&L and fees all reverted to zero after a confirmation | `test_ledger_projection.py::test_r108_*` | `fix: unify confirmed ledger projection and dashboard` |
| R-109 | 1.7 | the journal counted `("filled", "confirmed")` and dropped `confirmed_unplanned`, so slippage on an off-sheet fill was invisible | `test_ledger_projection.py::test_r109_*` | same |
| R-110 | 1.6 | no invariant check existed: a poisoned state could be written | `test_ledger_integrity.py::test_check_invariants_catches_a_poisoned_state` | `fix: make fills idempotent and corrections balanced` |
