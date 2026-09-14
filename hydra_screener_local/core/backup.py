"""Off-disk backup generations that cannot be silently clobbered, half-written, or faked.

What this replaces, and why
---------------------------
`portfolio_v9.copy_state_off_disk` was five lines: `dest.mkdir(exist_ok=True)`, then `copy2`
each file **if it exists**. Three consequences, all of them realised:

  * a second write to the same date overwrote the first, so a generation was whatever ran
    last rather than what the book was on that date;
  * a missing source was skipped in silence, so a generation could hold two of four files and
    look exactly like a complete one;
  * nothing recorded where the bytes came from, so a test writing through the same function
    produced a directory indistinguishable from a production backup.

On 2026-09-13 the three September generations under `HYDRA_BACKUP_DIR/state_v9/` were found to
be pytest fixtures - `20260904` carried `capital_reference: 8000` and a manifest whose
`source` was a pytest tmpdir, while the live book held 30 pending orders and 100000. There was
no valid off-disk copy of the live book at any date, and `docs/RUNBOOK.md` pointed at that
directory as the recovery path.

The rules here
--------------
1. **A generation is never overwritten.** A second write for the same date becomes `_r02`,
   `_r03`, ... The first one keeps saying what it always said.
2. **Every mandatory source must exist before anything is copied.** A missing one is a refusal
   with the path named, and nothing is written - not even the directory.
3. **The manifest is written LAST, and only after the copied bytes have been read back and
   hashed.** Its presence is therefore the statement "this generation is complete and was
   verified"; a generation without one is a partial copy, and `is_complete` says so.
4. **A test destination is identified by a marker FILE, not by the shape of its path.**
   `"hydra-test-backup" in str(path)` describes what a directory is called; a directory can be
   renamed. `.hydra-test-destination` inside the backup root travels with the directory, and
   the kind it implies is recorded in every manifest written there.

Nothing here deletes or renames an existing generation, ever.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

#: Written by the daily run; all three must be present or the generation is refused.
MANDATORY_ROLES = ("state", "sheet_json", "sheet_md")

MANIFEST_NAME = "backup_manifest.json"
TEST_DESTINATION_MARKER = ".hydra-test-destination"
SCHEMA = 2


class BackupRefused(Exception):
    """The generation was not written, and nothing on disk was touched."""


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def destination_kind(root) -> str:
    """`test` when the backup root carries the marker file, else `production`.

    Identity, not the shape of the path. A directory called `hydra-test-backup-xyz` can be
    renamed to anything; the marker inside it moves with it.
    """
    return "test" if (Path(root) / TEST_DESTINATION_MARKER).exists() else "production"


def mark_test_destination(root) -> Path:
    """Stamp a backup root as disposable. Used by the runner and by tests, never by a run."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    marker = root / TEST_DESTINATION_MARKER
    marker.write_text(
        "This directory is a THROWAWAY backup destination.\n"
        "Generations written here are test output and must never be restored from.\n",
        encoding="utf-8")
    return marker


def next_generation(parent: Path, date_str: str) -> Path:
    """`<date>`, or `<date>_r02`, `<date>_r03`, ... - whichever does not exist yet.

    Same convention the journal revisions already use in this tree (`2026-09-04_r01.json`).
    """
    stem = date_str.replace("-", "")
    candidate = parent / stem
    if not candidate.exists():
        return candidate
    n = 2
    while (parent / f"{stem}_r{n:02d}").exists():
        n += 1
        if n > 999:                              # pragma: no cover - a day with 999 reruns
            raise BackupRefused(f"more than 999 generations for {stem} under {parent}")
    return parent / f"{stem}_r{n:02d}"


def is_complete(generation) -> bool:
    """A generation is complete only if its manifest is there - it is written last."""
    return (Path(generation) / MANIFEST_NAME).exists()


def read_manifest(generation) -> dict | None:
    path = Path(generation) / MANIFEST_NAME
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def is_restorable(generation) -> tuple[bool, str]:
    """Should a human restore from this generation? Answer plus the reason.

    Consulted by the runbook drill. A partial copy, or one written into a destination marked
    as disposable, is not a restore candidate however plausible its filenames look.
    """
    gen = Path(generation)
    if not gen.is_dir():
        return False, f"no such generation: {gen}"
    man = read_manifest(gen)
    if man is None:
        return False, ("no manifest: the copy never completed verification, so this is a "
                       "partial generation")
    if man.get("destination_kind") == "test":
        return False, ("written into a destination marked "
                       f"{TEST_DESTINATION_MARKER!r}: this is test output, not a backup")
    missing = [r for r in MANDATORY_ROLES
               if r not in {f.get("role") for f in (man.get("files") or {}).values()}]
    if missing:
        return False, f"manifest is missing mandatory role(s): {missing}"
    return True, f"complete, {len(man.get('files') or {})} file(s), written {man.get('written_utc')}"


def write_generation(parent, date_str: str, sources: dict, *, book: str | None = None,
                     silent: bool = False) -> Path:
    """Copy one generation and return its directory. Refuses rather than half-writing.

    `sources` maps role -> path. Every role in MANDATORY_ROLES must be present AND exist on
    disk; an optional role that is absent is simply not copied and is recorded as such.
    """
    parent = Path(parent)
    missing = [f"{role}={sources.get(role)!r}" for role in MANDATORY_ROLES
               if not sources.get(role) or not Path(sources[role]).is_file()]
    if missing:
        raise BackupRefused(
            "refusing to write a partial generation: mandatory source(s) not on disk: "
            + ", ".join(missing) + ". Nothing was written.")

    kind = destination_kind(parent.parent if parent.name.startswith("state_v9") else parent)
    gen = next_generation(parent, date_str)
    gen.mkdir(parents=True, exist_ok=False)      # never into an existing generation

    manifest = dict(schema=SCHEMA, date=date_str, book=book or "live",
                    destination_kind=kind, written_utc=datetime.now(timezone.utc).isoformat(),
                    generation=gen.name, files={})
    try:
        for role, src in sources.items():
            if not src or not Path(src).is_file():
                manifest.setdefault("absent_optional", []).append(role)
                continue
            src = Path(src)
            want = sha256_file(src)
            dst = gen / src.name
            shutil.copy2(src, dst)
            got = sha256_file(dst)               # read BACK, not the source again
            if got != want:
                raise BackupRefused(
                    f"copy of {src.name} does not match its source "
                    f"(source {want[:12]}, copy {got[:12]}); generation left without a manifest")
            manifest["files"][src.name] = dict(
                role=role, sha256=got, bytes=dst.stat().st_size, source=str(src))
        # LAST, and only now: the manifest is the claim that the above all held.
        tmp = gen / (MANIFEST_NAME + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, gen / MANIFEST_NAME)
    except BackupRefused:
        raise
    except Exception as exc:                     # noqa: BLE001 - re-raised as a refusal
        raise BackupRefused(
            f"{type(exc).__name__} while writing {gen}: {exc}. The generation has no "
            "manifest and must be treated as partial.") from exc

    if not silent:
        note = "" if kind == "production" else "  [TEST DESTINATION]"
        print(f"[backup] {gen} ({len(manifest['files'])} file(s), verified){note}")
    return gen
