# Structural audit, September 2026 — final report

**Branch:** `structural-hardening-2026-09` (base `ee9d45b`, TASK-387 on `main`)
**Dates:** 2026-09-06 · **Phases:** 1–10 · **Reproductions:** 61 (R-100 … R-1004)
**Commits:** 12 · **Files:** 63 · **Suite:** 58 passed, 0 skipped · ruff, mypy and the
wheel smoke green.

Every defect below was reproduced against the code as it stood *before* the fix, and
the reproduction is a test that fails on the old behaviour. The per-defect evidence —
including the recorded before/after numbers — is
[`AUDIT_REPRODUCTIONS.md`](AUDIT_REPRODUCTIONS.md). This report is the summary and,
more importantly, the list of what is **not** claimed.

## The five that could have cost real money

1. **R-101 — correcting a confirmed fill doubled the position.** The reversal was
   gated on `status == "filled"`, so 10 shares corrected to 5 left **15** in the book
   and cash at 48.50 instead of 149.50. Lucas corrects fills by hand every week.
2. **R-210 — one unpriced held name cancelled the whole renewal.** `float(px.get(t,
   last_px) or 0.0)`: NaN is truthy, the tranche value became NaN, and every later
   comparison against NaN was False — no buys, no sells, no transfer. On the golden
   market five consecutive weekly renewals fell from 25 orders to 1, in silence.
3. **R-902 — an error deleted the evidence.** `append_error()` shared the in-place
   write with `save_record()`: a failed run replaced the successful record for that
   date, turning a book total of 123,456 into 0.0. R-901 is the same mechanism without
   the error — a rerun simply overwrote what the first run had recommended.
4. **R-401 — a provider outage lost the dividend permanently.** The window was
   `(last_run_date, today]` and `plan()` advanced the watermark whether or not the
   query succeeded, so an ex-date first reported after the watermark had passed it
   could never be credited.
5. **R-501 — `replace_ticker` destroyed history silently.** `min_bars=10` was no
   guard: a 12-bar frame passed it and cut **2800 stored bars down to 12**.

Two more deserve naming because they made the system *look* correct:
**R-805** (the differential driver compared orders and fills only, and printed
`IDENTICAL` while cash, tranches and fees disagreed) and **R-1004** (the suite printed
"ruff: All checks passed!" over an explicit module list while `ruff check .` found 5
errors outside it). A green light that does not look at the thing it certifies is
worse than no light.

## By phase

| phase | subject | ids | what changed |
|---|---|---|---|
| 1 | ledger and fills | R-100…R-110 | fills idempotent, corrections balanced, invariants checkable, `confirmed` fills projected like `filled` everywhere |
| 2 | numeric safety | R-201…R-210 | non-finite and non-positive prices rejected at the boundary, preflight records provider and capture time, carried prices marked |
| 3 | transactional commit | R-301…R-303 | the sheet is written before the state advances; backups are collision-free; every run has an id, a status and a recovery marker |
| 4 | dividends and actions | R-401…R-406 | overlapping query window, a coverage watermark that only advances on a verified window, retraction/versioning, conflicting and invalid `dps` reported |
| 5 | store and data quality | R-501…R-507 | non-destructive backfill, `verify` that fails on an empty store / an empty provider / no overlap, gap and duplicate metrics, `reconcile` with a real exit code |
| 6 | PIT and reproducibility | R-601…R-606 | snapshots immutable and content-addressed, identity travels with the data, a missing snapshot is an error, baselines bound to their inputs |
| 7 | universe and methodology | R-701…R-704 | the cap-rank proxies are no longer called "Russell", every universe carries source/method/bias, non-common securities excluded |
| 8 | engine and calendar | R-801…R-805 | the renewal schedule is on the calendar, not the download length; config, mix and sleeve registry persisted; every sleeve valued from the state; the diff driver compares the full state |
| 9 | CLI, journal, operation | R-901…R-905 | the journal is append-only and revisioned, records carry inputs/outputs/provenance, operational alerts exist |
| 10 | packaging and CI | R-1001…R-1004 | the wheel ships what it needs and every console script runs from an installed copy; dependencies coherent; seven CI gates |

## What this audit does **not** claim

1. **No scoring change.** Not one formula in `core/signals.py`, multiplier in
   `core/meta_layer.py` or gate threshold in `config.py` was touched (GROKBOARD rule 6).
   Nothing here changes what HYDRA recommends, except where the old behaviour was a
   defect — R-210 is the clearest case: the renewal now happens instead of silently
   not happening.
2. **No performance claim.** These are correctness fixes. The headline numbers are
   unchanged and still carry the caveats they had: the harness is S&P 500 only, and
   the 2004-26 OOS panel has real PIT membership but 53% price coverage in 2005.
3. **Two golden regenerations, both documented.** Phase 2 (R-210) moved numbers on
   purpose and the diff is the evidence; phase 8 moved **no** number — orders, fills,
   cash, ledger and dates byte-identical, only new persisted fields.
4. **Phase 9.6 (the scheduler) is not implemented here.** The pieces exist
   (`nyse_sessions_between()`, the market-calendar preflight, the timezone in the run
   manifest, `data/quality.py`); wiring them into the Windows scheduled task lives on
   `post-freeze-wiring` (TASK-364), which this branch does not merge.
5. **Branch protection is documented, not applied.** A ruleset is a repository
   setting; [`BRANCH_PROTECTION.md`](BRANCH_PROTECTION.md) is the exact configuration
   to paste in, and applying it needs admin on the repository.
6. **`BRK-A` / `BRK-B` / `BRK.B` is reported, not fixed.** The live universe holds one
   company twice under two spellings. Deduping changes the recommended list, so it
   needs a measurement and Lucas's approval — it is not a silent cleanup.
7. **The eight pre-existing PIT snapshots honestly report `verified=False`.** They
   predate content addressing. Backfilling a hash now would only certify that today's
   file matches today's file.

## Merge plan

The live path is **frozen on `main` until the first settle after the Tuesday
2026-09-08 close is verified**. Nothing here merges before that. Then, in order:

1. `post-freeze-wiring` — H-003 (`APPLY_SPLITS = True`), the scheduled task, the
   `USE_BAR_STORE` flip. Smallest, and the operational one.
2. `structural-hardening-2026-09` — this branch. It touches the ledger, the state, the
   journal and the engine, so it wants a quiet week and a re-run of the golden fixture
   and the OOS panel on `main` after the merge (expected identical; phase 8 proved it
   on the branch).
3. `n-sleeve-engine` — last, and only once the two above are settled. It is at OOS
   parity byte-for-byte with the two-sleeve engine; its value is optionality, not a
   number, so it has no reason to go first.

Rule for the comparisons: two headline numbers are only comparable with the **same
sector snapshot and the same PIT payload** (TASK-387). `main` today, snapshot
20260905: **7.1 / 0.75 / -17.8**.

## Open follow-ups

Queued as TASK-388…TASK-391 on GROKBOARD: the CI's first green run on a real pull
request (these seven jobs have never executed on GitHub), the duplicate-share-class
measurement, the next tier of typed modules with a raised coverage floor, and the
local pre-commit half of the gates.
