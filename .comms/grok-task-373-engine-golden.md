# TASK-373 — Engine characterisation golden

Engine not edited. 30 weekly steps on a seeded synthetic book; the fixture is
the characterisation, not a new strategy.

## What landed

- `test_engine_golden.py` — seed 373, 60 stocks, 10 ETFs, ^IRX 4%.
  Ranking rotates each week. Equity ETFs stay in an uptrend; the five
  rate/commodity names crash after week 15 so the T-bill hurdle turns them off.
  `S00` stops printing at week 12 → stale → write-off. `S01` has one NaN settle
  bar → `not_filled`. `state_check.check` after every `plan()` (zero ERROR).
- `test_fixtures/engine_golden_v9.json` — orders, fills, transfers, interest,
  write-offs, final state. Compare with `atol=1e-9`.
- `HYDRA_REGEN_GOLDEN=1` rewrites the fixture and prints a diff summary. Missing
  fixture fails the test.

## Fixture counts

30 weeks, 4 write-offs, 1 not_filled, 42 transfers, 58 interest records.

## Tests

`pytest test_engine_golden.py` 1 passed (~1.4 s). Full suite after this note.
