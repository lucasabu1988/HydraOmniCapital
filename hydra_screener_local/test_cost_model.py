"""TASK-327: size-aware cost curve. Auto-discovered by run_all_tests.py."""
import math
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

from cost_model import cost_bp_per_side, size_aware_net, _net_from_turnover


def test_flat_ignores_adv():
    assert cost_bp_per_side(1e9, 100, curve="flat", flat_bp=10) == 10.0
    assert cost_bp_per_side(1.0, 5, curve="flat", flat_bp=10) == 10.0


def test_nv2016_knots():
    assert cost_bp_per_side(50_000_000, curve="nv2016") == 5.0
    assert cost_bp_per_side(5_000_000, curve="nv2016") == 20.0
    assert cost_bp_per_side(500_000, curve="nv2016") == 50.0
    assert cost_bp_per_side(0, curve="nv2016") == 50.0
    assert cost_bp_per_side(float("nan"), curve="nv2016") == 50.0
    mid = cost_bp_per_side(math.sqrt(50e6 * 5e6), curve="nv2016")
    assert 5.0 < mid < 20.0


def test_flat_10_matches_harness_formula():
    ret, turnover, n = 0.01, 0.4, 10
    entered = {f"T{i}" for i in range(4)}  # 4/10 = 0.4
    adv = {t: 1e9 for t in entered}
    px = {t: 50.0 for t in entered}
    net, mean_bp = size_aware_net(ret, entered, n, adv, px, curve="flat", flat_bp=10)
    assert mean_bp == 10.0
    assert abs(net - _net_from_turnover(ret, turnover, 10)) < 1e-15
    assert abs(net - (ret - 2 * 10 / 10000 * turnover)) < 1e-15


def test_zero_turnover_net_equals_gross():
    net, mean_bp = size_aware_net(0.02, set(), 8, {}, {}, curve="nv2016")
    assert net == 0.02
    assert mean_bp == 0.0


def test_illiquid_names_cost_more_than_liquid():
    entered = {"LIQ", "ILL"}
    adv = {"LIQ": 200_000_000, "ILL": 100_000}
    px = {"LIQ": 80.0, "ILL": 8.0}
    net_flat, _ = size_aware_net(0.01, entered, 2, adv, px, curve="flat", flat_bp=10)
    net_sz, mean_bp = size_aware_net(0.01, entered, 2, adv, px, curve="nv2016")
    assert mean_bp > 10.0
    assert net_sz < net_flat
