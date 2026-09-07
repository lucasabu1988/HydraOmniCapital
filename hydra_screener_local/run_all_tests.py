"""
One-command runner for all HYDRA test files (contract, golden, integration, logic).

Usage:
    python run_all_tests.py
    python run_all_tests.py --fast          # skip heavy/long tests
    python run_all_tests.py --verbose       # show more output per test

Exit code 0 if all pass, 1 if any fail.
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
    has_main = "__main__" in src
    has_tests = re.search(r"^def test_", src, re.MULTILINE) is not None
    if has_tests and not has_main:
        return [sys.executable, "-m", "pytest", str(path), "-q"], "pytest"
    return [sys.executable, str(path)], "script"


def run_test(test_file: str, verbose: bool = False, extra_env: dict | None = None) -> tuple[str, float]:
    cmd, how = _invocation(test_file)
    suffix = "" if how == "script" else f"  [via {how}]"
    print(f"\n=== {test_file} ==={suffix}")
    start = time.perf_counter()
    env = os.environ.copy()
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
        return "fail", duration
    except OSError as e:
        duration = time.perf_counter() - start
        print(f"[ERROR] running {test_file}: {e} ({duration:.2f}s)")
        return "fail", duration

    duration = time.perf_counter() - start
    output = (result.stdout + result.stderr).strip()
    if verbose:
        print(output)
    else:
        lines = output.splitlines()
        for line in lines[-6:]:
            print(line)
    # Whole-file skip: a [SKIP] line and no overall-pass banner (a file may skip one
    # sub-check and still pass). Hybrid integration is the case this exists for.
    skipped = (
        result.returncode == 0
        and re.search(r"^\[SKIP\]", output, re.M)
        and not re.search(r"ALL .+ PASSED", output)
    )
    if skipped:
        print(f"[SKIP] {test_file} ({duration:.2f}s)")
        return "skip", duration
    if result.returncode == 0:
        print(f"[PASS] {test_file} ({duration:.2f}s)")
        return "pass", duration
    print(f"[FAIL] {test_file} (exit {result.returncode}, {duration:.2f}s)")
    return "fail", duration

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
    start_all = time.perf_counter()

    for t in test_files:
        status, dur = run_test(t, verbose=args.verbose, extra_env=extra_env)
        total_time += dur
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
    if failed:
        print("Failed tests:")
        for f in failed:
            print(f"  - {f}")
        return 1
    if skipped:
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
             "runlog_cli.py", "reprint_sheet.py", *tests],
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
