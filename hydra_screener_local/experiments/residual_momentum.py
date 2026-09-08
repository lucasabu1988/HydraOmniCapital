"""H-010 step 0 - does ranking the IDIOSYNCRATIC momentum sort future returns better? DEV only.

Conventional momentum is contaminated by market exposure: a name that rose because the market rose
scores the same as one that rose against a flat market, and `ret / vol63` cannot tell them apart.
Blitz, Huij & Martens (*Residual Momentum*, JEmpFin 2011) rank the momentum of the **residual** of
a market regression instead, and report roughly double the information ratio at the same turnover.

Different claim from H-009, which died at step 0 the same day: that one was about the PATH of the
return (gradual vs jumpy), this is about its SOURCE. The construction is fixed in the
pre-registration (H-010, `.comms/hypotheses.md`, committed BEFORE this file existed):

    beta, alpha   OLS of the name's daily returns on SPY's, over the 756 bars ENDING at t-126.
                  That window contains the formation window as its last 126 bars and nothing
                  after it, so the residuals are the paper's in-sample ones and no post-window
                  information can enter.
    e_s           r_s - alpha - beta * m_s, for the 126 days of the 12-7 window (t-251 .. t-126)
    primary       sum(e) / sd(e)      <- already risk-adjusted; REPLACES mom/vol63
    secondary     sum(e) / vol63      <- only the numerator changes; robustness only

The whole thing is closed-form from rolling sums, which is why it runs in seconds rather than
fitting 6.9 million regressions: with S_x the rolling sums,

    beta = (S_rm/W - S_r/W * S_m/W) / (S_m2/W - (S_m/W)^2)
    alpha = S_r/W - beta * S_m/W
    sum(e)   over the window = S_r' - n*alpha - beta*S_m'
    sum(e^2) over the window = S_r2' - 2a*S_r' - 2b*S_rm' + n*a^2 + 2ab*S_m' + b^2*S_m2'

(primed sums are over the 126-bar formation window, unprimed over the 756-bar estimation window.)

A property that surfaced while testing and that changes how the signal should be read: a constant
idiosyncratic drift across the whole 756-bar window is **absorbed by alpha**, so it does not score.
What survives in the residuals is the deviation from the name's own three-year alpha. Residual
momentum is therefore not "this name has quietly compounded for three years" - it is "the last six
months beat what this name normally does". Pinned by two tests.

    python experiments/residual_momentum.py                # DEV, the pre-registered run
    python experiments/residual_momentum.py --secondary     # the sum(e)/vol63 robustness variant
    python experiments/residual_momentum.py --test-read-once  # only if Lucas said so
"""
from __future__ import annotations

import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import redesign_lab as L  # noqa: E402
from path_momentum import forward_step_return  # noqa: E402
from reset_ab import block_index_matrix  # noqa: E402

FORMATION = 126           # bars in the 12-7 window
SKIP = 126                # the window ends this many bars before t
ESTIMATION = 756          # 36 months of daily bars for the regression
MIN_ESTIMATION = 500      # declared guard: a beta needs this many observations
MIN_FORMATION = 100       # declared guard: a window needs this many returns
STEP = 5
START = 280
N_BOOT = 5000
BLOCK = 13


