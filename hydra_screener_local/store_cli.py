"""TASK-361 — local bar store CLI.

    python store_cli.py --backfill --period 20y --universe all
    python store_cli.py --stats
    python store_cli.py --vacuum
"""
from __future__ import annotations

import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import UNIVERSE  # noqa: E402
from data.fetch import fetch_prices_and_volume_cached  # noqa: E402
from data.store import BarStore  # noqa: E402
from data.universe import get_universe  # noqa: E402


def _print_stats(st: dict) -> None:
    size = st.get("size_bytes") or 0
    mb = size / (1024 * 1024)
    print(f"bar store: {st.get('path')}")
    print(f"  tickers : {st.get('tickers')}")
    print(f"  bars    : {st.get('bars')}")
    print(f"  first   : {st.get('first')}")
    print(f"  last    : {st.get('last')}")
    print(f"  size    : {mb:.2f} MB ({size} bytes)")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="HYDRA local bar store")
    p.add_argument("--backfill", action="store_true", help="download and upsert bars for a universe")
    p.add_argument("--period", default="20y")
    p.add_argument("--universe", default=None)
    p.add_argument("--stats", action="store_true")
    p.add_argument("--vacuum", action="store_true")
    p.add_argument("--db", default=None, help="sqlite path (default data_cache/bars.sqlite)")
    args = p.parse_args(argv)

    if not (args.backfill or args.stats or args.vacuum):
        p.print_help()
        return 2

    store = BarStore(args.db)
    try:
        if args.backfill:
            uni = args.universe or os.environ.get("UNIVERSE") or UNIVERSE
            tickers = get_universe(universe=uni)
            print(f"backfill: universe={uni} tickers={len(tickers)} period={args.period}")
            report = {}
            fetch_prices_and_volume_cached(
                tickers, period=args.period, report=report, store=store,
            )
            print(
                f"backfill done: downloaded={report.get('downloaded')}/{report.get('requested')} "
                f"readjusted={len(report.get('readjusted') or [])} "
                f"failed={len(report.get('failed_tickers') or [])}"
            )
        if args.stats:
            _print_stats(store.stats())
        if args.vacuum:
            store.vacuum()
            print("vacuum: ok")
            if not args.stats:
                _print_stats(store.stats())
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
