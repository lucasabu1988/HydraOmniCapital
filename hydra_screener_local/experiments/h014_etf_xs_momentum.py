"""H-014 step 0 — cross-sectional momentum among the ETFs that already pass production's TSMOM filter.

Pre-registered 2026-09-10 (`.comms/hypotheses.md`, H-014). Universe = production's ten ETFs. The
absolute signal is B0's, computed exactly as `experiments/sleeve_lab.run_sleeve` does:

    ABS_{i,t} = px_t / px_{t-252} - 1  -  (IRX/252).rolling(252).sum()_t          active iff ABS > 0

Cross-sectional signal among the active ETFs: CS = ABS (the T-bill is common on a date). At each
sleeve decision date (bar 280 onwards, every 5 bars), with >= 4 active ETFs, sort by CS, split at the
median (odd count: the middle name is left out of both halves), and take the forward total return
from the t+1 close to the t+21 close. SPREAD_t = mean(HIGH) - mean(LOW). One expectation: E[SPREAD]
> 0. Moving-block bootstrap on the paired SPREAD_t series (13 dates per block, 5000 draws), 90 %
interval. Coverage gate: fewer than 50 % comparable dates after the universe is available ->
UNMEASURABLE. Point estimate <= 0 or interval including 0 -> REJECTED. DEV only; TEST closed.
Only measures; rule 6 intact.
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
import sleeve_lab as S  # noqa: E402
from reset_ab import block_index_matrix  # noqa: E402

LOOKBACK = 252
START = 280
STEP = 5
FWD = 20                    # the ~20 bars an ETF tranche lives: t+1 close -> t+21 close
MIN_ACTIVE = 4
N_BOOT = 5000
BLOCK = 13


def abs_signal(px: pd.DataFrame, irx: pd.Series, lookback: int = LOOKBACK) -> pd.DataFrame:
    """ABS for every ETF and date, B0's definition; NaN where the ETF lacks `lookback` bars."""
    tb = (irx.reindex(px.index).ffill() / 252.0).rolling(lookback).sum()
    mom = px / px.shift(lookback) - 1.0
    return mom.sub(tb, axis=0)


def forward_return(px: pd.DataFrame, t: int, fwd: int = FWD) -> pd.Series | None:
    """Total return from the t+1 close to the t+1+fwd close."""
    entry, exit_ = t + 1, t + 1 + fwd
    if exit_ >= len(px.index):
        return None
    a, b = px.iloc[entry], px.iloc[exit_]
    return (b / a - 1.0).where(np.isfinite(a) & np.isfinite(b) & (a > 0))


def split_halves(cs: pd.Series) -> tuple[list, list]:
    """HIGH = upper half by CS, LOW = lower half; odd count drops the median name from both."""
    order = cs.dropna().sort_values(ascending=False)
    n = len(order)
    k = n // 2
    high = list(order.index[:k])
    low = list(order.index[n - k:])
    return high, low


def step_row(px: pd.DataFrame, abs_: pd.DataFrame, t: int) -> dict:
    a = abs_.iloc[t]
    active = a[a > 0].dropna()
    row = {"date": px.index[t], "eligible": int(a.notna().sum()), "active": int(len(active)), "comparable": False}
    if len(active) < MIN_ACTIVE:
        return row
    fwd = forward_return(px, t)
    if fwd is None:
        return row
    high, low = split_halves(active)
    rh, rl = fwd.reindex(high), fwd.reindex(low)
    if rh.isna().any() or rl.isna().any():
        return row
    row.update(comparable=True, high=float(rh.mean()), low=float(rl.mean()),
               spread=float(rh.mean() - rl.mean()), high_names=high, low_names=low,
               cs_high=float(active[high].mean()), cs_low=float(active[low].mean()))
    return row


def universe_available_from(abs_: pd.DataFrame) -> pd.Timestamp | None:
    """First date on which every ETF in the universe has its 252 bars (ABS defined for all)."""
    ok = abs_.notna().all(axis=1)
    return ok.idxmax() if ok.any() else None


def collect(px: pd.DataFrame, irx: pd.Series, *, dev_only: bool = True) -> tuple[pd.DataFrame, dict]:
    abs_ = abs_signal(px, irx)
    idx = px.index
    steps = [t for t in range(START, len(idx) - FWD - 2, STEP) if (not dev_only or idx[t] < L.SPLIT)]
    rows = [step_row(px, abs_, t) for t in steps]
    df = pd.DataFrame(rows)
    avail = universe_available_from(abs_)
    after = df[df["date"] >= avail] if avail is not None else df.iloc[0:0]
    cov = {"universe_available_from": str(avail.date()) if avail is not None else None,
           "decision_dates": int(len(df)),
           "decision_dates_after_availability": int(len(after)),
           "comparable_after_availability": int(after["comparable"].sum()) if len(after) else 0,
           "coverage": round(float(after["comparable"].mean()), 3) if len(after) else 0.0,
           "mean_active_after_availability": round(float(after["active"].mean()), 2) if len(after) else None}
    return df, cov


