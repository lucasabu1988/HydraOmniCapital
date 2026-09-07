"""TASK-ASTRA-11 — the evidence report may not certify what nobody measured.

Ported from Astra's audit (§4 "Lo que la evidencia NO permite afirmar" and
TASK-ASTRA-11). Astra shipped no pytest probe for this finding — its probes live
in `test_adversarial.py` and none of the fifteen covers the reporting layer — so
the assertions here are its written specification, unweakened:

  * a report built from insufficient inputs REFUSES to print a capacity figure,
  * an excess-Sharpe row is never mislabelled,
  * the numbers Astra recomputed from the tracked cone are reproduced exactly
    (1084 steps, CAGR 6.9146%, raw ratio vs zero 0.7431, per-step sd 1.3569%,
    lag-1 autocorrelation -0.0958, and the four 90% CAGR intervals),
  * a p=0.009 inside a family of 15 is 0.135 family-wise, not 0.009.

No network, no state/, no data_cache/. Reads only `data/oos_cone_5050.json`,
which is tracked.
"""
import math
import os
import re
import sys

import numpy as np
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "experiments"))

import evidence_audit as EA  # noqa: E402

# Astra's recomputation from the tracked cone JSON (its measure_evidence.py).
ASTRA = dict(
    n=1084, cagr_pct=6.9146, raw_ratio=0.7431, step_sd_pct=1.3569, autocorr_lag1=-0.0958,
    intervals={1: (3.327, 10.551), 4: (3.597, 10.118), 13: (3.997, 9.794), 26: (4.224, 9.634)},
    mean_se_bp={1: 4.057, 4: 3.612, 13: 3.217, 26: 3.041},
    variance_equivalent_n_block13=1779.5,
    family_size=15, min_p=0.009, bonferroni=0.135,
    coverage_2005_pct=53.0,
)

FAST = dict(draws=200, blocks=(13,))


@pytest.fixture(scope="module")
def cone():
    return EA.load_cone()


@pytest.fixture(scope="module")
def report(cone):
    """The default report: no risk-free series, no fills, no panel snapshots."""
    return EA.build_report(cone, **FAST)


def _synthetic_rf(n, seed=3):
    """A T-bill-like step series: small, positive, no gaps. Aligned by construction."""
    rng = np.random.default_rng(seed)
    return np.abs(rng.normal(0.0004, 0.00005, n))


# --------------------------------------------------------------------------- #
# the two assertions the task names
# --------------------------------------------------------------------------- #
def test_capacity_refuses_a_figure_from_insufficient_inputs(report):
    """The headline: with no fills, no order sizes and no auction volume there is
    no "the edge dies at $X" — and the report prints no number at all."""
    row = report.row("edge_death_aum")
    assert not row.measured, row
    assert row.value is EA.NOT_MEASURED
    assert row.value_text().startswith("not measured"), row.value_text()

    missing = " ".join(row.missing).lower()
    for required in ("executed fills", "order sizes", "auction", "fees"):
        assert required in missing, (required, row.missing)

    # The estimator itself refuses; it does not fall back to a default.
    with pytest.raises(EA.InsufficientEvidence):
        EA.edge_death_aum(EA.CapacityInputs())

    # And the rendered capacity line carries no figure anywhere in it.
    line = row.rendered()
    assert "not measured" in line
    assert not re.search(r"\$\s*[\d,]+", line), line
    assert not re.search(r"\b\d+(?:[.,]\d+)*\s*(?:USD|M|bn)\b", line), line

    # Even with fills and order sizes, an uncalibrated impact model still refuses.
    partial = EA.CapacityInputs(executed_fills=30, order_sizes_usd=(2083.0, 568.0),
                                auction_volume_usd=(), arrival_and_decision_prices=30,
                                fees_usd=0.0)
    assert "auction" in " ".join(partial.missing()).lower()
    with pytest.raises(EA.InsufficientEvidence):
        EA.edge_death_aum(partial)
    full = EA.CapacityInputs(executed_fills=30, order_sizes_usd=(2083.0,),
                             auction_volume_usd=(1e6,), arrival_and_decision_prices=30,
                             fees_usd=0.0)
    assert full.sufficient
    # with every input present the ADV-only cost curve is still the blocker
    with pytest.raises(EA.InsufficientEvidence, match="(?i)responds to order size"):
        EA.edge_death_aum(full)
    # and even given a size-aware curve, no calibrated impact model exists here,
    # so the answer is still a refusal rather than an invented number
    size_aware = dict(EA.cost_model_size_sensitivity(), size_aware=True, spread_bp=7.0)
    with pytest.raises(EA.InsufficientEvidence, match="(?i)impact model"):
        EA.edge_death_aum(full, size_aware)
    assert not EA.capacity_rows(full, size_aware)[0].measured


