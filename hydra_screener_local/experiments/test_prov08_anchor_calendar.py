"""PROV-08: the anchor book answers to a grid derived from the rules, not to another book.

PROV-01 wired the consumers to `provenance.accredit`, and that exposed this: the anchor's
request carried `calendar=None`, which `cost_stress.request` deliberately refuses to turn
into a `calendar_anchor` declaration, because the grid IS derivable without any book. So
`russell/base` could not be accredited from cache at all, and `fully_accredited` could never
be true for the set - a correct refusal standing in for a missing fix.

The missing half already existed. `cost_stress.derived_grid` calls
`calendar_spec.expected_grid`, which rebuilds the grid from the identified inputs and the
engine's constants, takes no book and no book index, and refuses an empty or too-short
calendar. This file pins the wiring: the anchor now matches a grid that nothing about the
anchor produced, a SHIFTED grid is refused, and an underivable grid refuses rather than
quietly skipping the window.

Synthetic throughout. `derived_grid` is injected, so no panel, no membership record and no
264 MB cache is read; the file runs identically on a clean clone.
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import accredit_433 as A  # noqa: E402
import cost_stress as CS  # noqa: E402
import provenance as PV  # noqa: E402

MARKS = pd.bdate_range("2010-06-28", periods=8, freq="5B")


def _book(marks=MARKS):
    return pd.Series([1.0 + 0.01 * i for i in range(len(marks))], index=marks)


def _grid(marks=MARKS):
    return dict(marks=pd.DatetimeIndex(marks), n_marks=len(marks), start_bar=0,
                warmup=0, step=5, tail_bars=0, rules={"v": 1},
                calendar_source="synthetic grid for this test")


@pytest.fixture
def lab(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "ACC_DIR", str(tmp_path / "accredited"))
    os.makedirs(A.ACC_DIR, exist_ok=True)
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    names = ("price_close", "price_close_raw", "price_open", "volume", "spy",
             "membership", "coverage", "sp500_pit_payload", "etf_close", "irx")

    def fake_inputs(panel):
        out = {}
        for n in names:
            f = inputs / f"{panel}_{n}.bin"
            if not f.exists():
                f.write_bytes(f"{panel}:{n}".encode())
            out[n] = str(f)
        out["sp500_pit_payload" if panel == "russell" else "membership"] = None
        return out

    monkeypatch.setattr(CS, "data_inputs", fake_inputs)
    A._ANCHOR_CAL_CACHE.clear()          # the memo must not leak between cases
    return tmp_path


def _plant(panel, label, book, request):
    path = A.acc_path(panel, label)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pd.to_pickle(book, path)
    PV.write_manifest(book, path, request)
    return path


# ------------------------------------------------------------------ the anchor is checked

def test_the_anchors_request_carries_a_calendar_derived_from_the_rules(lab, monkeypatch):
    monkeypatch.setattr(CS, "derived_grid", lambda panel: _grid())
    req = A.effective_request("russell", "base")
    assert "calendar" in req, "the anchor's request still declares no window"
    assert req["calendar"]["sha256"] == PV.calendar_block(_book())["sha256"]
    assert req["calendar"]["n_marks"] == 8


def test_the_derived_calendar_does_not_come_from_the_book_being_judged(lab, monkeypatch):
    """The circularity this closes: the grid must not be read off the candidate.

    A book is planted with DIFFERENT marks from the derived grid, and the request still
    carries the derived ones - so the calendar demonstrably did not come from the candidate.
    """
    seen = []
    monkeypatch.setattr(CS, "derived_grid", lambda panel: (seen.append(panel), _grid())[1])
    other = pd.bdate_range("2015-01-05", periods=20, freq="5B")
    _plant("russell", "base", _book(other),
           CS.request("russell", "base", *A.scenario_bp("base"),
                      calendar=PV.calendar_block(_book(other))))

    req = A.effective_request("russell", "base")
    assert seen == ["russell"], "the calendar was not obtained from calendar_spec"
    assert req["calendar"]["sha256"] == PV.calendar_block(_book())["sha256"]
    assert req["calendar"]["sha256"] != PV.calendar_block(_book(other))["sha256"], (
        "the request took its window from the very book it is meant to judge")


def test_the_derived_grid_is_resolved_once_per_process(lab, monkeypatch):
    """Deriving loads the panel, and `reconcile` asks eight times."""
    calls = []
    monkeypatch.setattr(CS, "derived_grid", lambda panel: (calls.append(panel), _grid())[1])
    for _ in range(5):
        A.effective_request("russell", "base")
    assert calls == ["russell"], f"the panel was loaded {len(calls)} times"


def test_an_anchor_on_the_derived_grid_is_accredited(lab, monkeypatch):
    """The positive case: before PROV-08 this was CACHE REJECTED [calendar]."""
    monkeypatch.setattr(CS, "derived_grid", lambda panel: _grid())
    _plant("russell", "base", _book(), A.effective_request("russell", "base"))
    answer = A.accredit_answer("russell", "base")
    assert answer["state"] == PV.ACCREDITED, answer.get("rejected")
    assert "calendar" in answer["accreditation"]["compared"], (
        "the anchor's window must now be a COMPARED identity, not a degraded one")


def test_an_anchor_on_a_SHIFTED_grid_is_refused(lab, monkeypatch):
    """The falsifiable half. Same length, same step, different window."""
    monkeypatch.setattr(CS, "derived_grid", lambda panel: _grid())
    shifted = pd.bdate_range("2011-06-28", periods=8, freq="5B")
    _plant("russell", "base", _book(shifted),
           CS.request("russell", "base", *A.scenario_bp("base"),
                      calendar=PV.calendar_block(_book(shifted))))
    answer = A.accredit_answer("russell", "base")
    assert answer["state"] == "rejected", "a book on the wrong window was accredited"
    assert answer["rejected"]["field"] in ("calendar", "artifact"), answer["rejected"]


def test_an_anchor_with_MORE_marks_than_the_grid_is_refused(lab, monkeypatch):
    monkeypatch.setattr(CS, "derived_grid", lambda panel: _grid())
    longer = pd.bdate_range("2010-06-28", periods=12, freq="5B")
    _plant("russell", "base", _book(longer),
           CS.request("russell", "base", *A.scenario_bp("base"),
                      calendar=PV.calendar_block(_book(longer))))
    assert A.accredit_answer("russell", "base")["state"] == "rejected"


# --------------------------------------------------- an underivable grid refuses, loudly

def test_an_underivable_grid_yields_no_calendar_and_says_so(lab, monkeypatch, capsys):
    """A clean clone cannot derive it. That must refuse, not skip the window in silence."""
    def boom(panel):
        raise FileNotFoundError("close.pkl is not on this machine")

    monkeypatch.setattr(CS, "derived_grid", boom)
    assert A.derived_anchor_calendar("russell") is None
    assert "cannot derive the anchor grid" in capsys.readouterr().out


def test_an_empty_grid_is_not_treated_as_a_calendar(lab, monkeypatch):
    monkeypatch.setattr(CS, "derived_grid",
                        lambda panel: dict(marks=pd.DatetimeIndex([]), n_marks=0))
    assert A.derived_anchor_calendar("russell") is None


def test_with_no_derivable_grid_the_anchor_is_refused_rather_than_degraded(lab, monkeypatch):
    monkeypatch.setattr(CS, "derived_grid", lambda panel: None)
    _plant("russell", "base", _book(),
           CS.request("russell", "base", *A.scenario_bp("base"), calendar=None))
    answer = A.accredit_answer("russell", "base")
    assert answer["state"] == "rejected"
    assert answer["rejected"]["field"] == "calendar"


# ------------------------------------------------------------------ the rest of the set

def test_a_non_anchor_book_still_uses_the_anchors_calendar(lab, monkeypatch):
    """Only the anchor changes. Everything else is measured against the anchor, as before."""
    calls = []
    monkeypatch.setattr(A, "anchor_calendar",
                        lambda: (calls.append(1), PV.calendar_block(_book()))[1])
    monkeypatch.setattr(CS, "derived_grid", lambda panel: _grid())
    req = A.effective_request("russell", "stress")
    assert calls == [1], "a non-anchor scenario stopped asking the anchor"
    assert req["calendar"]["sha256"] == PV.calendar_block(_book())["sha256"]


def test_calendar_block_from_marks_and_from_a_book_agree(lab):
    """One identity, two ways in - a grid is an index, a book is a Series."""
    assert (PV.calendar_block_from_marks(MARKS)
            == PV.calendar_block(_book()))


def test_the_derived_grid_helper_is_the_one_that_takes_no_book():
    """Guard the property that makes this non-circular, in calendar_spec's own words."""
    src = open(os.path.join(HERE, "calendar_spec.py"), encoding="utf-8").read()
    flat = " ".join(src.split())
    assert "takes no book and no book index" in flat, (
        "expected_grid must keep refusing to read the candidate's own marks")


def test_nothing_here_read_a_real_lab_artifact(lab, monkeypatch):
    """The file's own claim, asserted: injected inputs, injected grid, tmp_path only."""
    monkeypatch.setattr(CS, "derived_grid", lambda panel: _grid())
    req = A.effective_request("russell", "base")
    blob = json.dumps(req, default=str)
    for forbidden in ("_sweep_cache_oos", "_lab_scratch", "TRADING_CACHE"):
        assert forbidden not in blob, f"the request reached a real lab path: {forbidden}"
