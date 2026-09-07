"""TASK-393 — the test-session isolation policy holds from every entry point.

Regression for the 2026-09-06 incident: every portfolio_v9.json under
OneDrive/HydraBackups/state_v9/ was a test fixture, and state_v9/20260904/ — the directory for the
book holding the 30 pending orders — had been overwritten with capital_reference 8000. Cause:
HYDRA_BACKUP_DIR is a user variable, journal.save_record and portfolio_v9.copy_state_off_disk read
it from the environment at call time, and both the runner (env = os.environ.copy()) and a bare
pytest invocation inherited it.

This file tests the FENCE. It is no longer the thing standing between a test and the real root —
since TASK-392 the backup service reads no environment variable and copies nothing a caller has
not authorised (`test_backup_service.py`), and the reproductions live in
`test_backup_regressions.py`. What is asserted here: the policy is installed however the process
was started, every layer agrees on one marker, each process gets its own destination, a child's
environment is BUILT rather than inherited, and whatever this process inherited is registered with
the service as a forbidden destination.
"""
import json
import os
from pathlib import Path

import pytest

import conftest
import hydra_test_policy
import run_all_tests
from backup_service import (
    BackupContext,
    BackupRefused,
    ExecutionMode,
    denied_destinations,
    new_run_id,
    publish_generation,
)

ROOT = Path(__file__).parent
REAL_BACKUP_HINTS = ("onedrive", "hydrabackups")


def _looks_like_a_real_backup_root(path) -> bool:
    low = str(path).lower()
    return any(h in low for h in REAL_BACKUP_HINTS)


def test_the_policy_is_installed_however_this_file_was_invoked():
    """Under run_all_tests.py or under a bare `pytest`, the variable is already redirected."""
    assert hydra_test_policy.is_installed()
    current = os.environ.get("HYDRA_BACKUP_DIR", "")
    assert conftest.TEST_BACKUP_MARKER in current, current
    assert not _looks_like_a_real_backup_root(current), current


def test_the_marker_is_the_same_string_in_every_layer():
    """Three layers install the redirect; a drifting marker would make them fight."""
    assert run_all_tests.TEST_BACKUP_MARKER == conftest.TEST_BACKUP_MARKER
    assert conftest.TEST_BACKUP_MARKER == hydra_test_policy.TEST_BACKUP_MARKER


def test_each_process_gets_its_own_destination_inside_one_session_tree():
    """Per-process directories: a parent and its children cannot scribble on each other's
    fixtures, and the whole run still cleans up as one tree."""
    mine = Path(run_all_tests.test_backup_dir())
    assert mine == hydra_test_policy.process_backup_dir()
    assert mine.parent == hydra_test_policy.session_root()
    assert mine.name.startswith(f"p{os.getpid()}-")
    assert conftest.TEST_BACKUP_MARKER in str(mine)
    assert mine == Path(run_all_tests.test_backup_dir()), "one destination per process, not per file"


def test_the_child_environment_is_built_not_inherited():
    """`os.environ.copy()` is exactly how the production value reached the children."""
    polluted = {"PATH": os.environ.get("PATH", ""),
                "HYDRA_BACKUP_DIR": r"C:\Users\caslu\OneDrive\HydraBackups",
                "HYDRA_BACKUP_DENY": "", "HYDRA_REGEN_GOLDEN": "1"}
    env = hydra_test_policy.build_child_env(base=polluted)
    assert hydra_test_policy.TEST_BACKUP_MARKER in env["HYDRA_BACKUP_DIR"]
    assert not _looks_like_a_real_backup_root(env["HYDRA_BACKUP_DIR"])
    assert env["HYDRA_TEST_POLICY"] == "1"
    assert env["HYDRA_REGEN_GOLDEN"] == "1", "a developer opt-in must still reach the child"


def test_whatever_was_inherited_is_a_forbidden_destination(tmp_path):
    """The inherited value is registered with the SERVICE, not merely overwritten in the env, so
    a caller that reconstructs that path by any route is refused rather than obeyed."""
    denied = hydra_test_policy.denied_roots()
    if not denied:
        pytest.skip("nothing was inherited in this environment (CI); nothing to forbid")
    for d in denied:
        assert Path(d).resolve() in denied_destinations()
    live = tmp_path / "live"
    live.mkdir()
    state = live / "portfolio_v9.json"
    state.write_text("{}", encoding="utf-8")
    # The inherited root is the operator's REAL backup root on this machine. A test must not read
    # it either (hashing it would pull cloud-only OneDrive files down), so the assertion is that
    # the refusal happens and that the probe subdirectory was never created.
    probe = Path(denied[0]) / "hydra-test-probe-never-created"
    ctx = BackupContext.create(run_id=new_run_id(), date="2026-09-04",
                               dest_root=probe, allowed_source_roots=(live,),
                               profile="sheet_only", mode=ExecutionMode.LIVE)
    with pytest.raises(BackupRefused) as e:
        publish_generation(ctx, [state])
    assert e.value.code == "DEST_DENIED"
    assert not probe.exists()


def test_the_incident_shape_is_recognisable(tmp_path):
    """What a polluted backup looks like, so a future reader can tell fixture from book.

    The fixtures found in the real root carried capital_reference 8000/25000 and AAA/BBB/CCC
    tickers; the production book carries 100000 and 30 real pending orders. This documents the
    tell rather than asserting on the machine's actual backup, which tests must never read.

    It is also the argument for TASK-395: of the 60 files in the real root, 35 were fixtures, 2
    were real and 21 were UNDECIDABLE from content — a journal record with an empty book is
    indistinguishable from the real book, which is also empty until the settle. No per-file tell
    can close that; only a run_id shared by every role of one execution can.
    """
    fixture = {"capital_reference": 8000.0, "pending": [{"ticker": "AAA"}]}
    book = {"capital_reference": 100000.0, "pending": [{"ticker": "SLAB"}] * 30}
    for name, payload, is_fixture in (("f.json", fixture, True), ("b.json", book, False)):
        p = tmp_path / name
        p.write_text(json.dumps(payload), encoding="utf-8")
        d = json.loads(p.read_text(encoding="utf-8"))
        synthetic = {o["ticker"] for o in d["pending"]} <= {"AAA", "BBB", "CCC"}
        assert synthetic is is_fixture
