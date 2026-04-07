# HYDRA Backtest v1.1 — Rattlesnake Standalone Pillar — Design Spec

**Date**: 2026-04-07
**Status**: Approved — proceeding to plan
**Author**: Claude Code brainstorming session
**Predecessor**: `2026-04-06-hydra-reproducible-backtest-design.md` (v1.0 COMPASS standalone)

## 1. Problem statement

`hydra_backtest/` v1.0 ships a reproducible COMPASS standalone backtest that
demonstrated the legacy dashboard number (CAGR 14.47%, Sharpe 1.01,
MaxDD -22.2%) is a 4-layer Frankenstein with no source code chain. The
honest COMPASS standalone result over 2000-2026 with PIT universe is
**CAGR 5.97%, Sharpe 0.387, MaxDD -21.11%** — well below the dashboard
number, but COMPASS alone under-states HYDRA because it omits the other
three pillars (Rattlesnake mean-reversion, Catalyst cross-asset trend,
EFA international diversification) and cash recycling.

This spec covers **v1.1: Rattlesnake standalone**, the second milestone
in the v1.0 incremental roadmap (§13). It adds Rattlesnake as a separate
sub-package that mirrors the v1.0 architecture but with mean-reversion
signal logic instead of momentum. It does NOT integrate with COMPASS or
introduce cash recycling — those land in v1.4 (HYDRA full).

Why standalone first: building Rattlesnake in isolation lets us validate
the signal/exit/entry logic against an independent reference
(`archive/strategies/rattlesnake_v1.py`) before introducing the
complexity of cash recycling. Same incremental philosophy as v1.0.

## 2. Success criterion

Same as v1.0: defendible publicly. A reproducible end-to-end Rattlesnake
backtest that any auditor can run with a single command from a versioned
commit and obtain byte-identical CSV outputs. Methodology defensible
under academic peer review (PIT universe, T-bill cash yield, realistic
execution model, per-trade costs).

## 3. Scope (decided)

**In scope for v1.1**:
- Rattlesnake standalone backtest as a sub-package `hydra_backtest/rattlesnake/`
- PIT universe = `R_UNIVERSE ∩ PIT_S&P500` per year (drops survivorship bias
  without requiring fresh PIT S&P 100 data)
- Signal logic imported from `rattlesnake_signals.py` (the live engine
  module, already fail-closed on VIX as of commit `b9d4ad7`)
- Same waterfall methodology as v1.0 (5 tiers: baseline → +T-bill →
  +next-open → +slippage → net_honest)
