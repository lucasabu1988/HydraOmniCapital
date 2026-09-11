# TASK-425 — the membership probe no longer calls Yahoo a hit rate

`russell_free_membership.py` was pricing departed names (and the current-list alive/dead
split) through `yfinance`. On 2026-09-11 that run returned 93 failed downloads and
`YFRateLimitError` on MSFT / RTX / SCHW: the 17-27% "hit rate" mixed "Yahoo has no
price" with "Yahoo would not answer".

## What landed

- `eodhd_closes` uses `EODHDProvider.fetch`. Report fields: `priced`, `no_price`,
  `provider_failed`, `control_hits`, `reliable`. There is no summed hit-rate field.
- 404 / `no rows` = no price. Timeouts, 5xx, non-JSON = the provider failed.
- `probe_reliable()` is unchanged and still the valla: every control (SPY, AAPL, MSFT)
  must print or the probe is not evidence.
- `yahoo_closes` is gone. `printing_recently` and `yahoo_price_probe` both go through
  EODHD. Injected `provider=` keeps the tests offline.

Suite: 95 passed, 0 skipped, ruff clean.
