"""The cheap half of CI, run before the commit or the push instead of minutes after it.

    python hydra_screener_local/tools/precommit_gates.py                  # the commit gates
    python hydra_screener_local/tools/precommit_gates.py --stage push     # the push gates
    python hydra_screener_local/tools/precommit_gates.py --list           # what it runs
    python hydra_screener_local/tools/precommit_gates.py --only ruff

Audit phase 10 follow-up (TASK-391). Each of the seven CI jobs was timed locally and
placed in the stage it can actually afford; the measured wall-clock is in the table
below and is printed on every run, so the hook stays honest about what it costs.

commit stage (`--stage commit`, ~5s total) — the `lint` and `secret-scan` jobs, plus
the packaging half of `reproducibility`:

    ruff        `ruff check .` over the whole screener tree, 0.1-0.2s. R-1004 was
                exactly the gap between the explicit module list and the tree
    secrets     tools/check_secrets.py, dependency-free, repo-wide, 1.0s. Gitleaks
                itself stays in CI: the binary is not installed locally
    packaging   test_packaging.py, 3.6s — requirements/pyproject coherence, the
                wheel's import closure, serialisation, state migration. This is the
                gate that fails the moment a module is added or deleted without
                `py-modules`/`[project.scripts]` following it

push stage (`--stage push`, ~10s warm / ~31s with a cold mypy cache) — the `typecheck`
job and the rest of `reproducibility`. Too slow to pay on every commit, cheap enough
to pay once per push:

    typecheck        `mypy --config-file mypy.ini`, 0.8s incremental / 21.8s cold
    reproducibility  the five ledger/PIT/numeric files of the CI job, 9.0s

Not here, and why (measured, not assumed):

    screener         run_all_tests.py is 140s (60 passed, 0 skipped, 2026-09-07).
                     tools/check_skips.py and tools/check_coverage.py both need that
                     run, so all three stay in CI
    build-install-smoke  the real job installs the wheel into a clean venv (network).
                     `wheel_smoke.py --structure-only` is available with `--only wheel`
                     but is 11.6s and proves a subset of what test_packaging.py
                     already asserts; CI runs the real one on every pull request
    dependency-audit pip-audit queries the advisory database (network) and is
                     report-only in CI; it cannot gate a local commit

The `ruff` gate runs from `hydra_screener_local/` because `ruff.toml` sets `src = ["."]`
and the secrets/pytest gates need that working directory too. Since 1c21bc4 the
per-file-ignores are anchored with `**/`, so the frozen-path ignores now apply from
either directory — verified on 2026-09-07: `core/portfolio_engine.py` reports 0 errors
from the repo root and 0 from inside, and 9 from both when the ignores are neutralised.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent

#: the five reproducibility files that are not test_packaging.py (the CI job's list)
_REPRODUCIBILITY_FILES = [
    "test_pit_identity.py",
    "test_commit_transaction.py",
    "test_ledger_integrity.py",
    "test_ledger_projection.py",
    "test_numeric_safety.py",
]

GATES: dict[str, list[str]] = {
    "ruff": [sys.executable, "-m", "ruff", "check", ".", "--config", "ruff.toml"],
    "secrets": [sys.executable, "tools/check_secrets.py"],
    "packaging": [sys.executable, "-m", "pytest", "-q", "test_packaging.py"],
    "typecheck": [sys.executable, "-m", "mypy", "--config-file", "mypy.ini"],
    "reproducibility": [sys.executable, "-m", "pytest", "-q", *_REPRODUCIBILITY_FILES],
    "wheel": [sys.executable, "tools/wheel_smoke.py", "--structure-only"],
}

#: what each stage runs. `wheel` is defined but in neither set: `--structure-only`
#: still builds the wheel (11.6s), and the guard that matters — the import closure vs
#: `py-modules` — is already asserted by test_packaging.py. CI runs the real one.
COMMIT_GATES = ("ruff", "secrets", "packaging")
PUSH_GATES = ("typecheck", "reproducibility")
STAGES: dict[str, tuple[str, ...]] = {"commit": COMMIT_GATES, "push": PUSH_GATES}

#: kept for callers that predate --stage
DEFAULT_GATES = COMMIT_GATES


def run_gate(name: str) -> tuple[bool, float, str]:
    started = time.time()
    proc = subprocess.run(GATES[name], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.returncode == 0, time.time() - started, (proc.stdout or "") + (proc.stderr or "")


def main(argv: list[str] | None = None) -> int:
    doc = __doc__ or ""
    ap = argparse.ArgumentParser(description=doc.splitlines()[0])
    ap.add_argument("--stage", choices=sorted(STAGES), default="commit",
                    help="which stage's gates to run (default: commit)")
    ap.add_argument("--only", action="append", choices=sorted(GATES),
                    help="run just this gate (repeatable); overrides --stage")
    ap.add_argument("--list", action="store_true", help="print the gates and exit")
    args = ap.parse_args(argv)

    if args.list:
        for name, cmd in GATES.items():
            stage = next((s for s, names in STAGES.items() if name in names), "on request")
            print(f"{name:16s} [{stage}] {' '.join(cmd[1:])}")
        return 0

    selected: list[str] = args.only or list(STAGES[args.stage])
    failed: list[str] = []
    for name in selected:
        ok, seconds, output = run_gate(name)
        print(f"[{'ok  ' if ok else 'FAIL'}] {name:16s} {seconds:5.1f}s")
        if not ok:
            failed.append(name)
            print(output.rstrip())

    label = args.stage if not args.only else "requested"
    if failed:
        print(f"\n{label} gates failed: {', '.join(failed)}")
        return 1
    print(f"{label} gates ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
