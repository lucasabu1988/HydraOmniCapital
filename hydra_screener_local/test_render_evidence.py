"""TASK-408: the published numbers match the canonical artifact, or this test fails.

The last test is the point of the whole task: edit 7.10 by hand in the README, or change the
JSON without re-rendering, and the suite goes red. Auto-discovered by run_all_tests.py.
"""
import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import render_evidence as R  # noqa: E402

SYNTHETIC = {
    "generated_by": "test",
    "measured_at": "2026-01-02",
    "source": {"script": "experiments/engine_backtest.py", "args": ["--oos"],
               "scratch": "experiments/_lab_scratch/task350.json", "commit": "abc1234"},
    "panel": {"name": "test panel", "name_es": "panel de prueba", "first_mark": "2005-02-11",
              "last_mark": "2026-08-24", "first_year": "2005", "last_year": "2026",
              "task": "TASK-350"},
    "rows": [
        {"key": "engine", "label": "engine", "cycles": 1083, "ann_net": 7.10,
         "ratio_net_vol": 0.75, "sharpe_excess": 0.57, "maxdd_net": -17.8,
         "rf_ann_pct": 1.76, "ratio_minus_sharpe": 0.18},
        {"key": "lab_mix", "label": "lab mix", "cycles": 1084, "ann_net": 6.91,
         "ratio_net_vol": 0.74, "sharpe_excess": 0.56, "maxdd_net": -19.5,
         "rf_ann_pct": 1.76, "ratio_minus_sharpe": 0.18},
    ],
    "reference": [
        {"key": "screener_v84", "label": "v8.4", "cycles": None, "ann_net": 5.5,
         "ratio_net_vol": 0.42, "sharpe_excess": None, "maxdd_net": -37.8, "source": "2026-09-06"},
        {"key": "spy_buy_hold", "label": "SPY", "cycles": None, "ann_net": 11.0,
         "ratio_net_vol": 0.68, "sharpe_excess": None, "maxdd_net": -54.7, "source": "2026-09-06"},
    ],
}


def test_readme_block_carries_every_headline_number():
    text = R.readme_block(SYNTHETIC)
    for token in ("7.10 % neto", "0.75", "-17.8 %", "0.57", "1.76 %", "6.91", "0.56",
                  "5.5 %", "11.0 %", "1083 planes"):
        assert token in text, token


def test_spec_block_is_a_table_with_both_ratios_named():
    text = R.spec_block(SYNTHETIC)
    assert "| config | cycles | net %/yr | net/vol | Sharpe (excess) | maxDD % |" in text
    assert "**7.10**" in text and "**0.57**" in text
    assert "not a Sharpe ratio" in text
    assert "1.76 % annualised" in text


def test_a_missing_sharpe_renders_as_a_dash_not_as_zero():
    data = copy.deepcopy(SYNTHETIC)
    data["rows"][0]["sharpe_excess"] = None
    table = R.spec_block(data)
    assert "| **-** |" in table
    engine_line = [ln for ln in table.splitlines() if ln.startswith("| engine ")][0]
    assert "0.00" not in engine_line


def test_changing_a_number_changes_the_rendered_text():
    data = copy.deepcopy(SYNTHETIC)
    data["rows"][0]["ann_net"] = 9.99
    assert R.readme_block(data) != R.readme_block(SYNTHETIC)
    assert "9.99" in R.spec_block(data)


def test_a_row_that_does_not_exist_raises_instead_of_rendering_a_blank():
    data = copy.deepcopy(SYNTHETIC)
    data["reference"] = []
    with pytest.raises(KeyError, match="screener_v84"):
        R.readme_block(data)


def test_replace_block_only_touches_what_is_between_the_markers():
    text = f"before\n{R.BEGIN}\nold\n{R.END}\nafter\n"
    out = R.replace_block(text, "new", "test")
    assert out == f"before\n{R.BEGIN}\nnew\n{R.END}\nafter\n"
    assert R.current_block(out) == "new"


def test_a_document_without_markers_is_an_error_not_a_silent_no_op():
    with pytest.raises(ValueError, match="no EVIDENCE markers"):
        R.replace_block("nothing here", "new", "test")


def test_promote_refuses_an_in_sample_payload(tmp_path):
    p = tmp_path / "task347.json"
    p.write_text(json.dumps({"oos": False, "rows": [{}, {}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="in-sample"):
        R.promote(p, tmp_path / "out.json")


def test_promote_keeps_the_hand_curated_reference_rows(tmp_path):
    out = tmp_path / "canonical.json"
    out.write_text(json.dumps({"reference": SYNTHETIC["reference"]}), encoding="utf-8")
    scratch = tmp_path / "task350.json"
    scratch.write_text(json.dumps({
        "oos": True, "engine_first": "2005-02-11", "engine_last": "2026-08-24",
        "rows": [
            {"cycles": 1084, "ann_net": 6.91, "ratio_net_vol": 0.74, "sharpe_excess": 0.56,
             "maxdd_net": -19.5, "rf_ann_pct": 1.76, "ratio_minus_sharpe": 0.18},
            {"cycles": 1083, "ann_net": 7.10, "ratio_net_vol": 0.75, "sharpe_excess": 0.57,
             "maxdd_net": -17.8, "rf_ann_pct": 1.76, "ratio_minus_sharpe": 0.18},
        ],
    }), encoding="utf-8")
    data = R.promote(scratch, out)
    assert [r["key"] for r in data["rows"]] == ["engine", "lab_mix"]
    assert data["rows"][0]["ann_net"] == 7.10 and data["rows"][0]["sharpe_excess"] == 0.57
    assert [r["key"] for r in data["reference"]] == ["screener_v84", "spy_buy_hold"]
    assert data["panel"]["first_year"] == "2005"


def test_the_committed_documents_match_the_committed_canonical_file():
    """TASK-408's whole point: no hand-typed number survives in README.md or SPEC 9.5."""
    problems = R.check()
    assert problems == [], (
        "the published numbers drifted from evidence_canonical.json; "
        "run python render_evidence.py --write"
    )
