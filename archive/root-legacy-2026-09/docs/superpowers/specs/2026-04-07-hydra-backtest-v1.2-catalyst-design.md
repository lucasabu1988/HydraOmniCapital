# HYDRA Backtest v1.2 — Catalyst Standalone Pillar — Design Spec

**Date**: 2026-04-07
**Status**: Approved — proceeding to plan + execute autonomously
**Predecessors**: v1.0 COMPASS, v1.1 Rattlesnake

## 1. Problem statement

`hydra_backtest/` v1.0 + v1.1 ship reproducible standalone backtests for
COMPASS and Rattlesnake. v1.2 adds the third HYDRA pillar: **Catalyst**, a
cross-asset trend-following strategy that holds 4 ETFs (TLT, ZROZ, GLD, DBC)
when each is above its 200-day SMA, rebalancing every 5 days.

This is the second-to-last pillar before v1.4 HYDRA full integration.
Catalyst is the only pillar that uses ring-fenced budget (15% in live)
because it has the most distinct return profile from COMPASS/Rattlesnake.

## 2. Success criterion

Same as v1.0/v1.1: defendible publicly. A reproducible end-to-end
Catalyst backtest that any auditor can run with one command from a
versioned commit and obtain byte-identical CSV outputs. Methodology
defensible (PIT not relevant since universe is 4 hardcoded ETFs;
T-bill, next-open, real costs all apply via the v1.0 waterfall).

## 3. Scope (decided)

**In scope for v1.2**:
- Catalyst standalone backtest as `hydra_backtest/catalyst/` sub-package
- Universe: hardcoded `CATALYST_TREND_ASSETS = ['TLT', 'ZROZ', 'GLD', 'DBC']`
  imported from `catalyst_signals.py` (no PIT — universe is fixed)
- Signal logic: imported pure functions from `catalyst_signals.py`
  (`compute_trend_holdings`, `compute_catalyst_targets`)
- Rebalance every `CATALYST_REBALANCE_DAYS = 5` (mirrors live exactly)
- Equal-weight allocation among assets above SMA200
- Integer shares, no fractional (matches live `int(per_asset / price)`)
- New data loader `data.load_catalyst_assets(path)` for the 4-ETF pickle
- Same waterfall methodology as v1.0/v1.1 (5 tiers)
- Layer A smoke tests adapted to Catalyst (rebalance counter, asset count bounds)
- Layer B cross-validation against `experiments/exp68_4th_pillar_trend_gold.py`
  (best-effort, non-blocking)
- New CLI: `python -m hydra_backtest.catalyst`
- Output schema compatible with v1.0 (drop-in for future merging)

**Out of scope for v1.2 (deferred)**:
- HydraCapitalManager integration / cash recycling — v1.4
- Permanent gold sub-strategy — `catalyst_signals.py` removed it (CATALYST_GOLD_WEIGHT = 0.0)
- Layer C walk-forward against live state JSONs — v1.5 (consistent with v1.1)
- Asset proxies for pre-inception periods (e.g., GC=F before GLD) — v1.5
- Catalyst position downsize on rebalance — mirrors live "silent over-allocation" quirk

**Non-goals (explicit)**:
- Not changing `catalyst_signals.py` (consumer-not-owner)
- Not adding new trend assets beyond TLT/ZROZ/GLD/DBC
- Not modifying SMA period (200 days) or rebalance cadence (5 days)
- Not handling pre-inception data with proxies (cash-only when no assets exist)

## 4. Architecture

### 4.1 Sub-package layout

```
hydra_backtest/                                    ← v1.0+v1.1 (untouched)
├── data.py                                        ← + load_catalyst_assets helper
└── catalyst/                                      ← NEW v1.2 sub-package
    ├── __init__.py                                ← public exports
    ├── __main__.py                                ← CLI entrypoint
    ├── engine.py                                  ← run_catalyst_backtest + apply_catalyst_rebalance
    ├── validation.py                              ← Layer A smoke tests Catalyst-adapted
    ├── README.md
    └── tests/
        ├── __init__.py
        ├── conftest.py                            ← catalyst_minimal_config fixture
        ├── test_engine.py
        ├── test_validation.py
        ├── test_integration.py                    ← CLI smoke
        └── test_e2e.py                            ← @pytest.mark.slow
.github/workflows/test.yml                         ← + new pytest step for catalyst
```

