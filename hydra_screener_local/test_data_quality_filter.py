"""apply_data_quality_filter: trailing-window |daily return| cap (TASK-335).

Filter, not scoring. A name drops iff max |r| over the last `lookback` bars
is strictly greater than `max_abs_daily_return`. Jumps outside that window
do not count (no look-ahead / no full-history scan).
"""
import numpy as np
import pandas as pd

from core.filters import apply_data_quality_filter

IDX = pd.bdate_range(end="2026-09-04", periods=400)


def _calm(n=400, start=50.0, seed=0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.01, n)
    return start * np.exp(np.cumsum(rets))


def _with_jump(base, loc, factor):
    """Multiply price at `loc` and after, so the daily return at `loc` is (factor-1)."""
    out = np.array(base, dtype=float)
    out[loc:] *= factor
    return out


def test_recent_jump_above_threshold_drops_only_that_name():
    calm = _calm()
    jumper = _with_jump(calm, loc=-1, factor=2.5)  # +150% on the last bar
    prices = pd.DataFrame({"OK": calm, "JUMP": jumper}, index=IDX)
    out = apply_data_quality_filter(prices, max_abs_daily_return=1.0, lookback=252)
    assert "OK" in out.columns
    assert "JUMP" not in out.columns


def test_negative_jump_also_drops():
    # |r| is what counts. A -60% day exceeds a 50% cap; a calm name does not.
    calm = _calm(seed=1)
    crash = _with_jump(calm, loc=-5, factor=0.4)
    prices = pd.DataFrame({"OK": calm, "CRASH": crash}, index=IDX)
    out = apply_data_quality_filter(prices, max_abs_daily_return=0.5, lookback=252)
    assert "OK" in out.columns
    assert "CRASH" not in out.columns


def test_jump_exactly_at_threshold_is_kept():
    # Strictly greater than: |r| == 1.0 stays. Last close = 2x previous close.
    calm = _calm(seed=2)
    edge = np.array(calm, dtype=float)
    edge[-1] = edge[-2] * 2.0
    prices = pd.DataFrame({"EDGE": edge}, index=IDX)
    out = apply_data_quality_filter(prices, max_abs_daily_return=1.0, lookback=252)
    assert "EDGE" in out.columns


def test_old_jump_outside_trailing_window_is_kept():
    """No look-ahead / no full-history scan: a +150% jump 300 bars ago must survive lookback=252."""
    calm = _calm(seed=3)
    # loc=50 is 350 bars before the last bar (400-1-50=349) — well outside 252.
    old = _with_jump(calm, loc=50, factor=3.0)
    prices = pd.DataFrame({"OLDJUMP": old, "CALM": calm}, index=IDX)
    out = apply_data_quality_filter(prices, max_abs_daily_return=1.0, lookback=252)
    assert list(out.columns) == ["OLDJUMP", "CALM"]


def test_old_jump_is_dropped_when_lookback_covers_it():
    calm = _calm(seed=4)
    old = _with_jump(calm, loc=50, factor=3.0)
    prices = pd.DataFrame({"OLDJUMP": old}, index=IDX)
    out = apply_data_quality_filter(prices, max_abs_daily_return=1.0, lookback=400)
    assert "OLDJUMP" not in out.columns


def test_jump_just_inside_window_is_dropped():
    calm = _calm(seed=5)
    # last 252 bars of a 400-row frame start at index 148. Put the jump at 148.
    inside = _with_jump(calm, loc=len(IDX) - 252, factor=2.5)
    prices = pd.DataFrame({"INSIDE": inside}, index=IDX)
    out = apply_data_quality_filter(prices, max_abs_daily_return=1.0, lookback=252)
    assert "INSIDE" not in out.columns


def test_empty_passthrough():
    out = apply_data_quality_filter(pd.DataFrame())
    assert out.empty


def test_all_nan_column_is_kept():
    prices = pd.DataFrame({"NAN": np.nan, "OK": _calm()}, index=IDX)
    out = apply_data_quality_filter(prices, max_abs_daily_return=1.0, lookback=252)
    assert "NAN" in out.columns
    assert "OK" in out.columns


def test_inf_return_from_zero_price_is_dropped():
    calm = _calm(seed=6)
    bad = calm.copy()
    bad[len(bad) - 10] = 0.0
    bad[len(bad) - 9] = 10.0  # 0 → 10 is inf
    prices = pd.DataFrame({"ZEROINF": bad, "OK": calm}, index=IDX)
    out = apply_data_quality_filter(prices, max_abs_daily_return=1.0, lookback=252)
    assert "ZEROINF" not in out.columns
    assert "OK" in out.columns
