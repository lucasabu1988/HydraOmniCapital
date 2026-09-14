"""TASK-433: twelve deliberate falsifications, and one positive case that must still accredit.

A suite that only proves rejections proves nothing about the path that matters. So the first
test here builds a book that DOES accredit - on the derived grid, sealed from the scenario's own
effective request, with every mandatory identity block compared - and every mutation below is a
single change away from that same book. If the positive case ever stops accrediting, the
rejections stop meaning anything and this file says so before they are quoted as evidence.

Portable by construction (HYDRA-CI-01): `cost_stress.data_inputs` is pointed at tiny synthetic
files and `cost_stress.derived_grid` at `calendar_spec.expected_grid` over a synthetic business-day
index, so nothing here reads the 264 MB caches, the lab books or any live state. The SAME twelve
mutations are run against the REAL accredited run by `audits/audit_task433_run.py`, where they are
evidence about the actual books rather than about the contract.

The twelve, as TASK-433 names them:

    1  scenario label            7  config identity
    2  cost pair                 8  a historical artifact substituted for a new run
    3  panel identity            9  an artifact modified and re-sealed
    4  calendar                 10  a missing identity block
    5  period                   11  a shifted calendar of EQUAL LENGTH
    6  data identity            12  metrics correct, provenance wrong

Mutation 9 is the one that documents a limit rather than a guarantee: `self_sha256` is an unkeyed
digest produced by the same public `seal()` a writer calls, so re-sealing restores it and the seal
check passes. The rejection comes from the REQUEST comparison, not from the seal. That is exactly
the distinction to keep: integrity of the artifact and compatibility with a request are two
different claims, and neither is independence from the author.
"""
from __future__ import annotations

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

#: Every identity block TASK-433 requires a verdict on.
MANDATORY = ("result", "artifact", "costs", "config", "code", "data", "calendar", "units",
             "period", "protocol")


# --------------------------------------------------------------------------------- fixtures
@pytest.fixture
def panels(tmp_path, monkeypatch):
    """Two synthetic input sets with the real sharing pattern (see test_accredit_433.py)."""
    root = str(tmp_path / "inputs")
    os.makedirs(root, exist_ok=True)
    names = ("coverage", "etf_close", "irx", "membership", "price_close", "price_close_raw",
             "price_open", "sp500_pit_payload", "spy", "volume")
    shared = {}
    for n in ("etf_close", "irx"):
        f = os.path.join(root, f"shared_{n}.bin")
        with open(f, "wb") as fh:
            fh.write(f"shared:{n}".encode())
        shared[n] = f

    def one(panel):
        out = dict(shared)
        for n in names:
            if n in shared:
                continue
            if panel == "russell" and n == "sp500_pit_payload":
                out[n] = None
                continue
            if panel == "sp500" and n in ("membership", "coverage"):
                out[n] = None
                continue
            f = os.path.join(root, f"{panel}_{n}.bin")
            with open(f, "wb") as fh:
                fh.write(f"{panel}:{n}".encode())
            out[n] = f
        return out

    inputs = {"russell": one("russell"), "sp500": one("sp500")}
    monkeypatch.setattr(CS, "data_inputs", lambda panel: dict(inputs[panel]))
    return inputs


@pytest.fixture
def grid(monkeypatch):
    """The real derivation (`calendar_spec.expected_grid`) over a synthetic calendar."""
    A._ANCHOR_CAL_CACHE.clear()
    idx = pd.bdate_range("2010-01-04", periods=4000)
    monkeypatch.setattr(CS, "derived_grid",
                        lambda panel: CSPEC.expected_grid(idx, calendar_source="synthetic index"))
    yield idx
    A._ANCHOR_CAL_CACHE.clear()


@pytest.fixture
def slot(tmp_path, monkeypatch):
    d = str(tmp_path / "acc")
    os.makedirs(d, exist_ok=True)
    monkeypatch.setattr(A, "ACC_DIR", d)
    return d


