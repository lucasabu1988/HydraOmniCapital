"""The TASK-433 table renderer, on synthetic payloads. Portable: reads no real run.

The renderer computes no statistic - every number comes from the payload `reconcile()` wrote -
so what is worth pinning is the part that can still mislead: that a NOT-ACCREDITED scenario can
never be rendered as a row of numbers, that the T-bill crossing is read from the data rather than
asserted, and that "no scenario crosses" is stated rather than left as an absence.
"""
from __future__ import annotations

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (HERE, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import report_433 as RPT  # noqa: E402

ORDER = [f"{p}/{s}" for p in ("russell", "sp500")
         for s in ("base", "conservative", "stress", "smallcap_crisis")]
BLOCKS = ["result", "artifact", "costs", "config", "code", "data", "calendar", "units",
          "period", "protocol"]


def _row(panel, scenario, ann, sharpe, dd, rf, d=(0.0, 0.0, 0.0)):
    return dict(panel=panel, scenario=scenario, ann_net=ann, sharpe_excess=sharpe,
                maxdd_net=dd, rf_ann_pct=rf, below_tbill=ann < rf,
                d_ann_net=d[0], d_sharpe_excess=d[1], d_maxdd=d[2],
                n=814, first="2010-06-28", last="2026-08-26",
                stock_bp=10.0, etf_bp=5.0, provenance="accredited")


CAL = dict(n_marks=814, first="2010-06-28", last="2026-08-26", sha256="cd" * 32)


def _payload(rows, *, accredited=None, fully=True, run_id="runid-test", cal_by=None):
    accredited = ORDER if accredited is None else accredited
    cal_by = cal_by or {}
    return dict(
        run_id=run_id, order=ORDER, accredited_dir="experiments/_lab_scratch/x",
        rows_accredited=rows,
        reconciliation=[dict(panel=r["panel"], scenario=r["scenario"], stock_bp=r["stock_bp"],
                             etf_bp=r["etf_bp"], accredited_sha256="ab" * 32,
                             accredited_calendar=cal_by.get((r["panel"], r["scenario"]), CAL))
                        for r in rows],
        marks_accredited=dict(n_books=len(rows), identical=True),
        provenance=dict(accredited=accredited, still_historical_only=[], rejected={},
                        compared_by_book={k: BLOCKS for k in accredited},
                        uncompared_by_book={k: {} for k in accredited},
                        uncompared_keys_by_book={}, fully_accredited=fully,
                        validated_by="test"))


def _eight(ann_by=None):
    ann_by = ann_by or {}
    rows = []
    for panel in ("russell", "sp500"):
        base = 6.0 if panel == "russell" else 8.0
        for i, sc in enumerate(("base", "conservative", "stress", "smallcap_crisis")):
            ann = ann_by.get((panel, sc), base - 0.5 * i)
            rows.append(_row(panel, sc, ann, 0.5 - 0.05 * i, -16.0 - i, 1.5,
                             d=(ann - base, -0.05 * i, -float(i))))
    return rows


def test_the_table_carries_every_scenario_and_all_three_deltas():
    md = RPT.table_md(_payload(_eight()))
    for sc in RPT.SCENARIOS:
        assert sc in md
    for bp in ("10/5", "20/8", "35/10", "50/15"):
        assert bp in md, f"the frozen cost pair {bp} is not in the table"
    for head in ("ΔCAGR pp", "ΔSharpe", "ΔmaxDD pp", "T-bill %"):
        assert head in md, f"the mandatory column {head!r} is missing"


def test_a_scenario_that_did_not_accredit_is_never_rendered_as_numbers():
    """The failure mode this exists to stop: a plausible row standing in for evidence."""
    rows = [r for r in _eight() if (r["panel"], r["scenario"]) != ("sp500", "stress")]
    md = RPT.table_md(_payload(rows, accredited=[k for k in ORDER if k != "sp500/stress"],
                               fully=False))
    line = [ln for ln in md.splitlines() if ln.startswith("| stress |") and "NOT ACCREDITED" in ln]
    assert line, "a missing scenario must be marked NOT ACCREDITED, not omitted or interpolated"


def test_the_tbill_crossing_is_read_from_the_data():
    below = {("russell", "stress"): 1.0, ("russell", "smallcap_crisis"): 0.5}
    got = dict(RPT.crossing(_payload(_eight(below))))
    assert got["russell"] == "stress", got
    assert got["sp500"] is None, got


def test_no_crossing_is_said_out_loud_rather_than_left_as_an_absence():
    text = RPT.render(_payload(_eight()))
    assert "ningun escenario" in text
    assert "50/15" in text


def test_a_crossing_is_named_with_its_cost_pair():
    text = RPT.render(_payload(_eight({("sp500", "smallcap_crisis"): 0.9})))
    assert "smallcap_crisis" in text and "50/15" in text


def test_the_self_sha256_limitation_travels_with_the_table():
    text = RPT.render(_payload(_eight()))
    assert "SIN" in text.upper() and "CLAVE" in text.upper()
    assert "resella" in text or "sellar" in text


def test_the_accreditation_section_lists_every_scenario_and_the_blocks_it_compared():
    md = RPT.identity_md(_payload(_eight()))
    for key in ORDER:
        assert key in md
    assert "fully_accredited = true" in md
    for block in BLOCKS:
        assert block in md


def test_a_partial_accreditation_renders_as_false():
    md = RPT.identity_md(_payload(_eight(), accredited=ORDER[:7], fully=False))
    assert "fully_accredited = false" in md
    assert "NOT ACCREDITED" in md


def test_an_absent_report_is_a_refusal_not_an_empty_table(tmp_path, monkeypatch):
    monkeypatch.setattr(RPT, "HERE", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="absent report is not an empty one"):
        RPT.load("nope")


def test_a_present_report_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(RPT, "HERE", str(tmp_path))
    os.makedirs(tmp_path / "_lab_scratch", exist_ok=True)
    payload = _payload(_eight(), run_id="rt")
    (tmp_path / "_lab_scratch" / "task433_accredited_rt.json").write_text(
        json.dumps(payload), encoding="utf-8")
    assert RPT.load("rt")["run_id"] == "rt"


# ------------------------------------------------------------------ the hard comparison-grid gate
def test_the_table_refuses_to_render_when_the_books_are_on_two_calendars():
    """The S&P NATIVE grid (1084 marks from 2005) is not the comparison grid (814 from 2010).

    A delta is a subtraction between two books. Two calendars would leave the table looking
    exactly as plausible and meaning nothing, so this is a refusal and not a footnote.
    """
    native = dict(n_marks=1084, first="2005-02-11", last="2026-08-24", sha256="ef" * 32)
    payload = _payload(_eight(), cal_by={("sp500", sc): native for sc in RPT.SCENARIOS})
    with pytest.raises(RPT.OneGridViolated, match="NOT on one comparison grid"):
        RPT.render(payload)


def test_the_gate_names_the_offending_scenarios_and_their_calendars():
    native = dict(n_marks=1084, first="2005-02-11", last="2026-08-24", sha256="ef" * 32)
    payload = _payload(_eight(), cal_by={("sp500", "stress"): native})
    with pytest.raises(RPT.OneGridViolated) as exc:
        RPT.assert_one_comparison_grid(payload)
    assert "sp500/stress" in str(exc.value) and "1084" in str(exc.value)


def test_an_incomplete_run_has_no_table_at_all():
    rows = [r for r in _eight() if (r["panel"], r["scenario"]) != ("sp500", "stress")]
    payload = _payload(rows, accredited=[k for k in ORDER if k != "sp500/stress"], fully=False)
    with pytest.raises(RPT.OneGridViolated, match="a missing book is not a zero"):
        RPT.render(payload)


def test_the_gate_checks_the_per_book_blocks_not_the_aggregate_boolean():
    """A boolean produced by the same pass that produced the rows is not independent of them."""
    payload = _payload(_eight())
    payload["marks_accredited"] = dict(n_books=8, identical=False)
    with pytest.raises(RPT.OneGridViolated, match="aggregate disagrees"):
        RPT.assert_one_comparison_grid(payload)


def test_one_grid_passes_and_reports_what_it_verified():
    got = RPT.assert_one_comparison_grid(_payload(_eight()))
    assert got["n_marks"] == 814
    assert got["first"] == "2010-06-28" and got["last"] == "2026-08-26"
    text = RPT.render(_payload(_eight()))
    assert "Rejilla de comparacion verificada: **814 marcas**" in text
    assert "identica en los ocho libros" in text


# ------------------------------------------------------------------ the degradation reading
def test_a_material_improvement_as_costs_rise_is_flagged():
    """Not monotonicity - the shape of a mislabelled book or a swapped cost pair."""
    rows = _eight({("russell", "stress"): 99.0})
    found = RPT.degradation_anomalies(_payload(rows))
    assert found and found[0]["panel"] == "russell"
    assert found[0]["cheaper"] == "conservative" and found[0]["dearer"] == "stress"
    text = RPT.render(_payload(rows))
    assert "ANOMALIA DE DEGRADACION" in text


def test_an_ordinary_degradation_is_not_flagged():
    assert RPT.degradation_anomalies(_payload(_eight())) == []
    assert "ANOMALIA DE DEGRADACION" not in RPT.render(_payload(_eight()))


def test_a_tiny_improvement_within_tolerance_is_not_flagged():
    """Sharpe and maxDD may move either way; ann_net noise below the tolerance is not a finding."""
    rows = _eight()
    by = {(r["panel"], r["scenario"]): r for r in rows}
    by[("sp500", "stress")]["ann_net"] = by[("sp500", "conservative")]["ann_net"] + 0.01
    assert RPT.degradation_anomalies(_payload(rows)) == []


def test_the_degradation_note_says_monotonicity_is_not_required():
    text = RPT.render(_payload(_eight()))
    assert "monotonicidad" in text and "trayectoria" in text


# ------------------------------------------------------------------ the sector caveat
def test_the_sector_caveat_is_in_every_rendered_report():
    text = RPT.render(_payload(_eight()))
    for phrase in ("fixed_map", "pit_valid=False", "turnover", "condicional",
                   "No son una estimacion universal"):
        assert phrase in text, f"the sector caveat lost {phrase!r}"


def test_the_caveat_ties_the_sector_map_to_turnover_and_therefore_to_cost_sensitivity():
    """The chain is the point: map -> selection/concentration -> turnover -> cost sensitivity."""
    c = RPT.SECTOR_CAVEAT
    assert "MAX_PER_SECTOR" in c
    assert "seleccion" in c and "concentracion" in c and "turnover" in c
    assert "no es independiente" in c


def test_the_caveat_scopes_the_deltas_to_this_experimental_trajectory():
    c = RPT.SECTOR_CAVEAT
    assert "TASK-431" in c, "the deltas are conditional on sharing TASK-431's construction"
    assert "niveles absolutos" in c
