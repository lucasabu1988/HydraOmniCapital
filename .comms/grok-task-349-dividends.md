# TASK-349 — dividends in the live book

Lucas lifted the HOLD ("trabajar en 349"). Same principle as interest: backtests
use `auto_adjust=True` (total return); the live book now credits the cash
dividend the broker will pay.

Does not edit `core/portfolio_engine.py`.

## Modules

- `data/dividends.py`: `yf.Ticker.dividends` (ex-date index), cache
  `data_cache/dividends_cache.json`, never raises, failures in `report`.
- `core/dividends.py` (pure): for every ex-date in `(last_run_date, today]`,
  credit `units held before the ex-date × dps` to that tranche's cash.
  Holdings reconstructed from the ledger (`exec_date < ex_date`; a buy on the
  ex-date does not get it). Recorded in `state["dividends"]`
  `{date, since, ex_date, sleeve, tranche, ticker, units, dps, dollars}`.
  Idempotent on `(ex_date, sleeve, tranche, ticker)`. First run (no
  `last_run_date`) credits nothing.

Applied in `portfolio_v9.run` after settle, before plan. Injected `fetch_fn`
(tests) does not hit Yahoo; `dividend_fn` is injectable.

## Display

Sheet and console: since last run + cumulative, per sleeve, like interest.
Dashboard: KPI **Dividendos** and `side=dividend` log rows. Missing key → 0.
`pnl_total` includes the cumulative (already in cash).

Broker pays on **pay-date**, later than ex-date. `reconcile.py` lists that lag
as a known residual (HOLD wording removed).

## Tests (`test_dividends.py` + dashboard/CLI)

Credit 10×0.50 / 4×0.25; units-on-ex-date (sold after still paid); buy-on-ex-date
skipped; idempotent; first run empty; summarize missing key; yfinance patched +
cache fallback; dashboard KPI/log; sheet; `run()` credits before plan.
