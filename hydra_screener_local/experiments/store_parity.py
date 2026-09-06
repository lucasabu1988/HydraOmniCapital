"""TASK-370 — same-day cached vs direct fetch comparison (evidence to flip USE_BAR_STORE).

    python experiments/store_parity.py
    python experiments/store_parity.py --period 2y

Uses the live yfinance path and the SQLite store. Network. Not part of the offline suite.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from config import V9  # noqa: E402
from data.fetch import (  # noqa: E402
    TBILL_SYMBOL,
    fetch_etf_closes,
    fetch_prices_and_volume,
    fetch_prices_and_volume_cached,
    fetch_tbill,
)
from data.store import BarStore  # noqa: E402
from data.universe import get_universe  # noqa: E402
from portfolio_v9 import build_ranking  # noqa: E402

SCORE_ATOL = 1e-9
REL_WARN = 1e-6


def _max_diffs(a: pd.DataFrame, b: pd.DataFrame) -> pd.DataFrame:
    cols = sorted(set(a.columns) | set(b.columns))
    rows = []
    for t in cols:
        if t not in a.columns:
            rows.append(dict(ticker=t, side="cached_only", max_abs=None, max_rel=None, n=0))
            continue
        if t not in b.columns:
            rows.append(dict(ticker=t, side="direct_only", max_abs=None, max_rel=None, n=0))
            continue
        x, y = a[t].align(b[t], join="inner")
        x, y = pd.to_numeric(x, errors="coerce"), pd.to_numeric(y, errors="coerce")
        ok = x.notna() & y.notna()
        x, y = x[ok], y[ok]
        if x.empty:
            rows.append(dict(ticker=t, side="both", max_abs=None, max_rel=None, n=0))
            continue
        absd = (x - y).abs()
        rel = absd / y.abs().clip(lower=1e-12)
        rows.append(dict(
            ticker=t, side="both", n=int(len(x)),
            max_abs=float(absd.max()), max_rel=float(rel.max()),
        ))
    return pd.DataFrame(rows)


def _summarise(label: str, df: pd.DataFrame) -> dict:
    both = df[df.side == "both"] if len(df) else df
    bad = both[both.max_rel > REL_WARN] if len(both) and "max_rel" in both else both.iloc[0:0]
    out = dict(
        label=label,
        n=int(len(df)),
        cached_only=int((df.side == "cached_only").sum()) if len(df) else 0,
        direct_only=int((df.side == "direct_only").sum()) if len(df) else 0,
        both=int(len(both)),
        rel_gt_tol=int(len(bad)),
    )
    if len(both) and both.max_abs.notna().any():
        out.update(
            max_abs_median=float(both.max_abs.median()),
            max_abs_p99=float(both.max_abs.quantile(0.99)),
            max_abs_max=float(both.max_abs.max()),
            max_rel_median=float(both.max_rel.median()),
            max_rel_p99=float(both.max_rel.quantile(0.99)),
            max_rel_max=float(both.max_rel.max()),
            worst=bad.sort_values("max_rel", ascending=False).head(15).to_dict("records")
            if len(bad) else [],
        )
    print(f"\n{label}: tickers {out['n']} both {out['both']} "
          f"cached_only {out['cached_only']} direct_only {out['direct_only']}", flush=True)
    if "max_rel_max" in out:
        print("  max_abs median/p99/max",
              round(out["max_abs_median"], 6),
              round(out["max_abs_p99"], 6),
              round(out["max_abs_max"], 6), flush=True)
        print("  max_rel median/p99/max",
              round(out["max_rel_median"], 8),
              round(out["max_rel_p99"], 8),
              round(out["max_rel_max"], 8), flush=True)
        print(f"  tickers with max_rel > {REL_WARN}: {out['rel_gt_tol']}", flush=True)
        if out.get("worst"):
            print(pd.DataFrame(out["worst"]).to_string(index=False), flush=True)
    return out


def _coverage_by_year(db_path: str) -> list[dict]:
    if not os.path.exists(db_path):
        return []
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            "SELECT substr(date,1,4) AS y, COUNT(DISTINCT ticker), COUNT(*) "
            "FROM bars GROUP BY y ORDER BY y"
        ).fetchall()
    finally:
        con.close()
    out = [dict(year=int(y), tickers=int(t), bars=int(b)) for y, t, b in rows if y]
    print("\ncoverage by year (store)", flush=True)
    if out:
        print(pd.DataFrame(out).to_string(index=False), flush=True)
    return out


def _series_frame(s: pd.Series, name: str) -> pd.DataFrame:
    if s is None or getattr(s, "empty", True):
        return pd.DataFrame()
    return s.to_frame(name=name)


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--period", default="2y")
    p.add_argument("--universe", default="all")
    args = p.parse_args(argv)

    tickers = get_universe(universe=args.universe)
    etfs = list(V9["etf_universe"])
    print(f"direct fetch stocks={len(tickers)} etf={len(etfs)} period={args.period}", flush=True)
    t0 = time.perf_counter()
    d_px, d_vol = fetch_prices_and_volume(tickers, period=args.period)
    d_etf = fetch_etf_closes(etfs, period=args.period)
    d_irx = fetch_tbill(period=args.period)
    direct_s = time.perf_counter() - t0

    print("cached fetch stocks + ETF + ^IRX...", flush=True)
    store = BarStore()
    t1 = time.perf_counter()
    c_px, c_vol = fetch_prices_and_volume_cached(tickers, period=args.period, store=store)
    c_etf, _ = fetch_prices_and_volume_cached(etfs, period=args.period, store=store)
    c_irx_px, _ = fetch_prices_and_volume_cached([TBILL_SYMBOL], period=args.period, store=store)
    cached_s = time.perf_counter() - t1

    stats = store.stats()
    print("store", {k: stats.get(k) for k in ("tickers", "bars", "first", "last", "size_bytes")},
          flush=True)
    coverage = _coverage_by_year(str(store.path))

    px = _summarise("adj close", _max_diffs(c_px, d_px))
    vol = _summarise("volume", _max_diffs(c_vol, d_vol))
    etf = _summarise("etf adj close", _max_diffs(c_etf, d_etf))
    irx_c = store.closes([TBILL_SYMBOL], c_irx_px.index.min() if len(c_irx_px) else "2000-01-01",
                         c_irx_px.index.max() if len(c_irx_px) else "2100-01-01", adjusted=False)
    irx_cached = irx_c[TBILL_SYMBOL] if (not irx_c.empty and TBILL_SYMBOL in irx_c.columns) else (
        c_irx_px[TBILL_SYMBOL] if TBILL_SYMBOL in c_irx_px.columns else pd.Series(dtype=float)
    )
    irx = _summarise("^IRX (store raw vs fetch_tbill)",
                     _max_diffs(_series_frame(irx_cached, TBILL_SYMBOL),
                                _series_frame(d_irx, TBILL_SYMBOL)))
    print("shapes direct", d_px.shape, "cached", c_px.shape,
          "etf_d", d_etf.shape, "etf_c", c_etf.shape, "irx", getattr(d_irx, "shape", None),
          flush=True)
    print(f"wall direct {direct_s:.1f}s cached {cached_s:.1f}s", flush=True)

    spy = d_etf["SPY"] if "SPY" in d_etf.columns else (
        d_px["SPY"] if "SPY" in d_px.columns else d_px.iloc[:, 0]
    )
    common = sorted(set(d_px.columns) & set(c_px.columns) & set(d_vol.columns) & set(c_vol.columns))
    print(f"\nbuild_ranking top-40 on {len(common)} common names...", flush=True)
    r_d = build_ranking(d_px[common], spy.reindex(d_px.index).ffill(), d_vol[common])
    r_c = build_ranking(c_px[common], spy.reindex(c_px.index).ffill(), c_vol[common])

    def _top(df: pd.DataFrame) -> pd.DataFrame:
        out = df.sort_values("rank").head(40) if "rank" in df.columns else df.head(40)
        cols = [c for c in ("rank", "ticker", "composite_score") if c in out.columns]
        return out[cols].reset_index(drop=True)

    top_d, top_c = _top(r_d), _top(r_c)
    names_d = list(top_d["ticker"]) if "ticker" in top_d.columns else []
    names_c = list(top_c["ticker"]) if "ticker" in top_c.columns else []
    names_equal = names_d == names_c
    score_max = None
    if names_equal and "composite_score" in top_d.columns and len(top_d):
        score_max = float((top_d["composite_score"] - top_c["composite_score"]).abs().max())
    print("  names equal", names_equal, flush=True)
    print("  score max |diff|", score_max, "atol", SCORE_ATOL,
          "pass", score_max is not None and score_max <= SCORE_ATOL, flush=True)
    if not names_equal:
        print("  only direct", [t for t in names_d if t not in names_c], flush=True)
        print("  only cached", [t for t in names_c if t not in names_d], flush=True)

    payload = dict(
        period=args.period,
        universe=args.universe,
        n_tickers=len(tickers),
        store=dict(tickers=stats.get("tickers"), bars=stats.get("bars"),
                   first=stats.get("first"), last=stats.get("last"),
                   size_bytes=stats.get("size_bytes"),
                   failed=stats.get("last_run")),
        coverage_by_year=coverage,
        adj_close=px, volume=vol, etf=etf, irx=irx,
        shapes=dict(direct=list(d_px.shape), cached=list(c_px.shape),
                    etf_direct=list(d_etf.shape), etf_cached=list(c_etf.shape)),
        ranking=dict(
            n_common=len(common),
            names_equal=names_equal,
            score_max_abs=score_max,
            score_atol=SCORE_ATOL,
            top40_direct=names_d,
            top40_cached=names_c,
        ),
        wall=dict(direct_s=round(direct_s, 2), cached_s=round(cached_s, 2)),
    )
    scratch = os.path.join(HERE, "_lab_scratch", "task370.json")
    os.makedirs(os.path.dirname(scratch), exist_ok=True)
    with open(scratch, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)
    print("wrote", scratch, flush=True)
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