def _marks():
    return pd.DatetimeIndex(CS.derived_grid("russell")["marks"])


def _book(marks=None, scale=1.0):
    marks = _marks() if marks is None else marks
    return pd.Series([1.0 + scale * 0.0007 * i for i in range(len(marks))], index=marks)


def _publish(panel, label, *, request=None, book=None):
    """Write a book and a manifest sealed from `request` (default: the scenario's own)."""
    book = _book() if book is None else book
    path = A.not_historical(A.acc_path(panel, label))
    pd.to_pickle(book, path)
    man = PV.write_manifest(book, path, request or A.effective_request(panel, label))
    return path, book, man


def _block(exc) -> str:
    """The identity BLOCK a rejection names.

    `provenance` tags a refusal as precisely as it can - `data:membership`,
    `config.v9_effective_sha256`, `period.declared` - which is better than a bare block name and
    is why the first version of these assertions failed against a contract that was doing more,
    not less. The tests compare the block and print the full tag.
    """
    return str(getattr(exc, "field", "")).split(":")[0].split(".")[0]


def _reject(panel, label, path=None):
    """Ask `accredit` the scenario's effective question; return the CacheRejected or None."""
    try:
        PV.accredit(path or A.acc_path(panel, label), A.effective_request(panel, label),
                    echo=False)
    except PV.CacheRejected as exc:
        return exc
    return None


def _reseal(path, mutate):
    """Mutate a manifest on disk and RE-SEAL it, so `self_sha256` verifies again."""
    man = PV.read_manifest(path)
    mutate(man)
    man.pop("self_sha256", None)
    man = PV.seal(man)
    with open(PV.manifest_path(path), "w", encoding="utf-8") as fh:
        json.dump(man, fh, indent=2, default=str)
    return man


# ------------------------------------------------------------------ the positive case, first
def test_a_book_driven_for_this_scenario_accredits_with_every_mandatory_block_compared(
        panels, grid, slot):
    """Without this, every rejection below is compatible with 'accredit() always says no'."""
    _publish("russell", "base")
    answer = A.accredit_answer("russell", "base")
    assert answer["state"] == PV.ACCREDITED, answer["rejected"]
    compared = set(answer["accreditation"]["compared"])
    missing = [b for b in MANDATORY if b not in compared]
    assert not missing, (
        f"accredited with {missing} never compared; uncompared_why="
        f"{answer['accreditation']['uncompared_why']}")
    for field, why in (answer["accreditation"]["uncompared_why"] or {}).items():
        assert A._permitted_uncompared(field, why), (
            f"{field} went uncompared for a reason the contract does not name: {why!r}. "
            "That is IDENTITY INCOMPLETE, not accredited.")


def test_the_anchor_grid_reaches_the_other_scenarios(panels, grid, slot):
    """PROV-08's second half, as a regression.

    `anchor_calendar()` used to build its own request with `calendar=None`, which `provenance`
    refuses, so it always returned None and every non-anchor scenario was requested without a
    calendar and rejected - `fully_accredited` could never be true. Found by preflight_433.py on
    2026-09-14 before any book was driven. The anchor is now validated with the same effective
    request everything else judges it by.
    """
    _publish("russell", "base")
    cal = A.anchor_calendar()
    assert cal, "the accredited anchor yielded no calendar; the other seven cannot be requested"
    marks = _marks()
    assert cal["n_marks"] == len(marks)
    assert cal["sha256"] == PV.calendar_sha256(marks), (
        "the anchor must hand over the grid it actually holds, not a summary of it")
    _publish("russell", "stress")
    assert A.accredit_answer("russell", "stress")["state"] == PV.ACCREDITED


