"""TASK-404: the published ratio was never a Sharpe. These tests pin the difference.

Auto-discovered by run_all_tests.py (pytest-routed: no __main__ block).
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

from metrics import (  # noqa: E402
    annual_max_drawdown, annualised_return, drawdown_curve, max_drawdown, net_vol_ratio,
    sharpe_excess, stats, step_risk_free,
)

STEP = 5
CAL = pd.bdate_range("2020-01-01", periods=520)


def _marks(every=STEP, n=100):
    return CAL[::every][:n]


def _net(n=100, mean=0.002, sd=0.02, seed=0):
    rng = np.random.default_rng(seed)
    idx = _marks(n=n + 1)[1:]
    return pd.Series(rng.normal(mean, sd, size=len(idx)), index=idx)


def test_net_vol_ratio_is_the_old_formula_by_hand():
    r = pd.Series([0.01, -0.005, 0.02, 0.0, 0.015])
    expected = r.mean() / r.std() * np.sqrt(252 / 5)
    assert net_vol_ratio(r, STEP) == pytest.approx(float(expected))


def test_zero_risk_free_makes_the_two_ratios_identical():
    net = _net()
    rf = pd.Series(0.0, index=net.index)
    assert sharpe_excess(net, rf, STEP) == pytest.approx(net_vol_ratio(net, STEP))


def test_a_real_risk_free_moves_the_sharpe_and_the_ratio_does_not():
    """The falsifier the task asked for: feed a non-zero rate and the Sharpe MUST move."""
    net = _net()
    flat = pd.Series(0.05, index=CAL)                      # 5% annualised, decimal
    rf = step_risk_free(flat, [net.index[0] - pd.tseries.offsets.BDay(STEP), *net.index])
    ratio = net_vol_ratio(net, STEP)
    sharpe = sharpe_excess(net, rf, STEP)
    assert sharpe < ratio - 0.05, "a 5% risk-free rate has to lower the Sharpe"
    # and the old number is untouched by the rate: that is exactly the bug being labelled
    assert net_vol_ratio(net, STEP) == pytest.approx(ratio)


def test_step_risk_free_compounds_over_the_bars_of_the_step():
    flat = pd.Series(0.05, index=CAL)
    marks = _marks(n=20)
    rf = step_risk_free(flat, marks)
    one_step = (1 + 0.05 / 252.0) ** STEP - 1
    assert len(rf) == len(marks) - 1
    assert rf.iloc[0] == pytest.approx(one_step, rel=1e-9)
    assert rf.index[0] == marks[1]                          # first mark has no return


def test_forward_convention_covers_the_bars_after_the_mark():
    flat = pd.Series(0.05, index=CAL)
    marks = _marks(n=20)
    back = step_risk_free(flat, marks)
    fwd = step_risk_free(flat, marks, forward=True, step=STEP)
    assert fwd.index[0] == marks[0]                          # the lab's row dated t
    assert len(fwd) == len(marks)
    assert fwd.iloc[0] == pytest.approx(back.iloc[0], rel=1e-9)


def test_a_mark_off_the_calendar_is_an_error_not_a_silent_zero():
    flat = pd.Series(0.05, index=CAL)
    with pytest.raises(ValueError, match="not bars of the risk-free calendar"):
        step_risk_free(flat, [CAL[0], pd.Timestamp("1999-01-04")])


def test_an_empty_risk_free_series_refuses_instead_of_defaulting_to_zero():
    with pytest.raises(ValueError, match="no risk-free series"):
        step_risk_free(pd.Series(dtype=float), _marks(n=3))


def test_max_drawdown_and_annualised_return_by_hand():
    r = pd.Series([0.10, -0.20, 0.05])
    # equity 1.10, 0.88, 0.924 -> trough 0.88 from peak 1.10
    assert max_drawdown(r) == pytest.approx(-20.0)
    total = 1.10 * 0.80 * 1.05
    py = 252 / 5
    assert annualised_return(r, STEP) == pytest.approx((total ** (py / 3) - 1) * 100)


def test_max_drawdown_counts_the_capital_that_went_in():
    """A loss on the first step is measured from the money that went in, not from what is left.

    The curve used to start at 1+r[0], so the pre-first-step peak of 1.0 never existed: a book
    that fell 20% and climbed straight back to par reported a drawdown of zero.
    """
    assert max_drawdown(pd.Series([-0.20, 0.25])) == pytest.approx(-20.0)   # 1.00 -> 0.80 -> 1.00
    assert max_drawdown(pd.Series([-0.10, -0.10])) == pytest.approx(-19.0)
    assert max_drawdown(pd.Series([0.05, 0.05])) == pytest.approx(0.0)      # a book that only rises


def test_stats_says_none_instead_of_pretending_when_there_is_no_rate():
    s = stats(_net(), "no rate", STEP, rf=None)
    assert s["sharpe_excess"] is None and s["rf_ann_pct"] is None
    assert s["ratio_net_vol"] is not None


def test_stats_reports_the_rate_it_subtracted():
    net = _net()
    flat = pd.Series(0.05, index=CAL)
    rf = step_risk_free(flat, [net.index[0] - pd.tseries.offsets.BDay(STEP), *net.index])
    s = stats(net, "with rate", STEP, rf=rf)
    assert s["rf_ann_pct"] == pytest.approx(5.0, abs=0.15)
    assert s["ratio_minus_sharpe"] == pytest.approx(s["ratio_net_vol"] - s["sharpe_excess"],
                                                    abs=0.011)


# --------------------------------------------------------------- the canonical drawdown
def _two_years():
    """Dec of one year, then a year that OPENS WITH A LOSS and ends up.

    2020 closes at 1.0192; 2021's first step is -8%, then +5% and +6% take the year back above
    where it opened. The old per-year form took `cummax` of the curve AFTER the first return,
    so the peak on the first step was the post-loss equity and the year reported no drawdown
    at all. That is the case this fixture exists to catch.
    """
    idx = pd.to_datetime(["2020-12-18", "2020-12-25", "2021-01-08", "2021-01-15", "2021-01-22"])
    return pd.Series([0.04, -0.02, -0.08, 0.05, 0.06], index=idx)


def test_drawdown_curve_is_the_path_max_drawdown_minimises():
    r = pd.Series([0.10, -0.20, 0.05])
    dd = drawdown_curve(r)
    assert list(dd.round(10)) == [0.0, pytest.approx(-0.2), pytest.approx(-0.16)]
    assert max_drawdown(r) == pytest.approx(float(dd.min()) * 100)
    assert drawdown_curve(pd.Series(dtype=float)).empty


def test_drawdown_curve_floors_the_peak_at_the_capital_that_went_in():
    dd = drawdown_curve(pd.Series([-0.20, 0.25]))
    assert dd.iloc[0] == pytest.approx(-0.20), "the first step must be measured from 1.0"
    assert dd.iloc[1] == pytest.approx(0.0)


def test_annual_drawdown_makes_the_caller_name_the_peak():
    r = _two_years()
    with pytest.raises(TypeError):
        annual_max_drawdown(r, "year")               # keyword-only: no silent positional
    with pytest.raises(ValueError, match="peak must be"):
        annual_max_drawdown(r, peak="whatever")
    assert annual_max_drawdown(pd.Series(dtype=float), peak="year") == {}


def test_annual_drawdown_year_reset_sees_a_year_that_opens_with_a_loss():
    """The point of the canonicalisation: the FIRST period of the year is inside the measure."""
    out = annual_max_drawdown(_two_years(), peak="year")
    assert set(out) == {2020, 2021}
    assert out[2021] == pytest.approx(-8.0), "a year that opens -8% is 8% under water"
    assert out[2021] != 0.0
    # and the year still ends up: the drawdown is not a restatement of the return
    assert (1 + _two_years()["2021"]).prod() > 1.0
    # the old, unfloored per-year form is what this replaces
    g = _two_years()["2021"]
    eq = (1 + g).cumprod()
    assert float((eq / eq.cummax() - 1).min()) * 100 == pytest.approx(0.0)


def test_annual_drawdown_carry_keeps_the_high_struck_in_an_earlier_year():
    """2020 ends below its own high; carrying that peak makes 2021 deeper than the year read."""
    r = _two_years()
    reset = annual_max_drawdown(r, peak="year")
    carry = annual_max_drawdown(r, peak="carry")
    # 2020 peak 1.04, 2021 trough 1.04 * 0.98 * 0.92 = 0.937664 -> -9.84% from 1.04
    assert carry[2021] == pytest.approx(-9.84, abs=0.01)
    assert carry[2021] < reset[2021], "the carried peak can only be deeper, never shallower"
    assert carry[2020] == pytest.approx(reset[2020]), "the first year has nothing to carry in"
