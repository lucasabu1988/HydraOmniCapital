# TASK-340 — v9 state, CLI, instruction sheet

`ALGO_VERSION` left at `"v8.4"`. Engine not edited.

## CLI (`portfolio_v9.py`)

Daily flow, matching the 03:10 interface:

1. Load `state/portfolio_v9.json` (create on first run; `--capital` defaults to **100000** USD).
   Anchor = last close. Lucas asked for Friday-close → Monday MOC: if the first run is not a
   Friday the CLI warns and still uses that last close. Renewals are every 5 **trading bars**,
   not every calendar Monday.
2. Fetch: stocks `period=V9["price_period"]`, ETFs `fetch_etf_closes(V9["etf_universe"])`,
   `fetch_tbill()` converted **/100** before `plan()`.
3. If `pending` and last close is after `planned`: `settle` at today's row.
4. If nothing pending: `generate_daily_candidates(..., momentum_window=V9["stock_momentum_window"])`
   then `plan(today=last close)`.
5. Backup previous state to `state/backup/<YYYYMMDD_HHMMSS>.json`, write the new JSON.
6. `state/instructions_<YYYYMMDD>.md` + `.json`. The sheet says **ejecutar al cierre del
   \<fecha t+1\>**. Empty orders → "No trades today".

Same-day rerun: pending is still waiting for t+1, plan is not called, no new orders.

## `daily.py`

`--v9` (and `--v9-capital`) runs the CLI after the screener. Without the flag, and
with `ALGO_VERSION == "v8.4"`, the ritual is unchanged. If the flag is later
`"v9"`, the CLI also runs without `--v9`.

## `.gitignore`

`hydra_screener_local/state/` (json, backups, instruction sheets).

## Tests (`test_portfolio_v9_cli.py`, no network)

7 passed: first run writes state+sheet; second run same date does not duplicate
and writes "No trades today" plus a backup; next bar settles then plans; missing
capital exits; `daily.py` without `--v9` does not call the CLI; `--v9` does;
gitignore line present.
