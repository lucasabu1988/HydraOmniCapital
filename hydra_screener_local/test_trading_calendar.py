"""utils/trading_calendar.py — positions come from the real bar index, not from weekdays."""
import pandas as pd

from utils.trading_calendar import signal_bar, first_bar_after, bar_ahead, business_days_behind

# Two trading weeks with a Monday holiday (2026-09-07 is missing) and a data gap on Thu 09-17.
IDX = pd.DatetimeIndex([
    "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
    "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
    "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-18",
])


def test_signal_bar_is_last_bar_on_or_before_run_date():
    assert IDX[signal_bar(IDX, "2026-09-04")] == pd.Timestamp("2026-09-04")   # exact
    assert IDX[signal_bar(IDX, "2026-09-05")] == pd.Timestamp("2026-09-04")   # Saturday run
    assert IDX[signal_bar(IDX, "2026-09-07")] == pd.Timestamp("2026-09-04")   # holiday run
    assert signal_bar(IDX, "2026-08-31") is None


def test_first_bar_after_skips_weekend_and_holiday():
    # Signal on Friday the 4th; Monday the 7th is a holiday, so the first fill is Tuesday the 8th.
    assert IDX[first_bar_after(IDX, "2026-09-04")] == pd.Timestamp("2026-09-08")
    # A run dated on the holiday itself still resolves to the same first executable bar.
    assert IDX[first_bar_after(IDX, "2026-09-07")] == pd.Timestamp("2026-09-08")
    assert first_bar_after(IDX, "2026-09-18") is None


def test_bar_ahead_counts_bars_not_days():
    entry = first_bar_after(IDX, "2026-09-04")            # 09-08
    exit5 = bar_ahead(IDX, entry, 5)
    # 5 BARS after 09-08: 09-09, 09-10, 09-11, 09-14, 09-15 -> 09-15 (calendar days would say 09-13)
    assert IDX[exit5] == pd.Timestamp("2026-09-15")
    assert bar_ahead(IDX, entry, 10) is None               # not enough forward history
    assert bar_ahead(IDX, None, 5) is None


def test_business_days_behind():
    assert business_days_behind("2026-09-04", today="2026-09-04") == 0
    assert business_days_behind("2026-09-03", today="2026-09-04") == 1
    assert business_days_behind("2026-09-04", today="2026-09-07") == 1   # over a weekend: Monday
    assert business_days_behind("2026-09-01", today="2026-09-08") == 5
