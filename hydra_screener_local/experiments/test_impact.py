"""TASK-438 rules, each pinned by a mutation. Synthetic data only; runs on any clone.

Every test names the line of `.comms/prereg-task-438-impact-2026-09-14.md` it enforces (G2..G5, §2).
"""
from __future__ import annotations

import math
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capacity as C  # noqa: E402
import impact as I  # noqa: E402

IDX = pd.bdate_range("2023-01-02", periods=120)
T = IDX[100]                                   # a settle bar with a full 63-bar window before it


def _fills(rows):
    """rows: (exec_date, sleeve, tranche, ticker, side, dollars)."""
    return C.fills_frame([dict(exec_date=d, sleeve=s, tranche=tr, ticker=t, side=side, dollars=x,
                               cost=x * 0.001, price=10.0, units=x / 10.0)
                          for d, s, tr, t, side, x in rows])


def _adv(values: dict) -> pd.DataFrame:
    return pd.DataFrame({t: [v] * len(IDX) for t, v in values.items()}, index=IDX, dtype=float)


def _sigma_const(values: dict) -> pd.DataFrame:
    return pd.DataFrame({t: [v] * len(IDX) for t, v in values.items()}, index=IDX, dtype=float)


def _one_fill(dollars=1.0, adv=1_000_000.0, sigma=0.02):
    f = _fills([(str(T.date()), "stocks", 0, "AAA", "buy", dollars)])
    return I.fills_with_footprints(f, {"stocks": _adv({"AAA": adv})}, {"stocks": _sigma_const({"AAA": sigma})})


# ---------------------------------------------------------------- sigma (§2, G2)
def test_sigma_is_the_std_of_log_returns_with_a_full_window_or_nan():
    rng = np.random.default_rng(1)
    close = pd.DataFrame(100.0 * np.exp(np.cumsum(rng.normal(0, 0.02, (120, 2)), axis=0)), index=IDX, columns=["A", "B"])
    sig = I.sigma_panel(close)
    assert sig.iloc[:63].isna().all().all(), "no sigma before 63 returns exist (bar 0 has no return)"
    assert sig.iloc[63:].notna().all().all()
    manual = np.log(close["A"] / close["A"].shift(1)).rolling(63).std()
    pd.testing.assert_series_equal(sig["A"], manual, check_names=False)


def test_sigma_window_is_never_shortened():
    close = pd.DataFrame({"A": np.linspace(100, 120, 120)}, index=IDX)
    sig = I.sigma_panel(close, window=63)
    assert math.isnan(sig["A"].iloc[62]) and not math.isnan(sig["A"].iloc[63])
    short = I.sigma_panel(close, window=21)
    assert not math.isnan(short["A"].iloc[21]), "the 21-bar sensitivity window is a different, declared window"


def test_sigma_is_read_at_the_previous_bar_not_the_settle_bar():
    sig = _sigma_const({"AAA": 0.02})
    sig.loc[T, "AAA"] = 0.99                   # the settle bar's own value
    sig.loc[IDX[99], "AAA"] = 0.03              # the bar before
    assert I.sigma_prev_bar(sig, "AAA", T) == 0.03
    f = _fills([(str(T.date()), "stocks", 0, "AAA", "buy", 1.0)])
    fw = I.fills_with_footprints(f, {"stocks": _adv({"AAA": 1e6})}, {"stocks": sig})
    assert fw["sigma_daily"].iloc[0] == 0.03


def test_non_positive_close_blanks_the_window_rather_than_fabricating_sigma():
    close = pd.DataFrame({"A": np.linspace(100, 120, 120)}, index=IDX)
    close.iloc[90, 0] = 0.0
    sig = I.sigma_panel(close)
    assert math.isnan(sig["A"].iloc[100]), "a zero close inside the window -> no sigma"


