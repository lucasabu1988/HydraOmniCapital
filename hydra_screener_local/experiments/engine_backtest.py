"""TASK-347 — drive the PRODUCTION engine through the in-sample lab panel.

Compares plan/settle/mark book values to the lab's T20+ETF 50/50 mix, and to the
same engine with inter-sleeve transfer orders stripped (1/8 reset off).

    python experiments/engine_backtest.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import redesign_lab as L  # noqa: E402
import sleeve_lab as S  # noqa: E402
from config import V9  # noqa: E402
import core.portfolio_engine as E  # noqa: E402

SCRATCH = os.path.join(HERE, "_lab_scratch", "task347.json")
START = 280
STEP = 5


def _stats(values: pd.Series, label: str, step=STEP) -> dict:
    r = values.pct_change().dropna()
    if r.empty:
        return dict(config=label, cycles=0)
    py = 252.0 / step
    def ann(x):
        return float(((1 + x).prod() ** (py / len(x)) - 1) * 100)
    eq = (1 + r).cumprod()
    dd = float((eq / eq.cummax() - 1).min()) * 100
    return dict(
        config=label, cycles=int(len(r)),
        ann_net=round(ann(r), 2),
        sharpe_net=round(float(r.mean() / r.std() * np.sqrt(py)), 2) if r.std() else 0.0,
        maxdd_net=round(dd, 1),
    )


def _ranking(P, t, c):
    out = L.rank_day(P, t, c)
    if out is None:
        return None
    m = P.meta_for(t, True)
    n = max(6, min(int(round(14 * m.overall_aggression * m.pillar_multipliers["COMPASS"])), 28))
    return pd.DataFrame({
        "ticker": out.index,
        "rank": range(1, len(out) + 1),
        "sector": out["sector"].values,
        "reason": np.where(L.vetoed(out).values, "Vetado: gate", ""),
        "recommended_count": n,
        "recommended": [i < n for i in range(len(out))],
    })


def drive_engine(P, reset: bool) -> tuple[pd.Series, dict]:
    cfg = dict(V9)
    idx = P.close.index
    st = E.new_state(1.0, str(idx[START].date()), cfg)
    recs = []
    expos, distincts, turnovers = [], [], []
    counts = dict(not_filled=0, write_offs=0, transfers=0, plans=0)
    prev_t = None
    etf = P.ETF
    irx = P.IRX
    c = dict(L.BASE)
    c.update(L.CONFIGS["T20"])
    for t in range(START, len(idx) - 6, STEP):
        today = str(idx[t].date())
        if st.get("pending") and prev_t is not None:
            e = prev_t + 1
            fills = E.settle(st, str(idx[e].date()), P.close.iloc[e], etf.iloc[e], cfg)
            counts["not_filled"] += sum(1 for f in fills if f.get("status") == "not_filled")
        rk = _ranking(P, t, c)
        if rk is None:
            prev_t = t
            continue
        tb = float(irx.iloc[t]) if t < len(irx) and pd.notna(irx.iloc[t]) else 0.0
        st, orders = E.plan(st, today, rk, P.close.iloc[: t + 1], etf.iloc[: t + 1], tb, cfg)
        if not reset:
            st["pending"] = [o for o in st.get("pending") or []
                             if not str(o.get("side", "")).startswith("transfer")]
        counts["plans"] += 1
        counts["transfers"] += sum(1 for o in (st.get("pending") or [])
                                   if str(o.get("side", "")).startswith("transfer"))
        traded = sum(float(o.get("dollars") or 0) for o in (st.get("pending") or [])
                     if o.get("side") in ("buy", "sell"))
        prev_t = t
        s = E.summary_table(st, P.close.iloc[t], etf.iloc[t], cfg)
        recs.append((idx[t], s["total"]))
        tot = s["total"] or 1.0
        expos.append(s["sleeves"]["stocks"]["exposure"] * 0.5 + s["sleeves"]["etf"]["exposure"] * 0.5)
        distincts.append(s["sleeves"]["stocks"]["distinct"] + s["sleeves"]["etf"]["distinct"])
        turnovers.append(traded / tot if tot else 0.0)
    counts["write_offs"] = len(st.get("write_offs") or [])
    counts["turnover"] = round(float(np.mean(turnovers) * 100), 1) if turnovers else 0.0
    counts["exposure"] = round(float(np.mean(expos) * 100), 0) if expos else 0.0
    counts["distinct"] = round(float(np.mean(distincts)), 1) if distincts else 0.0
    ser = pd.Series({d: v for d, v in recs}, dtype=float).sort_index()
    return ser, counts


def main():
    cache = os.path.join(HERE, "_sweep_cache", "close.pkl")
    if not os.path.exists(cache):
        print("SKIP: experiments/_sweep_cache/close.pkl missing")
        return 0
    print("loading in-sample panel...")
    P = L.load_panel(oos=False)
    P.ETF = S.load_etfs(P.close.index)
    print("  close", P.close.shape, "ETF", P.ETF.shape)

    print("lab T20 exec + ETF sleeve + mix equal...")
    t20 = L.run_exec(P, L.CONFIGS["T20"])
    etf = S.run_sleeve(P, {})
    mixed = S.mix([t20, etf], "equal")
    lab_val = (1 + mixed["net"]).cumprod()
    lab_val.index = mixed.index

    print("engine WITH 1/8 reset...")
    eng_on, c_on = drive_engine(P, reset=True)
    print("engine WITHOUT transfer reset...")
    eng_off, c_off = drive_engine(P, reset=False)

    common = lab_val.index.intersection(eng_on.index)
    lab_s = _stats(lab_val.reindex(common).dropna(), "lab mix T20+ETF equal")
    mix_c = mixed.reindex(common).dropna(how="all")
    if len(mix_c) and "turnover" in mix_c:
        lab_s["turnover"] = round(float(mix_c["turnover"].mean() * 100), 1)
        lab_s["exposure"] = round(float(mix_c["expo"].mean() * 100), 0) if "expo" in mix_c else None
    rows = [
        lab_s,
        {**_stats(eng_on, "engine 1/8 reset"), **c_on},
        {**_stats(eng_off, "engine no-transfer reset"), **c_off},
    ]
    print(pd.DataFrame(rows).to_string(index=False))
    os.makedirs(os.path.dirname(SCRATCH), exist_ok=True)
    with open(SCRATCH, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2, default=str)
    print("wrote", SCRATCH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
