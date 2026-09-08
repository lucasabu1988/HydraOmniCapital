"""Phase 1 of the Buffett indicator: the fetch, the snapshot store, and the honesty guards.

No network in here - the fetcher is exercised through a fake response, the way
test_build_russell_pit.py exercises Norgate. Auto-discovered by run_all_tests.py (pytest-routed:
no __main__ block).
"""
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from core.valuation import (  # noqa: E402
    MIN_EPISODES_TO_DECIDE, describe, enough_episodes_to_decide, episodes,
    expanding_percentiles, percentile_as_known,
)
from data import macro  # noqa: E402

QUARTERS = [f"{y}-{m:02d}-01" for y in range(2000, 2022) for m in (1, 4, 7, 10)]


def _series(values, dates=None):
    dates = dates or QUARTERS[: len(values)]
    return dict(zip(dates, values, strict=False))


# --------------------------------------------------------------------- the ratio itself
def test_the_definition_is_the_z1_one_in_billions():
    """equities are $ millions, GDP is $ billions: the /1000 is the whole trap."""
    got = macro.buffett_from_series({"2026-01-01": 69_511_628.0}, {"2026-01-01": 31_865.721})
    assert got["2026-01-01"] == pytest.approx(2.1814, abs=1e-4)


def test_only_quarters_present_in_both_series_are_used():
    got = macro.buffett_from_series({"a": 1000.0, "b": 2000.0}, {"b": 1.0, "c": 1.0})
    assert list(got) == ["b"]


def test_a_zero_gdp_is_dropped_not_divided_by():
    got = macro.buffett_from_series({"q": 1000.0}, {"q": 0.0})
    assert got == {}


# --------------------------------------------------------------------- the fetch
class _Resp:
    def __init__(self, text):
        self.text = text


def _install_fake(monkeypatch, payloads, calls=None):
    def fake_get(url, timeout=20, attempts=3, backoff=2.0, headers=None):
        if calls is not None:
            calls.append((url, headers))
        for series_id, text in payloads.items():
            if f"id={series_id}" in url:
                return None if text is None else _Resp(text)
        return None

    import data.universe as U
    monkeypatch.setattr(U, "_get_with_retry", fake_get)


CSV_EQ = "DATE,NCBEILQ027S\n2025-10-01,71863086\n2026-01-01,69511628\n"
CSV_GDP = "DATE,GDP\n2025-10-01,31422.526\n2026-01-01,31865.721\n"


def test_fetch_builds_the_ratio_and_labels_it_revised(monkeypatch):
    _install_fake(monkeypatch, {macro.EQUITIES_SERIES: CSV_EQ, macro.GDP_SERIES: CSV_GDP})
    r = macro.fetch_buffett()
    assert r["provenance"] == "revised"
    assert r["latest_obs_date"] == "2026-01-01"
    assert r["latest_value"] == pytest.approx(2.1814, abs=1e-4)
    assert r["n_quarters"] == 2


def test_the_fetch_sends_its_own_user_agent(monkeypatch):
    """FRED hangs on the browser-like UA data.universe sends; measured 2026-09-08. If this test
    goes red because the header was dropped, the symptom in production is a silent timeout."""
    calls = []
    _install_fake(monkeypatch, {macro.EQUITIES_SERIES: CSV_EQ, macro.GDP_SERIES: CSV_GDP}, calls)
    macro.fetch_buffett()
    assert calls, "nothing was fetched"
    for _url, headers in calls:
        assert headers is macro.FRED_HEADERS or headers == macro.FRED_HEADERS
        assert "Mozilla" not in headers["User-Agent"]


def test_a_failed_leg_returns_none_instead_of_half_a_ratio(monkeypatch):
    _install_fake(monkeypatch, {macro.EQUITIES_SERIES: CSV_EQ, macro.GDP_SERIES: None})
    assert macro.fetch_buffett() is None


def test_missing_observations_marked_with_a_dot_are_skipped(monkeypatch):
    _install_fake(monkeypatch, {
        macro.EQUITIES_SERIES: "DATE,X\n2026-01-01,.\n2025-10-01,71863086\n",
        macro.GDP_SERIES: CSV_GDP,
    })
    r = macro.fetch_buffett()
    assert r["n_quarters"] == 1 and r["latest_obs_date"] == "2025-10-01"


# --------------------------------------------------------------------- the snapshot store
def _reading(value=2.1814, obs="2026-01-01"):
    return {"latest_value": value, "latest_obs_date": obs, "n_quarters": 302,
            "definition": macro.DEFINITION}


def test_a_snapshot_is_recorded_once_per_day_and_a_rerun_is_a_no_op(tmp_path):
    path = str(tmp_path / "snaps.json")
    first = macro.append_snapshot(_reading(), "2026-09-08", path)
    again = macro.append_snapshot(_reading(), "2026-09-08", path)
    assert first["written"] and first["snapshots"] == 1
    assert not again["written"] and "same value" in again["reason"]
    assert len(macro.load_snapshots(path)) == 1


def test_a_different_value_on_the_same_day_is_refused_unless_forced(tmp_path):
    path = str(tmp_path / "snaps.json")
    macro.append_snapshot(_reading(2.18), "2026-09-08", path)
    clash = macro.append_snapshot(_reading(2.25), "2026-09-08", path)
    assert not clash["written"] and "DIFFERENT" in clash["reason"]
    forced = macro.append_snapshot(_reading(2.25), "2026-09-08", path, force=True)
    assert forced["written"]
    assert macro.load_snapshots(path)[0]["value"] == 2.25


