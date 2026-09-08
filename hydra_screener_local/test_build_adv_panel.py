"""Tests for experiments/build_adv_panel.py - the dollar-ADV panel fill_cost_report.py consumes.

The traps this pins, in order of how much money they could cost:

  1. A zero-volume day must NOT become a 0.0 ADV. `order$ / ADV` with ADV=0 is an infinity that
     lands in the ">20%" slippage bucket and looks like a measurement instead of a hole.
  2. close and volume must be aligned INNER on both axes. A bare `close * volume` aligns on the
     union, so a ticker present in only one frame comes back as an all-NaN column - which reads
     as "covered, no data" rather than "not covered".
  3. An empty or all-NaN panel must be refused, not written: a pickle of NaNs makes the report
     print an empty adv_bucket table with no warning that the panel was junk.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "experiments"))

import build_adv_panel as bap  # noqa: E402


def _frames(n_days=30, tickers=("AAA", "BBB"), start="2020-01-01"):
    idx = pd.date_range(start, periods=n_days, freq="B")
    close = pd.DataFrame(10.0, index=idx, columns=list(tickers))
    volume = pd.DataFrame(1_000_000.0, index=idx, columns=list(tickers))
    return close, volume


def test_rolling_window_and_definition():
    """ADV = mean of the last N (close*volume); flat inputs make the answer checkable by hand."""
    close, volume = _frames(n_days=30)
    adv = bap.build_adv(close, volume, window=20)
    # min_periods defaults to the window: the first 19 rows have no 20-bar mean
    assert adv["AAA"].iloc[:19].isna().all()
    assert adv["AAA"].iloc[19] == pytest.approx(10.0 * 1_000_000.0)
    assert adv.shape == close.shape


def test_window_actually_averages_the_last_n_only():
    close, volume = _frames(n_days=10)
    volume.iloc[:5, :] = 2_000_000.0        # first five days double volume
    adv = bap.build_adv(close, volume, window=5)
    # row 4 sees only the doubled days; row 9 sees only the normal ones
    assert adv["AAA"].iloc[4] == pytest.approx(10.0 * 2_000_000.0)
    assert adv["AAA"].iloc[9] == pytest.approx(10.0 * 1_000_000.0)


def test_window_of_one_is_plain_dollar_volume():
    close, volume = _frames(n_days=5)
    close.iloc[:, :] = [[3.0, 4.0]] * 5
    adv = bap.build_adv(close, volume, window=1)
    assert adv["AAA"].iloc[0] == pytest.approx(3.0 * 1_000_000.0)
    assert adv["BBB"].iloc[0] == pytest.approx(4.0 * 1_000_000.0)


def test_bad_window_rejected():
    close, volume = _frames()
    with pytest.raises(ValueError):
        bap.build_adv(close, volume, window=0)


def test_alignment_is_inner_on_both_axes():
    """A ticker or a date present in only one frame must be dropped, not carried as NaN."""
    close, volume = _frames(n_days=25, tickers=("AAA", "BBB", "ONLY_CLOSE"))
    volume = volume.drop(columns=["ONLY_CLOSE"])
    volume = volume.iloc[2:]                                    # and two fewer dates
    adv = bap.build_adv(close, volume, window=5)
    assert list(adv.columns) == ["AAA", "BBB"]                  # not present => not a column
    assert adv.index.equals(volume.index)
    assert len(adv) == 23


def test_alignment_does_not_reorder_or_duplicate():
    close, volume = _frames(n_days=25, tickers=("BBB", "AAA"))
    volume = volume[["AAA", "BBB"]]
    adv = bap.build_adv(close, volume, window=5)
    assert sorted(adv.columns) == ["AAA", "BBB"]
    assert len(adv.columns) == 2


def test_zero_volume_gives_nan_not_zero():
    """The whole point: a halted day must not divide as ADV=0 downstream."""
    close, volume = _frames(n_days=10)
    volume.iloc[5, 0] = 0.0
    adv = bap.build_adv(close, volume, window=1)
    assert np.isnan(adv["AAA"].iloc[5])
    assert adv["AAA"].iloc[4] == pytest.approx(10.0 * 1_000_000.0)   # neighbours untouched
    assert adv["BBB"].iloc[5] == pytest.approx(10.0 * 1_000_000.0)   # other ticker untouched


def test_missing_volume_gives_nan():
    close, volume = _frames(n_days=10)
    volume.iloc[3, 0] = np.nan
    adv = bap.build_adv(close, volume, window=1)
    assert np.isnan(adv["AAA"].iloc[3])


def test_negative_volume_gives_nan():
    close, volume = _frames(n_days=10)
    volume.iloc[7, 0] = -5.0
    adv = bap.build_adv(close, volume, window=1)
    assert np.isnan(adv["AAA"].iloc[7])


def test_keep_zero_volume_reproduces_the_lab():
    """The escape hatch is the lab's exact arithmetic: 0 volume => 0 dollars, averaged in."""
    close, volume = _frames(n_days=10)
    volume.iloc[5, 0] = 0.0
    adv = bap.build_adv(close, volume, window=1, keep_zero_volume=True)
    assert adv["AAA"].iloc[5] == 0.0


