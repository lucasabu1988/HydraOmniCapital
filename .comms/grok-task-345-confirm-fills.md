# TASK-345 — confirmed fills

`confirm_fills.py` replaces presumed ledger fills with what Lucas actually traded.

- `--from-csv fills.csv` (exec_date, sleeve, tranche, ticker, side, units, price, fee)
  or `--interactive`
- Match on exec_date/sleeve/tranche/ticker/side; reverse presumed, apply confirmed
  via `core.tranche_book.Tranche` (no rebalancing).
- Unmatched row -> `confirmed_unplanned` + warning.
- Same numbers twice -> no-op.
- `--report` prints the table and does not write. Write path uses `save_state` backup.

Do not edit `core/portfolio_engine.py`.