def test_snapshots_accumulate_in_date_order(tmp_path):
    path = str(tmp_path / "snaps.json")
    for d, v in (("2026-09-15", 2.20), ("2026-09-08", 2.18), ("2026-09-22", 2.22)):
        macro.append_snapshot(_reading(v), d, path)
    assert [s["observed_at"] for s in macro.load_snapshots(path)] == [
        "2026-09-08", "2026-09-15", "2026-09-22"]
    assert list(macro.pit_series(path).values()) == [2.18, 2.20, 2.22]


def test_the_pit_series_never_returns_revised_numbers(tmp_path):
    """The one guard that matters: a caller asking for point-in-time data cannot reach the
    revised history by accident, because revised entries are not `provenance == snapshot`."""
    path = str(tmp_path / "snaps.json")
    payload = {"version": 1, "snapshots": [
        {"observed_at": "2026-09-08", "provenance": "snapshot", "value": 2.18},
        {"observed_at": "2008-01-01", "provenance": "revised", "value": 1.05},
    ]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    assert macro.pit_series(path) == {"2026-09-08": 2.18}


def test_an_unreadable_store_is_empty_not_an_exception(tmp_path):
    path = str(tmp_path / "snaps.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write("{not json")
    assert macro.load_snapshots(path) == []
    assert macro.pit_series(path) == {}


def test_nothing_is_written_without_a_reading(tmp_path):
    path = str(tmp_path / "snaps.json")
    assert not macro.append_snapshot(None, "2026-09-08", path)["written"]
    assert not os.path.exists(path)


# --------------------------------------------------------------------- the percentile
def test_the_percentile_is_expanding_not_full_sample():
    """A value that is the highest ever WHEN SEEN scores ~100 even if later values exceed it."""
    s = _series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    mid = QUARTERS[7]
    assert percentile_as_known(s, mid) == pytest.approx(93.75)     # 7 below, itself half-counted
    assert percentile_as_known(s, QUARTERS[9]) == pytest.approx(95.0)


def test_a_short_history_gets_no_percentile_at_all():
    s = _series([1, 2, 3])
    assert percentile_as_known(s, QUARTERS[2]) is None
    assert expanding_percentiles(s) == {}


def test_a_date_outside_the_series_is_none():
    assert percentile_as_known(_series([1] * 10), "1999-01-01") is None


def test_a_flat_series_scores_fifty_not_zero_or_a_hundred():
    s = _series([1.0] * 12)
    assert percentile_as_known(s, QUARTERS[11]) == pytest.approx(50.0)


# --------------------------------------------------------------------- the episode gate
def test_episodes_are_contiguous_runs_not_observations():
    """8 flat quarters, then 20 identical high ones: ONE run - and it ends after 5.

    That is not a bug, it is the midrank expanding percentile doing what it should: with 8 ones
    and k nines the k-th nine scores (8 + 0.5k)/(8 + k), which crosses below 80 at k=6. A level
    that becomes the norm stops being extreme, so a percentile rule HABITUATES to a permanently
    elevated indicator - the exact real-world criticism of the Buffett indicator, and a property
    any phase-2 rule would inherit. Pinned here so nobody "fixes" it into a full-sample
    percentile, which would be look-ahead.
    """
    s = _series([1.0] * 8 + [9.0] * 20)
    eps = episodes(s)
    assert len(eps) == 1
    assert eps[0]["observations"] == 5
    assert eps[0]["start"] == QUARTERS[8]
    pcts = expanding_percentiles(s)
    assert pcts[QUARTERS[12]] >= 80.0 > pcts[QUARTERS[13]]


def test_two_separate_climbs_are_two_episodes():
    s = _series([1.0] * 8 + [9.0] * 4 + [0.5] * 6 + [9.0] * 4)
    assert len(episodes(s)) == 2


def test_the_window_keeps_only_episodes_a_backtest_could_observe():
    s = _series([1.0] * 8 + [9.0] * 4 + [0.5] * 6 + [9.0] * 4)
    early, late = episodes(s), episodes(s, window_start=QUARTERS[20])
    assert len(early) == 2 and len(late) == 1
    assert late[0]["end"] >= QUARTERS[20]


def test_the_gate_says_unmeasurable_rather_than_no_effect():
    s = _series([1.0] * 8 + [9.0] * 4)
    gate = enough_episodes_to_decide(s)
    assert gate["episodes"] == 1 and not gate["enough"]
    assert "UNMEASURABLE" in gate["verdict"]
    assert "no effect" in gate["verdict"]
    assert gate["minimum_required"] == MIN_EPISODES_TO_DECIDE


def test_enough_episodes_passes_the_gate():
    vals = [1.0] * 8
    for _ in range(6):
        vals += [9.0, 9.0, 0.4, 0.4]
    gate = enough_episodes_to_decide(_series(vals))
    assert gate["episodes"] >= MIN_EPISODES_TO_DECIDE and gate["enough"]


def test_describe_carries_the_disclaimer_and_the_sample_size():
    d = describe(_series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]))
    assert d["observations"] == 10
    assert d["percentile_as_known"] is not None
    assert "changes no order" in d["note"]
    assert d["enough_episodes_to_decide"] is False


def test_describe_on_an_empty_series_is_a_clean_record():
    d = describe({})
    assert d["observations"] == 0 and d["value"] is None
