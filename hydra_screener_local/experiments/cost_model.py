"""
TASK-327 — size-aware one-way trading costs.

The harness (TASK-322) charges a flat COST_BP_PER_SIDE on turnover:
    net = gross - 2 * bp/10000 * turnover
That is right for S&P 500 names and wrong for a $5M ADV Russell name.

Curve (per side), log-linear in 20-day dollar ADV, knots inspired by
Novy-Marx & Velikov 2016, "A Taxonomy of Anomalies and Their Trading Costs"
(RFS): mid-turnover anomalies cost ~19–57 bp *round-trip* on TAQ. Per side
that is roughly 10–28 bp in the middle of the book; we stretch the illiquid
tail because production includes Russell 2000:

    ADV >= $50M  ->  5 bp
    ADV  = $5M   -> 20 bp
    ADV <= $0.5M -> 50 bp

Missing/non-positive ADV -> 50 bp (assume illiquid, not free).

A `flat` curve ignores ADV and returns the given bp. At flat=10 the driver
must reproduce the harness net *exactly* (same formula, same turnover).

Does not edit backtest_variant_sweep.py. Reads `_sweep_cache_oos/` pickles.
"""
from __future__ import annotations

import math
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

EXP = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(EXP)
sys.path.insert(0, ROOT)
sys.path.insert(0, EXP)

OOS_CACHE = os.path.join(EXP, "_sweep_cache_oos")
CYCLES_PER_YEAR = 252 / 5

# knots: (adv_usd, bp_per_side)
_KNOTS = (
    (50_000_000.0, 5.0),
    (5_000_000.0, 20.0),
    (500_000.0, 50.0),
)


def cost_bp_per_side(adv_usd, price=None, *, curve="nv2016", flat_bp=10.0):
    """One-way cost in basis points.

    curve='nv2016' — size-aware (ADV). `price` is accepted for the documented
    signature and unused: NV2016 costs are quoted on dollar ADV, not on price
    alone.
    curve='flat' — always `flat_bp` (acceptance: 10 reproduces the harness).
    """
    if curve == "flat":
        return float(flat_bp)
    if curve != "nv2016":
        raise ValueError(f"unknown curve {curve!r}")
    try:
        adv = float(adv_usd)
    except (TypeError, ValueError):
        return 50.0
    if not math.isfinite(adv) or adv <= 0:
        return 50.0
    if adv >= _KNOTS[0][0]:
        return _KNOTS[0][1]
    if adv <= _KNOTS[-1][0]:
        return _KNOTS[-1][1]
    for (hi_adv, hi_bp), (lo_adv, lo_bp) in zip(_KNOTS, _KNOTS[1:]):
        if lo_adv <= adv <= hi_adv:
            w = (math.log(adv) - math.log(lo_adv)) / (math.log(hi_adv) - math.log(lo_adv))
            return lo_bp + w * (hi_bp - lo_bp)
    return 50.0


def _net_from_turnover(ret, turnover, bp):
    """Harness formula. net == ret when bp is 0."""
    return ret - (2.0 * bp / 10000.0) * turnover


def size_aware_net(ret, entered, n, adv_row, px_row, *, curve="nv2016", flat_bp=10.0):
    """Portfolio net for one cycle.

    Matches the harness when every entered name has cost_bp_per_side = flat_bp:
    turnover is |entered|/n, two sides.
    """
    n = max(int(n), 1)
    if not entered:
        return float(ret), 0.0
    bps = [cost_bp_per_side(adv_row.get(t, np.nan), px_row.get(t, np.nan),
                            curve=curve, flat_bp=flat_bp) for t in entered]
    mean_bp = float(np.mean(bps))
    turnover = len(entered) / n
    return _net_from_turnover(ret, turnover, mean_bp), mean_bp


