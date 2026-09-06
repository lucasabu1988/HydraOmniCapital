# TASK-370 — Seed the bar store and cached-vs-direct evidence

`USE_BAR_STORE` still False. Claude flips after reading this. No live-path edit.

## (1) Backfill

```
python store_cli.py --backfill --period 20y --universe all
```

| | |
|---|---|
| wall | **1039 s** (~17 min) |
| universe | 3002 unique; 2 filtered (`BF.B`, `BRK.B`); **3000** stored |
| bars | **10,309,441** (after parity ETF/^IRX ingest: 10,314,952) |
| first / last | 2006-09-06 / 2026-09-04 |
| size | **1222 MB** (1,281,531,904 bytes; 1287 MB after ETF/^IRX) |
| failed | **0** |
| readjusted | **0** (first fill, nothing to overlap) |

Coverage by year (tickers with ≥1 bar / bar count):

```
2006 1437 / 115k     2013 1757 / 433k     2020 2368 / 575k
2007 1490 / 368k     2014 1838 / 454k     2021 2579 / 627k
2008 1521 / 381k     2015 1911 / 473k     2022 2636 / 655k
2009 1547 / 385k     2016 1964 / 487k     2023 2695 / 666k
2010 1601 / 397k     2017 2030 / 501k     2024 2779 / 691k
2011 1632 / 408k     2018 2129 / 523k     2025 2886 / 708k
2012 1686 / 415k     2019 2219 / 548k     2026 3000 / 500k
```

Early years are thinner because today's `all` universe is survivors; that is the
same survivorship the live fetch has. Not a store defect.

## (2) Same-day parity (`experiments/store_parity.py --period 2y`)

Direct: `fetch_prices_and_volume` + `fetch_etf_closes` + `fetch_tbill`.
Cached: `fetch_prices_and_volume_cached` on the seeded store (tail + ETF/^IRX insert).

| series | both | cached_only | direct_only | max_rel median / p99 / max | > 1e-6 |
|---|---|---|---|---|---|
| stock adj close | 3000 | 0 | 0 | 1.6e-7 / 4.8e-7 / **7.1e-7** | **0** |
| volume | 3000 | 0 | 0 | 0 / 0 / 0 | 0 |
| ETF adj close | 10 | 0 | 0 | 2e-7 / 4.5e-7 / 4.5e-7 | 0 |
| ^IRX raw | 1 | 0 | 0 | 0 / 0 / 0 | 0 |

Shapes: direct stocks **502 × 3000**, cached **501 × 3000** (ETF 502 vs 501).
The extra direct bar is the yfinance `2y` window reaching one session past the
store's last date (2026-09-04). Overlap matches; not a price bug.

Wall this run: direct **154 s**, cached **290 s**. Cached is not yet cheaper on a
full-universe *tail* (it still asks Yahoo for 3000 names × 10 overlap bars, plus
first-time ETF/^IRX). The save is the 20y history (10M bars, 17 min) that a
direct path would re-download every day. After the flip, a Tuesday run should
only pay the tail.

Scratch: `experiments/_lab_scratch/task370.json` (gitignored).

## (3) Ranking

`build_ranking` on the 3000 common names, same SPY, both volume frames.

- top-40 **names equal**
- `composite_score` max |diff| = **0.0** (atol 1e-9)

Sector lookup hit Yahoo rate-limit on 6 unknown names (FISV, GOOGM, GOOGN, HOS,
LION, NIQ) on *both* calls; both fell back to buckets/Other the same way. DQ
filter dropped the same 14 names; sector cap displaced the same 13. Not a store
diff.

## Recommendation

Prices and the ranking are within float noise of the direct path. Safe to flip
`USE_BAR_STORE` from Claude's side after the first settle, with the TASK-376
empty-replace guard first (a failed batch must not wipe stored history).
