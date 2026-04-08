"""Unit tests for hydra_backtest.hydra.state."""
import pytest

from hydra_backtest.hydra.capital import HydraCapitalState
from hydra_backtest.hydra.state import (
    HydraBacktestState,
    compute_pillar_invested,
    merge_pillar_substate,
    slice_positions_by_strategy,
    to_pillar_substate,
)


def _make_state(positions=None, cash=100_000.0):
    capital = HydraCapitalState(
        compass_account=42_500, rattle_account=42_500,
        catalyst_account=15_000, efa_value=0.0,
    )
    return HydraBacktestState(
        cash=cash,
        positions=positions or {},
        peak_value=cash,
        crash_cooldown=0,
        portfolio_value_history=(),
        capital=capital,
    )


def test_slice_filters_by_strategy_tag():
    positions = {
        'AAPL': {'symbol': 'AAPL', 'shares': 100, '_strategy': 'compass'},
        'MSFT': {'symbol': 'MSFT', 'shares': 50, '_strategy': 'rattle'},
        'GLD': {'symbol': 'GLD', 'shares': 20, '_strategy': 'catalyst'},
        'EFA': {'symbol': 'EFA', 'shares': 10, '_strategy': 'efa'},
    }
    assert set(slice_positions_by_strategy(positions, 'compass').keys()) == {'AAPL'}
    assert set(slice_positions_by_strategy(positions, 'rattle').keys()) == {'MSFT'}
    assert set(slice_positions_by_strategy(positions, 'catalyst').keys()) == {'GLD'}
    assert set(slice_positions_by_strategy(positions, 'efa').keys()) == {'EFA'}


def test_slice_excludes_untagged_positions():
    positions = {
        'AAPL': {'symbol': 'AAPL', 'shares': 100, '_strategy': 'compass'},
        'ORPHAN': {'symbol': 'ORPHAN', 'shares': 5},  # no _strategy tag
    }
    assert set(slice_positions_by_strategy(positions, 'compass').keys()) == {'AAPL'}
    # ORPHAN is excluded from every strategy view
    for strat in ('compass', 'rattle', 'catalyst', 'efa'):
        assert 'ORPHAN' not in slice_positions_by_strategy(positions, strat)


def test_slice_invalid_strategy_raises():
    with pytest.raises(ValueError, match="Invalid strategy"):
        slice_positions_by_strategy({}, 'foo')


def test_to_pillar_substate_uses_full_cash_by_default():
    state = _make_state(positions={
        'AAPL': {'symbol': 'AAPL', 'shares': 100, '_strategy': 'compass'},
        'MSFT': {'symbol': 'MSFT', 'shares': 50, '_strategy': 'rattle'},
    })
    sub = to_pillar_substate(state, 'compass')
    assert sub.cash == 100_000.0
    assert set(sub.positions.keys()) == {'AAPL'}


def test_to_pillar_substate_cash_override():
    state = _make_state()
    sub = to_pillar_substate(state, 'compass', cash_override=42_500.0)
    assert sub.cash == 42_500.0


def test_merge_round_trip_lossless():
    """Slice → identity transform → merge should give back the same state."""
    positions = {
        'AAPL': {'symbol': 'AAPL', 'shares': 100, '_strategy': 'compass',
                 'entry_price': 150.0},
        'MSFT': {'symbol': 'MSFT', 'shares': 50, '_strategy': 'rattle',
                 'entry_price': 300.0},
    }
    state = _make_state(positions=positions)
    sub = to_pillar_substate(state, 'compass')
    merged = merge_pillar_substate(
        state, sub, 'compass', cash_delta=0.0, capital_account_delta=0.0
    )
    assert set(merged.positions.keys()) == {'AAPL', 'MSFT'}
    assert merged.positions['AAPL']['_strategy'] == 'compass'
    assert merged.positions['MSFT']['_strategy'] == 'rattle'
    assert merged.cash == state.cash
    assert merged.capital.compass_account == state.capital.compass_account


def test_merge_tags_new_positions():
    """A new position from the substate must inherit the strategy tag."""
    state = _make_state()
    new_sub = to_pillar_substate(state, 'compass', cash_override=42_500.0)
    new_sub_with_pos = new_sub._replace(
        cash=30_000.0,
        positions={'AAPL': {'symbol': 'AAPL', 'shares': 100, 'entry_price': 125.0}},
    )
    merged = merge_pillar_substate(
        state, new_sub_with_pos, 'compass',
        cash_delta=-12_500.0, capital_account_delta=-12_500.0,
    )
    assert merged.positions['AAPL']['_strategy'] == 'compass'
    assert merged.cash == 100_000.0 - 12_500.0
    assert merged.capital.compass_account == 42_500.0 - 12_500.0


