"""EXTERNAL EVIDENCE AUDIT - the TASK-434 capacity run, against the artefacts on this disk.

Not a unit test: `experiments/test_capacity*.py` prove the rules on synthetic data and are REQUIRED
on every clone. This file applies them to the REAL run `tools/external_audit.py` pins
(`HYDRA_434_RUN_ID`), which lives in the gitignored `_lab_scratch/capacity/runs/<run_id>/`.
Run by `tools/external_audit.py`; there is no `pytest.skip` here.

What it claims, in the pre-registration's words (`.comms/prereg-task-434-2026-09-14.md`):

  * F1 - the sidecar drive IS the accredited drive: the F1 record says so and its `book_sha256`
    is the TASK-433 accredited base book's; the sealed 434 book carries that same seal.
  * the sidecar is the ledger disaggregated: per-settle, per-sleeve fill sums equal the drive's own
    `ledger.by_step`, and its file digest is the one `capacity_drive.json` recorded;
  * the ADV panels on disk are the ones recorded (sha256), built from the recorded inputs;
  * the published report is what the rules produce: recomputing the ceiling and coverage from the
    sidecar and the ADV panels reproduces the JSON;
  * the P95 curve is monotone in capital; `CAPACITY_NOT_CERTIFIED` is on the payload, the ceiling
    and every table row;
  * the code the two books recorded still matches - the pinned commit's blobs once the run is
    closed (`HYDRA_434_CODE_REF`), the disk while it is open.
"""
import hashlib
import json
import os
import subprocess
import sys

import pandas as pd
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import capacity as C  # noqa: E402
import capacity_report as CR  # noqa: E402
import provenance as PV  # noqa: E402

pytestmark = pytest.mark.timeout(1800)      # the ADV panels are 264 MB; not a 30 s job

#: The TASK-433 accredited base books, BOTH panels - the independent reference F1 answers to.
#: Review of #97: the first version listed Russell only, so the S&P F1 was checked against
#: 434's own record and nothing else. Cross-checked below against the 433 manifests themselves.
ACCREDITED_433_RUN = "20260914-cae2c54599aa"
ACCREDITED_433_BASE_SHA = {
    "russell": "12e478f9752e51902ec268fd499cefc28dd7bb62c50ef37d6c77afb273fe83da",
    "sp500": "de56c7fbd62276b764811e384c693902d7f0339e0f5d9dc2fabd1430f3bcc9a5",
}
PANELS = ("russell", "sp500")


def resolve_run() -> str:
    run_id = os.environ.get("HYDRA_434_RUN_ID")
    assert run_id, "the runner must name the run (HYDRA_434_RUN_ID); this audit does not guess"
    return run_id


def _dir():
    return os.path.join(ROOT, "experiments", "_lab_scratch", "capacity", "runs", resolve_run())


def _load(name):
    with open(os.path.join(_dir(), name), encoding="utf-8") as fh:
        return json.load(fh)


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _report():
    path = os.path.join(ROOT, "experiments", "_lab_scratch", f"task434_capacity_{resolve_run()}.json")
    assert os.path.exists(path), f"no report at {path}"
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _panels_present():
    return [p for p in PANELS if os.path.exists(os.path.join(_dir(), f"{p}_base.F1.json"))]


# ----------------------------------------------------------------------------------------------
def test_f1_passed_and_the_book_is_the_accredited_book():
    for panel in _panels_present():
        f1 = _load(f"{panel}_base.F1.json")
        assert f1["passed"] is True and f1["problems"] == [], f"{panel}: F1 {f1['problems']}"
        assert f1["n_marks"] == 814
        assert panel in ACCREDITED_433_BASE_SHA, f"{panel}: no accredited reference declared"
        assert f1["book_sha256"] == ACCREDITED_433_BASE_SHA[panel], f"{panel}: not the accredited book"
        acc = os.path.join(ROOT, "experiments", "_lab_scratch", "accredited", "runs", ACCREDITED_433_RUN, f"{panel}_base.pkl")
        acc_man = PV.read_manifest(acc)
        assert acc_man and acc_man["result"]["sha256"] == ACCREDITED_433_BASE_SHA[panel], (
            f"{panel}: the declared reference is not what the 433 manifest says")
        book_path = os.path.join(_dir(), f"{panel}_base.pkl")
        man = PV.read_manifest(book_path)
        assert man and man["result"]["sha256"] == f1["book_sha256"], f"{panel}: the sealed book is not the F1 book"
        assert PV.book_sha256(pd.read_pickle(book_path)) == f1["book_sha256"]


