"""The annual table must answer a NAMED drawdown question, and must not lose January.

`engine_backtest._yearly` reported a per-year drawdown built from `(1 + g).cumprod()` with an
unfloored `cummax`. Two things were wrong with that and only one of them is arithmetic:

  * the year's FIRST return could never be a drawdown, because the running peak on step one
    was the equity left after that step. A year that opened with a loss and recovered reported
    a clean 0.0 — the single case an annual risk column exists to show;
  * the table never said whether the peak resets on 1 Jan or is carried in from the whole
    history. Those are different numbers, ten points apart on the real books, and a reader
    cannot tell them apart from a column called `engine_dd`.

The rows now carry both, from the one definition in `metrics`: `engine_dd` (peak resets on
1 Jan, the partner of `engine_net`) and `engine_dd_carry` (all-time high carried in).

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

import engine_backtest as EB  # noqa: E402
import metrics as M  # noqa: E402


def _book(dates, returns):
    """A BOOK VALUE series, which is what `_yearly` is given. The first mark is the capital."""
    idx = pd.to_datetime(list(dates))
    lvl = [1.0]
    for r in returns:
        lvl.append(lvl[-1] * (1 + r))
    return pd.Series(lvl, index=idx)


#: 2020 ends at its high; 2021 OPENS -8%, then +5% and +6%, so the year finishes UP.
OPENS_WITH_A_LOSS = _book(
    ["2020-12-11", "2020-12-18", "2020-12-25", "2021-01-08", "2021-01-15", "2021-01-22"],
    [0.04, -0.02, -0.08, 0.05, 0.06],
)


def _row(rows, year):
    return next(r for r in rows if r["year"] == year)


def test_a_year_that_opens_with_a_loss_is_not_reported_as_flat():
    rows = EB._yearly(OPENS_WITH_A_LOSS, None)
    y = _row(rows, 2021)
    assert y["engine_net"] > 0, "the fixture is a year that recovers; the return must be positive"
    assert y["engine_dd"] == pytest.approx(-8.0, abs=0.05), (
        "the first step of the year has to be inside the drawdown"
    )
    assert y["engine_dd"] != 0.0


def test_the_old_unfloored_form_is_what_this_replaces():
    """Pins the bug itself, so nobody re-derives the old spelling and calls it equivalent."""
    g = OPENS_WITH_A_LOSS.pct_change().dropna()
    g = g[g.index.year == 2021]
    eq = (1 + g).cumprod()
    old = float((eq / eq.cummax() - 1).min()) * 100
    assert old == pytest.approx(0.0), "the old form saw no drawdown at all in this year"
    assert M.annual_max_drawdown(OPENS_WITH_A_LOSS.pct_change().dropna(), peak="year")[2021] \
        == pytest.approx(-8.0, abs=0.05)


def test_the_row_carries_both_readings_and_they_are_not_the_same_question():
    rows = EB._yearly(OPENS_WITH_A_LOSS, None)
    y = _row(rows, 2021)
    # 2020 peaked at 1.04; 2021's trough is 1.04 * 0.98 * 0.92, so the carried read is deeper.
    assert y["engine_dd_carry"] == pytest.approx(-9.8, abs=0.05)
    assert y["engine_dd_carry"] < y["engine_dd"]
    first = _row(rows, 2020)
    assert first["engine_dd_carry"] == pytest.approx(first["engine_dd"]), (
        "the first year of a book has no earlier high to carry in"
    )


def test_every_row_takes_its_drawdown_from_the_canonical_definition():
    """No independent spelling survives in the annual path."""
    r = OPENS_WITH_A_LOSS.pct_change().dropna()
    reset = M.annual_max_drawdown(r, peak="year")
    carry = M.annual_max_drawdown(r, peak="carry")
    for row in EB._yearly(OPENS_WITH_A_LOSS, None):
        y = row["year"]
        assert row["engine_dd"] == pytest.approx(round(reset[y], 1))
        assert row["engine_dd_carry"] == pytest.approx(round(carry[y], 1))
