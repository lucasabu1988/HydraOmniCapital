# hydra_backtest.efa — EFA Standalone Backtest

Reproducible EFA passive international trend backtest, the fourth and
final standalone pillar of the HYDRA quantitative trading system.

## What this is

A Python sub-package that runs an EFA passive trend backtest from 2000
to 2026 on a single hardcoded ETF (iShares MSCI EAFE), producing a
waterfall methodology report
(baseline → +T-bill → +next-open → +slippage → NET HONEST).

## Strategy in one paragraph

A single-asset trend-following system: hold EFA when its closing price
is above its 200-day SMA, hold cash otherwise. Decisions are
state-driven and evaluated daily — no rebalance cadence, no fractional
sizing, no stops, no profit targets. New entries deploy 100% of
available cash; exits sell the entire position with
`exit_reason='EFA_BELOW_SMA200'`.

## How to run

```bash
# Download EFA history first (one-time setup — see Task 15 in the impl plan)
python - <<'PY'
import pickle
import pandas as pd
import yfinance as yf
df = yf.download('EFA', start='1999-01-01', end='2027-01-01',
                 auto_adjust=True, progress=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.droplevel(1)
with open('data_cache/efa_history.pkl', 'wb') as f:
    pickle.dump(df, f)
PY

# Run backtest
python -m hydra_backtest.efa \
  --start 2000-01-01 \
  --end 2026-03-05 \
  --out-dir backtests/efa_v1
```

Outputs in `backtests/efa_v1/`:
- `efa_v2_daily.csv` — daily equity curve, n_positions, drawdown,
  above_sma_today
- `efa_v2_trades.csv` — closed trades with exit reasons
  (`EFA_BELOW_SMA200`, `EFA_BACKTEST_END`)
- `efa_v2_waterfall.json` — 5 tiers + metadata

Stdout shows progress per year and a final waterfall summary table.

## Architecture

```
hydra_backtest/efa/
├── __init__.py          public exports
├── __main__.py          CLI: python -m hydra_backtest.efa
├── engine.py            apply_efa_decision + run_efa_backtest +
│                        _efa_above_sma200 + _apply_efa_daily_costs
├── validation.py        Layer A smoke tests (8 invariants)
└── tests/
    ├── conftest.py      efa_minimal_config fixture
    ├── test_engine.py   9 engine unit tests
    ├── test_validation.py  8 validation unit tests
    ├── test_integration.py CLI smoke (synthetic data)
    └── test_e2e.py      slow real-data tests (skipped if pickle missing)
```

Reuses from v1.0 (`hydra_backtest.engine`, `hydra_backtest.data`,
`hydra_backtest.methodology`, `hydra_backtest.reporting`,
`hydra_backtest.errors`):

| Symbol | Purpose |
|---|---|
| `BacktestState`, `BacktestResult` | shared state container |
| `_mark_to_market`, `_get_exec_price` | execution helpers |
| `compute_data_fingerprint` | provenance hash |
| `build_waterfall` | 5-tier methodology report |
| `write_daily_csv`, `write_trades_csv`, `write_waterfall_json` | output writers |
| `HydraBacktestValidationError` | validation failure exception |
| `load_efa_series`, `load_yield_series` | data loaders |

## Inline strategy note

Unlike Catalyst (which imports `compute_trend_holdings` from
`catalyst_signals.py`) and Rattlesnake (which imports its signal
functions from `rattlesnake_signals.py`), EFA's strategy is **not
factored out as a pure function** in any live module — it lives
embedded inside `omnicapital_live.py::_manage_efa_position`. v1.3
implements the SMA200 regime gate inline, depending only on the
constants:

```python
EFA_SYMBOL = 'EFA'
EFA_SMA_PERIOD = 200
```

These two values are duplicated from `omnicapital_live.py:264-266`. If
live ever changes them, the duplication is the only contract surface
to keep in sync. A future refactor could extract a `compute_efa_signal()`
pure function in live and have v1.3 consume it; the current design
deliberately avoids touching live code.

## Layer A smoke tests

`run_efa_smoke_tests` enforces 8 invariants and aggregates all
failures into a single `HydraBacktestValidationError`:

**Mathematical** (shared with v1.0/v1.1/v1.2):
1. No NaN in critical columns
2. Cash never < -1.0
3. Drawdown ∈ [-1.0, 0]
4. Peak monotonic non-decreasing
5. Annualized vol ∈ [0.5%, 50%]
6. No outlier daily returns > ±15% (2008 + 2020 crash days allowlisted)

**EFA-specific**:
7. `n_positions ∈ [0, 1]` always (single-asset universe)
8. Trade exit reasons ⊆ `{'EFA_BELOW_SMA200', 'EFA_BACKTEST_END'}`

(No rebalance cadence check — EFA has no cadence. No stop/profit
checks — EFA has neither.)

## v1.3 limitations (deferred to later versions)

- **No HydraCapitalManager integration** — EFA standalone runs on 100%
  of capital. Live uses idle cash overflow after COMPASS/Rattlesnake
  recycling. v1.4 will integrate.
- **No reverse-flow liquidation** — live sells EFA when COMPASS or
  Rattlesnake need capital (`_liquidate_efa_for_capital` at
  omnicapital_live.py:2508). Standalone has no other strategy
  competing for capital. v1.4 only.
- **No `$1,000` minimum-buy threshold** — irrelevant in standalone (no
  fragmented idle cash pool to wait on).
- **No 90% cash deployment cap** — irrelevant in standalone (no other
  strategy needs the buffer).
- **No asset proxies for pre-inception** — EFA inception is 2001-08-17.
  Pre-inception bars produce 0 holdings automatically because
  `_get_exec_price` returns `None` and `_efa_above_sma200` returns
  `False` until ≥200 bars are available.
- **No Layer B / Layer C cross-validation** — no isolated EFA backtest
  exists in any experiment script for comparison. Only Layer A is
  required.

## Roadmap

| Version | Status | Contains |
|---|---|---|
| v1.0 | ✅ DONE | COMPASS standalone |
| v1.1 | ✅ DONE | Rattlesnake standalone |
| v1.2 | ✅ DONE | Catalyst standalone |
| **v1.3** | ✅ THIS | EFA standalone |
| v1.4 | pending | HYDRA full integration with HydraCapitalManager |
| v1.5 | pending | Replace dashboard `hydra_clean_daily.csv` |

## See also

- Spec: `docs/superpowers/specs/2026-04-07-hydra-backtest-v1.3-efa-design.md`
- Plan: `docs/superpowers/plans/2026-04-07-hydra-backtest-v1.3-efa.md`
- Live consumer: `omnicapital_live.py::COMPASSLive._manage_efa_position`
