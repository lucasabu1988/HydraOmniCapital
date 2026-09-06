# TASK-383 — Tuesday rehearsal on a copy of the live state (done by Claude, 2026-09-06)

Grok ran out of credits before claiming this; Claude finished it. `state/` and `journal/` were never
written: the live `portfolio_v9.json` is byte-identical before and after both runs, `journal/` does not
exist. Reusable script: `experiments/rehearsal.py` (two modes), reports:
`.comms/journal-rehearsal-20260904-today.md` and `.comms/journal-rehearsal-20260908-simulate-t1.md`.

## Mode `today` (real fetch, Saturday 2026-09-06, last session 2026-09-04)

- Preflight: all OK except `HYDRA_BACKUP_DIR WARN unset` (Lucas's item).
- `pending orders from 2026-09-04 still waiting for t+1` -> plan skipped, sheet says "No trades",
  interest/dividends 0/0, copy's `pending` still 30, ledger 0. `verify_state`: clean.
- `sector_report()` all zeros (no ranking on the waiting path), `universe_report()`:
  `all`, union, 3002 names, fallback False.
- Journal record: 22 None fields, all explained by "no ranking, no fills, week 0". The cone is None
  because the journal derives the horizon from `len(live_curve) - 1`: the first record ever has no
  prior curve, so the cone appears from the second Tuesday onward. By design.

## Mode `simulate-t1` (real fetch + one synthetic bar dated 2026-09-08 at Friday's close)

Fake prices, real plumbing. This is the exact code path of the execution day:

```
preflight OK (7 rows; only HYDRA_BACKUP_DIR WARN)
[v9] settled 30 fill(s) at 2026-09-08 (planned 2026-09-04, run 2026-09-08)
[DATA QUALITY] 14 names dropped (>100% daily jump), [SECTOR CONTROL] 11 displaced by the cap of 5
[v9] plan 2026-09-08: 0 order(s)           <- non-renewal day: tranche 0 opened 2026-09-04, next renewal
                                             is 5 NYSE bars later (2026-09-11 run -> execute 2026-09-14)
[v9] interest since last run 12.75 USD (stocks 6.39, etf 6.36)   <- one bar of ^IRX/252 on idle cash
[v9] dividends 0.00 (real fetch path exercised; no ex-dates between 09-04 and 09-08)
book 100,001.97 = stocks 49,999 (cash 42,874, expo 0.14, 22 names) + etf 50,003 (cash 42,689, expo 0.15, 8 names)
```

- `verify_state` on the copy after settle + plan: **clean** (30 fills replayed).
- The low sleeve exposure is the design, not a defect: only tranche 0 (1/4 of each sleeve) is open in
  week 0, the stock tranche is scaled by `min(1, 15% / basket vol63)` (~0.57 on a Russell-heavy basket)
  and the ETF tranche puts the inverse-vol weight of the two OFF names (TLT, IEF, the low-vol ones)
  into T-bill. Both sleeves land near 57% of the tranche by coincidence.
- `sector_report()`: cached 2518, negative 5, unknown 5, fetched 0 -> the TASK-379 negative cache
  stopped the six rate-limited names from being retried.
- Journal record: 10 None fields, all expected on a settle-only day (`did.orders` empty, no cone
  yet). **One real defect:** `seen.regime_label` was None with a full ranking present — the journal
  reads column `meta_regime_type`, the ranking contract (SPEC 7) names it `regime_type`. Fixed on
  the `post-freeze-wiring` branch (TASK-384) with a test; the label would otherwise never appear.
- No non-JSON-native fields in the record (`json.dumps(default=str)` never needed).

## What Lucas will see on Tuesday 2026-09-08

Execute the 30 orders of `state/instructions_20260904.md` at the close, then `python daily.py --v9`:
preflight table, `settled 30 fill(s)`, `plan 2026-09-08: 0 order(s)`, interest ~13 USD, a sheet
saying "No trades today", the first journal entry (no cone yet). Then `confirm_fills.py` with the real
fills and `reconcile.py` against the broker export. The first new orders come from the Friday
2026-09-11 run (execute Monday 2026-09-14).

## Left

- `HYDRA_BACKUP_DIR` unset on this machine (User and Machine scope): set it before Tuesday.
- Scratch copy kept for inspection at `experiments/_lab_scratch/rehearsal_state/` (gitignored);
  `python experiments/rehearsal.py --mode simulate-t1` re-runs it any time.
