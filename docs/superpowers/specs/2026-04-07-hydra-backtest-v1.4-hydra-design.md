# HYDRA Backtest v1.4 — Full HYDRA Integration — Design Spec

**Date**: 2026-04-07
**Status**: Draft — awaiting approval before plan + execute
**Predecessors**: v1.0 COMPASS, v1.1 Rattlesnake, v1.2 Catalyst, v1.3 EFA

## 1. Problem statement

`hydra_backtest/` v1.0–v1.3 ship four reproducible **standalone**
pillars. v1.4 is the integration: a single backtest that runs all
four together with **HydraCapitalManager-style cash recycling**, the
**Catalyst 15% ring-fence**, and **EFA overflow** of remaining idle
cash. This is the first version that produces a number directly
comparable to live HYDRA performance.

This is the most architecturally complex commit in the refactor. It
introduces no new strategy logic — instead it composes the four
existing pillar engines into one orchestrated daily loop.

## 2. Success criterion

A reproducible end-to-end HYDRA backtest that any auditor can run with
one command from a versioned commit and obtain byte-identical CSV
outputs. The result must:

- Mirror live order-of-operations on each trading day
- Mirror live cash recycling (Rattlesnake idle → COMPASS, capped at 75%)
- Mirror live Catalyst ring-fence (15%, never recycles)
- Mirror live EFA overflow (idle cash after recycling, ≥ $1k threshold,
  90% deployment cap)
- Mirror live EFA liquidation when active strategies need capital
- Produce per-pillar attribution (CAGR/Sharpe/MaxDD per pillar) AND
  the combined HYDRA metric
- Pass the v1.0 5-tier waterfall methodology

## 3. Scope (decided)

**In scope for v1.4**:
- New sub-package `hydra_backtest/hydra/`
- New `HydraBacktestState` extending v1.0's `BacktestState` with four
  logical sub-accounts and a position-tagging convention
- New `HydraCapitalState` (frozen-dataclass equivalent of
  `HydraCapitalManager` for the backtest world)
- New `run_hydra_backtest` orchestrator that calls the four pillar
  apply helpers in the live order, mediated by sub-state slicing
- Reuse of v1.0–v1.3 apply functions WITHOUT modification (the
  orchestrator passes them sub-state slices and merges results back)
- New cross-pillar Layer A invariants in
  `hydra/validation.py::run_hydra_smoke_tests`
- New CLI `python -m hydra_backtest.hydra` taking the union of all
  v1.0–v1.3 inputs
- 5-tier methodology waterfall via `build_waterfall` (strategy-agnostic)
- Per-pillar attribution sidecar JSON
- Layer B cross-validation: best-effort comparison against the live
  state JSONs in `state/compass_state_*.json` (informational only)

