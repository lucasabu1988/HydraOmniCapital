"""TASK-359 — inspect / prune local run manifests.

    python runlog_cli.py --last
    python runlog_cli.py --prune
"""
from __future__ import annotations

import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.runlog import KEEP_LAST, latest_run, load_manifest, prune  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="HYDRA run manifests")
    p.add_argument("--last", action="store_true", help="print the latest manifest.json")
    p.add_argument("--prune", action="store_true", help=f"keep the last {KEEP_LAST} run dirs")
    p.add_argument("--keep", type=int, default=KEEP_LAST)
    p.add_argument("--dir", default=None, help="runs directory (default hydra_screener_local/runs)")
    args = p.parse_args(argv)
    if not (args.last or args.prune):
        p.print_help()
        return 2
    if args.prune:
        n = prune(args.dir, keep=args.keep)
        print(f"prune: removed {n}, keep={args.keep}")
    if args.last:
        path = latest_run(args.dir)
        if path is None:
            print("no runs")
            return 1
        man = load_manifest(path)
        print(f"# {path}")
        print(json.dumps(man, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
