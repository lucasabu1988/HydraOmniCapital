"""TASK-392 — the ONE place in the tree that reads the backup environment.

`HYDRA_BACKUP_DIR` (and the deny list `HYDRA_BACKUP_DENY`) are resolved here and nowhere else.
`backup_service` never consults the environment; `journal.save_record` and `portfolio_v9.run` no
longer do either. Only CLI entry points — `daily.main`, `portfolio_v9.main`, `verify_state.main`
— call into this module, and they pass the resulting `BackupContext` down explicitly.

That is the whole of TASK-392's "resolve environment variables only at the entry point": library
code cannot acquire a destination by ambient authority, so a test that does not build a context
gets no backup at all instead of getting the operator's real one.

`preflight.py` still *reads* the variable for its status row. Reading to print is not writing; it
takes `backup_dir=` explicitly when a caller has a context.
"""
from __future__ import annotations

import os
from pathlib import Path

from backup_service import BackupContext, ExecutionMode, new_run_id

ENV_BACKUP_DIR = "HYDRA_BACKUP_DIR"
#: os.pathsep-separated roots this process may never publish into. The test policy exports the
#: inherited production root here; in production it is normally unset.
ENV_BACKUP_DENY = "HYDRA_BACKUP_DENY"


def backup_root(env: dict | None = None) -> Path | None:
    """The configured destination root, or None when the operator has not set one."""
    raw = (env if env is not None else os.environ).get(ENV_BACKUP_DIR)
    if not raw or not str(raw).strip():
        return None
    return Path(str(raw).strip()).expanduser()


def denied_roots(env: dict | None = None) -> tuple[Path, ...]:
    raw = (env if env is not None else os.environ).get(ENV_BACKUP_DENY) or ""
    out = []
    for part in str(raw).split(os.pathsep):
        part = part.strip()
        if part:
            out.append(Path(part).expanduser())
    return tuple(out)


def context_from_env(*, date: str, profile: str, allowed_source_roots,
                     mode: ExecutionMode = ExecutionMode.LIVE, run_id: str | None = None,
                     env: dict | None = None) -> BackupContext | None:
    """Build the context an entry point will hand to the service, or None if no root is configured.

    `allowed_source_roots` is NOT taken from the environment: the entry point states which tree it
    is authorised to publish (for the CLIs, the screener package directory). A caller that cannot
    name its own tree has no business publishing a backup.
    """
    root = backup_root(env)
    if root is None:
        return None
    return BackupContext.create(
        run_id=run_id or new_run_id(),
        date=date,
        dest_root=root,
        allowed_source_roots=allowed_source_roots,
        profile=profile,
        mode=mode,
        denied_dest_roots=denied_roots(env),
    )


def unset_message() -> str:
    return (f"{ENV_BACKUP_DIR} is not set: state/ and journal/ stay on the same disk as the repo. "
            f"Point it at a synced or external folder to get an off-disk generation.")
