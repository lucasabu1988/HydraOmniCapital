"""ASTRA-05b — partial as-printed coverage must not delete names from the eligible universe.

`close_raw.pkl` for the OOS panel can only come from the bar store, which holds as-printed closes
from 2006-09-06 for the names it was seeded with. The panel starts in 2004 and is full of delisted
names the store never had; on the production cache that is 84% of priced cells and 671 of 1209
tickers. `eligibility_mask` tests `elig_px.notna()`, so a NaN raw cell would have made a PRICED name
ineligible — the delisted half of the panel would have vanished from selection, which is the
survivorship bias the point-in-time panel exists to avoid, and a worse look-ahead than the dividend
one the strict mode fixes.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "experiments"))

import redesign_lab as L  # noqa: E402


class _Panel:
    def __init__(self, cache_dir, close, volume):
        self.CACHE_DIR = cache_dir
        self.close = close
        self.volume = volume


def _panel(tmp_path, raw=None):
    idx = pd.bdate_range("2026-01-05", periods=30)
    close = pd.DataFrame({"AAA": 10.0, "BBB": 20.0, "DELISTED": 6.0}, index=idx)
    volume = pd.DataFrame(1_000_000.0, index=idx, columns=close.columns)
    if raw is not None:
        raw.to_pickle(os.path.join(tmp_path, L.RAW_CLOSE_PKL))
    return _Panel(str(tmp_path), close, volume)


def test_without_a_raw_file_the_run_is_labelled_adjusted(tmp_path, capsys):
    P = _panel(tmp_path)
    px, adv, label = L.attach_eligibility_panel(P)
    assert px is None and adv is None
    assert "adjusted" in label and L.RAW_CLOSE_PKL in label


def test_an_uncovered_cell_falls_back_to_the_adjusted_close_instead_of_nan(tmp_path):
    """The bug this file exists for: a priced name with no as-printed history must stay priced."""
    idx = pd.bdate_range("2026-01-05", periods=30)
    raw = pd.DataFrame({"AAA": 9.5, "BBB": 19.0}, index=idx)          # DELISTED has no raw history
    P = _panel(tmp_path, raw)
    px, adv, label = L.attach_eligibility_panel(P)
    assert px.loc[idx[-1], "AAA"] == pytest.approx(9.5), "covered cells use the as-printed close"
    assert px.loc[idx[-1], "DELISTED"] == pytest.approx(6.0), (
        "an uncovered cell keeps the adjusted close; NaN here would have made the name ineligible")
    assert not px.isna().any().any()
    assert adv.shape == px.shape


def test_the_label_carries_the_measured_share_and_the_uncovered_names(tmp_path):
    idx = pd.bdate_range("2026-01-05", periods=30)
    raw = pd.DataFrame({"AAA": 9.5, "BBB": 19.0}, index=idx)
    P = _panel(tmp_path, raw)
    _, _, label = L.attach_eligibility_panel(P)
    assert "66.7%" in label, label                     # 2 of 3 columns covered on every row
    assert "1 of 3 names with no as-printed history" in label
    assert "contemporaneous on" in label and "the rest adjusted" in label


def test_full_coverage_is_labelled_without_qualification(tmp_path):
    idx = pd.bdate_range("2026-01-05", periods=30)
    raw = pd.DataFrame({"AAA": 9.5, "BBB": 19.0, "DELISTED": 5.9}, index=idx)
    P = _panel(tmp_path, raw)
    px, _, label = L.attach_eligibility_panel(P, require_contemporaneous=True)
    assert "100.0%" in label and "0 of 3 names" in label
    assert px.loc[idx[-1], "DELISTED"] == pytest.approx(5.9)


def test_strict_mode_refuses_partial_coverage_with_the_number(tmp_path):
    """Strict means strict: it will not call a run contemporaneous when part of it is not."""
    idx = pd.bdate_range("2026-01-05", periods=30)
    raw = pd.DataFrame({"AAA": 9.5, "BBB": 19.0}, index=idx)
    P = _panel(tmp_path, raw)
    with pytest.raises(FileNotFoundError) as e:
        L.attach_eligibility_panel(P, require_contemporaneous=True)
    assert "66.7%" in str(e.value) and "33.3%" in str(e.value)


def test_a_partially_covered_row_is_covered_cell_by_cell(tmp_path):
    """Coverage is per cell, not per name: a name that starts printing mid-panel is raw from there."""
    idx = pd.bdate_range("2026-01-05", periods=30)
    col = np.full(30, np.nan)
    col[15:] = 9.0
    raw = pd.DataFrame({"AAA": col, "BBB": 19.0, "DELISTED": 5.9}, index=idx)
    P = _panel(tmp_path, raw)
    px, _, label = L.attach_eligibility_panel(P)
    assert px.loc[idx[0], "AAA"] == pytest.approx(10.0), "before its first raw print: adjusted"
    assert px.loc[idx[-1], "AAA"] == pytest.approx(9.0), "after it: as printed"
    assert "0 of 3 names" in label, "AAA has SOME raw history, so it is not an uncovered name"
