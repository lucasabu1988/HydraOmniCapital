"""Unit tests for hydra_backtest.efa.engine."""
import numpy as np
import pandas as pd
import pytest

from hydra_backtest.efa.engine import (
    EFA_SMA_PERIOD,
    EFA_SYMBOL,
    _efa_above_sma200,
    apply_efa_decision,
    run_efa_backtest,
)
from hydra_backtest.engine import BacktestState


def _make_efa(
    start: str = '2020-01-01',
    n_days: int = 400,
    drift: float = 0.0005,
    start_price: float = 50.0,
) -> pd.DataFrame:
    """Geometric-drift OHLCV DataFrame for deterministic engine tests."""
    dates = pd.bdate_range(start, periods=n_days)
    closes = start_price * (1.0 + drift) ** np.arange(n_days)
    return pd.DataFrame(
        {
            'Open': closes,
            'High': closes * 1.005,
            'Low': closes * 0.995,
            'Close': closes,
            'Volume': 1_000_000,
        },
        index=dates,
    )


def _empty_state(cash: float = 100_000.0) -> BacktestState:
    return BacktestState(
        cash=cash, positions={}, peak_value=cash,
        crash_cooldown=0, portfolio_value_history=(),
    )


def _held_state(
    cash: float = 0.0,
    shares: int = 1000,
    entry_price: float = 50.0,
    entry_date: pd.Timestamp = None,
) -> BacktestState:
    return BacktestState(
        cash=cash,
        positions={EFA_SYMBOL: {
            'symbol': EFA_SYMBOL, 'entry_price': entry_price, 'shares': shares,
            'entry_date': entry_date or pd.Timestamp('2020-01-01'),
            'entry_idx': 0, 'days_held': 100,
            'sub_strategy': 'passive_intl', 'sector': 'International Equity',
            'entry_vol': 0.0, 'entry_daily_vol': 0.0, 'high_price': entry_price,
        }},
        peak_value=cash + shares * entry_price,
        crash_cooldown=0, portfolio_value_history=(),
    )


def test_above_sma_uptrend():
    efa = _make_efa(drift=0.001)
    assert _efa_above_sma200(efa, efa.index[-1]) is True


def test_below_sma_downtrend():
    efa = _make_efa(drift=-0.001)
    assert _efa_above_sma200(efa, efa.index[-1]) is False


def test_sma_insufficient_history():
    efa = _make_efa()
    # Day 50 has fewer than 200 bars of history
    assert _efa_above_sma200(efa, efa.index[50]) is False


def test_apply_decision_buys_when_above_and_not_held(efa_minimal_config):
    efa = _make_efa(drift=0.001)
    state = _empty_state()
    last_date = efa.index[-1]
    new_state, trades, decisions = apply_efa_decision(
        state, last_date, len(efa) - 1, efa,
        efa_minimal_config, 'same_close', list(efa.index),
    )
    assert EFA_SYMBOL in new_state.positions
    assert trades == []  # entries are not trade records
    assert any(d['action'] == 'ENTRY' for d in decisions)
    assert new_state.cash < state.cash  # cash deployed


def test_apply_decision_sells_when_below_and_held(efa_minimal_config):
    """EFA crashes below SMA200 → sold with EFA_BELOW_SMA200."""
    n = 300
    efa = _make_efa(n_days=n, drift=0.001)
    # Crash the last 30 bars to force Close below SMA200
    crash_tail = np.linspace(
        efa['Close'].iloc[-31], efa['Close'].iloc[-31] * 0.4, 31
    )
    efa.iloc[-31:, efa.columns.get_loc('Close')] = crash_tail
    efa['Open'] = efa['Close']
    efa['High'] = efa['Close'] * 1.005
    efa['Low'] = efa['Close'] * 0.995

    state = _held_state(
        shares=500, entry_price=float(efa['Close'].iloc[-200]),
        entry_date=efa.index[0],
    )
    last_date = efa.index[-1]
    new_state, trades, _ = apply_efa_decision(
        state, last_date, len(efa) - 1, efa,
        efa_minimal_config, 'same_close', list(efa.index),
    )
    assert EFA_SYMBOL not in new_state.positions
    assert any(t['exit_reason'] == 'EFA_BELOW_SMA200' for t in trades)


def test_apply_decision_no_op_above_and_held(efa_minimal_config):
    efa = _make_efa(drift=0.001)
    state = _held_state(shares=1000, entry_price=50.0)
    last_date = efa.index[-1]
    new_state, trades, decisions = apply_efa_decision(
        state, last_date, len(efa) - 1, efa,
        efa_minimal_config, 'same_close', list(efa.index),
    )
    assert EFA_SYMBOL in new_state.positions
    assert trades == []
    assert decisions == []


def test_apply_decision_no_op_below_and_not_held(efa_minimal_config):
    efa = _make_efa(drift=-0.001)
    state = _empty_state()
    last_date = efa.index[-1]
    new_state, trades, decisions = apply_efa_decision(
        state, last_date, len(efa) - 1, efa,
        efa_minimal_config, 'same_close', list(efa.index),
    )
    assert EFA_SYMBOL not in new_state.positions
    assert trades == []
    assert decisions == []


def test_run_backtest_buy_and_hold_in_continuous_uptrend(efa_minimal_config):
    """Always-uptrend run produces a single ENTRY + a synthetic-end exit."""
    efa = _make_efa(drift=0.001, n_days=500)
    yld = pd.Series(0.0, index=efa.index)
    start = efa.index[210]   # after SMA200 settles
    end = efa.index[-1]
    result = run_efa_backtest(efa_minimal_config, efa, yld, start, end)
    # Exactly one trade record (the synthetic-end exit)
    assert len(result.trades) == 1
    assert result.trades.iloc[0]['exit_reason'] == 'EFA_BACKTEST_END'
    # Final PV > initial (uptrend)
    assert result.daily_values['portfolio_value'].iloc[-1] > 100_000.0
    # n_positions stable at 1 throughout
    assert (result.daily_values['n_positions'] == 1).all()


def test_run_backtest_handles_pre_inception(efa_minimal_config):
    """Bars before SMA200 has data must show n_positions == 0."""
    efa = _make_efa(n_days=400)
    yld = pd.Series(0.0, index=efa.index)
    # Range that starts BEFORE SMA200 has settled
    result = run_efa_backtest(
        efa_minimal_config, efa, yld, efa.index[0], efa.index[250]
    )
    early_snaps = result.daily_values.iloc[:100]
    assert (early_snaps['n_positions'] == 0).all()
