#!/usr/bin/env python3
"""
A/B Backtest: Long-Period Universe Rotation
============================================
Compares COMPASS v84 performance with longer universe rotation:
  A) Annual   (current, 12-month lookback, rotates every year)
  B) Biennial (24-month lookback, rotates every 2 years)
  C) Triennial (36-month lookback, rotates every 3 years)
  D) Quadrennial (48-month lookback, rotates every 4 years)

All other algorithm parameters are IDENTICAL.
"""

import sys
import os
import importlib
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
v84 = importlib.import_module('omnicapital_v84_compass')

TOP_N = v84.TOP_N  # 40


# ============================================================================
# MULTI-YEAR UNIVERSE COMPUTATION
# ============================================================================

def compute_multiyear_universe(price_data: Dict[str, pd.DataFrame],
                                rotation_years: int) -> Dict[int, List[str]]:
    """
    Compute top-40 universe with multi-year rotation.

    rotation_years=1: annual (baseline) - lookback 12mo, rotates every Jan
    rotation_years=2: biennial - lookback 24mo, rotates every 2 years
    rotation_years=3: triennial - lookback 36mo, rotates every 3 years
    rotation_years=4: quadrennial - lookback 48mo, rotates every 4 years

    Returns Dict[int, List[str]] keyed by year.
    For multi-year, the same list applies to all years in the rotation block.
    """
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    years = sorted(set(d.year for d in all_dates))
    tz = all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None

    # Determine rotation years (first data year, then every N years)
    first_year = years[0]
    rotation_schedule = list(range(first_year, years[-1] + 1, rotation_years))

    universe = {}
    lookback_months = 12 * rotation_years  # Scale lookback with rotation period

    for rot_year in rotation_schedule:
        # Ranking window: look back `lookback_months` from Jan 1 of rotation year
        ranking_end = pd.Timestamp(f'{rot_year}-01-01', tz=tz)

        # Go back lookback_months
        start_year = rot_year - rotation_years
        ranking_start = pd.Timestamp(f'{start_year}-01-01', tz=tz)

        scores = {}
        for symbol, df in price_data.items():
            mask = (df.index >= ranking_start) & (df.index < ranking_end)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dollar_vol = (window['Close'] * window['Volume']).mean()
            scores[symbol] = dollar_vol

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_n = [s for s, _ in ranked[:TOP_N]]

        # Apply this universe to all years in the block
        for y in range(rot_year, min(rot_year + rotation_years, years[-1] + 2)):
            universe[y] = top_n

        if rot_year > first_year and (rot_year - rotation_years) in universe:
            prev = set(universe[rot_year - rotation_years])
            curr = set(top_n)
            added = curr - prev
            removed = prev - curr
            if added or removed:
                print(f"  {rot_year}: Top-{TOP_N} | +{len(added)} added, -{len(removed)} removed | "
                      f"lookback {start_year}-{rot_year}")
        else:
            print(f"  {rot_year}: Initial top-{TOP_N} = {len(top_n)} stocks | "
                  f"lookback {start_year}-{rot_year}")

    return universe


# ============================================================================
# RUNNER
# ============================================================================

def run_backtest_with_multiyear(price_data, spy_data, cash_yield_daily,
                                 rotation_years: int, label: str) -> Dict:
    """Run the v84 backtest with a different universe rotation period."""
    print(f"\n{'='*80}")
    print(f"  COMPUTING UNIVERSE: {label}")
    print(f"{'='*80}")

    multiyear_universe = compute_multiyear_universe(price_data, rotation_years)
    print(f"  Year entries: {len(multiyear_universe)}")

    # The multiyear universe is Dict[int, List[str]] — same format v84 expects!
    # get_tradeable_symbols does annual_universe.get(date.year, [])
    # So this works directly without monkey-patching.
    results = v84.run_backtest(price_data, multiyear_universe, spy_data, cash_yield_daily)
    metrics = v84.calculate_metrics(results)

    return {
        'results': results,
        'metrics': metrics,
        'universe': multiyear_universe,
        'label': label,
        'rotation_years': rotation_years,
    }


