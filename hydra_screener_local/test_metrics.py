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
    annualised_return, max_drawdown, net_vol_ratio, sharpe_excess, stats, step_risk_free,
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
