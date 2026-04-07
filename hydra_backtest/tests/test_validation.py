"""Tests for hydra_backtest.validation (Layer A smoke tests)."""
from datetime import datetime

import pandas as pd
import pytest

from hydra_backtest.engine import BacktestResult
from hydra_backtest.errors import HydraBacktestValidationError
from hydra_backtest.validation import run_smoke_tests


def _good_result():
    # Synthetic equity curve with realistic vol (~10% annualized) so the
    # smoke tests' vol sanity check doesn't reject it as a bug signal.
    import numpy as np
    rng = np.random.default_rng(666)
    dates = pd.date_range('2020-01-01', periods=500)
    daily_rets = rng.normal(loc=0.0005, scale=0.006, size=500)  # ~9.5% annual vol
    values = (100_000 * np.cumprod(1 + daily_rets)).tolist()
    daily = pd.DataFrame({
        'date': dates,
        'portfolio_value': values,
        'cash': values,
        'n_positions': [5] * 500,
        'leverage': [0.8] * 500,
        'drawdown': [0.0] * 500,
        'regime_score': [0.7] * 500,
        'crash_active': [False] * 500,
        'max_positions': [5] * 500,
    })
    trades = pd.DataFrame(columns=[
        'symbol', 'entry_date', 'exit_date', 'exit_reason',
        'entry_price', 'exit_price', 'shares', 'pnl', 'return', 'sector',
    ])
    return BacktestResult(
        config={
            'NUM_POSITIONS': 5, 'LEVERAGE_MAX': 1.0,
            'CRASH_LEVERAGE': 0.15, 'LEV_FLOOR': 0.30,
            'BULL_OVERRIDE_THRESHOLD': 0.03, 'MAX_PER_SECTOR': 3,
            'HOLD_DAYS': 5, 'STOP_FLOOR': -0.06, 'STOP_CEILING': -0.15,
        },
        daily_values=daily,
        trades=trades,
        decisions=[],
        exit_events=[],
        universe_size={2020: 40},
        started_at=datetime(2026, 4, 6),
        finished_at=datetime(2026, 4, 6),
        git_sha='test',
        data_inputs_hash='test',
    )


def test_smoke_tests_pass_for_good_result():
    run_smoke_tests(_good_result())  # should not raise


def test_smoke_tests_detect_nan():
    r = _good_result()
    r.daily_values.loc[10, 'portfolio_value'] = float('nan')
    with pytest.raises(HydraBacktestValidationError, match="NaN"):
        run_smoke_tests(r)


def test_smoke_tests_detect_negative_cash():
    r = _good_result()
    r.daily_values.loc[5, 'cash'] = -1000.0
    with pytest.raises(HydraBacktestValidationError, match="cash"):
        run_smoke_tests(r)


def test_smoke_tests_detect_leverage_out_of_range():
    r = _good_result()
    r.daily_values.loc[10, 'leverage'] = 2.5
    with pytest.raises(HydraBacktestValidationError, match="leverage"):
        run_smoke_tests(r)


def test_smoke_tests_detect_too_many_positions():
    r = _good_result()
    r.daily_values.loc[10, 'n_positions'] = 20
    with pytest.raises(HydraBacktestValidationError, match="n_positions"):
        run_smoke_tests(r)


def test_smoke_tests_detect_drawdown_below_neg_one():
    r = _good_result()
    r.daily_values.loc[10, 'drawdown'] = -1.5
    with pytest.raises(HydraBacktestValidationError, match="drawdown"):
        run_smoke_tests(r)