def residual_momentum(rets: pd.DataFrame, market: pd.Series, *, formation: int = FORMATION,
                      skip: int = SKIP, estimation: int = ESTIMATION,
                      min_estimation: int = MIN_ESTIMATION,
                      min_formation: int = MIN_FORMATION) -> dict:
    """{'sum': DataFrame, 'sd': DataFrame, 'beta': DataFrame} aligned so row t uses only data
    up to t-126. Closed form from rolling sums; see the module docstring for the algebra."""
    r = rets
    m = pd.Series(market).astype(float).reindex(r.index)
    valid = r.notna() & m.notna().to_numpy()[:, None]
    r = r.where(valid)
    rm = r.mul(m, axis=0)
    r2 = r * r
    m_frame = pd.DataFrame(np.repeat(m.to_numpy()[:, None], r.shape[1], axis=1),
                           index=r.index, columns=r.columns).where(valid)
    m2_frame = m_frame * m_frame

    def roll(frame, window, min_periods):
        return frame.rolling(window, min_periods=min_periods).sum().shift(skip)

    # --- estimation window (756 bars ending at t-skip)
    n_est = roll(valid.astype(float), estimation, min_estimation)
    S_r = roll(r, estimation, min_estimation)
    S_m = roll(m_frame, estimation, min_estimation)
    S_rm = roll(rm, estimation, min_estimation)
    S_m2 = roll(m2_frame, estimation, min_estimation)
    mean_r, mean_m = S_r / n_est, S_m / n_est
    cov = S_rm / n_est - mean_r * mean_m
    var_m = S_m2 / n_est - mean_m * mean_m
    beta = cov / var_m.replace(0.0, np.nan)
    alpha = mean_r - beta * mean_m

    # --- formation window (126 bars ending at t-skip)
    n_f = roll(valid.astype(float), formation, min_formation)
    F_r = roll(r, formation, min_formation)
    F_m = roll(m_frame, formation, min_formation)
    F_rm = roll(rm, formation, min_formation)
    F_m2 = roll(m2_frame, formation, min_formation)
    F_r2 = roll(r2, formation, min_formation)

    S_e = F_r - n_f * alpha - beta * F_m
    SS_e = (F_r2 - 2 * alpha * F_r - 2 * beta * F_rm + n_f * alpha * alpha
            + 2 * alpha * beta * F_m + beta * beta * F_m2)
    var_e = (SS_e / n_f - (S_e / n_f) ** 2).clip(lower=0.0)
    sd_e = np.sqrt(var_e)
    enough = (n_est >= min_estimation) & (n_f >= min_formation)
    return {"sum": S_e.where(enough), "sd": sd_e.where(enough), "beta": beta.where(enough),
            "n_formation": n_f.where(enough)}


def scores(P, resid: dict, t: int, tickers, *, secondary: bool = False) -> pd.Series:
    """The pre-registered score at date t: sum(e)/sd(e) primary, sum(e)/vol63 secondary."""
    s_e = resid["sum"].iloc[t].reindex(tickers)
    if secondary:
        vol = P.VOL63.iloc[t].reindex(tickers).replace(0, np.nan)
        return s_e / vol
    sd = resid["sd"].iloc[t].reindex(tickers).replace(0, np.nan)
    return s_e / sd


def collect(P, resid: dict, *, dev_only: bool = True, secondary: bool = False,
            config: str = "T20", progress_every: int = 100) -> pd.DataFrame:
    """Per rebalance date: the top-minus-bottom tercile spread of BOTH rankings, on one pool."""
    c = dict(L.BASE)
    c.update(L.CONFIGS[config])
    idx = P.close.index
    rows = []
    steps = [t for t in range(START, len(idx) - STEP - 2, STEP)
             if (not dev_only or idx[t] < L.SPLIT)]
    for i, t in enumerate(steps):
        out = L.rank_day(P, t, c)
        if out is None:
            continue
        fwd = forward_step_return(P.close, t)
        if fwd is None:
            continue
        pool = out[~L.vetoed(out)]
        frame = pd.DataFrame({
            "conventional": pool["comp"],
            "residual": scores(P, resid, t, pool.index, secondary=secondary),
            "fwd": fwd.reindex(pool.index),
        }).dropna()
        if len(frame) < 30:
            continue
        spreads = {}
        for name in ("conventional", "residual"):
            tercile = pd.qcut(frame[name], 3, labels=["low", "mid", "high"], duplicates="drop")
            g = frame.groupby(tercile, observed=False)["fwd"].mean()
            if "high" not in g.index or "low" not in g.index or g.isna().any():
                spreads = {}
                break
            spreads[name] = float(g["high"] - g["low"])
            spreads[f"{name}_high"] = float(g["high"])
            spreads[f"{name}_low"] = float(g["low"])
        if not spreads:
            continue
        rows.append({
            "date": idx[t],
            "pool": len(frame),
            "spearman": float(frame["conventional"].corr(frame["residual"], method="spearman")),
            "mean_beta": float(resid["beta"].iloc[t].reindex(frame.index).mean()),
            **spreads,
        })
        if progress_every and (i + 1) % progress_every == 0:
            print(f"  {i + 1}/{len(steps)} {idx[t].date()} resid "
                  f"{rows[-1]['residual'] * 1e4:.1f} bp vs conv "
                  f"{rows[-1]['conventional'] * 1e4:.1f} bp", flush=True)
    return pd.DataFrame(rows)


