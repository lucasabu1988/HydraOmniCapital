"""Tests for hydra_backtest.engine module."""
from datetime import datetime

import pandas as pd
import pytest

from hydra_backtest.engine import (
    BacktestResult,
    BacktestState,
    _mark_to_market,
    get_tradeable_symbols,
)


# -- BacktestState + BacktestResult dataclasses -------------------------------

def test_backtest_state_is_frozen():
    state = BacktestState(
        cash=100_000.0,
        positions={},
        peak_value=100_000.0,
        crash_cooldown=0,
        portfolio_value_history=(),
    )
    with pytest.raises((AttributeError, TypeError)):
        state.cash = 50_000.0  # frozen — mutation not allowed


def test_backtest_state_replace():
    state = BacktestState(
        cash=100_000.0, positions={}, peak_value=100_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    new = state._replace(cash=50_000.0)
    assert new.cash == 50_000.0
    assert state.cash == 100_000.0  # original unchanged


def test_backtest_result_required_fields():
    result = BacktestResult(
        config={'NUM_POSITIONS': 5},
        daily_values=pd.DataFrame(),
        trades=pd.DataFrame(),
        decisions=[],
        exit_events=[],
        universe_size={2020: 40},
        started_at=datetime(2026, 4, 6, 10, 0, 0),
        finished_at=datetime(2026, 4, 6, 10, 5, 0),
        git_sha='abc123',
        data_inputs_hash='def456',
    )
    assert result.config['NUM_POSITIONS'] == 5
    assert result.git_sha == 'abc123'


# -- _mark_to_market ----------------------------------------------------------

def _make_position(entry_price, shares, entry_idx=0, high_price=None):
    return {
        'entry_price': float(entry_price),
        'shares': float(shares),
        'entry_date': pd.Timestamp('2020-01-02'),
        'entry_idx': entry_idx,
        'original_entry_idx': entry_idx,
        'high_price': float(high_price or entry_price),
        'entry_vol': 0.25,
        'entry_daily_vol': 0.016,
        'sector': 'Tech',
    }


def test_mark_to_market_empty_positions():
    state = BacktestState(
        cash=100_000.0, positions={}, peak_value=100_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    pv = _mark_to_market(state, {}, pd.Timestamp('2020-01-02'))
    assert pv == 100_000.0


def test_mark_to_market_with_one_position():
    state = BacktestState(
        cash=50_000.0,
        positions={'AAPL': _make_position(150.0, 100)},
        peak_value=50_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    price_data = {
        'AAPL': pd.DataFrame(
            {'Close': [155.0]}, index=[pd.Timestamp('2020-01-03')]
        ),
    }
    pv = _mark_to_market(state, price_data, pd.Timestamp('2020-01-03'))
    assert pv == 50_000.0 + 100.0 * 155.0


def test_mark_to_market_falls_back_to_entry_price_on_missing_date():
    state = BacktestState(
        cash=0.0,
        positions={'AAPL': _make_position(150.0, 10)},
        peak_value=1500.0, crash_cooldown=0, portfolio_value_history=(),
    )
    price_data = {
        'AAPL': pd.DataFrame(
            {'Close': [150.0]}, index=[pd.Timestamp('2020-01-02')]
        ),
    }
    pv = _mark_to_market(state, price_data, pd.Timestamp('2020-01-05'))
    assert pv == 1500.0  # fallback to entry_price * shares


# -- get_tradeable_symbols ----------------------------------------------------

def test_get_tradeable_symbols_intersects_pit_and_price_data():
    pit_universe = {2020: ['AAPL', 'GOOG', 'DELISTED']}
    price_data = {
        'AAPL': pd.DataFrame(
            {'Close': [100.0]}, index=[pd.Timestamp('2020-01-02')]
        ),
        'GOOG': pd.DataFrame(
            {'Close': [1500.0]}, index=[pd.Timestamp('2020-01-02')]
        ),
        # DELISTED has no price data at all — must be excluded
    }
    tradeable = get_tradeable_symbols(
        pit_universe, price_data, pd.Timestamp('2020-01-02'), min_age_days=0
    )
    assert 'AAPL' in tradeable
    assert 'GOOG' in tradeable
    assert 'DELISTED' not in tradeable


def test_get_tradeable_symbols_respects_min_age():
    pit_universe = {2020: ['AAPL', 'NEW_IPO']}
    # AAPL has 800 bars from 2018-01-01 — fully covers through 2020-01-02 with >63 days prior
    aapl_index = pd.date_range('2018-01-01', periods=800)
    # NEW_IPO has only 2 bars starting at 2020-01-01
    new_ipo_index = pd.date_range('2020-01-01', periods=2)
    price_data = {
        'AAPL': pd.DataFrame({'Close': list(range(800))}, index=aapl_index),
        'NEW_IPO': pd.DataFrame({'Close': [50.0, 51.0]}, index=new_ipo_index),
    }
    # Pick a date that both series cover
    query_date = pd.Timestamp('2020-01-02')
    assert query_date in aapl_index
    assert query_date in new_ipo_index
    tradeable = get_tradeable_symbols(
        pit_universe, price_data, query_date, min_age_days=63
    )
    assert 'AAPL' in tradeable
    assert 'NEW_IPO' not in tradeable  # only 2 days of history
