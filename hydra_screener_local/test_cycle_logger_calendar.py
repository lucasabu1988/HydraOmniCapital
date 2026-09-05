"""log_cycle_positions.py enters at the bar AFTER the signal and exits CYCLE_BARS bars later,
on the real price index — no weekday counting, no network (download is patched)."""
import numpy as np
import pandas as pd
from unittest.mock import patch

import log_cycle_positions as lcp

# Two trading weeks: Monday 2026-09-07 is a holiday, Thursday 2026-09-17 is a data gap.
IDX = pd.DatetimeIndex([
    "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
    "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
    "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-18",
])
CLOSES = pd.Series(np.arange(100.0, 100.0 + len(IDX)), index=IDX)


def fake_download(tkr, start, end):
    s = CLOSES[(CLOSES.index >= pd.Timestamp(start)) & (CLOSES.index < pd.Timestamp(end))]
    return s if len(s) else None


def test_entry_is_bar_after_signal_and_exit_is_five_bars_later():
    with patch.object(lcp, "_download_closes", side_effect=fake_download):
        r = lcp._resolve_cycle("AAA", "2026-09-04")       # Friday signal, Monday is a holiday
    assert r["entry_date"] == pd.Timestamp("2026-09-08")    # not the Friday close, not the holiday
    assert r["entry_price"] == float(CLOSES["2026-09-08"])
    # 5 BARS after 09-08 -> 09-15. Five weekdays would have said 09-11 (or 09-14 with the holiday).
    assert r["end_date"] == pd.Timestamp("2026-09-15")


def test_saturday_signal_resolves_to_the_same_entry_as_friday():
    with patch.object(lcp, "_download_closes", side_effect=fake_download):
        fri = lcp._resolve_cycle("AAA", "2026-09-04")
        sat = lcp._resolve_cycle("AAA", "2026-09-05")
    assert sat == fri


def test_no_next_bar_yet_means_provisional():
    with patch.object(lcp, "_download_closes", side_effect=fake_download):
        r = lcp._resolve_cycle("AAA", "2026-09-18")        # signal on the last available bar
    assert r["entry_price"] is None and r["entry_date"] is None and r["end_date"] is None


def test_log_cycle_uses_executable_close_not_the_signal_close(tmp_path):
    xlsx = tmp_path / "portfolio_cycles.xlsx"
    with patch.object(lcp, "_download_closes", side_effect=fake_download), \
         patch.object(lcp, "EXCEL_PATH", str(xlsx)):
        lcp.log_cycle("2026-09-04", ["AAA", "BBB"], notes="t",
                      entry_prices={"AAA": 999.0, "BBB": 999.0})   # the observed signal close
    pos = pd.read_excel(xlsx, sheet_name="All_Positions")
    summ = pd.read_excel(xlsx, sheet_name="Cycle_Summaries")
    assert (pos["entry_price"] == float(CLOSES["2026-09-08"])).all()        # 999 was NOT used
    assert (pd.to_datetime(pos["entry_date"]) == pd.Timestamp("2026-09-08")).all()
    assert pd.Timestamp(summ["end_date"].iloc[0]) == pd.Timestamp("2026-09-15")
    assert pd.Timestamp(summ["start_date"].iloc[0]) == pd.Timestamp("2026-09-04")  # signal date kept


def test_live_run_before_next_bar_keeps_provisional_entry(tmp_path):
    xlsx = tmp_path / "portfolio_cycles.xlsx"
    with patch.object(lcp, "_download_closes", side_effect=fake_download), \
         patch.object(lcp, "EXCEL_PATH", str(xlsx)):
        lcp.log_cycle("2026-09-18", ["AAA"], notes="live", entry_prices={"AAA": 111.0})
    pos = pd.read_excel(xlsx, sheet_name="All_Positions")
    summ = pd.read_excel(xlsx, sheet_name="Cycle_Summaries")
    assert pos["entry_price"].iloc[0] == 111.0            # provisional, from the caller
    assert pd.isna(pos["entry_date"].iloc[0])             # marked as not yet resolved
    assert pd.isna(summ["end_date"].iloc[0])


def test_backtest_fills_are_trusted_without_download(tmp_path):
    xlsx = tmp_path / "portfolio_cycles.xlsx"
    with patch.object(lcp, "_download_closes", side_effect=AssertionError("must not download")), \
         patch.object(lcp, "EXCEL_PATH", str(xlsx)):
        lcp.log_cycle("2026-09-04", ["AAA"], notes="backtest",
                      entry_prices={"AAA": 50.0}, realized_prices={"AAA": 55.0})
    pos = pd.read_excel(xlsx, sheet_name="All_Positions")
    assert pos["entry_price"].iloc[0] == 50.0 and pos["current_price"].iloc[0] == 55.0