def test_excess_sharpe_row_is_never_mislabelled(cone, report):
    """The raw ratio is not a Sharpe, and a Sharpe is not printed without a
    risk-free series. Neither row can borrow the other's label."""
    raw = report.row(EA.RAW_RATIO_KEY)
    excess = report.row(EA.EXCESS_SHARPE_KEY)
    assert raw.key != excess.key

    # 1. The raw ratio is labelled as what it is and says so about the Sharpe name.
    assert "not a sharpe ratio" in raw.label.lower(), raw.label
    assert "no risk-free subtraction" in raw.basis.lower(), raw.basis
    assert raw.value == pytest.approx(ASTRA["raw_ratio"], abs=5e-5)

    # 2. With no T-bill series tracked, the excess Sharpe is not measured — not 0,
    #    not the raw ratio, not None.
    assert not excess.measured, excess
    assert excess.value is EA.NOT_MEASURED
    assert excess.value != 0 and excess.value is not None
    assert "risk-free" in " ".join(excess.missing).lower(), excess.missing
    assert report.overclaims() == []

    # 3. Given an aligned risk-free series the Sharpe appears, is labelled excess,
    #    names its risk-free basis, and is strictly below the ratio over zero.
    rf = _synthetic_rf(cone["n"])
    with_rf = EA.build_report(cone, rf_step_returns=rf, **FAST)
    ex = with_rf.row(EA.EXCESS_SHARPE_KEY)
    assert ex.measured, ex
    assert "excess" in ex.label.lower()
    assert "risk-free" in ex.basis.lower() or "t-bill" in ex.basis.lower()
    assert ex.value < with_rf.row(EA.RAW_RATIO_KEY).value
    assert ex.value == pytest.approx(EA.excess_sharpe(cone["step_returns"], rf), abs=5e-5)
    assert with_rf.overclaims() == []

    # 4. Calling the raw ratio a Sharpe is caught, and blocks the whole report.
    bad = EA.Report("bad", "panel", sections=[("x", [
        EA.Row(EA.RAW_RATIO_KEY, "Sharpe (net)", 0.7431, basis="zero",
               provenance="recomputed here")])])
    assert any("labelled as a Sharpe" in v for v in bad.overclaims()), bad.overclaims()
    with pytest.raises(EA.MislabelledEvidence):
        EA.render(bad)

    # 5. A Sharpe published without naming its risk-free series is caught too.
    nameless = EA.Report("bad", "panel", sections=[("x", [
        EA.Row(EA.EXCESS_SHARPE_KEY, "excess Sharpe", 0.5, basis="net returns",
               provenance="recomputed here")])])
    assert any("without naming the risk-free series" in v for v in nameless.overclaims())
    with pytest.raises(EA.MislabelledEvidence):
        EA.render(nameless)

    # 6. And an unmeasured excess Sharpe that hides what is absent is caught.
    silent = EA.Report("bad", "panel", sections=[("x", [
        EA.Row(EA.EXCESS_SHARPE_KEY, "excess Sharpe over the risk-free series",
               EA.NOT_MEASURED, basis="aligned risk-free return")])])
    assert any("does not say what is absent" in v for v in silent.overclaims())


# --------------------------------------------------------------------------- #
# the null is explicit, never a default
# --------------------------------------------------------------------------- #
def test_not_measured_is_a_sentinel_and_not_a_number():
    n = EA.NOT_MEASURED
    assert n is EA._NotMeasured()          # singleton
    assert not n                           # falsy
    assert str(n) == "not measured"
    assert not EA.is_measured(n)
    assert not EA.is_measured(None)
    assert not EA.is_measured(float("nan"))
    assert EA.is_measured(0.0)             # a measured zero IS a number
    with pytest.raises(TypeError):
        float(n)
    with pytest.raises(TypeError):
        f"{n:.2f}"
    with pytest.raises(TypeError):
        f"{n:.1%}"


