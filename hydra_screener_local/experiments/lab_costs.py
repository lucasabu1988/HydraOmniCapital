"""
TASK-333 — size-aware costs on PROD, F1, T20.

Uses the lab's per-name `traded` weights. Flat 10 bp must reproduce the lab
ann_net to 2 decimals. A second pass adds +10 bp to every name (Russell stress).
TEST is allowed: no candidate is chosen, only re-priced. Does not edit
cost_model.py knots or the lab.
"""
from __future__ import annotations

import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import redesign_lab as L
from cost_model import cost_bp_per_side


def _reprice(P, df, *, curve="flat", flat_bp=10.0, extra_bp=0.0):
    nets = []
    for date, row in df.iterrows():
        t = P.close.index.get_loc(date)
        adv = P.ADV_USD.iloc[t]
        traded = row.get("traded") or {}
        cost = 0.0
        for name, dw in traded.items():
            try:
                a = float(adv.get(name, np.nan))
            except (TypeError, ValueError):
                a = np.nan
            bp = cost_bp_per_side(a, curve=curve, flat_bp=flat_bp) + extra_bp
            cost += float(dw) * bp / 10000.0
        nets.append(float(row["gross"]) - cost)
    out = df.copy()
    out["net_reprice"] = nets
    return out


def _ann_net(series, step):
    py = 252 / step
    r = series.dropna()
    return round(float((1 + r).prod() ** (py / len(r)) - 1) * 100, 2)


def _split_rows(P, name, df):
    step = L.step_of(L.CONFIGS[name])
    lab_net = {
        "DEV": _ann_net(df.loc[df.index < L.SPLIT, "net"], step),
        "TEST": _ann_net(df.loc[df.index >= L.SPLIT, "net"], step),
        "ALL": _ann_net(df["net"], step),
    }
    rows = []
    for extra, tag in ((0.0, "nv2016"), (10.0, "nv2016+10bp")):
        priced = _reprice(P, df, curve="nv2016", extra_bp=extra)
        flat = _reprice(P, df, curve="flat", flat_bp=10.0, extra_bp=0.0)
        for window, mask in (("DEV", df.index < L.SPLIT), ("TEST", df.index >= L.SPLIT), ("ALL", slice(None))):
            if window == "ALL":
                part_s, part_f = priced, flat
            else:
                part_s, part_f = priced.loc[mask], flat.loc[mask]
            rows.append(dict(
                config=name, window=window, curve=tag,
                ann_net_lab=lab_net[window],
                ann_net_flat10=_ann_net(part_f["net_reprice"], step),
                ann_net_sized=_ann_net(part_s["net_reprice"], step),
            ))
    return rows


def main():
    P = L.load_panel(oos=True)
    print(f"panel {P.close.shape}", flush=True)
    all_rows = []
    for name in ("PROD", "F1", "T20"):
        print("  running", name, flush=True)
        df = L.run_any(P, L.CONFIGS[name])
        # acceptance on ALL: flat 10 vs lab
        flat = _reprice(P, df, curve="flat", flat_bp=10.0)
        step = L.step_of(L.CONFIGS[name])
        lab = _ann_net(df["net"], step)
        got = _ann_net(flat["net_reprice"], step)
        print(f"    ALL lab {lab}  flat10 {got}  delta {abs(lab-got):.4f}", flush=True)
        all_rows.extend(_split_rows(P, name, df))
    print(pd.DataFrame(all_rows).to_string(index=False))


if __name__ == "__main__":
    main()
