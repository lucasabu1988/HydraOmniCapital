"""TASK-434: the properties the reviewer asked for, each pinned so a regression breaks a test.

What is deliberately NOT stubbed: `BarSource`. The ETF gap of the previous cycle was a
SOURCE-SELECTION bug - an S&P-500-only pickle was asked for ETF volume - so the tests build a
real SQLite file with the production `bars` schema and read it through the real `mode=ro`
connection. A fake in-memory source would prove nothing about the branch that shipped the bug.

The arithmetic fixtures are hand-checkable on purpose: 100 shares a day at $10 is $1,000 of ADV,
so a $10 order is exactly 1.000000 % and the unit conversion (shares x USD/share -> USD) is
visible in the assertion rather than asserted against whatever the code happens to return.

The two real instruction sheets are also exercised - they are committed state and need no
network - against the committed `journal_paper/2026-09-10.json`, which is the only independent
record of the whole-share arithmetic.

Auto-discovered by run_all_tests.py (pytest-routed: no __main__ block)."""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import warnings

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import capacity_434 as C  # noqa: E402

SCHEMA = """
CREATE TABLE bars (
    ticker TEXT NOT NULL, date TEXT NOT NULL, close_adj REAL, close_raw REAL,
    volume REAL, source TEXT, fetched_at TEXT, PRIMARY KEY (ticker, date));
"""


def _dates(n, start_day=1):
    """n business-ish ISO dates in 2026-06; ordering is all that matters, not the calendar."""
    return [f"2026-06-{d:02d}" for d in range(start_day, start_day + n)]


def _make_db(tmp_path, rows, name="bars.sqlite"):
    """rows = [(ticker, date, close_raw, volume)] or 5-tuples with close_adj."""
    path = tmp_path / name
    con = sqlite3.connect(str(path))
    con.executescript(SCHEMA)
    for r in rows:
        if len(r) == 4:
            t, d, craw, vol = r
            cadj = craw
        else:
            t, d, craw, cadj, vol = r
        con.execute("INSERT INTO bars (ticker, date, close_adj, close_raw, volume, source) "
                    "VALUES (?,?,?,?,?,'yfinance')", (t, d, cadj, craw, vol))
    con.commit()
    con.close()
    return str(path)


def _flat(ticker, n=25, price=10.0, volume=100.0, start_day=1):
    return [(ticker, d, price, volume) for d in _dates(n, start_day)]


def _sheet(book, date, orders, cap=100_000.0, exec_date="2026-07-01"):
    return dict(book=book, path="(fixture)", date=date, exec_date=exec_date,
                capital_reference=cap, orders=orders)


def _order(ticker, dollars, sleeve="stocks", side="buy", price=10.0):
    return dict(sleeve=sleeve, ticker=ticker, side=side, dollars=float(dollars),
                est_price=price, planned=None)


# ---------------------------------------------------------------- units and derivation

def test_dollar_adv_is_shares_times_price_in_usd(tmp_path):
    """20 bars of 100 shares at $10 = $1,000/day. A $10 order is 1.000000 % of that.

    This is the whole shares -> dollars conversion, asserted on a number a human can check.
    """
    db = _make_db(tmp_path, _flat("AAA", n=25, price=10.0, volume=100.0))
    src = C.BarSource(db)
    try:
        adv = C.dollar_adv(src, "AAA", "2026-06-25", window=20)
        assert adv["status"] == "ok"
        assert adv["adv_usd"] == pytest.approx(1000.0)
        assert adv["n_bars"] == 20 and adv["last_bar"] == "2026-06-25"
        sheet = _sheet("live", "2026-06-25", [_order("AAA", 10.0)])
        rows = C.participation_rows(sheet, src, 20, frozenset(), "close_raw")
        assert rows[0]["participation_pct"] == pytest.approx(1.0)
    finally:
        src.close()


def test_price_column_is_selectable_and_changes_the_answer(tmp_path):
    """close_raw is the tape's dollars; close_adj is what production's own filter multiplies."""
    rows = [("AAA", d, 10.0, 5.0, 100.0) for d in _dates(25)]   # raw 10, adj 5
    src = C.BarSource(_make_db(tmp_path, rows))
    try:
        assert C.dollar_adv(src, "AAA", "2026-06-25", 20, price_col="close_raw")["adv_usd"] == 1000.0
        assert C.dollar_adv(src, "AAA", "2026-06-25", 20, price_col="close_adj")["adv_usd"] == 500.0
        with pytest.raises(ValueError):
            C.dollar_adv(src, "AAA", "2026-06-25", 20, price_col="vwap")
    finally:
        src.close()


def test_window_is_point_in_time_and_cannot_see_past_the_asof(tmp_path):
    """A bar dated after the sheet was written must not enter its window."""
    rows = _flat("AAA", n=20, price=10.0, volume=100.0)
    rows += [("AAA", "2026-06-21", 10.0, 1_000_000.0)]      # a monster print, one day later
    src = C.BarSource(_make_db(tmp_path, rows))
    try:
        assert C.dollar_adv(src, "AAA", "2026-06-20", 20)["adv_usd"] == pytest.approx(1000.0)
        later = C.dollar_adv(src, "AAA", "2026-06-21", 20)["adv_usd"]
        assert later > 1000.0                                # proves the monster bar exists
    finally:
        src.close()


# ---------------------------------------------------------------- unknown stays unknown

@pytest.mark.parametrize("rows,reason", [
    ([], "no_bars"),
    (_flat("AAA", n=5), "insufficient_bars"),
    (_flat("AAA", n=19) + [("AAA", "2026-06-20", 10.0, 0.0)], "nonpositive_volume"),
    (_flat("AAA", n=19) + [("AAA", "2026-06-20", None, 100.0)], "missing_price"),
])
def test_unknown_is_never_zero_and_carries_a_named_reason(tmp_path, rows, reason):
    """A zero ADV would divide into +inf participation and land in the worst bucket."""
    src = C.BarSource(_make_db(tmp_path, rows or [("ZZZ", "2026-06-01", 1.0, 1.0)]))
    try:
        adv = C.dollar_adv(src, "AAA", "2026-06-20", 20)
        assert adv["status"] == reason and reason in C.UNKNOWN_REASONS
        assert adv["adv_usd"] is None                        # None, not 0.0, not imputed
    finally:
        src.close()


