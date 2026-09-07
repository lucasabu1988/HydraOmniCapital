"""
One-command runner for all HYDRA test files (contract, golden, integration, logic).

Usage:
    python run_all_tests.py
    python run_all_tests.py --fast          # skip heavy/long tests
    python run_all_tests.py --verbose       # show more output per test

Exit code 0 if all pass, 1 if any fail.

Accounting is at two levels (ASTRA-04). A *file* passes, skips or fails; inside a file
run through pytest, individual *cases* also pass, skip or fail. The runner used to
report only the first level: it looked for a whole-file `[SKIP]` line and never read
pytest's own `N passed, M skipped` summary, so a log could read "64 passed, 0 skipped"
while three pytest cases were skipping inside files reported as [PASS]. Every pytest
child now loads `tools/pytest_case_report.py`, which prints one `[CASE-SKIP] <id> ::
<reason>` line per skipped case plus a `[CASE-COUNTS]` tally; the runner relays both and
totals them in a `CASES:` line. `tools/check_skips.py` gates on those lines.
"""

import argparse
import glob
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent

# Captured test output is UTF-8, but this runner's own console may be cp1252
# (default Windows console). Printing a char like the check mark then raises
# UnicodeEncodeError, which used to be caught below and misreported as a test
# failure. Degrade unencodable chars instead of blowing up.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - non-standard stream
        pass

# Core tests that should always run
CORE_TESTS = [
    "test_spec_compliance.py",
    "test_generate_pine_watchlist.py",
    "test_hybrid_integration.py",
]

# Additional / moved tests (include via auto-discovery or explicit)
ADDITIONAL_TESTS = [
    "experiments/test_screener_logic.py",
    "validate_pine_contract.py",  # B3 contract validator for Pine parser vs summary JSON
]

def discover_tests() -> list[str]:
    """Auto-discover test_*.py in root and experiments/ (excluding __pycache__ etc)."""
    found = []
    for pattern in ["test_*.py", "experiments/test_*.py"]:
        for f in glob.glob(pattern):
            if f not in found and not f.startswith("__"):
                found.append(f.replace("\\", "/"))
    # Files whose names do not match the glob (the Pine contract validator) used to be listed
    # in ADDITIONAL_TESTS but never discovered -- a check that silently never ran (audit, step 4).
    for t in ADDITIONAL_TESTS:
        if t not in found and (ROOT / t).exists():
            found.append(t)
    # Ensure order: core first, then additional
    ordered = []
    for t in CORE_TESTS + ADDITIONAL_TESTS:
        if t in found:
            ordered.append(t)
            found.remove(t)
    ordered.extend(sorted(found))
    return ordered

#: A real entry-point guard, not the mere mention of `__main__`. The substring test this
#: replaces classified any file that so much as quoted the word as a script: it sent
#: test_console_encoding.py (which greps other files for `if __name__ == "__main__"`)
#: down the script path, where its single assertion never ran and the file was reported
#: [PASS] in 0.09s. Found while porting ASTRA-04.
MAIN_GUARD_RE = re.compile(r"^\s*if\s+__name__\s*==\s*[\"']__main__[\"']", re.MULTILINE)


def _invocation(test_file: str) -> tuple[list[str], str]:
    """How to run this file, and why.

    Files here come in two shapes: scripts that assert inside a `__main__` block, and
    pytest-style modules that only define `test_*` functions. Running the second shape
    as a script executes nothing and exits 0, which the runner used to report as [PASS] --
    a green light for assertions that never ran. Route those through pytest instead.
    """
    path = ROOT / test_file
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [sys.executable, str(path)], "script"
    has_main = MAIN_GUARD_RE.search(src) is not None
    has_tests = re.search(r"^def test_", src, re.MULTILINE) is not None
    if has_tests and not has_main:
        # -p tools.pytest_case_report: per-case skip accounting (ASTRA-04). Needs ROOT on
        # PYTHONPATH, which run_test sets for the child.
        return [sys.executable, "-m", "pytest", str(path), "-q",
                "-p", "tools.pytest_case_report"], "pytest"
    return [sys.executable, str(path)], "script"


CASE_SKIP_RE = re.compile(r"^\[CASE-SKIP\]\s+(\S+)\s*::\s*(.*)$")
CASE_COUNTS_RE = re.compile(r"^\[CASE-COUNTS\]\s+(.*)$")
#: pytest's own tail summary ("11 passed, 2 skipped in 1.16s"), read as an independent
#: witness of the case counts. Anchored on the whole `<counts> in <seconds>` shape so a
#: test that merely prints the word "skipped" cannot be mistaken for it.
PYTEST_TAIL_RE = re.compile(r"^((?:\d+ [a-z]+(?:, )?)+) in \d+(?:\.\d+)?s")


def _pytest_tail_skips(output: str) -> int | None:
    """How many cases pytest's own tail summary says it skipped, or None if absent."""
    found = None
    for line in output.splitlines():
        m = PYTEST_TAIL_RE.match(line.strip())
        if not m:
            continue
        for count, word in re.findall(r"(\d+) ([a-z]+)", m.group(1)):
            if word == "skipped":
                found = max(found or 0, int(count))
    return found


