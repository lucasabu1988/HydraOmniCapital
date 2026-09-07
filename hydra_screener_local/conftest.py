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
"""
import atexit
import os
import shutil
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
