# TASK-337 — Independent review of the executable simulator (`0d4f2e5`)

Review, not a re-implementation. Counterexamples in
`experiments/test_review_337.py` (12 tests: 11 hold, 1 fail). Reviewed modules
not edited. `run_exec` / `run_sleeve` call `tranche_book.run_book`; the attacks
are on that book plus `mix()`. Full-panel `run_exec` causality was not re-run
here (4 min, pytest `--timeout=30`); the engine they wrap is what was shocked.

## D and E, old paths on record

- **D.** Two 50% tranches, one long 100→200→100, one cash: `run_book` compounds
  to **1.00** (flat). The pre-audit mean-of-tranche-returns compounds to
  **+12.5%**. Reproduced. Author's `test_tranche_book.py` already had this;
  it stays on the record in the review file, asserted against `run_book` (the
  `nominal=True` lab path is the same arithmetic).
- **E.** `combine` from git `203c395` reconstructed in the test: a shock in
  step *i* moves the risk-parity weight **at** step *i*. New `mix()` does not
  (`shift(1)`); weights and nets up to *i* ignore returns after *i*. Holds.

## New attacks (author did not write these)

Holds:

- Three staggered tranches, each buying a different flat name: value conserved,
  distinct=3 after the third renewal.
- One name held by two tranches: when A doubles, both legs move, book ×2.
- Target weights sum to 1 at 10 bp: cash ≥ 0 (cost-before-sizing works).
  Leftover cash is ~1e-6 of book, the residual of the estimate, not a short.
- NaN at the renewal bar, valid at the step end: carried at last_px, then
  marked +10% when the print returns. No write-off.
- Exposure 0.4 + cash at 25.2% annual: idle cash accrues; expo is read *after*
  accrual so it is 0.4 / (1 + 0.6 × rate_step), not a flat 0.4.
- Renewal that keeps every name at unchanged prices: turnover 0 after the
  initial deploy.
- Cannot exit a name whose renewal print is missing: units stay, no invented
  fill at last_px. Documented in `rebalance`.
- `run_book` rows with measurement end ≤ bar 4 ignore a shock at bar 5.
- `mix` nets and weights up to *i* ignore returns after *i*.

**Breaks (1):**

- **`test_exposure_includes_names_carried_at_last_price`** — while a held name
  is stale (< 10 bars) P&L uses `value_with_stale` (last_px), but `exposure()`
  calls `value()` which **drops** NaN names. A fully-invested book reports
  `expo=0` during the carry. Audit §5's "exposición" column is then wrong on
  any step that is carrying a stale name. T20's three write-off steps (338)
  are the live case: ESRX/SCG were stale for 10 bars and expo under-counted
  them. Finding, not a P&L bug (net is still last_px).

## Assumptions in the code the docs do not all state

Stated in `tranche_book.py` header or mix docstring: stale carry 10 bars,
write-off at last price, cost estimate before sizing, lag=1 close-to-close,
`mix` `shift(1)`, realloc charged at 10 bp on the whole shifted amount.

Not stated (or easy to miss):

1. **`exposure()` ignores stale names** (the finding above). `n` / `distinct`
   still count units, so n>0 with expo=0 is possible.
2. **Write-off is not a `Trade`.** 0 cost to convert last_px into cash. Marking
   to zero instead costs 0.46 pp on T20 (TASK-338).
3. **`age_stale` runs at the step *end*, not at renewal.** A NaN renewal cannot
   liquidate; you wait for a later print or the 10-bar write-off.
4. **`target_w.sum() > 1` is renormalized; `sum < 1` leaves cash.** Partial
   exposure is how vol-targeting and the ETF "off" names get into the book.
5. **`run_exec` refuses `vol_estimator='cycles'`** with vol-target (assert).
   T20 uses `basket63`, so it is fine.
6. **`run_sleeve` ignores the `held` argument** — no buffer on the ETF sleeve.
   By construction of `target_fn`, not of the book.
7. **`mix` first step pays 0 realloc** (no prior weights to leave). Entering
   the mix is free; only subsequent resets cost.
8. **`mix` clip then renormalize.** Two sleeves clipped to (0.15, 0.6) are
   renormalized back to 1; the clip is not a cash sleeve.
9. **Nominal path `fillna(0.0)` on missing prices** (`run_tranched` /
   `run_sleeve_nominal`): a delist is a 0% return, not a write-off. Comparison
   table only; executable path does not do this.
10. **`mix` uses the stock-sleeve 10 bp** even when mixing T20 with an ETF
    sleeve that internally costs 5 bp. Stated as conservative in the docstring;
    still an assumption on the portfolio numbers in audit §5.2.

## Files

- `experiments/test_review_337.py`
- `.comms/grok-task-337-review-simulator.md`

Not edited: `tranche_book.py`, `redesign_lab.py`, `sleeve_lab.py`.
