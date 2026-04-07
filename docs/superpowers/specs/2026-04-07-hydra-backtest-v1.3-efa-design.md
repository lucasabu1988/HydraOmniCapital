# HYDRA Backtest v1.3 — EFA Standalone Pillar — Design Spec

**Date**: 2026-04-07
**Status**: Draft — awaiting approval before plan + execute
**Predecessors**: v1.0 COMPASS, v1.1 Rattlesnake, v1.2 Catalyst

## 1. Problem statement

`hydra_backtest/` v1.0 + v1.1 + v1.2 ship reproducible standalone
backtests for COMPASS, Rattlesnake, and Catalyst. v1.3 adds the fourth
and final standalone pillar: **EFA**, a passive single-asset trend
exposure to international developed markets via the iShares MSCI EAFE
ETF.

This is the **last pillar** before v1.4 HYDRA full integration. EFA is
the simplest of the four — a single ticker, a single SMA200 regime
gate, no rebalance cadence.

## 2. Success criterion

Same as v1.0/v1.1/v1.2: defendible publicly. A reproducible end-to-end
EFA backtest that any auditor can run with one command from a
versioned commit and obtain byte-identical CSV outputs. Methodology
defensible (PIT not relevant since universe is 1 hardcoded ETF;
T-bill, next-open, real costs all apply via the v1.0 waterfall).

## 3. Scope (decided)

**In scope for v1.3**:
- EFA standalone backtest as `hydra_backtest/efa/` sub-package
- Universe: hardcoded `EFA_SYMBOL = 'EFA'` imported from
  `omnicapital_live.py` (no PIT — universe is fixed)
- Signal logic: no external pure functions to import (the strategy is
  too small to factor out — `omnicapital_live.py::_manage_efa_position`
  embeds it inline). The v1.3 engine implements the regime gate
  directly using the EFA_SMA_PERIOD constant.
- Daily decision: hold EFA when `Close > SMA200`, hold cash otherwise
- Sizing: 100% of available cash deployed (no leverage, no fractional)
- Same waterfall methodology as v1.0/v1.1/v1.2 (5 tiers)
- New data loader `data.load_efa_series(path)` for EFA OHLCV pickle
- Layer A smoke tests adapted to EFA (single position bound, exit
  reasons, no rebalance cadence check)
- Layer B cross-validation: NONE (no exp* script produces a comparable
  EFA-only baseline; the live system has no isolated EFA history)
- New CLI: `python -m hydra_backtest.efa`
- Output schema compatible with v1.0 (drop-in for future merging)

**Out of scope for v1.3 (deferred)**:
- HydraCapitalManager integration / cash recycling — v1.4
- Reverse-flow `_liquidate_efa_for_capital` logic — v1.4 only
  (no other strategy competes for capital in standalone)
- $1,000 minimum-buy threshold — irrelevant in standalone (no
  fragmented idle cash pool)
- 90% cash deployment cap — irrelevant in standalone (no other
  strategy needs the buffer)
- Asset proxies for pre-inception periods (EFA inception 2001-08-17)
- Layer C walk-forward against live state JSONs — v1.5

**Non-goals (explicit)**:
- Not modifying `omnicapital_live.py` (no pure functions to factor out)
- Not extending the universe beyond EFA
- Not modifying SMA period (200 days)
- Not handling pre-2001-08-17 with proxies (cash-only when no history)

## 4. Architecture

### 4.1 Sub-package layout

```
hydra_backtest/                                    ← v1.0+v1.1+v1.2 (untouched)
├── data.py                                        ← + load_efa_series helper
└── efa/                                           ← NEW v1.3 sub-package
    ├── __init__.py                                ← public exports
    ├── __main__.py                                ← CLI entrypoint
    ├── engine.py                                  ← run_efa_backtest + apply_efa_decision
    ├── validation.py                              ← Layer A smoke tests EFA-adapted
    ├── README.md
    └── tests/
        ├── __init__.py
        ├── conftest.py                            ← efa_minimal_config fixture
        ├── test_engine.py
        ├── test_validation.py
        ├── test_integration.py                    ← CLI smoke
        └── test_e2e.py                            ← @pytest.mark.slow
.github/workflows/test.yml                         ← + new pytest step for efa
```

