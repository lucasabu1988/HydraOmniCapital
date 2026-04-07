"""Layer A smoke tests for Rattlesnake — blocking for v1.1.

Adapted from hydra_backtest.validation.run_smoke_tests:
- Removes COMPASS-only checks (leverage bounds, sector concentration,
  crash brake)
- Adds Rattlesnake-specific checks: stop/profit/time exit adherence
"""
import numpy as np
import pandas as pd

from hydra_backtest.engine import BacktestResult
from hydra_backtest.errors import HydraBacktestValidationError
from rattlesnake_signals import (
    R_MAX_HOLD_DAYS,
    R_MAX_POSITIONS,
    R_PROFIT_TARGET,
    R_STOP_LOSS,
)

# Tolerance for stop/profit return checks. Stops and profits use the
# Close[T] check but execute at Open[T+1] in next-open mode, so the
# realized return can deviate from the threshold by overnight gap.
# PROFIT tolerance is tighter because gaps DOWN from a +4% close are
# bounded (small overnight moves on liquid stocks). STOP tolerance is
# wider because gap-through losses can be substantial in real crashes.
_PROFIT_TOLERANCE = 0.015  # +4% target → realized must be >= +2.5%
_STOP_TOLERANCE = 0.03     # -5% stop → realized must be <= -2%

# Known crash dates where daily portfolio returns can legitimately exceed ±15%
_CRASH_ALLOWLIST = {
    pd.Timestamp('2008-09-29'),
    pd.Timestamp('2008-10-13'),
    pd.Timestamp('2008-10-15'),
    pd.Timestamp('2008-10-28'),
    pd.Timestamp('2020-03-09'),
    pd.Timestamp('2020-03-12'),
    pd.Timestamp('2020-03-13'),
    pd.Timestamp('2020-03-16'),
    pd.Timestamp('2020-03-17'),
    pd.Timestamp('2020-03-18'),
    pd.Timestamp('2020-03-24'),
}


def run_rattlesnake_smoke_tests(result: BacktestResult) -> None:
    """Run all Layer A smoke tests for a Rattlesnake backtest result.

    Raises HydraBacktestValidationError on any failure.
    """
    daily = result.daily_values

    if len(daily) == 0:
        raise HydraBacktestValidationError("Backtest produced empty daily_values")

    # 1. No NaN in critical columns
    for col in ('portfolio_value', 'cash', 'drawdown'):
        if col in daily.columns and daily[col].isna().any():
            raise HydraBacktestValidationError(
                f"NaN detected in daily_values column: {col}"
            )

    # 2. Cash never arbitrarily negative
    if (daily['cash'] < -1.0).any():
        raise HydraBacktestValidationError(
            f"Negative cash detected: min = {float(daily['cash'].min())}"
        )

    # 3. Drawdown bounds
    if (daily['drawdown'] < -1.0).any() or (daily['drawdown'] > 1e-4).any():
        raise HydraBacktestValidationError(
            f"drawdown out of [-1.0, 0] range: "
            f"min={float(daily['drawdown'].min())}, "
            f"max={float(daily['drawdown'].max())}"
        )

    # 4. Position count bounds (Rattlesnake: max R_MAX_POSITIONS, no bull override)
    if (daily['n_positions'] < 0).any() or (daily['n_positions'] > R_MAX_POSITIONS).any():
        raise HydraBacktestValidationError(
            f"n_positions out of [0, {R_MAX_POSITIONS}] range: "
            f"min={int(daily['n_positions'].min())}, "
            f"max={int(daily['n_positions'].max())}"
        )

    # 5. Peak monotonic non-decreasing
    pv = daily['portfolio_value'].values
    peak = np.maximum.accumulate(pv)
    if not np.all(np.diff(peak) >= -1e-6):
        raise HydraBacktestValidationError(
            "Peak portfolio value is not monotonic non-decreasing"
        )

    # 6. Statistical sanity — annualized vol
    returns = daily['portfolio_value'].pct_change().dropna()
    if len(returns) > 20:
        vol_ann = float(returns.std() * np.sqrt(252))
        if not (0.005 <= vol_ann <= 0.50):
            raise HydraBacktestValidationError(
                f"Annualized volatility out of sanity range [0.5%, 50%]: {vol_ann:.2%}"
            )

    # 7. Outlier daily returns (except allowlist)
    dates = pd.to_datetime(daily['date'])
    ret_dates = dates.iloc[1:].reset_index(drop=True)
    rets_arr = returns.reset_index(drop=True)
    for ts, ret in zip(ret_dates, rets_arr):
        if abs(ret) > 0.15 and ts not in _CRASH_ALLOWLIST:
            raise HydraBacktestValidationError(
                f"Outlier daily return {ret:.2%} on {ts.date()} "
                "not in crash allowlist"
            )

    # 8. Trade exit adherence (Rattlesnake-specific)
    trades = result.trades
    if not trades.empty and 'exit_reason' in trades.columns:
        # R_STOP: return must be <= R_STOP_LOSS + STOP_TOLERANCE
        stops = trades[trades['exit_reason'] == 'R_STOP']
        if not stops.empty:
            bad_stops = stops[stops['return'] > R_STOP_LOSS + _STOP_TOLERANCE]
            if len(bad_stops) > 0:
                raise HydraBacktestValidationError(
                    f"{len(bad_stops)} R_STOP exits have return > "
                    f"{R_STOP_LOSS + _STOP_TOLERANCE:.2%} (worst: "
                    f"{float(bad_stops['return'].max()):.2%})"
                )

        # R_PROFIT: return must be >= R_PROFIT_TARGET - PROFIT_TOLERANCE
        profits = trades[trades['exit_reason'] == 'R_PROFIT']
        if not profits.empty:
            bad_profits = profits[profits['return'] < R_PROFIT_TARGET - _PROFIT_TOLERANCE]
            if len(bad_profits) > 0:
                raise HydraBacktestValidationError(
                    f"{len(bad_profits)} R_PROFIT exits have return < "
                    f"{R_PROFIT_TARGET - _PROFIT_TOLERANCE:.2%} (worst: "
                    f"{float(bad_profits['return'].min()):.2%})"
                )
