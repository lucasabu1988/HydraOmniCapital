"""EXTERNAL EVIDENCE AUDIT - the TASK-433 regeneration, against the books actually on this disk.

Not a unit test. `experiments/test_accredit_433_adversarial.py` runs the same twelve mutations
against a synthetic book and is REQUIRED on every clean clone; that proves the CONTRACT. This
file applies them to the eight real accredited books of one run, which is a claim about specific
bytes in `_lab_scratch/` and can only be made where those bytes exist. Run by
`tools/external_audit.py`, which reports RAN - PASS / RAN - FAIL / DID NOT RUN with the exact
missing path. There is no `pytest.skip` in this file.

Which run: `HYDRA_433_RUN_ID`, or the newest directory under `accredited/runs/`. The legacy
`accredited/` directory - the WITHDRAWN 2026-09-12 run - is never read as a current result and
is asserted to be untouched.

The mutations are applied to a COPY in a temp directory. Nothing here opens a real book for
writing, and the write-isolation barrier installed by the repo conftest protects `_lab_scratch`
regardless.
"""
import json
import os
import shutil
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for _p in (ROOT, os.path.join(ROOT, "experiments")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import accredit_433 as A  # noqa: E402
import cost_stress as CS  # noqa: E402
import provenance as PV  # noqa: E402

MANDATORY = ("result", "artifact", "costs", "config", "code", "data", "calendar", "units",
             "period", "protocol")


def _runs_root():
    return os.path.join(A.ACC_ROOT, "runs")


def resolve_run() -> str:
    """The run id this audit is about. Explicit beats newest, and neither is the legacy slot."""
    explicit = os.environ.get("HYDRA_433_RUN_ID")
    if explicit:
        return explicit
    root = _runs_root()
    ids = sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d)))
    assert ids, f"no run directory under {root}"
    return ids[-1]


def _payload(run_id):
    path = os.path.join(ROOT, "experiments", "_lab_scratch",
                        f"task433_accredited_{run_id}.json")
    assert os.path.exists(path), f"the run published no reconciliation report at {path}"
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_the_run_published_eight_books_and_a_report():
    run_id = resolve_run()
    A.use_run(run_id)
    missing = [f"{p}/{lab}" for p, lab in A.ORDER if not os.path.exists(A.acc_path(p, lab))]
    assert not missing, f"run {run_id} is incomplete: {missing}"
    payload = _payload(run_id)
    assert payload["run_id"] == run_id
    assert len(payload["reconciliation"]) == 8


def test_every_one_of_the_eight_accredits_with_every_mandatory_block_compared():
    """`fully_accredited` must mean eight books each answered their own effective request."""
    run_id = resolve_run()
    A.use_run(run_id)
    problems = []
    for panel, label in A.ORDER:
        answer = A.accredit_answer(panel, label)
        if answer["state"] != PV.ACCREDITED:
            problems.append(f"{panel}/{label}: {answer['rejected']}")
            continue
        compared = set(answer["accreditation"]["compared"])
        gone = [b for b in MANDATORY if b not in compared]
        if gone:
            problems.append(f"{panel}/{label}: IDENTITY INCOMPLETE, never compared {gone}")
        for field, why in (answer["accreditation"]["uncompared_why"] or {}).items():
            if not A._permitted_uncompared(field, why):
                problems.append(f"{panel}/{label}: {field} uncompared for an unnamed reason {why!r}")
    assert not problems, "\n".join(problems)


def test_the_aggregate_says_fully_accredited_and_means_it():
    payload = _payload(resolve_run())
    prov = payload["provenance"]
    assert prov["fully_accredited"] is True, prov.get("rejected")
    assert len(prov["accredited"]) == 8
    assert prov["still_historical_only"] == []
    for key, blocks in prov["compared_by_book"].items():
        gone = [b for b in MANDATORY if b not in blocks]
        assert not gone, f"{key} is counted as accredited with {gone} never compared"


def test_all_eight_books_are_on_one_grid():
    """Every delta in the table is a subtraction between two books; two grids is not a delta."""
    payload = _payload(resolve_run())
    marks = payload["marks_accredited"]
    assert marks["n_books"] == 8, marks
    assert marks["identical"] is True, marks


def test_the_scenarios_are_the_frozen_ones():
    """10/5, 20/8, 35/10, 50/15 - declared before any number was looked at."""
    frozen = {"base": (10.0, 5.0), "conservative": (20.0, 8.0),
              "stress": (35.0, 10.0), "smallcap_crisis": (50.0, 15.0)}
    payload = _payload(resolve_run())
    seen = {}
    for rec in payload["reconciliation"]:
        seen[rec["scenario"]] = (float(rec["stock_bp"]), float(rec["etf_bp"]))
    assert seen == frozen, seen


def test_the_books_span_research_and_validation_and_never_live():
    """The live weeks are not in the tuning set, and the books must show it."""
    run_id = resolve_run()
    A.use_run(run_id)
    import holdout as HO  # noqa: PLC0415
    for panel, label in A.ORDER:
        book = pd.read_pickle(A.acc_path(panel, label))
        idx = pd.DatetimeIndex(book.index)
        spanned = set(HO.partitions_spanned(idx[0], idx[-1]))
        assert "live" not in spanned, (
            f"{panel}/{label} reaches {idx[-1].date()}, inside the live partition: HOLDOUT BREACH")
        assert spanned <= {"research", "validation"}, f"{panel}/{label} spans {spanned}"


