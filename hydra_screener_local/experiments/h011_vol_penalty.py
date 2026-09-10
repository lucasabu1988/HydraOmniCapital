"""H-011 step 0 — does dividing momentum by vol63 help or hurt the NEXT five days, on OUR pool?

Pre-registered 2026-09-10 (`.comms/hypotheses.md`, H-011). Control is production's score,
`mom12_7 / vol63` (the `comp` column `rank_day` produces, boosts included); the candidate is the
same thing without the division (`risk_adjust=False`, lab lever in `redesign_lab.BASE`). Nothing
else changes: same eligible pool, same veto gate, same sector map, same dates.

Per rebalance date (every STEP bars from START), on the pool `rank_day` produces after the veto:
rank the pool by both scores, take the top-minus-bottom TERCILE spread of the forward 5-bar return
on the production convention (buy at the t+1 close, sell at the t+6 close), and ALSO the mean
forward return of the top `n` names each score would actually pick (the selection the sleeve
trades). Paired: same dates, same pool, one block-bootstrap index matrix for both legs.

DEV only (< 2016-01-01) unless `--test-read-once`, which H-011 allows only after Lucas has seen
DEV and said so. Only measures; changing the score is rule 6.
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
TOP_N = 14                # production's nominal count at aggression 1.0 (14 * overall_aggression)


def paired_rankings(P, t: int, c: dict) -> pd.DataFrame | None:
    """The same pool scored both ways. `control` = production comp (mom/vol63), `raw` = comp without
    the division, computed by rank_day itself with the lever flipped, so boosts and the veto are
    applied identically on both sides."""
    ctl = L.rank_day(P, t, dict(c, risk_adjust=True))
    raw = L.rank_day(P, t, dict(c, risk_adjust=False))
    if ctl is None or raw is None:
        return None
    ctl = ctl[~L.vetoed(ctl)]
    raw = raw[~L.vetoed(raw)]
    common = ctl.index.intersection(raw.index)
    if len(common) < 30:
        return None
    return pd.DataFrame({"control": ctl.loc[common, "comp"], "raw": raw.loc[common, "comp"]})


def step_row(P, t: int, c: dict, *, top_n: int = TOP_N) -> dict | None:
    scores = paired_rankings(P, t, c)
    if scores is None:
        return None
    fwd = forward_step_return(P.close, t)
    if fwd is None:
        return None
    frame = scores.assign(fwd=fwd.reindex(scores.index)).dropna()
    if len(frame) < 30:
        return None
    row = {"date": P.close.index[t], "pool": int(len(frame)),
           "spearman": float(frame["control"].corr(frame["raw"], method="spearman"))}
    for name in ("control", "raw"):
        tercile = pd.qcut(frame[name], 3, labels=["low", "mid", "high"], duplicates="drop")
        g = frame.groupby(tercile, observed=False)["fwd"].mean()
        if "high" not in g.index or "low" not in g.index or g.isna().any():
            return None
        row[f"{name}_spread"] = float(g["high"] - g["low"])
        top = frame.nlargest(top_n, name)
        row[f"{name}_top"] = float(top["fwd"].mean())
        row[f"{name}_top_vol"] = float(P.VOL63.iloc[t].reindex(top.index).mean())
    ctl_top = set(frame.nlargest(top_n, "control").index)
    raw_top = set(frame.nlargest(top_n, "raw").index)
    row["top_overlap"] = len(ctl_top & raw_top) / float(top_n)
    return row


def collect(P, *, dev_only: bool = True, config: str = "T20", progress_every: int = 100) -> pd.DataFrame:
    c = dict(L.BASE)
    c.update(L.CONFIGS[config])
    idx = P.close.index
    steps = [t for t in range(START, len(idx) - STEP - 2, STEP) if (not dev_only or idx[t] < L.SPLIT)]
    rows = []
    for i, t in enumerate(steps):
        row = step_row(P, t, c)
        if row is not None:
            rows.append(row)
        if progress_every and (i + 1) % progress_every == 0 and rows:
            r = rows[-1]
            print(f"  {i + 1}/{len(steps)} {idx[t].date()} top raw {r['raw_top'] * 1e4:.1f} bp vs "
                  f"control {r['control_top'] * 1e4:.1f} bp, overlap {r['top_overlap']:.2f}", flush=True)
    return pd.DataFrame(rows)


def summarise(df: pd.DataFrame, *, rng=None, n: int = N_BOOT, block: int = BLOCK) -> dict:
    if df.empty:
        return {"steps": 0}
    rng = np.random.default_rng(0) if rng is None else rng
    idx = block_index_matrix(len(df), block=block, n=n, rng=rng)
    out = {"steps": int(len(df)), "first": str(df["date"].iloc[0].date()), "last": str(df["date"].iloc[-1].date()),
           "mean_pool": round(float(df["pool"].mean()), 1),
           "spearman_mean": round(float(df["spearman"].mean()), 3),
           "top_overlap_mean": round(float(df["top_overlap"].mean()), 3),
           "control_top_vol63": round(float(df["control_top_vol"].mean()), 4),
           "raw_top_vol63": round(float(df["raw_top_vol"].mean()), 4)}
    for kind in ("spread", "top"):
        ctl = df[f"control_{kind}"].to_numpy()
        raw = df[f"raw_{kind}"].to_numpy()
        paths = (raw[idx].mean(axis=1) - ctl[idx].mean(axis=1)) * 1e4
        out.update({
            f"control_{kind}_bp": round(float(ctl.mean() * 1e4), 2),
            f"raw_{kind}_bp": round(float(raw.mean() * 1e4), 2),
            f"{kind}_diff_bp": round(float((raw.mean() - ctl.mean()) * 1e4), 2),
            f"{kind}_diff_p05": round(float(np.percentile(paths, 5)), 2),
            f"{kind}_diff_p95": round(float(np.percentile(paths, 95)), 2),
            f"{kind}_p_diff_le_0": round(float((paths <= 0).mean()), 3),
            f"{kind}_share_steps_raw_better": round(float((raw > ctl).mean()), 3),
        })
    return out


def verdict(s: dict) -> str:
    """The rule written in H-011 before this ran. The deciding number at step 0 is the TOP-n paired
    difference (what the sleeve actually buys); the tercile spread is reported for context."""
    if not s.get("steps"):
        return "NO DATA"
    if s["top_overlap_mean"] > 0.95:
        return (f"NOTHING TO GAIN: the two scores pick the same names (top-{TOP_N} overlap "
                f"{s['top_overlap_mean']}); no room for a difference.")
    if s["top_diff_bp"] > 0 and s["top_diff_p05"] > 0:
        return "PREDICTED SIGN, interval clear of zero: step 0 passes, run the portfolio A/B (DEV first)."
    if s["top_diff_bp"] > 0:
        return ("predicted sign but the interval straddles zero: WEAK. H-011 says the portfolio A/B may "
                "still be run (the deciding metric is CAGR on B0), but expect a small effect.")
    return ("WRONG SIGN: the penalty helps the next five days on this pool. H-011 stops here by its "
            "own pre-registration; no portfolio A/B, TEST not read.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="H-011 step 0: mom12_7/vol63 vs raw mom12_7 on the same pool")
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
        print("READING TEST. H-011 allows this only after Lucas has seen DEV and said so.", flush=True)
    print("loading OOS PIT panel...", flush=True)
    P = L.load_panel(oos=True, sectors=args.sectors)
    print("  close", P.close.shape, str(P.close.index[0].date()), "->", str(P.close.index[-1].date()), flush=True)
    df = collect(P, dev_only=not args.test_read_once, config=args.config)
    s = summarise(df)
    s["sample"] = "DEV+TEST (read once)" if args.test_read_once else "DEV only (< 2016-01-01)"
    s["config"] = args.config
    print("", flush=True)
    print(f"H-011 step 0 - {s['sample']}, pool from `{args.config}`, control mom12_7/vol63 vs raw mom12_7", flush=True)
    print(pd.Series(s).to_string(), flush=True)
    print("", flush=True)
    print("verdict:", verdict(s), flush=True)
    tag = "test_read_once" if args.test_read_once else "dev"
    scratch = os.path.join(HERE, "_lab_scratch", f"h011_step0_{tag}.json")
    os.makedirs(os.path.dirname(scratch), exist_ok=True)
    with open(scratch, "w", encoding="utf-8") as f:
        json.dump({"summary": s, "verdict": verdict(s),
                   "steps": df.assign(date=df["date"].astype(str)).to_dict(orient="records") if not df.empty else []},
                  f, indent=2, default=str)
    print("wrote", scratch, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
