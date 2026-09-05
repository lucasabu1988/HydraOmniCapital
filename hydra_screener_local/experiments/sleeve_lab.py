"""
Sleeve lab: ETF trend-following sleeve + combination with T20.

Pre-registered in .comms/claude-sleeves-design-2026-09-06.md before any number was looked at.
Reuses redesign_lab's PIT panel (trading calendar, T-bill, T20 runner). Own ETF cache in
_sweep_cache_etf/ (yfinance, auto_adjust). Same DEV/TEST split, same reporting.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import redesign_lab as L  # noqa: E402

ETF_CACHE = os.path.join(HERE, '_sweep_cache_etf')
UNIVERSE = ['SPY', 'QQQ', 'IWM', 'EFA', 'EEM', 'TLT', 'IEF', 'GLD', 'DBC', 'VNQ']
ETF_COST_BP = 5.0

SLEEVE_BASE = dict(signal='tsmom12', weights='invvol', hold=20, tranches=4, cost_bp=ETF_COST_BP)
SLEEVES = {
    'ETF':          {},                                    # primary
    'ETF_ew':       dict(weights='equal'),
    'ETF_sma':      dict(signal='sma200'),
    'ETF_sma_ew':   dict(signal='sma200', weights='equal'),
    'ETF_10bp':     dict(cost_bp=10.0),
}


def load_etfs(index):
    os.makedirs(ETF_CACHE, exist_ok=True)
    path = os.path.join(ETF_CACHE, 'close.pkl')
    if os.path.exists(path):
        px = pd.read_pickle(path)
    else:
        import yfinance as yf
        d = yf.download(UNIVERSE, start='2003-01-01', progress=False, auto_adjust=True, threads=True)
        px = d['Close'] if 'Close' in d else d
        px = px[UNIVERSE].sort_index()
        px.to_pickle(path)
    px.index = pd.to_datetime(px.index).tz_localize(None)
    return px.reindex(index).ffill(limit=3)


def run_sleeve(P, cfg):
    """Same overlapping-tranche machinery as T20; per step = mean of tranche returns."""
    c = dict(SLEEVE_BASE); c.update(cfg)
    hold, K = c['hold'], c['tranches']
    step = hold // K
    px = P.ETF
    rets = px.pct_change(fill_method=None)
    vol63 = rets.rolling(63).std() * np.sqrt(252)
    irx_daily = P.IRX / 252.0
    tb12 = irx_daily.rolling(252).sum()
    mom12 = px / px.shift(252) - 1
    sma200 = px.rolling(200).mean()
    idx = px.index
    w_k = [pd.Series(dtype=float) for _ in range(K)]
    recs = []
    start = 280
    for j, t in enumerate(range(start, len(idx) - step - 1 - 1, step)):
        k = j % K
        elig = px.iloc[t].notna() & px.iloc[t - 252].notna()
        names = px.columns[elig.values]
        if c['signal'] == 'tsmom12':
            on = mom12.iloc[t][names] - tb12.iloc[t] > 0
        else:
            on = px.iloc[t][names] > sma200.iloc[t][names]
        if c['weights'] == 'invvol':
            iv = (1.0 / vol63.iloc[t][names]).replace([np.inf, -np.inf], np.nan).fillna(0.0)
            base = iv / iv.sum() if iv.sum() > 0 else pd.Series(1.0 / len(names), index=names)
        else:
            base = pd.Series(1.0 / len(names), index=names)
        w = (base * on.astype(float)).astype(float)
        w = w[w > 0]
        allw = pd.concat([w_k[k], w], axis=1).fillna(0.0)
        dw = (allw.iloc[:, 1] - allw.iloc[:, 0]).abs() / K
        turnover = float(0.5 * dw.sum())
        w_k[k] = w
        e, x = t + 1, t + 1 + step                      # lag 1, same as the stock lab
        tr = []
        for kk in range(K):
            wk = w_k[kk]
            cash_r = max(0.0, 1.0 - float(wk.sum())) * float(P.IRX.iloc[t]) * step / 252.0
            if len(wk):
                r = (px.iloc[x][wk.index] / px.iloc[e][wk.index] - 1).fillna(0.0)
                tr.append(float((wk * r).sum()) + cash_r)
            else:
                tr.append(cash_r)
        gross = float(np.mean(tr))
        net = gross - 2.0 * c['cost_bp'] / 10000.0 * turnover
        expo = float(np.mean([wk.sum() for wk in w_k]))
        recs.append(dict(date=idx[t], gross=gross, net=net, turnover=turnover, expo=expo,
                         n=float(np.mean([len(wk) for wk in w_k])), distinct=float(len(set().union(*[set(wk.index) for wk in w_k])))))
    return pd.DataFrame(recs).set_index('date')


def combine(a, b, mode='5050', lookback=63):
    """Weekly net series of two sleeves on common dates -> portfolio net series (weights rebalanced each step)."""
    df = pd.concat([a['net'].rename('a'), b['net'].rename('b')], axis=1).dropna()
    if mode == '5050':
        w = pd.Series(0.5, index=df.index)
    else:  # inverse-vol risk parity on trailing steps, 0.5 until enough history
        va = df['a'].rolling(lookback).std(); vb = df['b'].rolling(lookback).std()
        w = (1 / va) / (1 / va + 1 / vb)
        w = w.fillna(0.5).clip(0.2, 0.8)
    net = w * df['a'] + (1 - w) * df['b']
    out = pd.DataFrame({'gross': net, 'net': net, 'turnover': 0.0, 'expo': 1.0, 'n': 0.0})
    out['w_a'] = w
    return out


def main():
    P = L.load_panel(oos=True)
    P.ETF = load_etfs(P.close.index)
    print('ETF panel', P.ETF.shape, 'first valid:', {c: str(P.ETF[c].first_valid_index().date()) for c in P.ETF.columns}, flush=True)

    res = {}
    for name, cfg in SLEEVES.items():
        res[name] = run_sleeve(P, cfg)
        print('  done', name, flush=True)
    t20 = L.run_any(P, dict(L.CONFIGS['T20'], cash_yield=True))
    print('  done T20 (cash at T-bill)', flush=True)

    def rows(df, name):
        return [L.stats(df[df.index < L.SPLIT], 5, f'{name} DEV'), L.stats(df[df.index >= L.SPLIT], 5, f'{name} TEST'), L.stats(df, 5, f'{name} ALL')]

    print('\nETF SLEEVE (pre-registered configs), net of', ETF_COST_BP, 'bp/side unless stated; cash at T-bill')
    out = []
    for name, df in res.items():
        out += rows(df, name)
    L.table(out)

    print('\nT20 with cash at T-bill (reference)')
    L.table(rows(t20, 'T20_cy'))

    etf = res['ETF']
    common = pd.concat([t20['net'].rename('T20'), etf['net'].rename('ETF')], axis=1).dropna()
    print('\nweekly net correlation T20-ETF: ALL %.2f  DEV %.2f  TEST %.2f' % (
        common.corr().iloc[0, 1], common[common.index < L.SPLIT].corr().iloc[0, 1], common[common.index >= L.SPLIT].corr().iloc[0, 1]))
    for yr, g in common.groupby(common.index.year):
        pass

    print('\nPORTFOLIO (pre-registered combinations)')
    out = []
    for mode, label in (('5050', 'P_5050'), ('rp', 'P_rp')):
        port = combine(t20, etf, mode)
        out += rows(port, label)
    L.table(out)
    port = combine(t20, etf, 'rp')
    print('\nrisk-parity weight on T20: mean %.2f  min %.2f  max %.2f' % (port['w_a'].mean(), port['w_a'].min(), port['w_a'].max()))

    print('\nyearly net (%), T20 / ETF / 50-50')
    p5 = combine(t20, etf, '5050')
    yr = pd.DataFrame({'T20': t20['net'], 'ETF': etf['net'], 'P_5050': p5['net']}).dropna()
    yearly = yr.groupby(yr.index.year).apply(lambda g: ((1 + g).prod() - 1) * 100).round(1)
    print(yearly.to_string())


if __name__ == '__main__':
    main()
