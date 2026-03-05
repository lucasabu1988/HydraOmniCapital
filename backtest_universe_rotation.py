#!/usr/bin/env python3
"""
A/B Backtest: Universe Rotation Frequency
==========================================
Compares COMPASS v84 performance with 3 universe rotation frequencies:
  A) Annual   (current, 12-month lookback)
  B) Quadrimester (4-month lookback, rotates Jan/May/Sep)
  C) Quarterly (3-month lookback, rotates Jan/Apr/Jul/Oct)

All other algorithm parameters are IDENTICAL — only the universe rotation changes.
"""

import sys
import os
import importlib
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple
from datetime import timedelta

# Import v84 module (locked, but we can import it)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
v84 = importlib.import_module('omnicapital_v84_compass')

TOP_N = v84.TOP_N  # 40


# ============================================================================
# UNIVERSE COMPUTATION VARIANTS
# ============================================================================

def compute_periodic_universe(price_data: Dict[str, pd.DataFrame],
                              months_per_period: int) -> Dict[Tuple, List[str]]:
    """
    Compute top-40 universe with periodic rotation.

    months_per_period:
      12 = annual (current)
       4 = quadrimester (Jan, May, Sep)
       3 = quarterly (Jan, Apr, Jul, Oct)

    Returns: Dict[(year, period_index), List[str]]
      period_index: 0-based within year
      For annual: (2020, 0)
      For quadrimester: (2020, 0), (2020, 1), (2020, 2)
      For quarterly: (2020, 0), (2020, 1), (2020, 2), (2020, 3)
    """
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))

    years = sorted(set(d.year for d in all_dates))
    periods_per_year = 12 // months_per_period

    # Define period start months
    if months_per_period == 12:
        start_months = [1]
    elif months_per_period == 4:
        start_months = [1, 5, 9]
    elif months_per_period == 3:
        start_months = [1, 4, 7, 10]
    else:
        raise ValueError(f"Unsupported months_per_period: {months_per_period}")

    universe = {}
    tz = all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None

    for year in years:
        for pi, start_month in enumerate(start_months):
            # Ranking window: look back `months_per_period` months from start of this period
            ranking_end = pd.Timestamp(f'{year}-{start_month:02d}-01', tz=tz)

            # Go back months_per_period months
            end_month = start_month
            end_year = year
            start_m = end_month - months_per_period
            start_y = end_year
            if start_m <= 0:
                start_m += 12
                start_y -= 1
            ranking_start = pd.Timestamp(f'{start_y}-{start_m:02d}-01', tz=tz)

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
            universe[(year, pi)] = top_n

    return universe


def get_period_key(date: pd.Timestamp, months_per_period: int) -> Tuple[int, int]:
    """Get the (year, period_index) for a given date and rotation frequency."""
    if months_per_period == 12:
        return (date.year, 0)
    elif months_per_period == 4:
        # Jan-Apr=0, May-Aug=1, Sep-Dec=2
        pi = (date.month - 1) // 4
        return (date.year, pi)
    elif months_per_period == 3:
        # Jan-Mar=0, Apr-Jun=1, Jul-Sep=2, Oct-Dec=3
        pi = (date.month - 1) // 3
        return (date.year, pi)
    else:
        raise ValueError(f"Unsupported months_per_period: {months_per_period}")


def get_tradeable_symbols_periodic(price_data: Dict[str, pd.DataFrame],
                                    date: pd.Timestamp,
                                    first_date: pd.Timestamp,
                                    periodic_universe: Dict[Tuple, List[str]],
                                    months_per_period: int) -> List[str]:
    """Return tradeable symbols for the current period."""
    key = get_period_key(date, months_per_period)
    eligible = set(periodic_universe.get(key, []))

    tradeable = []
    for symbol in eligible:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        symbol_first_date = df.index[0]
        days_since_start = (date - symbol_first_date).days
        if date <= first_date + timedelta(days=30):
            tradeable.append(symbol)
        elif days_since_start >= v84.MIN_AGE_DAYS:
            tradeable.append(symbol)
    return tradeable


# ============================================================================
# MONKEY-PATCH RUNNER
# ============================================================================