def summarise(df: pd.DataFrame, *, rng=None, n: int = N_BOOT, block: int = BLOCK) -> dict:
    comp = df[df["comparable"]] if len(df) else df
    if comp.empty:
        return {"comparable_dates": 0}
    rng = np.random.default_rng(0) if rng is None else rng
    high = comp["high"].to_numpy()
    low = comp["low"].to_numpy()
    idx = block_index_matrix(len(comp), block=block, n=n, rng=rng)           # ONE matrix for both legs
    paths = (high[idx].mean(axis=1) - low[idx].mean(axis=1)) * 1e4
    spread = high - low
    return {
        "comparable_dates": int(len(comp)),
        "first": str(comp["date"].iloc[0].date()), "last": str(comp["date"].iloc[-1].date()),
        "mean_active": round(float(comp["active"].mean()), 2),
        "cs_high_mean": round(float(comp["cs_high"].mean()), 4), "cs_low_mean": round(float(comp["cs_low"].mean()), 4),
        "high_bp": round(float(high.mean() * 1e4), 2), "low_bp": round(float(low.mean() * 1e4), 2),
        "spread_bp": round(float(spread.mean() * 1e4), 2),
        "spread_p05": round(float(np.percentile(paths, 5)), 2), "spread_p95": round(float(np.percentile(paths, 95)), 2),
        "p_spread_le_0": round(float((paths <= 0).mean()), 3),
        "share_dates_positive": round(float((spread > 0).mean()), 3),
    }


def verdict(s: dict, cov: dict) -> str:
    """The rule written in H-014 before this ran."""
    if cov.get("coverage", 0.0) < 0.5:
        return (f"UNMEASURABLE: only {cov.get('coverage')} of the DEV dates after the universe became available "
                f"({cov.get('universe_available_from')}) had >= {MIN_ACTIVE} active ETFs. Not REJECTED; the definition is not "
                "modified to manufacture observations.")
    if not s.get("comparable_dates"):
        return "NO DATA"
    if s["spread_bp"] <= 0:
        return ("REJECTED: the relatively strong active ETFs did not beat the relatively weak ones over the next 20 bars "
                "(point estimate <= 0). No lever, no A/B, TEST not read, signal not inverted.")
    if s["spread_p05"] <= 0:
        return ("REJECTED: predicted sign but the 90 % interval includes zero. No lever, no A/B, TEST not read.")
    return "PREDICTED SIGN, interval clear of zero: step 0 passes; build the upper-half lever with the exposure invariant (DEV first)."


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="H-014 step 0: cross-sectional momentum among the active ETFs")
    ap.add_argument("--test-read-once", action="store_true",
                    help="include TEST (>= 2016). Only with Lucas's explicit approval.")
    ap.add_argument("--sectors", choices=L.SECTOR_MODES, default="fixed")
    args = ap.parse_args(argv)
    cache = os.path.join(HERE, "_sweep_cache_oos", "close.pkl")
    if not os.path.exists(cache):
        print("SKIP:", cache, "missing")
        return 0
    if args.test_read_once:
        print("READING TEST. H-014 allows this only after Lucas has seen DEV and said so.", flush=True)
    print("loading OOS PIT panel (for the calendar and ^IRX) and the production ETF panel...", flush=True)
    P = L.load_panel(oos=True, sectors=args.sectors)
    px = S.load_etfs(P.close.index)
    assert list(px.columns) == S.UNIVERSE, px.columns
    print("  ETF panel", px.shape, "first valid:", {c: str(px[c].first_valid_index().date()) for c in px.columns}, flush=True)
    df, cov = collect(px, P.IRX, dev_only=not args.test_read_once)
    s = summarise(df)
    s.update(sample="DEV+TEST (read once)" if args.test_read_once else "DEV only (< 2016-01-01)",
             signal="ABS = R252 - RF252 (B0's TSMOM rule); CS = ABS among the active; HIGH/LOW at the median; fwd t+1 -> t+21")
    print("", flush=True)
    print("coverage:", cov, flush=True)
    print(f"H-014 step 0 - {s['sample']}", flush=True)
    print(pd.Series(s).to_string(), flush=True)
    print("", flush=True)
    print("verdict:", verdict(s, cov), flush=True)
    tag = "test_read_once" if args.test_read_once else "dev"
    scratch = os.path.join(HERE, "_lab_scratch", f"h014_step0_{tag}.json")
    os.makedirs(os.path.dirname(scratch), exist_ok=True)
    with open(scratch, "w", encoding="utf-8") as f:
        json.dump({"summary": s, "coverage": cov, "verdict": verdict(s, cov),
                   "dates": df.assign(date=df["date"].astype(str)).to_dict(orient="records") if not df.empty else []},
                  f, indent=2, default=str)
    print("wrote", scratch, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
