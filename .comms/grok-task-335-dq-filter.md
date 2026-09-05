# TASK-335 — data-quality jump filter (production)

**From:** Grok
**Date:** 2026-09-06
Filter, not scoring (SPEC §1). Did not edit `redesign_lab.py`, `sleeve_lab.py`, or the harness.

`apply_data_quality_filter(prices, max_abs_daily_return=1.0, lookback=252)` in `core/filters.py`:
a name drops iff max |daily return| over the **trailing** `lookback` bars is **strictly greater**
than the threshold (same `>` as the lab's `P.JUMP252` / `max_jump`). Older jumps outside the
window do not count. All-NaN columns are kept (they cannot prove a jump). Wired in `screener.py`
immediately after `apply_practical_filters`, before the zombie check; dropped names print like
the zombie filter.

## Tests

`test_data_quality_filter.py` (9): recent jump drops only that name; negative jump uses |r|;
`|r| == 1.0` is kept; jump 350 bars ago survives lookback=252 and drops when lookback covers
it; jump on the first bar of the window drops; empty passthrough; all-NaN kept; 0→positive
(inf) drops.

`python run_all_tests.py`: 16 passed, 1 skipped.

## Production universe (2026-09-05, UNIVERSE=all, yfinance 1y = 252 bars)

Same order as the screener: practical filters, then this rule.

```
universe                 3002 unique (SP500+Nasdaq100+Dow+R1k+R2k)
blacklisted              2 (BF.B, BRK.B)
downloaded               3000/3000, 0 failed batches, last bar 2026-09-04
after practical          2539  (vol 275, dollar_vol 123, min_price 63)
DQ jump |r|>100%/252     14 dropped  (0.55% of the post-practical book)
remaining                2525
```

Dropped, largest |r| first:

| ticker | max \|r\| | date of jump | last close |
|---|---|---|---|
| DMRA | 3.830 | 2025-10-07 | 30.06 |
| QURE | 2.477 | 2025-09-24 | 44.50 |
| FTH  | 1.875 | 2026-02-18 | 40.05 |
| PRAX | 1.837 | 2025-10-16 | 351.81 |
| MRNA | 1.770 | 2026-08-19 | 145.55 |
| CRVS | 1.660 | 2026-01-20 | 14.39 |
| OMER | 1.541 | 2025-10-15 | 18.95 |
| OLMA | 1.364 | 2025-11-18 | 10.75 |
| RAPP | 1.192 | 2025-09-08 | 45.77 |
| COGT | 1.190 | 2025-11-10 | 34.76 |
| AGL  | 1.178 | 2026-05-07 | 88.50 |
| REPL | 1.070 | 2026-07-31 | 15.04 |
| GPCR | 1.025 | 2025-12-08 | 47.34 |
| INBX | 1.020 | 2025-10-24 | 121.17 |

These are live names at double-digit prices, not the penny artefacts (COMS/MCIC at 0.00).
MRNA is the same real +177% day the corpus already named. The rest are mostly biotech event
days (and AGL, which TASK-326 already flagged as a reused ticker). They stay ineligible for
a year after the jump — that is the list change, same as HIG/CAR/MRNA on the PIT panel.

The +500% reverse-split junk the legacy project saw is **not** in today's Russell-heavy list
after practical filters. The filter is still the right defence for the next one.

## PIT panel last bar (footnote, not production)

On `_sweep_cache_oos/close.pkl` at 2026-09-04 (1209 columns, full history, trailing 252):
**7 dropped** — COMS, CPWR, MCIC, MI, STI, UPC (Yahoo reuse / pennies) and MRNA. Membership
from TASK-325 already keeps the six garbage series out of selection; the filter would have
caught them on prices alone. Matches corpus review §2.

## What this is not

Not a scoring change. Threshold 1.0 / lookback 252 are hardcoded at the call site, not new
`config.py` knobs. `run_real_full_sp500.py` was not in the Files list and was not wired.
