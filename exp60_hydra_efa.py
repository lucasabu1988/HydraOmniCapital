#!/usr/bin/env python3
"""
EXP60: HYDRA Third Pillar — Idle Cash into EFA
===============================================
Extends HYDRA v2 (COMPASS + Rattlesnake with cash recycling) by parking
ALL idle cash in EFA (iShares MSCI EAFE — developed ex-US equities).

Two variants:
  A) Pure:           All idle cash -> EFA, no filter
  B) Regime-filtered: Only buy EFA when EFA > SMA(200)

Mechanics:
  - COMPASS and Rattlesnake run as normal (returns from standalone backtests)
  - After cash recycling (idle R cash -> COMPASS), remaining idle cash buys EFA
  - When active strategies need capital, EFA is sold first
  - EFA is never sold voluntarily

Baseline: HYDRA v2 — 13.28% CAGR, -23.49% MaxDD, 1.04 Sharpe
"""

import pandas as pd
import numpy as np
import yfinance as yf
import os
import pickle

# ── Parameters ──────────────────────────────────────────────────────────
INITIAL_CAPITAL = 100_000
MAX_COMPASS_ALLOC = 0.75      # Max 75% of total to COMPASS (same as HYDRA v2)
BASE_COMPASS_ALLOC = 0.50
BASE_RATTLE_ALLOC = 0.50
EFA_SMA_PERIOD = 200          # For variant B
SEED = 666

np.random.seed(SEED)


def load_efa_data():
    """Load EFA daily data, use cache if available."""
    cache_path = 'data_cache/efa_daily.pkl'
    os.makedirs('data_cache', exist_ok=True)

    if os.path.exists(cache_path):
        with open(cache_path, 'rb') as f:
            efa = pickle.load(f)
        print(f"  EFA loaded from cache: {efa.index[0].date()} to {efa.index[-1].date()}")
        return efa

    print("  Downloading EFA data from yfinance...")
    raw = yf.download('EFA', start='2001-01-01', end='2026-12-31', progress=False)

    # Handle multi-level columns from yfinance
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    efa = raw[['Close']].rename(columns={'Close': 'close'})
    efa['ret'] = efa['close'].pct_change()
    efa['sma200'] = efa['close'].rolling(EFA_SMA_PERIOD).mean()

    with open(cache_path, 'wb') as f:
        pickle.dump(efa, f)
    print(f"  EFA cached: {efa.index[0].date()} to {efa.index[-1].date()}")
    return efa


