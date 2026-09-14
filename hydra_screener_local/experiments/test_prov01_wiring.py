"""HYDRA-PROV-01: a seal is not an accreditation, and the consumers must ask the validator.

The defect, reproduced on 27afcf8 with nothing but synthetic data: eight books whose
manifests held `{fixture_only: true, self_sha256: ...}` and nothing else were all reported
`accredited`, the aggregate said `fully_accredited: true`, and `provenance.accredit` was
never called once. No identity block was ever compared. No private book and no engine run
were needed to produce that.

That is not the unkeyed-hash limit. `classify()` answers "is a manifest there and does its
own seal verify" - a question about the FILE. `accredit()` answers "does this book answer
the request being made" - a question about the SCENARIO. The consumers asked the first and
reported the second.

Everything below is synthetic: books of eight marks under tmp_path, no lab artefact, no
engine. Three of these tests fail on the pre-PROV-01 code; the rest pin the contract that
replaces it.
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


def _irx_series(n=8, start="2010-06-28"):
    """A synthetic annualised DECIMAL risk-free; never the lab's irx.pkl."""
    return pd.Series([0.05] * n, index=pd.bdate_range(start, periods=n, freq="5B"))


def _book(n=8, start="2010-06-28"):
    idx = pd.bdate_range(start, periods=n, freq="5B")
    return pd.Series([1.0 + 0.01 * i for i in range(n)], index=idx)


@pytest.fixture
def slot(monkeypatch, tmp_path):
    """An accredited directory of our own, over synthetic data inputs.

    `cost_stress.data_inputs` is injectable by design ("so a test never hashes the 264 MB
    caches"), which is also what keeps this file portable: it needs no `_sweep_cache_oos/`,
    no panel and no lab artefact, so it runs identically on a clean clone and in CI.
    """
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
        # Keep the panel-distinguishing shape: a file this panel does not read is None,
        # never absent, so a swap cannot look like a shorter manifest.
        out["sp500_pit_payload" if panel == "russell" else "membership"] = None
        return out

    monkeypatch.setattr(CS, "data_inputs", fake_inputs)
    # reconcile() writes its payload; send it to tmp_path, never to _lab_scratch.
    monkeypatch.setattr(A, "OUT_JSON", str(tmp_path / "task433_accredited_v2.json"))
    monkeypatch.setattr(A, "WITHDRAWN_JSON", str(tmp_path / "withdrawn.json"))
    return tmp_path


def _absent_historicals():
    """Historical books that are not on this machine - the clean-clone condition."""
    return {p: os.path.join("nonexistent", f"{p}_base.pkl")
            for p in {pan for pan, _ in A.ORDER}}


def _no_historicals(monkeypatch, tmp_path):
    """Neither the base books NOR the per-scenario ones.

    `BASE_BOOKS` covers only `label == "base"`; every other scenario resolves through
    `cost_stress.book_path`, which on the lab machine finds the REAL 813-mark books. Patching
    one and not the other made this file pass on a clean clone and fail here - the exact
    machine-dependence these tickets exist to remove.
    """
    monkeypatch.setattr(CS, "BASE_BOOKS", _absent_historicals())
    monkeypatch.setattr(CS, "book_path",
                        lambda panel, label: str(tmp_path / "nonexistent"
                                                 / f"{panel}_{label}.pkl"))


def _plant_minimal_manifest(panel, label, extra=None):
    """The decoy: a book, and a manifest that carries only a valid seal over nothing."""
    path = A.acc_path(panel, label)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pd.to_pickle(_book(), path)
    body = dict(fixture_only=True)
    body.update(extra or {})
    with open(PV.manifest_path(path), "w", encoding="utf-8") as fh:
        json.dump(PV.seal(body), fh)
    return path


# ------------------------------------------------------------------- the reproduction

def test_the_eight_minimal_manifests_no_longer_read_as_accredited(slot):
    """The headline. Before PROV-01 this produced eight accredited rows."""
    for panel, label in A.ORDER:
        _plant_minimal_manifest(panel, label)

    # The seal itself is genuinely valid - that is the whole point of the decoy.
    first = A.acc_path(*A.ORDER[0])
    assert PV.seal_ok(PV.read_manifest(first))[0], "precondition: the seal verifies"
    assert PV.classify(first) == PV.ACCREDITED, "precondition: classify() still says accredited"

    states = {A.accredit_answer(p, lab)["state"] for p, lab in A.ORDER}
    assert states == {"rejected"}, f"a manifest with no identity was accepted: {states}"