- Layer A smoke tests (blocking) adapted to Rattlesnake mechanics
- Layer B cross-validation against `archive/strategies/rattlesnake_v1.py`
  (best-effort — non-blocking if the archive script can't run)
- New VIX historical data loader added to `data.py` (~30 LOC)
- New CLI: `python -m hydra_backtest.rattlesnake`
- Output schema compatible with v1.0 (drop-in for future merging)

**Out of scope for v1.1 (deferred)**:
- HydraCapitalManager integration / cash recycling — v1.4
- COMPASS+Rattlesnake combined run — v1.4
- Catalyst, EFA pillars — v1.2, v1.3
- Walk-forward Layer C against live state JSONs — v1.2 (needs schema parser)
- Dashboard replacement — v1.5 (after HYDRA full lands in v1.4)
- VIX missing-data handling beyond fail-closed default — v1.4

**Explicit non-goals**:
- Not refactoring `omnicapital_live.py` or `rattlesnake_signals.py` (the
  consumer-not-owner principle from v1.0 applies)
- Not changing Rattlesnake parameters (R_PROFIT_TARGET=+4%, R_STOP_LOSS=-5%,
  R_HOLD_DAYS=8, R_MAX_POSITIONS=5/2)
- Not adding new strategies or modifying signal computation
- Not optimizing Rattlesnake parameters via grid search

## 4. Architecture

### 4.1 Sub-package layout

```
hydra_backtest/                       ← v1.0 (untouched)
├── __init__.py
├── __main__.py                       ← v1.0 COMPASS CLI
├── data.py                           ← REUSED (with new load_vix_series helper)
├── engine.py                         ← REUSED (BacktestState, BacktestResult, _mark_to_market, _get_exec_price)
├── methodology.py                    ← REUSED (waterfall, compute_metrics)
├── reporting.py                      ← REUSED
├── validation.py                     ← REUSED (run_smoke_tests still exists for COMPASS)
├── errors.py                         ← REUSED
├── tests/                            ← v1.0 tests stay green
├── README.md
└── rattlesnake/                      ← NEW v1.1 sub-package
    ├── __init__.py                   ← public exports
    ├── __main__.py                   ← CLI entrypoint
    ├── engine.py                     ← run_rattlesnake_backtest + apply_rattlesnake_*
    ├── validation.py                 ← run_rattlesnake_smoke_tests (Rattlesnake-adapted)
    ├── tests/
    │   ├── __init__.py
    │   ├── conftest.py               ← rattlesnake_minimal_config fixture
    │   ├── test_engine.py
    │   ├── test_validation.py
    │   ├── test_integration.py
    │   └── test_e2e.py               ← @pytest.mark.slow
    └── README.md
```

### 4.2 Reuse vs new code

| From v1.0 | Reuse? | How |
|---|---|---|
| `BacktestState` (frozen dataclass) | ✅ | Direct import. Rattlesnake leaves `peak_value`/`crash_cooldown` in defaults |
| `BacktestResult` (frozen dataclass) | ✅ | Direct import. Same `daily_values`/`trades` schema |
| `_mark_to_market`, `_get_exec_price`, `_slice_history_to_date` | ✅ | Direct imports from `hydra_backtest.engine` |
| `data.py` loaders | ✅ | All existing loaders. NEW: `load_vix_series` (added to data.py) |
| `methodology.py` (build_waterfall, compute_metrics) | ✅ | Strategy-agnostic |
| `reporting.py` (write_*, format_summary_table) | ✅ | Strategy-agnostic |
| `errors.py` | ✅ | Same exception hierarchy |
| `validation.py::run_smoke_tests` | ⚠️ | Stays as-is for COMPASS. Rattlesnake gets its own `run_rattlesnake_smoke_tests` |

### 4.3 New code in v1.1

| Module | LOC estimate | Responsibility |
|---|---:|---|
| `rattlesnake/engine.py` | 250-300 | run_rattlesnake_backtest + 2 pure helpers (apply_*) |
| `rattlesnake/validation.py` | 100-150 | Smoke tests adapted to Rattlesnake mechanics |
| `rattlesnake/__main__.py` | 80-120 | CLI with argparse + progress callback |
| `rattlesnake/__init__.py` | 30 | Public API exports |
| `data.py::load_vix_series` (added) | 30 | yfinance ^VIX or CSV loader |
| Tests | 400-500 | Unit + integration + E2E |
| `rattlesnake/README.md` | 80 | Usage, architecture, limitations |
| **Total new** | **~1,000 LOC** | |

### 4.4 Guiding principle (inherited from v1.0)

`rattlesnake/engine.py` is a **consumer**, not owner, of Rattlesnake
signal logic. Pure functions are imported directly from
`rattlesnake_signals.py`:

```python
from rattlesnake_signals import (
    R_UNIVERSE,                  # hardcoded S&P 100 (94 tickers, intersected with PIT)
    R_HOLD_DAYS, R_MAX_HOLD_DAYS,
    R_PROFIT_TARGET, R_STOP_LOSS,
    R_MAX_POSITIONS, R_MAX_POS_RISK_OFF,
    R_POSITION_SIZE, R_VIX_PANIC,
    R_MIN_AVG_VOLUME,
    check_rattlesnake_regime,    # already fail-closed (commit b9d4ad7)
    find_rattlesnake_candidates, # signal core
    check_rattlesnake_exit,      # exit logic (PROFIT/STOP/TIME)
)
```

If the live module is updated, the backtest absorbs the changes
automatically. The reimplemented surface (apply_rattlesnake_exits,
apply_rattlesnake_entries) is ~200 LOC of pure functions with parity
tests against the live class methods.

## 5. Data flow

```
CLI (rattlesnake/__main__.py)
    │
    ▼
data.py loaders (PIT, prices, SPY, VIX, T-bill, Aaa)
    │
    ▼
rattlesnake/engine.py::run_rattlesnake_backtest()
    │
    └─ for each trading day in [start, end]:
        1. _mark_to_market (reused)
        2. Update peak BEFORE drawdown (mirrors v1.0)
        3. Resolve PIT universe: R_UNIVERSE ∩ pit_universe[year]
        4. check_rattlesnake_regime(spy_slice, vix_at_date)
           → entries_allowed, max_positions
        5. apply_daily_costs (cash yield only — no leverage in Rattlesnake)
        6. apply_rattlesnake_exits (NEW pure fn — see §6)
        7. apply_rattlesnake_entries (NEW pure fn — see §6)
        8. Snapshot day (date, portfolio_value, cash, n_positions, drawdown,
           regime, vix_panic, max_positions)
        9. Increment days_held for ALL open positions
    │
    ▼
BacktestResult (raw tier 0)
    │
    ▼
methodology.py::build_waterfall (REUSED)
    │
    ├─ tier_0: Aaa cash, same_close
    ├─ tier_1: + T-bill (re-run)
    ├─ tier_2: + next_open (re-run)
    ├─ tier_3: + slippage 5bps round-trip (post-process of tier_2)
    └─ net_honest (alias of tier_3)
    │
    ▼
rattlesnake/validation.py::run_rattlesnake_smoke_tests (Layer A blocking)
    │
    ▼
reporting.py writers (REUSED)
    │
    ▼
backtests/rattlesnake_v1/rattlesnake_v2_{daily,trades}.csv
backtests/rattlesnake_v1/rattlesnake_v2_waterfall.json
```

## 6. Engine specification

### 6.1 Public function signature

```python
# hydra_backtest/rattlesnake/engine.py

def run_rattlesnake_backtest(
    config: dict,                       # Rattlesnake config (subset of full COMPASS config)
    price_data: Dict[str, pd.DataFrame],
    pit_universe: Dict[int, List[str]], # PIT S&P 500 (will intersect with R_UNIVERSE)
    spy_data: pd.DataFrame,
    vix_data: pd.DataFrame,             # NEW for v1.1 — daily ^VIX close
    cash_yield_daily: pd.Series,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    execution_mode: str = 'same_close', # 'same_close' or 'next_open'
    progress_callback: Optional[callable] = None,
) -> BacktestResult:
    """Run a Rattlesnake mean-reversion backtest from start_date to end_date.

    Returns BacktestResult compatible with v1.0 reporting/methodology layers.
    Pure function: no side effects.
    """
```

### 6.2 Position dict schema

The position dict mirrors the live `self.rattle_positions` items, with
extra placeholder fields so the reused `_mark_to_market` works without
modification:

```python
{
    'symbol': str,
    'entry_price': float,
    'shares': float,
    'entry_date': pd.Timestamp,
    'entry_idx': int,
    'days_held': int,                  # NEW vs COMPASS — explicit counter
    'sector': 'Unknown',               # placeholder for _mark_to_market compat
    'entry_vol': 0.0,                  # placeholder
    'entry_daily_vol': 0.0,            # placeholder
    'high_price': float,               # placeholder (Rattlesnake doesn't trail)
}
```

### 6.3 apply_rattlesnake_exits

```python
def apply_rattlesnake_exits(
    state: BacktestState,
    date: pd.Timestamp,
    i: int,
    price_data: Dict[str, pd.DataFrame],
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[BacktestState, list, list]:
    """Pure equivalent of COMPASSLive._check_rattlesnake_exits
    (omnicapital_live.py:2040).

    Iterates positions, calls check_rattlesnake_exit(symbol, entry_price,
    current_price, days_held), exits via _get_exec_price.

    Exit reasons: 'R_PROFIT', 'R_STOP', 'R_TIME' (the R_ prefix matches
    the live engine's trade tag at omnicapital_live.py:2080).
    """
```

Logic:
1. For each position in `state.positions`:
   - `current_price = price_data[symbol].loc[date, 'Close']`
   - `reason = check_rattlesnake_exit(symbol, pos['entry_price'], current_price, pos['days_held'])`
   - If `reason` is None, position carries
   - If reason fired, resolve `exit_price = _get_exec_price(symbol, date, i, all_dates, price_data, execution_mode)`
   - If exit_price is None (last bar / next-open lookup failed), position carries
   - Else: compute pnl, append trade with `exit_reason='R_' + reason`,
     update cash, delete from positions

### 6.4 apply_rattlesnake_entries

```python
def apply_rattlesnake_entries(
    state: BacktestState,
    date: pd.Timestamp,
    i: int,
    price_data: Dict[str, pd.DataFrame],
    candidates: List[dict],            # from find_rattlesnake_candidates
    max_positions: int,
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[BacktestState, list]:
    """Pure equivalent of COMPASSLive._open_rattlesnake_positions
    (omnicapital_live.py:2092).

    Sized at 20% of cash per position (R_POSITION_SIZE), capped by
    max_positions and the cash buffer (cost+commission ≤ cash * 0.90).
    """
```

Logic (mirrors `omnicapital_live.py:2137-2186`):
1. `slots = max_positions - len(state.positions)`
2. If `slots <= 0` or `cash < 1000`, return state unchanged
3. **Capture `initial_cash = state.cash` BEFORE the loop** — this is the
   analog of the live `r_budget`. All entries in this call size against
   the same fixed snapshot, NOT against the residual cash that decreases
   as positions are opened. (Live uses `r_budget = alloc['rattle_budget']`
   computed once before the candidate loop.)
4. For each `candidate` in `candidates[:slots]`:
   - Resolve `entry_price = _get_exec_price(...)` (handles next-open mode)
   - If None, skip (cannot execute)
   - `position_value = initial_cash * R_POSITION_SIZE` (20%, FIXED snapshot)
   - **`shares = int(position_value / entry_price)`** — INTEGER shares,
     mirroring `omnicapital_live.py:2152`. Rattlesnake uses whole shares,
     unlike COMPASS which uses fractional shares
   - If `shares < 1`, skip (price too high for the budget)
   - `cost = shares * entry_price`
   - `commission = shares * config['COMMISSION_PER_SHARE']`
   - If `cost + commission > state.cash * 0.90`, skip (uses CURRENT cash
     for the buffer check, matching live which uses `portfolio.cash * 0.90`)
   - Else: open position, deduct cash from `state.cash`

Note: in same_close mode, `entry_date` and `entry_idx` use the signal day.
In next_open mode, they use the fill day (i+1) so `days_held` counts from
the fill, not the signal — consistent with v1.0 behavior.

### 6.5 Daily increment of days_held

After exits and entries, before the snapshot:

```python
new_positions = {
    sym: {**p, 'days_held': p['days_held'] + 1}
    for sym, p in state.positions.items()
}
state = state._replace(positions=new_positions)
```

This is the only piece of state mutation that doesn't have a v1.0 analog.
COMPASS derives `days_held` from `i - entry_idx`; Rattlesnake stores it
explicitly because the live engine does.

## 7. PIT universe filter

```python
def _resolve_rattlesnake_universe(
    pit_universe: Dict[int, List[str]],
    year: int,
) -> List[str]:
    """Intersect R_UNIVERSE (S&P 100 hardcoded) with PIT S&P 500 for `year`.

    Returns the list of tickers that are BOTH in R_UNIVERSE AND were
    members of the S&P 500 at any point during `year`. This drops
    survivorship bias from R_UNIVERSE without requiring fresh PIT
    S&P 100 data (which we don't have).
    """
    sp500_year = set(pit_universe.get(year, []))
    return sorted([t for t in R_UNIVERSE if t in sp500_year])
```

Caveats:
- Tickers in R_UNIVERSE that were NEVER in the S&P 500 (rare) are
  permanently excluded
- The S&P 100 is a subset of the S&P 500, so this filter is lossy only
  for tickers that left the S&P 500 in years where they were still in
  the S&P 100 (small effect)

## 8. VIX historical data

NEW loader in `data.py`:

```python
def load_vix_series(path: str) -> pd.Series:
    """Load daily VIX close from a CSV file.

    Format: CSV with columns (date, vix_close).
    Returns a Series indexed by date.

    Caller is responsible for downloading the source data. Recommended:
        yf.download('^VIX', start='1999-01-01', end='2027-01-01').Close
    saved as data_cache/vix_history.csv with columns (Date, Close).
    """
```

If the date being queried is missing from the VIX series, the engine
passes `None` to `check_rattlesnake_regime`, which (per the fail-closed
fix in commit b9d4ad7) blocks new entries that day.

The CLI accepts a `--vix data_cache/vix_history.csv` flag; the v1.1 CLI
expects the file to exist. A pre-flight check fails fast with a clear
error if the file is missing.

## 9. Methodology waterfall (identical to v1.0)

| Tier | Cash yield | Execution | Per-trade cost |
|---|---|---|---|
| 0 baseline | Aaa IG Corporate (FRED DAAA) | same_close | IBKR commissions only |
| 1 t_bill | T-bill 3M (FRED DGS3MO) | same_close | same as tier 0 |
| 2 next_open | T-bill 3M | next_open | same as tier 0 |
| 3 real_costs | T-bill 3M | next_open | + 2 bps slippage + 0.5 bps half-spread |
| net_honest | (alias of real_costs) | | |

`build_waterfall` from v1.0 is reused unchanged. Three full backtest
runs + one post-process. Estimated runtime: ~3-5 minutes total (Rattlesnake
is faster than COMPASS because the universe is smaller and signals are
simpler).

## 10. Layer A smoke tests (blocking)

`rattlesnake/validation.py::run_rattlesnake_smoke_tests(result)` runs
after each backtest run, before reporting.

**Mathematical invariants** (same as v1.0):
1. No NaN in `daily_values` critical columns
2. `cash` never < -1.0
3. `drawdown ∈ [-1.0, 0]` always
4. Peak monotonic non-decreasing
5. Statistical sanity: vol annualized ∈ [3%, 50%]
6. Outlier returns: |daily| < 15% except crash allowlist

**Position bounds** (Rattlesnake-specific):
7. `n_positions ∈ [0, R_MAX_POSITIONS]` always (= [0, 5])
8. NO leverage check (Rattlesnake has no leverage parameter)
9. NO sector concentration check

**Trade adherence** (Rattlesnake-specific):
10. `exit_reason='R_STOP'` implies `return ≤ R_STOP_LOSS + 0.005` tolerance
11. `exit_reason='R_PROFIT'` implies `return ≥ R_PROFIT_TARGET - 0.005` tolerance
12. `exit_reason='R_TIME'` implies `days_held ≥ R_MAX_HOLD_DAYS`

**Regime adherence** (Rattlesnake-specific):
13. On VIX panic days (vix > R_VIX_PANIC) or missing-VIX days, NO new
    entries should appear in the decisions log

## 11. Layer B cross-validation (best-effort, non-blocking)

`rattlesnake/validation.py::cross_validate_against_archive(result)`:

1. Attempt to import / run `archive/strategies/rattlesnake_v1.py` programmatically
2. Capture its equity curve and trades for the matching date range
3. Compare daily values: cumulative tracking error
4. Compare trade sets: symbols, dates, returns

**Tolerance**: 100 bps tracking error per year (looser than v1.0's 50 bps
because the archive script likely uses different parameters than the
current `rattlesnake_signals.py`).

**Failure mode**: if the archive script can't run (missing dependencies,
data path mismatches, etc.), log a warning and skip Layer B. Layer A is
the only blocking gate.