### 4.2 Reuse vs new

| From v1.0/v1.1/v1.2 | Reuse? | How |
|---|---|---|
| `BacktestState`, `BacktestResult` | ✅ | Direct import |
| `_mark_to_market`, `_get_exec_price` | ✅ | Direct imports |
| `data.py` loaders | ✅ | NEW: `load_efa_series` (added to data.py) |
| `methodology.build_waterfall` | ✅ | Strategy-agnostic |
| `reporting.py` writers | ✅ | Strategy-agnostic |
| `errors.py` | ✅ | Same hierarchy |
| `validation.run_smoke_tests` (v1.0) | ❌ | EFA gets `run_efa_smoke_tests` |

### 4.3 New code in v1.3

| Module | LOC estimate |
|---|---:|
| `efa/engine.py` (run_efa_backtest + apply_efa_decision) | 150-200 |
| `efa/validation.py` | 80-120 |
| `efa/__main__.py` | 80-100 |
| `efa/__init__.py` | 20 |
| `data.py::load_efa_series` (added) | 30 |
| Tests | 250-350 |
| `efa/README.md` | 70 |
| **Total new** | **~700 LOC** |

### 4.4 Guiding principle

**Inline, not consumer.** Unlike Catalyst (which imports
`compute_trend_holdings` from `catalyst_signals.py`), EFA's strategy is
not factored out as a pure function in any live module — it lives
inline inside `_manage_efa_position` and `_efa_above_sma200`. v1.3
implements the regime gate directly using only the constants
`EFA_SYMBOL = 'EFA'` and `EFA_SMA_PERIOD = 200`. If a future refactor
extracts the live function, v1.3 can adopt it then.

## 5. Data flow

```
CLI (efa/__main__.py)
    │
    ▼
data.py loaders (efa_history.pkl, T-bill, Aaa)
    │
    ▼
efa/engine.py::run_efa_backtest()
    │
    └─ for each trading day in [start, end]:
        1. _mark_to_market (reused) — EFA close if held, else just cash
        2. Update peak BEFORE drawdown
        3. apply daily costs (cash yield only — no leverage)
        4. Decide: above_sma200 = (Close[date] > SMA200[date])?
        5. Apply decision via apply_efa_decision:
           a. If above_sma200 and not held: BUY (deploy 100% of cash)
              with exit_reason for any subsequent SELL
           b. If above_sma200 and held: no-op (already long)
           c. If not above_sma200 and held: SELL all
              (exit_reason='EFA_BELOW_SMA200')
           d. If not above_sma200 and not held: no-op (stay in cash)
        6. Snapshot day (date, portfolio_value, cash, n_positions=0|1,
           drawdown, above_sma_today flag)
    │
    ▼
At end of backtest: synthetic-close any open EFA position with
exit_reason='EFA_BACKTEST_END'.
    │
    ▼
BacktestResult (raw tier 0)
    │
    ▼
methodology.build_waterfall (REUSED — 5 tiers)
    │
    ▼
efa/validation.run_efa_smoke_tests (Layer A blocking)
    │
    ▼
reporting writers (REUSED)
    │
    ▼
backtests/efa_v1/efa_v2_{daily,trades}.csv
backtests/efa_v1/efa_v2_waterfall.json
```

## 6. Engine specification

### 6.1 Public function signature

```python
# hydra_backtest/efa/engine.py

def run_efa_backtest(
    config: dict,                     # EFA config (subset of COMPASS)
    efa_data: pd.DataFrame,           # OHLCV indexed by date
    cash_yield_daily: pd.Series,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    execution_mode: str = 'same_close',
    progress_callback: Optional[callable] = None,
) -> BacktestResult:
    """Run an EFA passive trend backtest from start_date to end_date."""
```

