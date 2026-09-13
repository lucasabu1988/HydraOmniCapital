"""One drawdown definition, reused everywhere. These tests are the fence around that.

Four modules each carried their own `(1 + r).cumprod()` / `cummax()` drawdown. They agreed
with `metrics.max_drawdown` on any book that rises before it falls, which is why the
divergence went unnoticed for so long, and disagreed exactly where it mattered: a series whose
first step is a LOSS. The unfloored form takes its high-water mark from the equity left AFTER
that loss, so a book that falls 20% and climbs back to par reports a drawdown of zero.

Each test below feeds that one series through a call site and asserts it sees -20%, which is
only possible if the site is reading the canonical definition rather than re-spelling it.

Auto-discovered by run_all_tests.py (pytest-routed: no __main__ block).
"""
import os
import sys

import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import backtest_variant_sweep as BVS  # noqa: E402
import metrics as M  # noqa: E402
import redesign_lab as L  # noqa: E402
import sector_exposure_post_carry as SX  # noqa: E402

#: falls 20% on the FIRST step, then back to exactly par. Unfloored: 0.0. Canonical: -20.0.
FALLS_FIRST = [-0.20, 0.25]


def _unfloored(r):
    eq = (1 + pd.Series(r)).cumprod()
    return float((eq / eq.cummax() - 1).min()) * 100


def test_the_fixture_really_does_split_the_two_definitions():
    assert _unfloored(FALLS_FIRST) == pytest.approx(0.0)
    assert M.max_drawdown(pd.Series(FALLS_FIRST)) == pytest.approx(-20.0)


def test_backtest_variant_sweep_stats_uses_the_canonical_drawdown():
    df = pd.DataFrame({"ret": FALLS_FIRST, "turnover": [0.0, 0.0], "n": [10, 10]})
    out = BVS.stats(df, "canon", cost_bp=0)
    assert out["maxdd_pct"] == pytest.approx(-20.0)
    assert out["maxdd_net_pct"] == pytest.approx(-20.0)


def test_redesign_lab_stats_uses_the_canonical_drawdown():
    df = pd.DataFrame({"gross": FALLS_FIRST, "net": FALLS_FIRST,
                       "turnover": [0.0, 0.0], "expo": [1.0, 1.0], "n": [10, 10]})
    assert L.stats(df, 5, "canon")["maxdd_net"] == pytest.approx(-20.0)


def test_sector_attribution_blames_the_step_that_happened_below_par():
    """When the sleeve never trades above par the window must start at the money put in.

    The old code took its peak from `argmax(eq[:trough+1])`, which on this series is the first
    step itself, so the -20% step fell OUTSIDE the blame window and the sector that caused the
    loss was never named. The floored peak makes the window cover it.
    """
    df = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=2).astype(str),
                       "step_return": FALLS_FIRST})
    sector_returns = [{"Energy": -0.20}, {"Energy": 0.25}]
    out = SX._drawdown_attribution(df, sector_returns)
    assert out["maxdd_pct"] == pytest.approx(-20.0)
    assert out["peak_is_initial_capital"] is True
    assert out["steps_in_window"] == 1
    assert out["worst_sectors"][0]["sector"] == "Energy"
    assert out["worst_sectors"][0]["sum_of_step_contributions_pct"] == pytest.approx(-20.0)


def test_sector_attribution_still_labels_a_real_peak_when_there_is_one():
    """The normal case is untouched: a sleeve that rises first keeps its dated peak."""
    df = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=3).astype(str),
                       "step_return": [0.10, -0.20, 0.05]})
    out = SX._drawdown_attribution(df, [{"Tech": 0.10}, {"Tech": -0.20}, {"Tech": 0.05}])
    assert out["peak_is_initial_capital"] is False
    assert out["peak_date"] == str(pd.bdate_range("2020-01-01", periods=3)[0].date())
    assert out["maxdd_pct"] == pytest.approx(-20.0)


def test_sector_attribution_refuses_a_hole_it_cannot_line_up():
    df = pd.DataFrame({"date": pd.bdate_range("2020-01-01", periods=3).astype(str),
                       "step_return": [0.10, float("nan"), 0.05]})
    with pytest.raises(ValueError, match="NaNs"):
        SX._drawdown_attribution(df, [{"Tech": 0.10}, {"Tech": 0.0}, {"Tech": 0.05}])


def test_no_module_carries_a_second_drawdown_spelling():
    """Grep the owned files: an unfloored `cummax()` drawdown must not come back."""
    owned = ["metrics.py", "redesign_lab.py", "engine_backtest.py",
             "backtest_variant_sweep.py", "sector_exposure_post_carry.py"]
    offenders = []
    for name in owned:
        src = open(os.path.join(HERE, name), encoding="utf-8").read()
        for n, line in enumerate(src.splitlines(), 1):
            if "cummax()" in line and "clip(lower=1.0)" not in line and not line.lstrip().startswith("#"):
                offenders.append(f"{name}:{n}: {line.strip()}")
    assert offenders == [], "unfloored drawdown spelling is back:\n" + "\n".join(offenders)