### 4.2 Reuse vs new

| From v1.0/v1.1 | Reuse? | How |
|---|---|---|
| `BacktestState`, `BacktestResult` | ✅ | Direct import |
| `_mark_to_market`, `_get_exec_price`, `_slice_history_to_date` | ✅ | Direct imports |
| `data.py` loaders | ✅ | NEW: `load_catalyst_assets` (added to data.py) |
| `methodology.build_waterfall` | ✅ | Strategy-agnostic |
| `reporting.py` writers | ✅ | Strategy-agnostic |
| `errors.py` | ✅ | Same hierarchy |
| `validation.run_smoke_tests` (v1.0) | ❌ | Catalyst gets its own `run_catalyst_smoke_tests` |

### 4.3 New code in v1.2

| Module | LOC estimate |
|---|---:|
| `catalyst/engine.py` (run_catalyst_backtest + helpers) | 250-300 |
| `catalyst/validation.py` | 100-150 |
| `catalyst/__main__.py` | 80-120 |
| `catalyst/__init__.py` | 30 |
| `data.py::load_catalyst_assets` (added) | 30 |
| Tests | 350-450 |
| `catalyst/README.md` | 80 |
| **Total new** | **~900 LOC** |

### 4.4 Guiding principle (inherited)

**Consumer, not owner.** Pure functions imported from `catalyst_signals.py`:

```python
from catalyst_signals import (
    CATALYST_TREND_ASSETS,
    CATALYST_REBALANCE_DAYS,
    CATALYST_SMA_PERIOD,
    compute_trend_holdings,
    compute_catalyst_targets,
)
```

The reimplementation surface is ~250 LOC (orchestrator + rebalance helper).
Any change to `catalyst_signals.py` propagates automatically to the backtest.

## 5. Data flow

```
CLI (catalyst/__main__.py)
    │
    ▼
data.py loaders (catalyst_assets.pkl, SPY, T-bill, Aaa)
    │
    ▼
catalyst/engine.py::run_catalyst_backtest()
    │
    └─ for each trading day in [start, end]:
        1. _mark_to_market (reused) — uses Close[date] for held assets
        2. Update peak BEFORE drawdown
        3. apply daily costs (cash yield only — no leverage)
        4. Increment catalyst_day_counter
        5. If counter >= CATALYST_REBALANCE_DAYS OR no positions yet:
           a. Reset counter to 0
           b. Compute trend_holdings = compute_trend_holdings(sliced_hist)
              (only over assets that have ≥ SMA_PERIOD days of history at `date`)
           c. Compute target_value = portfolio_value / len(trend_holdings) per asset
           d. SELLS: for each currently-held asset NOT in trend_holdings → emit
              exit trade with exit_reason='CATALYST_TREND_OFF', proceeds to cash
           e. BUYS: for each asset in trend_holdings NOT currently held → buy
              target_shares (mirrors live: no downsize on existing holdings)
        6. Snapshot day (date, portfolio_value, cash, n_positions, drawdown,
           rebalance_today flag, n_trend_holdings)
    │
    ▼
At end of backtest: synthetic-close any remaining open positions with
exit_reason='CATALYST_BACKTEST_END' so all positions appear in trades log.
    │
    ▼
BacktestResult (raw tier 0)
    │
    ▼
methodology.build_waterfall (REUSED — 5 tiers)
    │
    ▼
catalyst/validation.run_catalyst_smoke_tests (Layer A blocking)
    │
    ▼
reporting writers (REUSED)
    │
    ▼
backtests/catalyst_v1/catalyst_v2_{daily,trades}.csv
backtests/catalyst_v1/catalyst_v2_waterfall.json
```

## 6. Engine specification

### 6.1 Public function signature

```python
# hydra_backtest/catalyst/engine.py

def run_catalyst_backtest(
    config: dict,                       # Catalyst config (subset of COMPASS)
    asset_data: Dict[str, pd.DataFrame], # 4 ETFs, each indexed by date with OHLCV
    cash_yield_daily: pd.Series,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    execution_mode: str = 'same_close', # 'same_close' or 'next_open'
    progress_callback: Optional[callable] = None,
) -> BacktestResult:
    """Run a Catalyst cross-asset trend backtest from start_date to end_date."""
```

