"""The barrier is ARMED in this session - not merely importable.

Why this file exists, and why it lives at the package root rather than beside the module
it tests: `tools/test_write_isolation.py` proves that `write_isolation.install()` works when
the test calls it by hand, against an artificial root. That is a different claim. It passed
for the whole life of the defect it was supposed to catch.

The defect (audit 2026-09-13): `conftest.py` read TEST_BACKUP_MARKER inside the callback it
passed to `install()`, seven lines before the module bound that name. Python evaluates the
argument first, so `install()` was never entered at all, the NameError was swallowed by a
broad `except`, and every pytest session ran with no write protection whatsoever. Nothing
failed. `is_installed()` was False, `protected_roots()` was [] and WRITE_BARRIER_ROOTS was [].

So these tests assert the SESSION state that conftest produced, never a state they create
themselves. A test that installs the barrier to check the barrier cannot observe the wiring.

`run_all_tests.py` discovers `test_*.py` at the package root, so this file runs in CI. The
tools/ directory was NOT discovered when the defect shipped (glob covered root and
experiments/ only); that is fixed alongside this file, but the fix must not be what this
file depends on.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))

import conftest as CT  # noqa: E402
import write_isolation as WI  # noqa: E402


def test_the_barrier_is_installed_in_this_session():
    """The session-level claim: conftest armed it, and it is still armed here."""
    assert WI.is_installed(), (
        "write isolation is NOT installed in this pytest session. conftest.py reported "
        "'WRITE ISOLATION NOT INSTALLED' and continued anyway. The suite is running with "
        "no protection over state/, journal*/ or the evidence books."
    )


def test_the_module_and_conftest_agree_on_the_root_list():
    """Two observers of one barrier must not disagree about what it covers."""
    assert [r.lower() for r in WI.protected_roots()] == \
           [r.lower() for r in CT.WRITE_BARRIER_ROOTS], (
        "the roots the module reports and the roots conftest recorded disagree"
    )


def test_every_evidence_directory_that_exists_is_protected():
    """The real invariant, and the one that survives a clean checkout.

    Roots are filtered to directories that EXIST at install time: a name that is not on disk
    holds no evidence, and protecting it only refuses honest throwaways (that is what broke
    ~20 files on CI run 34765483260). So the claim is not "state/ is protected" - on a clean
    clone there is no state/ - but "everything that IS here is covered".
    """
    protected = {os.path.normcase(os.path.abspath(r)) for r in WI.protected_roots()}
    present = [d for d in WI.repo_evidence_roots() if os.path.isdir(d)]
    missing = [d for d in present
               if os.path.normcase(os.path.abspath(d)) not in protected
               and CT.TEST_BACKUP_MARKER not in d.lower()]
    assert not missing, f"evidence directories present on disk but NOT protected: {missing}"
    # Not an assertion that evidence exists - just a statement of which case ran, so a
    # vacuous pass on a bare checkout is visible in the log rather than silent.
    print(f"[barrier] {len(present)} evidence dirs on disk, {len(protected)} protected")


def test_no_protected_root_is_a_throwaway_backup_dir():
    """The redirect happens after install; protecting the throwaway would refuse honest writes."""
    for root in WI.protected_roots():
        assert CT.TEST_BACKUP_MARKER not in root.lower(), (
            f"a disposable test backup dir is being protected as evidence: {root}"
        )


def test_a_write_into_a_protected_root_is_refused():
    """The barrier REFUSES, rather than merely knowing which roots are real.

    The guard on the first line is load-bearing and must never become a skip: the probe
    below writes into a REAL evidence root, so it may only be attempted once the barrier
    is known to be armed. With the barrier down this fails without touching the disk -
    which is the whole reason the probe is safe to ship.
    """
    assert WI.is_installed(), (
        "refusing to probe: the barrier is not armed, so this write would actually land "
        "in a real evidence root. Fix conftest.py before reading anything into this failure."
    )
    roots = WI.protected_roots()
    if not roots:
        # A bare checkout with no evidence on disk. Rather than pass vacuously, assert the
        # REASON the list is empty - if any evidence dir existed, it would have to be here.
        present = [d for d in WI.repo_evidence_roots()
                   if os.path.isdir(d) and CT.TEST_BACKUP_MARKER not in d.lower()]
        assert not present, f"protected_roots() is empty but these exist: {present}"
        return
    root = roots[0]
    target = os.path.join(root, "__write_barrier_probe__.tmp")
    with pytest.raises(BaseException) as exc:
        with open(target, "w", encoding="utf-8") as fh:
            fh.write("this write must never land")
    assert "WriteIsolation" in type(exc.value).__name__, (
        f"expected a WriteIsolationError, got {type(exc.value).__name__}: {exc.value}"
    )
    assert not os.path.exists(target), f"the refused write still created {target}"