def _parse_case_report(test_file: str, output: str) -> dict | None:
    """Case-level counts and skips from a pytest child, or None if it reported none.

    Node ids are rewritten to `<test_file>::<case>` so the id an allowlist is keyed by
    does not depend on pytest's rootdir resolution in the child.
    """
    counts: dict[str, int] | None = None
    skips: list[tuple[str, str]] = []
    for line in output.splitlines():
        line = line.strip()
        if (m := CASE_SKIP_RE.match(line)):
            nodeid, reason = m.group(1), m.group(2).strip()
            case = nodeid.split("::", 1)[1] if "::" in nodeid else nodeid
            skips.append((f"{test_file}::{case}", reason or "no reason given"))
        elif (m := CASE_COUNTS_RE.match(line)):
            counts = {}
            for field in m.group(1).split():
                key, _, value = field.partition("=")
                try:
                    counts[key] = int(value)
                except ValueError:
                    continue
    if counts is None:
        return None
    return {"counts": counts, "skips": skips}


def _display_output(output: str) -> str:
    """The child's output without the machine-readable case lines (printed separately)."""
    return "\n".join(ln for ln in output.splitlines()
                     if not (CASE_SKIP_RE.match(ln.strip()) or CASE_COUNTS_RE.match(ln.strip())))


def run_test(test_file: str, verbose: bool = False, extra_env: dict | None = None) -> tuple[str, float, dict | None]:
    cmd, how = _invocation(test_file)
    suffix = "" if how == "script" else f"  [via {how}]"
    print(f"\n=== {test_file} ==={suffix}")
    start = time.perf_counter()
    env = os.environ.copy()
    if how == "pytest":
        # The child imports tools.pytest_case_report before collection, i.e. before pytest
        # puts the rootdir on sys.path, so pass it explicitly.
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = str(ROOT) + (os.pathsep + existing if existing else "")
    if extra_env:
        env.update(extra_env)
    # Only the subprocess call is guarded: a failure while printing the report
    # is a runner bug, not a test failure, and must not be swallowed here.
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            env=env,
        )
    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        print(f"[TIMEOUT] {test_file} after {duration:.1f}s")
        return "fail", duration, None
    except OSError as e:
        duration = time.perf_counter() - start
        print(f"[ERROR] running {test_file}: {e} ({duration:.2f}s)")
        return "fail", duration, None

    duration = time.perf_counter() - start
    output = (result.stdout + result.stderr).strip()
    cases = _parse_case_report(test_file, output) if how == "pytest" else None
    if verbose:
        print(_display_output(output))
    else:
        lines = _display_output(output).splitlines()
        for line in lines[-6:]:
            print(line)

    case_problem = None
    if how == "pytest":
        if cases is None:
            # The plugin did not report. Without it the runner is blind to case-level
            # skips again, which is the whole defect -- fail loudly instead. A child that
            # already failed reports through the normal path, with its own exit code.
            if result.returncode == 0:
                case_problem = "no [CASE-COUNTS] from tools.pytest_case_report"
        else:
            c = cases["counts"]
            print(f"[CASES] {test_file} passed={c.get('passed', 0)} "
                  f"skipped={c.get('skipped', 0)} failed={c.get('failed', 0)} "
                  f"errors={c.get('errors', 0)} xfailed={c.get('xfailed', 0)}")
            for nodeid, reason in cases["skips"]:
                print(f"[CASE-SKIP] {nodeid} :: {reason}")
            # Cross-check against pytest's own tail summary: if pytest counted more
            # skips than the plugin listed, the accounting is incomplete.
            tail = _pytest_tail_skips(output)
            if tail is not None and tail > c.get("skipped", 0):
                case_problem = (f"pytest reported {tail} skipped, plugin listed "
                                f"{c.get('skipped', 0)}")

    if case_problem:
        print(f"[FAIL] {test_file} (case accounting: {case_problem})")
        return "fail", duration, cases

    # Whole-file skip: a [SKIP] line and no overall-pass banner (a file may skip one
    # sub-check and still pass). Hybrid integration is the case this exists for.
    skipped = (
        result.returncode == 0
        and re.search(r"^\[SKIP\]", output, re.M)
        and not re.search(r"ALL .+ PASSED", output)
    )
    if skipped:
        print(f"[SKIP] {test_file} ({duration:.2f}s)")
        return "skip", duration, cases
    if result.returncode == 0:
        print(f"[PASS] {test_file} ({duration:.2f}s)")
        return "pass", duration, cases
    print(f"[FAIL] {test_file} (exit {result.returncode}, {duration:.2f}s)")
    return "fail", duration, cases

