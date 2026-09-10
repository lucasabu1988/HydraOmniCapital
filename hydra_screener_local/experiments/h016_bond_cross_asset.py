"""H-016 step 0 — Treasury momentum as a cross-asset predictor for the equity ETFs.

Pre-registered 2026-09-10 (`.comms/hypotheses.md`, H-016). Production's ten ETFs; the signal may only
switch the equity block SPY QQQ IWM EFA EEM VNQ. IEF is the single Treasury proxy, fixed beforehand.

    OWN_{i,t}  = R252_i - RF252      production's SLOW rule, REUSED (h015_fast_confirmation.slow_signal,
                                     itself h014's abs_signal pinned against sleeve_lab.run_sleeve)
    BOND_t     = R252_IEF - RF252    the SAME function evaluated on IEF; a test proves BOND == SLOW[IEF]

Among the equity ETFs with OWN > 0: CROSS-CONFIRMED = BOND > 0, CROSS-BAD = BOND <= 0. Decision at the
close of t; forward excess over the T-bill from the t+1 close to the t+21 close, net of the T-bill
accrued over those same 20 bars (H-015's forward_excess, reused). Per date with >= 1 equity ETF ON and
BOND <= 0: X_t = mean EXCESS of those ETFs; deciding statistic X_bar = mean(X_t), each date weighing
once. Expectation: X_bar < 0. Moving-block bootstrap on the X_t series (13 dates per block, 5000
draws), 90 % interval. Power gate: >= 130 CROSS-BAD dates with a complete forward return, else
UNMEASURABLE. REJECTED iff X_bar >= 0 or the 90 % interval contains zero. DEV only; TEST closed. Only
measures; rule 6 intact.
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
from h015_fast_confirmation import forward_excess, slow_signal  # noqa: E402  - reused, not re-implemented
from reset_ab import block_index_matrix  # noqa: E402

EQUITY = ("SPY", "QQQ", "IWM", "EFA", "EEM", "VNQ")
BOND_PROXY = "IEF"
UNTOUCHED = ("IEF", "TLT", "GLD", "DBC")
START = 280
STEP = 5
FWD = 20
N_BOOT = 5000
BLOCK = 13
MIN_DATES = 130


def bond_signal(px: pd.DataFrame, irx: pd.Series) -> pd.Series:
    """BOND_t = SLOW evaluated on IEF, by calling the same function as every ETF's own signal."""
    return slow_signal(px, irx)[BOND_PROXY]


def step_row(px: pd.DataFrame, own: pd.DataFrame, bond: pd.Series, irx: pd.Series, t: int) -> dict:
    o = own.iloc[t].reindex(list(EQUITY))
    b = bond.iloc[t]
    on = list(o[o > 0].index)
    row = {"date": px.index[t], "bond_defined": bool(np.isfinite(b)), "bond": float(b) if np.isfinite(b) else np.nan,
           "equity_on": int(len(on)), "state": None, "n_affected": 0}
    if not on or not np.isfinite(b):
        return row
    ex = forward_excess(px, irx, t)
    if ex is None:
        return row
    e = ex.reindex(on).dropna()
    if e.empty:
        return row
    state = "cross_bad" if b <= 0 else "cross_confirmed"
    row.update(state=state, n_affected=int(len(e)), excess=float(e.mean()), names=on)
    return row


def collect(px: pd.DataFrame, irx: pd.Series, *, dev_only: bool = True) -> tuple[pd.DataFrame, dict]:
    own = slow_signal(px, irx)
    bond = bond_signal(px, irx)
    idx = px.index
    steps = [t for t in range(START, len(idx) - FWD - 2, STEP) if (not dev_only or idx[t] < L.SPLIT)]
    df = pd.DataFrame([step_row(px, own, bond, irx, t) for t in steps])
    first_defined = bond.dropna().index.min()
    cov = {"first_date_bond_defined": str(first_defined.date()) if first_defined is not None else None,
           "decision_dates": int(len(df)),
           "eligible_dates": int(((df["equity_on"] > 0) & df["bond_defined"]).sum())}
    return df, cov