Note: no `pit_universe`, no `asset_data: Dict`, no `spy_data` — the
universe is a single ticker so the data input is just a single
DataFrame.

### 6.2 Position dict schema

```python
{
    'symbol': 'EFA',
    'entry_price': float,
    'shares': float,                # always integer-valued
    'entry_date': pd.Timestamp,
    'entry_idx': int,
    'days_held': int,               # diagnostic only
    'sub_strategy': 'passive_intl',
    'sector': 'International Equity',
    'entry_vol': 0.0,
    'entry_daily_vol': 0.0,
    'high_price': float,
}
```

### 6.3 apply_efa_decision pure function

```python
def apply_efa_decision(
    state: BacktestState,
    date: pd.Timestamp,
    i: int,
    efa_data: pd.DataFrame,
    config: dict,
    execution_mode: str,
    all_dates: list,
) -> Tuple[BacktestState, list, list]:
    """Pure equivalent of COMPASSLive._manage_efa_position
    (omnicapital_live.py:2409) for the standalone case (no recycling).

    Decision matrix:
        above_sma200 | held | action
        -------------+------+--------------------------------
        True         | no   | BUY 100% of cash
        True         | yes  | no-op
        False        | no   | no-op
        False        | yes  | SELL all (EFA_BELOW_SMA200)

    Returns (new_state, trades_list, decisions_list).
    """
```

### 6.4 Trade categorization

| Action | Trade record? | exit_reason |
|---|---|---|
| EFA newly above SMA200, not held → buy | ❌ no trade record (just position dict entry) | n/a |
| EFA above SMA200, already held → no-op | ❌ no trade | n/a |
| EFA newly below SMA200, currently held → sell | ✅ exit trade | `'EFA_BELOW_SMA200'` |
| EFA below SMA200, not held → no-op | ❌ no trade | n/a |
| Backtest end with open position | ✅ synthetic exit | `'EFA_BACKTEST_END'` |

### 6.5 Pre-inception handling

EFA inception is **2001-08-17**. For dates before that, `efa_data` has
no rows, so `_get_exec_price` returns `None` and no trade is possible.
The engine treats those days as 100% cash (with the configured cash
yield applied normally).

For dates after inception but before day 200, the SMA200 cannot be
computed; the engine treats EFA as "not above SMA200" → not held →
100% cash. First eligible decision day is approximately
**2002-06-04** (200 trading days after inception).

## 7. New data loader

`data.py::load_efa_series(path)`:

```python
def load_efa_series(path: str) -> pd.DataFrame:
    """Load EFA OHLCV from pickle.

    Format: pickle of a single pd.DataFrame with Open/High/Low/Close/Volume
    columns indexed by date. Caller is responsible for download:

        import yfinance as yf
        import pickle
        df = yf.download('EFA', start='1999-01-01', end='2027-01-01',
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.droplevel(1)
        with open('data_cache/efa_history.pkl', 'wb') as f:
            pickle.dump(df, f)
    """
```

Validation: must contain Open/High/Low/Close/Volume columns and have at
least 1 row.

## 8. Methodology waterfall (identical to v1.0/v1.1/v1.2)

Same 5 tiers via `build_waterfall`:
- Tier 0 baseline: Aaa cash, same_close
- Tier 1: + T-bill cash yield
- Tier 2: + next_open execution
- Tier 3: + 2 bps slippage + 0.5 bps half-spread
- net_honest: alias of tier 3

Estimated runtime: ~30-60 seconds (fastest of all four pillars — 1
asset, 1 decision per day).

## 9. Layer A smoke tests

`efa/validation.py::run_efa_smoke_tests`:

**Mathematical invariants** (same as v1.0/v1.1/v1.2):
1. No NaN in critical columns
2. Cash never < -1.0
3. Drawdown ∈ [-1.0, 0]
4. Peak monotonic non-decreasing
5. Vol ann ∈ [0.5%, 50%]
6. No outlier daily returns > ±15% (except crash allowlist)

