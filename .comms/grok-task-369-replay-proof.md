# TASK-369 — Prove ledger replay on real history

Engine not edited. `--check` verifies a JSON round-trip **copy**; it does not
replace the live engine state.

## What landed

- `experiments/engine_backtest.py --check`: after every `settle()` and `plan()`,
  `json.dumps/loads` the state and run `state_check.check`. First ERROR dumps
  `experiments/_lab_scratch/replay_fail_<date>.json` and exits 1.
- Defect found and fixed in `core/state_check.py`: after `settle()`, fills have
  `exec_date = t+1` while `last_run_date` is still the plan date `t`. The old
  rule `ledger <= last_run_date` was a false ERROR on a valid in-between book.
  New rule: flag `ledger_future` only when `pending` is also non-empty (a plan
  just ran). Regression: `test_post_settle_ledger_may_be_after_last_run_date`.

Event order (unchanged, confirmed against the engine): sell → transfer → buy
on a settle date; interest (kind 2) before write-off (kind 3) on the same day;
buy `cash -= dollars + cost`, sell `+= dollars - cost`; interest dollars split
across a sleeve's tranches proportional to cash (= `cash * (factor - 1)`).

## Results (zero ERROR, zero WARN)

| panel | plans | check calls | extra wall | ledger | transfers | interest | write-offs | not_filled |
|---|---|---|---|---|---|---|---|---|
| in-sample 2020-26 | 279 | 558 | 61.5 s | 8984 | 550 | 556 | 0 | 0 |
| OOS PIT 2004-26 | 1084 | 2168 | 969.9 s | 34154 | 2150 | 2166 | 2 (ESRX) | 1 (TWX) |

OOS plumbing matches TASK-350: 7.10 / 0.75 / −17.8, 2150 transfer legs.

## Tests

`test_state_check.py` + engine suite: 20 passed. Full suite run after this note.
