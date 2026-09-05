"""
TASK-330 — is F1 a strategy or a phase?

F1 = buffer 2 + hold 10, rebalanced every 10 bars from start=280. The 12-7
analogue swung ~2 pp and hold-20 swung ~4.6 pp across phases, which is why
T20 exists. Measure F1 at start=280+k for k in 0..9 (DEV only) plus F1_ens
at k=0 and k=5.

Import redesign_lab; never edit it. TEST not read.
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

SCRATCH = os.path.join(HERE, "_lab_scratch", "task330.json")


def _load_scratch():
    if os.path.exists(SCRATCH):
        with open(SCRATCH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_scratch(rows):
    os.makedirs(os.path.dirname(SCRATCH), exist_ok=True)
    with open(SCRATCH, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def _run(P, name, cfg, start, rows):
    key = f"{name}|start={start}"
    if key in rows:
        print("  skip", key, flush=True)
        return
    df = L.run_any(P, cfg, start=start)
    dev = df[df.index < L.SPLIT]
    s = L.stats(dev, L.step_of(cfg), key)
    rows[key] = s
    _save_scratch(rows)
    print("  done", key, s, flush=True)


def main():
    P = L.load_panel(oos=True)
    print(f"panel {P.close.shape}  DEV < {L.SPLIT.date()}", flush=True)
    rows = _load_scratch()
    f1 = L.CONFIGS["F1"]
    for k in range(10):
        _run(P, "F1", f1, 280 + k, rows)
    ens = L.CONFIGS["F1_ens"]
    for k in (0, 5):
        _run(P, "F1_ens", ens, 280 + k, rows)

    f1_rows = [rows[f"F1|start={280 + k}"] for k in range(10)]
    nets = [r["ann_net"] for r in f1_rows]
    print("\nF1 DEV by phase (start=280+k, k=0..9)")
    print(pd.DataFrame(f1_rows).to_string(index=False))
    print(f"ann_net mean {sum(nets)/len(nets):.2f}  min {min(nets):.2f}  max {max(nets):.2f}  "
          f"range {max(nets)-min(nets):.2f} pp")
    print("\nF1_ens")
    print(pd.DataFrame([rows[f"F1_ens|start={280 + k}"] for k in (0, 5)]).to_string(index=False))
    rng = max(nets) - min(nets)
    if rng > 2.0:
        print(f"\nVERDICT: F1 is a PHASE, not a strategy (range {rng:.2f} pp net > 2). Option B is dead.")
    else:
        print(f"\nVERDICT: F1 range {rng:.2f} pp net <= 2; phase-robust enough that option B still exists.")


if __name__ == "__main__":
    main()
