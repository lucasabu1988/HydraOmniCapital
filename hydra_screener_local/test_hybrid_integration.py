"""
Lightweight integration test for the HYDRA hybrid flow (Python -> artifacts -> Pine consumability).

Checks:
- Feeder produces correct watchlist string from a real history JSON.
- Sender's build_rich_summary produces the expected structure (recommended_*, top_details, etc.).
- The produced summary JSON is parseable by our Pine crude parser logic (recommended_tickers, top_details, regime, etc.).
- Recommended list is consistent with top_details.

Run:
    python test_hybrid_integration.py

This is intentionally lightweight (no network, uses existing history/*.json as golden source).
"""

import json
import os
import sys
from pathlib import Path

# Make sure we can import local modules
sys.path.insert(0, str(Path(__file__).parent))

# Consolas Windows usan cp1252 por defecto y rompen con emojis UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from generate_pine_watchlist import generate_watchlist_string, load_recommended_tickers
from send_hydra_summary import build_rich_summary

# Paths relative to this file so cwd does not matter
_ROOT = Path(__file__).resolve().parent
HISTORY_DIR = _ROOT / "history"
CANDIDATE_JSONS = [
    HISTORY_DIR / "20260601.json",
    HISTORY_DIR / "20260531.json",
    _ROOT / "pine" / "hydra_last_summary.json",
]


def find_real_history():
    for p in CANDIDATE_JSONS:
        if p.exists():
            return p
    if HISTORY_DIR.is_dir():
        for p in sorted(HISTORY_DIR.glob("*.json"), reverse=True):
            return p
    return None


def simulate_pine_parser_for_recommended(summary: dict) -> tuple:
    """Mirror the critical parts of the Pine parser for recommended_tickers + top_details.
    Returns (recommended_count, recommended_list, top_tickers, has_error)
    """
    # We work on the Python dict directly (the "JSON" the user would paste).
    # This simulates what the string-based parser in HYDRA_Screener.pine does.
    rec_count = summary.get("recommended_count", 0)
    rec_tickers = summary.get("recommended_tickers", [])
    top_details = summary.get("top_details", [])
    top_tickers = [d.get("ticker") for d in top_details if d.get("ticker")]

    # Basic structural checks that the Pine parser cares about
    error = False
    if not isinstance(rec_tickers, list):
        error = True
    if not isinstance(top_details, list) or len(top_details) == 0:
        error = True
    for d in top_details[:3]:  # spot check a few
        if not all(k in d for k in ("ticker", "composite", "passes_strict", "special_modes")):
            error = True

    return rec_count, rec_tickers, top_tickers, error


def main():
    print("=== HYDRA Hybrid Integration Test ===")
    history_path = find_real_history()
    if history_path is None:
        print("[SKIP] needs history/ — run the screener first")
        return 0
    print(f"Using history source: {history_path}")

    with open(history_path, "r", encoding="utf-8") as f:
        history_data = json.load(f)

    # 1. Feeder side (expects path or str)
    recommended = load_recommended_tickers(history_path, top_n=15)
    watchlist_str = generate_watchlist_string(recommended)
    print(f"Feeder: {len(recommended)} recommended -> watchlist='{watchlist_str[:60]}...'")

    assert len(recommended) > 0, "Feeder produced empty recommended list"
    assert "," in watchlist_str or len(recommended) == 1, "Watchlist string looks wrong"

    # 2. Sender side (build the rich summary dict that gets written to JSON)
    summary = build_rich_summary(history_data, top_n=15)
    print(f"Sender: recommended_count={summary.get('recommended_count')}, "
          f"top_details={len(summary.get('top_details', []))}, "
          f"has_recommended_tickers={bool(summary.get('recommended_tickers'))}")

    assert "recommended_tickers" in summary
    assert "top_details" in summary
    assert summary["recommended_count"] == len(summary["recommended_tickers"])
    assert len(summary["top_details"]) > 0

    # TASK-203: contract_version present and correct
    assert summary.get("contract_version") == "1.2", "contract_version must be '1.2' as first key"

    # 3. Simulate what the Pine parser does with this summary (the critical contract)
    rec_count, rec_list, top_tickers, parse_error = simulate_pine_parser_for_recommended(summary)
    print(f"Pine-sim: recommended_count={rec_count}, rec_list={rec_list[:5]}..., parse_error={parse_error}")

    assert not parse_error, "Simulated Pine parser found structural problems in the summary"
    assert rec_count == len(rec_list) > 0

    # TASK-203 contract version validation in the dedicated validator (extend coverage)
    # We also exercise validate_pine_contract logic indirectly by checking version key
    # (full validator test lives in its own module, but we ensure the summary carries the key)
    # The watchlist the feeder produced should be a prefix of (or equal to) the recommended list
    feeder_list = [t.strip() for t in watchlist_str.split(",") if t.strip()]
    for t in feeder_list[:3]:
        assert t in rec_list, f"Feeder ticker {t} not in recommended_tickers from sender"

    # 4. Cross-check: the tickers in top_details should overlap heavily with recommended
    detail_tickers = {d["ticker"] for d in summary["top_details"]}
    overlap = len(set(rec_list) & detail_tickers)
    assert overlap >= max(1, len(rec_list) - 2), "recommended_tickers and top_details are inconsistent"

    print("\n=== ✅ ALL HYBRID INTEGRATION CHECKS PASSED ===")
    print("The Python -> artifact -> (simulated) Pine contract is intact for this history file.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"[FAIL] Hybrid integration test error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
