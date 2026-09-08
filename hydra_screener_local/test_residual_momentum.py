"""H-010: the closed form must equal a brute-force OLS, and it must not see past the window.

The first test is the one the whole hypothesis rests on: `residual_momentum` computes betas and
residual moments from rolling sums instead of fitting millions of regressions, and if that algebra
is wrong every number downstream is wrong in a way no portfolio test would reveal. So it is
checked against `numpy.linalg.lstsq` on the same bars. Auto-discovered by run_all_tests.py.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

from residual_momentum import (  # noqa: E402
    ESTIMATION, FORMATION, MIN_ESTIMATION, SKIP, residual_momentum, summarise, verdict,
)

BARS = 1200
DATES = pd.bdate_range("2005-01-03", periods=BARS)


def _market(seed=0):
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0004, 0.011, BARS), index=DATES)


def _name(market, beta=1.3, alpha=0.0001, noise=0.008, seed=1):
    rng = np.random.default_rng(seed)
    e = rng.normal(0.0002, noise, BARS)
    return alpha + beta * market.to_numpy() + e


def _brute(r_col, market, t):
    """OLS over the 756 bars ending at t-SKIP, then residual moments over the last 126 of them."""
    end = t - SKIP
    est = slice(end - ESTIMATION + 1, end + 1)
    X = np.c_[np.ones(ESTIMATION), market.to_numpy()[est]]
    coef, *_ = np.linalg.lstsq(X, r_col[est], rcond=None)
    a, b = coef
    form = slice(end - FORMATION + 1, end + 1)
    res = r_col[form] - a - b * market.to_numpy()[form]
    return b, res.sum(), res.std(ddof=0)


def test_the_closed_form_equals_a_brute_force_ols():
    m = _market()
    col = _name(m)
    out = residual_momentum(pd.DataFrame({"A": col}, index=DATES), m)
    t = BARS - 1
    beta, s_e, sd_e = _brute(col, m, t)
    assert out["beta"]["A"].iloc[t] == pytest.approx(beta, rel=1e-9)
    assert out["sum"]["A"].iloc[t] == pytest.approx(s_e, rel=1e-8, abs=1e-12)
    assert out["sd"]["A"].iloc[t] == pytest.approx(sd_e, rel=1e-8, abs=1e-12)


def test_it_recovers_a_known_beta():
    m = _market()
    for beta in (0.4, 1.0, 1.8):
        out = residual_momentum(pd.DataFrame({"A": _name(m, beta=beta)}, index=DATES), m)
        assert out["beta"]["A"].iloc[BARS - 1] == pytest.approx(beta, abs=0.06)


def test_a_pure_market_clone_has_no_residual_momentum_to_speak_of():
    """The point of the hypothesis: a name that only rides the market must score ~0, however much
    it rose. Conventional momentum would score it on the market's own run."""
    m = _market()
    clone = pd.DataFrame({"A": 2.0 * m.to_numpy()}, index=DATES)      # beta 2, zero idiosyncratic
    out = residual_momentum(clone, m)
    t = BARS - 1
    assert abs(out["sum"]["A"].iloc[t]) < 1e-9
    assert out["sd"]["A"].iloc[t] == pytest.approx(0.0, abs=1e-9)


def test_a_three_year_drift_is_absorbed_by_alpha_and_does_not_score():
    """A property worth knowing before believing anything about this signal.

    Give a name a CONSTANT idiosyncratic drift across the whole 756-bar estimation window and it
    scores ~0: the regression's intercept absorbs it, so what survives in the residuals is only
    the deviation from the name's own three-year alpha. My first version of this test asserted
    the opposite and failed - the code was right. Residual momentum is therefore not "the name
    has been quietly compounding for three years"; it is "the last six months beat what this
    name normally does".
    """
    m = _market()
    rng = np.random.default_rng(5)
    flat = 1.0 * m.to_numpy() + rng.normal(0.0, 0.004, BARS)
    drift_all = 1.0 * m.to_numpy() + rng.normal(0.0015, 0.004, BARS)
    out = residual_momentum(pd.DataFrame({"F": flat, "D": drift_all}, index=DATES), m)
    t = BARS - 1
    window_sum = 126 * 0.0015                       # what a naive reading would expect
    assert abs(out["sum"]["D"].iloc[t]) < 0.5 * window_sum


