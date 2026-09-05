# TASK-334 — What an honest Russell history would cost

**From:** Grok
**Date:** 2026-09-06
**No purchases, no sign-ups.** Prices as published in August/September 2026 vendor pages.

TASK-326 closed the free road. Option C ("don't change scoring until we can measure production") is only a real option if a paid PIT book is buyable. This page prices that book.

## Verdict in one line

**Buy Norgate Data US Stocks Platinum, $630/year USD, personal use.** It is the only listed-price product that combines (a) historical Russell 1000/2000/3000 membership, (b) delisted prices, (c) entity suffixes like `AABA-201910`, (d) a Python API. Everything else is either S&P-only, quote-to-buy, or membership without delisted prices (or the reverse).

## Comparison

| Source | PIT Russell membership | Delisted prices | Entity ids | Price (personal) | Licence / catch |
|---|---|---|---|---|---|
| **Norgate Platinum** | Yes — `$RUI` / `$RUT` / `$RAA` (R1000/R2000/R3000) via `index_constituent_timeseries`; watchlist `Russell 3000 Current & Past` | Yes, back to 1990 | Yes (`AABA-201910` style, same family as fja05680) | **$630 / 12 months** (or $346.50 / 6 months). Diamond $787.50/yr goes to 1950 | Personal/research. Windows updater + `pip install norgatedata`. Silver/Gold ($270/$360) do **not** include delisteds or historical constituents — that is the trap |
| **FTSE Russell / LSEG** | Yes — official daily/quarterly constituent files for Russell US | Not a price database; constituents + weights | CUSIP / SEDOL | **No public USD list.** "Subscribe to index data" via LSEG sales; historical constituents "for a selection of indices, quarterly in arrears" | Institutional. The right *membership* file, the wrong *buying* process for a one-person screener |
| **Sharadar SEP + tickers** | **No.** Historical **S&P 500** constituents only (`sp500` table since 1957) | Yes, ~21k active+delisted US names from 1998, permaticker | Permaticker + ticker-change actions | Bundle (fundamentals+SEP) sold on sharadar.com; list price behind account. Historically a few hundred USD/year | Personal use allowed. Does **not** solve Russell |
| **EODHD** | **S&P / Dow only** (Index Components API, 2–12 years of add/remove). Russell is not in the published index list | Yes: delisted US EOD, pre-2018 EOD-only. Symbol-change history | Ticker + rename table, not CUSIP-level entity ids | EOD All World **$19.99/mo** ($199/yr); index-constituents add-on advertised at $29.99/mo for S&P/DJ | Cheap delisted *prices*. No Russell membership |
| **Polygon.io** | Not sold as index-constituent history | Stocks plans include many delisted tickers | Ticker, not index entity ids | Stocks Starter on the order of **$199/mo** (list price moves; no Russell PIT SKU) | Fine for live/recent prices, not for 2004–2026 Russell membership |
| **Algoseek US Equities Index Components** | Yes — daily R1000/R2000 from **July 2009** (S&P from 2007) | Separate from their price archive | Daily membership + change table | Research package **$2,500/mo** | Has membership, misses 2004–2008, priced for a desk |
| **FirstRate “Russell 3000 stocks”** | **No** — current-list survivors + “200 major delisted” | Partial (200 names) | No | $399.95 one-off | Survivorship with a handful of dead names. Not PIT |

## What we would actually do with Norgate

1. Subscribe Platinum 12 months ($630).
2. `watchlist_symbols('Russell 3000 Current & Past')` → union of names ever in R3000.
3. `index_constituent_timeseries(symbol, 'Russell 3000')` (and R1000/R2000) → 0/1 membership, daily.
4. Pull delisted prices under Norgate's suffixed symbols — the TASK-325 rule (never strip onto a live ticker) applies unchanged.
5. Rebuild `experiments/_sweep_cache_russell/` and re-run T20 vs PROD. Until then, every 10% net figure is an S&P 500 figure.

Harvard Dataverse `10.7910/DVN/EAJMTI` holds official month-end Russell holdings files (H_yyyymmdd) back to 1978 **for subscribers of that archive**, not as an anonymous download. Treat as institutional, not a cart button.

## Recommendation for option C

If Lucas wants “don't change scoring until we can measure production”, the blocking purchase is **Norgate Platinum, $630**. FTSE official files are cleaner membership but not a price database and not a published retail SKU. Sharadar/EODHD/Polygon do not replace it.