def test_unknown_orders_stay_in_coverage_by_count_and_by_notional(tmp_path):
    """Instruction 2: coverage twice, and the unknown notional is reported, not dropped."""
    db = _make_db(tmp_path, _flat("AAA", n=25) + _flat("BBB", n=3, start_day=1))
    src = C.BarSource(db)
    try:
        # BBB is the big order: count coverage and notional coverage must NOT agree
        sheet = _sheet("live", "2026-06-25", [_order("AAA", 10.0), _order("BBB", 990.0)])
        rows = C.participation_rows(sheet, src, 20, frozenset(), "close_raw")
    finally:
        src.close()
    cov = C.coverage(rows)
    assert cov["n_orders"] == 2 and cov["n_known"] == 1 and cov["n_unknown"] == 1
    assert cov["count_coverage_pct"] == pytest.approx(50.0)
    assert cov["notional_coverage_pct"] == pytest.approx(1.0)        # $10 of $1000
    assert cov["unknown_notional_share_pct"] == pytest.approx(99.0)
    assert cov["unknown_notional_usd"] == pytest.approx(990.0)
    assert cov["unknown_tickers"] == ["BBB"]
    assert cov["unknown_reasons"] == {"insufficient_bars": 1}
    # and the unknown order is not silently counted as participation
    stats = C.participation_stats(rows)
    assert stats["sample_known"] == 1 and stats["sample_total"] == 2 and stats["partial"] is True
    assert "PARTIAL SAMPLE" in stats["sample_label"]


def test_partial_sample_label_follows_the_31_of_56_rule(tmp_path):
    """Instruction 5: any statistic derived from a partial sample says so, with the counts."""
    rows = [dict(known=True, participation_pct=0.1, ticker="A", notional_usd=1.0),
            dict(known=False, participation_pct=None, ticker="B", notional_usd=1.0)]
    assert C.participation_stats(rows)["sample_label"] == "1 of 2 orders (PARTIAL SAMPLE)"
    full = [r for r in rows if r["known"]]
    assert C.participation_stats(full)["sample_label"] == "1 of 1 orders (complete)"
    assert C.participation_stats(full)["partial"] is False


# ---------------------------------------------------------------- holiday hygiene

def test_ghost_holiday_row_is_detected_and_excluded_from_the_window(tmp_path):
    """TASK-433's Labor Day row: 3 non-null cells of 2728 NaNs a rolling mean for 20 bars.

    Here: 30 tickers print every session; on the holiday only one does, and it prints a tiny
    volume. Without exclusion the holiday bar enters AAA's 20-bar window and drags the mean
    down; with exclusion the window reaches one bar further back and the answer is the clean
    $1,000. Both halves are asserted, so deleting the exclusion fails the test.
    """
    holiday = "2026-06-14"
    rows = []
    for i in range(30):
        t = f"T{i:02d}"
        rows += [(t, d, 10.0, 100.0) for d in _dates(25) if d != holiday]
    rows += [("AAA", d, 10.0, 100.0) for d in _dates(25) if d != holiday]
    rows += [("AAA", holiday, 10.0, 1.0)]                    # the lone ghost print

    src = C.BarSource(_make_db(tmp_path, rows))
    try:
        counts = src.date_counts("2026-01-01")
        ghosts = C.ghost_dates(counts)
        assert ghosts == [holiday]
        clean = C.dollar_adv(src, "AAA", "2026-06-25", 20, frozenset(ghosts))
        dirty = C.dollar_adv(src, "AAA", "2026-06-25", 20, frozenset())
        assert clean["adv_usd"] == pytest.approx(1000.0)
        assert dirty["adv_usd"] < 1000.0                      # the ghost really does poison it
        assert holiday not in (clean["first_bar"], clean["last_bar"])
    finally:
        src.close()


def test_ghost_detector_leaves_a_clean_calendar_alone():
    assert C.ghost_dates({}) == []
    assert C.ghost_dates({"2026-06-01": 3000, "2026-06-02": 2999, "2026-06-03": 3001}) == []
    assert C.ghost_dates({"2026-06-01": 3000, "2026-06-02": 3, "2026-06-03": 3001}) == ["2026-06-02"]


# ---------------------------------------------------------------- aggregation, no netting

def test_same_instrument_same_date_sums_absolute_and_never_nets_buys_against_sells():
    """Instruction 4: two opposite orders in one name are two real executions."""
    rows = [
        dict(book="live", date="2026-06-25", sleeve="stocks", ticker="AAA", side="buy",
             notional_usd=600.0, adv_usd=1000.0, known=True),
        dict(book="live", date="2026-06-25", sleeve="stocks", ticker="AAA", side="sell",
             notional_usd=400.0, adv_usd=1000.0, known=True),
    ]
    g = C.aggregate_instrument_date(rows)
    assert len(g) == 1
    assert g[0]["n_orders"] == 2 and g[0]["sides"] == ["buy", "sell"]
    assert g[0]["gross_notional_usd"] == pytest.approx(1000.0)     # 600 + 400, absolute
    assert g[0]["net_notional_usd"] == pytest.approx(200.0)        # 600 - 400, reported only
    assert g[0]["netting_would_hide_usd"] == pytest.approx(800.0)
    # the participation numerator is the GROSS, never the net
    assert g[0]["joint_participation_pct"] == pytest.approx(100.0)
    assert g[0]["joint_participation_pct"] != pytest.approx(20.0)


def test_instrument_date_groups_do_not_cross_books_or_dates():
    rows = [
        dict(book="live", date="2026-06-25", sleeve="stocks", ticker="AAA", side="buy",
             notional_usd=100.0, adv_usd=1000.0, known=True),
        dict(book="paper", date="2026-06-25", sleeve="stocks", ticker="AAA", side="buy",
             notional_usd=100.0, adv_usd=1000.0, known=True),
        dict(book="live", date="2026-06-26", sleeve="stocks", ticker="AAA", side="buy",
             notional_usd=100.0, adv_usd=1000.0, known=True),
    ]
    g = C.aggregate_instrument_date(rows)
    assert len(g) == 3 and all(x["n_orders"] == 1 for x in g)


