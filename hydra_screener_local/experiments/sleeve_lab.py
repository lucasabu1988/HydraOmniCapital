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
MR_BASE = dict(top_adv=100, drop5=-0.08, rsi_max=25.0, take=0.04, stop=-0.05, max_days=8,
               pos_on=5, pos_off=2, size=0.20, vix_block=35.0, cost_bp=10.0)
MR_SLEEVES = {
    'MR':        {},                          # primary: legacy Rattlesnake v1.0 rule on the PIT top-100-ADV universe
    'MR_novix':  dict(vix_block=None),
    'MR_top200': dict(top_adv=200),
}

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


def run_sleeve_nominal(P, cfg):
    """NOMINAL accounting (pre-audit, finding D). Kept for the comparison table only."""
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


def run_sleeve(P, cfg):
    """Executable accounting (tranche_book): weights drift, only the renewed tranche trades with
    its own value, costs on every trade, cash at the T-bill, step return = change in book value."""
    from tranche_book import run_book
    c = dict(SLEEVE_BASE); c.update(cfg)
    hold, K = c['hold'], c['tranches']
    step = hold // K
    px = P.ETF
    rets = px.pct_change(fill_method=None)
    vol63 = rets.rolling(63).std() * np.sqrt(252)
    tb12 = (P.IRX / 252.0).rolling(252).sum()
    mom12 = px / px.shift(252) - 1
    sma200 = px.rolling(200).mean()

    def target(t, k, held):
        elig = px.iloc[t].notna() & px.iloc[t - 252].notna()
        names = px.columns[elig.values]
        if not len(names):
            return pd.Series(dtype=float)
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
        return w[w > 0]

    return run_book(len(px.index), K, step, 280, 1, c['cost_bp'],
                    price_at=lambda i: px.iloc[i], target_fn=target,
                    rate_at=lambda t: float(P.IRX.iloc[t]), dates=px.index)


def mix(frames, mode='equal', lookback=63, cost_bp=10.0, clip=(0.15, 0.6)):
    """Portfolio of sleeves (audit E-compliant).

    Weights for step t use only returns up to step t-1 (`shift(1)`): the old `rolling().std()`
    included the return of the very step being weighted, and changing that one return moved the
    weight from 50% to 20%. The mix is rebalanced to its target every step, so the sleeves drift
    between steps and the reset trades |target - drifted| of the book, charged at `cost_bp`
    (10 bp one-way, the stock-sleeve cost, applied to the whole shifted amount as a conservative
    all-sleeves rate). Returns the portfolio net series plus the weights used and the cost paid."""
    df = pd.concat([f['net'].rename(str(i)) for i, f in enumerate(frames)], axis=1).dropna()
    n = df.shape[1]
    if mode in ('equal', '5050'):
        w = pd.DataFrame(1.0 / n, index=df.index, columns=df.columns)
    else:
        iv = 1.0 / df.rolling(lookback).std().shift(1)         # information available before the step
        w = iv.div(iv.sum(axis=1), axis=0).fillna(1.0 / n).clip(*clip)
        w = w.div(w.sum(axis=1), axis=0)
    bp = cost_bp / 10000.0
    prev = w.iloc[0].values.copy()
    net, cost_col = [], []
    for i in range(len(df)):
        tgt = w.iloc[i].values
        realloc = float(np.abs(tgt - prev).sum()) / 2.0 if i else 0.0     # one-way fraction of the book moved
        cost = realloc * 2 * bp
        r = float((tgt * df.iloc[i].values).sum()) - cost
        net.append(r)
        cost_col.append(cost)
        grown = tgt * (1 + df.iloc[i].values)
        prev = grown / grown.sum() if grown.sum() > 0 else tgt           # drifted weights entering the next step
    out = pd.DataFrame({'gross': np.array(net) + np.array(cost_col), 'net': net, 'turnover': 0.0, 'expo': 1.0, 'n': 0.0}, index=df.index)
    for j, col in enumerate(df.columns):
        out['w_' + col] = w[col].values
    out['realloc_cost'] = cost_col
    return out


