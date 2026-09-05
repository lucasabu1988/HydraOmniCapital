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

## TASK-325 (2026-09-05) — ticker reuse, coverage caveat, same three claims

Do not tune. Lucas asked to decide looking for better *honest* results, not better headline returns.

### What was wrong in 324

1. **Ticker reuse.** Blind `re.sub(r'-\d{6}$', '', t)` mapped 38 suffixed entities onto a live/reused symbol (26 of them current S&P members: AMP, BAC, C, DD, DELL, …). fja05680 applies those suffixes *retroactively*: `DD-201708` in 2008 is old DuPont, not today's DD. Better no prices than the other company's.

2. **Those suffixed names were also never selected.** Membership kept the suffix; price columns were stripped. So 324 both (a) downloaded the wrong series for collisions and (b) dropped the safe dead tickers that Yahoo still has (WAMUQ, etc.).

3. **Snapshots froze in 2019-01-11.** The file we used is Clenow's original (2595 dates). fja05680's *Updated* CSV continues to 2026-06-30 (123 extra dates) but strips suffixes. Wikipedia selected-changes still parses to 0 rows; `html5lib` is not declared and is not the path used.

4. **Coverage was under-stated as "survivorship signal".** A member without a Yahoo close cannot be selected — same as not existing. 2005: 53% of members have prices.

### Decisions (better sample, not better alpha)

- Keep **original** snapshots through 2019-01-11 (entity IDs with `-YYYYMM`).
- **Append Updated** after that date so 2019–2026 is not the January 2019 list.
- **Never strip** a suffix onto a symbol in `current` or unsuffixed in a later snapshot (`pit_yahoo_symbol` → `None`).
- **Do strip** when safe, and join membership to prices with `yahoo_membership_as_of` so those names actually enter the panel.
- **Drop `html5lib`** from the PIT Wikipedia flavor list. Primary path is github. Note no longer pretends Wikipedia ran.
- Do not add `html5lib` to requirements. Do not change k, cap, or gate.

### Coverage (Yahoo close that day / raw PIT members)

```
date         raw  mapped  blocked  with_px   pct
2005-06-30   501     484       16      265   53%
2008-09-15   502     490       10      308   61%
2011-06-30   501     491        9      333   66%
2014-06-30   503     494        7      361   72%
2017-06-30   516     504        3      409   79%
2020-06-30   505     505        0      443   88%
2023-06-30   503     503        0      476   95%
```

Later years improved vs 324 because membership now tracks the Updated file (324 was frozen at 2019-01-11, so 2023 coverage was 84% of the *wrong* 504). 2005 is still half the index — that is Yahoo, not the mapping. **This sample has real membership and is NOT survivorship-free on prices.** Do not quote 9.68% ann or Sharpe 0.66 without this table. The k=0 conclusion can be quoted: the bias favours k=0 and it still loses.

### Cycle changes vs 324 matching (1088 weekly dates, same panels)

- vs TASK-324 raw names (suffix never matched a column): **690 / 1088 cycles differ** (+2177 extra eligible-name slots — safe suffixes now map).
- vs naive suffix-strip (the bug): **639 / 1088 cycles differ** (1689 name-slots blocked as ticker reuse).
- 38 suffixes not stripped. 30 new post-2019 names downloaded (9 delisted at Yahoo, expected).

### Re-measure (1088 cycles, 2004-01-02 .. 2026-09-04, 1209 tickers, cost 10 bp/side)

```
variant                     cycles  mean_bp  net_bp  ann%   Sharpe  maxDD
baseline k=1 + sector cap     1088     20.9    13.6   9.68    0.66  -35.3
vol_exp=0                     1088     20.6    13.6   8.84    0.53  -41.3
no sector control             1088     21.2    14.0   9.78    0.65  -34.9
no regime gate                1088     26.4    18.6  12.37    0.74  -47.4
```

Same ranking as 324, slightly higher levels (more names eligible; 2019–2026 membership no longer frozen):

1. **k=0 still does not beat k=1** (20.6 vs 20.9 bp, Sharpe 0.53 vs 0.66, maxDD −41.3 vs −35.3). Keep k=1. TASK-319 (b) stands.
2. **Sector cap is still cheap** (−0.3 bp vs off) and does not improve maxDD. Not alpha; leave the TASK-320 hard cap. Do not cite "cheap" without the coverage caveat.
3. **Regime gate still costs return** (−5.5 bp vs off) **and buys drawdown** (−35.3% vs −47.4%). Keep it as a risk control, not a return feature.

Reproduce: `python experiments/backtest_variant_sweep.py --oos`

---

