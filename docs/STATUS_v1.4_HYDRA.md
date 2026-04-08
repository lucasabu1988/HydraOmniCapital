# HYDRA Backtest v1.4 — Status & Next-Session Memo

**Date paused:** 2026-04-07
**Branch:** `main`
**Last commit on v1.4:** `0b57bcc` (catalyst double-counting + derived bucket model)

## TL;DR

v1.4 is **code complete and unit-tested** but the official 2000–2026
run is blocked by an architectural feedback loop. Tasks 1–18 of the
implementation plan are done and committed. Task 19 (the official
run) needs an Option-A or Option-B redesign in a fresh session before
it will produce a defensible result.

## What works

- 39 unit tests pass across `hydra_backtest/hydra/tests/` (capital,
  state, engine wrappers, validation)
- 1 integration smoke test (`test_integration.py`) runs the CLI
  end-to-end on synthetic 7-input fixtures and validates all 4
  output files
- 3 E2E real-data tests (`test_e2e.py`, `@pytest.mark.slow`):
  - `test_e2e_determinism` verified byte-identical on Jan 2020
    (76 seconds)
  - The other two (3-month + Layer B) are gated on `data_cache/`
    files and skip cleanly in CI
- The byte-identity test against live `HydraCapitalManager` over 100
  random days passes — `compute_allocation_pure` and
  `update_accounts_after_day_pure` match live exactly
- All v1.0 + v1.1 + v1.2 + v1.3 test suites remain green (138 tests
  unchanged)

## What's broken (T19 blocker)

The dry run on real S&P 500 data (Jan–Dec 2003) reveals a feedback
loop in the budget allocation hack:

```
day N: COMPASS exits 4 positions
       broker cash grows by ~$46k (proceeds)
day N: orchestrator recomputes derived bucket:
       compass_account = compass_pos_value + cash * 0.425
                       ≈ $58k + $30k = $88k
day N+1: compass_budget = compass_account + recycled = $88k + $X
       capped at broker cash → ≈ $72k
day N+1: COMPASS spends $72k on new entries
         leaving ~$0 for rattle/catalyst/efa
day N+2: COMPASS exits → broker cash grows again
         compass_account grows AGAIN
         next compass_budget is even larger
... feedback loop until other strategies starve
```

The 2003 dry run finishes with PV = $91,547 (down 8.5%), which is
plausible mid-range but masks the broken allocation. A multi-decade
run would amplify the feedback loop catastrophically (the original
1999 run before the fix went $100k → $13k by year 1).

The 4 cascading bugs that WERE fixed during the dry-run debugging:

1. **Catalyst double-counting** in `apply_catalyst_wrapper`:
   `_mark_to_market(substate)` saw both `cash_override = catalyst_budget`
   AND the existing catalyst positions, so the rebalance target was
   2× reality. → Fixed by passing
   `cash_override = catalyst_budget − catalyst_pos_value`.

2. **Sub-account drift** with the percentage-return model. → Fixed
   by switching to dollar returns first, then to a derived bucket
   model (compute buckets from positions + cash share each day).

3. **Recycling settlement gap**: dollar returns left recycled cash
   stranded between buckets. → Solved by going derived (no settlement
   needed because buckets are recomputed).

4. **CLI config keys mismatched live**: `POSITION_STOP_PCT` vs
   `POSITION_STOP_LOSS`, `CRASH_BRAKE_*` vs `CRASH_VEL_*`, etc.
   → Fixed by syncing to `hydra_backtest/tests/conftest.py`.

## The remaining architectural issue

The derived bucket model is correct (sub_sum == PV by construction)
but it interacts badly with the budget hack:

- `compass_budget` is computed from `compass_account` (the derived
  bucket value)
