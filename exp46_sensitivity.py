"""
Exp46: Portfolio Stop Loss Sensitivity Analysis
Grid search: -13% to -20% in 1% increments
Also includes -16.5%, -17.5% for fine-grained analysis around -17%
"""

import subprocess
import re
import json
import os

# Values to test
STOP_VALUES = [-0.13, -0.14, -0.15, -0.16, -0.165, -0.17, -0.175, -0.18, -0.19, -0.20]

COMPASS_FILE = os.path.join(os.path.dirname(__file__), 'omnicapital_v8_compass.py')

def run_backtest(stop_value):
    """Modify the stop loss parameter and run the backtest."""
    # Read the file
    with open(COMPASS_FILE, 'r') as f:
        content = f.read()

    # Replace the PORTFOLIO_STOP_LOSS line
    import re as re2
    content = re2.sub(
        r'PORTFOLIO_STOP_LOSS = -[\d.]+.*',
        f'PORTFOLIO_STOP_LOSS = {stop_value}  # Sensitivity test',
        content
    )

    # Write back
    with open(COMPASS_FILE, 'w') as f:
        f.write(content)

    # Run backtest
    result = subprocess.run(
        ['python', COMPASS_FILE],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(__file__)
    )

    output = result.stdout

    # Parse results
    metrics = {}
    metrics['stop_loss'] = stop_value

    # Extract key metrics
    patterns = {
        'cagr': r'CAGR:\s+([\d.]+)%',
        'sharpe': r'Sharpe ratio:\s+([\d.]+)',
        'max_dd': r'Max drawdown:\s+-([\d.]+)%',
        'calmar': r'Calmar ratio:\s+([\d.]+)',
        'final_value': r'Final value:\s+\$\s*([\d,]+)',
        'trades': r'Trades executed:\s+([\d,]+)',
        'win_rate': r'Win rate:\s+([\d.]+)%',
        'stop_events': r'Stop loss events:\s+(\d+)',
        'protection_days_pct': r'Days in protection:\s+[\d,]+\s+\(([\d.]+)%\)',
        'positive_years': r'Positive years:\s+(\d+)/26',
        'volatility': r'Volatility \(annual\):\s+([\d.]+)%',
        'sortino': r'Sortino ratio:\s+([\d.]+)',
        'worst_year': r'Worst year:\s+-([\d.]+)%',
        'best_year': r'Best year:\s+([\d.]+)%',
        'profit_factor': r'Avg winner:.*\$\s*([\d,.]+)',
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, output)
        if match:
            val = match.group(1).replace(',', '')
            try:
                metrics[key] = float(val)
            except:
                metrics[key] = val
        else:
            metrics[key] = None

    return metrics


def main():
    results = []

    print("=" * 100)
    print("EXP46: PORTFOLIO STOP LOSS SENSITIVITY ANALYSIS")
    print("=" * 100)
    print()

    for i, sv in enumerate(STOP_VALUES):
        pct = abs(sv) * 100
        print(f"[{i+1}/{len(STOP_VALUES)}] Testing PORTFOLIO_STOP_LOSS = {sv:.1%} ...", end=" ", flush=True)
        metrics = run_backtest(sv)
        results.append(metrics)

        if metrics['cagr'] is not None:
            print(f"CAGR: {metrics['cagr']:.2f}% | Sharpe: {metrics['sharpe']:.2f} | MaxDD: -{metrics['max_dd']:.1f}% | Calmar: {metrics['calmar']:.2f} | Stops: {int(metrics['stop_events'])} | Prot: {metrics['protection_days_pct']:.1f}%")
        else:
            print("FAILED - could not parse output")

    # Print summary table
    print()
    print("=" * 100)
    print("SUMMARY TABLE")
    print("=" * 100)
    print(f"{'Stop Loss':>10} | {'CAGR':>7} | {'Sharpe':>7} | {'MaxDD':>7} | {'Calmar':>7} | {'Stops':>6} | {'Prot%':>6} | {'Final$':>12} | {'WinRate':>8} | {'Yr+':>4} | {'Vol':>6}")
    print("-" * 100)

    for r in results:
        if r['cagr'] is not None:
            print(f"{r['stop_loss']:>10.1%} | {r['cagr']:>6.2f}% | {r['sharpe']:>7.2f} | {r['max_dd']:>6.1f}% | {r['calmar']:>7.2f} | {int(r['stop_events']):>6} | {r['protection_days_pct']:>5.1f}% | ${r['final_value']:>11,.0f} | {r['win_rate']:>7.1f}% | {int(r['positive_years']) if r['positive_years'] else 'N/A':>4} | {r['volatility']:>5.1f}%")

    # Find best by each metric
    print()
    print("=" * 100)
    print("BEST BY METRIC")
    print("=" * 100)

    valid = [r for r in results if r['cagr'] is not None]

    best_cagr = max(valid, key=lambda x: x['cagr'])
    best_sharpe = max(valid, key=lambda x: x['sharpe'])
    best_calmar = max(valid, key=lambda x: x['calmar'])
    lowest_dd = min(valid, key=lambda x: x['max_dd'])

    print(f"Best CAGR:   {best_cagr['stop_loss']:.1%} -> {best_cagr['cagr']:.2f}%")
    print(f"Best Sharpe: {best_sharpe['stop_loss']:.1%} -> {best_sharpe['sharpe']:.2f}")
    print(f"Best Calmar: {best_calmar['stop_loss']:.1%} -> {best_calmar['calmar']:.2f}")
    print(f"Lowest MaxDD:{lowest_dd['stop_loss']:.1%} -> -{lowest_dd['max_dd']:.1f}%")

    # Determine if -17% is a peak or part of a plateau
    print()
    print("=" * 100)
    print("ROBUSTNESS ANALYSIS")
    print("=" * 100)

    # Check if nearby values are similar
    target_idx = next(i for i, r in enumerate(valid) if abs(r['stop_loss'] - (-0.17)) < 0.001)
    target_calmar = valid[target_idx]['calmar']

    plateau_threshold = 0.80  # within 80% of best
    plateau_values = [r for r in valid if r['calmar'] >= target_calmar * plateau_threshold]

    print(f"Target (-17%) Calmar: {target_calmar:.2f}")
    print(f"Values within 80% of target Calmar ({target_calmar * plateau_threshold:.2f}):")
    for r in plateau_values:
        print(f"  {r['stop_loss']:.1%}: Calmar {r['calmar']:.2f}, CAGR {r['cagr']:.2f}%")

    if len(plateau_values) >= 3:
        print("\n>>> PLATEAU DETECTED: Result appears ROBUST across multiple thresholds")
    else:
        print("\n>>> ISOLATED PEAK: Result appears FRAGILE / potential overfitting")

    # Save results
    output_file = os.path.join(os.path.dirname(__file__), 'backtests', 'exp46_sensitivity_results.json')
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {output_file}")


if __name__ == '__main__':
    main()
