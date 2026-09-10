"""H-015 — SLOW identity with production, FAST, the forward excess, the per-date statistic and the rule."""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import h015_fast_confirmation as H  # noqa: E402
import sleeve_lab as S  # noqa: E402

IDX = pd.bdate_range("2004-01-01", periods=700)


def _panel(seed=9):
    rng = np.random.default_rng(seed)
    drifts = np.linspace(-0.0004, 0.0012, len(S.UNIVERSE))
    rets = pd.DataFrame(rng.normal(0.0, 0.004, (len(IDX), len(S.UNIVERSE))) + drifts, index=IDX, columns=S.UNIVERSE)
    px = 100.0 * (1 + rets).cumprod()
    irx = pd.Series(0.03, index=IDX)
    return px, irx


def test_slow_is_production_s_rule_identically():
    """The harness must not re-implement the 12-month rule: same numbers as sleeve_lab.run_sleeve's target."""
    px, irx = _panel()
    slow = H.slow_signal(px, irx)
    t = 400
    tb12 = (irx / 252.0).rolling(252).sum().iloc[t]
    mom12 = (px / px.shift(252) - 1).iloc[t]
    assert np.allclose(slow.iloc[t].to_numpy(), (mom12 - tb12).to_numpy())
    on_sleeve = (mom12 - tb12) > 0
    assert ((slow.iloc[t] > 0) == on_sleeve).all()


def test_fast_is_the_same_convention_over_21_bars():
    px, irx = _panel()
    fast = H.fast_signal(px, irx)
    t = 400
    tb21 = (irx / 252.0).rolling(21).sum().iloc[t]
    mom21 = (px / px.shift(21) - 1).iloc[t]
    assert np.allclose(fast.iloc[t].to_numpy(), (mom21 - tb21).to_numpy())
    assert fast.iloc[20].isna().all() and fast.iloc[21].notna().all()


def test_forward_excess_is_next_close_to_close_plus_20_minus_the_t_bill_accrued_in_between():
    px, irx = _panel()
    t = 300
    ex = H.forward_excess(px, irx, t)
    r = px["SPY"].iloc[321] / px["SPY"].iloc[301] - 1.0
    rf = float((irx / 252.0).iloc[302:322].sum())          # 20 accrual bars, t+2 .. t+21
    assert ex["SPY"] == pytest.approx(r - rf)
    assert rf == pytest.approx(0.03 / 252.0 * 20)
    assert H.forward_excess(px, irx, len(px) - 5) is None


def test_step_row_splits_confirmed_and_correction_and_weighs_a_date_once():
    px, irx = _panel()
    slow, fast = H.slow_signal(px, irx), H.fast_signal(px, irx)
    t = 400
    slow2, fast2 = slow.copy(), fast.copy()
    slow2.iloc[t] = 0.1                                    # everyone ON
    fast2.iloc[t] = 0.05
    fast2.iloc[t, :3] = -0.01                              # three in CORRECTION
    row = H.step_row(px, slow2, fast2, irx, t)
    assert row["on"] == 10 and row["n_correction"] == 3 and row["n_confirmed"] == 7 and row["has_correction"]
    ex = H.forward_excess(px, irx, t)
    assert row["correction_excess"] == pytest.approx(float(ex.iloc[:3].mean()))
    assert row["confirmed_excess"] == pytest.approx(float(ex.iloc[3:].mean()))
    slow2.iloc[t] = -0.1                                   # nobody ON -> outside the hypothesis
    assert H.step_row(px, slow2, fast2, irx, t)["on"] == 0


def test_summarise_and_verdict_follow_the_pre_registered_rule():
    n = 120
    base = {"date": pd.bdate_range("2009-01-05", periods=n), "eligible": 10, "on": 7,
            "n_correction": 2, "n_confirmed": 5, "has_correction": True, "confirmed_excess": 0.004}
    rng = np.random.default_rng(3)
    dies = pd.DataFrame({**base, "correction_excess": rng.normal(-0.006, 0.006, n)})
    s = H.summarise(dies, n=500)
    assert s["correction_dates"] == n and s["correction_excess_bp"] < 0 and s["ci_p95"] < 0
    assert H.verdict(s).startswith("C_bar < 0 with the 90 % upper bound below zero")
    still_beats_cash = pd.DataFrame({**base, "correction_excess": rng.normal(0.003, 0.006, n)})
    assert H.verdict(H.summarise(still_beats_cash, n=500)).startswith("REJECTED: CORRECTION ETFs still beat")
    weak = pd.DataFrame({**base, "correction_excess": rng.normal(-0.0005, 0.01, n)})
    v = H.verdict(H.summarise(weak, n=500))
    assert v.startswith("REJECTED")
    few = dies.iloc[:10]
    assert H.verdict(H.summarise(few, n=500)).startswith("UNMEASURABLE")
