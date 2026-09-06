# TASK-347 — production engine end-to-end on the in-sample panel

`experiments/engine_backtest.py`. Does not edit `core/portfolio_engine.py`.
Panel: `_sweep_cache/` 2020-01-02 → 2026-09-04, 1678 bars, 503 names + 10 ETFs.
Each 5-bar step: lab `rank_day` reshaped as in the parity test → `plan()` →
`settle()` at t+1 → `summary_table` book value.

The "no-transfer" run strips `transfer_*` from `pending` before settle (the 1/8
cash reset never books). No engine flag, no parameter change.

## Results (278 overlapping cycles)

| config | ann_net | Sharpe | maxDD | turnover | expo | transfers | not_filled | write-offs |
|---|---|---|---|---|---|---|---|---|
| lab mix T20+ETF equal | 11.86 | 1.24 | −8.5 | n/a* | 100* | — | — | — |
| engine 1/8 reset (production) | **10.23** | 1.12 | −8.8 | 13.8% | 67 | 556 | 0 | 0 |
| engine, transfers stripped | 10.94 | 1.21 | −9.3 | 13.8% | 66 | 0 | 0 | 0 |

\* `mix()` writes `turnover=0` and `expo=1` by construction; sleeve costs already sit
in `net`. Distinct names on the engine: 69.4 average (both sleeves).

## Reading

- Same window, 278 cycles. The production 1/8-tranche reset costs **0.71 pp** net
  vs the same engine without those transfers (10.23 vs 10.94).
- Both engine paths sit **below** the lab 50/50 mix (11.86): about **1.6 pp**
  with the production reset. That gap is plumbing (vol-target cash, per-tranche
  books, lag-1 settle) plus the reset policy, not a new signal.
- 0 `not_filled`, 0 write-offs on this S&P in-sample book.

Audit §5 quoted 6.91% on the *OOS PIT 2004-2026* mix. These numbers are
in-sample 2020-2026 and are not that figure.
