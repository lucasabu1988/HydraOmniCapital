"""TASK-360 — check a portfolio state, optionally restore a backup.

TASK-395/396 add the generation drills: verify an off-disk generation against its manifest and the
frozen role contract, and restore it into an ISOLATED directory, staged, never over a live book.

    python verify_state.py
    python verify_state.py --state state/portfolio_v9.json
    python verify_state.py --restore state/backup/foo.json --yes
    python verify_state.py --verify-generation D:/hydra_backups/state_v9/20260904/<run_id>
    python verify_state.py --verify-generation D:/hydra_backups/state_v9/20260904   # --latest
    python verify_state.py --restore-into D:/tmp/drill --from-generation <generation dir>

Both drills are read-only with respect to the book. `--restore-into` refuses, before creating
anything, a target that is or contains the live state tree, a target that is not empty, a
generation that does not verify, and any manifest entry name that is not a single plain path
component.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from backup_service import (  # noqa: E402
    BackupRefused,
    latest_generation,
    read_manifest,
    restore_generation,
    verify_generation,
)
from core.state_check import check, format_findings, replay  # noqa: E402
from core.state_migrations import SchemaError, migrate  # noqa: E402

ROOT = Path(__file__).resolve().parent
DEFAULT_STATE = ROOT / "state" / "portfolio_v9.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _report(label: str, state: dict) -> tuple[str, bool]:
    try:
        migrate(state)
    except SchemaError as e:
        text = f"{label}: SCHEMA {e}"
        return text, True
    findings = check(state)
    text = f"{label}:\n{format_findings(findings)}"
    hard = any(f.level == "ERROR" for f in findings)
    return text, hard


def resolve_generation(path) -> Path:
    """Accept either a generation directory or the date directory above it (then use LATEST)."""
    path = Path(path)
    if (path / "backup_manifest.json").exists():
        return path
    latest = latest_generation(path)
    return latest if latest is not None else path


def format_generation_findings(findings) -> str:
    if not findings:
        return "generation check: clean (0 findings)"
    lines = [f"generation check: {len(findings)} finding(s)"]
    for f in findings:
        lines.append(f"  {f.level:<5} {f.code:<22} {f.message}")
    return "\n".join(lines)


def verify_generation_cli(path, *, require_profile: str | None = None) -> int:
    gen = resolve_generation(path)
    findings = verify_generation(gen, require_profile=require_profile)
    manifest = read_manifest(gen) or {}
    print(f"generation {gen}")
    print(f"  run_id  {manifest.get('run_id')}")
    print(f"  date    {manifest.get('date')}   profile {manifest.get('profile')}   "
          f"mode {manifest.get('mode')}")
    print(f"  files   {len(manifest.get('files') or {})}")
    print(format_generation_findings(findings))
    return 1 if any(f.level == "ERROR" for f in findings) else 0


def restore_into_cli(target, generation, *, state_path: Path, require_profile: str = "daily_v9") -> int:
    gen = resolve_generation(generation)
    try:
        out = restore_generation(gen, Path(target), live_state_path=state_path,
                                 require_profile=require_profile)
    except BackupRefused as e:
        print(f"restore REFUSED ({e.code}): {e.message}")
        print("nothing was created: the destination keeps the same file set, count and hashes")
        return 2
    print(f"restored generation {out['run_id']} -> {out['target']}")
    for name in out["names"]:
        print(f"  {out['hashes'][name][:12]}  {name}")
    if out["state_path"] is None:
        print("restored set has no state file")
        return 1
    state = _load(Path(out["state_path"]))
    text, hard = _report(f"restored state {out['state_path']}", state)
    print()
    print(text)
    try:
        books = replay(state)
    except (SchemaError, KeyError, TypeError, ValueError) as e:
        print(f"replay failed: {e}")
        return 1
    cash = sum(float(tr.get("cash") or 0.0)
               for sleeve in (books or {}).values()
               for tr in (sleeve.get("tranches") or []))
    print(f"replay: {len(books or {})} sleeve(s), reconstructed cash {cash:.2f} USD "
          f"(units are in the findings above if they disagree)")
    return 1 if hard else 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="HYDRA state integrity")
    p.add_argument("--state", default=str(DEFAULT_STATE))
    p.add_argument("--restore", default=None, help="backup JSON to copy over the state")
    p.add_argument("--yes", action="store_true", help="required to actually restore")
    p.add_argument("--verify-generation", default=None,
                   help="off-disk generation dir (or its date dir) to verify against its manifest")
    p.add_argument("--restore-into", default=None,
                   help="empty, isolated directory to restore a generation into (never the live tree)")
    p.add_argument("--from-generation", default=None,
                   help="generation dir to restore from; required with --restore-into")
    p.add_argument("--profile", default="daily_v9",
                   help="completeness contract to demand (daily_v9 or sheet_only)")
    args = p.parse_args(argv)

    if args.verify_generation:
        return verify_generation_cli(args.verify_generation, require_profile=args.profile)

    if args.restore_into:
        if not args.from_generation:
            print("--restore-into needs --from-generation")
            return 2
        return restore_into_cli(args.restore_into, args.from_generation,
                                state_path=Path(args.state), require_profile=args.profile)

    state_path = Path(args.state)
    if not state_path.exists():
        print(f"state not found: {state_path}")
        return 1

    current = _load(state_path)
    text, hard = _report(f"state {state_path}", current)
    print(text)

    if args.restore:
        backup_path = Path(args.restore)
        if not backup_path.exists():
            print(f"backup not found: {backup_path}")
            return 1
        backup = _load(backup_path)
        btext, bhard = _report(f"backup {backup_path}", backup)
        print()
        print(btext)
        if not args.yes:
            print("\nrestore refused: pass --yes to copy the backup over the state")
            return 2
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        keep_dir = state_path.parent / "backup"
        keep_dir.mkdir(parents=True, exist_ok=True)
        kept = keep_dir / f"{ts}_replaced.json"
        shutil.copy2(state_path, kept)
        shutil.copy2(backup_path, state_path)
        print(f"\nrestored {backup_path} -> {state_path}")
        print(f"previous state kept at {kept}")
        return 1 if bhard else 0

    return 1 if hard else 0


if __name__ == "__main__":
    raise SystemExit(main())
