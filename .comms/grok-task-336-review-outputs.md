# TASK-336 — Independent review of `839e375` (findings A, B, C)

Review, not a re-implementation. Diff read, then attacked. Counterexamples live in
`hydra_screener_local/test_review_336.py`. Reviewed modules were not edited.

Commit under review: `839e375` (`fix: zero recommendations stay zero; full recommended
set survives every export; tracking completes pending horizons`).

## Runner (rule 4 / discovery)

`python run_all_tests.py --list` includes, in this order among others:

- `validate_pine_contract.py` (via `ADDITIONAL_TESTS`, no longer glob-invisible)
- `test_output_integrity.py`
- `test_tracking_pending.py`
- `test_review_336.py` (this task)

Per-file lines of the subsequent `python run_all_tests.py` run (hydra_screener_local,
43 s):

| file | executed? | result |
|---|---|---|
| `validate_pine_contract.py` | yes | `[SKIP]` (no `pine/hydra_last_summary.json` / history artefact; exit 0) |
| `test_output_integrity.py` | yes, via pytest | 5 passed |
| `test_tracking_pending.py` | yes, via pytest | 4 passed |
| `test_review_336.py` | yes, via pytest | **6 failed, 7 passed** |
| `test_hybrid_integration.py` | yes | `[SKIP]` (needs `history/`) |

Suite totals: **20 passed, 2 skipped, 1 failed file** (`test_review_336.py`). Exit 1.
The red file is the review: the six failing tests are the findings below. Everything
else in the suite is green. Rule 4 vs "tests that fail": this task asked for failing
counterexamples, so the suite is red on purpose until Claude decides which holes to
close.

## Method

Read `839e375` and the current bodies of `send_hydra_summary.py`,
`generate_pine_watchlist.py`, `screener.py` (`history_records`, `executable_top5`,
hybrid calls), `validate_pine_contract.py`, `core/tracking.py` (`needs_update`,
`compute_forward_returns_for_run`). Then wrote one attack per Claude prompt plus the
holes the author's tests do not cover. Assertions describe the *desired* contract;
a pass means the fix holds, a fail is a finding.

## A — zero recommendations stay zero

**Holds.** Three attacks, three passes.

- Every row missing the `recommended` key (absent, not `False`) → summary count 0,
  empty watchlist file, validator accepts empty ≠ missing.
- Candidates frame with no `recommended` column → `executable_top5` returns `[]`
  (does not pad), `history_records` does not invent flags.
- 30 high-rank rejects (`recommended=False`) never become the watchlist or Top5.

Production path: `screener.py` calls `run_feeder(top_n=None)` / `run_sender(top_n=None)`
and `executable_top5`. The old `exec_pool = candidates` / `top_candidates[:top_n]`
fallbacks are gone. Author tests in `test_output_integrity.py` already cover 0/1/22/28
with the flag present; the missing-key case was the gap and it holds.

Note (not a fail): `screener.py:200` still does `candidates.head(TOP_CANDIDATES)` when
the column is missing, but that is the printed table only, not an export.

## B — full recommended set survives

**Holds** for the case the author cared about: 28 recommended names with *tied* rank 1
all survive summary, history_records, and the feeder. Rank uniqueness is not required.

**Breaks** (3 failing tests):

1. **`test_B_cli_default_does_not_truncate_the_watchlist`** — `python generate_pine_watchlist.py`
   with no `--top` still argparse-defaults to **15** and writes 15 of 28 names. The
   library (`load_recommended_tickers` / `run_feeder(top_n=None)`) and the screener
   hybrid path are fine; the helper CLI is the leftover cap. Docstring still says
   "default 15". Pine `i_max_watchlist` (default 15, table rows only) is the intended
   TV-side cap and is unchanged. Severity: footgun on the manual path, not live
   `screener.py`.

2. **`test_B_display_limit_does_not_waive_prefix_check`** — `simulate_pine_parser`
   skips the `top_details == recommended_tickers` check entirely when `display_limit`
   is set. A consumer can declare `display_limit: 15` and ship any 15 names. The
   producer (`build_rich_summary(..., top_n=15)`) does emit the correct prefix; the
   contract does not enforce it. Severity: validator hole, not a producer bug.

3. **`test_B_duplicate_recommended_ticker_is_not_double_published`** — two rows with
   the same ticker both flagged → `recommended_tickers` lists it twice (T01 at rank 1
   and again at rank 99). Production `generate_daily_candidates` is one row per ticker,
   so this is malformed-history only.

## C — tracking pending / provenance / idempotence

**Holds:**

- A v2 file whose `signal_date` key is missing is not treated as final
  (`needs_update` → `signal_date_changed`). The listed counterexample holds.
- `omitted` reason `no_price_data` is retryable; when the series later appears in
  the price frame the name is measured.
- A complete file with provenance is idempotent (`again == full`).

**Breaks** (3 failing tests):

1. **`test_C_complete_v2_without_snapshot_still_sees_a_changed_history_set`** — the
   operational one. `needs_update` only compares snapshots when
   `existing.get("recommended_snapshot") is not None`. A complete pre-C v2 file
   (measured returns, `signal_date` present, no snapshot) returns `(False, "complete")`
   even if history now has a larger recommended set. After finding B, names past
   rank 20 persist; old complete tracking files will not pick them up unless
   `--force`. Same skip if someone deletes the snapshot field.

2. **`test_C_omitted_no_entry_price_retries_when_the_hole_fills`** —
   `RETRYABLE_OMISSIONS = {no_price_data, no_bar_after_signal_yet}`. A NaN on the
   entry bar (`no_entry_price`) is final. Filling that hole later cannot be measured.
   Exit-bar holes with later prices become `unmeasurable` (also final); the entry
   case is the one that can still resolve by backfill. Author tests cover the
   `no_price_data` retry, not this.

3. **`test_C_duplicate_recommended_ticker_is_measured_once`** — `_run(("AAA","AAA"))`
   produces two candidate records and `recommended_snapshot == ["AAA", "AAA"]`.
   Same malformed-history class as B.3.

## What I did not treat as a fail

- Pine `i_max_watchlist = 15` is the documented TV display cap, not a Python
  truncation of `recommended_tickers`.
- `log_cycle_positions.log_cycle(..., candidates.head(20), ...)` still passes a
  head(20) *context* frame; the executable list itself is `executable_top5`.
- Truthy non-bool flags (`recommended: "no"`) would be included by `c.get("recommended")`
  and excluded by `== True` in `history_records` / `executable_top5`. Production
  writes a pandas bool. Not an attack on 839e375's actual path.

## Files touched (this task)

- `hydra_screener_local/test_review_336.py` (13 tests: 7 hold, 6 findings)
- `.comms/grok-task-336-review-outputs.md`
- GROKBOARD.md / `.comms/status.md` (Grok section only)

Not edited: `send_hydra_summary.py`, `generate_pine_watchlist.py`, `screener.py`,
`validate_pine_contract.py`, `core/tracking.py`, `run_all_tests.py`, the lab.