def test_a_missing_number_renders_as_not_measured_never_as_zero(report):
    text = EA.render(report)
    assert "not measured" in text
    assert "## Not measured" in text
    unmeasured = report.unmeasured_keys()
    assert unmeasured, "the default report has nulls; if not, the nulls were defaulted away"
    for key in unmeasured:
        row = report.row(key)
        assert row.value is EA.NOT_MEASURED
        assert "not measured" in row.rendered()
        assert not re.search(r":\s*-?\d", row.rendered().split("basis:")[0]), row.rendered()
    # a None value is itself an overclaim: nulls must be explicit
    noney = EA.Report("bad", "p", sections=[("x", [EA.Row("k", "label", None)])])
    assert any("value is None" in v for v in noney.overclaims())


# --------------------------------------------------------------------------- #
# family-wise significance
# --------------------------------------------------------------------------- #
def test_family_wise_p_replaces_the_per_comparison_p(report):
    assert len(EA.DEEP_DIVE_FAMILY) == ASTRA["family_size"]
    assert report.row("family_deep_dive_size").value == ASTRA["family_size"]
    assert report.row("family_deep_dive_min_p").value == pytest.approx(ASTRA["min_p"])
    fwer = report.row("family_deep_dive_fwer_p")
    assert fwer.value == pytest.approx(ASTRA["bonferroni"], abs=1e-9)
    assert "NOT family-wise significant" in fwer.note
    assert report.row("family_deep_dive_holm_p").value == pytest.approx(ASTRA["bonferroni"], abs=1e-9)

    s = report.families[0]
    assert s["any_significant_5pct"] is False
    # the second-smallest raw p (0.024) also does not survive the family
    holm = {t["trial"]: t["p_holm"] for t in s["trials"]}
    assert holm["additive score (sign-safe)"] == pytest.approx(0.336, abs=1e-9)

    # a differently sized family gives a different number, and families are declared,
    # never summed: 38 trials at p=0.009 is 0.342 only when 38 are declared.
    big = EA.family_summary([(f"t{i}", 0.009 if i == 0 else 0.9) for i in range(38)], "big", "synthetic")
    assert big["bonferroni_min_p"] == pytest.approx(0.342, abs=1e-9)
    assert {s["family"] for s in report.families} == {"deep_dive"}

    # Holm is monotone and never below the Bonferroni-of-the-minimum
    ps = [p for _, p in EA.DEEP_DIVE_FAMILY]
    adj = EA.holm_adjusted(ps)
    assert min(adj) == pytest.approx(min(1.0, len(ps) * min(ps)))
    assert all(a >= p for a, p in zip(adj, ps, strict=True))
    with pytest.raises(EA.InsufficientEvidence):
        EA.holm_adjusted([])


# --------------------------------------------------------------------------- #
# N of weeks vs variance-equivalent N
# --------------------------------------------------------------------------- #
def test_observed_steps_and_variance_equivalent_n_are_separate_rows(cone):
    rep = EA.build_report(cone, draws=5000, blocks=(1, 4, 13, 26))
    steps = rep.row("n_steps")
    equiv = rep.row("variance_equivalent_n_block13")
    assert steps.key != equiv.key
    assert steps.value == ASTRA["n"]
    assert "actually observed" in steps.label
    assert equiv.value == pytest.approx(ASTRA["variance_equivalent_n_block13"], abs=0.1)
    assert equiv.value > steps.value  # negative autocorrelation, so it exceeds the step count
    assert "variance-equivalent" in equiv.label.lower()
    assert "NOT new weeks" in equiv.note
    assert "drawdown" in equiv.note and "selection" in equiv.note
    assert "mean" in equiv.basis.lower()

    # relabelling the variance-equivalent N as weeks is refused
    liar = EA.Report("bad", "p", sections=[("x", [
        EA.Row("variance_equivalent_n_block13", "N of weeks observed", 1779.5,
               provenance="recomputed here")])])
    assert any("not labelled as such" in v for v in liar.overclaims())
    with pytest.raises(EA.MislabelledEvidence):
        EA.render(liar)