## 12. CLI

```bash
python -m hydra_backtest.rattlesnake \
    --start 2000-01-01 \
    --end 2026-03-05 \
    --out-dir backtests/rattlesnake_v1 \
    --constituents data_cache/sp500_constituents_history.pkl \
    --prices data_cache/sp500_universe_prices.pkl \
    --spy data_cache/SPY_2000-01-01_2027-01-01.csv \
    --vix data_cache/vix_history.csv \
    --aaa data_cache/moody_aaa_yield.csv \
    --aaa-date-col observation_date --aaa-value-col yield_pct \
    --tbill data_cache/tbill_3m_fred.csv \
    --slippage-bps 2.0 --half-spread-bps 0.5 --t-bill-rf 0.03
```

Outputs (to `--out-dir`):
- `rattlesnake_v2_daily.csv`
- `rattlesnake_v2_trades.csv`
- `rattlesnake_v2_waterfall.json`

Stdout: progress callback (per-year) + final waterfall summary table.

## 13. Testing strategy

### 13.1 Test pyramid

- **Unit tests**: ~25 (engine, validation, daily counter, exit reasons, sizing)
- **Integration tests**: ~5 (full smoke run on synthetic data)
- **E2E tests**: 2 (full real-data 2000-2026 + determinism), `@pytest.mark.slow`

