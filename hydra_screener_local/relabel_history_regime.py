#!/usr/bin/env python
"""
Bring history/*.json written before schema v2 up to date (audit 2026-09-06, finding T3).

Until TASK-315 (2026-09-05) screener.py persisted `regime.score` from `compute_regime_score`
- the simple 0.7*trend + 0.3*mom20 formula - while scoring used `compute_rich_regime_scores`.
Same day, same SPY: 0.793 stored vs 0.693 actually used. `regime.type` and `special_modes`
were already the rich ones (they came from the scored candidates), so only the SCORE is wrong.

This script recomputes the rich score for each v1 file from SPY as of the bar that was
scored. One caveat, stated in the file it writes: the rich regime's breadth sub-score (weight
0.10) needs the whole universe panel of that day, which history never stored. Breadth is
therefore assumed 0.5, so the relabelled score is exact on 90% of its weight and within
+-0.05 of the true value. That is still the right formula; the old number was the wrong one.

Nothing is lost: the original block is kept under `regime_legacy`.

Usage:
    python relabel_history_regime.py --dry-run
    python relabel_history_regime.py
    python relabel_history_regime.py --history-dir path/to/history
"""
import argparse
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import MIN_REGIME_SCORE
from core.history import HISTORY_DIR, HISTORY_SCHEMA_VERSION
from core.regime import compute_rich_regime_scores

RELABELLED_SOURCE = "rich_relabelled_no_breadth"


def signal_date_of(run: dict) -> pd.Timestamp:
    return pd.Timestamp(run.get("data_last_bar") or datetime.strptime(run["date"], "%Y%m%d"))


def relabel_run(run: dict, spy: pd.Series):
    """Return (new_run, changed). Pure: no I/O, so it is testable with a synthetic SPY."""
    if run.get("regime_source"):
        return run, False                       # already v2 (written by the fixed screener)

    s = spy[spy.index.normalize() <= signal_date_of(run)]
    if len(s) < 200:
        out = dict(run)
        out["regime_source"] = "unrelabelled_insufficient_spy"
        return out, True

    # prices=None -> breadth defaults to 0.5: the universe panel of that day was never stored.
    rr = compute_rich_regime_scores(s, None)
    old = run.get("regime", {}) or {}

    out = dict(run)
    out["regime_legacy"] = old
    out["regime"] = {
        **old,
        "score": rr.overall,
        "gate_blocked": bool(rr.overall < MIN_REGIME_SCORE * 0.85),
        "breadth_assumed": 0.5,
        "score_legacy": old.get("score"),
    }
    out["regime_gate_blocked"] = out["regime"]["gate_blocked"]
    out["regime_source"] = RELABELLED_SOURCE
    out["schema_version"] = HISTORY_SCHEMA_VERSION
    return out, True


def download_spy(first_date: datetime) -> pd.Series:
    import yfinance as yf
    start = (first_date - timedelta(days=400)).strftime("%Y-%m-%d")     # 200 bars + margin
    spy = yf.download("SPY", start=start, progress=False, auto_adjust=True)["Close"]
    if isinstance(spy, pd.DataFrame):
        spy = spy.iloc[:, 0]
    return spy.dropna()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", default=HISTORY_DIR)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    files = sorted(f for f in os.listdir(a.history_dir) if f.endswith(".json")) if os.path.isdir(a.history_dir) else []
    if not files:
        print(f"No history JSON in {a.history_dir}")
        return 0

    runs = {}
    for f in files:
        with open(os.path.join(a.history_dir, f), encoding="utf-8") as fh:
            runs[f] = json.load(fh)
    todo = [f for f, r in runs.items() if not r.get("regime_source")]
    print(f"{len(files)} history files, {len(todo)} without a regime_source (v1)")
    if not todo:
        return 0

    first = min(signal_date_of(runs[f]) for f in todo)
    spy = download_spy(first.to_pydatetime())

    changed = 0
    for f in todo:
        new, did = relabel_run(runs[f], spy)
        if not did:
            continue
        changed += 1
        old_s = (runs[f].get("regime") or {}).get("score")
        new_s = new["regime"].get("score")
        print(f"  {f}: score {old_s} -> {new_s}  [{new['regime_source']}]")
        if not a.dry_run:
            with open(os.path.join(a.history_dir, f), "w", encoding="utf-8") as fh:
                json.dump(new, fh, indent=2, ensure_ascii=False)
    print(f"{'Would relabel' if a.dry_run else 'Relabelled'} {changed} files. "
          f"Originals kept under 'regime_legacy'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