# ---------------------------------------------------------------- rounding, not loss

def test_whole_share_impact_is_per_sleeve_and_reports_deviation_not_loss():
    """Instruction 7: residual cash, zero-share orders and exposure deviation - never a loss."""
    sheet = _sheet("live", "2026-06-25", [
        _order("AAA", 250.0, sleeve="stocks", price=100.0),      # 2 shares -> $200
        _order("BBB", 50.0, sleeve="stocks", price=80.0),        # 0 shares -> $0
        _order("SPY", 1000.0, sleeve="etf", price=400.0),        # 2 shares -> $800
    ], cap=10_000.0)
    r = C.whole_share_impact(sheet)
    st, et = r["by_sleeve"]["stocks"], r["by_sleeve"]["etf"]
    assert st["requested_usd"] == pytest.approx(300.0) and st["placeable_usd"] == pytest.approx(200.0)
    assert st["n_zero_share"] == 1 and st["zero_share_names"] == ["BBB"]
    assert st["exposure_deviation_pp"] == pytest.approx(1.0)     # $100 short of a $10k book
    assert et["placeable_usd"] == pytest.approx(800.0)
    assert et["exposure_deviation_pp"] == pytest.approx(2.0)
    assert r["book_unplaced_usd"] == pytest.approx(300.0)
    assert r["residual_cash_usd"] == pytest.approx(10_000.0 - 1000.0)
    # the loss is NOT asserted as a number, because it is not one
    assert r["realised_economic_loss_usd"] is None
    assert "stayed in cash" in r["realised_loss_note"]
    # never pooled: the sleeves keep their own rows
    assert set(r["by_sleeve"]) == {"stocks", "etf"}


def test_unpriced_order_is_not_a_rounding_statement():
    sheet = _sheet("live", "2026-06-25", [dict(sleeve="stocks", ticker="X", side="hold_no_price",
                                               dollars=0.0, est_price=None, planned=None)])
    r = C.whole_share_impact(sheet)
    s = r["by_sleeve"]["stocks"]
    assert s["n_unpriced"] == 1 and s["n_zero_share"] == 0
    assert s["requested_usd"] == 0.0 and s["placeable_usd"] == 0.0


def test_paper_book_reproduces_the_committed_journal_record():
    """The only independent record of this arithmetic: journal_paper/2026-09-10.json.

    DEFECT D6. That artefact is a BOOK OF RECORD and is NOT edited here. It stores the whole-share
    ROUNDING RESIDUE under `did.sizing.loss_dollars` / `loss_share` - the loss framing capacity_434
    refuses in its own output. Reproducing the numbers silently would launder the wrong name
    through a passing test, so this test reproduces the arithmetic AND raises the naming
    discrepancy as a warning that names both sides, so it shows up in the run log.
    """
    journal = os.path.join(ROOT, "journal_paper", "2026-09-10.json")
    sheet = C.load_sheet(C.BOOKS["paper"], "paper")
    r = C.whole_share_impact(sheet)
    with open(journal, "r", encoding="utf-8") as f:
        rec = json.load(f)["did"]["sizing"]
    assert round(r["book_requested_usd"], 2) == rec["target_dollars"]
    assert round(r["book_placeable_usd"], 2) == rec["achievable_dollars"]
    assert round(r["book_unplaced_usd"], 2) == rec["loss_dollars"]
    assert round(r["book_unplaced_share_pct"] / 100.0, 4) == rec["loss_share"]
    assert r["n_zero_share"] == rec["n_zero_share"]
    names = sorted({n for s in r["by_sleeve"].values() for n in s["zero_share_names"]})
    assert names == sorted(rec["zero_share_names"])

    # D6: the committed record's key really is the loss name, and capacity_434's own output is not
    assert "loss_dollars" in rec and "loss_share" in rec
    assert "loss_dollars" not in r and "loss_share" not in r
    assert r["rounding_residue_usd"] == pytest.approx(rec["loss_dollars"], abs=0.005)
    assert r["realised_economic_loss_usd"] is None
    with pytest.warns(UserWarning, match=r"loss_dollars"):
        warnings.warn(
            "journal_paper/2026-09-10.json (a committed book of record, NOT edited) stores the "
            "whole-share rounding residue of $%.2f as did.sizing.loss_dollars / loss_share. That "
            "is a MISLABEL: nothing was executed, so no loss was realised. capacity_434 reports "
            "the same figure as capital_split.rounding_residue_usd and keeps "
            "realised_economic_loss_usd = None." % rec["loss_dollars"], UserWarning)


def test_residual_cash_splits_into_rounding_residue_and_undeployed_capital_and_no_loss():
    """DEFECT D1, the material one. `capital_reference - placeable` was printed under the heading
    "WHOLE-SHARE ROUNDING: a deviation, not a loss" and restated in the summary as a rounding
    outcome. On the live sheet that is $88,553 - of which only $2,992 is rounding residue. The
    other $85,561 is capital the sheet never asked for, because v9 funds one tranche of four.

    The three quantities are pinned apart here so they can never be conflated again:
      (i)   rounding residue                      = requested - placeable
      (ii)  capital not yet deployed by design    = capital_reference - requested
      (iii) realised economic loss                = None, NOT MEASURABLE
    with (i) + (ii) == residual cash, and (i) held to a small fraction of it.
    """
    expected = {                       # book: (rounding residue, not-yet-deployed, residual cash)
        "live": (2992.17, 85560.91, 88553.08),
        "paper": (2277.82, 86621.41, 88899.23),
    }
    for book, (residue, undeployed, residual) in expected.items():
        r = C.whole_share_impact(C.load_sheet(C.BOOKS[book], book))
        cs = r["capital_split"]
        assert cs["rounding_residue_usd"] == pytest.approx(residue, abs=0.01), book
        assert cs["not_requested_usd"] == pytest.approx(undeployed, abs=0.01), book
        assert cs["residual_cash_usd"] == pytest.approx(residual, abs=0.01), book
        # the identity, so the sum can never be quoted as one of its parts
        assert cs["identity_holds"] is True, book
        assert (cs["rounding_residue_usd"] + cs["not_requested_usd"]
                == pytest.approx(cs["residual_cash_usd"])), book
        # the mislabel in numbers: rounding is a few percent of what was called rounding
        assert cs["rounding_residue_share_of_residual_pct"] < 4.0, book
        assert cs["not_requested_share_of_residual_pct"] > 96.0, book
        # (iii) is still not measurable, and each part says what it is
        assert cs["realised_economic_loss_usd"] is None, book
        assert "NOT MEASURABLE" in cs["labels"]["realised_economic_loss_usd"], book
        assert "ROUNDING" in cs["labels"]["rounding_residue_usd"], book
        assert "NOT YET DEPLOYED BY DESIGN" in cs["labels"]["not_requested_usd"], book
        assert "SUM" in cs["labels"]["residual_cash_usd"], book