# ============================================================================
# COMPARISON OUTPUT
# ============================================================================

def print_comparison(all_runs: List[Dict]):
    """Print side-by-side comparison."""

    print("\n" + "=" * 120)
    print("  UNIVERSE ROTATION A/B COMPARISON — LONG PERIODS")
    print("=" * 120)

    labels = [r['label'] for r in all_runs]
    metrics = [r['metrics'] for r in all_runs]
    m_base = metrics[0]  # Annual baseline

    # Header
    header = f"{'Metric':<28}"
    for label in labels:
        header += f" {label:>22}"
    print(header)
    print("-" * len(header))

    def row(name, key, fmt='pct', higher_better=True):
        vals = [m[key] for m in metrics]
        line = f"{name:<28}"
        for v in vals:
            if fmt == 'pct':
                line += f" {v:>21.2%}"
            elif fmt == 'f2':
                line += f" {v:>22.2f}"
            elif fmt == 'f0':
                line += f" {v:>22,.0f}"
            elif fmt == 'dollar':
                line += f" ${v:>21,.2f}"
        print(line)

        # Print delta row
        delta_line = f"{'':28}"
        delta_line += f" {'(baseline)':>22}"
        for m in metrics[1:]:
            delta = m[key] - m_base[key]
            if fmt == 'pct':
                d_str = f"{delta:>+.2%}"
            elif fmt == 'f2':
                d_str = f"{delta:>+.2f}"
            elif fmt == 'f0':
                d_str = f"{delta:>+,.0f}"
            elif fmt == 'dollar':
                d_str = f"${delta:>+,.0f}"

            if higher_better:
                mark = "[+]" if delta > 0 else ("[-]" if delta < 0 else "[=]")
            else:
                mark = "[-]" if delta > 0 else ("[+]" if delta < 0 else "[=]")

            delta_line += f" {mark} {d_str:>17}"
        print(delta_line)

    print("\n--- Performance ---")
    row("Final Value", "final_value", "dollar")
    row("CAGR", "cagr", "pct")
    row("Total Return", "total_return", "pct")

    print("\n--- Risk-Adjusted ---")
    row("Sharpe", "sharpe", "f2")
    row("Sortino", "sortino", "f2")
    row("Calmar", "calmar", "f2")
    row("Max Drawdown", "max_drawdown", "pct", higher_better=False)

    print("\n--- Trading ---")
    row("Total Trades", "trades", "f0")
    row("Win Rate", "win_rate", "pct")
    row("Avg P&L/Trade", "avg_trade", "dollar")

    print("\n--- Risk Management ---")
    row("Stop Events", "stop_events", "f0", higher_better=False)
    row("Protection Days %", "protection_pct", "f2", higher_better=False)

    # Exit reason breakdown
    print("\n--- Exit Reasons ---")
    all_reasons = set()
    for m in metrics:
        all_reasons.update(m['exit_reasons'].keys())

    for reason in sorted(all_reasons):
        line = f"  {reason:<26}"
        for m in metrics:
            count = m['exit_reasons'].get(reason, 0)
            total = m['trades']
            pct = count / total * 100 if total > 0 else 0
            line += f" {count:>14,} ({pct:>4.1f}%)"
        print(line)

    # Universe rotation exits
    print("\n--- Universe Rotation Exits ---")
    for r in all_runs:
        rot_exits = r['metrics']['exit_reasons'].get('universe_rotation', 0)
        years = r['metrics']['years']
        per_year = rot_exits / years if years > 0 else 0
        print(f"  {r['label']:<24}: {rot_exits:>6,} total ({per_year:.1f}/year)")

    # Annual returns
    print("\n--- Annual Returns ---")
    ann_rets = [m['annual_returns'] for m in metrics]
    years_union = sorted(set().union(*[set(ar.index) for ar in ann_rets]))

    header = f"{'Year':<8}"
    for label in labels:
        header += f" {label:>18}"
    print(header)

    for yr in years_union:
        line = f"{yr.year:<8}"
        for ar in ann_rets:
            if yr in ar.index:
                line += f" {ar.loc[yr]:>17.2%}"
            else:
                line += f" {'N/A':>18}"
        print(line)

    print(f"\n{'Best Year':<8}", end="")
    for m in metrics:
        print(f" {m['best_year']:>17.2%}", end="")
    print(f"\n{'Worst Yr':<8}", end="")
    for m in metrics:
        print(f" {m['worst_year']:>17.2%}", end="")
    print()

    # Verdict
    print("\n" + "=" * 120)
    print("  VERDICT")
    print("=" * 120)

    n = len(metrics)
    best_sharpe_idx = max(range(n), key=lambda i: metrics[i]['sharpe'])
    best_cagr_idx = max(range(n), key=lambda i: metrics[i]['cagr'])
    best_dd_idx = max(range(n), key=lambda i: metrics[i]['max_drawdown'])

    print(f"  Best Sharpe:    {labels[best_sharpe_idx]} ({metrics[best_sharpe_idx]['sharpe']:.3f})")
    print(f"  Best CAGR:      {labels[best_cagr_idx]} ({metrics[best_cagr_idx]['cagr']:.2%})")
    print(f"  Best MaxDD:     {labels[best_dd_idx]} ({metrics[best_dd_idx]['max_drawdown']:.2%})")

    # Check dominance
    for i in range(1, n):
        label = labels[i]
        better_sharpe = metrics[i]['sharpe'] > m_base['sharpe']
        better_cagr = metrics[i]['cagr'] > m_base['cagr']
        better_dd = metrics[i]['max_drawdown'] > m_base['max_drawdown']

        if better_sharpe and better_cagr and better_dd:
            print(f"\n  >> {label} BEATS Annual on all key metrics!")
        elif better_sharpe or better_cagr or better_dd:
            wins = []
            if better_sharpe: wins.append("Sharpe")
            if better_cagr: wins.append("CAGR")
            if better_dd: wins.append("MaxDD")
            print(f"\n  >> {label} wins on: {', '.join(wins)}")
        else:
            print(f"\n  >> {label} loses on all key metrics")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("  COMPASS v8.4 -- UNIVERSE ROTATION A/B TEST (LONG PERIODS)")
    print("  Annual vs Biennial (2yr) vs Triennial (3yr) vs Quadrennial (4yr)")
    print("=" * 80)

    # 1. Load data (shared)
    print("\n--- Loading Data ---")
    price_data = v84.download_broad_pool()
    print(f"Symbols available: {len(price_data)}")

    spy_data = v84.download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    cash_yield_daily = v84.download_cash_yield()

    # 2. Run all variants
    configs = [
        (1, "Annual (1yr)"),
        (2, "Biennial (2yr)"),
        (3, "Triennial (3yr)"),
        (4, "Quadrennial (4yr)"),
    ]

    all_runs = []
    for rot_years, label in configs:
        run = run_backtest_with_multiyear(price_data, spy_data, cash_yield_daily,
                                           rot_years, label)
        all_runs.append(run)
        print(f"\n  {label}: CAGR={run['metrics']['cagr']:.2%}, "
              f"Sharpe={run['metrics']['sharpe']:.2f}, "
              f"MaxDD={run['metrics']['max_drawdown']:.2%}")

    # 3. Print comparison
    print_comparison(all_runs)

    # 4. Save results
    os.makedirs('backtests', exist_ok=True)
    for run in all_runs:
        tag = run['label'].split('(')[0].strip().lower().replace(' ', '_')
        run['results']['portfolio_values'].to_csv(
            f'backtests/v84_longrot_{tag}_daily.csv', index=False)
        if len(run['results']['trades']) > 0:
            run['results']['trades'].to_csv(
                f'backtests/v84_longrot_{tag}_trades.csv', index=False)

    print(f"\n\nResults saved to backtests/v84_longrot_*.csv")
