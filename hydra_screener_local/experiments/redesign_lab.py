#!/usr/bin/env python
"""
Redesign lab (2026-09-06). Target set by Lucas: >= 10% annualised, which this lab reads as
NET of costs (10 bp/side) on the point-in-time 2004-2026 panel. Production today: 9.68% gross,
5.72% net on that panel.

Protocol, fixed before any number was looked at:
  DEV  = cycles before 2016-01-01 (2004-2015, includes 2008)   -> explore levers here
  TEST = cycles from 2016-01-01   (2016-2026, includes 2020/22)-> run ONCE, finalists only
Finalists are chosen by design principle + literature, not by a grid:
  F1 cost-aware       production signal + hold buffer (Novy-Marx & Velikov buy/hold spread) + hold 10
  F2 risk-managed     F1 + binary regime gate replaced by volatility targeting (exposure <= 1)
  F3 canonical mom    F2 with 12-1 momentum (252d, skip 21) instead of 90d
Leverage is capped at 1.0 (project rule): vol targeting can only reduce exposure.

Reuses the validated harness (Panels, PIT membership, sector cap, meta-layer) and re-implements
only what the harness cannot express: a stateful buffer, holding periods, weights, exposure.

Usage:
    python experiments/redesign_lab.py --dev                 # lever table on DEV only
    python experiments/redesign_lab.py --test F1 F2 F3       # the one look at TEST
    python experiments/redesign_lab.py --full F2             # DEV + TEST rows for one config
    python experiments/redesign_lab.py --insample F2         # 2020-26 S&P panel (sanity only)
"""
import argparse
import importlib.util
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

_spec = importlib.util.spec_from_file_location('bvs', os.path.join(HERE, 'backtest_variant_sweep.py'))
bvs = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(bvs)

from config import (MAX_DIST_TO_HIGH_PCT, SHORT_TERM_BOOST, VOL_SURGE_THRESHOLD, MAX_PER_SECTOR,
                    GATE_MAX_DIST_TO_HIGH_PCT, GATE_MIN_RET_SHORT_PCT, MIN_REGIME_SCORE, COST_BP_PER_SIDE)
from core.regime import compute_rich_regime_scores
from data.sectors import lookup_sector

CYCLES_PER_YEAR = 252
SPLIT = pd.Timestamp('2016-01-01')


# ----------------------------------------------------------------------------- panels
def load_panel(oos=True):
    if oos:
        from data.universe import fetch_sp500_pit_payload
        payload = fetch_sp500_pit_payload()
        P = bvs.Panels(cache_dir=bvs.OOS_CACHE, pit_payload=payload)
    else:
        P = bvs.Panels()
    c = P.close
    P.MOM_12_1 = c.shift(21) / c.shift(252) - 1
    P.MOM_6_1 = c.shift(21) / c.shift(126) - 1
    P.MOM_12_7 = c.shift(126) / c.shift(252) - 1     # Novy-Marx (2012): the intermediate horizon carries the effect
    P.ADV_USD = (c * P.volume).rolling(20).mean()
    # data quality, point-in-time: legacy exp53 excluded names with a >50% single-day move (Yahoo's
    # delisted/reused tickers carry +3000% 'returns'). Trailing window so there is no look-ahead.
    P.JUMP252 = P.rets.abs().rolling(252, min_periods=20).max()
    P.SPY_R5 = P.spy / P.spy.shift(5) - 1
    irx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_sweep_cache_oos', 'irx.pkl')
    irx = pd.read_pickle(irx_path) if os.path.exists(irx_path) else pd.Series(dtype=float)
    P.IRX = irx.reindex(c.index).ffill().fillna(0.0) / 100.0      # 13-week T-bill, annualised, decimal
    P.SPY_R10 = P.spy / P.spy.shift(10) - 1
    # legacy COMPASS EXP56 (2026-03-05 design doc): risk-adjusted momentum at 21/63/126/252 bars with a
    # 5-bar skip, percentile-ranked within the eligible universe, averaged. Taken as specified, not tuned.
    P.ENS_PARTS = {lb: (c.shift(5) / c.shift(5 + lb) - 1) for lb in ENS_LOOKBACKS}
    P.SECTOR = {t: lookup_sector(t) for t in c.columns}

    # the harness recomputes the regime on the whole panel per date: O(T*N) each. Same values
    # from the last 300 rows (SMA200 is the longest window it uses); ~40x faster.
    P._cache_nb = {}
    def meta_fast(t, breadth=True, _cache=P._cache):
        if not breadth:
            _cache = P._cache_nb
        if t not in _cache:
            lo = max(0, t - 300)
            s = P.spy.iloc[lo:t + 1]
            rr = compute_rich_regime_scores(s, c.iloc[lo:t + 1] if breadth else None)
            cur = float(s.iloc[-1]); mx = float(s.rolling(60).max().iloc[-1])
            vl = float(s.pct_change(fill_method=None).rolling(20).std().iloc[-1] * np.sqrt(252))
            _cache[t] = P.meta.compute_adjustment(
                regime_score=rr.overall, recent_drawdown=max(0.0, (mx - cur) / mx),
                spy_20d_return=cur / float(s.iloc[-20]) - 1, spy_60d_return=cur / float(s.iloc[-60]) - 1,
                volatility_level=min(max(vl / 0.25, 0.3), 0.9))
        return _cache[t]
    P.meta_for = meta_fast
    return P