def _replay(P, cfg=None, start=260, step=5, hold=5, lag=1):
    import backtest_variant_sweep as sweep
    c = dict(sweep.DEFAULTS)
    c.update(cfg or {})
    idx, prev = P.close.index, set()
    rows = []
    adv = (P.close * P.volume).rolling(20).mean()
    for t in range(start, len(idx) - hold - lag - 1, step):
        out, tk = sweep.score_day(P, t, c)
        if out is None:
            continue
        m = P.meta_for(t)
        n = c["fixed_n"] or max(6, min(int(round(14 * m.overall_aggression * m.pillar_multipliers["COMPASS"])), 28))
        sel = sweep.pick(out, n, c) if (not c["regime_gate"] or m.regime_score >= c["regime_thr"]) else out.head(0)
        if c["gate"] and len(sel):
            neg = (sel["ret"] < 0) if c["gate_needs_negative"] else True
            veto = (neg & ((sel["dist"] < c["gate_dist"]) | (sel["ret"] < c["gate_ret"]))).fillna(False)
            veto |= sel["dist"].isna() | sel["ret"].isna()
            sel = sel[~veto]
        cur = set(sel.index)
        e, x = t + lag, t + lag + hold
        fwd = (P.close.iloc[x][sel.index] / P.close.iloc[e][sel.index] - 1).dropna() if len(sel) else pd.Series(dtype=float)
        ret = float(fwd.mean()) if len(fwd) else 0.0
        turnover = len(cur - prev) / max(len(cur), 1) if cur else 0.0
        entered = cur - prev
        adv_row = adv.iloc[t].to_dict() if t < len(adv) else {}
        px_row = P.close.iloc[t].to_dict()
        rows.append(dict(date=idx[t], n=len(sel), ret=ret, turnover=turnover,
                         entered=entered, adv_row=adv_row, px_row=px_row))
        prev = cur
    return rows


def summarise(rows, *, curve="nv2016", flat_bp=10.0):
    recs = []
    for r in rows:
        net, mean_bp = size_aware_net(r["ret"], r["entered"], r["n"], r["adv_row"], r["px_row"],
                                      curve=curve, flat_bp=flat_bp)
        recs.append(dict(date=r["date"], ret=r["ret"], turnover=r["turnover"],
                         net=net, mean_bp=mean_bp, n=r["n"]))
    df = pd.DataFrame(recs)
    if df.empty:
        return df, {}
    r, net = df["ret"], df["net"]
    stats = dict(
        cycles=len(df),
        mean_bp=round(r.mean() * 10000, 1),
        net_bp=round(net.mean() * 10000, 1),
        ann_pct=round(((1 + r).prod() ** (CYCLES_PER_YEAR / len(r)) - 1) * 100, 2),
        ann_net_pct=round(((1 + net).prod() ** (CYCLES_PER_YEAR / len(net)) - 1) * 100, 2),
        mean_cost_bp=round(float(df["mean_bp"].mean()), 1),
        turnover_pct=round(df["turnover"].mean() * 100, 1),
    )
    return df, stats


def main():
    import backtest_variant_sweep as sweep
    from config import COST_BP_PER_SIDE
    from data.universe import fetch_sp500_pit_payload

    if not os.path.exists(os.path.join(OOS_CACHE, "close.pkl")):
        sys.exit(f"no OOS cache at {OOS_CACHE}")
    payload = fetch_sp500_pit_payload()
    P = sweep.Panels(cache_dir=OOS_CACHE, pit_payload=payload)
    print("replaying production cycles on", P.close.shape)
    rows = _replay(P)
    harness = sweep.run(P)
    h_net = sweep._net_returns(harness, COST_BP_PER_SIDE)

    _, flat = summarise(rows, curve="flat", flat_bp=COST_BP_PER_SIDE)
    _, sized = summarise(rows, curve="nv2016")
    print(f"harness net_bp {round(h_net.mean()*10000, 1)}  ann_net "
          f"{round(((1+h_net).prod()**(CYCLES_PER_YEAR/len(h_net))-1)*100, 2)}")
    print("flat 10bp     ", flat)
    print("nv2016 sized  ", sized)
    delta = abs(flat["net_bp"] - round(h_net.mean() * 10000, 1))
    print("flat vs harness |net_bp| delta:", delta, "(must be 0.0)")


if __name__ == "__main__":
    main()