### 13.2 Critical tests

| Test | What it proves |
|---|---|
| `test_apply_rattlesnake_exits_profit_target` | +4% triggers R_PROFIT exit |
| `test_apply_rattlesnake_exits_stop_loss` | -5% triggers R_STOP exit |
| `test_apply_rattlesnake_exits_time_limit` | days_held=8 triggers R_TIME exit |
| `test_days_held_increments_correctly` | counter goes 0,1,2,...,8 across consecutive days |
| `test_apply_rattlesnake_entries_respects_vix_panic` | vix > 35 → no new entries |
| `test_apply_rattlesnake_entries_position_size` | each entry uses ~20% cash |
| `test_universe_intersection_with_pit` | year 2010 universe excludes pre-2010 defunct tickers |
| `test_run_rattlesnake_backtest_smoke` | full 200-day synthetic run completes without error |
| `test_e2e_determinism` | two runs produce byte-identical CSVs |

### 13.3 Coverage targets

- 80% line coverage in `hydra_backtest/rattlesnake/` (CI gate)
- 100% in `rattlesnake/validation.py` (small, critical, easy to cover)
- E2E tests excluded from default CI run

### 13.4 CI integration

Add to existing `.github/workflows/test.yml`, after the v1.0 test step:

```yaml
- name: Test hydra_backtest.rattlesnake sub-package
  run: >
    pytest hydra_backtest/rattlesnake/tests/ -v --tb=short
    --cov=hydra_backtest.rattlesnake
    --cov-report=term-missing
    -m "not slow"
```

