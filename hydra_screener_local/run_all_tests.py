"""
One-command runner for all HYDRA test files (contract, golden, integration, logic).

Usage:
    python run_all_tests.py

Exit code 0 if all pass, 1 if any fail.
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
TEST_FILES = [
    "test_spec_compliance.py",
    "test_generate_pine_watchlist.py",
    "test_hybrid_integration.py",
    "test_screener_logic.py",
]

def run_test(test_file: str) -> bool:
    print(f"\n=== {test_file} ===")
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / test_file)],
            capture_output=True,
            text=True,
            timeout=180,
        )
        # Print last 8 lines for visibility
        lines = (result.stdout + result.stderr).strip().splitlines()
        for line in lines[-8:]:
            print(line)
        if result.returncode == 0:
            print(f"[PASS] {test_file}")
            return True
        else:
            print(f"[FAIL] {test_file} (exit {result.returncode})")
            return False
    except Exception as e:
        print(f"[ERROR] running {test_file}: {e}")
        return False

def main():
    print("HYDRA Screener - All Tests Runner")
    print("=" * 40)
    passed = 0
    failed = []
    for t in TEST_FILES:
        if run_test(t):
            passed += 1
        else:
            failed.append(t)

    print("\n" + "=" * 40)
    print(f"RESULTS: {passed}/{len(TEST_FILES)} passed")
    if failed:
        print("Failed:", ", ".join(failed))
        return 1
    print("All tests passed.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
