# hydra_backtest.catalyst — Catalyst Standalone Backtest

Reproducible Catalyst cross-asset trend backtest, the third pillar of
the HYDRA quantitative trading system.

## What this is

A Python sub-package that runs a Catalyst trend-following backtest from
2000 to 2026 on a hardcoded 4-ETF universe (TLT, ZROZ, GLD, DBC),
producing a waterfall methodology report
(baseline → +T-bill → +next-open → +slippage → NET HONEST).

**Consumer-not-owner principle** (inherited from v1.0): pure functions
are imported directly from `catalyst_signals.py` (the live engine
module). The reimplementation surface is ~200 LOC of pure helpers
(`apply_catalyst_rebalance`, `_apply_catalyst_daily_costs`,
`_has_enough_history`, `run_catalyst_backtest`).

## Strategy in one paragraph

Every `CATALYST_REBALANCE_DAYS` (=5) trading days, hold the subset of
{TLT, ZROZ, GLD, DBC} whose closing price is above its 200-day SMA,
equal-weighted. Sell positions whose asset just dropped below SMA200
(`exit_reason='CATALYST_TREND_OFF'`). Increase existing positions when
their target share count grew (e.g. another asset left the trend so the
per-asset slice is now larger). **Never downsize** an existing position
when its target shrank — this mirrors the live engine's "silent
over-allocation" quirk (omnicapital_live.py:2270).

## How to run

```bash
# Download Catalyst assets first (one-time setup — see Task 14 in the impl plan)
python - <<'PY'
import pickle
import yfinance as yf
data = {}
for sym in ['TLT', 'ZROZ', 'GLD', 'DBC']:
    df = yf.download(sym, start='1999-01-01', end='2027-01-01',
                     auto_adjust=True, progress=False)
    if hasattr(df.columns, 'droplevel'):
        df.columns = df.columns.droplevel(1)
    data[sym] = df
with open('data_cache/catalyst_assets.pkl', 'wb') as f:
    pickle.dump(data, f)
PY

# Run backtest
python -m hydra_backtest.catalyst \
  --start 2000-01-01 \
  --end 2026-03-05 \
  --out-dir backtests/catalyst_v1
```

Outputs in `backtests/catalyst_v1/`:
- `catalyst_v2_daily.csv` — daily equity curve, n_positions, drawdown,
  rebalance_today, n_trend_holdings
- `catalyst_v2_trades.csv` — all closed trades with exit reasons
  (`CATALYST_TREND_OFF`, `CATALYST_BACKTEST_END`)
- `catalyst_v2_waterfall.json` — 5 tiers + metadata

Stdout shows progress per year and a final waterfall summary table.

## Architecture

```
hydra_backtest/catalyst/
├── __init__.py          public exports
├── __main__.py          CLI: python -m hydra_backtest.catalyst
├── engine.py            apply_catalyst_rebalance + run_catalyst_backtest
├── validation.py        Layer A smoke tests (9 invariants)
└── tests/
    ├── conftest.py      catalyst_minimal_config fixture
    ├── test_engine.py   7 engine unit tests
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
| `_mark_to_market`, `_get_exec_price`, `_slice_history_to_date` | execution helpers |
| `compute_data_fingerprint` | provenance hash |
| `build_waterfall` | 5-tier methodology report |
| `write_daily_csv`, `write_trades_csv`, `write_waterfall_json` | output writers |
| `HydraBacktestValidationError` | validation failure exception |
| `load_catalyst_assets`, `load_yield_series` | data loaders |

## Layer A smoke tests

`run_catalyst_smoke_tests` enforces 9 invariants and aggregates all
failures into a single `HydraBacktestValidationError`:

**Mathematical** (shared with v1.0/v1.1):
1. No NaN in critical columns
2. Cash never < -1.0
3. Drawdown ∈ [-1.0, 0]
4. Peak monotonic non-decreasing
5. Annualized vol ∈ [0.5%, 50%]
6. No outlier daily returns > ±15% (2008 + 2020 crash days allowlisted)

**Catalyst-specific**:
7. `n_positions ∈ [0, 4]` always (= `len(CATALYST_TREND_ASSETS)`)
8. Trade exit reasons ⊆ `{'CATALYST_TREND_OFF', 'CATALYST_BACKTEST_END'}`
9. Rebalance cadence: consecutive rebalance days exactly
   `CATALYST_REBALANCE_DAYS` (=5) apart after the first one

## v1.2 limitations (deferred to later versions)

- **No HydraCapitalManager integration** — Catalyst standalone runs on
  100% of capital. Live uses a 15% ring-fence + cash recycling. v1.4
  will integrate.
- **No permanent gold sub-strategy** — `catalyst_signals.py` removed it
  (`CATALYST_GOLD_WEIGHT = 0.0`). GLD participates only via the trend
  filter.
- **No asset proxies for pre-inception periods** — each asset enters the
  strategy only when it has ≥200 days of real history. Pre-2002 the
  strategy is 100% cash. v1.5 may add GC=F → GLD proxy and similar.
- **No Layer B / Layer C cross-validation** — only Layer A smoke tests
  block. v1.5 may compare against `experiments/exp68_4th_pillar_*.py`
  and live state JSONs.
- **"Silent over-allocation" mirrored, not corrected** — when an
  existing holding's target_shares shrinks (because per_asset shrank),
  the engine never sells down. This is a 1:1 mirror of live behavior so
  the backtest matches what the production engine actually does.

## Roadmap

| Version | Status | Contains |
|---|---|---|
| v1.0 | ✅ DONE | COMPASS standalone |
| v1.1 | ✅ DONE | Rattlesnake standalone |
| **v1.2** | ✅ THIS | Catalyst standalone |
| v1.3 | pending | EFA standalone (passive overflow) |
| v1.4 | pending | HYDRA full integration with HydraCapitalManager |
| v1.5 | pending | Replace dashboard `hydra_clean_daily.csv` |

## See also

- Spec: `docs/superpowers/specs/2026-04-07-hydra-backtest-v1.2-catalyst-design.md`
- Plan: `docs/superpowers/plans/2026-04-07-hydra-backtest-v1.2-catalyst.md`
- Live signals: `catalyst_signals.py`
- Live consumer: `omnicapital_live.py::COMPASSLive._manage_catalyst_positions`
