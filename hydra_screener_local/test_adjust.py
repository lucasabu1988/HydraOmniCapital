"""TASK-377 — local total-return adjustment (hand cases)."""
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.adjust import adjust, compare, dividends_from_rows  # noqa: E402

IDX = pd.bdate_range("2024-01-01", periods=6)          # Mon 01-01 .. Mon 01-08
RAW = pd.Series([100.0, 102.0, 101.0, 103.0, 104.0, 105.0], index=IDX)


def test_no_events_is_identity():
    out = adjust(RAW)
    pd.testing.assert_series_equal(out, RAW, check_names=False)


def test_one_dividend_scales_only_the_bars_before_the_ex_date():
    # ex-date Thu 01-04: previous close is Wed 01-03 = 101 -> factor 1 - 1.01/101 = 0.99
    rep = {}
    out = adjust(RAW, dividends={"2024-01-04": 1.01}, report=rep)
    assert rep["applied"] == 1 and rep["skipped"] == []
    assert out.loc["2024-01-01"] == pytest.approx(100.0 * 0.99)
    assert out.loc["2024-01-03"] == pytest.approx(101.0 * 0.99)
    assert out.loc["2024-01-04"] == pytest.approx(103.0)          # ex-date bar untouched
    assert out.loc["2024-01-08"] == pytest.approx(105.0)          # last bar == raw always


def test_two_dividends_compound_backwards():
    out = adjust(RAW, dividends={"2024-01-03": 2.04, "2024-01-05": 1.03})
    # 01-03 ex: prev 01-02 = 102 -> 0.98 ; 01-05 ex: prev 01-04 = 103 -> 0.99
    assert out.loc["2024-01-01"] == pytest.approx(100.0 * 0.98 * 0.99)
    assert out.loc["2024-01-02"] == pytest.approx(102.0 * 0.98 * 0.99)
    assert out.loc["2024-01-03"] == pytest.approx(101.0 * 0.99)
    assert out.loc["2024-01-04"] == pytest.approx(103.0 * 0.99)
    assert out.loc["2024-01-05"] == pytest.approx(104.0)


def test_split_on_unadjusted_raw():
    raw = pd.Series([200.0, 204.0, 102.0, 103.0], index=pd.bdate_range("2024-01-01", periods=4))
    out = adjust(raw, splits={"2024-01-03": 2.0})               # 2:1 on Wed
    assert out.loc["2024-01-01"] == pytest.approx(100.0)
    assert out.loc["2024-01-02"] == pytest.approx(102.0)
    assert out.loc["2024-01-03"] == pytest.approx(102.0)
    rev = adjust(raw, splits={"2024-01-03": 0.1})               # 1:10 reverse
    assert rev.loc["2024-01-01"] == pytest.approx(2000.0)


def test_dividend_and_split_together():
    raw = pd.Series([200.0, 204.0, 102.0, 103.0], index=pd.bdate_range("2024-01-01", periods=4))
    out = adjust(raw, dividends={"2024-01-04": 1.02}, splits={"2024-01-03": 2.0})
    # split factor 0.5 before 01-03; dividend factor 1 - 1.02/102 = 0.99 before 01-04
    assert out.loc["2024-01-01"] == pytest.approx(200.0 * 0.5 * 0.99)
    assert out.loc["2024-01-03"] == pytest.approx(102.0 * 0.99)
    assert out.loc["2024-01-04"] == pytest.approx(103.0)


def test_bad_events_are_skipped_and_reported():
    rep = {}
    out = adjust(RAW, dividends={"2023-12-01": 1.0, "2024-01-04": 500.0}, report=rep)
    pd.testing.assert_series_equal(out, RAW, check_names=False)
    kinds = sorted(r[3] for r in rep["skipped"])
    assert kinds == ["dps >= previous close", "no bar before ex-date"]
    assert rep["applied"] == 0


def test_rows_helper_and_compare():
    rows = [{"ticker": "AAA", "ex_date": "2024-01-04", "dps": 0.5},
            {"ticker": "AAA", "ex_date": "2024-01-04", "dps": 0.51},     # two records same day add up
            {"ticker": "BBB", "ex_date": "2024-01-04", "dps": 9.0}]
    s = dividends_from_rows(rows, "AAA")
    assert list(s.index) == [pd.Timestamp("2024-01-04")] and s.iloc[0] == pytest.approx(1.01)
    ref = adjust(RAW, dividends=s)
    c = compare(adjust(RAW, dividends={"2024-01-04": 1.01}), ref)
    assert c["n"] == 6 and c["max_rel"] == pytest.approx(0.0) and c["n_bad"] == 0
    c2 = compare(RAW, ref)
    assert c2["n_bad"] == 3 and c2["first_bad"] == "2024-01-01"      # the 3 bars before the ex-date
