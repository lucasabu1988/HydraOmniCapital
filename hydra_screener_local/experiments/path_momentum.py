"""H-009 step 0 - does the PATH of the momentum predict anything in OUR data? DEV only.

Two names with the same 12-7 return did not get there the same way. Da, Gurun & Warachka (*Frog
in the Pan*, RFS 2014) argue the gradual riser continues better: information that arrives in small
daily pieces is absorbed more slowly than information that arrives in jumps, so continuation is
what is left over. Their measure, over the same formation window production already uses (the 126
daily returns from t-251 to t-126, the window behind `MOM_12_7`):

    ID = sign(PRET) x (%neg - %pos)

`%pos` / `%neg` are the fractions of NON-ZERO days in the window that were positive / negative;
`PRET` is the window's cumulative return. Low (negative) ID means continuous information, high
means discrete. For a winner, many small up-days push `%pos` up and ID down.

This module answers only the question that comes before any portfolio variant: **at each
rebalance date, does the eligible pool's forward return line up with ID the way the paper says?**
The pre-registration (H-009, `.comms/hypotheses.md`, committed before this file ran) declares that
a wrong-signed DEV spread kills the hypothesis rather than inviting a flipped rule.

    python experiments/path_momentum.py                  # DEV (< 2016-01-01), the pre-registered run
    python experiments/path_momentum.py --winners-only   # the paper's own subsample
    python experiments/path_momentum.py --test-read-once  # refuses unless Lucas said so

Conventions taken from the live path rather than re-invented: the candidate pool is whatever
`redesign_lab.rank_day` returns (same filters, same gate), and the forward return is the
production one - buy at the t+1 close, sell at the t+6 close (`run_exec`'s `lag=1`, 5-bar step).
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
from reset_ab import block_index_matrix  # noqa: E402

FORMATION = 126          # bars in the 12-7 window
SKIP = 126               # the window ends this many bars before t
STEP = 5                 # rebalance step, and the holding period of the forward return
START = 280              # same warm-up as the rest of the lab
N_BOOT = 5000
BLOCK = 13


def information_discreteness(rets: pd.DataFrame, *, formation: int = FORMATION,
                             skip: int = SKIP) -> pd.DataFrame:
    """ID aligned so that row t is the ID of the window (t-251 .. t-126). Pure; no clock.

    Rolling over booleans, then shifted by `skip`, so nothing after the formation window enters
    the number - the same alignment `MOM_12_7 = close.shift(126)/close.shift(252) - 1` has.
    """
    r = rets
    pos = (r > 0).rolling(formation).sum().shift(skip)
    neg = (r < 0).rolling(formation).sum().shift(skip)
    nonzero = pos + neg
    pret = r.rolling(formation).sum().shift(skip)          # log-free proxy for the window's sign
    with np.errstate(invalid="ignore", divide="ignore"):
        share_pos = pos.div(nonzero.replace(0, np.nan))
        share_neg = neg.div(nonzero.replace(0, np.nan))
    return np.sign(pret) * (share_neg - share_pos)


def forward_step_return(close: pd.DataFrame, t: int, step: int = STEP) -> pd.Series | None:
    """Production convention: bought at the t+1 close, sold at the t+1+step close."""
    entry, exit_ = t + 1, t + 1 + step
    if exit_ >= len(close.index):
        return None
    a = close.iloc[entry]
    b = close.iloc[exit_]
    out = b / a - 1.0
    return out.where(np.isfinite(a) & np.isfinite(b) & (a > 0))


def collect(P, idf: pd.DataFrame, *, dev_only: bool = True, winners_only: bool = False,
            config: str = "T20", progress_every: int = 100) -> pd.DataFrame:
    """One row per (rebalance date, tercile): mean forward return of the eligible pool."""
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
        pool = out[~L.vetoed(out)]                          # the gate applies, as in production
        if winners_only:
            pool = pool[pool["comp"] > 0]
        ids = idf.iloc[t].reindex(pool.index)
        frame = pd.DataFrame({"comp": pool["comp"], "id": ids,
                              "fwd": fwd.reindex(pool.index)}).dropna()
        if len(frame) < 30:
            continue
        # terciles of ID *within the pool that day*: no global threshold, nothing fitted
        frame["tercile"] = pd.qcut(frame["id"], 3, labels=["continuous", "middle", "discrete"],
                                   duplicates="drop")
        g = frame.groupby("tercile", observed=False)["fwd"].mean()
        if g.isna().any() or "continuous" not in g.index or "discrete" not in g.index:
            continue
        rows.append({
            "date": idx[t],
            "pool": len(frame),
            "continuous": float(g["continuous"]),
            "middle": float(g.get("middle", np.nan)),
            "discrete": float(g["discrete"]),
            "spread": float(g["continuous"] - g["discrete"]),
            "id_continuous": float(frame.loc[frame["tercile"] == "continuous", "id"].mean()),
            "id_discrete": float(frame.loc[frame["tercile"] == "discrete", "id"].mean()),
        })
        if progress_every and (i + 1) % progress_every == 0:
            print(f"  {i + 1}/{len(steps)} {idx[t].date()} spread "
                  f"{rows[-1]['spread'] * 1e4:.1f} bp", flush=True)
    return pd.DataFrame(rows)


def summarise(df: pd.DataFrame, *, rng=None, n: int = N_BOOT, block: int = BLOCK) -> dict:
    """The pre-declared deciding number: the tercile spread in bp per 5-bar step, with a
    moving-block interval on the same block draws for both legs."""
    if df.empty:
        return {"steps": 0}
    rng = np.random.default_rng(0) if rng is None else rng
    cont = df["continuous"].to_numpy()
    disc = df["discrete"].to_numpy()
    idx = block_index_matrix(len(df), block=block, n=n, rng=rng)
    spread_paths = (cont[idx].mean(axis=1) - disc[idx].mean(axis=1)) * 1e4
    spread = float((cont.mean() - disc.mean()) * 1e4)
    hit = float((df["spread"] > 0).mean())
    return {
        "steps": int(len(df)),
        "first": str(df["date"].iloc[0].date()),
        "last": str(df["date"].iloc[-1].date()),
        "mean_pool": round(float(df["pool"].mean()), 1),
        "continuous_bp": round(float(cont.mean() * 1e4), 2),
        "middle_bp": round(float(df["middle"].mean() * 1e4), 2),
        "discrete_bp": round(float(disc.mean() * 1e4), 2),
        "spread_bp": round(spread, 2),
        "spread_p05": round(float(np.percentile(spread_paths, 5)), 2),
        "spread_p95": round(float(np.percentile(spread_paths, 95)), 2),
        "p_spread_le_0": round(float((spread_paths <= 0).mean()), 3),
        "share_of_steps_positive": round(hit, 3),
        "mean_id_continuous": round(float(df["id_continuous"].mean()), 4),
        "mean_id_discrete": round(float(df["id_discrete"].mean()), 4),
    }


def verdict(s: dict) -> str:
    """The rule written down in H-009 before this ran."""
    if not s.get("steps"):
        return "NO DATA"
    if s["spread_bp"] > 0 and s["spread_p05"] > 0:
        return ("PREDICTED SIGN, interval clear of zero: step 0 passes, the portfolio lever is "
                "worth building (still DEV only).")
    if s["spread_bp"] > 0:
        return ("predicted sign but the interval straddles zero: WEAK. H-009 says a straddling "
                "interval is indistinguishable - do not read TEST.")
    return ("WRONG SIGN: H-009 stops here by its own pre-registration. A wrong-signed spread is a "
            "rejection, not a reason to flip the rule.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="H-009 step 0: does the momentum path predict?")
    ap.add_argument("--winners-only", action="store_true",
                    help="the paper's subsample: positive composite only")
    ap.add_argument("--config", default="T20", help="lab config whose pool is used (default T20)")
    ap.add_argument("--test-read-once", action="store_true",
                    help="include TEST (>= 2016). Only with Lucas's explicit approval.")
    ap.add_argument("--sectors", choices=("pit", "live"), default="pit")
    args = ap.parse_args(argv)

    cache = os.path.join(HERE, "_sweep_cache_oos", "close.pkl")
    if not os.path.exists(cache):
        print("SKIP:", cache, "missing")
        return 0
    if args.test_read_once:
        print("READING TEST. H-009 allows this only after Lucas has seen DEV and said so.",
              flush=True)
    print("loading OOS PIT panel...", flush=True)
    P = L.load_panel(oos=True, sectors=args.sectors)
    print("  close", P.close.shape, str(P.close.index[0].date()), "->",
          str(P.close.index[-1].date()), flush=True)
    idf = information_discreteness(P.rets)
    print(f"  ID computed on the 12-7 window; {int(idf.notna().sum().sum())} name-days", flush=True)

    df = collect(P, idf, dev_only=not args.test_read_once, winners_only=args.winners_only,
                 config=args.config)
    s = summarise(df)
    s["winners_only"] = bool(args.winners_only)
    s["sample"] = "DEV+TEST (read once)" if args.test_read_once else "DEV only (< 2016-01-01)"
    print("", flush=True)
    print(f"H-009 step 0 - {s['sample']}, pool from `{args.config}`"
          f"{' , winners only' if args.winners_only else ''}", flush=True)
    print(pd.Series(s).to_string(), flush=True)
    print("", flush=True)
    print("verdict:", verdict(s), flush=True)

    # the subsample is in the filename: the winners-only run used to overwrite the full-pool one,
    # which is how a rejected result quietly disappears
    tag = "winners" if args.winners_only else "pool"
    if args.test_read_once:
        tag += "_test"
    scratch = os.path.join(HERE, "_lab_scratch", f"h009_step0_{tag}.json")
    os.makedirs(os.path.dirname(scratch), exist_ok=True)
    with open(scratch, "w", encoding="utf-8") as f:
        json.dump({"summary": s, "verdict": verdict(s),
                   "steps": df.assign(date=df["date"].astype(str)).to_dict(orient="records")
                   if not df.empty else []},
                  f, indent=2, default=str)
    print("wrote", scratch, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
