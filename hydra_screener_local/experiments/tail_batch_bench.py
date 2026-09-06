"""TASK-382 — measure the cached *tail* fetch for several tail batch sizes.

For each tail batch size, run `fetch_prices_and_volume_cached` on the full universe
against the seeded store N times and record wall time, downloads issued, failed
tickers, readjusted names and names requested but missing from the result. The
store is only touched through the normal upsert path (idempotent rows).

    python experiments/tail_batch_bench.py --sizes 75 150 300 500 --runs 3
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from config import V9  # noqa: E402
from data.fetch import fetch_prices_and_volume_cached  # noqa: E402
from data.providers.yfinance_provider import YFinanceProvider  # noqa: E402
from data.store import BarStore  # noqa: E402
from data.universe import get_universe  # noqa: E402


def one_run(tickers, size, period, store) -> dict:
    prov = YFinanceProvider(tail_batch_size=size)
    report: dict = {}
    buf = io.StringIO()
    t0 = time.perf_counter()
    with contextlib.redirect_stdout(buf):
        px, vol = fetch_prices_and_volume_cached(tickers, period=period, report=report, provider=prov, store=store)
    secs = time.perf_counter() - t0
    console = buf.getvalue()
    missing = [t for t in tickers if t not in px.columns]
    return dict(
        size=size, seconds=round(secs, 1), downloads=prov.total_batches,
        failed=len(report.get("failed_tickers") or []), readjusted=len(report.get("readjusted") or []),
        missing=len(missing), lost_batches=console.count("lote perdido"),
        rate_limit_hits=sum(console.lower().count(k) for k in ("429", "too many requests", "rate limit")),
        rows=int(px.shape[0]), cols=int(px.shape[1]),
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sizes", type=int, nargs="+", default=[75, 150, 300, 500])
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--period", default="2y")
    p.add_argument("--universe", default="all")
    p.add_argument("--out", default=str(HERE / "_lab_scratch" / "task382_bench.json"))
    args = p.parse_args(argv)

    tickers = get_universe(universe=args.universe)
    etfs = [t for t in V9["etf_universe"] if t not in tickers]
    names = list(tickers) + etfs
    store = BarStore()
    print(f"bench: {len(names)} names, period {args.period}, sizes {args.sizes}, runs {args.runs}", flush=True)
    results = []
    for r in range(args.runs):
        for size in args.sizes:
            res = one_run(names, size, args.period, store)
            res["run"] = r + 1
            results.append(res)
            print(json.dumps(res), flush=True)
            time.sleep(5.0)          # courtesy pause between runs
    Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("\n| tail batch | runs | wall s (min/med/max) | downloads | failed | missing | readjusted | lost batches | 429 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for size in args.sizes:
        rs = [x for x in results if x["size"] == size]
        w = sorted(x["seconds"] for x in rs)
        med = w[len(w) // 2]
        print(f"| {size} | {len(rs)} | {w[0]} / {med} / {w[-1]} | {rs[0]['downloads']} | "
              f"{max(x['failed'] for x in rs)} | {max(x['missing'] for x in rs)} | "
              f"{max(x['readjusted'] for x in rs)} | {sum(x['lost_batches'] for x in rs)} | "
              f"{sum(x['rate_limit_hits'] for x in rs)} |")
    print(f"\nresults -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