# ----------------------------------------------------------------------------- config
ENS_LOOKBACKS = (21, 63, 126, 252)

BASE = dict(
    mom='mom90',            # mom90 | mom12_1 | mom6_1 | mom12_7 | ens
    boost=SHORT_TERM_BOOST, strict_bonus=0.18,
    hold=5,                 # bars held = rebalance step
    buffer=1.0,             # keep a held name while it ranks within buffer * n (1.0 = no buffer)
    weights='equal',        # equal | invvol
    exposure='regime_gate', # regime_gate (production binary) | voltarget | full
    target_vol=0.15, vol_lookback_cycles=12,
    vol_estimator='cycles', # cycles   = std of the strategy's last K cycle returns (window changes with hold!)
                            # basket63 = trailing 63-day daily vol of the basket about to be held (hold-independent)
    min_dollar_vol=5e6,     # production FILTERS since 2026-09-06
    max_jump=None,          # exclude names whose trailing-252 max |daily ret| exceeds this (None = off, as production)
    crash_brake=False,      # legacy v8.4: no new entries when SPY 5d < -6% or 10d < -10%
    cash_yield=False,       # idle cash earns the 13-week T-bill (accounting fix, not a strategy lever)
    regime_breadth=True,    # False = rich regime without the 10% breadth sub-score (legacy found breadth harmful twice)
)

