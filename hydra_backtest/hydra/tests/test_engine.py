"""Unit tests for hydra_backtest.hydra.engine wrappers.

Verifies budget cap enforcement, position routing by strategy,
ring-fence behavior, idle gates, and the EFA liquidation helper.
"""
import numpy as np
import pandas as pd
import pytest

from hydra_backtest.efa.engine import EFA_SYMBOL
from hydra_backtest.hydra.capital import HydraCapitalState
from hydra_backtest.hydra.engine import (
    _needs_efa_liquidation,
    apply_catalyst_wrapper,
    apply_efa_liquidation,
    apply_efa_wrapper,
)
from hydra_backtest.hydra.state import (
    HydraBacktestState,
    slice_positions_by_strategy,
)


def _make_state(positions=None, cash=100_000.0,
                compass=42_500.0, rattle=42_500.0,
                catalyst=15_000.0, efa_value=0.0):
    capital = HydraCapitalState(
        compass_account=compass, rattle_account=rattle,
        catalyst_account=catalyst, efa_value=efa_value,
    )
    return HydraBacktestState(
        cash=cash,
        positions=positions or {},
        peak_value=cash,
        crash_cooldown=0,
        portfolio_value_history=(),
        capital=capital,
    )


def _make_efa_data(start='2020-01-01', n=400, drift=0.0005, start_price=50.0):
    dates = pd.bdate_range(start, periods=n)
    closes = start_price * (1.0 + drift) ** np.arange(n)
    return pd.DataFrame(
        {'Open': closes, 'High': closes * 1.005, 'Low': closes * 0.995,
         'Close': closes, 'Volume': 1_000_000},
        index=dates,
    )


def _make_catalyst_assets(start='2020-01-01', n=400):
    dates = pd.bdate_range(start, periods=n)
    out = {}
    for sym, p0, drift in [
        ('TLT', 95, 0.0003), ('ZROZ', 85, 0.0003),
        ('GLD', 180, 0.0004), ('DBC', 25, 0.0005),
    ]:
        closes = p0 * (1.0 + drift) ** np.arange(n)
        out[sym] = pd.DataFrame(
            {'Open': closes, 'High': closes * 1.005, 'Low': closes * 0.995,
             'Close': closes, 'Volume': 1_000_000},
            index=dates,
        )
    return out


CATALYST_CONFIG = {
    'INITIAL_CAPITAL': 100_000.0,
    'COMMISSION_PER_SHARE': 0.0035,
}


def test_apply_catalyst_wrapper_buys_only_uses_catalyst_budget():
    """Catalyst rebalance should not spend more than catalyst_account
    even when broker cash is much larger.
    """
    catalyst_assets = _make_catalyst_assets()
    state = _make_state(cash=100_000.0, catalyst=15_000.0)
    last_date = catalyst_assets['TLT'].index[-1]
    all_dates = sorted(catalyst_assets['TLT'].index)
    new_state, trades, decisions = apply_catalyst_wrapper(
        state, catalyst_budget=15_000.0, date=last_date,
        i=len(all_dates) - 1, catalyst_assets=catalyst_assets,
        config=CATALYST_CONFIG, execution_mode='same_close', all_dates=all_dates,
    )
    # 4 catalyst positions opened, each ~3750 deployed
    assert len(slice_positions_by_strategy(new_state.positions, 'catalyst')) == 4
    # Broker cash dropped by ~ catalyst_budget * deployment
    # (some integer rounding leftover stays in cash)
    spent = state.cash - new_state.cash
    assert 12_000.0 < spent < 15_001.0


def test_apply_catalyst_wrapper_does_not_touch_other_strategies():
    """Catalyst rebalance must not modify compass / rattle / efa positions."""
    catalyst_assets = _make_catalyst_assets()
    state = _make_state(positions={
        'AAPL': {'symbol': 'AAPL', 'shares': 100, 'entry_price': 150.0,
                 '_strategy': 'compass'},
        'MSFT': {'symbol': 'MSFT', 'shares': 50, 'entry_price': 300.0,
                 '_strategy': 'rattle'},
    })
    last_date = catalyst_assets['TLT'].index[-1]
    all_dates = sorted(catalyst_assets['TLT'].index)
    new_state, _, _ = apply_catalyst_wrapper(
        state, catalyst_budget=15_000.0, date=last_date,
        i=len(all_dates) - 1, catalyst_assets=catalyst_assets,
        config=CATALYST_CONFIG, execution_mode='same_close', all_dates=all_dates,
    )
    # AAPL + MSFT untouched
    assert 'AAPL' in new_state.positions
    assert 'MSFT' in new_state.positions
    assert new_state.positions['AAPL']['_strategy'] == 'compass'
    assert new_state.positions['MSFT']['_strategy'] == 'rattle'
    # rattle / compass logical accounts unchanged
    assert new_state.capital.compass_account == state.capital.compass_account
    assert new_state.capital.rattle_account == state.capital.rattle_account


def test_apply_efa_wrapper_skips_when_idle_below_min_buy_and_not_held():
    """EFA wrapper should be a no-op when efa_idle < $1k and EFA not held."""
    efa_data = _make_efa_data()
    state = _make_state(cash=100_000.0)
    last_date = efa_data.index[-1]
    new_state, trades, decisions = apply_efa_wrapper(
        state, efa_idle=500.0, date=last_date, i=len(efa_data) - 1,
        efa_data=efa_data, config=CATALYST_CONFIG,
        execution_mode='same_close', all_dates=list(efa_data.index),
    )
    assert EFA_SYMBOL not in new_state.positions
    assert trades == []
    assert decisions == []


