# TASK-388 — the CI's first real run

**Done by Claude (Grok unavailable), 2026-09-06.** PR **#40**, draft, `structural-hardening-2026-09` → `main`.
It stays draft: nothing merges before the first settle after the 2026-09-08 close is verified.

## Run 1 — 6 of 8 red

Everything was green on this machine and six jobs failed on the runner, which is exactly why the
task existed.

| job | run 1 | cause |
|---|---|---|
| `lint` | pass | |
| `dependency-audit` | pass | report-only, as designed |
| `secret-scan` | **fail** | gitleaks-action v2 refuses a `pull_request` event without `GITHUB_TOKEN` |
| `build-install-smoke` | **fail** | `console_dashboard` NameError — see below |
| `screener (3.12)` | **fail** | same NameError, plus one brittle assertion |
| `screener (3.13)` | **fail** | same |
| `typecheck` | **fail** | mypy with pandas-stubs (CI installs them, this machine had not) |
| `reproducibility` | **fail** | same NameError |

## The one real bug: the rich fallback never worked

`console_dashboard.py` advertises a plain-text fallback (`RICH_AVAILABLE`) but annotates its
formatters with `-> Panel`, `-> Table`, `-> Layout` at module level. With rich absent, **importing
the module raised `NameError: name 'Panel' is not defined`** — the fallback died before it could
fall back, and `hydra-console` was broken on any machine without rich.

It never showed here because rich is installed on this laptop. Phase 10.3 moved rich to an extra
(it is not a hard requirement and was not installed on Lucas's machine either), and the very first
clean-venv install found it in 30 seconds:

```
[4/5] import every public module from the installed copy
      FAIL  BAD=["console_dashboard: NameError: name 'Panel' is not defined"]
[5/5] run every console script
      FAIL hydra-console -> 1
```

Fix: `from __future__ import annotations`. Verified with rich forced absent — the module imports
and `hydra-console --help` exits 0.

## The three environment differences

- **gitleaks**: `GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}` added to the step, plus
  `contents: read` / `pull-requests: read` on the job. No secret to create; the automatic token is
  enough. The dependency-free `tools/check_secrets.py` sweep passed on run 1 either way, which is
  why that second pass exists.
- **mypy**: CI installs `pandas-stubs`; this machine did not, so `python -m mypy` was green here
  and red there. Two errors, both narrowed without moving logic (`to_numeric(None)` has no
  overload; `.values` is `ndarray | ExtensionArray` and only the first has `tobytes()`).
  pandas-stubs is installed locally now, so the local run means what CI means.
- **`test_quality_of_an_unknown_ticker_is_reported_not_dropped`** asserted `is None` for a missing
  date. `None` in a column that also holds timestamps is `None` here and `NaN` on the runner. The
  claim is that the row exists with a missing date, so it asserts `pd.isna`.

## Run 2 and run 3 — 8 of 8 green

```
build-install-smoke  pass   35s
dependency-audit     pass   25s
lint                 pass    9s
reproducibility      pass   35s
screener (3.12)      pass  2m18s
screener (3.13)      pass  1m34s
secret-scan          pass   13s
typecheck            pass   31s
```

**Linux coverage: 81.22%** (81.96% on Windows — the platform gap is real). Skip gate: 0 skips over
58 files. Recorded, not adjusted to fit: that number is what TASK-390 used to ratchet the floor to
80.0.

Wall clock for the whole run: about 2.5 minutes, dominated by `screener (3.12)`.

## What is still not proven by any of this

CI proves code regression coverage. It does not prove financial validity, and the seven required
checks in `docs/BRANCH_PROTECTION.md` are still **documented, not applied** — a ruleset is a
repository setting and needs admin. That one is Lucas's.
