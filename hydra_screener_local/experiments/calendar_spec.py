"""The expected mark grid, derived from the frozen rules - never from the candidate book.

WHY THIS EXISTS. `provenance.accredit` compares a book's calendar against an ANCHOR, and the
anchor is the first book of the run, which is compared against nothing. Counting 814 marks does
not establish identity, and neither does every book agreeing with every other: eight books can
share one wrong grid and agree perfectly. The only way to check the anchor is to rebuild the grid
from the rules that produced it and compare, which is what this module does.

THE RULES, as implemented today, each with its source:

  * the input calendar        the close index of the panel the run reads
  * the first planned bar     `run_russell_prereg.start_bar` (:294-300)
                              `max(engine_backtest.START, first membership bar on this calendar)`
                              START = 280 (engine_backtest.py:38) is the warmup
                              the membership term is the first date the Russell record is non-empty
  * the stride                STEP = 5 (engine_backtest.py:39, run_russell_prereg.py:64)
  * the final bar             `range(start, len(idx) - 6, STEP)` (engine_backtest.py:187)
                              the -6 tail is the engine's own bound, NOT a protocol statement

PROTOCOL vs IMPLEMENTATION - a difference found and left standing, deliberately. The prereg fixes
the universe, the dates and the frozen engine; it does NOT state a warmup of 280 bars or a tail
cut of 6. Both are properties of `engine_backtest` that the prereg inherits by freezing that
engine. So this module derives what the IMPLEMENTATION produces and says so: it validates that a
book is on the grid the frozen engine generates, which is the contract `accredit` needs. It is
NOT independent confirmation that the grid matches an intent written down somewhere else, and
`expected_grid` records that distinction in `basis` rather than letting the caller assume it.
Changing either constant changes the answer, which is why both are read from their modules
instead of copied here.

WHAT IS STILL MISSING, named exactly rather than left as "there is no protocol": the prereg does
not record the INPUT CALENDAR's own identity - which vendor close series, at which vintage, the
run was driven on. `expected_grid` therefore takes the calendar as an argument and the caller
must say where it came from; `provenance` already hashes it as `data:price_close`. Until the
prereg pins that series, this validates the grid GIVEN the calendar, not the calendar itself.
"""
from __future__ import annotations

import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

#: Read from the modules that own them, never copied, so a change there changes this.
import engine_backtest as EB  # noqa: E402

def _tail_bars_from_source() -> tuple:
    """Read the tail cut out of `engine_backtest`'s own mark loop instead of copying the 6.

    `START` and `STEP` are module attributes, so reading them binds this module to whatever the
    engine currently says. The tail bound is not an attribute - it is a literal inside
    `range(START, len(idx) - 6, STEP)` at engine_backtest.py:187 - and a copied 6 would keep
    answering 6 after the engine changed. Parsing it keeps all three rules on the same footing.

    Returns (value, where). Raises if the expression is not found: guessing the bound would
    silently move every mark.
    """
    import ast as _ast
    src_path = os.path.join(HERE, "engine_backtest.py")
    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()
    tree = _ast.parse(src)
    for node in _ast.walk(tree):
        if not (isinstance(node, _ast.Call) and getattr(node.func, "id", None) == "range"):
            continue
        if len(node.args) != 3:
            continue
        stop = node.args[1]
        # match `len(<something>) - <int>`
        if (isinstance(stop, _ast.BinOp) and isinstance(stop.op, _ast.Sub)
                and isinstance(stop.left, _ast.Call)
                and getattr(stop.left.func, "id", None) == "len"
                and isinstance(stop.right, _ast.Constant)
                and isinstance(stop.right.value, int)):
            return stop.right.value, f"engine_backtest.py:{stop.lineno} range(start, len(...) - N, step)"
    raise RuntimeError(
        "could not find the mark loop's `range(start, len(...) - N, step)` in engine_backtest.py; "
        "the tail bound cannot be guessed, and a wrong bound moves every mark")


