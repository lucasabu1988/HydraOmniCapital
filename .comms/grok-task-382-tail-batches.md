# TASK-382 — Tail fetch: fewer round trips when the window is short (done by Claude, 2026-09-06)

Grok ran out of credits; Claude finished it on main (freeze-safe: provider + cached path only,
`USE_BAR_STORE` still False).

## What landed

- `YFinanceProvider(tail_batch_size=300, tail_sleep=0.25, tail_max_bars=15)`: a window of <= 15 business
  days is a *tail* and uses the big batch and the short pause; the full-period path keeps 75 / 1 s.
  `batch_plan(start, end)` exposes the decision; `last_batches` / `total_batches` count downloads.
  No sleep after the last batch (the direct path already had none).
- **Second defect found by the bench:** the cached path computed one tail window for all 3000 names from
  the *earliest* overlap start, and eight warrants whose last stored bar is 2026-07-17 (CORZW, CORZZ,
  DJTWW, KYIVW, RGTIW, RUMBW, RVMDW, SVREW) dragged an 11-bar tail into a 35-bar window — the tail path
  never applied, whatever the batch size. Now names whose last bar is older than `BAR_STORE_STALE_BDAYS`
  (20) get their own request; the recent names share the short window.
- `experiments/tail_batch_bench.py`: N runs per size against the seeded store, counting downloads,
  failed/missing names, readjusts, lost batches and rate-limit hits.

## Measurement (3012 names, 2y window, seeded store, 3 runs each, 2026-09-06 afternoon)

| tail batch | wall s (min / med / max) | downloads | failed | missing* | readjusted | lost batches | 429 |
|---|---|---|---|---|---|---|---|
| 75 (old) | 136.2 / 148.2 / 153.9 | 42 | 0 | 2 | 0 | 0 | 0 |
| 150 | 130.0 / 134.4 / 149.4 | 22 | 0 | 2 | 0 | 0 | 0 |
| **300** | **117.2 / 117.9 / 127.2** | 12 | 0 | 2 | 0 | 0 | 0 |
| 500 | 113.8 / 135.6 / 138.2 | 8 | 0 | 2 | 0 | 0 | 0 |

\* the two "missing" are BF.B and BRK.B, filtered as bad tickers by the same rule the live fetch applies.

Direct path on the same day (TASK-378): 162 s. **300 is the setting kept**: lowest median with the
tightest spread and zero rate-limit errors across its three runs; 500 saves four more requests but is
noisier (114-138 s) and gains nothing in the median. Where the remaining ~117 s go: ~40 s of Yahoo
requests, the rest is the 3000 per-ticker overlap comparisons (one SQLite read each) and the upsert —
that is the next lever if one is ever needed (a single query for all overlaps).

## Flip criterion (revised in the TASK-378 review)

Zero data diffs (TASK-370: max rel 7.1e-7, ranking identical) **and** cached <= direct + 2 min: met
(117 s vs 162 s). `USE_BAR_STORE` flips after "first settle verified".

## Tests

`test_bar_store.py` +4: tail window uses the big batch (one download for seven names), long window keeps
75-style batching, no sleep after the last batch, a stale name gets its own window while the recent
names keep the 10-bar overlap. Suite green.
