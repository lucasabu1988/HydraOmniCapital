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


# --------------------------------------------------------------------------- forward-looking NYSE calendar
# The four helpers above need a price index, which does not yet contain tomorrow. The instruction
# sheet ("execute at the close of t+1") and the dashboard need the NEXT session before it prints,
# and a plain next-weekday guess put Labor Day 2026-09-07 on the first production sheet (found
# 2026-09-06). Regular NYSE closures below; ad-hoc closures (days of mourning, disasters) are not
# knowable in advance - the price index remains the authority once the bar exists.
from pandas.tseries.holiday import (AbstractHolidayCalendar, GoodFriday, Holiday, USLaborDay,  # noqa: E402
                                    USMartinLutherKingJr, USMemorialDay, USPresidentsDay,
                                    USThanksgivingDay, nearest_workday, sunday_to_monday)


class NYSEHolidayCalendar(AbstractHolidayCalendar):
    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=sunday_to_monday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas Day", month=12, day=25, observance=nearest_workday),
    ]


def nyse_holidays(start, end) -> pd.DatetimeIndex:
    return NYSEHolidayCalendar().holidays(pd.Timestamp(start), pd.Timestamp(end))


def is_nyse_session(date) -> bool:
    d = pd.Timestamp(date).normalize()
    if d.weekday() >= 5:
        return False
    return d not in nyse_holidays(d, d)


def next_nyse_session(date) -> str:
    """First regular NYSE session strictly after `date` (weekends and the holidays above skipped)."""
    d = pd.Timestamp(date).normalize() + pd.Timedelta(days=1)
    while not is_nyse_session(d):
        d += pd.Timedelta(days=1)
    return str(d.date())


def last_nyse_session_on_or_before(date) -> str:
    d = pd.Timestamp(date).normalize()
    while not is_nyse_session(d):
        d -= pd.Timedelta(days=1)
    return str(d.date())


# --------------------------------------------------------------------------- clock, not calendar
# ASTRA-03: every helper above normalises the time away, which is right for naming a session and
# wrong for deciding whether that session has printed its close. A run started at 11:00 ET sees a
# last bar dated today (yfinance serves the live, partial bar) and `last_nyse_session_on_or_before`
# agrees with it, so the preflight date comparison passes and fills get booked at an intraday
# price. These two functions are the only ones in the file that look at the time of day.
NYSE_TZ = "America/New_York"
NYSE_CLOSE_ET = (16, 0)
NYSE_EARLY_CLOSE_ET = (13, 0)
# yfinance keeps serving the live bar for a few minutes after the bell; the settled close is not
# necessarily the 16:00 print until the tape is done.
CLOSE_SETTLE_BUFFER_MIN = 15


def to_eastern(clock) -> pd.Timestamp:
    """`clock` as an America/New_York timestamp. A naive input is the machine's local wall clock."""
    ts = pd.Timestamp(clock)
    if ts.tz is None:
        from dateutil.tz import tzlocal
        ts = ts.tz_localize(tzlocal())
    return ts.tz_convert(NYSE_TZ)


def nyse_early_closes(year: int) -> set:
    """The 1pm ET half sessions: July 3, the Friday after Thanksgiving, Dec 24.

    Each counts only when it is itself a session (July 3 also needs July 4 to be a weekday, i.e.
    not observed on the 3rd or the 5th). Ad-hoc early closes are not knowable in advance.
    """
    out = set()
    thanksgiving = nyse_holidays(f"{year}-11-01", f"{year}-11-30")
    for d in thanksgiving:
        if d.month == 11 and d.weekday() == 3:                # the Thursday
            after = d + pd.Timedelta(days=1)
            if is_nyse_session(after):
                out.add(after.normalize())
    jul3 = pd.Timestamp(year=year, month=7, day=3)
    if is_nyse_session(jul3) and is_nyse_session(jul3 + pd.Timedelta(days=1)):
        out.add(jul3.normalize())
    dec24 = pd.Timestamp(year=year, month=12, day=24)
    if is_nyse_session(dec24):
        out.add(dec24.normalize())
    return out


def session_close_et(date) -> tuple:
    """(hour, minute) of the closing bell for `date` in ET: 16:00, or 13:00 on a half session."""
    d = pd.Timestamp(date).normalize()
    return NYSE_EARLY_CLOSE_ET if d in nyse_early_closes(d.year) else NYSE_CLOSE_ET


def session_is_closed(clock, *, buffer_minutes: int = CLOSE_SETTLE_BUFFER_MIN) -> bool:
    """Has the NYSE session covering `clock` printed its close (plus `buffer_minutes`)?

    True on a non-session day: whatever bar the frames hold is a finished one. Fail-closed by
    construction — anything it cannot resolve reads as "still open", which blocks a settlement.
    """
    et = to_eastern(clock)
    day = pd.Timestamp(et.year, et.month, et.day)
    if not is_nyse_session(day):
        return True
    hour, minute = session_close_et(day)
    bell = et.normalize() + pd.Timedelta(hours=hour, minutes=minute + int(buffer_minutes))
    return et >= bell
