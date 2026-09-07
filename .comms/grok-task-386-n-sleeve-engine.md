# TASK-386 — Engine iterates N sleeves from the registry (done by Claude, 2026-09-06)

Branch `n-sleeve-engine` (off `post-freeze-wiring`), commit `85bd377`, worktree `../HydraOmniCapital-engine`.
Main and `post-freeze-wiring` untouched. Merge order after the Tuesday settle: `post-freeze-wiring` first,
then `n-sleeve-engine` (it contains the former).

## What landed (design `docs/design/multi-sleeve-engine.md`, sections 3-8, questions 1-8 as answered)

- `core/portfolio_engine.py`: `new_state / plan / settle / mark / summary_table` build their sleeves from
  `sleeves.registry.build(cfg)` (default `["stocks", "etf"]`) and mark each one against the frame it
  declares (`Sleeve.mark_frame`, question 1). The renewed tranches form one **bundle** whose value V is
  split by `cfg["mix"]`: `target[s] = mix[s] * V`, so the transfer legs sum to zero for any N (the
  TASK-347 invariant, question 4's `1/2` replaced by `mix[s]`). One calendar (2); a sleeve with mix 0
  keeps empty tranches (3); `held` always passed (6); cash stays per sleeve (5); transient negative cash
  allowed and watched by the replay (7). Settlement order unchanged: sells, transfer_in, transfer_out, buys.
- `sleeves/registry.py`: entries are a type name or `{name, type, cost_bp}`, so two instances of one
  type can run side by side (question 8); duplicate names refused, unknown types fail closed.
- **Deviation from the task text, on purpose:** the mix is **not** stored in the state and the schema
  stays **1** — no migration. Reason: `test_engine_golden.py` compares the whole final state against the
  fixture (`set(a) == set(b)` on every dict), so a new `mix` key or a version bump would have forced a
  regeneration, which the acceptance criterion forbids; and since TASK-365 the mix already lives per
  book in `portfolios.toml` (policy, not book state). `state_check`, `preflight` and `verify_state`
  take the book's `cfg` so the replay uses its mix (found by `test_portfolios` on a 100/0 book).
- SPEC 9.1 (registry + bundle reset paragraph) and 9.4 (`sleeves` keyed by name, N keys) updated.

## Acceptance

| check | result |
|---|---|
| `test_engine_golden.py` against the existing fixture, **no regeneration** | pass |
| `test_portfolio_engine.py` (hand cases + lab parity with the caches junctioned in) | pass, unchanged |
| full suite `--strict-console` on the branch | 53 files, 0 skipped, 0 failed |
| three-sleeve synthetic (`test_n_sleeve_engine.py`, 5 tests) | design §4 example reproduced: owns 70/40/10 -> transfers -10/-4/+14, sum 0; settle funds every leg; second EtfTrend instance carries cost 3 bp; replay clean through plan/settle/plan; default cfg == two-sleeve engine |
| `engine_backtest.py --oos --check` (1084 PIT plans, replay every step) | running at the time of writing; result appended below |

## OOS parity (PIT panel, 1084 plans, `--check` on every step)

| metric | two-sleeve engine (`post-freeze-wiring`) | N-sleeve engine (`n-sleeve-engine`) |
|---|---|---|
| ann_net / Sharpe / maxDD | 6.96 / 0.73 / -17.8 | **6.96 / 0.73 / -17.8** |
| turnover / exposure / distinct | 13.3 / 76.0 / 38.0 | 13.3 / 76.0 / 38.0 |
| not_filled / hold_no_price / write-offs ($) | 1 / 5 / 2 (0.07281) | 1 / 5 / 2 (0.07281) |
| transfer legs / interest $ | 2150 / 0.231232 | 2150 / 0.231232 |
| yearly net, 22 rows | — | identical to 1e-9 |
| replay checks | — | 2168 calls, 0 findings |

Same run, same day, same caches: **byte-identical plumbing**, so the registry engine is the two-sleeve
engine with the default configuration, on 22 years of real history as well as on the golden.

**Why it is 6.96 and not the 7.10 of TASK-350/369 (corrected after the differential).** Not the engine and not
the sector cache drifting: `experiments/engine_diff.py` drove main's engine and each branch's engine side by
side on the SAME inputs for 300 OOS steps (2005-2011) and every order and fill was identical. The two branch
runs were made in git worktrees, and `data_cache/` is gitignored: those trees had **no `sector_cache.json`**
(every name fell to `SECTOR_BUCKETS`/"Other", so the sector cap barely bound) and fetched a **fresh
`sp500_pit.json`** from Wikipedia that differs from the cached payload (membership). Main, run the same
afternoon with its cache, still gives 7.10 / 0.75 / -17.8. So: identical engine, degraded inputs in the
worktree. That is what TASK-387 fixes (sector map pinned to a PIT snapshot, payload identity recorded,
loud warning when the map is mostly fallback). The parity table above stands: same inputs, same output.
