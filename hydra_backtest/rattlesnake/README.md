# hydra_backtest.rattlesnake — Rattlesnake Standalone Backtest

Reproducible Rattlesnake mean-reversion backtest, the second pillar of
the HYDRA quantitative trading system.

## What this is

A Python sub-package that runs a Rattlesnake mean-reversion backtest
from 2000 to 2026 using point-in-time S&P 500 membership (intersected
with the hardcoded R_UNIVERSE), producing a waterfall methodology
report (baseline → +T-bill → +next-open → +slippage → NET HONEST).

**Consumer-not-owner principle** (inherited from v1.0): pure functions
are imported directly from `rattlesnake_signals.py` (the live engine
module). The reimplementation surface is ~250 LOC of pure helpers
(`apply_rattlesnake_exits`, `apply_rattlesnake_entries`,
`_resolve_rattlesnake_universe`, `_apply_rattlesnake_daily_costs`,
`run_rattlesnake_backtest`).

## How to run

```bash
# Download VIX history first (one-time setup)
python -c "import yfinance as yf; yf.download('^VIX', start='1999-01-01', end='2027-01-01').to_csv('data_cache/vix_history.csv')"

# Run backtest
python -m hydra_backtest.rattlesnake \
  --start 2000-01-01 \
  --end 2026-03-05 \
  --out-dir backtests/rattlesnake_v1 \
  --aaa-date-col observation_date --aaa-value-col yield_pct \
  --tbill data_cache/tbill_3m_fred.csv
```

Outputs in `backtests/rattlesnake_v1/`:
- `rattlesnake_v2_daily.csv` — daily equity curve
- `rattlesnake_v2_trades.csv` — all trades with exit reasons (`R_PROFIT`, `R_STOP`, `R_TIME`)
- `rattlesnake_v2_waterfall.json` — 5 tiers + metadata

Stdout shows progress per year and final waterfall summary table.

## How to test

```bash
pytest hydra_backtest/rattlesnake/tests/ -v -m "not slow"        # fast (~10s)
pytest hydra_backtest/rattlesnake/tests/ -v -m slow              # E2E (~5min)
pytest hydra_backtest/rattlesnake/tests/ -v --cov=hydra_backtest.rattlesnake
```

## Architecture

```
hydra_backtest/rattlesnake/
├── engine.py        — run_rattlesnake_backtest + apply_rattlesnake_*
├── validation.py    — Layer A smoke tests (Rattlesnake-adapted)
├── __main__.py      — CLI entrypoint
└── __init__.py      — public API
```

Reuses from `hydra_backtest/` (v1.0):
- `BacktestState`, `BacktestResult` dataclasses
- `_mark_to_market`, `_get_exec_price`, `_slice_history_to_date`
- `methodology.build_waterfall` (5-tier waterfall)
- `reporting` writers
- `data` loaders (with new `load_vix_series` helper)
- `errors` exception hierarchy

## Differences from COMPASS (v1.0)

| Aspect | COMPASS | Rattlesnake |
|---|---|---|
| Signal | Risk-adjusted momentum (90d/5d-skip) | Drop ≥8% in 5d + RSI(5)<25 + above SMA200 + volume |
| Universe | S&P 500 PIT top-40 by score | S&P 100 (R_UNIVERSE) ∩ S&P 500 PIT |
| Hold | 5 days (with renewal) | 8 days (no renewal) |
| Exits | Hold expired / position stop / trailing stop / rotation / regime reduce | Profit target (+4%) / stop (-5%) / time (≥8d) |
| Position size | Inverse-volatility weights, fractional shares | 20% of cash snapshot, INTEGER shares |
| Leverage | Vol-targeted 0.30-1.00 | 1.0 always |
| DD scaling | Yes (3 tiers) + crash brake | No |
| Sector limits | Max 3 per sector | None |
| Bull override | Yes (+1 position) | No |

## Limitations (v1.1)

- **Standalone only**: no integration with COMPASS, no cash recycling. Standalone Rattlesnake CAGR under-states its real contribution because the live engine recycles idle Rattlesnake cash to COMPASS via HydraCapitalManager. Full integration is v1.4.
- **R_UNIVERSE intersection with PIT S&P 500 is lossy** for tickers that were in S&P 100 but not S&P 500 (rare edge case)
- **VIX missing data → fail-closed** (no entries) per the v1.0 fix in `rattlesnake_signals.py` (commit b9d4ad7)
- **Layer B cross-validation against `archive/strategies/rattlesnake_v1.py` is best-effort** — if the archive script can't run, Layer A is the only blocking gate