def run_variant(df, efa, variant_name, use_regime_filter=False):
    """
    Run HYDRA + EFA simulation.

    df: aligned DataFrame with c_ret, r_ret, r_exposure columns
    efa: EFA DataFrame with ret, sma200 columns
    """
    c_account = INITIAL_CAPITAL * BASE_COMPASS_ALLOC
    r_account = INITIAL_CAPITAL * BASE_RATTLE_ALLOC
    efa_value = 0.0

    portfolio_values = []
    c_allocs = []
    r_allocs = []
    efa_allocs = []
    recycled_amounts = []
    efa_invested_days = 0

    for i in range(len(df)):
        date = df.index[i]
        r_exp = df['r_exposure'].iloc[i]

        total_value = c_account + r_account + efa_value

        # ── Step 1: Cash recycling (R -> C), same as HYDRA v2 ──
        r_idle = r_account * (1.0 - r_exp)
        max_c_account = total_value * MAX_COMPASS_ALLOC
        max_recyclable = max(0, max_c_account - c_account)
        recycle_amount = min(r_idle, max_recyclable)

        c_effective = c_account + recycle_amount
        r_effective = r_account - recycle_amount

        # ── Step 2: Calculate remaining idle cash ──
        r_still_idle = r_effective * (1.0 - r_exp)
        idle_cash = r_still_idle

        # ── Step 3: EFA allocation ──
        efa_eligible = True
        if use_regime_filter and date in efa.index:
            sma = efa.loc[date, 'sma200']
            close = efa.loc[date, 'close']
            if pd.notna(sma) and close < sma:
                efa_eligible = False

        if date in efa.index and efa_eligible:
            target_efa = idle_cash
        else:
            target_efa = 0.0

        # Adjust EFA position
        if target_efa > efa_value:
            buy_amount = target_efa - efa_value
            r_effective -= buy_amount
            efa_value += buy_amount
        elif target_efa < efa_value:
            sell_amount = efa_value - target_efa
            efa_value -= sell_amount
            r_effective += sell_amount

        # ── Step 4: Apply daily returns ──
        c_ret = df['c_ret'].iloc[i]
        r_ret = df['r_ret'].iloc[i]

        if date in efa.index and efa_value > 0:
            efa_ret = efa.loc[date, 'ret']
            if pd.isna(efa_ret):
                efa_ret = 0.0
            efa_invested_days += 1
        else:
            efa_ret = 0.0

        c_account_new = c_effective * (1 + c_ret)
        r_account_new = r_effective * (1 + r_ret)
        efa_value_new = efa_value * (1 + efa_ret)

        recycled_after = recycle_amount * (1 + c_ret)
        c_account = c_account_new - recycled_after
        r_account = r_account_new + recycled_after
        efa_value = efa_value_new

        total_new = c_account + r_account + efa_value
        portfolio_values.append(total_new)
        c_allocs.append(c_effective / total_value if total_value > 0 else 0)
        r_allocs.append(r_effective / total_value if total_value > 0 else 0)
        efa_allocs.append(efa_value / total_new if total_new > 0 else 0)
        recycled_amounts.append(recycle_amount / total_value if total_value > 0 else 0)

    # ── Results ──
    pv = pd.Series(portfolio_values, index=df.index)
    returns = pv.pct_change().dropna()
    years = len(df) / 252

    cagr = (pv.iloc[-1] / INITIAL_CAPITAL) ** (1 / years) - 1
    maxdd = (pv / pv.cummax() - 1).min()
    sharpe = returns.mean() / returns.std() * np.sqrt(252)
    vol = returns.std() * np.sqrt(252)
    sortino = returns.mean() / returns[returns < 0].std() * np.sqrt(252)
    calmar = cagr / abs(maxdd) if maxdd != 0 else 0

    annual = pv.resample('YE').last().pct_change().dropna()

    efa_alloc_series = pd.Series(efa_allocs, index=df.index)

    print(f"\n{'=' * 70}")
    print(f"  HYDRA + EFA — Variant {variant_name}")
    print(f"{'=' * 70}")
    print(f"  Period:       {df.index[0].date()} -> {df.index[-1].date()}")
    print(f"  Years:        {years:.1f}")
    print()
    print(f"  -- PORTFOLIO --")
    print(f"  Initial:      ${INITIAL_CAPITAL:>12,.0f}")
    print(f"  Final:        ${pv.iloc[-1]:>12,.0f}")
    print(f"  CAGR:         {cagr:>11.2%}")
    print(f"  Annual Vol:   {vol:>11.2%}")
    print(f"  Max Drawdown: {maxdd:>11.2%}")
    print()
    print(f"  -- RATIOS --")
    print(f"  Sharpe:       {sharpe:>11.2f}")
    print(f"  Sortino:      {sortino:>11.2f}")
    print(f"  Calmar:       {calmar:>11.2f}")
    print()
    print(f"  -- EFA ALLOCATION --")
    print(f"  Avg EFA %:         {efa_alloc_series.mean():>8.1%}")
    print(f"  Max EFA %:         {efa_alloc_series.max():>8.1%}")
    print(f"  Days invested:     {efa_invested_days}/{len(df)} ({efa_invested_days/len(df)*100:.1f}%)")
    print()
    print(f"  -- ANNUAL RETURNS --")
    for idx, ret in annual.items():
        yr = idx.year
        bar = ('+' if ret > 0 else '-') * min(int(abs(ret) * 100), 50)
        print(f"  {yr}  {ret:>+6.1%}  {bar}")

    out = pd.DataFrame({
        'value': portfolio_values,
        'c_alloc': c_allocs,
        'r_alloc': r_allocs,
        'efa_alloc': efa_allocs,
        'recycled_pct': recycled_amounts,
    }, index=df.index)

    return pv, cagr, maxdd, sharpe, vol, sortino, calmar, out


