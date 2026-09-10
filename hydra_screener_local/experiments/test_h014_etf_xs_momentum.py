"""H-014 — the signals, the median split, the coverage gate and the rule on synthetic data. No network."""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import h014_etf_xs_momentum as H  # noqa: E402
import sleeve_lab as S  # noqa: E402

IDX = pd.bdate_range("2004-01-01", periods=700)


def _panel(seed=5):
    """Ten ETFs with distinct constant drifts, so ABS ranks them in a known order, plus a flat T-bill."""
    rng = np.random.default_rng(seed)
    drifts = np.linspace(-0.0004, 0.0012, len(S.UNIVERSE))          # some below the T-bill, some above
    rets = pd.DataFrame(rng.normal(0.0, 0.002, (len(IDX), len(S.UNIVERSE))) + drifts, index=IDX, columns=S.UNIVERSE)
    px = 100.0 * (1 + rets).cumprod()
    irx = pd.Series(0.02, index=IDX)                                    # 2 % annualised, flat
    return px, irx, drifts


def test_abs_is_b0s_rule_bit_for_bit():
    px, irx, _ = _panel()
    a = H.abs_signal(px, irx)
    t = 400
    tb12 = (irx / 252.0).rolling(252).sum().iloc[t]
    mom = px.iloc[t] / px.iloc[t - 252] - 1.0
    assert np.allclose(a.iloc[t].to_numpy(), (mom - tb12).to_numpy())
    assert a.iloc[251].isna().all() and a.iloc[252].notna().all()      # exactly 252 bars needed
    # the ETF with the highest drift is the most active; the lowest drifts fall below the T-bill
    assert a.iloc[t].idxmax() == S.UNIVERSE[-1]
    assert (a.iloc[t] > 0).sum() < len(S.UNIVERSE)


def test_forward_return_is_t_plus_1_close_to_t_plus_21_close():
    px, _, _ = _panel()
    t = 300
    f = H.forward_return(px, t)
    assert f["SPY"] == pytest.approx(px["SPY"].iloc[321] / px["SPY"].iloc[301] - 1.0)
    assert H.forward_return(px, len(px) - 10) is None


def test_median_split_drops_the_middle_name_when_odd_and_keeps_halves_equal():
    cs = pd.Series({"A": 5.0, "B": 4.0, "C": 3.0, "D": 2.0, "E": 1.0})
    high, low = H.split_halves(cs)
    assert high == ["A", "B"] and low == ["D", "E"]                    # C left out of both
    cs6 = pd.Series({"A": 6.0, "B": 5.0, "C": 4.0, "D": 3.0, "E": 2.0, "F": 1.0})
    high, low = H.split_halves(cs6)
    assert high == ["A", "B", "C"] and low == ["D", "E", "F"]


def test_a_date_with_fewer_than_four_active_etfs_is_not_comparable():
    px, irx, _ = _panel()
    a = H.abs_signal(px, irx)
    a2 = a.copy()
    a2.iloc[400] = -1.0
    a2.iloc[400, :3] = 1.0                                              # only three active
    assert H.step_row(px, a2, 400)["comparable"] is False
    a2.iloc[400, :4] = 1.0
    row = H.step_row(px, a2, 400)
    assert row["comparable"] is True and len(row["high_names"]) == 2 and len(row["low_names"]) == 2


def test_coverage_gate_and_rule():
    px, irx, _ = _panel()
    df, cov = H.collect(px, irx, dev_only=False)
    assert cov["universe_available_from"] == str(IDX[252].date())
    assert 0.0 <= cov["coverage"] <= 1.0
    good = pd.DataFrame({"date": pd.bdate_range("2009-01-05", periods=150), "comparable": True, "active": 6,
                         "cs_high": 0.2, "cs_low": 0.05,
                         "high": np.random.default_rng(1).normal(0.010, 0.01, 150),
                         "low": np.random.default_rng(2).normal(0.002, 0.01, 150)})
    s = H.summarise(good, n=500)
    assert s["spread_bp"] > 0 and s["spread_p05"] > 0
    assert H.verdict(s, {"coverage": 0.9}).startswith("PREDICTED SIGN")
    assert H.verdict(s, {"coverage": 0.4, "universe_available_from": "2007-01-01"}).startswith("UNMEASURABLE")
    s_neg = dict(s, spread_bp=-1.0)
    assert H.verdict(s_neg, {"coverage": 0.9}).startswith("REJECTED")
    s_weak = dict(s, spread_p05=-0.5)
    assert H.verdict(s_weak, {"coverage": 0.9}).startswith("REJECTED")
    assert H.verdict({"comparable_dates": 0}, {"coverage": 0.9}) == "NO DATA"
