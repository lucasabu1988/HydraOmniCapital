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
| R-201 | 2.3 | a close of exactly `0.0` raised `ZeroDivisionError` inside `plan()`, taking the whole daily run down | `test_numeric_safety.py::test_r201_*` | `fix: reject non-finite execution prices and invalid units` |
| R-202 | 2.3 | **a negative close produced a real buy order** — `$575.86 at est_units=-46.07, est_price=-12.50` — onto the sheet Lucas executes by hand | `test_numeric_safety.py::test_r202_*` | same |
| R-203 | 2.4 | `state_check` reported an infinite cash balance only as a replay mismatch, never as an impossible number | `test_numeric_safety.py::test_r203_*` | same |
| R-204 | 2.4 | `_f` coerced NaN to 0.0 for the replay arithmetic, so a NaN cash whose replay also landed at zero passed the check clean | `test_numeric_safety.py::test_r204_*` | same |
| R-205 | 2.4/8.3 | a mix of `{"stocks": -0.5, "etf": 1.5}` produced only a cascade of `replay_cash` findings and never said the weights were impossible | `test_numeric_safety.py::test_r205_*` | same |
| R-206 | 2.5/2.8 | a **negative ETF close passed preflight clean** (`pd.notna(-3.0)` is True), so the sleeve would have been sized off it | `test_numeric_safety.py::test_r206_*` | same |
| R-207 | 2.5 | a frame whose last bar was a month **after** the as-of instant passed preflight clean | `test_numeric_safety.py::test_r207_*` | same |
| R-208 | 2.5 | preflight recorded neither the provider nor the capture timestamp, so a recommendation carried a date and no provenance | `test_numeric_safety.py::test_r208_*` | same |
| R-209 | 2.6/2.7 | `data.fetch` forward-fills up to 3 bars and nothing downstream could tell a carried price from a printed one | `test_numeric_safety.py::test_r209_*` | same |
| R-210 | 2.3/rule 11 | **one unpriced held name silently cancelled the whole renewal.** `float(px.get(t, last_px) or 0.0)`: NaN is truthy, so the tranche value became NaN and every later comparison against NaN was False — no buys, no sells, no transfer. On the golden market five consecutive weekly renewals fell from 25 orders to 1 | `test_numeric_safety.py::test_r210_*` | same |

## Golden fixture regeneration (R-210)

`test_fixtures/engine_golden_v9.json` was regenerated in the R-210 commit. It is a
*characterisation* golden, so the diff is the evidence of the behaviour change:

```
weeks where the order count changed: 9
  week 12 2021-03-25: before  1 orders -> after 25
  week 13 2021-04-01: before  1 orders -> after 25
  week 14 2021-04-08: before  1 orders -> after 25
  week 15 2021-04-15: before  1 orders -> after 25
  week 16 2021-04-22: before  1 orders -> after 25
  week 17 2021-04-29: before 27 orders -> after 24
  week 18 2021-05-06: before 27 orders -> after 24
  week 19 2021-05-13: before 27 orders -> after 24
  week 20 2021-05-20: before 27 orders -> after 24
total orders 572 -> 680;  final cash 157.0635 -> 157.7849
```

Weeks 12-16 are the bug: the ghost name `S00` goes unpriced, the tranche value turns
NaN and the renewal collapses to the single `hold_no_price` note. Weeks 17-20 differ
because the book is no longer three renewals behind. **No scoring input changed** —
`stock_targets`, `etf_targets`, the ranking and every parameter in `config.py` are
untouched; only the refusal to size an order from an invalid price and the refusal to
let one NaN silently void a renewal.

The pre-regeneration fixture is recoverable with
`git show <parent>:hydra_screener_local/test_fixtures/engine_golden_v9.json`.

## Phase 3 — transactional commit

| id | phase | defect | reproduction | fixed in |
|---|---|---|---|---|
| R-301 | 3.1/3.3 | **a failure writing the instruction sheet still advanced the state.** `save_state()` ran before `write_instructions()`, so a sheet failure left fills settled, dividends credited and `last_run_date` stamped, with nothing for Lucas to execute | `test_commit_transaction.py::test_r301_*` | `fix: make portfolio state and instructions transactional` |
| R-302 | 3.5/3.6 | **backups were silently overwritten.** `%Y%m%d_%H%M%S` names collide within a second: three saves left one backup file and the first two state versions were gone | `test_commit_transaction.py::test_r302_*` | same |
| R-303 | 3.4/9.7 | no run id, no operational status and no recovery marker existed, so an interruption was indistinguishable from a clean run | `test_commit_transaction.py::test_r303_*`, `test_recovery_*` | same |

Recorded at the base commit:

```
R-301  a failure writing the instruction sheet still advances the state
  run 1 ok: last_run_date=2026-02-25 pending=13
  run 2 raised: OSError: disk full while writing the instruction sheet
  state CHANGED despite no sheet: True
R-302  two saves inside the same second overwrite the backup silently
  three saves -> 1 backup file(s): ['20260906_113403.json']
    20260906_113403.json: {"v": 2}          <- v1 is gone
R-303  files in state dir: instructions_*.json, instructions_*.md, portfolio_v9.json
       (no run journal, no status, no recovery marker)
```
