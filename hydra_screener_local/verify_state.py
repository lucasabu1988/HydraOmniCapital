"""TASK-360 — check a portfolio state, optionally restore a backup.

    python verify_state.py
    python verify_state.py --state state/portfolio_v9.json
    python verify_state.py --restore state/backup/foo.json --yes
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

from core.state_check import check, format_findings  # noqa: E402
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


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="HYDRA state integrity")
    p.add_argument("--state", default=str(DEFAULT_STATE))
    p.add_argument("--restore", default=None, help="backup JSON to copy over the state")
    p.add_argument("--yes", action="store_true", help="required to actually restore")
    args = p.parse_args(argv)

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
