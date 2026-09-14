"""EXTERNAL EVIDENCE AUDIT runner: RAN - PASS, RAN - FAIL, or DID NOT RUN - <exact path>.

    python tools/external_audit.py                 # run what this machine can, report the rest
    python tools/external_audit.py --list          # the registry, with the artefacts each needs
    python tools/external_audit.py --report a.json # machine-readable result
    python tools/external_audit.py --require-all   # non-zero unless EVERY audit actually ran

What this exists to prevent (HYDRA-CI-01)
-----------------------------------------
Eleven cases in the required suite were gated on gitignored private artefacts and skipped on
every machine that did not happen to have them - which is every CI run since they were written.
`run_all_tests.py` reported the files `[PASS]` and `check_skips.py` carried the eleven as a
TEMPORARY exemption. Seven of those eleven turned out to be portable invariants wearing an
artefact's clothes and now run everywhere. The other four, plus two halves split off from
portable cases, are genuinely claims about THIS disk - the published TASK-433 books, the
withdrawn result, the live and paper books, the OOS sweep caches - and they live here.

The contract, which is the whole point:

  * an audit whose artefacts are present RUNS, and reports PASS or FAIL;
  * an audit whose artefacts are absent reports DID NOT RUN and NAMES THE MISSING PATH;
  * a SKIPPED case inside an audit is reported as a FAILURE, not as a pass and not as a
    did-not-run - a skip here would rebuild the exact hole this replaced;
  * a missing file is never an error state of the audit itself. `DID NOT RUN` is a real,
    printed, machine-readable answer, and the default exit code treats it as such: absence of
    evidence exits 0 while reporting the absence, and only a real FAIL exits non-zero. Use
    `--require-all` on the lab machine, where absence IS the finding.

`audits/` is deliberately NOT discovered by `run_all_tests.py` (it globs `test_*.py` in the repo
root, `experiments/` and `tools/`). That separation is asserted, not assumed, by
`tools/test_external_audit.py`, which also checks that every audit function is registered here
and that no audit file contains a skip.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import results_report as RR  # noqa: E402

AUDIT_DIR = ROOT / "audits"

#: The three answers. There is no fourth, and in particular there is no "skipped".
RAN_PASS = "RAN - PASS"
RAN_FAIL = "RAN - FAIL"
DID_NOT_RUN = "DID NOT RUN"


def _p(*parts) -> str:
    return str(ROOT.joinpath(*parts))


#: Artefact sets, named once so a path is written down in exactly one place.
TASK_433_BOOKS = {
    "engine_book_russell.pkl": _p("experiments", "_lab_scratch", "engine_book_russell.pkl"),
    "engine_book_sp_samegrid.pkl": _p("experiments", "_lab_scratch",
                                      "engine_book_sp_samegrid.pkl"),
    "cost_stress books": _p("experiments", "_lab_scratch", "cost_stress"),
}
WITHDRAWN = {
    "task433_accredited.json": _p("experiments", "_lab_scratch", "task433_accredited.json"),
    "task433_accredited_WITHDRAWN.json": _p("experiments", "_lab_scratch",
                                            "task433_accredited_WITHDRAWN.json"),
}
OOS_CACHES = {
    "audit_steps.pkl": _p("experiments", "_sweep_cache_etf", "audit_steps.pkl"),
    "oos spy.pkl": _p("experiments", "_sweep_cache_oos", "spy.pkl"),
    "oos irx.pkl": _p("experiments", "_sweep_cache_oos", "irx.pkl"),
}

#: TASK-433's regeneration. PINNED to the run it audits, on purpose: "the newest directory under
#: runs/" would silently re-point this audit at whatever was produced last, and an audit that
#: follows the evidence around is not an audit. A new run is a new entry, added deliberately.
TASK_433_RUN_ID = "20260914-99967d14f3ad"
_T433 = _p("experiments", "_lab_scratch", "accredited", "runs", TASK_433_RUN_ID)
TASK_433_RUN = {
    **{f"{panel}_{label}.pkl": os.path.join(_T433, f"{panel}_{label}.pkl")
       for panel in ("russell", "sp500")
       for label in ("base", "conservative", "stress", "smallcap_crisis")},
    "reconciliation report": _p("experiments", "_lab_scratch",
                                f"task433_accredited_{TASK_433_RUN_ID}.json"),
}

#: (id, nodeid, {label: required path}, what it claims, why it cannot be portable).
#: Exact nodeids, no wildcards: "everything under audits/" is not a registry, it is an exemption.
REGISTRY: tuple = (
    dict(
        id="books.reconcile-does-not-touch",
        nodeid="audits/audit_evidence_books.py::"
               "test_reconcile_reports_the_real_historical_books_without_touching_them",
        requires=TASK_433_BOOKS,
        claims="a real reconcile leaves the eight published books byte-identical and unmanifested",
        why_external="the claim is about the bytes of eight specific evidence books on this disk",
    ),
    dict(
        id="books.still-historical",
        nodeid="audits/audit_evidence_books.py::"
               "test_the_published_books_are_still_classified_historical_and_not_accredited",
        requires=TASK_433_BOOKS,
        claims="none of the eight pre-manifest books has acquired an accredited classification",
        why_external="classification is read off the real files",
    ),
    dict(
        id="books.marks-are-the-431-books",
        nodeid="audits/audit_evidence_books.py::"
               "test_the_real_books_marks_are_what_the_task_431_row_was_measured_on",
        requires=TASK_433_BOOKS,
        claims="the two base books are wealth series on a sorted grid, i.e. the evidence this "
               "audit thinks it is reading",
        why_external="reads the real pickles",
    ),
    dict(
        id="withdrawn.preserved",
        nodeid="audits/audit_evidence_books.py::"
               "test_the_withdrawn_artifact_and_its_note_are_both_still_preserved",
        requires=WITHDRAWN,
        claims="the withdrawn 2026-09-12 result and its withdrawal note are both still on disk",
        why_external="preservation is a fact about this disk; the refusal contract is portable "
                     "and is pinned in experiments/test_accredit_433.py",
    ),
    dict(
        id="withdrawn.no-replacement-yet",
        nodeid="audits/audit_evidence_books.py::test_no_replacement_result_has_been_published_yet",
        requires=WITHDRAWN,
        claims="no task433_accredited_v2.json exists, i.e. TASK-433 is still open on this disk",
        why_external="reads the real result path",
    ),
    dict(
        id="reference-rows.remeasure",
        nodeid="audits/audit_reference_rows.py::"
               "test_the_reference_rows_are_what_reference_rows_py_measures",
        requires=OOS_CACHES,
        claims="the published baselines equal what reference_rows.py measures on the OOS caches",
        why_external="the numbers are properties of the real marks; a synthetic panel could only "
                     "compare the script with itself",
    ),
    dict(
        id="reference-rows.measurement-not-empty",
        nodeid="audits/audit_reference_rows.py::test_the_measurement_actually_produced_both_rows",
        requires=OOS_CACHES,
        claims="reference_rows.measure() actually produced the rows the comparison reads",
        why_external="same caches",
    ),
    dict(
        id="lab.published-mix-had-tbill",
        nodeid="audits/audit_lab_artifacts.py::test_the_published_mix_already_had_cash_at_the_t_bill",
        requires={"audit_steps.pkl": OOS_CACHES["audit_steps.pkl"]},
        claims="TASK-409's finding: P_5050 in the audit pickle already carried the T-bill leg",
        why_external="a statement about specific recorded bytes",
    ),
    dict(
        id="task433.run-published-eight-books-and-a-report",
        nodeid="audits/audit_task433_run.py::test_the_run_published_eight_books_and_a_report",
        requires=TASK_433_RUN,
        claims="the pinned run published all eight books and its reconciliation report",
        why_external="reads the eight accredited books of one real run, which live in the "
                     "gitignored _lab_scratch/ and are never committed",
    ),
    dict(
        id="task433.every-one-of-the-eight-accredits-with-every-",
        nodeid="audits/audit_task433_run.py::test_every_one_of_the_eight_accredits_with_every_mandatory_block_compared",
        requires=TASK_433_RUN,
        claims="each of the eight answers its own effective request with every mandatory identity block compared - not merely a valid seal",
        why_external="reads the eight accredited books of one real run, which live in the "
                     "gitignored _lab_scratch/ and are never committed",
    ),
    dict(
        id="task433.aggregate-says-fully-accredited-and-means-it",
        nodeid="audits/audit_task433_run.py::test_the_aggregate_says_fully_accredited_and_means_it",
        requires=TASK_433_RUN,
        claims="fully_accredited=true, and each book counted as accredited really compared every mandatory block",
        why_external="reads the eight accredited books of one real run, which live in the "
                     "gitignored _lab_scratch/ and are never committed",
    ),
    dict(
        id="task433.all-eight-books-are-on-one-grid",
        nodeid="audits/audit_task433_run.py::test_all_eight_books_are_on_one_grid",
        requires=TASK_433_RUN,
        claims="the eight books share one mark grid, so every delta in the table is a real subtraction",
        why_external="reads the eight accredited books of one real run, which live in the "
                     "gitignored _lab_scratch/ and are never committed",
    ),
    dict(
        id="task433.scenarios-are-the-frozen-ones",
        nodeid="audits/audit_task433_run.py::test_the_scenarios_are_the_frozen_ones",
        requires=TASK_433_RUN,
        claims="the cost pairs are the frozen 10/5, 20/8, 35/10, 50/15 and were not moved after the fact",
        why_external="reads the eight accredited books of one real run, which live in the "
                     "gitignored _lab_scratch/ and are never committed",
    ),
    dict(
        id="task433.books-span-research-and-validation-and-never",
        nodeid="audits/audit_task433_run.py::test_the_books_span_research_and_validation_and_never_live",
        requires=TASK_433_RUN,
        claims="no book reaches the live partition: no HOLDOUT BREACH",
        why_external="reads the eight accredited books of one real run, which live in the "
                     "gitignored _lab_scratch/ and are never committed",
    ),
    dict(
        id="task433.withdrawn-run-is-untouched-and-still-refused",
        nodeid="audits/audit_task433_run.py::test_the_withdrawn_run_is_untouched_and_still_refused",
        requires=TASK_433_RUN,
        claims="the withdrawn 2026-09-12 run is still eight books, none re-sealed under the running code",
        why_external="reads the eight accredited books of one real run, which live in the "
                     "gitignored _lab_scratch/ and are never committed",
    ),
    dict(
        id="task433.eight-historical-pre-manifest-books-are-stil",
        nodeid="audits/audit_task433_run.py::test_the_eight_historical_pre_manifest_books_are_still_unmanifested",
        requires=TASK_433_RUN,
        claims="the pre-manifest TASK-431/433 books are still there and still carry no manifest",
        why_external="reads the eight accredited books of one real run, which live in the "
                     "gitignored _lab_scratch/ and are never committed",
    ),
    dict(
        id="task433.twelve-mutations-are-all-refused-on-the-real",
        nodeid="audits/audit_task433_run.py::test_the_twelve_mutations_are_all_refused_on_the_real_books",
        requires=TASK_433_RUN,
        claims="the twelve TASK-433 falsifications are each refused on copies of the REAL books",
        why_external="reads the eight accredited books of one real run, which live in the "
                     "gitignored _lab_scratch/ and are never committed",
    ),
    dict(
        id="task433.unmutated-copy-still-accredits",
        nodeid="audits/audit_task433_run.py::test_the_unmutated_copy_still_accredits",
        requires=TASK_433_RUN,
        claims="the control: an unmutated copy of a real book still accredits, so the twelve rejections are about the mutations and not about the copying",
        why_external="reads the eight accredited books of one real run, which live in the "
                     "gitignored _lab_scratch/ and are never committed",
    ),
    dict(
        id="paper.20260910-sheet",
        nodeid="audits/audit_live_books.py::test_real_20260910_paper_sheet_matches_the_hand_figure",
        requires={"state_paper/instructions_20260910.json":
                  _p("state_paper", "instructions_20260910.json")},
        claims="the real paper sheet reproduces the TASK-417 hand figures",
        why_external="reads gitignored operator state that must never be committed",
    ),
    dict(
        id="live.state-readable",
        nodeid="audits/audit_live_books.py::"
               "test_the_live_state_is_readable_and_the_report_can_summarise_it",
        requires={"state/portfolio_v9.json": _p("state", "portfolio_v9.json")},
        claims="the live book parses and the fill-cost report can summarise it. NOT a claim "
               "about execution: only broker fills can say whether the orders were executed",
        why_external="reads the live book",
    ),
    dict(
        id="live.read-only",
        nodeid="audits/audit_live_books.py::test_reading_the_live_book_left_it_exactly_as_it_was",
        requires={"state/portfolio_v9.json": _p("state", "portfolio_v9.json")},
        claims="this audit only read the live book; its digest is unchanged afterwards",
        why_external="reads the live book",
    ),
)


def missing(case: dict) -> dict:
    """{label: path} for every required artefact that is not on this disk."""
    return {label: path for label, path in case["requires"].items() if not os.path.exists(path)}


def _run(nodeids: list, junit: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider",
           "--junitxml", junit, *nodeids]
    return subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=3600)


def _outcomes(junit: str) -> dict:
    """test function name -> (outcome, reason), from the junit XML pytest wrote.

    The registry's nodeids are the key everywhere else, but junit carries a dotted classname
    rather than a path, so the function name is what the two sides can agree on. Every registered
    audit function name is unique across `audits/` - `test_external_audit.py` asserts that, so a
    collision here cannot silently resolve to the wrong case.
    """
    out: dict = {}
    for case in RR.parse_junit(junit, ""):
        out[case["nodeid"].split("::", 1)[-1]] = (case["outcome"], case["reason"])
    return out


def evaluate(only=None) -> dict:
    """Run every audit whose artefacts are present; report the rest. Never raises on absence."""
    started = datetime.datetime.now(datetime.timezone.utc).isoformat()
    cases = [c for c in REGISTRY if not only or c["id"] in only]
    results, runnable = [], []
    for case in cases:
        gone = missing(case)
        if gone:
            results.append(dict(case, status=DID_NOT_RUN, missing=gone, outcome=None,
                                reason=None,
                                detail="; ".join(f"{k} not found at {v}" for k, v in gone.items())))
        else:
            runnable.append(case)

    if runnable:
        tmp = tempfile.mkdtemp(prefix="hydra-extaudit-")
        junit = os.path.join(tmp, "audit.xml")
        proc = _run([c["nodeid"] for c in runnable], junit)
        seen = _outcomes(junit) if os.path.exists(junit) else {}
        for case in runnable:
            name = case["nodeid"].split("::", 1)[-1]
            if name not in seen:
                results.append(dict(
                    case, status=RAN_FAIL, missing={}, outcome="not-reported", reason=None,
                    detail=("the audit was launched but pytest reported no result for it "
                            f"(exit {proc.returncode}). A registered audit that produces no "
                            "outcome is a failure, never a pass.\n"
                            + (proc.stdout or "")[-1500:])))
                continue
            outcome, reason = seen[name]
            if outcome == RR.PASSED:
                results.append(dict(case, status=RAN_PASS, missing={}, outcome=outcome,
                                    reason=reason, detail=None))
            elif outcome == RR.SKIPPED:
                # The hole this whole task exists to close. An audit may not skip.
                results.append(dict(
                    case, status=RAN_FAIL, missing={}, outcome=outcome, reason=reason,
                    detail=("a SKIPPED case inside an external audit is reported as a FAILURE: "
                            "the artefact gate belongs to this runner, which reports DID NOT RUN "
                            f"with the missing path. reason: {reason or 'none given'}")))
            else:
                results.append(dict(case, status=RAN_FAIL, missing={}, outcome=outcome,
                                    reason=reason, detail=reason))

    order = {c["id"]: i for i, c in enumerate(cases)}
    results.sort(key=lambda r: order[r["id"]])
    tally = dict(
        total=len(results),
        ran_pass=sum(r["status"] == RAN_PASS for r in results),
        ran_fail=sum(r["status"] == RAN_FAIL for r in results),
        did_not_run=sum(r["status"] == DID_NOT_RUN for r in results),
    )
    return dict(kind="hydra-external-audit", schema=1, started_utc=started,
                finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                host_has_artifacts=tally["did_not_run"] == 0,
                results=results,
                totals=tally)


def render(report: dict) -> None:
    t = report["totals"]
    print("EXTERNAL EVIDENCE AUDIT")
    print("=" * 78)
    for r in report["results"]:
        print(f"[{r['status']:<11}] {r['id']}")
        print(f"              {r['nodeid']}")
        print(f"              claims: {r['claims']}")
        if r["status"] == DID_NOT_RUN:
            for label, path in r["missing"].items():
                print(f"              MISSING: {label} -> {path}")
            print(f"              why external: {r['why_external']}")
        elif r["status"] == RAN_FAIL:
            first = (r["detail"] or "").strip().splitlines()
            print(f"              FAILED: {first[0] if first else 'no detail'}")
    print("-" * 78)
    print(f"{t['ran_pass']} RAN - PASS, {t['ran_fail']} RAN - FAIL, "
          f"{t['did_not_run']} DID NOT RUN, {t['total']} registered")
    if t["did_not_run"]:
        print("\nDID NOT RUN is a reported result, not a pass. The invariants that DO NOT need "
              "these\nartefacts run in the required suite; this machine could not make the "
              "claims above.")
    if not t["ran_fail"] and not t["did_not_run"]:
        print("\nEvery registered audit ran on this machine and passed.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="run the external evidence audits, or say why not")
    ap.add_argument("--list", action="store_true", help="print the registry and exit")
    ap.add_argument("--only", action="append", default=None, help="audit id (repeatable)")
    ap.add_argument("--report", type=str, default=None, help="write the JSON result here")
    ap.add_argument("--require-all", action="store_true",
                    help="exit non-zero unless every registered audit actually ran")
    args = ap.parse_args(argv)

    if args.list:
        for case in REGISTRY:
            print(f"{case['id']}\n  {case['nodeid']}\n  claims: {case['claims']}\n"
                  f"  why external: {case['why_external']}")
            for label, path in case["requires"].items():
                mark = "present" if os.path.exists(path) else "ABSENT "
                print(f"  [{mark}] {label}: {path}")
            print()
        return 0

    report = evaluate(only=args.only)
    render(report)
    if args.report:
        # Create the directory. In the workflow the suite step has already made `reports/` (its
        # own writer does `mkdir(parents=True)`), so this never fires there - which is exactly
        # why it is here: a latent dependency on step ORDER is not something to leave in a tool
        # whose whole job is to report honestly when something is absent.
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str)
        print(f"report: {args.report}")

    t = report["totals"]
    if t["ran_fail"]:
        return 1
    if args.require_all and t["did_not_run"]:
        print("\n--require-all: the artefacts were expected on this machine and are not here.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
