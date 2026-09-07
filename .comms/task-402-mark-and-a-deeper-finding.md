# TASK-402 — the sheet's valuation, and what measuring it turned up

Claude, 2026-09-07. Branch `fix/astra-03-observed-fill-prices`.

## What the task was

The re-review of ASTRA-03 returned objection 3 with two blockers, both correct:

1. the masked mark was **not falsifiable** — reverting it turned no test red, because the fixture
   put NaN on the last bar, and there the old and new code agree. The case that separates them is a
   forward FILL: a cell holding a number the ticker never printed;
2. where it did bite it **made the total worse**: refusing the filled price was right, but falling
   through to `value_with_stale`'s `last_px` — the price the tranche BOUGHT at — valued a name that
   printed yesterday at its entry instead of at yesterday's close.

## What was done

`last_observed(frame)` walks the OBSERVED frame (`frame.attrs["observed"]`, which `data.fetch`
records precisely because its own ffill makes a filled cell indistinguishable from a print) and
returns each column's most recent real print plus the date it printed on. The sheet is valued with
that, says which names are priced at an earlier bar, and keeps `last_px` as the fallback only for a
name with no print anywhere in the window (SPEC 9.4). The header no longer claims that every price
printed on the valuation bar.

Falsifiability, measured rather than asserted:

| mark | sleeve value in isolation | end to end |
|---|---|---|
| `_row(prices, last_bar)` — the first pass | **3600.00** | 4000.62 |
| `last_observed(prices)` — this task | **4000.00** | 4000.62 |

Entry 60, last real print 100, filled cell 100. In isolation the reviewer's blocker reproduces
exactly: 400 USD of difference on a ten-unit position. Reverting the mark turns
`test_task_402_mark.py` red (2 of 9 against `iloc[-1]`, on the dates and the wording; the value
assertion against the first pass I verified by direct call), so the fix is falsifiable in both
directions.

## The deeper finding: the STATE absorbs prices nobody printed

The two end-to-end numbers above are identical, and chasing that down is the useful part of this
task.

`core/tranche_book.age_stale(px)` refreshes `tr.last_px[tk]` for every FINITE price it is handed,
and resets `tr.stale[tk]`. It is handed the frame's prices, forward fills included. Measured on the
fixture — AAA printed 100 on the 9th and the 10th is a fill of that same 100:

```
last_px in the STATE after the run: {'AAA': 100.0}
stale:                              {}
```

So by the time the sheet is built, the book is already carrying the filled price and the staleness
counter has been reset. The sheet's total was therefore never going to move: the honesty problem
lives one step earlier, in the state.

Two consequences, and the second is the one that costs money:

- **`last_px` is not "the last price we saw", it is "the last number we were handed".** A forward
  fill writes into the book's own record of value, and that record is what a write-off is priced
  at.
- **the write-off clock resets on a fill.** `data.fetch` fills up to 3 bars, so a name that stops
  printing gets up to three resets per gap before `stale` starts counting again, and
  `max_stale_bars = 10` is measured in whatever mixture of prints and fills happened to arrive. A
  delisted name can be carried well past ten sessions without the counter noticing.

**Not fixed here, on purpose.** `age_stale` is the accounting of staleness and write-offs, which is
exactly the subject of **H-005** (ASTRA-08, registered PROPOSED on `docs/astra-prereg-01-08-10`,
awaiting Lucas with a measurement). Changing what counts as "a price arrived" changes when a
position is written off and at what value, on the live money path. It belongs to that hypothesis,
with its own measurement, not to a sheet-rendering task.

What H-005's measurement should now also answer, which it did not know to ask:

- how many held names have had `last_px` set from a filled cell rather than a print, historically;
- how many sessions a name is actually carried before write-off, counting prints only, versus the
  ten `max_stale_bars` claims;
- whether `age_stale` should take the observation mask (so a fill neither refreshes `last_px` nor
  resets `stale`), and what that does to the OOS write-off count — TASK-350 measured 492
  `hold_no_price` events on AET/ESRX/TWX before the counter was persisted, so the panel exists.

## Files

`hydra_screener_local/portfolio_v9.py` (`last_observed`, `_carried_forward`, the mark, the sheet
header), `hydra_screener_local/test_task_402_mark.py` (9 tests). Nothing under `core/` was touched.
