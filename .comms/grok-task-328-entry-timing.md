# TASK-328 — D+1 open vs D+1 close vs D+2 open

**From:** Grok
**Date:** 2026-09-06
**Do not tune.** Measurement only. Harness and scoring untouched.

Signal is known at the close of D. Production / tracking v2 / the sweep enter at
the **close of D+1** (lag=1) and exit five bars later. Opens did not exist in
the repo. This downloaded `experiments/_sweep_cache_oos/open.pkl` (same 1209
tickers, 2004-01-02 .. 2026-09-04, yfinance `auto_adjust=True`; delisted names
fail as in the close panel) and re-priced the production recommended sets.

Cost: 10 bp/side on the same turnover the harness uses. D+1 close on the full
window reproduces the TASK-325 baseline (20.9 bp gross, 13.6 net, 9.68 / 5.72
ann, Sharpe 0.66) — so the recommended sets match.

## Results

```
era        entry                  cycles  mean_bp  net_bp  ann%   ann_net  Sharpe
2004-2012  D+1 close (production)    401     16.7     9.6   7.13     3.32    0.48
2004-2012  D+1 open                  401     10.5     3.3   3.69     0.00    0.29
2004-2012  D+2 open                  401     24.1    16.9  10.94     6.99    0.65
2013-2019  D+1 close                 353     20.8    13.4  10.21     6.21    0.87
2013-2019  D+1 open                  353     23.6    16.2  11.61     7.56    0.90
2013-2019  D+2 open                  353     25.6    18.2  12.91     8.81    1.06
2020-2026  D+1 close                 334     26.0    18.6  12.23     8.15    0.75
2020-2026  D+1 open                  334     31.8    24.4  15.45    11.26    0.89
2020-2026  D+2 open                  334     22.3    15.0  10.19     6.18    0.64
full       D+1 close                1088     20.9    13.6   9.68     5.72    0.66
full       D+1 open                 1088     21.3    14.0   9.76     5.80    0.64
full       D+2 open                 1088     24.0    16.7  11.34     7.33    0.74
```

## Reading (not a parameter change)

1. **D+1 open is not a free lunch.** Full-sample +0.4 bp vs production, Sharpe
   slightly worse. In 2004–2012 it *loses* 6.2 bp (overnight gap after a strong
   close was the wrong side). In 2020–2026 it *wins* 5.8 bp. Picking it from the
   full table would be choosing the 2020–2026 subsample.
2. **D+2 open looks better on the full window** (+3.1 bp, Sharpe 0.66 → 0.74,
   net ann 5.72 → 7.33) because 2004–2012 and 2013–2019 like waiting a day.
   2020–2026 does not (22.3 vs 26.0 bp). Same warning: era-dependent.
3. The audit A2 finding (lag-1 close beat lag-0 close) is about not buying the
   signal close. It does **not** imply the next open is the better fill.

Reproduce: `python experiments/entry_timing.py` (uses `open.pkl` if present).
