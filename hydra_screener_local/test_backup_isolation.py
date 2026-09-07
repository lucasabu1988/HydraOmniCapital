"""A test run must not be able to write into the real backup root.

Regression for the 2026-09-06 incident: every portfolio_v9.json under
OneDrive/HydraBackups/state_v9/ was a test fixture, and state_v9/20260904/ — the directory for the
book holding the 30 pending orders — had been overwritten with capital_reference 8000. Cause:
HYDRA_BACKUP_DIR is a user variable, journal.save_record and portfolio_v9.copy_state_off_disk read
it from the environment at call time, and both the runner (env = os.environ.copy()) and a bare
pytest invocation inherit it.

These tests hold the containment down from both entry points. They do NOT assert that the write
paths are well designed — they are not, and the redesign is queued: resolving the environment deep
inside the copy is the defect, this only stops it reaching a real destination from a test.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import conftest
import journal
import run_all_tests

ROOT = Path(__file__).parent
REAL_BACKUP_HINTS = ("onedrive", "hydrabackups")


def _looks_like_a_real_backup_root(path: str) -> bool:
    low = str(path).lower()
    return any(h in low for h in REAL_BACKUP_HINTS)


def test_the_policy_is_installed_however_this_file_was_invoked():
    """Under run_all_tests.py or under a bare `pytest`, the variable is already redirected."""
    current = os.environ.get("HYDRA_BACKUP_DIR", "")
    assert conftest.TEST_BACKUP_MARKER in current, current
    assert not _looks_like_a_real_backup_root(current), current


def test_the_marker_is_the_same_string_in_both_layers():
    """Two layers install the redirect; a drifting marker would make them fight."""
    assert run_all_tests.TEST_BACKUP_MARKER == conftest.TEST_BACKUP_MARKER


def test_the_runner_hands_subprocesses_a_throwaway_destination():
    d = run_all_tests.test_backup_dir()
    assert conftest.TEST_BACKUP_MARKER in d
    assert not _looks_like_a_real_backup_root(d)
    assert d == run_all_tests.test_backup_dir(), "one destination per run, not one per test file"


def test_a_journal_write_lands_in_the_throwaway_root_and_nowhere_else(tmp_path):
    """The real leak, reproduced: save_record copies into <HYDRA_BACKUP_DIR>/state_v9/<date>/."""
    backup = Path(os.environ["HYDRA_BACKUP_DIR"])
    before = {p for p in backup.rglob("*") if p.is_file()}
    journal.save_record({"date": "2026-09-04", "book": {"total": 100000.0}}, journal_dir=tmp_path)
    written = {p for p in backup.rglob("*") if p.is_file()} - before
    assert written, "save_record did copy off-disk; if this fails the copy moved and this test is stale"
    for p in written:
        assert conftest.TEST_BACKUP_MARKER in str(p)
    assert (tmp_path / "2026-09-04.json").exists()


def test_a_bare_pytest_run_of_the_real_leaker_writes_nothing_to_the_inherited_root(tmp_path):
    """The exact shape of the incident: `python -m pytest test_journal.py` from inside the package
    with HYDRA_BACKUP_DIR inherited. Before conftest.py this wrote four files into
    <root>/state_v9/20260903 and /20260904. The decoy root must come back empty.

    The inherited value here is a DECOY under tmp_path — never the machine's real backup root, which
    is the whole point of the regression.
    """
    decoy = tmp_path / "inherited-backup-root"
    decoy.mkdir()
    env = dict(os.environ, HYDRA_BACKUP_DIR=str(decoy))
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "test_journal.py", "-q", "-p", "no:cacheprovider"],
        cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=180,
    )
    assert out.returncode == 0, out.stdout[-2000:] + out.stderr[-2000:]
    leaked = sorted(str(p.relative_to(decoy)) for p in decoy.rglob("*") if p.is_file())
    assert leaked == [], f"test run wrote into the inherited backup root: {leaked}"


def test_the_incident_shape_is_recognisable(tmp_path):
    """What a polluted backup looks like, so a future reader can tell fixture from book.

    The fixtures found in the real root carried capital_reference 8000/25000 and AAA/BBB/CCC
    tickers; the production book carries 100000 and 30 real pending orders. This documents the
    tell rather than asserting on the machine's actual backup, which tests must never read.
    """
    fixture = {"capital_reference": 8000.0, "pending": [{"ticker": "AAA"}]}
    book = {"capital_reference": 100000.0, "pending": [{"ticker": "SLAB"}] * 30}
    for name, payload, is_fixture in (("f.json", fixture, True), ("b.json", book, False)):
        p = tmp_path / name
        p.write_text(json.dumps(payload), encoding="utf-8")
        d = json.loads(p.read_text(encoding="utf-8"))
        synthetic = {o["ticker"] for o in d["pending"]} <= {"AAA", "BBB", "CCC"}
        assert synthetic is is_fixture