# ---------------------------------------------------------------- the model (§2, G3, G4)
def test_impact_is_k_sigma_sqrt_participation_in_bp_with_participation_as_a_fraction():
    fw = _one_fill(dollars=1.0, adv=1_000_000.0, sigma=0.02)
    # at C = 10 000 USD the footprint is 10 000 / 1e6 = 1 % participation = 0.01 as a fraction
    bp = I.impact_bp(fw, 10_000.0, k=1.0).iloc[0]
    assert bp == pytest.approx(1.0 * 0.02 * math.sqrt(0.01) * 1e4)          # = 20 bp
    # mutation: using percent (1.0) instead of fraction (0.01) would give 200 bp
    assert bp != pytest.approx(1.0 * 0.02 * math.sqrt(1.0) * 1e4)
    assert I.impact_bp(fw, 10_000.0, k=0.5).iloc[0] == pytest.approx(bp * 0.5), "linear in k"
    assert I.impact_bp(fw, 40_000.0, k=1.0).iloc[0] == pytest.approx(bp * 2.0), "sqrt in capital"


def test_the_fill_inherits_its_footprints_participation_net_across_tranches():
    d = str(T.date())
    f = _fills([(d, "stocks", 0, "AAA", "buy", 100.0), (d, "stocks", 2, "AAA", "sell", 30.0)])
    fw = I.fills_with_footprints(f, {"stocks": _adv({"AAA": 1e6})}, {"stocks": _sigma_const({"AAA": 0.02})})
    assert len(fw) == 2 and np.allclose(fw["part_frac_at_1"].to_numpy(), 70.0 / 1e6), (
        "both micro-fills carry the footprint's NET participation, 434's rule")


def test_unknown_sigma_or_unknown_adv_is_unknown_impact_never_zero():
    f = _fills([(str(T.date()), "stocks", 0, "AAA", "buy", 1.0), (str(T.date()), "stocks", 0, "BBB", "buy", 1.0)])
    fw = I.fills_with_footprints(f, {"stocks": _adv({"AAA": 1e6, "BBB": 1e6})},
                                 {"stocks": _sigma_const({"AAA": 0.02})})           # BBB has no sigma
    bp = I.impact_bp(fw, 1e6)
    assert not math.isnan(bp.iloc[0]) and math.isnan(bp.iloc[1])
    fw2 = I.fills_with_footprints(f, {"stocks": _adv({"AAA": 1e6})},                   # BBB has no ADV
                                  {"stocks": _sigma_const({"AAA": 0.02, "BBB": 0.02})})
    assert math.isnan(I.impact_bp(fw2, 1e6).iloc[1])
    eff = I.effective_bp(fw, 1e6)["total"]
    assert eff["n_known"] == 1 and eff["unknown_share_by_notional"] == pytest.approx(0.5)
    assert eff["measurable"] is False, "50 % unknown notional -> not measurable"


# ---------------------------------------------------------------- aggregation (§2)
def test_effective_bp_is_dollar_weighted_not_a_plain_mean():
    d = str(T.date())
    f = _fills([(d, "stocks", 0, "AAA", "buy", 9.0), (d, "stocks", 0, "BBB", "buy", 1.0)])
    fw = I.fills_with_footprints(f, {"stocks": _adv({"AAA": 1e6, "BBB": 1e6})},
                                 {"stocks": _sigma_const({"AAA": 0.01, "BBB": 0.05})})
    C_ = 1e6
    bp = I.impact_bp(fw, C_)
    weighted = (bp * fw["abs_dollars"]).sum() / fw["abs_dollars"].sum()
    eff = I.effective_bp(fw, C_)["stocks"]["eff_bp_side"]
    assert eff == pytest.approx(weighted)
    assert eff != pytest.approx(bp.mean()), "a plain mean would over-weight the small, volatile fill"


def test_effective_bp_reports_per_sleeve_and_total():
    d = str(T.date())
    f = _fills([(d, "stocks", 0, "AAA", "buy", 1.0), (d, "etf", 0, "SPY", "buy", 1.0)])
    fw = I.fills_with_footprints(f, {"stocks": _adv({"AAA": 1e6}), "etf": _adv({"SPY": 1e9})},
                                 {"stocks": _sigma_const({"AAA": 0.02}), "etf": _sigma_const({"SPY": 0.01})})
    eff = I.effective_bp(fw, 1e6)
    assert set(eff) == {"total", "stocks", "etf"}
    assert eff["etf"]["eff_bp_side"] < eff["stocks"]["eff_bp_side"]