## 14. Open questions / risks

1. **VIX historical data not in `data_cache/`**: needs to be downloaded
   before first run. The plan should include a data prep step that uses
   yfinance `^VIX` to populate `data_cache/vix_history.csv`. Consistent
   with how T-bill was handled in v1.0 final run.

2. **R_UNIVERSE may have tickers never in S&P 500**: rare but possible
   (e.g., a stock briefly in S&P 100 but never S&P 500 — extremely
   unlikely but worth a sanity check). The PIT filter would silently
   exclude them. v1.1 logs a WARNING listing any such tickers.

3. **archive/strategies/rattlesnake_v1.py may not run**: it's from Feb
   2026, before the current `rattlesnake_signals.py` evolved. If it has
   data path bugs or schema mismatches, Layer B falls back to "skipped
   with warning". This is non-blocking by design.

4. **No cash recycling means Rattlesnake hoards idle cash**: in this
   standalone mode, when Rattlesnake has 0 entries (e.g., during
   sustained bull markets where no stock drops 8%+), 100% of capital
   sits in cash earning T-bill. This will produce a flat-ish equity
   curve during such periods. The full HYDRA value comes from cash
   recycling to COMPASS — that's why standalone Rattlesnake CAGR alone
   under-states its contribution.

5. **R_HOLD_DAYS=8 vs R_MAX_HOLD_DAYS=8**: the live `check_rattlesnake_exit`
   uses `>= R_MAX_HOLD_DAYS` which is 8. The R_HOLD_DAYS constant (also 8)
   is currently unused but exists for future flexibility. v1.1 uses
   `R_MAX_HOLD_DAYS` consistently.

