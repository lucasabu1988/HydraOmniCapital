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
"""
import atexit
import os
import pathlib
import shutil
import sys
import tempfile

#: Any path carrying this marker is a throwaway test destination, never a real backup root.
TEST_BACKUP_MARKER = "hydra-test-backup"


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