def test_the_pre_prov08_anchor_calendar_makes_fully_accredited_impossible(
        panels, grid, slot, tmp_path, monkeypatch):
    """The DEFECT, reproduced end to end, not just the fix asserted.

    This is the chain preflight_433.py found on 2026-09-14, before any book was driven:

        anchor_calendar() builds its own request with calendar=None
          -> provenance refuses a request that declares neither a grid nor 'calendar_anchor'
          -> anchor_calendar() returns None
          -> the seven non-anchor scenarios are requested WITHOUT a calendar
          -> the seven are rejected on [calendar]
          -> fully_accredited can never be true, however good the books are

    The eight books published here are the SAME eight in both halves of the test. Only
    `anchor_calendar` changes, so the difference in the verdict is attributable to it and to
    nothing else. That is the point: a regression that only asserted "the fixed version works"
    would pass against a version that happened to work for another reason.
    """
    out_dir = str(tmp_path / "hist")
    os.makedirs(os.path.join(out_dir, "cost_stress"), exist_ok=True)
    monkeypatch.setattr(CS, "OUT_DIR", os.path.join(out_dir, "cost_stress"))
    monkeypatch.setattr(CS, "BASE_BOOKS",
                        {p: os.path.join(out_dir, f"engine_book_{p}.pkl") for p in CS.PANELS})
    monkeypatch.setattr(A, "OUT_JSON", str(tmp_path / "out.json"))
    for panel, label in A.ORDER:
        _publish(panel, label)
    irx = pd.Series(0.015, index=pd.bdate_range("2010-01-04", periods=4000))

    # --- half 1: the pre-PROV-08 implementation, restored verbatim
    def pre_prov08_anchor_calendar():
        path = A.acc_path("russell", "base")
        if not os.path.exists(path):
            return None
        try:
            PV.accredit(path, CS.request("russell", "base", *A.scenario_bp("base"),
                                         calendar=None), echo=False)
        except (PV.CacheRejected, A.PanelMismatch):
            return None
        return PV.calendar_block(pd.read_pickle(path))

    real_anchor_calendar = A.anchor_calendar
    monkeypatch.setattr(A, "anchor_calendar", pre_prov08_anchor_calendar)
    A._ANCHOR_CAL_CACHE.clear()
    assert pre_prov08_anchor_calendar() is None, (
        "the old implementation must fail to validate the anchor - that IS the defect")
    broken = A.reconcile(irx=irx)
    assert broken["provenance"]["fully_accredited"] is False
    assert len(broken["provenance"]["accredited"]) == 1, (
        "only the anchor should survive: the other seven lose their calendar")
    for rec in broken["reconciliation"]:
        if (rec["panel"], rec["scenario"]) == ("russell", "base"):
            continue
        assert rec["accredited_class"] != PV.ACCREDITED
        assert "calendar" in json.dumps(rec["rejected"]), rec["rejected"]

    # --- half 2: the same eight books, the fixed implementation.
    # Restore ONLY `anchor_calendar`. `monkeypatch.undo()` would also unwind the `panels` and
    # `grid` fixtures, putting the real 271 MB panel back in the path - measured: the test hit
    # the 30 s timeout inside `Panels.__init__` rather than failing on anything meaningful.
    monkeypatch.setattr(A, "anchor_calendar", real_anchor_calendar)
    monkeypatch.setattr(A, "OUT_JSON", str(tmp_path / "out2.json"))
    A._ANCHOR_CAL_CACHE.clear()
    fixed = A.reconcile(irx=irx)
    assert fixed["provenance"]["fully_accredited"] is True, fixed["provenance"]["rejected"]
    assert len(fixed["provenance"]["accredited"]) == 8


def test_the_anchor_is_validated_with_the_same_request_it_is_judged_by():
    """Two requests for one book is how the two halves of PROV-08 drifted apart. One request.

    Read from the AST, not from the text: the docstring of `anchor_calendar` quotes the old
    `calendar=None` request on purpose, to record what the defect was, and a substring search
    over the source cannot tell that apart from the defect itself.
    """
    import ast  # noqa: PLC0415

    src = open(os.path.join(HERE, "accredit_433.py"), encoding="utf-8").read()
    fn = next(n for n in ast.parse(src).body
              if isinstance(n, ast.FunctionDef) and n.name == "anchor_calendar")
    body = fn.body[1:] if ast.get_docstring(fn) else fn.body      # drop the docstring node
    code = chr(10).join(ast.unparse(n) for n in body)
    assert "effective_request('russell', 'base')" in code.replace('"', "'"), (
        "anchor_calendar must validate the anchor with effective_request, not with a request it "
        "builds itself - a second hand-built request is exactly what went stale. Got: " + code)
    assert "calendar=None" not in code, (
        "the pre-PROV-08 request is back in anchor_calendar's BODY: " + code)


