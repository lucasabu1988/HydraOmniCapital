"""The invariants `accredit_433` exists to hold: preserve, never overwrite, never cross panels."""
import json
import os
import sys

import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import accredit_433 as A  # noqa: E402
import calendar_spec as CSPEC  # noqa: E402
import cost_stress as CS  # noqa: E402
import provenance as PV  # noqa: E402


# HYDRA-CI-01 (2026-09-14). Four cases here were gated on gitignored artefacts
# (`_lab_scratch/russell_prereg_cache/coverage.json`, `_lab_scratch/task433_accredited.json`) and
# therefore skipped in every CI run since they were written. What the artefacts supplied was the
# INPUT to `cost_stress.data_inputs` - which that module documents as injectable precisely so a
# test never hashes the 264 MB caches - and not the property. The four properties (panel-swap
# refusal, never-overwrite, the reconcile contract, the withdrawal contract) are now pinned on
# synthetic inputs below and run everywhere.
#
# The halves that genuinely need the lab machine - that the REAL historical books are still
# untouched and unmanifested, and that the REAL withdrawn artefact is still preserved beside its
# note - are not unit tests and are not silently dropped either: they live in
# `audits/audit_evidence_books.py`, run by `tools/external_audit.py`, which reports
# RAN - PASS / RAN - FAIL / DID NOT RUN with the exact missing path.

#: The logical names `cost_stress.data_inputs` contracts on. Recorded here so this file goes red
#: if the real contract grows or loses a name rather than silently testing a stale shape.
INPUT_NAMES = ("coverage", "etf_close", "irx", "membership", "price_close", "price_close_raw",
               "price_open", "sp500_pit_payload", "spy", "volume")


def _synthetic_inputs(root):
    """Two panels' input sets, with the real sharing pattern and tiny files.

    Faithful to `cost_stress.data_inputs`: `etf_close` and `irx` are the SAME file for both
    panels, `membership`/`coverage` belong to russell only, `sp500_pit_payload` to sp500 only,
    and the price/volume/spy files differ per panel. The sharing matters - a swap has to be
    caught on a panel-specific input, not on "everything differs".
    """
    shared = {}
    for name in ("etf_close", "irx"):
        f = os.path.join(root, f"shared_{name}.bin")
        with open(f, "wb") as fh:
            fh.write(f"shared:{name}".encode())
        shared[name] = f

    def one(panel):
        out = dict(shared)
        for name in INPUT_NAMES:
            if name in shared:
                continue
            if panel == "russell" and name == "sp500_pit_payload":
                out[name] = None
                continue
            if panel == "sp500" and name in ("membership", "coverage"):
                out[name] = None
                continue
            f = os.path.join(root, f"{panel}_{name}.bin")
            with open(f, "wb") as fh:
                fh.write(f"{panel}:{name}".encode())
            out[name] = f
        return out

    return {"russell": one("russell"), "sp500": one("sp500")}


@pytest.fixture
def synthetic_panels(tmp_path, monkeypatch):
    """`cost_stress.data_inputs` pointed at the synthetic sets, for the whole test."""
    root = str(tmp_path / "inputs")
    os.makedirs(root, exist_ok=True)
    inputs = _synthetic_inputs(root)
    monkeypatch.setattr(CS, "data_inputs", lambda panel: dict(inputs[panel]))
    return inputs


@pytest.fixture
def synthetic_grid(monkeypatch):
    """`cost_stress.derived_grid` on a synthetic trading calendar.

    PROV-08 has the anchor answer to a grid derived from the RULES, and deriving it loads the
    271 MB panel - which is why anything calling `accredit_answer` was unrunnable on a clean
    clone. The rules are what matters here, not the bytes, so `calendar_spec.expected_grid` -
    the real derivation - is applied to a synthetic business-day index instead of being faked.
    Its own coverage lives in the PROV-08 tests; this fixture only keeps the 271 MB off the path.

    `_ANCHOR_CAL_CACHE` is a module global, so it is cleared before AND after: a value cached by
    one test must not decide another one's answer.
    """
    A._ANCHOR_CAL_CACHE.clear()
    idx = pd.bdate_range("2010-01-04", periods=4000)
    monkeypatch.setattr(CS, "derived_grid",
                        lambda panel: CSPEC.expected_grid(idx, calendar_source="synthetic index"))
    yield idx
    A._ANCHOR_CAL_CACHE.clear()


