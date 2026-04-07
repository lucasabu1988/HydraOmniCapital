"""Layer A smoke tests — blocking for v1.

Mathematical invariants, statistical sanity, config consistency.
Runs after each backtest run, before reporting. Fails loud.
"""
import numpy as np
import pandas as pd

from hydra_backtest.engine import BacktestResult
from hydra_backtest.errors import HydraBacktestValidationError


# Known crash dates where daily returns can legitimately exceed ±15%.
# Used by the "no outlier daily returns" check to avoid false positives.
_CRASH_ALLOWLIST = {
    pd.Timestamp('2008-09-29'),  # Lehman Brothers
    pd.Timestamp('2008-10-13'),  # Bounce
    pd.Timestamp('2008-10-15'),
    pd.Timestamp('2008-10-28'),
    pd.Timestamp('2020-03-09'),  # COVID crash
    pd.Timestamp('2020-03-12'),
    pd.Timestamp('2020-03-13'),
    pd.Timestamp('2020-03-16'),
    pd.Timestamp('2020-03-17'),
    pd.Timestamp('2020-03-18'),
    pd.Timestamp('2020-03-24'),
}


def run_smoke_tests(result: BacktestResult) -> None:
    """Run all Layer A smoke tests.

    Raises HydraBacktestValidationError on any failure. Designed to run
    in <2 seconds on a 26-year backtest.
    """
    daily = result.daily_values
    config = result.config

    if len(daily) == 0:
        raise HydraBacktestValidationError("Backtest produced empty daily_values")

    # 1. No NaN in critical columns
    for col in ('portfolio_value', 'cash', 'drawdown', 'leverage'):
        if col in daily.columns and daily[col].isna().any():
            raise HydraBacktestValidationError(
                f"NaN detected in daily_values column: {col}"
            )

    # 2. Cash conservation (loose): cash never arbitrarily negative
    if (daily['cash'] < -1.0).any():
        raise HydraBacktestValidationError(
            f"Negative cash detected: min = {float(daily['cash'].min())}"
        )

    # 3. Drawdown bounds
    if (daily['drawdown'] < -1.0).any() or (daily['drawdown'] > 1e-4).any():
        raise HydraBacktestValidationError(
            f"drawdown out of [-1.0, 0] range: min={float(daily['drawdown'].min())}, "
            f"max={float(daily['drawdown'].max())}"
        )

    # 4. Leverage bounds
    lev_min = config.get('CRASH_LEVERAGE', 0.15) - 1e-6
    lev_max = config.get('LEVERAGE_MAX', 1.0) + 1e-6
    if (daily['leverage'] < lev_min).any() or (daily['leverage'] > lev_max).any():
        raise HydraBacktestValidationError(
            f"leverage out of [{lev_min}, {lev_max}] range: "
            f"min={float(daily['leverage'].min())}, max={float(daily['leverage'].max())}"
        )

    # 5. Position count bounds (bull override may add +1)
    n_max = config.get('NUM_POSITIONS', 5) + 1
    if (daily['n_positions'] < 0).any() or (daily['n_positions'] > n_max).any():
        raise HydraBacktestValidationError(
            f"n_positions out of [0, {n_max}] range: "
            f"min={int(daily['n_positions'].min())}, max={int(daily['n_positions'].max())}"
        )

    # 6. Peak portfolio value monotonic non-decreasing
    pv = daily['portfolio_value'].values
    peak = np.maximum.accumulate(pv)
    if not np.all(np.diff(peak) >= -1e-6):
        raise HydraBacktestValidationError(
            "Peak portfolio value is not monotonic non-decreasing"
        )

    # 7. Statistical sanity — annualized volatility
    returns = daily['portfolio_value'].pct_change().dropna()
    if len(returns) > 20:
        vol_ann = float(returns.std() * np.sqrt(252))
        if not (0.03 <= vol_ann <= 0.50):
            raise HydraBacktestValidationError(
                f"Annualized volatility out of sanity range [3%, 50%]: {vol_ann:.2%}"
            )

    # 8. Outlier daily returns except allowlist
    dates = pd.to_datetime(daily['date'])
    ret_dates = dates.iloc[1:].reset_index(drop=True)
    rets_arr = returns.reset_index(drop=True)
    for ts, ret in zip(ret_dates, rets_arr):
        if abs(ret) > 0.15 and ts not in _CRASH_ALLOWLIST:
            raise HydraBacktestValidationError(
                f"Outlier daily return {ret:.2%} on {ts.date()} not in crash allowlist"
            )

    # 9. Stop adherence (if trades exist)
    trades = result.trades
    if not trades.empty and 'exit_reason' in trades.columns:
        stops = trades[trades['exit_reason'] == 'position_stop']
        if not stops.empty and 'return' in stops.columns:
            bad_stops = stops[stops['return'] > 0.01]
            if len(bad_stops) > 0:
                raise HydraBacktestValidationError(
                    f"{len(bad_stops)} position_stop exits have positive return"
                )
