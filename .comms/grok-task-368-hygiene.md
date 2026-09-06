# TASK-368 — Engineering hygiene

Live path not edited except two non-behaviour ruff fixes outside `core/` /
`portfolio_v9.py` / `daily.py` / `preflight.py`. No scoring change.

## What landed

- `hydra_screener_local/ruff.toml` — E, F, I, B; line-length 120. Ignores: E501
  (no mass wrap), E402 (sys.path convention), I001 (no mass isort). Frozen live
  path and legacy/Pine/experiments are per-file ignored so CI is green during
  the freeze.
- `.pre-commit-config.yaml` (repo root) — kept the existing `check-json` /
  `check-yaml` / trailing-whitespace / end-of-file hooks; ruff now points at
  `hydra_screener_local/ruff.toml` and only runs under that tree. No mass rewrite.
- `requirements-dev.txt` — pytest, pytest-timeout, pytest-cov, ruff, pre-commit.
  Production install is still `requirements.txt`.
- `run_all_tests.py --cov` — after a green suite, re-runs the pytest-style files
  with `--cov=core --cov=data --cov=utils --cov=sleeves`, prints the table,
  writes `coverage.xml` (gitignored). **No fail-under floor** (Claude's call).
  Missing pytest-cov → exit 1 with the install hint. Default path (no `--cov`)
  unchanged.
- CI `test.yml` — matrix 3.12 / 3.13, `run_all_tests.py --cov`, coverage XML
  artifact on 3.12. New `lint` job: `ruff check` on the lint surface.
- `.github/workflows/data-smoke.yml` — nightly 05:00 UTC + `workflow_dispatch`.
  yfinance 5 stocks + the 10 ETFs + `^IRX`, `preflight.evaluate` on the frames.
  `continue-on-error: true`. No secrets.
- `docs/ARCHITECTURE.md` — modules, mermaid data flow, state schema, writes vs
  read-only, env names, legacy.
- `docs/RUNBOOK.md` — Tuesday close ritual, failure modes (HARD, split, delist,
  not_filled, disk loss → `HYDRA_BACKUP_DIR`), moving the machine. Local time
  conversion called out (machine is not ET).

## Real findings fixed (non-frozen)

| file | rule | change |
|---|---|---|
| `data/fetch.py` | F401 | unused `datetime`, `timedelta` imports dropped |
| `utils/display.py` | F541 | f-string with no placeholders |
| `evidence_review.py` | F541 | two header f-strings |
| `dashboard_v9.py` | B007 | unused loop name; iterate `.values()` |
| `data/universe.py` | B023 | bind loop `df` as `_col(..., _df=df)` |

## Frozen findings (not fixed — live path)

`core/portfolio_engine.py`: F401 (`typing.Dict`), B905 (`zip` without `strict=`),
E702 (semicolons on one line), I001. `core/meta_layer.py`: F401 (`numpy`).
`portfolio_v9.py` / `preflight.py`: I001. Listed for Claude after "first settle
verified".

## Coverage (report-only, this machine, Python 3.14)

TOTAL **62%** over `core data utils sleeves`. Engine 96%, tranche_book 98%,
signals 84%, `data/universe.py` 13%, `utils/display.py` 10%. Floor not set.

## Tests

`ruff check` on the lint surface: clean.
Suite: **36 passed, 2 skipped, exit 0**. `--cov` extra pass 227 pytest tests, exit 0.