def test_the_withdrawn_run_is_untouched_and_still_refused():
    """The 2026-09-12 books stay where they are, and still cannot answer today's request."""
    legacy = [os.path.join(A.ACC_ROOT, f"{p}_{lab}.pkl") for p, lab in A.ORDER]
    present = [q for q in legacy if os.path.exists(q)]
    assert len(present) == 8, f"the withdrawn run lost books: only {len(present)} of 8 remain"
    digests = set()
    for q in present:
        man = PV.read_manifest(q) or {}
        digests.add((man.get("code") or {}).get("modules_combined", "")[:12])
    running = PV.code_identity().get("modules_combined", "")[:12]
    assert running not in digests, (
        "a withdrawn book now records the RUNNING code digest, which means it was re-sealed "
        "rather than left as historical evidence")


def test_the_eight_historical_pre_manifest_books_are_still_unmanifested():
    for path in CS.historical_books():
        assert os.path.exists(path), f"a published TASK-431/433 book vanished: {path}"
        assert not os.path.exists(PV.manifest_path(path)), (
            f"a pre-manifest book was given a manifest: {path}")


# --------------------------------------------------------- the twelve, on the real books
def _copy_run(tmp_path, panel, label):
    """A writable copy of one real book and its manifest, so the originals are never touched."""
    run_id = resolve_run()
    A.use_run(run_id)
    src = A.acc_path(panel, label)
    dst = str(tmp_path / os.path.basename(src))
    shutil.copy2(src, dst)
    shutil.copy2(PV.manifest_path(src), PV.manifest_path(dst))
    return dst


def _reseal(path, mutate):
    man = PV.read_manifest(path)
    mutate(man)
    man.pop("self_sha256", None)
    man = PV.seal(man)
    with open(PV.manifest_path(path), "w", encoding="utf-8") as fh:
        json.dump(man, fh, indent=2, default=str)
    return man


def _refused(path, panel, label):
    try:
        PV.accredit(path, A.effective_request(panel, label), echo=False)
    except PV.CacheRejected as exc:
        return exc
    return None


def test_the_twelve_mutations_are_all_refused_on_the_real_books(tmp_path):
    """Same twelve as the portable battery, applied to copies of the real accredited books."""
    cases = []

    def case(name, panel, label, mutate=None, book=None):
        p = _copy_run(tmp_path / name if False else tmp_path, panel, label)
        p2 = str(tmp_path / f"{name}.pkl")
        shutil.move(p, p2)
        shutil.move(PV.manifest_path(p), PV.manifest_path(p2))
        if book is not None:
            pd.to_pickle(book, p2)
        if mutate is not None:
            _reseal(p2, mutate)
        cases.append((name, p2, panel, label))
        return p2

    real = pd.read_pickle(_copy_run(tmp_path, "russell", "base"))
    marks = pd.DatetimeIndex(real.index)

    case("1_scenario_label", "russell", "base",
         mutate=lambda m: m["costs"].update(scenario_label="stress"))
    case("2_cost_pair", "russell", "base",
         mutate=lambda m: m["costs"].update(stock_bp_per_side=35.0))
    case("3_panel_identity", "russell", "base",
         mutate=lambda m: m["data"].update(
             {k: v for k, v in PV.data_identity(CS.data_inputs("sp500")).items()}))
    case("4_calendar", "russell", "base", book=real.iloc[:-25])
    case("5_period", "russell", "base",
         mutate=lambda m: m["period"].update(declared="research"))
    case("6_data_identity", "russell", "base",
         mutate=lambda m: m["data"]["price_close"].update(sha256="0" * 64))
    case("7_config_identity", "russell", "base",
         mutate=lambda m: m["config"].update(v9_effective_sha256="0" * 64))
    case("9_modified_and_resealed", "russell", "base",
         mutate=lambda m: m["costs"].update(etf_bp_per_side=99.0))
    case("10_missing_block", "russell", "base", mutate=lambda m: m.pop("costs", None))
    shifted = pd.Series(real.values,
                        index=pd.DatetimeIndex([d + pd.Timedelta(days=7) for d in marks]))
    case("11_shifted_same_length", "russell", "base", book=shifted)
    case("12_metrics_right_provenance_wrong", "russell", "base",
         mutate=lambda m: m["data"]["spy"].update(sha256="0" * 64))

    accepted = []
    for name, path, panel, label in cases:
        exc = _refused(path, panel, label)
        if exc is None:
            accepted.append(name)
    assert not accepted, f"these mutations were ACCEPTED on the real books: {accepted}"

    # 8: a historical, pre-manifest book cannot answer anything
    hist = [p for p in CS.historical_books() if os.path.exists(p)]
    assert hist, "no historical book on this disk to substitute"
    assert _refused(hist[0], "russell", "base") is not None, (
        "a pre-manifest historical book answered a TASK-433 request")


def test_the_unmutated_copy_still_accredits(tmp_path):
    """The control on the real books: if a plain copy stopped accrediting, every rejection above
    would be explained by the copy rather than by the mutation."""
    path = _copy_run(tmp_path, "russell", "base")
    assert _refused(path, "russell", "base") is None, (
        "an unmutated copy of the real accredited book was refused")
