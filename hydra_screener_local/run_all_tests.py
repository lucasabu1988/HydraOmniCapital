"""
One-command runner for all HYDRA test files (contract, golden, integration, logic).

Usage:
    python run_all_tests.py
    python run_all_tests.py --fast          # skip heavy/long tests
    python run_all_tests.py --verbose       # show more output per test

Exit code 0 if all pass, 1 if any fail.
"""

import argparse
import datetime
import glob
import json
import os
import re
import atexit
import shutil
import subprocess
import tempfile
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "tools"))
import results_report as RR  # noqa: E402

# Captured test output is UTF-8, but this runner's own console may be cp1252
# (default Windows console). Printing a char like the check mark then raises
# UnicodeEncodeError, which used to be caught below and misreported as a test
# failure. Degrade unencodable chars instead of blowing up.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - non-standard stream
        pass

# Core tests that should always run
CORE_TESTS = [
    "test_spec_compliance.py",
    "test_generate_pine_watchlist.py",
    "test_hybrid_integration.py",
]

# Additional / moved tests (include via auto-discovery or explicit)
ADDITIONAL_TESTS = [
    "experiments/test_screener_logic.py",
    "validate_pine_contract.py",  # B3 contract validator for Pine parser vs summary JSON
]

def discover_tests() -> list[str]:
    """Auto-discover test_*.py in root, experiments/ and tools/ (excluding __pycache__ etc).

    tools/ was missing from this list, so tools/test_write_isolation.py - the only coverage of
    the write barrier - never ran in CI at all from the commit that added it.
    """
    found = []
    for pattern in ["test_*.py", "experiments/test_*.py", "tools/test_*.py"]:
        for f in glob.glob(pattern):
            if f not in found and not f.startswith("__"):
                found.append(f.replace("\\", "/"))
    # Files whose names do not match the glob (the Pine contract validator) used to be listed
    # in ADDITIONAL_TESTS but never discovered -- a check that silently never ran (audit, step 4).
    for t in ADDITIONAL_TESTS:
        if t not in found and (ROOT / t).exists():
            found.append(t)
    # Ensure order: core first, then additional
    ordered = []
    for t in CORE_TESTS + ADDITIONAL_TESTS:
        if t in found:
            ordered.append(t)
            found.remove(t)
    ordered.extend(sorted(found))
    return ordered

# --------------------------------------------------------------------------------------------
# SAFE-04: arm the barrier in the CHILDREN too.
#
# `write_isolation` patches one process. Nine files here run as SCRIPTS, and a script loads no
# conftest, so those children had no barrier at all: measured on 27afcf8, the parent refused a
# write to a decoy and its child performed the same write and exited 0.
#
# The roots are resolved HERE, at import time, for two reasons. `repo_evidence_roots()` reads
# HYDRA_BACKUP_DIR from the environment, and `test_backup_dir()` below rebinds it to a
# throwaway - resolving afterwards would hand the children the disposable directory and leave
# the real one open. And `screener=ROOT` is passed explicitly so the answer does not depend on
# the cwd the runner happened to be launched from.
# --------------------------------------------------------------------------------------------
BOOTSTRAP_DIR = str(ROOT / "tools" / "_bootstrap")
EXIT_BOOTSTRAP_FAILED = 97


def real_evidence_roots() -> list[str]:
    """Evidence roots as they are BEFORE any test redirect, minus disposable destinations."""
    try:
        import write_isolation as _WI
    except Exception as exc:                       # noqa: BLE001 - reported, then fatal below
        print(f"[runner] cannot import write_isolation: {exc!r}", file=sys.stderr)
        return None
    roots = _WI.repo_evidence_roots(screener=str(ROOT))
    return [r for r in roots if TEST_BACKUP_MARKER not in r.lower()]


