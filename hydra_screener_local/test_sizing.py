"""Sizing loss (paper evidence, 2026-09-10): the dollars a run asks for vs what whole shares can place,
one number per run on the sheet and in the journal. No network."""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import portfolio_v9 as V  # noqa: E402
from core.journal import build_record, render_markdown  # noqa: E402
from core.sizing import sizing_summary, whole_share  # noqa: E402

ORDERS = [
    {"sleeve": "stocks", "tranche": 0, "side": "buy", "ticker": "DBRG", "dollars": 328.41, "est_price": 15.92},   # 20 shares
    {"sleeve": "stocks", "tranche": 0, "side": "buy", "ticker": "SNDK", "dollars": 328.41, "est_price": 1692.59},  # 0 shares
    {"sleeve": "stocks", "tranche": 0, "side": "buy", "ticker": "LITE", "dollars": 328.41, "est_price": 935.70},   # 0 shares
    {"sleeve": "etf", "tranche": 0, "side": "buy", "ticker": "SPY", "dollars": 1000.0, "est_price": 500.0},        # exact
    {"sleeve": "stocks", "tranche": 1, "side": "sell", "ticker": "AAA", "dollars": 200.0, "est_price": 30.0},      # not a buy
    {"sleeve": "stocks", "tranche": 1, "side": "buy", "ticker": "NOPX", "dollars": 100.0, "est_price": None},      # unpriced
    {"sleeve": "stocks", "tranche": 1, "side": "hold_no_price", "ticker": "HOLD", "dollars": 0.0, "est_price": None},
]


def test_whole_share_is_the_sheet_rule_and_the_sheet_delegates_to_it():
    assert whole_share(ORDERS[0]) == {"shares": 20, "at_est": 318.4, "leftover": 10.01}
    assert whole_share(ORDERS[1])["shares"] == 0 and whole_share(ORDERS[1])["leftover"] == 328.41
    assert whole_share(ORDERS[3]) == {"shares": 2, "at_est": 1000.0, "leftover": 0.0}
    assert whole_share(ORDERS[5]) is None and whole_share(ORDERS[6]) is None
    for o in ORDERS:
        assert V.whole_share_display(o) == whole_share(o)


def test_sizing_summary_counts_buys_only_and_names_the_zero_share_orders():
    s = sizing_summary(ORDERS)
    assert s["n_buys"] == 4                                            # NOPX has no price, AAA is a sell
    assert s["target_dollars"] == pytest.approx(328.41 * 3 + 1000.0, abs=0.01)
    assert s["achievable_dollars"] == pytest.approx(318.4 + 0 + 0 + 1000.0, abs=0.01)
    assert s["loss_dollars"] == pytest.approx(10.01 + 328.41 + 328.41, abs=0.01)
    assert s["loss_share"] == pytest.approx(s["loss_dollars"] / s["target_dollars"], abs=1e-4)
    assert s["n_zero_share"] == 2 and s["zero_share_names"] == ["LITE", "SNDK"]
    empty = sizing_summary([])
    assert empty["n_buys"] == 0 and empty["loss_share"] is None and empty["zero_share_names"] == []


def test_the_journal_record_carries_the_sizing_and_the_markdown_says_it():
    rec = build_record(date="2026-09-10", state={}, orders=ORDERS)
    sz = rec["did"]["sizing"]
    assert sz["n_buys"] == 4 and sz["n_zero_share"] == 2
    md = render_markdown([rec])
    assert "Sizing loss" in md and "SNDK" in md and "LITE" in md


def test_the_instruction_sheet_carries_the_sizing_in_payload_and_text():
    state = {"capital_reference": 100000, "week_index": 0, "last_renewal_date": "2026-09-10", "pending": []}
    sheet = V.render_instructions("2026-09-10", ORDERS, [], {}, state, "2026-09-11")
    assert sheet["payload"]["sizing"]["n_zero_share"] == 2
    assert "Sizing loss" in sheet["md_text"] and "SNDK" in sheet["md_text"]
    quiet = V.render_instructions("2026-09-10", [], [], {}, state, "2026-09-11")
    assert quiet["payload"]["sizing"]["n_buys"] == 0 and "Sizing loss" not in quiet["md_text"]
