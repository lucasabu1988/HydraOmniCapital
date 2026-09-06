# TASK-355 — weekly journal (spec 10.1)

Pure builder `core/journal.py` (`state + ranking + summary + orders/fills -> record`).
I/O in `journal.py` (write `journal/<date>.json`, rebuild `JOURNAL.md`). Hook in
`daily.py` after the v9 CLI (`--note` appends observations, never overwrites).
`portfolio_v9.run` only **returns** the pieces (state, ranking, summary, preflight,
last_bars, prices); no journal logic there. Engine not edited.

`journal/` is already gitignored. Records are copied to `HYDRA_BACKUP_DIR/state_v9/<date>/`
with the state when the env is set.

The journal never changes a parameter.

## Record (schema `journal-1`)

- **seen**: regime score/label, recommended_count, stock exposure, basket vol63
  (from held names, if prices given), vol-target `min(1, 0.15/vol)`, ETF on/off +
  weights, sector-cap displacements (`sector_penalty_applied`), DEGRADED, coverage,
  last bars per source.
- **did**: orders, presumed vs confirmed fills, slippage bp vs modelled 10/5,
  not_filled / hold_no_price / write-offs / transfers / interest.
- **book**: total, per sleeve value/share/cash, week, last renewal.
- **expectation vs realisation**: step return vs prior journal total; percentile
  in the OOS 50/50 mix 5-bar nets (`audit_steps.pkl` `P_5050`; `task332_series.json`
  has no mix path); live cumulative vs 5/50/95 cone of overlapping n-step windows.
- **process**: preflight result (352), reconcile residual (351, None until then), errors.
- **observations**: `--note` and any previous notes for that date, appended.

Same-day rerun updates the rollup and **appends** notes. `python journal.py --dir …`
rebuilds the markdown from the json files.

A v9 `SystemExit` / exception still writes a thin record with `process.errors`
so a preflight hard fail is visible to TASK-356.

## Tests (`test_journal.py`)

9: seen/did/book fields, missing pieces, percentile/cone, step-return percentile,
note append, md rebuild, state not mutated, v9 return pieces, `daily.py --note`.
