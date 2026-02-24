"""
COMPASS v8.2 Monte Carlo Portfolio Simulator
=============================================
Inspired by Google Cloud Data Science Guide (Case 5: CPI Prediction).

Generates N=10,000 simulated future equity paths from historical COMPASS
daily returns using bootstrap sampling. Computes confidence bands,
milestone probabilities, and drawdown risk distributions.

Usage:
    python compass_montecarlo.py
"""

import os
import numpy as np
import pandas as pd
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DAILY_CSV = os.path.join(SCRIPT_DIR, 'backtests', 'v8_compass_daily.csv')
SEED = 666
N_SIMULATIONS = 10_000
TRADING_DAYS_PER_YEAR = 252


class COMPASSMonteCarlo:
    """Monte Carlo portfolio simulator for COMPASS v8.2."""

    def __init__(self, daily_csv_path=DAILY_CSV, n_simulations=N_SIMULATIONS, seed=SEED):
        self.daily_csv_path = daily_csv_path
        self.n_simulations = n_simulations
        self.seed = seed
        self.daily_returns = None
        self.historical_stats = {}
        self.simulated_paths = {}
        self.results = {}

    def load_data(self):
        """Load backtest equity curve and compute daily returns."""
        df = pd.read_csv(self.daily_csv_path, parse_dates=['date'])
        df = df.sort_values('date').reset_index(drop=True)

        values = df['value'].values
        daily_ret = np.diff(values) / values[:-1]
        daily_ret = daily_ret[np.isfinite(daily_ret)]
        self.daily_returns = daily_ret

        n_years = len(daily_ret) / TRADING_DAYS_PER_YEAR
        annual_return = (1 + daily_ret.mean()) ** TRADING_DAYS_PER_YEAR - 1
        annual_vol = daily_ret.std() * np.sqrt(TRADING_DAYS_PER_YEAR)

        self.historical_stats = {
            'n_days': len(daily_ret),
            'n_years': round(n_years, 1),
            'mean_daily': float(daily_ret.mean()),
            'std_daily': float(daily_ret.std()),
            'annual_return': float(annual_return),
            'annual_vol': float(annual_vol),
            'sharpe': float(annual_return / annual_vol) if annual_vol > 0 else 0.0,
            'min_daily': float(daily_ret.min()),
            'max_daily': float(daily_ret.max()),
        }

    def run_simulation(self, horizons_years=None, initial_capital=100_000):
        """Run Monte Carlo simulation for each horizon via bootstrap sampling."""
        if horizons_years is None:
            horizons_years = [1, 3, 5, 10]
        if self.daily_returns is None:
            self.load_data()

        rng = np.random.default_rng(seed=self.seed)

        for h in horizons_years:
            n_days = h * TRADING_DAYS_PER_YEAR
            # Bootstrap: sample daily returns with replacement
            sampled = rng.choice(self.daily_returns, size=(self.n_simulations, n_days), replace=True)
            # Cumulative equity paths
            growth = np.cumprod(1 + sampled, axis=1)
            paths = initial_capital * growth

            # Percentile bands
            percentiles = {}
            for p in [5, 25, 50, 75, 95]:
                percentiles[p] = np.percentile(paths, p, axis=0)

            # Final values
            final_values = paths[:, -1]

            self.simulated_paths[h] = paths
            self.results[h] = {
                'horizon_years': h,
                'n_days': n_days,
                'initial_capital': initial_capital,
                'percentiles': percentiles,
                'final_values': final_values,
                'final_stats': {
                    'mean': float(final_values.mean()),
                    'median': float(np.median(final_values)),
                    'std': float(final_values.std()),
                    'min': float(final_values.min()),
                    'max': float(final_values.max()),
                    'p5': float(np.percentile(final_values, 5)),
                    'p25': float(np.percentile(final_values, 25)),
                    'p75': float(np.percentile(final_values, 75)),
                    'p95': float(np.percentile(final_values, 95)),
                },
            }

    def compute_milestones(self, targets=None, initial_capital=100_000):
        """Compute probability of reaching target values per horizon."""
        if targets is None:
            targets = [200_000, 500_000, 1_000_000]

        milestones = {}
        for h, res in self.results.items():
            final_vals = res['final_values']
            milestones[h] = {}
            for t in targets:
                prob = float(np.mean(final_vals >= t))
                milestones[h][t] = round(prob, 4)
        return milestones

    def compute_drawdown_risk(self, thresholds=None):
        """Compute probability of max drawdown exceeding thresholds per horizon."""
        if thresholds is None:
            thresholds = [-0.30, -0.40, -0.50]

        dd_risk = {}
        for h, paths in self.simulated_paths.items():
            running_max = np.maximum.accumulate(paths, axis=1)
            drawdowns = (paths - running_max) / running_max
            max_dd_per_sim = drawdowns.min(axis=1)

            dd_risk[h] = {}
            for t in thresholds:
                prob = float(np.mean(max_dd_per_sim < t))
                dd_risk[h][t] = round(prob, 4)
        return dd_risk

    def get_fan_chart_data(self, horizon_years=10, max_points=500):
        """Return downsampled percentile paths for Chart.js rendering."""
        if horizon_years not in self.results:
            return {}

        res = self.results[horizon_years]
        n_days = res['n_days']
        step = max(1, n_days // max_points)
        indices = list(range(0, n_days, step))
        if indices[-1] != n_days - 1:
            indices.append(n_days - 1)

        # Convert to year offsets
        years = [round(i / TRADING_DAYS_PER_YEAR, 2) for i in indices]

        chart_data = {'years': years}
        for p in [5, 25, 50, 75, 95]:
            chart_data[f'p{p}'] = [round(float(res['percentiles'][p][i]), 2) for i in indices]

        return chart_data

    def get_summary(self):
        """Return JSON-serializable summary for dashboard API."""
        milestones = self.compute_milestones()
        dd_risk = self.compute_drawdown_risk()
        fan_chart = self.get_fan_chart_data(horizon_years=10)

        horizons_summary = {}
        for h, res in self.results.items():
            horizons_summary[str(h)] = {
                'horizon_years': h,
                'final_stats': res['final_stats'],
                'milestones': {str(k): v for k, v in milestones.get(h, {}).items()},
                'drawdown_risk': {str(k): v for k, v in dd_risk.get(h, {}).items()},
            }

        return {
            'generated_at': datetime.now().isoformat(),
            'n_simulations': self.n_simulations,
            'seed': self.seed,
            'historical_stats': self.historical_stats,
            'horizons': horizons_summary,
            'fan_chart': fan_chart,
        }

    def run_all(self):
        """Load data, run simulation, return summary."""
        self.load_data()
        self.run_simulation()
        return self.get_summary()


def print_report(summary):
    """Print formatted Monte Carlo report to console."""
    stats = summary['historical_stats']
    print("=" * 70)
    print("  COMPASS v8.2 -- Monte Carlo Portfolio Simulator")
    print(f"  {summary['n_simulations']:,} simulations | seed {summary['seed']}")
    print("=" * 70)
    print()
    print("  HISTORICAL STATISTICS (backtest 2000-2026)")
    print(f"  {'Daily returns:':<25} {stats['n_days']:,} days ({stats['n_years']} years)")
    print(f"  {'Annual return:':<25} {stats['annual_return']*100:>8.2f}%")
    print(f"  {'Annual volatility:':<25} {stats['annual_vol']*100:>8.2f}%")
    print(f"  {'Sharpe ratio:':<25} {stats['sharpe']:>8.2f}")
    print(f"  {'Worst day:':<25} {stats['min_daily']*100:>8.2f}%")
    print(f"  {'Best day:':<25} {stats['max_daily']*100:>8.2f}%")
    print()

    print("  PROJECTED FINAL VALUES (from $100K)")
    print(f"  {'Horizon':<10} {'5th%':>12} {'25th%':>12} {'Median':>12} {'75th%':>12} {'95th%':>12}")
    print("  " + "-" * 68)
    for h_str in sorted(summary['horizons'].keys(), key=lambda x: int(x)):
        h_data = summary['horizons'][h_str]
        fs = h_data['final_stats']
        print(f"  {h_str + 'yr':<10} ${fs['p5']:>10,.0f} ${fs['p25']:>10,.0f} ${fs['median']:>10,.0f} ${fs['p75']:>10,.0f} ${fs['p95']:>10,.0f}")
    print()

    print("  MILESTONE PROBABILITIES")
    print(f"  {'Horizon':<10} {'P(>$200K)':>12} {'P(>$500K)':>12} {'P(>$1M)':>12}")
    print("  " + "-" * 44)
    for h_str in sorted(summary['horizons'].keys(), key=lambda x: int(x)):
        m = summary['horizons'][h_str]['milestones']
        vals = [m.get('200000', 0), m.get('500000', 0), m.get('1000000', 0)]
        print(f"  {h_str + 'yr':<10} {vals[0]*100:>11.1f}% {vals[1]*100:>11.1f}% {vals[2]*100:>11.1f}%")
    print()

    print("  DRAWDOWN RISK (probability of max DD exceeding threshold)")
    print(f"  {'Horizon':<10} {'P(DD>30%)':>12} {'P(DD>40%)':>12} {'P(DD>50%)':>12}")
    print("  " + "-" * 44)
    for h_str in sorted(summary['horizons'].keys(), key=lambda x: int(x)):
        d = summary['horizons'][h_str]['drawdown_risk']
        vals = [d.get('-0.3', 0), d.get('-0.4', 0), d.get('-0.5', 0)]
        print(f"  {h_str + 'yr':<10} {vals[0]*100:>11.1f}% {vals[1]*100:>11.1f}% {vals[2]*100:>11.1f}%")
    print()
    print("=" * 70)


if __name__ == '__main__':
    mc = COMPASSMonteCarlo()
    summary = mc.run_all()
    print_report(summary)