CONFIGS = {
    'PROD':   {},
    # --- single levers (DEV exploration)
    'hold10': dict(hold=10),
    'hold20': dict(hold=20),
    'buf2':   dict(buffer=2.0),
    'buf2_h10': dict(buffer=2.0, hold=10),
    'nogate': dict(exposure='full'),
    'voltgt': dict(exposure='voltarget'),
    'invvol': dict(weights='invvol'),
    'noboost': dict(boost=0.0, strict_bonus=0.0),
    'm12_1':  dict(mom='mom12_1'),
    'm6_1':   dict(mom='mom6_1'),
    'm12_7':  dict(mom='mom12_7'),
    'buf2_h20': dict(buffer=2.0, hold=20),
    # --- pre-registered finalists (one knob may be adjusted after DEV: hold 10 vs 20, horizon 12-1 vs 12-7)
    'F1': dict(buffer=2.0, hold=10),
    'F2': dict(buffer=2.0, hold=10, exposure='voltarget'),
    'F3': dict(buffer=2.0, hold=10, exposure='voltarget', mom='mom12_1'),
    'F2_h20': dict(buffer=2.0, hold=20, exposure='voltarget'),
    'F3_h20': dict(buffer=2.0, hold=20, exposure='voltarget', mom='mom12_1'),
    'F3_12_7': dict(buffer=2.0, hold=10, exposure='voltarget', mom='mom12_7'),
    'F3_12_7_h20': dict(buffer=2.0, hold=20, exposure='voltarget', mom='mom12_7'),
    # hold-independent vol estimator (design fix, not a tuning knob)
    'F3_12_7_b63': dict(buffer=2.0, hold=10, exposure='voltarget', mom='mom12_7', vol_estimator='basket63'),
    'F3_12_7_h20_b63': dict(buffer=2.0, hold=20, exposure='voltarget', mom='mom12_7', vol_estimator='basket63'),
    'F3_h20_b63': dict(buffer=2.0, hold=20, exposure='voltarget', mom='mom12_1', vol_estimator='basket63'),
    # decomposition of the 12-7 monthly candidate: which component does what
    'm12_7_h20_gate':           dict(mom='mom12_7', hold=20, buffer=2.0),
    'm12_7_h20_gate_noboost':   dict(mom='mom12_7', hold=20, buffer=2.0, boost=0.0, strict_bonus=0.0),
    'm12_7_h20_voltgt_noboost': dict(mom='mom12_7', hold=20, buffer=2.0, exposure='voltarget', boost=0.0, strict_bonus=0.0),
    'm12_7_h10_gate':           dict(mom='mom12_7', hold=10, buffer=2.0),
    'm12_7_h10_gate_noboost':   dict(mom='mom12_7', hold=10, buffer=2.0, boost=0.0, strict_bonus=0.0),
    'm12_7_h20_nobuf_gate':     dict(mom='mom12_7', hold=20, buffer=1.0),
    # tranched (overlapping) portfolios: the phase-robust way to hold for 10 or 20 bars
    'T20':      dict(mom='mom12_7', hold=20, tranches=4, buffer=2.0, exposure='voltarget', vol_estimator='basket63'),
    'T20_gate': dict(mom='mom12_7', hold=20, tranches=4, buffer=2.0),
    'T10':      dict(mom='mom12_7', hold=10, tranches=2, buffer=2.0, exposure='voltarget', vol_estimator='basket63'),
    'T10_gate': dict(mom='mom12_7', hold=10, tranches=2, buffer=2.0),
    'T20_mom90': dict(mom='mom90', hold=20, tranches=4, buffer=2.0, exposure='voltarget', vol_estimator='basket63'),
    # legacy EXP56 idea, surfaced from the OneDrive corpus after TEST was already read: DEV-only evidence
    'PROD_ens': dict(mom='ens'),
    'T20_ens':  dict(mom='ens', hold=20, tranches=4, buffer=2.0, exposure='voltarget', vol_estimator='basket63'),
    'F1_ens':   dict(mom='ens', buffer=2.0, hold=10),
    # legacy corpus, second pass (2026-09-06): data-quality filter (exp53) and market crash brake (v8.4)
    'PROD_dq':  dict(max_jump=1.0),
    'T20_dq':   dict(mom='mom12_7', hold=20, tranches=4, buffer=2.0, exposure='voltarget', vol_estimator='basket63', max_jump=1.0),
    'T20_brake': dict(mom='mom12_7', hold=20, tranches=4, buffer=2.0, exposure='voltarget', vol_estimator='basket63', crash_brake=True),
    'PROD_brake': dict(crash_brake=True),
    'PROD_cy':  dict(cash_yield=True),
    'T20_cy':   dict(mom='mom12_7', hold=20, tranches=4, buffer=2.0, exposure='voltarget', vol_estimator='basket63', cash_yield=True),
    'PROD_nobreadth': dict(regime_breadth=False),
    'T20_nobreadth':  dict(mom='mom12_7', hold=20, tranches=4, buffer=2.0, exposure='voltarget', vol_estimator='basket63', regime_breadth=False),
}


# ----------------------------------------------------------------------------- one date
def rank_day(P, t, c):
    """Ranked frame for date t. Same scoring as production except the momentum panel."""
    px = P.close.iloc[t]
    elig = (px.notna() & (px >= 5.0) & (P.VOL20M.iloc[t] >= 100_000) & (P.FLAT5.iloc[t] != 1)
            & (P.ADV_USD.iloc[t] >= c['min_dollar_vol']))
    if c['max_jump'] is not None:
        elig &= ~(P.JUMP252.iloc[t] > c['max_jump']).fillna(False)
    if getattr(P, 'pit_payload', None):
        from data.universe import yahoo_membership_as_of
        members = set(yahoo_membership_as_of(P.close.index[t].strftime('%Y-%m-%d'), P.pit_payload))
        elig &= px.index.isin(members)
    tk = px.index[elig.fillna(False)]
    if len(tk) < 50:
        return None
    vol = P.VOL63.iloc[t][tk].replace(0, np.nan)
    if c['mom'] == 'ens':
        parts = pd.DataFrame({lb: P.ENS_PARTS[lb].iloc[t][tk] / vol for lb in ENS_LOOKBACKS})
        ram = parts.rank(pct=True).mean(axis=1).where(parts.notna().all(axis=1))
    else:
        src = {'mom90': P.MOM, 'mom12_1': P.MOM_12_1, 'mom6_1': P.MOM_6_1, 'mom12_7': P.MOM_12_7}[c['mom']].iloc[t][tk]
        ram = src / vol
    f = pd.DataFrame({'mom': ram, 'ret': P.RET10.iloc[t][tk], 'dist': P.DIST20.iloc[t][tk],
                      'vr': P.VRATIO.iloc[t][tk], 'vol': vol}).dropna(subset=['mom'])
    if f.empty:
        return None
    boost = (((f['ret'].fillna(0) / 20).clip(-0.5, 1.5)) +
             ((MAX_DIST_TO_HIGH_PCT + f['dist'].fillna(-10)).clip(0, MAX_DIST_TO_HIGH_PCT) / MAX_DIST_TO_HIGH_PCT)) / 2
    strict = (f['ret'].fillna(0) > 15) & (f['dist'].fillna(-100) >= -2) & (f['vr'].fillna(0) > VOL_SURGE_THRESHOLD)
    comp = f['mom'] * (1 + boost * c['boost'])
    comp = comp.where(~strict, comp * (1 + c['strict_bonus']))
    out = pd.DataFrame({'comp': comp, 'ret': f['ret'], 'dist': f['dist'], 'vol': f['vol']})
    out['sector'] = [P.SECTOR.get(x, 'Other') for x in out.index]
    return out.sort_values('comp', ascending=False)


