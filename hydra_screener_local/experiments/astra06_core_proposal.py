#!/usr/bin/env python
"""ASTRA-06 follow-up: what the PROPOSED core/regime.py breadth patch would change.

`core/regime.py` is NOT modified by this script or by the branch that carries it. Its treatment of
missing data is GROKBOARD rule 6 (Lucas's explicit approval), so the patch is a proposal with
numbers attached: .comms/claude-astra06-core-proposal-2026-09-07.md, hypothesis H-007.

HOW THE PROPOSED BEHAVIOUR IS MEASURED WITHOUT PATCHING CORE
------------------------------------------------------------
The proposal is: a column enters the breadth statistics only when all three comparisons are
DEFINED for it on the date -- it has a close at t, a return at t, a 50-bar SMA and a 200-bar SMA --
and the ">30 columns" guard counts those columns, not the frame's width.

Every breadth statistic core computes is a column-wise mean over the last row of a per-column
rolling quantity:

    ret_1d      = prices.pct_change().iloc[-1]                 (per column)
    above_sma50 = prices.iloc[-1] > prices.rolling(50).mean().iloc[-1]     (per column)
    above_sma200= prices.iloc[-1] > prices.rolling(200).mean().iloc[-1]    (per column)
    breadth     = 0.3*mean(ret_1d > 0) + 0.3*mean(above_sma50) + 0.4*mean(above_sma200)

Nothing there mixes columns, so restricting the frame to a subset of columns BEFORE the call gives
exactly what the patched function would return on the full frame:

    compute_rich_regime_scores(spy, prices.loc[:, defined])  ==  patched(spy, prices)

That identity is what this script measures with -- the real, unmodified core function -- so the
numbers in the note are the proposed code's numbers, not a re-implementation's. `--self-check`
asserts the identity's premise (a frame that is already fully defined is unchanged by the mask).

WHAT IS COMPARED, PER DATE
    A  lab fix only  (today's branch): core over the point-in-time eligible universe
    B  lab fix + the proposed core patch
    C  neither       (pre-ASTRA-06): core over every column of the panel
    D  core patch only, no lab fix
A -> B is the marginal effect Lucas is being asked to approve. C -> D says what the core patch
would have done on its own, which is the interesting comparison if the lab fix is ever reverted.

Read-only: it runs no production CLI, writes only the CSV you ask for, and touches no state.

    python experiments/astra06_core_proposal.py --self-check
    python experiments/astra06_core_proposal.py --cache-dir <_sweep_cache_oos> \
        --payload <data_cache/sp500_pit.json> --pit-dir <data_cache/pit> --csv out.csv

Every number it prints is S&P 500 only, and the 2004-2026 PIT panel has real membership but
~53% price coverage in 2005 -- do not quote absolute levels from it without that caveat.
"""
import argparse
import hashlib
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


def defined_columns(frame):
    """Columns for which every breadth comparison is defined on the last bar of `frame`.

    `pct_change()` without `fill_method=None` is deliberate: it is what core.regime calls, and this
    mask has to answer "what would the patched core see", not "what should core have called".
    """
    last = frame.iloc[-1]
    ret_1d = frame.pct_change().iloc[-1]
    sma50 = frame.rolling(50).mean().iloc[-1]
    sma200 = frame.rolling(200).mean().iloc[-1]
    return (last.notna() & ret_1d.notna() & sma50.notna() & sma200.notna()).fillna(False)


def masked(spy, frame):
    """The proposed core's regime on `frame`, computed with the real (unpatched) core function."""
    ok = defined_columns(frame)
    return compute_rich_regime_scores(spy, frame.loc[:, ok[ok].index]), int(ok.sum()), int((~ok).sum())


