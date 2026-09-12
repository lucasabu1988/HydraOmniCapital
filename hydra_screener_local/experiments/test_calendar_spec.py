"""The derived grid must catch truncation, shift, omission and duplicates - not just count."""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import calendar_spec as CSPEC  # noqa: E402
import engine_backtest as EB  # noqa: E402


def _calendar(n=1000):
    return pd.bdate_range("2010-01-04", periods=n)


def _membership(cal, first=300):
    """A record that is empty until `first`, like the Russell overlay before its first date."""
    m = pd.DataFrame(False, index=cal, columns=["AAA", "BBB"])
    m.iloc[first:, 0] = True
    return m


def test_the_grid_comes_from_the_rules_and_not_from_any_book():
    cal = _calendar()
    spec = CSPEC.expected_grid(cal)
    # start = warmup (no membership supplied), stride = STEP, bound = len - 6
    assert spec["start_bar"] == EB.START
    assert spec["step"] == EB.STEP
    assert spec["n_marks"] == len(range(EB.START, len(cal) - 6, EB.STEP))
    assert list(spec["marks"]) == list(cal[range(EB.START, len(cal) - 6, EB.STEP)])
    # and it says what it is, and is not
    assert "NOT independent confirmation" in spec["basis"]
    assert "NOT ESTABLISHED" in spec["calendar_identity"]


def test_membership_moves_the_start_when_it_is_later_than_the_warmup():
    cal = _calendar()
    spec = CSPEC.expected_grid(cal, _membership(cal, first=400))
    assert spec["start_bar"] == 400          # max(280, 400)
    spec_early = CSPEC.expected_grid(cal, _membership(cal, first=100))
    assert spec_early["start_bar"] == EB.START   # max(280, 100)


def test_an_empty_membership_record_is_an_error_not_a_default():
    cal = _calendar()
    empty = pd.DataFrame(False, index=cal, columns=["AAA"])
    with pytest.raises(ValueError, match="membership is empty"):
        CSPEC.expected_grid(cal, empty)


def test_the_valid_book_passes():
    cal = _calendar()
    spec = CSPEC.expected_grid(cal)
    r = CSPEC.validate_marks(spec["marks"], spec)
    assert r["ok"] and r["problems"] == []


def test_truncation_is_named_as_truncation():
    cal = _calendar()
    spec = CSPEC.expected_grid(cal)
    r = CSPEC.validate_marks(spec["marks"][:-20], spec)
    assert not r["ok"] and r["n_missing"] == 20 and r["n_extra"] == 0
    assert "expected mark(s)" in r["problems"][0]


def test_a_shift_of_the_same_length_is_not_mistaken_for_a_valid_book():
    """The count matches exactly - only a date-by-date comparison catches this."""
    cal = _calendar()
    spec = CSPEC.expected_grid(cal)
    shifted = pd.DatetimeIndex(spec["marks"]) + pd.Timedelta(days=1)
    r = CSPEC.validate_marks(shifted, spec)
    assert not r["ok"] and r["n_got"] == r["n_expected"]
    assert any("a shift, not a truncation" in p for p in r["problems"])


def test_an_omission_in_the_middle_is_caught():
    cal = _calendar()
    spec = CSPEC.expected_grid(cal)
    marks = pd.DatetimeIndex(spec["marks"])
    dropped = marks.delete(len(marks) // 2)
    r = CSPEC.validate_marks(dropped, spec)
    assert not r["ok"] and r["n_missing"] == 1


def test_a_duplicate_is_caught_even_when_the_length_is_right():
    """One dropped and one duplicated keeps the count identical."""
    cal = _calendar()
    spec = CSPEC.expected_grid(cal)
    marks = list(spec["marks"])
    marks = marks[:6] + [marks[5]] + marks[7:]      # duplicate marks[5], drop marks[6]
    r = CSPEC.validate_marks(pd.DatetimeIndex(marks), spec)
    assert not r["ok"]
    assert any("duplicated marks" in p for p in r["problems"])


def test_a_bad_input_calendar_is_refused_before_a_grid_is_derived():
    cal = _calendar(50)
    with pytest.raises(ValueError, match="duplicate dates"):
        CSPEC.expected_grid(cal.append(cal[-1:]).sort_values())
    with pytest.raises(ValueError, match="not sorted"):
        CSPEC.expected_grid(cal[::-1])


def test_equality_between_books_is_not_validation():
    """Two books can agree perfectly and both be on the wrong grid - the point of this module."""
    cal = _calendar()
    spec = CSPEC.expected_grid(cal)
    wrong = pd.DatetimeIndex(spec["marks"]) + pd.Timedelta(days=1)
    a, b = wrong, wrong           # two "books" that agree with each other
    assert a.equals(b) and len(a) == spec["n_marks"]
    assert not CSPEC.validate_marks(a, spec)["ok"]


# --- inputs must be validated before any position is derived ------------------------------

def test_an_empty_calendar_is_refused_rather_than_yielding_an_empty_grid():
    """Two absences are not a match: an empty grid made validate_marks([]) report ok=True."""
    with pytest.raises(ValueError, match="calendar is empty"):
        CSPEC.expected_grid(pd.DatetimeIndex([]))


def test_a_calendar_too_short_to_produce_a_mark_is_refused():
    with pytest.raises(ValueError, match="produces NO marks"):
        CSPEC.expected_grid(_calendar(50))          # 50 bars vs a 280-bar warmup


def test_an_empty_candidate_is_never_agreement():
    cal = _calendar()
    spec = CSPEC.expected_grid(cal)
    r = CSPEC.validate_marks([], spec)
    assert r["ok"] is False and r["n_got"] == 0 and r["n_missing"] == spec["n_marks"]
    assert "empty book is not a match" in r["problems"][0]


def test_membership_shifted_but_the_same_length_is_refused_not_aligned():
    """A position only means a date if both objects sit on one index.

    An 800-day shift with the same row count was accepted and set start_bar by row number, so
    the grid began on a date unrelated to when the traded universe started.
    """
    cal = _calendar()
    shifted = _membership(cal, first=400)
    shifted.index = cal + pd.Timedelta(days=800)
    with pytest.raises(ValueError, match="different dates"):
        CSPEC.expected_grid(cal, shifted)


def test_membership_of_a_different_length_is_refused():
    cal = _calendar()
    short = _membership(cal, first=400).iloc[:-10]
    with pytest.raises(ValueError, match="not the same calendar"):
        CSPEC.expected_grid(cal, short)


def test_nonsensical_grid_parameters_are_refused():
    cal = _calendar()
    for kw in (dict(step=0), dict(warmup=-1), dict(tail_bars=-1)):
        with pytest.raises(ValueError, match="nonsensical grid parameters"):
            CSPEC.expected_grid(cal, **kw)


def test_the_tail_bound_is_read_from_the_engine_not_copied():
    """A copied 6 keeps answering 6 after the engine changes; this is parsed from the loop."""
    assert CSPEC.TAIL_BARS == 6
    assert "engine_backtest.py:" in CSPEC.TAIL_BARS_SOURCE
    assert "range(start, len(...) - N, step)" in CSPEC.TAIL_BARS_SOURCE


def test_the_spec_names_the_implementation_it_read_the_rules_from():
    """Calling a rule 'frozen' does not freeze it - recording the bytes is what identifies it."""
    spec = CSPEC.expected_grid(_calendar())
    rules = spec["rules"]
    assert len(rules["module_sha256"]["engine_backtest.py"]) == 64
    assert rules["warmup"] == EB.START and rules["step"] == EB.STEP
    assert "not evidence about the implementation a historical book was driven under" in rules["caveat"]
