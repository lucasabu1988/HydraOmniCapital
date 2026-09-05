"""
TASK-331 — T20 sensitivity around pre-specified knobs. Not tuning.

Axes (one at a time, others at the T20 base: vol 0.15, buffer 2, hold 20 / 4 tranches):
  target_vol in {0.12, 0.15, 0.18}
  buffer     in {1.5, 2.0, 3.0}
  (hold, K)  in {(20,4), (20,2), (30,6)}
Nine named rows; the three base cells share one run. DEV only. Do not pick a cell.
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import redesign_lab as L

SCRATCH = os.path.join(HERE, "_lab_scratch", "task331.json")


def _load():
    if os.path.exists(SCRATCH):
        with open(SCRATCH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(rows):
    os.makedirs(os.path.dirname(SCRATCH), exist_ok=True)
    with open(SCRATCH, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def _key(cfg):
    return json.dumps(
        {k: cfg[k] for k in ("target_vol", "buffer", "hold", "tranches") if k in cfg},
        sort_keys=True,
    )


def _run(P, label, cfg, rows):
    k = _key(cfg)
    if k in rows:
        rows[k]["label"] = label
        print("  skip", label, flush=True)
        return
    df = L.run_any(P, cfg)
    s = L.stats(df[df.index < L.SPLIT], L.step_of(cfg), label)
    s["cfg_key"] = k
    rows[k] = s
    _save(rows)
    print("  done", label, s, flush=True)


def main():
    P = L.load_panel(oos=True)
    print(f"panel {P.close.shape}  DEV < {L.SPLIT.date()}", flush=True)
    rows = _load()
    base = dict(L.CONFIGS["T20"])

    jobs = []
    for v in (0.12, 0.15, 0.18):
        c = dict(base); c["target_vol"] = v
        jobs.append((f"vol={v}", c))
    for b in (1.5, 2.0, 3.0):
        c = dict(base); c["buffer"] = b
        jobs.append((f"buffer={b}", c))
    for h, k in ((20, 4), (20, 2), (30, 6)):
        c = dict(base); c["hold"] = h; c["tranches"] = k
        jobs.append((f"hold={h}/K={k}", c))

    for label, cfg in jobs:
        _run(P, label, cfg, rows)

    table = []
    for label, cfg in jobs:
        s = dict(rows[_key(cfg)])
        s["label"] = label
        table.append(s)
    print("\nT20 DEV sensitivity (one axis at a time; do not pick a cell)")
    print(pd.DataFrame(table).to_string(index=False))

    def spread(prefix):
        nets = [r["ann_net"] for r in table if r["label"].startswith(prefix)]
        return max(nets) - min(nets), min(nets), max(nets)

    for axis, pref in (("target_vol", "vol="), ("buffer", "buffer="), ("hold/K", "hold=")):
        rng, lo, hi = spread(pref)
        print(f"ann_net spread {axis}: {rng:.2f} pp  [{lo:.2f}, {hi:.2f}]")


if __name__ == "__main__":
    main()
