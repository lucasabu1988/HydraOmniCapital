"""Test-session policy: a test run must never be able to write into the real backup root.

`journal.save_record` and `portfolio_v9.copy_state_off_disk` both read `HYDRA_BACKUP_DIR` from the
environment at call time and copy into `<root>/state_v9/<YYYYMMDD>/`. `HYDRA_BACKUP_DIR` is a USER
variable on this machine, so every test process inherits the production value: on 2026-09-06 the only
off-disk copies of the live book were test fixtures, and `state_v9/20260904/` — the directory for the
book holding the 30 pending orders — had been overwritten by a fixture with `capital_reference: 8000`.
Reproduced: `python -m pytest test_journal.py` against a decoy root writes four files into
`state_v9/20260903/` and `state_v9/20260904/`.

This redirects the variable for the whole session, at import time, before any test module is imported
and therefore before any code can read it. It is containment, not the fix: the real fix is to stop
resolving the environment deep inside the write path and to hand the backup an explicit destination
(queued as the ASTRA-12 redesign). Until that lands, this is what keeps a suite run away from the book.

Two layers are needed, and this is only one of them: `run_all_tests.py` also runs some files as
scripts, and a script never loads a conftest — the runner sets the same redirect for its subprocesses.

The same policy, second destination (TASK-422): the real `runs/` directory. `portfolio_v9.run`
calls `data.fetch.load_last_ok_print_quality()` with no `runs_dir`, so it resolves
`utils.runlog.DEFAULT_RUNS_DIR` = `hydra_screener_local/runs/` — gitignored live state. Every test
that drives the CLI therefore READS the operator's last real run, and which branch of the loader
executes depends on what happens to be on this disk. Measured on this tree: dropping a
`runs/last_ok_print_quality.json` in place flips **35 statements** of `data/fetch.py`
(238-250, 259, 268-303, 319-328) between covered and uncovered over the same two test files, which
is what made two coverage runs of one commit disagree (82.33 vs 82.35, TASK-419). Redirecting the
default at session import time makes the measurement a property of the code again. The branches it
stops covering by accident are covered on purpose instead, with an explicit `runs_dir`
(`test_provider_refresh.py`).

Same gap as the layer above, said out loud: a file `run_all_tests.py` runs as a *script* loads no
conftest, and this redirect is a module attribute rather than an environment variable, so the runner
cannot pass it down. Coverage is measured over the pytest files only, so the measurement is fenced;
a script-mode test that drove the CLI would still read the operator's `runs/`. The real fix is to
hand the reader its destination instead of resolving it deep in the read path (ASTRA-12's shape).
"""
import atexit
import os
import pathlib
import shutil
import sys
import tempfile

# --------------------------------------------------------------------------------------------
# WRITE ISOLATION - installed FIRST, and the order is the whole point.
#
# `_redirect_backup_dir()` below rebinds HYDRA_BACKUP_DIR to a throwaway. The barrier reads the
# INHERITED value to learn which real root to protect, so installing after the redirect would
# guard the throwaway and leave the only off-disk copy of the live book unguarded. Textual
# position is not the guarantee, though - `tools/test_write_isolation.py` demonstrates the
# refusal against an ARTIFICIAL protected root, and `test_write_barrier_armed.py` asserts the
# SESSION state this block produces rather than assuming it.
#
# HYDRA_BACKUP_DIR only ever protected backups that honour that variable. Books, manifests,
# journals and runs/ are separate destinations and are enumerated by `repo_evidence_roots()`.
# What is NOT covered is written down in tools/write_isolation.py: non-Python subprocesses,
# handles opened before install, raw file descriptors and C-level path openers.
#
# TEST_BACKUP_MARKER is bound HERE, above the block that reads it. It used to be defined below,
# and `_real_evidence_roots` closed over a name that did not exist yet: Python evaluates the
# argument before calling, so `install()` was never entered, the NameError was swallowed by the
# `except` and every session ran unprotected with only a line on stderr. Keep this above.
# --------------------------------------------------------------------------------------------

#: Any path carrying this marker is a throwaway test destination, never a real backup root.
TEST_BACKUP_MARKER = "hydra-test-backup"

