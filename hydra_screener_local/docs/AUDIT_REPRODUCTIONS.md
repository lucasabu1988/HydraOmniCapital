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

## Phase 4 — dividends and corporate actions

| id | phase | defect | reproduction | fixed in |
|---|---|---|---|---|
| R-401 | 4.1/4.2/4.3 | **a provider outage lost the dividend permanently.** The window was `(last_run_date, today]` and `plan()` advanced `last_run_date` whether or not the dividend query succeeded, so an ex-date first reported after the watermark had passed it could never be credited | `test_dividend_coverage.py::test_r401_*` | `fix: preserve dividend and corporate-action watermarks` |
| R-402 | 4.3 | the query window had no overlap, so a late report was out of scope by construction | same | same |
| R-403 | 4.5 | no coverage record existed: a run could not tell a verified window from an unobserved one, and nothing could say coverage was incomplete | `test_dividend_coverage.py::test_r403_*` | same |
| R-404 | 4.4 | no way to retract or version a withdrawn corporate action — the credited cash was stuck in the book | `test_dividend_coverage.py::test_r404_*` | same |
| R-405 | 4.6 | two different amounts for one (ticker, ex_date) were resolved silently by whichever row came first | `test_dividend_coverage.py::test_r405_*` | same |
| R-406 | 4.6 | a NaN, infinite, zero or negative `dps` was dropped in silence rather than reported | `test_dividend_coverage.py::test_r406_*` | same |

Recorded at the base commit:

```
R-401  a provider that returns nothing loses the dividend for good
  day 1 (provider empty): credited=0  cash=100.0
  day 2 (provider recovers, ex-date 01-08): credited=0  cash=100.0   <- $5.00 gone
R-402  ex_date BEFORE the watermark (a late report): credited=0      <- lost
R-403  state keys after crediting: ['dividends']                     (no coverage record)
R-404  retraction API present: []
R-405  two CONFLICTING dps for one ex-date -> credited=1 cash=105.0  (silent first-wins)
R-406  NaN dps -> credited=0 cash=100.0                              (silently dropped)
```

## Phase 5 — data store and data quality

| id | phase | defect | reproduction | fixed in |
|---|---|---|---|---|
| R-501 | 5.3/5.4 | **`replace_ticker` destroyed history silently.** `min_bars=10` was no guard: a 12-bar frame passed it and cut **2800 stored bars down to 12** | `test_store_integrity.py::test_r501_*` | `fix: repair store verification and non-destructive backfill` |
| R-502 | 5.2 | `stored_vs_fresh` was computed, printed and thrown away — only `local_vs_fresh` gated the exit code, and that needs actions coverage the store often lacks | `test_store_integrity.py::test_r502_*` | same |
| R-503 | 5.1 | `verify` on an **empty store** returned True (exit 0) | `test_store_integrity.py::test_r503_*` | same |
| R-504 | 5.1 | a provider that returned nothing was a per-ticker `continue`, and the command still printed `verify ok` | `test_store_integrity.py::test_r504_*` | same |
| R-505 | 5.1 | no date overlap between stored and fresh was also just a `continue` | `test_store_integrity.py::test_r505_*` | same |
| R-506 | 5.6 | no gap, duplicate, non-positive-close, provider or capture-time metric existed anywhere | `test_store_integrity.py::test_r506_*` | same |
| R-507 | 5.7 | **`reconcile.py` always returned 0**, including from a bare `except Exception`, so a broken CSV read as a clean reconciliation | `test_store_integrity.py::test_r507_*` | same |

Recorded at the base commit:

```
R-501  stored: 2800 bars 2015-01-01 -> 2025-09-24
       after replace_ticker with a 12-bar frame: 12 bars 2026-01-01 -> 2026-01-16
R-502  local_vs_fresh gates the exit code : True
       stored_vs_fresh gates the exit code: False
R-503  empty store -> verify returns True  (exit code 0)
R-504  AAA: provider empty  /  verify ok  -> True
R-505  AAA: no overlap      /  verify ok  -> True
R-506  coverage columns: ticker, first, last, n_bars, has_asof   (no gaps/duplicates)
R-507  reconcile.main() ends in `return 0` on every path, after `except Exception`
```

Two existing tests asserted the defect and were rewritten:
`test_bar_store.py::test_replace_ticker_drops_old_rows` (required that a 15-bar frame
shrink a 40-bar history) and `test_reconcile.py::test_cli_exit_0_on_missing_state`
(required exit 0 when the state file was missing).

## Phase 6 — PIT, sectors and reproducibility

