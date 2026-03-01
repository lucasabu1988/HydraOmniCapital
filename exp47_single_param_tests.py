"""
Exp47: Single Parameter Tests
Tests 4 proposals individually against baseline.
Each test modifies ONE parameter, runs backtest, restores original.
"""

import subprocess
import re
import json
import os
import time

COMPASS_FILE = os.path.join(os.path.dirname(__file__), 'omnicapital_v8_compass.py')

# Baseline parameters (for restoration)
BASELINE = {
    'RECOVERY_STAGE_1_DAYS': '63',
    'RECOVERY_STAGE_2_DAYS': '126',
    'LEVERAGE_MIN': '0.3',
    'MOMENTUM_LOOKBACK': '90',
}

# Tests to run
TESTS = [
    {
        'name': 'BASELINE',
        'params': {},  # No changes
    },
    {
        'name': 'P1_RECOVERY_S1_42d',
        'params': {'RECOVERY_STAGE_1_DAYS': '42'},
    },
    {
        'name': 'P2_RECOVERY_S2_100d',
        'params': {'RECOVERY_STAGE_2_DAYS': '100'},
    },
    {
        'name': 'P3_LEV_MIN_0.5',
        'params': {'LEVERAGE_MIN': '0.5'},
    },
    {
        'name': 'P4_MOM_120d',
        'params': {'MOMENTUM_LOOKBACK': '120'},
    },
]


def modify_param(content, param_name, new_value):
    """Replace a parameter value in the file content."""
    # Match patterns like: PARAM_NAME = value  or PARAM_NAME = value  # comment
    pattern = rf'^({param_name}\s*=\s*)[\d.]+(.*)$'
    replacement = rf'\g<1>{new_value}\2'
    new_content, count = re.subn(pattern, replacement, content, flags=re.MULTILINE)
    if count == 0:
        print(f"  WARNING: Could not find parameter {param_name}")
    return new_content


def restore_baseline(original_content):
    """Write the original content back."""
    with open(COMPASS_FILE, 'w') as f:
        f.write(original_content)


def run_backtest():
    """Run the backtest and parse results."""
    result = subprocess.run(
        ['python', COMPASS_FILE],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(__file__),
        timeout=600
    )

    output = result.stdout
    metrics = {}

    patterns = {
        'cagr': r'CAGR:\s+([\d.]+)%',
        'sharpe': r'Sharpe ratio:\s+([\d.]+)',
        'max_dd': r'Max drawdown:\s+-([\d.]+)%',
        'calmar': r'Calmar ratio:\s+([\d.]+)',
        'final_value': r'Final value:\s+\$\s*([\d,]+)',
        'trades': r'Trades executed:\s+([\d,]+)',
        'win_rate': r'Win rate:\s+([\d.]+)%',
        'stop_events': r'Stop loss events:\s+(\d+)|DD scale events.*?:\s+(\d+)',
        'protection_days_pct': r'Days in protection:\s+[\d,]+\s+\(([\d.]+)%\)|Days at low leverage:\s+[\d,]+\s+\(([\d.]+)%\)',
        'volatility': r'Volatility \(annual\):\s+([\d.]+)%',
        'sortino': r'Sortino ratio:\s+([\d.]+)',
        'worst_year': r'Worst year:\s+-([\d.]+)%',
        'best_year': r'Best year:\s+([\d.]+)%',
        'positive_years': r'Positive years:\s+(\d+)/(\d+)',
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, output)
        if match:
            # Handle multi-group patterns
            val = None
            for g in match.groups():
                if g is not None:
                    val = g
                    break
            if val:
                val = val.replace(',', '')
                try:
                    metrics[key] = float(val)
                except ValueError:
                    metrics[key] = val
        else:
            metrics[key] = None

    # Special handling for positive_years
    match = re.search(r'Positive years:\s+(\d+)/(\d+)', output)
    if match:
        metrics['positive_years'] = f"{match.group(1)}/{match.group(2)}"

    return metrics


