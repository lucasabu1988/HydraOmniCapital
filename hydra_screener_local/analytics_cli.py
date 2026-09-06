"""TASK-367 — attribution report over the v9 state (read-only).

    python analytics_cli.py                       # live book, marks = last_px in the state
    python analytics_cli.py --portfolio mini
    python analytics_cli.py --state-dir path/to/state --out-dir path/to/reports

Writes <state-dir>/analytics/attribution_<date>.csv (positions) and ATTRIBUTION.md; never touches
portfolio_v9.json. The weekly column comes from the previous ATTRIBUTION block saved next to it.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from analytics.attribution import attribution, diff, render_markdown  # noqa: E402
from portfolio_v9 import DEFAULT_STATE_DIR, STATE_NAME  # noqa: E402

FIELDS = ("sleeve", "tranche", "ticker", "units", "avg_cost", "mark", "market_value", "unrealised", "realised", "fees")


def write_report(state: dict, out_dir: Path) -> tuple[Path, Path, dict]:
    out_dir.mkdir(parents=True, exist_ok=True)
    block = attribution(state)
    prev_path = out_dir / "attribution_last.json"
    prev = None
    if prev_path.exists():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
        except Exception:
            prev = None
    weekly = diff(prev, block) if prev and prev.get("as_of") != block.get("as_of") else None
    stamp = str(block.get("as_of") or "undated").replace("-", "")
    csv_path = out_dir / f"attribution_{stamp}.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for p in block["positions"]:
            w.writerow({k: p.get(k) for k in FIELDS})
    md_path = out_dir / "ATTRIBUTION.md"
    md_path.write_text(render_markdown(block, weekly), encoding="utf-8")
    slim = {k: v for k, v in block.items() if k != "positions"}
    prev_path.write_text(json.dumps(slim, indent=2, default=str), encoding="utf-8")
    return csv_path, md_path, block


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="HYDRA v9 attribution (read-only)")
    p.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    p.add_argument("--portfolio", default=None, help="Book from portfolios.toml (TASK-365)")
    p.add_argument("--out-dir", default=None, help="default <state-dir>/analytics")
    args = p.parse_args(argv)
    state_dir = Path(args.state_dir)
    if args.portfolio:
        from core.portfolios import resolve
        state_dir = resolve(args.portfolio, allow_disabled=True).state_dir
    path = state_dir / STATE_NAME
    if not path.exists():
        print(f"[attribution] no state at {path}")
        return 1
    state = json.loads(path.read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir) if args.out_dir else state_dir / "analytics"
    csv_path, md_path, block = write_report(state, out_dir)
    print(md_path.read_text(encoding="utf-8"))
    print(f"[attribution] positions -> {csv_path}")
    print(f"[attribution] report    -> {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
