# TASK-341 — Independent review of the v9 engine (`62598ab`)

Review, not a re-implementation. Engine not edited. 8 tests in `test_review_341.py`:
**7 hold, 1 fail.**

## Parity (reproduced)

`test_parity_stock_targets_reproduced` on `experiments/_sweep_cache/` (in-sample):
≥ 20 renewal dates, `stock_targets` vs `redesign_lab` T20 weights, atol 1e-9. Passed.
ETF parity was already in `test_portfolio_engine.py`; not duplicated.

## Attacks (Claude's list)

| Attack | Result |
|---|---|
| Zero recommended → T-bill, never fallback | Holds (park, no buy) |
| All ETFs off (no 252 bars) | Holds (etf park, no buy) |
| Held name with no price on execution day | Holds (`not_filled`, no invented units) |
| 50/50 reset when sleeves imbalanced | Holds (cash transfer_out = transfer_in) |
| Plan twice on the same date | Holds (`[]`) |
| `capital_reference` changed mid-life | Holds — units/cash of the live book are **not** rescaled. The reference is a label; sizing uses marked value. Adding capital still needs a cash deposit, not a JSON edit. |

## Finding

**`test_park_and_hold_no_price_survive_settle_into_the_ledger` fails.**
`settle()` only walks `sell` / `transfer_in` / `transfer_out` / `buy`, then sets
`pending = []`. `park` and `hold_no_price` are dropped with no ledger row and no
status. The instruction sheet from TASK-340 still shows them on the plan day;
the next run's fills list does not. Cash is already in the tranche so P&L is
fine — the audit trail is not.

## Files

`test_review_341.py`, this note. Not edited: `core/portfolio_engine.py`.