def test_the_sidecar_is_the_ledger_disaggregated_and_its_digest_is_the_recorded_one():
    summary = _load("capacity_drive.json")
    for panel in _panels_present():
        fills_path = os.path.join(_dir(), f"{panel}_base.fills.pkl")
        assert _sha(fills_path) == summary["drives"][panel]["sidecar"]["sha256"], f"{panel}: sidecar bytes moved"
        fills = pd.read_pickle(fills_path)
        eng = _load(f"{panel}_base.engine.json")
        by_step = eng["ledger"]["by_step"]
        mine = fills.groupby([fills["exec_date"].dt.strftime("%Y-%m-%d"), "sleeve"])["dollars"].sum()
        theirs = {(d, s): rec["filled_dollars"] for d, sl in by_step.items() for s, rec in sl.items()
                  if rec["filled_dollars"] > 0}
        assert set(mine.index) == set(theirs), f"{panel}: settles/sleeves differ between sidecar and ledger"
        worst = max(abs(mine[k] - v) for k, v in theirs.items())
        assert worst <= 1e-9, f"{panel}: sidecar vs ledger max |diff| {worst}"


def test_the_adv_panels_are_the_recorded_ones_built_from_the_recorded_inputs():
    summary = _load("capacity_drive.json")
    assert "etf" in summary["adv"], "the ETF sleeve's ADV must be sealed in the run like the stock panels'"
    for panel in list(_panels_present()) + ["etf"]:
        rec = summary["adv"][panel]
        path = os.path.join(ROOT, rec["path"])
        assert _sha(path) == rec["sha256"], f"{panel}: adv panel bytes moved"
        for name, inp in rec["inputs"].items():
            assert _sha(os.path.join(ROOT, inp["path"])) == inp["sha256"], f"{panel}: input {name} moved"
        assert rec["window"] == C.ADV_WINDOW == 20


def test_the_report_is_what_the_rules_produce():
    rep = _report()
    etf_adv = None
    if rep["etf_adv"]["available"]:
        # the SEALED panel in the run dir, checked against the sha the report says it used -
        # never the mutable cache files (review of #97)
        etf_path = os.path.join(ROOT, rep["etf_adv"]["path"])
        assert _sha(etf_path) == rep["etf_adv"]["sha256"], "adv_usd_etf.pkl is not the one the report used"
        etf_adv = pd.read_pickle(etf_path)
    for panel in _panels_present():
        pub = rep["panels"][panel]
        fills = pd.read_pickle(os.path.join(_dir(), f"{panel}_base.fills.pkl"))
        adv = pd.read_pickle(os.path.join(_dir(), f"adv_usd_{panel}.pkl"))
        fa = CR.attach_adv_by_sleeve(C.footprints(fills), {"stocks": adv, "etf": etf_adv})
        ce = C.aum_ceiling(fa)
        assert ce["status"] == pub["ceiling"]["status"], panel
        assert ce["ceiling_usd"] == pub["ceiling"]["ceiling_usd"], panel
        assert ce["coverage"]["footprints_known"] == pub["ceiling"]["coverage"]["footprints_known"], panel
        assert abs(ce["coverage"]["notional_covered_share"] - pub["ceiling"]["coverage"]["notional_covered_share"]) < 1e-12


def test_the_p95_curve_is_monotone_and_the_label_is_everywhere():
    rep = _report()
    assert rep["label"] == C.LABEL
    for panel in _panels_present():
        pub = rep["panels"][panel]
        assert pub["label"] == C.LABEL and pub["ceiling"]["label"] == C.LABEL
        assert all(r["label"] == C.LABEL for r in pub["table"])
        curve = [r["p95_conservative"] for r in pub["ceiling"]["curve"]]
        assert curve == sorted(curve), f"{panel}: P95 not monotone in capital"
        caps = [r["capital"] for r in pub["ceiling"]["curve"]]
        assert caps == sorted(caps) and caps[0] == 10_000.0 and caps[-1] == 100_000_000.0, (
            "the scan is the pre-registered 10 k .. 100 M grid, ending exactly at 100 M")
    sheets = rep.get("sheets") or {}
    for rec in sheets.get("sheets") or []:
        assert "p95" not in json.dumps(rec), "a sheet is one point and gets no percentile"


def test_the_code_the_books_recorded_still_matches():
    ref = os.environ.get("HYDRA_434_CODE_REF")
    if ref:
        anc = subprocess.run(["git", "merge-base", "--is-ancestor", ref, "HEAD"], cwd=ROOT, capture_output=True)
        assert anc.returncode == 0, f"{ref} is not an ancestor of HEAD"
    problems = []
    for panel in _panels_present():
        man = PV.read_manifest(os.path.join(_dir(), f"{panel}_base.pkl"))
        code = (man or {}).get("code") or {}
        for block in ("modules", "swept"):
            for rel, stored in (code.get(block) or {}).items():
                now = PV.sha256_lf_at(ref, rel) if ref else (
                    PV.sha256_lf(os.path.join(ROOT, rel)) if os.path.exists(os.path.join(ROOT, rel)) else None)
                if now != stored:
                    problems.append(f"{panel}: {block}:{rel} stored {stored[:12]} now {str(now)[:12]}")
    assert not problems, "\n".join(problems)
