# TASK-348 — show accrued interest

Read-only. `core/portfolio_engine.py` not edited.

`state["interest"]` records (date, since, sleeve, bars, rate, dollars). Old states
without the key render as 0.

- Dashboard: KPI **Interés** (cumulative) next to realised/unrealised; log rows with
  `side=interest` (sleeve, bars, rate, $).
- Instruction sheet + JSON: since previous run (per sleeve) and cumulative.
- Console: `[v9] interest since last run … cumulative …`

`summarize_interest(state)` in `dashboard_v9.py`; `portfolio_v9.py` imports it.
