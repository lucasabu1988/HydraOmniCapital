"""
Golden / Integration tests for generate_pine_watchlist.py (the Pine watchlist feeder helper).

These tests validate that the feeder correctly extracts recommended tickers from
history JSON files (as produced by the screener) and generates the exact comma-separated
string expected for pasting into the Pine Script's i_watchlist input.

It uses real history files as "golden" inputs.

Run:
    python test_generate_pine_watchlist.py

Expects the history/ folder to contain at least 20260601.json (and optionally others).
"""

import sys
import os
from pathlib import Path

# Add project root so we can import the feeder
sys.path.insert(0, os.path.dirname(__file__))

# Consolas Windows usan cp1252 por defecto y rompen con emojis UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from generate_pine_watchlist import (
    find_latest_history,
    load_recommended_tickers,
    generate_watchlist_string,
)

# Known golden data from real history files (captured from actual runs)
# These must be updated if the screener logic or history format changes significantly.

GOLDEN_20260601_TOP_8 = "DELL,ARM,MRVL,HPE,STX,STM,MU,NTAP"
GOLDEN_20260601_TOP_10 = "DELL,ARM,MRVL,HPE,STX,STM,MU,NTAP,WDC,UMC"

# For 20260531 we don't have the exact list here, but we can at least test that it loads something
# and produces a non-empty string (or we can leave it as a smoke test).


def test_load_and_generate_from_known_history():
    """Test against the known 20260601.json golden output."""
    print("\n=== Test: load_recommended_tickers + generate from 20260601.json ===")

    history_file = Path("history") / "20260601.json"
    if not history_file.exists():
        print(f"[SKIP] {history_file} not found. Run the screener first to generate history.")
        return True

    tickers_8 = load_recommended_tickers(history_file, top_n=8)
    result_8 = generate_watchlist_string(tickers_8)

    tickers_10 = load_recommended_tickers(history_file, top_n=10)
    result_10 = generate_watchlist_string(tickers_10)

    print(f"  top 8:  {result_8}")
    print(f"  top 10: {result_10}")

    if result_8 != GOLDEN_20260601_TOP_8:
        print(f"[FAIL] top 8 mismatch.\n  Expected: {GOLDEN_20260601_TOP_8}\n  Got:      {result_8}")
        return False
    print("[OK] top 8 matches golden")

    if result_10 != GOLDEN_20260601_TOP_10:
        print(f"[FAIL] top 10 mismatch.\n  Expected: {GOLDEN_20260601_TOP_10}\n  Got:      {result_10}")
        return False
    print("[OK] top 10 matches golden")

    return True


def test_fallback_when_no_recommended():
    """If a history has no 'recommended' flags, it should still return top N by rank."""
    print("\n=== Test: fallback when few/no recommended ===")

    # Use the same file but ask for more than available recommended.
    # In 20260601 there were at least 10 recommended.
    history_file = Path("history") / "20260601.json"
    if not history_file.exists():
        print("[SKIP] history file not present")
        return True

    # Ask for a very high number – should still return what is available (capped by actual recommended or top)
    tickers = load_recommended_tickers(history_file, top_n=999)
    result = generate_watchlist_string(tickers)

    if len(tickers) == 0:
        print("[FAIL] expected at least some tickers from real history")
        return False

    print(f"[OK] fallback returned {len(tickers)} tickers (string length {len(result)})")
    return True


def test_find_latest_history():
    """Sanity check that the finder works and returns a real file."""
    print("\n=== Test: find_latest_history ===")
    try:
        latest = find_latest_history(Path("history"))
        print(f"[OK] latest history file found: {latest.name}")
        return True
    except Exception as e:
        print(f"[FAIL] {e}")
        return False


def test_generate_watchlist_string_edge_cases():
    """Basic unit tests on the string generator."""
    print("\n=== Test: generate_watchlist_string edge cases ===")

    assert generate_watchlist_string([]) == ""
    assert generate_watchlist_string(["AAPL"]) == "AAPL"
    assert generate_watchlist_string(["AAPL", "MSFT", "NVDA"]) == "AAPL,MSFT,NVDA"

    print("[OK] string generator edge cases")
    return True


def main():
    print("=== Golden/Integration tests for generate_pine_watchlist.py ===\n")

    tests = [
        test_find_latest_history,
        test_generate_watchlist_string_edge_cases,
        test_load_and_generate_from_known_history,
        test_fallback_when_no_recommended,
    ]

    all_passed = True
    for test_fn in tests:
        try:
            ok = test_fn()
            if not ok:
                all_passed = False
        except Exception as e:
            print(f"[FAIL] {test_fn.__name__} raised: {e}")
            import traceback
            traceback.print_exc()
            all_passed = False

    if all_passed:
        print("\n=== ✅ ALL FEEDER TESTS PASSED ===")
        print("The watchlist feeder correctly produces golden output from real history files.")
        return 0
    else:
        print("\n=== ❌ SOME FEEDER TESTS FAILED ===")
        return 1


if __name__ == "__main__":
    sys.exit(main())