**Out of scope for v1.4 (deferred)**:
- Implementation Shortfall tracking (live has it; backtest doesn't need it)
- Order execution strategies (TWAP/VWAP/Passive — uses next_open or
  same_close like the standalone backtests)
- IBKR-specific features (commission tiers, MOC deadline, position
  reconciliation)
- Multi-thread safety (backtest is single-threaded)
- Position metadata round-tripping (backtest doesn't persist runtime state)
- v1.5 dashboard `hydra_clean_daily.csv` replacement — separate task

**Non-goals (explicit)**:
- Not modifying any of `hydra_backtest/{compass,rattlesnake,catalyst,efa}/`
- Not modifying `omnicapital_live.py`, `hydra_capital.py`,
  `rattlesnake_signals.py`, `catalyst_signals.py`
- Not introducing new strategy parameters
- Not modifying the methodology waterfall

## 4. Architecture

### 4.1 Sub-package layout

```
hydra_backtest/                                    ← v1.0+v1.1+v1.2+v1.3 (untouched)
└── hydra/                                         ← NEW v1.4 sub-package
    ├── __init__.py                                ← public exports
    ├── __main__.py                                ← CLI: python -m hydra_backtest.hydra
    ├── state.py                                   ← HydraBacktestState + HydraCapitalState
    ├── capital.py                                 ← compute_allocation_pure +
    │                                                update_accounts_after_day_pure
    ├── engine.py                                  ← run_hydra_backtest + per-pillar wrappers
    ├── validation.py                              ← cross-pillar Layer A smoke tests
    ├── README.md
    └── tests/
        ├── __init__.py
        ├── conftest.py                            ← hydra_minimal_config + fixtures
        ├── test_state.py                          ← position tagging, mark-to-market
        ├── test_capital.py                        ← cash recycling unit tests
        ├── test_engine.py                         ← orchestration unit tests
        ├── test_validation.py
        ├── test_integration.py                    ← CLI smoke
        └── test_e2e.py                            ← @pytest.mark.slow
.github/workflows/test.yml                         ← + new pytest step for hydra
```

### 4.2 Reuse vs new

| From v1.0–v1.3 | How |
|---|---|
| `BacktestState`, `BacktestResult` | Wrapped by `HydraBacktestState` |
| `_mark_to_market`, `_get_exec_price`, `_slice_history_to_date` | Direct imports |
| `data.load_*` (PIT, prices, SPY, VIX, catalyst, EFA, yields) | Direct imports |
| `methodology.build_waterfall` | Direct import |
| `reporting.write_*`, `format_summary_table` | Direct imports |
| `errors.HydraBacktestValidationError` | Direct import |
| `apply_exits`, `apply_entries` (COMPASS) | Called via sub-state wrapper |
| `apply_rattlesnake_exits`, `apply_rattlesnake_entries` | Called via sub-state wrapper |
| `apply_catalyst_rebalance` | Called via sub-state wrapper |
| `apply_efa_decision` | Called via sub-state wrapper |

### 4.3 New code in v1.4

| Module | LOC estimate |
|---|---:|
| `hydra/state.py` (HydraBacktestState + HydraCapitalState) | 150-200 |
| `hydra/capital.py` (pure-function HCM equivalents) | 100-150 |
| `hydra/engine.py` (run_hydra_backtest + 4 sub-state wrappers) | 400-500 |
| `hydra/validation.py` (cross-pillar smoke tests) | 150-200 |
| `hydra/__main__.py` (CLI) | 150-180 |
| `hydra/__init__.py` | 30 |
| Tests | 600-800 |
| `hydra/README.md` | 150 |
| **Total new** | **~1700 LOC** |

This is roughly 2× the size of any single previous pillar, reflecting
that v1.4 is integration code, not strategy code.

### 4.4 Guiding principle

**Compose, don't fork.** v1.0–v1.3 apply helpers are the single source
of truth for each pillar's behavior. v1.4 wraps them in sub-state
adapters but never duplicates their logic. If a future change to
Catalyst's rebalance behavior lands in v1.2, v1.4 picks it up
automatically on the next run.

## 5. State model

### 5.1 HydraBacktestState

```python
@dataclass(frozen=True)
class HydraBacktestState:
    """Combined state for the full HYDRA backtest.

    Wraps v1.0's BacktestState with sub-account accounting and a
    position-tagging convention.

    All positions live in a single dict (so _mark_to_market sees the
    whole portfolio). Each position's metadata includes a `_strategy`
    field identifying which pillar owns it:
        '_strategy' ∈ {'compass', 'rattle', 'catalyst', 'efa'}
    """
    # Shared broker-level state
    cash: float                       # ONE shared cash pool
    positions: dict                   # ALL positions, tagged by _strategy
    peak_value: float
    crash_cooldown: int
    portfolio_value_history: tuple

    # HYDRA logical accounting (mirrors hydra_capital.py)
    capital: 'HydraCapitalState'
```

`HydraBacktestState` is convertible to/from a plain `BacktestState` via
helpers `to_compass_substate(state)` etc., which build a temporary
`BacktestState` containing only the positions of one pillar plus the
pillar's allocated cash budget.

### 5.2 HydraCapitalState

```python
@dataclass(frozen=True)
class HydraCapitalState:
    """Pure-function equivalent of HydraCapitalManager.

    Logical accounting only — does NOT hold cash. The shared broker
    cash lives in HydraBacktestState.cash. These four numbers track
    how much each pillar 'owns' of total_value.
    """
    compass_account: float
    rattle_account: float
    catalyst_account: float
    efa_value: float

    base_compass_alloc: float = 0.425
    base_rattle_alloc: float = 0.425
    base_catalyst_alloc: float = 0.15
    max_compass_alloc: float = 0.75

    @property
    def total_capital(self) -> float:
        return (self.compass_account + self.rattle_account
                + self.catalyst_account + self.efa_value)

    def _replace(self, **kwargs) -> 'HydraCapitalState':
        return replace(self, **kwargs)
```

### 5.3 Position tagging convention

Every position dict added to `state.positions` MUST include
`'_strategy'` set to one of `'compass'|'rattle'|'catalyst'|'efa'`. The
sub-state wrappers use this tag to slice positions by pillar before
calling the existing apply helpers.

The standalone v1.0–v1.3 apply helpers never read `_strategy` (they
just see whatever positions are in their sliced state), so this is a
zero-impact convention.

## 6. Cash recycling — pure functions

`hydra/capital.py` ports `HydraCapitalManager.compute_allocation` and
`update_accounts_after_day` as pure functions:

```python
def compute_allocation_pure(
    capital: HydraCapitalState,
    rattle_exposure: float,
) -> dict:
    """Pure equivalent of HydraCapitalManager.compute_allocation.

    Returns dict with keys: compass_budget, rattle_budget,
    catalyst_budget, recycled_amount, efa_idle, compass_alloc,
    rattle_alloc, catalyst_alloc.
    """


def update_accounts_after_day_pure(
    capital: HydraCapitalState,
    compass_return: float,
    rattle_return: float,
    rattle_exposure: float,
) -> HydraCapitalState:
    """Pure equivalent of HydraCapitalManager.update_accounts_after_day.

    Settles recycled cash (which earns COMPASS returns) back into the
    rattle account at end-of-day. Returns a NEW HydraCapitalState.
    """
```

These mirror `hydra_capital.py:68-138` line-by-line — same math,
frozen-dataclass interface. Unit tests verify byte-identical results
against the live class.

## 7. Engine specification

### 7.1 Public function signature

```python
def run_hydra_backtest(
    config: dict,
    price_data: Dict[str, pd.DataFrame],     # COMPASS + Rattlesnake universe
    pit_universe: Dict[int, List[str]],       # PIT for COMPASS + Rattlesnake
    spy_data: pd.DataFrame,                   # COMPASS regime
    vix_data: pd.Series,                      # Rattlesnake panic
    catalyst_assets: Dict[str, pd.DataFrame], # Catalyst 4 ETFs
    efa_data: pd.DataFrame,                   # EFA single ETF
    cash_yield_daily: pd.Series,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    execution_mode: str = 'same_close',
    progress_callback: Optional[callable] = None,
) -> BacktestResult:
    """Run the full HYDRA backtest from start_date to end_date.

    Composes COMPASS + Rattlesnake + Catalyst + EFA via the v1.0-v1.3
    apply helpers, mediated by HydraCapitalState cash recycling.
    """
```

### 7.2 Per-day order of operations

Mirrors `omnicapital_live.py::execute_preclose_entries` (line 2972):

```
For each trading day in [start_date, end_date]:

  1. Mark-to-market — _mark_to_market on the full state.positions dict
  2. Update peak before drawdown
  3. Apply daily cash yield (Aaa or T-bill on cash, not on positions)
  4. Compute current rattle_exposure (sum of rattle positions / rattle_account)
  5. Compute compass_budget, rattle_budget, catalyst_budget, efa_idle
     via compute_allocation_pure

  --- COMPASS ---
  6. apply_compass_exits_wrapper(state)
     → builds compass-only sub-state, calls v1.0 apply_exits, merges back
  7. apply_compass_entries_wrapper(state, compass_budget)
     → builds compass sub-state with cash=compass_budget, calls v1.0
       apply_entries, merges back (only deducts from real cash by the
       amount actually spent)

  --- EFA LIQUIDATION (if active strategies need capital) ---
  8. If broker_cash < 20% portfolio_value AND
        (compass slots open OR rattle has signals) AND efa_held:
       apply_efa_liquidation(state)  ← mirrors _liquidate_efa_for_capital

  --- RATTLESNAKE ---
  9. apply_rattle_exits_wrapper(state)
  10. apply_rattle_entries_wrapper(state, rattle_budget)

  --- CATALYST ---
  11. catalyst_day_counter += 1
  12. If counter >= CATALYST_REBALANCE_DAYS or no catalyst positions:
        apply_catalyst_rebalance_wrapper(state, catalyst_budget)

  --- EFA ---
  13. apply_efa_decision_wrapper(state, efa_idle)
        ← uses efa_idle from compute_allocation_pure, applies the
          $1k min-buy threshold and 90% deployment cap inside the wrapper

  --- ACCOUNTING ---
  14. Compute c_ret and r_ret from per-pillar position value changes
  15. update_accounts_after_day_pure(capital, c_ret, r_ret, rattle_exposure)
  16. Snapshot day with per-pillar breakdown
```

### 7.3 Sub-state wrapper pattern

Each pillar wrapper looks like:

```python
def apply_compass_entries_wrapper(
    state: HydraBacktestState,
    compass_budget: float,
    date, i, price_data, pit_universe, spy_data, config, execution_mode, all_dates,
) -> Tuple[HydraBacktestState, list, list]:
    # 1. Build compass-only sub-state with cash = compass_budget
    compass_positions = {
        sym: pos for sym, pos in state.positions.items()
        if pos.get('_strategy') == 'compass'
    }
    compass_substate = BacktestState(
        cash=compass_budget,                       # NOT state.cash
        positions=compass_positions,
        peak_value=state.peak_value,
        crash_cooldown=state.crash_cooldown,
        portfolio_value_history=state.portfolio_value_history,
    )

    # 2. Call existing v1.0 apply_entries (untouched)
    new_substate, decisions = apply_entries(
        compass_substate, date, i, price_data, ...
    )

    # 3. Compute cash actually spent
    spent = compass_budget - new_substate.cash

    # 4. Merge back into the full state:
    #    - Deduct `spent` from real broker cash
    #    - Add new compass positions (tagged with _strategy='compass')
    #    - Update compass_account by -spent
    new_compass_positions = {
        sym: {**pos, '_strategy': 'compass'}
        for sym, pos in new_substate.positions.items()
    }
    other_positions = {
        sym: pos for sym, pos in state.positions.items()
        if pos.get('_strategy') != 'compass'
    }
    merged_positions = {**other_positions, **new_compass_positions}

    new_capital = state.capital._replace(
        compass_account=state.capital.compass_account - spent,
    )
    new_state = state._replace(
        cash=state.cash - spent,
        positions=merged_positions,
        capital=new_capital,
    )
    return new_state, [], decisions
```

The same pattern applies for the other 7 wrappers (compass exits,
rattle exits/entries, catalyst rebalance, efa decision/liquidation).
Each wrapper is ~30-50 LOC of state slicing + a single call to the
underlying v1.0–v1.3 helper.

## 8. Data flow

```
CLI (hydra/__main__.py)
    │
    ▼
data.py loaders (PIT, prices, SPY, VIX, catalyst, EFA, yields)
    │
    ▼
hydra/engine.py::run_hydra_backtest()
    │
    └─ for each trading day in [start, end]:
        1. mark-to-market full portfolio
        2. cash yield on cash
        3. compute_allocation_pure → budgets
        4. compass exits wrapper → state'
        5. compass entries wrapper(compass_budget) → state''
        6. efa liquidation if needed → state'''
        7. rattle exits wrapper → state''''
        8. rattle entries wrapper(rattle_budget) → ...
        9. catalyst rebalance wrapper(catalyst_budget) every 5 days
        10. efa decision wrapper(efa_idle)
        11. update_accounts_after_day_pure → new HydraCapitalState
        12. snapshot day with per-pillar breakdown
    │
    ▼
hydra/validation.run_hydra_smoke_tests (Layer A blocking)
    │
    ▼
methodology.build_waterfall (REUSED — 5 tiers)
    │
    ▼
reporting writers (REUSED) + sidecar attribution JSON
    │
    ▼
backtests/hydra_v1/hydra_v2_{daily,trades}.csv
backtests/hydra_v1/hydra_v2_waterfall.json
backtests/hydra_v1/hydra_v2_attribution.json
```

## 9. Layer A smoke tests (cross-pillar)

`hydra/validation.py::run_hydra_smoke_tests` enforces:

**Mathematical (shared with v1.0–v1.3)**:
1. No NaN in critical columns
2. Cash never < -1.0
3. Drawdown ∈ [-1.0, 0]
4. Peak monotonic non-decreasing
5. Vol ann ∈ [0.5%, 50%]
6. No outlier daily returns > ±15% (allowlist crash days)

**HYDRA-specific cross-pillar**:
7. `n_compass_positions ≤ MAX_COMPASS_POSITIONS` (typically 5)
8. `n_rattle_positions ≤ R_MAX_POSITIONS` (typically 5)
9. `n_catalyst_positions ≤ 4` (CATALYST_TREND_ASSETS)
10. `n_efa_positions ≤ 1`
11. Trade exit reasons ⊆ union of {COMPASS exit reasons, R_*, CATALYST_*, EFA_*}
12. **Sub-account sum invariant**: `compass_account + rattle_account + catalyst_account + efa_value` should equal `portfolio_value` to within $1.00 tolerance every day. (This is the most important new check — it validates that recycling doesn't leak cash.)
13. **Recycling cap invariant**: `recycled_amount ≤ max_compass_alloc * total_capital - base_compass_alloc * total_capital`
14. **Catalyst ring-fence invariant**: `catalyst_account` change between days must equal Catalyst position P&L (ring-fence: no recycling in/out)
15. **Position tag completeness**: every position in `state.positions` must have `_strategy` set

## 10. Per-pillar attribution

Sidecar `hydra_v2_attribution.json` contains:

```json
{
  "compass":   {"cagr": 0.1257, "sharpe": 0.793, "max_dd": -0.299, "trades": 1234, "final_value": 543210},
  "rattle":    {"cagr": 0.0xxx, ...},
  "catalyst":  {"cagr": 0.1195, ...},
  "efa":       {"cagr": 0.0746, ...},
  "hydra":     {"cagr": 0.1xxx, ...},
  "recycling": {
      "total_days": 6515,
      "recycled_days": 4892,
      "recycling_frequency": 0.751,
      "avg_recycled_pct": 0.18,
      "max_recycled_pct": 0.34
  }
}
```

This is informational only — the canonical metric is the
`hydra_v2_waterfall.json` net_honest tier on the combined HYDRA series.

## 11. Methodology waterfall (identical to v1.0–v1.3)

Same 5 tiers via `build_waterfall`. The full HYDRA backtest is
re-run three times (Aaa same_close → T-bill same_close → T-bill
next_open) and post-processed for tier 3.

Estimated runtime: ~15-20 minutes for the full 2000-2026 run with
all four pillars active. (COMPASS dominates the runtime; the other
three are O(seconds).)

## 12. Layer B cross-validation (best-effort, non-blocking)

`backtests/hydra_v1/layer_b_report.json` (informational):

- Compare v1.4 daily HYDRA series against the existing
  `backtests/hydra_v1_official/hydra_clean_daily.csv` (the dashboard's
  current source of truth).
- Compute correlation, mean abs error, max abs error.
- **Non-blocking**: any divergence is reported but does not fail the run.
- Acceptance threshold (informational): Spearman correlation ≥ 0.95
  on daily portfolio_value.

## 13. CLI

```bash
python -m hydra_backtest.hydra \
    --start 2000-01-01 \
    --end 2026-03-05 \
    --out-dir backtests/hydra_v1
```

Defaults pull from `data_cache/`:
- `sp500_constituents_history.pkl` (PIT for COMPASS+Rattlesnake)
- `sp500_universe_prices.pkl` (price history)
- `SPY_2000-01-01_2027-01-01.csv`
- `vix_history.csv`
- `catalyst_assets.pkl`
- `efa_history.pkl`
- `moody_aaa_yield.csv`, `tbill_3m_fred.csv`

Outputs:
- `hydra_v2_daily.csv`
- `hydra_v2_trades.csv`
- `hydra_v2_waterfall.json`
- `hydra_v2_attribution.json`
- `layer_b_report.json` (if `hydra_clean_daily.csv` exists)

## 14. Testing strategy

| Test | What it proves |
|---|---|
| `test_hydra_capital_state_pure_matches_live` | `compute_allocation_pure` and `update_accounts_after_day_pure` produce byte-identical results vs live `HydraCapitalManager` over a synthetic 100-day sequence |
| `test_substate_slice_round_trip` | slicing positions by `_strategy` and merging back is lossless |
| `test_position_tag_invariant` | every position added by every wrapper has `_strategy` set |
| `test_compass_wrapper_uses_budget_not_cash` | COMPASS entries are bounded by `compass_budget`, not the broker cash (which may be much larger) |
| `test_recycling_caps_at_75pct` | when Rattlesnake is 100% idle, COMPASS budget is exactly `0.75 * total_capital` |
| `test_catalyst_ring_fence` | Catalyst account never changes from non-Catalyst trades |
| `test_efa_liquidation_when_compass_short_on_capital` | mirrors live `_liquidate_efa_for_capital` |
| `test_efa_overflow_only_uses_remaining_idle` | EFA buys are capped at `efa_idle` from `compute_allocation_pure`, not the full broker cash |
| `test_run_hydra_backtest_smoke` | full synthetic 1-year run completes |
| `test_smoke_tests_sub_account_sum_invariant` | catches cash leaks |
| `test_e2e_full_run` | full 2000-2026 with real data |
| `test_e2e_determinism` | two runs produce byte-identical outputs |
| `test_e2e_layer_b_correlation` | Spearman ≥ 0.95 vs `hydra_clean_daily.csv` |

Coverage target: 80% in `hydra_backtest/hydra/`.

## 15. Roadmap context

| Version | Status | Contains |
|---|---|---|
| v1.0 | ✅ DONE | COMPASS standalone |
| v1.1 | ✅ DONE | Rattlesnake standalone |
| v1.2 | ✅ DONE | Catalyst standalone |
| v1.3 | ✅ DONE | EFA standalone |
| **v1.4** | ← THIS | HYDRA full integration |
| v1.5 | pending | Replace dashboard `hydra_clean_daily.csv` with v1.4 output |

## 16. Success criteria (measurable)

v1.4 is complete when:

1. `python -m hydra_backtest.hydra --start 2000-01-01 --end 2026-03-05`
   runs to completion without errors
2. Two consecutive runs produce byte-identical `hydra_v2_daily.csv`
3. All Layer A smoke tests (15 invariants) pass for all 3 tier runs
4. Coverage ≥ 80% for `hydra_backtest/hydra/`
5. v1.0 + v1.1 + v1.2 + v1.3 test suites remain green
6. Waterfall report prints 5 tiers
7. Sub-account sum invariant holds within $1.00 tolerance every day
8. Layer B Spearman correlation ≥ 0.95 vs `hydra_clean_daily.csv`
   (informational; if it fails, document the divergence root cause but
   do not block the release)
9. `hydra_v2_attribution.json` present with per-pillar metrics
10. `hydra_capital.py` and the four pillar packages remain unmodified

v1.4 does NOT require:
- Beating the live HYDRA performance number
- Matching `hydra_clean_daily.csv` byte-for-byte (different methodology
  for execution costs and the dashboard CSV may have its own quirks)
- Modifying live code or the standalone backtests

## 17. Risks & open questions

| Risk | Mitigation |
|---|---|
| Sub-state slicing introduces a position-tag bug that orphans positions across days | Layer A invariant 15 catches missing tags; round-trip test (test 2) catches lossy slice/merge |
| Cash recycling math drifts from live HCM | Layer A invariant 12 (sub-account sum) is the canary; test 1 verifies pure functions byte-identical to live class |
| Order of operations differs from live in subtle ways → results don't match dashboard | Spec §7.2 enumerates the exact order; Layer B correlation check measures divergence |
| Per-pillar return attribution for HCM accounting drifts (live uses `compass_invested / compass_prev_invested`, may not match summing trade PnLs) | Mirror live's exact formula in `_compute_pillar_returns`; document the approximation in the README |
| Runtime > 20 minutes for full 2000-2026 run blocks E2E tests | Mark as `@pytest.mark.slow`; CI uses `not slow` filter |
| Cross-strategy position symbol collision (e.g. EFA ends up in COMPASS PIT universe) | EFA is in `_CATALYST_EFA_TICKERS` exclude list in live; v1.4 inherits the exclusion via PIT loading |
| Position-tag convention may collide with existing v1.0–v1.3 positions that don't have `_strategy` | Wrappers ALWAYS add the tag when creating new positions; sub-state extractors filter by tag and the standalone helpers never read `_strategy` so adding it is invisible to them |