# ------------------------------------------------------------------------ 1: scenario label
def test_1_a_book_sealed_for_another_scenario_label_is_refused(panels, grid, slot):
    path, _b, _m = _publish("russell", "stress",
                            request=A.effective_request("russell", "conservative"))
    exc = _reject("russell", "stress", path)
    assert exc is not None, "a conservative book answered the stress question"
    assert _block(exc) == "costs", exc


# ---------------------------------------------------------------------------- 2: cost pair
def test_2_a_moved_cost_pair_is_refused(panels, grid, slot):
    path, _b, _m = _publish("russell", "base")
    _reseal(path, lambda m: m["costs"].update(stock_bp_per_side=11.0))
    exc = _reject("russell", "base", path)
    assert exc is not None and _block(exc) == "costs", exc
    assert "11" in str(exc) or "10" in str(exc)


def test_2b_the_effective_config_carries_the_scenario_costs_not_the_defaults(panels, grid):
    """The cost pair must reach `config.v9_effective`, or 20/8 and 15/13 would be indistinguishable."""
    for label, s_bp, e_bp in (("base", 10.0, 5.0), ("conservative", 20.0, 8.0),
                              ("stress", 35.0, 10.0), ("smallcap_crisis", 50.0, 15.0)):
        req = A.effective_request("russell", label)
        assert req["costs"]["stock_bp_per_side"] == s_bp
        assert req["costs"]["etf_bp_per_side"] == e_bp
        assert req["config"]["v9_effective"]["stock_cost_bp"] == s_bp
        assert req["config"]["v9_effective"]["etf_cost_bp"] == e_bp


# ------------------------------------------------------------------------- 3: panel identity
def test_3_a_book_driven_on_the_other_panel_is_refused(panels, grid, slot):
    path, _b, _m = _publish("sp500", "base", request=A.effective_request("russell", "base"))
    exc = _reject("sp500", "base", path)
    assert exc is not None, "a russell book answered the sp500 question"
    assert _block(exc) == "data", exc
    with pytest.raises(A.PanelMismatch):
        A.data_answers("sp500", path)


# ------------------------------------------------------------------------------ 4: calendar
def test_4_a_book_on_a_different_calendar_is_refused(panels, grid, slot):
    short = _marks()[:-40]
    path, _b, _m = _publish("russell", "base", book=_book(short))
    exc = _reject("russell", "base", path)
    assert exc is not None and _block(exc) == "calendar", exc
    assert str(len(short)) in str(exc)


# -------------------------------------------------------------------------------- 5: period
def test_5_a_moved_period_declaration_is_refused(panels, grid, slot):
    path, _b, _m = _publish("russell", "base")
    _reseal(path, lambda m: m["period"].update(declared="research"))
    exc = _reject("russell", "base", path)
    assert exc is not None and _block(exc) == "period", exc


def test_5b_a_moved_holdout_hash_is_refused(panels, grid, slot):
    path, _b, _m = _publish("russell", "base")
    _reseal(path, lambda m: m["period"].update(holdout_sha256="0" * 64))
    exc = _reject("russell", "base", path)
    assert exc is not None and _block(exc) == "period", exc


# ------------------------------------------------------------------------- 6: data identity
def test_6_one_changed_input_digest_is_refused(panels, grid, slot):
    path, _b, _m = _publish("russell", "base")
    _reseal(path, lambda m: m["data"]["price_close"].update(sha256="0" * 64))
    exc = _reject("russell", "base", path)
    assert exc is not None and _block(exc) == "data", exc


