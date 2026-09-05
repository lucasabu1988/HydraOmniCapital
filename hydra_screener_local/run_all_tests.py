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
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent

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
    # Ensure order: core first, then additional
    ordered = []
    for t in CORE_TESTS + ADDITIONAL_TESTS:
        if t in found:
            ordered.append(t)
            found.remove(t)
    ordered.extend(sorted(found))
    return ordered

def run_test(test_file: str, verbose: bool = False) -> tuple[bool, float]:
    print(f"\n=== {test_file} ===")
    start = time.perf_counter()
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / test_file)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        duration = time.perf_counter() - start
        output = (result.stdout + result.stderr).strip()
        if verbose:
            print(output)
        else:
            # Print last 6 lines for visibility
            lines = output.splitlines()
            for line in lines[-6:]:
                print(line)
        if result.returncode == 0:
            print(f"[PASS] {test_file} ({duration:.2f}s)")
            return True, duration
        else:
            print(f"[FAIL] {test_file} (exit {result.returncode}, {duration:.2f}s)")
            return False, duration
    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        print(f"[TIMEOUT] {test_file} after {duration:.1f}s")
        return False, duration
    except Exception as e:
        duration = time.perf_counter() - start
        print(f"[ERROR] running {test_file}: {e} ({duration:.2f}s)")
        return False, duration

def main():
    parser = argparse.ArgumentParser(description="HYDRA Screener - All Tests Runner")
    parser.add_argument("--fast", action="store_true", help="Skip heavy/long tests (contract tests only)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show full output for each test")
    parser.add_argument("--list", action="store_true", help="Just list discovered tests and exit")
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
    print()

    passed = 0
    failed = []
    total_time = 0.0
    start_all = time.perf_counter()

    for t in test_files:
        ok, dur = run_test(t, verbose=args.verbose)
        total_time += dur
        if ok:
            passed += 1
        else:
            failed.append(t)

    elapsed = time.perf_counter() - start_all
    print("\n" + "=" * 50)
    print(f"RESULTS: {passed}/{len(test_files)} passed in {elapsed:.2f}s (tests time: {total_time:.2f}s)")
    if failed:
        print("Failed tests:")
        for f in failed:
            print(f"  - {f}")
        return 1
    print("All tests passed!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
