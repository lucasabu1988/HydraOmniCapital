"""TASK-392..396 — the backup service. One place that copies the book off disk, and it is told
everything it needs instead of discovering any of it.

WHY THIS EXISTS
---------------
Until 2026-09-06 two write paths (`journal.save_record` and `portfolio_v9.copy_state_off_disk`)
each read `HYDRA_BACKUP_DIR` from the environment *at call time* and copied into it. The variable
is a USER variable on this machine, so every test process inherited the production value: of the
60 files in the real backup root, 35 were pytest fixtures, 2 were real and 21 were undecidable
from content — a journal record with an empty book looks exactly like the live book, which is also
empty until the first settle. No per-file check can separate those, which is why a backup here is
a GENERATION, not a pile of files.

The first attempt at a fix (`feat/astra-12-restore-drill`, rejected) kept the ambient reads and
tried to recognise *temporary locations* instead. Fixture names and locations are arbitrary; a
fixture under a custom `--basetemp` was copied anyway. This module refuses on **authorisation**,
never on location:

  * a source file is copied only if it resolves under a root the CALLER declared authorised;
  * a destination is refused if it resolves under a root something in this process declared
    forbidden (`deny_destination`, installed by the test policy before any module is imported);
  * `HYDRA_BACKUP_DIR` is not read here at all. It is read in exactly one place in the tree,
    `backup_env.py`, and only by CLI entry points.

WHAT "VERIFIED" MEANS
--------------------
Hashes prove byte identity. They do not prove that the state, the sheets and the journal belong to
the same execution. So a generation carries a common `run_id`, its required roles come from the
frozen `GENERATION_PROFILES` table in this file (never from the manifest on disk, which an editor
can weaken), and it is published indivisibly: a generation directory is created whole by an atomic
rename and is never appended to. A second run of the same date publishes a NEW generation with a
new `run_id`; it cannot update the state while keeping yesterday's sheets.

TRANSACTIONAL REFUSAL
---------------------
Every validation runs before the first byte is written. `publish_generation` and
`restore_generation` stage into a private directory and rename it into place at the end; on any
refusal they unwind every directory they created. Before and after a refusal the destination tree
keeps the same file set, count and hashes — `tree_fingerprint` is the assertion the tests use.
"""
from __future__ import annotations

import hashlib
import json
import ntpath
import os
import posixpath
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Iterable, Sequence

from core.state_check import Finding

SCHEMA = 2
MANIFEST_NAME = "backup_manifest.json"
LATEST_NAME = "LATEST"
STATE_NAME = "portfolio_v9.json"
GENERATIONS_SUBDIR = "state_v9"
_STAGING_PREFIX = ".staging-"

#: Roles a generation can hold, and how a flat copy's file NAME maps onto one. The copy is flat,
#: so the name is the only evidence available — which is also why `verify_generation` recomputes
#: the role from the name instead of trusting the manifest's own `role` field.
_JOURNAL_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")
#: `write_instructions` names the sheet `instructions_YYYYMMDD.*` (portfolio_v9.py:233); the
#: hyphenated form is accepted too so a hand-copied sheet still carries its role.
_SHEET = re.compile(r"^instructions_(\d{8}|\d{4}-\d{2}-\d{2})\.(md|json)$")
_PIT = re.compile(r"^(universe_[A-Za-z0-9_.-]+|sectors_\d{8})\.json$")

#: A profile names the set of roles a complete generation of that kind must hold. The table is
#: frozen HERE: `verify_generation` looks the roles up by the manifest's profile NAME and ignores
#: any role list the manifest carries, so editing a manifest cannot reduce the contract to
#: `["state"]` (defect 7 of the rejected branch).
GENERATION_PROFILES: dict[str, tuple[str, ...]] = {
    # daily.py: the whole execution — book, both sheet renderings, the day's journal record and
    # the rebuilt JOURNAL.md. This is the only profile a restore drill accepts.
    "daily_v9": ("state", "sheet_md", "sheet_json", "journal", "journal_md"),
    # portfolio_v9.py run standalone: no journal is written, so demanding one would make every
    # such run "incomplete". A sheet_only generation is a lesser thing BY NAME and can never pass
    # as a daily_v9 one.
    "sheet_only": ("state", "sheet_md", "sheet_json"),
}