def vetoed(sel):
    v = ((sel['ret'] < 0) & ((sel['dist'] < GATE_MAX_DIST_TO_HIGH_PCT) | (sel['ret'] < GATE_MIN_RET_SHORT_PCT))).fillna(False)
    return v | sel['dist'].isna() | sel['ret'].isna()


def select(out, n, held, buffer):
    """Hard sector cap at selection (production) + buy/hold buffer.

    Held names stay while they rank within buffer*n and are not vetoed; vacancies are filled
    walking down the ranking. buffer=1.0 reproduces production (re-pick the top n every cycle).
    """
    out = out[~vetoed(out)]
    order = list(out.index)
    keep_zone = set(order[:int(round(buffer * n))]) if buffer > 1.0 else set()
    picked, counts = [], {}
    for name in order:                                  # held names first, in rank order
        if name in held and name in keep_zone:
            picked.append(name); s = out.at[name, 'sector']
            counts[s] = counts.get(s, 0) + 1
    for name in order:
        if len(picked) >= n:
            break
        if name in picked:
            continue
        s = out.at[name, 'sector']
        if s != 'Other' and counts.get(s, 0) >= MAX_PER_SECTOR:
            continue
        picked.append(name); counts[s] = counts.get(s, 0) + 1
    # held names were appended first, so if dynamic_count shrank the ones ranked lowest drop out
    return out.loc[picked[:n]]


# ----------------------------------------------------------------------------- backtest
def run(P, cfg, start=280, lag=1):
    c = dict(BASE); c.update(cfg)
    hold = c['hold']; idx = P.close.index
    held, prev_w, recs, port_rets = set(), pd.Series(dtype=float), [], []
    for t in range(start, len(idx) - hold - lag - 1, hold):
        out = rank_day(P, t, c)
        if out is None:
            continue
        m = P.meta_for(t, c['regime_breadth'])
        n = max(6, min(int(round(14 * m.overall_aggression * m.pillar_multipliers['COMPASS'])), 28))

        sel = select(out, n, held, c['buffer'])

        # exposure (leverage capped at 1.0: this can only take risk off)
        if c['exposure'] == 'regime_gate':
            expo = 1.0 if m.regime_score >= MIN_REGIME_SCORE * 0.85 else 0.0
        elif c['exposure'] == 'voltarget' and c['vol_estimator'] == 'basket63' and len(sel):
            # realised vol of the equal-weight basket we are about to hold, last 63 bars up to t
            basket = P.rets.iloc[t - 62:t + 1][sel.index].mean(axis=1)
            rv = float(basket.std(ddof=1)) * np.sqrt(252)
            expo = float(min(1.0, c['target_vol'] / rv)) if rv > 0 else 1.0
        elif c['exposure'] == 'voltarget':
            k = c['vol_lookback_cycles']
            if len(port_rets) >= k:
                rv = float(np.std(port_rets[-k:], ddof=1)) * np.sqrt(CYCLES_PER_YEAR / hold)
                expo = float(min(1.0, c['target_vol'] / rv)) if rv > 0 else 1.0
            else:
                expo = 1.0
        else:
            expo = 1.0
        if c['crash_brake'] and (P.SPY_R5.iloc[t] < -0.06 or P.SPY_R10.iloc[t] < -0.10):
            expo = 0.0
        if expo <= 0:
            sel = out.head(0)
        if len(sel):
            if c['weights'] == 'invvol':
                w = (1.0 / sel['vol']).replace([np.inf, -np.inf], np.nan).fillna(0.0)
                w = w / w.sum() if w.sum() > 0 else pd.Series(1.0 / len(sel), index=sel.index)
            else:
                w = pd.Series(1.0 / len(sel), index=sel.index)
            w = w * expo
        else:
            w = pd.Series(dtype=float)

        e, x = t + lag, t + lag + hold
        r = (P.close.iloc[x][w.index] / P.close.iloc[e][w.index] - 1).fillna(0.0) if len(w) else pd.Series(dtype=float)
        gross = float((w * r).sum()) if len(w) else 0.0            # cash earns 0 unless cash_yield
        if c['cash_yield']:
            gross += max(0.0, 1.0 - float(w.sum())) * float(P.IRX.iloc[t]) * hold / 252.0
        # one-way traded fraction of the portfolio, exposure changes included
        allw = pd.concat([prev_w, w], axis=1).fillna(0.0)
        dw = (allw.iloc[:, 1] - allw.iloc[:, 0]).abs()
        turnover = float(0.5 * dw.sum())
        net = gross - 2.0 * COST_BP_PER_SIDE / 10000.0 * turnover
        recs.append(dict(date=idx[t], gross=gross, net=net, turnover=turnover, expo=expo, n=len(w),
                         traded=dw[dw > 0].to_dict()))     # {name: |dweight|}, sums to 2*turnover
        port_rets.append(gross / expo if expo > 0 else 0.0)        # unlevered basket return for the vol estimate
        held, prev_w = set(w.index), w
    return pd.DataFrame(recs).set_index('date')


