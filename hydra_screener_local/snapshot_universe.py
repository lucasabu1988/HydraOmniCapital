"""TASK-362 — write PIT snapshots of universes and sectors.

    python snapshot_universe.py --seed
    python snapshot_universe.py --universe all --date 20260906

`--seed` reads local ticker CSVs / sector cache (no network). A live
`--universe` call uses `get_universe` and is not used in tests.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.pit import (  # noqa: E402
    DEFAULT_PIT,
    write_sectors_snapshot,
    write_universe_snapshot,
)
from data.sectors import UNKNOWN_SECTOR  # noqa: E402

ROOT = Path(__file__).resolve().parent
CSV_UNIVERSES = ("sp500", "nasdaq100", "dow30", "russell1000", "russell2000")
ALL_PARTS = ("sp500", "nasdaq100", "dow30", "russell1000", "russell2000")


def _csv_path(name: str) -> Path | None:
    for folder in (ROOT / "output", ROOT / "data_cache"):
        p = folder / f"{name}_tickers.csv"
        if p.exists():
            return p
    return None


def _read_csv(path: Path) -> list[str]:
    names = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines()):
        t = line.strip().strip('"')
        if not t or (i == 0 and t.lower() == "ticker"):
            continue
        names.append(t)
    return names


def _mtime_date(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y%m%d")


def seed(pit_dir=None) -> list[Path]:
    """First snapshots from local ticker files + sector cache. No network."""
    written = []
    loaded: dict[str, tuple[list[str], str, str]] = {}
    for name in CSV_UNIVERSES:
        path = _csv_path(name)
        if path is None:
            print(f"seed: no csv for {name}")
            continue
        tickers = _read_csv(path)
        d = _mtime_date(path)
        loaded[name] = (tickers, d, str(path.relative_to(ROOT)).replace("\\", "/"))
        written.append(write_universe_snapshot(
            name, tickers, d, loaded[name][2], pit_dir=pit_dir,
        ))
        print(f"seed universe {name}: {len(tickers)} names date={d}")

    if "russell1000" in loaded and "russell2000" in loaded:
        r3 = sorted(set(loaded["russell1000"][0]) | set(loaded["russell2000"][0]))
        d = max(loaded["russell1000"][1], loaded["russell2000"][1])
        written.append(write_universe_snapshot(
            "russell3000", r3, d, "union:russell1000+russell2000", pit_dir=pit_dir,
        ))
        print(f"seed universe russell3000: {len(r3)} names date={d}")

    if loaded:
        parts = [loaded[n][0] for n in ALL_PARTS if n in loaded]
        if parts:
            all_t = sorted(set().union(*parts))
            d = max(loaded[n][1] for n in ALL_PARTS if n in loaded)
            written.append(write_universe_snapshot(
                "all", all_t, d, "union:" + "+".join(n for n in ALL_PARTS if n in loaded),
                pit_dir=pit_dir,
            ))
            print(f"seed universe all: {len(all_t)} names date={d}")

    cache_file = ROOT / "data_cache" / "sector_cache.json"
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"seed sectors skipped: {e}")
            cache = {}
        sectors = dict((cache or {}).get("sectors") or {})
        unknown = sorted(t for t, s in sectors.items() if s == UNKNOWN_SECTOR)
        d = _mtime_date(cache_file)
        written.append(write_sectors_snapshot(
            sectors, d, unknown=unknown, pit_dir=pit_dir,
            fetched_at=str((cache or {}).get("updated") or ""),
        ))
        print(f"seed sectors: {len(sectors)} mapped, {len(unknown)} unknown date={d}")
    else:
        print("seed: no sector_cache.json")
    return written


def snapshot_live(universe: str, date: str | None, pit_dir=None) -> Path:
    from data.universe import get_universe
    tickers = get_universe(universe=universe)
    d = date or datetime.now().strftime("%Y%m%d")
    return write_universe_snapshot(
        universe, tickers, d, f"get_universe({universe})", pit_dir=pit_dir,
    )


def snapshot_sectors_from_cache(date: str | None = None, pit_dir=None) -> Path | None:
    """Sectors snapshot from data_cache/sector_cache.json (no network)."""
    cache_file = ROOT / "data_cache" / "sector_cache.json"
    if not cache_file.exists():
        return None
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
    except Exception:
        return None
    raw = dict((cache or {}).get("sectors") or {})
    sectors = {t: (v if isinstance(v, str) else (v or {}).get("sector")) for t, v in raw.items()}
    sectors = {t: s for t, s in sectors.items() if s}
    unknown = sorted(t for t, s in sectors.items() if s == UNKNOWN_SECTOR)
    d = date or datetime.now().strftime("%Y%m%d")
    return write_sectors_snapshot(
        sectors, d, unknown=unknown, pit_dir=pit_dir,
        fetched_at=str((cache or {}).get("updated") or ""),
    )


def snapshot_after_run(universe: str, date: str | None = None, pit_dir=None) -> list[Path]:
    """daily.py hook (TASK-362): one universe snapshot (get_universe is cache-fresh right
    after a run) and one sectors snapshot from the cache. Pointers when nothing changed."""
    written = []
    try:
        written.append(snapshot_live(universe, date, pit_dir=pit_dir))
    except Exception as e:
        print(f"[pit] universe snapshot skipped: {e}")
    try:
        p = snapshot_sectors_from_cache(date, pit_dir=pit_dir)
        if p is not None:
            written.append(p)
    except Exception as e:
        print(f"[pit] sectors snapshot skipped: {e}")
    return written


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="HYDRA PIT universe/sector snapshots")
    p.add_argument("--seed", action="store_true", help="seed from local CSVs (no network)")
    p.add_argument("--universe", default=None)
    p.add_argument("--date", default=None)
    p.add_argument("--pit-dir", default=None)
    args = p.parse_args(argv)
    pit = args.pit_dir or str(DEFAULT_PIT)
    if args.seed:
        seed(pit_dir=pit)
        return 0
    if args.universe:
        path = snapshot_live(args.universe, args.date, pit_dir=pit)
        print(f"wrote {path}")
        return 0
    p.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