_RUN_ID = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_UNSAFE_CHARS = set('<>:"/\\|?*') | {chr(c) for c in range(32)}
_WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class ExecutionMode(Enum):
    """Why this copy is being made. Recorded in the manifest and checkable on verify, so a drill
    copy can never be mistaken for the book's backup."""

    LIVE = "live"
    DRILL = "drill"


class BackupRefused(RuntimeError):
    """Nothing was written. Carries the machine-readable reason and any findings behind it."""

    def __init__(self, code: str, message: str, findings: Sequence[Finding] = ()):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.findings = list(findings)


# --------------------------------------------------------------------------- forbidden destinations

_DENIED: list[Path] = []


def deny_destination(path) -> Path:
    """Declare a destination root this process may never publish into.

    Authorisation, not location: the test policy installs the operator's REAL backup root here
    before any module is imported, so a test that reconstructs that path by any route is refused
    by the service itself rather than by a temp-path heuristic. Production denies nothing.
    """
    resolved = _resolve(path)
    if resolved not in _DENIED:
        _DENIED.append(resolved)
    return resolved


def denied_destinations() -> tuple[Path, ...]:
    return tuple(_DENIED)


def clear_denied_destinations() -> None:
    """Only the tests of the deny list itself should need this."""
    _DENIED.clear()


# --------------------------------------------------------------------------- small helpers

