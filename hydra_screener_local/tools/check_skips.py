"""A skip is not a pass: fail when a test file *or a single test case* skips unexplained.

    python tools/check_skips.py
    python tools/check_skips.py --from-file suite.log

Two levels of accounting, because the gate used to see only the first one (audit ASTRA-04,
defect 1):

  files   `run_all_tests.py` reports `[SKIP] <file>` and a `RESULTS: N passed, M skipped`
          line. A file may skip only if it is listed in `EXPECTED_SKIPS` with a reason.
  cases   inside a file run through pytest, individual tests can skip while the file is
          still reported `[PASS]`. Astra ran the suite on merge-prepared-2026-09 and got
          "64 passed, 0 skipped" while three pytest cases were skipping. Both this gate
          and the runner parsed only the file level, so it exited 0. A case may skip only
          if it is listed in `EXPECTED_CASE_SKIPS`, keyed by test id, and its reason still
          matches the allowlisted text.

The gate also refuses to be blind: if a log reports skipped cases that are not itemised
with a reason (an old-format log, or the case-report plugin failing to load), that is a
failure, not a tolerance.
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

#: test id -> the reason that test is allowed to skip for. The reason is checked, not just
#: the id: a case that starts skipping for a *different* reason is a new skip.
#: Keys are `<file>::<case>` as the runner normalises them (parametrised ids keep their
#: `[param]` suffix). Nothing else may skip.
EXPECTED_CASE_SKIPS: dict[str, str] = {
    "test_portfolio_engine.py::test_parity_stock_targets_with_redesign_lab":
        "lab cache experiments/_sweep_cache/ not present",
    "test_portfolio_engine.py::test_parity_etf_targets_with_sleeve_lab":
        "lab cache experiments/_sweep_cache/ not present",
    "test_review_341.py::test_parity_stock_targets_reproduced":
        "lab cache experiments/_sweep_cache/ not present",
}

RESULTS_RE = re.compile(r"RESULTS:\s*(\d+)\s+passed,\s*(\d+)\s+skipped")
SKIP_LINE_RE = re.compile(r"^\[SKIP\]\s+(\S+)")
CASE_SKIP_RE = re.compile(r"^\[CASE-SKIP\]\s+(\S+)\s*::\s*(.*)$")
CASES_RE = re.compile(r"^CASES:.*?(\d+)\s+skipped")
#: pytest's own tail summary ("11 passed, 2 skipped in 1.16s"), the independent witness
#: of how many cases skipped. Anchored on the whole `<counts> in <seconds>` shape so a
#: test that merely prints the word "skipped" cannot trip it.
PYTEST_TAIL_RE = re.compile(r"^((?:\d+ [a-z]+(?:, )?)+) in \d+(?:\.\d+)?s")


def run_suite() -> tuple[int, str]:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run(
        [sys.executable, "run_all_tests.py", "--strict-console"],
        cwd=str(ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=1800,
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _pytest_tail_skips(out: str) -> int:
    """Cases pytest itself said it skipped, summed over the per-file tail summaries."""
    total = 0
    for line in out.splitlines():
        m = PYTEST_TAIL_RE.match(line.strip())
        if not m:
            continue
        for count, word in re.findall(r"(\d+) ([a-z]+)", m.group(1)):
            if word == "skipped":
                total += int(count)
    return total


def parse_log(out: str) -> dict:
    """Everything the gate needs from a runner log."""
    file_skips = [m.group(1) for line in out.splitlines()
                  if (m := SKIP_LINE_RE.match(line.strip()))]
    case_skips = [(m.group(1), m.group(2).strip()) for line in out.splitlines()
                  if (m := CASE_SKIP_RE.match(line.strip()))]
    m = RESULTS_RE.search(out)
    results = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    m = CASES_RE.search(out)
    declared_case_skips = int(m.group(1)) if m else None
    return {
        "file_skips": file_skips,
        "case_skips": case_skips,
        "results": results,
        "declared_case_skips": declared_case_skips,
        "pytest_tail_skips": _pytest_tail_skips(out),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="fail on unexplained skips (files and cases)")
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

    log = parse_log(out)
    n_passed, n_skipped = log["results"]
    failures: list[str] = []

    # --- level 1: whole files -------------------------------------------------
    print(f"skips: {len(log['file_skips'])} file(s) skipped"
          + (f"; runner reports {n_passed} passed, {n_skipped} skipped"
             if n_passed is not None else ""))
    for f in log["file_skips"]:
        why = EXPECTED_SKIPS.get(f)
        print(f"  {f:<34} {'expected: ' + why if why else 'UNEXPLAINED'}")
    unexplained_files = [f for f in log["file_skips"] if f not in EXPECTED_SKIPS]
    if unexplained_files:
        failures.append(f"{len(unexplained_files)} unexplained file skip(s): "
                        f"{', '.join(unexplained_files)}")

    # --- level 2: individual pytest cases ------------------------------------
    itemised = log["case_skips"]
    print(f"case skips: {len(itemised)} itemised")
    unexplained_cases: list[str] = []
    for nodeid, reason in itemised:
        allowed = EXPECTED_CASE_SKIPS.get(nodeid)
        if allowed is None:
            print(f"  {nodeid} :: {reason}  <- UNEXPLAINED")
            unexplained_cases.append(nodeid)
        elif allowed.lower() not in reason.lower():
            print(f"  {nodeid} :: {reason}  <- REASON CHANGED (allowlisted: {allowed})")
            unexplained_cases.append(nodeid)
        else:
            print(f"  {nodeid} :: expected: {allowed}")
    if unexplained_cases:
        failures.append(f"{len(unexplained_cases)} unexplained case skip(s): "
                        f"{', '.join(unexplained_cases)}")

    # --- level 3: the gate refuses to be blind -------------------------------
    # Skipped cases that nothing itemised with a reason. This is what made the old gate
    # green on a log with three internal skips: it never looked below the file level.
    witness = max(log["pytest_tail_skips"], log["declared_case_skips"] or 0)
    if witness > len(itemised):
        failures.append(
            f"the log reports {witness} skipped case(s) but only {len(itemised)} are "
            f"itemised with a reason; run the suite with tools/pytest_case_report.py "
            f"loaded (run_all_tests.py does this) so every skip is named")

    if failures:
        for f in failures:
            print(f"check_skips FAILED: {f}")
        print("      add it to EXPECTED_SKIPS / EXPECTED_CASE_SKIPS with a reason, "
              "or make the test run.")
        return 1

    total = len(log["file_skips"]) + len(itemised)
    print(f"check_skips ok ({total} skip(s), all explained; a skip is still not a pass)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
