# TASK-367 — Attribution and analytics (done by Claude, 2026-09-06)

Branch `post-freeze-wiring`, commit `89a9d6e`. Read-only over the state; nothing writes to
`portfolio_v9.json`.

## What landed

- `core/costbasis.py` — the average-cost lot rule the dashboard carried inline, now one implementation
  (`lots_from_ledger(state, statuses=...)`). The dashboard keeps counting `"filled"` fills only, as before;
  the attribution counts confirmed fills too.
- `analytics/attribution.py` — pure. Cumulative since the anchor, per sleeve and for the book:

  `value_now - initial_cash = trading + fees + interest + dividends + transfers + residual`

  trading = market value + sell proceeds + write-off proceeds - buy dollars (stock sleeve = **selection**,
  ETF sleeve = **etf**); fees = -(fill costs); interest / dividends / transfers from the state records;
  **residual** = what the identity does not explain (zero on a replay-clean state; non-zero means confirmed
  fills with other units/prices, or a state edit). `transfers_net_zero` asserted at book level,
  `identity_gap` kept as a self-check. `positions()` per sleeve/tranche/ticker (units, avg cost, mark,
  market value, unrealised, realised, fees; closed lots keep their realised P/L). `diff(prev, cur)` gives
  the weekly delta of two cumulative blocks; `render_markdown()` the table.
- `analytics_cli.py` — writes `<state-dir>/analytics/attribution_<date>.csv` (positions) and
  `ATTRIBUTION.md` with a weekly column from the previous saved block; `--portfolio` aware.
- Dashboard: a row of "Atribución" cards (selection, ETF, interest, dividends, fees, transfers, residual,
  total change) from `snapshot["attribution"]`; `core/journal.py` record gets `attribution` (slim block,
  no per-position list) from the same builder.

## Tests (8, `test_attribution.py`)

Synthetic two-sleeve book with three fills, one confirmed sell, one write-off, one dividend, two interest
records and a transfer pair: components sum to the change within 1e-9, residual 0, an unexplained cash
edit shows up as residual, average-cost rule, marks override `last_px`, weekly diff + markdown, dashboard
uses the shared lots and exposes the block, journal carries the block, CLI writes both files and leaves
the state untouched.

## Reading on Tuesday

After the first settle the book will show: selection ≈ 0 (fills at the close, marks at the same close),
interest ≈ 13 USD, fees ≈ -15 USD (10 bp on ~15k deployed), transfers 0, residual 0. Anything else in
`residual` on the first week means `confirm_fills` replaced presumed fills with different units.
