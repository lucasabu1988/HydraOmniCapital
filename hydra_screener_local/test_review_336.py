"""TASK-336 independent review of commit 839e375 (audit findings A, B, C).

Review, do not re-implement. Each test is a counterexample: if the fix holds the
assertion passes; if it breaks, the test fails and that failure IS the finding.
Do not edit the reviewed modules to make these green.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from generate_pine_watchlist import load_recommended_tickers, run_feeder, main as feeder_main  # noqa: E402
from send_hydra_summary import build_rich_summary  # noqa: E402
from validate_pine_contract import simulate_pine_parser  # noqa: E402
from screener import history_records, executable_top5  # noqa: E402
from core.tracking import (  # noqa: E402
    compute_forward_returns_for_run,
    needs_update,
    TRACKING_SCHEMA_VERSION,
)


def _history(n_rec, n_total=30, date="20260904", tie_rank=False):
    rec_ranks = set()
    if n_rec:
        step = max(1, n_total // n_rec)
        rec_ranks = set(range(1, n_total + 1, step))
        rec_ranks = set(sorted(rec_ranks)[:n_rec])
        while len(rec_ranks) < n_rec:
            rec_ranks.add(max(r for r in range(1, n_total + 1) if r not in rec_ranks))
    cands = []
    for i in range(1, n_total + 1):
        rank = 1 if tie_rank and i in rec_ranks else i
        cands.append({
            "ticker": f"T{i:02d}",
            "rank": rank,
            "recommended": i in rec_ranks,
            "composite_score": 1.0 / i,
            "momentum": 0.1,
            "passes_strict": False,
            "special_modes": "",
        })
    return {
        "date": date,
        "regime": {"score": 0.6, "type": "BULL", "special_modes": []},
        "pillar_multipliers": {"COMPASS": 1.0},
        "meta_rationale": "test",
        "top_candidates": cands,
    }


def _expected(hist):
    return [
        c["ticker"]
        for c in sorted(
            (c for c in hist["top_candidates"] if c.get("recommended") is True),
            key=lambda c: c.get("rank", 10**6),
        )
    ]


def _frame(hist):
    return pd.DataFrame(hist["top_candidates"]).sort_values("rank").reset_index(drop=True)


# ---------------------------------------------------------------------------
# A — zero recommendations stay zero; no fallback to rejected names
# ---------------------------------------------------------------------------

def test_A_missing_recommended_key_does_not_promote_rejected():
    """Counterexample: every row lacks the `recommended` key (not False — absent)."""
    hist = _history(0)
    for c in hist["top_candidates"]:
        del c["recommended"]
    s = build_rich_summary(hist)
    assert s["recommended_count"] == 0
    assert s["recommended_tickers"] == []
    assert s["top_details"] == []
    assert s["watchlist_for_pine"] == ""
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "20260904.json"
        p.write_text(json.dumps(hist), encoding="utf-8")
        assert load_recommended_tickers(p) == []
        assert load_recommended_tickers(p, top_n=15) == []
        hp = Path(d) / "history"
        hp.mkdir()
        (hp / "20260904.json").write_text(json.dumps(hist), encoding="utf-8")
        out = Path(d) / "watchlist.txt"
        assert run_feeder(output_path=str(out), history_dir=str(hp), silent=True) == ""
        assert out.read_text(encoding="utf-8") == ""
        sp = Path(d) / "summary.json"
        sp.write_text(json.dumps(s), encoding="utf-8")
        res = simulate_pine_parser(str(sp))
        assert res["errors"] == [], res["errors"]


def test_A_missing_recommended_column_does_not_pad_top5_or_history():
    df = pd.DataFrame(
        [{"ticker": f"T{i:02d}", "rank": i, "composite_score": 1.0 / i} for i in range(1, 31)]
    )
    assert executable_top5(df) == []
    rows = history_records(df)
    assert all(not r.get("recommended") for r in rows)


def test_A_high_rank_rejects_never_become_the_watchlist():
    hist = _history(0)
    assert all(c["recommended"] is False for c in hist["top_candidates"])
    s = build_rich_summary(hist)
    assert s["recommended_tickers"] == []
    assert executable_top5(_frame(hist)) == []


# ---------------------------------------------------------------------------
# B — full recommended set survives; display caps are explicit
# ---------------------------------------------------------------------------

def test_B_twenty_eight_with_rank_ties_all_survive():
    """Counterexample: 28 recommended names, every one sharing rank 1."""
    hist = _history(28, tie_rank=True)
    recs = [c for c in hist["top_candidates"] if c["recommended"] is True]
    assert len(recs) == 28
    assert len({c["rank"] for c in recs}) == 1
    s = build_rich_summary(hist)
    assert s["recommended_count"] == 28
    assert len(s["recommended_tickers"]) == 28
    assert set(s["recommended_tickers"]) == {c["ticker"] for c in recs}
    rows = history_records(_frame(hist))
    persisted = [r["ticker"] for r in rows if r.get("recommended")]
    assert set(persisted) == {c["ticker"] for c in recs}
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "20260904.json"
        p.write_text(json.dumps(hist), encoding="utf-8")
        got = load_recommended_tickers(p)
        assert len(got) == 28
        assert set(got) == {c["ticker"] for c in recs}


def test_B_duplicate_recommended_ticker_is_not_double_published():
    """Counterexample: the same ticker is flagged recommended twice in one run."""
    hist = _history(8)
    first = next(c for c in hist["top_candidates"] if c["recommended"] is True)
    hist["top_candidates"].append(dict(first, rank=99))
    s = build_rich_summary(hist)
    assert s["recommended_tickers"].count(first["ticker"]) == 1, (
        f"duplicate {first['ticker']} leaked into recommended_tickers: "
        f"{s['recommended_tickers']}"
    )
    assert s["recommended_count"] == len(s["recommended_tickers"])
    rows = history_records(_frame(hist))
    persisted = [r["ticker"] for r in rows if r.get("recommended")]
    assert persisted.count(first["ticker"]) == 1


def test_B_cli_default_does_not_truncate_the_watchlist(tmp_path, monkeypatch):
    """Counterexample: `python generate_pine_watchlist.py` with no --top.

    The library default is the full list (Pine `i_max_watchlist` is the TV cap).
    The CLI still advertised default=15 at 839e375 — that path must not silently
    drop names 16..N.
    """
    hist = _history(28)
    want = _expected(hist)
    assert len(want) == 28
    hp = tmp_path / "history"
    hp.mkdir()
    (hp / "20260904.json").write_text(json.dumps(hist), encoding="utf-8")
    out = tmp_path / "watchlist.txt"
    monkeypatch.setattr(
        sys,
        "argv",
        ["generate_pine_watchlist.py", "--history-dir", str(hp), "--output", str(out)],
    )
    rc = feeder_main()
    assert rc == 0
    got = [t for t in out.read_text(encoding="utf-8").split(",") if t]
    assert got == want, (
        f"CLI default truncated the watchlist: {len(want)} recommended -> {len(got)} written"
    )


def test_B_display_limit_does_not_waive_prefix_check():
    """Counterexample: a consumer declares display_limit but ships the wrong 15 names.

    The contract must still require top_details == recommended_tickers[:display_limit].
    An all-or-nothing bypass of the equality check would let a truncating consumer
    hide an arbitrary substitution.
    """
    hist = _history(28)
    s = build_rich_summary(hist, top_n=15)
    assert s.get("display_limit") == 15
    # swap the displayed 15 for the *last* 15 recommended (same count, wrong names)
    s["top_details"] = list(reversed(s["top_details"]))
    with tempfile.TemporaryDirectory() as d:
        sp = Path(d) / "summary.json"
        sp.write_text(json.dumps(s), encoding="utf-8")
        res = simulate_pine_parser(str(sp))
        assert res["errors"], (
            "validator accepted top_details that are not the prefix of "
            "recommended_tickers just because display_limit was set"
        )


# ---------------------------------------------------------------------------
# C — tracking completes pending horizons; provenance; idempotence
# ---------------------------------------------------------------------------

IDX = pd.bdate_range("2026-09-01", periods=20)
PX = pd.DataFrame(
    {
        "AAA": np.arange(100.0, 120.0),
        "BBB": np.arange(50.0, 70.0),
        "NEW": np.arange(20.0, 40.0),
    },
    index=IDX,
)


def _run(tickers=("AAA", "BBB"), date="20260903", **extra):
    run = {
        "date": date,
        "schema_version": 2,
        "data_last_bar": "2026-09-03",
        "top_candidates": [{"ticker": t, "recommended": True} for t in tickers]
        + [{"ticker": "NO", "recommended": False}],
    }
    run.update(extra)
    return run


def test_C_missing_signal_date_on_v2_file_is_not_treated_as_final():
    """Counterexample: a v2 tracking file whose `signal_date` key is missing."""
    run = _run()
    existing = {
        "schema_version": TRACKING_SCHEMA_VERSION,
        "recommended_snapshot": ["AAA", "BBB"],
        "candidates": [
            {
                "ticker": "AAA",
                "returns": {"return_5d": 0.01, "return_10d": 0.02},
                "status": {"5d": {"state": "measured"}, "10d": {"state": "measured"}},
            }
        ],
        "omitted": [],
    }
    redo, why = needs_update(existing, run)
    assert redo is True
    assert why == "signal_date_changed"


def test_C_omitted_no_price_data_retries_when_prices_arrive():
    """Counterexample: an omitted name later gets a price series."""
    run = _run(("AAA", "NEW"))
    first = compute_forward_returns_for_run(run, PX[["AAA"]], horizons=[5])
    omitted = {o["ticker"]: o["reason"] for o in first["omitted"]}
    assert omitted.get("NEW") == "no_price_data"
    redo, why = needs_update(first, run)
    assert redo is True and why == "retryable_omissions"
    later = compute_forward_returns_for_run(run, PX, horizons=[5])
    measured = {c["ticker"] for c in later["candidates"]}
    assert "NEW" in measured
    assert all(o["ticker"] != "NEW" for o in later["omitted"])


def test_C_omitted_no_entry_price_retries_when_the_hole_fills():
    """Counterexample: entry bar was NaN, then the hole is filled.

    `no_entry_price` is not in RETRYABLE_OMISSIONS, so a later backfill would
    stay omitted forever — the same class of hole that `no_price_data` retries.
    """
    run = _run(("AAA",))
    hole = PX.copy()
    hole.loc[IDX[3], "AAA"] = np.nan  # entry is first bar AFTER 2026-09-03 = IDX[3]
    first = compute_forward_returns_for_run(run, hole, horizons=[5])
    omitted = {o["ticker"]: o["reason"] for o in first["omitted"]}
    assert omitted.get("AAA") == "no_entry_price", omitted
    redo, why = needs_update(first, run)
    assert redo is True, (
        f"no_entry_price was treated as final ({why}); a filled hole cannot be measured"
    )
    filled = compute_forward_returns_for_run(run, PX, horizons=[5])
    assert filled["candidates"] and filled["candidates"][0]["ticker"] == "AAA"
    assert filled["omitted"] == []


def test_C_complete_v2_without_snapshot_still_sees_a_changed_history_set():
    """Counterexample: a complete pre-C v2 file has no recommended_snapshot.

    After finding B, history/ can grow (names past rank 20 now persist). A file
    that already looks complete must not freeze the truncated set.
    """
    run = _run(("AAA", "BBB", "NEW"))
    existing = {
        "schema_version": TRACKING_SCHEMA_VERSION,
        "signal_date": "2026-09-03",
        "candidates": [
            {
                "ticker": "AAA",
                "returns": {"return_5d": 0.01, "return_10d": 0.02},
                "status": {"5d": {"state": "measured"}, "10d": {"state": "measured"}},
            }
        ],
        "omitted": [],
    }
    assert "recommended_snapshot" not in existing
    redo, why = needs_update(existing, run)
    assert redo is True, (
        f"missing recommended_snapshot skipped the set check ({why}); "
        "a larger post-B history would never be re-measured"
    )
    assert why == "history_recommended_set_changed"


def test_C_duplicate_recommended_ticker_is_measured_once():
    """Counterexample: ticker recommended twice in one run."""
    run = _run(("AAA", "AAA"))
    res = compute_forward_returns_for_run(run, PX, horizons=[5])
    names = [c["ticker"] for c in res["candidates"]]
    assert names.count("AAA") == 1, f"AAA measured twice: {names}"
    assert res["recommended_snapshot"] == ["AAA"]


def test_C_idempotent_on_a_complete_file_with_provenance():
    run = _run(("AAA",))
    full = compute_forward_returns_for_run(run, PX, horizons=[5, 10])
    assert needs_update(full, run) == (False, "complete")
    again = compute_forward_returns_for_run(run, PX, horizons=[5, 10])
    assert again == full