# --------------------------------------------------------------------------- #
# the reused numbers agree with the tracked JSON
# --------------------------------------------------------------------------- #
def test_cone_numbers_reproduce_astras_recomputation(cone):
    x = cone["step_returns"]
    assert cone["n"] == ASTRA["n"]
    assert cone["first"] == "2005-02-11" and cone["last"] == "2026-08-24"
    cagr = 100.0 * (math.exp(float(np.log1p(x).sum()) * EA.STEPS_PER_YEAR / x.size) - 1.0)
    assert cagr == pytest.approx(ASTRA["cagr_pct"], abs=5e-4)
    assert float(x.std(ddof=1)) * 100 == pytest.approx(ASTRA["step_sd_pct"], abs=5e-4)
    assert EA.raw_ratio_over_zero(x) == pytest.approx(ASTRA["raw_ratio"], abs=5e-5)
    import pandas as pd
    assert float(pd.Series(x).autocorr(1)) == pytest.approx(ASTRA["autocorr_lag1"], abs=5e-5)

    for block, (p05, p95) in ASTRA["intervals"].items():
        s = EA.resample_summary(x, block, draws=5000, seed=0)
        assert s["cagr_p05"] == pytest.approx(p05, abs=1e-3), (block, s)
        assert s["cagr_p95"] == pytest.approx(p95, abs=1e-3), (block, s)
        assert s["mean_se_bp"] == pytest.approx(ASTRA["mean_se_bp"][block], abs=1e-3), (block, s)


# --------------------------------------------------------------------------- #
# DSR vs the hardcoded haircut
# --------------------------------------------------------------------------- #
def test_dsr_needs_the_trialled_sharpe_dispersion(cone, report):
    dsr = report.row("dsr")
    assert not dsr.measured, dsr
    missing = " ".join(dsr.missing).lower()
    assert "trialled sharpe" in missing and "trials actually run" in missing
    assert "N_TRIALS=38" in dsr.note and "rho=0.7" in dsr.note

    # PSR against zero IS measurable: skew and kurtosis exist here.
    psr = report.row("psr_vs_zero")
    assert psr.measured and 0.0 < psr.value < 1.0
    assert report.row("skew").value < 0
    assert report.row("excess_kurtosis").value > 0

    # Supply the two inputs and the real DSR appears, and it is a haircut: with a
    # trial family it must be no larger than the PSR against zero.
    x = cone["step_returns"]
    sr_step = float(x.mean() / x.std(ddof=1))
    real = EA.deflated_sharpe(sr_step, x.size, report.row("skew").value,
                              report.row("excess_kurtosis").value,
                              trial_sr_sd_per_step=0.05, n_trials=38)
    assert 0.0 <= real <= psr.value
    with_inputs = EA.build_report(cone, trial_sr_sd_per_step=0.05, n_trials=38, **FAST)
    assert with_inputs.row("dsr").measured
    assert with_inputs.row("dsr").value == pytest.approx(real, abs=1e-4)

    # A hardcoded constant is not an input: zero dispersion or one trial still refuses.
    for kwargs in ({"trial_sr_sd_per_step": 0.0, "n_trials": 38},
                   {"trial_sr_sd_per_step": 0.05, "n_trials": 1},
                   {"trial_sr_sd_per_step": None, "n_trials": None}):
        with pytest.raises(EA.InsufficientEvidence):
            EA.deflated_sharpe(sr_step, x.size, -1.0, 4.8, **kwargs)


# --------------------------------------------------------------------------- #
# coverage per era, cost model, participation
# --------------------------------------------------------------------------- #
def test_price_coverage_shows_2005_and_interpolates_nothing(report):
    c2005 = report.row("coverage_2005")
    assert c2005.measured and c2005.value == pytest.approx(ASTRA["coverage_2005_pct"])
    assert "survivorship-free" in c2005.note
    assert "documented" in c2005.provenance
    for era in ("2008", "2011", "2014", "2017", "2020", "2026"):
        row = report.row(f"coverage_{era}")
        assert not row.measured, (era, row)
        assert "not interpolated" in row.note
    assert report.row("coverage_2023").value == pytest.approx(95.0)

    # a measured era overrides the documented value and says it was recomputed
    measured = EA.coverage_rows({"2011": 71.4})
    row = [r for r in measured if r.key == "coverage_2011"][0]
    assert row.measured and row.value == pytest.approx(71.4)
    assert "recomputed here" in row.provenance


def test_cost_curve_does_not_respond_to_order_size(report):
    s = EA.cost_model_size_sensitivity()
    assert s["spread_bp"] == 0.0
    assert s["size_aware"] is False
    assert set(s["inputs_absent"]) == {"order size", "AUM", "observed spread", "auction participation"}
    assert report.row("cost_size_sensitivity_bp").value == 0.0
    assert "cannot price impact" in report.row("cost_size_sensitivity_bp").note
    assert report.row("cost_bp_at_5m_adv").value == pytest.approx(20.0)
    assert "before taxes" in report.row("cost_basis_taxes").note.lower()


