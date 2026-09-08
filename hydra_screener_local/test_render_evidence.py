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
        {"key": "screener_v84", "label": "v8.4", "cycles": 1084, "ann_net": 5.48,
         "ratio_net_vol": 0.42, "sharpe_excess": 0.31, "maxdd_net": -37.8,
         "rf_ann_pct": 1.76, "ratio_minus_sharpe": 0.11, "source": "2026-09-06"},
        {"key": "spy_buy_hold", "label": "SPY", "cycles": 1084, "ann_net": 10.99,
         "ratio_net_vol": 0.69, "sharpe_excess": 0.59, "maxdd_net": -52.5,
         "rf_ann_pct": 1.76, "ratio_minus_sharpe": 0.1, "source": "2026-09-06"},
    ],
}

REFERENCE_KEYS = ("screener_v84", "spy_buy_hold")
CACHES = (
    os.path.join(ROOT, "experiments", "_sweep_cache_etf", "audit_steps.pkl"),
    os.path.join(ROOT, "experiments", "_sweep_cache_oos", "spy.pkl"),
    os.path.join(ROOT, "experiments", "_sweep_cache_oos", "irx.pkl"),
)


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


def test_the_reference_rows_are_in_the_spec_table_and_named_as_baselines():
    """They used to be quoted only in prose: a reader could not see them next to the engine."""
    table = R.spec_block(SYNTHETIC)
    v84 = [ln for ln in table.splitlines() if ln.endswith("| -37.8 |")]
    spy = [ln for ln in table.splitlines() if ln.endswith("| -52.5 |")]
    assert len(v84) == 1 and len(spy) == 1, table
    for line in v84 + spy:
        assert "baseline" in line and "2026-09-06 audit" in line
        assert "**" not in line, "a baseline must not be bolded like the engine's own row"
    assert "0.31" in v84[0] and "0.59" in spy[0]
    assert "COMPARISON BASELINES, not the engine" in table


def test_the_published_reference_rows_carry_a_sharpe_and_a_risk_free_level():
    """A reference Sharpe dropped back to null renders a dash - and this goes red."""
    data = R.load()
    for key in REFERENCE_KEYS:
        row = R._row(data, key)
        for field in ("sharpe_excess", "rf_ann_pct", "ratio_net_vol", "cycles"):
            assert isinstance(row[field], (int, float)), f"{key}.{field} is {row[field]!r}"
    readme = R.readme_block(data)
    assert "sin recomputar" not in readme, "the two baselines are re-measured; drop the asterisk"
    assert "recomputadas el" in readme
    for key in REFERENCE_KEYS:
        assert f"{R._row(data, key)['sharpe_excess']:.2f}" in readme


@pytest.mark.skipif(not all(os.path.exists(p) for p in CACHES),
                    reason="the sweep caches are gitignored; a fresh clone cannot re-measure")
def test_the_reference_rows_are_what_reference_rows_py_measures():
    """The one test a hand-typed baseline cannot survive: re-measure and compare.

    Type 0.60 for SPY's Sharpe, or restore the audit's -54.7 maxDD, and this fails - the numbers
    in evidence_canonical.json have to be the ones the script produces on the marks of the
    engine's own grid. Skips only where the (gitignored) OOS caches are absent.
    """
    sys.path.insert(0, os.path.join(ROOT, "experiments"))
    import reference_rows  # noqa: PLC0415

    measured = {row["config"]: row for row in reference_rows.measure()["rows"]}
    published = {"screener_v84": "screener v8.4 alone (T5, no ETF sleeve)",
                 "spy_buy_hold": "SPY buy-and-hold"}
    data = R.load()
    for key, config in published.items():
        row, got = R._row(data, key), measured[config]
        for field in ("cycles", "ann_net", "ratio_net_vol", "sharpe_excess", "maxdd_net",
                      "rf_ann_pct", "ratio_minus_sharpe"):
            assert row[field] == got[field], f"{key}.{field}: published {row[field]}, measured {got[field]}"


def test_the_committed_documents_match_the_committed_canonical_file():
    """TASK-408's whole point: no hand-typed number survives in README.md or SPEC 9.5."""
    problems = R.check()
    assert problems == [], (
        "the published numbers drifted from evidence_canonical.json; "
        "run python render_evidence.py --write"
    )


def test_every_published_row_is_internally_consistent_without_any_cache():
    """The hand-typed guard that does NOT skip in CI.

    `test_the_reference_rows_are_what_reference_rows_py_measures` is the strong check, but it is
    gated on the gitignored sweep caches, so in CI and on a fresh clone it skips - and
    run_all_tests.py reports the file as [PASS] with 0 skipped, which is exactly the "a skip is
    not a pass" trap this project keeps falling into (found by the TASK-413 falsifiability
    review, where 4 of 4 hand-typed mutations stayed green with that one test deselected).

    This one needs no data at all: `ratio_minus_sharpe` is by definition
    `ratio_net_vol - sharpe_excess`, and every row was measured against the same T-bill series, so
    they must share `rf_ann_pct`. Type a Sharpe by hand and the identity breaks.
    """
    data = R.load()
    rows = data["rows"] + data["reference"]
    rf_levels = {r["key"]: r["rf_ann_pct"] for r in rows}
    assert len(set(rf_levels.values())) == 1, (
        f"rows measured against different risk-free levels: {rf_levels}"
    )
    for r in rows:
        for field in ("ann_net", "ratio_net_vol", "sharpe_excess", "maxdd_net", "rf_ann_pct",
                      "ratio_minus_sharpe", "cycles"):
            assert isinstance(r[field], (int, float)), f"{r['key']}.{field} is {r[field]!r}"
        implied = round(r["ratio_net_vol"] - r["sharpe_excess"], 2)
        # exact at 2 dp on purpose: every field is published rounded to 2 dp, so a one-tick
        # hand edit (0.59 -> 0.60) has to break this. A 0.011 tolerance let exactly that through.
        assert abs(implied - r["ratio_minus_sharpe"]) < 0.005, (
            f"{r['key']}: ratio {r['ratio_net_vol']} - sharpe {r['sharpe_excess']} = {implied}, "
            f"but the row says {r['ratio_minus_sharpe']} - one of the three was typed by hand"
        )
        assert r["sharpe_excess"] < r["ratio_net_vol"], (
            f"{r['key']}: a positive risk-free rate must make the Sharpe the LOWER of the two"
        )


def test_the_baselines_publish_their_own_measurement_date_not_the_engines():
    """`promote()` re-dates `measured_at` on every engine run and carries the reference rows over
    verbatim. Rendering the baselines from that global date published "re-measured on <today>"
    for rows nobody re-measured - green suite, false claim (TASK-413 review). So each baseline
    carries its own date and the prose renders from that."""
    data = R.load()
    for key in REFERENCE_KEYS:
        assert R._row(data, key)["measured_at"] == "2026-09-08"
    moved = copy.deepcopy(data)
    moved["measured_at"] = "2027-01-01"                  # a later engine promote
    text = R.readme_block(moved) + R.spec_block(moved)
    assert "2027-01-01" not in text.split("Estas cifras se generan")[0], (
        "the baselines' 'recomputadas el' date followed the engine's promote date again"
    )
    assert "2026-09-08" in text
