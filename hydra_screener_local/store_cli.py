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


def _verify(store, n: int, provider=None, tol: float = 1e-5, names: list[str] | None = None) -> bool:
    """Fresh Yahoo Adj Close vs (a) the stored Adj Close and (b) the locally derived series
    (close_raw x dividend factors, TASK-385). Returns False when any local diff exceeds `tol`."""
    from data.adjust import adjust as adjust_local
    names = names or store.sample_tickers(n)
    if not names:
        print("verify: store is empty")
        return True
    if provider is None:
        from data.providers.yfinance_provider import YFinanceProvider
        provider = YFinanceProvider()
    stats = store.stats()
    start = stats.get("first") or "2000-01-01"
    end = stats.get("last")
    print(f"verify: {len(names)} tickers {start} -> {end} (tol {tol:g})")
    fresh = provider.fetch(names, start, end)
    cov = store.actions_coverage(names)
    divs = store.dividends(names, start, end)
    ok = True
    bad = []
    for t in names:
        stored = store.closes([t], start, end, adjusted=True)
        raw = store.closes([t], start, end, adjusted=False)
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
        line = f"  {t}: n={len(a)} stored_vs_fresh max_rel={float(rel.max()):.3e}"
        if t in cov and t in raw.columns:
            local = adjust_local(raw[t].dropna(), dividends=divs.get(t))
            la, lb = local.align(got, join="inner")
            lrel = (lb.astype(float) - la.astype(float)).abs() / la.abs().clip(lower=1e-12)
            lmax = float(lrel.max()) if len(lrel) else 0.0
            line += f"  local_vs_fresh max_rel={lmax:.3e}"
            if lmax > tol:
                ok = False
                bad.append(t)
                line += "  <-- FAIL"
        else:
            line += "  local: no actions coverage"
        print(line)
    if bad:
        print(f"verify FAILED: {len(bad)} name(s) above {tol:g}: {', '.join(bad)}")
    else:
        print("verify ok")
    return ok


def _print_stats(st: dict) -> None:
    size = st.get("size_bytes") or 0
    mb = size / (1024 * 1024)
    print(f"bar store: {st.get('path')}")
    print(f"  tickers : {st.get('tickers')}")
    print(f"  bars    : {st.get('bars')}")
    print(f"  actions : {st.get('actions')} events, coverage {st.get('actions_covered_tickers')} tickers")
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
                   help="fetch N random stored tickers fresh; compare stored and locally derived adj close; exit 1 above --verify-tol")
    p.add_argument("--verify-tol", type=float, default=1e-5)
    p.add_argument("--backfill-actions", action="store_true",
                   help="TASK-385: refetch every stored ticker over --period with dividends/splits so the "
                        "actions table covers the window (needed before adjust='local')")
    p.add_argument("--db", default=None, help="sqlite path (default data_cache/bars.sqlite)")
    args = p.parse_args(argv)

    if not (args.backfill or args.stats or args.vacuum or args.verify or args.backfill_actions):
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
        if args.backfill_actions:
            from data.fetch import period_to_start
            from data.providers.yfinance_provider import YFinanceProvider
            names = sorted(store.last_dates().keys())
            end = pd.Timestamp.now().normalize()
            start = period_to_start(args.period, end)
            prov = YFinanceProvider()
            print(f"backfill-actions: {len(names)} tickers {start.date()} -> {end.date()} in chunks of 300")
            done = 0
            for i in range(0, len(names), 300):
                chunk = names[i:i + 300]
                try:
                    frame = prov.fetch(chunk, start, end)
                    n = store.upsert(frame)
                    done += len(chunk)
                    print(f"  {done}/{len(names)} rows={n}", flush=True)
                except Exception as e:
                    print(f"  chunk {i} failed: {e}")
            st = store.stats()
            print(f"actions: {st.get('actions')} events, coverage for {st.get('actions_covered_tickers')} tickers")
        if args.stats:
            _print_stats(store.stats())
        if args.vacuum:
            store.vacuum()
            print("vacuum: ok")
            if not args.stats:
                _print_stats(store.stats())
        if args.verify:
            if not _verify(store, int(args.verify), tol=args.verify_tol):
                return 1
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