def test_participation_rows_are_labelled_hypothesis(report):
    row = report.row("participation_aum100000_n6")
    assert row.label.lower().startswith("hypothesis")
    assert row.value == pytest.approx(2083.0, abs=1.0)          # 100k x 0.125 / 6
    assert report.row("participation_aum100000_n22").value == pytest.approx(568.0, abs=1.0)
    assert report.row("participation_aum10000000_n6").value == pytest.approx(208333.0, abs=1.0)
    assert "not measured slippage" in row.note
    # the tranche fraction comes from config, it is not a literal in the report
    from config import V9
    assert f"{V9['mix']['stocks'] / V9['tranches']:g}" in row.basis

    naked = EA.Report("bad", "p", sections=[("x", [
        EA.Row("participation_aum1_n1", "order per name", 100.0, provenance="scenario")])])
    assert any("without the HYPOTHESIS label" in v for v in naked.overclaims())


# --------------------------------------------------------------------------- #
# regression guard: every overclaim shape blocks the render
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("row,fragment", [
    (EA.Row("edge_death_aum", "AUM at which the modelled edge dies", 2_500_000.0,
            unit="USD", provenance="scenario"), "capacity figure is published"),
    (EA.Row(EA.RAW_RATIO_KEY, "Sharpe ratio (net)", 0.74, basis="zero",
            provenance="recomputed here"), "labelled as a Sharpe"),
    (EA.Row(EA.RAW_RATIO_KEY, "net return / own sd (NOT a Sharpe ratio)", 0.74,
            basis="net returns", provenance="recomputed here"), "measured against zero"),
    (EA.Row(EA.EXCESS_SHARPE_KEY, "Sharpe", 0.6, basis="aligned risk-free return",
            provenance="recomputed here"), "not labelled as excess"),
    (EA.Row("variance_equivalent_n_block13", "effective sample size", 1779.5,
            provenance="recomputed here"), "not labelled as such"),
    (EA.Row("participation_aum1_n1", "order per name", 100.0,
            provenance="scenario"), "without the HYPOTHESIS label"),
    (EA.Row("cagr_net", "net CAGR", 6.91, unit="%"), "without provenance"),
    (EA.Row("anything", "a label", None), "value is None"),
])
def test_render_refuses_each_overclaim_shape(row, fragment):
    rep = EA.Report("t", "p", sections=[("section", [row])])
    violations = rep.overclaims()
    assert any(fragment in v for v in violations), (fragment, violations)
    with pytest.raises(EA.MislabelledEvidence):
        EA.render(rep)


def test_the_default_report_renders_and_declares_its_source(report):
    assert report.overclaims() == []
    text = EA.render(report)
    assert "oos_cone_5050.json" in text
    assert report.meta["cone_sha256"][:16] in text
    assert "before taxes" in text.lower()
    assert "GROKBOARD rule 6" in text
    # the family table and the not-measured list both appear
    assert "| trial | p raw | p Holm |" in text
    assert "edge_death_aum" in text.split("## Not measured")[1]
    d = report.as_dict()
    assert d["overclaims"] == []
    assert d["sections"][1]["rows"][1]["value"] is None      # excess Sharpe: null, explicit
    assert d["sections"][1]["rows"][1]["measured"] is False


def test_cli_writes_a_report_without_touching_state(tmp_path):
    out = tmp_path / "evidence-audit.md"
    js = tmp_path / "evidence-audit.json"
    rc = EA.main(["--draws", "200", "--seed", "0", "--out", str(out), "--json", str(js)])
    assert rc == 0 and out.exists() and js.exists()
    body = out.read_text(encoding="utf-8")
    assert "not measured" in body
    assert "AUM at which the modelled edge dies: not measured" in body
    import json
    blob = json.loads(js.read_text(encoding="utf-8"))
    assert blob["overclaims"] == []
    assert "edge_death_aum" in blob["unmeasured"]
    assert "excess_sharpe" in blob["unmeasured"]
    # nothing under state/ or data_cache/ was created
    assert not (tmp_path / "state").exists()


if __name__ == "__main__":
    raise SystemExit(pytest.main([os.path.abspath(__file__), "-q"]))
