"""TASK-381 — persist the OOS 50/50 mix cone as tracked JSON.

    python experiments/build_cone.py

Reads experiments/_sweep_cache_etf/audit_steps.pkl P_5050.net when present
(the published mix). If missing, rebuilds via sleeve_lab.mix(T20, ETF) on the
PIT panel. Writes data/oos_cone_5050.json.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

PICKLE = os.path.join(HERE, "_sweep_cache_etf", "audit_steps.pkl")
OUT = os.path.join(ROOT, "data", "oos_cone_5050.json")
MAX_H = 52
RECIPE = "sleeve_lab.mix([run_exec(T20), run_sleeve(ETF)], equal) on PIT _sweep_cache_oos"


def horizons(net: np.ndarray, max_h: int = MAX_H) -> dict:
    r = np.asarray(net, dtype=float)
    r = r[np.isfinite(r)]
    out = {}
    for h in range(1, max_h + 1):
        if len(r) < h:
            break
        windows = np.array([(1.0 + r[i:i + h]).prod() - 1.0 for i in range(len(r) - h + 1)])
        qs = np.percentile(windows, [5, 25, 50, 75, 95])
        out[str(h)] = dict(
            n_windows=int(len(windows)),
            p5=round(float(qs[0]) * 100, 2),
            p25=round(float(qs[1]) * 100, 2),
            p50=round(float(qs[2]) * 100, 2),
            p75=round(float(qs[3]) * 100, 2),
            p95=round(float(qs[4]) * 100, 2),
        )
    return out


def _from_pickle(path: str) -> tuple[np.ndarray, str, str]:
    blob = pd.read_pickle(path)
    mix = blob["P_5050"]
    net = mix["net"].dropna()
    first = str(pd.Timestamp(net.index[0]).date())
    last = str(pd.Timestamp(net.index[-1]).date())
    return net.to_numpy(dtype=float), first, last


def _from_lab() -> tuple[np.ndarray, str, str]:
    import redesign_lab as L
    import sleeve_lab as S
    P = L.load_panel(oos=True)
    P.ETF = S.load_etfs(P.close.index)
    t20 = L.run_exec(P, L.CONFIGS["T20"])
    etf = S.run_sleeve(P, {})
    mixed = S.mix([t20, etf], "equal")
    net = mixed["net"].dropna()
    return net.to_numpy(dtype=float), str(net.index[0].date()), str(net.index[-1].date())


def build(net: np.ndarray, *, first: str | None = None, last: str | None = None,
          source: str = "audit_steps.pkl P_5050") -> dict:
    r = np.asarray(net, dtype=float)
    r = r[np.isfinite(r)]
    return dict(
        panel="PIT 2004-2026",
        generated=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        n_steps=int(len(r)),
        first=first,
        last=last,
        recipe=RECIPE,
        source=source,
        horizons=horizons(r),
        step_returns=[round(float(x), 10) for x in r],
    )


def main() -> int:
    if os.path.exists(PICKLE):
        net, first, last = _from_pickle(PICKLE)
        source = "audit_steps.pkl P_5050"
        print(f"loaded pickle {len(net)} steps {first} -> {last}", flush=True)
    else:
        print("pickle missing; rebuilding from lab PIT panel...", flush=True)
        net, first, last = _from_lab()
        source = "lab rebuild"
        print(f"lab mix {len(net)} steps {first} -> {last}", flush=True)
    payload = build(net, first=first, last=last, source=source)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    h = payload["horizons"]
    print("wrote", OUT, "bytes", os.path.getsize(OUT), flush=True)
    for k in ("4", "13", "26", "52"):
        rec = h.get(k, {})
        print(f"  h={k} p5={rec.get('p5')} p50={rec.get('p50')} p95={rec.get('p95')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
