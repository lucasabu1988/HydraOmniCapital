"""TASK-411 (a): the accounting clock, pinned on synthetic series.

The engine arms in `stale_policy_ab.py` need the panel and take minutes; what has to be exactly
right is cheap to test on its own: the fill is production's fill, and a fill inside the window
resets the clock and delays the write-off. Every test here fails if that stops being true.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import stale_policy_ab as A  # noqa: E402
from data.fetch import FFILL_LIMIT_BARS  # noqa: E402

N = np.nan


def test_fill_is_the_production_fill():
    """Gaps up to FFILL_LIMIT_BARS are filled; the bar after the limit stays NaN."""
    close = pd.DataFrame({"AAA": [10.0] + [N] * (FFILL_LIMIT_BARS + 1) + [11.0]})
    out = A.fill_like_production(close)["AAA"]
    assert out.iloc[1:1 + FFILL_LIMIT_BARS].tolist() == [10.0] * FFILL_LIMIT_BARS
    assert np.isnan(out.iloc[1 + FFILL_LIMIT_BARS])
    assert out.iloc[-1] == 11.0


def test_write_off_lands_on_the_limit_bar():
    prices = [10.0] + [N] * 12
    assert A.write_off_step(prices, max_stale_bars=10) == 10
    assert A.write_off_step([10.0] * 13, max_stale_bars=10) is None


def test_a_fill_inside_the_window_delays_the_write_off():
    """The finding itself: one invented price buys the name ten more bars."""
    raw = [10.0] + [N] * 20
    filled = A.fill_like_production(pd.DataFrame({"AAA": raw}))["AAA"].tolist()
    observed = A.write_off_step(raw, max_stale_bars=10)
    production = A.write_off_step(filled, max_stale_bars=10)
    assert observed == 10
    assert production is not None and production > observed
    assert production - observed == FFILL_LIMIT_BARS


def test_a_print_between_two_gaps_restarts_the_count_in_both_arms():
    """One real print at bar 2, then a long hole: the fill only buys the limit, and the two
    arms disagree by exactly that."""
    raw = [10.0, N, 10.5] + [N] * 12
    filled = A.fill_like_production(pd.DataFrame({"AAA": raw}))["AAA"].tolist()
    assert A.fill_carried_bars(raw, filled) == 1 + FFILL_LIMIT_BARS
    assert A.write_off_step(raw, max_stale_bars=10) == 12
    assert A.write_off_step(filled, max_stale_bars=10) is None   # ran out of series first


def test_carried_bars_are_the_ageing_the_fill_erased():
    raw = [10.0, N, N, N, N, N, N]
    filled = A.fill_like_production(pd.DataFrame({"AAA": raw}))["AAA"].tolist()
    assert A.fill_carried_bars(raw, filled) == FFILL_LIMIT_BARS   # bars 1..3
    assert A.fill_carried_bars(raw, raw) == 0


def test_a_name_that_never_prints_is_not_rescued_by_the_fill():
    """ffill has nothing to carry, so both arms agree — the effect needs a prior print."""
    raw = [N] * 15
    filled = A.fill_like_production(pd.DataFrame({"AAA": raw}))["AAA"].tolist()
    assert A.fill_carried_bars(raw, filled) == 0
    assert A.write_off_step(raw, max_stale_bars=10) == A.write_off_step(filled, max_stale_bars=10)
