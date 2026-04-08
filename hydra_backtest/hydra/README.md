# hydra_backtest.hydra — Full HYDRA Integration Backtest

The fifth and final piece of the `hydra_backtest/` refactor: a single
backtest that orchestrates all four standalone pillars (COMPASS,
Rattlesnake, Catalyst, EFA) with HydraCapitalManager-style cash
recycling, the Catalyst 15% ring-fence, and EFA overflow.

## ✅ Status: COMPLETE — official 2000-2026 run shipped 2026-04-08

All 19 tasks done. The official run produced **NET HONEST 10.70%
CAGR / 0.591 Sharpe / -32.73% MaxDD** ($100k → $1.45M over 2000-2026)
with Layer B verdict **PASS Spearman 0.9958** vs the production
dashboard's `hydra_clean_daily.csv`.

**47 unit tests** pass (17 capital + 13 state + 8 engine wrapper +
11 validation), plus 1 CLI integration smoke + 3 E2E real-data
tests. v1.0–v1.3 suites unchanged (138 tests still green).

The original Task 19 blocker (a feedback loop in the derived bucket
budget hack) was resolved by **Option C**: NAV-derived budgets via
the new pure function `compute_budgets_from_snapshot` in `capital.py`.
Budgets now depend ONLY on the current economic snapshot
(positions + cash + prices + nav), never on accumulated
HydraCapitalState buckets. Replay determinism is enforced by unit
test.

A second critical bug was discovered while validating Option C on
real 2000 data: a **symbol collision** in `merge_pillar_substate`
silently overwrote prior pillars' positions when two pillars held
the same symbol (e.g., GE held by compass at $11k AND picked by
rattle on 2000-01-07). Fixed by filtering cross-pillar held symbols
in compass and rattle entry wrappers, plus a defensive assertion in
`merge_pillar_substate` that raises ValueError on any collision.

## What this is

A Python sub-package that runs the full HYDRA system from 2000 to
2026 with the same order-of-operations as live (per-day flow mirrors
`omnicapital_live.py::execute_preclose_entries`), producing a
waterfall methodology report and per-pillar attribution columns in
the daily CSV.

## Architecture (the 30-second version)

```
hydra_backtest/hydra/
├── capital.py           HydraCapitalState + pure function ports of
│                        HydraCapitalManager.compute_allocation /
│                        update_accounts_after_day / update_efa_value /
│                        update_catalyst_value
├── state.py             HydraBacktestState (frozen dataclass) +
│                        slice_positions_by_strategy +
│                        to_pillar_substate + merge_pillar_substate +
│                        compute_pillar_invested[_at_prev_close]
├── engine.py            run_hydra_backtest + 7 sub-state wrappers +
│                        EFA liquidation helper
├── validation.py        run_hydra_smoke_tests (Layer A invariants)
├── layer_b.py           compute_layer_b_report (informational)
├── __main__.py          CLI: python -m hydra_backtest.hydra
└── tests/
    ├── test_capital.py        9 unit tests incl. byte-identity vs live
    ├── test_state.py          11 unit tests for slice/merge/round-trip
    ├── test_engine.py         8 wrapper unit tests
    ├── test_validation.py     11 smoke check unit tests
    ├── test_integration.py    CLI smoke against synthetic 7-input fixtures
    └── test_e2e.py            3 @pytest.mark.slow real-data tests
```

**Compose, don't fork.** v1.0–v1.3 apply helpers are the single source
of truth for each pillar's behavior. v1.4 wraps them in sub-state
adapters but never duplicates their logic. If a future change to
Catalyst's rebalance behavior lands in v1.2, v1.4 picks it up
automatically on the next run.

## Position tagging

Every position in `state.positions` carries `_strategy ∈
{compass, rattle, catalyst, efa}`. The sub-state wrappers slice by
this tag before calling the existing v1.0–v1.3 helpers, then re-tag
new positions during the merge back. The standalone helpers never
read `_strategy` so the convention is invisible to them.

## Cash recycling math

`hydra/capital.py` ports `HydraCapitalManager.compute_allocation` and
`update_accounts_after_day` line-by-line as pure functions over a
frozen `HydraCapitalState` dataclass. A 100-day random sequence test
in `test_capital.py::test_update_accounts_after_day_byte_identical_100d`
verifies byte-identical results vs the live class.