_TOOLS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
try:
    import write_isolation as _WI

    def _real_evidence_roots():
        """Resolve which roots are REAL before anything redirects a destination.

        `repo_evidence_roots()` includes whatever HYDRA_BACKUP_DIR points at. When the runner
        has already pointed it at a throwaway (run_all_tests.py:124 does exactly that), that
        directory is disposable BY DESIGN and protecting it refuses the writes the tests are
        supposed to make - measured: 5 files, 12 tests, all writing into their own temp backup.
        Identity, not position, decides: a path carrying TEST_BACKUP_MARKER is never evidence.
        """
        # Under `run_all_tests.py` the variable is already rebound by the time this child
        # starts, and the parent passes the captured value in HYDRA_WRITE_BARRIER_BACKUP_ROOT.
        # Handing it over keeps this path honest too: the bootstrap has normally armed the
        # barrier already, so `install()` below is a no-op, but a bare `python -m pytest` in a
        # shell that inherited a redirect would otherwise resolve its roots with the real one
        # silently missing - and, before HYDRA-CI-01, would say so in a message that was wrong
        # in every other case.
        real_backup = os.environ.get("HYDRA_WRITE_BARRIER_BACKUP_ROOT") or None
        roots = _WI.repo_evidence_roots(backup_root=real_backup)
        keep = [r for r in roots if TEST_BACKUP_MARKER not in r.lower()]
        dropped = [r for r in roots if TEST_BACKUP_MARKER in r.lower()]
        for d in dropped:
            print(f"[conftest] not protecting disposable backup root: {d}", file=sys.stderr)
        return keep

    WRITE_BARRIER_ROOTS = _WI.install(protected=_real_evidence_roots())
except Exception as _exc:                      # noqa: BLE001 - re-raised, never swallowed
    # FAIL CLOSED. This used to set WRITE_BARRIER_ROOTS = [] and print to stderr, and the suite
    # carried on unprotected; pytest captures stderr by default, so the warning reached nobody
    # and the barrier was dead from the commit that introduced it until the 2026-09-13 audit.
    # A barrier that cannot be installed stops collection - it does not downgrade to a notice.
    WRITE_BARRIER_ROOTS = []
    print(f"[conftest] WRITE ISOLATION NOT INSTALLED: {_exc}", file=sys.stderr)
    raise RuntimeError(
        f"write isolation could not be installed ({type(_exc).__name__}: {_exc}). "
        "Refusing to run the suite unprotected: tests write to state/, journal*/ and the "
        "evidence books. Fix the barrier, do not bypass this."
    ) from _exc


def _redirect_backup_dir() -> str:
    """Point HYDRA_BACKUP_DIR at a private temp directory unless it already is one."""
    current = os.environ.get("HYDRA_BACKUP_DIR", "")
    if TEST_BACKUP_MARKER in current:
        return current  # the runner (or an outer session) already installed the policy
    path = tempfile.mkdtemp(prefix=f"{TEST_BACKUP_MARKER}-")
    os.environ["HYDRA_BACKUP_DIR"] = path
    atexit.register(shutil.rmtree, path, True)
    return path


BACKUP_DIR = _redirect_backup_dir()


#: Same idea for the run log: a throwaway runs/ root, never the operator's.
TEST_RUNS_MARKER = "hydra-test-runs"


def _redirect_runs_dir() -> str:
    """Point `utils.runlog.DEFAULT_RUNS_DIR` at a private temp directory.

    Not an environment variable — this one is a module constant, so the redirect is an
    attribute assignment done before any test module is imported. `data/fetch.py` reads it
    inside the function (`from utils.runlog import DEFAULT_RUNS_DIR` at call time), so the
    new value is the one the live code path sees under test.
    """
    here = str(pathlib.Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    from utils import runlog

    if TEST_RUNS_MARKER in str(runlog.DEFAULT_RUNS_DIR):
        return str(runlog.DEFAULT_RUNS_DIR)
    path = tempfile.mkdtemp(prefix=f"{TEST_RUNS_MARKER}-")
    runlog.DEFAULT_RUNS_DIR = pathlib.Path(path)
    atexit.register(shutil.rmtree, path, True)
    return path


RUNS_DIR = _redirect_runs_dir()
