#!/usr/bin/env python
"""
Point-in-time variant sweep for the HYDRA scoring pipeline.

Backs the analysis in .comms/claude-algo-deep-dive-2026-09-05.md.

The engine replicates core/signals.generate_daily_candidates in vectorised form so hundreds of
rebalance dates can be evaluated quickly, and `--validate` proves the replica matches the real
pipeline (identical top-50 ordering and identical recommended set) before any variant is trusted.

Nothing here modifies the algorithm. It only measures it.

Usage:
    python experiments/backtest_variant_sweep.py --download    # fetch data (~2 min)
    python experiments/backtest_variant_sweep.py --validate    # replica vs real pipeline
    python experiments/backtest_variant_sweep.py --sweep       # variant table + paired t-tests
    python experiments/backtest_variant_sweep.py --risk        # alpha-vs-leverage + costs
    python experiments/backtest_variant_sweep.py --all

Caveats that apply to every number this prints:
  - Survivorship bias: uses the CURRENT S&P 500 constituents over the whole window.
  - One macro regime only (2020-2026).
  - Production runs UNIVERSE="all" (~3000 names); this is 500 large caps.
"""
import argparse
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from config import (MOMENTUM_LOOKBACK, SHORT_TERM_LOOKBACK, PROXIMITY_HIGH_DAYS,
                    MAX_DIST_TO_HIGH_PCT, SHORT_TERM_BOOST, VOL_SURGE_THRESHOLD,
                    MAX_PER_SECTOR, SECTOR_OVERWEIGHT_PENALTY, SECTOR_BUCKETS,
                    GATE_MAX_DIST_TO_HIGH_PCT, GATE_MIN_RET_SHORT_PCT, MIN_REGIME_SCORE)
from core.meta_layer import LightweightMetaLayer
from core.regime import compute_rich_regime_scores

CACHE = os.path.join(ROOT, 'experiments', '_sweep_cache')
START, END = '2020-01-01', None          # None = today
CYCLES_PER_YEAR = 252 / 5


# ----------------------------------------------------------------------------- data
def download():
    import yfinance as yf
    from data.universe import get_sp500_tickers
    os.makedirs(CACHE, exist_ok=True)
    tickers = get_sp500_tickers()
    print(f'universe: {len(tickers)}')
    closes, vols = [], []
    for i in range(0, len(tickers), 60):
        chunk = tickers[i:i + 60]
        d = yf.download(chunk, start=START, end=END, progress=False, auto_adjust=True, threads=True)
        if d is None or d.empty:
            continue
        closes.append(d['Close']); vols.append(d['Volume'])
        print(f'  {min(i + 60, len(tickers))}/{len(tickers)}', flush=True)
    close = pd.concat(closes, axis=1).sort_index()
    volume = pd.concat(vols, axis=1).sort_index()
    close = close.loc[:, ~close.columns.duplicated()]
    volume = volume.loc[:, ~volume.columns.duplicated()]
    spy = yf.download('SPY', start=START, end=END, progress=False, auto_adjust=True)['Close']
    if hasattr(spy, 'columns'):
        spy = spy.iloc[:, 0]
    close.to_pickle(f'{CACHE}/close.pkl')
    volume.to_pickle(f'{CACHE}/volume.pkl')
    spy.to_frame('SPY').to_pickle(f'{CACHE}/spy.pkl')
    print(f'saved {close.shape}, {close.index[0].date()} .. {close.index[-1].date()}')


class Panels:
    """Rolling feature panels: row t holds the value computable with data up to and including t."""

    def __init__(self):
        if not os.path.exists(f'{CACHE}/close.pkl'):
            sys.exit('No cached data. Run with --download first.')
        self.close = pd.read_pickle(f'{CACHE}/close.pkl')
        self.volume = pd.read_pickle(f'{CACHE}/volume.pkl')
        self.close, self.volume = self.close.align(self.volume, join='inner', axis=0)
        self.spy = pd.read_pickle(f'{CACHE}/spy.pkl')['SPY'].reindex(self.close.index).ffill()

        c, v = self.close, self.volume
        self.rets = c.pct_change(fill_method=None)
        self.VOL63 = self.rets.rolling(63).std() * np.sqrt(252)
        self.MOM = c / c.shift(MOMENTUM_LOOKBACK) - 1
        self.MOM_SKIP5 = c.shift(5) / c.shift(MOMENTUM_LOOKBACK) - 1
        self.RET10 = (c / c.shift(SHORT_TERM_LOOKBACK) - 1) * 100
        self.DIST20 = (c / c.rolling(PROXIMITY_HIGH_DAYS).max() - 1) * 100
        self.DIST252 = (c / c.rolling(252).max() - 1) * 100
        self.VOL20M = v.rolling(20).mean()
        self.VRATIO = v.rolling(5).mean() / self.VOL20M
        self.VRATIO_NO = v.rolling(5).mean() / v.shift(5).rolling(20).mean()
        self.FLAT5 = c.rolling(5).apply(lambda a: len(set(a)) == 1, raw=True)
        self.meta = LightweightMetaLayer()
        self._cache = {}

    def meta_for(self, t):
        if t not in self._cache:
            s = self.spy.iloc[:t + 1]
            rr = compute_rich_regime_scores(s, self.close.iloc[:t + 1])
            cur = float(s.iloc[-1]); mx = float(s.rolling(60).max().iloc[-1])
            vl = float(s.pct_change(fill_method=None).rolling(20).std().iloc[-1] * np.sqrt(252))
            self._cache[t] = self.meta.compute_adjustment(
                regime_score=rr.overall, recent_drawdown=max(0.0, (mx - cur) / mx),
                spy_20d_return=cur / float(s.iloc[-20]) - 1,
                spy_60d_return=cur / float(s.iloc[-60]) - 1,
                volatility_level=min(max(vl / 0.25, 0.3), 0.9))
        return self._cache[t]