## 15. Success criteria (measurable)

v1.1 is considered complete when:

1. `python -m hydra_backtest.rattlesnake --start 2000-01-01 --end 2026-03-05 ...`
   runs to completion without errors on a clean checkout
2. Two consecutive runs produce byte-identical `rattlesnake_v2_daily.csv`
3. All Layer A smoke tests pass for all 3 tier runs (baseline, t_bill, next_open)
4. Unit + integration test coverage ≥ 80% in CI
5. Waterfall report prints 5 tiers with monotonic CAGR degradation
   (within ±5 bp tolerance for noise)
6. Spec self-review passes (no placeholders, no contradictions)
7. User approves the spec in review
8. v1.0 test suite (74 tests) remains green after v1.1 changes
9. Layer B cross-validation either passes (within 100 bps/year tracking
   error) OR is gracefully skipped with warning (archive script unrunnable)

v1.1 does NOT require:
- Beating COMPASS standalone CAGR (Rattlesnake alone is expected to be
  in the 4-8% range; that's normal)
- Matching the live engine bit-for-bit (parity is a v1.4 concern when
  cash recycling is included)
- Modifying the dashboard

## 16. Roadmap context

| Version | Status | Contains |
|---|---|---|
| v1.0 | ✅ DONE 2026-04-06 | COMPASS standalone |
| **v1.1** | ← THIS SPEC | Rattlesnake standalone |
| v1.2 | pending | Catalyst standalone + Layer C walk-forward |
| v1.3 | pending | EFA standalone (passive overflow) |
| v1.4 | pending | HYDRA full integration with HydraCapitalManager |
| v1.5 | pending | Replace dashboard `hydra_clean_daily.csv` with HYDRA full output |

v1.4 is the milestone that enables replacing the dashboard number. v1.1
through v1.3 are necessary preparations.

## 17. Non-goals (explicit)

- Not building a generic backtest framework
- Not optimizing Rattlesnake parameters
- Not adding new Rattlesnake variants (e.g., RSI-7 instead of RSI-5)
- Not modifying the live `rattlesnake_signals.py` (consumer-not-owner)
- Not introducing dependencies not already in `requirements.txt`
- Not changing v1.0's behavior in any way
