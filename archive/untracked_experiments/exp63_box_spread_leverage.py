"""
Experiment #63: Box Spread Leverage (Funding Layer)
====================================================
Applies leverage at the FUNDING layer, not the strategy layer.
The algorithm runs unchanged — it just operates on more capital.

Method: Take exp62 survivorship-corrected daily equity curve,
compute daily returns, scale by leverage ratio, subtract daily
financing cost (SOFR + 20bps) on the borrowed portion.

Leveraged daily return = L * R_t - (L-1) * financing_rate / 252

Tests leverage ratios: 1.0x (baseline), 1.1x, 1.2x, 1.3x, 1.5x

Usage: python experiments/exp63_box_spread_leverage.py
"""
import os
import sys
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- Configuration ---
INITIAL_EQUITY = 100_000
LEVERAGE_RATIOS = [1.0, 1.1, 1.2, 1.3, 1.5]

# Box spread financing: SOFR + 20bps
# Historical SOFR proxy: use Fed Funds Rate from FRED
# Simplified: use annual rates by period (more realistic than flat rate)
# Pre-2008: ~4-5%, 2008-2015: ~0.1-0.25%, 2016-2018: ~1-2.5%, 2019: ~1.5-2.5%
# 2020-2021: ~0.05-0.1%, 2022-2025: ~4.3-5.3%
SOFR_SPREAD_BPS = 20  # box spread premium over SOFR

# Historical Fed Funds Rate annual averages (proxy for SOFR)
FED_FUNDS_BY_YEAR = {
    2000: 6.24, 2001: 3.88, 2002: 1.67, 2003: 1.13, 2004: 1.35,
    2005: 3.22, 2006: 4.97, 2007: 5.02, 2008: 1.92, 2009: 0.16,
    2010: 0.18, 2011: 0.10, 2012: 0.14, 2013: 0.11, 2014: 0.09,
    2015: 0.13, 2016: 0.39, 2017: 1.00, 2018: 1.83, 2019: 2.16,
    2020: 0.36, 2021: 0.08, 2022: 1.68, 2023: 5.33, 2024: 5.33,
    2025: 4.50, 2026: 4.50,  # estimate
}


def get_financing_rate(year):
    base = FED_FUNDS_BY_YEAR.get(year, 4.50)
    return (base + SOFR_SPREAD_BPS / 100) / 100  # annual rate as decimal


def run_leverage_simulation(daily_values, leverage_ratio):
    df = daily_values.copy()
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').reset_index(drop=True)

    # Compute daily returns from unlevered portfolio
    df['return'] = df['value'].pct_change().fillna(0)

    # Apply leverage to daily returns with time-varying financing cost
    equity = INITIAL_EQUITY
    equity_curve = [equity]
    dates = [df['date'].iloc[0]]
    borrowed_fraction = leverage_ratio - 1.0  # e.g., 0.3 for 1.3x

    peak = equity
    max_dd = 0
    daily_returns = []

    for i in range(1, len(df)):
        r = df['return'].iloc[i]
        year = df['date'].iloc[i].year
        financing_rate = get_financing_rate(year)

        # Leveraged return: scale strategy return, subtract financing on borrowed portion
        lev_return = leverage_ratio * r - borrowed_fraction * (financing_rate / 252)

        equity *= (1 + lev_return)
        equity_curve.append(equity)
        dates.append(df['date'].iloc[i])
        daily_returns.append(lev_return)

        if equity > peak:
            peak = equity
        dd = (equity - peak) / peak
        if dd < max_dd:
            max_dd = dd

    result = pd.DataFrame({'date': dates, 'equity': equity_curve})

    # Metrics
    years = (result['date'].iloc[-1] - result['date'].iloc[0]).days / 365.25
    cagr = (equity / INITIAL_EQUITY) ** (1 / years) - 1
    daily_ret = np.array(daily_returns)
    sharpe = np.mean(daily_ret) / np.std(daily_ret) * np.sqrt(252) if np.std(daily_ret) > 0 else 0
    volatility = np.std(daily_ret) * np.sqrt(252)

    # Average annual financing cost paid
    total_financing = 0
    for i in range(1, len(df)):
        year = df['date'].iloc[i].year
        rate = get_financing_rate(year)
        # Daily financing on borrowed portion (based on current equity)
        total_financing += equity_curve[i-1] * borrowed_fraction * (rate / 252)
    avg_annual_financing = total_financing / years if years > 0 else 0

    return {
        'leverage': leverage_ratio,
        'cagr': cagr,
        'sharpe': sharpe,
        'max_drawdown': max_dd,
        'volatility': volatility,
        'final_value': equity,
        'years': years,
        'avg_annual_financing': avg_annual_financing,
        'equity_curve': result,
    }


