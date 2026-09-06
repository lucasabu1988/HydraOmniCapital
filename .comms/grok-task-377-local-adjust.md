# TASK-377 — Local total-return adjustment: prototype + evidence (done by Claude, 2026-09-06)

No production change, no flag. `data/adjust.py` + `test_adjust.py` (7 hand cases) +
`experiments/adjust_parity.py`.

## Method

CRSP / Yahoo convention: every bar strictly before an ex-date is multiplied by
`1 - dps / raw_close[last bar before the ex-date]`; factors compound backwards from the last bar
(which always equals the raw close). Splits use `1 / ratio` the same way — but Yahoo's raw `Close`
and its `dividends` series are already split-adjusted, so for Yahoo data no split factor is applied.
Bad events (ex-date before the first bar, dps >= previous close) are skipped and reported.

## Evidence (50 random S&P names + the 10 ETFs, 2y window, store `Close` vs `Adj Close`)

```
within 1e-6: 59   within 1e-4: 0   worse: 1   of 60
median of max_rel: 1.79e-07   max of max_rel (excluding the one failure): 2.99e-07
13 names without a dividend in the window: max_rel 0 (raw == adj, as it must)
```

Worst names (max relative diff vs Yahoo's Adj Close): KVUE 3.0e-7, EXE 3.0e-7, TLT 2.9e-7 (24 monthly
dividends), IEF 2.9e-7, APO, MAS, ADP, GD, CARR all < 3e-7 — Yahoo rounds its factors to ~6 decimals,
the local computation does not; 1e-7 is that rounding.

**The one failure is the finding.** MKC came back with **0 dividend rows** because `fetch_dividends`
hit Yahoo's rate limit for that ticker ("Too Many Requests") and the cache had nothing; the local
adjustment then equals the raw close and sits 5.6 % off Yahoo's Adj Close on 456 bars. Nothing in the
numbers flags it except the comparison itself.

## Recommendation

The method is exact to Yahoo's own rounding, so the store **can** keep `close_raw` plus a dividend
table and derive the adjusted series locally, dropping the daily readjust downloads — **with one guard
that is not optional**: an incomplete dividend table produces a silently wrong series. Before any
switch: (1) the dividend cache must record "fetched, none" separately from "fetch failed" (today both
are an empty list); (2) a weekly sample check (`store_cli.py --verify N` already exists) must compare
the derived series against Yahoo's Adj Close and alert on any name > 1e-5; (3) TASK-363's split table
is needed only for a provider whose raw close is not split-adjusted (not Yahoo). Until (1) and (2)
exist, keep the readjust path (TASK-371/376/382) as is — it costs ~40 s of requests a day and is
self-correcting. Filed as a follow-up, not scheduled.
