# TASK-354 — uncertainty around the audit numbers

Stationary bootstrap (Politis & Romano), mean block **13** steps, **5000**
draws, seed 0. Series: executable OOS step nets from `audit_steps.pkl`
(PROD_cy, T20_cy, ETF, P_5050), aligned on 1084 weeks 2005-02-11 → 2026-08-24.
`task332_series.json` has no mix path.

This is analysis only. No parameter change. TEST-read-once: the same published
series, not a new variant.

## Point vs 90% interval

ann_net in %, Sharpe, maxDD in %. Interval = 5th–95th percentile of the
bootstrap distribution. maxDD 5/50/95 is the distribution of path maxDD
(5th = worse).

| series | ann_net | 90% ann | Sharpe | 90% Sharpe | maxDD | maxDD 5/50/95 |
|---|---|---|---|---|---|---|
| PROD (T-bill) | 5.48 | **[−0.01, 11.05]** | 0.42 | [0.08, 0.75] | −37.8 | −58.3 / −37.3 / −24.5 |
| T20 (T-bill) | 7.55 | **[3.16, 11.93]** | 0.59 | [0.29, 0.92] | −29.2 | −46.3 / −29.8 / −19.9 |
| ETF | 6.05 | **[4.09, 8.00]** | 0.91 | [0.62, 1.22] | −11.9 | −17.1 / −11.9 / −7.5 |
| 50/50 mix | 6.91 | **[4.01, 9.73]** | 0.74 | [0.44, 1.06] | −19.5 | −29.1 / −19.5 / −12.2 |

Paired stationary paths (same index sequence):

- **P(T20 ann > PROD ann) = 0.776**
- **P(mix Sharpe > T20 Sharpe) = 0.999**

The 10% net target is above the mix 90% interval (p95 = 9.73). T20's return
edge over PROD is likely but not a lock (overlap of the two ann intervals is
large; 0.78 is the same qualitative read as TASK-332's CI that included 0 on
the nominal series). The mix's Sharpe over T20 is.

## Appendix paragraph (for the audit note)

Stationary block bootstrap (mean block 13 weeks, 5000 draws, seed 0) on the
executable OOS step returns (PROD/T20 with T-bill, ETF, 50/50 mix; 1084
overlapping weeks 2005-02-11 to 2026-08-24). 90% intervals for ann_net: PROD
[−0.0, 11.1], T20 [3.2, 11.9], ETF [4.1, 8.0], mix [4.0, 9.7]. The 10% net
target sits above the mix p95. P(T20 > PROD) = 0.78; P(mix Sharpe > T20
Sharpe) = 0.999. MaxDD 5/50/95 for the mix: −29.1 / −19.5 / −12.2. Same
published series; not a new variant.
