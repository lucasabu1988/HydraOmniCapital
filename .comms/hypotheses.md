# Hypothesis register — HYDRA evolution protocol (spec section 10.3)

Write the hypothesis BEFORE testing it. One entry per idea; rejected ideas stay with their numbers.
Status: PROPOSED -> TESTED (numbers) -> ACCEPTED (version) | REJECTED | WITHDRAWN.

| id | date | proposer | statement | decides on | status |
|---|---|---|---|---|---|
| H-001 | 2026-09-06 | Claude | Dividends credited to the tranche holding the units on ex-date (accounting parity with total-return backtests) | book vs broker residual | ACCEPTED by Lucas 2026-09-06 (accounting, not scoring): TASK-349, `a38c732`; spec 9.3 |
| H-002 | 2026-09-06 | Claude | The 1/8-per-week pair reset vs a full weekly 50/50 reset: measure the return/Sharpe difference on the OOS panel with the production engine | paired ann_net / Sharpe, OOS | PROPOSED — evidence from TASK-350 first |
| H-003 | 2026-09-06 | Claude | Stock splits applied to the book's units on the effective date (`units *= ratio`, `last_px /= ratio`, recorded in `state["splits"]`); accounting parity with split-adjusted closes, same principle as H-001 | book vs broker residual; no phantom quantity diff in `reconcile` after a split | ACCEPTED by Lucas 2026-09-06 (accounting, not scoring): TASK-363 on branch `post-freeze-wiring`, `APPLY_SPLITS = True` (`4a77d6f`), SPEC 9.3; live after the post-settle merge |

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

## Closed before the register existed (for the record)

- NO momentum skip (skip-minus-last-5d was a reversal bet; worse in- and OOS) — 2026-09-06.
- vol-scaling k=1 stays (k=0 is beta, loses OOS) — 2026-09-06.
- MAX_PER_SECTOR=5 hard cap on GICS at selection — 2026-09-06.
- Regime on SPY, IWM secondary persisted for evidence only — 2026-09-06.
- MR (Rattlesnake) sleeve killed at pre-registration (DEV Sharpe 0.21) — 2026-09-06.
- Redesign target >= 10% net: not reached by any robust variant; production moved to the 50/50
  portfolio for return per unit of risk — 2026-09-06/07.
