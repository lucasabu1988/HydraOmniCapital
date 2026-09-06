"""Point-in-time universe and sector snapshots (TASK-362, hardened in audit phase 6).

No network.

Identity
--------
A snapshot is identified by its **content**, not by its date. Before phase 6 the
dated file was rewritten in place, so writing a different universe for the same date
replaced the earlier one and left no trace — two completely different memberships
shared one identity (repro R-601), and nothing recorded a hash at all (R-602).

Three things are on disk now:

    pit/objects/<sha256>.json                      immutable, write-once payload
    pit/universe_<name>_<date>_r<NN>_<sha12>.json  immutable per-revision manifest
    pit/universe_<name>_<date>.json                mutable pointer to the current
                                                   revision (kept so existing
                                                   readers and the snapshots
                                                   already on disk keep working)
    pit/revisions/universe_<name>_<date>.jsonl     append-only revision log

Writing the same content twice is a no-op that returns the existing revision.
Writing *different* content for the same date mints revision 2 and leaves revision 1
byte-identical on disk, so an audit can see both.

Snapshots written before phase 6 carry no hash. They stay readable, and
`snapshot_identity()` reports `recorded_sha256=None` with `verified=False`, so an
audit can tell a content-addressed snapshot from a legacy one instead of assuming.

Missing data
------------
`membership()` and `sectors_at()` still return empty for a missing snapshot, because
the live path has a documented fallback. `require_membership()` and
`require_sectors_at()` raise `PitMissing` — that is what audit and backtest modes
call, so a missing point-in-time input fails closed (phase 6.6).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

_MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _MODULE_DIR.parent
DEFAULT_PIT = PROJECT_ROOT / "data_cache" / "pit"

SCHEMA = 2
OBJECTS_DIRNAME = "objects"
REVISIONS_DIRNAME = "revisions"

# legacy (pre-phase-6) and versioned names both resolve
UNIVERSE_FILE = re.compile(r"^universe_(.+?)_(\d{8})(?:_r(\d+)_([0-9a-f]{12}))?$")
SECTORS_FILE = re.compile(r"^sectors_(\d{8})(?:_r(\d+)_([0-9a-f]{12}))?$")
POINTER_RE = re.compile(r"^same_as_(\d{8})\s*$")


class PitMissing(RuntimeError):
    """A point-in-time input an audited run needs is not on disk."""


def _pit(pit_dir=None) -> Path:
    return Path(pit_dir) if pit_dir is not None else DEFAULT_PIT


def _date_str(date) -> str:
    if date is None:
        return datetime.now().strftime("%Y%m%d")
    s = str(date).replace("-", "")[:8]
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"bad snapshot date {date!r}")
    return s


# ------------------------------------------------------------------ hashing
def canonical_json(obj) -> str:
    """The one serialisation hashes are taken over. Sorted keys, no whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_of(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


#: the only keys that are part of a snapshot's content. Everything else on a
#: manifest is bookkeeping — `fetched_at`, the revision number and the source must
#: not change a snapshot's identity, because fetching the same membership twice is
#: the same snapshot.
CONTENT_KEYS = ("tickers", "sectors", "unknown", "dropped")


def _content_of(payload: dict) -> dict:
    """The part of a manifest that *is* the snapshot, with the bookkeeping stripped."""
    return {k: payload[k] for k in CONTENT_KEYS if k in payload}


# ------------------------------------------------------------------ low-level io
def _read(path: Path):
    text = path.read_text(encoding="utf-8").strip()
    m = POINTER_RE.match(text)
    if m:
        return {"same_as": m.group(1)}
    if text.startswith("{"):
        data = json.loads(text)
        if isinstance(data, dict) and "same_as" in data:
            out = {"same_as": str(data["same_as"]).replace("-", "")[:8]}
            for k in ("sha256", "revision", "schema"):
                if k in data:
                    out[k] = data[k]
            return out
        return data
    return json.loads(text)


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_once(path: Path, obj) -> bool:
    """Write `obj` only if `path` does not exist. Returns True when it wrote."""
    if path.exists():
        return False
    _write_json(path, obj)
    return True


def _object_path(pit: Path, digest: str) -> Path:
    return pit / OBJECTS_DIRNAME / f"{digest}.json"


def _revision_log(pit: Path, kind: str, name: str, date: str) -> Path:
    stem = f"{kind}_{name}_{date}" if name else f"{kind}_{date}"
    return pit / REVISIONS_DIRNAME / f"{stem}.jsonl"


def _append_revision(pit: Path, kind: str, name: str, date: str, record: dict) -> None:
    path = _revision_log(pit, kind, name, date)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(canonical_json(record) + "\n")


def revisions(kind: str, date, *, name: str = "", pit_dir=None) -> list[dict]:
    """Every revision ever written for this (kind, name, date), oldest first."""
    path = _revision_log(_pit(pit_dir), kind, name, _date_str(date))
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                out.append({"revision": None, "raw": line})
    return out


def _versioned_name(kind: str, name: str, date: str, revision: int, digest: str) -> str:
    stem = f"{kind}_{name}_{date}" if name else f"{kind}_{date}"
    return f"{stem}_r{revision:02d}_{digest[:12]}.json"


def _next_revision(pit: Path, kind: str, name: str, date: str) -> int:
    recs = revisions(kind, date, name=name, pit_dir=pit)
    if not recs:
        return 1
    return max(int(r.get("revision") or 0) for r in recs) + 1


def _existing_revision(pit: Path, kind: str, name: str, date: str, digest: str) -> dict | None:
    for rec in revisions(kind, date, name=name, pit_dir=pit):
        if rec.get("sha256") == digest:
            return rec
    return None


# ------------------------------------------------------------------ listing
def list_universe_dates(name: str, pit_dir=None) -> list[str]:
    pit = _pit(pit_dir)
    if not pit.exists():
        return []
    out = []
    for p in pit.glob(f"universe_{name}_*.json"):
        m = UNIVERSE_FILE.match(p.stem)
        if m and m.group(1) == name:
            out.append(m.group(2))
    return sorted(set(out))


def list_sector_dates(pit_dir=None) -> list[str]:
    pit = _pit(pit_dir)
    if not pit.exists():
        return []
    out = []
    for p in pit.glob("sectors_*.json"):
        m = SECTORS_FILE.match(p.stem)
        if m:
            out.append(m.group(1))
    return sorted(set(out))


def _on_or_before(dates: list[str], date: str) -> str | None:
    ok = [d for d in dates if d <= date]
    return ok[-1] if ok else None


# ------------------------------------------------------------------ resolution
def _payload(pit: Path, path: Path) -> dict | None:
    """Read a manifest and inline its content-addressed object when it has one."""
    if not path.exists():
        return None
    data = _read(path)
    if not isinstance(data, dict):
        return None
    digest = data.get("object") or data.get("sha256")
    if digest and "tickers" not in data and "sectors" not in data:
        obj = _object_path(pit, str(digest))
        if obj.exists():
            body = _read(obj)
            if isinstance(body, dict):
                merged = dict(body)
                merged.update({k: v for k, v in data.items() if k not in body})
                return merged
    return data


def _resolve_universe(name: str, date: str, pit_dir, _seen=None) -> dict | None:
    pit = _pit(pit_dir)
    data = _payload(pit, pit / f"universe_{name}_{date}.json")
    if data is None:
        return None
    if "same_as" in data:
        seen = _seen or set()
        if data["same_as"] in seen:
            return None
        seen.add(data["same_as"])
        return _resolve_universe(name, data["same_as"], pit, seen)
    return data


def _resolve_sectors(date: str, pit_dir, _seen=None) -> dict | None:
    pit = _pit(pit_dir)
    data = _payload(pit, pit / f"sectors_{date}.json")
    if data is None:
        return None
    if "same_as" in data:
        seen = _seen or set()
        if data["same_as"] in seen:
            return None
        seen.add(data["same_as"])
        return _resolve_sectors(data["same_as"], pit, seen)
    return data


# ------------------------------------------------------------------ writing
def _commit(pit: Path, kind: str, name: str, date: str, content: dict, *,
            source: str | None, fetched_at: str | None) -> tuple[Path, dict]:
    """Write an immutable revision plus the mutable dated pointer. Idempotent."""
    digest = sha256_of(content)
    raw_digest = sha256_of(content.get("_raw")) if content.get("_raw") is not None else None
    body = {k: v for k, v in content.items() if k != "_raw"}

    prior = _existing_revision(pit, kind, name, date, digest)
    if prior is not None:
        # same content for the same date: nothing new to record
        return Path(prior["path"]), prior

    revision = _next_revision(pit, kind, name, date)
    stamp = fetched_at or datetime.now().isoformat()
    rows = len(body.get("tickers") or body.get("sectors") or ())

    _write_once(_object_path(pit, digest), body)

    manifest = {
        "schema": SCHEMA,
        "kind": kind,
        "name": name or None,
        "date": date,
        "revision": revision,
        "sha256": digest,
        "raw_sha256": raw_digest,
        "object": digest,
        "source": source,
        "fetched_at": stamp,
        "rows": rows,
        "count": rows,
    }
    versioned = pit / _versioned_name(kind, name, date, revision, digest)
    _write_once(versioned, {**manifest, **body})

    record = dict(manifest, path=str(versioned))
    _append_revision(pit, kind, name, date, record)

    # the dated file is the pointer to the current revision; the revision itself and
    # its object are immutable, so replacing this pointer destroys nothing
    _write_json(pit / (f"{kind}_{name}_{date}.json" if name else f"{kind}_{date}.json"),
                {**manifest, **body})
    return versioned, record


def _commit_pointer(pit: Path, kind: str, name: str, date: str, same_as: str,
                    digest: str) -> tuple[Path, dict]:
    """Record 'this date's content equals an earlier date's'. Saves a 3000-name copy."""
    content = {"same_as": same_as}
    prior = _existing_revision(pit, kind, name, date, sha256_of(content))
    if prior is not None:
        return Path(prior["path"]), prior
    revision = _next_revision(pit, kind, name, date)
    manifest = {
        "schema": SCHEMA, "kind": kind, "name": name or None, "date": date,
        "revision": revision, "sha256": sha256_of(content), "content_sha256": digest,
        "same_as": same_as, "fetched_at": datetime.now().isoformat(),
    }
    versioned = pit / _versioned_name(kind, name, date, revision, manifest["sha256"])
    _write_once(versioned, manifest)
    record = dict(manifest, path=str(versioned))
    _append_revision(pit, kind, name, date, record)
    _write_json(pit / (f"{kind}_{name}_{date}.json" if name else f"{kind}_{date}.json"), manifest)
    return versioned, record


def write_universe_snapshot(
    name: str,
    tickers: list[str],
    date,
    source: str,
    *,
    pit_dir=None,
    fetched_at: str | None = None,
    raw=None,
) -> Path:
    """Write a universe snapshot. Returns the *pointer* path for this date.

    Writing the same membership twice for one date is a no-op. Writing a different
    membership mints a new revision and leaves the previous one on disk (phase 6.2).
    """
    pit = _pit(pit_dir)
    pit.mkdir(parents=True, exist_ok=True)
    d = _date_str(date)
    names = sorted({str(t).strip() for t in tickers if t and str(t).strip()})
    content: dict = {"tickers": names}
    if raw is not None:
        content["_raw"] = raw

    prev_dates = [x for x in list_universe_dates(name, pit) if x < d]
    if prev_dates:
        prev = _resolve_universe(name, prev_dates[-1], pit)
        if prev and list(prev.get("tickers") or []) == names:
            _commit_pointer(pit, "universe", name, d, prev_dates[-1], sha256_of({"tickers": names}))
            return pit / f"universe_{name}_{d}.json"

    _commit(pit, "universe", name, d, content, source=source, fetched_at=fetched_at)
    return pit / f"universe_{name}_{d}.json"


def write_sectors_snapshot(
    sectors: dict[str, str],
    date,
    *,
    unknown: list[str] | None = None,
    pit_dir=None,
    fetched_at: str | None = None,
    raw=None,
) -> Path:
    """Write a sector snapshot. Corrupt entries are dropped, never serialised.

    Phase 6.7: a `None`, a float NaN or a negative-cache sentinel must not become the
    string `"None"` / `"nan"` and then be read back as a real GICS sector.
    """
    pit = _pit(pit_dir)
    pit.mkdir(parents=True, exist_ok=True)
    d = _date_str(date)
    sec, dropped = clean_sector_map(sectors)
    unk = sorted(set(str(u) for u in (unknown or [])) | set(dropped))
    content: dict = {"sectors": dict(sorted(sec.items())), "unknown": unk}
    if dropped:
        content["dropped"] = sorted(dropped)
    if raw is not None:
        content["_raw"] = raw

    prev_dates = [x for x in list_sector_dates(pit) if x < d]
    if prev_dates:
        prev = _resolve_sectors(prev_dates[-1], pit)
        if prev and dict(prev.get("sectors") or {}) == sec and list(prev.get("unknown") or []) == unk:
            _commit_pointer(pit, "sectors", "", d, prev_dates[-1],
                            sha256_of({k: v for k, v in content.items() if k != "_raw"}))
            return pit / f"sectors_{d}.json"

    _commit(pit, "sectors", "", d, content, source=None, fetched_at=fetched_at)
    return pit / f"sectors_{d}.json"


BAD_SECTOR_VALUES = frozenset({"", "none", "nan", "null", "n/a", "na", "-", "?", "unknown"})


def clean_sector_map(sectors) -> tuple[dict[str, str], list[str]]:
    """(usable map, names dropped). Phase 6.7.

    A sector is usable only if it is a non-empty string that is not one of the
    placeholder spellings a failed lookup leaves behind. Everything else goes to the
    dropped list and is reported as unknown, never serialised as a sector.
    """
    out: dict[str, str] = {}
    dropped: list[str] = []
    for ticker, sector in (sectors or {}).items():
        tk = str(ticker).strip()
        if not tk:
            continue
        if sector is None or isinstance(sector, bool):
            dropped.append(tk)
            continue
        if isinstance(sector, float):
            dropped.append(tk)                       # NaN and any numeric sector
            continue
        if not isinstance(sector, str):
            dropped.append(tk)
            continue
        s = sector.strip()
        if not s or s.lower() in BAD_SECTOR_VALUES:
            dropped.append(tk)
            continue
        out[tk] = s
    return out, sorted(set(dropped))


# ------------------------------------------------------------------ reading
def snapshot_identity(kind: str, date, *, name: str = "", pit_dir=None) -> dict:
    """Everything an audit needs to say *which* snapshot a run used (phase 6.4/6.5).

    `verified` is True only when the manifest carries a sha256 and the content still
    hashes to it. A snapshot written before phase 6 has no recorded hash, so
    `recorded_sha256` is None and `verified` is False — legacy, not corrupt.
    """
    pit = _pit(pit_dir)
    d = _date_str(date)
    if kind == "universe":
        data = _resolve_universe(name, d, pit)
        pointer = pit / f"universe_{name}_{d}.json"
    else:
        data = _resolve_sectors(d, pit)
        pointer = pit / f"sectors_{d}.json"
    if data is None:
        return {"kind": kind, "name": name or None, "date": d, "present": False,
                "sha256": None, "recorded_sha256": None, "verified": False,
                "revision": None, "source": None, "fetched_at": None, "rows": 0,
                "schema": None, "path": str(pointer)}

    raw_manifest = _read(pointer) if pointer.exists() else {}
    content = _content_of(data)
    computed = sha256_of(content)
    recorded = data.get("sha256") or (raw_manifest.get("sha256") if isinstance(raw_manifest, dict) else None)
    rows = len(data.get("tickers") or data.get("sectors") or ())
    return {
        "kind": kind,
        "name": name or None,
        "date": d,
        "present": True,
        "sha256": computed,
        "recorded_sha256": recorded,
        "raw_sha256": data.get("raw_sha256"),
        "verified": bool(recorded) and recorded == computed,
        "revision": data.get("revision"),
        "source": data.get("source"),
        "fetched_at": data.get("fetched_at"),
        "rows": rows,
        "schema": data.get("schema"),
        "path": str(pointer),
        "same_as": raw_manifest.get("same_as") if isinstance(raw_manifest, dict) else None,
    }


def sectors_at(date=None, *, pit_dir=None) -> tuple[dict, str | None]:
    """(ticker -> sector, snapshot date) from the latest snapshot on or before `date`.

    ({}, None) when there is none. Use `require_sectors_at` in audit/backtest mode.
    """
    dates = list_sector_dates(pit_dir)
    if not dates:
        return {}, None
    pick = _on_or_before(dates, _date_str(date)) if date is not None else dates[-1]
    if pick is None:
        return {}, None
    data = _resolve_sectors(pick, pit_dir)
    if not data:
        return {}, None
    clean, _ = clean_sector_map(data.get("sectors") or {})
    return clean, pick


def require_sectors_at(date=None, *, pit_dir=None) -> tuple[dict, str | None, dict]:
    """Like `sectors_at`, but raises `PitMissing` instead of returning empty.

    Phase 6.6: an audited or backtested run must not silently proceed without the
    point-in-time sector map it claims to have used.
    """
    sec, pick = sectors_at(date, pit_dir=pit_dir)
    if not sec or pick is None:
        raise PitMissing(
            f"no PIT sector snapshot on or before {_date_str(date) if date is not None else 'today'} "
            f"in {_pit(pit_dir)}; refusing to run in audit mode")
    return sec, pick, snapshot_identity("sectors", pick, pit_dir=pit_dir)


def membership(name: str, date, *, pit_dir=None) -> set:
    """Tickers in `name` on the latest snapshot on or before `date`."""
    d = _date_str(date)
    target = _on_or_before(list_universe_dates(name, pit_dir), d)
    if not target:
        return set()
    data = _resolve_universe(name, target, pit_dir) or {}
    return set(data.get("tickers") or [])


def require_membership(name: str, date, *, pit_dir=None) -> tuple[set, str, dict]:
    """Like `membership`, but raises `PitMissing` and returns the identity too."""
    d = _date_str(date)
    target = _on_or_before(list_universe_dates(name, pit_dir), d)
    if not target:
        raise PitMissing(
            f"no PIT universe snapshot for {name!r} on or before {d} in {_pit(pit_dir)}; "
            f"refusing to run in audit mode")
    names = membership(name, d, pit_dir=pit_dir)
    if not names:
        raise PitMissing(f"PIT universe snapshot {name!r} at {target} is empty")
    return names, target, snapshot_identity("universe", target, name=name, pit_dir=pit_dir)


def changes(name: str, d1, d2, *, pit_dir=None) -> tuple[set, set]:
    a = membership(name, d1, pit_dir=pit_dir)
    b = membership(name, d2, pit_dir=pit_dir)
    return (b - a, a - b)


def history(name: str, *, pit_dir=None) -> pd.DataFrame:
    dates = list_universe_dates(name, pit_dir)
    rows = []
    prev: set | None = None
    for d in dates:
        data = _resolve_universe(name, d, pit_dir)
        if data is None:
            continue
        pit = _pit(pit_dir)
        raw = _read(pit / f"universe_{name}_{d}.json")
        if "same_as" in raw:
            continue
        cur = set(data.get("tickers") or [])
        added = cur if prev is None else cur - prev
        dropped = set() if prev is None else prev - cur
        rows.append({
            "date": d,
            "count": len(cur),
            "added": len(added),
            "dropped": len(dropped),
        })
        prev = cur
    if not rows:
        return pd.DataFrame(columns=["date", "count", "added", "dropped"])
    return pd.DataFrame(rows)


def inputs_manifest(*, universes: list[str] | None = None, date=None, pit_dir=None) -> dict:
    """Identity of every PIT input a run used, for the run JSON (phase 6.5)."""
    out: dict = {"pit_dir": str(_pit(pit_dir)), "schema": SCHEMA, "universes": {}}
    for name in (universes or []):
        target = _on_or_before(list_universe_dates(name, pit_dir),
                               _date_str(date) if date is not None else _date_str(None))
        out["universes"][name] = (
            snapshot_identity("universe", target, name=name, pit_dir=pit_dir) if target
            else {"kind": "universe", "name": name, "present": False, "sha256": None,
                  "verified": False}
        )
    dates = list_sector_dates(pit_dir)
    pick = _on_or_before(dates, _date_str(date) if date is not None else _date_str(None)) if dates else None
    out["sectors"] = (
        snapshot_identity("sectors", pick, pit_dir=pit_dir) if pick
        else {"kind": "sectors", "present": False, "sha256": None, "verified": False}
    )
    out["fallback_used"] = [
        k for k, v in [("sectors", out["sectors"]), *out["universes"].items()]
        if not v.get("present")
    ]
    return out