Note: no `pit_universe` parameter because the universe is hardcoded.

### 6.2 Position dict schema

```python
{
    'symbol': str,                  # 'TLT', 'ZROZ', 'GLD', or 'DBC'
    'entry_price': float,
    'shares': float,                # stored as float but always integer-valued
    'entry_date': pd.Timestamp,
    'entry_idx': int,
    'days_held': int,               # incremented daily for diagnostic only
    'sub_strategy': 'trend',        # placeholder for future gold sub-strategy
    'sector': 'Catalyst',           # placeholder for _mark_to_market compat
    'entry_vol': 0.0,
    'entry_daily_vol': 0.0,
    'high_price': float,
}
```

### 6.3 apply_catalyst_rebalance pure function

```python
def apply_catalyst_rebalance(
    state: BacktestState,
    date: pd.Timestamp,
    i: int,
    asset_data: Dict[str, pd.DataFrame],
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[BacktestState, list, list]:
    """Pure equivalent of COMPASSLive._manage_catalyst_positions
    (omnicapital_live.py:2196).

    Computes trend_holdings via compute_trend_holdings, sells positions
    no longer in trend, buys new entrants. Mirrors live's "no downsize"
    behavior on existing holdings (omnicapital_live.py:2270).

    Returns (new_state, trades_list, decisions_list).
    """
```

### 6.4 Rebalance trade categorization

| Action | Trade record? | exit_reason |
|---|---|---|
| Asset newly above SMA200, not held → buy | ❌ no trade record (just position dict entry) | n/a |
| Asset still above SMA200, already held → no-op | ❌ no trade | n/a |
| Asset above SMA200 but its target_shares > current → buy more | ❌ trade record continues; entry_price recomputed as weighted avg | n/a |
| Asset newly below SMA200, currently held → sell all | ✅ exit trade | `'CATALYST_TREND_OFF'` |
| Asset above SMA200 but target_shares < current → keep (live "no downsize") | ❌ no trade | n/a |
| Backtest end with open position | ✅ synthetic exit | `'CATALYST_BACKTEST_END'` |

### 6.5 Pre-inception handling

For each asset, the engine checks if `len(asset_data[ticker].loc[:date]) >= CATALYST_SMA_PERIOD` before computing SMA. If insufficient history, the asset is treated as "not above SMA200" → not held. This naturally produces:
- Pre-2002: 0 holdings, 100% cash
- 2002-2004: TLT only (when above SMA200)
- 2004-2006: TLT, GLD
- 2006-2009: TLT, GLD, DBC
- 2009+: All 4

No proxies, no synthetic data. Each asset enters the strategy when it has ≥200 days of real history.

## 7. New data loader

`data.py::load_catalyst_assets(path)`:

```python
def load_catalyst_assets(path: str) -> Dict[str, pd.DataFrame]:
    """Load Catalyst asset OHLCV from pickle.

    Format: pickle of dict {ticker: DataFrame with Open/High/Low/Close/Volume}.
    Caller is responsible for download. Recommended one-time setup:

        import yfinance as yf
        import pickle
        data = {}
        for sym in ['TLT', 'ZROZ', 'GLD', 'DBC']:
            df = yf.download(sym, start='1999-01-01', end='2027-01-01',
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            data[sym] = df
        with open('data_cache/catalyst_assets.pkl', 'wb') as f:
            pickle.dump(data, f)
    """
```

Same shape as `load_price_history` for COMPASS. Validation: must contain
all of TLT, ZROZ, GLD, DBC keys with OHLCV columns.

## 8. Methodology waterfall (identical to v1.0/v1.1)

Same 5 tiers via `build_waterfall`:
- Tier 0 baseline: Aaa cash, same_close
- Tier 1: + T-bill cash yield
- Tier 2: + next_open execution
- Tier 3: + 2 bps slippage + 0.5 bps half-spread
- net_honest: alias of tier 3

Estimated runtime: ~2-3 minutes (faster than COMPASS/Rattlesnake because
the universe is only 4 assets and rebalances are infrequent).

## 9. Layer A smoke tests

`catalyst/validation.py::run_catalyst_smoke_tests`:

