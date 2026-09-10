"""H-012 — the SEA signal and the step-0 rule on synthetic data. No network, no lab cache."""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import h012_seasonality as H  # noqa: E402


def _monthly_close(start="2004-01-01", months=84, names=("AAA", "BBB"), seed=0):
    """Daily closes whose month-end-to-month-end returns are known: +1 % every month for AAA,
    -1 % for BBB, except September, which is +10 % / -10 % in every year."""
    idx = pd.bdate_range(start, periods=months * 22)
    close = pd.DataFrame(index=idx, columns=list(names), dtype=float)
    level = {n: 100.0 for n in names}
    for period, days in close.groupby(close.index.to_period("M")).groups.items():
        for n in names:
            sign = 1.0 if n == "AAA" else -1.0
            r = 0.10 * sign if period.month == 9 else 0.01 * sign
            level[n] *= 1 + r
            close.loc[days, n] = level[n]          # flat inside the month, so the month return is exactly r
    return close


def test_month_returns_are_month_end_to_month_end_and_not_filled():
    close = _monthly_close(months=14)
    m = H.month_returns(close)
    assert isinstance(m.index, pd.PeriodIndex) and m.index.freqstr == "M"
    assert m.loc[pd.Period("2004-02", "M"), "AAA"] == pytest_approx(0.01)
    assert m.loc[pd.Period("2004-09", "M"), "AAA"] == pytest_approx(0.10)
    assert m.loc[pd.Period("2004-09", "M"), "BBB"] == pytest_approx(-0.10)
    close.loc[close.index.to_period("M") == pd.Period("2004-06", "M"), "BBB"] = np.nan
    m2 = H.month_returns(close)
    assert np.isnan(m2.loc[pd.Period("2004-06", "M"), "BBB"]) and np.isnan(m2.loc[pd.Period("2004-07", "M"), "BBB"])


def test_sea_uses_exactly_the_same_month_at_lags_24_36_48_60_and_skips_the_year_ago_month():
    close = _monthly_close(start="2004-01-01", months=84)      # 2004-01 .. 2010-12
    m = H.month_returns(close)
    # decision in September 2010 -> Septembers of 2008, 2007, 2006, 2005; NOT 2009
    sea = H.sea_at(m, pd.Timestamp("2010-09-15"))
    assert sea["AAA"] == pytest_approx(0.10) and sea["BBB"] == pytest_approx(-0.10)
    # make the year-ago September enormous: SEA must not move
    m.loc[pd.Period("2009-09", "M"), "AAA"] = 5.0
    assert H.sea_at(m, pd.Timestamp("2010-09-15"))["AAA"] == pytest_approx(0.10)
    # a decision in October reads Octobers, whose returns are the ordinary +1 % / -1 %
    sea_oct = H.sea_at(m, pd.Timestamp("2010-10-05"))
    assert sea_oct["AAA"] == pytest_approx(0.01) and sea_oct["BBB"] == pytest_approx(-0.01)


def test_a_name_without_all_four_months_has_no_sea_and_is_not_invented():
    close = _monthly_close(start="2004-01-01", months=84)
    m = H.month_returns(close)
    m.loc[pd.Period("2006-09", "M"), "BBB"] = np.nan          # one of the four lags missing
    sea = H.sea_at(m, pd.Timestamp("2010-09-15"))
    assert np.isnan(sea["BBB"]) and sea["AAA"] == pytest_approx(0.10)
    # too early: lag 60 would need 2000, which the panel does not have -> everyone NaN
    assert H.sea_at(m, pd.Timestamp("2005-09-15")).isna().all()


def test_summarise_and_verdict_follow_the_pre_registered_rule():
    rng = np.random.default_rng(7)
    n = 200
    base = {"date": pd.bdate_range("2009-01-05", periods=n), "pool": 250, "with_sea": 200, "coverage": 0.8,
            "high": 0.0, "low": 0.0, "sea_high": 0.05, "sea_low": -0.05}
    good = pd.DataFrame({**base, "spread": rng.normal(0.0030, 0.004, n)})
    s = H.summarise(good, n=500)
    assert s["steps"] == n and s["spread_bp"] > 0 and s["spread_p05"] > 0
    assert H.verdict(s).startswith("PREDICTED SIGN")
    weak = pd.DataFrame({**base, "spread": rng.normal(0.0002, 0.01, n)})
    v = H.verdict(H.summarise(weak, n=500))
    assert v.startswith("INDISTINGUISHABLE") or v.startswith("REJECTED")
    bad = pd.DataFrame({**base, "spread": rng.normal(-0.0030, 0.004, n)})
    assert H.verdict(H.summarise(bad, n=500)).startswith("REJECTED")
    assert H.verdict({"steps": 0}) == "NO DATA"


def pytest_approx(x, rel=1e-9):
    import pytest
    return pytest.approx(x, rel=rel, abs=1e-12)
