"""TASK-405 / H-006: the carry hole in the sector cap, pinned, plus the measurement helpers.

The first two tests assert what the code does TODAY (a carried name is not checked against the
cap). They are a pin, not an endorsement: if someone later adds a portfolio-level or carry-level
cap, they go red and that is the signal to update them together with the rule. Auto-discovered by
run_all_tests.py (pytest-routed: no __main__ block).
"""
import os
import sys

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

from config import MAX_PER_SECTOR  # noqa: E402
from core.portfolio_engine import select_tranche_names  # noqa: E402
from sector_exposure_post_carry import (  # noqa: E402
    _drawdown_attribution, _streaks, sector_view, summarise, tranche_weights,
)

TECH = "Information Technology"


def _ranking(names_sectors):
    return pd.DataFrame({
        "ticker": [t for t, _ in names_sectors],
        "rank": range(1, len(names_sectors) + 1),
        "sector": [s for _, s in names_sectors],
        "reason": [""] * len(names_sectors),
    })


def test_the_cap_binds_when_nothing_is_held():
    """Ten tech names at the top, nothing held: the cap lets exactly MAX_PER_SECTOR through."""
    rows = [(f"T{i}", TECH) for i in range(10)] + [(f"H{i}", "Health Care") for i in range(10)]
    picked = select_tranche_names(_ranking(rows), n=10, held=set(), buffer=2.0)
    tech = [p for p in picked if p.startswith("T")]
    assert len(tech) == MAX_PER_SECTOR
    assert len(picked) == 10


def test_a_carried_name_is_never_checked_against_the_cap():
    """H-006's mechanism: six held tech names inside the keep zone all come back, cap or not.

    The guard is genuinely absent — but see the induction test below: a tranche that starts empty
    can never REACH six of one sector, so on the PIT panel this hole fires zero times
    (TASK-405, 1084 steps, 0 per-tranche breaches). Unreachable from the engine's own dynamics by
    luck of arithmetic, not by design, which is why it stays pinned here.
    """
    rows = [(f"T{i}", TECH) for i in range(6)] + [(f"H{i}", "Health Care") for i in range(14)]
    held = {f"T{i}" for i in range(6)}                    # all inside buffer*n = 20
    picked = select_tranche_names(_ranking(rows), n=10, held=held, buffer=2.0)
    tech = [p for p in picked if p.startswith("T")]
    assert len(tech) == 6 > MAX_PER_SECTOR, (
        "if this fails the carry now respects the cap: update H-006 and this test together"
    )


def test_a_tranche_that_starts_empty_never_climbs_past_the_cap():
    """Why the carry hole does not fire in practice: the fill loop can never put a sixth name in,
    so the carry has nothing above five to carry."""
    rows = [(f"T{i}", TECH) for i in range(20)] + [(f"H{i}", "Health Care") for i in range(20)]
    rk = _ranking(rows)
    held = set()
    for _ in range(12):                                  # a year of renewals on a frozen ranking
        held = set(select_tranche_names(rk, n=10, held=held, buffer=2.0))
        tech = [t for t in held if t.startswith("T")]
        assert len(tech) <= MAX_PER_SECTOR


def test_four_tranches_can_hold_four_times_the_cap_without_breaking_it():
    """The cap is per tranche. Portfolio level is what H-006 measures."""
    rows = [(f"T{i}", TECH) for i in range(20)] + [(f"H{i}", "Health Care") for i in range(20)]
    rk = _ranking(rows)
    tranches = [set(select_tranche_names(rk, n=10, held=set(), buffer=2.0)) for _ in range(4)]
    counts, _ = sector_view(tranche_weights(tranches, 4), {t: s for t, s in rows})
    assert counts[TECH] == MAX_PER_SECTOR          # same names in every tranche here
    # but distinct tranches holding distinct names multiply the exposure:
    disjoint = [{f"T{i}"} for i in range(4)]
    counts2, share2 = sector_view(tranche_weights(disjoint, 4), {t: s for t, s in rows})
    assert counts2[TECH] == 4
    assert share2[TECH] == pytest.approx(1.0)


def test_tranche_weights_sum_to_one_and_split_by_tranche():
    tranches = [{"A", "B"}, {"C"}, set(), set()]
    w = tranche_weights(tranches, 4)
    assert w["A"] == pytest.approx(0.125) and w["B"] == pytest.approx(0.125)
    assert w["C"] == pytest.approx(0.25)
    assert sum(w.values()) == pytest.approx(0.5)   # two empty tranches stay uninvested


def test_a_name_held_in_two_tranches_adds_up():
    w = tranche_weights([{"A"}, {"A"}, set(), set()], 4)
    assert w["A"] == pytest.approx(0.5)


def test_sector_view_shares_are_of_the_invested_part():
    w = {"A": 0.25, "B": 0.25}
    counts, share = sector_view(w, {"A": TECH, "B": "Health Care"})
    assert counts == {TECH: 1, "Health Care": 1}
    assert share[TECH] == pytest.approx(0.5)


def test_unknown_sector_is_kept_separate_not_folded_into_a_real_one():
    counts, share = sector_view({"A": 0.5, "B": 0.5}, {"A": TECH})
    assert counts["Other"] == 1 and share["Other"] == pytest.approx(0.5)


def test_streaks_counts_runs_and_the_longest_one():
    s = _streaks([False, True, True, False, True, True, True])
    assert s == {"longest_steps": 3, "runs": 2}
    assert _streaks([]) == {"longest_steps": 0, "runs": 0}


def test_drawdown_attribution_finds_the_window_and_blames_the_right_sector():
    df = pd.DataFrame({
        "date": pd.bdate_range("2020-01-01", periods=4).astype(str),
        "step_return": [0.10, -0.20, -0.05, 0.03],
    })
    sector_returns = [
        {TECH: 0.10},
        {TECH: -0.15, "Energy": -0.05},
        {TECH: -0.05},
        {TECH: 0.03},
    ]
    out = _drawdown_attribution(df, sector_returns)
    assert out["peak_date"] == str(pd.bdate_range("2020-01-01", periods=4)[0].date())
    assert out["trough_date"] == str(pd.bdate_range("2020-01-01", periods=4)[2].date())
    assert out["steps_in_window"] == 2
    worst = out["worst_sectors"][0]
    assert worst["sector"] == TECH
    assert worst["sum_of_step_contributions_pct"] == pytest.approx(-20.0)


def test_summarise_reports_the_breach_it_was_given():
    steps = pd.DataFrame({
        "date": pd.bdate_range("2020-01-01", periods=3).astype(str),
        "distinct": [10, 10, 10],
        "max_names_in_a_sector": [4, 7, 6],
        "max_names_sector": ["Health Care", TECH, TECH],
        "max_share_pct": [20.0, 40.0, 35.0],
        "max_share_sector": ["Health Care", TECH, TECH],
        "unknown_share_pct": [0.0, 0.0, 0.0],
        "step_return": [0.01, -0.02, 0.005],
        "missing_prices": [0, 0, 0],
    })
    out = dict(steps=steps, sector_returns=[{TECH: 0.01}, {TECH: -0.02}, {TECH: 0.005}],
               per_tranche_breach=[dict(date="2020-01-02", tranche=1, sector=TECH, names=6)])
    s = summarise(out)
    assert s["portfolio_max_names"] == 7
    assert s["steps_over_cap"] == 2 and s["pct_steps_over_cap"] == pytest.approx(66.7)
    assert s["sectors_over_cap"] == {TECH: 2}
    assert s["max_sector_share_pct"] == pytest.approx(40.0)
    assert s["per_tranche_breaches"] == 1
