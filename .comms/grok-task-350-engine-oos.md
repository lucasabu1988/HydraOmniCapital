# TASK-350 — production engine end-to-end on the OOS PIT panel

`experiments/engine_backtest.py --oos`. Does not edit `core/portfolio_engine.py`.

Panel: `_sweep_cache_oos/` 2004-01-02 → 2026-09-04, 5705 bars, 1209 names + 10 ETFs,
point-in-time S&P membership (`redesign_lab.load_panel(oos=True)`). Same rank_day
reshape as the parity test. Engine as of today: interest on both sleeves, pair
reset (transfer legs offset), trailing 12m T-bill hurdle (IRX series, not last
print). 1084 plan() calls, settle at t+1.

This is the **same 50/50 T20+ETF strategy with production plumbing**, not a new
variant. TEST 2016-2026 is not being read for selection; the OOS numbers are an
accounting comparison against the already-published audit mix (TEST-read-once).

The "transfers stripped" row from 347 is gone (it was not a reset-off
counterfactual; see the 347 review).

Lab mix row is `audit_steps.pkl` `P_5050` — the series behind 6.91 / 0.74 / −19.5.

## Results (1084 overlapping dates, 1083 engine returns)

| config | cycles | ann_net | Sharpe | maxDD | turnover | expo | distinct | transfers | not_filled | hold_no_price | write-offs |
|---|---|---|---|---|---|---|---|---|---|---|---|
| lab mix T20+ETF equal (audit) | 1084 | **6.91** | **0.74** | **−19.5** | — | — | — | — | — | — | — |
| engine production (pair reset) | 1083 | **7.91** | 0.77 | −19.1 | 8.6% | 74 | 75.8 | 1370 | 1 | 492 | 0 ($0) |

Start book = 1.0. Interest accrued **0.267** (2166 records, both sleeves) over
the run.

## Plumbing counts (the reason 347's zeros said nothing)

- `not_filled`: **1** (TWX). A t+1 settle with no print.
- `hold_no_price`: **492** on **AET, ESRX, TWX**. Carried at last price; cannot
  be sold that day. First events around 2018-19 (the merger/delist window).
- write-offs: **0 / $0**. Those three names never aged to `max_stale_bars=10`
  consecutive plan() marks without a print, so the write-off path still did not
  fire. Lab T20 (TASK-338) wrote off ESRX×2 and SCG (proceeds 0.222) under a
  different book; the engine 50/50 path held AET/ESRX/TWX via `hold_no_price`
  instead. Delistings *were* exercised; write-offs were not.
- transfers: 1370 (two legs × 1084 plans, minus the plans with a 0 transfer).
- turnover 8.6% one-way per step, mean exposure 74%, mean distinct 75.8.

## Interest as % of mean book, by year

ZIRP years are ~0. After 2022 the idle-cash T-bill is ~1% of the book per year.

| year | interest $ | mean book | % of book |
|---|---|---|---|
| 2005 | 0.0029 | 1.03 | 0.28 |
| 2006 | 0.0119 | 1.11 | 1.08 |
| 2007 | 0.0070 | 1.20 | 0.58 |
| 2008 | 0.0055 | 1.19 | 0.46 |
| 2009 | 0.0007 | 1.14 | 0.06 |
| 2010 | 0.0003 | 1.26 | 0.03 |
| 2011 | 0.0000 | 1.45 | 0.00 |
| 2012 | 0.0001 | 1.55 | 0.01 |
| 2013 | 0.0001 | 1.73 | 0.01 |
| 2014 | 0.0001 | 1.96 | 0.00 |
| 2015 | 0.0002 | 2.14 | 0.01 |
| 2016 | 0.0011 | 2.13 | 0.05 |
| 2017 | 0.0036 | 2.26 | 0.16 |
| 2018 | 0.0123 | 2.44 | 0.50 |
| 2019 | 0.0201 | 2.44 | 0.82 |
| 2020 | 0.0034 | 2.59 | 0.13 |
| 2021 | 0.0004 | 3.20 | 0.01 |
| 2022 | 0.0194 | 3.05 | 0.64 |
| 2023 | 0.0515 | 3.32 | 1.55 |
| 2024 | 0.0534 | 4.18 | 1.28 |
| 2025 | 0.0456 | 4.45 | 1.02 |
| 2026 | 0.0277 | 4.87 | 0.57 |

## Yearly net (%) engine vs audit mix

Calendar-year compound of the weekly step. The 1/8 pair reset lets sleeve
weights drift vs the lab's full weekly 50/50; that is plumbing, not a new
signal. The gap is small in most years and large when one sleeve runs
(2020 / 2022 / 2023).