def test_the_tranche_reading_is_verified_against_the_sheets_and_config_not_assumed():
    """The evidence behind "not yet deployed BY DESIGN", checked rather than asserted.

    config.V9["tranches"] == 4 (read from the declared literal), both sheets are week_index 0,
    every order carries tranche 0, and each sheet's own valuation shows exposure 0.0 across 0
    names - so exactly one tranche of four is funded and $75,000 of the $100,000 reference sits in
    tranches the schedule has not opened. The remainder of the undeployed capital is cash left
    INSIDE the open tranche (vol-targeting, ETF eligibility), which is a different thing again.
    """
    import json as _json
    assert C.declared_v9_tranches()["tranches"] == 4
    for book in ("live", "paper"):
        raw = _json.load(open(C.BOOKS[book], encoding="utf-8"))
        assert raw["week_index"] == 0
        assert {o.get("tranche") for o in raw["orders"]} == {0}
        for s in raw["valuation"]["sleeves"].values():
            assert s["exposure"] == 0.0 and s["distinct"] == 0 and s["names"] == []

        r = C.whole_share_impact(C.load_sheet(C.BOOKS[book], book))
        tr, nb = r["tranche"], r["capital_split"]["not_requested_breakdown"]
        assert tr["schedule_readable"] is True and tr["tranches"] == 4
        assert tr["tranches_opened"] == 1 and tr["tranches_not_yet_opened"] == 3
        assert tr["capital_per_tranche_usd"] == pytest.approx(25_000.0)
        assert nb["not_yet_opened_tranches_usd"] == pytest.approx(75_000.0)
        assert (nb["not_yet_opened_tranches_usd"] + nb["undeployed_inside_the_open_tranche_usd"]
                == pytest.approx(r["capital_split"]["not_requested_usd"]))
        assert "week_index 0" in tr["reading"] and "tranche 0 of 4" in tr["reading"]


def test_a_sheet_whose_schedule_cannot_be_read_refuses_to_split_the_undeployed_capital():
    """The tranche sub-split is a READING, so it is withheld when the sheet does not support it.

    The aggregate `not_requested_usd` is true whatever the schedule does and is always reported;
    only the "3 of 4 tranches unopened" breakdown depends on the reading.
    """
    bare = _sheet("live", "2026-06-25", [_order("AAA", 250.0, price=100.0)], cap=10_000.0)
    r = C.whole_share_impact(bare)                    # fixture sheet: no tranche, no week_index
    assert r["tranche"]["schedule_readable"] is False
    assert "tranche index" in r["tranche"]["reading"]
    nb = r["capital_split"]["not_requested_breakdown"]
    assert nb["not_yet_opened_tranches_usd"] is None
    assert nb["undeployed_inside_the_open_tranche_usd"] is None
    assert r["capital_split"]["not_requested_usd"] == pytest.approx(9_750.0)   # still reported
    assert r["capital_split"]["identity_holds"] is True
    assert r["capital_split"]["residual_cash_is_literally_cash"] is False

    # a sheet that already holds something is not a zero book, so the reading is refused too
    held = _sheet("live", "2026-06-25", [_order("AAA", 250.0, price=100.0)], cap=10_000.0)
    held["orders"][0]["tranche"] = 0
    held["week_index"] = 0
    held["valuation"] = {"sleeves": {"stocks": {"exposure": 4_000.0, "distinct": 5}}}
    assert C.whole_share_impact(held)["tranche"]["schedule_readable"] is False

    # and a sheet past the first pass through the schedule cannot say how many are funded
    later = _sheet("live", "2026-06-25", [_order("AAA", 250.0, price=100.0)], cap=10_000.0)
    later["orders"][0]["tranche"] = 1
    later["week_index"] = 5
    later["valuation"] = {"sleeves": {"stocks": {"exposure": 0.0, "distinct": 0}}}
    t = C.whole_share_impact(later)["tranche"]
    assert t["schedule_readable"] is False and "first pass" in t["reading"]


def test_live_and_paper_are_separate_books_and_are_not_pooled():
    """Instruction 1. The pooled $27,817.69 of the previous cycle must not reappear."""
    live = C.whole_share_impact(C.load_sheet(C.BOOKS["live"], "live"))
    paper = C.whole_share_impact(C.load_sheet(C.BOOKS["paper"], "paper"))
    assert live["book_requested_usd"] != paper["book_requested_usd"]
    pooled = live["book_requested_usd"] + paper["book_requested_usd"]
    assert round(pooled, 2) == 27_817.69                    # the pooled figure, shown to be a sum
    for r in (live, paper):
        assert r["book_requested_usd"] < pooled
        assert set(r["by_sleeve"]) == {"etf", "stocks"}
        assert r["book_unplaced_share_pct"] != pytest.approx(18.94, abs=0.005)


# ---------------------------------------------------------------- filter applicability

def test_filter_applicability_is_derived_from_the_real_code():
    """Instruction 6, answered structurally so a code change changes the answer."""
    a = C.filter_applicability()
    assert a["threshold_usd"] == 5_000_000.0
    # and it says which value it used and where it came from
    assert a["threshold_declared_usd"] == 5_000_000.0
    assert "config.py:" in a["threshold_source"] and "min_dollar_volume" in a["threshold_source"]
    assert "SOURCE LITERAL" in a["threshold_source"]
    assert a["evidence"]["config"] == a["threshold_source"]
    assert a["applies_to"]["stocks_on_entry"] is True
    assert a["applies_to"]["etfs_on_entry"] is False        # the ETF leg carries no volume
    assert a["applies_to"]["stocks_on_exit"] is False       # plan() sells on a price check alone
    assert a["applies_to"]["etfs_on_exit"] is False
    assert a["as_of_run_date_not_point_in_time"] is True
    assert "ENTRY" in a["verdict"] and "STOCKS ONLY" in a["verdict"]


