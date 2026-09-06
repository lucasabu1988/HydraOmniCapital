# TASK-384 — Post-freeze wiring, prepared on a separate worktree (done by Claude, 2026-09-06)

Grok ran out of credits before claiming this; Claude finished it. **Main is untouched.** The work is on
branch `post-freeze-wiring`, checked out in the worktree `../HydraOmniCapital-wiring` (never in this
directory: Lucas runs production from this tree). Suite on the branch: `run_all_tests.py --strict-console`
**46 passed / 0 skipped / 0 failed**, ruff clean.

## Commits on the branch (in order)

| commit | item |
|---|---|
| `df2b111` | TASK-360: preflight runs `state_check.check` before settle — ERROR -> HARD, WARN -> WARN, no state -> SKIP. TASK-375: `universe_report()["fallback"]` -> WARN. Two test fixtures were hand-built states no ledger explained (units set without fills); made consistent. |
| `77f6df1` | TASK-359: `core/journal.py` record carries `process.manifest_path`. Plus a real defect found by the TASK-383 rehearsal: the journal read `meta_regime_type`, the ranking contract (SPEC 7) names the column `regime_type` — the regime label was always None. |
| `ec60f43` | Frozen ruff findings in `core/portfolio_engine.py` (unused `Dict`, `zip(strict=True)`, five semicolon lines split) and `core/meta_layer.py` (unused numpy). `test_engine_golden.py` and `test_portfolio_engine.py` pass unchanged; **the golden was not regenerated**. |
| `6d51b0c` | TASK-359: `portfolio_v9.main` and `daily.main` run inside `utils.runlog.start_run` (fingerprints for stocks/etf/^IRX after the fetch, artifacts = state, sheet md/json, backup; exit status; `manifest_path` in the return dict). TASK-360: `load_state` applies `migrate`, unknown schema -> `SystemExit`. TASK-375: `fetch_v9_market` carries `universe_report()` to preflight. TASK-362: `daily.py` writes a universe + sectors PIT snapshot after a real run (only when the run returned prices, never in dry tests); `copy_state_off_disk` mirrors `data_cache/pit/` and `runs/` to `HYDRA_BACKUP_DIR`. |
| `eebaeeb` | `test_wiring_384.py`: 13 tests (migrate fill / refuse, replay OK on the execution-day configuration with pending + empty ledger, replay HARD on unexplained cash, universe WARN/OK/SKIP, runlog fingerprints + artifacts + manifest_path, `runlog=None` unchanged, daily snapshot hook only after a real run, daily manifest, off-disk mirror, regime label). |

`git diff --stat main..post-freeze-wiring`: 11 files, +386 / -24.

## What changes for the operator after the merge

- Every `daily.py` / `portfolio_v9.py` run leaves `runs/<stamp>_<name>/manifest.json` + `log.txt`
  (`python runlog_cli.py --last`), mirrored to `HYDRA_BACKUP_DIR/runs/` when the env is set.
- Preflight gains two rows: `state replay` (HARD if the stored tranches disagree with the ledger) and
  `universe source` (WARN if the S&P list came from the hardcoded fallback).
- `data_cache/pit/` gets a new universe/sectors snapshot (or a pointer) after each real run.
- Default behaviour is otherwise identical: `runlog=None` paths are the old ones; the parity suite is green.

## Merge (after "first settle verified", from this tree)

```
git merge --no-ff post-freeze-wiring -m "merge: post-freeze wiring (TASK-384)"
cd hydra_screener_local && python run_all_tests.py --strict-console
git push origin main
git worktree remove ../HydraOmniCapital-wiring && git branch -d post-freeze-wiring
```

Do not merge before the Tuesday 2026-09-08 settle has been verified on the frozen code.
