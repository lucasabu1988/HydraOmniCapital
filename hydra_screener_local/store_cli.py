"""TASK-361 — local bar store CLI.

    python store_cli.py --backfill --period 20y --universe all
    python store_cli.py --stats
    python store_cli.py --vacuum
    python store_cli.py --verify 20
"""
from __future__ import annotations

import argparse
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd  # noqa: E402

from config import UNIVERSE  # noqa: E402
from data.fetch import fetch_prices_and_volume_cached  # noqa: E402
from data.store import BarStore  # noqa: E402
from data.universe import get_universe  # noqa: E402


def _verify(store, n: int, provider=None) -> None:
    names = store.sample_tickers(n)
    if not names:
        print("verify: store is empty")
        return
    if provider is None:
        from data.providers.yfinance_provider import YFinanceProvider
        provider = YFinanceProvider()
    stats = store.stats()
    start = stats.get("first") or "2000-01-01"
    end = stats.get("last")
    print(f"verify: {len(names)} tickers {start} -> {end}")
    fresh = provider.fetch(names, start, end)
    for t in names:
        stored = store.closes([t], start, end, adjusted=True)
        if stored.empty or t not in stored.columns:
            print(f"  {t}: not in store")
            continue
        inc = fresh[fresh["ticker"].astype(str) == t] if (fresh is not None and not fresh.empty) else None
        if inc is None or inc.empty:
            print(f"  {t}: provider empty")
            continue
        s = stored[t].dropna()
        idx = pd.to_datetime(inc["date"]).dt.normalize()
        got = pd.Series(pd.to_numeric(inc["close_adj"], errors="coerce").values, index=idx).dropna()
        a, b = s.align(got, join="inner")
        if a.empty:
            print(f"  {t}: no overlap")
            continue
        rel = (b.astype(float) - a.astype(float)).abs() / a.abs().clip(lower=1e-12)
        print(f"  {t}: n={len(a)} max_rel={float(rel.max()):.3e} max_abs={float((b-a).abs().max()):.6g}")


def _print_stats(st: dict) -> None:
    size = st.get("size_bytes") or 0
    mb = size / (1024 * 1024)
    print(f"bar store: {st.get('path')}")
    print(f"  tickers : {st.get('tickers')}")
    print(f"  bars    : {st.get('bars')}")
    print(f"  first   : {st.get('first')}")
    print(f"  last    : {st.get('last')}")
    print(f"  size    : {mb:.2f} MB ({size} bytes)")
    print(f"  readjusted_last_run : {st.get('readjusted_last_run')}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="HYDRA local bar store")
    p.add_argument("--backfill", action="store_true", help="download and upsert bars for a universe")
    p.add_argument("--period", default="20y")
    p.add_argument("--universe", default=None)
    p.add_argument("--stats", action="store_true")
    p.add_argument("--vacuum", action="store_true")
    p.add_argument("--verify", type=int, default=None, metavar="N",
                   help="fetch N random stored tickers fresh and print max relative adj diff")
    p.add_argument("--db", default=None, help="sqlite path (default data_cache/bars.sqlite)")
    args = p.parse_args(argv)

    if not (args.backfill or args.stats or args.vacuum or args.verify):
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
        if args.verify:
            _verify(store, int(args.verify))
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
