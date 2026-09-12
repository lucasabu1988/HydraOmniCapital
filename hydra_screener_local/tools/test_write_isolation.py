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
    was_installed = WI.is_installed()
    real_roots = WI.protected_roots() if was_installed else None
    if was_installed:
        WI.uninstall()
    WI.install(protected=[str(protected)], index_identities=False)
    try:
        yield protected, decoy, disposable
    finally:
        WI.uninstall()
        if was_installed:
            WI.install(protected=real_roots, index_identities=False)
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


def test_the_real_roots_are_resolved_and_include_more_than_the_backup_dir():
    """HYDRA_BACKUP_DIR only ever covered backups that honour it; books and manifests are separate."""
    roots = [r.lower() for r in WI.repo_evidence_roots()]
    assert any("_lab_scratch" in r for r in roots), "the books' own directory must be protected"
    assert any(r.endswith("state") for r in roots)
    assert any("journal" in r for r in roots)
    assert len(roots) >= 5


def test_the_uncovered_paths_are_written_down_not_implied():
    """An honest gap list is part of the deliverable, in the module's own words."""
    src = open(os.path.join(TOOLS, "write_isolation.py"), encoding="utf-8").read().lower()
    for expected in ("subprocess", "descriptor"):
        assert expected in src, f"the module must name the {expected} gap in writing"