def test_the_synthetic_input_contract_still_matches_the_real_one():
    """The fixture above is only evidence while it has the same shape as the thing it stands in for."""
    for panel in ("russell", "sp500"):
        assert tuple(sorted(CS.data_inputs(panel))) == INPUT_NAMES, (
            f"cost_stress.data_inputs({panel!r}) changed its logical names; the synthetic sets in "
            "this file no longer stand in for it")


def _book(n=8, start="2010-06-28"):
    idx = pd.bdate_range(start, periods=n, freq="5B")
    return pd.Series([1.0 + 0.01 * i for i in range(n)], index=idx)


def test_the_accredited_slot_never_collides_with_a_historical_book():
    """Preservation is structural, not a promise: no accredited path is any historical path."""
    historical = {os.path.normcase(os.path.abspath(p)) for p in CS.historical_books()}
    assert historical, "the historical set must be non-empty or this test proves nothing"
    for panel, label in A.ORDER:
        acc = os.path.normcase(os.path.abspath(A.acc_path(panel, label)))
        assert acc not in historical
        assert os.path.normcase(os.path.abspath(A.ACC_DIR)) != os.path.normcase(
            os.path.abspath(CS.OUT_DIR))


def test_the_write_guard_refuses_every_historical_path_wherever_acc_path_is_pointed(monkeypatch):
    """The guard sits on the WRITE, not on a path convention, so a redirected ACC_DIR cannot win.

    On 2026-09-12 a mutation run redirected `acc_path` at `cost_stress.book_path` and a fixture
    write landed on `_lab_scratch/cost_stress/russell_stress.pkl`, replacing an 814-mark book with
    an 8-mark synthetic one. A disjointness assertion did not stop it; this does.
    """
    for path in CS.historical_books():
        with pytest.raises(SystemExit, match="REFUSING TO WRITE OVER A HISTORICAL BOOK"):
            A.not_historical(path)

    monkeypatch.setattr(A, "acc_path", CS.book_path)       # the exact mutation that did the damage
    calls = []
    monkeypatch.setattr(pd, "to_pickle", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(CS, "drive", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("the engine was driven after the guard should have stopped the run")))
    # TWO layers now stop this, and the outer one fires first: since the write-isolation barrier
    # was installed in conftest, a write anywhere under _lab_scratch is refused on the RESOLVED
    # PATH before `produce` reaches its own function guard. The function guard is still proven
    # above, called directly, on every historical path. Accept either refusal; what must hold is
    # that no write happened.
    with pytest.raises(BaseException) as exc:
        A.produce("russell", "stress")
    msg, name = str(exc.value), type(exc.value).__name__
    assert ("REFUSING TO WRITE OVER A HISTORICAL BOOK" in msg
            or "WRITE ISOLATION BARRIER" in msg), f"unexpected {name}: {msg[:120]}"
    assert calls == [], "a write was attempted past the guard"


def test_the_payload_goes_to_a_new_name_and_not_over_the_published_one():
    assert os.path.abspath(A.OUT_JSON) != os.path.abspath(CS.SCRATCH)
    assert "superseded" not in os.path.basename(A.OUT_JSON)
    # This used to pin "task433_accredited.json". That artifact was WITHDRAWN on 2026-09-12 and
    # is preserved where it is, so publishing there again would overwrite retired evidence AND
    # hand readers the retired name. A new run publishes to an unambiguous new destination.
    assert os.path.basename(A.OUT_JSON) == "task433_accredited_v2.json"
    assert os.path.abspath(A.OUT_JSON) != os.path.abspath(A.WITHDRAWN_JSON)


