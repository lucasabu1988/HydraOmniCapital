# TASK-342 — local live v9 dashboard

Read-only over `state/portfolio_v9.json`. Bind `127.0.0.1` only. Never mutates
state, never places orders, never webhooks. The only write is append-only
`state/equity_curve.csv` (timestamp, total, stocks, etf, cash, spy_close),
idempotent per timestamp.

## Cost basis (average cost)

Per `(sleeve, tranche, ticker)` walking the ledger then write-offs:

- filled **buy**: `qty += u; cost_total += u * price`
- filled **sell**: `realised += (price - avg) * u`; qty down; avg unchanged
- **write-off**: `realised += proceeds - cost_total`; qty = 0
- `cost` (fees) summed separately, **not** in avg
- `not_filled` / `noted` / transfers do not move units

Unrealised = `(last - avg) * remaining units`.

## Files

- `dashboard_v9.py` — `build_snapshot(state, quotes, spy)` (pure), quotes via
  yfinance with `last_px` fallback marked stale, stdlib `ThreadingHTTPServer`
- `dashboard/index.html` — polls `/api/snapshot`; banner required
- `test_dashboard_v9.py` — 6 tests, no network

## Run

```
cd hydra_screener_local
python dashboard_v9.py
```

Prints `http://127.0.0.1:8765/`. `--refresh` default 300s (quote cache TTL).
Until the first real `state/` exists, the page shows "sin estado v9".

Did not touch `portfolio_v9.py`, `core/`, `daily.py`.