def test_a_minimal_manifest_is_rejected_by_NAME_of_what_is_missing(slot):
    _plant_minimal_manifest("russell", "base")
    answer = A.accredit_answer("russell", "base")
    assert answer["state"] == "rejected"
    rej = answer["rejected"]
    assert rej["field"], "the rejection must name the field that failed"
    assert rej["message"], "the rejection must carry a diagnosis"
    # The seal was fine; that is exactly the distinction being drawn.
    assert answer["seal_class"] == PV.ACCREDITED


def test_the_aggregate_cannot_say_fully_accredited_over_rejected_books(slot, monkeypatch, tmp_path):
    for panel, label in A.ORDER:
        _plant_minimal_manifest(panel, label)
    _no_historicals(monkeypatch, tmp_path)
    payload = A.reconcile(irx=_irx_series())
    prov = payload["provenance"]
    assert prov["fully_accredited"] is False
    assert len(prov["still_historical_only"]) == len(A.ORDER)
    assert prov["accredited"] == []
    assert prov["rejected"], "the aggregate must carry WHY each book was refused"
    assert payload["rows_accredited"] == [], "no row may be published as accredited"


def test_no_row_is_stamped_accredited_without_a_validation(slot, monkeypatch, tmp_path):
    """A metrics row may only claim provenance it can show."""
    for panel, label in A.ORDER:
        _plant_minimal_manifest(panel, label)
    _no_historicals(monkeypatch, tmp_path)
    payload = A.reconcile(irx=_irx_series())
    for row in payload["rows_accredited"]:
        assert row.get("compared"), f"row claims accreditation with nothing compared: {row}"


# --------------------------------------------------------- the positive case, synthetic

def _plant_accredited(panel, label, book=None):
    """A book AND a request that genuinely answers for it, both synthetic.

    The calendar is taken from the book itself, which is what a non-anchor scenario gets from
    `anchor_calendar()` in a real run. That keeps this portable: no panel, no lab cache.
    """
    book = _book() if book is None else book
    path = A.acc_path(panel, label)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pd.to_pickle(book, path)
    s_bp, e_bp = A.scenario_bp(label)
    req = CS.request(panel, label, s_bp, e_bp, calendar=PV.calendar_block(book))
    PV.write_manifest(book, path, req)
    return path, req


def test_a_properly_requested_book_IS_accredited_and_shows_its_evidence(slot, monkeypatch):
    """The positive control. Not "a function was called": a real comparison that passes."""
    book = _book()
    _plant_accredited("russell", "stress", book)
    monkeypatch.setattr(A, "anchor_calendar", lambda: PV.calendar_block(book))

    answer = A.accredit_answer("russell", "stress")
    assert answer["state"] == PV.ACCREDITED, answer.get("rejected")
    acc = answer["accreditation"]
    assert acc["compared"], "an accredited book must name what was compared"
    for block in ("code", "costs", "config", "protocol", "data", "calendar", "units", "period"):
        assert block in acc["compared"], f"{block} not compared; got {acc['compared']}"
    assert answer["book"] is not None
    assert list(answer["book"].index) == list(book.index)


def test_the_same_book_asked_a_DIFFERENT_scenarios_question_is_refused(slot, monkeypatch):
    """Compatibility with a request, not integrity of a file: the cost pair differs."""
    book = _book()
    src, _ = _plant_accredited("russell", "stress", book)
    monkeypatch.setattr(A, "anchor_calendar", lambda: PV.calendar_block(book))
    dst = A.acc_path("russell", "smallcap_crisis")
    import shutil
    shutil.copy(src, dst)
    shutil.copy(PV.manifest_path(src), PV.manifest_path(dst))

    answer = A.accredit_answer("russell", "smallcap_crisis")
    assert answer["state"] == "rejected", "the stress book answered the crisis question"
    # Refused on `artifact` - the manifest records which slot the book was driven for,
    # so the substitution is caught before the cost comparison is even reached. Either
    # field is a real, named diagnosis; what must never happen is acceptance.
    assert answer["rejected"]["field"] in ("artifact", "costs"), answer["rejected"]
    assert answer["rejected"]["message"].strip(), "a refusal must carry a diagnosis"


