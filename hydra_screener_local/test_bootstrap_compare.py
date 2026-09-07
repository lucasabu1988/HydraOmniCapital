"""TASK-332: bootstrap helpers. Auto-discovered by run_all_tests.py.

ASTRA-07 (2026-09-06) added the algebraic controls. They are algebra, not
tolerance checks: if the interval does not estimate the statistic the point
estimate reports, the identities below break. Do not relax them into
inequalities -- an inequality is exactly what hid the defect for a week
(test_identical_series_interval_contains_zero passed the whole time).
"""
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

from bootstrap_compare import (
    _compound_prod_to_f1,
    ann_net,
    block_index_matrix,
    expected_max_sharpe,
    summarise_diff,
)


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


# --------------------------------------------------------------- ASTRA-07 probes
# Ported verbatim from the external audit
# (Auditoria-Hydra-2026-09-06/test_adversarial.py). Both failed on main at
# 1c21bc4: the self-comparison returned d_sharpe_p05/p95 = -0.850 / +0.852
# around an exact zero, and the constant pair returned a point estimate of
# 106.18 pp beside a degenerate 65.12 / 65.12 "interval".

def test_paired_sharpe_identical_series_is_exactly_zero():
    x = np.random.default_rng(7).normal(.001, .02, 400)
    r = summarise_diff(x, x, 5, 'self', np.random.default_rng(0))
    assert r['d_sharpe_p05'] == r['d_sharpe_p95'] == 0., r


def test_cagr_interval_estimates_difference_of_cagrs():
    a, b = np.full(104, .02), np.full(104, .01)
    r = summarise_diff(a, b, 5, 'constant', np.random.default_rng(0))
    assert r['d_ann_p05'] == r['d_ann_net_pp'] == r['d_ann_p95'], r


# ------------------------------------------------------- regression guards (fix)

def test_one_index_matrix_is_applied_to_both_series():
    """The pairing must be structural, not a property of the input.

    Two series that differ everywhere but have the same VALUE SET per block
    still cannot be told apart by an unpaired bootstrap. This instead pins the
    mechanism: resampling b on a's index matrix must reproduce, replicate by
    replicate, exactly the differences summarise_diff reports.
    """
    rng = np.random.default_rng(11)
    a = rng.normal(0.002, 0.02, size=200)
    b = rng.normal(0.001, 0.03, size=200)
    seed = 5
    got = summarise_diff(a, b, step=5, label="mech", rng=np.random.default_rng(seed), n=300)
    idx = block_index_matrix(len(a), n=300, rng=np.random.default_rng(seed))
    assert idx.shape == (300, 200)
    from bootstrap_compare import sharpe
    want = np.array([sharpe(a[i], 5) - sharpe(b[i], 5) for i in idx])
    assert round(float(np.percentile(want, 5)), 3) == got["d_sharpe_p05"]
    assert round(float(np.percentile(want, 95)), 3) == got["d_sharpe_p95"]


def test_point_estimate_lies_inside_its_own_interval():
    """The pre-fix module could put the point estimate outside the interval.

    That is what the published F1-PROD row did (+1.74 pp against a "90% CI" of
    [-1.96, +1.89]). A percentile interval of a statistic whose sample value is
    the point estimate cannot exclude it on a stationary series.
    """
    rng = np.random.default_rng(3)
    a = rng.normal(0.003, 0.02, size=300)
    b = rng.normal(0.001, 0.02, size=300)
    s = summarise_diff(a, b, step=5, label="inside", rng=rng, n=1000)
    assert s["d_ann_p05"] <= s["d_ann_net_pp"] <= s["d_ann_p95"], s
    assert s["d_sharpe_p05"] <= s["d_sharpe"] <= s["d_sharpe_p95"], s


def test_summarise_diff_rejects_misaligned_series():
    rng = np.random.default_rng(4)
    try:
        summarise_diff(np.zeros(100), np.zeros(99), step=5, label="bad", rng=rng)
    except ValueError:
        return
    raise AssertionError("misaligned series must not be bootstrapped as a pair")


