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
import pytest

#: `pytest.ini` sets `--timeout=30`, which is right for the portable suite and wrong here: these
#: audits re-derive the mark grid from the raw panel caches (~70 s for Russell, ~15 s for the S&P
#: panel, per call, uncached ON PURPOSE - `cost_stress.py` is inside the code identity the books
#: recorded, so it may not be edited while this run's evidence is being judged). Before this
#: marker every case here died on the 30 s timeout, which killed the whole pytest session and
#: took the 11 unrelated audits down with it - reported as RAN - FAIL, never as a pass.
pytestmark = pytest.mark.timeout(1800)

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


# ============================================================ the two closing checks
# Both were asked for after the void run, and both are verifications rather than production
# code: nothing here changes what a drive does, and this file is NOT in the drive's swept set
# (measured: 10 modules, listed under `code.swept` in any manifest).

def _manifests():
    run_id = resolve_run()
    A.use_run(run_id)
    out = {}
    for panel, label in A.ORDER:
        man = PV.read_manifest(A.acc_path(panel, label))
        assert man, f"{panel}/{label} has no manifest"
        out[(panel, label)] = man
    return out


def test_the_code_fingerprint_still_matches_after_the_last_book():
    """CLOSES THE WINDOW `check_code_unchanged` leaves open during the FINAL book.

    The guard runs before each drive, so nothing verifies the code between the start of book
    eight and its seal. This recomputes every recorded module digest FROM DISK, in this fresh
    process, and requires it to equal what all eight books recorded.

    Reading the files rather than `code_identity()` is the point: `swept` depends on what a
    process happens to have imported, so comparing two processes' sweeps compares their import
    graphs. `sha256_lf(path)` is a property of the bytes, so it answers the question actually
    being asked - did the code move while the evidence was being produced.
    """
    mans = _manifests()
    problems = []
    for (panel, label), man in mans.items():
        code = man.get("code") or {}
        for block in ("modules", "swept"):
            for rel, stored in (code.get(block) or {}).items():
                path = os.path.join(ROOT, rel)
                if not os.path.exists(path):
                    problems.append(f"{panel}/{label}: {block}:{rel} recorded but now absent")
                    continue
                now = PV.sha256_lf(path)
                if now != stored:
                    problems.append(
                        f"{panel}/{label}: {block}:{rel} stored {stored[:12]} but the file on "
                        f"disk is {now[:12]} - the code moved")
    assert not problems, "\n".join(problems)


def test_every_book_recorded_the_same_code():
    """Eight books, one code identity. A run split across two versions is not one experiment."""
    mans = _manifests()
    combined = {f"{p}/{lab}": (m.get("code") or {}).get("modules_combined")
                for (p, lab), m in mans.items()}
    assert len(set(combined.values())) == 1, combined

    swept = {}
    for (panel, label), man in mans.items():
        for rel, digest in ((man.get("code") or {}).get("swept") or {}).items():
            swept.setdefault(rel, {})[f"{panel}/{label}"] = digest
    disagree = {rel: by for rel, by in swept.items() if len(set(by.values())) > 1}
    assert not disagree, (
        f"a swept module has different digests across the eight books: {disagree}. That is the "
        "shape of the void run 20260914-99967d14f3ad, where accredit_433.py was edited mid-run.")


def _config_without_costs(cfg: dict) -> dict:
    """`config` with only the parts that MUST be constant across scenarios."""
    out = {k: v for k, v in (cfg or {}).items()
           if k not in ("v9_effective", "v9_effective_sha256")}
    v9 = dict((cfg or {}).get("v9_effective") or {})
    v9.pop("stock_cost_bp", None)
    v9.pop("etf_cost_bp", None)
    out["v9_effective_minus_costs"] = v9
    return out


def test_within_each_panel_only_the_costs_differ():
    """THE SUBTRACTION HAS TO MEAN SOMETHING.

    TASK-433 reports `result(costs B) - result(costs A)`. For that difference to be attributable
    to the costs, everything else must be identical: the same inputs, the same calendar, the same
    configuration apart from the two cost fields, the same holdout declaration and the same
    protocol. Russell and S&P legitimately read different files; WITHIN a panel they must not.

    If `membership.pkl`, `close.pkl`, `irx.pkl` or any other input moved between base and stress,
    the deltas would stop being cost deltas and nothing in the table would say so.
    """
    mans = _manifests()
    problems = []
    for panel in ("russell", "sp500"):
        ref_label = "base"
        ref = mans[(panel, ref_label)]
        for label in ("conservative", "stress", "smallcap_crisis"):
            man = mans[(panel, label)]
            for block in ("data", "calendar", "period", "protocol", "units", "sectors",
                          "universe"):
                if (ref.get(block) or {}) != (man.get(block) or {}):
                    a, b = ref.get(block) or {}, man.get(block) or {}
                    keys = sorted(set(a) | set(b))
                    diff = {k: (str(a.get(k))[:40], str(b.get(k))[:40])
                            for k in keys if a.get(k) != b.get(k)}
                    problems.append(
                        f"{panel}: {block!r} differs between {ref_label} and {label}: {diff}")
            if _config_without_costs(ref.get("config")) != _config_without_costs(
                    man.get("config")):
                problems.append(
                    f"{panel}: config differs between {ref_label} and {label} beyond the cost "
                    "fields")
    assert not problems, "\n".join(problems)


def test_the_cost_blocks_differ_exactly_as_the_frozen_table_says():
    """The other half: the costs must actually have moved, and to the declared pairs."""
    frozen = {"base": (10.0, 5.0), "conservative": (20.0, 8.0),
              "stress": (35.0, 10.0), "smallcap_crisis": (50.0, 15.0)}
    mans = _manifests()
    for (panel, label), man in mans.items():
        costs = man.get("costs") or {}
        want = frozen[label]
        got = (float(costs.get("stock_bp_per_side")), float(costs.get("etf_bp_per_side")))
        assert got == want, f"{panel}/{label}: costs {got} but the frozen scenario is {want}"
        v9 = (man.get("config") or {}).get("v9_effective") or {}
        assert (float(v9.get("stock_cost_bp")), float(v9.get("etf_cost_bp"))) == want, (
            f"{panel}/{label}: the cost pair did not reach config.v9_effective; 20/8 and 15/13 "
            "would be indistinguishable")


def test_the_shared_inputs_are_shared_across_panels_too():
    """`etf_close` and `irx` are the SAME files for both panels, so they must hash the same.

    If they did not, a Russell-vs-S&P comparison would carry an input difference nobody declared.
    """
    mans = _manifests()
    for name in ("etf_close", "irx"):
        digests = {f"{p}/{lab}": ((m.get("data") or {}).get(name) or {}).get("sha256")
                   for (p, lab), m in mans.items()}
        assert len(set(digests.values())) == 1, f"{name} differs across the eight books: {digests}"


def test_ann_net_degrades_essentially_monotonically_as_costs_rise():
    """The economic coherence check. Not strict monotonicity of Sharpe or maxDD - a cost change
    moves the NAV and therefore the later trajectory - but a MATERIAL improvement in annualised
    return when execution gets more expensive needs a mechanical explanation before publication."""
    import report_433 as RPT  # noqa: PLC0415

    payload = _payload(resolve_run())
    anomalies = RPT.degradation_anomalies(payload)
    assert not anomalies, (
        "raising costs improved ann_net materially; find the mechanism before accepting the "
        f"table: {[a['detail'] for a in anomalies]}")