def test_a_book_on_another_PANEL_is_refused_by_the_name_of_the_input(slot, monkeypatch):
    """The substitution `accredit` alone does not catch; `data_answers` is the second check."""
    book = _book()
    src, _ = _plant_accredited("russell", "stress", book)
    monkeypatch.setattr(A, "anchor_calendar", lambda: PV.calendar_block(book))
    dst = A.acc_path("sp500", "stress")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    import shutil
    shutil.copy(src, dst)
    shutil.copy(PV.manifest_path(src), PV.manifest_path(dst))

    answer = A.accredit_answer("sp500", "stress")
    assert answer["state"] == "rejected", "a russell-driven book answered the sp500 question"


def test_the_anchor_book_is_refused_rather_than_accredited_with_nothing_compared(slot):
    """PROV-08, pinned rather than papered over.

    `cost_stress.request(calendar=None)` deliberately no longer declares `calendar_anchor`:
    the grid is derivable from the rules (`calendar_spec`), so "there is no earlier book" was
    never a reason to skip the window check. The consequence is that `russell/base` cannot be
    accredited FROM CACHE at all until its request carries a derived calendar.

    Before PROV-01 that same book was reported `accredited` with nothing compared. Refusing it
    is the correct failure, and it is why `fully_accredited` stays False for the set until
    PROV-08 is closed - which is a separate ticket and is NOT closed here.
    """
    book = _book()
    path = A.acc_path("russell", "base")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pd.to_pickle(book, path)
    req = CS.request("russell", "base", *A.scenario_bp("base"), calendar=None)
    PV.write_manifest(book, path, req)

    answer = A.accredit_answer("russell", "base")
    assert answer["state"] == "rejected"
    assert answer["rejected"]["field"] == "calendar"
    assert answer["seal_class"] == PV.ACCREDITED, "the seal is fine; the REQUEST is incomplete"


def test_an_absent_book_is_absent_not_rejected(slot):
    assert A.accredit_answer("russell", "smallcap_crisis")["state"] == "absent"


# ------------------------------------------------------------- the contract, in the open

def test_the_effective_request_is_built_from_the_scenario_not_from_the_manifest(slot):
    """Copying the stored manifest into the request would compare the artifact with itself."""
    _plant_minimal_manifest("russell", "stress")
    req = A.effective_request("russell", "stress")
    s_bp, e_bp = A.scenario_bp("stress")
    assert req["costs"]["stock_bp_per_side"] == s_bp
    assert req["costs"]["etf_bp_per_side"] == e_bp
    assert "fixture_only" not in json.dumps(req), "the request quoted the file it must judge"


def test_an_uncompared_block_with_an_unnamed_reason_is_not_fully_accredited(slot, monkeypatch):
    """A permitted exception has a written reason; anything else cannot pass for a comparison."""
    assert A._permitted_uncompared("universe", PV.DERIVED_BLOCKS["universe"]) is True
    assert A._permitted_uncompared("calendar", "declared anchor (russell/base): ...") is True
    assert A._permitted_uncompared("costs", "nothing requested") is False
    assert A._permitted_uncompared("data", "") is False


def test_the_anchor_calendar_refuses_an_unvalidated_book(slot):
    """The anchor defines the grid every other book is compared to."""
    _plant_minimal_manifest("russell", "base")
    assert A.anchor_calendar() is None, (
        "a seal-only check let an unvalidated book define the mark grid")


def test_the_stale_validator_note_no_longer_claims_an_open_gap(slot, monkeypatch, tmp_path):
    for panel, label in A.ORDER:
        _plant_minimal_manifest(panel, label)
    _no_historicals(monkeypatch, tmp_path)
    note = A.reconcile(irx=_irx_series())["known_validator_gap"]
    assert "CLOSED" in note, "the note still describes _check_data as if it did not compare"
    assert "self_sha256" in note, "the limit that IS open must stay named"
    assert "independence" in note.lower(), (
        "integrity, compatibility and independence must stay distinguished")


def test_historical_artifacts_are_not_re_sealed_to_look_current(slot, monkeypatch):
    """Nothing here may fabricate a contemporary manifest for a preserved result."""
    hist = os.path.join(str(slot), "historical_book.pkl")
    pd.to_pickle(_book(), hist)
    before = os.path.getmtime(hist)
    _no_historicals(monkeypatch, slot)
    books = _absent_historicals(); books["russell"] = hist
    monkeypatch.setattr(CS, "BASE_BOOKS", books)
    for panel, label in A.ORDER:
        _plant_minimal_manifest(panel, label)
    A.reconcile(irx=_irx_series())
    assert not os.path.exists(PV.manifest_path(hist)), (
        "a manifest was fabricated beside a historical book")
    assert os.path.getmtime(hist) == before, "the historical book was rewritten"