def test_threshold_survives_another_module_rebinding_config_filters(monkeypatch):
    """THE SUITE BUG. `config.FILTERS` is a mutable process global and two test modules REBIND it
    at IMPORT time - `test_spec_compliance.py:31,33` and `experiments/test_screener_logic.py:21,22`
    both assign a relaxed dict that has NO `min_dollar_volume` key, and never restore it. Reading
    `config.FILTERS.get("min_dollar_volume")` therefore returned None and
    `float(None)` raised `TypeError` - but only when pytest happened to collect one of those files
    first, so `pytest experiments/test_capacity_434.py` passed 28 and
    `pytest experiments/test_screener_logic.py experiments/test_capacity_434.py` failed 4.

    This reproduces the rebinding exactly (same dict) and pins that the module now:
      - still answers $5,000,000, taken from the declared literal in config.py;
      - says so, naming the source;
      - and FLAGS the in-process divergence instead of silently reading around it.
    """
    import config
    monkeypatch.setattr(config, "FILTERS",
                        {"min_avg_volume": 0, "min_price": 0, "max_price": None,
                         "exclude_sectors": []}, raising=False)
    assert "min_dollar_volume" not in config.FILTERS          # the contamination is in place

    t = C.declared_filter_threshold()
    assert t["threshold_usd"] == 5_000_000.0
    assert t["live_usd"] is None and t["live_matches_declared"] is False
    assert "REBOUND" in t["live_error"]

    a = C.filter_applicability()
    assert a["threshold_usd"] == 5_000_000.0                  # the answer stays CORRECT
    assert a["threshold_live_matches_declared"] is False      # and the divergence is visible
    assert "declared literal" in a["threshold_divergence_note"]
    assert "$5,000,000" in a["consequence"]


def test_a_changed_declared_threshold_changes_the_answer_and_a_missing_one_diagnoses(tmp_path):
    """The declared literal is read, not hardcoded - and an unreadable one is a NAMED error.

    Three cases on throwaway config files under tmp_path (never the real config.py):
      1. a different declared floor -> a different answer, so this is not a constant in disguise;
      2. a FILTERS dict without the key -> ConfigReadError naming the key, never a TypeError;
      3. no FILTERS assignment at all -> ConfigReadError naming the module.
    """
    good = tmp_path / "cfg_ok.py"
    good.write_text('FILTERS = {"min_dollar_volume": 9_000_000, "min_price": 5.0}\n', encoding="utf-8")
    assert C.declared_filter_threshold(str(good))["threshold_usd"] == 9_000_000.0

    nokey = tmp_path / "cfg_nokey.py"
    nokey.write_text('FILTERS = {"min_avg_volume": 0, "min_price": 0}\n', encoding="utf-8")
    with pytest.raises(C.ConfigReadError) as e1:
        C.declared_filter_threshold(str(nokey))
    assert "min_dollar_volume" in str(e1.value)
    assert not isinstance(e1.value, TypeError)

    empty = tmp_path / "cfg_empty.py"
    empty.write_text("X = 1\n", encoding="utf-8")
    with pytest.raises(C.ConfigReadError) as e2:
        C.declared_filter_threshold(str(empty))
    assert "FILTERS" in str(e2.value)

    with pytest.raises(C.ConfigReadError) as e3:
        C.declared_filter_threshold(str(tmp_path / "does_not_exist.py"))
    assert "cannot read" in str(e3.value)


def test_etf_scenario_loses_its_basis_and_the_stock_one_is_only_weakened():
    sheets = {"live": C.load_sheet(C.BOOKS["live"], "live")}
    a = C.filter_applicability()
    by_name = {s["name"]: s for s in C.scenarios({}, sheets, a)}

    s1 = by_name["S1_p95_at_3pct_of_measured_adv"]
    assert s1["published_usd"] == 204_000_000.0
    assert s1["recomputed_usd"] == pytest.approx(204_081_632.65, rel=1e-6)
    assert any("PARTIAL sample of 31 of 56" in x for x in s1["assumptions"])
    assert "NOT capacity" in s1["basis"]

    s2 = by_name["S2_largest_stock_order_at_3pct_of_filter_floor"]
    assert s2["published_usd"] == 46_000_000.0
    assert s2["recomputed_usd"] == pytest.approx(46_313_728, rel=1e-4)
    assert s2["basis_valid"] is True and "WEAKENED" in s2["basis"]

    s3 = by_name["S3_largest_etf_order_at_3pct_of_filter_floor"]
    assert s3["published_usd"] == 11_600_000.0
    assert s3["recomputed_usd"] == pytest.approx(11_655_731, rel=1e-4)
    assert s3["basis_valid"] is False and "BASIS INVALID" in s3["basis"]

    # no scenario may present itself as capacity, and every one carries its assumptions
    for name, s in by_name.items():
        assert s["assumptions"], name
        assert "CERTIFIED" not in s["basis"].upper(), name
        assert "SCENARIO" in s["basis"].upper() or "BASIS INVALID" in s["basis"] \
            or "WEAKENED" in s["basis"], name
    # D2: only the LIVE sheet was passed in, so the evidence must claim only the live sheet
    assert "every order on this sheet (live) is a buy (30 of 30)" in s2["basis"].lower()
    assert "these sheets" not in s2["basis"].lower()


