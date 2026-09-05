"""Audit findings A and B on the output consumers.

A. Zero recommendations must stay zero through the summary JSON, the Pine watchlist and the
   contract validator. No fallback may promote rejected candidates.
B. The full recommended set (0, 1, 22, 28 names, ranks above 20 included) must survive every
   consumer untouched; display caps are explicit and never shrink `recommended_tickers`.

The persistence side of B (`screener.py` used to write `candidates.head(20)`) is covered by
`test_screener_persists_full_recommended_set` through the pure helpers `history_records` and
`executable_top5`; `main()` itself needs the network and is not exercised here.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generate_pine_watchlist import load_recommended_tickers, run_feeder  # noqa: E402
from send_hydra_summary import build_rich_summary  # noqa: E402
from validate_pine_contract import simulate_pine_parser  # noqa: E402


def _history(n_rec, n_total=30, date="20260904"):
    """n_total candidates ranked 1..n_total; the recommended ones are spread across the ranking so
    that some sit beyond rank 20 (the sector cap and the veto do exactly this in production)."""
    rec_ranks = set()
    if n_rec:
        step = max(1, n_total // n_rec)
        rec_ranks = set(range(1, n_total + 1, step))
        rec_ranks = set(sorted(rec_ranks)[:n_rec])
        while len(rec_ranks) < n_rec:                 # top up from the bottom of the ranking
            rec_ranks.add(max(r for r in range(1, n_total + 1) if r not in rec_ranks))
    cands = [{"ticker": f"T{i:02d}", "rank": i, "recommended": i in rec_ranks,
              "composite_score": 1.0 / i, "momentum": 0.1, "passes_strict": False, "special_modes": ""}
             for i in range(1, n_total + 1)]
    return {"date": date, "regime": {"score": 0.6, "type": "BULL", "special_modes": []},
            "pillar_multipliers": {"COMPASS": 1.0}, "meta_rationale": "test", "top_candidates": cands}


def _expected(hist):
    return [c["ticker"] for c in sorted((c for c in hist["top_candidates"] if c["recommended"]), key=lambda c: c["rank"])]


def test_summary_and_watchlist_keep_the_full_recommended_set():
    for n in (0, 1, 22, 28):
        hist = _history(n)
        want = _expected(hist)
        assert len(want) == n
        if n >= 22:
            assert any(int(t[1:]) > 20 for t in want), "fixture must include ranks above 20"

        s = build_rich_summary(hist)
        assert s["recommended_count"] == n
        assert s["recommended_tickers"] == want
        assert [d["ticker"] for d in s["top_details"]] == want
        assert "display_limit" not in s

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / f"{hist['date']}.json"
            p.write_text(json.dumps(hist), encoding="utf-8")
            assert load_recommended_tickers(p) == want
            # display cap is explicit and only ever shortens, never substitutes
            capped = load_recommended_tickers(p, top_n=15)
            assert capped == want[:15]


def test_zero_recommended_never_falls_back():
    hist = _history(0)
    s = build_rich_summary(hist)
    assert s["recommended_count"] == 0 and s["recommended_tickers"] == [] and s["top_details"] == []
    assert s["watchlist_for_pine"] == ""
    with tempfile.TemporaryDirectory() as d:
        hp = Path(d) / "history"; hp.mkdir()
        (hp / "20260904.json").write_text(json.dumps(hist), encoding="utf-8")
        out = Path(d) / "watchlist.txt"
        result = run_feeder(output_path=str(out), history_dir=str(hp), silent=True)
        assert result == "" and out.read_text(encoding="utf-8") == ""
        # a valid summary with an empty list must pass the contract validator (empty != missing)
        sp = Path(d) / "summary.json"
        sp.write_text(json.dumps(s), encoding="utf-8")
        res = simulate_pine_parser(str(sp))
        assert res["errors"] == [], res["errors"]
        assert res["recommended_count"] == 0 and res["recommended_tickers"] == []


def test_display_cap_is_explicit_and_does_not_touch_the_list():
    hist = _history(28)
    s = build_rich_summary(hist, top_n=15)
    assert s["recommended_count"] == 28 and len(s["recommended_tickers"]) == 28
    assert len(s["top_details"]) == 15 and s["display_limit"] == 15


def test_contract_validator_accepts_28_and_flags_mismatch():
    hist = _history(28)
    s = build_rich_summary(hist)
    with tempfile.TemporaryDirectory() as d:
        sp = Path(d) / "summary.json"
        sp.write_text(json.dumps(s), encoding="utf-8")
        assert simulate_pine_parser(str(sp))["errors"] == []
        bad = dict(s); bad["recommended_tickers"] = s["recommended_tickers"][:20]   # a truncating consumer
        sp.write_text(json.dumps(bad), encoding="utf-8")
        assert simulate_pine_parser(str(sp))["errors"], "a shortened list must be caught by the contract check"


def _frame(n_rec, n_total=30):
    import pandas as pd
    hist = _history(n_rec, n_total)
    df = pd.DataFrame(hist["top_candidates"]).sort_values("rank").reset_index(drop=True)
    return df, _expected(hist)


def test_screener_persists_full_recommended_set():
    """Finding B at the source: history/ must carry every recommended row, ranks > 20 included."""
    from screener import history_records, executable_top5
    for n in (0, 1, 22, 28):
        df, want = _frame(n)
        rows = history_records(df)
        persisted_rec = [r["ticker"] for r in rows if r["recommended"]]
        assert persisted_rec == want, (n, persisted_rec)
        assert len(rows) >= max(20, n) and len(rows) <= 30
        # context: the top-20 of the ranking is always there too
        assert [r["ticker"] for r in rows][:20] == [f"T{i:02d}" for i in range(1, 21)]
    # zero recommended -> zero executable positions, even though 30 candidates exist
    df0, _ = _frame(0)
    assert executable_top5(df0) == []
    df28, want28 = _frame(28)
    assert executable_top5(df28) == want28[:5]
    df3, _ = _frame(3)
    assert executable_top5(df3) == [], "fewer than five recommended: no Top5 cycle, no padding with rejected names"
