"""H-015 step 0 — fast confirmation of the ETF absolute momentum.

Pre-registered 2026-09-10 (`.comms/hypotheses.md`, H-015). Universe = production's ten ETFs.

    SLOW_{i,t} = R252 - RF252      production's rule, REUSED from h014_etf_xs_momentum.abs_signal
                                   (itself pinned bit for bit against sleeve_lab.run_sleeve)
    FAST_{i,t} = R21  - RF21       the same function over 21 bars; the only new variable

For ETFs with SLOW > 0: CONFIRMED = FAST > 0, CORRECTION = FAST <= 0. Decision at the close of t;
forward return from the next executable close over the life of an ETF tranche, R_fwd20 = P_{t+21} /
P_{t+1} - 1; the T-bill realisable over exactly that interval, RF_fwd20 = sum(IRX/252) over the 20
accrual bars t+2..t+21; EXCESS_fwd20 = R_fwd20 - RF_fwd20. Per DEV date with >= 1 CORRECTION ETF,
C_t = mean EXCESS_fwd20 of the CORRECTION ETFs (each date weighs once); the deciding statistic is
C_bar = mean(C_t). Expectation: C_bar < 0. Moving-block bootstrap on the C_t series (13 dates per
block, 5000 draws), 90 % interval. REJECTED iff C_bar >= 0 or the interval contains zero. Fewer than
two full blocks of CORRECTION dates -> UNMEASURABLE. DEV only; TEST closed. Only measures; rule 6.
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
from h014_etf_xs_momentum import abs_signal  # noqa: E402  - SLOW is production's rule, not a re-implementation
from reset_ab import block_index_matrix  # noqa: E402

SLOW_BARS = 252
FAST_BARS = 21
START = 280
STEP = 5
FWD = 20
N_BOOT = 5000
BLOCK = 13
MIN_DATES = 2 * BLOCK


def slow_signal(px: pd.DataFrame, irx: pd.Series) -> pd.DataFrame:
    return abs_signal(px, irx, lookback=SLOW_BARS)


def fast_signal(px: pd.DataFrame, irx: pd.Series) -> pd.DataFrame:
    return abs_signal(px, irx, lookback=FAST_BARS)


def forward_excess(px: pd.DataFrame, irx: pd.Series, t: int, fwd: int = FWD) -> pd.Series | None:
    """R_fwd = P_{t+1+fwd}/P_{t+1} - 1 minus the T-bill accrued over the same 20 bars (t+2..t+1+fwd)."""
    entry, exit_ = t + 1, t + 1 + fwd
    if exit_ >= len(px.index):
        return None
    a, b = px.iloc[entry], px.iloc[exit_]
    r = (b / a - 1.0).where(np.isfinite(a) & np.isfinite(b) & (a > 0))
    daily = irx.reindex(px.index).ffill().fillna(0.0) / 252.0
    rf = float(daily.iloc[entry + 1:exit_ + 1].sum())
    return r - rf


def step_row(px: pd.DataFrame, slow: pd.DataFrame, fast: pd.DataFrame, irx: pd.Series, t: int) -> dict:
    sl, fa = slow.iloc[t], fast.iloc[t]
    on = sl[(sl > 0) & fa.notna()].index
    row = {"date": px.index[t], "eligible": int(sl.notna().sum()), "on": int(len(on)),
           "n_correction": 0, "n_confirmed": 0, "has_correction": False}
    if not len(on):
        return row
    ex = forward_excess(px, irx, t)
    if ex is None:
        return row
    corr = [c for c in on if fa[c] <= 0]
    conf = [c for c in on if fa[c] > 0]
    ex_corr, ex_conf = ex.reindex(corr).dropna(), ex.reindex(conf).dropna()
    row.update(n_correction=int(len(ex_corr)), n_confirmed=int(len(ex_conf)),
               confirmed_excess=float(ex_conf.mean()) if len(ex_conf) else np.nan,
               correction_names=corr)
    if len(ex_corr):
        row.update(has_correction=True, correction_excess=float(ex_corr.mean()))
    return row


def collect(px: pd.DataFrame, irx: pd.Series, *, dev_only: bool = True) -> pd.DataFrame:
    slow, fast = slow_signal(px, irx), fast_signal(px, irx)
    idx = px.index
    steps = [t for t in range(START, len(idx) - FWD - 2, STEP) if (not dev_only or idx[t] < L.SPLIT)]
    return pd.DataFrame([step_row(px, slow, fast, irx, t) for t in steps])


def summarise(df: pd.DataFrame, *, rng=None, n: int = N_BOOT, block: int = BLOCK) -> dict:
    if df.empty:
        return {"eligible_dates": 0, "correction_dates": 0}
    elig = df[df["on"] > 0]
    corr = df[df["has_correction"]]
    out = {"eligible_dates": int(len(elig)), "correction_dates": int(len(corr)),
           "share_dates_with_correction": round(float(len(corr) / len(elig)), 3) if len(elig) else None,
           "correction_observations": int(df["n_correction"].sum()),
           "mean_correction_count_when_present": round(float(corr["n_correction"].mean()), 2) if len(corr) else None,
           "confirmed_excess_bp": round(float(df["confirmed_excess"].dropna().mean() * 1e4), 2) if "confirmed_excess" in df else None}
    if len(corr) < MIN_DATES:
        return out
    rng = np.random.default_rng(0) if rng is None else rng
    c = corr["correction_excess"].to_numpy()
    idx = block_index_matrix(len(c), block=block, n=n, rng=rng)
    paths = c[idx].mean(axis=1) * 1e4
    out.update({
        "first": str(corr["date"].iloc[0].date()), "last": str(corr["date"].iloc[-1].date()),
        "correction_excess_bp": round(float(c.mean() * 1e4), 2),
        "ci_p05": round(float(np.percentile(paths, 5)), 2), "ci_p95": round(float(np.percentile(paths, 95)), 2),
        "p_c_ge_0": round(float((paths >= 0).mean()), 3),
        "share_correction_dates_negative": round(float((c < 0).mean()), 3),
        "confirmed_minus_correction_bp": (round(out["confirmed_excess_bp"] - float(c.mean() * 1e4), 2)
                                          if out["confirmed_excess_bp"] is not None else None),
    })
    return out


def verdict(s: dict) -> str:
    """The rule written in H-015 before this ran."""
    if s.get("correction_dates", 0) < MIN_DATES:
        return (f"UNMEASURABLE: {s.get('correction_dates', 0)} CORRECTION dates, fewer than two bootstrap blocks "
                f"({MIN_DATES}). Specification not modified; TEST stays closed.")
    if s["correction_excess_bp"] >= 0:
        return ("REJECTED: CORRECTION ETFs still beat the T-bill over the next 20 bars (C_bar >= 0). Switching them off "
                "has no economic justification. No lever, no A/B, TEST not read.")
    if s["ci_p95"] >= 0:
        return ("REJECTED: C_bar < 0 but the 90 % interval contains zero. No lever, no A/B, TEST not read.")
    return "C_bar < 0 with the 90 % upper bound below zero: step 0 passes; build the SLOW-and-FAST lever (DEV gate next)."


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="H-015 step 0: do CORRECTION ETFs (SLOW > 0, FAST <= 0) lose against the T-bill?")
    ap.add_argument("--test-read-once", action="store_true",
                    help="include TEST (>= 2016). Only with Lucas's explicit approval.")
    ap.add_argument("--sectors", choices=L.SECTOR_MODES, default="fixed")
    args = ap.parse_args(argv)
    cache = os.path.join(HERE, "_sweep_cache_oos", "close.pkl")
    if not os.path.exists(cache):
        print("SKIP:", cache, "missing")
        return 0
    if args.test_read_once:
        print("READING TEST. H-015 allows this only after Lucas has seen DEV and said so.", flush=True)
    print("loading OOS PIT panel (calendar and ^IRX) and the production ETF panel...", flush=True)
    P = L.load_panel(oos=True, sectors=args.sectors)
    px = S.load_etfs(P.close.index)
    assert list(px.columns) == S.UNIVERSE, px.columns
    df = collect(px, P.IRX, dev_only=not args.test_read_once)
    s = summarise(df)
    s.update(sample="DEV+TEST (read once)" if args.test_read_once else "DEV only (< 2016-01-01)",
             signals=f"SLOW = R{SLOW_BARS} - RF{SLOW_BARS} (production, reused); FAST = R{FAST_BARS} - RF{FAST_BARS}; "
                     f"excess fwd{FWD} vs the T-bill accrued t+2..t+{FWD + 1}")
    print("", flush=True)
    print(f"H-015 step 0 - {s['sample']}", flush=True)
    print(pd.Series(s).to_string(), flush=True)
    print("", flush=True)
    print("verdict:", verdict(s), flush=True)
    tag = "test_read_once" if args.test_read_once else "dev"
    scratch = os.path.join(HERE, "_lab_scratch", f"h015_step0_{tag}.json")
    os.makedirs(os.path.dirname(scratch), exist_ok=True)
    with open(scratch, "w", encoding="utf-8") as f:
        json.dump({"summary": s, "verdict": verdict(s),
                   "dates": df.assign(date=df["date"].astype(str)).to_dict(orient="records") if not df.empty else []},
                  f, indent=2, default=str)
    print("wrote", scratch, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
