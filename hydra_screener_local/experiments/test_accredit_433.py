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
import cost_stress as CS  # noqa: E402
import provenance as PV  # noqa: E402


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


def test_a_book_driven_on_another_panel_is_refused_by_name_of_the_input(monkeypatch, tmp_path):
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


def test_an_unaccreditable_file_in_the_accredited_slot_stops_the_run_and_is_left_alone(
        monkeypatch, tmp_path):
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


def test_reconcile_reports_the_historical_books_without_touching_them(monkeypatch, tmp_path):
    """With no accredited book at all, the historical table is still produced and nothing moves."""
    monkeypatch.setattr(A, "ACC_DIR", str(tmp_path / "acc"))
    monkeypatch.setattr(A, "OUT_JSON", str(tmp_path / "out.json"))
    before = {p: os.stat(p).st_mtime_ns for p in CS.historical_books() if os.path.exists(p)}
    if not before:
        pytest.skip("no historical books on this machine")

    payload = A.reconcile()
    assert payload["provenance"]["fully_accredited"] is False
    assert payload["provenance"]["accredited"] == []
    assert len(payload["provenance"]["still_historical_only"]) == 8
    assert payload["rows_accredited"] == []
    assert {r["provenance"] for r in payload["rows_historical"]} == {PV.HISTORICAL}
    assert {p: os.stat(p).st_mtime_ns for p in before} == before
    for p in before:
        assert not os.path.exists(PV.manifest_path(p)), "a historical book was given a manifest"
    with open(str(tmp_path / "out.json"), encoding="utf-8") as fh:
        assert json.load(fh)["artifact_set"] == "accredited"


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

    The withdrawn artifact still sits at the path consumers knew, so the refusal has to be in
    the accessor, and a new run must publish somewhere unambiguous rather than overwrite it.
    """
    import pytest
    with pytest.raises(ValueError, match="WITHDRAWN on 2026-09-12"):
        A.current_result(A.WITHDRAWN_JSON)
    assert os.path.exists(A.WITHDRAWN_JSON), "the historical artifact must be preserved"
    assert os.path.exists(A.WITHDRAWAL_NOTE), "the withdrawal record must sit beside it"
    assert os.path.abspath(A.OUT_JSON) != os.path.abspath(A.WITHDRAWN_JSON), \
        "a new run must not overwrite the preserved artifact"
    # and with no replacement yet, asking for the current result is a refusal, not a fallback
    if not os.path.exists(A.OUT_JSON):
        with pytest.raises(FileNotFoundError, match="TASK-433 is OPEN"):
            A.current_result()
