import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
#!/usr/bin/env python
"""
Artifact Hygiene Script for HYDRA Screener

Safely removes generated runtime artifacts so the repo stays clean.

Usage:
    python clean_artifacts.py                    # preview (default, safe)
    python clean_artifacts.py --force            # actually delete
    python clean_artifacts.py --all --force      # also clean history (careful!)

What it cleans by default (safe):
- output/*.xlsx, output/*.csv
- backtest/*.xlsx, backtest/*.csv, backtest/*.json (keeps portfolio_cycles.xlsx by default)
- data_cache/*
- __pycache__/** (recursive)
- pine/*.json, pine/*.txt (the runtime summary/watchlist artifacts; source of truth is history/)
- experiments/__pycache__ etc.

Does NOT touch:
- history/ (unless --include-history)
- source code, tests, docs
- .git, venvs, etc.
"""

import argparse
import shutil
from pathlib import Path
import glob

ROOT = Path(__file__).parent

DEFAULT_PATTERNS = [
    "output/*",
    "backtest/*.xlsx",
    "backtest/*.csv",
    "backtest/*.json",
    "backtest/screener_top5_hold5d_equity.csv",
    "data_cache/*",
    "**/__pycache__",
    "pine/hydra_last_summary.*",
    "pine/watchlist*.txt",
    "experiments/__pycache__",
]

HISTORY_PATTERNS = [
    "history/*.json",
]

def find_artifacts(patterns: list[str]) -> list[Path]:
    found = []
    for pat in patterns:
        for p in glob.glob(pat, recursive=True):
            path = Path(p)
            if path.exists() and not path.is_dir() or (path.is_dir() and path.name == "__pycache__"):
                found.append(path)
    return sorted(set(found))

def clean(paths: list[Path], dry_run: bool = True) -> int:
    count = 0
    for p in paths:
        try:
            if p.is_dir():
                if dry_run:
                    print(f"[DRY] Would remove dir: {p}")
                else:
                    shutil.rmtree(p)
                    print(f"[CLEAN] Removed dir: {p}")
            else:
                if dry_run:
                    print(f"[DRY] Would remove: {p}")
                else:
                    p.unlink()
                    print(f"[CLEAN] Removed: {p}")
            count += 1
        except Exception as e:
            print(f"[WARN] Could not remove {p}: {e}")
    return count

def main():
    parser = argparse.ArgumentParser(description="Clean HYDRA generated artifacts")
    parser.add_argument("--force", action="store_true", help="Actually delete files (default is dry-run)")
    parser.add_argument("--all", "--include-history", action="store_true", dest="include_history",
                        help="Also clean history/*.json (destructive for analysis!)")
    parser.add_argument("--keep-portfolio", action="store_true", default=True,
                        help="Keep backtest/portfolio_cycles.xlsx (default)")
    args = parser.parse_args()

    dry = not args.force
    print("HYDRA Artifact Cleaner")
    print("======================")
    if dry:
        print("(DRY RUN - no files will be deleted. Use --force to apply.)")
    else:
        print("!!! LIVE MODE - files will be permanently deleted !!!")

    patterns = DEFAULT_PATTERNS.copy()
    if args.include_history:
        patterns.extend(HISTORY_PATTERNS)

    artifacts = find_artifacts(patterns)

    # Filter portfolio if requested
    if args.keep_portfolio:
        artifacts = [a for a in artifacts if "portfolio_cycles.xlsx" not in str(a)]

    if not artifacts:
        print("No artifacts found to clean.")
        return 0

    print(f"\nFound {len(artifacts)} artifact(s):")
    for a in artifacts[:20]:
        print(f"  - {a}")
    if len(artifacts) > 20:
        print(f"  ... and {len(artifacts)-20} more")

    count = clean(artifacts, dry_run=dry)

    print(f"\n{'Would clean' if dry else 'Cleaned'} {count} item(s).")
    if dry:
        print("Re-run with --force to actually delete.")
    else:
        print("Done. Run 'git status' to see the effect (most should have been ignored anyway).")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