def test_stated_evidence_matches_the_stated_scope_across_both_books():
    """DEFECT D2. The S2 basis said "Every order on these sheets is a BUY (30 of 30)" while
    counting `live["orders"]` alone. The claim covered 56 orders; the count covered 30. The fact
    happened to be true (paper is all buys too), but the evidence did not reach the claim, and a
    paper sheet with one sell would have left the sentence asserting something it had not checked.

    Same narrowing in `max_stock` / `max_etf`: both were taken over the live sheet only, so the
    "largest order" feeding S2 and S3 was the largest LIVE order, not the largest on these sheets.
    Paper's biggest stock order ($328.41) is larger than live's ($323.88), so the old code
    understated the binding order and OVERSTATED the scenario book.
    """
    sheets = {b: C.load_sheet(C.BOOKS[b], b) for b in ("live", "paper")}
    a = C.filter_applicability()
    by_name = {s["name"]: s for s in C.scenarios({}, sheets, a)}

    s2 = by_name["S2_largest_stock_order_at_3pct_of_filter_floor"]
    n_all = sum(len(s["orders"]) for s in sheets.values())
    n_buy = sum(1 for s in sheets.values() for o in s["orders"] if o["side"] == "buy")
    assert (n_all, n_buy) == (56, 56)
    assert f"is a BUY ({n_buy} of {n_all})" in s2["basis"]
    assert "these sheets (live + paper)" in s2["basis"]
    assert s2["inputs"]["scope"] == "these sheets (live + paper): 56 orders"
    assert s2["inputs"]["buy_orders"] == 56 and s2["inputs"]["total_orders"] == 56

    # the largest order is taken over the same scope the sentence claims
    biggest_stock = max(abs(o["dollars"]) for s in sheets.values()
                        for o in s["orders"] if o["sleeve"] == "stocks")
    biggest_etf = max(abs(o["dollars"]) for s in sheets.values()
                      for o in s["orders"] if o["sleeve"] == "etf")
    assert s2["inputs"]["largest_stock_order_usd"] == pytest.approx(biggest_stock)
    assert s2["inputs"]["largest_stock_order_book"] == "paper"        # NOT live: the old bug
    live_only = max(abs(o["dollars"]) for o in sheets["live"]["orders"] if o["sleeve"] == "stocks")
    assert biggest_stock > live_only                                  # the narrowing really mattered
    s3 = by_name["S3_largest_etf_order_at_3pct_of_filter_floor"]
    assert s3["inputs"]["largest_etf_order_usd"] == pytest.approx(biggest_etf)
    assert s3["inputs"]["largest_etf_order_book"] == "paper"
    assert s3["inputs"]["scope"] == s2["inputs"]["scope"]


def test_every_scenario_that_scales_linearly_carries_the_qualifier():
    """DEFECT D5. S1 said linear scaling is "true only while the strategy keeps the same names and
    the same weights at every size". The four S4_measured scenarios - the ones the summary promotes
    as the binding constraint - carried only the bare "Linear scaling of order size with the book",
    dropping the condition the linearity depends on. Every scenario whose arithmetic divides a cap
    by a participation ratio now carries the full qualifier.
    """
    QUALIFIER = ("scales LINEARLY with the book - true only while the strategy keeps the same "
                 "names and the same weights at every size")
    stats = {"live/stocks": dict(max_pct=0.001, worst_ticker="AAA", sample_label="22 of 22 orders (complete)"),
             "live/etf": dict(max_pct=0.004, worst_ticker="DBC", sample_label="8 of 8 orders (complete)")}
    sheets = {"live": C.load_sheet(C.BOOKS["live"], "live")}
    out = C.scenarios(stats, sheets, C.filter_applicability())
    s4 = [s for s in out if s["name"].startswith("S4_measured_")]
    assert len(s4) == 2
    for s in s4:
        assert any(QUALIFIER in x for x in s["assumptions"]), s["name"]
        assert not any(x == "Linear scaling of order size with the book." for x in s["assumptions"])
    for s in out:
        if any("LINEAR" in x.upper() for x in s["assumptions"]):
            assert any(QUALIFIER in x for x in s["assumptions"]), s["name"]


# ---------------------------------------------------------------- gate and verdict

def test_gate_blocks_the_announcement_when_notional_coverage_is_short():
    cov = {"live/stocks": dict(notional_coverage_pct=55.4, unknown_notional_usd=1000.0,
                              unknown_tickers=["QQQ"]),
           "live/etf": dict(notional_coverage_pct=100.0, unknown_notional_usd=0.0,
                            unknown_tickers=[])}
    g = C.announce_gate(cov)
    assert g["coverage_sufficient"] is False and g["blocked_cells"] == ["live/stocks"]
    v = C.capacity_verdict(g)
    assert v["status"] == "NOT_CERTIFIED"
    assert v["missing"][0].startswith("Coverage is insufficient in: live/stocks")


def test_gate_tolerance_admits_a_cell_whose_unknown_notional_is_exactly_zero():
    """100 * x / x is 99.99999999999999 for the live/stocks notional; a bare >= blocked it."""
    x = 7125.317155430973
    pct = 100.0 * x / x
    assert pct < 100.0                                   # the float fact this guards against
    g = C.announce_gate({"live/stocks": dict(notional_coverage_pct=pct,
                                             unknown_notional_usd=0.0, unknown_tickers=[])})
    assert g["coverage_sufficient"] is True
    # but the tolerance is far too small to admit a genuinely missing order
    g2 = C.announce_gate({"live/stocks": dict(notional_coverage_pct=96.2,
                                              unknown_notional_usd=270.0, unknown_tickers=["X"])})
    assert g2["coverage_sufficient"] is False


def test_capacity_is_never_certified_even_on_full_coverage():
    """Coverage is necessary, not sufficient. The verdict is hard-wired."""
    g = C.announce_gate({"live/etf": dict(notional_coverage_pct=100.0, unknown_notional_usd=0.0,
                                          unknown_tickers=[])})
    v = C.capacity_verdict(g)
    assert g["coverage_sufficient"] is True
    assert v["status"] == "NOT_CERTIFIED" and v["participation_measured"] is True
    assert any("impact model" in m for m in v["missing"])
    assert any("ledgers are empty" in m for m in v["missing"])
    assert "NOT announced" in v["statement"]


def test_empty_ledger_means_no_executions_recorded_and_names_the_evidence():
    """Instruction 8: nothing more, nothing less, and no invented fills."""
    led = C.ledger_evidence()
    assert led["books"]["live"]["n_ledger"] == 0 and led["books"]["paper"]["n_ledger"] == 0
    assert led["books"]["live"]["n_pending"] == 30 and led["books"]["paper"]["n_pending"] == 26
    assert "not evidence that trades did or did not happen" in led["meaning"]
    ev = " ".join(led["evidence_required_to_verify_external_execution"]).lower()
    for token in ("confirmation", "statement", "settlement", "position"):
        assert token in ev
    assert "VERIFIED SETTLE" in led["note"]