def main():
    print("EXP60: HYDRA Third Pillar — Idle Cash into EFA")
    print("=" * 60)

    # ── Load data ──
    print("\nLoading data...")
    compass = pd.read_csv('backtests/exp55_baseline_774_daily.csv',
                          index_col=0, parse_dates=True)
    rattle = pd.read_csv('backtests/rattlesnake_daily.csv',
                         index_col=0, parse_dates=True)
    efa = load_efa_data()

    c_ret = compass['value'].pct_change()
    r_ret = rattle['value'].pct_change()
    r_exposure = rattle['exposure']

    df = pd.DataFrame({
        'c_ret': c_ret,
        'r_ret': r_ret,
        'r_exposure': r_exposure,
    }).dropna()

    print(f"  Aligned period: {df.index[0].date()} to {df.index[-1].date()} ({len(df)} days)")
    print(f"  EFA available:  {efa.index[0].date()} to {efa.index[-1].date()}")

    # ── Variant A: Pure (no filter) ──
    pv_a, cagr_a, maxdd_a, sharpe_a, vol_a, sortino_a, calmar_a, out_a = \
        run_variant(df, efa, "A: Pure (all idle cash -> EFA)", use_regime_filter=False)

    # ── Variant B: Regime-filtered (EFA > SMA200) ──
    pv_b, cagr_b, maxdd_b, sharpe_b, vol_b, sortino_b, calmar_b, out_b = \
        run_variant(df, efa, "B: Regime-filtered (EFA > SMA200)", use_regime_filter=True)

    # ── Save outputs ──
    os.makedirs('backtests', exist_ok=True)
    out_a.to_csv('backtests/exp60_hydra_efa_pure.csv')
    out_b.to_csv('backtests/exp60_hydra_efa_filtered.csv')

    # ── Comparison table ──
    print(f"\n\n{'=' * 70}")
    print(f"  EXP60 COMPARISON TABLE")
    print(f"{'=' * 70}")
    print(f"  {'METRIC':<18} {'HYDRA v2':>12} {'+ EFA Pure':>12} {'+ EFA Filter':>12}")
    print(f"  {'-' * 56}")
    print(f"  {'CAGR':<18} {'13.28%':>12} {cagr_a:>11.2%} {cagr_b:>11.2%}")
    print(f"  {'Max DD':<18} {'-23.49%':>12} {maxdd_a:>11.2%} {maxdd_b:>11.2%}")
    print(f"  {'Sharpe':<18} {'1.04':>12} {sharpe_a:>11.2f} {sharpe_b:>11.2f}")
    print(f"  {'Sortino':<18} {'--':>12} {sortino_a:>11.2f} {sortino_b:>11.2f}")
    print(f"  {'Calmar':<18} {'--':>12} {calmar_a:>11.2f} {calmar_b:>11.2f}")
    print(f"  {'Volatility':<18} {'--':>12} {vol_a:>11.2%} {vol_b:>11.2%}")
    print(f"  {'Final Value':<18} {'--':>12} ${pv_a.iloc[-1]:>10,.0f} ${pv_b.iloc[-1]:>10,.0f}")
    print(f"{'=' * 70}")

    # ── Verdict ──
    print(f"\n  VERDICT:")
    for name, cagr, maxdd, sharpe in [
        ("A: Pure", cagr_a, maxdd_a, sharpe_a),
        ("B: Filtered", cagr_b, maxdd_b, sharpe_b),
    ]:
        if cagr >= 0.145 and maxdd > -0.25:
            verdict = "STRONG PASS"
        elif cagr >= 0.14 and sharpe >= 1.04:
            verdict = "PASS"
        elif cagr >= 0.1328:
            verdict = "MARGINAL"
        else:
            verdict = "FAIL"
        print(f"    {name}: {verdict} (CAGR={cagr:.2%}, MaxDD={maxdd:.2%}, Sharpe={sharpe:.2f})")

    print(f"\nSaved: backtests/exp60_hydra_efa_pure.csv")
    print(f"Saved: backtests/exp60_hydra_efa_filtered.csv")


if __name__ == '__main__':
    main()
