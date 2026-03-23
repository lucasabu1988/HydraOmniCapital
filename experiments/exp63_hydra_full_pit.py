#!/usr/bin/env python3
"""
Experiment #63: Full HYDRA Backtest with Point-in-Time Universe
================================================================
Combines ALL 4 HYDRA strategies with proper allocations:
  - COMPASS (42.5%) — from exp61 PIT universe results
  - Rattlesnake (42.5%) — from rattlesnake_daily.csv
  - Catalyst (15% ring-fenced) — 10% cross-asset trend + 5% gold
  - EFA — idle cash overflow after recycling
  - Cash recycling: Rattlesnake idle -> COMPASS (capped 75%)

This is the TRUE survivorship-corrected HYDRA performance.
Period: 2009-01-01 to 2026-03-12 (limited by data availability)
"""

import os
import sys
import pickle
import numpy as np
import pandas as pd
import yfinance as yf
import warnings
warnings.filterwarnings('ignore')

INITIAL_CAPITAL = 100_000
SEED = 666
np.random.seed(SEED)

# HYDRA allocations (from hydra_capital.py)
W_COMPASS = 0.425
W_RATTLE = 0.425
W_CATALYST = 0.15
MAX_COMPASS_ALLOC = 0.75  # max after recycling

# Catalyst sub-allocations
CATALYST_TREND_WEIGHT = 0.667   # 10% of total
CATALYST_GOLD_WEIGHT = 0.333    # 5% of total
CATALYST_TREND_ASSETS = ['TLT', 'GLD', 'DBC']
CATALYST_GOLD = 'GLD'
SMA_PERIOD = 200

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
bt_dir = os.path.join(base_dir, 'backtests')


def load_compass_pit():
    path = os.path.join(bt_dir, 'exp61_compass_daily.csv')
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    print(f"  COMPASS PIT: {df.index[0].date()} to {df.index[-1].date()} ({len(df)} days)")
    return df


def load_rattlesnake():
    path = os.path.join(bt_dir, 'rattlesnake_daily.csv')
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    print(f"  Rattlesnake: {df.index[0].date()} to {df.index[-1].date()} ({len(df)} days)")
    return df


def load_efa():
    cache_path = os.path.join(base_dir, 'data_cache', 'efa_daily.pkl')
    if os.path.exists(cache_path):
        with open(cache_path, 'rb') as f:
            efa = pickle.load(f)
        print(f"  EFA: {efa.index[0].date()} to {efa.index[-1].date()}")
        return efa
    raw = yf.download('EFA', start='2001-01-01', end='2026-12-31', progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    efa = raw[['Close']].rename(columns={'Close': 'close'})
    efa['ret'] = efa['close'].pct_change()
    efa['sma200'] = efa['close'].rolling(200).mean()
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, 'wb') as f:
        pickle.dump(efa, f)
    print(f"  EFA: {efa.index[0].date()} to {efa.index[-1].date()}")
    return efa


def load_catalyst_assets():
    """Load TLT, GLD, DBC, GC=F for Catalyst pillar."""
    assets = {}
    for ticker in CATALYST_TREND_ASSETS + ['GC=F']:
        cache_path = os.path.join(base_dir, 'data_cache', f'catalyst_{ticker.replace("=", "_")}.pkl')
        if os.path.exists(cache_path):
            with open(cache_path, 'rb') as f:
                df = pickle.load(f)
        else:
            df = yf.download(ticker, start='1999-01-01', end='2026-12-31', progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df[['Close']].dropna()
            df.columns = ['close']
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)
            df['ret'] = df['close'].pct_change().fillna(0)
            df['sma200'] = df['close'].rolling(SMA_PERIOD).mean()
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, 'wb') as f:
                pickle.dump(df, f)
        assets[ticker] = df
        print(f"  {ticker}: {df.index[0].date()} to {df.index[-1].date()}")
    return assets


