"""TASK-377 — evidence: local adjustment vs Yahoo's Adj Close on stored tickers.

Raw and adjusted closes come from the bar store (Yahoo `Close` / `Adj Close`, TASK-378
one-pass provider); dividends from `data.dividends.fetch_dividends` (cached, ex-dates).
Yahoo's raw close is already split-adjusted, so no splits are applied.

    python experiments/adjust_parity.py --n 50 --seed 377 --period 2y
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from config import V9  # noqa: E402
from data.adjust import adjust, compare, dividends_from_rows  # noqa: E402
from data.dividends import fetch_dividends  # noqa: E402
from data.fetch import period_to_start  # noqa: E402
from data.store import BarStore  # noqa: E402
from data.universe import get_universe  # noqa: E402


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=50)
    p.add_argument("--seed", type=int, default=377)
    p.add_argument("--period", default="2y")
    p.add_argument("--out", default=str(HERE / "_lab_scratch" / "task377_parity.json"))
    args = p.parse_args(argv)

    store = BarStore()
    stored = set(store.last_dates().keys())
    sp = [t for t in get_universe(universe="sp500") if t in stored]
    random.Random(args.seed).shuffle(sp)
    names = sp[: args.n] + [t for t in V9["etf_universe"] if t in stored]
    end = pd.Timestamp.now().normalize()
    start = period_to_start(args.period, end)
    raw = store.closes(names, start, end, adjusted=False)
    ref = store.closes(names, start, end, adjusted=True)
    rows = fetch_dividends(names)
    print(f"{len(names)} names, {raw.shape[0]} bars, {len(rows)} dividend rows", flush=True)

    results = []
    for t in names:
        if t not in raw.columns or t not in ref.columns:
            continue
        divs = dividends_from_rows(rows, t)
        rep: dict = {}
        mine = adjust(raw[t].dropna(), dividends=divs, report=rep)
        c = compare(mine, ref[t].dropna())
        # how far is Yahoo's own adjustment from raw? (0 = no dividends in the window)
        yahoo_gap = float(((ref[t] / raw[t]) - 1.0).abs().max()) if raw[t].abs().max() > 0 else None
        results.append(dict(
            ticker=t, n_div=int((divs.index >= start).sum()) if len(divs) else 0, applied=rep["applied"],
            skipped=len(rep["skipped"]), max_rel=c["max_rel"], median_rel=c["median_rel"],
            n_bad=c.get("n_bad", 0), first_bad=c.get("first_bad"), yahoo_gap=yahoo_gap,
        ))
    df = pd.DataFrame(results)
    Path(args.out).write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    mx = df["max_rel"].fillna(0.0)
    print(f"\nwithin 1e-6: {(mx <= 1e-6).sum()}   within 1e-4: {((mx > 1e-6) & (mx <= 1e-4)).sum()}   "
          f"worse: {(mx > 1e-4).sum()}   of {len(df)}")
    print(f"median of max_rel: {mx.median():.2e}   max of max_rel: {mx.max():.2e}")
    print(f"names with no dividend in the window: {(df['n_div'] == 0).sum()} (their max_rel should be 0)")
    print("\nworst 10:")
    cols = ["ticker", "n_div", "applied", "skipped", "max_rel", "median_rel", "n_bad", "first_bad", "yahoo_gap"]
    print(df.sort_values("max_rel", ascending=False).head(10)[cols].to_string(index=False))
    print(f"\nresults -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
