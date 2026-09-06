# TASK-357 — execution date skips NYSE holidays

The first production sheet said "ejecutar al cierre del 2026-09-07" (Labor Day,
market closed). `next_session_date` used `BDay(1)` whenever the price index had
no later bar — always, on a Friday run.

Wired `utils.trading_calendar.next_nyse_session` / `last_nyse_session_on_or_before`
(already tested by Claude):

- `portfolio_v9.next_session_date` fallback
- `dashboard_v9.exec_date_for` fallback
- `preflight.last_weekday_session` (Labor Day no longer false-alarms as "stale")

`core/journal.py` does not derive t+1 dates (it records `date` from the v9 run);
left untouched.

Live sheet `state/instructions_20260904.md/.json` re-rendered: **2026-09-08**.
Pending orders carry no exec_date; unchanged.

Tests: Friday 2026-09-04 -> 2026-09-08 on CLI, `next_session_date`, dashboard
fallback, and preflight asof=Labor Day uses Friday 09-04.