The four logical accounts (`compass_account`, `rattle_account`,
`catalyst_account`, `efa_value`) sum to total_capital. They evolve
via:
- **Daily dollar returns** on each pillar's positions (the v1.4
  divergence from live — see "Divergence from live HCM" below)
- **EFA buy/sell**: inter-bucket transfer between rattle and efa
  (mirrors `buy_efa` / `sell_efa` in live HCM)
- **Recycling settlement**: handled inside `compute_allocation_pure`
  on each call

## How to run

```bash
python -m hydra_backtest.hydra \
    --start 2000-01-01 \
    --end 2026-03-05 \
    --out-dir backtests/hydra_v1
```

Defaults pull from `data_cache/`:
- `sp500_constituents_history.pkl` (PIT for COMPASS+Rattlesnake)
- `sp500_universe_prices.pkl`
- `sp500_sector_map.json`
- `SPY_2000-01-01_2027-01-01.csv`
- `vix_history.csv`
- `catalyst_assets.pkl` (built in v1.2)
- `efa_history.pkl` (built in v1.3)
- `moody_aaa_yield.csv`, `tbill_3m_fred.csv`

Outputs in `backtests/hydra_v1/`:
- `hydra_v2_daily.csv` — daily snapshot with per-pillar columns
  (compass_account, rattle_account, catalyst_account, efa_value,
  recycled_pct, n_compass, n_rattle, n_catalyst, n_efa)
- `hydra_v2_trades.csv` — closed trades from all four pillars
- `hydra_v2_waterfall.json` — 5-tier methodology report
- `layer_b_report.json` — Spearman correlation vs `hydra_clean_daily.csv`
  (informational)
- `run.log` — full progress trace

Estimated runtime: 15–20 min for the full 2000-2026 run.

## Per-day order of operations

Mirrors `omnicapital_live.py::execute_preclose_entries` (line 2972):

1. Mark-to-market the full portfolio
2. Update peak before drawdown
3. Apply daily cash yield (distributed proportionally to all 4 buckets)
4. Compute COMPASS scoring inputs (regime, leverage, max_pos,
   quality, momentum)
5. Capture pure price-only daily returns for all 4 pillars (BEFORE
   any wrapper mutates positions, so trade activity doesn't
   contaminate the return calc)
6. COMPASS exits wrapper
7. EFA liquidation if compass slots open or rattle signals pending
   AND broker cash < 20% of PV
8. COMPASS entries wrapper (cash-budget hack: substate.cash =
   min(compass_budget, broker_cash))
9. Rattlesnake exits + entries wrapper
10. Catalyst rebalance every CATALYST_REBALANCE_DAYS or whenever
    catalyst is empty
11. EFA passive overflow wrapper (uses idle cash after recycling,
    enforces $1k min-buy and 90% deployment cap)
12. Apply dollar returns to all 4 capital buckets
13. Snapshot day with 11 per-pillar columns
14. Stamp `_prev_close` on each position for the next day's daily
    return calc

## Layer A invariants

`run_hydra_smoke_tests` enforces:

**Math (shared with v1.0–v1.3):**
1. No NaN in critical columns
2. Cash never < -1.0
3. Drawdown ∈ [-1.0, 0]
4. Peak monotonic non-decreasing
5. Annualized vol ∈ [0.5%, 50%]
6. No outlier daily returns > ±15% (allowlist crash days)

**HYDRA-specific cross-pillar:**
7. n_compass ≤ 10
8. n_rattle ≤ 10
9. n_catalyst ≤ 4
10. n_efa ≤ 1
11. Trade exit reasons ⊆ union of all four pillar reasons +
    `EFA_LIQUIDATED_FOR_CAPITAL`
12. **Sub-account sum invariant** (the cash-leak canary):
    `compass_account + rattle_account + catalyst_account + efa_value`
    must equal `portfolio_value` within max(0.5% of PV, $500). This
    catches large cash leaks while accepting the small numerical
    drift from cash yield distribution rounding.

The recycling cap invariant (`compass_budget ≤ MAX * total_capital`)
is **enforced by construction** inside `compute_allocation_pure` and
covered by `test_compute_allocation_full_idle_rattle_caps_at_75pct`,
not by a snapshot check.

