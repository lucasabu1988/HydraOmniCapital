# TASK-417 — day-one paper sizing backfill

`state_paper/` was created 2026-09-10 16:55, before #71, so neither the sheet
payload nor the journal carried `did.sizing`. Hand figure from
`core.sizing.sizing_summary` on `instructions_20260910.json`:

| | |
|---|---|
| n_buys | 26 |
| target | 13,378.59 |
| achievable | 11,100.77 |
| loss | 2,277.82 (17.03%) |
| zero-share | LITE, SNDK |

## What landed

`tools/backfill_sizing.py` reads an `instructions_<date>.json`, recomputes
`sizing_summary`, and writes/repairs `journal_paper/<date>.json` at `did.sizing`.
Idempotent: a second run leaves the same bytes. Existing fields are preserved.
Never touches `state/` or `portfolio_v9.json`.

Ran against the live paper sheet: first call wrote
`journal_paper/2026-09-10.json`, second call printed `unchanged` with the same
numbers. That directory is gitignored (a paper book must not be committed).

Tests: fixture sheet, idempotence, repair-without-dropping-fields, and the
2026-09-10 assertion when the local paper book is present.
