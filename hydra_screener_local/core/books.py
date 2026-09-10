"""Which book a state directory is, and where its off-disk copies go.

The live book lives in `state/`; a paper book lives next to it in `state_<name>/` (TASK: paper
trading, 2026-09-10). Both used to copy their off-disk backups and journal revisions into
`HYDRA_BACKUP_DIR/state_v9/<date>/`, so a paper run on the same date would have overwritten the
real book's backup. Every writer now asks these two functions instead of hard-coding the folder.
"""
from __future__ import annotations

import os
from pathlib import Path

LIVE = "state"


def book_of(state_dir) -> str | None:
    """None for the live book (`state`), the suffix for `state_<suffix>` (e.g. "paper"), else the
    directory's own name."""
    name = Path(state_dir).name
    if name == LIVE:
        return None
    return name[len(LIVE) + 1:] if name.startswith(LIVE + "_") and len(name) > len(LIVE) + 1 else name


def backup_folder(book: str | None) -> str:
    """`state_v9` for the live book, `state_v9_<book>` otherwise."""
    return "state_v9" if not book else f"state_v9_{book}"


def journal_dir_for(book: str | None, root) -> Path:
    """`journal/` for the live book, `journal_<book>/` otherwise."""
    return Path(root) / ("journal" if not book else f"journal_{book}")


def off_disk_dest(date_str: str, book: str | None) -> Path | None:
    """HYDRA_BACKUP_DIR/<backup_folder>/<YYYYMMDD>, or None when the variable is unset."""
    root = os.environ.get("HYDRA_BACKUP_DIR")
    if not root:
        return None
    return Path(root) / backup_folder(book) / date_str.replace("-", "")