def run_backtest_with_rotation(price_data, spy_data, cash_yield_daily,
                                months_per_period: int, label: str) -> Dict:
    """
    Run the v84 backtest with a different universe rotation frequency.

    We monkey-patch get_tradeable_symbols in the v84 module so the entire
    backtest logic (signals, regime, risk management) stays identical.
    """
    print(f"\n{'='*80}")
    print(f"  COMPUTING UNIVERSE: {label}")
    print(f"{'='*80}")

    # Compute universe for this rotation frequency
    periodic_universe = compute_periodic_universe(price_data, months_per_period)

    # Count total unique period keys
    print(f"  Periods computed: {len(periodic_universe)}")

    # Convert to the format v84 expects: Dict[int, List[str]] for annual,
    # or we need to patch get_tradeable_symbols for periodic

    # Save original function
    original_get_tradeable = v84.get_tradeable_symbols

    # Create patched version
    def patched_get_tradeable(price_data_inner, date, first_date, annual_universe_ignored):
        return get_tradeable_symbols_periodic(
            price_data_inner, date, first_date,
            periodic_universe, months_per_period
        )

    # Monkey-patch
    v84.get_tradeable_symbols = patched_get_tradeable

    try:
        # For annual_universe arg, pass a dummy — our patch ignores it
        dummy_universe = {}
        results = v84.run_backtest(price_data, dummy_universe, spy_data, cash_yield_daily)
        metrics = v84.calculate_metrics(results)
    finally:
        # Restore original
        v84.get_tradeable_symbols = original_get_tradeable

    return {
        'results': results,
        'metrics': metrics,
        'universe': periodic_universe,
        'label': label,
        'months_per_period': months_per_period,
    }


# ============================================================================
# COMPARISON OUTPUT
# ============================================================================

