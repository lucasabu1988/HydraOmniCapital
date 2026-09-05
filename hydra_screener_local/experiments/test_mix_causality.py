"""Audit finding E: sleeve-mix weights may only use information available before the step, and
moving capital between sleeves costs money.

Run: python -m pytest experiments/test_mix_causality.py -q
"""
import numpy as np
import pandas as pd
import pytest

from sleeve_lab import mix


def _sleeves(seed=0, n=200):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2010-01-01", periods=n, freq="7D")
    a = pd.DataFrame({"net": rng.normal(0.002, 0.02, n)}, index=idx)
    b = pd.DataFrame({"net": rng.normal(0.001, 0.01, n)}, index=idx)
    return a, b


def test_risk_parity_weight_does_not_depend_on_the_step_it_applies_to():
    a, b = _sleeves()
    base = mix([a, b], "rp", lookback=20)
    i = 120
    a2 = a.copy(); a2.iloc[i, 0] = 0.5                        # a huge return IN step i (and only there)
    shocked = mix([a2, b], "rp", lookback=20)
    # weights up to and including step i are identical: the shock is not yet observable
    pd.testing.assert_frame_equal(base[["w_0", "w_1"]].iloc[: i + 1], shocked[["w_0", "w_1"]].iloc[: i + 1])
    # ... and the weight for step i+1 does react (the shock is now in the trailing window)
    assert shocked["w_0"].iloc[i + 1] < base["w_0"].iloc[i + 1]
    # equal-weight mix is untouched by construction
    pd.testing.assert_frame_equal(mix([a, b], "equal")[["w_0", "w_1"]], mix([a2, b], "equal")[["w_0", "w_1"]])


def test_reallocation_and_drift_rebalance_are_charged():
    a, b = _sleeves()
    eq = mix([a, b], "equal", cost_bp=10.0)
    assert (eq["realloc_cost"].iloc[1:] > 0).all()            # every weekly reset of a drifted 50/50 trades
    free = mix([a, b], "equal", cost_bp=0.0)
    assert (free["realloc_cost"] == 0).all()
    assert (free["net"] - eq["net"]).sum() > 0
    # hand check on step 1: drifted weights after step 0, reset to 50/50, one-way |dw|/2, two sides
    g = np.array([0.5 * (1 + a["net"].iloc[0]), 0.5 * (1 + b["net"].iloc[0])])
    drift = g / g.sum()
    expect = abs(drift - 0.5).sum() / 2 * 2 * 10 / 10000
    assert eq["realloc_cost"].iloc[1] == pytest.approx(expect)


def test_weights_sum_to_one_and_respect_clip():
    a, b = _sleeves(1)
    rp = mix([a, b], "rp", lookback=20, clip=(0.2, 0.8))
    assert np.allclose(rp["w_0"] + rp["w_1"], 1.0)
    assert rp["w_0"].between(0.2, 0.8).all()