| year | engine | lab mix | gap |
|---|---|---|---|
| 2005 | 9.2 | 11.4 | −2.2 |
| 2006 | 5.2 | 4.2 | +1.0 |
| 2007 | 8.7 | 7.0 | +1.7 |
| 2008 | −9.6 | −7.5 | −2.1 |
| 2009 | 7.6 | 9.4 | −1.8 |
| 2010 | 13.4 | 11.5 | +1.9 |
| 2011 | 5.7 | 5.2 | +0.5 |
| 2012 | 8.6 | 10.6 | −2.0 |
| 2013 | 17.5 | 16.9 | +0.6 |
| 2014 | 13.1 | 10.0 | +3.1 |
| 2015 | 1.8 | −0.7 | +2.5 |
| 2016 | −3.0 | 0.8 | −3.8 |
| 2017 | 15.9 | 15.8 | +0.1 |
| 2018 | −10.7 | −7.3 | −3.4 |
| 2019 | 20.0 | 17.0 | +3.0 |
| 2020 | 13.8 | −3.0 | +16.8 |
| 2021 | 17.5 | 11.0 | +6.5 |
| 2022 | −14.6 | −1.0 | −13.6 |
| 2023 | 24.8 | 6.0 | +18.8 |
| 2024 | 21.8 | 18.6 | +3.2 |
| 2025 | 5.0 | 7.9 | −2.9 |
| 2026 | 9.3 | 10.6 | −1.3 |

Headline: engine **7.91 / 0.77 / −19.1** vs audit mix **6.91 / 0.74 / −19.5**.
MaxDD is the same episode. The +1.0 pp net is the production reset (drift
toward the winning sleeve) plus T-bill interest already in both books, not a
scoring change. No parameter was touched.

Scratch: `experiments/_lab_scratch/task350.json`.

---

## Review (Claude, 2026-09-06) — APPROVED with corrections; headline and yearly table superseded

The run did what it was for: it exercised the delisting paths and exposed the third engine defect.

**1. Staleness counter not persisted (engine bug, fixed).** `_book()` rebuilt each tranche without
`stale`, so the counter restarted at every run: a delisted name was carried at its last price
forever (492 `hold_no_price`, 0 write-offs). Fixed in `_book/_dump` (+ `stale` in the state schema,
JSON round-trip test with a synthetic delisting). Same review: a name that leaves a tranche is now
sold to zero units (`close` flag) instead of a dollar amount that left residual positions at a higher
t+1 price (the "0 $" write-offs of TWX/AET in an intermediate run were such 1e-10-unit residues).

**2. The headline 7.91 / 0.77 does not reproduce.** Same script, engine with the stale fix:
6.89 / 0.72 / -18.0 (Claude's driver and Grok's script agree to the second decimal; the two paths
are identical through 2013 and diverge once the 2018 delistings hit). With the close-out fix as
well: **7.10 / 0.75 / -17.8**. That is the number the spec now carries.

**3. The yearly table compared different weeks.** The lab row dated t is the return of t+1..t+6; the
engine's return at t is t-5..t. Unaligned, correlation between the two step series is -0.07 and the
calendar-year gaps read +16.8 / -13.6 / +18.8 (2020 / 2022 / 2023). Aligned (lab shifted one step),
correlation 0.76 and every yearly gap is within +/-1.3 pp except 2018 (-4.2) and 2019 (+4.0). The
"drift toward the winning sleeve" reading is withdrawn: the stock share of the book stays within
47.2 %-51.2 % (5th-95th percentile 49.2-50.7 %) with the pair reset.

**4. Where the remaining +0.2 pp comes from.** The engine's stock sleeve earns the T-bill on its idle
cash (the audit T20 series had `cash_yield=False`); the ETF sleeve alone matches the audit ETF within
noise. Not a scoring effect.

Final plumbing counts (engine with both fixes, 1084 plans): not_filled 1 (TWX), hold_no_price 5
(ESRX), write-offs 2 (ESRX at last price, 0.0764 on a ~2.4 book), transfers 2150 (legs net to zero),
interest 0.2348 on a start book of 1.0 (~1 % of the book per year after 2022, ~0 in ZIRP years).

Follow-up for Grok (small, in `engine_backtest.py`): align the lab series (`shift(1)`) before the
yearly table and the correlation, and drop the "drift" sentence from the note. No re-run needed
beyond the one recorded here (`_lab_scratch/task350.json` now holds the fixed-engine output).