TAIL_BARS, TAIL_BARS_SOURCE = _tail_bars_from_source()


def rules_version() -> dict:
    """WHICH implementation these rules were read from, so a result can name it.

    START and STEP are read live and TAIL_BARS is parsed live, which makes this module track the
    CURRENT engine. The experiment was driven by whatever engine existed then. Calling a rule
    "frozen" does not freeze it; recording the bytes it came from is what lets a reader tell
    whether the rules used to validate a book are the rules that produced it.
    """
    import hashlib
    out = {}
    for name in ("engine_backtest.py", "run_russell_prereg.py"):
        path = os.path.join(HERE, name)
        try:
            with open(path, "rb") as fh:
                out[name] = hashlib.sha256(fh.read()).hexdigest()
        except OSError as exc:
            out[name] = f"unreadable: {exc}"
    return dict(module_sha256=out, warmup=int(EB.START), step=int(EB.STEP),
                tail_bars=int(TAIL_BARS), tail_bars_source=TAIL_BARS_SOURCE,
                caveat=("these are the rules as implemented NOW. They are not evidence about the "
                        "implementation a historical book was driven under; compare against that "
                        "run's own recorded module hashes to establish that."))


def _require_same_calendar(membership, idx: pd.DatetimeIndex) -> None:
    """The membership record must be indexed by the SAME calendar the grid is derived on.

    `first_membership_bar` returns a POSITION, and a position only means a date if both objects
    are on one index. A record with the right number of rows but dates shifted by 800 days was
    accepted and silently set `start_bar` by row number - the grid then started on a date that
    had nothing to do with when the traded universe began. Aligning or reindexing here would
    manufacture the agreement being tested, so this refuses instead.
    """
    m_idx = pd.DatetimeIndex(getattr(membership, "index", []))
    if m_idx.equals(idx):
        return
    if len(m_idx) != len(idx):
        raise ValueError(
            f"membership is indexed by {len(m_idx)} date(s), the calendar by {len(idx)}: it is "
            "not the same calendar, and a row position would not mean the date it appears to.")
    first_diff = next((i for i, (a, b) in enumerate(zip(m_idx, idx)) if a != b), None)
    raise ValueError(
        f"membership has the same number of rows as the calendar but different dates (row "
        f"{first_diff}: {m_idx[first_diff].date()} vs {idx[first_diff].date()}). Positions would "
        "resolve to the wrong dates. Supply the membership on this calendar, or an explicit, "
        "documented and verified transformation - this will not align it silently.")


def first_membership_bar(membership: pd.DataFrame) -> int:
    """The first bar on this calendar where the traded-universe record is non-empty.

    `run_russell_prereg.start_bar` (:296-299) computes exactly this and raises when the record is
    empty; an empty record here is the same error, because a grid cannot be derived without it.
    """
    has = membership.any(axis=1)
    if not bool(has.any()):
        raise ValueError("membership is empty on this calendar: no first bar to start from")
    return int(has.to_numpy().argmax())


