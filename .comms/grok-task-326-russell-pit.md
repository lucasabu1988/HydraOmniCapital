# TASK-326 — Historical Russell membership: is a PIT panel of production feasible?

**From:** Grok
**Date:** 2026-09-06
**Verdict:** **No honest free source.** Deliverable is this note. `data/universe.py` not edited.
**Cache pattern:** `experiments/_sweep_cache_russell/` added to `.gitignore`; no panel downloaded.

Production `UNIVERSE="all"` is S&P 500 ∪ Nasdaq-100 ∪ Dow ∪ Russell 1000 ∪ Russell 2000 (~3000 names, two-thirds mid/small). Every number we have (deep-dive, TASK-320/324/325, the redesign lab) is S&P 500. A redesign validated only on large caps is validated on the wrong universe. This task asked whether a point-in-time **Russell** panel can be built the way TASK-324/325 built S&P.

## What "honest" meant for S&P (the bar)

fja05680: **daily** snapshots 1996 → 2026, ~500 names, `-YYYYMM` entity IDs so ticker reuse is visible, Wikipedia as documented-incomplete fallback. Even then Yahoo prices cover 53% of 2005 members. TASK-325 exists because getting membership right and prices right are different jobs.

Russell needs at least: dated constituent lists across 2004–2026, ticker normalisation, a reuse rule, and a coverage print. Annual PDFs with no entity IDs do not clear that bar.

## Sources tried

### 1. Official FTSE Russell / Norgate / CRSP

Paid. Norgate was on the old roadmap. CRSP/Compustat are institutional. Not used.

### 2. `kact998/Russell3000Components` (best free dated lists)

- Annual June reconstitution CSVs, **2010–2023 except 2013**. Columns: `Company`, `Ticker`. ~2995–3125 names.
- **Missing 2004–2009** — the window that contains 2008, which is why the S&P PIT exists.
- **Missing 2013, 2024–2026.**
- PDF extraction, no CUSIP/entity id, no `-YYYYMM`.
- Ticker reuse is real. Same ticker, different company, 2010 vs 2023 examples: `AMR` (AMR Corp vs Alpha Metallurgical), `AGL` (AGL Resources vs Agilon Health), `ADPT` (ADPT Corporation vs Adaptive Biotechnologies). 1575 tickers in 2010 are gone by 2023; 1112 of the 1420 survivors changed the printed name (renames + reuse mixed).
- Russell reconstitutes in June, so annual snapshots match the official calendar — but intra-year IPOs, delistings and promotions are missing, and yfinance will attach live-company prices to reused tickers exactly as TASK-325 forbade.

Usable as a **footnote**, not as a production-universe panel.

### 3. iShares IWM / IWB / IWV holdings history

- IWM ≈ Russell 2000, IWB ≈ Russell 1000, IWV ≈ Russell 3000. Product pages expose a holdings CSV; scrapers (talsan/ishares, various gists) claim monthly files back to ~2006.
- Probed `…/1467271812596.ajax?fileType=csv&asOfDate=20151231` for IWM: HTTP 200, **HTML login/app shell**, not a holdings table. Historical `asOfDate` is not an open CSV dump.
- Even when holdings download: ETF ≠ index (sampling, cash, futures, 1–2 day lag, ~1900 of 2000 names). No delist suffixes. This is "what IWM held", not "what Russell reconstituted".

### 4. Wikipedia / Wayback / yfiua/index-constituents

- Wikipedia has no S&P-style "Selected changes" table for Russell 2000/1000. Walking a changelog backwards is not an option.
- yfiua/index-constituents: Nasdaq/S&P/Dow from 2023-07, **no Russell**, and history only from when they started archiving.

### 5. One-shot current lists (Barchart, Sure Dividend, major/index-etfs)

Today's IWM/Russell 2000 tickers. Survivorship of the current list — the thing TASK-324 was written to stop.

### 6. MIT Dataverse / academic Russell holdings

Month-end official holdings exist for subscribers (H_yyyymmdd files back to 1986). Not a free anonymous download.

## Decision

**Do not ship `russell_membership_as_of()`.** A function that returns kact998's June lists (or IWM's current book) would be used as if it were fja05680, and every small-cap backtest would be a 2010–2023 large-and-alive-ticker study with 2008 missing and reused tickers priced as the live company.

What this caps:

- The redesign's 10% net target is **S&P 500 PIT**, not production. Production is Russell-heavy.
- Audit R1 (SPY vs IWM regime, 12.5% of days) cannot be scored on a PIT small-cap book. The IWM secondary regime in history is observability, not a backtest.
- TASK-327's size-aware costs on the S&P PIT understate small-cap trading costs; they do not become a Russell result.

To get an honest panel later: buy Norgate (or FTSP Russell historical) or intern iShares month-end holdings with CUSIP mapping and a TASK-325-style reuse rule, and still print Yahoo coverage. Until then, treat any Russell backtest as a current-list screen.

`data/universe.py` untouched. No `_sweep_cache_russell/` download.
