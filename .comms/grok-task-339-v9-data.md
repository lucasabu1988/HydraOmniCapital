# TASK-339 — v9 data layer

Pure additions to `data/fetch.py`. Scoring, `config.py` values, `core/`, `screener.py`
and `daily.py` were not edited (v8.4 still requests the default `period="1y"`).

## What landed

- `V9_PRICE_PERIOD = "2y"` — 12-7 needs 252 + 126 + vol63 bars. `fetch_prices_and_volume`
  already took `period`; the v8.4 call is unchanged. A v9 caller (TASK-340 / screener
  later) passes `period=V9_PRICE_PERIOD`.
- `fetch_etf_closes(symbols=None, period="2y", report=None)` — default universe
  SPY QQQ IWM EFA EEM TLT IEF GLD DBC VNQ. `auto_adjust=True`. Same retry-once /
  report-not-raise contract as the stock fetch (`requested`, `downloaded`,
  `failed_batches`, `failed_tickers`, `missing_share`).
- `fetch_tbill(period="2y", report=None)` — `^IRX` as a **percent** Series (e.g. 5.21,
  not 0.0521). `auto_adjust=False` (it is a yield, not a total-return price). Empty
  Series on failure, never raised.
- `FFILL_LIMIT_BARS = 3` on both new fetchers. Isolated holiday holes fill; a 4th
  consecutive NaN stays NaN. Holdings stale-carry (10 bars) is the engine's job.

## Tests (`test_fetch_v9.py`, yfinance patched, no network)

7 passed: v8.4 still asks `1y`; `period="2y"` is forwarded; ETF shape 12×10 in design
order; 2-bar hole fills and 4-bar hole leaves the 4th NaN; ETF/T-bill failures populate
`report` and do not raise; T-bill is percent and `auto_adjust is False`.

## Not in this task

- `screener.py` does not pass `2y` yet (would change the v8.4 call). TASK-340 / the
  engine CLI will.
- `config.V9` is Claude's; this module keeps its own default list so fetch does not
  depend on an uncommitted config block.