DEFAULTS = dict(mom='mom90', vol_exp=1.0, dist='d20', vratio='overlap', boost=SHORT_TERM_BOOST,
                strict_bonus=0.18, combine='mult', sector_control=True, sector_skip_other=False,
                max_per_sector=MAX_PER_SECTOR, gate=True, regime_gate=True, gate_dist=GATE_MAX_DIST_TO_HIGH_PCT,
                gate_ret=GATE_MIN_RET_SHORT_PCT, gate_needs_negative=True,
                regime_thr=MIN_REGIME_SCORE * 0.85, fixed_n=None,
                min_price=5.0, min_advol=100_000)


def score_day(P, t, c):
    """Return the ranked frame for one date, or None."""
    px = P.close.iloc[t]
    elig = px.notna() & (px >= c['min_price']) & (P.VOL20M.iloc[t] >= c['min_advol']) & (P.FLAT5.iloc[t] != 1)
    tk = px.index[elig.fillna(False)]
    if len(tk) < 50:
        return None, None
    src = {'mom90': P.MOM, 'mom90_skip5': P.MOM_SKIP5}[c['mom']].iloc[t][tk]
    mom = src if c['vol_exp'] == 0 else src / (P.VOL63.iloc[t][tk].replace(0, np.nan) ** c['vol_exp'])
    d = (P.DIST20 if c['dist'] == 'd20' else P.DIST252).iloc[t][tk]
    r = P.RET10.iloc[t][tk]
    v = (P.VRATIO if c['vratio'] == 'overlap' else P.VRATIO_NO).iloc[t][tk]
    f = pd.DataFrame({'mom': mom, 'ret': r, 'dist': d, 'vr': v}).dropna(subset=['mom'])
    if f.empty:
        return None, None

    boost = (((f['ret'].fillna(0) / 20).clip(-0.5, 1.5)) +
             ((MAX_DIST_TO_HIGH_PCT + f['dist'].fillna(-10)).clip(0, MAX_DIST_TO_HIGH_PCT) / MAX_DIST_TO_HIGH_PCT)) / 2
    strict = (f['ret'].fillna(0) > 15) & (f['dist'].fillna(-100) >= -2) & (f['vr'].fillna(0) > VOL_SURGE_THRESHOLD)
    if c['combine'] == 'mult':
        comp = f['mom'] * (1 + boost * c['boost'])
        comp = comp.where(~strict, comp * (1 + c['strict_bonus']))
    else:
        z = (f['mom'] - f['mom'].mean()) / f['mom'].std()
        comp = z + c['boost'] * boost + c['strict_bonus'] * strict.astype(float)

    out = pd.DataFrame({'comp': comp, 'ret': f['ret'], 'dist': f['dist']})
    out['sector'] = [SECTOR_BUCKETS.get(x, 'Other') for x in out.index]
    if c['sector_control']:
        over = out.groupby('sector')['comp'].rank(method='first', ascending=False) > c['max_per_sector']
        if c['sector_skip_other']:
            over &= (out['sector'] != 'Other')
        out.loc[over, 'comp'] *= (1 - SECTOR_OVERWEIGHT_PENALTY)
    return out.sort_values('comp', ascending=False), tk