def test_matches_the_lab_formula_when_nothing_is_zero():
    """No second definition of ADV: with clean volume this IS (c*v).rolling(20).mean()."""
    rng = np.random.default_rng(11)
    idx = pd.date_range("2021-01-01", periods=60, freq="B")
    close = pd.DataFrame(rng.uniform(10, 100, (60, 3)), index=idx, columns=["A", "B", "C"])
    volume = pd.DataFrame(rng.uniform(1e5, 1e7, (60, 3)), index=idx, columns=["A", "B", "C"])
    expected = (close * volume).rolling(20).mean()
    pd.testing.assert_frame_equal(bap.build_adv(close, volume, window=20), expected)


def test_min_periods_relaxes_the_warmup():
    close, volume = _frames(n_days=30)
    adv = bap.build_adv(close, volume, window=20, min_periods=1)
    assert adv["AAA"].iloc[0] == pytest.approx(10.0 * 1_000_000.0)


def test_refuses_empty_panel_no_common_columns():
    close, volume = _frames(n_days=25, tickers=("AAA",))
    volume = volume.rename(columns={"AAA": "ZZZ"})
    with pytest.raises(bap.EmptyPanel):
        bap.build_adv(close, volume, window=5)


def test_refuses_empty_panel_no_common_dates():
    close, _ = _frames(n_days=25, start="2020-01-01")
    _, volume = _frames(n_days=25, start="2023-01-01")
    with pytest.raises(bap.EmptyPanel):
        bap.build_adv(close, volume, window=5)


def test_refuses_all_nan_panel_when_history_is_shorter_than_the_window():
    close, volume = _frames(n_days=5)
    with pytest.raises(bap.EmptyPanel):
        bap.build_adv(close, volume, window=20)


def test_refuses_all_nan_panel_when_every_volume_is_zero():
    close, volume = _frames(n_days=30)
    volume.iloc[:, :] = 0.0
    with pytest.raises(bap.EmptyPanel):
        bap.build_adv(close, volume, window=5)


def test_coverage_report_flags_absent_ticker():
    close, volume = _frames(n_days=25, tickers=("AAA", "BBB"))
    adv = bap.build_adv(close, volume, window=5)
    rows, covered = bap.coverage_report(adv, ["AAA", "NOPE"])
    assert covered == 1
    by_ticker = {r["ticker"]: r for r in rows}
    assert by_ticker["AAA"]["covered"] is True
    assert by_ticker["AAA"]["last_adv"] == pytest.approx(10.0 * 1_000_000.0)
    assert by_ticker["NOPE"]["covered"] is False
    assert by_ticker["NOPE"]["last_adv"] is None
    assert by_ticker["NOPE"]["n_obs"] == 0


def test_coverage_report_counts_an_all_nan_column_as_not_covered():
    """Present as a column but never a real value is a hole, not coverage."""
    close, volume = _frames(n_days=25, tickers=("AAA", "BBB"))
    volume["BBB"] = 0.0
    adv = bap.build_adv(close, volume, window=5)
    rows, covered = bap.coverage_report(adv, ["AAA", "BBB"])
    assert covered == 1
    assert {r["ticker"]: r["covered"] for r in rows} == {"AAA": True, "BBB": False}