def test_6b_an_input_recorded_as_null_that_was_actually_read_is_refused(panels, grid, slot):
    """A panel swap must not be able to hide as a SHORTER manifest."""
    path, _b, _m = _publish("russell", "base")
    _reseal(path, lambda m: m["data"].update(membership=None))
    exc = _reject("russell", "base", path)
    assert exc is not None and _block(exc) == "data", exc


# ----------------------------------------------------------------------- 7: config identity
def test_7_a_moved_config_digest_is_refused(panels, grid, slot):
    path, _b, _m = _publish("russell", "base")
    _reseal(path, lambda m: m["config"].update(v9_effective_sha256="0" * 64))
    exc = _reject("russell", "base", path)
    assert exc is not None and _block(exc) == "config", exc


def test_7b_a_moved_code_digest_is_refused(panels, grid, slot):
    path, _b, _m = _publish("russell", "base")
    _reseal(path, lambda m: m["code"].update(modules_combined="0" * 64))
    exc = _reject("russell", "base", path)
    assert exc is not None and _block(exc) == "code", exc


# ------------------------------------------ 8: a historical artifact substituted for a new run
def test_8_a_historical_book_cannot_stand_in_for_a_new_run(panels, grid, slot, tmp_path):
    """The pre-manifest books carry no manifest at all, so they cannot answer anything - and the
    accredited slot may not be pointed at one either."""
    hist = tmp_path / "engine_book_russell.pkl"
    pd.to_pickle(_book(), hist)
    exc = _reject("russell", "base", str(hist))
    assert exc is not None, "a book with no manifest answered a request"
    assert _block(exc) in ("artifact", "self_sha256", "manifest"), exc

    # and the write guard refuses the historical PATHS wherever acc_path is pointed
    for p in CS.historical_books():
        with pytest.raises(SystemExit, match="REFUSING TO WRITE OVER A HISTORICAL BOOK"):
            A.not_historical(p)


# ------------------------------------------------------- 9: modified and re-sealed (the LIMIT)
def test_9_an_artifact_modified_and_resealed_passes_the_seal_and_is_still_refused(
        panels, grid, slot):
    """`self_sha256` is unkeyed: re-sealing restores it. The REQUEST is what refuses.

    This is the documented limitation, pinned as a test so it cannot be quietly overstated: the
    seal proves the file was not corrupted, not that its author did not change it on purpose.
    """
    path, _b, _m = _publish("russell", "base")
    man = _reseal(path, lambda m: m["costs"].update(stock_bp_per_side=99.0))
    ok, _stored, _recomputed = PV.seal_ok(man)
    assert ok, "the re-sealed manifest must pass the seal check - that is the point of this test"
    exc = _reject("russell", "base", path)
    assert exc is not None and _block(exc) == "costs", (
        "a re-sealed artifact was accepted; integrity of the file is not compatibility with a "
        "request")


def test_9b_the_limitation_is_written_down_where_the_result_is_published(panels, grid, slot):
    src = open(os.path.join(HERE, "accredit_433.py"), encoding="utf-8").read()
    assert "unkeyed digest" in src and "re-seal" in src, (
        "the self_sha256 limitation must travel with the published result")


# --------------------------------------------------------------- 10: a missing identity block
@pytest.mark.parametrize("block", ["costs", "data", "config", "period", "protocol", "units"])
def test_10_a_missing_identity_block_is_refused(panels, grid, slot, block):
    path, _b, _m = _publish("russell", "base")
    _reseal(path, lambda m: m.pop(block, None))
    exc = _reject("russell", "base", path)
    assert exc is not None, f"a manifest with no {block!r} block was accredited"


def test_10b_an_empty_identity_block_is_refused_too(panels, grid, slot):
    """Present-but-empty is the shape the PROV-01 decoy used: `fixture_only=true` and nothing else."""
    path, _b, _m = _publish("russell", "base")
    _reseal(path, lambda m: m.update(costs={}))
    exc = _reject("russell", "base", path)
    assert exc is not None, "an empty costs block was accredited"