def proposed_meta_for(P):
    """`P.meta_for` as it would behave with the patched core, built ONLY from the identity above.

    It re-runs the lab's own `meta_fast` logic with one line changed -- the frame handed to
    `compute_rich_regime_scores` is restricted to the columns whose comparisons are defined -- so
    the backtest below is the proposed core's backtest without core being edited.
    `--validate-replica` checks that with the mask switched off this reproduces `P.meta_for`
    exactly, which is what makes the duplication trustworthy.
    """
    cache = {}

    def meta(t, cfg=True, mask=True):
        c_ = dict(L.BASE)
        if isinstance(cfg, dict):
            c_.update(cfg)
        else:
            c_['regime_breadth'] = bool(cfg)
        use = bool(c_['regime_breadth'])
        key = (t, use, c_['min_dollar_vol'], c_['max_jump'], mask) if use else (t, False, None, None, mask)
        if key not in cache:
            lo = max(0, t - 300)
            s = P.spy.iloc[lo:t + 1]
            frame = None
            if use:
                frame = P.close.loc[:, L.breadth_universe(P, t, c_)].iloc[lo:t + 1]
                if mask:
                    ok = defined_columns(frame)
                    frame = frame.loc[:, ok[ok].index]
            rr = compute_rich_regime_scores(s, frame)
            cur = float(s.iloc[-1]); mx = float(s.rolling(60).max().iloc[-1])
            vl = float(s.pct_change(fill_method=None).rolling(20).std().iloc[-1] * np.sqrt(252))
            cache[key] = P.meta.compute_adjustment(
                regime_score=rr.overall, recent_drawdown=max(0.0, (mx - cur) / mx),
                spy_20d_return=cur / float(s.iloc[-20]) - 1, spy_60d_return=cur / float(s.iloc[-60]) - 1,
                volatility_level=min(max(vl / 0.25, 0.3), 0.9))
        return cache[key]
    return meta


def validate_replica(P, c, dates):
    """The replica with masking OFF must be the lab's own meta_for, bit for bit."""
    replica = proposed_meta_for(P)
    for t in dates:
        a, b = P.meta_for(t, c), replica(t, c, mask=False)
        fields = (lambda m: (m.overall_aggression, m.pillar_multipliers['COMPASS'], m.regime_score))
        assert fields(a) == fields(b), (t, a, b)
    print(f'replica OK: unmasked meta_for reproduced on {len(dates)} dates')


def self_check():
    """The identity the measurement rests on, asserted rather than asserted-to-be-true."""
    idx = pd.bdate_range('2005-01-03', periods=260)
    t = np.arange(260)
    clean = pd.DataFrame({f'M{i}': 100.0 + t for i in range(50)}, index=idx)
    spy = pd.Series(100 + t * 0.1, index=idx)
    base = compute_rich_regime_scores(spy, clean)
    same, n_ok, n_bad = masked(spy, clean)
    assert (n_ok, n_bad) == (50, 0), (n_ok, n_bad)
    assert same == base, (base, same)
    # and the probe: 50 columns with no observation move core today, and not under the proposal
    dirty = clean.assign(**{f'FUTURE{i}': np.full(len(idx), np.nan) for i in range(50)})
    today = compute_rich_regime_scores(spy, dirty)
    proposed, n_ok, n_bad = masked(spy, dirty)
    assert (n_ok, n_bad) == (50, 50), (n_ok, n_bad)
    assert today.overall != base.overall, today
    assert proposed == base, (base, proposed)
    print(f'self-check OK: clean {base.overall} / breadth {base.breadth_proxy}; '
          f'+50 unobserved columns -> core today {today.overall} / {today.breadth_proxy}, '
          f'proposed {proposed.overall} / {proposed.breadth_proxy}')