| id | phase | defect | reproduction | fixed in |
|---|---|---|---|---|
| R-601 | 6.1/6.2/6.10 | **the same date was overwritten with different content.** Writing `["CCC","DDD"]` for 2026-01-05 replaced `["AAA","BBB"]` in place; two completely different memberships shared one identity and the first left no trace | `test_pit_identity.py::test_r601_*` | `fix: make PIT inputs immutable and content-addressed` |
| R-602 | 6.4 | no hash of any kind was recorded — payload keys were `count, fetched_at, source, tickers` | `test_pit_identity.py::test_r602_*` | same |
| R-603 | 6.4/6.5 | readers got a bare `set` and could not say which snapshot they had loaded | `test_pit_identity.py::test_r603_*` | same |
| R-604 | 6.6 | a missing PIT snapshot returned `set()` / `({}, None)` and the run continued as if it had point-in-time data | `test_pit_identity.py::test_r604_*` | same |
| R-605 | 6.7 | a corrupt sector value was serialised as a sector — `str(None)` is `"None"`, which reads back as a GICS sector | `test_pit_identity.py::test_r605_*` | same |
| R-606 | 6.8/6.9 | nothing tied `audit_steps.pkl` to the panel, sector map, config or code it came from, so a stale baseline could outlive all four and still print a percentile | `test_pit_identity.py::test_r606_*` | same |

Recorded at the base commit:

```
R-601  path 1 == path 2 : True
       content 1 tickers: ['AAA','BBB']  ->  content 2 tickers: ['CCC','DDD']
R-602  payload keys: ['count', 'fetched_at', 'source', 'tickers']
R-603  membership returns a bare set: set ['CCC','DDD']
R-604  membership on an empty dir : set()
       sectors_at on an empty dir : ({}, None)
R-606  no *.key.json sidecar anywhere; nothing binds the baseline to its inputs
```

The eight snapshots already in `data_cache/pit/` were re-read after the rewrite:
sp500 = 503 names, all = 3002, sectors = 2897, no fallback. Their identity honestly
reports `recorded_sha256=None, verified=False` — they predate content addressing, and
saying so is the point.

## Phase 7 — universe and methodology

| id | phase | defect | reproduction | fixed in |
|---|---|---|---|---|
| R-701 | 7.1/7.3 | **a market-cap ranking was called "Russell".** The primary source for `russell1000`/`russell2000` is a NASDAQ cap ranking, and the code said "Russell 1000" in docstrings, in console output, and in a comment asserting the method was "igual que la metodología FTSE Russell" | `test_universe_registry.py::test_r701_*` | `docs: name the cap-rank proxy universes and document provenance` |
| R-702 | 7.2 | no universe carried a documented source, definition, membership method, exclusion list, coverage or hash | `test_universe_registry.py::test_r702_*` | same |
| R-703 | 7.5/7.6 | PIT / current / proxy / fallback were not distinguished anywhere, and no bias statement travelled with a universe | `test_universe_registry.py::test_r703_*` | same |
| R-704 | 7.4 | nothing excluded warrants, units, rights, preferreds or malformed symbols | `test_universe_registry.py::test_r704_*` | same |

Measured, not assumed: `exclude_non_common()` against the live `all` universe on
2026-09-06 (3002 names) removes **zero** names — the sources already return common
stock only. The guard is there so a warrant cannot enter unnoticed later, and
production behaviour is unchanged.

One real finding surfaced by `duplicate_share_classes()`: the live universe holds
**`BRK-A`, `BRK-B` and `BRK.B`** — the last two are the same security under two
spellings, i.e. one company counted twice with two price series. Reported, not
silently deduped: deduping it changes the recommended list and needs a measurement.

That measurement is TASK-389 (`experiments/duplicate_classes.py`,
`.comms/grok-task-389-duplicate-classes.md`), and it turned the finding around. The
duplicate never double-counted — Yahoo returns 0 bars for `BRK.B`, and `BRK-A` averages
161 shares a day and fails the liquidity filter every day. The spelling is what costs:
`BF.B` is dot-spelled with **no** dash twin, so Brown-Forman cannot be scored at all,
and both names sit in the in-sample panel as all-NaN columns (2 of 503). Filling them
moves the in-sample headline 12.18 → 12.24 ann_net (`BRK-B` enters the T20 on 11 of 279
dates; `BF-B` on none). The OOS panel already normalises through `_yahoo_ticker` and is
unaffected.

## Phase 8 — engine, calendar and sleeves

