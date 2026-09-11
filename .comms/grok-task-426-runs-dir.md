# TASK-426 — the sidecar reader receives its destination

`portfolio_v9.run` was calling `load_last_ok_print_quality()` / `save_last_ok_print_quality()`
with no `runs_dir`, so both resolved `utils.runlog.DEFAULT_RUNS_DIR` deep in the read path.
A file the runner executes as a script never loads `conftest.py`, so that path was the
operator's gitignored `runs/`. TASK-422 fenced the measurement; this is the ASTRA-12-shaped
fix: resolve once in `run()`, pass it to both calls.

## What landed

- `run(..., runs_dir=None)` resolves `Path(runs_dir) if runs_dir is not None else DEFAULT_RUNS_DIR`
  once and hands that Path to `_print_quality_diagnostic` and `_save_print_quality`.
- Default None is production. Additive: a live call with no `runs_dir` still reads/writes
  the same `hydra_screener_local/runs/` it did yesterday.
- Tests in `test_provider_refresh.py` point the real loader at `tmp_path` with no module
  monkeypatch. The conftest fence stays (defence in depth).

Suite: 95 passed, 0 skipped, ruff clean.