# ---------------------------------------------------------------- end to end

def test_run_end_to_end_on_a_fixture_store(tmp_path):
    """The whole pipeline over a synthetic store: ETFs covered, stocks covered, nothing pooled."""
    rows = []
    for t in ("AAA", "BBB"):
        rows += _flat(t, n=25, price=10.0, volume=100.0)          # ADV $1,000
    for t in ("SPY", "DBC"):
        rows += _flat(t, n=25, price=100.0, volume=1000.0)        # ADV $100,000
    db = _make_db(tmp_path, rows)

    live = tmp_path / "live.json"
    live.write_text(json.dumps(dict(
        date="2026-06-25", exec_date="2026-06-26", capital_reference=100_000.0, orders=[
            dict(sleeve="stocks", ticker="AAA", side="buy", dollars=10.0, est_price=10.0),
            dict(sleeve="stocks", ticker="BBB", side="buy", dollars=5.0, est_price=10.0),
            dict(sleeve="etf", ticker="SPY", side="buy", dollars=1000.0, est_price=100.0),
            dict(sleeve="etf", ticker="DBC", side="buy", dollars=2000.0, est_price=100.0),
        ])), encoding="utf-8")

    p = C.run(db_path=db, books=("live",), book_paths={"live": str(live)}, root=str(tmp_path))
    assert set(p["coverage"]) == {"live/stocks", "live/etf"}         # split, never pooled
    for c in p["coverage"].values():
        assert c["unknown_notional_usd"] == 0.0 and c["n_unknown"] == 0
    assert p["participation"]["live/stocks"]["max_pct"] == pytest.approx(1.0)     # $10 / $1,000
    assert p["participation"]["live/etf"]["max_pct"] == pytest.approx(2.0)        # $2,000/$100,000
    assert p["participation"]["live/etf"]["worst_ticker"] == "DBC"
    assert p["participation"]["live/stocks"]["breaches"]["gt_1pct"] == 0          # 1.0 is not > 1
    assert p["participation"]["live/etf"]["breaches"]["gt_1pct"] == 1
    assert p["announce_gate"]["coverage_sufficient"] is True
    assert p["capacity"]["status"] == "NOT_CERTIFIED"
    assert p["source"]["volume_units"] == "shares" and p["source"]["dollar_adv_units"] == "USD"
    assert p["hygiene"]["ghost_dates"] == []
    assert p["staleness"]["live"]["adv_is_current_to_sheet_date"] is True
    C.print_report(p)                                                # the printer must not raise


def test_run_on_the_real_books_covers_every_order_including_the_etfs():
    """The correction this cycle makes: 31/56 was a source bug, not a data gap.

    The production bar store carries volume for all eight ETFs. If this ever regresses, the
    gate blocks and the test says which cell lost coverage.
    """
    db = C.DEFAULT_DB
    assert os.path.exists(db), f"production bar store missing: {db}"
    p = C.run(db_path=db)
    assert set(p["coverage"]) == {"live/stocks", "live/etf", "paper/stocks", "paper/etf"}
    assert sum(c["n_orders"] for c in p["coverage"].values()) == 56
    assert sum(c["n_known"] for c in p["coverage"].values()) == 56
    for key, c in p["coverage"].items():
        assert c["unknown_notional_usd"] == pytest.approx(0.0), key
    etf = [r for r in p["orders"] if r["sleeve"] == "etf"]
    assert len(etf) == 16 and all(r["known"] for r in etf)
    assert {r["ticker"] for r in etf} == {"SPY", "QQQ", "IWM", "EFA", "EEM", "GLD", "DBC", "VNQ"}
    # every measured participation is far under 1 % - but the verdict is still not capacity
    assert max(r["participation_pct"] for r in p["orders"]) < 0.01
    assert p["announce_gate"]["coverage_sufficient"] is True
    assert p["capacity"]["status"] == "NOT_CERTIFIED"
    # the paper sheet's ADV is stale: its own date is past the store's last bar
    assert p["staleness"]["live"]["adv_is_current_to_sheet_date"] is True
    assert p["staleness"]["paper"]["adv_is_current_to_sheet_date"] is False


def test_percentile_is_linear_interpolation_and_checkable_by_hand():
    assert C._pctile([], 50.0) is None
    assert C._pctile([7.0], 95.0) == 7.0
    assert C._pctile([0.0, 1.0, 2.0, 3.0, 4.0], 50.0) == pytest.approx(2.0)
    assert C._pctile([0.0, 10.0], 95.0) == pytest.approx(9.5)
    assert C._pctile([0.0, 1.0, 2.0, 3.0], 95.0) == pytest.approx(2.85)


def test_bar_source_is_read_only(tmp_path):
    """The store is live data. The connection must refuse a write, not merely avoid one."""
    src = C.BarSource(_make_db(tmp_path, _flat("AAA", n=3)))
    try:
        with pytest.raises(sqlite3.OperationalError):
            src.con.execute("DELETE FROM bars")
    finally:
        src.close()


def test_math_floor_semantics_match_the_sheet_reprint():
    """Sanity: flooring, never rounding - 1.99 shares is one share, not two."""
    assert math.floor(1.99) == 1
    sheet = _sheet("live", "2026-06-25", [_order("AAA", 199.0, price=100.0)], cap=1000.0)
    assert C.whole_share_impact(sheet)["book_placeable_usd"] == pytest.approx(100.0)


# --- audited-run configuration: discovery / validation / reconstruction -------------------
#
# These use tmp_path only. The previous test asserted that THIS MACHINE has no run manifest
# today, which pins a circumstance of the disk rather than a contract. Every manifest below is
# SYNTHETIC and labelled as such - no historical evidence is invented to manufacture a pass.

def _synthetic_manifest(filters, date="2026-09-04", algo="v9"):
    """A runlog-shaped manifest. SYNTHETIC: built for this test, not recovered from any run."""
    return {
        "SYNTHETIC": "fixture built by test_capacity_434 - not evidence of any real run",
        "ALGO_VERSION": algo,
        "date": date,
        "config": {"FILTERS": C._sha256_of_config(filters), "V9": "0" * 64},
    }