def test_the_order_puts_the_anchor_first_and_its_grid_partner_second():
    """sp500 cannot be driven before russell:base exists - it has no grid to land on."""
    assert A.ORDER[0] == ("russell", "base")
    assert A.ORDER[1] == ("sp500", "base")
    assert len(A.ORDER) == len(CS.PANELS) * len(CS.SCENARIOS) == 8
    assert len(set(A.ORDER)) == 8


def test_russell_start_date_refuses_rather_than_guessing(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "ACC_DIR", str(tmp_path))
    with pytest.raises(SystemExit, match="must be driven first"):
        A.russell_start_date()


def test_a_book_driven_on_another_panel_is_refused_by_name_of_the_input(
        monkeypatch, tmp_path, synthetic_panels):
    """The comparison `provenance._check_data` does not make: stored block vs REQUESTED block."""
    monkeypatch.setattr(A, "ACC_DIR", str(tmp_path))
    book = _book()
    path = A.acc_path("sp500", "base")
    # a manifest whose data block is the RUSSELL panel's, beside a book in the sp500 slot
    req = dict(data=PV.data_identity(CS.data_inputs("russell")))
    PV.write_manifest(book, A.not_historical(path), req)

    A.data_answers("russell", path)                       # the panel it was actually driven on
    with pytest.raises(A.PanelMismatch) as exc:
        A.data_answers("sp500", path)
    msg = str(exc.value)
    assert "PANEL MISMATCH [data:" in msg
    assert "driven on a different panel" in msg
    # the logical name is inside the tag, so the message is a diagnosis and not a bare 'data'
    assert any(f"[data:{name}]" in msg for name in ("membership", "coverage", "price_close",
                                                    "sp500_pit_payload"))


def test_the_panel_check_agrees_when_the_book_does_answer_for_its_panel(
        monkeypatch, tmp_path, synthetic_panels):
    """The control the refusal above needs: `data_answers` must not raise unconditionally.

    Without this, a `data_answers` that raised `PanelMismatch` on EVERY call would satisfy the
    test above and prove nothing. Here the manifest and the request are the same panel, every
    logical name is compared, and it returns.
    """
    monkeypatch.setattr(A, "ACC_DIR", str(tmp_path))
    path = A.acc_path("sp500", "base")
    PV.write_manifest(_book(), A.not_historical(path),
                      dict(data=PV.data_identity(CS.data_inputs("sp500"))))
    got = A.data_answers("sp500", path)
    assert got["agrees"] is True
    assert got["inputs_compared"] == len(INPUT_NAMES), (
        "a shorter comparison would let a panel swap hide in a name that was never read")


def test_a_swap_confined_to_one_panel_specific_input_is_still_caught(
        monkeypatch, tmp_path, synthetic_panels):
    """The sharp case: the two panels share `etf_close` and `irx`, so only a panel-specific
    input can carry the diagnosis. One byte of `membership`, and the refusal names it."""
    monkeypatch.setattr(A, "ACC_DIR", str(tmp_path))
    path = A.acc_path("russell", "base")
    stored = PV.data_identity(CS.data_inputs("russell"))
    stored["membership"] = dict(stored["membership"], sha256="0" * 64)
    PV.write_manifest(_book(), A.not_historical(path), dict(data=stored))
    with pytest.raises(A.PanelMismatch, match=r"PANEL MISMATCH \[data:membership\]"):
        A.data_answers("russell", path)


def test_an_unaccreditable_file_in_the_accredited_slot_stops_the_run_and_is_left_alone(
        monkeypatch, tmp_path, synthetic_panels):
    """`produce` never overwrites: a file it cannot accredit is a refusal, not a re-drive."""
    monkeypatch.setattr(A, "ACC_DIR", str(tmp_path))
    path = A.not_historical(A.acc_path("russell", "stress"))
    assert str(tmp_path) in path, "the fixture must never be written outside tmp_path"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pd.to_pickle(_book(), path)                            # no manifest at all -> unaccredited
    before = open(path, "rb").read()

    def _must_not_drive(*a, **kw):
        raise AssertionError("produce() drove the engine over an existing file")

    monkeypatch.setattr(CS, "drive", _must_not_drive)
    with pytest.raises(SystemExit, match="never overwrites a book"):
        A.produce("russell", "stress")
    assert open(path, "rb").read() == before
    assert not os.path.exists(PV.manifest_path(path))