def compute_catalyst_return(date, catalyst_assets):
    """Compute daily return for the Catalyst pillar (10% trend + 5% gold)."""
    # Trend component: equal-weight among assets above SMA200
    trend_rets = []
    for ticker in CATALYST_TREND_ASSETS:
        df = catalyst_assets.get(ticker)
        if df is None or date not in df.index:
            continue
        if pd.isna(df.loc[date, 'sma200']):
            continue
        if df.loc[date, 'close'] > df.loc[date, 'sma200']:
            trend_rets.append(df.loc[date, 'ret'])

    trend_ret = np.mean(trend_rets) if trend_rets else 0.0

    # Gold component: always hold
    gold_ret = 0.0
    gld = catalyst_assets.get('GLD')
    if gld is not None and date in gld.index:
        gold_ret = gld.loc[date, 'ret']
    elif 'GC=F' in catalyst_assets and date in catalyst_assets['GC=F'].index:
        gold_ret = catalyst_assets['GC=F'].loc[date, 'ret']

    # Blend: 2/3 trend + 1/3 gold within Catalyst's 15%
    return CATALYST_TREND_WEIGHT * trend_ret + CATALYST_GOLD_WEIGHT * gold_ret


def run_full_hydra(compass_daily, rattle_daily, efa, catalyst_assets):
    """
    Run full HYDRA simulation with 4 strategies + cash recycling + EFA.

    Allocations:
      42.5% COMPASS | 42.5% Rattlesnake | 15% Catalyst (ring-fenced)
      Cash recycling: Rattle idle -> COMPASS (capped 75% total)
      EFA: remaining idle cash (regime-filtered)
    """
    c_ret = compass_daily['value'].pct_change()
    r_ret = rattle_daily['value'].pct_change()
    r_exposure = rattle_daily['exposure']

    df = pd.DataFrame({
        'c_ret': c_ret,
        'r_ret': r_ret,
        'r_exposure': r_exposure,
    }).dropna()

    # Initialize accounts
    c_account = INITIAL_CAPITAL * W_COMPASS
    r_account = INITIAL_CAPITAL * W_RATTLE
    cat_account = INITIAL_CAPITAL * W_CATALYST
    efa_value = 0.0

    portfolio_values = []
    catalyst_values = []

    for i in range(len(df)):
        date = df.index[i]
        r_exp = df['r_exposure'].iloc[i]
        total_value = c_account + r_account + cat_account + efa_value

        # ── Cash recycling: Rattle idle -> COMPASS (capped) ──
        r_idle = r_account * (1.0 - r_exp)
        max_c_account = (total_value - cat_account) * MAX_COMPASS_ALLOC  # 75% of non-Catalyst
        max_recyclable = max(0, max_c_account - c_account)
        recycle_amount = min(r_idle, max_recyclable)

        c_effective = c_account + recycle_amount
        r_effective = r_account - recycle_amount

        # ── EFA: remaining idle cash from Rattlesnake ──
        r_still_idle = r_effective * (1.0 - r_exp)

        efa_eligible = True
        if date in efa.index:
            sma = efa.loc[date, 'sma200']
            close = efa.loc[date, 'close']
            if pd.notna(sma) and close < sma:
                efa_eligible = False

        target_efa = r_still_idle if (date in efa.index and efa_eligible) else 0.0

        if target_efa > efa_value:
            buy = target_efa - efa_value
            r_effective -= buy
            efa_value += buy
        elif target_efa < efa_value:
            sell = efa_value - target_efa
            efa_value -= sell
            r_effective += sell

        # ── Apply daily returns ──
        c_ret_val = df['c_ret'].iloc[i]
        r_ret_val = df['r_ret'].iloc[i]
        cat_ret_val = compute_catalyst_return(date, catalyst_assets)

        efa_ret = 0.0
        if date in efa.index and efa_value > 0:
            efa_ret = efa.loc[date, 'ret']
            if pd.isna(efa_ret):
                efa_ret = 0.0

        c_account_new = c_effective * (1 + c_ret_val)
        r_account_new = r_effective * (1 + r_ret_val)
        cat_account_new = cat_account * (1 + cat_ret_val)
        efa_value_new = efa_value * (1 + efa_ret)

        # Return recycled capital to Rattlesnake
        recycled_after = recycle_amount * (1 + c_ret_val)
        c_account = c_account_new - recycled_after
        r_account = r_account_new + recycled_after
        cat_account = cat_account_new
        efa_value = efa_value_new

        total_new = c_account + r_account + cat_account + efa_value
        portfolio_values.append(total_new)
        catalyst_values.append(cat_account)

    pv = pd.Series(portfolio_values, index=df.index)
    cat_pv = pd.Series(catalyst_values, index=df.index)
    return pv, cat_pv


