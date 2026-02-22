#!/usr/bin/env python3
"""
COMBINED PORTFOLIO: COMPASS + RATTLESNAKE (Cyclic Rotation)
============================================================
RATTLESNAKE se activa cada 6 anos en ciclos ON/OFF.
Cuando RATTLESNAKE esta OFF, 100% COMPASS.
Cuando RATTLESNAKE esta ON, split entre ambos.

Prueba multiples configuraciones:
- Variante A: RATTLE ON primeros 6y, OFF siguientes 6y, etc.
- Variante B: RATTLE OFF primeros 6y, ON siguientes 6y, etc.
- Variante C: Diferentes splits cuando RATTLE esta ON (50/50, 70/30, etc.)
"""

import numpy as np
import pandas as pd
import warnings

warnings.filterwarnings('ignore')

INITIAL_CAPITAL = 100_000
RISK_FREE = 0.02
CYCLE_YEARS = 6


def load_data():
    compass_df = pd.read_csv('backtests/v8_compass_daily.csv', parse_dates=['date'])
    compass_df = compass_df.set_index('date')[['value']].rename(columns={'value': 'compass'})

    rattle_df = pd.read_csv('backtests/rattlesnake_daily.csv', parse_dates=['date'])
    rattle_df = rattle_df.set_index('date')

    # Align
    common = compass_df.index.intersection(rattle_df.index)
    c = compass_df.loc[common, 'compass']
    r = rattle_df.loc[common, 'rattlesnake']

    # Normalize to start at same value
    c_norm = c / c.iloc[0] * INITIAL_CAPITAL
    r_norm = r / r.iloc[0] * INITIAL_CAPITAL

    return c_norm, r_norm


def compute_metrics(equity, name="Strategy"):
    daily_ret = equity.pct_change().dropna()
    years = len(daily_ret) / 252
    final = equity.iloc[-1]
    initial = equity.iloc[0]
    cagr = (final / initial) ** (1 / years) - 1
    vol = daily_ret.std() * np.sqrt(252)
    sharpe = (cagr - RISK_FREE) / vol if vol > 0 else 0

    cummax = equity.cummax()
    dd = (equity / cummax) - 1
    max_dd = dd.min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    downside = daily_ret[daily_ret < 0].std() * np.sqrt(252)
    sortino = (cagr - RISK_FREE) / downside if downside > 0 else 0

    monthly = equity.resample('ME').last()
    monthly_ret = monthly.pct_change().dropna()
    monthly_win = (monthly_ret > 0).mean()

    yearly = equity.resample('YE').last()
    yearly_ret = yearly.pct_change().dropna()

    return {
        'name': name,
        'final': final, 'cagr': cagr, 'vol': vol,
        'sharpe': sharpe, 'sortino': sortino, 'calmar': calmar,
        'max_dd': max_dd, 'monthly_win': monthly_win,
        'worst_year': yearly_ret.min() if len(yearly_ret) > 0 else 0,
        'yearly_ret': yearly_ret
    }


def build_cyclic_portfolio(c_ret, r_ret, dates, rattle_on_first, split_compass, split_rattle, label):
    """
    Build equity curve where RATTLESNAKE cycles ON/OFF every 6 years.
    When ON: split_compass% COMPASS + split_rattle% RATTLESNAKE
    When OFF: 100% COMPASS
    """
    start_year = dates[0].year
    combined_ret = pd.Series(index=dates, dtype=float)

    for idx, date in enumerate(dates):
        if idx == 0:
            combined_ret.iloc[0] = 0
            continue

        years_elapsed = date.year - start_year
        cycle_num = years_elapsed // CYCLE_YEARS  # 0, 1, 2, 3...

        if rattle_on_first:
            rattle_active = (cycle_num % 2 == 0)  # ON in cycles 0, 2, 4...
        else:
            rattle_active = (cycle_num % 2 == 1)  # ON in cycles 1, 3, 5...

        cr = c_ret.iloc[idx] if idx < len(c_ret) else 0
        rr = r_ret.iloc[idx] if idx < len(r_ret) else 0

        if pd.isna(cr): cr = 0
        if pd.isna(rr): rr = 0

        if rattle_active:
            combined_ret.iloc[idx] = split_compass * cr + split_rattle * rr
        else:
            combined_ret.iloc[idx] = cr  # 100% COMPASS

    equity = (1 + combined_ret).cumprod() * INITIAL_CAPITAL
    return equity