def _write_run(root, run_name, payload):
    """Write at the real runlog layout: <root>/runs/<run>/manifest.json (utils/runlog.py:132)."""
    d = root / "runs" / run_name
    d.mkdir(parents=True, exist_ok=True)
    f = d / "manifest.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    return f


def _assert_coherent(r):
    """The contract, checked on every branch: reconstructible iff a value came back."""
    assert r["reconstructible"] == (r["value_usd"] is not None)
    if r["reconstructible"]:
        assert "RECONSTRUCTED" in r["note"]
    else:
        assert "NOT RECONSTRUCTIBLE" in r["note"]


def test_no_evidence_at_all_is_refused(tmp_path):
    r = C.audited_run_threshold(str(tmp_path), audited_dates=["2026-09-04"])
    assert r["reconstructible"] is False and r["candidates_found"] == []
    _assert_coherent(r)


def test_a_foreign_file_and_invalid_json_never_make_it_reconstructible(tmp_path):
    """The regression Codex found: a NAME containing 'manifest' used to return True."""
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "unrelated_manifest.json").write_text("not valid JSON", encoding="utf-8")
    r = C.audited_run_threshold(str(tmp_path), audited_dates=["2026-09-04"])
    assert r["candidates_found"], "discovery must still report the candidate"
    assert r["reconstructible"] is False
    assert "does not parse as JSON" in r["examined"][0]["reason"]
    _assert_coherent(r)


def test_a_manifest_in_the_real_runlog_layout_is_discovered(tmp_path):
    """runlog writes runs/<run>/manifest.json - a flat listing of runs/ used to miss it."""
    filters = {"min_dollar_volume": 5_000_000, "min_avg_volume": 100_000}
    _write_run(tmp_path, "20260904_120000", _synthetic_manifest(filters))
    r = C.audited_run_threshold(str(tmp_path), audited_dates=["2026-09-04"])
    assert r["usable_manifests"], "the nested manifest must be found and validated"
    # found and usable, but still not reconstructible: a sha256 is not a value
    assert r["reconstructible"] is False
    assert "does not invert" in r["note"]
    _assert_coherent(r)


def test_a_manifest_for_the_wrong_run_date_is_rejected(tmp_path):
    filters = {"min_dollar_volume": 5_000_000}
    _write_run(tmp_path, "20250101_000000", _synthetic_manifest(filters, date="2025-01-01"))
    r = C.audited_run_threshold(str(tmp_path), audited_dates=["2026-09-04"])
    assert r["reconstructible"] is False and r["usable_manifests"] == []
    assert "not to the audited sheet" in r["examined"][0]["reason"]
    _assert_coherent(r)


def test_a_candidate_config_whose_hash_disagrees_is_refused(tmp_path):
    _write_run(tmp_path, "20260904_120000",
               _synthetic_manifest({"min_dollar_volume": 5_000_000}))
    r = C.audited_run_threshold(
        str(tmp_path), audited_dates=["2026-09-04"],
        candidate_configs={"relaxed": {"min_dollar_volume": 0}})   # hashes to something else
    assert r["reconstructible"] is False and r["value_usd"] is None
    assert "no supplied candidate configuration hashes" in r["note"]
    _assert_coherent(r)


def test_a_usable_manifest_plus_a_matching_candidate_reconstructs(tmp_path):
    """The positive control, on SYNTHETIC evidence only."""
    filters = {"min_dollar_volume": 5_000_000, "min_avg_volume": 100_000}
    _write_run(tmp_path, "20260904_120000", _synthetic_manifest(filters))
    r = C.audited_run_threshold(str(tmp_path), audited_dates=["2026-09-04"],
                                candidate_configs={"declared": filters})
    assert r["reconstructible"] is True and r["value_usd"] == 5_000_000.0
    assert r["matched"]["candidate"] == "declared"
    _assert_coherent(r)


def test_the_published_block_carries_the_same_verdict(tmp_path):
    """Coherence must survive into the published artifact, not just the helper."""
    blk = C.filter_applicability()
    a = blk["threshold_of_the_audited_run"]
    assert a["reconstructible"] == (a["value_usd"] is not None)
    assert a["reconstructible"] is False, "no real manifest is tied to the audited sheets"
    assert "NOT RECONSTRUCTIBLE" in a["note"]
    assert blk["threshold_declared_usd"] == 5_000_000.0
    assert "ast" in blk["threshold_source"]



def test_the_three_capital_quantities_are_each_computed_from_the_sheet():
    """Pin the three VALUES independently, not the tautology that relates them.

    `identity_holds` is self-consistency, not evidence: given the definitions
    (residual = cap - placeable, rounding = requested - placeable, not_requested = cap - requested)
    the identity is algebraically necessary and can never report False, so asserting it catches
    nothing - an adversary replaced it with a literal `True` and the suite stayed green. What IS
    falsifiable is each quantity against an independent recomputation from the sheet, which is
    what this does. The docstring of `whole_share_impact` is the claim under test.
    """
    sheet = dict(
        book="synthetic", date="2026-09-04", capital_reference=10_000.0,
        orders=[dict(sleeve="stock", ticker="AAA", est_price=100.0, dollars=1_000.0),
                dict(sleeve="stock", ticker="BBB", est_price=333.0, dollars=500.0)],
    )
    r = C.whole_share_impact(sheet)
    cs = r["capital_split"]

    # independent arithmetic, straight from the sheet: whole shares only
    requested = 1_000.0 + 500.0
    placeable = int(1_000.0 // 100.0) * 100.0 + int(500.0 // 333.0) * 333.0   # 1000 + 333
    assert cs["requested_usd"] == pytest.approx(requested)
    assert cs["placeable_usd"] == pytest.approx(placeable)
    assert cs["rounding_residue_usd"] == pytest.approx(requested - placeable)   # 167.0
    assert cs["not_requested_usd"] == pytest.approx(10_000.0 - requested)       # 8500.0
    assert cs["residual_cash_usd"] == pytest.approx(10_000.0 - placeable)       # 8667.0
    # the three still reconcile, and realised loss stays unmeasurable
    assert cs["realised_economic_loss_usd"] is None
    assert "NOT MEASURABLE" in cs["labels"]["realised_economic_loss_usd"]
