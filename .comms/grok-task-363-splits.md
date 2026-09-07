# TASK-363 — Splits in the live book, H-003 (done by Claude, 2026-09-06)

Branch `post-freeze-wiring`, commit `1dc416f`. **Behind `config.APPLY_SPLITS = False`**: the modules and
tests are in place, the wiring runs only when Lucas accepts H-003 (`.comms/hypotheses.md`). Accounting,
not scoring — same principle as H-001 (dividends).

## Why

Yahoo closes are split-adjusted, the book's `units` are not: a 2:1 split halves the position on paper at
the next mark and `reconcile` shows a phantom quantity diff against the broker.

## What landed

- `data/splits.py` — `fetch_splits(tickers)` from `yf.Ticker(t).splits`, cached in
  `data_cache/splits_cache.json`, one download per ticker per UTC day, cache fallback, never raises.
- `core/splits.py` — `apply_splits(state, table, today)`: for each split effective in
  `(last_run_date, today]`, the units held on the split date are reconstructed from the ledger
  (`holdings_before`, now split-aware), scaled by the ratio and added to the tranche (so a fill settled
  after the split is not scaled twice); `last_px /= ratio`; pending `est_units` x ratio and `est_price`
  / ratio (display), dollar orders untouched, `close` orders need nothing. Records
  `{date, since, sleeve, tranche, ticker, ratio, units_before, units_after}` in `state["splits"]`,
  idempotent on `(date, sleeve, tranche, ticker)`.
- `core/dividends.holdings_before` applies recorded splits before the as-of date (a dividend after a
  split pays on post-split units); `core/state_check.replay` applies split records before that day's
  fills, so `verify_state` stays clean.
- `portfolio_v9.run(split_fn=...)`: after settle, before dividends, only when `APPLY_SPLITS`; the sheet
  gets a "Splits" section, the dashboard log a `split` row, `reconcile` lists `splits recorded`.

## Tests (8, `test_splits.py`)

2:1 (units x2, last_px /2), 1:10 reverse, not-held and out-of-window ignored, same split twice is a
no-op, a fill settled after the split is not rescaled, replay clean + holdings and a later dividend are
split-aware, pending estimates rescaled with dollars untouched, `run()` skips the fetch when the flag is
off and applies when on (sheet shows the section).

## Decision: ACCEPTED by Lucas 2026-09-06

`APPLY_SPLITS = True` and the SPEC 9.3 paragraph landed on the branch (`4a77d6f`); live with the merge.

## (original text)

H-003 in `.comms/hypotheses.md`: ACCEPT -> `APPLY_SPLITS = True` in `config.py` (one-line, after the
merge), REJECT -> the modules stay as tooling for `reconcile`. Recommendation: accept; the book cannot be
reconciled through a split without it.