| id | phase | defect | reproduction | fixed in |
|---|---|---|---|---|
| R-801 | 8.8 | **the renewal schedule depended on how many bars the last download returned.** `bars_between` counted rows of whatever index it was handed | `test_engine_state_meta.py::test_r801_*` | `fix: persist engine configuration and dynamic sleeve registry` |
| R-802 | 8.1/8.2 | the state persisted no effective config, mix, sleeve registry, config hash, registry hash, calendar or last-mark date, so a replay used whatever config the process had imported | `test_engine_state_meta.py::test_r802_*` | same |
| R-803 | 8.3 | nothing validated that the sleeve weights were finite, non-negative, complete and summed to 1 | `test_engine_state_meta.py::test_r803_*` | same |
| R-804 | 8.4/8.6 | every valuation, settlement and summary walked the module constant `SLEEVES = ("stocks","etf")`, so a sleeve the state held but the constant did not was never valued — capital hidden by a loop | `test_engine_state_meta.py::test_r804_*` | same |
| R-805 | 8.9/8.10 | **the differential driver compared orders and fills only** and returned 0 as soon as those matched: two engines could agree on every order and disagree on cash, positions, tranches, fees or the whole state, and it printed `IDENTICAL` | `test_engine_state_meta.py::test_r805_*` | `fix: compare full engine state in the differential driver` |

Recorded at the base commit for R-801, with a 700-session calendar and the anchor at
its start:

```
bars_between on the FULL index   : 699    -> week 139 -> renewal_slot None
bars_between on a 500-bar index  : 500    -> week 100 -> renewal_slot (100, 0)

  index of 700 bars -> bars_between = 699  week = 139
  index of 600 bars -> bars_between = 600  week = 120
  index of 500 bars -> bars_between = 500  week = 100
  index of 400 bars -> bars_between = 400  week =  80
```

A renewal fired or did not, and a *different tranche* renewed, purely because of the
download length. `V9["price_period"] = "2y"` masks this today only because the anchor
(2026-09-04) is days old; it breaks silently once the anchor is older than the fetch
window.

### Golden fixture regeneration (phase 8)

`test_fixtures/engine_golden_v9.json` was regenerated, and **no number moved** — the
change is purely the new persisted fields. Verified before regenerating:

```
  orders         before=680                after=680                SAME
  fills          before=611                after=611                SAME
  transfers      before=52                 after=52                 SAME
  write_offs     before=4                  after=4                  SAME
  interest_sum   before=1.9247703284       after=1.9247703284       SAME
  cash_sum       before=157.784936045      after=157.784936045      SAME
  ledger         before=628                after=628                SAME
  week_index     before=29                 after=29                 SAME
  last_renewal   before='2021-07-22'       after='2021-07-22'       SAME
  order lists byte-identical: True
```

## Phase 9 — CLI, journal and operation

| id | phase | defect | reproduction | fixed in |
|---|---|---|---|---|
| R-901 | 9.5 | **a rerun of the same day replaced the evidence.** `journal/<date>.json` was rewritten in place, so what the earlier run of that day recommended was gone | `test_journal_revisions.py::test_r901_*` | `fix: propagate universe and make journal append-only` |
| R-902 | 9.4 | **an error deleted the successful record.** `append_error()` went through the same in-place write: a book total of 123,456 became 0.0 | `test_journal_revisions.py::test_r902_*` | same |
| R-903 | 9.3 | records carried no run_id, revision, parent_run_id, status, error, inputs, outputs or timestamps | `test_journal_revisions.py::test_r903_*` | same |
| R-904 | 9.1/9.2 | each stage re-derived the universe from the environment and nothing recorded which one actually ran | `test_journal_revisions.py::test_r904_*` | same |
| R-905 | 9.8 | nothing surfaced stale data, a missing sheet, unreconciled cash or a partial execution as an operational alert | `test_journal_revisions.py::test_r905_*` | same |

Recorded at the base commit:

```
R-901  after run 1: {'n_orders': 13}
       after run 2: {'n_orders': 0}          <- run 1 gone
       files: ['2026-09-04.json', 'JOURNAL.md']
R-902  before:             {'total': 123456.0}
       after append_error: {'total': 0.0, ...}
       the successful total is gone: True
R-903  keys in the record: ['algo_version','book','date','did','expectation',
                            'observations','process','schema','seen']
```

A further gap was found *by* the phase-9 tests rather than by the probe: a day that
only ever failed writes a book total of 0.0, and `prior_total` / the equity curve read
it as a valuation, inventing a -100% step. `successful_records()` now filters those
out — a failure is evidence of a failure, not a valuation.

### Phase 9.6 — the scheduler

Not implemented here, and not claimed. `utils/trading_calendar.py` gained
`nyse_sessions_between()` in phase 2 and the preflight uses the market calendar, the
timezone is recorded in the run manifest (phase 6), and the last observed close is
now a first-class concept (`data/quality.py`). Wiring those into the Windows scheduled
task lives on `post-freeze-wiring` (TASK-364), which this branch does not merge — see
[the final report](AUDIT_REPORT_2026-09.md).

