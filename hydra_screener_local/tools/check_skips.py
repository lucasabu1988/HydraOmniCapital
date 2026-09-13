"""A skip is not a pass - and now that holds per CASE, not only per file.

    python tools/check_skips.py                              # run the suite, then gate it
    python tools/check_skips.py --from-report reports/run.json --expect-token <token>

What this gate used to miss
---------------------------
It scraped `run_all_tests.py` stdout, which reported one status per FILE. pytest can skip
individual cases inside a file that otherwise passes, so on a clean checkout of `b85e9e4`
three files reported `21 passed, 4 skipped` to pytest while the runner headline said
`0 skipped` and this gate printed `check_skips ok`. Four assertions did not run and nothing
failed. The old `if n_skipped:` branch printed a note and returned 0 anyway.

Scraping had a second hole, reproduced on the same tree: `--from-file` set `rc = 0`
unconditionally and treated a missing `RESULTS:` line as "nothing to report". A file holding
one line of arbitrary text, an empty file, and a log whose own body read
`[FAIL] test_everything.py (exit 1, 1.0s)` each produced `check_skips ok`, exit 0.

So the gate now reads a structured report (tools/results_report.py) and every way of having
no measurement - absent, unparseable, truncated, foreign, or from a run that did not finish
- is a failure rather than a quiet pass.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import results_report as RR  # noqa: E402

#: file -> why the WHOLE file is allowed to skip. A file skip with no entry here fails.
EXPECTED_SKIPS: dict[str, str] = {
    "test_hybrid_integration.py":
        "needs history/, which is gitignored and lives on one disk (CLAUDE.md)",
    "validate_pine_contract.py":
        "needs pine/hydra_last_summary.json, produced by a real screener run",
}

#: nodeid -> the policy that permits it. Exact nodeids only: no directory or prefix
#: wildcards, because "everything under experiments/ may skip" is not a policy, it is an
#: exemption with no edge. `reason_contains` must appear in the reason the run actually
#: reported, so a test that starts skipping for a DIFFERENT reason is not covered by an
#: entry written for the old one - the allowlist cannot drift into a name-only pass.
#:
#: All eleven entries below are the SAME policy - HYDRA-CI-01, an invariant that is only
#: exercised where a gitignored private artefact happens to exist - and every one of them is
#: TEMPORARY. CI-01 has to re-express each portable invariant as a fixture-backed test and
#: move the genuinely external audit into a job that reports ran / did-not-run with reasons.
#: Until then they are declared here, in the open, with the exact reason each one reports.
#:
#: Scope, measured rather than assumed: a full clean-clone run on 2026-09-13 (base 910bd00)
#: reported 1199 passed and ELEVEN skipped cases. The earlier note in the board named four;
#: that came from a focused three-file invocation, not the suite. The other seven had been
#: skipping in every CI run since they were written, with nothing reporting it.
_CI01 = "HYDRA-CI-01 (TEMPORARY): "
EXPECTED_CASE_SKIPS: dict[str, dict[str, str]] = {
    nodeid: dict(reason_contains=reason, policy=_CI01 + policy)
    for nodeid, reason, policy in (
        # --- the accreditation invariants, TASK-433 artefacts ---
        ("experiments/test_accredit_433.py::"
         "test_a_book_driven_on_another_panel_is_refused_by_name_of_the_input",
         "russell_prereg_cache/coverage.json",
         "needs the Russell coverage artefact, gitignored. The panel-swap refusal it pins "
         "is expressible on a synthetic panel and must become one."),
        ("experiments/test_accredit_433.py::"
         "test_an_unaccreditable_file_in_the_accredited_slot_stops_the_run_and_is_left_alone",
         "russell_prereg_cache/coverage.json",
         "same artefact. The never-overwrite invariant needs no real book."),
        ("experiments/test_accredit_433.py::"
         "test_reconcile_reports_the_historical_books_without_touching_them",
         "no historical books on this machine",
         "needs the historical books, which live only on the lab machine. Genuinely "
         "external: belongs in the real-book audit job, not in the required suite."),
        ("experiments/test_accredit_433.py::"
         "test_the_withdrawn_result_cannot_be_read_as_current",
         "task433_accredited.json",
         "needs the withdrawn artefact. The withdrawal contract is synthesisable."),
        # --- the lab-cache parity checks ---
        ("test_portfolio_engine.py::test_parity_stock_targets_with_redesign_lab",
         "experiments/_sweep_cache/",
         "engine-vs-lab parity needs the gitignored sweep cache. A small committed fixture "
         "would make the parity portable."),
        ("test_portfolio_engine.py::test_parity_etf_targets_with_sleeve_lab",
         "experiments/_sweep_cache/",
         "same cache, ETF side."),
        ("test_review_341.py::test_parity_stock_targets_reproduced",
         "experiments/_sweep_cache/",
         "same cache, TASK-341 reproduction."),
        ("test_render_evidence.py::"
         "test_the_reference_rows_are_what_reference_rows_py_measures",
         "sweep caches are gitignored",
         "the published reference rows cannot be re-measured on a fresh clone."),
        # --- checks that read the live or paper book ---
        ("test_backfill_sizing.py::test_real_20260910_sheet_matches_the_hand_figure",
         "paper book not on this disk",
         "reads state_paper/. Real-book audit, never a required check."),
        ("test_fill_cost_report.py::"
         "test_the_live_state_is_readable_and_still_has_nothing_to_measure",
         "no live state on this machine",
         "reads state/. Real-book audit, never a required check."),
        ("test_reset_ab.py::test_the_published_mix_already_had_cash_at_the_t_bill",
         "audit_steps.pkl",
         "needs a gitignored lab artefact from the A/B reset."),
    )
}


def run_suite(report_path: str, token: str) -> int:
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run(
        [sys.executable, "run_all_tests.py", "--strict-console",
         "--report", report_path, "--report-token", token],
        cwd=str(ROOT), text=True, encoding="utf-8", errors="replace",
        env=env, timeout=1800,
    )
    return r.returncode


def _check(report: dict) -> list[str]:
    """Every reason this run may not go green. Collected, not short-circuited."""
    problems: list[str] = []

    if report["exit_code"] != 0:
        problems.append(
            f"the run itself exited {report['exit_code']}; a non-zero suite can never "
            f"satisfy this gate")

    for f in report["files"]:
        name, status, mode = f["file"], f["status"], f["mode"]
        if status == RR.F_FAIL:
            problems.append(f"{name}: file FAILED ({f.get('note') or 'no detail'})")
        elif status == RR.F_SKIP and name not in EXPECTED_SKIPS:
            problems.append(f"{name}: whole file SKIPPED and not in EXPECTED_SKIPS")

        if mode == "pytest" and f["cases"] is None:
            # "no cases found" and "no cases skipped" must never look alike.
            problems.append(
                f"{name}: routed through pytest but the report carries NO case detail "
                f"({f.get('note') or 'no junit xml'}). Treated as a broken report, not as "
                f"an absence of skips.")

        for c in (f["cases"] or []):
            nodeid, outcome, reason = c["nodeid"], c["outcome"], c["reason"] or ""
            if outcome in RR.BAD_OUTCOMES:
                problems.append(f"{nodeid}: {outcome.upper()} - {reason or 'no detail'}")
            elif outcome == RR.SKIPPED:
                policy = EXPECTED_CASE_SKIPS.get(nodeid)
                if policy is None:
                    problems.append(
                        f"{nodeid}: SKIPPED and not declared. reason: "
                        f"{reason or 'no reason given'}")
                elif policy["reason_contains"] not in reason:
                    problems.append(
                        f"{nodeid}: SKIPPED for a reason the policy does not cover. "
                        f"declared {policy['reason_contains']!r}, reported {reason!r}")
    return problems


def _report_summary(report: dict) -> None:
    t = report["totals"]
    print(f"files : {t['files_pass']} pass, {t['files_skip']} skip, {t['files_fail']} fail")
    print(f"cases : {t['cases_passed']} passed, {t['cases_skipped']} skipped, "
          f"{t['cases_failed']} failed, {t['cases_error']} error")
    if t["files_without_case_detail"]:
        # Stated, not hidden: these files genuinely cannot report cases.
        print(f"        {t['files_without_case_detail']} file(s) run as scripts and report "
              f"one result each - no per-case truth exists for them")
    for f in report["files"]:
        if f["status"] == RR.F_SKIP:
            why = EXPECTED_SKIPS.get(f["file"], "UNEXPLAINED")
            print(f"  [file skip] {f['file']:<34} {why}")
        for c in (f["cases"] or []):
            if c["outcome"] == RR.SKIPPED:
                pol = EXPECTED_CASE_SKIPS.get(c["nodeid"])
                tag = pol["policy"] if pol else "UNDECLARED"
                print(f"  [case skip] {c['nodeid']}\n              reason: "
                      f"{c['reason'] or 'none given'}\n              policy: {tag}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="fail on undeclared skips, per file AND per case")
    ap.add_argument("--from-report", type=str, default=None,
                    help="gate an existing results report instead of running the suite")
    ap.add_argument("--expect-token", type=str, default=None,
                    help="require the report to carry this token, so a residual file from "
                         "an earlier run cannot satisfy the gate")
    ap.add_argument("--from-file", type=str, default=None,
                    help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.from_file:
        print("check_skips: --from-file parsed runner STDOUT and accepted an empty or "
              "truncated log as 'no skips' (measured 2026-09-13). Use --from-report with "
              "the JSON written by `run_all_tests.py --report`.")
        return 2

    tmp = None
    if args.from_report:
        path, expect = args.from_report, args.expect_token
    else:
        tmp = tempfile.mkdtemp(prefix="hydra-skipgate-")
        path = os.path.join(tmp, "run.json")
        expect = uuid.uuid4().hex
        run_suite(path, expect)          # the report carries the real exit code; read it there

    try:
        report = RR.read(path, expect_token=expect)
    except RR.ReportError as exc:
        print(f"check_skips FAILED: {exc}")
        return 1

    _report_summary(report)
    problems = _check(report)
    if problems:
        print(f"\ncheck_skips FAILED: {len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        print("\n      Declare the skip in EXPECTED_CASE_SKIPS with its nodeid, the reason "
              "it actually reports and the policy that allows it, or make the test run.")
        return 1

    print("\ncheck_skips ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