def test_merge_does_not_touch_other_strategies():
    positions = {
        'AAPL': {'symbol': 'AAPL', 'shares': 100, '_strategy': 'compass',
                 'entry_price': 150.0},
        'MSFT': {'symbol': 'MSFT', 'shares': 50, '_strategy': 'rattle',
                 'entry_price': 300.0},
        'GLD': {'symbol': 'GLD', 'shares': 20, '_strategy': 'catalyst',
                'entry_price': 400.0},
    }
    state = _make_state(positions=positions)
    sub = to_pillar_substate(state, 'compass')
    sub2 = sub._replace(positions={})  # all compass positions exited
    merged = merge_pillar_substate(
        state, sub2, 'compass', cash_delta=15_000.0, capital_account_delta=15_000.0
    )
    # MSFT (rattle) and GLD (catalyst) untouched
    assert 'MSFT' in merged.positions
    assert 'GLD' in merged.positions
    assert merged.positions['MSFT']['_strategy'] == 'rattle'
    assert merged.positions['GLD']['_strategy'] == 'catalyst'
    # AAPL gone
    assert 'AAPL' not in merged.positions


def test_compute_pillar_invested_uses_current_prices():
    positions = {
        'AAPL': {'symbol': 'AAPL', 'shares': 100, 'entry_price': 150.0,
                 '_strategy': 'compass'},
        'MSFT': {'symbol': 'MSFT', 'shares': 50, 'entry_price': 300.0,
                 '_strategy': 'rattle'},
    }
    prices = {'AAPL': 200.0, 'MSFT': 250.0}
    assert compute_pillar_invested(positions, 'compass', prices) == 20_000.0
    assert compute_pillar_invested(positions, 'rattle', prices) == 12_500.0


def test_compute_pillar_invested_falls_back_to_entry_price():
    positions = {
        'AAPL': {'symbol': 'AAPL', 'shares': 100, 'entry_price': 150.0,
                 '_strategy': 'compass'},
    }
    # AAPL not in prices → falls back to entry_price
    assert compute_pillar_invested(positions, 'compass', {}) == 15_000.0


def test_compute_pillar_invested_empty_pillar():
    positions = {
        'AAPL': {'symbol': 'AAPL', 'shares': 100, 'entry_price': 150.0,
                 '_strategy': 'compass'},
    }
    assert compute_pillar_invested(positions, 'rattle', {'AAPL': 200.0}) == 0.0


def test_merge_raises_on_symbol_collision_with_other_pillar():
    """v1.4 T19 catastrophic bug: state.positions is keyed by symbol, so
    if pillar A merges a position whose symbol is held by pillar B, the
    dict spread silently overwrites B's position, vanishing its value.
    The defensive assertion in merge_pillar_substate must catch this so
    the orchestrator is forced to filter cross-pillar held symbols
    BEFORE calling apply_*_entries.

    Repro: GE held by compass on 2000-01-07, rattle finds GE as RSI<25
    candidate and tries to enter it. The merge would silently overwrite
    compass's GE position, causing a $11k vanish from PV.
    """
    from hydra_backtest.engine import BacktestState

    state = _make_state(positions={
        'GE': {
            '_strategy': 'compass', 'shares': 100, 'entry_price': 50.0,
            'entry_date': None,
        },
    })
    # Rattle substate that "buys" GE — simulates the bug condition
    new_substate = BacktestState(
        cash=50_000, peak_value=100_000, crash_cooldown=0,
        portfolio_value_history=(),
        positions={
            'GE': {'shares': 80, 'entry_price': 51.0, 'entry_date': None},
        },
    )
    with pytest.raises(ValueError, match="symbol collision"):
        merge_pillar_substate(
            state, new_substate, 'rattle',
            cash_delta=-4_080.0, capital_account_delta=0.0,
        )


def test_merge_no_collision_when_pillars_disjoint():
    """When the merged pillar's symbols are disjoint from other pillars'
    symbols, merge proceeds normally — the collision check must not
    trigger false positives."""
    from hydra_backtest.engine import BacktestState

    state = _make_state(positions={
        'AAPL': {
            '_strategy': 'compass', 'shares': 100, 'entry_price': 150.0,
            'entry_date': None,
        },
    })
    new_substate = BacktestState(
        cash=20_000, peak_value=100_000, crash_cooldown=0,
        portfolio_value_history=(),
        positions={
            'XOM': {'shares': 200, 'entry_price': 80.0, 'entry_date': None},
        },
    )
    # Should not raise
    new_state = merge_pillar_substate(
        state, new_substate, 'rattle',
        cash_delta=-16_000.0, capital_account_delta=0.0,
    )
    assert 'AAPL' in new_state.positions
    assert 'XOM' in new_state.positions
    assert new_state.positions['AAPL']['_strategy'] == 'compass'
    assert new_state.positions['XOM']['_strategy'] == 'rattle'
