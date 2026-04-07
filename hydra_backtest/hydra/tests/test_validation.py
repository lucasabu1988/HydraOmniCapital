"""Unit tests for hydra_backtest.hydra.validation."""
import numpy as np
import pandas as pd
import pytest

from hydra_backtest.engine import BacktestResult
from hydra_backtest.errors import HydraBacktestValidationError
from hydra_backtest.hydra.validation import run_hydra_smoke_tests


def _make_result(daily, trades=None) -> BacktestResult:
    if trades is None:
        trades = pd.DataFrame(columns=['symbol', 'exit_reason'])
    return BacktestResult(
        config={}, daily_values=daily, trades=trades, decisions=[],
        exit_events=[], universe_size={},
        started_at=pd.Timestamp.now(), finished_at=pd.Timestamp.now(),
        git_sha='test', data_inputs_hash='test',
    )


def _good_daily(n: int = 300) -> pd.DataFrame:
    """Build a clean HYDRA daily snapshot table that passes every check."""
    np.random.seed(666)
    dates = pd.bdate_range('2020-01-01', periods=n)
    rets = 0.0003 + np.random.normal(0, 0.008, n)
    pv = 100_000.0 * np.cumprod(1 + rets)
    peak = np.maximum.accumulate(pv)
    drawdown = (pv - peak) / peak
    # Distribute portfolio_value across the four sub-accounts so the
    # sub-account sum invariant holds exactly
    return pd.DataFrame({
        'date': dates,
        'portfolio_value': pv,
        'cash': [5_000.0] * n,
        'n_positions': [10] * n,
        'drawdown': drawdown,
        'compass_account': pv * 0.425,
        'rattle_account': pv * 0.425,
        'catalyst_account': pv * 0.15,
        'efa_value': pv * 0.0,
        'recycled_pct': [0.05] * n,
        'n_compass': [5] * n,
        'n_rattle': [5] * n,
        'n_catalyst': [4] * n,
        'n_efa': [0] * n,
    })


def test_smoke_passes_clean_result():
    run_hydra_smoke_tests(_make_result(_good_daily()))


def test_smoke_fails_n_compass_over_max():
    daily = _good_daily()
    daily.loc[10, 'n_compass'] = 11
    with pytest.raises(HydraBacktestValidationError, match="n_compass out of"):
        run_hydra_smoke_tests(_make_result(daily))


def test_smoke_fails_n_catalyst_over_max():
    daily = _good_daily()
    daily.loc[10, 'n_catalyst'] = 5
    with pytest.raises(HydraBacktestValidationError, match="n_catalyst out of"):
        run_hydra_smoke_tests(_make_result(daily))


def test_smoke_fails_invalid_exit_reason():
    daily = _good_daily()
    trades = pd.DataFrame([{'symbol': 'AAPL', 'exit_reason': 'WRONG_REASON'}])
    with pytest.raises(HydraBacktestValidationError,
                       match="Invalid HYDRA exit reasons"):
        run_hydra_smoke_tests(_make_result(daily, trades))


def test_smoke_accepts_all_pillar_exit_reasons():
    """The whitelist must include reasons from all four pillars + EFA liquidation."""
    daily = _good_daily()
    trades = pd.DataFrame([
        {'symbol': 'AAPL', 'exit_reason': 'hold_expired'},
        {'symbol': 'MSFT', 'exit_reason': 'R_PROFIT'},
        {'symbol': 'GLD', 'exit_reason': 'CATALYST_TREND_OFF'},
        {'symbol': 'EFA', 'exit_reason': 'EFA_BELOW_SMA200'},
        {'symbol': 'EFA', 'exit_reason': 'EFA_LIQUIDATED_FOR_CAPITAL'},
    ])
    run_hydra_smoke_tests(_make_result(daily, trades))


def test_smoke_fails_sub_account_sum_diverges():
    """The most important check — drift > $1 should fail."""
    daily = _good_daily()
    # Inject $5 leak into compass_account
    daily.loc[50, 'compass_account'] = daily.loc[50, 'compass_account'] + 5.0
    with pytest.raises(HydraBacktestValidationError,
                       match="Sub-account sum diverged"):
        run_hydra_smoke_tests(_make_result(daily))


def test_smoke_passes_when_sub_account_sum_within_tolerance():
    """A 50-cent drift should still pass (under the $1 tolerance)."""
    daily = _good_daily()
    daily.loc[50, 'compass_account'] = daily.loc[50, 'compass_account'] + 0.50
    run_hydra_smoke_tests(_make_result(daily))


def test_smoke_fails_recycling_cap_breach():
    daily = _good_daily()
    daily.loc[50, 'recycled_pct'] = 0.40  # > 0.325 cap
    with pytest.raises(HydraBacktestValidationError,
                       match="Recycling cap breached"):
        run_hydra_smoke_tests(_make_result(daily))


def test_smoke_fails_negative_cash():
    daily = _good_daily()
    daily.loc[5, 'cash'] = -10.0
    with pytest.raises(HydraBacktestValidationError, match="Cash < -1.0"):
        run_hydra_smoke_tests(_make_result(daily))


def test_smoke_fails_drawdown_out_of_range():
    daily = _good_daily()
    daily.loc[5, 'drawdown'] = 0.5  # positive drawdown impossible
    with pytest.raises(HydraBacktestValidationError, match="Drawdown out of"):
        run_hydra_smoke_tests(_make_result(daily))


def test_smoke_fails_empty_daily():
    empty = pd.DataFrame(
        columns=['date', 'portfolio_value', 'cash', 'n_positions', 'drawdown']
    )
    with pytest.raises(HydraBacktestValidationError, match="empty daily_values"):
        run_hydra_smoke_tests(_make_result(empty))