def _plant_historical_books(root, monkeypatch):
    """Eight synthetic books where `cost_stress` looks for the published ones.

    Redirecting `BASE_BOOKS` and `OUT_DIR` moves `historical_books()`, `book_path()` and therefore
    `accredit_433._historical_paths()` together - the whole set, with nothing left pointing at the
    real `_lab_scratch/`. Marks sit on the 5-business-day grid the real books use, so `stats_row`
    has something to annualise.
    """
    out_dir = os.path.join(root, "cost_stress")
    os.makedirs(out_dir, exist_ok=True)
    base = {p: os.path.join(root, f"engine_book_{p}.pkl") for p in CS.PANELS}
    monkeypatch.setattr(CS, "OUT_DIR", out_dir)
    monkeypatch.setattr(CS, "BASE_BOOKS", base)
    planted = []
    for i, path in enumerate(CS.historical_books()):
        pd.to_pickle(_book(n=60 + i), path)
        planted.append(path)
    assert len(planted) == 8, planted
    return planted


def test_reconcile_reports_the_historical_books_without_touching_them(
        monkeypatch, tmp_path, synthetic_panels, synthetic_grid):
    """With no accredited book at all, the historical table is still produced and nothing moves.

    HYDRA-CI-01: this used to `pytest.skip("no historical books on this machine")`, so on every
    clean clone the whole contract - eight rows, `fully_accredited` False, no manifest written
    beside a historical book, no mtime moved - was simply not checked. The books are planted here
    instead. The same assertions against the REAL eight live in `audits/audit_evidence_books.py`.
    """
    monkeypatch.setattr(A, "ACC_DIR", str(tmp_path / "acc"))
    monkeypatch.setattr(A, "OUT_JSON", str(tmp_path / "out.json"))
    planted = _plant_historical_books(str(tmp_path / "hist"), monkeypatch)
    before = {q: (os.stat(q).st_mtime_ns, open(q, "rb").read()) for q in planted}
    irx = pd.Series(0.015, index=pd.bdate_range("2010-01-04", periods=4000))

    payload = A.reconcile(irx=irx)
    assert payload["provenance"]["fully_accredited"] is False
    assert payload["provenance"]["accredited"] == []
    assert len(payload["provenance"]["still_historical_only"]) == 8
    assert payload["rows_accredited"] == []
    assert len(payload["rows_historical"]) == 8
    assert {r["provenance"] for r in payload["rows_historical"]} == {PV.HISTORICAL}
    for path, (mtime, blob) in before.items():
        assert os.stat(path).st_mtime_ns == mtime, f"reconcile touched {path}"
        assert open(path, "rb").read() == blob, f"reconcile rewrote {path}"
        assert not os.path.exists(PV.manifest_path(path)), (
            f"a historical book was given a manifest: {path}")
    with open(str(tmp_path / "out.json"), encoding="utf-8") as fh:
        assert json.load(fh)["artifact_set"] == "accredited"