if __name__ == '__main__':
    print("=" * 90)
    print("EXPERIMENT #63: BOX SPREAD LEVERAGE (FUNDING LAYER)")
    print("=" * 90)
    print("Method: Scale exp62 survivorship-corrected daily returns by leverage ratio,")
    print("        subtract daily box spread financing cost (SOFR + 20bps) on borrowed portion.")
    print("        Algorithm runs UNCHANGED — leverage is invisible to the engine.")
    print()

    # Load exp62 survivorship-corrected daily equity curve
    daily_path = os.path.join(BASE_DIR, 'backtests', 'exp62_survivorship_daily.csv')
    if not os.path.exists(daily_path):
        print(f"ERROR: {daily_path} not found. Run exp62 first.")
        sys.exit(1)

    daily = pd.read_csv(daily_path)
    print(f"Loaded exp62 daily data: {len(daily)} trading days")
    print(f"Period: {daily['date'].iloc[0]} to {daily['date'].iloc[-1]}")
    print(f"Baseline final value: ${daily['value'].iloc[-1]:,.0f}")

    # Check for anomalous last-day drop
    last_return = (daily['value'].iloc[-1] / daily['value'].iloc[-2]) - 1
    if last_return < -0.30:
        print(f"\n*** WARNING: Last day shows {last_return:.1%} return — likely data anomaly ***")
        print(f"    Running with AND without last day for comparison.\n")
        daily_trimmed = daily.iloc[:-1].copy()
        run_trimmed = True
    else:
        run_trimmed = False

    # Run leverage simulations
    print("\n--- Leverage Simulations ---")
    results = []
    for lev in LEVERAGE_RATIOS:
        r = run_leverage_simulation(daily, lev)
        results.append(r)

    # Also run trimmed (excluding anomalous last day) if needed
    results_trimmed = []
    if run_trimmed:
        for lev in LEVERAGE_RATIOS:
            r = run_leverage_simulation(daily_trimmed, lev)
            results_trimmed.append(r)

    # Display results
    print("\n" + "=" * 90)
    print("RESULTS: BOX SPREAD LEVERAGE ANALYSIS")
    print("=" * 90)

    header = (f"{'Leverage':<10} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>10} "
              f"{'Volatility':>10} {'Final Value':>15} {'Avg Fin Cost':>14}")
    print(f"\n{header}")
    print("-" * 78)

    baseline_cagr = results[0]['cagr']
    for r in results:
        delta = f"({r['cagr'] - baseline_cagr:+.2%})" if r['leverage'] > 1.0 else ""
        print(f"{r['leverage']:<10.1f} {r['cagr']:>7.2%} {r['sharpe']:>8.2f} "
              f"{r['max_drawdown']:>9.1%} {r['volatility']:>10.1%} "
              f"${r['final_value']:>13,.0f} ${r['avg_annual_financing']:>12,.0f}")
        if delta:
            print(f"{'':>10} {delta}")

    if run_trimmed and results_trimmed:
        print(f"\n--- Without Anomalous Last Day ---")
        print(f"\n{header}")
        print("-" * 78)

        baseline_cagr_t = results_trimmed[0]['cagr']
        for r in results_trimmed:
            delta = f"({r['cagr'] - baseline_cagr_t:+.2%})" if r['leverage'] > 1.0 else ""
            print(f"{r['leverage']:<10.1f} {r['cagr']:>7.2%} {r['sharpe']:>8.2f} "
                  f"{r['max_drawdown']:>9.1%} {r['volatility']:>10.1%} "
                  f"${r['final_value']:>13,.0f} ${r['avg_annual_financing']:>12,.0f}")
            if delta:
                print(f"{'':>10} {delta}")

    # Incremental analysis for recommended 1.3x
    print("\n" + "=" * 90)
    print("DETAILED: 1.3x BOX SPREAD LEVERAGE")
    print("=" * 90)

    base = results[0]
    target_idx = LEVERAGE_RATIOS.index(1.3)
    lev13 = results[target_idx]

    print(f"\n  Equity deployed:        $130,000 ($100K equity + $30K box spread)")
    print(f"  Financing rate:         SOFR + 20bps (variable, ~{FED_FUNDS_BY_YEAR[2025]+0.20:.1f}% current)")
    print(f"  Avg annual fin. cost:   ${lev13['avg_annual_financing']:,.0f}")
    print(f"\n  {'Metric':<22} {'1.0x (Baseline)':>18} {'1.3x (Leveraged)':>18} {'Delta':>12}")
    print(f"  {'-'*72}")
    print(f"  {'CAGR':<22} {base['cagr']:>17.2%} {lev13['cagr']:>17.2%} {lev13['cagr']-base['cagr']:>+11.2%}")
    print(f"  {'Sharpe Ratio':<22} {base['sharpe']:>18.2f} {lev13['sharpe']:>18.2f} {lev13['sharpe']-base['sharpe']:>+12.2f}")
    print(f"  {'Max Drawdown':<22} {base['max_drawdown']:>17.1%} {lev13['max_drawdown']:>17.1%} {lev13['max_drawdown']-base['max_drawdown']:>+11.1%}")
    print(f"  {'Volatility':<22} {base['volatility']:>17.1%} {lev13['volatility']:>17.1%} {lev13['volatility']-base['volatility']:>+11.1%}")
    print(f"  {'Final Value':<22} ${base['final_value']:>16,.0f} ${lev13['final_value']:>16,.0f}")

    if run_trimmed and results_trimmed:
        base_t = results_trimmed[0]
        lev13_t = results_trimmed[target_idx]
        print(f"\n  --- Without anomalous last day ---")
        print(f"  {'Metric':<22} {'1.0x (Baseline)':>18} {'1.3x (Leveraged)':>18} {'Delta':>12}")
        print(f"  {'-'*72}")
        print(f"  {'CAGR':<22} {base_t['cagr']:>17.2%} {lev13_t['cagr']:>17.2%} {lev13_t['cagr']-base_t['cagr']:>+11.2%}")
        print(f"  {'Sharpe Ratio':<22} {base_t['sharpe']:>18.2f} {lev13_t['sharpe']:>18.2f} {lev13_t['sharpe']-base_t['sharpe']:>+12.2f}")
        print(f"  {'Max Drawdown':<22} {base_t['max_drawdown']:>17.1%} {lev13_t['max_drawdown']:>17.1%} {lev13_t['max_drawdown']-base_t['max_drawdown']:>+11.1%}")
        print(f"  {'Volatility':<22} {base_t['volatility']:>17.1%} {lev13_t['volatility']:>17.1%} {lev13_t['volatility']-base_t['volatility']:>+11.1%}")
        print(f"  {'Final Value':<22} ${base_t['final_value']:>16,.0f} ${lev13_t['final_value']:>16,.0f}")

    # Break-even analysis
    print(f"\n--- Break-Even Analysis ---")
    print(f"  At what financing rate does 1.3x leverage break even with 1.0x?")
    print(f"  Rule: leverage adds value when strategy return > financing rate")
    print(f"  Strategy CAGR (unlevered): {base['cagr']:.2%}")
    # Weighted avg financing rate across the backtest
    avg_rate_pct = sum(get_financing_rate(y) for y in range(2000, 2027)) / 27 * 100
    print(f"  Avg historical SOFR+20bps: ~{avg_rate_pct:.1f}%")
    print(f"  Spread (CAGR - financing): ~{base['cagr']*100 - avg_rate_pct:.1f}pp (positive = leverage adds value)")
    print(f"  Break-even financing rate: ~{base['cagr']:.2%}")

    # Save equity curves
    output_dir = os.path.join(BASE_DIR, 'backtests')
    for r in results:
        lev_str = f"{r['leverage']:.1f}".replace('.', '')
        r['equity_curve'].to_csv(
            os.path.join(output_dir, f'exp63_leverage_{lev_str}x.csv'), index=False)

    # Risk-adjusted comparison
    print(f"\n--- Risk-Adjusted Comparison ---")
    print(f"  {'Leverage':<10} {'Return/DD':>12} {'Calmar':>10} {'Incremental CAGR':>18} {'Incremental DD':>16}")
    print(f"  {'-'*68}")
    for r in results:
        ret_dd = abs(r['cagr'] / r['max_drawdown']) if r['max_drawdown'] != 0 else 0
        calmar = r['cagr'] / abs(r['max_drawdown']) if r['max_drawdown'] != 0 else 0
        inc_cagr = r['cagr'] - base['cagr'] if r['leverage'] > 1.0 else 0
        inc_dd = r['max_drawdown'] - base['max_drawdown'] if r['leverage'] > 1.0 else 0
        print(f"  {r['leverage']:<10.1f} {ret_dd:>12.3f} {calmar:>10.3f} {inc_cagr:>+17.2%} {inc_dd:>+15.1%}")

    print(f"\n{'='*90}")
    print(f"EXPERIMENT #63 COMPLETE")
    print(f"Recommendation: 1.3x via box spread adds ~{lev13['cagr']-base['cagr']:+.2%} CAGR")
    print(f"but deepens MaxDD from {base['max_drawdown']:.1%} to {lev13['max_drawdown']:.1%}")
    print(f"{'='*90}")
