"""The skip gate must be unable to go green without a real, complete measurement.

Every case below is a way the old gate DID go green. They are written as the failure they
reproduce, not as a description of the fix: each one fails on the pre-CI-02 code.

Measured on a clean checkout of `b85e9e4` before this change:
  * a file with a passed and a skipped case  -> runner headline "0 skipped", gate ok
  * `--from-file` on one line of arbitrary text -> "skips: 0 file(s) skipped", ok, exit 0
  * `--from-file` on an EMPTY file             -> ok, exit 0
  * `--from-file` on a log containing `[FAIL] test_everything.py (exit 1, 1.0s)` -> ok, exit 0
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))

import check_skips as CS  # noqa: E402
import results_report as RR  # noqa: E402

TOKEN = "token-for-this-invocation"


def _case(nodeid, outcome=RR.PASSED, reason=None):
    return dict(nodeid=nodeid, outcome=outcome, reason=reason)


def _report(files, *, exit_code=0, token=TOKEN, finished="2026-09-13T18:00:00+00:00"):
    rep = RR.build(files, exit_code=exit_code, token=token, argv=["run_all_tests.py"],
                   started_utc="2026-09-13T17:00:00+00:00", finished_utc=finished)
    return rep


def _write(tmp_path, report, name="run.json"):
    p = tmp_path / name
    p.write_text(json.dumps(report), encoding="utf-8")
    return str(p)


def _gate(path, token=TOKEN):
    return CS.main(["--from-report", path] + (["--expect-token", token] if token else []))


# --------------------------------------------------------------- the headline case (CI-02)

def test_a_file_with_one_passed_and_one_skipped_case_keeps_both(tmp_path, capsys):
    """The defect exactly: a PASSING file hiding a skipped case. The file total is not the case total."""
    files = [RR.file_record("test_mixed.py", "pytest", RR.F_PASS, 1.0, [
        _case("test_mixed.py::test_ok"),
        _case("test_mixed.py::test_needs_artifact", RR.SKIPPED, "artefact absent here"),
    ])]
    rep = _report(files)
    assert rep["totals"]["files_pass"] == 1, "the file still counts as passing"
    assert rep["totals"]["cases_skipped"] == 1, "and the skipped CASE survives in the report"

    assert _gate(_write(tmp_path, rep)) == 1
    out = capsys.readouterr().out
    assert "test_mixed.py::test_needs_artifact" in out, "the gate must name the case"
    assert "artefact absent here" in out, "and the reason it reported"


def test_an_undeclared_case_skip_fails_and_a_declared_one_passes(tmp_path, capsys):
    declared = next(iter(CS.EXPECTED_CASE_SKIPS))
    reason = CS.EXPECTED_CASE_SKIPS[declared]["reason_contains"]
    files = [RR.file_record("experiments/test_accredit_433.py", "pytest", RR.F_PASS, 1.0,
                            [_case(declared, RR.SKIPPED, f"...{reason}: absent here")])]
    assert _gate(_write(tmp_path, _report(files))) == 0
    assert "check_skips ok" in capsys.readouterr().out


def test_a_declared_case_that_skips_for_a_DIFFERENT_reason_is_not_covered(tmp_path, capsys):
    """The allowlist is nodeid + reason, so it cannot decay into a name-only exemption."""
    declared = next(iter(CS.EXPECTED_CASE_SKIPS))
    files = [RR.file_record("experiments/test_accredit_433.py", "pytest", RR.F_PASS, 1.0,
                            [_case(declared, RR.SKIPPED, "skipped because it was flaky")])]
    assert _gate(_write(tmp_path, _report(files))) == 1
    assert "the policy does not cover" in capsys.readouterr().out


def test_every_declared_policy_names_an_exact_nodeid_and_a_reason():
    """No directory or prefix wildcards: an exemption with no edge is not a policy."""
    for nodeid, pol in CS.EXPECTED_CASE_SKIPS.items():
        assert "::" in nodeid, f"{nodeid} is not a nodeid"
        assert "*" not in nodeid, f"{nodeid} is a wildcard, not an exact case"
        assert pol.get("reason_contains"), f"{nodeid} has no reason to match"
        assert pol.get("policy"), f"{nodeid} has no policy text"


def test_all_cases_skipped_in_a_file_still_fails_when_undeclared(tmp_path):
    files = [RR.file_record("test_all_skipped.py", "pytest", RR.F_PASS, 1.0, [
        _case("test_all_skipped.py::a", RR.SKIPPED, "no artefact"),
        _case("test_all_skipped.py::b", RR.SKIPPED, "no artefact"),
    ])]
    assert _gate(_write(tmp_path, _report(files))) == 1


# ------------------------------------------------- no measurement is never a green result

def test_a_failed_case_fails_the_gate(tmp_path, capsys):
    files = [RR.file_record("test_x.py", "pytest", RR.F_FAIL, 1.0,
                            [_case("test_x.py::test_a", RR.FAILED, "assert 1 == 2")])]
    assert _gate(_write(tmp_path, _report(files, exit_code=1))) == 1
    assert "exited 1" in capsys.readouterr().out


def test_a_collection_error_fails_the_gate(tmp_path, capsys):
    """An error is not 'did not run'. pytest reports it apart from a failing assertion."""
    files = [RR.file_record("test_x.py", "pytest", RR.F_FAIL, 0.1,
                            [_case("test_x.py::test_a", RR.ERROR, "ImportError: no module")])]
    assert _gate(_write(tmp_path, _report(files, exit_code=1))) == 1
    assert "ERROR" in capsys.readouterr().out


def test_a_pytest_file_with_no_case_detail_is_a_broken_report(tmp_path, capsys):
    """'no cases found' and 'no cases skipped' must not look alike."""
    files = [RR.file_record("test_x.py", "pytest", RR.F_PASS, 1.0, None,
                            note="junit xml unreadable")]
    assert _gate(_write(tmp_path, _report(files))) == 1
    assert "NO case detail" in capsys.readouterr().out


def test_a_missing_report_fails(tmp_path, capsys):
    assert _gate(str(tmp_path / "nope.json")) == 1
    assert "not found" in capsys.readouterr().out


def test_a_corrupt_report_fails(tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text("this is not json", encoding="utf-8")
    assert _gate(str(p)) == 1
    assert "unreadable" in capsys.readouterr().out


def test_an_empty_report_fails(tmp_path, capsys):
    """The exact shape that used to print `skips: 0 file(s) skipped` and exit 0."""
    p = tmp_path / "empty.json"
    p.write_text("", encoding="utf-8")
    assert _gate(str(p)) == 1
    assert "unreadable" in capsys.readouterr().out


def test_a_truncated_report_fails(tmp_path, capsys):
    rep = _report([])
    del rep["totals"]
    assert _gate(_write(tmp_path, rep)) == 1
    assert "incomplete" in capsys.readouterr().out


def test_a_run_that_never_finished_fails(tmp_path, capsys):
    rep = _report([], finished="")
    assert _gate(_write(tmp_path, rep)) == 1
    assert "finished_utc" in capsys.readouterr().out


def test_a_stale_report_from_another_run_fails(tmp_path, capsys):
    """Criterion 4: the report must belong to the invocation being judged."""
    rep = _report([RR.file_record("test_x.py", "pytest", RR.F_PASS, 1.0,
                                  [_case("test_x.py::test_a")])],
                  token="a-previous-run")
    assert _gate(_write(tmp_path, rep), token=TOKEN) == 1
    assert "different run" in capsys.readouterr().out


def test_a_nonzero_exit_cannot_be_argued_away_by_a_clean_case_list(tmp_path, capsys):
    """The saved output keeps its real exit code; --from-file used to force rc = 0."""
    files = [RR.file_record("test_x.py", "pytest", RR.F_PASS, 1.0,
                            [_case("test_x.py::test_a")])]
    assert _gate(_write(tmp_path, _report(files, exit_code=1))) == 1
    assert "exited 1" in capsys.readouterr().out


def test_the_stdout_scraping_entrypoint_is_gone(tmp_path, capsys):
    log = tmp_path / "fake.log"
    log.write_text("this is not a runner log at all\n", encoding="utf-8")
    assert CS.main(["--from-file", str(log)]) == 2
    assert "--from-report" in capsys.readouterr().out


# --------------------------------------------------------- declared granularity of scripts

def test_a_script_file_declares_that_it_has_no_case_detail(tmp_path, capsys):
    """Not a gap to paper over: script mode genuinely reports one result."""
    files = [RR.file_record("validate_pine_contract.py", "script", RR.F_PASS, 1.0, None,
                            note="script mode: reports one exit code")]
    rep = _report(files)
    assert rep["files"][0]["granularity"] == "file"
    assert rep["totals"]["files_without_case_detail"] == 1
    assert _gate(_write(tmp_path, rep)) == 0, "a script file is not treated as broken"
    assert "no per-case truth exists" in capsys.readouterr().out


def test_an_expected_whole_file_skip_still_passes_and_an_unexpected_one_does_not(tmp_path):
    ok = RR.file_record("test_hybrid_integration.py", "script", RR.F_SKIP, 1.0, None)
    assert _gate(_write(tmp_path, _report([ok]), "a.json")) == 0
    bad = RR.file_record("test_surprise.py", "script", RR.F_SKIP, 1.0, None)
    assert _gate(_write(tmp_path, _report([bad]), "b.json")) == 1


# ------------------------------------------------------------- the parser, against pytest

def test_junit_parsing_round_trips_a_real_pytest_run(tmp_path):
    """Not a mock: drive pytest and read what it actually writes."""
    t = tmp_path / "test_probe.py"
    t.write_text(
        "import pytest\n"
        "def test_ok(): assert True\n"
        "@pytest.mark.skipif(True, reason='artefact absent here')\n"
        "def test_skipped(): assert False\n",
        encoding="utf-8")
    xml = tmp_path / "out.xml"
    subprocess.run([sys.executable, "-m", "pytest", str(t), "-q",
                    "--junitxml", str(xml), "-p", "no:cacheprovider"],
                   capture_output=True, text=True, encoding="utf-8",
                   errors="replace", cwd=str(tmp_path), timeout=180)
    cases = RR.parse_junit(xml, "test_probe.py")
    by = {c["nodeid"]: c for c in cases}
    assert by["test_probe.py::test_ok"]["outcome"] == RR.PASSED
    skipped = by["test_probe.py::test_skipped"]
    assert skipped["outcome"] == RR.SKIPPED
    assert "artefact absent here" in (skipped["reason"] or "")


def test_the_runner_resolves_real_cases_for_a_pytest_routed_file(tmp_path):
    """One real file through the runner's own run_test, junit and all.

    Deliberately not via `--fast`: every CORE_TESTS file has a `__main__` guard and so runs
    in script mode, where no case detail exists by design. Asserting "cases > files" over
    that set would assert the opposite of what script mode means.
    """
    sys.path.insert(0, str(ROOT))
    import run_all_tests as R

    target = "test_write_barrier_armed.py"
    assert R._invocation(target)[1] == "pytest", "precondition: this file is pytest-routed"
    rec = R.run_test(target, junit_dir=str(tmp_path))
    assert rec["status"] == RR.F_PASS, rec.get("note")
    assert rec["granularity"] == "case"
    assert rec["cases"], "a pytest-routed file must resolve its cases"
    assert len(rec["cases"]) > 1
    assert all(c["nodeid"].startswith(target + "::") for c in rec["cases"])


def test_the_runner_writes_a_bound_report_with_the_real_exit_code(tmp_path):
    """End to end through run_all_tests.py itself, on a throwaway backup root."""
    env = dict(os.environ)
    env["HYDRA_BACKUP_DIR"] = str(tmp_path / "hydra-test-backup-probe")
    # Pin the child's console encoding. Under `--strict-console` the runner hands its own
    # children PYTHONIOENCODING=cp1252:strict, and this test would then be decoding cp1252
    # bytes as utf-8 - which is how it failed on CI while passing locally.
    env["PYTHONIOENCODING"] = "utf-8"
    report = tmp_path / "run.json"
    r = subprocess.run(
        [sys.executable, str(ROOT / "run_all_tests.py"), "--fast",
         "--report", str(report), "--report-token", "probe-token"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=str(ROOT), env=env, timeout=900)
    assert report.exists(), f"the runner wrote no report (exit {r.returncode})"
    rep = RR.read(report, expect_token="probe-token")
    assert rep["exit_code"] == r.returncode, "the report carries the real exit code"
    assert rep["totals"]["files_total"] >= 1
    assert "CASES:" in r.stdout, "the headline reports cases as well as files"
    # --fast selects CORE_TESTS, all of which are script-mode: the report must SAY that
    # rather than imply zero skipped cases.
    assert rep["totals"]["files_without_case_detail"] == rep["totals"]["files_total"]


def test_reading_a_report_with_the_wrong_schema_fails(tmp_path):
    rep = _report([])
    rep["schema"] = 99
    with pytest.raises(RR.ReportError, match="schema"):
        RR.read(_write(tmp_path, rep))
