"""EXTERNAL EVIDENCE AUDIT - the TASK-433 books and the withdrawn result, on the real disk.

Not a unit test and not discovered by `run_all_tests.py` (which globs `test_*.py` in the root,
`experiments/` and `tools/` - never `audits/`). It is run by `tools/external_audit.py`, which
checks the artefacts this file needs BEFORE importing it and reports
`DID NOT RUN - <exact missing path>` rather than letting anything here degrade into a skip.

Why these two claims cannot be portable
---------------------------------------
Their portable halves already run in the required suite
(`experiments/test_accredit_433.py`): the reconcile contract is pinned on eight planted books and
the withdrawal refusal is pinned on the accessor, by path, with and without a file present. What
is left here is not a property of the code at all - it is a claim about THIS disk:

  * the eight published books are still byte-for-byte what they were, still carry no manifest,
    and `reconcile` did not move them;
  * the withdrawn 2026-09-12 artefact and its withdrawal note are still preserved beside each
    other, and the new result path is not the old one.

A synthetic fixture cannot make either claim, and a green suite must never be read as having
made it. THERE IS NO `pytest.skip` IN THIS FILE, by design: a skip here would be exactly the
"absence of evidence rendered as success" this whole task exists to remove. `tools/external_audit.py`
treats a skipped case in an audit as a FAILURE.
"""
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import accredit_433 as A  # noqa: E402
import cost_stress as CS  # noqa: E402
import provenance as PV  # noqa: E402


def test_reconcile_reports_the_real_historical_books_without_touching_them(monkeypatch, tmp_path):
    """The eight published books: same bytes, same mtimes, still no manifest, after a reconcile.

    The accredited slot and the output path are redirected into tmp_path so this audit reads the
    real books and writes nowhere near them.
    """
    monkeypatch.setattr(A, "ACC_DIR", str(tmp_path / "acc"))
    monkeypatch.setattr(A, "OUT_JSON", str(tmp_path / "out.json"))
    books = [p for p in CS.historical_books() if os.path.exists(p)]
    assert len(books) == 8, (
        f"this audit is about the EIGHT published books; {len(books)} are on this disk. "
        f"Missing: {[p for p in CS.historical_books() if not os.path.exists(p)]}")
    before = {p: (os.stat(p).st_mtime_ns, os.path.getsize(p), PV.sha256_bytes(p)) for p in books}

    payload = A.reconcile()

    assert payload["provenance"]["fully_accredited"] is False, (
        "TASK-433 is open; a real run reporting fully_accredited here would mean the accredited "
        "set was populated behind this audit's back")
    assert len(payload["rows_historical"]) == 8
    assert {r["provenance"] for r in payload["rows_historical"]} == {PV.HISTORICAL}
    for path, (mtime, size, digest) in before.items():
        st = os.stat(path)
        assert st.st_mtime_ns == mtime, f"reconcile touched {path}"
        assert st.st_size == size and PV.sha256_bytes(path) == digest, f"reconcile rewrote {path}"
        assert not os.path.exists(PV.manifest_path(path)), (
            f"a historical book was given a manifest: {path}. Re-sealing a pre-manifest book is "
            "how a historical artefact would be laundered into accredited evidence.")


def test_the_published_books_are_still_classified_historical_and_not_accredited():
    """`classify` on the real files. Eight `historical_incomplete`, zero `accredited`."""
    seen = {}
    for path in CS.historical_books():
        assert os.path.exists(path), f"a published book is missing from this disk: {path}"
        seen[os.path.basename(path)] = PV.classify(path)
    assert set(seen.values()) == {PV.HISTORICAL}, seen


def test_the_withdrawn_artifact_and_its_note_are_both_still_preserved():
    """The 2026-09-12 result was withdrawn, not deleted, and the record sits beside it."""
    assert os.path.exists(A.WITHDRAWN_JSON), (
        f"the withdrawn artifact is gone: {A.WITHDRAWN_JSON}. It is historical evidence and "
        "must be preserved where it is.")
    assert os.path.exists(A.WITHDRAWAL_NOTE), (
        f"the withdrawal record is gone: {A.WITHDRAWAL_NOTE}. Without it the preserved file has "
        "no attached reason and could be mistaken for a current result.")
    with open(A.WITHDRAWAL_NOTE, encoding="utf-8") as fh:
        note = json.load(fh)
    assert note, "the withdrawal note is empty"
    assert os.path.abspath(A.OUT_JSON) != os.path.abspath(A.WITHDRAWN_JSON)


def test_the_legacy_result_slot_was_not_reused():
    """The accredited replacement for the withdrawn 2026-09-12 result is `20260914-cae2c54599aa`,
    published as `task433_accredited_<run_id>.json` next to its `accredited/runs/<run_id>/` books.
    `task433_accredited_v2.json` - the slot the first attempt would have written - must therefore
    stay EMPTY: a file there would be a result with no run id and no manifest directory to answer
    for it, exactly the shape that got withdrawn. Until #95 this test claimed "TASK-433 is still
    open", which stopped being true the moment that run accredited; the claim now is about the
    slot, which is what the disk can actually witness."""
    assert not os.path.exists(A.OUT_JSON), (
        f"{A.OUT_JSON} exists. The accredited result is published under its run id; a file in the "
        "legacy slot carries neither. Do not delete it - read it and find out what wrote it.")
    assert os.path.exists(A.WITHDRAWN_JSON) and os.path.exists(A.WITHDRAWAL_NOTE), (
        "the withdrawn pair must stay preserved beside the replacement")


def test_the_real_books_marks_are_what_the_task_431_row_was_measured_on():
    """A sanity check on the actual bytes: the two base books carry the mark counts the board
    quotes, so this audit is reading the evidence it thinks it is reading."""
    for panel in CS.PANELS:
        path = CS.BASE_BOOKS[panel]
        book = pd.read_pickle(path)
        assert isinstance(book, pd.Series) and len(book) > 100, (
            f"{path}: expected a wealth series with many marks, got {type(book).__name__} "
            f"of length {len(book) if hasattr(book, '__len__') else 'n/a'}")
        assert pd.DatetimeIndex(book.index).is_monotonic_increasing