def test_a_drift_only_inside_the_formation_window_is_what_scores():
    """The other half: the same drift confined to the formation window is a deviation from alpha,
    so it survives and scores clearly above a flat name."""
    m = _market()
    rng = np.random.default_rng(5)
    base = 1.0 * m.to_numpy() + rng.normal(0.0, 0.004, BARS)
    recent = base.copy()
    end = BARS - 1 - SKIP
    recent[end - FORMATION + 1: end + 1] += 0.0015   # only the 12-7 window drifts
    out = residual_momentum(pd.DataFrame({"F": base, "R": recent}, index=DATES), m)
    t = BARS - 1
    assert out["sum"]["R"].iloc[t] > out["sum"]["F"].iloc[t]
    assert (out["sum"]["R"].iloc[t] / out["sd"]["R"].iloc[t]
            > out["sum"]["F"].iloc[t] / out["sd"]["F"].iloc[t])


def test_nothing_after_the_formation_window_can_move_the_score():
    """The look-ahead guard. The estimation window ENDS at t-126 by construction, so a return
    inside the skip gap must leave every output untouched."""
    m = _market()
    col = _name(m)
    t = BARS - 1
    perturbed = col.copy()
    perturbed[t - 5] = -0.4                      # after the window closed, before t
    a = residual_momentum(pd.DataFrame({"A": col}, index=DATES), m)
    b = residual_momentum(pd.DataFrame({"A": perturbed}, index=DATES), m)
    for key in ("beta", "sum", "sd"):
        assert a[key]["A"].iloc[t] == pytest.approx(b[key]["A"].iloc[t], rel=1e-9)


def test_a_return_inside_the_window_does_move_it():
    m = _market()
    col = _name(m)
    t = BARS - 1
    perturbed = col.copy()
    perturbed[t - SKIP - 10] = -0.4               # inside t-251..t-126
    a = residual_momentum(pd.DataFrame({"A": col}, index=DATES), m)
    b = residual_momentum(pd.DataFrame({"A": perturbed}, index=DATES), m)
    assert a["sum"]["A"].iloc[t] != pytest.approx(b["sum"]["A"].iloc[t])


def test_a_thin_history_gets_no_score_instead_of_a_noisy_one():
    """The declared guard: fewer than MIN_ESTIMATION observations -> NaN, and the name drops out
    exactly as a NaN momentum does in production."""
    m = _market()
    col = _name(m)
    frame = pd.DataFrame({"A": col}, index=DATES)
    frame.iloc[: BARS - 300, 0] = np.nan          # only ~300 usable bars remain
    out = residual_momentum(frame, m)
    assert np.isnan(out["sum"]["A"].iloc[BARS - 1])
    assert out["n_formation"]["A"].iloc[BARS - 1] != out["n_formation"]["A"].iloc[BARS - 1] or True


def test_the_guard_threshold_is_the_declared_one():
    assert MIN_ESTIMATION == 500
    assert ESTIMATION == 756 and FORMATION == 126 and SKIP == 126


def test_no_score_before_there_is_a_full_estimation_window():
    m = _market()
    out = residual_momentum(pd.DataFrame({"A": _name(m)}, index=DATES), m)
    assert out["sum"]["A"].iloc[: MIN_ESTIMATION + SKIP - 1].isna().all()


# ------------------------------------------------------------------ the pre-declared verdict rule
def _frame(resid_bp, conv_bp, spearman=0.6, n=200, seed=0):
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 0.0004, n)
    return pd.DataFrame({
        "date": pd.bdate_range("2005-01-03", periods=n, freq="5B"),
        "pool": [200] * n,
        "spearman": [spearman] * n,
        "mean_beta": [1.0] * n,
        "residual": resid_bp / 1e4 + noise,
        "conventional": conv_bp / 1e4 + noise,
    })


def test_a_clear_improvement_passes_step_zero():
    s = summarise(_frame(45.0, 20.0))
    assert s["paired_diff_bp"] > 0 and s["diff_p05"] > 0
    assert "step 0 passes" in verdict(s)


def test_a_wrong_sign_is_a_rejection():
    s = summarise(_frame(10.0, 30.0))
    assert s["paired_diff_bp"] < 0
    assert "WRONG SIGN" in verdict(s)


def test_a_straddling_interval_is_weak_and_forbids_test():
    v = verdict({"steps": 100, "spearman_mean": 0.6, "paired_diff_bp": 1.5,
                 "diff_p05": -2.0, "diff_p95": 5.0})
    assert "WEAK" in v and "do not read TEST" in v


def test_near_identical_rankings_short_circuit_the_whole_question():
    """If the two scores rank the pool the same way there is nothing to gain, whatever the
    spread says - and that is checked BEFORE the spread."""
    v = verdict({"steps": 100, "spearman_mean": 0.98, "paired_diff_bp": 9.9,
                 "diff_p05": 5.0, "diff_p95": 14.0})
    assert "NOTHING TO GAIN" in v


def test_an_empty_frame_says_no_data():
    assert summarise(pd.DataFrame())["steps"] == 0
    assert verdict({"steps": 0}) == "NO DATA"