## Phase 10 — packaging, CI and supply chain

| id | phase | defect | reproduction | fixed in |
|---|---|---|---|---|
| R-1001 | 10.1/10.2 | **the wheel was broken.** `packages.find.include` listed `core*, data*, utils*` and no `sleeves*`, and the five console scripts point at top-level modules, which `find` never ships: the wheel contained neither `sleeves`, nor `config.py`, nor a single entry-point module. Every script was dead on an installed copy and `import core.signals` failed on `from config import ...` | `test_packaging.py::test_r1001_*` (4 tests) + `tools/wheel_smoke.py` | `fix: ship a wheel that actually runs` |
| R-1002 | 10.3 | **`requirements.txt` and `pyproject.toml` declared different products.** pyproject had `requests` and neither `scipy`, `python-dateutil` nor `rich`; requirements had `rich` — which is not installed on Lucas's machine and is not needed — and no `requests`. Nothing compared them | `test_packaging.py::test_r1002_*` (4 tests) | same |
| R-1003 | 10.3 | `requires-python = ">=3.9"` was wrong: the tree uses `zip(..., strict=True)` and PEP 604 unions at runtime, so a 3.9 install fails on import | `test_packaging.py::test_r1003_*`, `test_the_ruff_target_matches_the_python_floor` | same |
| R-1004 | 10.5 | **the lint gate said "All checks passed" while the tree was red.** The suite and CI ran ruff over an explicit module list; the brief runs `ruff check .`, and five errors in four files outside that list (unused `os`/`Path`/`numpy` imports, an f-string with no placeholders, an unannotated empty tuple) had been passing for as long as the list existed | `python -m ruff check . --config ruff.toml`, now its own CI step | same |

Recorded at the base commit:

```
R-1001  wheel contents: core/, data/, utils/ only
        missing: sleeves/, config.py, daily.py, refresh_current_prices.py,
                 live_watcher.py, generate_html_dashboard.py, console_dashboard.py
        hydra-daily --help  ->  ModuleNotFoundError: No module named 'daily'
R-1002  only in requirements.txt: rich, python-dateutil, scipy
        only in pyproject:        requests
R-1003  requires-python = ">=3.9"; strict=True used in core/, data/, utils/ and the root
R-1004  python -m ruff check . --config ruff.toml  ->  Found 5 errors
        (run_all_tests.py reported: ruff (report-only): All checks passed!)
```

### What phase 10 added as gates, not as claims

`.github/workflows/test.yml` grew from two jobs to seven, and every one of them except
`dependency-audit` is meant to be required on `main`
([`docs/BRANCH_PROTECTION.md`](BRANCH_PROTECTION.md) has the exact ruleset; a ruleset is
a repository setting, so it is documented, not applied):

| gate | what it would have caught |
|---|---|
| `build-install-smoke` (`tools/wheel_smoke.py`) | R-1001 — builds the wheel, installs it into a fresh venv, imports every declared module from *outside* the source tree and runs every console script's `--help` |
| coverage floor (`tools/check_coverage.py --min 80.0`) | a silent drop in test coverage. Measured: **81.96%** here, **81.22%** on the Linux runner. The floor was ratcheted from 77.0 to 80.0 once CI produced a real number (TASK-390); it ratchets up, and is never lowered to make a build green |
| skip gate (`tools/check_skips.py`) | a skip reported as a pass. Baseline is **0 skips over 58 files** since TASK-374; a new skipping file fails unless it is listed with a reason |
| `ruff check .` | R-1004 |
| `typecheck` (`mypy.ini`) | the modules this audit added or rewrote are annotated and checked (10 files). The older tree is not, and a gate that passes because everything is ignored is not a gate |
| `secret-scan` | gitleaks with `.gitleaks.toml`, plus `tools/check_secrets.py` — a dependency-free sweep so the gate still means something if the action is unavailable, and so an `.env` never lands |
| `reproducibility` | serialisation, state migration, PIT identity and ledger integrity on their own job, so a failure there is unmistakable |
| `dependency-audit` | `pip-audit`, **report-only on purpose**: a CVE in a transitive pin is not a reason to block a screener commit, but it must be visible |

Phase 10.6 also covers what the wheel is *not*: `test_packaging.py::test_no_broker_or_cloud_execution_is_declared`
asserts no broker SDK and no cloud-execution dependency is declared anywhere in the
install (rule 3 of the brief), and the state written every run is proved JSON-clean and
migratable from the pre-phase-1 shape that is on Lucas's disk today — without a rewrite
and without moving a number.