def print_comparison(all_runs: List[Dict]):
    """Print side-by-side comparison of all rotation variants."""

    print("\n" + "=" * 100)
    print("  UNIVERSE ROTATION A/B COMPARISON")
    print("=" * 100)

    labels = [r['label'] for r in all_runs]
    metrics = [r['metrics'] for r in all_runs]

    # Header
    header = f"{'Metric':<28}"
    for label in labels:
        header += f" {label:>20}"
    header += f" {'D.Quad vs Ann':>16} {'D.Qtr vs Ann':>16}"
    print(header)
    print("-" * len(header))

    m_ann = metrics[0]
    m_quad = metrics[1]
    m_qtr = metrics[2]

    def row(name, key, fmt='pct', higher_better=True):
        vals = [m[key] for m in metrics]
        line = f"{name:<28}"
        for v in vals:
            if fmt == 'pct':
                line += f" {v:>19.2%}"
            elif fmt == 'pct1':
                line += f" {v:>19.1%}"
            elif fmt == 'f2':
                line += f" {v:>20.2f}"
            elif fmt == 'f0':
                line += f" {v:>20,.0f}"
            elif fmt == 'dollar':
                line += f" ${v:>19,.2f}"

        # Deltas
        for m_test in [m_quad, m_qtr]:
            delta = m_test[key] - m_ann[key]
            if fmt == 'pct':
                d_str = f"{delta:>+.2%}"
            elif fmt == 'pct1':
                d_str = f"{delta:>+.1%}"
            elif fmt == 'f2':
                d_str = f"{delta:>+.2f}"
            elif fmt == 'f0':
                d_str = f"{delta:>+,.0f}"
            elif fmt == 'dollar':
                d_str = f"${delta:>+,.2f}"

            # Indicator
            if higher_better:
                indicator = "+" if delta > 0 else ("-" if delta < 0 else "=")
            else:
                indicator = "-" if delta > 0 else ("+" if delta < 0 else "=")

            line += f" {indicator} {d_str:>13}"

        print(line)

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
    row("Avg Winner", "avg_winner", "dollar")
    row("Avg Loser", "avg_loser", "dollar", higher_better=False)

    print("\n--- Risk Management ---")
    row("Stop Events", "stop_events", "f0", higher_better=False)
    row("Protection Days %", "protection_pct", "f2", higher_better=False)
    row("Risk-Off %", "risk_off_pct", "f2")

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
            line += f" {count:>12,} ({pct:>4.1f}%)"
        print(line)

    # Universe rotation forced exits specifically
    print("\n--- Universe Rotation Exits ---")
    for r in all_runs:
        rot_exits = r['metrics']['exit_reasons'].get('universe_rotation', 0)
        total = r['metrics']['trades']
        years = r['metrics']['years']
        per_year = rot_exits / years if years > 0 else 0
        print(f"  {r['label']:<20}: {rot_exits:>6,} total ({per_year:.1f}/year)")

    # Annual returns comparison
    print("\n--- Annual Returns ---")
    ann_rets = [m['annual_returns'] for m in metrics]
    years_union = sorted(set().union(*[set(ar.index) for ar in ann_rets]))

    header = f"{'Year':<8}"
    for label in labels:
        header += f" {label:>15}"
    print(header)

    for yr in years_union:
        line = f"{yr.year:<8}"
        for ar in ann_rets:
            if yr in ar.index:
                line += f" {ar.loc[yr]:>14.2%}"
            else:
                line += f" {'N/A':>15}"
        print(line)

    print(f"\n{'Best Year':<8}", end="")
    for m in metrics:
        print(f" {m['best_year']:>14.2%}", end="")
    print(f"\n{'Worst Year':<8}", end="")
    for m in metrics:
        print(f" {m['worst_year']:>14.2%}", end="")
    print()

    # Verdict
    print("\n" + "=" * 100)
    print("  VERDICT")
    print("=" * 100)

    best_sharpe_idx = max(range(3), key=lambda i: metrics[i]['sharpe'])
    best_cagr_idx = max(range(3), key=lambda i: metrics[i]['cagr'])
    best_dd_idx = max(range(3), key=lambda i: metrics[i]['max_drawdown'])  # less negative = better

    print(f"  Best Sharpe:    {labels[best_sharpe_idx]} ({metrics[best_sharpe_idx]['sharpe']:.3f})")
    print(f"  Best CAGR:      {labels[best_cagr_idx]} ({metrics[best_cagr_idx]['cagr']:.2%})")
    print(f"  Best MaxDD:     {labels[best_dd_idx]} ({metrics[best_dd_idx]['max_drawdown']:.2%})")

    # Check if any variant is clearly better
    quad_better = (m_quad['sharpe'] > m_ann['sharpe'] and
                   m_quad['cagr'] > m_ann['cagr'] and
                   m_quad['max_drawdown'] > m_ann['max_drawdown'])
    qtr_better = (m_qtr['sharpe'] > m_ann['sharpe'] and
                  m_qtr['cagr'] > m_ann['cagr'] and
                  m_qtr['max_drawdown'] > m_ann['max_drawdown'])

    if quad_better and qtr_better:
        print("\n  >> Both Quadrimester and Quarterly beat Annual on all key metrics!")
    elif quad_better:
        print("\n  >> Quadrimester beats Annual on all key metrics (Sharpe, CAGR, MaxDD)")
    elif qtr_better:
        print("\n  >> Quarterly beats Annual on all key metrics (Sharpe, CAGR, MaxDD)")
    else:
        print("\n  >> No variant dominates on all metrics -- trade-offs exist")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("  COMPASS v8.4 — UNIVERSE ROTATION A/B TEST")
    print("  Annual vs Quadrimester (4mo) vs Quarterly (3mo)")
    print("=" * 80)

    # 1. Load data (shared across all runs)
    print("\n--- Loading Data ---")
    price_data = v84.download_broad_pool()
    print(f"Symbols available: {len(price_data)}")

    spy_data = v84.download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    cash_yield_daily = v84.download_cash_yield()

    # 2. Run all three variants
    configs = [
        (12, "Annual (12mo)"),
        (4,  "Quadrimester (4mo)"),
        (3,  "Quarterly (3mo)"),
    ]

    all_runs = []
    for months, label in configs:
        run = run_backtest_with_rotation(price_data, spy_data, cash_yield_daily,
                                          months, label)
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
            f'backtests/v84_rotation_{tag}_daily.csv', index=False)
        if len(run['results']['trades']) > 0:
            run['results']['trades'].to_csv(
                f'backtests/v84_rotation_{tag}_trades.csv', index=False)

    print(f"\n\nResults saved to backtests/v84_rotation_*.csv")