## Layer B comparison

`hydra/layer_b.py::compute_layer_b_report` aligns v1.4's daily
portfolio_value against `backtests/hydra_clean_daily.csv` (the
dashboard's source of truth) and computes Spearman + Pearson
correlation, MAE, max_err. **Non-blocking**: returns `SKIPPED` if
the reference CSV is missing or has < 100 overlapping days. The
verdict (`PASS` if Spearman ≥ 0.95, `INVESTIGATE` otherwise) is
informational — divergence may be legitimate (the dashboard CSV has
its own methodology history and quirks).

## Divergence from live HCM (intentional)

v1.4 diverges from `hydra_capital.py` in one specific place: it uses
**dollar returns** to evolve the capital buckets instead of percentage
returns. The reason:

- Live HCM: `compass_account *= (1 + compass_return)` — applies a
  percentage return to the bucket TOTAL (positions + implicit cash
  share). Only positions actually move, so the cash share gets a
  phantom return → bucket drifts away from PV.
- v1.4: `compass_account += sum(compass position dollar appreciation)`
  — adds the actual dollar movement of compass positions. This
  preserves `sum(buckets) == PV` exactly (modulo cash yield
  distribution noise).

Live tolerates the drift because 5-day position rotation auto-corrects
it. In long backtests it accumulates. The v1.4 model is mathematically
cleaner and gives a defensible per-pillar attribution that always sums
to the canonical PV.

This divergence does NOT affect the aggregate PV (which is computed
fresh from positions + cash on every snapshot). It only affects how
the per-pillar attribution is reported.

## Constants duplicated from hydra_capital.py

To avoid pulling the heavy `omnicapital_live.py` import surface into
the backtest, four allocation constants are duplicated as
module-level globals in `hydra/capital.py`:

```python
BASE_COMPASS_ALLOC = 0.425   # mirrors hydra_capital.py:22
BASE_RATTLE_ALLOC = 0.425    # mirrors hydra_capital.py:23
BASE_CATALYST_ALLOC = 0.15   # mirrors hydra_capital.py:24
MAX_COMPASS_ALLOC = 0.75     # mirrors hydra_capital.py:25
EFA_MIN_BUY = 1000.0         # mirrors hydra_capital.py:26
EFA_DEPLOYMENT_CAP = 0.90    # 90% cap from omnicapital_live.py:2484
```

If live ever changes these values, this duplication is the only
contract surface to keep in sync. v1.5 may extract a shared constants
module to eliminate the duplication.

## v1.4 limitations (deferred to later versions or non-goals)

- **No Implementation Shortfall tracking** — live has it via the
  `_submit_order` execution-strategy hook, but the backtest assumes
  same-close or next-open execution exclusively
- **No execution strategies (TWAP, VWAP, Smart, etc.)** — only
  same-close and next-open via `execution_mode` parameter
- **No IBKR-specific features** — commission tiers, MOC deadline,
  position reconciliation
- **No multi-thread safety** — backtest is single-threaded
- **No position metadata round-tripping** — backtest doesn't persist
  runtime state across runs
- **Per-pillar attribution is approximate** — see "Divergence from
  live HCM" above. The aggregate PV is exact; the bucket breakdown
  has small numerical noise from cash yield distribution

## Roadmap

| Version | Status | Contains |
|---|---|---|
| v1.0 | ✅ DONE | COMPASS standalone |
| v1.1 | ✅ DONE | Rattlesnake standalone |
| v1.2 | ✅ DONE | Catalyst standalone |
| v1.3 | ✅ DONE | EFA standalone |
| **v1.4** | ✅ THIS | Full HYDRA integration |
| v1.5 | pending | Replace dashboard `hydra_clean_daily.csv` with v1.4 output |

## See also

- Spec: `docs/superpowers/specs/2026-04-07-hydra-backtest-v1.4-hydra-design.md`
- Plan: `docs/superpowers/plans/2026-04-07-hydra-backtest-v1.4-hydra.md`
- Live consumer: `omnicapital_live.py::COMPASSLive.execute_preclose_entries`
- Live capital manager: `hydra_capital.py::HydraCapitalManager`