def run_tranched(P, cfg, start=280, lag=1):
    """Overlapping portfolios (Jegadeesh & Titman): K tranches, each held `hold` bars, rebalanced in
    rotation every hold/K bars. The single-phase monthly result swung from 3.6% to 8.2% net on DEV
    depending on the start bar; tranching averages the phases by construction and is how a
    monthly-hold strategy is actually run. Per-step return = mean of tranche returns; only the
    tranche being rebalanced trades, so annual turnover matches a plain `hold`-bar strategy.
    """
    c = dict(BASE); c.update(cfg)
    hold, K = c['hold'], c['tranches']
    assert hold % K == 0, 'hold must be a multiple of tranches'
    step = hold // K
    idx = P.close.index
    held = [set() for _ in range(K)]
    w_k = [pd.Series(dtype=float) for _ in range(K)]
    expo_k = [1.0] * K
    recs = []
    for j, t in enumerate(range(start, len(idx) - step - lag - 1, step)):
        k = j % K
        out = rank_day(P, t, c)
        turnover, traded = 0.0, {}
        if out is not None:
            m = P.meta_for(t, c['regime_breadth'])
            n = max(6, min(int(round(14 * m.overall_aggression * m.pillar_multipliers['COMPASS'])), 28))
            sel = select(out, n, held[k], c['buffer'])
            if c['exposure'] == 'regime_gate':
                expo = 1.0 if m.regime_score >= MIN_REGIME_SCORE * 0.85 else 0.0
            elif c['exposure'] == 'voltarget' and len(sel):
                basket = P.rets.iloc[t - 62:t + 1][sel.index].mean(axis=1)
                rv = float(basket.std(ddof=1)) * np.sqrt(252)
                expo = float(min(1.0, c['target_vol'] / rv)) if rv > 0 else 1.0
            else:
                expo = 1.0
            if c['crash_brake'] and (P.SPY_R5.iloc[t] < -0.06 or P.SPY_R10.iloc[t] < -0.10):
                expo = 0.0
            if expo <= 0:
                sel = out.head(0)
            if len(sel):
                if c['weights'] == 'invvol':
                    w = (1.0 / sel['vol']).replace([np.inf, -np.inf], np.nan).fillna(0.0)
                    w = w / w.sum() if w.sum() > 0 else pd.Series(1.0 / len(sel), index=sel.index)
                else:
                    w = pd.Series(1.0 / len(sel), index=sel.index)
                w = w * expo
            else:
                w = pd.Series(dtype=float)
            allw = pd.concat([w_k[k], w], axis=1).fillna(0.0)
            dw = (allw.iloc[:, 1] - allw.iloc[:, 0]).abs() / K                          # this tranche is 1/K of the book
            turnover = float(0.5 * dw.sum())
            traded = dw[dw > 0].to_dict()
            held[k], w_k[k], expo_k[k] = set(w.index), w, expo

        e, x = t + lag, t + lag + step
        tr = []
        for kk in range(K):
            wk = w_k[kk]
            cash_r = max(0.0, 1.0 - float(wk.sum())) * float(P.IRX.iloc[t]) * step / 252.0 if c['cash_yield'] else 0.0
            if len(wk):
                r = (P.close.iloc[x][wk.index] / P.close.iloc[e][wk.index] - 1).fillna(0.0)
                tr.append(float((wk * r).sum()) + cash_r)
            else:
                tr.append(cash_r)
        gross = float(np.mean(tr))
        net = gross - 2.0 * COST_BP_PER_SIDE / 10000.0 * turnover
        recs.append(dict(date=idx[t], gross=gross, net=net, turnover=turnover,
                         expo=float(np.mean(expo_k)), n=float(np.mean([len(w) for w in w_k])),
                         distinct=float(len(set().union(*[set(w.index) for w in w_k]))),
                         traded=traded))
    return pd.DataFrame(recs).set_index('date')


