"""Point-in-time universe and sector snapshots (TASK-362). No network."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

_MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _MODULE_DIR.parent
DEFAULT_PIT = PROJECT_ROOT / "data_cache" / "pit"

UNIVERSE_FILE = re.compile(r"^universe_(.+)_(\d{8})$")
SECTORS_FILE = re.compile(r"^sectors_(\d{8})$")
POINTER_RE = re.compile(r"^same_as_(\d{8})\s*$")


def _pit(pit_dir=None) -> Path:
    return Path(pit_dir) if pit_dir is not None else DEFAULT_PIT


def _date_str(date) -> str:
    if date is None:
        return datetime.now().strftime("%Y%m%d")
    s = str(date).replace("-", "")[:8]
    if len(s) != 8 or not s.isdigit():
        raise ValueError(f"bad snapshot date {date!r}")
    return s


def _read(path: Path):
    text = path.read_text(encoding="utf-8").strip()
    m = POINTER_RE.match(text)
    if m:
        return {"same_as": m.group(1)}
    if text.startswith("{"):
        data = json.loads(text)
        if isinstance(data, dict) and "same_as" in data:
            return {"same_as": str(data["same_as"]).replace("-", "")[:8]}
        return data
    return json.loads(text)


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _write_pointer(path: Path, same_as: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"same_as_{same_as}\n", encoding="utf-8")


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


def _resolve_universe(name: str, date: str, pit_dir, _seen=None) -> dict | None:
    pit = _pit(pit_dir)
    path = pit / f"universe_{name}_{date}.json"
    if not path.exists():
        return None
    data = _read(path)
    if "same_as" in data:
        seen = _seen or set()
        if data["same_as"] in seen:
            return None
        seen.add(data["same_as"])
        return _resolve_universe(name, data["same_as"], pit, seen)
    return data


def _resolve_sectors(date: str, pit_dir, _seen=None) -> dict | None:
    pit = _pit(pit_dir)
    path = pit / f"sectors_{date}.json"
    if not path.exists():
        return None
    data = _read(path)
    if "same_as" in data:
        seen = _seen or set()
        if data["same_as"] in seen:
            return None
        seen.add(data["same_as"])
        return _resolve_sectors(data["same_as"], pit, seen)
    return data


def write_universe_snapshot(
    name: str,
    tickers: list[str],
    date,
    source: str,
    *,
    pit_dir=None,
    fetched_at: str | None = None,
) -> Path:
    pit = _pit(pit_dir)
    pit.mkdir(parents=True, exist_ok=True)
    d = _date_str(date)
    path = pit / f"universe_{name}_{d}.json"
    names = sorted({str(t).strip() for t in tickers if t and str(t).strip()})
    prev_dates = [x for x in list_universe_dates(name, pit) if x < d]
    if prev_dates:
        prev = _resolve_universe(name, prev_dates[-1], pit)
        if prev and list(prev.get("tickers") or []) == names:
            _write_pointer(path, prev_dates[-1])
            return path
    payload = {
        "source": source,
        "fetched_at": fetched_at or datetime.now().isoformat(),
        "count": len(names),
        "tickers": names,
    }
    _write_json(path, payload)
    return path


def write_sectors_snapshot(
    sectors: dict[str, str],
    date,
    *,
    unknown: list[str] | None = None,
    pit_dir=None,
    fetched_at: str | None = None,
) -> Path:
    pit = _pit(pit_dir)
    pit.mkdir(parents=True, exist_ok=True)
    d = _date_str(date)
    path = pit / f"sectors_{d}.json"
    sec = {str(t): str(s) for t, s in (sectors or {}).items() if t}
    unk = sorted(set(unknown or []))
    prev_dates = [x for x in list_sector_dates(pit) if x < d]
    if prev_dates:
        prev = _resolve_sectors(prev_dates[-1], pit)
        if prev and dict(prev.get("sectors") or {}) == sec and list(prev.get("unknown") or []) == unk:
            _write_pointer(path, prev_dates[-1])
            return path
    payload = {
        "fetched_at": fetched_at or datetime.now().isoformat(),
        "count": len(sec),
        "sectors": dict(sorted(sec.items())),
        "unknown": unk,
    }
    _write_json(path, payload)
    return path


def membership(name: str, date, *, pit_dir=None) -> set:
    """Tickers in `name` on the latest snapshot on or before `date`."""
    d = _date_str(date)
    target = _on_or_before(list_universe_dates(name, pit_dir), d)
    if not target:
        return set()
    data = _resolve_universe(name, target, pit_dir) or {}
    return set(data.get("tickers") or [])


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
