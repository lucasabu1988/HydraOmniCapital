"""TASK-413: re-measure the two published REFERENCE rows with the corrected metric.

Until 2026-09-08 the README compared the engine against two baselines - the v8.4 screener alone
and SPY buy-and-hold - whose figures came from the 2026-09-06 audit and carried the old
"Sharpe" (really `mean/sd * sqrt(periods)` on the NET return, no risk-free leg). TASK-404 named
that quantity `net_vol_ratio` and added the real `sharpe_excess`; the engine and lab-mix rows
were recomputed, these two were not. This script recomputes them from data already on disk, so
`evidence_canonical.json` stops carrying `"sharpe_excess": null` and a note saying so.

Both rows live on the SAME mark grid, the index of the `PROD_cy` frame (1084 non-overlapping
5-bar steps, 2005-02-11 -> 2026-08-24), so the four published rows are comparable:

    screener v8.4 alone  = the `net` column of `_sweep_cache_etf/audit_steps.pkl['PROD_cy']`
    SPY buy-and-hold     = `_sweep_cache_oos/spy.pkl` (dividend-adjusted close) sampled on the
                           same marks, forward: the row dated t is spy[t+5]/spy[t] - 1

What it produced on 2026-09-08 (OOS S&P 500 PIT panel, `python experiments/reference_rows.py`):

    screener v8.4 alone   1084 cycles   ann  5.48 %   net/vol 0.42   Sharpe 0.31   maxDD -37.8 %
    SPY buy-and-hold      1084 cycles   ann 10.99 %   net/vol 0.69   Sharpe 0.59   maxDD -52.5 %
    T-bill over the panel 1.76 % annualised (the same level the engine row carries)

The v8.4 row reproduces the published 5.5 / 0.42 / -37.8 exactly - it IS the audit's own frame.

SPY only partly reproduces the published 11.0 / 0.68 / -54.7. The annual return does (10.99 vs
10.96) and the ratio rounds one tick higher (0.693 -> 0.69 vs the audit's 0.68), but the maxDD
does not: on this grid it is -52.5 %. Where -54.7 % comes from was measured, not guessed - a
5-bar grid starting 2004-01-05 (1140 marks) gives exactly -54.7 % ALL / -31.7 % TEST, the audit's
two drawdown figures, while its ALL return on that grid is 10.83 %. So the audit's SPY row was
built on a grid offset from the strategy rows despite being labelled "misma rejilla": the
drawdown came from one grid and the return from another. On the daily series over the same window
the drawdown is -55.19 % (trough 2009-03-09). The row published from here is the internally
consistent one: every figure from the 1084-mark PROD_cy grid, so the four published rows share a
calendar.

These are NOT the production universe (S&P 500 only, not the Russell-heavy live universe) and
NOT a track record. Early-sample price coverage of the PIT membership is partial (see the panel's
own caveat), so absolute levels at the start of the sample are thin - what these rows are for is
the comparison ON ONE GRID, not the level.
"""
from __future__ import annotations

import json
import os
import sys

import pandas as pd

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # TASK-380: cp1252 consoles

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import metrics  # noqa: E402

ETF_CACHE = os.path.join(HERE, "_sweep_cache_etf")
OOS_CACHE = os.path.join(HERE, "_sweep_cache_oos")
STEP = 5


def load_marks_and_rf():
    """The mark grid of the lab's PROD_cy frame, and the risk-free return of each 5-bar step.

    `irx.pkl` is the 13-week T-bill, annualised, in PERCENT; the lab divides by 100 and ffills it
    onto the price calendar (`load_panel`, the `P.IRX` line). `spy.pkl` carries that calendar - it
    is bar-for-bar the index of the OOS close panel (checked 2026-09-08), and loading 90 KB
    instead of the 55 MB panel keeps this script cheap.
    """
    steps = pd.read_pickle(os.path.join(ETF_CACHE, "audit_steps.pkl"))
    marks = steps["PROD_cy"].index
    spy = pd.read_pickle(os.path.join(OOS_CACHE, "spy.pkl"))
    cal = spy.index
    irx = pd.read_pickle(os.path.join(OOS_CACHE, "irx.pkl"))
    rate = irx.reindex(cal).ffill().fillna(0.0) / 100.0
    rf = metrics.step_risk_free(rate, marks, forward=True, step=STEP)
    return steps, spy, cal, marks, rf


def v84_row(steps, rf) -> dict:
    """The screener v8.4 alone: the audit's own net steps, no ETF sleeve. Not re-simulated.

    The column guard is not decoration. During the TASK-413 review this measurement came back as
    9.72 % three times in ~21 runs - which is exactly this frame's GROSS annualised return, i.e.
    the wrong column read while another process was rewriting a 55 MB pickle in the same
    directory. The mechanism was never reproduced, so the code now refuses to publish a row it
    cannot prove is the net one: gross and net must both be present and must differ.
    """
    frame = steps["PROD_cy"]
    for col in ("net", "gross"):
        if col not in frame.columns:
            raise ValueError(f"PROD_cy has no {col!r} column: refusing to publish a baseline")
    if bool((frame["net"] - frame["gross"]).abs().max() < 1e-12):
        raise ValueError("PROD_cy net and gross are identical: the frame is not what this "
                         "measurement assumes (net is after costs)")
    return metrics.stats(frame["net"], "screener v8.4 alone (T5, no ETF sleeve)",
                         step=STEP, rf=rf)


def spy_row(spy, cal, marks, rf) -> dict:
    """SPY buy-and-hold sampled on the lab's forward convention: the row dated t covers t -> t+5.

    Not a daily series: the maxDD below is the worst 5-bar-marked peak-to-trough, which is NOT
    the daily maxDD the 2026-09-06 audit quoted (-54.7 %).
    """
    px = spy["SPY"].astype(float)
    pos = cal.get_indexer(marks)
    if (pos < 0).any():
        raise ValueError("a mark is not a bar of the SPY calendar")
    out = {}
    for m, p in zip(marks, pos):
        end = p + STEP
        if end >= len(cal):
            continue
        out[m] = float(px.iloc[end] / px.iloc[p] - 1.0)
    r = pd.Series(out, dtype=float).sort_index()
    return metrics.stats(r, "SPY buy-and-hold", step=STEP, rf=rf)


def measure() -> dict:
    steps, spy, cal, marks, rf = load_marks_and_rf()
    return {
        "measured_at": "2026-09-08",
        "panel": "S&P 500 point-in-time panel with delistings (OOS)",
        "first_mark": str(marks[0].date()),
        "last_mark": str(marks[-1].date()),
        "step": STEP,
        "forward": True,
        "rows": [v84_row(steps, rf), spy_row(spy, cal, marks, rf)],
    }


def main(argv=None) -> int:
    payload = measure()
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
