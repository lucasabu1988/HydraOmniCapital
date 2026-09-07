"""TASK-402 — the sheet's valuation, and a fixture that can actually falsify it.

The first pass at this replaced `prices.iloc[-1]` with "this bar's prints or nothing" and was
returned by review on two counts, both correct:

  1. **it was not falsifiable.** Its fixture put NaN on the last bar, and there the old and new
     code agree — `iloc[-1]` is NaN too. The case that separates them is a FORWARD FILL: a cell
     that holds a number the ticker never printed. `data.fetch` creates exactly that (ETF holes
     are filled so a 252-bar signal window survives a one-bar gap) and records what really
     printed in `frame.attrs["observed"]`. Every fixture here carries that mask, so reverting the
     mark to `prices.iloc[-1]` turns these tests red.
  2. **it made the total worse where it bit.** Refusing the filled price is right; falling through
     to `value_with_stale`'s `last_px` is not, because that is the price the tranche BOUGHT at. A
     name that printed yesterday and not today was valued at its entry rather than at yesterday's
     close — further from reality, not closer. `last_observed` walks back to the most recent real
     print and says how old it is.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import portfolio_v9 as V
from config import V9
from core import portfolio_engine as E
from data.fetch import OBSERVED_ATTR

IDX = pd.to_datetime(["2026-09-08", "2026-09-09", "2026-09-10"])


def _frame(values: dict, printed: dict) -> pd.DataFrame:
    """A frame with a forward-filled cell and the mask that says it was not a print."""
    f = pd.DataFrame(values, index=IDX)
    f.attrs[OBSERVED_ATTR] = pd.DataFrame(printed, index=IDX)
    return f


# ------------------------------------------------------------------ last_observed
def test_a_forward_filled_cell_is_not_taken_as_a_price():
    """The falsifying case. AAA printed 100 on the 9th; the 10th is a fill of that same number."""
    f = _frame({"AAA": [98.0, 100.0, 100.0]}, {"AAA": [True, True, False]})
    values, asof = V.last_observed(f)
    assert values["AAA"] == pytest.approx(100.0)
    assert asof["AAA"] == "2026-09-09", "the price is real, and it is the 9th's, not the 10th's"


def test_the_fill_and_the_print_are_told_apart_even_when_the_numbers_differ():
    f = _frame({"AAA": [98.0, 100.0, 123.0]}, {"AAA": [True, True, False]})
    values, asof = V.last_observed(f)
    assert values["AAA"] == pytest.approx(100.0), "123 was never printed; 100 was"
    assert asof["AAA"] == "2026-09-09"


def test_a_name_printing_on_the_last_bar_is_priced_there():
    f = _frame({"AAA": [98.0, 100.0, 101.0]}, {"AAA": [True, True, True]})
    values, asof = V.last_observed(f)
    assert values["AAA"] == pytest.approx(101.0) and asof["AAA"] == "2026-09-10"


def test_a_name_that_never_printed_has_no_price_and_no_date():
    f = _frame({"AAA": [np.nan, np.nan, np.nan]}, {"AAA": [False, False, False]})
    values, asof = V.last_observed(f)
    assert pd.isna(values["AAA"]) and "AAA" not in asof


def test_an_unprovenanced_frame_falls_back_to_notna():
    """A frame built by hand has no mask; `notna()` is then the best available answer."""
    f = pd.DataFrame({"AAA": [98.0, np.nan, 100.0]}, index=IDX)
    values, asof = V.last_observed(f)
    assert values["AAA"] == pytest.approx(100.0) and asof["AAA"] == "2026-09-10"


def test_an_empty_frame_prices_nothing():
    values, asof = V.last_observed(pd.DataFrame())
    assert values.empty and asof == {}


# ------------------------------------------------------------------ through the sheet
def _market(_universe=None):
    """AAA holds; it prints on the 9th and the 10th is a FILL. The ETFs print throughout."""
    prices = _frame({"AAA": [98.0, 100.0, 100.0]}, {"AAA": [True, True, False]})
    etf = pd.DataFrame({t: [100.0, 100.0, 101.0] for t in V9["etf_universe"]}, index=IDX)
    etf.attrs[OBSERVED_ATTR] = pd.DataFrame(
        {t: [True, True, True] for t in V9["etf_universe"]}, index=IDX)
    return dict(prices=prices, volumes=prices * 1000,
                spy=pd.Series([400.0, 401.0, 402.0], index=IDX, name="SPY"),
                etf=etf, irx=pd.Series([5.25, 5.25, 5.20], index=IDX),
                stock_report={}, etf_report={}, irx_report={})


def _rank(prices, spy, volumes):
    return pd.DataFrame({"ticker": ["AAA"], "rank": [1], "sector": ["Other"],
                         "recommended": [False], "reason": [""], "recommended_count": [0]})


def _held(state_dir: Path, entry_price: float) -> Path:
    """A tranche holding 10 AAA bought at `entry_price`, so entry and last print differ."""
    state = E.new_state(8000.0, "2026-09-04", V9)
    state["last_run_date"] = "2026-09-09"
    tr = state["sleeves"]["stocks"]["tranches"][0]
    tr["units"], tr["last_px"], tr["cash"] = {"AAA": 10.0}, {"AAA": entry_price}, 0.0
    state["ledger"] = [dict(exec_date="2026-09-08", sleeve="stocks", tranche=0, ticker="AAA",
                            side="buy", units=10.0, price=entry_price, dollars=10.0 * entry_price,
                            cost=0.0, status="filled")]
    path = state_dir / V.STATE_NAME
    path.write_text(json.dumps(state), encoding="utf-8")
    return path


def test_the_book_is_valued_at_the_last_real_print_not_at_the_entry_price(tmp_path, monkeypatch):
    """The second blocker, as a number. Entry 60, last real print 100, filled cell 100 on the 10th.

    Marking at the entry (what the first pass did once it refused the fill) values the position at
    600; marking at the last real print values it at 1000. 1000 is the answer: the price is real,
    it is simply a day older, and the sheet says so.
    """
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))
    _held(tmp_path, entry_price=60.0)
    out = V.run(tmp_path, fetch_fn=_market, rank_fn=_rank, silent=True,
                dividend_fn=lambda _t: [], force=True)
    stocks = out["summary"]["sleeves"]["stocks"]
    assert stocks["value"] == pytest.approx(1000.0 + 3000.0, abs=1.0), (
        "10 units at the last real print of 100, plus the 3000 the other three tranches hold")
    assert out["summary"]["priced_asof"]["AAA"] == "2026-09-09"
    assert out["summary"]["carried_forward"] == [("AAA", "2026-09-09")]
    assert out["summary"]["carried_stale"] == [], "AAA has a real price; it is not carried at entry"


def test_the_sheet_says_the_price_is_older_than_the_bar(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))
    _held(tmp_path, entry_price=60.0)
    out = V.run(tmp_path, fetch_fn=_market, rank_fn=_rank, silent=True,
                dividend_fn=lambda _t: [], force=True)
    sheet = Path(out["instructions_md"]).read_text(encoding="utf-8")
    assert "## Valuation (each name at its last real print, bar 2026-09-10)" in sheet
    assert "Priced at an earlier print than 2026-09-10: **AAA (2026-09-09)**" in sheet
    # and it must NOT claim every price printed on the valuation bar, which the old header did
    assert "closes that printed on" not in sheet


def test_a_name_with_no_print_at_all_is_still_carried_at_the_entry_and_labelled(tmp_path, monkeypatch):
    """The `last_px` fallback survives for the case it was written for (SPEC 9.4)."""
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))

    def dark(_universe=None):
        m = _market()
        m["prices"] = _frame({"AAA": [np.nan, np.nan, np.nan]}, {"AAA": [False, False, False]})
        m["volumes"] = m["prices"] * 1000
        return m

    _held(tmp_path, entry_price=60.0)
    out = V.run(tmp_path, fetch_fn=dark, rank_fn=_rank, silent=True,
                dividend_fn=lambda _t: [], force=True)
    assert out["summary"]["carried_stale"] == ["AAA"]
    assert "AAA" not in out["summary"]["priced_asof"]
    sheet = Path(out["instructions_md"]).read_text(encoding="utf-8")
    assert "carried at the price the tranche bought at: **AAA**" in sheet
    # 10 units at the entry of 60 + the 3000 the other tranches hold
    assert out["summary"]["sleeves"]["stocks"]["value"] == pytest.approx(600.0 + 3000.0, abs=1.0)


def test_the_state_absorbs_a_filled_price_and_resets_the_write_off_clock(tmp_path, monkeypatch):
    """DOCUMENTS A LIVE DEFECT one step earlier than this task, and says whose it is.

    `core.tranche_book.age_stale(px)` refreshes `tr.last_px[tk]` for every FINITE price it is
    handed and resets `tr.stale[tk]`. It is handed the frame's prices, forward fills included, so
    the book's own record of value absorbs a number the ticker never printed and the write-off
    clock restarts. `data.fetch` fills up to 3 bars, so a name that stops printing can get three
    resets per gap while `max_stale_bars = 10` counts a mixture of prints and fills.

    This is why the sheet's total does not move end to end: the state was already carrying the
    filled price before the sheet was built. NOT fixed here — `age_stale` is the accounting of
    staleness and write-offs, which is H-005 (ASTRA-08), registered PROPOSED and awaiting Lucas
    with a measurement. This test pins the behaviour so the fix cannot land unnoticed, and it
    asserts what IS true today rather than what should be.

    Detail: .comms/task-402-mark-and-a-deeper-finding.md
    """
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))
    _held(tmp_path, entry_price=60.0)
    out = V.run(tmp_path, fetch_fn=_market, rank_fn=_rank, silent=True,
                dividend_fn=lambda _t: [], force=True)
    state = json.loads(Path(out["state_path"]).read_text(encoding="utf-8"))
    tr = state["sleeves"]["stocks"]["tranches"][0]
    assert tr["last_px"]["AAA"] == pytest.approx(100.0), (
        "today the state takes the filled cell as a price; when H-005 lands this becomes 100.0 "
        "from the 09-09 PRINT and the assertion below is what changes")
    assert tr.get("stale") in ({}, None), (
        "and the write-off clock was reset by a bar the ticker never printed")
    # the sheet, meanwhile, is honest about it: same number, dated correctly
    assert out["summary"]["priced_asof"]["AAA"] == "2026-09-09"
