"""Test-session policy: a test run must never be able to write into a real backup root.

This file exists to be imported by pytest BEFORE any test module, so the policy is in place
before any package module can be imported. Everything it does lives in `hydra_test_policy`, which
`run_all_tests.py` imports too — files run as scripts never load a conftest, so one layer here
would leave the subprocesses uncovered (TASK-393).

History: `HYDRA_BACKUP_DIR` is a USER variable on this machine and, until TASK-392,
`journal.save_record` and `portfolio_v9.copy_state_off_disk` both read it at call time and copied
into it. On 2026-09-06 every off-disk copy of the live book turned out to be a test fixture, and
`state_v9/20260904/` — the directory for the book holding the 30 pending orders — had been
overwritten by a fixture with `capital_reference: 8000`.

This redirect is no longer the thing standing between a test and the real root. Since TASK-392 the
backup service reads no environment variable at all and refuses any source file the caller has not
declared authorised, so a test that does not build a `BackupContext` publishes nothing. The policy
here is the fence around that: an explicit deny list for the inherited root, per-process throwaway
destinations, and an explicitly built environment for child processes.
"""
import hydra_test_policy

#: Re-exported so the isolation tests can assert both layers agree on one marker.
TEST_BACKUP_MARKER = hydra_test_policy.TEST_BACKUP_MARKER

_POLICY = hydra_test_policy.install()
BACKUP_DIR = str(_POLICY["process_dir"])
SESSION_ROOT = str(_POLICY["session_root"])
DENIED_ROOTS = _POLICY["denied"]
