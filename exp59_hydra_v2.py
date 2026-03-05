#!/usr/bin/env python3
"""
EXP59 v2: HYDRA — Segregated Accounts with Cash Recycling
==========================================================
Each strategy has its own capital account. Cash recycling works by
transferring idle Rattlesnake cash to COMPASS's account daily, and
returning it when Rattlesnake needs it.

This preserves each strategy's internal position sizing logic exactly
as designed, while allowing idle capital to earn COMPASS returns.
"""

import pandas as pd
import numpy as np
import os

# Cash recycling parameters
MAX_COMPASS_ALLOC = 0.75  # Max 75% of total portfolio to COMPASS
BASE_COMPASS_ALLOC = 0.50
BASE_RATTLE_ALLOC = 0.50
INITIAL_CAPITAL = 100_000


def run():
    # Load standalone daily data with real exposure info
    compass = pd.read_csv('backtests/exp55_baseline_774_daily.csv', index_col=0, parse_dates=True)
    rattle = pd.read_csv('backtests/rattlesnake_daily.csv', index_col=0, parse_dates=True)

    # Returns from standalone runs
    c_ret = compass['value'].pct_change()
    r_ret = rattle['value'].pct_change()
    r_exposure = rattle['exposure']  # real exposure from rattlesnake_v1

    # Align
    df = pd.DataFrame({
        'c_ret': c_ret,
        'r_ret': r_ret,
        'r_exposure': r_exposure,
        'c_leverage': compass['leverage'],
    }).dropna()

    print(f"Period: {df.index[0].date()} to {df.index[-1].date()} ({len(df)} days)")
    years = len(df) / 252

    # Segregated accounts simulation
    c_account = INITIAL_CAPITAL * BASE_COMPASS_ALLOC  # $50K
    r_account = INITIAL_CAPITAL * BASE_RATTLE_ALLOC    # $50K
    recycled_to_c = 0.0  # cash currently loaned from R to C

    portfolio_values = []
    c_allocs = []
    r_allocs = []
    recycled_amounts = []

    for i in range(len(df)):
        date = df.index[i]
        r_exp = df['r_exposure'].iloc[i]

        total_value = c_account + r_account

        # How much of Rattlesnake's account is idle?
        r_idle = r_account * (1.0 - r_exp)

        # Max we can lend to COMPASS: cap at MAX_COMPASS_ALLOC
        max_c_account = total_value * MAX_COMPASS_ALLOC
        max_recyclable = max(0, max_c_account - c_account)
        recycle_amount = min(r_idle, max_recyclable)

        # Transfer: R -> C
        c_effective = c_account + recycle_amount
        r_effective = r_account - recycle_amount

        # Track allocation
        c_alloc_pct = c_effective / total_value if total_value > 0 else 0.5
        r_alloc_pct = r_effective / total_value if total_value > 0 else 0.5

        # Apply returns to each account
        # COMPASS: the recycled cash earns COMPASS returns (it's deployed in COMPASS)
        c_account_new = c_effective * (1 + df['c_ret'].iloc[i])
        # Rattlesnake: only its effective (non-recycled) portion earns R returns
        r_account_new = r_effective * (1 + df['r_ret'].iloc[i])

        # After returns, the "loan" is settled:
        # C returns the recycled amount (adjusted for C's return)
        # Actually, the recycled cash earned C's return, so:
        recycled_after = recycle_amount * (1 + df['c_ret'].iloc[i])
        c_account = c_account_new - recycled_after
        r_account = r_account_new + recycled_after

        total_new = c_account + r_account
        portfolio_values.append(total_new)
        c_allocs.append(c_alloc_pct)
        r_allocs.append(r_alloc_pct)
        recycled_amounts.append(recycle_amount / total_value if total_value > 0 else 0)

    # Results
    pv = pd.Series(portfolio_values, index=df.index)
    returns = pv.pct_change().dropna()
    eq = pv / pv.iloc[0]

    cagr = (pv.iloc[-1] / INITIAL_CAPITAL) ** (1/years) - 1
    maxdd = (pv / pv.cummax() - 1).min()
    sharpe = returns.mean() / returns.std() * np.sqrt(252)
    vol = returns.std() * np.sqrt(252)
    sortino = returns.mean() / returns[returns < 0].std() * np.sqrt(252)
    calmar = cagr / abs(maxdd) if maxdd != 0 else 0

    annual = pv.resample('YE').last().pct_change().dropna()

    c_alloc_series = pd.Series(c_allocs, index=df.index)
    recycled_series = pd.Series(recycled_amounts, index=df.index)

    print(f"\n{'='*70}")
    print(f"  HYDRA v2 -- Segregated Accounts with Cash Recycling")
    print(f"{'='*70}")
    print(f"  Period:       {df.index[0].date()} -> {df.index[-1].date()}")
    print(f"  Years:        {years:.1f}")
    print(f"")
    print(f"  -- PORTFOLIO --")
    print(f"  Initial:      ${INITIAL_CAPITAL:>12,.0f}")
    print(f"  Final:        ${pv.iloc[-1]:>12,.0f}")
    print(f"  CAGR:         {cagr:>11.2%}")
    print(f"  Annual Vol:   {vol:>11.2%}")
    print(f"  Max Drawdown: {maxdd:>11.2%}")
    print(f"")
    print(f"  -- RATIOS --")
    print(f"  Sharpe:       {sharpe:>11.2f}")
    print(f"  Sortino:      {sortino:>11.2f}")
    print(f"  Calmar:       {calmar:>11.2f}")

    print(f"")
    print(f"  -- CASH RECYCLING --")
    print(f"  Avg COMPASS effective: {c_alloc_series.mean():>8.1%}")
    print(f"  Avg recycled to C:     {recycled_series.mean():>8.1%}")
    print(f"  Days at max alloc:     {(c_alloc_series >= MAX_COMPASS_ALLOC - 0.001).sum()}/{len(c_alloc_series)} ({(c_alloc_series >= MAX_COMPASS_ALLOC - 0.001).mean()*100:.1f}%)")

    print(f"")
    print(f"  -- ANNUAL RETURNS --")
    for idx, ret in annual.items():
        yr = idx.year
        bar = ('+' if ret > 0 else '-') * min(int(abs(ret) * 100), 50)
        print(f"  {yr}  {ret:>+6.1%}  {bar}")

    print(f"")
    print(f"  {'METRIC':<18} {'HYDRA v2':>10} {'COMPASS':>10} {'50/50':>10} {'HYDRA v1':>10}")
    print(f"  {'-'*60}")
    print(f"  {'CAGR':<18} {cagr:>9.2%} {'12.27%':>10} {'11.87%':>10} {'10.29%':>10}")
    print(f"  {'Sharpe':<18} {sharpe:>10.2f} {'0.85':>10} {'1.09':>10} {'1.00':>10}")
    print(f"  {'Max DD':<18} {maxdd:>9.2%} {'-32.10%':>10} {'-18.57%':>10} {'-18.01%':>10}")
    print(f"  {'Volatility':<18} {vol:>9.2%} {'~14%':>10} {'~10%':>10} {'10.28%':>10}")
    print(f"")
    print(f"{'='*70}")

    # Save
    out = pd.DataFrame({
        'value': portfolio_values,
        'c_alloc': c_allocs,
        'r_alloc': r_allocs,
        'recycled_pct': recycled_amounts,
    }, index=df.index)
    os.makedirs('backtests', exist_ok=True)
    out.to_csv('backtests/hydra_v2_daily.csv')
    print(f"\nSaved: backtests/hydra_v2_daily.csv")


if __name__ == '__main__':
    print("HYDRA v2 - Segregated Accounts with Cash Recycling")
    print("=" * 60)
    run()
