"""The cheap half of CI, run before the commit instead of minutes after the push.

    python hydra_screener_local/tools/precommit_gates.py            # all gates
    python hydra_screener_local/tools/precommit_gates.py --list     # what it runs
    python hydra_screener_local/tools/precommit_gates.py --only ruff

Audit phase 10 follow-up (TASK-391). Three gates by default, ~4s together:

    ruff        `ruff check .` over the whole screener tree — R-1004 was exactly the
                gap between the explicit module list and the tree
    secrets     tools/check_secrets.py, dependency-free, repo-wide
    packaging   test_packaging.py — requirements/pyproject coherence, the wheel's
                import closure, serialisation, state migration

A fourth gate, `wheel` (`wheel_smoke.py --structure-only`), is available with
`--only wheel` but is not run by default: it builds the wheel (~10s), and what it
proves about the closure is already asserted by test_packaging.py. CI runs the full
build-install-smoke on every pull request.

The full suite (143s) deliberately stays in CI. Each gate prints its wall-clock so the
hook stays honest about what it costs; anything that grows past a few seconds belongs
in CI, not here.

The hook needs the working directory to be `hydra_screener_local/` (ruff's
per-file-ignores are relative to it), so this script does the chdir itself and can be
called from anywhere.
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

GATES: dict[str, list[str]] = {
    "ruff": [sys.executable, "-m", "ruff", "check", ".", "--config", "ruff.toml"],
    "secrets": [sys.executable, "tools/check_secrets.py"],
    "packaging": [sys.executable, "-m", "pytest", "-q", "test_packaging.py"],
    "wheel": [sys.executable, "tools/wheel_smoke.py", "--structure-only"],
}

#: `wheel` is defined but not in the default set: `--structure-only` still builds the
#: wheel (~10s), and the guard that matters — the import closure vs `py-modules` — is
#: already asserted by test_packaging.py in the `packaging` gate. CI runs the real one.
DEFAULT_GATES = ("ruff", "secrets", "packaging")


def run_gate(name: str) -> tuple[bool, float, str]:
    started = time.time()
    proc = subprocess.run(GATES[name], cwd=ROOT, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    return proc.returncode == 0, time.time() - started, (proc.stdout or "") + (proc.stderr or "")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", action="append", choices=sorted(GATES),
                    help="run just this gate (repeatable)")
    ap.add_argument("--list", action="store_true", help="print the gates and exit")
    args = ap.parse_args(argv)

    if args.list:
        for name, cmd in GATES.items():
            print(f"{name:10s} {' '.join(cmd[1:])}")
        return 0

    failed = []
    for name in (args.only or list(DEFAULT_GATES)):
        ok, seconds, output = run_gate(name)
        print(f"[{'ok  ' if ok else 'FAIL'}] {name:10s} {seconds:5.1f}s")
        if not ok:
            failed.append(name)
            print(output.rstrip())

    if failed:
        print(f"\npre-commit gates failed: {', '.join(failed)}")
        return 1
    print("pre-commit gates ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