def sha256(path, limit=None):
    h = hashlib.sha256()
    with open(path, 'rb') as fh:
        while True:
            b = fh.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--cache-dir', default=None, help='panel cache (default experiments/_sweep_cache_oos)')
    ap.add_argument('--payload', default=None, help='sp500_pit.json (default: data_cache/, else fetched)')
    ap.add_argument('--pit-dir', default=None, help='PIT snapshots dir for the sector map')
    ap.add_argument('--start', type=int, default=280)
    ap.add_argument('--step', type=int, default=5)
    ap.add_argument('--config', default='PROD')
    ap.add_argument('--csv', default=None)
    ap.add_argument('--self-check', action='store_true', help='assert the identity and exit')
    ap.add_argument('--headline', nargs='*', default=None,
                    help='also run the paired executable backtest for these configs (e.g. T20 PROD): '
                         'current core vs the proposal, DEV/TEST/ALL rows. Slow.')
    ap.add_argument('--deltas', action='store_true', default=None,
                    help='per-date delta table (default when --headline is not given)')
    a = ap.parse_args()

    self_check()                       # always: the measurement is worthless if it fails
    if a.self_check:
        return

    # provenance, so every number below can be re-derived or falsified
    cache = a.cache_dir or os.path.join(HERE, '_sweep_cache_oos')
    print('\n=== inputs ===')
    for f in ('close.pkl', 'volume.pkl', 'spy.pkl'):
        p = os.path.join(cache, f)
        if os.path.exists(p):
            print(f'  {p}  {os.path.getsize(p)} bytes  mtime {pd.Timestamp(os.path.getmtime(p), unit="s")}  '
                  f'sha256 {sha256(p)}')
    if a.payload:
        print(f'  {a.payload}  {os.path.getsize(a.payload)} bytes  '
              f'mtime {pd.Timestamp(os.path.getmtime(a.payload), unit="s")}  sha256 {sha256(a.payload)}')

    payload = json.load(open(a.payload, encoding='utf-8')) if a.payload else None
    P = L.load_panel(oos=True, cache_dir=cache, payload=payload,
                     sectors='pit', sectors_date=None, pit_dir=a.pit_dir)
    print(f'panel {P.close.shape}  {P.close.index[0].date()} .. {P.close.index[-1].date()}', flush=True)

    c = dict(L.BASE); c.update(L.CONFIGS[a.config])
    validate_replica(P, c, [400, 1200, 2400, 3600, 4800, len(P.close.index) - 10])

    if a.headline:
        for name in a.headline:
            cfg = L.CONFIGS[name]; h = L.step_of(cfg)
            unpatched = P.meta_for
            cur = L.run_any(P, cfg)
            P.meta_for = proposed_meta_for(P)          # == the patched core, per the identity above
            new = L.run_any(P, cfg)
            P.meta_for = unpatched                     # never leave the panel in the patched state
            print()
            print(f'=== paired executable backtest, {name} (current core vs H-007) ===')
            L.table([L.stats(cur[cur.index < L.SPLIT], h, f'{name} DEV  current'),
                     L.stats(new[new.index < L.SPLIT], h, f'{name} DEV  H-007'),
                     L.stats(cur[cur.index >= L.SPLIT], h, f'{name} TEST current'),
                     L.stats(new[new.index >= L.SPLIT], h, f'{name} TEST H-007'),
                     L.stats(cur, h, f'{name} ALL  current'),
                     L.stats(new, h, f'{name} ALL  H-007')])
            d = (new['net'] - cur['net'])
            print(f'paired net difference per cycle: mean {d.mean():+.6f}  cycles differing '
                  f'{int((d != 0).sum())}/{len(d)}')
        if a.deltas is None:
            return

    idx = P.close.index
    rows = []
    for t in range(a.start, len(idx) - 7, a.step):
        out = L.rank_day(P, t, c)
        if out is None:
            continue
        lo = max(0, t - 300)
        s = P.spy.iloc[lo:t + 1]
        univ = L.breadth_universe(P, t, c)
        f_lab = P.close.loc[:, univ].iloc[lo:t + 1]
        f_all = P.close.iloc[lo:t + 1]

        rr_a = compute_rich_regime_scores(s, f_lab)
        rr_b, ok_lab, bad_lab = masked(s, f_lab)
        rr_c = compute_rich_regime_scores(s, f_all)
        rr_d, ok_all, bad_all = masked(s, f_all)

        cur = float(s.iloc[-1]); mx = float(s.rolling(60).max().iloc[-1])
        vl = float(s.pct_change(fill_method=None).rolling(20).std().iloc[-1] * np.sqrt(252))

        def count(rr):
            m = P.meta.compute_adjustment(
                regime_score=rr.overall, recent_drawdown=max(0.0, (mx - cur) / mx),
                spy_20d_return=cur / float(s.iloc[-20]) - 1, spy_60d_return=cur / float(s.iloc[-60]) - 1,
                volatility_level=min(max(vl / 0.25, 0.3), 0.9))
            return max(6, min(int(round(14 * m.overall_aggression * m.pillar_multipliers['COMPASS'])), 28)), m

        n_a, m_a = count(rr_a); n_b, m_b = count(rr_b)
        n_c, _ = count(rr_c); n_d, _ = count(rr_d)
        sel_a = list(L.select(out, n_a, set(), 1.0).index)
        sel_b = list(L.select(out, n_b, set(), 1.0).index)
        rows.append(dict(
            date=idx[t], cols_lab=len(univ), ok_lab=ok_lab, bad_lab=bad_lab, ok_all=ok_all, bad_all=bad_all,
            reg_a=rr_a.overall, reg_b=rr_b.overall, reg_c=rr_c.overall, reg_d=rr_d.overall,
            br_a=rr_a.breadth_proxy, br_b=rr_b.breadth_proxy, br_c=rr_c.breadth_proxy, br_d=rr_d.breadth_proxy,
            agg_a=round(m_a.overall_aggression, 4), agg_b=round(m_b.overall_aggression, 4),
            n_a=n_a, n_b=n_b, n_c=n_c, n_d=n_d,
            same_list=sel_a == sel_b,
            added=len(set(sel_b) - set(sel_a)), removed=len(set(sel_a) - set(sel_b))))
        if len(rows) % 200 == 0:
            print('  ...', len(rows), idx[t].date(), flush=True)

    d = pd.DataFrame(rows).set_index('date')
    if a.csv:
        d.to_csv(a.csv)
    gate = MIN_REGIME_SCORE * 0.85

    def block(title, old, new, n_old, n_new):
        delta = d[new] - d[old]
        print(f'\n--- {title} ---')
        print(f'regime differs   {int((delta != 0).sum())}/{len(d)} dates ({(delta != 0).mean() * 100:.1f}%)  '
              f'mean {delta.mean():+.4f}  mean|d| {delta.abs().mean():.4f}  max|d| {delta.abs().max():.4f}  '
              f'higher/lower {int((delta > 0).sum())}/{int((delta < 0).sum())}')
        print(f'dynamic count    {int((d[n_old] != d[n_new]).sum())} dates differ  '
              f'mean {d[n_old].mean():.2f} -> {d[n_new].mean():.2f}  '
              f'delta {(d[n_new] - d[n_old]).value_counts().sort_index().to_dict()}')
        print(f'gate flips       {int(((d[old] >= gate) != (d[new] >= gate)).sum())} dates (threshold {gate:.4f})')

    print(f'\n=== ASTRA-06 core proposal, config {a.config}, {len(d)} dates '
          f'({d.index[0].date()} .. {d.index[-1].date()}) ===')
    print(f'panel {P.close.shape[1]} columns; PIT eligible universe min/median/max '
          f'{d.cols_lab.min()}/{int(d.cols_lab.median())}/{d.cols_lab.max()}')
    print(f'columns the patch would DROP from the breadth denominator: '
          f'on the PIT frame min/median/max {d.bad_lab.min()}/{int(d.bad_lab.median())}/{d.bad_lab.max()} '
          f'(of {int(d.cols_lab.median())} median); on the whole panel '
          f'{d.bad_all.min()}/{int(d.bad_all.median())}/{d.bad_all.max()}')
    print(f'breadth sub-score mean: A {d.br_a.mean():.4f}  B {d.br_b.mean():.4f}  '
          f'C {d.br_c.mean():.4f}  D {d.br_d.mean():.4f}')
    block('A -> B  the marginal effect of the core patch ON TOP of the lab fix (what H-007 asks for)',
          'reg_a', 'reg_b', 'n_a', 'n_b')
    print(f'order list differs {int((~d.same_list).sum())} dates ({(~d.same_list).mean() * 100:.1f}%)  '
          f'mean in/out on a changed date '
          f'{d.loc[~d.same_list, "added"].mean() if (~d.same_list).any() else 0:.2f}/'
          f'{d.loc[~d.same_list, "removed"].mean() if (~d.same_list).any() else 0:.2f}')
    print(f'aggression differs {int((d.agg_a != d.agg_b).sum())} dates  '
          f'mean {d.agg_a.mean():.4f} -> {d.agg_b.mean():.4f}')
    block('C -> D  the core patch ALONE, on the unmasked panel (if the lab fix were reverted)',
          'reg_c', 'reg_d', 'n_c', 'n_d')
    era = d.assign(ad=(d.reg_b - d.reg_a).abs(), diff=~d.same_list).groupby(d.index.year).agg(
        dates=('n_a', 'size'), mean_abs_delta=('ad', 'mean'), list_diff_share=('diff', 'mean'),
        univ=('cols_lab', 'median'), dropped=('bad_lab', 'median'), n_a=('n_a', 'mean'), n_b=('n_b', 'mean'))
    print('\nby year (A -> B):')
    print(era.round(4).to_string())


if __name__ == '__main__':
    main()
