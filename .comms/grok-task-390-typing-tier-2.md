# TASK-390 — typed tier 2, and the coverage ratchet

**Done by Claude (Grok unavailable), 2026-09-06.** Commit `56d4b66`.

## Typing

`mypy.ini` went from 10 modules to 16: the five the audit rewrote heavily
(`core/dividends.py`, `core/journal.py`, `core/state_migrations.py`, `data/pit.py`,
`utils/runlog.py`) plus `tools/precommit_gates.py`.

Rule for the task was annotations only — no logic change, and anything needing one gets left out
with a reason. Nothing had to be left out. What the pass found:

- **`MIGRATIONS: dict[int, callable]`** used the *builtin* `callable` as a type. mypy: "Function
  `builtins.callable` is not valid as a type". The annotation said nothing at all; it is
  `Callable[[dict], dict]`. (Watch the import order: `from __future__ import annotations` must
  stay the first statement — putting the new import above it is a `SyntaxError`, which the suite
  caught immediately.)
- **`datetime.now().astimezone().utcoffset().total_seconds()`** dereferenced an Optional.
  `astimezone()` never returns a naive datetime so it cannot fire in practice, but the type says
  it can; `_utc_offset_seconds()` handles it explicitly.
- **`V9` is a heterogeneous config dict**, so every read out of it is `object` to mypy —
  `set(V9["etf_universe"])`, `V9.get("stock_target_vol", 0.15) / vol`. Rather than a cast at each
  use site, `core.dividends.etf_universe()` is now the single place that says what
  `V9["etf_universe"]` is, and `core/journal.py` uses it.
- `config.py` and `data/sectors.py` are imported by the checked modules but are not audited yet:
  `follow_imports = silent` for those two, so their own errors are not reported as if this tier
  had adopted them. Both carry real findings for a later tier (`FILTERS` has no element type;
  `sectors.py` has an implicit-Optional parameter).

`python -m mypy --config-file mypy.ini` → **Success: no issues found in 16 source files**, with
pandas-stubs installed (see TASK-388: without the stubs the local run is weaker than CI's).

## Coverage ratchet

CI produced the first real number on Linux: **81.22%**. Windows measures **81.96%** on the same
commit — the gap is platform, not test selection.

Floor raised **77.0 → 80.0** in `.github/workflows/test.yml`, with ~1pp of headroom under the
lower of the two. `BASELINE_PCT` in `tools/check_coverage.py` updated to 81.22 so the tool's
"consider raising" hint is measured against the truth.

The floor ratchets up and is never lowered to make a red build green. If a change drops coverage
below 80, the answer is tests, not a smaller number.

## Verification

Suite 58 passed / 0 skipped, `ruff check .` clean, mypy clean over 16 modules, coverage 81.96%
locally and CI green on all eight jobs after the change.
