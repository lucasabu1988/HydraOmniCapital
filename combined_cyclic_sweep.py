#!/usr/bin/env python3
"""
CYCLIC SWEEP: Test ALL possible 6-year cycle offsets
=====================================================
If Cycle A worked because of hindsight, then shifting
the ON window by 1, 2, 3, 4, 5 years should degrade it.
If ALL offsets beat COMPASS on Sharpe, it's NOT hindsight.

We test offsets 0-5 (covers all possible starting points).
For each offset, RATTLESNAKE is ON for years [offset, offset+6, offset+12...]
and OFF for the rest.

Also tests cycle lengths 3, 4, 5, 6, 7, 8 years to find optimal.
"""

import numpy as np
import pandas as pd
import warnings

warnings.filterwarnings('ignore')

INITIAL_CAPITAL = 100_000
RISK_FREE = 0.02


def load_data():
    compass_df = pd.read_csv('backtests/v8_compass_daily.csv', parse_dates=['date'])
    compass_df = compass_df.set_index('date')[['value']].rename(columns={'value': 'compass'})

    rattle_df = pd.read_csv('backtests/rattlesnake_daily.csv', parse_dates=['date'])
    rattle_df = rattle_df.set_index('date')

    common = compass_df.index.intersection(rattle_df.index)
    c = compass_df.loc[common, 'compass']
    r = rattle_df.loc[common, 'rattlesnake']

    c_norm = c / c.iloc[0] * INITIAL_CAPITAL
    r_norm = r / r.iloc[0] * INITIAL_CAPITAL
    return c_norm, r_norm


def compute_metrics(equity):
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

    return {
        'final': final, 'cagr': cagr, 'vol': vol,
        'sharpe': sharpe, 'sortino': sortino, 'calmar': calmar,
        'max_dd': max_dd,
    }


def build_cyclic(c_ret, r_ret, dates, cycle_len, offset, wc, wr):
    """
    RATTLESNAKE ON when: (year - start_year - offset) % (cycle_len*2) < cycle_len
    This creates alternating ON/OFF windows of cycle_len years,
    shifted by offset years.
    """
    start_year = dates[0].year
    combined_ret = pd.Series(0.0, index=dates)

    for idx in range(len(dates)):
        years_since = dates[idx].year - start_year
        shifted = (years_since - offset) % (cycle_len * 2)
        rattle_on = shifted < cycle_len

        cr = c_ret.iloc[idx] if not pd.isna(c_ret.iloc[idx]) else 0
        rr = r_ret.iloc[idx] if not pd.isna(r_ret.iloc[idx]) else 0

        if rattle_on:
            combined_ret.iloc[idx] = wc * cr + wr * rr
        else:
            combined_ret.iloc[idx] = cr

    equity = (1 + combined_ret).cumprod() * INITIAL_CAPITAL
    return equity


