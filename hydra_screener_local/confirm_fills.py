"""Replace presumed v9 fills with what Lucas actually traded (TASK-345).

    python confirm_fills.py --from-csv fills.csv
    python confirm_fills.py --report --from-csv fills.csv
    python confirm_fills.py --interactive

CSV columns: exec_date, sleeve, tranche, ticker, side, units, price, fee
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.fills import apply_confirmations, report_lines  # noqa: E402
from portfolio_v9 import DEFAULT_STATE_DIR, STATE_NAME, load_state, save_state  # noqa: E402


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def interactive() -> list[dict]:
    print("Enter fills; empty ticker to stop. side=buy|sell")
    rows = []
    while True:
        ticker = input("ticker: ").strip()
        if not ticker:
            break
        rows.append({
            "exec_date": input("exec_date YYYY-MM-DD: ").strip(),
            "sleeve": input("sleeve stocks|etf: ").strip(),
            "tranche": input("tranche: ").strip(),
            "ticker": ticker,
            "side": input("side buy|sell: ").strip(),
            "units": input("units: ").strip(),
            "price": input("price: ").strip(),
            "fee": input("fee: ").strip() or "0",
        })
    return rows


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Confirm v9 fills (replace presumed with actual)")
    p.add_argument("--from-csv", type=str, default=None)
    p.add_argument("--interactive", action="store_true")
    p.add_argument("--report", action="store_true", help="print diffs, do not write")
    p.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    args = p.parse_args(argv)

    path = Path(args.state_dir) / STATE_NAME
    state = load_state(path)
    if not state:
        print(f"[confirm] no state at {path}")
        return 1
    if args.from_csv:
        rows = read_csv(Path(args.from_csv))
    elif args.interactive:
        rows = interactive()
    else:
        print("need --from-csv or --interactive")
        return 1
    result = apply_confirmations(state, rows)
    for line in report_lines(result):
        print(line)
    if result["warnings"]:
        for w in result["warnings"]:
            print(f"[WARN] {w}")
    if args.report:
        return 0
    backup = save_state(path, result["state"])
    print(f"[confirm] wrote {path}" + (f" (backup {backup})" if backup else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