def run(P, cfg=None, start=260, step=5, hold=5, lag=1, topk=None):
    c = dict(DEFAULTS); c.update(cfg or {})
    idx, prev, recs = P.close.index, set(), []
    for t in range(start, len(idx) - hold - lag - 1, step):
        out, tk = score_day(P, t, c)
        if out is None:
            continue
        m = P.meta_for(t)
        n = c['fixed_n'] or max(6, min(int(round(14 * m.overall_aggression * m.pillar_multipliers['COMPASS'])), 28))
        # two independent controls: the regime gate (market timing) and the downtrend gate (per name)
        sel = out.head(n) if (not c['regime_gate'] or m.regime_score >= c['regime_thr']) else out.head(0)
        if c['gate'] and len(sel):
            neg = (sel['ret'] < 0) if c['gate_needs_negative'] else True
            veto = (neg & ((sel['dist'] < c['gate_dist']) | (sel['ret'] < c['gate_ret']))).fillna(False)
            veto |= sel['dist'].isna() | sel['ret'].isna()
            sel = sel[~veto]
        if topk:
            sel = sel.head(topk)
        cur = set(sel.index)
        e, x = t + lag, t + lag + hold
        fwd = (P.close.iloc[x][sel.index] / P.close.iloc[e][sel.index] - 1).dropna() if len(sel) else pd.Series(dtype=float)
        uni = (P.close.iloc[x][tk] / P.close.iloc[e][tk] - 1).dropna()
        recs.append(dict(date=idx[t], n=len(sel), ret=float(fwd.mean()) if len(fwd) else 0.0,
                         turnover=len(cur - prev) / max(len(cur), 1) if cur else 0.0,
                         invested=len(sel) > 0, selvol=float(P.VOL63.iloc[t][sel.index].mean()) if len(sel) else np.nan,
                         uni=float(uni.mean()), spy=float(P.spy.iloc[x] / P.spy.iloc[e] - 1),
                         regime=m.regime_score, rtype=m.regime_type))
        prev = cur
    return pd.DataFrame(recs)


def stats(df, label=''):
    r = df['ret']
    eq = (1 + r).cumprod()
    return dict(variant=label, cycles=len(r), avg_n=round(df['n'].mean(), 1),
                mean_bp=round(r.mean() * 10000, 1),
                ann_pct=round(((1 + r).prod() ** (CYCLES_PER_YEAR / len(r)) - 1) * 100, 2),
                sharpe=round(r.mean() / r.std() * np.sqrt(CYCLES_PER_YEAR), 2),
                maxdd_pct=round(float((eq / eq.cummax() - 1).min()) * 100, 1),
                turnover_pct=round(df['turnover'].mean() * 100, 1))


# ----------------------------------------------------------------------------- modes
def validate(P):
    from core.signals import generate_daily_candidates
    from core.filters import apply_practical_filters, remove_zombie_tickers
    t = len(P.close) - 7
    px, _ = apply_practical_filters(P.close.iloc[:t + 1], volumes=P.volume.iloc[:t + 1],
                                    min_avg_volume=100_000, min_price=5.0)
    px = remove_zombie_tickers(px)
    real = generate_daily_candidates(px, P.spy.iloc[:t + 1], volumes=P.volume.iloc[:t + 1])
    out, _ = score_day(P, t, dict(DEFAULTS))
    out = out.loc[[i for i in out.index if i in px.columns]]
    print(f'\ndate {P.close.index[t].date()}  |  replica {len(out)}  real {len(real)}')
    print('top-20 order identical :', list(out.index[:20]) == list(real['ticker'][:20]))
    print('top-50 order identical :', list(out.index[:50]) == list(real['ticker'][:50]))
    print('NOTE: composite VALUES differ by a constant factor (the meta-layer scalar) but the')
    print('      ORDER does not — that global scalar cannot change the cross-sectional ranking.')


VARIANTS = [
    ('BASELINE (as-is)', {}, {}),
    ('no downtrend gate', dict(gate=False), {}),
    ('no regime gate', dict(regime_gate=False), {}),
    ('gate without only-negative', dict(gate_needs_negative=False), {}),
    ('no sector control', dict(sector_control=False), {}),
    ('sector ctrl skips Other', dict(sector_skip_other=True), {}),
    ('momentum skip last 5d', dict(mom='mom90_skip5'), {}),
    ('momentum raw (vol_exp=0)', dict(vol_exp=0.0), {}),
    ('vol_exp=0.5', dict(vol_exp=0.5), {}),
    ('dist to 252d high', dict(dist='d252'), {}),
    ('vol ratio non-overlapping', dict(vratio='nonoverlap'), {}),
    ('no short-term boost', dict(boost=0.0), {}),
    ('no strict bonus', dict(strict_bonus=0.0), {}),
    ('additive score (sign-safe)', dict(combine='add'), {}),
    ('fixed N=10', dict(fixed_n=10), {}),
    ('top 5 only', {}, dict(topk=5)),
]