**EFA-specific invariants**:
7. `n_positions ∈ [0, 1]` always (single-asset universe)
8. Trade exit reasons ⊆ {'EFA_BELOW_SMA200', 'EFA_BACKTEST_END'}
9. Pre-inception (before 2001-08-17) snapshots: `n_positions == 0`

The strict stop/profit checks from v1.1 don't apply (EFA has no
stops or profit targets). The rebalance cadence check from v1.2
doesn't apply (EFA has no rebalance cadence — decisions are daily and
state-driven).

## 10. Layer B cross-validation

**Skipped for v1.3.** No existing experiment script produces an
isolated EFA backtest. The live system never ran EFA in isolation; it
has only ever existed as the overflow pillar in HYDRA. v1.3's
correctness is validated against:
- Layer A smoke tests (blocking)
- Buy-and-hold sanity check in unit tests (an EFA backtest where
  EFA is always above SMA200 should match buy-and-hold returns
  minus commissions)

## 11. CLI

```bash
python -m hydra_backtest.efa \
    --start 2000-01-01 \
    --end 2026-03-05 \
    --out-dir backtests/efa_v1 \
    --efa data_cache/efa_history.pkl
```

Outputs:
- `efa_v2_daily.csv`
- `efa_v2_trades.csv`
- `efa_v2_waterfall.json`

CLI defaults match the real on-disk format (`observation_date/yield_pct`
for Aaa, `DATE/DGS3MO` for T-bill — same as Catalyst).

## 12. Testing strategy

| Test | What it proves |
|---|---|
| `test_apply_decision_buys_when_above_sma_and_not_held` | New entry path |
| `test_apply_decision_sells_when_below_sma_and_held` | Exit path with `EFA_BELOW_SMA200` |
| `test_apply_decision_no_op_when_above_sma_and_held` | Stays long |
| `test_apply_decision_no_op_when_below_sma_and_not_held` | Stays in cash |
| `test_apply_decision_handles_pre_inception` | Pre-2001-08-17 → no buy |
| `test_run_backtest_buy_and_hold_in_uptrend` | Always-uptrend run = single buy + synthetic-end exit |
| `test_run_backtest_oscillating_regime` | Multiple BELOW_SMA exits |
| `test_smoke_tests_n_positions_bounds` | Catches >1 holding |
| `test_smoke_tests_invalid_exit_reason` | Catches non-EFA exit reasons |
| `test_e2e_full_run` | Full 2000-2026 with real data |
| `test_e2e_determinism` | Two runs produce byte-identical outputs |

Coverage target: 80% in `hydra_backtest/efa/`.

## 13. Roadmap context

| Version | Status | Contains |
|---|---|---|
| v1.0 | ✅ DONE | COMPASS standalone |
| v1.1 | ✅ DONE | Rattlesnake standalone |
| v1.2 | ✅ DONE | Catalyst standalone |
| **v1.3** | ← THIS | EFA standalone |
| v1.4 | pending | HYDRA full integration with HydraCapitalManager |
| v1.5 | pending | Replace dashboard `hydra_clean_daily.csv` |

## 14. Success criteria (measurable)

v1.3 is complete when:

1. `python -m hydra_backtest.efa --start 2000-01-01 --end 2026-03-05 ...`
   runs to completion without errors
2. Two consecutive runs produce byte-identical `efa_v2_daily.csv`
3. All Layer A smoke tests pass for all 3 tier runs
4. Coverage ≥ 80% for `hydra_backtest/efa/`
5. v1.0 + v1.1 + v1.2 test suites remain green
6. Waterfall report prints 5 tiers
7. Pre-inception (before 2001-08-17) snapshots show `n_positions == 0`
8. Buy-and-hold sanity test: an always-above-SMA200 synthetic run
   produces a single trade record (the synthetic-end exit) with
   return ≈ (final_close / first_close) - commission cost

v1.3 does NOT require:
- Beating COMPASS / Rattlesnake / Catalyst CAGR
- Any cross-validation against an experiment script
- Modifying the dashboard
- Modifying live code