**Mathematical invariants** (same as v1.0/v1.1):
1. No NaN in critical columns
2. Cash never < -1.0
3. Drawdown ∈ [-1.0, 0]
4. Peak monotonic non-decreasing
5. Vol ann ∈ [0.5%, 50%]
6. No outlier daily returns > ±15% (except crash allowlist)

**Catalyst-specific invariants**:
7. `n_positions ∈ [0, 4]` always (= len(CATALYST_TREND_ASSETS))
8. Trade exit reasons ⊆ {'CATALYST_TREND_OFF', 'CATALYST_BACKTEST_END'}
9. Pre-2002 (before TLT inception) snapshots: `n_positions == 0`
10. Rebalance frequency: in same_close mode, the difference between
    consecutive rebalance days should be exactly `CATALYST_REBALANCE_DAYS`
    (=5) except for the first rebalance which is on day 1

The strict stop/profit checks from v1.1 don't apply (Catalyst has no
stops or profit targets).

## 10. Layer B cross-validation (best-effort, non-blocking)

`experiments/exp68_4th_pillar_trend_gold.py` produces a Catalyst-like
output but with 85% HYDRA + 10% trend + 5% gold weighting (a Frankenstein
that became the dashboard number). v1.2's Layer B compares ONLY the
trend portion of exp68 (extracted by reading the underlying trend basket
returns). If exp68 cannot be parsed cleanly, Layer B falls back to a
warning and skips. **Non-blocking**: only Layer A is required for v1.2.

## 11. CLI

```bash
python -m hydra_backtest.catalyst \
    --start 2000-01-01 \
    --end 2026-03-05 \
    --out-dir backtests/catalyst_v1 \
    --catalyst-assets data_cache/catalyst_assets.pkl \
    --aaa data_cache/moody_aaa_yield.csv \
    --aaa-date-col observation_date --aaa-value-col yield_pct \
    --tbill data_cache/tbill_3m_fred.csv
```

Outputs:
- `catalyst_v2_daily.csv`
- `catalyst_v2_trades.csv`
- `catalyst_v2_waterfall.json`

## 12. Testing strategy

| Test | What it proves |
|---|---|
| `test_resolve_trend_holdings_with_data_gap` | TLT not held before 2002-07 (insufficient history) |
| `test_apply_rebalance_buys_new_trend_assets` | New trend asset → position opens |
| `test_apply_rebalance_sells_assets_off_trend` | Asset crosses below SMA200 → exit with CATALYST_TREND_OFF |
| `test_apply_rebalance_no_downsize_existing` | Mirrors live "silent over-allocation" |
| `test_rebalance_only_every_5_days` | Counter logic correct |
| `test_run_catalyst_backtest_smoke` | Full 200-day synthetic run completes |
| `test_smoke_tests_n_positions_bounds` | Catches >4 holdings |
| `test_smoke_tests_invalid_exit_reason` | Catches non-Catalyst exit reasons |
| `test_e2e_full_run` | Full 2000-2026 with real data |
| `test_e2e_determinism` | Two runs produce byte-identical outputs |

Coverage target: 80% in `hydra_backtest/catalyst/`.

## 13. Roadmap context

| Version | Status | Contains |
|---|---|---|
| v1.0 | ✅ DONE | COMPASS standalone |
| v1.1 | ✅ DONE | Rattlesnake standalone |
| **v1.2** | ← THIS | Catalyst standalone |
| v1.3 | pending | EFA standalone (passive overflow) |
| v1.4 | pending | HYDRA full integration with HydraCapitalManager |
| v1.5 | pending | Replace dashboard `hydra_clean_daily.csv` |

## 14. Success criteria (measurable)

v1.2 is complete when:

1. `python -m hydra_backtest.catalyst --start 2000-01-01 --end 2026-03-05 ...`
   runs to completion without errors
2. Two consecutive runs produce byte-identical `catalyst_v2_daily.csv`
3. All Layer A smoke tests pass for all 3 tier runs
4. Coverage ≥ 80% for `hydra_backtest/catalyst/`
5. v1.0 + v1.1 test suites remain green
6. Waterfall report prints 5 tiers
7. Pre-2002 snapshots show `n_positions == 0` (data gap respected)

v1.2 does NOT require:
- Beating COMPASS or Rattlesnake CAGR
- Matching exp68 Catalyst output (different methodology)
- Modifying the dashboard
