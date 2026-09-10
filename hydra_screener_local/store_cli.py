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


def _verify(store, n: int, provider=None, tol: float = 1e-5, names: list[str] | None = None,
            min_overlap: int = 20, min_coverage: float = 1.0, report: dict | None = None) -> bool:
    """Compare the store against a fresh provider fetch. False -> exit non-zero.

    Audit phase 5.1/5.2. Every one of these used to pass as "verify ok":

    * an empty store (nothing was checked, repro R-503);
    * a provider that returned nothing for a ticker (R-504);
    * no date overlap between stored and fresh (R-505);
    * a `stored_vs_fresh` discrepancy above the tolerance — it was computed, printed
      and then thrown away, because only `local_vs_fresh` gated the exit code (R-502).

    A check that cannot be performed is a failure, not a pass: verification is the
    whole point of the command.
    """
    from data.adjust import adjust as adjust_local

    out = report if report is not None else {}
    names = names or store.sample_tickers(n)
    rows: list[dict] = []
    problems: list[str] = []

    if not names:
        print("verify FAILED: the store is empty — nothing to verify")
        out.update(checked=0, problems=["store is empty"], rows=rows)
        return False
    if provider is None:
        from data.providers.yfinance_provider import YFinanceProvider
        provider = YFinanceProvider()
    stats = store.stats()
    start = stats.get("first") or "2000-01-01"
    end = stats.get("last")
    print(f"verify: {len(names)} tickers {start} -> {end} (tol {tol:g}, min_overlap {min_overlap})")
    try:
        fresh = provider.fetch(names, start, end)
    except Exception as e:
        print(f"verify FAILED: provider raised: {e}")
        out.update(checked=0, problems=[f"provider raised: {e}"], rows=rows)
        return False

    if fresh is None or getattr(fresh, "empty", True):
        print(f"verify FAILED: the provider returned nothing for all {len(names)} ticker(s)")
        out.update(checked=0, problems=["provider returned an empty frame"], rows=rows)
        return False
    missing_cols = [c for c in ("ticker", "date", "close_adj") if c not in fresh.columns]
    if missing_cols:
        print(f"verify FAILED: provider frame is missing column(s) {missing_cols}")
        out.update(checked=0, problems=[f"provider missing columns {missing_cols}"], rows=rows)
        return False

    cov = store.actions_coverage(names)
    divs = store.dividends(names, start, end)
    quality = store.quality(names)
    q_by = {r["ticker"]: r for r in quality.to_dict(orient="records")} if len(quality) else {}

    for tk in names:
        row: dict = {"ticker": tk, "status": "ok", "problems": []}
        stored = store.closes([tk], start, end, adjusted=True)
        raw = store.closes([tk], start, end, adjusted=False)
        if stored.empty or tk not in stored.columns:
            row.update(status="fail", problems=["not in store"])
            problems.append(f"{tk}: not in store")
            rows.append(row)
            print(f"  {tk}: not in store  <-- FAIL")
            continue

        inc = fresh[fresh["ticker"].astype(str) == tk]
        if inc is None or inc.empty:
            row.update(status="fail", problems=["provider returned no rows"])
            problems.append(f"{tk}: provider empty")
            rows.append(row)
            print(f"  {tk}: provider empty  <-- FAIL")
            continue

        s = stored[tk].dropna()
        idx = pd.to_datetime(inc["date"]).dt.normalize()
        got = pd.Series(pd.to_numeric(inc["close_adj"], errors="coerce").values, index=idx).dropna()
        a, b = s.align(got, join="inner")
        row["n_overlap"] = int(len(a))
        if len(a) < int(min_overlap):
            row.update(status="fail")
            row["problems"].append(f"overlap {len(a)} < min_overlap {min_overlap}")
            problems.append(f"{tk}: overlap {len(a)} < {min_overlap}")
            rows.append(row)
            print(f"  {tk}: overlap {len(a)} bars < {min_overlap}  <-- FAIL")
            continue

        coverage_ratio = len(a) / max(len(got), 1)
        row["coverage"] = round(float(coverage_ratio), 4)
        if coverage_ratio < float(min_coverage) - 1e-9:
            row.update(status="fail")
            row["problems"].append(
                f"coverage {coverage_ratio:.3f} < requested {min_coverage:.3f}")
            problems.append(f"{tk}: coverage {coverage_ratio:.3f} < {min_coverage:.3f}")

        rel = (b.astype(float) - a.astype(float)).abs() / a.abs().clip(lower=1e-12)
        stored_max = float(rel.max()) if len(rel) else 0.0
        row["stored_vs_fresh"] = stored_max
        line = f"  {tk}: n={len(a)} stored_vs_fresh max_rel={stored_max:.3e}"
        if stored_max > tol:
            row.update(status="fail")
            row["problems"].append(f"stored_vs_fresh {stored_max:.3e} > tol {tol:g}")
            problems.append(f"{tk}: stored_vs_fresh {stored_max:.3e} > {tol:g}")

        if tk in cov and tk in raw.columns:
            local = adjust_local(raw[tk].dropna(), dividends=divs.get(tk))
            la, lb = local.align(got, join="inner")
            lrel = (lb.astype(float) - la.astype(float)).abs() / la.abs().clip(lower=1e-12)
            local_max = float(lrel.max()) if len(lrel) else 0.0
            row["local_vs_fresh"] = local_max
            line += f"  local_vs_fresh max_rel={local_max:.3e}"
            if local_max > tol:
                row.update(status="fail")
                row["problems"].append(f"local_vs_fresh {local_max:.3e} > tol {tol:g}")
                problems.append(f"{tk}: local_vs_fresh {local_max:.3e} > {tol:g}")
        else:
            line += "  local: no actions coverage"
            row["local_vs_fresh"] = None

        q = q_by.get(tk) or {}
        row["gaps"] = q.get("gaps")
        row["duplicates"] = q.get("duplicates")
        row["non_positive"] = q.get("non_positive")
        if q.get("duplicates"):
            row.update(status="fail")
            row["problems"].append(f"{q['duplicates']} duplicate row(s)")
            problems.append(f"{tk}: {q['duplicates']} duplicate row(s)")
        if q.get("non_positive"):
            row.update(status="fail")
            row["problems"].append(f"{q['non_positive']} non-positive close(s)")
            problems.append(f"{tk}: {q['non_positive']} non-positive close(s)")

        if row["status"] == "fail":
            line += "  <-- FAIL"
        rows.append(row)
        print(line)

    out.update(checked=len(names), problems=problems, rows=rows,
               failed=[r["ticker"] for r in rows if r["status"] == "fail"])
    if problems:
        print(f"verify FAILED: {len(problems)} problem(s) over {len(names)} ticker(s)")
        for msg in problems[:20]:
            print(f"  - {msg}")
        return False
    print(f"verify ok: {len(names)} ticker(s) within {tol:g}")
    return True


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
    p.add_argument("--verify-min-overlap", type=int, default=20,
                   help="minimum overlapping bars needed before a comparison counts as done")
    p.add_argument("--verify-min-coverage", type=float, default=1.0,
                   help="fraction of the provider's bars the store must also hold (1.0 = all)")
    p.add_argument("--quality", nargs="?", const="", metavar="TICKERS",
                   help="per-ticker gaps/duplicates/discrepancy metrics (comma-separated, or all)")
    p.add_argument("--backfill-actions", action="store_true",
                   help="TASK-385: refetch every stored ticker over --period with dividends/splits so the "
                        "actions table covers the window (needed before adjust='local')")
    p.add_argument("--db", default=None, help="sqlite path (default data_cache/bars.sqlite)")
    args = p.parse_args(argv)

    if not (args.backfill or args.stats or args.vacuum or args.verify or args.backfill_actions
            or args.quality is not None):
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
        if args.quality is not None:
            names = [s.strip() for s in args.quality.split(",") if s.strip()] or \
                sorted(store.last_dates().keys())
            q = store.quality(names)
            if q.empty:
                print("quality: the store is empty")
                return 1
            print(q.to_string(index=False))
            bad = q[(q["duplicates"] > 0) | (q["non_positive"] > 0)]
            if len(bad):
                print(f"quality FAILED: {len(bad)} ticker(s) with duplicates or non-positive closes")
                return 1
        if args.verify:
            if not _verify(store, int(args.verify), tol=args.verify_tol,
                           min_overlap=args.verify_min_overlap,
                           min_coverage=args.verify_min_coverage):
                return 1
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
