"""TASK-406: slippage from a synthetic ledger, and the honesty guards around N.

Auto-discovered by run_all_tests.py (pytest-routed: no __main__ block).
"""
import json
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "experiments"))

from fill_cost_report import (  # noqa: E402
    MIN_N_FOR_CALIBRATION, build_frame, fee_bp, header, load_ledger, reference_price,
    slippage_bp, summarise,
)


def _fill(**kw):
    base = dict(sleeve="stocks", tranche=0, ticker="AAPL", side="buy", status="confirmed",
                exec_date="2026-09-09", units=10.0, price=100.0, dollars=1000.0, cost=1.0,
                cost_bp=10.0, est_price=99.0)
    base.update(kw)
    return base


def test_the_presumed_close_wins_over_the_planning_close():
    p, which = reference_price(_fill(presumed_price=101.0, est_price=99.0))
    assert (p, which) == (101.0, "presumed_close")


def test_the_planning_close_is_used_but_labelled():
    p, which = reference_price(_fill(est_price=99.0))
    assert (p, which) == (99.0, "planning_close")


def test_no_reference_at_all_is_reported_as_none_not_as_zero():
    p, which = reference_price(_fill(est_price=None))
    assert p is None and which == "none"
    assert slippage_bp(_fill(est_price=None))["cost_bp"] is None


def test_a_buy_above_the_reference_costs_money_and_a_sell_below_it_does_too():
    buy = slippage_bp(_fill(side="buy", price=101.0, presumed_price=100.0))
    sell = slippage_bp(_fill(side="sell", price=99.0, presumed_price=100.0))
    assert buy["cost_bp"] == pytest.approx(100.0)
    assert sell["cost_bp"] == pytest.approx(100.0)
    # and the raw signed move keeps its direction, so the two are never confused
    assert buy["raw_bp"] == pytest.approx(100.0)
    assert sell["raw_bp"] == pytest.approx(-100.0)


def test_a_good_fill_shows_up_as_a_negative_cost():
    good = slippage_bp(_fill(side="buy", price=99.5, presumed_price=100.0))
    assert good["cost_bp"] == pytest.approx(-50.0)


def test_fee_bp_is_the_fee_actually_charged():
    assert fee_bp(_fill(dollars=1000.0, cost=1.0)) == pytest.approx(10.0)
    assert fee_bp(_fill(dollars=0.0, cost=0.0)) is None


def test_a_small_sample_says_so_in_the_header():
    df = build_frame([_fill(presumed_price=100.0)])
    s = summarise(df)
    assert s["priced"] == 1 and s["enough_for_calibration"] is False
    text = " ".join(header(s))
    assert "NOT ENOUGH DATA" in text and str(MIN_N_FOR_CALIBRATION) in text


def test_enough_fills_flips_the_flag_and_drops_the_warning():
    fills = [_fill(presumed_price=100.0, price=100.0 + i * 0.01)
             for i in range(MIN_N_FOR_CALIBRATION)]
    s = summarise(build_frame(fills))
    assert s["priced"] == MIN_N_FOR_CALIBRATION and s["enough_for_calibration"] is True
    assert "NOT ENOUGH DATA" not in " ".join(header(s))


def test_the_header_warns_when_references_are_mixed():
    s = summarise(build_frame([_fill(presumed_price=100.0), _fill(est_price=99.0)]))
    text = " ".join(header(s))
    assert "planning close" in text and "Do not average" in text


def test_unconfirmed_rows_are_counted_but_never_priced():
    df = build_frame([
        _fill(status="filled", presumed_price=100.0),          # presumed, not confirmed by Lucas
        _fill(status="not_filled", price=None, presumed_price=100.0),
        _fill(status="confirmed", presumed_price=100.0, price=101.0),
    ])
    s = summarise(df)
    assert s["fills"] == 3
    assert s["confirmed"] == 1
    assert s["priced"] == 1
    assert s["mean_bp"] == pytest.approx(100.0)


def test_order_size_against_adv_is_bucketed_when_a_panel_is_given():
    idx = pd.to_datetime(["2026-09-08", "2026-09-09"])
    adv = pd.DataFrame({"AAPL": [50_000.0, 50_000.0]}, index=idx)
    df = build_frame([_fill(presumed_price=100.0, dollars=1000.0)], adv)
    assert df["adv_dollars"].iloc[0] == pytest.approx(50_000.0)
    assert df["order_pct_of_adv"].iloc[0] == pytest.approx(2.0)
    assert df["adv_bucket"].iloc[0] == "1-5%"


def test_a_ticker_missing_from_the_adv_panel_is_none_not_an_exception():
    adv = pd.DataFrame({"MSFT": [1.0]}, index=pd.to_datetime(["2026-09-09"]))
    df = build_frame([_fill(presumed_price=100.0)], adv)
    assert df["adv_dollars"].iloc[0] is None or np.isnan(df["adv_dollars"].iloc[0])
    assert summarise(df)["adv_coverage"] == 0


def test_an_empty_ledger_is_a_clean_zero_not_a_crash(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"ledger": [], "pending": []}), encoding="utf-8")
    df = build_frame(load_ledger(str(p)))
    assert df.empty
    s = summarise(df)
    assert s == dict(fills=0, confirmed=0, priced=0, enough_for_calibration=False, tables={},
                     references={}, statuses={})


def test_the_live_state_is_readable_and_still_has_nothing_to_measure():
    """As of 2026-09-08 the book has 30 pending orders and an empty ledger. When Wednesday's
    settle lands this test keeps passing; it only asserts the report can read the real file."""
    live = os.path.join(ROOT, "state", "portfolio_v9.json")
    if not os.path.exists(live):
        pytest.skip("no live state on this machine")
    df = build_frame(load_ledger(live))
    s = summarise(df)
    assert s["fills"] >= 0
    assert isinstance(header(s), list) and header(s)
