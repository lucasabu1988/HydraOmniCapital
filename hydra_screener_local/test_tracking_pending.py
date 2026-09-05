"""Audit finding C: tracking must complete pending horizons on later updates, idempotently.

Scenario: a run is tracked when only 3 bars after entry exist (5d/10d pending), then bars
arrive and the horizons fill in; running again changes nothing. Pending, measured and
unmeasurable are distinguished with a reason; the original signal and recommended set are
kept so a changed history file is detected instead of silently re-measured.
"""
import numpy as np
import pandas as pd

from core.tracking import compute_forward_returns_for_run, needs_update, TRACKING_SCHEMA_VERSION

IDX = pd.bdate_range("2026-09-01", periods=20)          # 20 weekdays, no holidays needed here
PX = pd.DataFrame({"AAA": np.arange(100.0, 120.0), "BBB": np.arange(50.0, 70.0), "GAP": np.arange(10.0, 30.0)}, index=IDX)
PX.loc[IDX[8], "GAP"] = np.nan                           # a hole exactly at the 5-bar exit (entry pos 3 + 5) of a 09-03 signal


def _run(tickers=("AAA", "BBB", "GAP"), date="20260903"):
    return {"date": date, "schema_version": 2, "data_last_bar": "2026-09-03",
            "top_candidates": [{"ticker": t, "recommended": True} for t in tickers] + [{"ticker": "NO", "recommended": False}]}


def test_partial_then_complete_then_idempotent():
    run = _run()
    partial = compute_forward_returns_for_run(run, PX.iloc[:7], horizons=[5, 10])   # entry 09-04 (pos 3), only 3 bars after
    aaa = {c["ticker"]: c for c in partial["candidates"]}["AAA"]
    assert aaa["entry_date"] == "2026-09-04" and aaa["entry_price"] == 103.0
    assert aaa["returns"]["return_5d"] is None and aaa["returns"]["return_10d"] is None
    assert aaa["status"]["5d"]["state"] == "pending" and aaa["status"]["10d"]["state"] == "pending"
    assert needs_update(partial, run) == (True, "pending_returns")

    full = compute_forward_returns_for_run(run, PX, horizons=[5, 10])
    aaa2 = {c["ticker"]: c for c in full["candidates"]}["AAA"]
    assert aaa2["entry_price"] == 103.0                                  # entry never moves
    assert aaa2["returns"]["return_5d"] == round(108.0 / 103.0 - 1, 4)
    assert aaa2["returns"]["return_10d"] == round(113.0 / 103.0 - 1, 4)
    assert aaa2["status"]["5d"] == {"state": "measured"}
    assert needs_update(full, run) == (False, "complete")

    again = compute_forward_returns_for_run(run, PX, horizons=[5, 10])
    assert again == full                                                # idempotent


def test_unmeasurable_has_a_reason_and_is_not_pending_forever():
    full = compute_forward_returns_for_run(_run(), PX, horizons=[5, 10])
    gap = {c["ticker"]: c for c in full["candidates"]}["GAP"]
    assert gap["returns"]["return_5d"] is None
    assert gap["status"]["5d"] == {"state": "unmeasurable", "reason": "no_price_at_exit_bar"}
    assert gap["status"]["10d"]["state"] == "measured"
    assert needs_update(full, _run()) == (False, "complete")            # a hole is final, not pending


def test_delisted_name_becomes_unmeasurable_after_enough_bars():
    px = PX.copy()
    px.loc[IDX[8]:, "BBB"] = np.nan                                      # BBB stops trading at its 5d exit bar (pos 8)
    res = compute_forward_returns_for_run(_run(("BBB",)), px, horizons=[5])
    bbb = res["candidates"][0]
    assert bbb["status"]["5d"] == {"state": "unmeasurable", "reason": "delisted_or_missing_after_exit"}
    short = compute_forward_returns_for_run(_run(("BBB",)), px.iloc[:12], horizons=[5])   # only 2 bars after the exit
    assert short["candidates"][0]["status"]["5d"]["state"] == "pending"


def test_changed_history_or_old_schema_forces_recompute():
    run = _run()
    full = compute_forward_returns_for_run(run, PX, horizons=[5])
    assert full["recommended_snapshot"] == ["AAA", "BBB", "GAP"] and full["run_schema_version"] == 2
    edited = _run(("AAA", "BBB"))
    assert needs_update(full, edited) == (True, "history_recommended_set_changed")
    moved = dict(run, data_last_bar="2026-09-02")
    assert needs_update(full, moved) == (True, "signal_date_changed")
    v1 = dict(full, schema_version=1)
    assert needs_update(v1, run) == (True, "older_schema")
    assert needs_update(None, run) == (True, "no_tracking_yet")
    # a pre-status v2 file with a None return is pending, not final (the exact bug of finding C)
    legacy_v2 = {"schema_version": TRACKING_SCHEMA_VERSION, "signal_date": "2026-09-03",
                 "candidates": [{"ticker": "AAA", "returns": {"return_5d": None, "return_10d": 0.01}},
                                {"ticker": "BBB", "returns": {"return_5d": 0.01, "return_10d": 0.01}}],
                 "omitted": [{"ticker": "GAP", "reason": "no_price_at_exit_bar"}]}
    assert needs_update(legacy_v2, run) == (True, "pending_returns")
    # a pre-provenance file whose own set (candidates + omitted) is smaller than history's is re-measured (review 336)
    smaller = dict(legacy_v2, candidates=legacy_v2["candidates"][:1], omitted=[])
    assert needs_update(smaller, run) == (True, "history_recommended_set_changed")