def main():
    print("=" * 72)
    print("  HINDSIGHT BIAS TEST: All Cycle Offsets & Lengths")
    print("  If results are consistent across offsets -> NOT hindsight")
    print("  If only 1-2 offsets work -> IS hindsight")
    print("=" * 72)

    c_norm, r_norm = load_data()
    c_ret = c_norm.pct_change().fillna(0)
    r_ret = r_norm.pct_change().fillna(0)
    dates = c_norm.index
    start_year = dates[0].year
    end_year = dates[-1].year

    # Baselines
    compass_eq = (1 + c_ret).cumprod() * INITIAL_CAPITAL
    always50_ret = 0.5 * c_ret + 0.5 * r_ret
    always50_eq = (1 + always50_ret).cumprod() * INITIAL_CAPITAL

    compass_m = compute_metrics(compass_eq)
    always50_m = compute_metrics(always50_eq)

    print(f"\n  Baselines:")
    print(f"  {'Strategy':<25} {'CAGR':>7} {'Sharpe':>7} {'MaxDD':>8} {'Calmar':>7} {'$Final':>12}")
    print(f"  {'-'*68}")
    print(f"  {'100% COMPASS':<25} {compass_m['cagr']:>6.2%} {compass_m['sharpe']:>7.2f} {compass_m['max_dd']:>7.2%} {compass_m['calmar']:>7.2f} ${compass_m['final']:>10,.0f}")
    print(f"  {'Always 50/50':<25} {always50_m['cagr']:>6.2%} {always50_m['sharpe']:>7.2f} {always50_m['max_dd']:>7.2%} {always50_m['calmar']:>7.2f} ${always50_m['final']:>10,.0f}")

    # ═══════════════════════════════════════════════
    # TEST 1: Fixed 6-year cycle, ALL offsets (0-5)
    # ═══════════════════════════════════════════════
    print(f"\n{'='*72}")
    print(f"  TEST 1: 6-Year Cycle, ALL Offsets (50/50 when ON)")
    print(f"  Offset = which year the first ON window starts")
    print(f"{'='*72}\n")

    cycle_len = 6
    print(f"  {'Offset':<10} {'ON years':<30} {'CAGR':>7} {'Sharpe':>7} {'MaxDD':>8} {'Calmar':>7} {'$Final':>12} {'vs COMPASS':>12}")
    print(f"  {'-'*96}")

    offset_results = []
    for offset in range(cycle_len):
        # Show which years are ON
        on_years = []
        for y in range(start_year, end_year + 1):
            shifted = (y - start_year - offset) % (cycle_len * 2)
            if shifted < cycle_len:
                on_years.append(y)

        # Compress year ranges for display
        ranges = []
        if on_years:
            rng_start = on_years[0]
            prev = on_years[0]
            for y in on_years[1:]:
                if y == prev + 1:
                    prev = y
                else:
                    ranges.append(f"{rng_start}-{prev}" if rng_start != prev else f"{rng_start}")
                    rng_start = y
                    prev = y
            ranges.append(f"{rng_start}-{prev}" if rng_start != prev else f"{rng_start}")

        eq = build_cyclic(c_ret, r_ret, dates, cycle_len, offset, 0.5, 0.5)
        m = compute_metrics(eq)
        offset_results.append(m)

        sharpe_vs = m['sharpe'] - compass_m['sharpe']
        label = ', '.join(ranges[:3])
        if len(ranges) > 3:
            label += '...'
        print(f"  {offset:<10} {label:<30} {m['cagr']:>6.2%} {m['sharpe']:>7.2f} {m['max_dd']:>7.2%} {m['calmar']:>7.2f} ${m['final']:>10,.0f} {sharpe_vs:>+11.2f}")

    # Summary
    sharpes = [m['sharpe'] for m in offset_results]
    cagrs = [m['cagr'] for m in offset_results]
    dds = [m['max_dd'] for m in offset_results]
    beats_compass_sharpe = sum(1 for s in sharpes if s > compass_m['sharpe'])

    print(f"\n  SUMMARY (6-year cycle, 50/50 split):")
    print(f"  Offsets that beat COMPASS Sharpe ({compass_m['sharpe']:.2f}): {beats_compass_sharpe}/{len(sharpes)}")
    print(f"  Sharpe range: {min(sharpes):.2f} - {max(sharpes):.2f} (mean: {np.mean(sharpes):.2f})")
    print(f"  CAGR range:   {min(cagrs):.2%} - {max(cagrs):.2%}")
    print(f"  MaxDD range:  {min(dds):.2%} - {max(dds):.2%}")

    if beats_compass_sharpe >= len(sharpes) * 0.8:
        print(f"  >> ROBUST: {beats_compass_sharpe}/{len(sharpes)} offsets beat COMPASS -> NOT hindsight")
    elif beats_compass_sharpe >= len(sharpes) * 0.5:
        print(f"  >> MIXED: Only {beats_compass_sharpe}/{len(sharpes)} offsets beat COMPASS -> SOME hindsight")
    else:
        print(f"  >> FRAGILE: Only {beats_compass_sharpe}/{len(sharpes)} offsets beat COMPASS -> IS hindsight")

    # ═══════════════════════════════════════════════
    # TEST 2: Different cycle lengths (3-8 years), all offsets
    # ═══════════════════════════════════════════════
    print(f"\n{'='*72}")
    print(f"  TEST 2: Different Cycle Lengths, All Offsets (50/50 when ON)")
    print(f"  Average across all possible offsets for each length")
    print(f"{'='*72}\n")

    print(f"  {'CycleLen':<10} {'AvgSharpe':>10} {'MinSharpe':>10} {'MaxSharpe':>10} {'AvgCAGR':>8} {'AvgMaxDD':>9} {'Beats%':>8}")
    print(f"  {'-'*66}")

    all_cycle_results = {}
    for cl in [3, 4, 5, 6, 7, 8]:
        cycle_sharpes = []
        cycle_cagrs = []
        cycle_dds = []
        for offset in range(cl):
            eq = build_cyclic(c_ret, r_ret, dates, cl, offset, 0.5, 0.5)
            m = compute_metrics(eq)
            cycle_sharpes.append(m['sharpe'])
            cycle_cagrs.append(m['cagr'])
            cycle_dds.append(m['max_dd'])

        beats = sum(1 for s in cycle_sharpes if s > compass_m['sharpe'])
        all_cycle_results[cl] = {
            'avg_sharpe': np.mean(cycle_sharpes),
            'min_sharpe': min(cycle_sharpes),
            'max_sharpe': max(cycle_sharpes),
            'avg_cagr': np.mean(cycle_cagrs),
            'avg_dd': np.mean(cycle_dds),
            'beats_pct': beats / len(cycle_sharpes),
        }

        print(f"  {cl} years{'':<5} {np.mean(cycle_sharpes):>10.2f} {min(cycle_sharpes):>10.2f} {max(cycle_sharpes):>10.2f} {np.mean(cycle_cagrs):>7.2%} {np.mean(cycle_dds):>8.2%} {beats/len(cycle_sharpes):>7.0%}")

    # ═══════════════════════════════════════════════
    # TEST 3: Different splits when ON
    # ═══════════════════════════════════════════════
    print(f"\n{'='*72}")
    print(f"  TEST 3: Different Splits (6-year cycle, averaged over ALL offsets)")
    print(f"{'='*72}\n")

    splits = [(0.7, 0.3), (0.6, 0.4), (0.5, 0.5), (0.4, 0.6), (0.3, 0.7)]
    print(f"  {'Split C/R':<12} {'AvgSharpe':>10} {'MinSharpe':>10} {'MaxSharpe':>10} {'AvgCAGR':>8} {'AvgMaxDD':>9}")
    print(f"  {'-'*60}")

    for wc, wr in splits:
        sharpes = []
        cagrs = []
        dds = []
        for offset in range(6):
            eq = build_cyclic(c_ret, r_ret, dates, 6, offset, wc, wr)
            m = compute_metrics(eq)
            sharpes.append(m['sharpe'])
            cagrs.append(m['cagr'])
            dds.append(m['max_dd'])

        print(f"  {int(wc*100)}/{int(wr*100)}{'':<8} {np.mean(sharpes):>10.2f} {min(sharpes):>10.2f} {max(sharpes):>10.2f} {np.mean(cagrs):>7.2%} {np.mean(dds):>8.2%}")

    # ═══════════════════════════════════════════════
    # FINAL VERDICT
    # ═══════════════════════════════════════════════
    print(f"\n{'='*72}")
    print(f"  FINAL VERDICT: Hindsight Bias Test")
    print(f"{'='*72}")
    print(f"")
    print(f"  COMPASS baseline:  Sharpe {compass_m['sharpe']:.2f} | CAGR {compass_m['cagr']:.2%} | MaxDD {compass_m['max_dd']:.2%}")
    print(f"  Always 50/50:      Sharpe {always50_m['sharpe']:.2f} | CAGR {always50_m['cagr']:.2%} | MaxDD {always50_m['max_dd']:.2%}")
    print(f"")

    # Check 6-year cycle robustness
    r6 = all_cycle_results[6]
    print(f"  6Y Cyclic (avg all offsets):")
    print(f"    Avg Sharpe: {r6['avg_sharpe']:.2f} (range {r6['min_sharpe']:.2f}-{r6['max_sharpe']:.2f})")
    print(f"    Beats COMPASS: {r6['beats_pct']:.0%} of offsets")
    print(f"")

    # Does ANY cycling strategy reliably beat Always 50/50?
    print(f"  Key Question: Does cycling beat ALWAYS 50/50?")
    best_cycle = max(all_cycle_results.items(), key=lambda x: x[1]['avg_sharpe'])
    print(f"  Best avg cycle: {best_cycle[0]}Y with avg Sharpe {best_cycle[1]['avg_sharpe']:.2f}")
    print(f"  Always 50/50:   Sharpe {always50_m['sharpe']:.2f}")
    print(f"")

    if best_cycle[1]['avg_sharpe'] > always50_m['sharpe']:
        print(f"  >> Cycling ({best_cycle[0]}Y) beats Always 50/50 on average")
        print(f"     But check min Sharpe: {best_cycle[1]['min_sharpe']:.2f}")
        if best_cycle[1]['min_sharpe'] > compass_m['sharpe']:
            print(f"     Even WORST offset beats COMPASS -> ROBUST strategy")
        else:
            print(f"     Worst offset LOSES to COMPASS -> offset matters -> HINDSIGHT RISK")
    else:
        print(f"  >> NO cycle length reliably beats Always 50/50")
        print(f"     ALWAYS 50/50 is the robust choice")
        print(f"     Cycling = added complexity for ZERO benefit")

    print(f"\n{'='*72}")


if __name__ == '__main__':
    main()
