"""Staged, recoverable commit of a run's state and artefacts (audit phase 3).

`portfolio_v9.run()` used to call `save_state()` and *then* write the instruction
sheet. If the sheet failed, the book had already advanced: fills settled, dividends
credited, `last_run_date` stamped, and no sheet to execute (repro R-301). The next
run would see a planned week that never reached Lucas.

The transaction here inverts that. Nothing final is written until every artefact is
staged, validated and read back:

    1. stage the candidate state and every candidate artefact under
       `state/.staging/<run_id>/`
    2. validate: schema, ledger invariants, and a byte-for-byte readback of each
       staged file against the sha256 recorded for it
    3. write COMMIT_INTENT — the point of no return
    4. replace the live files in a fixed order, **state last**
    5. append the completion record to the run journal and clear the staging dir

Multi-file atomicity does not exist on a filesystem, so step 4 is idempotent and
replayable instead. State goes last, so an interruption anywhere in step 4 leaves the
*previous* state authoritative; `recover()` re-applies the remaining replacements from
the staged bytes, verifying each hash, and finishes the journal entry. Running
`recover()` twice is a no-op.

Operational states (phase 9.7): planned -> instructions_written -> committed, or
failed / failed_pending_recovery. `settled` is stamped by the next run that books the
fills, and belongs to the journal, not to this module.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.ledger import check_invariants, format_violations

STAGING_DIRNAME = ".staging"
RUN_JOURNAL = "runs.jsonl"
INTENT_NAME = "COMMIT_INTENT"
MANIFEST_NAME = "manifest.json"
BACKUP_DIRNAME = "backup"

# operational states
PLANNED = "planned"
INSTRUCTIONS_WRITTEN = "instructions_written"
AWAITING_CONFIRMATION = "awaiting_confirmation"
SETTLED = "settled"
COMMITTED = "committed"
FAILED = "failed"
RECOVERY_REQUIRED = "failed_pending_recovery"

TERMINAL_STATES = frozenset({COMMITTED, FAILED, SETTLED})


class CommitError(RuntimeError):
    """The transaction refused to commit. The previous state is still authoritative."""


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def new_run_id(now: datetime | None = None) -> str:
    """Monotonic-by-prefix and collision-proof: microseconds plus a uuid4 tail.

    Second resolution was not enough: three `save_state` calls inside one second
    produced a single backup file and the first two versions were gone (repro R-302).
    """
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S_%f")
    return f"{stamp}_{uuid.uuid4().hex[:8]}"


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def unique_path(path: Path) -> Path:
    """`path` if free, else `path` with a `_2`, `_3`, ... suffix. Never overwrites.

    Phase 3.6: a backup or a journal is evidence. Replacing one silently is how the
    only copy of a state version disappears.
    """
    path = Path(path)
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for n in range(2, 10000):
        candidate = path.with_name(f"{stem}_{n}{suffix}")
        if not candidate.exists():
            return candidate
    raise CommitError(f"cannot find a free name for {path}")


def append_journal(state_dir: Path, record: dict) -> Path:
    """Append one record to the append-only run journal. Never rewrites a line."""
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / RUN_JOURNAL
    line = json.dumps(record, sort_keys=True, default=str, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())
    return path


def read_journal(state_dir: Path) -> list[dict]:
    path = Path(state_dir) / RUN_JOURNAL
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"status": "unparseable", "raw": line})
    return out


class RunTransaction:
    """One run's staged write. Use as a context manager or drive the steps by hand."""

    def __init__(self, state_dir, *, run_id: str | None = None, kind: str = "v9-daily",
                 date: str | None = None, parent_run_id: str | None = None):
        self.state_dir = Path(state_dir)
        self.run_id = run_id or new_run_id()
        self.kind = str(kind)
        self.date = str(date) if date else None
        self.parent_run_id = parent_run_id
        self.staging = self.state_dir / STAGING_DIRNAME / self.run_id
        self.status = PLANNED
        self.error: str | None = None
        self._files: list[dict] = []
        self._state_entry: dict | None = None
        self._committed = False
        self.staging.mkdir(parents=True, exist_ok=True)
        append_journal(self.state_dir, self._record(PLANNED))

    # ------------------------------------------------------------------ staging
    def stage_text(self, target_name: str, text: str, *, role: str = "artifact",
                   encoding: str = "utf-8") -> Path:
        """Stage one text artefact destined for `state_dir/target_name`."""
        return self._stage(target_name, text.encode(encoding), role=role)

    def stage_json(self, target_name: str, payload, *, role: str = "artifact",
                   indent: int = 2) -> Path:
        blob = (json.dumps(payload, indent=indent, default=str, ensure_ascii=False) + "\n")
        return self._stage(target_name, blob.encode("utf-8"), role=role)

    def stage_state(self, target_name: str, state: dict) -> Path:
        """Stage the candidate state. Exactly one per transaction; replaced last."""
        blob = json.dumps(state, indent=2, default=str, ensure_ascii=False)
        entry = self._stage(target_name, blob.encode("utf-8"), role="state")
        return entry

    def _stage(self, target_name: str, blob: bytes, *, role: str) -> Path:
        name = Path(str(target_name)).name
        if not name or name in (".", ".."):
            raise CommitError(f"bad target name {target_name!r}")
        staged = self.staging / name
        staged.write_bytes(blob)
        entry = {
            "name": name,
            "role": role,
            "target": str(self.state_dir / name),
            "staged": str(staged),
            "sha256": sha256_bytes(blob),
            "bytes": len(blob),
        }
        if role == "state":
            if self._state_entry is not None:
                raise CommitError("a transaction stages exactly one state file")
            self._state_entry = entry
        self._files = [f for f in self._files if f["name"] != name]
        self._files.append(entry)
        return staged

    # ------------------------------------------------------------------ validation
    def validate(self, *, state: dict | None = None, extra_checks=None) -> list[str]:
        """Problems that must stop the commit. Empty list = safe to commit.

        Reads every staged file back off the disk and re-hashes it, so a short write
        or a full disk is caught here rather than after the live files are replaced.
        """
        problems: list[str] = []
        if self._state_entry is None:
            problems.append("no candidate state was staged")
        for entry in self._files:
            staged = Path(entry["staged"])
            if not staged.exists():
                problems.append(f"{entry['name']}: staged file is missing")
                continue
            blob = staged.read_bytes()
            if len(blob) != entry["bytes"]:
                problems.append(
                    f"{entry['name']}: staged {len(blob)} bytes, expected {entry['bytes']}")
            elif sha256_bytes(blob) != entry["sha256"]:
                problems.append(f"{entry['name']}: staged content does not match its hash")
            if entry["role"] in ("state", "artifact") and staged.suffix == ".json":
                try:
                    json.loads(blob.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as e:
                    problems.append(f"{entry['name']}: staged JSON does not parse ({e})")
        if state is not None:
            violations = check_invariants(state)
            if violations:
                problems.append(format_violations(violations))
        for check in (extra_checks or []):
            try:
                out = check(state)
            except Exception as e:                       # a broken check is a problem
                problems.append(f"validation check {getattr(check, '__name__', check)!r} raised: {e}")
                continue
            if out:
                problems.extend(out if isinstance(out, list) else [str(out)])
        return problems

    # ------------------------------------------------------------------ commit
    def commit(self, *, state: dict | None = None, extra_checks=None,
               backup: bool = True) -> dict:
        """Validate, then replace the live files. State goes last, on purpose."""
        if self._committed:
            return self.manifest()
        problems = self.validate(state=state, extra_checks=extra_checks)
        if problems:
            self.fail("; ".join(problems), recovery_required=False)
            raise CommitError(
                f"refusing to commit run {self.run_id}; the previous state stays "
                f"authoritative:\n  " + "\n  ".join(problems))

        manifest = self.manifest()
        (self.staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")

        backups = self._backup_targets() if backup else []
        # Point of no return: from here a crash is recoverable, not ambiguous.
        (self.staging / INTENT_NAME).write_text(self.run_id + "\n", encoding="utf-8")

        applied = _apply_staged(self._files, self._state_entry)
        self.status = COMMITTED
        self._committed = True
        record = self._record(COMMITTED, applied=applied, backups=[str(b) for b in backups])
        append_journal(self.state_dir, record)
        shutil.rmtree(self.staging, ignore_errors=True)
        return record

    def mark(self, status: str, **extra) -> dict:
        """Record an operational state transition in the run journal."""
        self.status = str(status)
        rec = self._record(self.status, **extra)
        append_journal(self.state_dir, rec)
        return rec

    def fail(self, error: str, *, recovery_required: bool = True) -> dict:
        """Record a failure. `recovery_required` means live files may be half-replaced."""
        self.error = str(error)
        self.status = RECOVERY_REQUIRED if recovery_required else FAILED
        rec = self._record(self.status, error=self.error)
        append_journal(self.state_dir, rec)
        return rec

    def abandon(self) -> None:
        """Drop the staging dir. Safe only before COMMIT_INTENT exists."""
        if (self.staging / INTENT_NAME).exists():
            raise CommitError(
                f"run {self.run_id} is past COMMIT_INTENT; call recover() instead of abandoning it")
        shutil.rmtree(self.staging, ignore_errors=True)

    def manifest(self) -> dict:
        return {
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "kind": self.kind,
            "date": self.date,
            "status": self.status,
            "files": [dict(f) for f in self._files],
            "state_file": None if self._state_entry is None else self._state_entry["name"],
        }

    def _record(self, status: str, **extra) -> dict:
        rec = {
            "run_id": self.run_id,
            "parent_run_id": self.parent_run_id,
            "kind": self.kind,
            "date": self.date,
            "status": str(status),
            "at": _utc(),
            "files": [f["name"] for f in self._files],
        }
        rec.update(extra)
        return rec

    def _backup_targets(self) -> list[Path]:
        """Copy every live file this run will replace into `backup/<run_id>/`."""
        bdir = self.state_dir / BACKUP_DIRNAME / self.run_id
        out: list[Path] = []
        for entry in self._files:
            live = Path(entry["target"])
            if not live.exists():
                continue
            bdir.mkdir(parents=True, exist_ok=True)
            dest = unique_path(bdir / live.name)
            shutil.copy2(live, dest)
            out.append(dest)
        return out

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc is not None and not self._committed:
            # nothing was replaced: the previous state is intact
            self.fail(f"{type(exc).__name__}: {exc}", recovery_required=False)
            shutil.rmtree(self.staging, ignore_errors=True)
        return False


def _apply_staged(files: list[dict], state_entry: dict | None) -> list[str]:
    """Replace the live files from their staged copies. Artefacts first, state last."""
    applied: list[str] = []
    ordered = [f for f in files if f["role"] != "state"]
    if state_entry is not None:
        ordered.append(state_entry)
    for entry in ordered:
        staged = Path(entry["staged"])
        target = Path(entry["target"])
        if not staged.exists():
            # already applied by an earlier pass: verify the target instead
            if target.exists() and sha256_file(target) == entry["sha256"]:
                applied.append(entry["name"])
                continue
            raise CommitError(f"{entry['name']}: staged copy gone and target does not match")
        if target.exists() and sha256_file(target) == entry["sha256"]:
            applied.append(entry["name"])                # idempotent re-apply
            staged.unlink(missing_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".committing")
        shutil.copy2(staged, tmp)
        os.replace(tmp, target)
        staged.unlink(missing_ok=True)
        applied.append(entry["name"])
    return applied


# ------------------------------------------------------------------ recovery
def pending_runs(state_dir) -> list[dict]:
    """Staged runs that were interrupted, newest last.

    `needs_recovery` is True only past COMMIT_INTENT: those may have replaced some
    live files already. Without the intent marker nothing was touched and the staging
    dir is simply stale.
    """
    root = Path(state_dir) / STAGING_DIRNAME
    if not root.exists():
        return []
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        manifest_path = d / MANIFEST_NAME
        manifest = None
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                manifest = None
        out.append({
            "run_id": d.name,
            "dir": str(d),
            "needs_recovery": (d / INTENT_NAME).exists(),
            "manifest": manifest,
        })
    return out


def recover(state_dir, *, discard_unintended: bool = True) -> dict:
    """Finish or discard interrupted runs. Idempotent: a second call does nothing.

    A run past COMMIT_INTENT is completed from its staged bytes, each verified against
    the manifest hash. A run without the intent marker never touched a live file, so
    its staging dir is discarded (`discard_unintended=False` keeps it for inspection).
    """
    state_dir = Path(state_dir)
    recovered, discarded, failed = [], [], []
    for run in pending_runs(state_dir):
        d = Path(run["dir"])
        if not run["needs_recovery"]:
            if discard_unintended:
                shutil.rmtree(d, ignore_errors=True)
                discarded.append(run["run_id"])
                append_journal(state_dir, {
                    "run_id": run["run_id"], "status": FAILED, "at": _utc(),
                    "note": "staging discarded during recovery; no live file had been replaced",
                })
            continue
        manifest = run["manifest"]
        if not manifest or not manifest.get("files"):
            failed.append({"run_id": run["run_id"], "error": "no usable manifest in the staging dir"})
            append_journal(state_dir, {
                "run_id": run["run_id"], "status": RECOVERY_REQUIRED, "at": _utc(),
                "error": "no usable manifest in the staging dir",
            })
            continue
        files = list(manifest["files"])
        state_entry = next((f for f in files if f.get("role") == "state"), None)
        artefacts = [f for f in files if f.get("role") != "state"]
        try:
            applied = _apply_staged(artefacts, state_entry)
        except CommitError as e:
            failed.append({"run_id": run["run_id"], "error": str(e)})
            append_journal(state_dir, {
                "run_id": run["run_id"], "status": RECOVERY_REQUIRED, "at": _utc(), "error": str(e),
            })
            continue
        append_journal(state_dir, {
            "run_id": run["run_id"], "status": COMMITTED, "at": _utc(),
            "applied": applied, "note": "completed by recover()",
        })
        shutil.rmtree(d, ignore_errors=True)
        recovered.append(run["run_id"])
    return {"recovered": recovered, "discarded": discarded, "failed": failed}


def last_status(state_dir, *, run_id: str | None = None) -> str | None:
    """The most recent journal status, overall or for one run."""
    records = read_journal(state_dir)
    if run_id is not None:
        records = [r for r in records if r.get("run_id") == run_id]
    return records[-1].get("status") if records else None
