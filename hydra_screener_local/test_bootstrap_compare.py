"""TASK-332: bootstrap helpers. Auto-discovered by run_all_tests.py."""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

from bootstrap_compare import summarise_diff, expected_max_sharpe, ann_net


def test_identical_series_interval_contains_zero():
    rng = np.random.default_rng(1)
    x = rng.normal(0.001, 0.02, size=400)
    s = summarise_diff(x, x, step=5, label="zero", rng=rng)
    assert s["d_ann_p05"] <= 0 <= s["d_ann_p95"]
    assert s["p_le_prod"] > 0.3


def test_shifted_series_excludes_zero():
    rng = np.random.default_rng(2)
    x = rng.normal(0.002, 0.015, size=400)
    y = x - 0.004
    s = summarise_diff(x, y, step=5, label="shift", rng=rng)
    assert s["d_ann_p05"] > 0
    assert s["p_le_prod"] < 0.05


def test_ann_net_zero_is_zero():
    assert abs(ann_net(np.zeros(50), 5)) < 1e-12


def test_expected_max_sharpe_positive_and_corr_reduces():
    d = expected_max_sharpe(38, 500, step=5, rho=0.7)
    assert d["e_max_sr_independent"] > d["e_max_sr_correlated"] > 0
    assert d["n_eff"] < 38
