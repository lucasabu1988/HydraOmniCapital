# Hypothesis register — HYDRA evolution protocol (spec section 10.3)

Write the hypothesis BEFORE testing it. One entry per idea; rejected ideas stay with their numbers.
Status: PROPOSED -> TESTED (numbers) -> ACCEPTED (version) | REJECTED | WITHDRAWN.

| id | date | proposer | statement | decides on | status |
|---|---|---|---|---|---|
| H-001 | 2026-09-06 | Claude | Dividends credited to the tranche holding the units on ex-date (accounting parity with total-return backtests) | book vs broker residual | ACCEPTED by Lucas 2026-09-06 (accounting, not scoring): TASK-349, `a38c732`; spec 9.3 |
| H-002 | 2026-09-06 | Claude | The 1/8-per-week pair reset vs a full weekly 50/50 reset: measure the return/Sharpe difference on the OOS panel with the production engine | paired ann_net / Sharpe, OOS | PROPOSED — evidence from TASK-350 first |
| H-003 | 2026-09-06 | Claude | Stock splits applied to the book's units on the effective date (`units *= ratio`, `last_px /= ratio`, recorded in `state["splits"]`); accounting parity with split-adjusted closes, same principle as H-001 | book vs broker residual; no phantom quantity diff in `reconcile` after a split | ACCEPTED by Lucas 2026-09-06 (accounting, not scoring): TASK-363 on branch `post-freeze-wiring`, `APPLY_SPLITS = True` (`4a77d6f`), SPEC 9.3; live after the post-settle merge |
| H-004 | 2026-09-07 | Claude | `core/regime.py` breadth counts columns whose comparisons are UNDEFINED on the date (no close / no return / no 50d or 200d SMA); count only the columns that participate | paired OOS ann_net (T20, executable) and the live regime series | PROPOSED — patch, measured effect and provenance in `.comms/claude-astra06-core-proposal-2026-09-07.md`; rule 6, Lucas decides |

## Template

```
### H-### — <short title>
- Date / proposer:
- Statement: what changes, exactly (parameter, rule, accounting).
- Motivation: journal entries / evidence review / paper / audit finding that prompted it.
- Expected effect and the single deciding metric (e.g. paired OOS Sharpe difference >= +0.05 with
  SE; or reconciliation residual reduced to < 0.1%).
- Falsifier: what result rejects it.
- Test plan: DEV panel (< 2016) first; TEST (>= 2016) read once and declared; executable accounting
  (`run_exec` / engine driver), costs included; paired difference with standard error.
- Result: table (gross, net, Sharpe, maxDD, turnover, distinct) current vs proposed; DEV and TEST.
- Decision (Lucas, date): ACCEPTED -> version vX.Y, ALGO_VERSION bump, SPEC section, journal marker
  date | REJECTED (why) | WITHDRAWN.
```

### H-004 — breadth counts only the columns that participate (core/regime.py)

- Date / proposer: 2026-09-07 / Claude (follow-up to ASTRA-06, external audit 2026-09-06).
- Statement: in `core.regime.compute_rich_regime_scores`, a column enters the three breadth
  statistics only when all of its comparisons are DEFINED on the date (it has a close, a return,
  a 50-bar SMA and a 200-bar SMA), and the ">30 columns" guard counts those columns rather than
  the frame's width. Today `NaN > sma` is False and that False sits in the denominator, so a name
  with no price on the date is counted as "not participating" and pushes breadth down.
- Motivation: Astra's probe — 50 all-NaN columns move `overall` 0.773 -> 0.723 (breadth 1.0 ->
  0.5). ASTRA-06 fixed the LAB (it stopped handing core the whole 2004-2026 panel); core itself is
  untouched because its treatment of missing data is GROKBOARD rule 6.
- Two sizes, decide them separately:
  - **A (minimal)**: drop only the columns with no observation on the date. Provably live-neutral
    today — the live filter chain removes them before scoring (`min_price` compares
    `prices.iloc[-1] >= 5.0`, False for NaN), asserted by
    `test_pit_breadth.py::test_DEFECT_is_currently_unreachable_from_the_live_filter_chain`.
  - **B (complete)**: also drop columns whose 50d/200d SMA or return is undefined (short history).
    This one DOES move the live regime, because the production frame keeps recent listings.
- Expected effect and deciding metric: paired difference in annualised NET return of T20 on the
  OOS PIT panel with executable accounting, current vs patched. Expected |delta| < 0.25 pp, same
  sign on DEV and TEST.
- Falsifier: T20 OOS `ann_net` drops by more than 0.25 pp, or DEV and TEST move in OPPOSITE
  directions — then the "fix" is a return lever in disguise: leave core as it is and document the
  defect instead of correcting it silently. Also killed if the minimal variant A stops being
  live-neutral (that test failing means the live regime IS eating unobserved columns today, which
  is an escalation, not a hypothesis).
- Test plan: `experiments/astra06_core_proposal.py` (committed) measures the regime / aggression /
  dynamic-count / order-list deltas date by date and asserts the identity it relies on
  (`--self-check`); then `experiments/redesign_lab.py --full T20 --cache-dir ... --payload ...
  --pit-dir ...` for the paired headline, DEV and TEST reported separately. Inputs, hashes and
  dates in the note.
- Result (2026-09-07, OOS PIT S&P panel, 1084 five-bar cycles, executable accounting, 10 bp/side;
  full tables and provenance in `.comms/claude-astra06-core-proposal-2026-09-07.md`):
  T20 ann_net 7.28 -> 7.30 ALL (6.97 -> 7.00 DEV, 7.60 -> 7.60 TEST); PROD 4.87 -> 4.88 ALL
  (3.19 -> 3.20 DEV, 6.63 -> 6.63 TEST). Sharpe, maxDD, turnover, exposure, avg_n, distinct
  unchanged. Paired per-cycle net difference +0.000003 (T20) / +0.000002 (PROD). On top of the
  ASTRA-06 lab fix the regime moves on 122/1084 dates by a mean of +0.0001 (max 0.0010),
  `dynamic_count` on 2 dates, the order list on those same 2, the regime gate never.
  **Passes the falsifier.** NOT measured: variant B's effect on the LIVE regime (it needs the
  production price frame; `data_cache/bars.sqlite` was deliberately not opened).
- Decision (Lucas, date): pending.

## Closed before the register existed (for the record)

- NO momentum skip (skip-minus-last-5d was a reversal bet; worse in- and OOS) — 2026-09-06.
- vol-scaling k=1 stays (k=0 is beta, loses OOS) — 2026-09-06.
- MAX_PER_SECTOR=5 hard cap on GICS at selection — 2026-09-06.
- Regime on SPY, IWM secondary persisted for evidence only — 2026-09-06.
- MR (Rattlesnake) sleeve killed at pre-registration (DEV Sharpe 0.21) — 2026-09-06.
- Redesign target >= 10% net: not reached by any robust variant; production moved to the 50/50
  portfolio for return per unit of risk — 2026-09-06/07.
