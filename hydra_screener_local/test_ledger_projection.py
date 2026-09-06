"""Audit phase 1.7/1.8 — one canonical ledger projection for every consumer.

Before this, five modules each carried their own literal set of "counts as a fill":

    core/dividends.py      {"filled", "confirmed", "confirmed_unplanned"}
    core/state_check.py    {"filled", "confirmed", "confirmed_unplanned"}
    reconcile.py           ("filled", "confirmed", "confirmed_unplanned")
    core/journal.py        ("filled", "confirmed")            <- dropped unplanned
    dashboard_v9.py        status != "filled" -> skip          <- dropped everything else

The last two are repros R-108 and R-109.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core.dividends as DV  # noqa: E402
import core.journal as CJ  # noqa: E402
import core.state_check as SC  # noqa: E402
import dashboard_v9 as DASH  # noqa: E402
import reconcile as RC  # noqa: E402
from core.fills import apply_confirmations  # noqa: E402
from core.ledger import EFFECTIVE_STATUSES, is_trade, moves_book  # noqa: E402


def _state(status="filled", **extra):
    fill = {"exec_date": "2026-01-06", "sleeve": "stocks", "tranche": 0, "side": "buy",
            "ticker": "AAA", "units": 10.0, "price": 10.0, "dollars": 100.0, "cost": 1.0,
            "status": status}
    fill.update(extra)
    return {
        "schema_version": 1,
        "capital_reference": 800.0,
        "sleeves": {
            "stocks": {"tranches": [
                {"k": 0, "cash": 99.0, "units": {"AAA": 10.0}, "last_px": {"AAA": 10.0}},
                {"k": 1, "cash": 200.0, "units": {}, "last_px": {}},
            ]},
            "etf": {"tranches": [{"k": 0, "cash": 200.0, "units": {}, "last_px": {}}]},
        },
        "ledger": [fill],
        "transfers": [], "write_offs": [], "interest": [], "dividends": [],
        "last_run_date": "2026-01-05",
    }


# --------------------------------------------------------------- one definition
def test_every_consumer_shares_the_same_definition():
    """Phase 1.7: no module may keep a private copy of the effective-status set."""
    assert DV.FILLED is EFFECTIVE_STATUSES
    assert SC.FILLED is EFFECTIVE_STATUSES


# --------------------------------------------------------------- R-108 dashboard
@pytest.mark.parametrize("status", sorted(EFFECTIVE_STATUSES))
def test_r108_dashboard_lots_see_every_effective_status(status):
    """R-108 — phase 1.8. Pre-fix a `confirmed` fill produced lots == {}, so cost
    basis, realised P&L and fees on the dashboard all read zero."""
    st = _state(status=status)
    lots = DASH._lots_from_ledger(st)
    key = ("stocks", 0, "AAA")
    assert key in lots, f"status {status!r} dropped out of the lots walk"
    assert lots[key]["qty"] == pytest.approx(10.0)
    assert lots[key]["cost_total"] == pytest.approx(100.0)
    assert lots[key]["fees"] == pytest.approx(1.0)


@pytest.mark.parametrize("status", ["not_filled", "noted", "cancelled", "corrected", "rejected"])
def test_dashboard_lots_ignore_inert_statuses(status):
    st = _state(status=status)
    assert DASH._lots_from_ledger(st) == {}


def test_r108_end_to_end_confirmation_keeps_the_dashboard_lots():
    """The real sequence: engine presumes, Lucas confirms, the dashboard still adds up."""
    st = _state()
    before = DASH._lots_from_ledger(st)[("stocks", 0, "AAA")]
    assert before["qty"] == pytest.approx(10.0)

    apply_confirmations(st, [{"exec_date": "2026-01-06", "sleeve": "stocks", "tranche": 0,
                              "ticker": "AAA", "side": "buy", "units": 9, "price": 10.2, "fee": 0.9}])
    after = DASH._lots_from_ledger(st)[("stocks", 0, "AAA")]
    assert after["qty"] == pytest.approx(9.0)
    assert after["cost_total"] == pytest.approx(9 * 10.2)
    assert after["fees"] == pytest.approx(0.9)


def test_r108_a_correction_is_not_double_counted_in_the_lots():
    """The retired event is inert, so only the correction reaches cost basis."""
    st = _state()
    row = {"exec_date": "2026-01-06", "sleeve": "stocks", "tranche": 0, "ticker": "AAA",
           "side": "buy", "units": 10, "price": 10.0, "fee": 1.0}
    apply_confirmations(st, [row])
    apply_confirmations(st, [dict(row, units=4, price=10.0, fee=0.4)])
    assert len(st["ledger"]) == 2
    lots = DASH._lots_from_ledger(st)[("stocks", 0, "AAA")]
    assert lots["qty"] == pytest.approx(4.0)
    assert lots["cost_total"] == pytest.approx(40.0)
    assert lots["fees"] == pytest.approx(0.4)


# --------------------------------------------------------------- R-109 journal
def test_r109_journal_slippage_counts_unplanned_confirmations():
    """R-109 — phase 1.7. `("filled", "confirmed")` dropped confirmed_unplanned, so
    slippage on an off-sheet fill never reached the journal."""
    fills = [{"status": "confirmed_unplanned", "side": "buy", "sleeve": "stocks",
              "ticker": "AAA", "est_price": 10.0, "price": 10.1}]
    out = CJ._slippage_bp(fills)
    assert out["n"] == 1
    assert out["mean_bp"] == pytest.approx(100.0, rel=1e-6)


def test_r109_journal_splits_presumed_from_confirmed():
    fills = [
        {"status": "filled", "side": "buy", "ticker": "A"},
        {"status": "presumed", "side": "buy", "ticker": "B"},
        {"status": "confirmed", "side": "buy", "ticker": "C"},
        {"status": "confirmed_unplanned", "side": "buy", "ticker": "D"},
        {"status": "corrected", "side": "buy", "ticker": "E"},
    ]
    rec = CJ.build_record(date="2026-01-06", state=_state(), fills=fills)
    assert rec["did"]["fills_presumed"] == 2
    assert rec["did"]["fills_confirmed"] == 2, "corrected must not count as confirmed"


# --------------------------------------------------------------- other consumers
@pytest.mark.parametrize("status", sorted(EFFECTIVE_STATUSES))
def test_reconcile_fees_count_every_effective_status(status):
    st = _state(status=status)
    assert RC.explanations(st)["fees_recorded"] == pytest.approx(1.0)


def test_reconcile_fees_ignore_a_corrected_event():
    st = _state(status="corrected")
    assert RC.explanations(st)["fees_recorded"] == pytest.approx(0.0)


@pytest.mark.parametrize("status", sorted(EFFECTIVE_STATUSES))
def test_dividends_holdings_see_every_effective_status(status):
    st = _state(status=status)
    held = DV.holdings_before(st, "2026-01-07")
    assert held.get(("stocks", 0, "AAA")) == pytest.approx(10.0)


def test_state_check_replay_sees_every_effective_status():
    for status in sorted(EFFECTIVE_STATUSES):
        st = _state(status=status)
        books = SC.replay(st)
        assert books["stocks"]["tranches"][0]["units"].get("AAA") == pytest.approx(10.0), status


def test_state_check_replay_ignores_a_corrected_event():
    st = _state(status="corrected")
    books = SC.replay(st)
    assert "AAA" not in books["stocks"]["tranches"][0]["units"]


def test_state_check_replay_agrees_with_the_book_after_a_correction():
    """The book and the ledger tell the same story once a correction has landed."""
    st = _state()
    st["capital_reference"] = 800.0
    row = {"exec_date": "2026-01-06", "sleeve": "stocks", "tranche": 0, "ticker": "AAA",
           "side": "buy", "units": 10, "price": 10.0, "fee": 1.0}
    apply_confirmations(st, [row])
    apply_confirmations(st, [dict(row, units=4, price=10.0, fee=0.4)])
    books = SC.replay(st)
    assert books["stocks"]["tranches"][0]["units"]["AAA"] == pytest.approx(4.0)


def test_is_trade_and_moves_book_agree():
    for status in sorted(EFFECTIVE_STATUSES):
        event = {"status": status, "side": "buy", "ticker": "AAA"}
        assert moves_book(status) and is_trade(event)
    assert not is_trade({"status": "filled", "side": "buy", "ticker": "CASH"})
    assert not is_trade({"status": "filled", "side": "park", "ticker": "AAA"})
