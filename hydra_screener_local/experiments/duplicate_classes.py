"""TASK-389 — what the duplicate share class actually costs.

Phase 7 (R-704) reported that the live `all` universe holds `BRK-A`, `BRK-B` **and**
`BRK.B`: one company under two spellings. It was reported and not fixed, because
deduping changes the recommended list. This measures it before anyone touches it.

    python experiments/duplicate_classes.py              # spelling audit only (offline, seconds)
    python experiments/duplicate_classes.py --oos        # + T20 frequency on the OOS panel (minutes)
    python experiments/duplicate_classes.py --probe      # + ask Yahoo which spellings resolve (network)

The three questions the task asks:

1. how many duplicate groups exist, in the live universe caches and in the PIT snapshots;
2. whether a group ever contributes two names to the same T20;
3. what deduping would do to the headline.

Everything printed here is measured on this machine, offline unless `--probe` is given.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from data.universe_registry import duplicate_share_classes  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PANELS = {
    "in-sample (S&P 500, 2020-26)": os.path.join(HERE, "_sweep_cache", "close.pkl"),
    "OOS PIT (2004-26)": os.path.join(HERE, "_sweep_cache_oos", "close.pkl"),
}


def _tickers(path: str) -> list[str]:
    blob = json.load(open(path, encoding="utf-8"))
    got = blob.get("tickers") if isinstance(blob, dict) else blob
    return got if isinstance(got, list) else []


def audit_universes() -> dict:
    """Duplicate groups per source, in the union, and in the PIT snapshots."""
    print("=" * 78)
    print("1. spellings in the universe sources")
    print("=" * 78)
    srcs = {os.path.basename(p).replace("universe_cache_", "").replace(".json", ""): _tickers(p)
            for p in sorted(glob.glob(os.path.join(os.path.dirname(HERE), "data_cache",
                                                   "universe_cache_*.json")))}
    for name, tick in srcs.items():
        dup = duplicate_share_classes(tick)
        dots = [t for t in tick if "." in t]
        print(f"  {name:14s} n={len(tick):5d}  duplicate groups={len(dup):2d}  dot-spelled={len(dots)} {dots[:5]}")

    union = sorted({t for v in srcs.values() for t in v})
    dup = duplicate_share_classes(union)
    print(f"\n  union ('all')  n={len(union):5d}  duplicate groups={len(dup)}")
    for root, names in dup.items():
        where = {k: [n for n in names if n in v] for k, v in srcs.items()}
        print(f"    {root}: {names}   from {[k for k, v in where.items() if v]}")

    orphans = sorted(t for t in union if "." in t and t.replace(".", "-") not in union)
    if orphans:
        print(f"\n  dot-spelled with NO dash twin in the union: {orphans}")
        print("    (these have no second spelling to rescue them — see section 3)")

    print("\n  PIT snapshots:")
    for p in sorted(glob.glob(os.path.join(os.path.dirname(HERE), "data_cache", "pit", "universe_*.json"))):
        tick = _tickers(p)
        if not tick:
            continue
        print(f"    {os.path.basename(p):42s} n={len(tick):5d} duplicate groups={len(duplicate_share_classes(tick))}")
    return {"union": union, "duplicates": dup, "orphans": orphans}


def audit_panels(names: list[str]) -> dict:
    """A spelling that never resolves is an all-NaN column: present, never eligible."""
    print()
    print("=" * 78)
    print("2. the same spellings in the measurement panels")
    print("=" * 78)
    out = {}
    for label, path in PANELS.items():
        if not os.path.exists(path):
            print(f"  {label}: panel missing ({path})")
            continue
        close = pd.read_pickle(path)
        empty = [c for c in close.columns if close[c].notna().sum() == 0]
        dotted = [c for c in close.columns if "." in c]
        print(f"  {label}: {close.shape[1]} columns, {len(empty)} all-NaN, {len(dotted)} dot-spelled {dotted[:6]}")
        for t in names:
            if t in close.columns:
                n = int(close[t].notna().sum())
                print(f"      {t:6s} present, {n} bars" + ("   <- never eligible" if n == 0 else ""))
        out[label] = {"columns": int(close.shape[1]), "all_nan": len(empty), "dotted": dotted}
    return out


def probe_yahoo(symbols: list[str]) -> dict:
    """Which spelling actually resolves. The only part of this script that uses the network."""
    print()
    print("=" * 78)
    print("3. what the provider says (network)")
    print("=" * 78)
    import yfinance as yf
    out = {}
    for t in symbols:
        try:
            df = yf.download(t, period="1mo", progress=False, auto_adjust=False, threads=False)
            bars = 0 if df is None or df.empty else len(df)
            vol = None if not bars else float(pd.to_numeric(df["Volume"].squeeze()).mean())
            out[t] = {"bars": bars, "avg_volume": vol}
            print(f"  {t:7s} bars={bars:3d} avg_volume={'-' if vol is None else f'{vol:,.0f}'}")
        except Exception as e:                                   # network, never fatal
            out[t] = {"error": f"{type(e).__name__}: {e}"}
            print(f"  {t:7s} ERROR {type(e).__name__}: {e}")
    return out


def t20_frequency(names: list[str], sectors: str = "pit", sectors_date=None) -> dict:
    """How often each name is inside the recommended count on the OOS panel.

    The OOS panel carries the normalised spellings, so this answers the question the
    live universe cannot: if both spellings were eligible, would the pair ever be
    selected together?
    """
    print()
    print("=" * 78)
    print("4. T20 membership on the OOS PIT panel")
    print("=" * 78)
    import redesign_lab as L
    from engine_backtest import START, STEP, _ranking

    P = L.load_panel(oos=True, sectors=sectors, sectors_date=sectors_date)
    idx = P.close.index
    cfg = dict(L.BASE)
    cfg.update(L.CONFIGS["T20"])
    print(f"  panel {P.close.shape}  {idx[0].date()} -> {idx[-1].date()}  sectors={P.SECTOR_SOURCE}")

    counts = {t: 0 for t in names}
    eligible = {t: 0 for t in names}
    together = 0
    steps = 0
    for t in range(START, len(idx) - 6, STEP):
        rk = _ranking(P, t, cfg)
        if rk is None:
            continue
        steps += 1
        picked = set(rk.loc[rk["recommended"], "ticker"])
        ranked = set(rk["ticker"])
        hit = [n for n in names if n in picked]
        for n in names:
            if n in ranked:
                eligible[n] += 1
        for n in hit:
            counts[n] += 1
        if len(hit) > 1:
            together += 1

    print(f"  {steps} selection dates")
    for n in names:
        print(f"    {n:6s} ranked on {eligible[n]:4d} dates, recommended on {counts[n]:4d} "
              f"({100.0 * counts[n] / steps if steps else 0:.1f}% of dates)")
    print(f"  dates where more than one of {names} was recommended together: {together}")
    return {"steps": steps, "recommended": counts, "eligible": eligible, "together": together}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--oos", action="store_true", help="run the T20 frequency pass (minutes)")
    ap.add_argument("--probe", action="store_true", help="ask Yahoo which spellings resolve")
    ap.add_argument("--sectors", choices=("pit", "live"), default="pit")
    ap.add_argument("--sectors-date", default=None)
    args = ap.parse_args(argv)

    uni = audit_universes()
    watched = sorted({n for g in uni["duplicates"].values() for n in g}
                     | set(uni["orphans"])
                     | {o.replace(".", "-") for o in uni["orphans"]})
    audit_panels(watched)
    if args.probe:
        probe_yahoo(watched)
    if args.oos:
        t20_frequency([w for w in watched if "." not in w], args.sectors, args.sectors_date)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
