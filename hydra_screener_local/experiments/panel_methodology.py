"""TASK-338 — data & methodology sheet for the PIT panel, per variant.

Executable `run_any(P, cfg)` for PROD and T20 on the OOS panel. No new configs, no
tuning. Does not edit redesign_lab.py.

Usage:
    python experiments/panel_methodology.py
"""
from __future__ import annotations

import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from collections import defaultdict

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import redesign_lab as L
from data.universe import (
    membership_as_of,
    yahoo_membership_as_of,
    pit_yahoo_symbol,
    fetch_sp500_pit_payload,
)

SCRATCH = os.path.join(HERE, "_lab_scratch", "task338.json")
SPOTS = [
    "2005-06-30", "2008-09-15", "2011-06-30", "2014-06-30",
    "2017-06-30", "2020-06-30", "2023-06-30",
]


def _year_end_bars(idx):
    years = {}
    for ts in idx:
        years[int(ts.year)] = ts
    return years


def _coverage_row(P, payload, as_of):
    raw = membership_as_of(as_of, payload)
    mapped = yahoo_membership_as_of(as_of, payload)
    blocked = sum(1 for t in raw if pit_yahoo_symbol(t, payload) is None)
    idx = P.close.index[P.close.index <= pd.Timestamp(as_of)]
    if len(idx) == 0:
        return dict(as_of=as_of, raw=len(raw), mapped=len(mapped), blocked=blocked,
                    with_px=0, pct=None)
    day = P.close.loc[idx[-1]]
    n_px = sum(1 for t in mapped if t in day.index and pd.notna(day[t]))
    return dict(as_of=str(idx[-1].date()), requested=as_of, raw=len(raw),
                mapped=len(mapped), blocked=blocked, with_px=n_px,
                pct=round(100.0 * n_px / max(len(raw), 1), 1))


def _membership_windows(payload):
    """First and last snapshot date each yahoo symbol (and each raw name) appears."""
    snaps = payload.get("snapshots") or {}
    first, last = {}, {}
    raw_first, raw_last = {}, {}
    for d in sorted(snaps):
        ts = pd.Timestamp(d)
        for raw in snaps[d]:
            raw_first.setdefault(raw, ts)
            raw_last[raw] = ts
            y = pit_yahoo_symbol(raw, payload)
            if not y:
                continue
            first.setdefault(y, ts)
            last[y] = ts
    return first, last, raw_first, raw_last


def _series_span(close):
    first, last = {}, {}
    for col in close.columns:
        s = close[col].dropna()
        if s.empty:
            continue
        first[col] = s.index[0]
        last[col] = s.index[-1]
    return first, last


def _traded_names(row):
    traded = row.get("traded") or {}
    if isinstance(traded, float) and pd.isna(traded):
        return {}
    return {str(k): float(v) for k, v in dict(traded).items() if float(v) > 0}


def _analyse_book(name, df, P, first_px, last_px, first_mem, last_mem):
    panel_end = P.close.index[-1]
    doomed = {t for t, ts in last_px.items() if ts < panel_end}
    panel_start = P.close.index[0]
    late_start = []          # joined during the sample, Yahoo starts after the join
    after_window = []        # Yahoo starts after they left the index (reuse)
    left_censored = []       # member before the 2004 panel start
    for t, fp in first_px.items():
        fm = first_mem.get(t)
        lm = last_mem.get(t)
        if fm is not None and fm < panel_start:
            left_censored.append(t)
        if fm is not None and fm >= panel_start and fp > fm + pd.Timedelta(days=5):
            late_start.append(t)
        if lm is not None and fp > lm:
            after_window.append(t)
    late_start, after_window = set(late_start), set(after_window)
    left_censored = set(left_censored)

    by_year = []
    years = sorted({int(ts.year) for ts in df.index})
    for y in years:
        sub = df[df.index.year == y]
        w_all = w_doom = w_late = w_after = w_left = 0.0
        names = set()
        doom_n, late_n, after_n, left_n = set(), set(), set(), set()
        for _, row in sub.iterrows():
            traded = _traded_names(row)
            for t, w in traded.items():
                names.add(t)
                w_all += w
                if t in doomed:
                    w_doom += w
                    doom_n.add(t)
                if t in late_start:
                    w_late += w
                    late_n.add(t)
                if t in after_window:
                    w_after += w
                    after_n.add(t)
                if t in left_censored:
                    w_left += w
                    left_n.add(t)
        by_year.append(dict(
            year=y, steps=int(len(sub)),
            names_traded=len(names),
            doomed_names=len(doom_n),
            doomed_traded_share=round(w_doom / w_all, 4) if w_all else 0.0,
            late_start_names=len(late_n),
            late_start_traded_share=round(w_late / w_all, 4) if w_all else 0.0,
            after_window_names=len(after_n),
            after_window_traded_share=round(w_after / w_all, 4) if w_all else 0.0,
            left_censored_names=len(left_n),
            left_censored_traded_share=round(w_left / w_all, 4) if w_all else 0.0,
        ))

    offs = list(df.attrs.get("write_offs") or [])
    off_rows = []
    for o in offs:
        step = int(o["step"])
        date = str(df.index[step].date()) if 0 <= step < len(df) else None
        tk = o["ticker"]
        off_rows.append(dict(
            date=date, step=step, tranche=o.get("tranche"), ticker=tk,
            proceeds=round(float(o["proceeds"]), 6),
            last_px_date=str(last_px[tk].date()) if tk in last_px else None,
            first_px_date=str(first_px[tk].date()) if tk in first_px else None,
        ))

    # sensitivity: write-off at 0 instead of last price
    nets = df["net"].astype(float).copy()
    v = (1.0 + nets).cumprod()
    # v_pre for step i is the book value at the start; df['value'] is v_x.
    # proceeds were added at the end, so at-0 net_i' = net_i - proceeds / v_pre
    # v_pre = value / (1+net) when net != -1
    delta = 0.0
    for o in offs:
        step = int(o["step"])
        if not (0 <= step < len(df)):
            continue
        net = float(nets.iloc[step])
        vx = float(df["value"].iloc[step]) if "value" in df.columns else float("nan")
        v_pre = vx / (1.0 + net) if np.isfinite(vx) and net != -1 else float("nan")
        proceeds = float(o["proceeds"])
        if v_pre and np.isfinite(v_pre) and v_pre > 0:
            nets.iloc[step] = net - proceeds / v_pre
            delta += proceeds
    py = 252.0 / L.step_of(L.CONFIGS[name])
    def ann(r):
        r = r.dropna()
        return float(((1 + r).prod() ** (py / len(r)) - 1) * 100) if len(r) else 0.0
    return dict(
        config=name,
        cycles=int(len(df)),
        trades=int(df.attrs.get("trades") or 0),
        write_offs=off_rows,
        write_off_proceeds=round(sum(float(o["proceeds"]) for o in offs), 6),
        write_off_at_0_proceeds=0.0,
        write_off_at_0_lost_book=round(delta, 6),
        ann_net=round(ann(df["net"].astype(float)), 2),
        ann_net_writeoff_at_0=round(ann(nets), 2),
        doomed_tickers_ever=sorted(doomed),
        late_start_ever=sorted(late_start),
        after_window_ever=sorted(after_window),
        left_censored_ever=sorted(left_censored),
        by_year=by_year,
        stats_all=L.stats(df, L.step_of(L.CONFIGS[name]), name),
    )


