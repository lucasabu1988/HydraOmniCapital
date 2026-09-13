"""Per-CASE test results, not just per-file. The contract `check_skips.py` gates on.

Why this module exists
----------------------
`run_all_tests.py` reported one status per FILE, and `check_skips.py` gated by scraping
that stdout. pytest can skip individual cases inside a file that otherwise passes, so on
2026-09-13, on a clean checkout of `b85e9e4`:

    python -m pytest test_write_barrier_armed.py tools/test_write_isolation.py \
                     experiments/test_accredit_433.py -q -rs
    -> 21 passed, 4 skipped

while the runner headline for those files said `0 skipped` and the gate reported
`skips: 0 file(s) skipped ... check_skips ok`. Four assertions did not run and nothing said
so. Number of FILES is not number of CASES, and `0 skipped` was never a claim about cases.

Scraping stdout had a second failure, reproduced on the same tree: `check_skips.py
--from-file` set `rc = 0` unconditionally and treated a missing `RESULTS:` line as "no
information" rather than as a broken report. A file containing one line of arbitrary text,
an empty file, and a log whose own body read `[FAIL] test_everything.py (exit 1, 1.0s)` all
produced `check_skips ok`, exit 0.

So results travel as DATA, with the invocation that produced them, and the gate reads that
data instead of prose.

Granularity is declared, never assumed
--------------------------------------
`run_all_tests.py` routes a file through pytest only when it defines `test_*` functions and
has no `__main__` guard; everything else runs as a script. A script reports one exit code
and nothing finer, so its record carries `granularity="file"` and `cases=None`. That is a
stated limit, not a gap to paper over with an invented per-assertion count: a consumer can
see exactly which files it has case-level truth for.
"""
from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SCHEMA = 1

#: Outcomes a case can carry. `error` is a collection/setup failure, which pytest reports
#: separately from a failing assertion and which must never be read as "did not run".
PASSED, SKIPPED, FAILED, ERROR = "passed", "skipped", "failed", "error"
BAD_OUTCOMES = (FAILED, ERROR)

#: File-level statuses produced by the runner.
F_PASS, F_SKIP, F_FAIL = "pass", "skip", "fail"


class ReportError(Exception):
    """The report cannot be trusted to describe a real run."""


def parse_junit(xml_path: str | os.PathLike, test_file: str) -> list[dict]:
    """Cases from one pytest `--junitxml` file.

    The nodeid is rebuilt as `<test_file>::<name>` from the file the runner actually
    launched, rather than from the XML's dotted `classname`: with the default junit family
    pytest emits no `file` attribute, and a dotted module path cannot be turned back into a
    path unambiguously. The runner knows the file exactly, so it supplies it.
    """
    root = ET.parse(os.fspath(xml_path)).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    cases: list[dict] = []
    for suite in suites:
        for tc in suite.iter("testcase"):
            name = tc.attrib.get("name", "")
            outcome, reason = PASSED, None
            for child in tc:
                if child.tag == "skipped":
                    outcome = SKIPPED
                    reason = child.attrib.get("message") or (child.text or "").strip()
                elif child.tag == "failure":
                    outcome = FAILED
                    reason = child.attrib.get("message") or (child.text or "").strip()
                elif child.tag == "error":
                    outcome = ERROR
                    reason = child.attrib.get("message") or (child.text or "").strip()
            cases.append(dict(nodeid=f"{test_file}::{name}", outcome=outcome,
                              reason=(reason or None)))
    return cases


def file_record(test_file: str, mode: str, status: str, duration: float,
                cases: list[dict] | None, note: str | None = None) -> dict:
    """One file's record. `cases is None` means the mode cannot report cases at all."""
    return dict(
        file=test_file,
        mode=mode,
        status=status,
        duration=round(float(duration), 3),
        granularity=("case" if cases is not None else "file"),
        cases=cases,
        note=note,
    )


def _tally(files: list[dict]) -> dict:
    t = dict(files_total=len(files), files_pass=0, files_skip=0, files_fail=0,
             cases_total=0, cases_passed=0, cases_skipped=0, cases_failed=0, cases_error=0,
             files_without_case_detail=0)
    for f in files:
        t[{F_PASS: "files_pass", F_SKIP: "files_skip"}.get(f["status"], "files_fail")] += 1
        if f["cases"] is None:
            t["files_without_case_detail"] += 1
            continue
        for c in f["cases"]:
            t["cases_total"] += 1
            t[{PASSED: "cases_passed", SKIPPED: "cases_skipped",
               FAILED: "cases_failed", ERROR: "cases_error"}[c["outcome"]]] += 1
    return t


def build(files: list[dict], *, exit_code: int, token: str | None,
          argv: list[str], started_utc: str, finished_utc: str) -> dict:
    return dict(
        schema=SCHEMA,
        token=token,
        exit_code=int(exit_code),
        invocation=dict(argv=list(argv), cwd=os.getcwd(),
                        python=sys.version.split()[0],
                        started_utc=started_utc, finished_utc=finished_utc),
        totals=_tally(files),
        files=files,
    )


def write(report: dict, path: str | os.PathLike) -> str:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)
    return str(p)


def read(path: str | os.PathLike, *, expect_token: str | None = None) -> dict:
    """Load a report, or raise. Every failure here is a HARD one, by design.

    A missing, unparseable, truncated or foreign report is not "no skips found" - it is an
    absent measurement, and the gate must be unable to go green on one. `expect_token` binds
    the report to the invocation being judged, so a residual file from an earlier run is
    rejected instead of satisfying the gate.
    """
    p = Path(path)
    if not p.exists():
        raise ReportError(f"results report not found: {p}")
    try:
        report = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReportError(
            f"results report unreadable ({type(exc).__name__}: {exc}): {p}") from exc
    if not isinstance(report, dict):
        raise ReportError(f"results report is not an object: {p}")
    if report.get("schema") != SCHEMA:
        raise ReportError(f"results report schema {report.get('schema')!r} != {SCHEMA}: {p}")
    for key in ("exit_code", "files", "totals", "invocation"):
        if key not in report:
            raise ReportError(f"results report is incomplete, missing {key!r}: {p}")
    if not isinstance(report["files"], list):
        raise ReportError(f"results report 'files' is not a list: {p}")
    if not report["invocation"].get("finished_utc"):
        raise ReportError(
            f"results report has no finished_utc - the run did not complete, so it cannot "
            f"be used as evidence: {p}")
    if expect_token is not None and report.get("token") != expect_token:
        raise ReportError(
            f"results report token {report.get('token')!r} does not match the invocation "
            f"being judged ({expect_token!r}). This report describes a different run: {p}")
    return report