def main():
    # Read original file
    with open(COMPASS_FILE, 'r') as f:
        original_content = f.read()

    results = []

    print("=" * 110)
    print("EXP47: SINGLE PARAMETER TESTS")
    print("=" * 110)
    print()

    for i, test in enumerate(TESTS):
        name = test['name']
        params = test['params']

        print(f"[{i+1}/{len(TESTS)}] Testing: {name}", end="", flush=True)

        if params:
            # Modify parameters
            content = original_content
            for param_name, new_value in params.items():
                content = modify_param(content, param_name, new_value)
                print(f" ({param_name}={new_value})", end="", flush=True)
            with open(COMPASS_FILE, 'w') as f:
                f.write(content)

        print(" ... running", flush=True)
        start = time.time()

        try:
            metrics = run_backtest()
            elapsed = time.time() - start
            metrics['name'] = name
            metrics['elapsed'] = elapsed
            results.append(metrics)

            if metrics.get('cagr') is not None:
                print(f"  -> CAGR: {metrics['cagr']:.2f}% | Sharpe: {metrics['sharpe']:.2f} | "
                      f"MaxDD: -{metrics['max_dd']:.1f}% | Calmar: {metrics['calmar']:.2f} | "
                      f"Stops: {int(metrics.get('stop_events', 0))} | "
                      f"Prot: {metrics.get('protection_days_pct', 0):.1f}% | "
                      f"({elapsed:.0f}s)")
            else:
                print(f"  -> FAILED to parse output ({elapsed:.0f}s)")
        except Exception as e:
            print(f"  -> ERROR: {e}")
            results.append({'name': name, 'error': str(e)})

        # Always restore
        restore_baseline(original_content)

    # Summary table
    print()
    print("=" * 110)
    print("SUMMARY TABLE")
    print("=" * 110)
    print(f"{'Test':<25} | {'CAGR':>7} | {'Sharpe':>7} | {'MaxDD':>7} | {'Calmar':>7} | {'Stops':>6} | {'Prot%':>6} | {'Final$':>12} | {'WinRate':>8} | {'Yr+':>6}")
    print("-" * 110)

    baseline_cagr = None
    for r in results:
        if r.get('cagr') is None:
            print(f"{r['name']:<25} | {'FAILED':>7}")
            continue

        cagr = r['cagr']
        if baseline_cagr is None:
            baseline_cagr = cagr

        delta = cagr - baseline_cagr if baseline_cagr else 0
        delta_str = f"({delta:+.2f})" if r['name'] != 'BASELINE' else ""

        print(f"{r['name']:<25} | {cagr:>6.2f}% | {r['sharpe']:>7.2f} | {r['max_dd']:>6.1f}% | "
              f"{r['calmar']:>7.2f} | {int(r.get('stop_events', 0)):>6} | "
              f"{r.get('protection_days_pct', 0):>5.1f}% | "
              f"${r.get('final_value', 0):>11,.0f} | {r.get('win_rate', 0):>7.1f}% | "
              f"{r.get('positive_years', 'N/A'):>6} {delta_str}")

    # Best result
    print()
    print("=" * 110)
    print("ANALYSIS")
    print("=" * 110)

    valid = [r for r in results if r.get('cagr') is not None and r['name'] != 'BASELINE']
    if valid and baseline_cagr:
        best = max(valid, key=lambda x: x['cagr'])
        worst = min(valid, key=lambda x: x['cagr'])

        print(f"Baseline CAGR:  {baseline_cagr:.2f}%")
        print(f"Best result:    {best['name']} -> {best['cagr']:.2f}% (delta: {best['cagr'] - baseline_cagr:+.2f}%)")
        print(f"Worst result:   {worst['name']} -> {worst['cagr']:.2f}% (delta: {worst['cagr'] - baseline_cagr:+.2f}%)")

        improved = [r for r in valid if r['cagr'] > baseline_cagr]
        if improved:
            print(f"\nIMPROVED ({len(improved)}):")
            for r in sorted(improved, key=lambda x: x['cagr'], reverse=True):
                print(f"  {r['name']}: {r['cagr']:.2f}% ({r['cagr'] - baseline_cagr:+.2f}%) | "
                      f"Sharpe: {r['sharpe']:.2f} | MaxDD: -{r['max_dd']:.1f}%")
        else:
            print("\nNO improvements found. All proposals performed worse than baseline.")

        degraded = [r for r in valid if r['cagr'] < baseline_cagr]
        if degraded:
            print(f"\nDEGRADED ({len(degraded)}):")
            for r in sorted(degraded, key=lambda x: x['cagr']):
                print(f"  {r['name']}: {r['cagr']:.2f}% ({r['cagr'] - baseline_cagr:+.2f}%) | "
                      f"Sharpe: {r['sharpe']:.2f} | MaxDD: -{r['max_dd']:.1f}%")

    # Save results
    output_file = os.path.join(os.path.dirname(__file__), 'backtests', 'exp47_single_param_results.json')
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to: {output_file}")


if __name__ == '__main__':
    main()