def new_run_id() -> str:
    """One id per execution. Every role in a generation is stamped with it."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def is_safe_entry_name(name) -> bool:
    """A manifest entry (and a source file name) must be ONE plain path component.

    The rejected branch checked the target directory and then did `target / name`; an entry named
    `../victim.txt` overwrote a sibling file. Absolute paths, drive letters, either separator,
    `.`/`..`, control characters and the Windows device names are all refused here, before the
    name is ever joined to anything.
    """
    if not isinstance(name, str) or not name or name in (".", ".."):
        return False
    if any(ch in _UNSAFE_CHARS for ch in name):
        return False
    if name != os.path.basename(name) or name != ntpath.basename(name) or name != posixpath.basename(name):
        return False
    if os.path.isabs(name) or ntpath.isabs(name) or posixpath.isabs(name):
        return False
    if name.endswith(" ") or name.endswith("."):
        return False
    return name.split(".")[0].upper() not in _WIN_RESERVED


def role_for(name: str) -> str:
    """Which guarantee a file carries, from its name. `""` = no role: it may not enter a generation."""
    if name == STATE_NAME:
        return "state"
    if _SHEET.match(name):
        return "sheet_md" if name.endswith(".md") else "sheet_json"
    if name.upper() == "JOURNAL.MD":
        return "journal_md"
    if _JOURNAL_DAY.match(name):
        return "journal"
    if name == "manifest.json":
        return "run_manifest"
    if _PIT.match(name):
        return "pit"
    return ""


def required_roles(profile: str) -> tuple[str, ...]:
    try:
        return GENERATION_PROFILES[profile]
    except KeyError as e:
        raise BackupRefused("UNKNOWN_PROFILE", f"no such generation profile: {profile!r}") from e


def tree_fingerprint(root) -> dict[str, str]:
    """{relative path: sha256} for every file under `root`. `{}` if it does not exist.

    This is what "the destination tree keeps the same file set, count and hashes" is measured
    with, on both sides of a refusal.
    """
    root = Path(root)
    if not root.exists():
        return {}
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            out[p.relative_to(root).as_posix()] = sha256_file(p)
    return out


def _resolve(path) -> Path:
    return Path(path).expanduser().resolve()


def _is_within(child: Path, parent: Path) -> bool:
    if child == parent:
        return True
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def _missing_ancestors(target: Path) -> list[Path]:
    """The directories `target.mkdir(parents=True)` would create, deepest last."""
    out: list[Path] = []
    node = target
    while not node.exists():
        out.append(node)
        if node.parent == node:
            break
        node = node.parent
    out.reverse()
    return out


class _Unwind:
    """Remember what we created so a refusal can leave the tree byte-identical."""

    def __init__(self) -> None:
        self._dirs: list[Path] = []
        self._files: list[Path] = []

    def created(self, path: Path) -> None:
        self._dirs.append(path)

    def mkdir(self, path: Path) -> Path:
        for node in _missing_ancestors(path):
            self.created(node)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def file(self, path: Path) -> Path:
        """A file placed into a destination that already existed, so rollback must remove it."""
        self._files.append(path)
        return path

    def rollback(self) -> None:
        for path in self._files:
            try:
                path.unlink()
            except OSError:  # pragma: no cover - best effort
                pass
        for path in reversed(self._dirs):
            shutil.rmtree(path, ignore_errors=True)
        self._files.clear()
        self._dirs.clear()

    def commit(self) -> None:
        self._files.clear()
        self._dirs.clear()


# --------------------------------------------------------------------------- the context

@dataclass(frozen=True)
class BackupContext:
    """Everything the service is allowed to know. Build it with `BackupContext.create`.

    A caller must pass ALL of:

      run_id                 one id for the whole execution (`new_run_id()`)
      date                   the trading date, YYYY-MM-DD
      dest_root              where generations live. Resolved by the CALLER; the service never
                             consults the environment to find it.
      allowed_source_roots   the tree whose files this caller is authorised to publish. A source
                             that does not resolve under one of these is refused. Entry points
                             declare the live tree; a test declares its own fixture root, which is
                             why a test that forgets to declare one fails CLOSED.
      profile                a key of GENERATION_PROFILES — the role set a complete generation of
                             this kind must hold.
      mode                   LIVE or DRILL.
    """

    run_id: str
    date: str
    dest_root: Path
    allowed_source_roots: tuple[Path, ...]
    profile: str
    mode: ExecutionMode
    denied_dest_roots: tuple[Path, ...] = field(default=())

    @classmethod
    def create(cls, *, run_id: str, date: str, dest_root, allowed_source_roots: Iterable,
               profile: str, mode: ExecutionMode = ExecutionMode.LIVE,
               denied_dest_roots: Iterable = ()) -> BackupContext:
        if not _RUN_ID.match(str(run_id or "")):
            raise BackupRefused("BAD_RUN_ID", f"run_id {run_id!r} is not <YYYYMMDDTHHMMSSZ>-<8 hex>")
        if not _DATE.match(str(date or "")):
            raise BackupRefused("BAD_DATE", f"date {date!r} is not YYYY-MM-DD")
        required_roles(profile)  # raises UNKNOWN_PROFILE
        if not isinstance(mode, ExecutionMode):
            raise BackupRefused("BAD_MODE", f"mode {mode!r} is not an ExecutionMode")
        roots = tuple(dict.fromkeys(_resolve(r) for r in allowed_source_roots))
        if not roots:
            raise BackupRefused(
                "NO_AUTHORISED_SOURCES",
                "allowed_source_roots is empty: a caller must declare which tree it may publish",
            )
        return cls(
            run_id=str(run_id), date=str(date), dest_root=_resolve(dest_root),
            allowed_source_roots=roots, profile=str(profile), mode=mode,
            denied_dest_roots=tuple(dict.fromkeys(_resolve(r) for r in denied_dest_roots)),
        )

    def with_date(self, date: str) -> BackupContext:
        """Same execution (same run_id, same authorisation), re-keyed to the real trading date.

        An entry point has to build the context before the CLI knows which bar it is running on;
        `run()` re-keys it once `today` is known. Nothing about the authorisation changes.
        """
        if str(date) == self.date:
            return self
        return BackupContext.create(
            run_id=self.run_id, date=date, dest_root=self.dest_root,
            allowed_source_roots=self.allowed_source_roots, profile=self.profile,
            mode=self.mode, denied_dest_roots=self.denied_dest_roots,
        )

    def with_profile(self, profile: str) -> BackupContext:
        """Same execution, a different completeness contract. Used by daily.py, which upgrades a
        run to `daily_v9` once the journal exists."""
        if str(profile) == self.profile:
            return self
        return BackupContext.create(
            run_id=self.run_id, date=self.date, dest_root=self.dest_root,
            allowed_source_roots=self.allowed_source_roots, profile=profile,
            mode=self.mode, denied_dest_roots=self.denied_dest_roots,
        )

    @property
    def roles(self) -> tuple[str, ...]:
        return required_roles(self.profile)

    @property
    def date_dir(self) -> Path:
        return self.dest_root / GENERATIONS_SUBDIR / self.date.replace("-", "")

    @property
    def generation_dir(self) -> Path:
        return self.date_dir / self.run_id

    def authorises(self, source: Path) -> bool:
        return any(_is_within(source, root) for root in self.allowed_source_roots)

    def forbidden_by(self) -> Path | None:
        for root in tuple(self.denied_dest_roots) + denied_destinations():
            if _is_within(self.dest_root, root) or _is_within(root, self.dest_root):
                return root
        return None


# --------------------------------------------------------------------------- 394: validate first

@dataclass(frozen=True)
class GenerationPlan:
    """What `publish_generation` WOULD write. Producing one writes nothing."""

    context: BackupContext
    entries: dict[str, dict]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self.entries))


def plan_generation(ctx: BackupContext, sources: Sequence) -> GenerationPlan:
    """Validate every source and the destination. Writes NOTHING, creates NOTHING.

    Raises `BackupRefused` on the first structural problem. This is deliberately called before any
    directory exists: the rejected branch created the destination and wrote a manifest *before*
    judging the files, so a refused copy still left a directory and a manifest behind.
    """
    forbidden = ctx.forbidden_by()
    if forbidden is not None:
        raise BackupRefused(
            "DEST_DENIED",
            f"{ctx.dest_root} is inside a forbidden root ({forbidden}); this process may not publish there",
        )
    if not ctx.allowed_source_roots:  # pragma: no cover - create() refuses this
        raise BackupRefused("NO_AUTHORISED_SOURCES", "no authorised source roots")
    paths = [Path(p) for p in sources]
    if not paths:
        raise BackupRefused("NO_SOURCES", "a generation needs at least the state file")

    entries: dict[str, dict] = {}
    for src in paths:
        name = src.name
        if name == MANIFEST_NAME:
            raise BackupRefused("SOURCE_IS_MANIFEST", f"{name} is written by the service, not copied")
        if not is_safe_entry_name(name):
            raise BackupRefused("SOURCE_UNSAFE_NAME", f"{name!r} is not a single plain path component")
        if src.is_symlink():
            raise BackupRefused("SOURCE_IS_LINK", f"{src} is a link; a generation copies real files only")
        if not src.exists():
            raise BackupRefused("SOURCE_MISSING", f"{src} does not exist")
        if not src.is_file():
            raise BackupRefused("SOURCE_NOT_A_FILE", f"{src} is not a regular file")
        resolved = _resolve(src)
        if not ctx.authorises(resolved):
            raise BackupRefused(
                "SOURCE_NOT_AUTHORISED",
                f"{resolved} is outside the caller's authorised roots "
                f"({', '.join(str(r) for r in ctx.allowed_source_roots)})",
            )
        role = role_for(name)
        if not role:
            raise BackupRefused("SOURCE_UNKNOWN_ROLE", f"{name}: no role in the generation contract")
        prev = entries.get(name)
        if prev is not None:
            if prev["source"] != str(resolved):
                raise BackupRefused(
                    "SOURCE_NAME_COLLISION",
                    f"{name}: two different sources claim this name ({prev['source']} and {resolved})",
                )
            continue
        entries[name] = {
            "role": role,
            "sha256": sha256_file(resolved),
            "bytes": resolved.stat().st_size,
            "source": str(resolved),
            "run_id": ctx.run_id,
        }

    have = {e["role"] for e in entries.values()}
    missing = [r for r in ctx.roles if r not in have]
    if missing:
        raise BackupRefused(
            "GENERATION_INCOMPLETE",
            f"profile {ctx.profile} needs role(s) {', '.join(missing)}; "
            f"a run may not complete by reusing an older generation's roles",
        )
    if ctx.generation_dir.exists():
        raise BackupRefused(
            "GENERATION_EXISTS",
            f"{ctx.generation_dir} already exists; a published generation is immutable, "
            f"publish a new run_id instead",
        )
    return GenerationPlan(context=ctx, entries=entries)


# --------------------------------------------------------------------------- 395: publish whole

def publish_generation(ctx: BackupContext, sources: Sequence) -> dict:
    """Validate, stage, verify, then publish the complete generation in one rename.

    Returns {"generation_dir", "run_id", "date", "profile", "names", "hashes"}.
    Raises `BackupRefused` having written nothing and created no directory.
    """
    plan = plan_generation(ctx, sources)
    unwind = _Unwind()
    staging = ctx.date_dir / f"{_STAGING_PREFIX}{ctx.run_id}"
    try:
        unwind.mkdir(ctx.date_dir)
        unwind.mkdir(staging)
        hashes: dict[str, str] = {}
        for name, entry in sorted(plan.entries.items()):
            dest = staging / name
            if not _is_within(_resolve(dest.parent), _resolve(staging)):  # pragma: no cover - name is validated
                raise BackupRefused("STAGING_ESCAPE", f"{name} would land outside {staging}")
            shutil.copy2(entry["source"], dest)
            digest = sha256_file(dest)
            if digest != entry["sha256"]:
                raise BackupRefused(
                    "COPY_HASH_MISMATCH",
                    f"{name}: staged copy {digest[:12]} != source {entry['sha256'][:12]}",
                )
            hashes[name] = digest
        manifest = {
            "schema": SCHEMA,
            "run_id": ctx.run_id,
            "date": ctx.date,
            "profile": ctx.profile,
            "mode": ctx.mode.value,
            "published_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            # Informational only. verify_generation takes the role set from GENERATION_PROFILES
            # by profile NAME and never from this list.
            "required_roles_informational": list(ctx.roles),
            "files": plan.entries,
        }
        (staging / MANIFEST_NAME).write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        bad = [f for f in verify_generation(staging, require_profile=ctx.profile, require_mode=ctx.mode)
               if f.level == "ERROR"]
        if bad:
            raise BackupRefused(
                "STAGED_GENERATION_INVALID",
                "; ".join(f"{f.code} {f.message}" for f in bad),
                bad,
            )
        os.replace(staging, ctx.generation_dir)
    except BaseException:
        unwind.rollback()
        raise
    unwind.commit()
    _write_latest(ctx.date_dir, ctx.run_id)
    return {
        "generation_dir": ctx.generation_dir, "run_id": ctx.run_id, "date": ctx.date,
        "profile": ctx.profile, "mode": ctx.mode.value,
        "names": sorted(hashes), "hashes": hashes,
    }


def _write_latest(date_dir: Path, run_id: str) -> Path:
    path = date_dir / LATEST_NAME
    tmp = date_dir / f"{LATEST_NAME}.tmp"
    tmp.write_text(run_id + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def latest_generation(date_dir) -> Path | None:
    """The newest published generation for a date, or None. Refuses an unsafe pointer."""
    date_dir = Path(date_dir)
    pointer = date_dir / LATEST_NAME
    if not pointer.exists():
        return None
    run_id = pointer.read_text(encoding="utf-8").strip()
    if not _RUN_ID.match(run_id) or not is_safe_entry_name(run_id):
        return None
    candidate = date_dir / run_id
    return candidate if candidate.is_dir() else None


# --------------------------------------------------------------------------- verification

def read_manifest(generation_dir) -> dict | None:
    path = Path(generation_dir) / MANIFEST_NAME
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def verify_generation(generation_dir, *, require_profile: str | None = None,
                      require_mode: ExecutionMode | None = None) -> list[Finding]:
    """Is this directory a complete, coherent, byte-identical generation? Read-only.

    Checks, in order: the manifest is readable and of a known schema; the profile is one this
    build knows (and the one demanded, if any); every entry name is a safe single component; every
    file is present with the manifest's size and sha256; the role recomputed FROM THE NAME matches
    the manifest's claim; every entry carries the generation's own `run_id`; and no untracked file
    has appeared next to them. Only then are the required roles — taken from GENERATION_PROFILES,
    not from the manifest — checked for completeness.
    """
    gen = Path(generation_dir)
    if not gen.is_dir():
        return [Finding("ERROR", "GEN_MISSING", f"generation dir not found: {gen}")]
    manifest = read_manifest(gen)
    if manifest is None:
        return [Finding("ERROR", "GEN_NO_MANIFEST",
                        f"no readable {MANIFEST_NAME} in {gen}: nothing to verify against")]
    out: list[Finding] = []
    if manifest.get("schema") != SCHEMA:
        out.append(Finding("ERROR", "GEN_SCHEMA",
                           f"manifest schema {manifest.get('schema')!r} != {SCHEMA}"))
    run_id = str(manifest.get("run_id") or "")
    if not _RUN_ID.match(run_id):
        out.append(Finding("ERROR", "GEN_NO_RUN_ID",
                           f"manifest run_id {run_id!r} is missing or malformed: the roles cannot be "
                           f"shown to belong to one execution"))
    profile = str(manifest.get("profile") or "")
    if profile not in GENERATION_PROFILES:
        out.append(Finding("ERROR", "GEN_UNKNOWN_PROFILE",
                           f"profile {profile!r} is not in this build's contract"))
    elif require_profile is not None and profile != require_profile:
        out.append(Finding("ERROR", "GEN_PROFILE_MISMATCH",
                           f"generation is profile {profile!r}, caller demands {require_profile!r}"))
    if require_mode is not None and str(manifest.get("mode") or "") != require_mode.value:
        out.append(Finding("ERROR", "GEN_MODE_MISMATCH",
                           f"generation mode {manifest.get('mode')!r}, caller demands "
                           f"{require_mode.value!r}"))

    entries = manifest.get("files")
    if not isinstance(entries, dict) or not entries:
        out.append(Finding("ERROR", "GEN_EMPTY", f"{MANIFEST_NAME} lists no files"))
        entries = {}
    roles: set[str] = set()
    for name in sorted(entries):
        rec = entries[name] if isinstance(entries[name], dict) else {}
        if not is_safe_entry_name(name):
            out.append(Finding("ERROR", "GEN_UNSAFE_NAME",
                               f"{name!r}: not a single plain path component; refusing to resolve it"))
            continue
        target = gen / name
        if target.is_symlink():
            out.append(Finding("ERROR", "GEN_LINK_ENTRY", f"{name}: is a link, not a copied file"))
            continue
        if not target.is_file():
            out.append(Finding("ERROR", "GEN_FILE_MISSING", f"{name}: in the manifest, not on disk"))
            continue
        digest = sha256_file(target)
        if digest != rec.get("sha256"):
            out.append(Finding("ERROR", "GEN_HASH_MISMATCH",
                               f"{name}: sha256 {digest[:12]} != manifest {str(rec.get('sha256'))[:12]}"))
            continue
        size = target.stat().st_size
        if rec.get("bytes") is not None and int(rec["bytes"]) != size:
            out.append(Finding("ERROR", "GEN_SIZE_MISMATCH",
                               f"{name}: {size} bytes on disk, manifest says {rec.get('bytes')}"))
            continue
        actual_role = role_for(name)
        if not actual_role:
            out.append(Finding("ERROR", "GEN_ROLELESS_FILE",
                               f"{name}: no role in the generation contract"))
            continue
        if rec.get("role") != actual_role:
            out.append(Finding("ERROR", "GEN_ROLE_TAMPERED",
                               f"{name}: manifest claims role {rec.get('role')!r}, the name is "
                               f"{actual_role!r}"))
            continue
        if str(rec.get("run_id") or "") != run_id:
            out.append(Finding("ERROR", "GEN_RUN_ID_MIXED",
                               f"{name}: run_id {rec.get('run_id')!r} != generation {run_id!r}; "
                               f"roles from different executions are not a generation"))
            continue
        roles.add(actual_role)

    tracked = set(entries) | {MANIFEST_NAME}
    untracked = sorted(p.name for p in gen.iterdir() if p.name not in tracked)
    if untracked:
        out.append(Finding("ERROR", "GEN_UNTRACKED_FILE",
                           f"{', '.join(untracked)}: present in {gen.name} but not in the manifest; "
                           f"a published generation is immutable"))

    if profile in GENERATION_PROFILES:
        missing = [r for r in GENERATION_PROFILES[profile] if r not in roles]
        if missing:
            out.append(Finding("ERROR", "GEN_INCOMPLETE",
                               f"profile {profile} is missing role(s) {', '.join(missing)}"))
    return out


def generation_is_complete(generation_dir, *, require_profile: str | None = None,
                           require_mode: ExecutionMode | None = None) -> bool:
    findings = verify_generation(generation_dir, require_profile=require_profile,
                                 require_mode=require_mode)
    return not any(f.level == "ERROR" for f in findings)


# --------------------------------------------------------------------------- 396: hardened restore

def _assert_isolated_target(target: Path, live_state_path: Path) -> None:
    """Refuse a target that could be, contain or be contained by the live book — before any mkdir."""
    live_dir = _resolve(live_state_path).parent
    try:
        resolved = _resolve(target)
    except OSError as e:  # pragma: no cover - unresolvable path
        raise BackupRefused("RESTORE_TARGET_UNRESOLVABLE", f"cannot resolve {target}: {e}") from e
    if _is_within(resolved, live_dir) or _is_within(live_dir, resolved):
        raise BackupRefused("RESTORE_TARGET_IS_LIVE",
                            f"{resolved} is the live state tree ({live_dir}); restore into an "
                            f"isolated directory and compare there")
    if resolved.is_symlink():
        raise BackupRefused("RESTORE_TARGET_IS_LINK", f"{target} is a link; refusing to follow it")
    if resolved.exists():
        if not resolved.is_dir():
            raise BackupRefused("RESTORE_TARGET_NOT_A_DIR", f"{resolved} is not a directory")
        if any(resolved.iterdir()):
            raise BackupRefused("RESTORE_TARGET_NOT_EMPTY", f"{resolved} is not empty")


def restore_generation(generation_dir, target_dir, *, live_state_path,
                       require_profile: str | None = "daily_v9",
                       require_mode: ExecutionMode | None = None) -> dict:
    """Copy a VERIFIED generation into an isolated directory, staging first.

    Order matters and is the point: the generation is verified, then the target is judged, then
    every manifest name is judged, and only after all of that is anything created. The rejected
    branch collected `verify_backup`'s findings and copied anyway, then exited non-zero — exiting
    non-zero after writing is not refusing.

    Returns {"target", "generation_dir", "run_id", "names", "hashes", "state_path"}.
    Raises `BackupRefused` having created nothing.
    """
    gen = Path(generation_dir)
    target = Path(target_dir)

    findings = verify_generation(gen, require_profile=require_profile, require_mode=require_mode)
    bad = [f for f in findings if f.level == "ERROR"]
    if bad:
        raise BackupRefused(
            "RESTORE_SOURCE_INVALID",
            f"{gen} did not verify: " + "; ".join(f"{f.code} {f.message}" for f in bad),
            bad,
        )
    _assert_isolated_target(target, Path(live_state_path))

    manifest = read_manifest(gen) or {}
    entries = dict(manifest.get("files") or {})
    for name in sorted(entries):
        if not is_safe_entry_name(name):  # pragma: no cover - verify already refused this
            raise BackupRefused("RESTORE_UNSAFE_NAME", f"{name!r} is not a single plain path component")
        if (gen / name).is_symlink():  # pragma: no cover - verify already refused this
            raise BackupRefused("RESTORE_LINK_SOURCE", f"{name} is a link inside the generation")

    unwind = _Unwind()
    staging = target / f"{_STAGING_PREFIX}{manifest.get('run_id')}"
    try:
        unwind.mkdir(target)
        unwind.mkdir(staging)
        staging_root = _resolve(staging)
        hashes: dict[str, str] = {}
        for name in sorted(entries):
            dest = staging / name
            if not _is_within(_resolve(dest), staging_root):
                raise BackupRefused("RESTORE_ESCAPE",
                                    f"{name} resolves outside {staging_root}: refusing the write")
            shutil.copy2(gen / name, dest)
            digest = sha256_file(dest)
            if digest != entries[name].get("sha256"):
                raise BackupRefused("RESTORE_HASH_MISMATCH",
                                    f"{name}: restored copy {digest[:12]} differs from the manifest")
            hashes[name] = digest
        shutil.copy2(gen / MANIFEST_NAME, staging / MANIFEST_NAME)
        bad = [f for f in verify_generation(staging, require_profile=require_profile,
                                            require_mode=require_mode) if f.level == "ERROR"]
        if bad:
            raise BackupRefused(
                "RESTORE_STAGED_INVALID",
                "; ".join(f"{f.code} {f.message}" for f in bad),
                bad,
            )
        for name in sorted(entries) + [MANIFEST_NAME]:
            os.replace(staging / name, unwind.file(target / name))
        staging.rmdir()
    except BaseException:
        unwind.rollback()
        raise
    unwind.commit()
    return {
        "target": target, "generation_dir": gen, "run_id": manifest.get("run_id"),
        "profile": manifest.get("profile"), "names": sorted(hashes), "hashes": hashes,
        "state_path": (target / STATE_NAME) if (target / STATE_NAME).exists() else None,
    }