def compute_metrics(pv, label=""):
    years = len(pv) / 252
    cagr = (pv.iloc[-1] / INITIAL_CAPITAL) ** (1 / years) - 1
    returns = pv.pct_change().dropna()
    vol = returns.std() * np.sqrt(252)
    maxdd = (pv / pv.cummax() - 1).min()
    sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
    sortino_denom = returns[returns < 0].std() * np.sqrt(252)
    sortino = cagr / sortino_denom if sortino_denom > 0 else 0
    calmar = cagr / abs(maxdd) if maxdd != 0 else 0

    # Annual returns
    annual = pv.resample('YE').last().pct_change().dropna()

    return {
        'final': pv.iloc[-1],
        'cagr': cagr,
        'vol': vol,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'maxdd': maxdd,
        'years': years,
        'annual': annual,
    }


# Also run without Catalyst for comparison (50/50 like exp61)
def run_hydra_no_catalyst(compass_daily, rattle_daily, efa):
    """HYDRA without Catalyst: 50% COMPASS + 50% Rattlesnake + EFA."""
    c_ret = compass_daily['value'].pct_change()
    r_ret = rattle_daily['value'].pct_change()
    r_exposure = rattle_daily['exposure']

    df = pd.DataFrame({
        'c_ret': c_ret,
        'r_ret': r_ret,
        'r_exposure': r_exposure,
    }).dropna()

    c_account = INITIAL_CAPITAL * 0.50
    r_account = INITIAL_CAPITAL * 0.50
    efa_value = 0.0

    portfolio_values = []

    for i in range(len(df)):
        date = df.index[i]
        r_exp = df['r_exposure'].iloc[i]
        total_value = c_account + r_account + efa_value

        r_idle = r_account * (1.0 - r_exp)
        max_c_account = total_value * MAX_COMPASS_ALLOC
        max_recyclable = max(0, max_c_account - c_account)
        recycle_amount = min(r_idle, max_recyclable)

        c_effective = c_account + recycle_amount
        r_effective = r_account - recycle_amount

        r_still_idle = r_effective * (1.0 - r_exp)

        efa_eligible = True
        if date in efa.index:
            sma = efa.loc[date, 'sma200']
            close = efa.loc[date, 'close']
            if pd.notna(sma) and close < sma:
                efa_eligible = False

        target_efa = r_still_idle if (date in efa.index and efa_eligible) else 0.0

        if target_efa > efa_value:
            buy = target_efa - efa_value
            r_effective -= buy
            efa_value += buy
        elif target_efa < efa_value:
            sell = efa_value - target_efa
            efa_value -= sell
            r_effective += sell

        c_ret_val = df['c_ret'].iloc[i]
        r_ret_val = df['r_ret'].iloc[i]

        efa_ret = 0.0
        if date in efa.index and efa_value > 0:
            efa_ret = efa.loc[date, 'ret']
            if pd.isna(efa_ret):
                efa_ret = 0.0

        c_account_new = c_effective * (1 + c_ret_val)
        r_account_new = r_effective * (1 + r_ret_val)
        efa_value_new = efa_value * (1 + efa_ret)

        recycled_after = recycle_amount * (1 + c_ret_val)
        c_account = c_account_new - recycled_after
        r_account = r_account_new + recycled_after
        efa_value = efa_value_new

        total_new = c_account + r_account + efa_value
        portfolio_values.append(total_new)

    return pd.Series(portfolio_values, index=df.index)


