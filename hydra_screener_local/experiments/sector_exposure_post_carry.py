"""TASK-405 / H-006 - the sector cap binds at SELECTION; measure the PORTFOLIO.

`MAX_PER_SECTOR = 5` is enforced inside `core/portfolio_engine.select_tranche_names`, and only
in its second loop - the one that fills vacancies walking down the ranking. The first loop puts
back every held name that still ranks inside `buffer * n` and merely *counts* its sector, so a
carried name can push a sector past the cap. On top of that the cap is per TRANCHE: four
tranches each holding five names of one sector is twenty at portfolio level, with no rule broken.

This script measures what the book actually ends up holding. It changes nothing: no rule here,
no config, no engine. Deciding whether HYDRA needs a portfolio-level constraint is rule 6 and
waits for Lucas with these numbers in front of him.

    python experiments/sector_exposure_post_carry.py            # in-sample 2020-26
    python experiments/sector_exposure_post_carry.py --oos      # PIT panel 2004-26

Modelling choices, stated because they matter:
  * Each of the 4 tranches is taken as 1/4 of the stock sleeve, equal-weighted inside. The real
    engine lets tranche values drift between resets (47-51% between pair resets), so the weights
    here are the intended ones, not the drifted ones.
  * The vol-target exposure scales every name in a tranche by the same factor, so it cannot move
    a sector's SHARE of the invested sleeve. Shares are therefore reported on the invested part.
  * Sectors come from the same panel map the lab's cap uses (`--sectors pit|live`).
  * The drawdown here is the STOCK SLEEVE fully invested and unlevered: no vol-target scaling, no
    ETF sleeve, no cash. It is far deeper than the book's, and that gap is the point of the 50/50
    design - do not quote it as HYDRA's drawdown.
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

import engine_backtest as EB  # noqa: E402
import metrics as M  # noqa: E402
import redesign_lab as L  # noqa: E402
from config import MAX_PER_SECTOR, V9  # noqa: E402
from core.portfolio_engine import select_tranche_names  # noqa: E402

UNKNOWN = "Other"


def tranche_weights(tranches: list, n_tranches: int) -> dict:
    """Name -> weight of the stock sleeve, 1/n_tranches per tranche, equal inside."""
    w = {}
    for names in tranches:
        if not names:
            continue
        each = (1.0 / n_tranches) / len(names)
        for t in names:
            w[t] = w.get(t, 0.0) + each
    return w


def sector_view(weights: dict, sectors: dict) -> tuple[dict, dict]:
    """(names per sector, weight share per sector of the invested sleeve)."""
    counts, mass = {}, {}
    for t, w in weights.items():
        s = sectors.get(t, UNKNOWN)
        counts[s] = counts.get(s, 0) + 1
        mass[s] = mass.get(s, 0.0) + w
    total = sum(mass.values()) or 1.0
    share = {s: v / total for s, v in mass.items()}
    return counts, share


def _step_returns(close: pd.DataFrame, weights: dict, t: int, nxt: int) -> dict:
    """Name -> weight * price return from bar t to bar nxt. Missing print = skipped, and counted."""
    out, missing = {}, 0
    p0 = close.iloc[t]
    p1 = close.iloc[nxt]
    for name, w in weights.items():
        a, b = float(p0.get(name, np.nan)), float(p1.get(name, np.nan))
        if not (np.isfinite(a) and np.isfinite(b)) or a <= 0:
            missing += 1
            continue
        out[name] = w * (b / a - 1.0)
    return dict(contrib=out, missing=missing)


def run(P, *, oos: bool, progress_every: int = 100) -> dict:
    cfg = dict(V9)
    n_tr = int(cfg["tranches"])
    buf = float(cfg["stock_buffer"])
    idx = P.close.index
    sectors = {}
    c = dict(L.BASE)
    c.update(L.CONFIGS["T20"])
    tranches = [set() for _ in range(n_tr)]
    steps = list(range(EB.START, len(idx) - 6, EB.STEP))
    rows, per_tranche_breach, sector_steps = [], [], []
    for i, t in enumerate(steps):
        k = i % n_tr
        rk = EB._ranking(P, t, c)
        if rk is not None:
            n = int(rk["recommended_count"].iloc[0])
            if "sector" in rk.columns:
                sectors.update(dict(zip(rk["ticker"], rk["sector"])))
            picked = select_tranche_names(rk, n, set(tranches[k]), buf)
            carried = sorted(set(picked) & set(tranches[k]))
            tranches[k] = set(picked)
            # the cap's own scope: does THIS tranche hold more than the cap in one sector?
            tc = {}
            for name in picked:
                s = sectors.get(name, UNKNOWN)
                if s != UNKNOWN:
                    tc[s] = tc.get(s, 0) + 1
            worst_sector = max(tc, key=tc.get) if tc else None
            worst = tc.get(worst_sector, 0) if worst_sector else 0
            if worst > MAX_PER_SECTOR:
                per_tranche_breach.append(dict(date=str(idx[t].date()), tranche=k,
                                               sector=worst_sector, names=worst,
                                               carried=len(carried), picked=len(picked)))
        weights = tranche_weights(tranches, n_tr)
        if not weights:
            continue
        counts, share = sector_view(weights, sectors)
        known = {s: v for s, v in counts.items() if s != UNKNOWN}
        top_sector = max(known, key=known.get) if known else None
        known_share = {s: v for s, v in share.items() if s != UNKNOWN}
        top_share_sector = max(known_share, key=known_share.get) if known_share else None
        nxt = t + EB.STEP
        ret = _step_returns(P.close, weights, t, nxt) if nxt < len(idx) else dict(contrib={},
                                                                                 missing=0)
        by_sector_ret = {}
        for name, r in ret["contrib"].items():
            s = sectors.get(name, UNKNOWN)
            by_sector_ret[s] = by_sector_ret.get(s, 0.0) + r
        rows.append(dict(
            date=str(idx[t].date()),
            distinct=len(weights),
            max_names_in_a_sector=int(known.get(top_sector, 0)) if top_sector else 0,
            max_names_sector=top_sector,
            max_share_pct=round(float(known_share.get(top_share_sector, 0.0)) * 100, 2)
            if top_share_sector else 0.0,
            max_share_sector=top_share_sector,
            unknown_share_pct=round(float(share.get(UNKNOWN, 0.0)) * 100, 2),
            step_return=round(float(sum(by_sector_ret.values())), 6),
            missing_prices=ret["missing"],
        ))
        sector_steps.append(by_sector_ret)
        if progress_every and (i + 1) % progress_every == 0:
            print(f"  {i + 1}/{len(steps)} {rows[-1]['date']} "
                  f"max {rows[-1]['max_names_in_a_sector']} names in "
                  f"{rows[-1]['max_names_sector']}", flush=True)
    df = pd.DataFrame(rows)
    return dict(steps=df, sector_returns=sector_steps, per_tranche_breach=per_tranche_breach,
                oos=bool(oos))


def _streaks(over) -> dict:
    """Longest run of consecutive steps above the cap, and how many runs there were."""
    best = cur = runs = 0
    for v in pd.Series(over).astype(bool).tolist():
        if v:
            cur += 1
            if cur == 1:
                runs += 1
            best = max(best, cur)
        else:
            cur = 0
    return dict(longest_steps=int(best), runs=int(runs))


def _drawdown_attribution(df: pd.DataFrame, sector_returns: list) -> dict:
    """Sector contribution inside the sleeve's worst peak-to-trough window.

    The under-water path comes from `metrics.drawdown_curve`, the one definition in the repo,
    so the high-water mark is floored at the capital that went in. That floor is what lets the
    window start BEFORE the first step: if the sleeve never traded above par, the peak is the
    money put in rather than whatever was left after the first losing step, and the blame has
    to cover that step too. `peak_is_initial_capital` says when that happened, because in that
    case `peak_date` is the first mark of the sleeve and not a date the peak was struck on.
    """
    r = pd.Series(df["step_return"].values, index=pd.DatetimeIndex(df["date"]))
    if r.isna().any():
        # `drawdown_curve` drops NaNs, and `sector_returns` is indexed by POSITION in `df`.
        # A hole would silently shift the blame window onto the wrong steps, so refuse.
        raise ValueError("step_return has NaNs: the drawdown window would not line up with "
                         "the per-step sector contributions")
    eq = (1 + r).cumprod()
    dd = M.drawdown_curve(r)
    trough = int(np.argmin(dd.values))
    from_capital = bool(float(eq.values[: trough + 1].max()) <= 1.0)
    if from_capital:
        peak = 0
        window = range(0, trough + 1)
    else:
        peak = int(np.argmax(eq.values[: trough + 1])) if trough > 0 else 0
        window = range(peak + 1, trough + 1)
    contrib = {}
    for i in window:
        for s, v in sector_returns[i].items():
            contrib[s] = contrib.get(s, 0.0) + v
    ordered = sorted(contrib.items(), key=lambda kv: kv[1])
    return dict(
        maxdd_pct=round(float(dd.min()) * 100, 2),
        peak_date=str(r.index[peak].date()), trough_date=str(r.index[trough].date()),
        peak_is_initial_capital=from_capital,
        steps_in_window=len(window),
        worst_sectors=[dict(sector=s, sum_of_step_contributions_pct=round(v * 100, 2))
                       for s, v in ordered[:5]],
    )


def summarise(out: dict) -> dict:
    df = out["steps"]
    names = df["max_names_in_a_sector"]
    share = df["max_share_pct"]
    over = names > MAX_PER_SECTOR
    top = (df.loc[over, "max_names_sector"].value_counts().head(5).to_dict() if over.any() else {})
    return dict(
        steps=int(len(df)),
        cap=int(MAX_PER_SECTOR),
        portfolio_max_names=int(names.max()),
        portfolio_p95_names=float(np.percentile(names, 95)),
        portfolio_median_names=float(names.median()),
        steps_over_cap=int(over.sum()),
        pct_steps_over_cap=round(float(over.mean()) * 100, 1),
        streaks_over_cap=_streaks(over),
        sectors_over_cap=top,
        max_sector_share_pct=round(float(share.max()), 2),
        p95_sector_share_pct=round(float(np.percentile(share, 95)), 2),
        median_sector_share_pct=round(float(share.median()), 2),
        unknown_share_pct_mean=round(float(df["unknown_share_pct"].mean()), 2),
        per_tranche_breaches=len(out["per_tranche_breach"]),
        per_tranche_breach_examples=out["per_tranche_breach"][:5],
        drawdown=_drawdown_attribution(df, out["sector_returns"]),
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description="H-006: sector exposure after the carry")
    ap.add_argument("--oos", action="store_true", help="PIT panel 2004-26 instead of in-sample")
    ap.add_argument("--sectors", choices=("pit", "live"), default="pit")
    ap.add_argument("--sectors-date", default=None)
    args = ap.parse_args(argv)

    cache = os.path.join(HERE, "_sweep_cache_oos" if args.oos else "_sweep_cache", "close.pkl")
    if not os.path.exists(cache):
        print("SKIP:", cache, "missing")
        return 0
    print(f"loading {'OOS PIT' if args.oos else 'in-sample'} panel...", flush=True)
    P = L.load_panel(oos=args.oos, sectors=args.sectors, sectors_date=args.sectors_date)
    print("  close", P.close.shape, str(P.close.index[0].date()), "->",
          str(P.close.index[-1].date()), flush=True)
    out = run(P, oos=args.oos)
    s = summarise(out)
    print("", flush=True)
    print("H-006 - sector exposure of the stock sleeve AFTER the carry", flush=True)
    print(pd.Series(
        {k: v for k, v in s.items()
         if k not in ("sectors_over_cap", "streaks_over_cap", "drawdown",
                      "per_tranche_breach_examples")}).to_string(), flush=True)
    print("sectors most often over the cap:", s["sectors_over_cap"], flush=True)
    print("streaks over the cap:", s["streaks_over_cap"], flush=True)
    print("per-tranche breaches (the cap's own scope):", s["per_tranche_breaches"], flush=True)
    for b in s["per_tranche_breach_examples"]:
        print("   ", b, flush=True)
    print("worst drawdown of the STOCK SLEEVE fully invested (no vol-target, no ETF sleeve, no "
          "cash - not the book's drawdown), by sector contribution:", flush=True)
    print(json.dumps(s["drawdown"], indent=2), flush=True)

    scratch = os.path.join(HERE, "_lab_scratch",
                           "task405_oos.json" if args.oos else "task405.json")
    os.makedirs(os.path.dirname(scratch), exist_ok=True)
    payload = dict(summary=s, steps=out["steps"].to_dict(orient="records"),
                   per_tranche_breach=out["per_tranche_breach"],
                   note="measurement only; no rule changed (H-006 stays PROPOSED). The drawdown "
                        "is the fully invested unlevered stock sleeve, not the 50/50 book.")
    with open(scratch, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    print("wrote", scratch, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
