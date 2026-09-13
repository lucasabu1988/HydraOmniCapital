"""Arm the write barrier in every Python child the runner starts, before anything else runs.

The gap this closes (SAFE-04, measured 2026-09-13 on 27afcf8)
------------------------------------------------------------
`tools/write_isolation.py` patches one process. `run_all_tests.py` runs nine files as
SCRIPTS, and a script loads no conftest, so those children had no barrier at all. Measured
with a decoy in a protected directory:

    parent: refused -> WriteIsolationError
    child : wrote, exit 0, the decoy's hash changed

The module's own notes described a `sitecustomize` layer as if it existed. It did not - this
file is it. #82 armed the barrier for pytest-routed children (they do load conftest); this
arms it for everything else.

Why this file exits instead of raising
--------------------------------------
CPython imports `sitecustomize` at interpreter startup and SWALLOWS any exception it raises.
Measured:

    $ PYTHONPATH=<dir with a raising sitecustomize> python -c "print('CHILD RAN ANYWAY')"
    Error in sitecustomize; set PYTHONVERBOSE for traceback:
    RuntimeError: BARRIER BOOTSTRAP FAILED
    CHILD RAN ANYWAY
    EXIT=0

So a bootstrap that raises is fail-OPEN, which is the opposite of the point. `os._exit` is
not swallowed:

    $ PYTHONPATH=<dir whose sitecustomize calls os._exit(97)> python -c "print('...')"
    [barrier] cannot install; refusing to run unprotected
    EXIT=97

Every failure path here therefore ends in `os._exit(EXIT_BOOTSTRAP_FAILED)`: the interpreter
stops before the module under test is imported, and the runner sees a distinctive code
rather than a green run that protected nothing.

What still is not covered
-------------------------
This arms PYTHON children that inherit PYTHONPATH and the flag. It does nothing for a
non-Python program (`cmd /c echo > file`), for a child started with `-S` or `-E`, for a file
handle opened before install, for a raw file descriptor, or for a C-level path opener.
`run_all_tests.py` runs a canary before the suite so that "the bootstrap silently did not
load" is caught rather than assumed, but the limits above are real and stay documented.
"""
import json
import os
import sys

#: Distinct from any exit code a test is likely to produce, so the runner can name the cause.
EXIT_BOOTSTRAP_FAILED = 97

#: Set by the parent. Absent means "this child is not part of a guarded run" - do nothing.
FLAG = "HYDRA_WRITE_BARRIER"
#: Explicit root list. Used by the tests to aim the barrier at an isolated decoy; when it is
#: absent the child resolves the roots itself (see `_roots`).
ROOTS = "HYDRA_WRITE_BARRIER_ROOTS"
#: Where the repo is, passed rather than inferred from cwd.
SCREENER = "HYDRA_SCREENER_DIR"
#: The REAL backup root, as the parent saw it BEFORE redirecting HYDRA_BACKUP_DIR.
REAL_BACKUP = "HYDRA_WRITE_BARRIER_BACKUP_ROOT"
#: Any path carrying this is a throwaway test destination, never evidence.
TEST_BACKUP_MARKER = "hydra-test-backup"


def _roots(write_isolation):
    """Which roots this child protects.

    The repo-local directories are resolved HERE, in the child, not inherited as a snapshot
    from the parent. They have to be: the runner resolves its list once at import, and on a
    clean checkout `experiments/_lab_scratch/` does not exist yet - an earlier test file
    creates it, and a later child would then be running beside a real evidence directory
    that the frozen list did not mention. Measured exactly that way on a clean clone.

    The one thing the child CANNOT resolve for itself is the backup root: by the time it
    starts, HYDRA_BACKUP_DIR has been rebound to a throwaway, so the parent passes the real
    value it saw before the redirect. That is why the split exists.
    """
    explicit = os.environ.get(ROOTS, "")
    if explicit:
        roots = json.loads(explicit)
        if not isinstance(roots, list) or not all(isinstance(r, str) for r in roots):
            raise ValueError(f"expected a list of strings, got {type(roots).__name__}")
        return roots
    screener = os.environ.get(SCREENER) or os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    roots = [r for r in write_isolation.repo_evidence_roots(screener=screener)
             if TEST_BACKUP_MARKER not in r.lower()]
    real_backup = os.environ.get(REAL_BACKUP, "")
    if real_backup and os.path.isdir(real_backup):
        roots.append(real_backup)
    return roots


def _die(message):
    sys.stderr.write(f"[write-isolation bootstrap] {message}\n")
    sys.stderr.write("[write-isolation bootstrap] refusing to run unprotected.\n")
    sys.stderr.flush()
    os._exit(EXIT_BOOTSTRAP_FAILED)


def _arm():
    tools_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        import write_isolation
    except Exception as exc:                      # noqa: BLE001 - becomes a hard exit
        _die(f"cannot import write_isolation from {tools_dir}: {exc!r}")

    try:
        roots = _roots(write_isolation)
    except Exception as exc:                      # noqa: BLE001 - becomes a hard exit
        _die(f"cannot resolve the roots to protect ({exc}); "
             f"{ROOTS}={os.environ.get(ROOTS, '')!r}")

    try:
        # import_optional=False keeps pandas/numpy out of the startup import graph: this runs
        # before the interpreter has finished booting and must stay cheap.
        write_isolation.install(protected=roots, index_identities=False,
                                import_optional=False)
    except Exception as exc:                      # noqa: BLE001 - becomes a hard exit
        _die(f"install() raised {exc!r}")

    if not write_isolation.is_installed():
        _die("install() returned without arming the barrier")

    # An empty root list is legitimate - a clean clone has no evidence directories (#82) -
    # but it must be what the PARENT asked for, not the result of a lost variable.
    got = {r.lower() for r in write_isolation.protected_roots()}
    want = {r.lower() for r in (write_isolation._key(r) for r in roots)}
    if got != want:
        _die(f"armed the wrong roots: asked for {sorted(want)}, armed {sorted(got)}")


if os.environ.get(FLAG) == "1":
    _arm()