# ---------------------------------------------------------------- curve and crossings (§2)
def test_curve_uses_the_434_grid_ending_exactly_at_100M_and_is_monotone():
    fw = _one_fill()
    rows = I.curve(fw)
    caps = [r["capital"] for r in rows]
    assert caps[0] == 10_000.0 and caps[-1] == 100_000_000.0
    effs = [r["total"]["eff_bp_side"] for r in rows]
    assert effs == sorted(effs)


def test_crossings_are_read_on_top_of_the_base_bp_and_bracketed():
    fw = _one_fill(dollars=1.0, adv=1_000_000.0, sigma=0.02)
    # eff_bp(C) = 0.02 * sqrt(C / 1e6) * 1e4 = 200 * sqrt(C / 1e6): +10 bp at C = 2 500 USD,
    # +25 bp at 15 625, +40 bp at 40 000
    grid = [1_000.0, 2_000.0, 3_000.0, 10_000.0, 20_000.0, 30_000.0, 50_000.0]
    rows = I.curve(fw, grid)
    x = I.crossings(rows)
    assert x["conservative"]["stocks"]["target_impact_bp"] == 10.0
    assert x["conservative"]["stocks"]["capital_reaching_rung"] == 3_000.0
    assert x["conservative"]["stocks"]["largest_capital_below"] == 2_000.0
    assert x["stress"]["stocks"]["capital_reaching_rung"] == 20_000.0
    assert x["smallcap_crisis"]["stocks"]["capital_reaching_rung"] == 50_000.0
    assert x["conservative"]["etf"]["capital_reaching_rung"] is None, "no ETF fills -> nothing measurable"


def test_crossing_is_grid_exhausted_when_the_top_does_not_reach_the_rung():
    fw = _one_fill(dollars=1.0, adv=1e12, sigma=0.001)             # tiny participation, tiny sigma
    x = I.crossings(I.curve(fw))
    r = x["conservative"]["stocks"]
    assert r["capital_reaching_rung"] is None and r["grid_exhausted"] is True
    assert r["largest_capital_below"] == 100_000_000.0


def test_crossing_capital_scales_as_one_over_k_squared():
    fw = _one_fill(dollars=1.0, adv=1_000_000.0, sigma=0.02)
    grid = [float(c) for c in range(500, 3_001, 25)]           # fine enough to see 625 and 2 500
    c1 = I.crossings(I.curve(fw, grid, k=1.0))["conservative"]["stocks"]["capital_reaching_rung"]
    c2 = I.crossings(I.curve(fw, grid, k=2.0))["conservative"]["stocks"]["capital_reaching_rung"]
    assert c1 == 2_500.0 and c2 == 625.0 and c1 / c2 == 4.0, "doubling k quarters the crossing capital"


# ---------------------------------------------------------------- drag cross-check, payload
def test_drag_is_turnover_times_bp():
    assert I.drag_pp_per_year(10.0, 5.427) == pytest.approx(5.427 * 10.0 / 1e4 * 100.0)   # 0.5427 pp
    assert math.isnan(I.drag_pp_per_year(float("nan"), 5.0))


def test_payload_carries_the_label_the_band_and_the_crossings_for_each_k():
    fw = _one_fill()
    p = I.payload(fw, grid=[1e4, 1e5, 1e6])
    assert p["label"] == I.LABEL and p["k_headline"] == 1.0 and p["k_band"] == [0.5, 1.0, 1.5]
    assert set(p["curves"]) == {"0.5", "1.0", "1.5"} and set(p["crossings"]) == {"0.5", "1.0", "1.5"}
    assert all(x["label"] == I.LABEL for k in p["crossings"].values() for rung in k.values() for x in rung.values())
    assert {r["capital"] for r in p["fixed"]} == set(I.FIXED_CAPITALS)
