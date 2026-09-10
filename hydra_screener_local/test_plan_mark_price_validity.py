"""The `NaN or 0.0` bug, pinned per way a price can be wrong (consolidation 2026-09-10).

`main` at 3232772 valued a renewing tranche with
    float(px.get(t, tr.get("last_px", {}).get(t, np.nan)) or 0.0)
NaN is truthy, so `or 0.0` never fired: one name without a print made the tranche value NaN,
`tranche_target` NaN, and every transfer and sizing downstream carried it. The hardened
`plan()` (structural-hardening, phase 2) must instead reject the mark, keep the renewal target
finite, record the refusal on the state and emit orders that validate. One case each for
`nan`, `inf`, `-inf`, `0` and a negative close, plus the control with a valid close. No network.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core.portfolio_engine as E  # noqa: E402
from config import V9  # noqa: E402

STOCKS = ("AAA", "BBB", "CCC")
BAD = "ZZZ"           # held in every stocks tranche, absent from the ranking, no last_px carried
UNITS = 100.0
ENTRY = 15.0


def _frames(last_close, n=301, start="2025-01-01"):
    idx = pd.bdate_range(start, periods=n)
    stocks = pd.DataFrame({t: np.linspace(10.0, 20.0, n) for t in STOCKS}, index=idx)
    stocks[BAD] = ENTRY
    stocks.iloc[-1, stocks.columns.get_loc(BAD)] = last_close
    etf = pd.DataFrame({t: np.linspace(50.0, 60.0, n) for t in V9["etf_universe"]}, index=idx)
    return stocks, etf, idx


def _ranking():
    return pd.DataFrame({
        "ticker": list(STOCKS), "rank": [1, 2, 3], "sector": ["Tech"] * 3,
        "recommended": [True] * 3, "reason": [""] * 3, "composite": [1.0, 0.9, 0.8],
    })


def _state_holding_bad(idx):
    st = E.new_state(100000.0, str(idx[0].date()), V9)
    for tr in st["sleeves"]["stocks"]["tranches"]:
        tr["units"][BAD] = UNITS
        tr["cash"] = float(tr["cash"]) - UNITS * ENTRY      # bought at ENTRY: the book is conserved
    return st


def test_the_truthy_nan_is_the_bug_being_pinned():
    """The arithmetic claim behind this file, on its own: `nan or 0.0` is nan."""
    assert not np.isfinite(float(np.nan or 0.0))
    assert float(0.0 or 0.0) == 0.0


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf, 0.0, -5.0],
                         ids=["nan", "inf", "-inf", "zero", "negative"])
def test_a_bad_mark_is_rejected_and_the_renewal_target_stays_finite(bad):
    stocks, etf, idx = _frames(bad)
    today = str(idx[-1].date())
    st = _state_holding_bad(idx)
    st, orders = E.plan(st, today, _ranking(), stocks, etf, 0.04, V9)
    assert st["last_renewal_date"] == today, "the renewal block must actually have run"
    # first the bug itself: nothing non-finite reaches the order sheet (on main at 3232772 the
    # NaN tranche value made every sizing below it NaN)
    for o in orders:
        assert np.isfinite(float(o["dollars"])), f"non-finite dollars on the sheet: {o}"
        if o["est_price"] is not None:
            assert np.isfinite(float(o["est_price"])) and float(o["est_price"]) > 0.0, o
    assert E.validate_orders(orders) == []
    # then the hardened contract: the refusal is recorded, structured, dated
    rej = [r for r in st.get("data_errors", []) if r["ticker"] == BAD and r["intent"] == "mark"]
    assert len(rej) == 1, f"exactly one structured mark refusal expected, got {rej}"
    assert rej[0]["code"] == "price_not_executable" and rej[0]["date"] == today
    # and the name is visible on the sheet, not silently dropped
    held = [o for o in orders if o["ticker"] == BAD]
    assert held and all(o["side"] == "hold_no_price" and o["dollars"] == 0.0 for o in held), held
    # the book itself is untouched by a rejected mark: units and cash are conserved
    for tr in st["sleeves"]["stocks"]["tranches"]:
        assert tr["units"].get(BAD) == UNITS
        assert np.isfinite(float(tr["cash"]))


def test_a_valid_close_is_not_rejected_and_is_counted_in_the_renewal():
    stocks, etf, idx = _frames(ENTRY)
    today = str(idx[-1].date())
    st = _state_holding_bad(idx)
    st, orders = E.plan(st, today, _ranking(), stocks, etf, 0.04, V9)
    assert st["last_renewal_date"] == today
    assert not [r for r in st.get("data_errors", []) if r["ticker"] == BAD]
    assert E.validate_orders(orders) == []
    # a held name that left the ranking is sold at a real price, not parked as hold_no_price
    sells = [o for o in orders if o["ticker"] == BAD]
    assert sells and all(o["side"] == "sell" and o["est_price"] == pytest.approx(ENTRY) for o in sells), sells
