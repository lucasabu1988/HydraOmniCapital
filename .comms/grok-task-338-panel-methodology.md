# TASK-338 — PIT panel data & methodology sheet (PROD vs T20, executable)

`experiments/panel_methodology.py`. Imports `redesign_lab`, does not edit it. No new
configs. `run_any(P, cfg)` executable on the OOS panel (`_sweep_cache_oos/close.pkl`).

Panel: 2004-01-02 → 2026-09-04, 5705 bars, 1209 Yahoo columns. 1084 cycles each.
Matches Claude's audit §5: PROD ann_net **5.36**, T20 **7.36**.

## Identity of the prices

- **Source:** yfinance download with `auto_adjust=True` (see `data/fetch.py`,
  `experiments/backtest_variant_sweep.py`, this panel's cache).
- **What `auto_adjust=True` does:** yfinance returns a `Close` that is the
  split- *and dividend-adjusted* series (Adj Close promoted to Close). Daily
  `pct_change` is therefore a **total-return approximation**: dividends sit inside
  the price path via backward adjustment, not as a separate cash yield. It is not
  a formal total-return index (no withholding, no VWAP reinvestment, odd
  corporate actions can still be messy). Dividends are **not** missing.
- **Entity suffix (TASK-325):** `pit_yahoo_symbol` strips `-YYYYMM` only when the
  bare symbol is not in the current S&P and does not appear unsuffixed on/after
  the delist month. Better no prices than another company's. 17 blocked in 2004
  → 0 from 2018. Unmapped members never enter `elig`.
- **Stale / write-off (tranche_book):** a held name with no print is carried at
  last price for 10 bars, then written off at that last price (cash += proceeds,
  recorded in `df.attrs['write_offs']`). Not a trade, so 0 cost on the write-off.
- **Entry:** signal close *t*, execution close *t+1*, measurement *t+1 → t+1+step*.
  Costs 10 bp/side on dollars traded.

## Price coverage (PIT members vs members with a valid close)

Same universe for both variants. Year-end bar of each year (raw PIT, mapped to
Yahoo, blocked by the suffix rule, with a non-NaN close that day). Spots from
`--oos` in parentheses where they differ from year-end.

```
year   raw  mapped  blocked  with_px   pct
2004   501     483       17      264  52.7
2005   501     485       15      276  55.1   (30 Jun: 501/484/16/265 52.9%)
2008   501     490       10      311  62.1   (15 Sep: 502/490/10/308 61.4%)
2011   501     491        9      341  68.1   (30 Jun: 501/491/9/333 66.5%)
2014   504     495        7      363  72.0   (30 Jun: 503/494/7/361 71.8%)
2017   515     505        1      415  80.6   (30 Jun: 516/504/3/409 79.3%)
2020   505     505        0      446  88.3   (30 Jun: 505/505/0/443 87.7%)
2023   503     503        0      480  95.4   (30 Jun: 503/503/0/476 94.6%)
2026   503     503        0      500  99.4
```

Membership is real. Prices are not survivorship-free. Absolute ann%/Sharpe are
not quotable without this table (TASK-325 caveat, unchanged).

## PROD (executable)

| | |
|---|---|
| cycles / trades | 1084 / 24 286 |
| ann gross / net | 9.59 / **5.36** |
| Sharpe / maxDD / turnover | 0.41 / −38.1 / 39.1%/week |
| exposure / avg n | 91% / 16.1 |
| write-offs | **0** |
| write-off at last px vs at 0 | 5.36 → 5.36 (nothing to stress) |

Doomed = traded names whose Yahoo series ends before 2026-09-04:
`AET, ANDV, BMS, ESRX, EVHC, SCG, SVU, TWX` (8).

Share of *traded dollars* that year sitting in names that later lose their
series (doomed_traded_share):

```
2005 3.7%  2006 1.6  2007 4.7  2008 0.6  2009 2.1
2010 0.1   2011 1.5  2012 1.7  2013 2.2  2014 2.1
2015 0.7   2016 1.6  2017 1.4  2018 2.6  2019..2026 0.0
```

**Reuse (Yahoo series starts after the membership window):**
`after_window_traded = []`. No PROD trade was in a name whose first Yahoo print
is after that name left the index. TASK-325's block did its job on the book.

The 95% "late_start" share in 2005 in the first dump is **left-censoring**, not
reuse: those names were S&P members before 2004-01-02 and the panel simply
starts then (AAPL, XOM, …). Script corrected to split `left_censored` vs
`late_start` (joined during the sample, Yahoo late) vs `after_window` (reuse).
The shares above for doomed / after_window did not use the shared-set bug
(only the name *counts* in the by-year print did; unique lists are the ones
quoted).

## T20 (executable)

| | |
|---|---|
| cycles / trades | 1084 / 26 557 |
| ann gross / net | 8.61 / **7.36** |
| Sharpe / maxDD / turnover | 0.58 / −29.7 / 11.5%/week |
| exposure / avg n / distinct | 86% / 16.7 per tranche / 31.2 distinct |
| write-offs | **3** (proceeds 0.222 of starting book = 1) |

Write-off detail (carried 10 bars at last price, then cash += proceeds):

| date | tranche | ticker | proceeds | last print |
|---|---|---|---|---|
| 2019-02-22 | 1 | ESRX | 0.081 | 2018-12-21 |
| 2019-02-22 | 2 | ESRX | 0.069 | 2018-12-21 |
| 2019-03-01 | 2 | SCG  | 0.073 | 2018-12-31 |

ESRX = Express Scripts, acquired by Cigna 2018. SCG = SCANA, acquired by
Dominion 2018. Two T20 tranches still held ESRX through the 10-bar stale window.

**Sensitivity, write-off at 0 instead of last price:** proceeds 0.222 are
destroyed instead of recovered. T20 ann_net **7.36 → 6.90** (−0.46 pp). Not
rounding error. PROD unchanged (0 write-offs).

Doomed names traded: `AET, ANDV, BMS, ESRX, SCG, SVU, TWX` (7; no EVHC).
Doomed_traded_share:

```
2005 3.1%  2006 3.5  2007 3.5  2008 5.6  2009 2.7
2010 0.0   2011 1.8  2012 0.8  2013 2.9  2014 1.0
2015 1.7   2016 1.5  2017 1.8  2018 3.2  2019..2026 0.0
```

Reuse: `after_window_traded = []`, same as PROD.

## Which variant is more exposed, and why

Coverage of the *universe* is identical — both select from `yahoo_membership_as_of`
on this panel.

**T20 is more exposed to delisting-while-held.** A 20-bar hold in 4 tranches can
keep a name 15 bars after the last print (10 stale + remaining tranche life),
which is how ESRX/SCG became write-offs. PROD fully rebalances every 5 bars, so
the same names are sold before the 10-bar write-off fires (0 write-offs). The
0.46 pp hit if those three are marked to zero is a T20-only number.

**PROD is more exposed to *trading* doomed names**, not to holding them through
the death: 39%/week turnover vs 11.5%, similar doomed share of traded dollars
in most years (a few percent pre-2019, then zero). 2008 is the exception — T20
doomed share 5.6% vs PROD 0.6% — consistent with holding through the crash.

**Neither is exposed to ticker-reuse in the book.** Zero trades whose Yahoo
series starts after the membership window. The 38 unmapped suffixes never
become columns, so they cannot be selected.

Survivorship of *prices* (53% of 2004 members have a close → 99% in 2026) is a
panel fact, not a variant fact. It still inflates both books the same way
TASK-325 described: names without prices cannot be picked. T20's extra
exposure is the hold-through-delist channel, quantified as 3 write-offs / 0.22
book / 0.46 pp if marked to zero.
