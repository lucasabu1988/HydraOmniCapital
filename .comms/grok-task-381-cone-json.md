# TASK-381 — Tracked OOS cone JSON

Tuesday's journal no longer needs `audit_steps.pkl`. Live path otherwise
unchanged: `cone()` on an injected series still wins in tests.

## What landed

- `experiments/build_cone.py` — reads `audit_steps.pkl` `P_5050.net` when
  present (this machine); rebuilds from `sleeve_lab.mix(T20, ETF)` on the PIT
  panel if the pickle is missing.
- `data/oos_cone_5050.json` (29 KB, tracked): 1084 steps, 2005-02-11 →
  2026-08-24, horizons 1..52 with p5/p25/p50/p75/p95, plus `step_returns`.
- `core/journal.py`: `load_cone_table` / `cone_from_table` / `load_oos_step_returns`
  (JSON first, pickle fallback). `build_record` uses the table when no series
  is injected.
- `journal.py` `load_oos_step_returns` delegates to core (one-line).
- `evidence_review.py` fills `last_cone` from the JSON when journal records
  have none.

## p5 of the 50/50 mix (percent)

| steps | p5 | p50 | p95 |
|---|---|---|---|
| 4 | −3.82 | 0.85 | 4.08 |
| 13 | −5.80 | 2.39 | 7.47 |
| 26 | −6.54 | 4.62 | 11.76 |
| 52 | −5.27 | 7.94 | 18.74 |

## Tests

`test_json_and_pickle_same_cone`: fake pickle series vs `cone_from_table`, plus
JSON-first / pickle-fallback loaders.
