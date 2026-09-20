"""EXTERNAL EVIDENCE AUDIT - the TASK-438 impact overlay, against the artefacts on this disk.

Not a unit test: `experiments/test_impact.py` proves the rules on synthetic data and is REQUIRED on
every clone. This file applies them to the REAL report `tools/external_audit.py` names through
`HYDRA_434_RUN_ID` (438 drives nothing - its report is keyed by the 434 run it overlays). Run by
`tools/external_audit.py`; there is no `pytest.skip` here.

Claims, in the pre-registration's words (`.comms/prereg-task-438-impact-2026-09-14.md`):
  * G1 - the overlay was computed on the F1-proved 434 sidecars: the report's recorded sidecar
    shas equal `capacity_drive.json`'s and the bytes on disk;
  * the close panels used are the 433-recorded `data:price_close` blocks, by sha;
  * the report is what the rules produce: recomputing one panel end to end reproduces the fixed
    rows and the crossings;
  * `eff_bp_side` is monotone in capital (sqrt is monotone - a violation is a bug) on every curve;
  * `IMPACT_MODELLED_NOT_MEASURED` is on the payload and on every crossing; the grid ends at 100 M;
    k band and sigma window are the pre-registered ones.
"""
import hashlib
import json
import os
import sys

import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import capacity as C  # noqa: E402
import impact as I  # noqa: E402
import impact_report as IR  # noqa: E402
import provenance as PV  # noqa: E402

pytestmark = pytest.mark.timeout(1800)


def resolve_run() -> str:
    run_id = os.environ.get("HYDRA_434_RUN_ID")
    assert run_id, "the runner must name the 434 run (HYDRA_434_RUN_ID); this audit does not guess"
    return run_id


def _run_dir():
    return os.path.join(ROOT, "experiments", "_lab_scratch", "capacity", "runs", resolve_run())


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _report():
    path = os.path.join(ROOT, "experiments", "_lab_scratch", f"task438_impact_{resolve_run()}.json")
    assert os.path.exists(path), f"no report at {path}"
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _summary():
    with open(os.path.join(_run_dir(), "capacity_drive.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ----------------------------------------------------------------------------------------------
def test_g1_the_overlay_sits_on_the_f1_proved_sidecars():
    rep, summary = _report(), _summary()
    assert rep["run_434"] == resolve_run() and rep["run_433"] == IR.ACCREDITED_433
    for panel, pay in rep["panels"].items():
        rec = summary["drives"][panel]["sidecar"]
        assert pay["gate"]["sidecar_sha256"] == rec["sha256"], f"{panel}: report used a different sidecar"
        assert _sha(os.path.join(ROOT, rec["path"])) == rec["sha256"], f"{panel}: sidecar bytes moved"
        with open(os.path.join(_run_dir(), f"{panel}_base.F1.json"), encoding="utf-8") as fh:
            f1 = json.load(fh)
        assert f1["passed"] is True and f1["book_sha256"] == pay["gate"]["f1_book_sha256"]


def test_the_close_panels_are_the_433_recorded_data_blocks():
    rep = _report()
    for panel, pay in rep["panels"].items():
        man = PV.read_manifest(os.path.join(IR.ACC_433, f"{panel}_base.pkl"))
        stored = ((man or {}).get("data") or {}).get("price_close", {}).get("sha256")
        assert stored, f"{panel}: the 433 manifest records no price_close digest"
        assert pay["close_panel"]["sha256"] == stored == _sha(os.path.join(ROOT, pay["close_panel"]["path"])), (
            f"{panel}: close.pkl is not the 433-recorded data block")
        assert pay["close_panel"]["matches_433_data_block"] is True
    etf = rep["inputs"]["etf_close"]
    assert _sha(os.path.join(ROOT, etf["path"])) == etf["sha256"]


def test_the_impact_report_is_what_the_rules_produce():
    """One panel recomputed end to end from the sealed artefacts: fixed rows and k=1 crossings."""
    rep, summary = _report(), _summary()
    panel = "russell" if "russell" in rep["panels"] else next(iter(rep["panels"]))
    pub = rep["panels"][panel]
    fills = pd.read_pickle(os.path.join(_run_dir(), f"{panel}_base.fills.pkl"))
    adv = pd.read_pickle(os.path.join(ROOT, summary["adv"][panel]["path"]))
    adv_etf = pd.read_pickle(os.path.join(ROOT, summary["adv"]["etf"]["path"]))
    close = pd.read_pickle(os.path.join(ROOT, pub["close_panel"]["path"]))
    etf_close = pd.read_pickle(os.path.join(ROOT, rep["inputs"]["etf_close"]["path"]))
    f = I.fills_with_footprints(fills, {"stocks": adv, "etf": adv_etf},
                                {"stocks": I.sigma_panel(close), "etf": I.sigma_panel(etf_close)})
    for row in pub["fixed"]:
        mine = I.effective_bp(f, row["capital"], row["k"])
        for name in ("total", "stocks", "etf"):
            assert abs(mine[name]["eff_bp_side"] - row[name]["eff_bp_side"]) < 1e-9, (panel, row["capital"], row["k"], name)
            assert mine[name]["n_known"] == row[name]["n_known"]
    mine_x = I.crossings(I.curve(f, C.aum_grid(), I.K_HEADLINE))
    for rung, per in pub["crossings"]["1.0"].items():
        for sleeve, v in per.items():
            assert mine_x[rung][sleeve]["capital_reaching_rung"] == v["capital_reaching_rung"], (rung, sleeve)


def test_eff_bp_is_monotone_in_capital_on_every_curve_and_the_grid_ends_at_100M():
    rep = _report()
    for panel, pay in rep["panels"].items():
        for k, rows in pay["curves"].items():
            caps = [r["capital"] for r in rows]
            assert caps == sorted(caps) and caps[0] == 10_000.0 and caps[-1] == 100_000_000.0, (panel, k)
            assert rows, (panel, k)
            for name in ("total", "stocks", "etf"):
                effs = [r[name]["eff_bp_side"] for r in rows if r[name]["measurable"]]
                assert effs == sorted(effs), f"{panel} k={k} {name}: eff_bp not monotone in capital"


def test_the_label_the_band_and_the_window_are_the_pre_registered_ones():
    rep = _report()
    assert rep["label"] == I.LABEL == "IMPACT_MODELLED_NOT_MEASURED"
    for pay in rep["panels"].values():
        assert pay["label"] == I.LABEL and pay["k_headline"] == 1.0 and pay["k_band"] == [0.5, 1.0, 1.5]
        assert pay["sigma_window"] == 63 and pay["sigma_window_sensitivity"]["window"] == 21
        for per_rung in pay["crossings"].values():
            for rung, per_sleeve in per_rung.items():
                for sleeve, v in per_sleeve.items():
                    assert v["label"] == I.LABEL
                    assert v["rung_bp_side"] == I.RUNGS_BP[rung][sleeve] and v["base_bp_side"] == I.BASE_BP[sleeve]
