"""hydra_backtest.efa.validation — Layer A smoke tests for EFA.

Mathematical invariants (shared with v1.0/v1.1/v1.2):
1. No NaN in critical columns
2. Cash never < -1.0
3. Drawdown ∈ [-1.0, 0]
4. Peak monotonic non-decreasing
5. Vol ann ∈ [0.5%, 50%]
6. No outlier daily returns > ±15% (allowlist crash days)

EFA-specific invariants:
7. n_positions ∈ [0, 1] always (single-asset universe)
8. Trade exit reasons ⊆ {'EFA_BELOW_SMA200', 'EFA_BACKTEST_END'}
"""
from typing import List

import numpy as np
import pandas as pd

from hydra_backtest.engine import BacktestResult
from hydra_backtest.errors import HydraBacktestValidationError

# Crash days where ±15% portfolio moves are tolerated (same allowlist as v1.0)
_CRASH_ALLOWLIST = {
    pd.Timestamp('2008-10-13'),
    pd.Timestamp('2008-10-15'),
    pd.Timestamp('2020-03-12'),
    pd.Timestamp('2020-03-16'),
}


def _check_no_nan(daily: pd.DataFrame, errors: List[str]) -> None:
    critical = ['portfolio_value', 'cash', 'n_positions', 'drawdown']
    for col in critical:
        if col in daily.columns and daily[col].isna().any():
            errors.append(f"NaN in critical column: {col}")


def _check_cash_floor(daily: pd.DataFrame, errors: List[str]) -> None:
    if 'cash' in daily.columns and (daily['cash'] < -1.0).any():
        bad = daily[daily['cash'] < -1.0].iloc[0]
        errors.append(f"Cash < -1.0 at {bad['date']}: {bad['cash']:.4f}")


def _check_drawdown_range(daily: pd.DataFrame, errors: List[str]) -> None:
    if 'drawdown' not in daily.columns:
        return
    dd = daily['drawdown']
    if (dd < -1.0).any() or (dd > 0).any():
        errors.append(
            f"Drawdown out of [-1.0, 0]: min={dd.min():.4f}, max={dd.max():.4f}"
        )


def _check_peak_monotonic(daily: pd.DataFrame, errors: List[str]) -> None:
    if 'portfolio_value' not in daily.columns:
        return
    pv = daily['portfolio_value'].values
    peak = np.maximum.accumulate(pv)
    if not np.all(np.diff(peak) >= -1e-9):
        errors.append("Peak series is not monotonic non-decreasing")


def _check_vol_range(daily: pd.DataFrame, errors: List[str]) -> None:
    if 'portfolio_value' not in daily.columns or len(daily) < 30:
        return
    rets = daily['portfolio_value'].pct_change().dropna()
    if len(rets) < 2:
        return
    vol_ann = rets.std() * np.sqrt(252) * 100
    if vol_ann < 0.5 or vol_ann > 50:
        errors.append(f"Annualized vol out of [0.5%, 50%]: {vol_ann:.2f}%")


def _check_outlier_returns(daily: pd.DataFrame, errors: List[str]) -> None:
    if 'portfolio_value' not in daily.columns or len(daily) < 2:
        return
    rets = daily['portfolio_value'].pct_change()
    for idx, r in rets.items():
        if pd.isna(r):
            continue
        if abs(r) > 0.15:
            row_date = daily.loc[idx, 'date'] if 'date' in daily.columns else idx
            if pd.Timestamp(row_date) not in _CRASH_ALLOWLIST:
                errors.append(
                    f"Outlier daily return {r * 100:.2f}% on {row_date}"
                )


def _check_n_positions_bounds(daily: pd.DataFrame, errors: List[str]) -> None:
    if 'n_positions' not in daily.columns:
        return
    bad = daily[(daily['n_positions'] < 0) | (daily['n_positions'] > 1)]
    if not bad.empty:
        row = bad.iloc[0]
        errors.append(
            f"n_positions out of [0, 1] at {row.get('date', '?')}: "
            f"{row['n_positions']}"
        )


def _check_exit_reasons(trades: pd.DataFrame, errors: List[str]) -> None:
    if trades.empty or 'exit_reason' not in trades.columns:
        return
    valid = {'EFA_BELOW_SMA200', 'EFA_BACKTEST_END'}
    invalid = set(trades['exit_reason'].unique()) - valid
    if invalid:
        errors.append(f"Invalid EFA exit reasons: {invalid}")


def run_efa_smoke_tests(result: BacktestResult) -> None:
    """Run all Layer A smoke tests on an EFA BacktestResult.

    Raises HydraBacktestValidationError with all errors aggregated.
    Returns silently on success.
    """
    errors: List[str] = []
    daily = result.daily_values
    trades = result.trades

    if daily.empty:
        raise HydraBacktestValidationError(
            "EFA backtest produced empty daily_values"
        )

    _check_no_nan(daily, errors)
    _check_cash_floor(daily, errors)
    _check_drawdown_range(daily, errors)
    _check_peak_monotonic(daily, errors)
    _check_vol_range(daily, errors)
    _check_outlier_returns(daily, errors)
    _check_n_positions_bounds(daily, errors)
    _check_exit_reasons(trades, errors)

    if errors:
        msg = "EFA smoke tests failed:\n  - " + "\n  - ".join(errors)
        raise HydraBacktestValidationError(msg)
