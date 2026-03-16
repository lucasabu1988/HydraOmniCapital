import json
import os
from datetime import datetime

import numpy as np
import pandas as pd


SEED = 666
N_SIMULATIONS = 10_000
HORIZON_DAYS = 252
CYCLE_DAYS = 5
MIN_LIVE_CYCLES = 8

STATE_FILE = os.path.join('state', 'compass_state_latest.json')
CYCLE_LOG_FILE = os.path.join('state', 'cycle_log.json')
BACKTEST_DAILY_CSV = os.path.join('backtests', 'hydra_clean_daily.csv')

V84_CONFIG = {
    'DD_SCALE_TIER1': -0.10,
    'DD_SCALE_TIER2': -0.20,
    'DD_SCALE_TIER3': -0.35,
    'LEV_FULL': 1.0,
    'LEV_MID': 0.60,
    'LEV_FLOOR': 0.30,
    'CRASH_VEL_5D': -0.06,
    'CRASH_VEL_10D': -0.10,
    'CRASH_LEVERAGE': 0.15,
    'CRASH_COOLDOWN': 10,
}


def _dd_leverage(drawdown, config):
    t1 = config['DD_SCALE_TIER1']
    t2 = config['DD_SCALE_TIER2']
    t3 = config['DD_SCALE_TIER3']
    lf = config['LEV_FULL']
    lm = config['LEV_MID']
    lfl = config['LEV_FLOOR']
    if drawdown >= t1:
        return lf
    if drawdown >= t2:
        frac = (drawdown - t1) / (t2 - t1)
        return lf + frac * (lm - lf)
    if drawdown >= t3:
        frac = (drawdown - t2) / (t3 - t2)
        return lm + frac * (lfl - lm)
    return lfl


