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

`rescue/subtract-parked-clis-95f5a53` is LOCAL ONLY and holds Grok's eleven commits from the
parked-CLI work, superseded by `audit/subtract-parked-clis-v2`. It was left alone: it is the only
copy of that work and it costs nothing to keep.
