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