def expected_grid(calendar, membership=None, *, warmup: int = None, step: int = None,
                  tail_bars: int = TAIL_BARS, calendar_source: str = None) -> dict:
    """Rebuild the mark grid from the rules. `calendar` is the INPUT close index, not a book.

    Deliberately takes no book and no book index: reading the candidate's own marks to decide
    what the candidate's marks should be is the circularity this module exists to break.
    """
    idx = pd.DatetimeIndex(calendar)
    if len(idx) == 0:
        raise ValueError(
            "the input calendar is empty: no grid can be derived from it. An empty grid would "
            "make `validate_marks` accept an empty candidate as agreement - two absences are not "
            "a match.")
    if not idx.is_monotonic_increasing:
        raise ValueError("the input calendar is not sorted; a grid derived from it is meaningless")
    if idx.has_duplicates:
        raise ValueError("the input calendar has duplicate dates; it is not a trading calendar")
    warmup = int(EB.START if warmup is None else warmup)
    step = int(EB.STEP if step is None else step)
    tail_bars = int(tail_bars)
    if warmup < 0 or step < 1 or tail_bars < 0:
        raise ValueError(f"nonsensical grid parameters: warmup={warmup}, step={step}, "
                         f"tail_bars={tail_bars}")
    start = warmup
    if membership is not None:
        _require_same_calendar(membership, idx)
        start = max(warmup, first_membership_bar(membership))
    if len(idx) - tail_bars <= start:
        raise ValueError(
            f"the calendar holds {len(idx)} bar(s); with warmup/first-membership {start} and a "
            f"{tail_bars}-bar tail cut it produces NO marks. A zero-length grid cannot validate "
            "anything.")
    positions = list(range(start, len(idx) - tail_bars, step))
    return dict(
        marks=idx[positions],
        n_marks=len(positions),
        start_bar=start,
        warmup=warmup,
        step=step,
        tail_bars=int(tail_bars),
        calendar_source=calendar_source,
        rules=rules_version(),
        basis=("derived from the frozen implementation: engine_backtest.START warmup, "
               "engine_backtest.STEP stride, the range(start, len-%d, step) bound at "
               "engine_backtest.py:187, and run_russell_prereg.start_bar's membership term. "
               "NOT independent confirmation against a separately written protocol - the prereg "
               "fixes the engine, and these constants are properties of that engine."
               % int(tail_bars)),
        calendar_identity=("NOT ESTABLISHED by this module: the prereg does not pin which vendor "
                           "close series at which vintage the run used. This validates the grid "
                           "GIVEN the calendar supplied by the caller."),
    )


def validate_marks(book_marks, spec: dict) -> dict:
    """Compare a candidate's marks against a derived grid. Reports WHICH way it differs.

    Truncation, a shift, omissions in the middle and duplicates are four different faults and a
    bare count catches none of them: a truncated book and a shifted book can have the same length,
    and a book with one date dropped and one duplicated has the right length too.
    """
    want = pd.DatetimeIndex(spec["marks"])
    got = pd.DatetimeIndex(book_marks)
    if len(want) == 0:
        raise ValueError("the expected grid is empty; it cannot validate anything")
    problems = []
    if len(got) == 0:
        return dict(ok=False, n_expected=len(want), n_got=0, n_missing=len(want), n_extra=0,
                    problems=["the candidate has no marks at all: an empty book is not a match "
                              "for a %d-mark grid" % len(want)],
                    checked="candidate rejected before comparison: it is empty")
    if got.has_duplicates:
        dupes = got[got.duplicated()].unique()
        problems.append("duplicated marks: %s%s"
                        % (", ".join(str(d.date()) for d in dupes[:3]),
                           " ..." if len(dupes) > 3 else ""))
    if not got.is_monotonic_increasing:
        problems.append("marks are not in ascending order")
    missing = want.difference(got)
    extra = got.difference(want)
    if len(got) == len(want) and len(missing) and len(extra):
        problems.append("same length, different dates: %d expected mark(s) absent, first %s; "
                        "%d unexpected, first %s - a shift, not a truncation"
                        % (len(missing), missing[0].date(), len(extra), extra[0].date()))
    else:
        if len(missing):
            where = ("truncated at the end" if len(got) and want[len(got) - 1:].equals(missing[:0])
                     else "absent")
            problems.append("%d expected mark(s) %s, first %s, last %s"
                            % (len(missing), where, missing[0].date(), missing[-1].date()))
        if len(extra):
            problems.append("%d mark(s) the grid does not contain, first %s"
                            % (len(extra), extra[0].date()))
    return dict(
        ok=not problems,
        n_expected=len(want), n_got=len(got),
        n_missing=len(missing), n_extra=len(extra),
        problems=problems,
        checked=("marks compared date by date against a grid derived from the rules, not against "
                 "another book and not by counting"),
    )