def build_child_env(base: dict) -> dict:
    """Environment that arms tools/_bootstrap/sitecustomize.py in the child.

    The child resolves the repo-local evidence directories ITSELF, at its own start: this
    runner resolves its list once at import, and on a clean checkout `experiments/_lab_scratch/`
    does not exist yet - an earlier test file creates it, and a later child would then run
    beside a real evidence directory the frozen list never mentioned. Measured on a clean clone.

    The backup root is the exception and the reason the parent is involved at all: by the time
    a child starts, `test_backup_dir()` has rebound HYDRA_BACKUP_DIR to a throwaway, so the
    real value has to be captured here, before that, and handed over.
    """
    env = dict(base)
    env["HYDRA_WRITE_BARRIER"] = "1"
    env["HYDRA_SCREENER_DIR"] = str(ROOT)
    env["HYDRA_WRITE_BARRIER_BACKUP_ROOT"] = _REAL_BACKUP_ROOT or ""
    env.pop("HYDRA_WRITE_BARRIER_ROOTS", None)   # the child resolves; tests override explicitly
    prior = env.get("PYTHONPATH", "")
    if BOOTSTRAP_DIR not in prior.split(os.pathsep):
        env["PYTHONPATH"] = BOOTSTRAP_DIR + (os.pathsep + prior if prior else "")
    return env


def canary(env: dict) -> tuple[bool, str]:
    """Prove the bootstrap is live in a child of THIS invocation, before trusting it.

    A missing `sitecustomize` is silent: PYTHONPATH can be stripped, or the interpreter
    started with -S or -E, and nothing would say so. So one child is asked to report what it
    sees, and the suite does not start if the answer is wrong.
    """
    probe = (
        "import json,sys,os;"
        "sys.path.insert(0, os.environ['HYDRA_BARRIER_TOOLS']);"
        "import write_isolation as W;"
        "print(json.dumps({'installed': W.is_installed(), 'roots': W.protected_roots()}))"
    )
    env = dict(env, HYDRA_BARRIER_TOOLS=str(ROOT / "tools"))
    r = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env, cwd=str(ROOT), timeout=120)
    if r.returncode != 0:
        return False, f"canary exited {r.returncode}: {(r.stderr or '').strip()[:300]}"
    try:
        seen = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as exc:                       # noqa: BLE001
        return False, f"canary output unreadable ({exc}): {r.stdout.strip()[:200]!r}"
    if not seen.get("installed"):
        return False, "the child reported the barrier NOT installed"
    got = [r for r in seen.get("roots", [])]
    for r in got:
        if TEST_BACKUP_MARKER in r.lower():
            return False, f"a child is protecting a throwaway backup dir as evidence: {r}"
    if _REAL_BACKUP_ROOT and not any(
            os.path.normcase(r) == os.path.normcase(_REAL_BACKUP_ROOT) for r in got):
        return False, ("the child did not arm the real backup root "
                       f"{_REAL_BACKUP_ROOT!r}; it would be writable")
    return True, f"{len(got)} root(s) armed in children"


#: Marks a throwaway backup destination; conftest.py uses the same marker.
TEST_BACKUP_MARKER = "hydra-test-backup"
_TEST_BACKUP_DIR = None

#: Resolved once, at import, BEFORE test_backup_dir() rebinds HYDRA_BACKUP_DIR.
#: None means write_isolation could not be imported at all - a hard stop, not a warning.
_REAL_ROOTS = real_evidence_roots()

#: The backup root as it is on this machine, captured before any redirect. The children
#: cannot work this out for themselves once the variable has been rebound.
_REAL_BACKUP_ROOT = (os.environ.get("HYDRA_BACKUP_DIR") or "")     if TEST_BACKUP_MARKER not in (os.environ.get("HYDRA_BACKUP_DIR") or "").lower() else ""

#: A REAL main guard, not the string "__main__" anywhere in the file. The substring test
#: sent every pytest module whose docstring merely mentions __main__ (nine of them on the
#: 2026-09-10 consolidation tree: settle_driver, macro_valuation, fill_cost_report, metrics,
#: path_momentum, reset_ab, sector_exposure_post_carry, whole_share_sizing, build_russell_pit)
#: down the script path, where their test_ functions never ran and the file was reported
#: [PASS]; they were also missing from the coverage invocation. Same regex as ASTRA-04.
MAIN_GUARD_RE = re.compile(r"^\s*if\s+__name__\s*==\s*[\"']__main__[\"']", re.MULTILINE)


