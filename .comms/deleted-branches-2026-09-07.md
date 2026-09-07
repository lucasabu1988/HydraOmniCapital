# Branches deleted 2026-09-07

Lucas asked for the ten dead branches to be removed, having verified they affect nothing.
Deleting a remote branch does not delete its commits: every SHA below still exists in this
repository's object database and is recoverable with
`git branch <name> <sha>` (or `git push origin <sha>:refs/heads/<name>`) until git garbage-collects
unreachable objects. This file is the record that makes that possible, which is why it is in git
and not in a terminal scrollback.

## Already contained in `main` — deleting them loses nothing at all

- **`feature/hydra-local-screener`** — `fdb5a05f13213c28647190e9d53764ee1dd10039` (2026-05-31) — ancestor of main, 0 unique commits. "chore(screener): Minor cleanup before save & exit"
- **`feature/hydra-meta-layer-v1`** — `cec172484aecdfd09ede0ee9511b5efdb865c431` (2026-05-31) — ancestor of main, 0 unique commits. "feat(meta): complete live Meta-Layer v1 wiring on omnicapital.onrender.com algorithm"
- **`fix/utc-timezone-dashboard-update-age`** — `611fb8b61b53bbe7d786242b1dfb36d1ce8aacc2` (2026-03-25) — ancestor of main, 0 unique commits. "fix: resolve UTC timezone mismatch causing negative update age on dashboard"

## Unmerged, and every file they touch is a subsystem that no longer exists

COMPASS, the Render deployment and both dashboards were deleted on 2026-09-06;
`omnicapital_live.py` and `omnicapital_broker.py` went on 2026-06-05. None of these branches
touches `hydra_screener_local/`, which is the whole of the live project.

- **`claude/analyze-test-coverage-DroLw`** — `ab2fc220ad9cfb7a878a4e882e36b77836504409` (2026-03-13), 1 unique commit(s). "docs: add comprehensive test coverage analysis"
  - touches: `docs/plans/2026-03-13-test-coverage-analysis.md`
- **`claude/check-dashboard-health-3sNYP`** — `66bbc29dccedde657f835588e627b168daf6ad6b` (2026-04-10), 1 unique commit(s). "fix: restore modules deleted by repo cleanup that broke test imports"
  - touches: `backtest_lab.py`, `exp44_modules/__init__.py`, `exp44_modules/exits.py`, `exp44_modules/regime.py`, `exp44_modules/risk.py`, `exp44_modules/signals.py`, `src/__init__.py`, `src/core/__init__.py` …
- **`claude/mobile-dashboard-view-X1lOG`** — `8ee4d2014b2241cc1add73bafbcbe1d95322215f` (2026-02-24), 2 unique commit(s). "chore: ignore compass runtime log files in .gitignore"
  - touches: `.gitignore`, `templates/dashboard.html`
- **`devin/1780523422-security-hardening`** — `16ddd756baf8a1d24113c00db05078fdd2592ccf` (2026-06-03), 1 unique commit(s). "fix: security hardening — remove hardcoded secrets, add auth guards, add security headers"
  - touches: `compass_dashboard.py`, `compass_dashboard_cloud.py`, `scripts/daily_monitor.py`, `scripts/download_missing_tiingo.py`, `scripts/test_tiingo_delisted.py`
- **`fix/bugs-identified-review`** — `80ba2515ce323621d8a05b3bda4b469ea34d55d7` (2026-04-04), 1 unique commit(s). "fix: apply 7 bug fixes identified in code review"
  - touches: `omnicapital_live.py`
- **`fix/live-dashboard-bugs`** — `8b1ee3268b42f8619b2c4bbb806ec8ff84f48ff3` (2026-04-05), 2 unique commit(s). "fix(core): resolve 8 bugs across engine, broker and tooling modules"
  - touches: `compass/sp500_universe.py`, `compass_dashboard.py`, `hydra_tools.py`, `omnicapital_broker.py`, `omnicapital_live.py`
- **`project-overview-explanation-0b83a`** — `cba783bbb69c9f449b30e29e3c174f25cae85966` (2026-05-11), 4 unique commit(s). "Update gitignore with comprehensive ignore patterns"
  - touches: `.gitignore`, `__pycache__/compass_fred_data.cpython-312.pyc`, `__pycache__/compass_ml_learning.cpython-312.pyc`, `__pycache__/compass_overlays.cpython-312.pyc`, `__pycache__/git_sync.cpython-312.pyc`, `__pycache__/hydra_capital.cpython-312.pyc`, `__pycache__/omnicapital_broker.cpython-312.pyc`, `__pycache__/omnicapital_data_feed.cpython-312.pyc` …
