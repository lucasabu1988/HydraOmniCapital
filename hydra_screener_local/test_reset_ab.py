"""TASK-409: the paired bootstrap actually pairs, and the verdict rule is written down.

The first test is the regression against the defect `fix/astra-07` found in TASK-332: a series
compared with ITSELF must give a zero-width interval, not +-0.85. Auto-discovered by
run_all_tests.py (pytest-routed: no __main__ block).
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

from reset_ab import BLOCK, block_index_matrix, paired_difference, verdict  # noqa: E402

STEP = 5


def _series(n=400, mean=0.002, sd=0.02, seed=0):
    idx = pd.bdate_range("2005-01-03", periods=n * STEP, freq="B")[::STEP]
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(mean, sd, size=len(idx)), index=idx)


def _rf(idx, annual=0.02):
    return pd.Series((1 + annual / 252.0) ** STEP - 1, index=idx)


def test_a_series_against_itself_gives_a_zero_interval():
    """The TASK-332 defect, as a regression: paired means paired."""
    a = _series()
    d = paired_difference(a, a, _rf(a.index), rng=np.random.default_rng(1), n=300)
    assert d["d_ann_pp"] == 0.0
    assert d["d_ann_p05"] == 0.0 and d["d_ann_p95"] == 0.0
    assert d["d_sharpe"] == 0.0
    assert d["d_sharpe_p05"] == 0.0 and d["d_sharpe_p95"] == 0.0
    assert d["mean_step_diff_bp"] == 0.0


def test_a_constant_edge_separates_from_zero():
    a = _series()
    b = a - 0.004
    d = paired_difference(a, b, _rf(a.index), rng=np.random.default_rng(2), n=300)
    assert d["d_ann_pp"] > 0
    assert d["d_ann_p05"] > 0
    assert d["p_a_le_b"] < 0.05
    assert "FULL WEEKLY RESET WINS" in verdict(d)


def test_a_worse_series_is_called_for_the_other_side():
    a = _series()
    b = a + 0.004
    d = paired_difference(a, b, _rf(a.index), rng=np.random.default_rng(3), n=300)
    assert d["d_ann_pp"] < 0
    assert "PAIR RESET WINS" in verdict(d)


def test_noise_is_reported_as_indistinguishable_not_as_a_winner():
    a = _series(seed=4)
    b = _series(seed=5)
    d = paired_difference(a, b, _rf(a.index), rng=np.random.default_rng(6), n=400)
    v = verdict(d)
    assert ("INDISTINGUISHABLE" in v) or ("MIXED" in v)


def test_the_risk_free_leg_is_subtracted_from_both_sides():
    a = _series(seed=7)
    b = _series(seed=8)
    idx = a.index
    low = paired_difference(a, b, _rf(idx, 0.0), rng=np.random.default_rng(9), n=200)
    high = paired_difference(a, b, _rf(idx, 0.10), rng=np.random.default_rng(9), n=200)
    # a common risk-free leg cancels in the DIFFERENCE of Sharpes only if the vols match; what must
    # hold is that each side's own Sharpe moves down when the rate goes up
    assert high["a_sharpe"] < low["a_sharpe"]
    assert high["b_sharpe"] < low["b_sharpe"]


def test_block_index_matrix_stays_inside_the_series_and_keeps_blocks_contiguous():
    idx = block_index_matrix(100, block=13, n=50, rng=np.random.default_rng(0))
    assert idx.shape == (50, 100)
    assert idx.min() >= 0 and idx.max() < 100
    row = idx[0]
    # inside a block the positions increase by one; a jump only happens at block boundaries
    steps = np.diff(row[:13])
    assert (steps == 1).all()


def test_a_series_shorter_than_a_block_is_an_error():
    a = _series(n=5)
    with pytest.raises(ValueError, match="not enough for a"):
        paired_difference(a, a, _rf(a.index), n=10)
    with pytest.raises(ValueError, match="shorter than one block"):
        block_index_matrix(BLOCK - 1)


def test_only_common_dates_are_compared():
    a = _series(n=200, seed=10)
    b = a.iloc[50:]
    d = paired_difference(a, b, _rf(a.index), rng=np.random.default_rng(11), n=200)
    assert d["n"] == len(b)
    assert d["first"] == str(b.index[0].date())


def test_the_published_mix_already_had_cash_at_the_t_bill():
    """The finding TASK-409 produced: SPEC 9.5 blamed a confound that was not there.

    `P_5050` in the audit pickle is `mix(T20_cy + ETF)` to machine precision, so the lab's stock
    sleeve DID earn the T-bill. Skips on a machine without the lab cache; on this one it is the
    guard that keeps the corrected spec sentence honest.
    """
    import sleeve_lab as S
    from reset_ab import AUDIT_STEPS, load_lab

    if not os.path.exists(AUDIT_STEPS):
        pytest.skip("no audit_steps.pkl on this machine")
    lab = load_lab()
    p5050 = lab["P_5050"]["net"]
    with_tbill = S.mix([lab["T20_cy"], lab["ETF"]], "equal")["net"]
    without = S.mix([lab["T20"], lab["ETF"]], "equal")["net"]
    assert float((with_tbill - p5050).abs().max()) == 0.0
    assert float((without - p5050).abs().max()) > 1e-6
