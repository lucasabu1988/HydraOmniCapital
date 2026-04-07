"""Tests for hydra_backtest.rattlesnake.validation."""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from hydra_backtest.engine import BacktestResult
from hydra_backtest.errors import HydraBacktestValidationError
from hydra_backtest.rattlesnake.validation import run_rattlesnake_smoke_tests


def _good_rattlesnake_result():
    rng = np.random.default_rng(666)
    dates = pd.date_range('2020-01-01', periods=500)
    daily_rets = rng.normal(loc=0.0003, scale=0.005, size=500)
    values = (100_000 * np.cumprod(1 + daily_rets)).tolist()
    daily = pd.DataFrame({
        'date': dates,
        'portfolio_value': values,
        'cash': values,
        'n_positions': [3] * 500,
        'leverage': [1.0] * 500,
        'drawdown': [0.0] * 500,
        'regime_score': [1.0] * 500,
        'crash_active': [False] * 500,
        'max_positions': [5] * 500,
    })
    trades = pd.DataFrame(columns=[
        'symbol', 'entry_date', 'exit_date', 'exit_reason',
        'entry_price', 'exit_price', 'shares', 'pnl', 'return', 'sector',
    ])
    return BacktestResult(
        config={'NUM_POSITIONS': 5, 'COMMISSION_PER_SHARE': 0.0035},
        daily_values=daily, trades=trades, decisions=[], exit_events=[],
        universe_size={2020: 60}, started_at=datetime(2026, 4, 7),
        finished_at=datetime(2026, 4, 7), git_sha='test', data_inputs_hash='test',
    )


def test_smoke_tests_pass_for_good_result():
    run_rattlesnake_smoke_tests(_good_rattlesnake_result())


def test_smoke_tests_detect_nan():
    r = _good_rattlesnake_result()
    r.daily_values.loc[10, 'portfolio_value'] = float('nan')
    with pytest.raises(HydraBacktestValidationError, match="NaN"):
        run_rattlesnake_smoke_tests(r)


def test_smoke_tests_detect_negative_cash():
    r = _good_rattlesnake_result()
    r.daily_values.loc[5, 'cash'] = -1000.0
    with pytest.raises(HydraBacktestValidationError, match="cash"):
        run_rattlesnake_smoke_tests(r)


def test_smoke_tests_detect_too_many_positions():
    r = _good_rattlesnake_result()
    r.daily_values.loc[10, 'n_positions'] = 10
    with pytest.raises(HydraBacktestValidationError, match="n_positions"):
        run_rattlesnake_smoke_tests(r)


def test_smoke_tests_detect_drawdown_below_neg_one():
    r = _good_rattlesnake_result()
    r.daily_values.loc[10, 'drawdown'] = -1.5
    with pytest.raises(HydraBacktestValidationError, match="drawdown"):
        run_rattlesnake_smoke_tests(r)


def test_smoke_tests_detect_bad_stop_exit():
    """An R_STOP exit with positive return is impossible."""
    r = _good_rattlesnake_result()
    r.trades.loc[0] = {
        'symbol': 'AAA', 'entry_date': pd.Timestamp('2020-01-02'),
        'exit_date': pd.Timestamp('2020-01-05'), 'exit_reason': 'R_STOP',
        'entry_price': 100.0, 'exit_price': 110.0, 'shares': 10.0,
        'pnl': 100.0, 'return': 0.10, 'sector': 'Unknown',
    }
    with pytest.raises(HydraBacktestValidationError, match="R_STOP"):
        run_rattlesnake_smoke_tests(r)


def test_smoke_tests_detect_bad_profit_exit():
    """An R_PROFIT exit must have return >= R_PROFIT_TARGET (-tolerance)."""
    r = _good_rattlesnake_result()
    r.trades.loc[0] = {
        'symbol': 'AAA', 'entry_date': pd.Timestamp('2020-01-02'),
        'exit_date': pd.Timestamp('2020-01-05'), 'exit_reason': 'R_PROFIT',
        'entry_price': 100.0, 'exit_price': 101.0, 'shares': 10.0,
        'pnl': 10.0, 'return': 0.01, 'sector': 'Unknown',
    }
    with pytest.raises(HydraBacktestValidationError, match="R_PROFIT"):
        run_rattlesnake_smoke_tests(r)


def test_smoke_tests_accept_valid_profit_exit():
    """A correct R_PROFIT exit (return ~ +4%) should pass."""
    r = _good_rattlesnake_result()
    r.trades.loc[0] = {
        'symbol': 'AAA', 'entry_date': pd.Timestamp('2020-01-02'),
        'exit_date': pd.Timestamp('2020-01-05'), 'exit_reason': 'R_PROFIT',
        'entry_price': 100.0, 'exit_price': 104.0, 'shares': 10.0,
        'pnl': 40.0, 'return': 0.04, 'sector': 'Unknown',
    }
    run_rattlesnake_smoke_tests(r)