def _invocation(test_file: str) -> tuple[list[str], str]:
    """How to run this file, and why.

    Files here come in two shapes: scripts that assert inside a `__main__` block, and
    pytest-style modules that only define `test_*` functions. Running the second shape
    as a script executes nothing and exits 0, which the runner used to report as [PASS] --
    a green light for assertions that never ran. Route those through pytest instead.
    """
    path = ROOT / test_file
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [sys.executable, str(path)], "script"
    has_main = MAIN_GUARD_RE.search(src) is not None
    has_tests = re.search(r"^def test_", src, re.MULTILINE) is not None
    if has_tests and not has_main:
        return [sys.executable, "-m", "pytest", str(path), "-q"], "pytest"
    return [sys.executable, str(path)], "script"


def test_backup_dir() -> str:
    """One throwaway HYDRA_BACKUP_DIR for the whole suite run.

    The variable is a USER variable on this machine and every write path reads it from the
    environment, so an inherited value points test writes at the production backup root — that is
    how the only off-disk copies of the live book became fixtures (2026-09-06). conftest.py covers
    pytest-routed files; files run as SCRIPTS never load a conftest, so the boundary has to be here.
    """
    global _TEST_BACKUP_DIR
    if _TEST_BACKUP_DIR is None:
        _TEST_BACKUP_DIR = tempfile.mkdtemp(prefix=f"{TEST_BACKUP_MARKER}-")
        atexit.register(shutil.rmtree, _TEST_BACKUP_DIR, True)
    return _TEST_BACKUP_DIR


def run_test(test_file: str, verbose: bool = False, extra_env: dict | None = None,
             junit_dir: str | None = None) -> dict:
    """Run one file and return its record (see tools/results_report.py).

    A pytest-routed file also writes a JUnit XML so the per-CASE outcomes survive: the
    stdout tail cannot carry them, and a skipped case inside a passing file is exactly
    what the old file-level report lost.
    """
    cmd, how = _invocation(test_file)
    junit_path = None
    if junit_dir and how == "pytest":
        slug = test_file.replace("/", "__").replace("\\", "__")
        junit_path = os.path.join(junit_dir, slug + ".xml")
        cmd = cmd + ["--junitxml", junit_path]
    suffix = "" if how == "script" else f"  [via {how}]"
    print(f"\n=== {test_file} ==={suffix}")
    start = time.perf_counter()
    env = build_child_env(os.environ)
    env["HYDRA_BACKUP_DIR"] = test_backup_dir()
    if extra_env:
        env.update(extra_env)
    # Only the subprocess call is guarded: a failure while printing the report
    # is a runner bug, not a test failure, and must not be swallowed here.
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            env=env,
        )
    except subprocess.TimeoutExpired:
        duration = time.perf_counter() - start
        print(f"[TIMEOUT] {test_file} after {duration:.1f}s")
        return _record(test_file, how, "fail", duration, None,
                       note=f"timed out after {duration:.1f}s; no report was produced")
    except OSError as e:
        duration = time.perf_counter() - start
        print(f"[ERROR] running {test_file}: {e} ({duration:.2f}s)")
        return _record(test_file, how, "fail", duration, None,
                       note=f"could not be launched: {e}")

    duration = time.perf_counter() - start
    output = (result.stdout + result.stderr).strip()
    # A failing file prints in full: the 6-line tail hides every failure but the last,
    # so a red run named one test out of twelve. Passing files stay on the tail.
    if verbose or result.returncode != 0:
        print(output)
    else:
        lines = output.splitlines()
        for line in lines[-6:]:
            print(line)
    # Whole-file skip: a [SKIP] line and no overall-pass banner (a file may skip one
    # sub-check and still pass). Hybrid integration is the case this exists for.
    skipped = (
        result.returncode == 0
        and re.search(r"^\[SKIP\]", output, re.M)
        and not re.search(r"ALL .+ PASSED", output)
    )
    if skipped:
        print(f"[SKIP] {test_file} ({duration:.2f}s)")
        return _record(test_file, how, "skip", duration, junit_path)
    if result.returncode == 0:
        print(f"[PASS] {test_file} ({duration:.2f}s)")
        return _record(test_file, how, "pass", duration, junit_path)
    if result.returncode == EXIT_BOOTSTRAP_FAILED:
        print(f"[FAIL] {test_file}: the write-isolation bootstrap refused to arm; the file\n               was NOT run. This is a broken barrier, not a failing test.")
        return _record(test_file, how, "fail", duration, junit_path,
                       note="write-isolation bootstrap failed; the file did not run")
    print(f"[FAIL] {test_file} (exit {result.returncode}, {duration:.2f}s)")
    return _record(test_file, how, "fail", duration, junit_path,
                   note=f"exit {result.returncode}")


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _record(test_file: str, how: str, status: str, duration: float,
            junit_path: str | None, note: str | None = None) -> dict:
    """Turn one run into a record, reading the JUnit XML when pytest produced one.

    A pytest file whose XML is missing or unparseable gets `cases=None` and says so. That
    is deliberately NOT silent: check_skips treats a pytest file with no case detail as a
    broken report, because "no cases found" and "no cases skipped" must never look alike.
    """
    cases = None
    if junit_path and how == "pytest":
        try:
            cases = RR.parse_junit(junit_path, test_file)
        except Exception as exc:                      # noqa: BLE001 - recorded, not raised
            note = (note + "; " if note else "") + f"junit xml unreadable: {exc}"
    if how == "script":
        note = (note + "; " if note else "") + 'script mode: the file asserts inside a __main__ block and reports one exit code, so no per-case outcomes exist for it'
    return RR.file_record(test_file, how, status, duration, cases, note)