def run_any(P, cfg, **kw):
    c = dict(BASE); c.update(cfg)
    return run_tranched(P, cfg, **kw) if c.get('tranches', 1) > 1 else run(P, cfg, **kw)


def step_of(cfg):
    c = dict(BASE); c.update(cfg)
    return c['hold'] // c.get('tranches', 1)


def stats(df, hold, label=''):
    py = CYCLES_PER_YEAR / hold
    def ann(r): return ((1 + r).prod() ** (py / len(r)) - 1) * 100
    def dd(r): eq = (1 + r).cumprod(); return float((eq / eq.cummax() - 1).min()) * 100
    g, nt = df['gross'], df['net']
    return dict(config=label, cycles=len(df), hold=hold,
                ann_gross=round(ann(g), 2), ann_net=round(ann(nt), 2),
                sharpe_net=round(nt.mean() / nt.std() * np.sqrt(py), 2) if nt.std() > 0 else 0.0,
                maxdd_net=round(dd(nt), 1), turnover=round(df['turnover'].mean() * 100, 1),
                exposure=round(df['expo'].mean() * 100, 0), avg_n=round(df['n'].mean(), 1),
                distinct=round(df['distinct'].mean(), 1) if 'distinct' in df else round(df['n'].mean(), 1))


def table(rows):
    pd.set_option('display.width', 220)
    print(pd.DataFrame(rows).to_string(index=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dev', action='store_true')
    ap.add_argument('--test', nargs='*')
    ap.add_argument('--full', nargs='*')
    ap.add_argument('--insample', nargs='*')
    ap.add_argument('--only', nargs='*', help='restrict --dev to these config names')
    a = ap.parse_args()

    if a.dev or a.test is not None or a.full is not None:
        P = load_panel(oos=True)
        print(f'PIT panel {P.close.shape}  {P.close.index[0].date()} .. {P.close.index[-1].date()}  '
              f'DEV < {SPLIT.date()} <= TEST')
    if a.dev:
        rows = []
        for name, cfg in CONFIGS.items():
            if a.only and name not in a.only:
                continue
            df = run_any(P, cfg)
            rows.append(stats(df[df.index < SPLIT], step_of(cfg), name))
            print('  done', name, flush=True)
        print('\nDEV 2004-2015 (net = 10 bp/side). Explore here; do not read TEST yet.')
        table(rows)
    if a.test:
        rows = []
        for name in a.test:
            df = run_any(P, CONFIGS[name])
            rows.append(stats(df[df.index >= SPLIT], step_of(CONFIGS[name]), name))
        print('\nTEST 2016-2026 - the one look. Finalists only.')
        table(rows)
    if a.full:
        for name in a.full:
            df = run_any(P, CONFIGS[name]); h = step_of(CONFIGS[name])
            table([stats(df[df.index < SPLIT], h, f'{name} DEV'), stats(df[df.index >= SPLIT], h, f'{name} TEST'),
                   stats(df, h, f'{name} ALL')])
    if a.insample is not None:
        P2 = load_panel(oos=False)
        rows = [stats(run_any(P2, CONFIGS[n]), step_of(CONFIGS[n]), f'{n} in-sample 2020-26') for n in (a.insample or ['PROD'])]
        table(rows)


if __name__ == '__main__':
    main()