- **`audit/subtract-parked-clis`** — `924c656360befcc75798773cf831cf5cd63d55a6` (2026-09-06), 2 unique commit(s). "docs(comms): exhaustive analysis prompt for ChatGPT Astra"
  - touches: `.comms/astra-analysis-prompt-2026-09-06.md`, `GROKBOARD.md`

## `audit/subtract-parked-clis` — its two commits are already on main, under different SHAs

Its unique commits are `924c656` (the Astra audit prompt) and `042873c` (a board message). Both were
cherry-picked onto main at the start of the 2026-09-06 session as `309bc60` and `70be198`, because
they had been left stranded on this branch when a window closed. So the branch is redundant by
content, not merely superseded: `git log --oneline main --grep="exhaustive analysis prompt"` finds it.
The v2 branch (`audit/subtract-parked-clis-v2`, PR #44) carries the actual CLI subtraction and is NOT
being deleted.

## The one judgement call

`claude/analyze-test-coverage-DroLw` adds a single document, `docs/plans/2026-03-13-test-coverage-analysis.md`,
analysing a test suite that was archived in September (`archive/root-legacy-2026-09/tests/`). It is the only
one of the ten whose content is not code for a deleted subsystem, so its SHA is worth having above: the
analysis is recoverable, it just describes a suite that no longer exists.

## Not deleted

~~`rescue/subtract-parked-clis-95f5a53` is LOCAL ONLY and holds Grok's eleven commits from the
parked-CLI work, superseded by `audit/subtract-parked-clis-v2`. It was left alone: it is the only
copy of that work and it costs nothing to keep.~~ **Superseded the same evening.** Keeping the only
copy on one laptop was the wrong way to preserve it. The eleven commits were pushed to `origin` as
the annotated tag `rescue/grok-parked-clis-2026-09`, and the branch was then deleted. Second batch below.

## Second batch, 2026-09-07 evening - 21 superseded LOCAL branches (Lucas: "ok proceder")

All twenty-one were local only, so **nothing was removed from GitHub**. Measured before deleting,
not assumed; every SHA below is still in the object database and recoverable with
`git branch <name> <sha>`.

### First: the eleven commits that were NOT anywhere on GitHub

This file's earlier "Not deleted" section kept `rescue/subtract-parked-clis-95f5a53` alive on the
grounds that it was *the only copy* of eleven parked-CLI commits. That was still true today:
`git branch -r --contains` found each of the eleven on **zero** remote branches. Content-wise they
are superseded by `audit/subtract-parked-clis-v2` (PR #44), but superseded content is not the same
thing as a backed-up commit, and "the only copy is on one laptop" is not a place to leave work.
So before the branch was deleted the eleven were pushed as an annotated tag:

```
rescue/grok-parked-clis-2026-09 -> 95f5a53   (on origin)
git branch <name> rescue/grok-parked-clis-2026-09    # to get them back
```

The eleven, newest first:

- `95f5a539b60ad8612b80e49db5c814b9cd27eff7` chore: strip log_cycle_positions from run_real_full_sp500.py
- `04d162b22cba503aa6d9cfbef2f189fb84abb233` chore: strip log_cycle_positions from run_real_full_sp500.py
- `2afb4ccbd663ecf1b08e67b124d0ed7f61478756` chore: strip log_cycle_positions from experiments/run_real_headless.py
- `9c7d036a02dbb848a85b38ea9312598fc8a77dba` chore: remove --refresh-pnl and maybe_refresh_pnl from daily.py
- `8d24207e02f8d474f81870c25c50ab0fdb4d0118` chore: drop log_cycle_positions per-file-ignore from ruff.toml
- `67f188b8299a42c9d77e1fcb4a9b6dfd70092e87` chore: delete test_cycle_logger_calendar.py
- `8f082aa9d0255e981762053f245c73c3ddd1698d` chore: delete refresh_current_prices.py (parked PnL refresher)
- `ea009163e7dbd03afe5ff37af718de9b19d110c3` chore: delete log_cycle_positions.py (parked Excel cycle logger)
- `1a0c1f595c1d31d9abb12dcf73395eb1ba026252` chore: delete parked live_watcher.py
- `2dde76a5176746b0311ad3c62defa6da9aee6cd5` chore: delete parked console_dashboard.py
- `cdb417c8d98814140a7293fa73c30584f2388d65` chore: delete parked generate_html_dashboard.py

### The three superseded work branches, now deleted

- **`review-astra03`** - `93d8ddf1e8cd6b218d862ded4e128dcda9592cb4` (2026-09-07) - "Merge remote-tracking branch 'origin/main' into review-astra03"
- **`audit/subtract-parked-clis`** - `924c656360befcc75798773cf831cf5cd63d55a6` (2026-09-06) - "docs(comms): exhaustive analysis prompt for ChatGPT Astra"
- **`rescue/subtract-parked-clis-95f5a53`** - `95f5a539b60ad8612b80e49db5c814b9cd27eff7` (2026-09-06) - "chore: strip log_cycle_positions from run_real_full_sp500.py"

Why each one loses nothing:

- **`audit/subtract-parked-clis`** - this file already recorded it as deleted in the first batch,
  but only the remote side had gone; the local ref survived. Its two unique commits were
  cherry-picked onto main and both were re-verified today as ancestors of `origin/main`:
  `309bc60` ("exhaustive analysis prompt for ChatGPT Astra") and `70be198` ("the parked-CLI
  subtraction is done, coherent, and CI-green"). The audit prompt's blob is byte-identical on
  main: `260ff7c3176a8884bee9f9735f7e3b56fdcba213`.
- **`rescue/subtract-parked-clis-95f5a53`** - its eleven commits are now on `origin` as the tag
  above, and its content is published through v2 (`git grep log_cycle_positions
  origin/audit/subtract-parked-clis-v2 -- run_real_full_sp500.py` returns nothing).
- **`review-astra03`** - a scratch review branch. Its single unique commit is a merge, and against
  `origin/fix/astra-03-observed-fill-prices` its tree **deletes** 614 lines including
  `test_execution_prices.py` and `test_task_402_mark.py`: it was simply eight commits stale.

### The 18 `worktree-wf_*` leftovers, now deleted

Branch refs left behind by the ultracode workflow runs (their worktrees had already been pruned).
**Zero unique commits across all eighteen** - `git rev-list --count <b> --not --remotes` returned 0
for every one, so each was only a second name for a commit already on a remote.

- `worktree-wf_4c9fe854-c54-1` - `1c21bc4c7fa9a0f91f0cd2cd040b0f7d6fe30a8b`
- `worktree-wf_4c9fe854-c54-10` - `1c21bc4c7fa9a0f91f0cd2cd040b0f7d6fe30a8b`
- `worktree-wf_4c9fe854-c54-11` - `1c21bc4c7fa9a0f91f0cd2cd040b0f7d6fe30a8b`
- `worktree-wf_4c9fe854-c54-12` - `1c21bc4c7fa9a0f91f0cd2cd040b0f7d6fe30a8b`
- `worktree-wf_4c9fe854-c54-2` - `1c21bc4c7fa9a0f91f0cd2cd040b0f7d6fe30a8b`
- `worktree-wf_4c9fe854-c54-3` - `1c21bc4c7fa9a0f91f0cd2cd040b0f7d6fe30a8b`
- `worktree-wf_4c9fe854-c54-4` - `1c21bc4c7fa9a0f91f0cd2cd040b0f7d6fe30a8b`
- `worktree-wf_4c9fe854-c54-5` - `1c21bc4c7fa9a0f91f0cd2cd040b0f7d6fe30a8b`
- `worktree-wf_4c9fe854-c54-6` - `1c21bc4c7fa9a0f91f0cd2cd040b0f7d6fe30a8b`
- `worktree-wf_4c9fe854-c54-7` - `1c21bc4c7fa9a0f91f0cd2cd040b0f7d6fe30a8b`
- `worktree-wf_4c9fe854-c54-8` - `1c21bc4c7fa9a0f91f0cd2cd040b0f7d6fe30a8b`
- `worktree-wf_4c9fe854-c54-9` - `1c21bc4c7fa9a0f91f0cd2cd040b0f7d6fe30a8b`
- `worktree-wf_d930c0a1-edb-1` - `965d22c1531be639230f5635acb5c4cb9ac7fe90`
- `worktree-wf_d930c0a1-edb-2` - `965d22c1531be639230f5635acb5c4cb9ac7fe90`
- `worktree-wf_d930c0a1-edb-3` - `965d22c1531be639230f5635acb5c4cb9ac7fe90`
- `worktree-wf_d930c0a1-edb-4` - `965d22c1531be639230f5635acb5c4cb9ac7fe90`
- `worktree-wf_d930c0a1-edb-5` - `965d22c1531be639230f5635acb5c4cb9ac7fe90`
- `worktree-wf_d930c0a1-edb-6` - `965d22c1531be639230f5635acb5c4cb9ac7fe90`
