"""TASK-407: flooring orders to whole shares, and the tracking error it produces.

Auto-discovered by run_all_tests.py (pytest-routed: no __main__ block).
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

from engine_backtest import floor_orders_to_whole_shares  # noqa: E402
from whole_share_sizing import tracking_error  # noqa: E402


def _state(orders):
    return {"pending": list(orders)}


def test_a_buy_is_floored_to_whole_shares_and_the_rest_stays_unspent():
    st = _state([dict(side="buy", ticker="AAPL", dollars=1000.0, est_price=93.0,
                      est_units=1000 / 93.0)])
    r = floor_orders_to_whole_shares(st)
    o = st["pending"][0]
    assert o["est_units"] == 10.0                     # floor(1000/93) = 10
    assert o["dollars"] == pytest.approx(930.0)
    assert r["unspent"] == pytest.approx(70.0)
    assert r["orders"] == 1 and r["zeroed"] == 0
    assert o["whole_shares"] is True


def test_an_order_smaller_than_one_share_becomes_no_order_at_all():
    """The SNDK / LITE / QQQ case from the first live sheet."""
    st = _state([dict(side="buy", ticker="SNDK", dollars=120.0, est_price=190.0,
                      est_units=120 / 190.0)])
    r = floor_orders_to_whole_shares(st)
    assert st["pending"][0]["dollars"] == 0.0
    assert st["pending"][0]["est_units"] == 0.0
    assert r["zeroed"] == 1
    assert r["unspent"] == pytest.approx(120.0)


def test_an_exact_multiple_is_left_alone():
    st = _state([dict(side="buy", ticker="X", dollars=500.0, est_price=50.0, est_units=10.0)])
    r = floor_orders_to_whole_shares(st)
    assert st["pending"][0]["dollars"] == pytest.approx(500.0)
    assert r["unspent"] == pytest.approx(0.0) and r["zeroed"] == 0


def test_a_closing_sell_is_never_floored():
    """close=True liquidates the position whatever its size; rounding it would strand units."""
    st = _state([dict(side="sell", ticker="Y", dollars=1234.56, est_price=99.0, close=True,
                      est_units=12.47)])
    r = floor_orders_to_whole_shares(st)
    assert st["pending"][0]["dollars"] == pytest.approx(1234.56)
    assert r["orders"] == 0


def test_a_trim_sell_is_floored_like_a_buy():
    st = _state([dict(side="sell", ticker="Z", dollars=250.0, est_price=80.0, close=False,
                      est_units=3.125)])
    floor_orders_to_whole_shares(st)
    assert st["pending"][0]["est_units"] == 3.0
    assert st["pending"][0]["dollars"] == pytest.approx(240.0)


def test_transfers_parks_and_unpriced_holds_are_untouched():
    st = _state([
        dict(side="transfer_in", ticker="CASH", dollars=500.0, est_price=None, est_units=None),
        dict(side="park", ticker="TBILL", dollars=2500.0, est_price=None, est_units=None),
        dict(side="hold_no_price", ticker="ESRX", dollars=0.0, est_price=None, est_units=3.0),
        dict(side="buy", ticker="W", dollars=100.0, est_price=float("nan"), est_units=None),
        dict(side="buy", ticker="V", dollars=100.0, est_price=0.0, est_units=None),
    ])
    r = floor_orders_to_whole_shares(st)
    assert r == dict(unspent=0.0, zeroed=0, orders=0)
    assert [o["dollars"] for o in st["pending"]] == [500.0, 2500.0, 0.0, 100.0, 100.0]


def test_flooring_is_idempotent():
    st = _state([dict(side="buy", ticker="A", dollars=1000.0, est_price=93.0, est_units=None)])
    first = floor_orders_to_whole_shares(st)
    second = floor_orders_to_whole_shares(st)
    assert first["unspent"] == pytest.approx(70.0)
    assert second["unspent"] == pytest.approx(0.0)
    assert st["pending"][0]["dollars"] == pytest.approx(930.0)


def test_tracking_error_is_zero_against_itself_and_positive_otherwise():
    idx = pd.bdate_range("2020-01-01", periods=60)[::5]
    a = pd.Series(np.linspace(1.0, 1.5, len(idx)), index=idx)
    assert tracking_error(a, a) == pytest.approx(0.0, abs=1e-12)
    rng = np.random.default_rng(3)
    b = a * (1 + pd.Series(rng.normal(0, 0.002, len(idx)), index=idx)).cumprod()
    assert tracking_error(a, b) > 0


def test_tracking_error_needs_two_common_points_and_says_nan_otherwise():
    idx = pd.bdate_range("2020-01-01", periods=2)
    a = pd.Series([1.0, 1.1], index=idx)
    b = pd.Series([1.0, 1.2], index=pd.bdate_range("2021-01-01", periods=2))
    assert np.isnan(tracking_error(a, b))
