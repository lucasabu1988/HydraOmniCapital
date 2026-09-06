# Branch protection and merge checks for `main`

Audit phase 10.7. Nothing here is applied automatically — a ruleset is a repository
setting, not a file — so this is the exact configuration to paste in, and the reason
for each part.

## Required status checks

Settings -> Rules -> Rulesets -> New branch ruleset, target `main`:

- **Require a pull request before merging** — 1 approval, dismiss stale approvals on
  new commits.
- **Require status checks to pass**, with *Require branches to be up to date* on.
  The checks, exactly as `.github/workflows/test.yml` names them:

  | check | job | why it blocks a merge |
  |---|---|---|
  | `screener (3.12)` | `screener` | the suite, the coverage floor and the skip gate |
  | `screener (3.13)` | `screener` | the version Lucas will move to |
  | `lint` | `lint` | includes `ruff check .` over the whole tree |
  | `build-install-smoke` | `build-install-smoke` | the wheel installs clean and every console script runs |
  | `typecheck` | `typecheck` | mypy over the audited modules |
  | `secret-scan` | `secret-scan` | gitleaks plus the dependency-free sweep |
  | `reproducibility` | `reproducibility` | serialisation, state migration, PIT identity, ledger integrity |

  `dependency-audit` is deliberately **not** required: a CVE in a transitive pin is
  not a reason to block a screener commit, but it must be visible. Read it, do not
  gate on it.

- **Block force pushes** — on. Rule 5 of the audit brief: the history is never
  rewritten.
- **Restrict deletions** — on.
- **Require linear history** — optional. The Claude/Grok workflow uses small commits
  on a branch, so either merge strategy is fine; pick one and stay with it.

## What still needs a human

CI proves code regression coverage. It does not prove financial validity or a track
record, and no gate here should be read as doing so:

1. **A scoring change needs Lucas's explicit approval** (GROKBOARD rule 6). CI runs
   `test_spec_compliance.py`, which enforces the formulas and the parameter values in
   `config.py` against `HYDRA_ALGORITHM_SPEC.md` section 6 — so a scoring change
   *fails* CI until the spec is updated in the same commit. That is the mechanism, not
   a substitute for the approval.
2. **The golden fixture** (`test_fixtures/engine_golden_v9.json`) is a
   characterisation test. Regenerating it is allowed only with the before/after
   numbers in the commit message; see the two regeneration records in
   `docs/AUDIT_REPRODUCTIONS.md` for the format.
3. **A merge from `post-freeze-wiring` or `n-sleeve-engine`** is a review, not a
   status check. The preconditions for the N-sleeve engine are listed in the audit
   report.

## Local pre-commit

`.pre-commit-config.yaml` already runs ruff. To get the fast half of CI before
pushing:

```bash
cd hydra_screener_local
python run_all_tests.py --cov --strict-console
python tools/check_coverage.py --min 77.0
python -m ruff check . --config ruff.toml
python -m mypy --config-file mypy.ini
python tools/check_secrets.py
python tools/wheel_smoke.py --structure-only     # seconds; no venv, no downloads
```

The full `python tools/wheel_smoke.py` builds a venv and downloads pandas, numpy and
scipy — a few minutes. CI runs that one on every pull request, so locally the
`--structure-only` pass is usually enough.
