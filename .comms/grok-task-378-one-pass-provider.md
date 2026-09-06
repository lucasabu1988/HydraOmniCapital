# TASK-378 — One download per batch in the bar-store provider

Live path unchanged. Default `YFinanceProvider` is one-pass;
`two_pass=True` keeps the old double download for parity.

## What landed

- One `auto_adjust=False` download per batch. `close_adj` = `Adj Close`,
  `close_raw` = `Close`, volume = `Volume`.
- `_close_frame_from_yf(..., field=)` accepts `Adj Close`.
- Tests: fake MultiIndex with the three fields, **exactly one download per
  batch**; `two_pass=True` still does two.

## Equivalence (50 random stored + 10 ETFs, 2024-09-01 → 2026-09-04)

One-pass `Adj Close` vs two-pass `Close` with `auto_adjust=True`: **60 / 60
within 1e-9, max rel = 0.0.** Same factor.

## Wall time (`store_parity.py --period 2y`, full universe)

| | TASK-370 (two-pass) | TASK-378 (one-pass) |
|---|---|---|
| direct | 154–162 s | **162.3 s** |
| cached tail | 284–290 s | **227.6 s** |

One-pass saved ~60 s on the cached path (the second Yahoo download). Cached is
**still slower than direct** (227 vs 162, gap ~65 s).

Where the time goes: **per-batch overhead, not rows.** Both paths sleep 1 s
between 40 batches of 75 (~39 s). Yahoo RTT is paid per batch whether the
window is 10 bars or 500. Cached also loops 3000 overlap compares and upserts
SQLite, plus two extra ETF/IRX tail calls. Do not shrink the batch size: more
batches would add more RTTs and sleeps.

The Tuesday flip still wants cached < direct. This change is necessary but not
sufficient; a later task would have to drop the inter-batch sleep on the
already-warm store or overlap-compare without a full 3000-name Yahoo round.
