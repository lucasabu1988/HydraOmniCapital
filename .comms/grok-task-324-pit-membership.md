# TASK-324 — Point-in-time membership (design note)

**From:** Grok
**Date:** 2026-09-06
**Status:** implementing after this note (Lucas ordered 321-324). Claude: the membership logic is the part to review.

## Why this is easy to get wrong

Wikipedia's S&P 500 page has two useful tables: current constituents (`Symbol`) and
**"Selected changes to the list"**. The second is *selected*, not complete. Walking only
that changelog backwards from today's list will miss additions/removals Wikipedia never
bothered to record, and will never resurrect names that left before the changelog starts.

So: Wikipedia-alone reconstruction is **biased toward recent, well-documented changes**.
It is still better than "today's 500 for every year", which is what the deep-dive used.

## Reconstruction rule (Wikipedia)

Let `C` = today's constituent set.
Let `changes` = rows `(date, added, removed)` parsed from the changes table.

`membership(as_of)`:
1. start with `C`
2. for every change with `date > as_of`, **undo** it: drop `added`, add back `removed`
3. result is the set that would have been in the index just after the last change ≤ as_of,
   modulo Wikipedia's incomplete log

Dates parsed as calendar dates (not trading days). Tickers normalised to Yahoo style
(`BRK.B` → `BRK-B`).

## Supplement (not a silent substitute)

If fetchable, also cache `fja05680/sp500` historical-components CSV (the same source
exp40 used). When that file exists, `membership(as_of)` prefers it: it is a dated
snapshot, not an incomplete changelog. Wikipedia remains the SPEC-requested path and
the fallback.

A run logs which source it used and how many names the two methods disagree on for a
spot-check date, so a broken parser cannot hide.

## Prices

yfinance, 2004-01-01 through today, union of all PIT names in the window. Missing
bars and dead tickers **stay missing** — they are the survivorship signal. Eligibility
on a date is: in the PIT set that day AND has a valid close that day. No forward-fill
across a delisting.

## What we re-measure (no tuning)

On that sample, three claims only:
1. vol-scaling exponent k=0 vs k=1 (deep-dive 4.1)
2. TASK-320 hard sector cap vs no sector control
3. regime gate on vs off

If 2020-2026 does not survive 2004-2019 / 2008, the 2020-2026 result was the sample.

## What we will not do

- Optimise any parameter on the OOS window
- Drop a ticker from the universe because yfinance has no history
- Pretend Wikipedia selected-changes is complete

## Run (2026-09-06) — do not tune on this

Source used: **github snapshots** (fja05680, 2595 dates). Wikipedia selected-changes parse returned 0 rows (`html5lib` missing; lxml did not yield the changes table). Spot-check 2008-09-15: 502 names.

Prices: yfinance 2004-01-02 .. 2026-09-04, 1179 tickers (many delisted failed — expected). 1088 weekly cycles. Cost 10 bp/side modelled.

```
variant                     cycles  mean_bp  net_bp  ann%   Sharpe  maxDD
baseline k=1 + sector cap     1088     19.0    11.7   8.67    0.61  -35.3
vol_exp=0                     1088     18.5    11.5   7.70    0.48  -41.3
no sector control             1088     19.5    12.3   8.89    0.61  -34.9
no regime gate                1088     24.2    16.4  11.14    0.68  -47.4
```

Falsification vs 2020-2026 survivors-only sample:
1. **k=0 does not beat k=1** here (18.5 vs 19.0 bp, worse Sharpe and maxDD). The 2020-2026 k=0 headline was the sample.
2. **Sector cap is cheap** on this window (−0.5 bp vs no control) and does not improve maxDD.
3. **Regime gate costs return** (−5.2 bp vs off) and **buys drawdown** (−35.3% vs −47.4%). That trade-off survived; the 2020-2026 "gate is free" vibe did not.

Reproduce: `python experiments/backtest_variant_sweep.py --oos` (uses `experiments/_sweep_cache_oos/` if present).

---

