# TASK-391 — the local half of the gates

**Done by Claude (Grok unavailable), 2026-09-06.** Commit `56d4b66`.

`.pre-commit-config.yaml` ran ruff over `hydra_screener_local/` and nothing else, so the four
cheap checks the audit added only fired in CI — minutes after the push, on someone else's machine.

## What runs now

New hook `hydra-gates` → `tools/precommit_gates.py`, measured on this machine:

```
[ok  ] ruff          0.1s     ruff check . over the whole screener tree
[ok  ] secrets       0.9s     tools/check_secrets.py, dependency-free, repo-wide
[ok  ] packaging     3.3s     test_packaging.py — requirements/pyproject coherence,
                              the wheel's import closure, serialisation, migration
pre-commit gates ok           4.3s total
```

`ruff check .` over the *tree* is the point: R-1004 was precisely the gap between the explicit
module list the runner linted and the tree the brief lints.

## What deliberately stays out

- **The suite** (147s). Not a commit hook. CI owns it.
- **`wheel_smoke.py --structure-only`** (9.8s measured). It is defined as a gate and reachable
  with `--only wheel`, but not in the default set: `--structure-only` still *builds* the wheel,
  and the guard that matters — the import closure against `py-modules` — is already asserted by
  `test_packaging.py` inside the `packaging` gate. CI runs the full build-install-smoke, with the
  venv and the console scripts, on every pull request. The task said drop anything over ~5s, and
  this is the one that hit it.

The script chdir's into `hydra_screener_local/` itself (ruff's per-file-ignores are relative to
that directory — run from the repo root the same config reports 1197 errors), so it works from
anywhere and pre-commit can call it from the repo root.

Each gate prints its own wall-clock. That is not decoration: a hook that quietly grows to 20s is a
hook people start skipping with `--no-verify`, and then the gate is worse than nothing.

## Verification

`python hydra_screener_local/tools/precommit_gates.py` → all three gates ok, 4.3s.
Suite 58/0/0 and CI green on all eight jobs on the same commit.

---

# TASK-391, part 2 — the stage split, and every gate proved able to fail

**Claude, 2026-09-07**, branch `chore/task-391-local-gates` (`origin/main` merged in first, so the
backup fence in `conftest.py` was present: the suite run below wrote nothing into the real backup
root — 298 files before, 298 after).

## Correction to part 1

Part 1 said "run from the repo root the same config reports 1197 errors". That was true and is no
longer: `1c21bc4` on `main` anchors every `per-file-ignores` pattern with `**/`. Measured here on
2026-09-07, both invocations now agree exactly:

| invocation | `core/portfolio_engine.py` | whole tree |
|---|---|---|
| from the repo root (`--config hydra_screener_local/ruff.toml`) | 0 errors | All checks passed, 0.21s |
| from `hydra_screener_local/` (`--config ruff.toml`) | 0 errors | All checks passed, 0.21s |
| either one with `--config 'lint.per-file-ignores={}'` | **9 errors** | — |

The third row is the one that matters: the parked findings are still there, still 9, and they are
suppressed by the config rather than by the gate failing to look. `precommit_gates.py` keeps its
chdir because `ruff.toml` sets `src = ["."]` and the pytest gate needs that directory anyway.

## The seven CI jobs, classified by measured cost

| CI job | command | measured here | verdict |
|---|---|---|---|
| `lint` | `ruff check . --config ruff.toml` | 0.18s (`--no-cache`) | **LOCAL** (commit) |
| `secret-scan` (python half) | `tools/check_secrets.py` | 1.0s | **LOCAL** (commit) |
| `reproducibility` (packaging half) | `pytest -q test_packaging.py` | 3.6s | **LOCAL** (commit) |
| `typecheck` | `mypy --config-file mypy.ini` | 0.8s incremental / **21.8s cold** | **PRE-PUSH** |
| `reproducibility` (the other 5 files) | `pytest -q test_pit_identity.py …` | 9.0s, 172 tests | **PRE-PUSH** |
| `screener` | `run_all_tests.py --strict-console` | **140.0s**, 60 passed 0 skipped | CI-ONLY |
| `screener` / coverage floor | `tools/check_coverage.py --min 80.0` | needs a `--cov` suite run | CI-ONLY |
| `screener` / skip census | `tools/check_skips.py` | re-runs the whole suite | CI-ONLY |
| `build-install-smoke` | `tools/wheel_smoke.py` | clean venv + network; `--structure-only` alone is **11.6s** | CI-ONLY |
| `secret-scan` (gitleaks half) | `gitleaks/gitleaks-action@v2` | no gitleaks binary on this machine | CI-ONLY |
| `dependency-audit` | `pip-audit -r requirements*.txt` | pip-audit not installed; queries the advisory DB; `continue-on-error` in CI | CI-ONLY |

