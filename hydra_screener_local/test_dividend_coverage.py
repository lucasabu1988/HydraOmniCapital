"""Audit phase 4 — dividend watermark, pending queue and corporate-action retraction.

Reproductions R-401..R-406 in docs/AUDIT_REPRODUCTIONS.md. Synthetic table, no network.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core.dividends as D  # noqa: E402
from config import DIVIDEND_OVERLAP_DAYS  # noqa: E402


def _state(last="2026-01-05"):
    return {
        "last_run_date": last,
        "sleeves": {
            "stocks": {"tranches": [
                {"k": 0, "cash": 100.0, "units": {"AAA": 10.0}, "last_px": {"AAA": 10.0}},
                {"k": 1, "cash": 200.0, "units": {}, "last_px": {}}]},
            "etf": {"tranches": [{"k": 0, "cash": 50.0, "units": {}, "last_px": {}}]},
        },
        "ledger": [{"exec_date": "2026-01-02", "sleeve": "stocks", "tranche": 0, "side": "buy",
                    "ticker": "AAA", "units": 10.0, "price": 10.0, "status": "filled"}],
        "write_offs": [],
    }


def _cash(st, sleeve="stocks", k=0):
    return st["sleeves"][sleeve]["tranches"][k]["cash"]


def _ok_report(n=1):
    return {"requested": n, "downloaded": n, "failed_tickers": [], "skipped_fresh": []}


def _failed_report(n=1, failed=("AAA",)):
    return {"requested": n, "downloaded": 0, "failed_tickers": list(failed), "skipped_fresh": []}


# ------------------------------------------------------------------ verification
def test_is_verified_fails_closed():
    """Phase 4.1: no report, or any failed ticker, is not verification."""
    assert D.is_verified(None) is False
    assert D.is_verified({}) is False
    assert D.is_verified({"requested": 3, "downloaded": 3, "failed_tickers": ["X"]}) is False
    assert D.is_verified({"requested": 3, "downloaded": 2, "failed_tickers": []}) is False
    assert D.is_verified({"requested": 3, "downloaded": 3, "failed_tickers": []}) is True
    assert D.is_verified({"requested": 3, "downloaded": 1,
                          "skipped_fresh": ["A", "B"], "failed_tickers": []}) is True


def test_the_query_window_pulls_back_by_the_overlap():
    st = _state()
    st["dividend_coverage"] = {"through": "2026-02-01"}
    start, end = D.query_window(st, "2026-02-10")
    assert end == "2026-02-10"
    assert start < "2026-02-01"
    assert D.query_window(st, "2026-02-10", overlap_days=0)[0] == "2026-02-01"
    assert DIVIDEND_OVERLAP_DAYS > 0


# ------------------------------------------------------------------ R-401
def test_r401_a_provider_outage_does_not_lose_the_dividend():
    """R-401 — phase 4.1/4.2, the worst finding of this phase.

    Day 1 the provider returns nothing, so no dividend is credited — but `plan()`
    advanced `last_run_date` anyway, and the window was `(last_run_date, today]`.
    When the provider recovered on day 2 the 01-08 ex-date was already behind the
    watermark and the $5.00 was gone for good.
    """
    st = _state()
    # day 1: the provider is down
    rep1: dict = {}
    credited = D.apply_dividends(st, [], "2026-01-10",
                                 report=rep1, fetch_report=_failed_report())
    assert credited == []
    assert rep1["verified"] is False
    assert _cash(st) == pytest.approx(100.0)
    assert D.coverage_through(st) == "2026-01-05", "the watermark must not advance"
    assert D.pending_gaps(st), "the unverified window must be queued"

    st["last_run_date"] = "2026-01-10"          # what plan() does regardless

    # day 2: the provider recovers and reports the 01-08 ex-date
    rep2: dict = {}
    late = D.apply_dividends(st, [{"ticker": "AAA", "ex_date": "2026-01-08", "dps": 0.50}],
                             "2026-01-15", report=rep2, fetch_report=_ok_report())
    assert len(late) == 1
    assert _cash(st) == pytest.approx(105.0), "the late dividend is credited, not lost"
    assert rep2["verified"] is True
    assert D.coverage_through(st) == "2026-01-15"
    assert D.pending_gaps(st) == [], "the gap closes once the window is verified"


def test_r401_the_gap_record_survives_as_evidence():
    """Append-only: the outage is still visible after it is resolved."""
    st = _state()
    D.apply_dividends(st, [], "2026-01-10", fetch_report=_failed_report())
    st["last_run_date"] = "2026-01-10"
    D.apply_dividends(st, [], "2026-01-15", fetch_report=_ok_report())
    gaps = st["dividend_gaps"]
    assert len(gaps) == 1
    assert gaps[0]["status"] == "closed"
    assert gaps[0]["tickers"] == ["AAA"]
    assert gaps[0]["closed_through"] == "2026-01-15"


def test_r401_repeated_outages_update_one_gap_record():
    st = _state()
    for day in ("2026-01-10", "2026-01-11", "2026-01-12"):
        D.apply_dividends(st, [], day, fetch_report=_failed_report())
    open_gaps = D.pending_gaps(st)
    assert len(open_gaps) == 3, "one per distinct window"
    assert all(g["seen"] == 1 for g in open_gaps)

    # the same window seen twice updates in place rather than piling up
    D.apply_dividends(st, [], "2026-01-12", fetch_report=_failed_report())
    assert len(D.pending_gaps(st)) == 3
    assert any(g["seen"] == 2 for g in D.pending_gaps(st))


def test_an_unverified_run_still_credits_what_it_did_see():
    """A partial answer is better than none; it just does not count as coverage."""
    st = _state()
    rep: dict = {}
    credited = D.apply_dividends(st, [{"ticker": "AAA", "ex_date": "2026-01-08", "dps": 0.5}],
                                 "2026-01-10", report=rep,
                                 fetch_report=_failed_report(n=2, failed=("BBB",)))
    assert len(credited) == 1
    assert _cash(st) == pytest.approx(105.0)
    assert rep["verified"] is False
    assert rep["unverified_tickers"] == ["BBB"]
    assert D.coverage_through(st) == "2026-01-05"


# ------------------------------------------------------------------ R-403 / 4.5
def test_r403_coverage_is_recorded_and_never_claimed_complete_over_a_gap():
    """R-403 — phase 4.5."""
    st = _state()
    assert D.coverage_is_complete(st, "2026-01-10") is False

    D.apply_dividends(st, [], "2026-01-10", fetch_report=_ok_report())
    cov = st["dividend_coverage"]
    assert cov["through"] == "2026-01-10"
    assert cov["verified_at"]
    assert cov["last_verified"] is True
    assert D.coverage_is_complete(st, "2026-01-10") is True
    assert D.coverage_is_complete(st, "2026-01-11") is False, "not verified that far"

    st["last_run_date"] = "2026-01-10"
    D.apply_dividends(st, [], "2026-01-11", fetch_report=_failed_report())
    assert D.coverage_is_complete(st, "2026-01-10") is False, "an open gap voids completeness"


# ------------------------------------------------------------------ R-404 retraction
def test_r404_a_retracted_dividend_is_reversed_and_versioned():
    """R-404 — phase 4.4. No retraction API existed at all."""
    st = _state()
    D.apply_dividends(st, [{"ticker": "AAA", "ex_date": "2026-01-08", "dps": 0.5}],
                      "2026-01-10", fetch_report=_ok_report())
    assert _cash(st) == pytest.approx(105.0)
    key = ("2026-01-08", "stocks", 0, "AAA")

    rec = D.retract_dividend(st, key, reason="provider withdrew the declaration",
                             today="2026-01-12")
    assert rec is not None
    assert _cash(st) == pytest.approx(100.0), "cash goes back"
    assert rec["stage"] == D.RETRACTED
    assert rec["revision"] == 2
    assert rec["revisions"][0]["dollars"] == pytest.approx(5.0)
    assert rec["retract_reason"].startswith("provider withdrew")
    assert len(st["dividends"]) == 1, "versioned, not deleted"


def test_r404_retracting_twice_is_a_noop():
    st = _state()
    D.apply_dividends(st, [{"ticker": "AAA", "ex_date": "2026-01-08", "dps": 0.5}],
                      "2026-01-10", fetch_report=_ok_report())
    key = ("2026-01-08", "stocks", 0, "AAA")
    D.retract_dividend(st, key, reason="withdrawn")
    cash = _cash(st)
    assert D.retract_dividend(st, key, reason="withdrawn again") is None
    assert _cash(st) == pytest.approx(cash)


def test_r404_a_corrected_amount_can_be_credited_after_a_retraction():
    """The whole point of retracting rather than deleting."""
    st = _state()
    D.apply_dividends(st, [{"ticker": "AAA", "ex_date": "2026-01-08", "dps": 0.5}],
                      "2026-01-10", fetch_report=_ok_report())
    D.retract_dividend(st, ("2026-01-08", "stocks", 0, "AAA"), reason="wrong amount")
    assert _cash(st) == pytest.approx(100.0)

    credited = D.apply_dividends(st, [{"ticker": "AAA", "ex_date": "2026-01-08", "dps": 0.30}],
                                 "2026-01-12", fetch_report=_ok_report())
    assert len(credited) == 1
    assert _cash(st) == pytest.approx(103.0)
    stages = sorted(r["stage"] for r in st["dividends"])
    assert stages == [D.APPLIED, D.RETRACTED]


def test_retracting_an_unknown_key_is_reported_as_none():
    st = _state()
    assert D.retract_dividend(st, ("2026-01-08", "stocks", 0, "NOPE"), reason="x") is None


# ------------------------------------------------------------------ R-405 / R-406
def test_r405_duplicate_rows_are_deduped_at_normalisation():
    rows = [{"ticker": "AAA", "ex_date": "2026-01-08", "dps": 0.5},
            {"ticker": "aaa", "ex_date": "2026-01-08", "dps": 0.5}]
    out = D.normalize_dividends(rows, source="test")
    assert len(out["rows"]) == 1
    assert out["conflicts"] == []
    assert out["rows"][0]["ticker"] == "AAA", "ticker case is normalised"


def test_r405_conflicting_amounts_are_reported_not_first_wins():
    """R-405 — phase 4.6. Two different amounts for one (ticker, ex_date) used to be
    resolved silently by whichever row came first."""
    rows = [{"ticker": "AAA", "ex_date": "2026-01-09", "dps": 0.5},
            {"ticker": "AAA", "ex_date": "2026-01-09", "dps": 0.7}]
    out = D.normalize_dividends(rows, source="test")
    assert len(out["conflicts"]) == 1
    assert out["conflicts"][0]["values"] == [0.5, 0.7]
    assert len(out["rows"]) == 1

    st = _state()
    rep: dict = {}
    D.apply_dividends(st, rows, "2026-01-10", report=rep, fetch_report=_ok_report())
    assert rep["conflicts"], "the conflict must reach the caller"


@pytest.mark.parametrize("bad,reason", [
    (float("nan"), "not finite"),
    (float("inf"), "not finite"),
    (0.0, "> 0"),
    (-0.5, "> 0"),
    (None, "not finite"),
])
def test_r406_an_invalid_dps_is_rejected_with_a_reason(bad, reason):
    """R-406 — phase 4.6/rule 11. These were dropped in silence."""
    out = D.normalize_dividends([{"ticker": "AAA", "ex_date": "2026-01-08", "dps": bad}])
    assert out["rows"] == []
    assert len(out["rejected"]) == 1
    assert reason in out["rejected"][0]["reason"]


def test_a_bad_ex_date_or_empty_ticker_is_rejected():
    out = D.normalize_dividends([
        {"ticker": "", "ex_date": "2026-01-08", "dps": 0.5},
        {"ticker": "AAA", "ex_date": "nope", "dps": 0.5},
        {"ticker": "AAA", "ex_date": "", "dps": 0.5},
    ])
    assert out["rows"] == []
    assert len(out["rejected"]) == 3


def test_rejected_rows_reach_the_caller():
    st = _state()
    rep: dict = {}
    D.apply_dividends(st, [{"ticker": "AAA", "ex_date": "2026-01-08", "dps": float("nan")}],
                      "2026-01-10", report=rep, fetch_report=_ok_report())
    assert len(rep["rejected"]) == 1
    assert _cash(st) == pytest.approx(100.0)


# ------------------------------------------------------------------ stages
def test_the_three_event_stages_are_distinct():
    """Phase 4.6: raw / normalized / applied are separate, labelled objects."""
    raw = [{"ticker": "AAA", "ex_date": "2026-01-08", "dps": 0.5}]
    assert "stage" not in raw[0]

    norm = D.normalize_dividends(raw, source="yfinance", fetched_at="2026-01-10T00:00:00Z")
    assert norm["rows"][0]["stage"] == D.NORMALIZED
    assert norm["rows"][0]["source"] == "yfinance"
    assert norm["rows"][0]["fetched_at"] == "2026-01-10T00:00:00Z"

    st = _state()
    applied = D.apply_dividends(st, raw, "2026-01-10", fetch_report=_ok_report(), source="yfinance")
    assert applied[0]["stage"] == D.APPLIED
    assert applied[0]["source"] == "yfinance"
    assert applied[0]["applied_at"]
    assert applied[0]["revision"] == 1


def test_a_retracted_record_does_not_block_a_fresh_credit_key():
    """The idempotency index ignores retracted records (that is what lets 4.4 work)."""
    st = _state()
    D.apply_dividends(st, [{"ticker": "AAA", "ex_date": "2026-01-08", "dps": 0.5}],
                      "2026-01-10", fetch_report=_ok_report())
    D.retract_dividend(st, ("2026-01-08", "stocks", 0, "AAA"), reason="x")
    again = D.apply_dividends(st, [{"ticker": "AAA", "ex_date": "2026-01-08", "dps": 0.5}],
                              "2026-01-11", fetch_report=_ok_report())
    assert len(again) == 1


def test_coverage_through_falls_back_to_last_run_date_for_old_states():
    """Migration: a state written before phase 4 has no coverage record."""
    st = _state(last="2026-03-03")
    assert "dividend_coverage" not in st
    assert D.coverage_through(st) == "2026-03-03"
