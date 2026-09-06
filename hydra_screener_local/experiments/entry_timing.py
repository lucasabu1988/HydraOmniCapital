"""
TASK-328 — first executable price: D+1 open vs D+1 close vs D+2 open.

Signal is known at the close of D. Production / tracking v2 / the harness
enter at the close of D+1 (lag=1) and exit five bars later. Nobody has
measured the OPEN of D+1. This downloads Open for the OOS panel (same
tickers, same window, yfinance auto_adjust=True) and reports gross + net
by era. Does not tune; does not edit the harness.
"""
from __future__ import annotations

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
ERAS = (
    ("2004-2012", "2004-01-01", "2012-12-31"),
    ("2013-2019", "2013-01-01", "2019-12-31"),
    ("2020-2026", "2020-01-01", "2026-12-31"),
    ("full", "2004-01-01", "2026-12-31"),
)


def _download_open(tickers, start="2004-01-01"):
    import yfinance as yf
    path = os.path.join(OOS_CACHE, "open.pkl")
    existing = pd.read_pickle(path) if os.path.exists(path) else None
    have = set(existing.columns) if existing is not None else set()
    need = [t for t in tickers if t not in have]
    print(f"open cache has {len(have)}; downloading {len(need)}")
    if not need:
        return existing
    parts = []
    for i in range(0, len(need), 60):
        chunk = need[i:i + 60]
        d = yf.download(chunk, start=start, progress=False, auto_adjust=True, threads=True)
        if d is None or d.empty:
            continue
        o = d["Open"] if "Open" in d else d
        if isinstance(o, pd.Series):
            o = o.to_frame(chunk[0])
        parts.append(o)
        print(f"  {min(i + 60, len(need))}/{len(need)}", flush=True)
    if not parts:
        return existing
    fresh = pd.concat(parts, axis=1).sort_index()
    fresh = fresh.loc[:, ~fresh.columns.duplicated()]
    open_px = pd.concat([existing, fresh], axis=1) if existing is not None else fresh
    open_px = open_px.loc[:, ~open_px.columns.duplicated()].sort_index()
    os.makedirs(OOS_CACHE, exist_ok=True)
    open_px.to_pickle(path)
    print("saved open", open_px.shape)
    return open_px


def _replay_sels(P, start=260, step=5, hold=5, lag=1):
    import backtest_variant_sweep as sweep
    c = dict(sweep.DEFAULTS)
    idx, prev = P.close.index, set()
    rows = []
    for t in range(start, len(idx) - hold - lag - 2, step):
        out, _tk = sweep.score_day(P, t, c)
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
        turnover = len(cur - prev) / max(len(cur), 1) if cur else 0.0
        rows.append(dict(t=t, date=idx[t], names=list(sel.index), turnover=turnover, n=len(sel)))
        prev = cur
    return rows


def _cycle_return(entry, exit_, names):
    if not names:
        return 0.0
    common = [n for n in names if n in entry.index and n in exit_.index
              and pd.notna(entry[n]) and pd.notna(exit_[n]) and float(entry[n]) != 0]
    if not common:
        return 0.0
    return float((exit_[common] / entry[common] - 1).mean())


def _stats(rets, turnovers, cost_bp):
    r = pd.Series(rets)
    if r.empty:
        return {}
    net = r - (2.0 * cost_bp / 10000.0) * pd.Series(turnovers)
    return dict(
        cycles=len(r),
        mean_bp=round(r.mean() * 10000, 1),
        net_bp=round(net.mean() * 10000, 1),
        ann_pct=round(((1 + r).prod() ** (CYCLES_PER_YEAR / len(r)) - 1) * 100, 2),
        ann_net_pct=round(((1 + net).prod() ** (CYCLES_PER_YEAR / len(net)) - 1) * 100, 2),
        sharpe=round(r.mean() / r.std() * np.sqrt(CYCLES_PER_YEAR), 2) if r.std() else 0.0,
    )


def measure(P, open_px, cost_bp=10):
    close, open_px = P.close.align(open_px, join="inner", axis=0)
    open_px = open_px.reindex(columns=close.columns)
    P.close, P.volume = close, P.volume.reindex(close.index)
    rows = _replay_sels(P)
    variants = {
        "D+1 close (production)": [],
        "D+1 open": [],
        "D+2 open": [],
    }
    turns = {k: [] for k in variants}
    dates = []
    idx = P.close.index
    for row in rows:
        t = row["t"]
        names = row["names"]
        if t + 7 >= len(idx):
            continue
        dates.append(idx[t])
        # D+1 close -> close[t+1+5] / close[t+1]   (harness lag=1 hold=5)
        variants["D+1 close (production)"].append(
            _cycle_return(P.close.iloc[t + 1], P.close.iloc[t + 1 + 5], names))
        variants["D+1 open"].append(
            _cycle_return(open_px.iloc[t + 1], P.close.iloc[t + 1 + 5], names))
        variants["D+2 open"].append(
            _cycle_return(open_px.iloc[t + 2], P.close.iloc[t + 2 + 5], names))
        for k in variants:
            turns[k].append(row["turnover"])
    dates = pd.DatetimeIndex(dates)
    out = []
    for era, lo, hi in ERAS:
        mask = (dates >= lo) & (dates <= hi)
        for name, rets in variants.items():
            r = [x for x, m in zip(rets, mask) if m]
            to = [x for x, m in zip(turns[name], mask) if m]
            s = _stats(r, to, cost_bp)
            s.update(era=era, entry=name)
            out.append(s)
    return pd.DataFrame(out)


def main():
    import backtest_variant_sweep as sweep
    from config import COST_BP_PER_SIDE
    from data.universe import fetch_sp500_pit_payload

    close_path = os.path.join(OOS_CACHE, "close.pkl")
    if not os.path.exists(close_path):
        sys.exit(f"no OOS cache at {OOS_CACHE}")
    close = pd.read_pickle(close_path)
    open_px = _download_open(list(close.columns), start="2004-01-01")
    payload = fetch_sp500_pit_payload()
    P = sweep.Panels(cache_dir=OOS_CACHE, pit_payload=payload)
    df = measure(P, open_px, cost_bp=COST_BP_PER_SIDE)
    print(df.to_string(index=False))
    return df


if __name__ == "__main__":
    main()
