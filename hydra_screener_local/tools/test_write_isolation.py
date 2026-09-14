"""The write barrier, proven against an ARTIFICIAL protected root - never against real evidence.

On 2026-09-12 a mutation test redirected `accredit_433.acc_path` onto `cost_stress.book_path` and
wrote an 8-mark fixture over an 814-mark evidence book. Restoring the mutated source did not undo
the write: by then it had happened. The barrier refuses on the RESOLVED ABSOLUTE PATH, so it does
not care which function asked - which is what makes it independent of the mutated path builder.

Everything here writes inside tmp_path. No test in this file targets a real output directory.
"""
import os
import sys

import pytest

TOOLS = os.path.dirname(os.path.abspath(__file__))
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import write_isolation as WI  # noqa: E402


@pytest.fixture
def guarded(tmp_path):
    """An artificial protected root holding a decoy, plus a disposable root that stays writable."""
    protected = tmp_path / "evidence"
    protected.mkdir()
    decoy = protected / "book.pkl"
    decoy.write_bytes(b"ORIGINAL EVIDENCE BYTES")
    disposable = tmp_path / "scratch"
    disposable.mkdir()
    # conftest installs the barrier over the REAL roots at import time. Swap it for the
    # artificial root for the duration of this test, then put the real policy back - so nothing
    # here is ever aimed at real evidence and the session keeps its protection afterwards.
    # No `if was_installed` branch: that made the whole file pass while conftest's barrier was
    # dead, because the fixture simply installed its own. The session state is a precondition
    # here, not something to paper over - test_write_barrier_armed.py owns the session claim.
    assert WI.is_installed(), "conftest did not install the barrier; see test_write_barrier_armed.py"
    # An EMPTY list is legitimate on a bare checkout: roots are filtered to directories that
    # exist, and a clean clone has no state/, journal/ or _lab_scratch/. Restoring [] restores
    # the truth. What must not happen is this fixture standing in for an absent barrier.
    real_roots = WI.protected_roots()
    WI.uninstall()
    WI.install(protected=[str(protected)], index_identities=False)
    try:
        yield protected, decoy, disposable
    finally:
        WI.uninstall()
        # index_identities=True on the way back: restoring with it False silently dropped the
        # hardlink-identity control for the rest of the session.
        WI.install(protected=real_roots, index_identities=True)
    assert decoy.read_bytes() == b"ORIGINAL EVIDENCE BYTES", "the decoy was modified"


def test_a_write_by_absolute_path_is_refused(guarded):
    _protected, decoy, _ = guarded
    with pytest.raises(WI.WriteIsolationError):
        open(str(decoy), "wb").write(b"x")


def test_a_write_by_relative_path_is_refused(guarded, monkeypatch):
    protected, decoy, _ = guarded
    monkeypatch.chdir(protected)
    with pytest.raises(WI.WriteIsolationError):
        open("book.pkl", "wb").write(b"x")


def test_pathlib_is_refused_too(guarded):
    """`pathlib.Path.open` goes through `io.open`, not `builtins.open` - a silent hole if missed."""
    _protected, decoy, _ = guarded
    with pytest.raises(WI.WriteIsolationError):
        decoy.write_bytes(b"x")
    with pytest.raises(WI.WriteIsolationError):
        decoy.open("wb")


def test_the_incident_shape_is_refused(guarded):
    """A path builder redirected onto another module's - the exact 2026-09-12 mutation."""
    protected, decoy, _ = guarded

    def acc_path(name):                 # "accredited" destination...
        return str(protected / name)    # ...mutated to point at the evidence directory

    with pytest.raises(WI.WriteIsolationError):
        open(acc_path("book.pkl"), "wb").write(b"8-mark fixture")


def test_the_disposable_root_stays_writable(guarded):
    """A barrier that blocks everything is useless: the positive control."""
    _protected, _decoy, disposable = guarded
    target = disposable / "out.pkl"
    target.write_bytes(b"fine")
    assert target.read_bytes() == b"fine"


def test_the_refusal_cannot_be_swallowed_by_a_bare_except_exception(guarded):
    """The screener is full of `except Exception:` fallbacks; a guard they can absorb is no guard."""
    _protected, decoy, _ = guarded
    swallowed = False
    try:
        try:
            open(str(decoy), "wb").write(b"x")
        except Exception:               # noqa: BLE001 - deliberately the wrong net
            swallowed = True
    except BaseException:
        pass
    assert not swallowed, "the refusal was caught by `except Exception`"


def test_the_real_roots_are_resolved_and_include_more_than_the_backup_dir(tmp_path):
    """HYDRA_BACKUP_DIR only ever covered backups that honour it; books and manifests are separate.

    Driven against a SYNTHETIC screener dir, not this checkout: roots are filtered to
    directories that exist, so asserting against the live tree would test which machine ran
    the suite (all eight present on Lucas's, none on a clean CI clone) instead of the rule.
    """
    for rel in ("experiments/_lab_scratch", "state", "state_paper", "journal",
                "journal_paper", "runs", "history", "backups"):
        (tmp_path / rel).mkdir(parents=True)
    roots = [r.lower() for r in WI.repo_evidence_roots(screener=str(tmp_path))]
    assert any("_lab_scratch" in r for r in roots), "the books' own directory must be protected"
    assert any(r.endswith("state") for r in roots)
    assert any("journal" in r for r in roots)
    assert len(roots) >= 5