def main():
    parser = argparse.ArgumentParser(description="HYDRA Screener - All Tests Runner")
    parser.add_argument("--fast", action="store_true", help="Skip heavy/long tests (contract tests only)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show full output for each test")
    parser.add_argument("--list", action="store_true", help="Just list discovered tests and exit")
    parser.add_argument("--cov", action="store_true",
                        help="report-only coverage over core, data, utils, sleeves (no floor)")
    parser.add_argument("--strict-console", action="store_true",
                        help="run children with PYTHONIOENCODING=cp1252:strict (Windows console)")
    parser.add_argument("--report", type=str, default=None,
                        help="write per-CASE results as JSON here (tools/check_skips.py reads it)")
    parser.add_argument("--report-token", type=str, default=None,
                        help="stamp the report with this token so a consumer can bind it "
                             "to THIS invocation and reject a residual file")
    args = parser.parse_args()

    test_files = discover_tests()
    if args.fast:
        test_files = [t for t in test_files if t in CORE_TESTS]

    if args.list:
        print("Discovered tests:")
        for t in test_files:
            print(f"  - {t}")
        return 0

    print("HYDRA Screener - All Tests Runner")
    print("=" * 50)
    if args.fast:
        print("(FAST mode: core contract tests only)")
    extra_env = {"PYTHONIOENCODING": "cp1252:strict"} if args.strict_console else None
    if args.strict_console:
        print("(strict-console: PYTHONIOENCODING=cp1252:strict)")
    print()

    if _REAL_ROOTS is None:
        print("[runner] write_isolation is not importable: refusing to run the suite "
              "unprotected (SAFE-04).")
        return EXIT_BOOTSTRAP_FAILED
    ok, detail = canary(build_child_env(os.environ))
    if not ok:
        print(f"[runner] write-isolation bootstrap check FAILED: {detail}")
        print("[runner] children would run unprotected; refusing to start (SAFE-04).")
        return EXIT_BOOTSTRAP_FAILED
    print(f"(write isolation: {detail})")

    passed = 0
    skipped = 0
    failed = []
    total_time = 0.0
    records: list[dict] = []
    started_utc = _utc_now()
    junit_dir = tempfile.mkdtemp(prefix="hydra-junit-") if args.report else None
    if junit_dir:
        atexit.register(shutil.rmtree, junit_dir, True)
    start_all = time.perf_counter()

    for t in test_files:
        rec = run_test(t, verbose=args.verbose, extra_env=extra_env, junit_dir=junit_dir)
        records.append(rec)
        status, dur = rec["status"], rec["duration"]
        total_time += dur
        if status == "pass":
            passed += 1
        elif status == "skip":
            skipped += 1
        else:
            failed.append(t)

    elapsed = time.perf_counter() - start_all
    print("\n" + "=" * 50)
    tally = RR._tally(records)
    print(f"RESULTS: {passed} passed, {skipped} skipped in {elapsed:.2f}s "
          f"(tests time: {total_time:.2f}s)")
    # Files are not cases. The old headline counted files only, so four skipped cases
    # inside passing files were reported as "0 skipped".
    print(f"CASES:   {tally['cases_passed']} passed, {tally['cases_skipped']} skipped, "
          f"{tally['cases_failed']} failed, {tally['cases_error']} error "
          f"({tally['files_without_case_detail']} file(s) report no case detail)")
    for _f in records:
        for _c in (_f["cases"] or []):
            if _c["outcome"] == RR.SKIPPED:
                print(f"  [SKIPPED CASE] {_c['nodeid']} :: {_c['reason'] or 'no reason given'}")
    def _finish(code: int) -> int:
        """Write the report before returning, whatever the outcome.

        A red run needs its report MORE than a green one: the gate has to be able to
        see a failure or a collection error rather than find no file and guess.
        """
        if args.report:
            rep = RR.build(records, exit_code=code, token=args.report_token,
                           argv=sys.argv, started_utc=started_utc,
                           finished_utc=_utc_now())
            print(f"report: {RR.write(rep, args.report)}")
        return code

    if failed:
        print("Failed tests:")
        for f in failed:
            print(f"  - {f}")
        return _finish(1)
    if skipped:
        print("No failures (skips are not passes).")
    else:
        print("All tests passed!")

    _print_ruff_summary()

    if args.cov:
        cov_rc = _run_coverage()
        if cov_rc != 0 and not failed:
            return _finish(cov_rc)
    return _finish(0)