def test_a_book_that_does_answer_its_own_request_accredits_with_evidence(
        monkeypatch, tmp_path, synthetic_panels, synthetic_grid):
    """The positive path, which nothing portable reached before.

    Found by mutation on 2026-09-14: emptying `compared`/`uncompared` on an ACCREDITED answer left
    all eighteen cases green, because every case here produced a rejection and the yes-branch was
    unreachable. A suite that can only ever observe "no" cannot tell a working accreditation from
    one that never says yes, which is precisely the PROV-01 failure shape in reverse.

    So: a book driven onto the DERIVED grid, sealed from the scenario's own effective request,
    must come back ACCREDITED - and must carry positive evidence, with every mandatory identity
    block actually compared rather than skipped.
    """
    acc = str(tmp_path / "acc")
    os.makedirs(acc, exist_ok=True)
    monkeypatch.setattr(A, "ACC_DIR", acc)
    marks = CS.derived_grid("russell")["marks"]
    book = pd.Series([1.0 + 0.001 * i for i in range(len(marks))], index=marks)
    path = A.not_historical(A.acc_path("russell", "base"))
    pd.to_pickle(book, path)
    PV.write_manifest(book, path, A.effective_request("russell", "base"))

    answer = A.accredit_answer("russell", "base")
    assert answer["state"] == PV.ACCREDITED, answer.get("rejected")
    compared = set(answer["accreditation"]["compared"])
    assert compared, "accredited with zero blocks compared is the PROV-01 defect"
    for block in ("code", "config", "costs", "data", "calendar", "units", "period",
                  "protocol", "result"):
        assert block in compared, (
            f"{block!r} was not compared, yet the book was called accredited; "
            f"uncompared={answer['accreditation']['uncompared_why']}")
    assert A.data_answers("russell", path)["agrees"] is True


def test_that_same_book_stops_accrediting_when_one_declared_cost_moves(
        monkeypatch, tmp_path, synthetic_panels, synthetic_grid):
    """The control for the test above: the yes must be contingent on something.

    Same book, same seal, one scenario label swapped, so the requested cost pair is 35/10 instead
    of 10/5. It must be refused - otherwise `accredited` would just mean `a manifest is present`.
    """
    acc = str(tmp_path / "acc")
    os.makedirs(acc, exist_ok=True)
    monkeypatch.setattr(A, "ACC_DIR", acc)
    marks = CS.derived_grid("russell")["marks"]
    book = pd.Series([1.0 + 0.001 * i for i in range(len(marks))], index=marks)
    path = A.not_historical(A.acc_path("russell", "stress"))
    pd.to_pickle(book, path)
    PV.write_manifest(book, path, A.effective_request("russell", "base"))   # the WRONG scenario
    answer = A.accredit_answer("russell", "stress")
    assert answer["state"] != PV.ACCREDITED
    assert answer["rejected"], "a refusal must name what disagreed"


def test_reconcile_refuses_to_call_a_sealed_but_unanswering_book_accredited(
        monkeypatch, tmp_path, synthetic_panels, synthetic_grid):
    """PROV-01's defect as a standing regression, now portable.

    A manifest that verifies its own seal but answers no part of the request used to come back
    `accredited` with zero blocks compared. Eight of those must still add up to
    `fully_accredited=False`, and every row must carry a stated rejection.
    """
    acc = str(tmp_path / "acc")
    os.makedirs(acc, exist_ok=True)
    monkeypatch.setattr(A, "ACC_DIR", acc)
    monkeypatch.setattr(A, "OUT_JSON", str(tmp_path / "out.json"))
    _plant_historical_books(str(tmp_path / "hist"), monkeypatch)
    for panel, label in A.ORDER:
        path = A.acc_path(panel, label)
        book = _book(n=40)
        pd.to_pickle(book, path)
        PV.write_manifest(book, path, dict(config=dict(fixture_only=True)))
    irx = pd.Series(0.015, index=pd.bdate_range("2010-01-04", periods=4000))

    payload = A.reconcile(irx=irx)
    assert payload["provenance"]["fully_accredited"] is False
    assert payload["provenance"]["accredited"] == []
    assert len(payload["reconciliation"]) == 8
    assert len(payload["provenance"]["rejected"]) == 8
    for rec in payload["reconciliation"]:
        assert rec["accredited_class"] != PV.ACCREDITED, rec
        assert rec["rejected"], "a rejected book must say why"