def test_coverage_report_output_says_not_covered(capsys):
    close, volume = _frames(n_days=25)
    adv = bap.build_adv(close, volume, window=5)
    rows, covered = bap.coverage_report(adv, ["AAA", "NOPE"])
    bap.print_coverage(rows, covered, "test")
    out = capsys.readouterr().out
    assert "NOT COVERED" in out
    assert "NOPE" in out
    assert "1/2 covered" in out


def test_live_pending_tickers_reads_the_pending_list(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"pending": [{"ticker": "AAA"}, {"ticker": "BBB"},
                                         {"ticker": "AAA"}, {"nope": 1}]}), encoding="utf-8")
    assert bap.live_pending_tickers(str(p)) == ["AAA", "BBB"]


def test_live_pending_tickers_tolerates_a_missing_file(tmp_path):
    assert bap.live_pending_tickers(str(tmp_path / "absent.json")) == []


def test_main_writes_a_pickle_the_report_can_read(tmp_path):
    close, volume = _frames(n_days=30)
    cache = tmp_path / "cache"
    cache.mkdir()
    close.to_pickle(cache / "close.pkl")
    volume.to_pickle(cache / "volume.pkl")
    out = tmp_path / "adv_usd.pkl"
    rc = bap.main(["--cache", str(cache), "--out", str(out), "--window", "20",
                   "--report-tickers", "AAA,NOPE"])
    assert rc == 0
    got = pd.read_pickle(out)
    assert got.shape == (30, 2)
    assert got["AAA"].dropna().iloc[-1] == pytest.approx(10.0 * 1_000_000.0)


def test_main_dry_run_writes_nothing(tmp_path):
    close, volume = _frames(n_days=30)
    cache = tmp_path / "cache"
    cache.mkdir()
    close.to_pickle(cache / "close.pkl")
    volume.to_pickle(cache / "volume.pkl")
    out = tmp_path / "adv_usd.pkl"
    assert bap.main(["--cache", str(cache), "--out", str(out), "--dry-run"]) == 0
    assert not out.exists()


def test_main_refuses_and_writes_nothing_when_the_panel_is_empty(tmp_path):
    close, volume = _frames(n_days=5)
    cache = tmp_path / "cache"
    cache.mkdir()
    close.to_pickle(cache / "close.pkl")
    volume.to_pickle(cache / "volume.pkl")
    out = tmp_path / "adv_usd.pkl"
    assert bap.main(["--cache", str(cache), "--out", str(out), "--window", "20"]) == 1
    assert not out.exists()


def test_main_skips_cleanly_without_a_cache(tmp_path, capsys):
    assert bap.main(["--cache", str(tmp_path / "nothing")]) == 0
    assert "SKIP" in capsys.readouterr().out


def test_the_default_window_is_pinned_to_the_labs_definition():
    """Both TASK-413 reviewers mutated DEFAULT_WINDOW (20 -> 21, 20 -> 25) with 25/25 still green.

    That constant is what every CLI run bakes into the artefact, and `P.ADV_USD` in
    experiments/redesign_lab.py is `rolling(20).mean()`. Forking the definition would make two
    different ADVs circulate under one name, so it is pinned here.
    """
    import re

    from build_adv_panel import DEFAULT_WINDOW
    assert DEFAULT_WINDOW == 20
    lab = pathlib.Path(__file__).parent / "experiments" / "redesign_lab.py"
    src = lab.read_text(encoding="utf-8")
    m = re.search(r"ADV_USD\s*=\s*\(c \* P\.volume\)\.rolling\((\d+)\)", src)
    assert m, "redesign_lab no longer defines P.ADV_USD the way this test reads it"
    assert int(m.group(1)) == DEFAULT_WINDOW, (
        f"the lab uses rolling({m.group(1)}) but build_adv_panel defaults to {DEFAULT_WINDOW}"
    )