Commit stage total **4.7s**, push stage **7.6s** warm.

## Two gaps found while doing it

1. **The secret sweep was behind `files: ^hydra_screener_local/`.** A commit touching only a root
   file skipped it. Reproduced: a root `_gate_probe.md` holding an AWS-shaped key was reported
   `hydra commit gates … (no files to check) Skipped`. It is now its own `always_run` hook.
2. **`check-merge-conflict` could not fail.** Its default only looks while `MERGE_HEAD` exists, so
   a staged file with a full marker triple committed clean. Fixed with `--assume-in-merge`
   (`04f3cb9`); no tracked file starts a line with a marker, so there is nothing to absorb.

## Every gate, made to fail on purpose (commit refused, verbatim)

```
end-of-file-fixer   Fixing hydra_screener_local/tools/_gate_probe.py  ("files were modified by this hook")
check-json          _gate_probe.json: Failed to json decode (Expecting value: line 1 column 7 (char 6))
check-yaml          expected the node content, but found '<stream end>'  in "_gate_probe.yaml", line 2, column 1
check-toml          _gate_probe.toml: Expected ']' at the end of a table declaration (at line 1, column 7)
check-merge-conflict _gate_probe.md:2: Merge conflict string '<<<<<<<' found
check-case-conflict Case-insensitivity conflict found: _GATE_PROBE_CASE.MD
detect-private-key  Private key found: _gate_probe.md
hydra-gates (ruff)  F401 [*] `os` imported but unused --> tools\_gate_probe.py:1:8   -> requested gates failed: ruff
hydra-gates (pkg)   AssertionError: _gate_probe_missing (test_every_declared_module_actually_exists)
hydra-secret-sweep  MATCH  _gate_probe.md:1: aws access key: AKIA…  -> secret sweep FAILED: 0 env file(s), 1 match(es)
hydra-push-gates    tools\check_coverage.py:82: error: Incompatible types in assignment … -> push gates failed: typecheck
hydra-push-gates    FAILED test_numeric_safety.py::test_gate_probe_must_fail -> push gates failed: reproducibility
```

`HEAD` was unchanged after each refusal and every probe file is gone. The two push-stage probes were
committed on purpose and then reset: a type error and a red ledger test **commit** cleanly and are
stopped at the push, which is the split working as intended.

The pre-push hook was exercised through a private `core.hooksPath` (`git -c core.hooksPath=… push
--dry-run`), never by installing anything into the shared `.git/hooks` — that directory is common to
the operator's clone and every worktree, and the live path is frozen.

## What the operator has to do once

`.git/hooks/` currently holds only `pre-commit`. `default_install_hook_types: [pre-commit, pre-push]`
is in the config, so one command installs both:

    python -m pre_commit install

Until that is run the push gates do not exist on this machine — the config alone does not install them.

## Not added, on purpose

- **No hook over the frozen-path ruff findings.** `core/`, `portfolio_v9.py`, `daily.py` and
  `preflight.py` are parked in `per-file-ignores` until the first settle after the 2026-09-08 close.
  A gate there could only pass by ignoring something real.
- **`no-commit-to-branch --branch main`** looks made for rule 1, and is wrong here: the operator and
  Copilot commit to `main` as normal practice (the board commits do). It would block them daily.
- **`mixed-line-ending`.** The tree is CRLF-on-checkout via git; a normalising hook is a mass rewrite.
- **`pre-commit run --all-files` still rewrites 15 files** (trailing whitespace / missing final
  newline), three of them rule-6 locked: `core/signals.py`, `core/meta_layer.py`, `core/regime.py`,
  plus `HYDRA_ALGORITHM_SPEC.md`. Reverted here, untouched. So a future commit that legitimately
  edits one of those files will have its whitespace fixed by the hook as a side effect. Excluding the
  locked files from the two fixers is a one-line change and is **not** made here — it is Lucas's call
  whether the fixers may touch them at all.
