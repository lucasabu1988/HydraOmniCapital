"""core/tracking.py v2 — horizons are bars, entry is the first bar after the signal, nothing is dropped silently."""
import numpy as np
import pandas as pd

import core.tracking as T
from core.tracking import compute_forward_returns_for_run, TRACKING_SCHEMA_VERSION

# Fri 09-04 signal; Mon 09-07 holiday; Thu 09-17 data gap.
IDX = pd.DatetimeIndex([
    "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
    "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
    "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-18",
])
PX = pd.DataFrame({
    "AAA": np.arange(100.0, 112.0),          # 100, 101, ... 111
    "BBB": np.arange(50.0, 62.0),
}, index=IDX)
PX.loc["2026-09-08", "BBB"] = np.nan         # no price at the entry bar


def _run(date, tickers=("AAA", "BBB", "ZZZ"), **extra):
    run = {"date": date, "top_candidates": [{"ticker": t, "recommended": True} for t in tickers]}
    run["top_candidates"].append({"ticker": "NOT", "recommended": False})
    run.update(extra)
    return run


def test_entry_is_first_bar_after_signal_and_horizon_counts_bars():
    res = compute_forward_returns_for_run(_run("20260904"), PX, horizons=[5])
    assert res["schema_version"] == TRACKING_SCHEMA_VERSION
    assert res["horizon_basis"] == "trading_days"
    aaa = {c["ticker"]: c for c in res["candidates"]}["AAA"]
    assert aaa["entry_date"] == "2026-09-08"                 # Friday signal, Monday holiday
    assert aaa["entry_price"] == 104.0
    assert aaa["returns"]["exit_date_5d"] == "2026-09-15"     # 5 BARS later, not 5 calendar days
    assert aaa["returns"]["return_5d"] == round(109.0 / 104.0 - 1, 4)


def test_weekend_run_resolves_to_the_same_entry_as_friday():
    fri = compute_forward_returns_for_run(_run("20260904", ("AAA",)), PX, horizons=[5])
    sat = compute_forward_returns_for_run(_run("20260905", ("AAA",)), PX, horizons=[5])
    assert fri["candidates"][0]["entry_date"] == sat["candidates"][0]["entry_date"] == "2026-09-08"


def test_data_last_bar_overrides_run_date():
    # Screener ran on Sunday the 6th but scored Thursday's bar: entry is Friday the 4th.
    res = compute_forward_returns_for_run(_run("20260906", ("AAA",), data_last_bar="2026-09-03"), PX, horizons=[1])
    assert res["signal_date"] == "2026-09-03"
    assert res["candidates"][0]["entry_date"] == "2026-09-04"


def test_unmeasurable_names_are_listed_not_dropped():
    res = compute_forward_returns_for_run(_run("20260904"), PX, horizons=[5])
    omitted = {o["ticker"]: o["reason"] for o in res["omitted"]}
    assert omitted == {"BBB": "no_entry_price", "ZZZ": "no_price_data"}
    assert [c["ticker"] for c in res["candidates"]] == ["AAA"]


def test_pending_horizon_is_none_not_omitted():
    res = compute_forward_returns_for_run(_run("20260916", ("AAA",)), PX, horizons=[5])
    assert res["omitted"] == []
    assert res["candidates"][0]["entry_date"] == "2026-09-18"
    assert res["candidates"][0]["returns"]["return_5d"] is None


def test_update_tracking_recomputes_old_schema_files(monkeypatch, tmp_path):
    saved = {}
    monkeypatch.setattr(T, "list_available_dates", lambda: ["20260904", "20260908"])
    monkeypatch.setattr(T, "load_daily_run", lambda d: _run(d, ("AAA",)))
    monkeypatch.setattr(T, "_fetch_prices", lambda tickers, start, end: PX)
    monkeypatch.setattr(T, "save_tracking", lambda d, data: saved.__setitem__(d, data))
    complete = {                       # current schema, every horizon measured, same signal and set
        "schema_version": TRACKING_SCHEMA_VERSION, "signal_date": "2026-09-08", "recommended_snapshot": ["AAA"],
        "candidates": [{"ticker": "AAA", "returns": {"return_5d": 0.01, "return_10d": 0.02},
                        "status": {"5d": {"state": "measured"}, "10d": {"state": "measured"}}}],
        "omitted": [],
    }
    existing = {
        "20260904": {"candidates": [{"ticker": "AAA"}]},                                   # v1: no version
        "20260908": complete,
    }
    monkeypatch.setattr(T, "load_tracking", lambda d: existing[d])

    T.update_tracking()
    assert "20260904" in saved, "a v1 file must be recomputed even without --force"
    assert "20260908" not in saved, "a COMPLETE current-schema file is left alone (a pending one is not: test_tracking_pending)"