def test_a_root_that_does_not_exist_is_not_protected(tmp_path):
    """Existence is the test for evidence: an absent directory has nothing to destroy.

    Protecting absent names refused honest throwaways on a clean checkout - `os.rmdir('journal')`
    at teardown blew up ~20 files on CI run 34765483260 while every one of them passed on a
    machine where journal/ really existed.
    """
    (tmp_path / "state").mkdir()
    roots = [r.lower() for r in WI.repo_evidence_roots(screener=str(tmp_path))]
    assert any(r.endswith("state") for r in roots), "an existing evidence dir must be protected"
    assert not any(r.endswith("journal") for r in roots), \
        "an absent evidence dir must NOT be protected"


def test_the_uncovered_paths_are_written_down_not_implied():
    """An honest gap list is part of the deliverable, in the module's own words."""
    src = open(os.path.join(TOOLS, "write_isolation.py"), encoding="utf-8").read().lower()
    for expected in ("subprocess", "descriptor"):
        assert expected in src, f"the module must name the {expected} gap in writing"


# ------------------------------------------------------------------ HYDRA-CI-01: the backup root
# The anomaly: every CI run printed "The real backup root was NOT captured and is NOT protected."
# Reproduced 2026-09-14 in both shapes and found FALSE in both. In a child of `run_all_tests.py`
# on the lab machine the same child had `C:\Users\caslu\OneDrive\HydraBackups` armed; in the CI
# shape no real root existed at all. The barrier was never installed late - the message asserted
# the opposite of what had happened. `repo_evidence_roots` cannot know what its caller captured,
# so it is now told, and the notice is emitted only in the case that is genuinely unprotected.

def _redirect(tmp_path):
    d = tmp_path / f"{WI.TEST_BACKUP_MARKER}-throwaway"
    d.mkdir()
    return str(d)


def test_an_explicit_backup_root_is_protected_and_says_nothing(tmp_path, monkeypatch, capsys):
    real = tmp_path / "RealBackups"
    real.mkdir()
    (tmp_path / "state").mkdir()
    monkeypatch.setenv("HYDRA_BACKUP_DIR", _redirect(tmp_path))
    roots = [r.lower() for r in WI.repo_evidence_roots(screener=str(tmp_path),
                                                       backup_root=str(real))]
    assert any("realbackups" in r for r in roots), "the supplied real root must be protected"
    assert not any(WI.TEST_BACKUP_MARKER in r for r in roots), "the throwaway must not be"
    assert "NOT protected" not in capsys.readouterr().err, (
        "the notice fired while the root it names was armed in the same call")


def test_the_notice_fires_only_when_nobody_supplied_the_real_root(tmp_path, monkeypatch, capsys):
    (tmp_path / "state").mkdir()
    monkeypatch.setenv("HYDRA_BACKUP_DIR", _redirect(tmp_path))
    WI.repo_evidence_roots(screener=str(tmp_path))
    err = capsys.readouterr().err
    assert "test redirect" in err and "backup_root" in err
    # and it must not claim a real root exists: on a clean checkout there is none
    assert "was NOT captured" not in err


def test_an_unredirected_backup_dir_is_protected_without_a_notice(tmp_path, monkeypatch, capsys):
    real = tmp_path / "RealBackups"
    real.mkdir()
    (tmp_path / "state").mkdir()
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(real))
    roots = [r.lower() for r in WI.repo_evidence_roots(screener=str(tmp_path))]
    assert any("realbackups" in r for r in roots)
    assert capsys.readouterr().err.strip() == ""


def test_no_backup_variable_at_all_is_silent_and_protects_nothing_extra(tmp_path, monkeypatch,
                                                                       capsys):
    """The CI shape. Nothing to protect is not the same claim as something left unprotected."""
    (tmp_path / "state").mkdir()
    monkeypatch.delenv("HYDRA_BACKUP_DIR", raising=False)
    roots = WI.repo_evidence_roots(screener=str(tmp_path))
    assert len(roots) == 1 and roots[0].lower().endswith("state")
    assert capsys.readouterr().err.strip() == ""


def test_the_bootstrap_hands_the_captured_root_over_rather_than_appending_it():
    """The fix has to be in the caller too, or the notice comes back on every child."""
    src = open(os.path.join(TOOLS, "_bootstrap", "sitecustomize.py"), encoding="utf-8").read()
    assert "backup_root=real_backup" in src, (
        "sitecustomize must pass the captured root INTO repo_evidence_roots; appending it "
        "afterwards is what made the notice fire on every child of run_all_tests.py")