def test_apply_efa_wrapper_buys_when_idle_above_min_buy():
    """EFA wrapper should deploy when efa_idle > $1k and EFA above SMA200."""
    efa_data = _make_efa_data(drift=0.001)  # uptrend, will be above SMA200
    state = _make_state(cash=100_000.0)
    last_date = efa_data.index[-1]
    new_state, trades, decisions = apply_efa_wrapper(
        state, efa_idle=10_000.0, date=last_date, i=len(efa_data) - 1,
        efa_data=efa_data, config=CATALYST_CONFIG,
        execution_mode='same_close', all_dates=list(efa_data.index),
    )
    # EFA position opened
    assert EFA_SYMBOL in new_state.positions
    assert new_state.positions[EFA_SYMBOL]['_strategy'] == 'efa'
    # Cash reduced by ~$9k (90% deployment cap of 10k idle, integer shares)
    assert state.cash - new_state.cash > 8_000.0
    assert state.cash - new_state.cash < 9_001.0


def test_apply_efa_liquidation_frees_cash_and_emits_trade():
    """Liquidation helper sells the entire EFA position."""
    efa_data = _make_efa_data(drift=0.001)
    last_date = efa_data.index[-1]
    held_state = _make_state(cash=5_000.0, efa_value=10_000.0, positions={
        EFA_SYMBOL: {
            'symbol': EFA_SYMBOL, 'entry_price': 50.0, 'shares': 200,
            'entry_date': efa_data.index[0], 'entry_idx': 0, 'days_held': 100,
            'sub_strategy': 'passive_intl', 'sector': 'International Equity',
            'entry_vol': 0.0, 'entry_daily_vol': 0.0, 'high_price': 60.0,
            '_strategy': 'efa',
        },
    })
    new_state, trades = apply_efa_liquidation(
        held_state, last_date, len(efa_data) - 1, efa_data,
        CATALYST_CONFIG, 'same_close', list(efa_data.index),
    )
    assert EFA_SYMBOL not in new_state.positions
    assert len(trades) == 1
    assert trades[0]['exit_reason'] == 'EFA_LIQUIDATED_FOR_CAPITAL'
    # Cash increased substantially
    assert new_state.cash > held_state.cash
    # efa_value cleared
    assert new_state.capital.efa_value == 0.0


def test_apply_efa_liquidation_no_op_when_not_held():
    efa_data = _make_efa_data()
    state = _make_state(cash=100_000.0)
    new_state, trades = apply_efa_liquidation(
        state, efa_data.index[-1], len(efa_data) - 1, efa_data,
        CATALYST_CONFIG, 'same_close', list(efa_data.index),
    )
    assert new_state is state
    assert trades == []


def test_needs_efa_liquidation_decision_logic():
    config = {'EFA_LIQUIDATION_CASH_THRESHOLD_PCT': 0.20}
    held_state = _make_state(cash=10_000.0, positions={
        EFA_SYMBOL: {'symbol': EFA_SYMBOL, 'shares': 100, '_strategy': 'efa',
                     'entry_price': 50.0},
    })
    # PV = 100k. broker cash 10k = 10% < 20% threshold. compass slots open.
    assert _needs_efa_liquidation(
        held_state, portfolio_value=100_000.0, config=config,
        n_compass_positions=2, n_compass_max=5, rattle_signal_pending=False,
    ) is True
    # No EFA held → False
    no_efa = _make_state(cash=10_000.0)
    assert _needs_efa_liquidation(
        no_efa, portfolio_value=100_000.0, config=config,
        n_compass_positions=2, n_compass_max=5, rattle_signal_pending=False,
    ) is False
    # No active strategy needs capital → False
    assert _needs_efa_liquidation(
        held_state, portfolio_value=100_000.0, config=config,
        n_compass_positions=5, n_compass_max=5, rattle_signal_pending=False,
    ) is False
    # Plenty of cash → False
    fat_state = _make_state(cash=50_000.0, positions={
        EFA_SYMBOL: {'symbol': EFA_SYMBOL, 'shares': 100, '_strategy': 'efa',
                     'entry_price': 50.0},
    })
    assert _needs_efa_liquidation(
        fat_state, portfolio_value=100_000.0, config=config,
        n_compass_positions=2, n_compass_max=5, rattle_signal_pending=False,
    ) is False


def test_position_tag_invariant_after_catalyst_wrapper():
    """Every position created by the wrapper must have _strategy set."""
    catalyst_assets = _make_catalyst_assets()
    state = _make_state(cash=100_000.0)
    last_date = catalyst_assets['TLT'].index[-1]
    all_dates = sorted(catalyst_assets['TLT'].index)
    new_state, _, _ = apply_catalyst_wrapper(
        state, catalyst_budget=15_000.0, date=last_date,
        i=len(all_dates) - 1, catalyst_assets=catalyst_assets,
        config=CATALYST_CONFIG, execution_mode='same_close', all_dates=all_dates,
    )
    # All positions tagged
    for sym, pos in new_state.positions.items():
        assert '_strategy' in pos, f"position {sym} missing _strategy tag"
        assert pos['_strategy'] == 'catalyst'
