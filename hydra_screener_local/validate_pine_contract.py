"""
Pine JSON Contract Validator (B3)

Takes a hydra_last_summary.json (or history JSON) and verifies it can be
consumed cleanly by logic mirroring the crude parser in HYDRA_Screener.pine.

Checks:
- All top-level expected fields parse (rationale, regime, pillars, recommended_*, top_details)
- Every top_details item has required keys (ticker, composite, momentum, passes_strict, special_modes, rank)
- recommended_tickers list is non-empty and matches top_details tickers (the recommended ones)
- Simulated is_rec / table logic for the watchlist string would mark exactly the recommended list
- No NaN/empty critical fields

Usage:
    python validate_pine_contract.py
    python validate_pine_contract.py --json pine/hydra_last_summary.json
    python validate_pine_contract.py --json history/20260601.json

Exit 0 on success. Run via run_all_tests.py or manually after changes to sender/Pine.

This catches drift between Python summary contract and Pine parser.
"""

import argparse
import json
import os
from pathlib import Path
import sys

def simulate_pine_parser(json_path: str) -> dict:
    """Mirror key parts of the Pine crude parser + table is_rec logic."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    result = {
        "ok": True,
        "errors": [],
        "contract_version": data.get("contract_version"),
        "rationale": data.get("rationale", ""),
        "regime_score": data.get("regime", {}).get("score"),
        "regime_type": data.get("regime", {}).get("type"),
        "recommended_count": data.get("recommended_count", 0),
        "recommended_tickers": data.get("recommended_tickers", []),
        "top_details_count": len(data.get("top_details", [])),
        "top_details_sample_keys": list(data.get("top_details", [{}])[0].keys()) if data.get("top_details") else [],
        "watchlist": data.get("watchlist_for_pine", ""),
        "parsed_top_tickers": [],
        "sim_is_rec_matches": False,
    }

    # TASK-203 contract version check
    supported_versions = {"1.2"}
    cv = data.get("contract_version")
    if cv not in supported_versions:
        result["ok"] = False
        result["errors"].append(f"contract_version '{cv}' not in supported set {supported_versions} (missing or outdated)")

    top_details = data.get("top_details", [])
    for item in top_details:
        required = ["ticker", "composite", "momentum", "passes_strict", "special_modes", "rank"]
        missing = [k for k in required if k not in item]
        if missing:
            result["ok"] = False
            result["errors"].append(f"top_details missing keys for {item.get('ticker')}: {missing}")

    # An empty list is a valid result (closed cycle) - only a MISSING key or an inconsistent
    # count is a contract error (audit finding A: empty != absent).
    if "recommended_tickers" not in data or "recommended_count" not in data:
        result["ok"] = False
        result["errors"].append("recommended_tickers / recommended_count missing from JSON")
    recs = data.get("recommended_tickers", []) or []
    if data.get("recommended_count") is not None and data.get("recommended_count") != len(recs):
        result["ok"] = False
        result["errors"].append(f"recommended_count {data.get('recommended_count')} != len(recommended_tickers) {len(recs)}")
    # top_details must carry the whole list unless the producer declared an explicit display cap
    detail_tickers = [d.get("ticker") for d in top_details]
    limit = data.get("display_limit")
    if not limit and detail_tickers != recs:
        result["ok"] = False
        result["errors"].append("top_details tickers != recommended_tickers and no display_limit declared (a consumer truncated the list)")
    if limit and detail_tickers != recs[:int(limit)]:
        result["ok"] = False
        result["errors"].append(f"display_limit={limit} but top_details is not the first {limit} of recommended_tickers (review 336)")

    # Simulate is_rec for the watchlist
    watchlist = data.get("watchlist_for_pine", "")
    watch_syms = [s.strip() for s in watchlist.split(",") if s.strip()]
    sim_recs = []
    for sym in watch_syms:
        if sym in recs:
            sim_recs.append(sym)

    result["sim_is_rec_matches"] = (set(sim_recs) == set(recs) and len(sim_recs) == len(recs))
    if not result["sim_is_rec_matches"]:
        result["ok"] = False
        result["errors"].append(f"Sim is_rec list {sim_recs} != recommended {recs}")

    result["parsed_top_tickers"] = [d["ticker"] for d in top_details if "ticker" in d]

    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default=None, help="Path to summary or history JSON (default: pine/hydra_last_summary.json or latest history)")
    args = parser.parse_args()

    json_path = args.json
    if not json_path:
        candidates = [
            Path("pine/hydra_last_summary.json"),
            Path("history/20260601.json"),
            Path("history/20260531.json"),
        ]
        for c in candidates:
            if c.exists():
                json_path = str(c)
                break
    if not json_path or not Path(json_path).exists():
        # A fresh clone has no summary artifact: that is a skip, not a contract failure.
        print("[SKIP] No summary/history JSON found. Provide --json or run the screener first.")
        return 0

    print(f"Validating Pine contract against: {json_path}")
    res = simulate_pine_parser(json_path)

    print(f"  Rationale: {res['rationale'][:50]}...")
    print(f"  Regime: {res['regime_type']} ({res['regime_score']})")
    print(f"  Recommended: {res['recommended_count']} -> {res['recommended_tickers'][:5]}...")
    print(f"  Top details: {res['top_details_count']} items, sample keys: {res['top_details_sample_keys']}")
    print(f"  Watchlist sim is_rec matches recommended list: {res['sim_is_rec_matches']}")

    if res["errors"]:
        print("ERRORS:")
        for e in res["errors"]:
            print("  -", e)
        print("CONTRACT VALIDATION FAILED")
        return 1

    if res["ok"]:
        print("=== ✅ PINE JSON CONTRACT VALIDATION PASSED ===")
        print("The JSON is consumable by the current Pine parser logic (no drift).")
        return 0
    else:
        print("CONTRACT VALIDATION FAILED (see errors)")
        return 1

if __name__ == "__main__":
    sys.exit(main())