def main():
    print("=" * 70)
    print("  CYCLIC ROTATION: COMPASS + RATTLESNAKE (6-Year Cycles)")
    print("=" * 70)

    c_norm, r_norm = load_data()
    c_ret = c_norm.pct_change().fillna(0)
    r_ret = r_norm.pct_change().fillna(0)
    dates = c_norm.index

    start_year = dates[0].year
    end_year = dates[-1].year

    # Show which years are ON/OFF for each variant
    print(f"\n  Period: {start_year}-{end_year}")
    print(f"\n  Cycle A (RATTLE ON first):")
    for y in range(start_year, end_year + 1):
        cycle = (y - start_year) // CYCLE_YEARS
        status = "RATTLE ON " if cycle % 2 == 0 else "COMPASS only"
        if y == start_year or (y - start_year) % CYCLE_YEARS == 0:
            print(f"    {y}-{min(y + CYCLE_YEARS - 1, end_year)}: {status}")

    print(f"\n  Cycle B (RATTLE ON second):")
    for y in range(start_year, end_year + 1):
        cycle = (y - start_year) // CYCLE_YEARS
        status = "COMPASS only" if cycle % 2 == 0 else "RATTLE ON "
        if y == start_year or (y - start_year) % CYCLE_YEARS == 0:
            print(f"    {y}-{min(y + CYCLE_YEARS - 1, end_year)}: {status}")

    # ── BUILD ALL VARIANTS ──
    configs = [
        # (rattle_on_first, compass_split, rattle_split, label)
        (None, 1.0, 0.0, "100% COMPASS (baseline)"),
        (None, 0.0, 1.0, "100% RATTLESNAKE"),
        (None, 0.5, 0.5, "Always 50/50"),

        # Cycle A: RATTLE ON in years 0-5, 12-17, 24-29...
        (True, 0.5, 0.5, "CycleA 50/50 when ON"),
        (True, 0.6, 0.4, "CycleA 60/40 when ON"),
        (True, 0.7, 0.3, "CycleA 70/30 when ON"),

        # Cycle B: RATTLE ON in years 6-11, 18-23...
        (False, 0.5, 0.5, "CycleB 50/50 when ON"),
        (False, 0.6, 0.4, "CycleB 60/40 when ON"),
        (False, 0.7, 0.3, "CycleB 70/30 when ON"),
    ]

    results = []
    for rattle_first, wc, wr, label in configs:
        if rattle_first is None:
            # Static allocation (no cycling)
            combined_ret = wc * c_ret + wr * r_ret
            equity = (1 + combined_ret).cumprod() * INITIAL_CAPITAL
        else:
            equity = build_cyclic_portfolio(c_ret, r_ret, dates, rattle_first, wc, wr, label)

        m = compute_metrics(equity, label)
        results.append(m)

    # ── RESULTS TABLE ──
    print(f"\n{'='*70}")
    print(f"  RESULTS SWEEP")
    print(f"{'='*70}")
    print(f"\n  {'Strategy':<28} {'CAGR':>7} {'Sharpe':>7} {'Sortino':>8} {'MaxDD':>8} {'Calmar':>7} {'$Final':>12}")
    print(f"  {'-'*79}")

    best_sharpe = max(results, key=lambda m: m['sharpe'])
    best_calmar = max(results, key=lambda m: m['calmar'])

    for m in results:
        markers = []
        if m == best_sharpe: markers.append('*S')
        if m == best_calmar: markers.append('*C')
        marker = ' '.join(markers)
        print(f"  {m['name']:<28} {m['cagr']:>6.2%} {m['sharpe']:>7.2f} {m['sortino']:>8.2f} {m['max_dd']:>7.2%} {m['calmar']:>7.2f} ${m['final']:>10,.0f}  {marker}")

    # ── YEARLY DETAIL FOR BEST CYCLIC ──
    # Find best cyclic variant
    cyclic_results = [m for m in results if 'Cycle' in m['name']]
    if cyclic_results:
        best_cyclic = max(cyclic_results, key=lambda m: m['sharpe'])
        baseline = results[0]  # 100% COMPASS

        print(f"\n{'='*70}")
        print(f"  BEST CYCLIC: {best_cyclic['name']}")
        print(f"  vs COMPASS baseline")
        print(f"{'='*70}")
        print(f"\n  {'Year':<6} {'COMPASS':>10} {'Cyclic':>10} {'Delta':>10} {'Winner':>10}")
        print(f"  {'-'*48}")

        b_yr = baseline['yearly_ret']
        c_yr = best_cyclic['yearly_ret']

        cyclic_wins = 0
        for idx in b_yr.index:
            yr = idx.year
            bv = b_yr.get(idx, float('nan'))
            cv = c_yr.get(idx, float('nan'))
            if pd.isna(bv) or pd.isna(cv):
                continue
            delta = cv - bv
            winner = 'CYCLIC' if cv > bv else 'COMPASS'
            if cv > bv: cyclic_wins += 1
            print(f"  {yr:<6} {bv:>9.1%} {cv:>9.1%} {delta:>+9.1%} {winner:>10}")

        total = len(b_yr)
        print(f"\n  Cyclic wins: {cyclic_wins}/{total} years ({cyclic_wins/max(total,1)*100:.0f}%)")

    # ── OVERALL COMPARISON ──
    always_50 = [m for m in results if m['name'] == 'Always 50/50'][0]
    compass_only = results[0]

    print(f"\n{'='*70}")
    print(f"  FINAL COMPARISON")
    print(f"{'='*70}")
    print(f"")
    print(f"  {'':>28} {'COMPASS':>10} {'Always50':>10} {'BestCycl':>10}")
    print(f"  {'-'*60}")

    bcy = best_cyclic if cyclic_results else always_50
    for label, key, fmt in [
        ('CAGR', 'cagr', '.2%'),
        ('Sharpe', 'sharpe', '.2f'),
        ('Sortino', 'sortino', '.2f'),
        ('Calmar', 'calmar', '.2f'),
        ('Max Drawdown', 'max_dd', '.2%'),
        ('Volatility', 'vol', '.2%'),
        ('Monthly Win%', 'monthly_win', '.1%'),
        ('Worst Year', 'worst_year', '.1%'),
    ]:
        cv = compass_only[key]
        av = always_50[key]
        bcv = bcy[key]
        print(f"  {label:<28} {cv:>10{fmt}} {av:>10{fmt}} {bcv:>10{fmt}}")

    print(f"\n  Conclusion:")
    if bcy['sharpe'] > always_50['sharpe'] and bcy['sharpe'] > compass_only['sharpe']:
        print(f"  >> CYCLIC ROTATION WINS on risk-adjusted basis!")
        print(f"     {bcy['name']}: Sharpe {bcy['sharpe']:.2f}, CAGR {bcy['cagr']:.2%}, MaxDD {bcy['max_dd']:.2%}")
    elif always_50['sharpe'] > bcy['sharpe']:
        print(f"  >> ALWAYS 50/50 is better than cycling.")
        print(f"     Cyclic adds complexity without benefit.")
    else:
        print(f"  >> COMPASS alone remains king of CAGR.")
        print(f"     But blends improve risk-adjusted returns.")

    print(f"\n{'='*70}")


if __name__ == '__main__':
    main()
