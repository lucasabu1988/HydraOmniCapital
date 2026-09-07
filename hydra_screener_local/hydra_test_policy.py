"""TASK-393 — isolate the whole test process, not one module.

An autouse fixture in one file protects neither the other modules nor the subprocesses that
`run_all_tests.py` spawns (a file run as a script never loads a conftest). This module is the
policy itself, and it is installed by IMPORT, at the top of `conftest.py` and at the top of
`run_all_tests.py`, before either imports anything from the package. What it does:

1. **External export.** It exports `HYDRA_BACKUP_DIR` for this process AND every child, so a
   subprocess inherits the throwaway destination rather than the operator's real one.
2. **Explicitly built child environment.** `build_child_env()` strips every `HYDRA_BACKUP*`
   variable and then sets exactly the ones a child should see. `run_all_tests.py` used
   `os.environ.copy()`, which is how the production value reached the children in the first place.
3. **Per-process directories.** One throwaway session tree per suite run, and inside it one
   directory per process (`p<pid>-<token>`), so a parent and its children cannot scribble on each
   other's fixtures.
4. **A deny list, not a temp-path heuristic.** Whatever `HYDRA_BACKUP_DIR` the process INHERITED
   — on this machine, the operator's OneDrive backup root — is registered with
   `backup_service.deny_destination()` and exported in `HYDRA_BACKUP_DENY`, so the service itself
   refuses that destination however a test arrives at it. The rejected branch instead recognised
   temporary LOCATIONS captured at import; a fixture under a custom `--basetemp` was copied
   anyway, because fixture names and locations are arbitrary and provenance is not a path shape.

None of these is the load-bearing guarantee on its own. The load-bearing one is TASK-392: nothing
under `backup_service` reads the environment, and a caller that does not declare its authorised
source roots publishes nothing. This module is the fence around that, for the case where some
future write path forgets.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Any path carrying this marker is a throwaway test destination, never a real backup root.
TEST_BACKUP_MARKER = "hydra-test-backup"

ENV_BACKUP_DIR = "HYDRA_BACKUP_DIR"
ENV_BACKUP_DENY = "HYDRA_BACKUP_DENY"
ENV_SESSION = "HYDRA_TEST_BACKUP_SESSION"
ENV_POLICY = "HYDRA_TEST_POLICY"

_INSTALLED: dict | None = None


#: Written inside a session tree this policy created. Ownership is a fact we recorded, not a
#: shape we recognise: an inherited directory is only ours if this file is in it.
OWNERSHIP_MARKER = ".hydra-test-policy"


def _is_our_session(path: str) -> bool:
    """True only for a directory this policy created and stamped.

    The first version asked `"hydra-test-backup" in str(path)` — the shape of the path, which is
    exactly the mistake this module's own docstring condemns. Two consequences, both reproduced:
    an inherited `HYDRA_BACKUP_DIR` merely CONTAINING that substring (say
    `.../OneDrive/HydraBackups/hydra-test-backup/oops`) was treated as a throwaway and never
    denied, so the service had no forbidden root at all; and `HYDRA_TEST_BACKUP_SESSION` could
    relocate the whole suite's destination into any directory whose name carried the substring.
    """
    if not path or not path.strip():
        return False
    root = Path(path.strip())
    try:
        return root.is_dir() and (root / OWNERSHIP_MARKER).is_file()
    except OSError:  # pragma: no cover - unreadable path
        return False


def _session_root() -> tuple[Path, bool]:
    """The suite run's throwaway tree. Inherited only from a session we can prove is ours."""
    inherited = os.environ.get(ENV_SESSION, "")
    if _is_our_session(inherited):
        return Path(inherited.strip()), False
    root = Path(tempfile.mkdtemp(prefix=f"{TEST_BACKUP_MARKER}-session-"))
    (root / OWNERSHIP_MARKER).write_text(
        f"created by hydra_test_policy, pid {os.getpid()}\n", encoding="utf-8")
    return root, True


def install() -> dict:
    """Install the policy for this process. Idempotent; safe to call from several entry points.

    Returns {"session_root", "process_dir", "denied", "owner"}.
    """
    global _INSTALLED
    if _INSTALLED is not None:
        return _INSTALLED

    # 1. Whatever we inherited is a destination the test session must never publish into. Recorded
    #    BEFORE the export below overwrites it, which is the only moment it is still visible.
    denied: list[str] = []
    inherited = os.environ.get(ENV_BACKUP_DIR, "")
    if inherited.strip():
        # Whatever we inherited is denied, unconditionally. No shape test: a path is not
        # trustworthy because of what it is called. If an outer policy process passed its own
        # per-process directory, denying it is also correct — processes must not publish into each
        # other's fixtures, which is what the per-process split is for.
        denied.append(inherited.strip())
    for part in (os.environ.get(ENV_BACKUP_DENY) or "").split(os.pathsep):
        if part.strip() and part.strip() not in denied:
            denied.append(part.strip())

    session_root, owner = _session_root()
    process_dir = session_root / f"p{os.getpid()}-{uuid.uuid4().hex[:6]}"
    process_dir.mkdir(parents=True, exist_ok=True)

    os.environ[ENV_SESSION] = str(session_root)
    os.environ[ENV_BACKUP_DIR] = str(process_dir)
    os.environ[ENV_BACKUP_DENY] = os.pathsep.join(denied)
    os.environ[ENV_POLICY] = "1"

    # 2. The service refuses the denied roots directly, so this does not depend on the export
    #    surviving a monkeypatch or a re-read.
    try:
        import backup_service
    except ImportError:  # pragma: no cover - only if the package layout changes
        pass
    else:
        for d in denied:
            backup_service.deny_destination(d)

    if owner:
        atexit.register(shutil.rmtree, str(session_root), True)
    _INSTALLED = {"session_root": session_root, "process_dir": process_dir,
                  "denied": tuple(denied), "owner": owner}
    return _INSTALLED


def session_root() -> Path:
    return install()["session_root"]


def process_backup_dir() -> Path:
    """This process's throwaway `HYDRA_BACKUP_DIR`."""
    return install()["process_dir"]


def denied_roots() -> tuple[str, ...]:
    return install()["denied"]


def is_installed(env: dict | None = None) -> bool:
    return (env if env is not None else os.environ).get(ENV_POLICY) == "1"


def build_child_env(extra: dict | None = None, base: dict | None = None) -> dict:
    """The environment a test subprocess gets — built, not inherited.

    Every `HYDRA_BACKUP*` variable is dropped and then set explicitly, so no ambient value can
    reach the child. Other variables pass through: children need PATH and friends, and the
    developer opt-ins (`HYDRA_REGEN_GOLDEN`, `HYDRA_SKIP_HYBRID`, `UNIVERSE`) are deliberate.
    """
    state = install()
    # `HYDRA_TEST_BACKUP_SESSION` does not start with HYDRA_BACKUP, so the original strip left the
    # one variable that relocates the session tree in place, contrary to this docstring.
    env = {k: v for k, v in (base if base is not None else os.environ).items()
           if not k.startswith(("HYDRA_BACKUP", "HYDRA_TEST_BACKUP"))}
    env[ENV_BACKUP_DIR] = str(state["process_dir"])
    env[ENV_SESSION] = str(state["session_root"])
    env[ENV_BACKUP_DENY] = os.pathsep.join(state["denied"])
    env[ENV_POLICY] = "1"
    if extra:
        env.update(extra)
    return env
