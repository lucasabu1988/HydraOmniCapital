"""H-009: information discreteness, its alignment, and the verdict rule.

The alignment tests are the ones that matter. ID at row t must depend ONLY on the 126 returns
from t-251 to t-126 - the same window `MOM_12_7` uses - so a return that lands after the window
cannot move it. If that breaks, the whole hypothesis is measuring look-ahead. Auto-discovered by
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

from path_momentum import (  # noqa: E402
    FORMATION, SKIP, forward_step_return, information_discreteness, summarise, verdict,
)

BARS = 400
DATES = pd.bdate_range("2005-01-03", periods=BARS)


def _rets(pattern):
    """One column, `pattern` broadcast over the bars."""
    return pd.DataFrame({"A": pattern}, index=DATES)


def test_a_perfectly_gradual_riser_is_the_most_continuous_possible():
    """Every day up: %pos = 1, %neg = 0, PRET > 0 -> ID = -1, the floor."""
    idf = information_discreteness(_rets([0.001] * BARS))
    at = FORMATION + SKIP + 10
    assert idf["A"].iloc[at] == pytest.approx(-1.0)


def test_a_one_jump_riser_is_discrete():
    """Same positive window return, but delivered in a single day: ID goes to the ceiling."""
    pattern = [-0.001] * BARS
    window_end = FORMATION + SKIP           # the window of row `window_end` is [1 .. FORMATION]
    pattern[10] = 0.5                        # one jump inside that window
    idf = information_discreteness(_rets(pattern))
    at = window_end
    got = idf["A"].iloc[at]
    assert got > 0.9, got                    # almost every other day was negative


def test_a_falling_name_flips_the_sign_convention():
    """ID is sign(PRET) x (%neg - %pos): a gradual FALLER is also 'continuous' (ID = -1)."""
    idf = information_discreteness(_rets([-0.001] * BARS))
    at = FORMATION + SKIP + 10
    assert idf["A"].iloc[at] == pytest.approx(-1.0)


def test_zero_days_count_in_neither_fraction():
    """Half the window flat, half up: %pos = 1 of the NON-ZERO days, so ID is still -1."""
    pattern = [0.0] * BARS
    for i in range(1, FORMATION + 1, 2):
        pattern[i] = 0.002
    idf = information_discreteness(_rets(pattern))
    assert idf["A"].iloc[FORMATION + SKIP] == pytest.approx(-1.0)


def test_id_ignores_everything_after_the_formation_window():
    """The look-ahead guard: perturb a return AFTER the window and ID must not move."""
    base = [0.001] * BARS
    at = FORMATION + SKIP + 20
    perturbed = list(base)
    perturbed[at - 5] = -0.30                # inside the skip gap, after the window closes
    a = information_discreteness(_rets(base))["A"].iloc[at]
    b = information_discreteness(_rets(perturbed))["A"].iloc[at]
    assert a == pytest.approx(b), "ID moved on a return that is not in its window"


def test_id_does_move_on_a_return_inside_the_window():
    """The other half of the guard: if nothing moves it, it is not measuring anything."""
    base = [0.001] * BARS
    at = FORMATION + SKIP + 20
    inside = at - SKIP - 5                   # comfortably inside t-251..t-126
    perturbed = list(base)
    perturbed[inside] = -0.30
    a = information_discreteness(_rets(base))["A"].iloc[at]
    b = information_discreteness(_rets(perturbed))["A"].iloc[at]
    assert a != pytest.approx(b)


def test_no_id_before_there_is_a_full_window():
    idf = information_discreteness(_rets([0.001] * BARS))
    assert idf["A"].iloc[: FORMATION + SKIP - 1].isna().all()


def test_the_forward_return_is_the_production_convention():
    """Buy at the t+1 close, sell at the t+1+step close - `run_exec`'s lag=1, 5-bar step."""
    close = pd.DataFrame({"A": np.arange(1.0, BARS + 1.0)}, index=DATES)
    got = forward_step_return(close, 100, step=5)
    assert got["A"] == pytest.approx(close["A"].iloc[106] / close["A"].iloc[101] - 1)


def test_the_forward_return_is_none_at_the_edge_instead_of_wrapping():
    close = pd.DataFrame({"A": np.arange(1.0, BARS + 1.0)}, index=DATES)
    assert forward_step_return(close, BARS - 2, step=5) is None


def test_a_missing_or_zero_price_gives_nan_not_a_fake_return():
    close = pd.DataFrame({"A": [10.0] * BARS, "B": [10.0] * BARS, "C": [10.0] * BARS},
                         index=DATES)
    close.iloc[101, close.columns.get_loc("B")] = np.nan
    close.iloc[101, close.columns.get_loc("C")] = 0.0
    got = forward_step_return(close, 100, step=5)
    assert np.isnan(got["B"]) and np.isnan(got["C"])
    assert got["A"] == pytest.approx(0.0)


# ----------------------------------------------------------------- the pre-declared verdict rule
def _frame(cont_bp, disc_bp, n=200, seed=0):
    rng = np.random.default_rng(seed)
    noise = rng.normal(0, 0.0005, n)
    return pd.DataFrame({
        "date": pd.bdate_range("2005-01-03", periods=n, freq="5B"),
        "pool": [120] * n,
        "continuous": cont_bp / 1e4 + noise,
        "middle": (cont_bp + disc_bp) / 2e4 + noise,
        "discrete": disc_bp / 1e4 + noise,
        "spread": (cont_bp - disc_bp) / 1e4,
        "id_continuous": [-0.6] * n,
        "id_discrete": [0.2] * n,
    })


def test_a_clear_predicted_spread_passes_step_zero():
    s = summarise(_frame(40.0, 5.0))
    assert s["spread_bp"] > 0 and s["spread_p05"] > 0
    assert "step 0 passes" in verdict(s)


def test_a_wrong_signed_spread_is_a_rejection_not_a_flipped_rule():
    s = summarise(_frame(5.0, 40.0))
    assert s["spread_bp"] < 0
    v = verdict(s)
    assert "WRONG SIGN" in v and "not a reason to flip the rule" in v


def test_a_noisy_positive_spread_is_called_weak_and_forbids_reading_test():
    """Tested on the rule, not on a random draw: a skip here would be a hole in the guard, and
    this project's own rule is that a skip is not a pass."""
    weak = {"steps": 100, "spread_bp": 1.2, "spread_p05": -3.4, "spread_p95": 5.6}
    v = verdict(weak)
    assert "WEAK" in v and "do not read TEST" in v


def test_an_empty_frame_says_no_data_rather_than_zero():
    assert summarise(pd.DataFrame())["steps"] == 0
    assert verdict({"steps": 0}) == "NO DATA"