def _print_ruff_summary() -> None:
    """Report-only ruff line; never fails the suite (TASK-372)."""
    tests = sorted(p.name for p in ROOT.glob("test_*.py"))
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--config", str(ROOT / "ruff.toml"),
             "core", "data", "utils", "sleeves",
             "portfolio_v9.py", "daily.py", "dashboard_v9.py", "preflight.py",
             "reconcile.py", "confirm_fills.py", "journal.py", "store_cli.py",
             "evidence_review.py", "warm_sectors.py", "send_hydra_summary.py",
             "snapshot_universe.py", "verify_state.py",
             "runlog_cli.py", "reprint_sheet.py", *tests],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except OSError:
        print("ruff: not installed (pip install -r requirements-dev.txt)")
        return
    out = (result.stdout or "") + (result.stderr or "")
    summary = [ln for ln in out.splitlines() if "Found" in ln or "All checks passed" in ln]
    line = summary[-1] if summary else ("ruff exit " + str(result.returncode))
    print("ruff (report-only):", line)


def _run_coverage() -> int:
    """Report-only coverage over core/ data/ utils/ sleeves/. No fail-under floor."""
    print("\n" + "=" * 50)
    print("COVERAGE (report-only; floor is Claude's call)")
    try:
        import pytest_cov  # noqa: F401
    except ImportError:
        print("pytest-cov not installed. pip install -r requirements-dev.txt")
        return 1
    xml_path = ROOT / "coverage.xml"
    pytest_files = []
    for t in discover_tests():
        _cmd, how = _invocation(t)
        if how == "pytest":
            pytest_files.append(str(ROOT / t))
    cmd = [
        sys.executable, "-m", "pytest",
        "--cov=core", "--cov=data", "--cov=utils", "--cov=sleeves",
        "--cov-report=term",
        f"--cov-report=xml:{xml_path}",
        "-q", "--tb=no",
        *pytest_files,
    ]
    print("coverage over", len(pytest_files), "pytest files")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if xml_path.exists():
        print(f"coverage XML: {xml_path}")
    return 0 if result.returncode == 0 else result.returncode

if __name__ == "__main__":
    sys.exit(main())
