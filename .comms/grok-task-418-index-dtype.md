# TASK-418 — load_panel normalizes StringDtype axes

Parity with the engine (`test_review_341`, `test_portfolio_engine`) failed locally
only when `experiments/_sweep_cache/` was present: pickle restored ticker columns as
`StringDtype`, the engine builds `object` indexes, `assert_series_equal` refused.
CI has no cache, so the gate was green for the wrong reason.

## What landed

`experiments/redesign_lab.load_panel` is the single site. After `Panels()` builds,
`_normalize_panel_axes` rewrites any StringDtype index/columns to a plain object
Index of Python str. DatetimeIndex is left alone. `prepare_panel` then derives the
rest from the already-normalized `P.close`.

New test `test_lab_index_dtype.py` pickles a cache whose columns are StringDtype
and asserts the loader returns `object`.

The two parity tests were not edited: they already skip without a cache and now
pass with one.

## Numbers

`engine_backtest.py --oos` after the change: **7.03 / 0.74 / -17.7** (1083 cycles,
2005-02-11 -> 2026-08-24). Same row as the post-consolidation reference. The
in-sample and OOS caches on this machine already stored object columns; the
loader now also accepts StringDtype without moving a number.

Suite: 92 passed, 0 skipped. ruff clean.