def main():
    os.makedirs(os.path.dirname(SCRATCH), exist_ok=True)
    print("loading OOS panel...")
    P = L.load_panel(oos=True)
    payload = P.pit_payload or fetch_sp500_pit_payload()
    print(f"  close {P.close.index[0].date()} -> {P.close.index[-1].date()}  "
          f"{P.close.shape[1]} cols, {len(P.close)} bars")

    coverage_spots = [_coverage_row(P, payload, s) for s in SPOTS]
    coverage_years = []
    for y, ts in _year_end_bars(P.close.index).items():
        row = _coverage_row(P, payload, ts.strftime("%Y-%m-%d"))
        row["year"] = y
        coverage_years.append(row)

    first_mem, last_mem, _, _ = _membership_windows(payload)
    first_px, last_px = _series_span(P.close)

    variants = {}
    for name in ("PROD", "T20"):
        print(f"running {name} executable...")
        df = L.run_any(P, L.CONFIGS[name])
        traded_all = set()
        for _, row in df.iterrows():
            traded_all.update(_traded_names(row))
        v = _analyse_book(name, df, P, first_px, last_px, first_mem, last_mem)
        v["doomed_tickers_traded"] = sorted(t for t in v["doomed_tickers_ever"] if t in traded_all)
        v["late_start_traded"] = sorted(t for t in v["late_start_ever"] if t in traded_all)
        v["after_window_traded"] = sorted(t for t in v["after_window_ever"] if t in traded_all)
        v["left_censored_traded"] = sorted(t for t in v["left_censored_ever"] if t in traded_all)
        del v["doomed_tickers_ever"]
        del v["late_start_ever"]
        del v["after_window_ever"]
        del v["left_censored_ever"]
        variants[name] = v
        print(f"  {name}: cycles={v['cycles']} trades={v['trades']} "
              f"write_offs={len(v['write_offs'])} proceeds={v['write_off_proceeds']} "
              f"ann_net={v['ann_net']}")

    out = dict(
        panel=dict(
            start=str(P.close.index[0].date()),
            end=str(P.close.index[-1].date()),
            bars=int(len(P.close)),
            tickers=int(P.close.shape[1]),
            auto_adjust=True,
        ),
        coverage_spots=coverage_spots,
        coverage_years=coverage_years,
        variants=variants,
    )
    with open(SCRATCH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"wrote {SCRATCH}")

    print("\nPRICE COVERAGE (year-end)")
    print(f"{'year':<6} {'raw':>5} {'mapped':>7} {'blocked':>8} {'with_px':>8} {'pct':>6}")
    for r in coverage_years:
        print(f"{r['year']:<6} {r['raw']:5d} {r['mapped']:7d} {r['blocked']:8d} "
              f"{r['with_px']:8d} {r['pct']:5.1f}%")
    for name, v in variants.items():
        print(f"\n{name} write-offs: {v['write_offs']}")
        print(f"{name} by year (doomed_share / late_start / after_window):")
        for r in v["by_year"]:
            print(f"  {r['year']} traded={r['names_traded']:4d}  "
                  f"doomed={r['doomed_traded_share']:.3f} ({r['doomed_names']})  "
                  f"late={r['late_start_traded_share']:.3f} ({r['late_start_names']})  "
                  f"after={r['after_window_traded_share']:.3f} ({r['after_window_names']})")


if __name__ == "__main__":
    main()
