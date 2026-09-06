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

---

## Review (Claude, 2026-09-05) — APPROVED with corrections; two engine defects found

The task did its job: driving `plan()/settle()` through history exposed two production defects the
parity tests could not see. The gap Grok read as "plumbing" decomposes as follows (same 278 cycles,
same panel, scratch drivers on top of `engine_backtest.py`, engine untouched for the measurement):

| step | ann_net | Sharpe | maxDD | what changed |
|---|---|---|---|---|
| engine as delivered | 10.23 | 1.12 | -8.8 | Grok's row |
| + **fix A**: reset legs offset (pair split by value) | 10.87 | 1.20 | -9.2 | `plan()` sized each renewed tranche to 1/8 of the whole book; the two transfer legs differed by `total/4 - (own_s + own_e)` and that amount was created or destroyed on paper at every renewal. Leak == net transfer at every settle (corr 1.000, max diff 7e-10); net -4.5% of the starting book over the run. |
| + **fix B**: trailing T-bill hurdle instead of the last print | 10.87 | 1.20 | -9.2 | on/off set differed from the lab on 29/279 steps (GLD 9, IEF 8, EFA 4, TLT 3); return effect < 0.1 pp. Friday 2026-09-04 weights identical under both. |
| + ETF-sleeve cash accrual at ^IRX (lab-equivalent accounting) | 11.75 | 1.28 | -9.2 | not in the engine; scratch only |
| lab mix T20+ETF equal (reference) | 11.86 | 1.24 | -8.5 | residual 0.11 pp = 1/8-per-week reset vs the lab's full weekly reset + mark timing |
| + cash accrual on both sleeves (what a money-market account earns) | 12.03 | 1.31 | -9.1 | scratch only; decision for Lucas |

Checks that passed: costs 0.64 pp/yr engine vs 0.66 lab; one-way turnover 6.8% per step both; mean
exposure 81% stocks / 53% ETF both; 0 `not_filled`, 0 write-offs (in-sample panel has no delistings,
so this says nothing about the OOS book); no negative cash; 98 buys clipped by < 0.1%.

Grok's "transfers stripped" variant is not the reset-off counterfactual the task asked for: the
buys stay sized to 1/8 of the book while the tranche is funded with its own cash, so the last-ranked
names are clipped or cash idles (exposure 72/61 vs 81/53). Its 0.71 pp is not a measurement of the
reset policy. The lab-level counterfactual is: never reset 12.27 vs weekly full reset 11.86 in-sample
(the stock sleeve won 16.5 vs 7.1 here, so any reset gives up return in this window; that is not
the OOS picture and no policy change follows).

Fixes committed (Claude, engine owner): `core/portfolio_engine.py` (pair split, Series hurdle),
`portfolio_v9.py` (passes the ^IRX history), tests `test_reset_legs_offset_and_the_book_is_conserved_
when_tranches_have_drifted`, `test_etf_hurdle_uses_the_trailing_tbill_history_not_the_last_print`,
CLI test updated. Spec 9.3 documents both. `engine_backtest.py` re-run on the fixed engine: 10.87 /
1.20 / -9.2, 550 transfers, 0 not_filled. Production sheet of 2026-09-04 unchanged (all tranches
equal, no transfer legs, ETF weights identical).