# ------------------------------------------------- ASTRA-07 alignment (PROBABLE)
# Astra flagged _compound_prod_to_f1 as PROBABLE but did not prove it. These two
# impulse tests are the proof. redesign_lab.run* stamps each record with
# date=idx[t] and fills it with the return earned from t+lag to t+lag+hold, i.e.
# every label is FORWARD-looking, so the PROD legs of the F1 window opening at d
# are [d, next_f1_date). The misalignment is REAL: the old (d, nxt] rule put a
# single-step impulse one PROD step (5 bars) EARLY, into the preceding F1 window.

def _f1_grid():
    days = pd.bdate_range("2020-01-02", periods=40)
    prod_dates = days[::5][:6]      # t = 0 5 10 15 20 25
    f1_dates = days[::10][:3]       # t = 0 10 20
    return prod_dates, f1_dates


def _old_rule(prod, f1):
    """The pre-ASTRA-07 window, kept here only as the counter-example."""
    out, f1_dates = [], list(f1.index)
    for i, d in enumerate(f1_dates):
        nxt = f1_dates[i + 1] if i + 1 < len(f1_dates) else None
        chunk = prod[prod.index > d]
        if nxt is not None:
            chunk = chunk[chunk.index <= nxt]
        out.append(np.nan if chunk.empty else float((1 + chunk).prod() - 1))
    return pd.Series(out, index=f1.index)


def test_compound_prod_to_f1_places_impulse_in_the_window_that_opens_it():
    prod_dates, f1_dates = _f1_grid()
    prod = pd.Series(0.0, index=prod_dates)
    prod.loc[prod_dates[2]] = 0.07          # the leg that OPENS f1_dates[1]
    got = _compound_prod_to_f1(prod, pd.Series(0.0, index=f1_dates))
    assert got.notna().all(), got
    assert abs(got.loc[f1_dates[1]] - 0.07) < 1e-12, got
    assert abs(got.loc[f1_dates[0]]) < 1e-12, got
    assert abs(got.loc[f1_dates[2]]) < 1e-12, got


def test_old_compound_rule_was_one_prod_step_early():
    """Evidence for the finding, not a specification of the old behaviour."""
    prod_dates, f1_dates = _f1_grid()
    prod = pd.Series(0.0, index=prod_dates)
    prod.loc[prod_dates[2]] = 0.07
    old = _old_rule(prod, pd.Series(0.0, index=f1_dates))
    assert abs(old.loc[f1_dates[0]] - 0.07) < 1e-12, old   # one window EARLY
    assert abs(old.loc[f1_dates[1]]) < 1e-12, old


def test_compound_prod_to_f1_drops_the_first_leg_no_more():
    """The impulse on the very first PROD leg used to leave the sample entirely."""
    prod_dates, f1_dates = _f1_grid()
    prod = pd.Series(0.0, index=prod_dates)
    prod.loc[prod_dates[0]] = 0.05
    got = _compound_prod_to_f1(prod, pd.Series(0.0, index=f1_dates))
    assert abs(got.loc[f1_dates[0]] - 0.05) < 1e-12, got
    old = _old_rule(prod, pd.Series(0.0, index=f1_dates))
    assert abs(old.sum()) < 1e-12, old      # 5% of return silently vanished


def test_trailing_f1_window_without_a_right_edge_is_dropped():
    """PROD runs past the last F1 label; that tail is not a 10-bar F1 window."""
    days = pd.bdate_range("2020-01-02", periods=60)
    prod = pd.Series(0.01, index=days[::5][:8])     # t = 0 .. 35
    f1 = pd.Series(0.0, index=days[::10][:3])       # t = 0 10 20
    got = _compound_prod_to_f1(prod, f1)
    assert np.isnan(got.iloc[-1]), got              # 4 legs available, wants 2
    assert abs(got.iloc[0] - (1.01 ** 2 - 1)) < 1e-12, got
    old = _old_rule(prod, f1)
    assert abs(old.iloc[-1] - (1.01 ** 3 - 1)) < 1e-12, old   # 3 legs vs 2: over-covered