- `compass_account = compass_pos + cash * weight` grows whenever
  cash grows (from any strategy's exits)
- When COMPASS rotates, broker cash spikes temporarily, inflating
  compass's bucket — and on the NEXT compass entry, compass_budget
  is too large
- COMPASS over-spends, starving other pillars

## Two candidate fixes for next session

### Option A — Budget scales with portfolio_value (recommended)

Replace `compass_budget = compass_account + recycled` with:

```python
compass_budget = min(
    BASE_COMPASS_ALLOC * portfolio_value + recycled_amount,
    broker_cash,
)
rattle_budget = BASE_RATTLE_ALLOC * portfolio_value
catalyst_budget = BASE_CATALYST_ALLOC * portfolio_value
```

Where `recycled_amount` is computed from current rattle exposure but
is also bounded by `(MAX_COMPASS - BASE_COMPASS) * portfolio_value`.

This breaks the analogy with `HydraCapitalManager` (which tracks
buckets via daily returns) but is **stable**: budgets scale with
current PV, not with bucket accumulation. No feedback loop possible.

The derived bucket model can stay (for sub_sum == PV) — it just
becomes a reporting view, not the source of truth for budgeting.

**Estimated effort:** 2–3 hours.

### Option B — Restore live HCM percentage returns + loose canary

Revert the bucket update to live HCM `update_accounts_after_day_pure`
(percentage returns on bucket totals). Accept that buckets drift from
PV by a few percent over a long backtest. Relax the sub-account sum
canary to a much larger tolerance (say 5–10% of PV) so it only
catches truly catastrophic leaks.

This preserves the live HCM analogy and the existing
`update_accounts_after_day_pure` byte-identity test, but loses the
canary's sensitivity. The aggregate PV is still correct because it's
computed from positions + cash directly.

**Estimated effort:** 1 hour.

## Files changed in v1.4

```
hydra_backtest/hydra/
├── __init__.py        public API exports
├── __main__.py        CLI entrypoint
├── capital.py         HydraCapitalState + 4 pure functions
├── engine.py          run_hydra_backtest + 7 wrappers + EFA liquidation
├── state.py           HydraBacktestState + slicers + merger
├── validation.py      Layer A 12-invariant smoke tests
├── layer_b.py         Layer B comparison helper
├── README.md          architecture + status warning
└── tests/             39 unit + 1 integration + 3 E2E (slow)

docs/superpowers/specs/2026-04-07-hydra-backtest-v1.4-hydra-design.md
docs/superpowers/plans/2026-04-07-hydra-backtest-v1.4-hydra.md
docs/STATUS_v1.4_HYDRA.md  ← this file
.github/workflows/test.yml  (+1 step)
```

## Commits on v1.4 (chronological)

```
fff6a4c feat(hydra_backtest): bootstrap hydra sub-package + conftest
d3692e0 feat(hydra_backtest.hydra): HydraCapitalState + compute_allocation_pure
e384367 feat(hydra_backtest.hydra): update_accounts_after_day_pure + value updaters
bbdcd3d feat(hydra_backtest.hydra): HydraBacktestState + slicers
7454a74 feat(hydra_backtest.hydra): COMPASS sub-state wrappers
08d90ba feat(hydra_backtest.hydra): Rattle + Catalyst + EFA wrappers + liquidation
5c30855 feat(hydra_backtest.hydra): run_hydra_backtest orchestrator
d645e66 feat(hydra_backtest.hydra): Layer A 15-invariant smoke tests
a5d12fa feat(hydra_backtest.hydra): Layer B comparison helper
102daad test(hydra_backtest.hydra): capital + state unit tests
fb0e8de feat(hydra_backtest.hydra): wire public API exports
8c00b91 test(hydra_backtest.hydra): engine wrapper unit tests
cf69ccb test(hydra_backtest.hydra): validation unit tests
199a53d feat(hydra_backtest.hydra): CLI entrypoint with Layer B integration
24e0910 test(hydra_backtest.hydra): CLI integration smoke + 5 cascading fixes
2660d6b test(hydra_backtest.hydra): E2E tests (slow, real data)
d461d41 docs(hydra_backtest.hydra): README
94b4aed ci(hydra_backtest.hydra): add CI step for hydra tests
0b57bcc fix(hydra_backtest.hydra): catalyst double-counting + derived bucket model
```

19 commits, ~2200 LOC of new code, 0 modifications to v1.0–v1.3 or
to `hydra_capital.py` / live engine modules.

## Recommended next-session prompt

> Resume HYDRA v1.4 from `docs/STATUS_v1.4_HYDRA.md`. Implement
> Option A: replace `compass_budget = compass_account + recycled`
> with `compass_budget = min(BASE_COMPASS * portfolio_value +
> recycled, broker_cash)` in `hydra_backtest/hydra/engine.py`. Then
> re-run the integration smoke + a 1-year dry run on 2003 real
> data, and if the smoke test passes execute T19 (the official
> 2000-2026 run) in the background.
