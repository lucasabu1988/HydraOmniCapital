"""TASK-345 — confirmed fills. Synthetic state, no network."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.fills import apply_confirmations, fill_key  # noqa: E402


def _state():
    return {
        "capital_reference": 800.0,
        "sleeves": {
            "stocks": {"tranches": [
                {"k": 0, "cash": 99.0, "units": {"AAA": 10.0}, "last_px": {"AAA": 10.0}},
                {"k": 1, "cash": 200.0, "units": {}, "last_px": {}},
            ]},
            "etf": {"tranches": [
                {"k": 0, "cash": 200.0, "units": {}, "last_px": {}},
                {"k": 1, "cash": 200.0, "units": {}, "last_px": {}},
            ]},
        },
        "ledger": [
            {"exec_date": "2026-01-06", "sleeve": "stocks", "tranche": 0, "side": "buy",
             "ticker": "AAA", "units": 10.0, "price": 10.0, "dollars": 100.0, "cost": 1.0,
             "status": "filled"},
        ],
        "transfers": [],
    }


def test_exact_match_marks_confirmed_and_is_idempotent():
    st = _state()
    row = {"exec_date": "2026-01-06", "sleeve": "stocks", "tranche": 0, "ticker": "AAA",
           "side": "buy", "units": 10, "price": 10, "fee": 1}
    r1 = apply_confirmations(st, [row])
    assert r1["report"][0]["status"] == "confirmed"
    assert st["ledger"][0]["status"] == "confirmed"
    cash = st["sleeves"]["stocks"]["tranches"][0]["cash"]
    units = st["sleeves"]["stocks"]["tranches"][0]["units"]["AAA"]
    r2 = apply_confirmations(st, [row])
    assert r2["report"][0]["changed"] is False
    assert st["sleeves"]["stocks"]["tranches"][0]["cash"] == pytest.approx(cash)
    assert st["sleeves"]["stocks"]["tranches"][0]["units"]["AAA"] == pytest.approx(units)


def test_partial_units_and_price_slip():
    st = _state()
    # bought 9 @ 10.2 instead of 10 @ 10, fee 0.9
    row = {"exec_date": "2026-01-06", "sleeve": "stocks", "tranche": 0, "ticker": "AAA",
           "side": "buy", "units": 9, "price": 10.2, "fee": 0.9}
    apply_confirmations(st, [row])
    tr = st["sleeves"]["stocks"]["tranches"][0]
    assert tr["units"]["AAA"] == pytest.approx(9.0)
    # reverse 10*10+1, apply 9*10.2+0.9 = 91.8+0.9=92.7
    # start cash 99; +101 - 92.7 = 107.3
    assert tr["cash"] == pytest.approx(99.0 + 101.0 - 92.7)
    assert st["ledger"][0]["status"] == "confirmed"
    assert st["ledger"][0]["price"] == pytest.approx(10.2)


def test_unplanned_fill_is_recorded_with_warning():
    st = _state()
    row = {"exec_date": "2026-01-06", "sleeve": "stocks", "tranche": 0, "ticker": "BBB",
           "side": "buy", "units": 2, "price": 20, "fee": 0.4}
    r = apply_confirmations(st, [row])
    assert r["warnings"]
    assert r["report"][0]["status"] == "confirmed_unplanned"
    assert st["sleeves"]["stocks"]["tranches"][0]["units"]["BBB"] == pytest.approx(2.0)
    assert any(f.get("ticker") == "BBB" and f["status"] == "confirmed_unplanned" for f in st["ledger"])
    assert fill_key(row) == ("2026-01-06", "stocks", 0, "BBB", "buy")
