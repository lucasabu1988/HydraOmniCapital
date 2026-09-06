# TASK-372 — Close the hygiene gaps

Frozen live path still ignored by ruff (`core/**`, `portfolio_v9.py`, `daily.py`,
`preflight.py`).

## (a) Lint surface

CI now checks `test_*.py`, `send_hydra_summary.py`, `console_dashboard.py`,
`snapshot_universe.py`, `verify_state.py`, `runlog_cli.py` as well as the 368
set.

Safe `ruff check --fix` (30 F401/F541). Hand fixes: `zip(..., strict=True)` in
the golden and filters tests; `test_state_check` lambda → def; semicolon in
`send_hydra_summary`; unused vars in journal/filters.

Per-file ignores (one-line reasons in `ruff.toml`):
- `test_portfolio_engine.py` E702 — compact engine cases
- `test_output_integrity.py` E702 — same
- `test_spec_compliance.py` E712, B904 — `== True` is the SPEC contract style

`ruff check` on the new surface: **All checks passed.**

## (b) No `custom` universe snapshot

`snapshot_universe.py` no longer writes `INITIAL_UNIVERSE` as a universe.
Deleted `data_cache/pit/universe_custom_20260906.json`. Test
`test_seed_does_not_write_custom_fallback`.

## (c) Runner

`run_all_tests.py` prints `ruff (report-only): ...` after the suite. Never fails
the suite on ruff.

## (d) RUNBOOK

"Peru" → "the machine's zone (SA Pacific Standard Time, UTC-5, no DST)".
Same 16:00 ET = 15:00 local arithmetic.