def summarise(df: pd.DataFrame, *, rng=None, n: int = N_BOOT, block: int = BLOCK) -> dict:
    if df.empty:
        return {"steps": 0}
    rng = np.random.default_rng(0) if rng is None else rng
    res = df["residual"].to_numpy()
    con = df["conventional"].to_numpy()
    idx = block_index_matrix(len(df), block=block, n=n, rng=rng)
    diff_paths = (res[idx].mean(axis=1) - con[idx].mean(axis=1)) * 1e4
    return {
        "steps": int(len(df)),
        "first": str(df["date"].iloc[0].date()),
        "last": str(df["date"].iloc[-1].date()),
        "mean_pool": round(float(df["pool"].mean()), 1),
        "spearman_mean": round(float(df["spearman"].mean()), 3),
        "spearman_p05": round(float(np.percentile(df["spearman"], 5)), 3),
        "mean_beta": round(float(df["mean_beta"].mean()), 3),
        "conventional_spread_bp": round(float(con.mean() * 1e4), 2),
        "residual_spread_bp": round(float(res.mean() * 1e4), 2),
        "paired_diff_bp": round(float((res.mean() - con.mean()) * 1e4), 2),
        "diff_p05": round(float(np.percentile(diff_paths, 5)), 2),
        "diff_p95": round(float(np.percentile(diff_paths, 95)), 2),
        "p_diff_le_0": round(float((diff_paths <= 0).mean()), 3),
        "share_of_steps_residual_better": round(float((res > con).mean()), 3),
    }


def verdict(s: dict) -> str:
    """The rule written in H-010 before this ran."""
    if not s.get("steps"):
        return "NO DATA"
    if s["spearman_mean"] > 0.95:
        return (f"NOTHING TO GAIN: the two scores rank the pool at Spearman "
                f"{s['spearman_mean']} - there is no room for a difference, whatever the spread.")
    if s["paired_diff_bp"] > 0 and s["diff_p05"] > 0:
        return ("PREDICTED SIGN, interval clear of zero: step 0 passes, build the lab lever "
                "(still DEV only).")
    if s["paired_diff_bp"] > 0:
        return ("predicted sign but the interval straddles zero: WEAK. H-010 says that is "
                "indistinguishable - do not read TEST.")
    return ("WRONG SIGN: H-010 stops here by its own pre-registration. A wrong sign is not an "
            "invitation to invert the rule.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="H-010 step 0: residual vs conventional ranking")
    ap.add_argument("--secondary", action="store_true", help="sum(e)/vol63 instead of sum(e)/sd(e)")
    ap.add_argument("--config", default="T20")
    ap.add_argument("--test-read-once", action="store_true",
                    help="include TEST (>= 2016). Only with Lucas's explicit approval.")
    ap.add_argument("--sectors", choices=("pit", "live"), default="pit")
    args = ap.parse_args(argv)

    cache = os.path.join(HERE, "_sweep_cache_oos", "close.pkl")
    if not os.path.exists(cache):
        print("SKIP:", cache, "missing")
        return 0
    if args.test_read_once:
        print("READING TEST. H-010 allows this only after Lucas has seen DEV and said so.",
              flush=True)
    print("loading OOS PIT panel...", flush=True)
    P = L.load_panel(oos=True, sectors=args.sectors)
    print("  close", P.close.shape, str(P.close.index[0].date()), "->",
          str(P.close.index[-1].date()), flush=True)
    print("residual momentum (closed form over rolling sums)...", flush=True)
    market = P.spy.pct_change(fill_method=None)
    resid = residual_momentum(P.rets, market)
    print(f"  usable name-days {int(resid['sum'].notna().sum().sum())}, "
          f"mean beta {float(resid['beta'].stack().mean()):.3f}", flush=True)

    df = collect(P, resid, dev_only=not args.test_read_once, secondary=args.secondary,
                 config=args.config)
    s = summarise(df)
    s["score"] = "sum(e)/vol63 (secondary)" if args.secondary else "sum(e)/sd(e) (primary)"
    s["sample"] = "DEV+TEST (read once)" if args.test_read_once else "DEV only (< 2016-01-01)"
    print("", flush=True)
    print(f"H-010 step 0 - {s['sample']}, pool from `{args.config}`, {s['score']}", flush=True)
    print(pd.Series(s).to_string(), flush=True)
    print("", flush=True)
    print("verdict:", verdict(s), flush=True)

    tag = "secondary" if args.secondary else "primary"
    if args.test_read_once:
        tag += "_test"
    scratch = os.path.join(HERE, "_lab_scratch", f"h010_step0_{tag}.json")
    os.makedirs(os.path.dirname(scratch), exist_ok=True)
    with open(scratch, "w", encoding="utf-8") as f:
        json.dump({"summary": s, "verdict": verdict(s),
                   "steps": df.assign(date=df["date"].astype(str)).to_dict(orient="records")
                   if not df.empty else []}, f, indent=2, default=str)
    print("wrote", scratch, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