def test_the_published_431_targets_are_the_board_rows_and_are_never_inputs():
    """They are compared against, never fed in - a typo here must not move a computed number."""
    assert A.PUBLISHED_431["russell"] == dict(ann_net=5.6638, rf_ann_pct=1.5090,
                                              sharpe_excess=0.4878, maxdd_net=-16.01)
    assert A.PUBLISHED_431["sp500"] == dict(ann_net=7.9594, rf_ann_pct=1.5090,
                                            sharpe_excess=0.7238, maxdd_net=-19.67)
    src = open(os.path.join(HERE, "accredit_433.py"), encoding="utf-8").read()
    body = src.split("def reconcile", 1)[1]
    # PUBLISHED_431 may only be read into the report, never into a statistic
    allowed = ('pub = PUBLISHED_431[panel]',        # read out, for the comparison
               'rec["published_431"] = pub',        # recorded verbatim in the report
               'published_431=PUBLISHED_431,')      # carried into the payload
    for line in body.splitlines():
        if "PUBLISHED_431" in line:
            assert line.strip() in allowed, f"PUBLISHED_431 reached a computation: {line!r}"


def test_the_inference_rule_travels_with_the_measurement():
    """The back-solve must never be quoted beside the direct measurement without the caveat."""
    assert "never independent evidence" in CS.INFERENCE_RULE
    for panel in ("russell", "sp500"):
        assert "back-solved" in A.INFERRED_TURNOVER_PCT[panel]["source"]


def test_the_withdrawn_result_cannot_be_read_as_current():
    """A comment in the writer does not change what a reader loads.

    The withdrawn artifact still sits at the path consumers knew, so the refusal has to be in the
    accessor, and a new run must publish somewhere unambiguous rather than overwrite it.

    HYDRA-CI-01: this used to be gated on the withdrawn file EXISTING, which left the refusal
    untested on every clean clone - and the refusal is exactly the part that must hold whether or
    not the file is there, because it is decided by PATH, before any read. That is what is checked
    here. That the real artefact and its note are still preserved on disk is a different claim, it
    needs the lab machine, and it is in `audits/audit_evidence_books.py`.
    """
    with pytest.raises(ValueError, match="WITHDRAWN on 2026-09-12"):
        A.current_result(A.WITHDRAWN_JSON)
    assert os.path.abspath(A.OUT_JSON) != os.path.abspath(A.WITHDRAWN_JSON), \
        "a new run must not overwrite the preserved artifact"


def test_the_withdrawal_is_decided_by_path_and_not_by_what_is_on_disk(monkeypatch, tmp_path):
    """Point the constant at a file that DOES exist and holds a perfectly readable payload: the
    refusal must still fire. A withdrawal that only worked while the file was missing would be no
    withdrawal at all - and on the lab machine the file is always there, so this branch was the
    one never exercised."""
    decoy = tmp_path / "task433_accredited.json"
    decoy.write_text(json.dumps({"fully_accredited": True}), encoding="utf-8")
    monkeypatch.setattr(A, "WITHDRAWN_JSON", str(decoy))
    with pytest.raises(ValueError, match="WITHDRAWN on 2026-09-12"):
        A.current_result(str(decoy))


def test_with_no_replacement_the_current_result_is_a_refusal_not_a_fallback(monkeypatch, tmp_path):
    """TASK-433 open must read as open. An absent result is never a passing one."""
    monkeypatch.setattr(A, "OUT_JSON", str(tmp_path / "task433_accredited_v2.json"))
    with pytest.raises(FileNotFoundError, match="TASK-433 is OPEN"):
        A.current_result()


def test_a_replacement_at_the_new_path_is_what_current_result_hands_back(monkeypatch, tmp_path):
    """The other side of the contract: once a NEW run publishes, the reader gets that, by path."""
    out = tmp_path / "task433_accredited_v2.json"
    out.write_text(json.dumps({"artifact_set": "accredited", "run_id": "synthetic"}),
                   encoding="utf-8")
    monkeypatch.setattr(A, "OUT_JSON", str(out))
    assert A.current_result()["run_id"] == "synthetic"
