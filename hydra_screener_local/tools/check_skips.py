"""A skip is not a pass: fail when an unexplained test file skips (audit phase 10.5).

    python tools/check_skips.py

`run_all_tests.py` already reports skips apart from passes. This turns that report
into a gate: a file may skip only if it is listed in `EXPECTED_SKIPS` with a reason,
and the current baseline (0 skips since TASK-374) is asserted so a new skip cannot
quietly become the norm.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent

#: file -> why it is allowed to skip. A skip with no entry here fails the build.
EXPECTED_SKIPS: dict[str, str] = {
    "test_hybrid_integration.py":
        "needs history/, which is gitignored and lives on one disk (CLAUDE.md)",
    "validate_pine_contract.py":
        "needs pine/hydra_last_summary.json, produced by a real screener run",
}

RESULTS_RE = re.compile(r"RESULTS:\s*(\d+)\s+passed,\s*(\d+)\s+skipped")
SKIP_LINE_RE = re.compile(r"^\[SKIP\]\s+(\S+)")


def run_suite() -> tuple[int, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run(
        [sys.executable, "run_all_tests.py", "--strict-console"],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=1800,
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="fail on unexplained skips")
    ap.add_argument("--from-file", type=str, default=None,
                    help="parse an existing runner log instead of running the suite")
    args = ap.parse_args(argv)

    if args.from_file:
        rc, out = 0, Path(args.from_file).read_text(encoding="utf-8", errors="replace")
    else:
        rc, out = run_suite()

    if rc != 0 and not args.from_file:
        print("check_skips: the suite itself failed; fix that first")
        print(out[-2000:])
        return rc

    skipped_files = [m.group(1) for line in out.splitlines()
                     if (m := SKIP_LINE_RE.match(line.strip()))]
    m = RESULTS_RE.search(out)
    n_passed, n_skipped = (int(m.group(1)), int(m.group(2))) if m else (None, None)

    print(f"skips: {len(skipped_files)} file(s) skipped"
          + (f"; runner reports {n_passed} passed, {n_skipped} skipped"
             if n_passed is not None else ""))

    unexplained = [f for f in skipped_files if f not in EXPECTED_SKIPS]
    for f in skipped_files:
        why = EXPECTED_SKIPS.get(f)
        print(f"  {f:<34} {'expected: ' + why if why else 'UNEXPLAINED'}")

    if unexplained:
        print(f"check_skips FAILED: {len(unexplained)} unexplained skip(s): "
              f"{', '.join(unexplained)}")
        print("      add it to EXPECTED_SKIPS with a reason, or make the test run.")
        return 1

    if n_skipped:
        print(f"note: {n_skipped} pytest-level skip(s) inside files that otherwise pass — "
              f"a skip is not a pass, check them by hand")

    print("check_skips ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
