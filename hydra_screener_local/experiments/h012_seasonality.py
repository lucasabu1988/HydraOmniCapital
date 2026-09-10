"""H-012 step 0 — same-calendar-month seasonality inside the candidate pool (Heston & Sadka).

Pre-registered 2026-09-10 (`.comms/hypotheses.md`, H-012). For stock i and decision date t in
calendar month M of year Y:

    SEA_{i,t} = mean of the TOTAL return of month M in years Y-2, Y-3, Y-4, Y-5

(lags 24/36/48/60 months; the month one year back is excluded on purpose so the signal cannot
overlap with mom12_7). Month returns are month-end to month-end on the dividend-adjusted close
panel. A name without all four months has no SEA and is never expelled for it.

Step 0, DEV only (< 2016-01-01): at each rebalance date, the veto-filtered pool `rank_day`
produces; names with a valid SEA split into terciles; deciding number = mean forward 5-bar
return (t+1 close -> t+6 close) of the high tercile minus the low tercile, with the moving-block
bootstrap in use since H-009 (13-step blocks, 5000 draws). Direction pre-declared positive.
Negative point estimate -> REJECTED; 90 % interval crossing zero -> INDISTINGUISHABLE (= REJECTED).
TEST is not read. Only measures; rule 6 intact.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # TASK-380: cp1252 consoles

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import redesign_lab as L  # noqa: E402
from path_momentum import forward_step_return  # noqa: E402
from reset_ab import block_index_matrix  # noqa: E402

STEP = 5
START = 280
N_BOOT = 5000
BLOCK = 13
LAGS_YEARS = (2, 3, 4, 5)          # "years 2-5": 24 / 36 / 48 / 60 months back
MIN_NAMES = 30


def month_returns(close: pd.DataFrame) -> pd.DataFrame:
    """Total return of each calendar month, indexed by month period (month-end close over the
    previous month-end close). Missing closes stay NaN; nothing is filled."""
    me = close.resample("ME").last()
    r = me / me.shift(1) - 1.0
    r.index = r.index.to_period("M")
    return r


def sea_at(mrets: pd.DataFrame, date, lags_years=LAGS_YEARS) -> pd.Series:
    """SEA for every column at decision `date`: the mean of the same calendar month's return in the
    lagged years. NaN unless ALL lagged months are present (a name is not favoured for having more
    history, and not expelled for having less)."""
    ts = pd.Timestamp(date)
    periods = [pd.Period(year=ts.year - k, month=ts.month, freq="M") for k in lags_years]
    rows = []
    for p in periods:
        rows.append(mrets.loc[p] if p in mrets.index else pd.Series(np.nan, index=mrets.columns))
    stack = pd.concat(rows, axis=1)
    return stack.mean(axis=1).where(stack.notna().all(axis=1))


def step_row(P, mrets: pd.DataFrame, t: int, c: dict) -> dict | None:
    out = L.rank_day(P, t, c)
    if out is None:
        return None
    pool = out[~L.vetoed(out)]
    fwd = forward_step_return(P.close, t)
    if fwd is None:
        return None
    date = P.close.index[t]
    frame = pd.DataFrame({"sea": sea_at(mrets, date).reindex(pool.index), "fwd": fwd.reindex(pool.index)})
    coverage = float(frame["sea"].notna().mean()) if len(frame) else 0.0
    frame = frame.dropna()
    if len(frame) < MIN_NAMES:
        return None
    tercile = pd.qcut(frame["sea"], 3, labels=["low", "mid", "high"], duplicates="drop")
    g = frame.groupby(tercile, observed=False)["fwd"].mean()
    if "high" not in g.index or "low" not in g.index or g.isna().any():
        return None
    return {"date": date, "pool": int(len(pool)), "with_sea": int(len(frame)), "coverage": coverage,
            "high": float(g["high"]), "low": float(g["low"]), "spread": float(g["high"] - g["low"]),
            "sea_high": float(frame.loc[tercile == "high", "sea"].mean()),
            "sea_low": float(frame.loc[tercile == "low", "sea"].mean())}


def collect(P, *, dev_only: bool = True, config: str = "T20", progress_every: int = 100) -> pd.DataFrame:
    c = dict(L.BASE)
    c.update(L.CONFIGS[config])
    mrets = month_returns(P.close)
    idx = P.close.index
    steps = [t for t in range(START, len(idx) - STEP - 2, STEP) if (not dev_only or idx[t] < L.SPLIT)]
    rows = []
    for i, t in enumerate(steps):
        row = step_row(P, mrets, t, c)
        if row is not None:
            rows.append(row)
        if progress_every and (i + 1) % progress_every == 0 and rows:
            r = rows[-1]
            print(f"  {i + 1}/{len(steps)} {idx[t].date()} spread {r['spread'] * 1e4:.1f} bp "
                  f"({r['with_sea']} names with SEA of {r['pool']})", flush=True)
    return pd.DataFrame(rows)


def summarise(df: pd.DataFrame, *, rng=None, n: int = N_BOOT, block: int = BLOCK) -> dict:
    if df.empty:
        return {"steps": 0}
    rng = np.random.default_rng(0) if rng is None else rng
    spread = df["spread"].to_numpy()
    idx = block_index_matrix(len(df), block=block, n=n, rng=rng)
    paths = spread[idx].mean(axis=1) * 1e4
    return {
        "steps": int(len(df)),
        "first": str(df["date"].iloc[0].date()),
        "last": str(df["date"].iloc[-1].date()),
        "mean_pool": round(float(df["pool"].mean()), 1),
        "mean_with_sea": round(float(df["with_sea"].mean()), 1),
        "sea_coverage": round(float(df["coverage"].mean()), 3),
        "sea_high_mean": round(float(df["sea_high"].mean()), 4),
        "sea_low_mean": round(float(df["sea_low"].mean()), 4),
        "high_bp": round(float(df["high"].mean() * 1e4), 2),
        "low_bp": round(float(df["low"].mean() * 1e4), 2),
        "spread_bp": round(float(spread.mean() * 1e4), 2),
        "spread_p05": round(float(np.percentile(paths, 5)), 2),
        "spread_p95": round(float(np.percentile(paths, 95)), 2),
        "p_spread_le_0": round(float((paths <= 0).mean()), 3),
        "share_steps_positive": round(float((spread > 0).mean()), 3),
    }


def verdict(s: dict) -> str:
    """The rule written in H-012 before this ran."""
    if not s.get("steps"):
        return "NO DATA"
    if s["spread_bp"] < 0:
        return ("REJECTED: the high-SEA tercile earned LESS than the low tercile over the next five days. "
                "Negative point estimate; H-012 stops here, TEST not read.")
    if s["spread_p05"] <= 0:
        return ("INDISTINGUISHABLE (= REJECTED): predicted sign, but the 90 % interval crosses zero. "
                "H-012 stops here, TEST not read.")
    return "PREDICTED SIGN, interval clear of zero: step 0 passes; build the secondary-selection lever (top 1.5n)."


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="H-012 step 0: same-calendar-month seasonality (lags 24/36/48/60m) inside the pool")
    ap.add_argument("--config", default="T20")
    ap.add_argument("--test-read-once", action="store_true",
                    help="include TEST (>= 2016). Only with Lucas's explicit approval.")
    ap.add_argument("--sectors", choices=L.SECTOR_MODES, default="fixed")
    args = ap.parse_args(argv)
    cache = os.path.join(HERE, "_sweep_cache_oos", "close.pkl")
    if not os.path.exists(cache):
        print("SKIP:", cache, "missing")
        return 0
    if args.test_read_once:
        print("READING TEST. H-012 allows this only after Lucas has seen DEV and said so.", flush=True)
    print("loading OOS PIT panel...", flush=True)
    P = L.load_panel(oos=True, sectors=args.sectors)
    print("  close", P.close.shape, str(P.close.index[0].date()), "->", str(P.close.index[-1].date()), flush=True)
    df = collect(P, dev_only=not args.test_read_once, config=args.config)
    s = summarise(df)
    s["sample"] = "DEV+TEST (read once)" if args.test_read_once else "DEV only (< 2016-01-01)"
    s["config"] = args.config
    s["signal"] = "SEA = mean same-calendar-month total return, lags 24/36/48/60 months"
    print("", flush=True)
    print(f"H-012 step 0 - {s['sample']}, pool from `{args.config}`, {s['signal']}", flush=True)
    print(pd.Series(s).to_string(), flush=True)
    print("", flush=True)
    print("verdict:", verdict(s), flush=True)
    tag = "test_read_once" if args.test_read_once else "dev"
    scratch = os.path.join(HERE, "_lab_scratch", f"h012_step0_{tag}.json")
    os.makedirs(os.path.dirname(scratch), exist_ok=True)
    with open(scratch, "w", encoding="utf-8") as f:
        json.dump({"summary": s, "verdict": verdict(s),
                   "steps": df.assign(date=df["date"].astype(str)).to_dict(orient="records") if not df.empty else []},
                  f, indent=2, default=str)
    print("wrote", scratch, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
