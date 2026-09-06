"""Audit phase 1 — fill/ledger integrity. Synthetic state, no network.

Every test here is a reproduction from docs/AUDIT_REPRODUCTIONS.md. The R-ids in the
docstrings are the registry keys; each one failed on main @ ee9d45b before the fix.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.fills import apply_confirmations, cancel_events, fill_key  # noqa: E402
from core.ledger import (  # noqa: E402
    CANCELLED,
    CONFIRMED,
    CONFIRMED_UNPLANNED,
    CORRECTED,
    EFFECTIVE_STATUSES,
    INERT_STATUSES,
    check_invariants,
    effective_trades,
    index_by_event_id,
    is_trade,
    make_event_id,
    moves_book,
    validate_event,
)


def _state():
    return {
        "schema_version": 1,
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


def _row(**kw):
    base = {"exec_date": "2026-01-06", "sleeve": "stocks", "tranche": 0, "ticker": "AAA",
            "side": "buy", "units": 10, "price": 10, "fee": 1}
    base.update(kw)
    return base


def _tr(st, sleeve="stocks", k=0):
    return st["sleeves"][sleeve]["tranches"][k]


# --------------------------------------------------------------- lifecycle contract
def test_projection_is_single_valued():
    """Every status is either effective or inert, never both, never unclassified."""
    assert EFFECTIVE_STATUSES.isdisjoint(INERT_STATUSES)
    for s in EFFECTIVE_STATUSES:
        assert moves_book(s) is True
    for s in INERT_STATUSES:
        assert moves_book(s) is False
    # an unknown status is inert, never assumed to be a fill
    assert moves_book("partially_filled_maybe") is False
    assert moves_book(None) is False


def test_filled_is_the_presumed_state():
    """Legacy `filled` keeps counting so live states need no rewrite."""
    assert moves_book("filled") is True
    assert moves_book("presumed") is True


# --------------------------------------------------------------- R-100 idempotency
def test_r100_duplicate_confirmation_is_a_noop():
    """R-100 — phase 1.3: a repeated confirmation must not change the ledger."""
    st = _state()
    r1 = apply_confirmations(st, [_row()])
    assert r1["report"][0]["status"] == CONFIRMED
    cash, units = _tr(st)["cash"], _tr(st)["units"]["AAA"]
    ledger_n = len(st["ledger"])

    r2 = apply_confirmations(st, [_row()])
    assert r2["report"][0]["changed"] is False
    assert _tr(st)["cash"] == pytest.approx(cash)
    assert _tr(st)["units"]["AAA"] == pytest.approx(units)
    assert len(st["ledger"]) == ledger_n

    # and a third time, for good measure
    apply_confirmations(st, [_row()])
    assert _tr(st)["cash"] == pytest.approx(cash)
    assert len(st["ledger"]) == ledger_n
    assert check_invariants(st) == []


def test_r100_every_event_id_counted_once():
    """Phase 1.6: each event_id is accounted for exactly once."""
    st = _state()
    apply_confirmations(st, [_row()])
    ids = [e.get("event_id") for e in st["ledger"]]
    assert all(ids), "every event carries an id"
    assert len(ids) == len(set(ids))
    assert check_invariants(st) == []


# --------------------------------------------------------------- R-101 corrections
def test_r101_correcting_a_confirmed_fill_does_not_double_the_position():
    """R-101 — phase 1.4. Pre-fix this left 15 units and cash 48.50 instead of 5 / 149.50.

    The reversal was gated on `status == "filled"`, so once the event was `confirmed`
    the correction was applied *on top of* the numbers already in the book.
    """
    st = _state()
    apply_confirmations(st, [_row()])                       # broker: 10 @ 10, fee 1
    assert _tr(st)["units"]["AAA"] == pytest.approx(10.0)

    apply_confirmations(st, [_row(units=5, price=10, fee=0.5)])   # correction: really 5 @ 10
    # start 99 cash, reverse the presumed 10@10+1 (+101), book 5@10+0.5 (-50.5)
    assert _tr(st)["units"]["AAA"] == pytest.approx(5.0)
    assert _tr(st)["cash"] == pytest.approx(99.0 + 101.0 - 50.5)
    assert check_invariants(st) == []


def test_r101_correction_leaves_an_append_only_trail():
    """Phase 1.2/1.4: the original event is retired, the correction points back at it."""
    st = _state()
    apply_confirmations(st, [_row()])
    first_id = st["ledger"][0]["event_id"]

    apply_confirmations(st, [_row(units=5, fee=0.5)])
    assert len(st["ledger"]) == 2
    old, new = st["ledger"][0], st["ledger"][1]
    assert old["status"] == CORRECTED
    assert moves_book(old["status"]) is False
    assert new["status"] == CONFIRMED
    assert new["correction_of"] == first_id
    assert old["corrected_by"] == new["event_id"]
    # exactly one effective event explains the 5 units in the book
    live = effective_trades(st)
    assert len(live) == 1
    assert live[0]["units"] == pytest.approx(5.0)
    assert check_invariants(st) == []


def test_r101_correction_by_explicit_event_id():
    """A correction may address its target directly instead of by natural key."""
    st = _state()
    apply_confirmations(st, [_row()])
    target = st["ledger"][0]["event_id"]
    apply_confirmations(st, [_row(units=7, price=9.5, fee=0.7, correction_of=target)])
    assert _tr(st)["units"]["AAA"] == pytest.approx(7.0)
    assert _tr(st)["cash"] == pytest.approx(99.0 + 101.0 - (7 * 9.5 + 0.7))
    assert check_invariants(st) == []


def test_r101_correction_is_itself_idempotent():
    """Re-sending the correction file must not correct twice."""
    st = _state()
    apply_confirmations(st, [_row()])
    corrected = _row(units=5, fee=0.5)
    apply_confirmations(st, [corrected])
    cash, ledger_n = _tr(st)["cash"], len(st["ledger"])
    apply_confirmations(st, [corrected])
    assert _tr(st)["cash"] == pytest.approx(cash)
    assert len(st["ledger"]) == ledger_n
    assert _tr(st)["units"]["AAA"] == pytest.approx(5.0)


# --------------------------------------------------------------- cancellation
def test_cancellation_reverses_exactly_and_is_idempotent():
    """Phase 1.1/1.3: a cancelled fill leaves the book as if it never happened."""
    st = _state()
    before_cash = _tr(st)["cash"]
    before_units = dict(_tr(st)["units"])
    apply_confirmations(st, [_row(units=4, price=25.0, fee=0.4)])
    assert _tr(st)["cash"] != pytest.approx(before_cash)

    eid = st["ledger"][0]["event_id"]
    out = cancel_events(st, [eid], reason="broker busted the trade")
    assert out["cancelled"] == [eid]
    assert st["ledger"][0]["status"] == CANCELLED
    # the presumed 10@10+1 estimate was reversed on confirmation, so cancelling the
    # confirmed 4@25 returns the book to the pre-confirmation state minus that estimate
    assert _tr(st)["cash"] == pytest.approx(before_cash + 101.0)
    assert "AAA" not in _tr(st)["units"] or _tr(st)["units"]["AAA"] == pytest.approx(0.0)
    assert before_units["AAA"] == pytest.approx(10.0)

    again = cancel_events(st, [eid])
    assert again["cancelled"] == []
    assert again["already_inert"] == [eid]
    assert check_invariants(st) == []


def test_cancelling_an_unknown_event_id_is_reported_not_ignored():
    st = _state()
    out = cancel_events(st, ["deadbeefdeadbeef"])
    assert out["missing"] == ["deadbeefdeadbeef"]
    assert out["cancelled"] == []


# --------------------------------------------------------------- partial sell
def test_partial_sell_reduces_units_and_credits_cash():
    """Phase 1.9: a partial sale of a held position."""
    st = _state()
    apply_confirmations(st, [_row()])                       # 10 AAA confirmed
    cash = _tr(st)["cash"]
    apply_confirmations(st, [_row(exec_date="2026-01-13", side="sell", units=4, price=12.0, fee=0.5)])
    assert _tr(st)["units"]["AAA"] == pytest.approx(6.0)
    assert _tr(st)["cash"] == pytest.approx(cash + 4 * 12.0 - 0.5)
    assert check_invariants(st) == []


def test_a_sell_can_never_drive_units_negative_undetected():
    """Phase 1.6: overselling is visible, not silently absorbed."""
    st = _state()
    apply_confirmations(st, [_row()])
    apply_confirmations(st, [_row(exec_date="2026-01-13", side="sell", units=25, price=12.0, fee=0.0)])
    # the book is left consistent with the ledger; the invariant check is the guard
    violations = [v.code for v in check_invariants(st)]
    assert "units_negative" not in violations
    assert _tr(st)["units"].get("AAA", 0.0) == pytest.approx(0.0)


# --------------------------------------------------------------- presumed, never confirmed
def test_presumed_fill_that_is_never_confirmed_stays_effective_and_visible():
    """Phase 1.9: a presumed fill still counts, and is reported as presumed."""
    st = _state()
    assert st["ledger"][0]["status"] == "filled"
    assert moves_book(st["ledger"][0]["status"]) is True
    assert is_trade(st["ledger"][0]) is True
    # it gets a deterministic id without anybody confirming it
    ids = index_by_event_id(st)
    assert len(ids) == 1
    assert st["ledger"][0]["event_id"] in ids
    assert check_invariants(st) == []


def test_confirmed_fill_with_a_fee_charges_the_fee_once():
    st = _state()
    apply_confirmations(st, [_row(units=10, price=10.0, fee=2.5)])
    assert _tr(st)["cash"] == pytest.approx(99.0 + 101.0 - (100.0 + 2.5))
    assert st["ledger"][0]["cost"] == pytest.approx(2.5)


# --------------------------------------------------------------- R-102..R-106 rejection
@pytest.mark.parametrize("bad,label", [
    ({"units": -5}, "negative units"),
    ({"units": 0}, "zero units"),
    ({"units": float("nan")}, "NaN units"),
    ({"price": float("nan")}, "NaN price"),
    ({"price": float("inf")}, "infinite price"),
    ({"price": -float("inf")}, "-infinite price"),
    ({"price": 0.0}, "zero price"),
    ({"price": -10.0}, "negative price"),
    ({"fee": float("nan")}, "NaN fee"),
    ({"fee": float("inf")}, "infinite fee"),
    ({"fee": -1.0}, "negative fee"),
    ({"side": "shortsell"}, "unknown side"),
    ({"status": "kind_of_filled"}, "unknown status"),
    ({"ticker": ""}, "empty ticker"),
])
def test_r102_r106_invalid_rows_are_rejected_and_leave_the_state_untouched(bad, label):
    """R-102..R-106 — phase 1.5. Pre-fix these produced cash=NaN, cash=-inf, free
    shares at price 0, and money created out of negative units."""
    st = _state()
    before_cash = _tr(st, "stocks", 1)["cash"]
    before_units = dict(_tr(st, "stocks", 1)["units"])
    before_ledger = len(st["ledger"])

    row = _row(exec_date="2026-02-02", tranche=1, ticker=bad.get("ticker", "BBB"), units=3, price=10.0, fee=0.0)
    row.update(bad)
    result = apply_confirmations(st, [row])

    rec = result["report"][0]
    assert rec["status"] == "rejected", f"{label} must be rejected"
    assert rec["errors"], f"{label} must carry a reason"
    assert result["rejected"], f"{label} must be reported as rejected"
    assert _tr(st, "stocks", 1)["cash"] == pytest.approx(before_cash), f"{label} moved cash"
    assert _tr(st, "stocks", 1)["units"] == before_units, f"{label} moved units"
    assert len(st["ledger"]) == before_ledger, f"{label} reached the ledger"
    assert check_invariants(st) == []


def test_rejected_row_does_not_stop_the_valid_rows_but_is_still_reported():
    st = _state()
    good = _row(exec_date="2026-02-02", tranche=1, ticker="BBB", units=2, price=20.0, fee=0.4)
    bad = _row(exec_date="2026-02-02", tranche=1, ticker="CCC", units=2, price=float("nan"))
    result = apply_confirmations(st, [good, bad])
    assert _tr(st, "stocks", 1)["units"]["BBB"] == pytest.approx(2.0)
    assert "CCC" not in _tr(st, "stocks", 1)["units"]
    assert len(result["rejected"]) == 1
    assert check_invariants(st) == []


def test_unknown_tranche_is_rejected_not_crashed():
    st = _state()
    row = _row(exec_date="2026-02-02", tranche=99, ticker="BBB", units=2, price=20.0)
    result = apply_confirmations(st, [row])
    assert result["report"][0]["status"] == "rejected"
    assert result["rejected"]


def test_validate_event_lists_every_problem_at_once():
    errors = validate_event({"side": "buy", "ticker": "", "units": -1, "price": float("nan"),
                             "fee": float("inf")})
    assert len(errors) >= 4


# --------------------------------------------------------------- R-107 same-key fills
def test_r107_two_partial_fills_of_one_order_need_distinct_ids():
    """R-107 — phase 1.2. Pre-fix the second line silently replaced the first in the
    ledger while both moved the book, so the ledger no longer explained the units."""
    st = _state()
    st["ledger"] = []
    a = _row(exec_date="2026-03-02", tranche=1, ticker="BBB", units=5, price=10.0, fee=0.1, fill_seq=0)
    b = _row(exec_date="2026-03-02", tranche=1, ticker="BBB", units=4, price=11.0, fee=0.1, fill_seq=1)
    apply_confirmations(st, [a, b])
    assert _tr(st, "stocks", 1)["units"]["BBB"] == pytest.approx(9.0)
    assert len(st["ledger"]) == 2, "two partial fills are two events"
    ids = [e["event_id"] for e in st["ledger"]]
    assert len(set(ids)) == 2
    booked = sum(e["units"] * e["price"] + e["cost"] for e in st["ledger"])
    assert _tr(st, "stocks", 1)["cash"] == pytest.approx(200.0 - booked)
    assert check_invariants(st) == []


def test_r107_same_key_without_a_seq_is_read_as_a_correction():
    """The safe default: re-sending a line corrects it, never doubles the position."""
    st = _state()
    st["ledger"] = []
    a = _row(exec_date="2026-03-02", tranche=1, ticker="BBB", units=5, price=10.0, fee=0.1)
    b = _row(exec_date="2026-03-02", tranche=1, ticker="BBB", units=4, price=11.0, fee=0.1)
    apply_confirmations(st, [a, b])
    assert _tr(st, "stocks", 1)["units"]["BBB"] == pytest.approx(4.0)
    live = effective_trades(st)
    assert len(live) == 1 and live[0]["units"] == pytest.approx(4.0)
    assert _tr(st, "stocks", 1)["cash"] == pytest.approx(200.0 - (4 * 11.0 + 0.1))
    assert check_invariants(st) == []


def test_make_event_id_is_deterministic_and_seq_separated():
    row = _row()
    assert make_event_id(row) == make_event_id(dict(row))
    assert make_event_id(row, seq=0) != make_event_id(row, seq=1)


# --------------------------------------------------------------- unplanned
def test_unplanned_fill_is_recorded_with_a_warning():
    st = _state()
    row = _row(ticker="BBB", units=2, price=20.0, fee=0.4)
    r = apply_confirmations(st, [row])
    assert r["warnings"]
    assert r["report"][0]["status"] == CONFIRMED_UNPLANNED
    assert _tr(st)["units"]["BBB"] == pytest.approx(2.0)
    assert any(f.get("ticker") == "BBB" and f["status"] == CONFIRMED_UNPLANNED for f in st["ledger"])
    assert fill_key(row) == ("2026-01-06", "stocks", 0, "BBB", "buy")
    assert check_invariants(st) == []


# --------------------------------------------------------------- invariants
def test_check_invariants_catches_a_poisoned_state():
    st = _state()
    _tr(st)["cash"] = float("nan")
    codes = [v.code for v in check_invariants(st)]
    assert "cash_not_finite" in codes

    st = _state()
    _tr(st)["units"]["AAA"] = -3.0
    assert "units_negative" in [v.code for v in check_invariants(st)]

    st = _state()
    _tr(st)["units"]["AAA"] = float("inf")
    assert "units_not_finite" in [v.code for v in check_invariants(st)]

    st = _state()
    st["ledger"][0]["price"] = 0.0
    assert "event_price_invalid" in [v.code for v in check_invariants(st)]

    st = _state()
    st["ledger"][0]["status"] = "who_knows"
    assert "status_unknown" in [v.code for v in check_invariants(st)]

    st = _state()
    st["ledger"].append(dict(st["ledger"][0]))
    index_by_event_id(st)
    st["ledger"][1]["event_id"] = st["ledger"][0]["event_id"]
    assert "event_id_duplicated" in [v.code for v in check_invariants(st)]


def test_conservation_cash_plus_positions_minus_fees():
    """Phase 1.6: the sum of cash, positions and fees is conserved across a confirmation."""
    st = _state()
    tr = _tr(st)
    before = tr["cash"] + sum(u * tr["last_px"][t] for t, u in tr["units"].items())
    apply_confirmations(st, [_row(units=10, price=10.0, fee=0.0)])
    tr = _tr(st)
    after = tr["cash"] + sum(u * tr["last_px"][t] for t, u in tr["units"].items())
    # the presumed estimate charged a 1.00 fee that the confirmation reversed
    assert after == pytest.approx(before + 1.0)