def main():
    parser = argparse.ArgumentParser(description="HYDRA Screener - All Tests Runner")
    parser.add_argument("--fast", action="store_true", help="Skip heavy/long tests (contract tests only)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show full output for each test")
    parser.add_argument("--list", action="store_true", help="Just list discovered tests and exit")
    parser.add_argument("--cov", action="store_true",
                        help="report-only coverage over core, data, utils, sleeves (no floor)")
    parser.add_argument("--strict-console", action="store_true",
                        help="run children with PYTHONIOENCODING=cp1252:strict (Windows console)")
    args = parser.parse_args()

    test_files = discover_tests()
    if args.fast:
        test_files = [t for t in test_files if t in CORE_TESTS]

    if args.list:
        print("Discovered tests:")
        for t in test_files:
            print(f"  - {t}")
        return 0

    print("HYDRA Screener - All Tests Runner")
    print("=" * 50)
    if args.fast:
        print("(FAST mode: core contract tests only)")
    extra_env = {"PYTHONIOENCODING": "cp1252:strict"} if args.strict_console else None
    if args.strict_console:
        print("(strict-console: PYTHONIOENCODING=cp1252:strict)")
    print()

    passed = 0
    skipped = 0
    failed = []
    total_time = 0.0
    case_totals = {"passed": 0, "skipped": 0, "failed": 0, "errors": 0, "xfailed": 0}
    case_skips: list[tuple[str, str]] = []
    pytest_files = 0
    start_all = time.perf_counter()

    for t in test_files:
        status, dur, cases = run_test(t, verbose=args.verbose, extra_env=extra_env)
        total_time += dur
        if cases is not None:
            pytest_files += 1
            for key in case_totals:
                case_totals[key] += cases["counts"].get(key, 0)
            case_skips.extend(cases["skips"])
        if status == "pass":
            passed += 1
        elif status == "skip":
            skipped += 1
        else:
            failed.append(t)

    elapsed = time.perf_counter() - start_all
    print("\n" + "=" * 50)
    print(f"RESULTS: {passed} passed, {skipped} skipped in {elapsed:.2f}s "
          f"(tests time: {total_time:.2f}s)")
    # Second level of accounting (ASTRA-04): files can all pass while cases inside them
    # skip. Script-style files assert in a __main__ block and have no case counts.
    script_files = len(test_files) - pytest_files
    print(f"CASES: {case_totals['passed']} passed, {case_totals['skipped']} skipped, "
          f"{case_totals['failed']} failed, {case_totals['errors']} errors, "
          f"{case_totals['xfailed']} xfailed over {pytest_files} pytest file(s) "
          f"({script_files} script file(s) report file level only)")
    print(f"CASE-SKIPS: {len(case_skips)}")
    for nodeid, reason in case_skips:
        print(f"  {nodeid} :: {reason}")
    if failed:
        print("Failed tests:")
        for f in failed:
            print(f"  - {f}")
        return 1
    if skipped or case_skips:
        print("No failures (skips are not passes).")
    else:
        print("All tests passed!")

    _print_ruff_summary()

    if args.cov:
        cov_rc = _run_coverage()
        if cov_rc != 0 and not failed:
            return cov_rc
    return 0


def _print_ruff_summary() -> None:
    """Report-only ruff line; never fails the suite (TASK-372)."""
    tests = sorted(p.name for p in ROOT.glob("test_*.py"))
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--config", str(ROOT / "ruff.toml"),
             "core", "data", "utils", "sleeves",
             "portfolio_v9.py", "daily.py", "dashboard_v9.py", "preflight.py",
             "reconcile.py", "confirm_fills.py", "journal.py", "store_cli.py",
             "evidence_review.py", "warm_sectors.py", "send_hydra_summary.py",
             "console_dashboard.py", "snapshot_universe.py", "verify_state.py",
             "runlog_cli.py", *tests],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        print("ruff: not installed (pip install -r requirements-dev.txt)")
        return
    out = (result.stdout or "") + (result.stderr or "")
    summary = [ln for ln in out.splitlines() if "Found" in ln or "All checks passed" in ln]
    line = summary[-1] if summary else ("ruff exit " + str(result.returncode))
    print("ruff (report-only):", line)


def _run_coverage() -> int:
    """Report-only coverage over core/ data/ utils/ sleeves/. No fail-under floor."""
    print("\n" + "=" * 50)
    print("COVERAGE (report-only; floor is Claude's call)")
    try:
        import pytest_cov  # noqa: F401
    except ImportError:
        print("pytest-cov not installed. pip install -r requirements-dev.txt")
        return 1
    xml_path = ROOT / "coverage.xml"
    pytest_files = []
    for t in discover_tests():
        _cmd, how = _invocation(t)
        if how == "pytest":
            pytest_files.append(str(ROOT / t))
    cmd = [
        sys.executable, "-m", "pytest",
        "--cov=core", "--cov=data", "--cov=utils", "--cov=sleeves",
        "--cov-report=term",
        f"--cov-report=xml:{xml_path}",
        "-q", "--tb=no",
        *pytest_files,
    ]
    print("coverage over", len(pytest_files), "pytest files")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if xml_path.exists():
        print(f"coverage XML: {xml_path}")
    return 0 if result.returncode == 0 else result.returncode

if __name__ == "__main__":
    sys.exit(main())
