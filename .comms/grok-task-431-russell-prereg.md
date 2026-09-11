# TASK-431 — frozen v9 on Russell PIT

`.comms/prereg-russell-pit-2026-09-08.md` as written. No threshold moved.
sha256 (LF-normalized) `3d5598d944ce887caf1abb6121daff3c46b3fdee1c7513027b99d6274fae890e`.
Hashes: signals `f9806b77bd61`, regime `0f475602519b`, filters `95c78d2591c6`,
meta_layer `5e81ff429455`. V9 and the listed `config.py` values match.

Engine: `engine_backtest.drive_engine` on `_sweep_cache_russell/` with
`membership.pkl` overlay (Wikipedia S&P payload never installed). SPY injected
from the OOS cache. `close` for signal, `close_raw` for eligibility (same as OOS).
START = first membership bar 2010-06-28. 814 plans, 2010-06-28 → 2026-08-26.

## Calendar hygiene (not a threshold)

EODHD keeps US holidays as rows where 1–7 of 6048 names print. Yahoo's OOS panel
drops those days. A holiday NaN poisons `rolling(20)` volume for 20 bars and
`rolling(63)` vol for 63 bars, so `rank_day` returned None on almost every step
(24 marks in 16 years, T-bill 66 % — void). **153 holiday rows dropped**
(print share < 5 %). Trading cache 5456 × 6048. That is the same calendar
convention as the S&P `--oos` row, not a scoring change.

## Caveats (own table)

| item | value | note |
|---|---|---|
| cell_coverage | 0.8691 | priced member-cells / full membership record |
| ghost_names | 547 | still members >1y after last print |
| ghost_member_cells | 196856 | empty member-cells after last print + 1y |
| spliced_dropped | BBBY,SBNY | ticker-reuse columns excluded |
| honest_window | 2010-2026 | free record starts June 2010 |
| names | 6048 | requested 6547 |
| holiday_rows_dropped | 153 | EODHD US-holiday rows |

Sector map is `fixed` snapshot 20260905: 2048 mapped, **4000 fallback**. The
sector cap does not bind the same way as S&P. Labelled; not a PIT sector run.

## Universe comparison

| config | cycles | ann_net | ratio_net_vol | sharpe_excess | maxDD |
|---|---|---|---|---|---|
| S&P 500 PIT engine `--oos` (published) | 1083 | **7.03** | **0.74** | 0.56 | **−17.7** |
| engine Russell PIT | 813 | **5.66** | **0.65** | 0.49 | **−16.0** |
| S&P 500 on overlap (same dates) | 813 | 8.09 | 0.83 | 0.68 | −17.8 |

Pair: S&P wealth ffilled onto Russell marks (Yahoo vs EODHD 5-bar grids do not
share dates). 813 overlapping returns, 2010-06-28 → 2026-08-26.

| d_sharpe (R−S&P) | SE | rho | maxDD R | maxDD S&P | worse_pp |
|---|---|---|---|---|---|
| **−0.19** | 0.26 | 0.48 | −16.0 | −17.8 | −1.8 (Russell better) |

Costs: 12.7 % turnover/step, blended 7.5 bp, ann cost 0.59 % of mean book =
**10 % of ann_net** (fail if > 50 %). Plumbing: not_filled 65, hold_no_price
1829, write-offs **810** ($7.62 on start book 1.0) — delistings/ghosts, not
S&P's 3 write-offs.

## Verdict: INCONCLUSIVE

Rule written before looking:

- Survive if d_sharpe ≥ −0.10 and maxDD not worse by > 5 pp
- Fail if d_sharpe ≤ −0.25 **or** costs erase > half of ann_net
- **−0.25 < −0.19 < −0.10 → inconcluso. Se declara así y no se toca nada.**

maxDD and costs would have passed Survive. The Sharpe delta is the middle
zone. **No H-0xx. No retune. Block B does not start.**
