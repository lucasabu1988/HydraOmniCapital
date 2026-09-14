"""The external-audit contract, as REQUIRED tests. Portable: no private artefact anywhere.

`tools/external_audit.py` is the half of HYDRA-CI-01 that takes the checks which genuinely need
the lab machine out of the required suite. That move is only safe while three things hold, and
none of them is self-enforcing:

  1. nothing in `audits/` can quietly stop being registered, or stop existing;
  2. nothing in `audits/` can skip - a skip there would rebuild the exact hole this replaced;
  3. a missing artefact must produce DID NOT RUN with the path, never a pass, and a failing or
     unreported audit must produce a non-zero exit.

So the registry is cross-checked against the files by parsing them, and the runner's decision
table is exercised on synthetic audit files built in tmp_path.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for _p in (str(ROOT), str(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import external_audit as EA  # noqa: E402

AUDIT_FILES = sorted(p.name for p in (ROOT / "audits").glob("audit_*.py"))


def _functions(path: Path) -> list:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [n.name for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test_")]


# ------------------------------------------------------------------ the registry and the files
def test_there_are_audit_files_at_all():
    """A registry checked against an empty directory would pass every test below."""
    assert AUDIT_FILES, "audits/ holds no audit_*.py; the external audit path is not wired up"
    assert EA.REGISTRY, "the registry is empty"


def test_every_registered_nodeid_resolves_to_a_real_function():
    for case in EA.REGISTRY:
        rel, _, func = case["nodeid"].partition("::")
        path = ROOT / rel
        assert path.exists(), f"{case['id']}: {rel} does not exist"
        assert func in _functions(path), f"{case['id']}: {rel} has no function {func!r}"


def test_every_audit_function_is_registered():
    """The direction that actually rots: a new audit lands in the file and nothing runs it."""
    registered = {c["nodeid"] for c in EA.REGISTRY}
    orphans = []
    for name in AUDIT_FILES:
        for func in _functions(ROOT / "audits" / name):
            nodeid = f"audits/{name}::{func}"
            if nodeid not in registered:
                orphans.append(nodeid)
    assert not orphans, (
        "these audit functions are in audits/ but in no registry entry, so nothing would ever "
        f"run them and nothing would report that they did not run: {orphans}")


def test_audit_function_names_are_unique_across_the_directory():
    """The runner keys junit results by function name; a collision would resolve to the wrong case."""
    seen: dict = {}
    for name in AUDIT_FILES:
        for func in _functions(ROOT / "audits" / name):
            seen.setdefault(func, []).append(name)
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    assert not dupes, f"duplicate audit function names across audits/: {dupes}"


def test_no_audit_file_can_skip():
    """A skip inside an audit is indistinguishable from a satisfied assertion. Ban it at the source."""
    banned = ("pytest.skip", "pytest.importorskip", "skipif", "pytest.xfail")
    problems = []
    for name in AUDIT_FILES:
        src = (ROOT / "audits" / name).read_text(encoding="utf-8")
        tree = ast.parse(src, filename=name)
        for node in ast.walk(tree):
            text = None
            if isinstance(node, ast.Call):
                text = ast.unparse(node.func)
            elif isinstance(node, ast.Attribute):
                text = ast.unparse(node)
            if text and any(b in text for b in banned):
                problems.append(f"{name}:{getattr(node, 'lineno', '?')} {text}")
    assert not problems, (
        "audits/ must not skip; the artefact gate belongs to tools/external_audit.py, which "
        f"reports DID NOT RUN with the missing path: {problems}")


def test_every_registered_case_declares_what_it_needs_and_why_it_is_external():
    for case in EA.REGISTRY:
        assert case["requires"], f"{case['id']}: an audit that requires nothing is not external"
        for label, path in case["requires"].items():
            assert os.path.isabs(path), f"{case['id']}: {label} is not an absolute path: {path}"
        assert case["claims"].strip(), f"{case['id']}: no claim stated"
        assert case["why_external"].strip(), f"{case['id']}: no reason it cannot be portable"


def test_registry_ids_are_unique():
    ids = [c["id"] for c in EA.REGISTRY]
    assert len(set(ids)) == len(ids), f"duplicate registry ids: {ids}"


# ------------------------------------------------------------------ audits stay OUT of the suite
def test_the_required_runner_does_not_discover_the_audits():
    """`run_all_tests.py` globs test_*.py in the root, experiments/ and tools/ - never audits/.

    If that ever changes, the audits would run as required tests on a clean clone and fail on
    missing artefacts - which is a different wrong answer, not a better one.
    """
    sys.path.insert(0, str(ROOT))
    import run_all_tests  # noqa: PLC0415

    cwd = os.getcwd()
    os.chdir(str(ROOT))
    try:
        discovered = run_all_tests.discover_tests()
    finally:
        os.chdir(cwd)
    leaked = [t for t in discovered if t.replace("\\", "/").startswith("audits/")]
    assert not leaked, f"the required runner discovered external audits: {leaked}"


def test_the_audits_are_not_named_like_required_tests():
    """Belt and braces: the glob is `test_*.py`, so an audit must not be called that."""
    bad = [p.name for p in (ROOT / "audits").glob("test_*.py")]
    assert not bad, f"these would be discovered by pytest's default collection too: {bad}"


# ------------------------------------------------------------------ the runner's decision table
AUDIT_SRC = {
    "passes": "def test_synthetic_pass():\n    assert True\n",
    "fails": "def test_synthetic_fail():\n    assert False, 'the synthetic audit failed on purpose'\n",
    "skips": ("import pytest\n\n\n"
              "def test_synthetic_skip():\n"
              "    pytest.skip('a skip inside an audit must never read as a pass')\n"),
}


def _synthetic(tmp_path, kind: str, requires: dict) -> dict:
    """One registry case pointing at a throwaway audit file under tmp_path."""
    path = tmp_path / f"audit_synthetic_{kind}.py"
    path.write_text(AUDIT_SRC[kind], encoding="utf-8")
    func = f"test_synthetic_{ {'passes': 'pass', 'fails': 'fail', 'skips': 'skip'}[kind] }"
    return dict(id=f"synthetic.{kind}", nodeid=f"{path}::{func}", requires=requires,
                claims=f"synthetic {kind}", why_external="synthetic")


def test_a_missing_artifact_is_did_not_run_and_names_the_path(tmp_path, monkeypatch):
    gone = str(tmp_path / "not_here" / "book.pkl")
    case = _synthetic(tmp_path, "passes", {"the book": gone})
    monkeypatch.setattr(EA, "REGISTRY", (case,))
    report = EA.evaluate()
    r = report["results"][0]
    assert r["status"] == EA.DID_NOT_RUN
    assert r["missing"] == {"the book": gone}
    assert gone in r["detail"], "the report must name the exact path that was not found"
    assert report["totals"] == dict(total=1, ran_pass=0, ran_fail=0, did_not_run=1)
    assert report["host_has_artifacts"] is False


def test_a_missing_artifact_never_counts_as_a_pass(tmp_path, monkeypatch):
    """The whole point. Absence of evidence must not be reported as evidence."""
    case = _synthetic(tmp_path, "passes", {"the book": str(tmp_path / "nope.pkl")})
    monkeypatch.setattr(EA, "REGISTRY", (case,))
    report = EA.evaluate()
    assert report["totals"]["ran_pass"] == 0
    assert EA.RAN_PASS not in {r["status"] for r in report["results"]}


def test_a_present_artifact_runs_the_audit_and_reports_pass(tmp_path, monkeypatch):
    present = tmp_path / "book.pkl"
    present.write_bytes(b"x")
    case = _synthetic(tmp_path, "passes", {"the book": str(present)})
    monkeypatch.setattr(EA, "REGISTRY", (case,))
    report = EA.evaluate()
    assert report["results"][0]["status"] == EA.RAN_PASS
    assert report["totals"] == dict(total=1, ran_pass=1, ran_fail=0, did_not_run=0)
    assert report["host_has_artifacts"] is True


def test_a_failing_audit_is_ran_fail(tmp_path, monkeypatch):
    present = tmp_path / "book.pkl"
    present.write_bytes(b"x")
    case = _synthetic(tmp_path, "fails", {"the book": str(present)})
    monkeypatch.setattr(EA, "REGISTRY", (case,))
    report = EA.evaluate()
    assert report["results"][0]["status"] == EA.RAN_FAIL
    assert "failed on purpose" in (report["results"][0]["detail"] or ""), (
        "a failing audit must carry the reason it failed, not just a status")


def test_a_skipped_case_inside_an_audit_is_reported_as_a_failure(tmp_path, monkeypatch):
    """A skip must never be indistinguishable from a satisfied assertion, here least of all."""
    present = tmp_path / "book.pkl"
    present.write_bytes(b"x")
    case = _synthetic(tmp_path, "skips", {"the book": str(present)})
    monkeypatch.setattr(EA, "REGISTRY", (case,))
    report = EA.evaluate()
    r = report["results"][0]
    assert r["status"] == EA.RAN_FAIL, "a skipped audit was not reported as a failure"
    assert r["outcome"] == "skipped"
    assert "SKIPPED" in r["detail"]


def test_an_audit_pytest_never_reports_is_a_failure_not_a_pass(tmp_path, monkeypatch):
    """A nodeid that does not resolve produces no junit row. That must be red, never silent."""
    present = tmp_path / "book.pkl"
    present.write_bytes(b"x")
    case = _synthetic(tmp_path, "passes", {"the book": str(present)})
    case = dict(case, nodeid=case["nodeid"].replace("test_synthetic_pass", "test_does_not_exist"))
    monkeypatch.setattr(EA, "REGISTRY", (case,))
    report = EA.evaluate()
    assert report["results"][0]["status"] == EA.RAN_FAIL
    assert "no result" in report["results"][0]["detail"]


# ------------------------------------------------------------------ exit codes
def _cli(args, expect):
    proc = subprocess.run([sys.executable, str(HERE / "external_audit.py"), *args],
                          cwd=str(ROOT), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=900)
    assert proc.returncode == expect, (
        f"expected exit {expect}, got {proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-800:]}")
    return proc


def test_the_list_mode_exits_zero_and_prints_every_registered_audit():
    proc = _cli(["--list"], 0)
    for case in EA.REGISTRY:
        assert case["id"] in proc.stdout
        for path in case["requires"].values():
            assert path in proc.stdout, f"{case['id']} did not print the path it needs: {path}"


def test_a_did_not_run_alone_exits_zero_but_require_all_exits_one(tmp_path, monkeypatch):
    """Two different questions. "Did anything fail?" and "could this machine answer at all?"."""
    case = _synthetic(tmp_path, "passes", {"the book": str(tmp_path / "nope.pkl")})
    monkeypatch.setattr(EA, "REGISTRY", (case,))
    assert EA.main([]) == 0
    assert EA.main(["--require-all"]) == 1


def test_a_failure_exits_one_even_without_require_all(tmp_path, monkeypatch):
    present = tmp_path / "book.pkl"
    present.write_bytes(b"x")
    monkeypatch.setattr(EA, "REGISTRY", (_synthetic(tmp_path, "fails", {"b": str(present)}),))
    assert EA.main([]) == 1


def test_the_report_is_written_even_when_its_directory_does_not_exist_yet(tmp_path, monkeypatch):
    """The runner must not depend on a previous CI step having made `reports/` for it."""
    case = _synthetic(tmp_path, "passes", {"the book": str(tmp_path / "nope.pkl")})
    monkeypatch.setattr(EA, "REGISTRY", (case,))
    out = tmp_path / "made" / "up" / "audit.json"
    assert not out.parent.exists()
    assert EA.main(["--report", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["totals"]["did_not_run"] == 1


def test_the_report_file_is_written_and_reloadable(tmp_path, monkeypatch):
    case = _synthetic(tmp_path, "passes", {"the book": str(tmp_path / "nope.pkl")})
    monkeypatch.setattr(EA, "REGISTRY", (case,))
    out = tmp_path / "audit.json"
    assert EA.main(["--report", str(out)]) == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["kind"] == "hydra-external-audit"
    assert payload["results"][0]["status"] == EA.DID_NOT_RUN
    assert payload["totals"]["did_not_run"] == 1


def test_the_three_statuses_are_distinct_strings():
    """`DID NOT RUN` must never be spelled in a way a grep for PASS would match."""
    assert len({EA.RAN_PASS, EA.RAN_FAIL, EA.DID_NOT_RUN}) == 3
    assert "PASS" not in EA.DID_NOT_RUN and "PASS" not in EA.RAN_FAIL


@pytest.mark.parametrize("case", EA.REGISTRY, ids=[c["id"] for c in EA.REGISTRY])
def test_each_real_registry_entry_is_routed_without_being_executed(case, monkeypatch):
    """Runs on any machine: absent artefacts are NAMED, present ones are HANDED to pytest.

    What this asserts is the runner's routing, not the audits' outcomes. It deliberately does not
    execute the real audit, and the defect that taught us why is worth writing down: while the
    TASK-433 evidence was missing this test was cheap, because sixteen of the twenty-seven cases
    classified as DID NOT RUN and never launched anything. The moment the evidence existed on disk
    the SAME required suite grew twenty-seven pytest launches, sixteen of them re-deriving the mark
    grid from the raw caches - about 70 s per call. A required suite whose runtime and coverage
    depend on whether gitignored artefacts happen to exist is the CI-01 hole wearing a new hat.

    Executing the real audits is `python tools/external_audit.py`, which is the entry point built
    for it and reports RAN - PASS / RAN - FAIL / DID NOT RUN for all twenty-seven.
    """
    gone = EA.missing(case)
    assert set(gone) <= set(case["requires"]), "missing() invented an artefact the case never asked for"
    monkeypatch.setattr(EA, "REGISTRY", (case,))

    launched: list = []

    def _never_runs(nodeids, junit):
        launched.append(list(nodeids))
        raise AssertionError("a case with every artefact present must reach _run, and this test "
                             "stops it there rather than paying for the real audit")

    monkeypatch.setattr(EA, "_run", _never_runs)

    if gone:
        report = EA.evaluate()
        assert report["results"][0]["status"] == EA.DID_NOT_RUN
        assert report["results"][0]["missing"], "DID NOT RUN with nothing named as missing"
        assert launched == [], "a case with a missing artefact must never launch pytest"
    else:
        with pytest.raises(AssertionError):
            EA.evaluate()
        assert launched == [[case["nodeid"]]], (
            "a case whose artefacts are all present must be handed to pytest by its exact nodeid")


def test_the_runner_tells_the_subprocess_which_run_it_pinned(monkeypatch, tmp_path):
    """`_run` must carry `HYDRA_433_RUN_ID=TASK_433_RUN_ID` into pytest's environment. Without it
    the runner verifies the presence of the pinned run's books and the audit resolves "the newest
    directory" - two different runs the moment a later one exists (found in review of #95)."""
    seen = {}

    def _fake_run(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw.get("env")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(EA.subprocess, "run", _fake_run)
    monkeypatch.setenv("HYDRA_433_RUN_ID", "something-stale-from-the-shell")
    EA._run(["audits/x.py::test_y"], str(tmp_path / "j.xml"))
    assert seen["env"] is not None, "_run launched pytest with an inherited, unpinned environment"
    assert seen["env"]["HYDRA_433_RUN_ID"] == EA.TASK_433_RUN_ID
    assert seen["env"]["HYDRA_433_CODE_REF"] == EA.TASK_433_CODE_REF
    assert len(EA.TASK_433_CODE_REF) == 40, "the pinned commit is a full sha, not something git has to guess"
    assert seen["env"].get("PATH") == os.environ.get("PATH"), "the rest of the environment is inherited"