# ------------------------------------------------ 11: a shifted calendar of EQUAL LENGTH
def test_11_a_shifted_calendar_of_the_same_length_is_refused(panels, grid, slot):
    """Length is not identity. Same number of marks, different dates, must not answer."""
    marks = _marks()
    shifted = pd.DatetimeIndex([d + pd.Timedelta(days=7) for d in marks])
    assert len(shifted) == len(marks) and not shifted.equals(marks)
    path, _b, _m = _publish("russell", "base", book=_book(shifted))
    exc = _reject("russell", "base", path)
    assert exc is not None and _block(exc) == "calendar", (
        f"a calendar shifted by a week with the same {len(marks)} marks was accepted: {exc}")


# ---------------------------------------------- 12: metrics correct, provenance incorrect
def test_12_a_book_whose_numbers_are_right_but_whose_provenance_is_wrong_is_refused(
        panels, grid, slot):
    """The whole point of TASK-433: a plausible number is not evidence.

    The book is bit-identical to the one that accredits - same marks, same values, so every
    statistic computed from it is identical - and only its recorded provenance is wrong. It must
    be refused, and `reconcile` must not count it.
    """
    good_path, good_book, _m = _publish("russell", "base")
    good_sha = PV.book_sha256(good_book)
    _reseal(good_path, lambda m: m["data"]["spy"].update(sha256="0" * 64))
    assert PV.book_sha256(pd.read_pickle(good_path)) == good_sha, "the BOOK must be untouched"
    exc = _reject("russell", "base", good_path)
    assert exc is not None and _block(exc) == "data", exc
    assert A.accredit_answer("russell", "base")["state"] != PV.ACCREDITED


def test_12b_the_aggregate_refuses_to_say_fully_accredited_with_one_bad_book(
        panels, grid, slot, tmp_path, monkeypatch):
    """Seven good books and one with wrong provenance is not `fully_accredited`."""
    out_dir = str(tmp_path / "hist")
    os.makedirs(os.path.join(out_dir, "cost_stress"), exist_ok=True)
    monkeypatch.setattr(CS, "OUT_DIR", os.path.join(out_dir, "cost_stress"))
    monkeypatch.setattr(CS, "BASE_BOOKS",
                        {p: os.path.join(out_dir, f"engine_book_{p}.pkl") for p in CS.PANELS})
    monkeypatch.setattr(A, "OUT_JSON", str(tmp_path / "out.json"))
    for panel, label in A.ORDER:
        _publish(panel, label)
    bad = A.acc_path("sp500", "stress")
    _reseal(bad, lambda m: m["costs"].update(etf_bp_per_side=1.0))

    irx = pd.Series(0.015, index=pd.bdate_range("2010-01-04", periods=4000))
    payload = A.reconcile(irx=irx)
    assert payload["provenance"]["fully_accredited"] is False
    assert "sp500/stress" in payload["provenance"]["still_historical_only"]
    assert len(payload["provenance"]["accredited"]) == 7


def test_12c_eight_good_books_do_reach_fully_accredited(panels, grid, slot, tmp_path, monkeypatch):
    """And the control: the aggregate is not hard-wired to False either."""
    out_dir = str(tmp_path / "hist")
    os.makedirs(os.path.join(out_dir, "cost_stress"), exist_ok=True)
    monkeypatch.setattr(CS, "OUT_DIR", os.path.join(out_dir, "cost_stress"))
    monkeypatch.setattr(CS, "BASE_BOOKS",
                        {p: os.path.join(out_dir, f"engine_book_{p}.pkl") for p in CS.PANELS})
    monkeypatch.setattr(A, "OUT_JSON", str(tmp_path / "out.json"))
    for panel, label in A.ORDER:
        _publish(panel, label)
    irx = pd.Series(0.015, index=pd.bdate_range("2010-01-04", periods=4000))
    payload = A.reconcile(irx=irx)
    assert payload["provenance"]["fully_accredited"] is True
    assert len(payload["provenance"]["accredited"]) == 8
    assert payload["provenance"]["still_historical_only"] == []