class COMPASSMonteCarlo:
    def __init__(self, cycle_log_path=CYCLE_LOG_FILE,
                 daily_csv_path=BACKTEST_DAILY_CSV,
                 n_simulations=N_SIMULATIONS,
                 seed=SEED,
                 horizon_days=HORIZON_DAYS):
        self.cycle_log_path = cycle_log_path
        self.daily_csv_path = daily_csv_path
        self.n_simulations = n_simulations
        self.seed = seed
        self.horizon_days = horizon_days
        self.cycle_days = CYCLE_DAYS
        self.source = None
        self.initial_value = self._load_initial_value()
        self.cycle_returns = np.array([], dtype=float)
        self.paths = None

    def _load_initial_value(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as handle:
                    state = json.load(handle)
                portfolio_value = float(state.get('portfolio_value', 100000))
                if portfolio_value > 0:
                    return portfolio_value
            except Exception:
                pass
        return 100000.0

    def load_live_cycle_returns(self):
        if not os.path.exists(self.cycle_log_path):
            return np.array([], dtype=float)

        try:
            with open(self.cycle_log_path, 'r', encoding='utf-8') as handle:
                cycles = json.load(handle)
        except Exception:
            return np.array([], dtype=float)

        values = []
        for cycle in cycles:
            if cycle.get('status') != 'closed':
                continue
            cycle_return = cycle.get('cycle_return_pct')
            if cycle_return is None:
                cycle_return = cycle.get('hydra_return')
            try:
                cycle_return = float(cycle_return)
            except (TypeError, ValueError):
                continue
            if np.isfinite(cycle_return):
                values.append(cycle_return / 100.0)
        return np.array(values, dtype=float)

    def load_backtest_cycle_returns(self):
        if not os.path.exists(self.daily_csv_path):
            raise FileNotFoundError(f"Backtest daily CSV not found: {self.daily_csv_path}")

        df = pd.read_csv(self.daily_csv_path)
        if 'value' not in df.columns:
            raise ValueError("Backtest daily CSV must contain a value column")

        values = pd.to_numeric(df['value'], errors='coerce').dropna()
        if len(values) <= self.cycle_days:
            raise ValueError("Backtest daily CSV does not have enough data for 5-day cycles")

        cycle_returns = values.pct_change(self.cycle_days).dropna().iloc[::self.cycle_days]
        cycle_returns = cycle_returns[np.isfinite(cycle_returns)]
        return cycle_returns.to_numpy(dtype=float)

    def load_input_returns(self):
        live_returns = self.load_live_cycle_returns()
        if len(live_returns) >= MIN_LIVE_CYCLES:
            self.source = 'live_cycle_log'
            self.cycle_returns = live_returns
            return

        self.source = 'backtest_fallback'
        self.cycle_returns = self.load_backtest_cycle_returns()

    def _simulate_single_path(self, sampled_returns):
        values = np.empty(len(sampled_returns) + 1, dtype=float)
        values[0] = self.initial_value
        peak_value = self.initial_value
        crash_cooldown = 0
        realized_cycle_returns = []

        for idx, sampled_return in enumerate(sampled_returns, start=1):
            drawdown = (values[idx - 1] - peak_value) / peak_value if peak_value > 0 else 0.0
            leverage = _dd_leverage(drawdown, V84_CONFIG)

            recent_10d = None
            if len(realized_cycle_returns) >= 2:
                recent_10d = (1 + realized_cycle_returns[-2]) * (1 + realized_cycle_returns[-1]) - 1

            if crash_cooldown > 0:
                leverage = min(leverage, V84_CONFIG['CRASH_LEVERAGE'])
                crash_cooldown -= 1
            elif realized_cycle_returns:
                if realized_cycle_returns[-1] <= V84_CONFIG['CRASH_VEL_5D']:
                    leverage = min(leverage, V84_CONFIG['CRASH_LEVERAGE'])
                    crash_cooldown = V84_CONFIG['CRASH_COOLDOWN'] - 1
                elif recent_10d is not None and recent_10d <= V84_CONFIG['CRASH_VEL_10D']:
                    leverage = min(leverage, V84_CONFIG['CRASH_LEVERAGE'])
                    crash_cooldown = V84_CONFIG['CRASH_COOLDOWN'] - 1

            effective_return = sampled_return * leverage
            realized_cycle_returns.append(effective_return)
            values[idx] = values[idx - 1] * (1 + effective_return)
            peak_value = max(peak_value, values[idx])

        return values

    def run_simulation(self):
        if len(self.cycle_returns) == 0:
            self.load_input_returns()

        n_cycles = int(np.ceil(self.horizon_days / self.cycle_days))
        rng = np.random.default_rng(self.seed)
        sampled = rng.choice(self.cycle_returns, size=(self.n_simulations, n_cycles), replace=True)
        self.paths = np.vstack([self._simulate_single_path(path) for path in sampled])

    def _historical_stats(self):
        cycle_returns = self.cycle_returns
        return {
            'source': self.source,
            'sample_size': int(len(cycle_returns)),
            'avg_cycle_return_pct': round(float(cycle_returns.mean() * 100), 3),
            'median_cycle_return_pct': round(float(np.median(cycle_returns) * 100), 3),
            'cycle_vol_pct': round(float(cycle_returns.std(ddof=0) * 100), 3),
            'win_rate_pct': round(float(np.mean(cycle_returns > 0) * 100), 2),
        }

    def _fan_chart(self):
        percentiles = np.percentile(self.paths, [5, 25, 50, 75, 95], axis=0)
        days = [idx * self.cycle_days for idx in range(self.paths.shape[1])]
        return {
            'days': days,
            'p5': [round(float(value), 2) for value in percentiles[0]],
            'p25': [round(float(value), 2) for value in percentiles[1]],
            'p50': [round(float(value), 2) for value in percentiles[2]],
            'p75': [round(float(value), 2) for value in percentiles[3]],
            'p95': [round(float(value), 2) for value in percentiles[4]],
        }

    def _summary(self):
        final_values = self.paths[:, -1]
        total_returns = (final_values / self.initial_value) - 1.0
        running_max = np.maximum.accumulate(self.paths, axis=1)
        drawdowns = (self.paths - running_max) / running_max
        max_drawdowns = drawdowns.min(axis=1)

        return {
            'median_outcome': round(float(np.median(final_values)), 2),
            'p5_outcome': round(float(np.percentile(final_values, 5)), 2),
            'p95_outcome': round(float(np.percentile(final_values, 95)), 2),
            'median_return_pct': round(float(np.median(total_returns) * 100), 2),
            'p5_return_pct': round(float(np.percentile(total_returns, 5) * 100), 2),
            'p95_return_pct': round(float(np.percentile(total_returns, 95) * 100), 2),
            'prob_gain_10_pct': round(float(np.mean(total_returns > 0.10) * 100), 2),
            'prob_drawdown_better_than_20_pct': round(float(np.mean(max_drawdowns > -0.20) * 100), 2),
            'median_max_drawdown_pct': round(float(np.median(max_drawdowns) * 100), 2),
        }

    def get_summary(self):
        if self.paths is None:
            self.run_simulation()

        return {
            'generated_at': datetime.now().isoformat(),
            'seed': self.seed,
            'n_simulations': self.n_simulations,
            'initial_value': round(float(self.initial_value), 2),
            'horizon_days': self.horizon_days,
            'cycle_days': self.cycle_days,
            'source': self.source,
            'historical_stats': self._historical_stats(),
            'summary': self._summary(),
            'fan_chart': self._fan_chart(),
        }

    def run_all(self):
        self.load_input_returns()
        self.run_simulation()
        return self.get_summary()


if __name__ == '__main__':
    results = COMPASSMonteCarlo().run_all()
    print(json.dumps(results, indent=2))