def summarise(df: pd.DataFrame, *, rng=None, n: int = N_BOOT, block: int = BLOCK) -> dict:
    if df.empty:
        return {"cross_bad_dates": 0}
    elig = df[(df["equity_on"] > 0) & df["bond_defined"]]
    bad = df[df["state"] == "cross_bad"]
    good = df[df["state"] == "cross_confirmed"]
    out = {"eligible_dates": int(len(elig)), "cross_bad_dates": int(len(bad)),
           "share_dates_cross_bad": round(float(len(bad) / len(elig)), 3) if len(elig) else None,
           "mean_equity_on": round(float(elig["equity_on"].mean()), 2) if len(elig) else None,
           "mean_affected_when_cross_bad": round(float(bad["n_affected"].mean()), 2) if len(bad) else None,
           "cross_confirmed_excess_bp": round(float(good["excess"].mean() * 1e4), 2) if len(good) else None}
    if len(bad) < MIN_DATES:
        return out
    rng = np.random.default_rng(0) if rng is None else rng
    x = bad["excess"].to_numpy()
    idx = block_index_matrix(len(x), block=block, n=n, rng=rng)
    paths = x[idx].mean(axis=1) * 1e4
    out.update({
        "first": str(bad["date"].iloc[0].date()), "last": str(bad["date"].iloc[-1].date()),
        "cross_bad_excess_bp": round(float(x.mean() * 1e4), 2),
        "ci_p05": round(float(np.percentile(paths, 5)), 2), "ci_p95": round(float(np.percentile(paths, 95)), 2),
        "p_x_ge_0": round(float((paths >= 0).mean()), 3),
        "share_cross_bad_dates_negative": round(float((x < 0).mean()), 3),
        "confirmed_minus_bad_bp": (round(out["cross_confirmed_excess_bp"] - float(x.mean() * 1e4), 2)
                                   if out["cross_confirmed_excess_bp"] is not None else None),
    })
    return out


def verdict(s: dict) -> str:
    """The rule written in H-016 before this ran."""
    if s.get("cross_bad_dates", 0) < MIN_DATES:
        return (f"UNMEASURABLE: {s.get('cross_bad_dates', 0)} CROSS-BAD dates, fewer than the {MIN_DATES} the power gate "
                "requires. IEF stays IEF, horizon and threshold unchanged; TEST stays closed.")
    if s["cross_bad_excess_bp"] >= 0:
        return ("REJECTED: equity ETFs ON while IEF's 12-month excess return was <= 0 still beat the T-bill over the next "
                "20 bars (X_bar >= 0). Switching them off has no economic justification. No lever, no A/B, TEST not read.")
    if s["ci_p95"] >= 0:
        return "REJECTED: X_bar < 0 but the 90 % interval contains zero. No lever, no A/B, TEST not read."
    return "X_bar < 0 with the 90 % upper bound below zero: step 0 passes; build the OWN-and-BOND lever (DEV gate next)."


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="H-016 step 0: do equity ETFs ON lose against the T-bill when IEF's 12m momentum is <= 0?")
    ap.add_argument("--test-read-once", action="store_true",
                    help="include TEST (>= 2016). Only with Lucas's explicit approval.")
    ap.add_argument("--sectors", choices=L.SECTOR_MODES, default="fixed")
    args = ap.parse_args(argv)
    cache = os.path.join(HERE, "_sweep_cache_oos", "close.pkl")
    if not os.path.exists(cache):
        print("SKIP:", cache, "missing")
        return 0
    if args.test_read_once:
        print("READING TEST. H-016 allows this only after Lucas has seen DEV and said so.", flush=True)
    print("loading OOS PIT panel (calendar and ^IRX) and the production ETF panel...", flush=True)
    P = L.load_panel(oos=True, sectors=args.sectors)
    px = S.load_etfs(P.close.index)
    assert list(px.columns) == S.UNIVERSE, px.columns
    df, cov = collect(px, P.IRX, dev_only=not args.test_read_once)
    s = summarise(df)
    s.update(sample="DEV+TEST (read once)" if args.test_read_once else "DEV only (< 2016-01-01)",
             signals=f"OWN = SLOW (production, reused) on {list(EQUITY)}; BOND = SLOW on {BOND_PROXY}; "
                     f"excess fwd{FWD} vs the T-bill accrued t+2..t+{FWD + 1}")
    print("", flush=True)
    print("coverage:", cov, flush=True)
    print(f"H-016 step 0 - {s['sample']}", flush=True)
    print(pd.Series(s).to_string(), flush=True)
    print("", flush=True)
    print("verdict:", verdict(s), flush=True)
    tag = "test_read_once" if args.test_read_once else "dev"
    scratch = os.path.join(HERE, "_lab_scratch", f"h016_step0_{tag}.json")
    os.makedirs(os.path.dirname(scratch), exist_ok=True)
    with open(scratch, "w", encoding="utf-8") as f:
        json.dump({"summary": s, "coverage": cov, "verdict": verdict(s),
                   "dates": df.assign(date=df["date"].astype(str)).to_dict(orient="records") if not df.empty else []},
                  f, indent=2, default=str)
    print("wrote", scratch, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
