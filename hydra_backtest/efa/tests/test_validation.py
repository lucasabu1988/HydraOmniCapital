"""Unit tests for hydra_backtest.efa.validation."""
import numpy as np
import pandas as pd
import pytest

from hydra_backtest.efa.validation import run_efa_smoke_tests
from hydra_backtest.engine import BacktestResult
from hydra_backtest.errors import HydraBacktestValidationError


def _make_result(
    daily: pd.DataFrame, trades: pd.DataFrame = None
) -> BacktestResult:
    if trades is None:
        trades = pd.DataFrame(columns=['symbol', 'exit_reason'])
    return BacktestResult(
        config={}, daily_values=daily, trades=trades, decisions=[],
        exit_events=[], universe_size={},
        started_at=pd.Timestamp.now(), finished_at=pd.Timestamp.now(),
        git_sha='test', data_inputs_hash='test',
    )


def _good_daily(n: int = 300) -> pd.DataFrame:
    """Build a clean daily snapshot table that passes every smoke check."""
    np.random.seed(666)
    dates = pd.bdate_range('2020-01-01', periods=n)
    rets = 0.0003 + np.random.normal(0, 0.008, n)
    pv = 100_000.0 * np.cumprod(1 + rets)
    peak = np.maximum.accumulate(pv)
    drawdown = (pv - peak) / peak
    return pd.DataFrame({
        'date': dates,
        'portfolio_value': pv,
        'cash': [10_000.0] * n,
        'n_positions': [1] * n,
        'drawdown': drawdown,
    })


def test_smoke_passes_clean_result():
    run_efa_smoke_tests(_make_result(_good_daily()))


def test_smoke_fails_n_positions_over_max():
    daily = _good_daily()
    daily.loc[10, 'n_positions'] = 2
    with pytest.raises(HydraBacktestValidationError, match="n_positions out of"):
        run_efa_smoke_tests(_make_result(daily))


def test_smoke_fails_invalid_exit_reason():
    daily = _good_daily()
    trades = pd.DataFrame([{'symbol': 'EFA', 'exit_reason': 'COMPASS_STOP'}])
    with pytest.raises(HydraBacktestValidationError,
                       match="Invalid EFA exit reasons"):
        run_efa_smoke_tests(_make_result(daily, trades))


def test_smoke_accepts_valid_exit_reasons():
    daily = _good_daily()
    trades = pd.DataFrame([
        {'symbol': 'EFA', 'exit_reason': 'EFA_BELOW_SMA200'},
        {'symbol': 'EFA', 'exit_reason': 'EFA_BACKTEST_END'},
    ])
    run_efa_smoke_tests(_make_result(daily, trades))


def test_smoke_fails_negative_cash():
    daily = _good_daily()
    daily.loc[5, 'cash'] = -10.0
    with pytest.raises(HydraBacktestValidationError, match="Cash < -1.0"):
        run_efa_smoke_tests(_make_result(daily))


def test_smoke_fails_drawdown_out_of_range():
    daily = _good_daily()
    daily.loc[5, 'drawdown'] = 0.5  # positive drawdown impossible
    with pytest.raises(HydraBacktestValidationError, match="Drawdown out of"):
        run_efa_smoke_tests(_make_result(daily))


def test_smoke_fails_empty_daily():
    empty = pd.DataFrame(
        columns=['date', 'portfolio_value', 'cash', 'n_positions', 'drawdown']
    )
    with pytest.raises(HydraBacktestValidationError, match="empty daily_values"):
        run_efa_smoke_tests(_make_result(empty))


def test_smoke_fails_outlier_return():
    daily = _good_daily()
    # Force a +20% jump on a non-allowlist day
    daily.loc[50, 'portfolio_value'] = daily.loc[49, 'portfolio_value'] * 1.20
    with pytest.raises(HydraBacktestValidationError, match="Outlier daily return"):
        run_efa_smoke_tests(_make_result(daily))
