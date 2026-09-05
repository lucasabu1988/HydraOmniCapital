"""
Trading-calendar helpers driven by an actual price index, never by a weekday guess.

Why this exists (project audit 2026-09-06, findings T1 and S4): `core/tracking.py` measured
"5d" horizons in calendar days — 3 trading days in 65% of cycles — and the Excel logger used a
Mon-Fri calendar with no holidays. Two P&L systems, two wrong calendars. Every horizon and
entry decision in the project now goes through these four functions, and all of them take the
real bar index of the price series they operate on, so a holiday or a data gap is handled by
construction rather than by assumption.

Positions are integer offsets into `index`; callers turn them back into dates/prices.
"""
import numpy as np
import pandas as pd


def _as_index(index) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(index)
    return idx.normalize()


def signal_bar(index, run_date):
    """Position of the last bar on or before `run_date`: the bar the screener actually saw.

    Returns None if no bar exists on or before that date.
    """
    idx = _as_index(index)
    pos = idx.searchsorted(pd.Timestamp(run_date).normalize(), side="right") - 1
    return int(pos) if pos >= 0 else None


def first_bar_after(index, date):
    """Position of the first bar strictly after `date`: the earliest executable close.

    A recommendation produced from the close of day D cannot be bought at that close; the
    first price anyone can actually get is the next session. Returns None if that bar does
    not exist yet.
    """
    idx = _as_index(index)
    pos = idx.searchsorted(pd.Timestamp(date).normalize(), side="right")
    return int(pos) if pos < len(idx) else None


def bar_ahead(index, pos, n_bars):
    """`pos + n_bars` if that bar exists, else None (not enough forward history yet).

    `n_bars` is in trading days by definition, because it counts bars.
    """
    if pos is None:
        return None
    target = int(pos) + int(n_bars)
    return target if 0 <= target < len(index) else None


def business_days_behind(last_bar, today=None) -> int:
    """How many weekdays separate the last bar we have from today.

    Weekday-based (numpy busday), so a market holiday shows up as one extra day. Good enough
    for a staleness WARNING - a false alarm a few times a year - and deliberately not used to
    block a run. 0 means the last bar is today; 1 means yesterday's close.
    """
    today = pd.Timestamp(today or pd.Timestamp.now()).normalize()
    last = pd.Timestamp(last_bar).normalize()
    if last >= today:
        return 0
    return int(np.busday_count(last.date(), today.date()))