# ------------------------------------------------ the run-level code freeze (TASK-433)
def test_the_freeze_guard_tolerates_a_module_loaded_for_the_first_time(monkeypatch):
    """`swept` GROWS during a run. A module ARRIVING is not a module that MOVED.

    Measured 2026-09-14: comparing the two snapshots by dict equality read the first import of
    `sleeves/etf_trend.py` as a change and aborted a healthy run at book two. The guard now
    compares the intersection, exactly as `provenance._check_code` does.
    """
    frozen = dict(modules_combined="abc", swept={"a.py": "1"}, modules={}, deps={})
    monkeypatch.setattr(A, "_RUN_CODE", frozen)
    grew = dict(modules_combined="abc", swept={"a.py": "1", "new.py": "2"}, modules={}, deps={})
    monkeypatch.setattr(PV, "code_identity", lambda: grew)
    A.check_code_unchanged("book2")          # must not raise


def test_the_freeze_guard_stops_a_module_that_actually_changed(monkeypatch):
    frozen = dict(modules_combined="abc", swept={"a.py": "1"}, modules={}, deps={})
    monkeypatch.setattr(A, "_RUN_CODE", frozen)
    moved = dict(modules_combined="abc", swept={"a.py": "CHANGED"}, modules={}, deps={})
    monkeypatch.setattr(PV, "code_identity", lambda: moved)
    with pytest.raises(A.CodeMovedDuringRun, match="CODE MOVED DURING THE RUN"):
        A.check_code_unchanged("book2")


def test_the_freeze_guard_stops_an_enumerated_module_that_changed(monkeypatch):
    frozen = dict(modules_combined="abc", swept={}, modules={}, deps={})
    monkeypatch.setattr(A, "_RUN_CODE", frozen)
    moved = dict(modules_combined="DIFFERENT", swept={}, modules={}, deps={})
    monkeypatch.setattr(PV, "code_identity", lambda: moved)
    with pytest.raises(A.CodeMovedDuringRun, match="modules_combined"):
        A.check_code_unchanged()


def test_the_guard_is_inert_outside_a_run(monkeypatch):
    monkeypatch.setattr(A, "_RUN_CODE", None)
    A.check_code_unchanged("anywhere")       # nothing frozen, nothing to compare


def test_the_run_id_is_a_property_of_the_repo_not_of_one_process(monkeypatch):
    """It is minted from files read off disk, so the preflight and the driver agree.

    Minting over `swept` made the id depend on what a process happened to have imported, which is
    how the preflight and the driver came to disagree about the id for one tree.
    """
    first = A.mint_run_id()
    monkeypatch.setitem(sys.modules, "_a_module_that_was_not_loaded_before", pytest)
    assert A.mint_run_id() == first


def test_the_run_id_moves_when_a_driver_module_moves(monkeypatch, tmp_path):
    before = A.mint_run_id()
    real = PV.sha256_lf

    def shifted(path):
        if path.endswith("accredit_433.py"):
            return "0" * 64
        return real(path)

    monkeypatch.setattr(PV, "sha256_lf", shifted)
    assert A.mint_run_id() != before, (
        "editing accredit_433.py must move the run id; it is in the swept set and voided run "
        "20260914-99967d14f3ad")


def test_the_driver_list_is_what_a_finished_run_actually_sweeps():
    """The list the id is minted over must not go stale against the modules a drive loads."""
    assert "experiments/accredit_433.py" in A.RUN_ID_DRIVERS
    assert "sleeves/etf_trend.py" in A.RUN_ID_DRIVERS
    for rel in A.RUN_ID_DRIVERS:
        assert os.path.exists(os.path.join(A.ROOT, rel)), f"{rel} is in the list but not on disk"