def combine(a, b, mode='5050', lookback=63):
    """Two-sleeve wrapper kept for the existing call sites; see mix()."""
    out = mix([a, b], 'equal' if mode == '5050' else 'rp', lookback, clip=(0.2, 0.8))
    out['w_a'] = out['w_0']
    return out


def combine_n(frames, mode='equal', lookback=63):
    return mix(frames, mode, lookback)


# ----------------------------------------------------------------------------- sleeve 3: short-term mean reversion
def _rsi(px, n=5):
    d = px.diff()
    up = d.clip(lower=0.0); dn = (-d).clip(lower=0.0)
    au = up.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()      # Wilder smoothing
    ad = dn.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = au / ad.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def load_vix(index):
    path = os.path.join(ETF_CACHE, 'vix.pkl')
    v = pd.read_pickle(path) if os.path.exists(path) else pd.Series(dtype=float)
    return v.reindex(index).ffill()


def run_mr(P, cfg, start=280, cost_bp=None):
    """Daily event-driven simulation of the legacy Rattlesnake rule. Returns (daily equity, step frame)."""
    from data.universe import yahoo_membership_as_of
    c = dict(MR_BASE); c.update(cfg)
    if cost_bp is not None:
        c['cost_bp'] = cost_bp
    px = P.close; idx = px.index
    ret5 = px / px.shift(5) - 1
    rsi5 = _rsi(px, 5)
    above200 = px > px.rolling(200).mean()
    spy_on = (P.spy > P.spy.rolling(200).mean()).values
    vix = load_vix(idx).values
    irx_d = (P.IRX / 252.0).values
    adv = P.ADV_USD
    mem_cache = {}
    payload = getattr(P, 'pit_payload', None)

    def members(t):
        d = idx[t].strftime('%Y-%m-%d')
        if d not in mem_cache:
            mem_cache[d] = set(yahoo_membership_as_of(d, payload)) if payload else set(px.columns)
        return mem_cache[d]

    equity = 1.0; cash = 1.0
    pos = {}            # ticker -> dict(shares, entry_px, entry_t)
    pending = []        # tickers signalled at t, bought at t+1
    eq = np.full(len(idx), np.nan)
    traded = np.zeros(len(idx))
    npos = np.zeros(len(idx))
    bp = c['cost_bp'] / 10000.0
    for t in range(start, len(idx) - 1):
        row = px.iloc[t]
        for tk in pending:                                   # 1) buy yesterday's signals at today's close
            p0 = row.get(tk, np.nan)
            if not np.isfinite(p0) or tk in pos:
                continue
            amt = min(c['size'] * equity, cash)
            if amt <= 0:
                continue
            pos[tk] = dict(shares=amt * (1 - bp) / p0, entry_px=p0, entry_t=t)
            cash -= amt; traded[t] += amt
        pending = []
        for tk in list(pos):                                 # 2) exits at today's close
            p0 = row.get(tk, np.nan)
            if not np.isfinite(p0):
                continue
            r = p0 / pos[tk]['entry_px'] - 1
            if r >= c['take'] or r <= c['stop'] or (t - pos[tk]['entry_t']) >= c['max_days']:
                val = pos[tk]['shares'] * p0
                cash += val * (1 - bp); traded[t] += val
                del pos[tk]
        cash *= (1 + irx_d[t])                               # 3) mark to market, cash earns T-bill
        mtm = 0.0
        for tk, v in pos.items():
            p0 = row.get(tk, np.nan)
            mtm += v['shares'] * (p0 if np.isfinite(p0) else v['entry_px'])
        equity = cash + mtm
        eq[t] = equity; npos[t] = len(pos)
        if c['vix_block'] is not None and np.isfinite(vix[t]) and vix[t] > c['vix_block']:
            continue                                         # 4) signals at today's close for tomorrow
        cap = c['pos_on'] if spy_on[t] else c['pos_off']
        slots = cap - len(pos)
        if slots <= 0:
            continue
        mem = members(t)
        a = adv.iloc[t]
        elig = row.notna() & (row >= 5.0) & a.notna() & row.index.isin(mem)
        top = a[elig].nlargest(c['top_adv']).index
        sig = (ret5.iloc[t][top] <= c['drop5']) & (rsi5.iloc[t][top] < c['rsi_max']) & above200.iloc[t][top]
        cands = rsi5.iloc[t][top][sig.fillna(False)].sort_values()
        pending = [tk for tk in cands.index if tk not in pos][:slots]
    eq_s = pd.Series(eq, index=idx)
    recs = []                                                # 5-bar grid, entry convention close t+1 -> close t+6
    for t in range(start, len(idx) - 5 - 1 - 1, 5):
        e, x = t + 1, t + 1 + 5
        if not (np.isfinite(eq[e]) and np.isfinite(eq[x])):
            continue
        r = eq[x] / eq[e] - 1
        recs.append(dict(date=idx[t], gross=r, net=r, turnover=traded[e + 1:x + 1].sum() / eq[e] / 2.0,
                         expo=float(1.0), n=float(npos[e:x + 1].mean())))
    return eq_s, pd.DataFrame(recs).set_index('date')


