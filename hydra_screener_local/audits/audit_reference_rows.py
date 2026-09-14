"""EXTERNAL EVIDENCE AUDIT - the published reference rows, re-measured on the real OOS caches.

Moved out of `test_render_evidence.py` by HYDRA-CI-01. It is the one check a hand-typed baseline
cannot survive, and it is also the one that CANNOT be made portable: the numbers in
`evidence_canonical.json` are what `experiments/reference_rows.py` computes on the real
`_sweep_cache_oos/` and `_sweep_cache_etf/` marks. A synthetic panel would produce different
numbers, so a synthetic version of this test could only compare the script with itself.

What stays in the required suite instead: `test_every_published_row_is_internally_consistent_
without_any_cache`, which needs no data at all and catches a hand-typed Sharpe through the
`ratio_minus_sharpe = ratio_net_vol - sharpe_excess` identity and the shared `rf_ann_pct`. That is
a weaker check, and saying so is the point - it is not a substitute, it is what survives portably.

Run by `tools/external_audit.py`. No `pytest.skip` in this file.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import render_evidence as R  # noqa: E402

PUBLISHED = {"screener_v84": "screener v8.4 alone (T5, no ETF sleeve)",
             "spy_buy_hold": "SPY buy-and-hold"}
FIELDS = ("cycles", "ann_net", "ratio_net_vol", "sharpe_excess", "maxdd_net",
          "rf_ann_pct", "ratio_minus_sharpe")


def test_the_reference_rows_are_what_reference_rows_py_measures():
    """Type 0.60 for SPY's Sharpe, or restore the audit's -54.7 maxDD, and this fails.

    The numbers in `evidence_canonical.json` have to be the ones the script produces on the marks
    of the engine's own grid.
    """
    import reference_rows  # noqa: PLC0415

    measured = {row["config"]: row for row in reference_rows.measure()["rows"]}
    data = R.load()
    problems = []
    for key, config in PUBLISHED.items():
        assert config in measured, (
            f"reference_rows.measure() produced no row for {config!r}; it returned "
            f"{sorted(measured)}")
        row, got = R._row(data, key), measured[config]
        for field in FIELDS:
            if row[field] != got[field]:
                problems.append(f"{key}.{field}: published {row[field]!r}, measured {got[field]!r}")
    assert not problems, (
        "the published reference rows are not what the script measures on this disk:\n  "
        + "\n  ".join(problems))


def test_the_measurement_actually_produced_both_rows():
    """A `measure()` that quietly returned nothing would make the comparison above vacuous."""
    import reference_rows  # noqa: PLC0415

    rows = reference_rows.measure()["rows"]
    assert len(rows) >= len(PUBLISHED), f"measure() returned {len(rows)} row(s): {rows!r}"
    for row in rows:
        for field in FIELDS:
            assert field in row, f"measured row {row.get('config')!r} has no {field!r}"