if __name__ == "__main__":
    print("=" * 80)
    print("EXPERIMENT #63: FULL HYDRA — POINT-IN-TIME UNIVERSE")
    print("42.5% COMPASS(PIT) + 42.5% Rattlesnake + 15% Catalyst + EFA")
    print("=" * 80)

    # ── Load all components ──
    print("\n--- Loading Components ---")
    compass = load_compass_pit()
    rattle = load_rattlesnake()
    efa = load_efa()
    catalyst_assets = load_catalyst_assets()

    # ── Run full HYDRA (4 strategies) ──
    print("\n--- Running Full HYDRA (42.5/42.5/15 + EFA + recycling) ---")
    hydra_pv, catalyst_pv = run_full_hydra(compass, rattle, efa, catalyst_assets)
    hydra_m = compute_metrics(hydra_pv)

    # ── Run without Catalyst for comparison ──
    print("\n--- Running HYDRA without Catalyst (50/50 + EFA) ---")
    hydra_nocat_pv = run_hydra_no_catalyst(compass, rattle, efa)
    nocat_m = compute_metrics(hydra_nocat_pv)

    # ── Compute SPY benchmark ──
    print("\n--- Loading SPY benchmark ---")
    spy_cache = os.path.join(base_dir, 'data_cache', 'SPY_2009-01-01_2027-01-01.csv')
    if os.path.exists(spy_cache):
        spy = pd.read_csv(spy_cache, index_col=0, parse_dates=True)
    else:
        spy = yf.download('SPY', start='2009-01-01', end='2027-01-01', progress=False)
        if isinstance(spy.columns, pd.MultiIndex):
            spy.columns = [c[0] for c in spy.columns]
    # Align SPY to HYDRA dates
    common = hydra_pv.index.intersection(spy.index)
    spy_aligned = spy.loc[common, 'Close']
    spy_ret = spy_aligned / spy_aligned.iloc[0] * INITIAL_CAPITAL
    spy_years = len(spy_ret) / 252
    spy_cagr = (spy_ret.iloc[-1] / INITIAL_CAPITAL) ** (1 / spy_years) - 1
    spy_maxdd = (spy_ret / spy_ret.cummax() - 1).min()
    spy_sharpe = spy_aligned.pct_change().dropna().mean() / spy_aligned.pct_change().dropna().std() * np.sqrt(252)

    # ── Save results ──
    os.makedirs(bt_dir, exist_ok=True)
    pd.DataFrame({'value': hydra_pv}).to_csv(os.path.join(bt_dir, 'exp63_hydra_full_pit.csv'))
    pd.DataFrame({'value': hydra_nocat_pv}).to_csv(os.path.join(bt_dir, 'exp63_hydra_nocat_pit.csv'))

    # ── Results ──
    print(f"\n\n{'=' * 90}")
    print(f"  EXPERIMENT #63 — FULL HYDRA WITH POINT-IN-TIME UNIVERSE")
    print(f"{'=' * 90}")
    print(f"  Period: {hydra_pv.index[0].date()} to {hydra_pv.index[-1].date()} ({hydra_m['years']:.1f} years)")
    print(f"\n  {'METRIC':<18} {'SPY':>12} {'No Catalyst':>14} {'Full HYDRA':>14}")
    print(f"  {'-' * 60}")
    print(f"  {'Allocation':<18} {'100% SPY':>12} {'50/50+EFA':>14} {'42.5/42.5/15':>14}")
    print(f"  {'CAGR':<18} {spy_cagr:>11.2%} {nocat_m['cagr']:>13.2%} {hydra_m['cagr']:>13.2%}")
    print(f"  {'Sharpe':<18} {spy_sharpe:>11.2f} {nocat_m['sharpe']:>13.2f} {hydra_m['sharpe']:>13.2f}")
    print(f"  {'Sortino':<18} {'--':>12} {nocat_m['sortino']:>13.2f} {hydra_m['sortino']:>13.2f}")
    print(f"  {'Calmar':<18} {'--':>12} {nocat_m['calmar']:>13.2f} {hydra_m['calmar']:>13.2f}")
    print(f"  {'Max DD':<18} {spy_maxdd:>11.2%} {nocat_m['maxdd']:>13.2%} {hydra_m['maxdd']:>13.2%}")
    print(f"  {'Volatility':<18} {'--':>12} {nocat_m['vol']:>13.2%} {hydra_m['vol']:>13.2%}")
    print(f"  {'Final ($100K)':<18} ${spy_ret.iloc[-1]/1e6:>9.2f}M ${nocat_m['final']/1e6:>11.2f}M ${hydra_m['final']/1e6:>11.2f}M")
    print(f"  {'-' * 60}")
    print(f"  {'vs SPY CAGR':<18} {'--':>12} {nocat_m['cagr']-spy_cagr:>+12.2%} {hydra_m['cagr']-spy_cagr:>+12.2%}")
    print(f"  {'vs SPY Sharpe':<18} {'--':>12} {nocat_m['sharpe']-spy_sharpe:>+12.2f} {hydra_m['sharpe']-spy_sharpe:>+12.2f}")
    print(f"{'=' * 90}")

    # ── Catalyst contribution ──
    cat_cagr = (catalyst_pv.iloc[-1] / (INITIAL_CAPITAL * W_CATALYST)) ** (1 / hydra_m['years']) - 1
    print(f"\n  CATALYST PILLAR (15% allocation):")
    print(f"    CAGR: {cat_cagr:.2%}")
    print(f"    Final: ${catalyst_pv.iloc[-1]:,.0f} (from ${INITIAL_CAPITAL * W_CATALYST:,.0f})")

    # ── Annual returns ──
    print(f"\n  ANNUAL RETURNS:")
    print(f"  {'Year':<6} {'SPY':>8} {'No Cat':>10} {'Full HYDRA':>12}")
    print(f"  {'-' * 38}")
    spy_annual = spy_ret.resample('YE').last().pct_change().dropna()
    for yr in sorted(set(hydra_m['annual'].index.year)):
        h = hydra_m['annual'][hydra_m['annual'].index.year == yr]
        n = nocat_m['annual'][nocat_m['annual'].index.year == yr]
        s = spy_annual[spy_annual.index.year == yr]
        h_str = f"{h.iloc[0]:>+7.2%}" if len(h) > 0 else f"{'--':>8}"
        n_str = f"{n.iloc[0]:>+7.2%}" if len(n) > 0 else f"{'--':>8}"
        s_str = f"{s.iloc[0]:>+7.2%}" if len(s) > 0 else f"{'--':>8}"
        print(f"  {yr:<6} {s_str:>8} {n_str:>10} {h_str:>12}")

    # ── vs Dashboard production numbers ──
    print(f"\n  {'=' * 60}")
    print(f"  vs DASHBOARD PRODUCTION (survivorship-biased)")
    print(f"  {'=' * 60}")
    print(f"  {'':>18} {'Dashboard':>12} {'PIT (this)':>14} {'Delta':>10}")
    print(f"  {'-' * 55}")
    print(f"  {'CAGR':<18} {'14.50%':>12} {hydra_m['cagr']:>13.2%} {hydra_m['cagr']-0.145:>+9.2%}")
    print(f"  {'Sharpe':<18} {'1.01':>12} {hydra_m['sharpe']:>13.2f} {hydra_m['sharpe']-1.01:>+9.2f}")
    print(f"  {'Max DD':<18} {'-22.20%':>12} {hydra_m['maxdd']:>13.2%} {hydra_m['maxdd']-(-0.222):>+9.2%}")
    print(f"  {'-' * 55}")
    bias = 0.145 - hydra_m['cagr']
    print(f"  Survivorship bias cost: {bias:.2%} CAGR")

    print(f"\nSaved: backtests/exp63_hydra_full_pit.csv")
    print(f"Saved: backtests/exp63_hydra_nocat_pit.csv")