def mr_with_gross(P, cfg):
    """net run + a zero-cost twin so stats() shows gross and net."""
    _, net = run_mr(P, cfg)
    _, gross = run_mr(P, cfg, cost_bp=0.0)
    out = net.copy()
    out['gross'] = gross['gross'].reindex(out.index)
    return out


def sleeve3_main():
    P = L.load_panel(oos=True)
    P.ETF = load_etfs(P.close.index)
    cache = os.path.join(ETF_CACHE, 'steps_t20_etf_exec.pkl')
    if os.path.exists(cache):
        t20, etf = pd.read_pickle(cache)
    else:
        t20 = L.run_any(P, dict(L.CONFIGS['T20'], cash_yield=True))
        etf = run_sleeve(P, SLEEVES['ETF'])
        pd.to_pickle((t20, etf), cache)
    print('  T20/ETF step frames ready', flush=True)

    def rows(df, name):
        return [L.stats(df[df.index < L.SPLIT], 5, f'{name} DEV'), L.stats(df[df.index >= L.SPLIT], 5, f'{name} TEST'), L.stats(df, 5, f'{name} ALL')]

    res, out = {}, []
    for name, cfg in MR_SLEEVES.items():
        res[name] = mr_with_gross(P, cfg)
        out += rows(res[name], name)
        print('  done', name, flush=True)
    print('\nMEAN-REVERSION SLEEVE (legacy Rattlesnake rule, PIT top-ADV universe), net 10 bp/side, cash at T-bill')
    L.table(out)

    mr = res['MR']
    p2 = combine(t20, etf, '5050')
    common = pd.concat([t20['net'].rename('T20'), etf['net'].rename('ETF'), mr['net'].rename('MR'), p2['net'].rename('P_5050')], axis=1).dropna()
    print('\nweekly net correlations (ALL):'); print(common.corr().round(2).to_string())
    print('MR vs P_5050: DEV %.2f  TEST %.2f' % (common[common.index < L.SPLIT][['MR', 'P_5050']].corr().iloc[0, 1],
                                                 common[common.index >= L.SPLIT][['MR', 'P_5050']].corr().iloc[0, 1]))
    print('\nPORTFOLIOS')
    out = rows(p2, 'P_5050 (T20+ETF)')
    out += rows(combine_n([t20, etf, mr], 'equal'), 'P3_equal')
    out += rows(combine_n([t20, etf, mr], 'rp'), 'P3_rp')
    L.table(out)
    p3 = combine_n([t20, etf, mr], 'rp')
    print('\nrisk-parity mean weights T20/ETF/MR: %.2f / %.2f / %.2f' % (p3['w_0'].mean(), p3['w_1'].mean(), p3['w_2'].mean()))
    yr = pd.DataFrame({'T20': t20['net'], 'ETF': etf['net'], 'MR': mr['net'], 'P3_equal': combine_n([t20, etf, mr], 'equal')['net']}).dropna()
    print('\nyearly net (%)'); print(yr.groupby(yr.index.year).apply(lambda g: ((1 + g).prod() - 1) * 100).round(1).to_string())
    pd.to_pickle(res, os.path.join(ETF_CACHE, 'steps_mr.pkl'))


def main():
    if '--mr' in sys.argv:
        return sleeve3_main()
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