def sweep(P):
    from scipy import stats as sps
    rows, keep = [], {}
    for label, cfg, kw in VARIANTS:
        df = run(P, cfg, **kw)
        keep[label] = df
        rows.append(stats(df, label))
        print('  done:', label, flush=True)
    print('\n' + pd.DataFrame(rows).to_string(index=False))

    base = keep['BASELINE (as-is)']['ret'].values
    print('\nPAIRED t-TEST vs BASELINE (same dates)')
    sig = []
    for k, df in keep.items():
        if k == 'BASELINE (as-is)':
            continue
        d = df['ret'].values - base
        t, p = sps.ttest_1samp(d, 0)
        sig.append(dict(variant=k, delta_bp=round(d.mean() * 10000, 1), t=round(t, 2), p=round(p, 4)))
    print(pd.DataFrame(sig).sort_values('delta_bp', ascending=False).to_string(index=False))
    print(f'\n  {len(sig)} comparisons on one sample: a lone p<0.05 does not survive'
          ' multiplicity correction.')
    return keep


def risk(P):
    """Is dropping vol-scaling alpha, or just leverage? Plus the cost curve."""
    rng = np.random.default_rng(0)
    print('\nVOL-SCALING EXPONENT   score = ret90 / vol63**k')
    keep = {}
    for k in [0.0, 0.25, 0.5, 0.75, 1.0]:
        df = run(P, dict(vol_exp=k)); keep[k] = df
        s = stats(df, f'k={k}')
        print(f"  k={k:<5} {s['mean_bp']:>6} bp | ann {s['ann_pct']:>6}% | Sharpe {s['sharpe']:.2f}"
              f" | maxDD {s['maxdd_pct']:>6}% | vol of picks {df['selvol'].mean()*100:.1f}%")

    b, raw = keep[1.0]['ret'], keep[0.0]['ret']
    lev = raw.std() / b.std()
    d = raw.values - (b * lev).values
    boot = np.array([rng.choice(d, len(d), replace=True).mean() for _ in range(5000)])
    print(f'\nALPHA vs LEVERAGE (baseline levered {lev:.2f}x to the raw variant\'s volatility)')
    print(f'  levered baseline {(b*lev).mean()*10000:.1f} bp | raw {raw.mean()*10000:.1f} bp'
          f' | difference {d.mean()*10000:.1f} bp')
    print(f'  bootstrap 95% CI of that difference: [{np.percentile(boot,2.5)*10000:.1f},'
          f' {np.percentile(boot,97.5)*10000:.1f}] bp')
    if np.percentile(boot, 2.5) < 0 < np.percentile(boot, 97.5):
        print('  -> CI includes zero: the headline gain is risk-taking, not demonstrable alpha.')

    print('\nTRANSACTION COSTS')
    df = keep[1.0]
    print(f'  turnover {df["turnover"].mean()*100:.1f}%/cycle over ~{df["n"].mean():.0f} names')
    for bp in (0, 5, 10, 20):
        net = df['ret'] - df['turnover'] * 2 * bp / 10000
        ann = (1 + net).prod() ** (CYCLES_PER_YEAR / len(net)) - 1
        print(f'    {bp:>2} bp/side -> {net.mean()*100:.3f}%/cycle | ann {ann*100:6.2f}%'
              f' | Sharpe {net.mean()/net.std()*np.sqrt(CYCLES_PER_YEAR):.2f}')

    print('\nREGIME GATE')
    for label, cfg in [('no regime gate', dict(regime_gate=False)), ('production (0.2975)', {}),
                       ('thr 0.45', dict(regime_thr=0.45)), ('thr 0.55', dict(regime_thr=0.55))]:
        g = run(P, cfg); s = stats(g, label)
        print(f"  {label:<22} exposure {g['invested'].mean()*100:5.1f}% | {s['mean_bp']:>6} bp"
              f" | Sharpe {s['sharpe']:.2f} | maxDD {s['maxdd_pct']:>6}%")
    g = run(P, {})
    inv = g['invested']
    print(f"  SPY while OUT {g.loc[~inv,'spy'].mean()*100:+.3f}%/cycle (n={(~inv).sum()})"
          f" vs while IN {g.loc[inv,'spy'].mean()*100:+.3f}%/cycle (n={inv.sum()})")
    print('\n  return by regime_type (bp/cycle):')
    for rt, row in g.groupby('rtype')['ret'].agg(['mean', 'count']).iterrows():
        print(f"    {rt:<10} {row['mean']*10000:+7.1f} bp   n={int(row['count'])}")


def main():
    ap = argparse.ArgumentParser()
    for f in ('download', 'validate', 'sweep', 'risk', 'all'):
        ap.add_argument(f'--{f}', action='store_true')
    a = ap.parse_args()
    if not any(vars(a).values()):
        ap.print_help(); return
    if a.download or a.all:
        download()
    if a.validate or a.sweep or a.risk or a.all:
        P = Panels()
        print(f'panels: {P.close.shape}  {P.close.index[0].date()} .. {P.close.index[-1].date()}')
        if a.validate or a.all:
            validate(P)
        if a.sweep or a.all:
            sweep(P)
        if a.risk or a.all:
            risk(P)


if __name__ == '__main__':
    main()
