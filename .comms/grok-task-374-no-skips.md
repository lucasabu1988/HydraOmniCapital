# TASK-374 — Retire the permanent skip

No production history path was changed. `HYDRA_HISTORY_DIR` is read only inside
`test_hybrid_integration.py`.

## What landed

- `test_fixtures/history_min/` — two schema-v2 runs (20260901, 20260908), five
  tickers each, some `recommended`. Matches `core/history.py` v2 keys.
- `test_hybrid_integration.py`: live `history/` if present; else
  `HYDRA_HISTORY_DIR`; else the fixture (and the test sets the env to that
  directory). Missing both is a FAIL, not a skip.
- Pine summary skip: `test_fixtures/pine_min/hydra_last_summary.json` is 989
  bytes (< 50 KB), produced by `build_rich_summary` on the second fixture run.
  `validate_pine_contract.py` uses it when `pine/hydra_last_summary.json` and
  live history are absent.

`test_generate_pine_watchlist.py` still prints a sub-check `[SKIP]` when the
real 20260601 golden is missing, but the file prints `ALL FEEDER TESTS PASSED`
(the zero-recommended and string tests always run), so the runner does not
count it as a skip.

## Result

`run_all_tests.py` reports **0 skipped**.
