#!/usr/bin/env python
"""ASTRA-06: what the point-in-time breadth universe changes on the OOS panel.

Before the fix, `meta_fast` computed the regime over EVERY column of the lab panel — the union of
every S&P member 2004-2026, including names that were not members at t and columns with no
observation at all. core.regime counts those columns (a NaN is False against its own SMA and
still sits in the denominator), so the future universe was setting the historical regime, hence
aggression, hence dynamic_count, hence the size of the recommended list.

This script quantifies the difference on the point-in-time panel, date by date: regime, breadth
sub-score, dynamic count, and whether the selected list changes. Read-only; it runs no
production CLI and writes only the CSV you ask for.

    python experiments/astra06_breadth_delta.py                       # repo-local caches
    python experiments/astra06_breadth_delta.py --cache-dir <dir> --payload <sp500_pit.json> \
        --pit-dir <data_cache/pit> --csv out.csv

Every number it prints is S&P 500 only, and the 2004-2026 PIT panel has real membership but
~53% price coverage in 2005 — do not quote absolute levels from it without that caveat.
"""
import argparse
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

import redesign_lab as L  # noqa: E402
from config import MIN_REGIME_SCORE  # noqa: E402
from core.regime import compute_rich_regime_scores  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache-dir', default=None, help='panel cache (default experiments/_sweep_cache_oos)')
    ap.add_argument('--payload', default=None, help='sp500_pit.json (default: data_cache/, else fetched)')
    ap.add_argument('--pit-dir', default=None, help='PIT snapshots dir for the sector map')
    ap.add_argument('--start', type=int, default=280)
    ap.add_argument('--step', type=int, default=5, help='rebalance schedule (PROD and T20 are both 5)')
    ap.add_argument('--config', default='PROD')
    ap.add_argument('--csv', default=None)
    a = ap.parse_args()

    payload = json.load(open(a.payload, encoding='utf-8')) if a.payload else None
    P = L.load_panel(oos=True, cache_dir=a.cache_dir, payload=payload,
                     sectors='pit', sectors_date=None, pit_dir=a.pit_dir)
    print(f'panel {P.close.shape}  {P.close.index[0].date()} .. {P.close.index[-1].date()}', flush=True)

    c = dict(L.BASE); c.update(L.CONFIGS[a.config])
    idx = P.close.index
    rows = []
    for t in range(a.start, len(idx) - 7, a.step):
        out = L.rank_day(P, t, c)
        if out is None:
            continue
        lo = max(0, t - 300)
        s = P.spy.iloc[lo:t + 1]
        univ = L.breadth_universe(P, t, c)
        rr_new = compute_rich_regime_scores(s, P.close.loc[:, univ].iloc[lo:t + 1])
        rr_old = compute_rich_regime_scores(s, P.close.iloc[lo:t + 1])        # the pre-fix frame

        cur = float(s.iloc[-1]); mx = float(s.rolling(60).max().iloc[-1])
        vl = float(s.pct_change(fill_method=None).rolling(20).std().iloc[-1] * np.sqrt(252))

        def meta(rr):
            return P.meta.compute_adjustment(
                regime_score=rr.overall, recent_drawdown=max(0.0, (mx - cur) / mx),
                spy_20d_return=cur / float(s.iloc[-20]) - 1, spy_60d_return=cur / float(s.iloc[-60]) - 1,
                volatility_level=min(max(vl / 0.25, 0.3), 0.9))

        def count(m):
            return max(6, min(int(round(14 * m.overall_aggression * m.pillar_multipliers['COMPASS'])), 28))

        n_new, n_old = count(meta(rr_new)), count(meta(rr_old))
        # held is empty on both sides: the difference measured is the one the regime causes, not
        # the path. buffer 1.0 (PROD) makes the buffer irrelevant as well.
        sel_new = list(L.select(out, n_new, set(), 1.0).index)
        sel_old = list(L.select(out, n_old, set(), 1.0).index)
        rows.append(dict(date=idx[t], cols_univ=len(univ), reg_old=rr_old.overall, reg_new=rr_new.overall,
                         br_old=rr_old.breadth_proxy, br_new=rr_new.breadth_proxy, n_old=n_old, n_new=n_new,
                         same_list=sel_old == sel_new,
                         added=len(set(sel_new) - set(sel_old)), removed=len(set(sel_old) - set(sel_new))))
        if len(rows) % 100 == 0:
            print('  ...', len(rows), idx[t].date(), flush=True)

    d = pd.DataFrame(rows).set_index('date')
    if a.csv:
        d.to_csv(a.csv)
    delta = d['reg_new'] - d['reg_old']
    gate = MIN_REGIME_SCORE * 0.85
    print(f'\n=== ASTRA-06, config {a.config}, {len(d)} dates ({d.index[0].date()} .. {d.index[-1].date()}) ===')
    print(f'panel columns {P.close.shape[1]}  ->  breadth universe min/median/max '
          f'{d.cols_univ.min()}/{int(d.cols_univ.median())}/{d.cols_univ.max()}')
    print(f'regime differs        {int((delta != 0).sum())} dates ({(delta != 0).mean() * 100:.1f}%)  '
          f'mean {delta.mean():+.4f}  mean|d| {delta.abs().mean():.4f}  max|d| {delta.abs().max():.4f}  '
          f'p95|d| {delta.abs().quantile(.95):.4f}')
    print(f'  new higher/lower    {int((delta > 0).sum())}/{int((delta < 0).sum())}   '
          f'breadth sub-score mean old {d.br_old.mean():.4f} -> new {d.br_new.mean():.4f}')
    print(f'dynamic count differs {int((d.n_old != d.n_new).sum())} dates '
          f'({(d.n_old != d.n_new).mean() * 100:.1f}%)  mean n {d.n_old.mean():.2f} -> {d.n_new.mean():.2f}')
    print(f'  delta distribution  {(d.n_new - d.n_old).value_counts().sort_index().to_dict()}')
    print(f'order list differs    {int((~d.same_list).sum())} dates ({(~d.same_list).mean() * 100:.1f}%)  '
          f'mean names in/out on a changed date {d.loc[~d.same_list, "added"].mean():.2f}/'
          f'{d.loc[~d.same_list, "removed"].mean():.2f}')
    print(f'regime gate flips     {int(((d.reg_old >= gate) != (d.reg_new >= gate)).sum())} dates (threshold {gate:.4f})')
    era = d.assign(ad=delta.abs(), diff=~d.same_list).groupby(d.index.year).agg(
        dates=('n_old', 'size'), mean_abs_delta=('ad', 'mean'), list_diff_share=('diff', 'mean'),
        univ=('cols_univ', 'median'), n_old=('n_old', 'mean'), n_new=('n_new', 'mean'))
    print('\nby year:')
    print(era.round(4).to_string())


if __name__ == '__main__':
    main()
