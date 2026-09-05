# Paper trading record - COMPASS v8.4 live engine (2026-02-19 .. 2026-04-02)

`state/` is the runtime state the legacy live engine (`omnicapital_live.py`, deleted 2026-06-05)
and its Flask dashboard (`compass_dashboard.py`, deleted 2026-09-06) wrote while paper trading.

- `state/archive_run1/`: first run, 2026-02-19 .. 2026-03-05 (state snapshots, cycle log, ML logs).
- `state/compass_state_latest.json`: last state of the second run, last trading date 2026-04-02.
- `state/cycle_log.json`, `state/ml_learning/`, `state/intelligence/`: the rest of that run.

The old CLAUDE.md called `state/compass_state_latest.json` "the source of truth for live
positions". There have been no live positions since 2026-04-02. This folder is a historical
record, not state. Nothing reads it.
