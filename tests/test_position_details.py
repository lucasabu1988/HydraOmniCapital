import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import compass_dashboard as dashboard


def make_state(positions=None, position_meta=None, trading_day_counter=6):
    return {
        'positions': positions or {},
        'position_meta': position_meta if position_meta is not None else {},
        'trading_day_counter': trading_day_counter,
    }


def test_compute_position_details_returns_empty_list_without_positions():
    result = dashboard.compute_position_details(make_state(), {})

    assert result == []


def test_compute_position_details_uses_avg_cost_when_entry_price_missing():
    state = make_state(
        positions={'AAPL': {'shares': 10, 'avg_cost': 123.45}},
        position_meta={'AAPL': {'entry_day_index': 5}},
        trading_day_counter=5,
    )

    result = dashboard.compute_position_details(state, {'AAPL': 130.0})

    assert len(result) == 1
    assert result[0]['entry_price'] == 123.45
    assert result[0]['current_price'] == 130.0


def test_compute_position_details_handles_zero_current_price_without_division_error():
    state = make_state(
        positions={'AAPL': {'shares': 10, 'avg_cost': 100.0}},
        position_meta={'AAPL': {'entry_price': 100.0, 'entry_day_index': 1}},
    )

    result = dashboard.compute_position_details(state, {'AAPL': 0.0})

    assert len(result) == 1
    assert result[0]['current_price'] == 100.0
    assert result[0]['market_value'] == 1000.0
    assert result[0]['pnl_pct'] == 0.0
    assert result[0]['pnl_dollar'] == 0.0


def test_compute_position_details_handles_invalid_entry_date_with_day_index_fallback():
    state = make_state(
        positions={'AAPL': {'shares': 10, 'avg_cost': 100.0}},
        position_meta={
            'AAPL': {
                'entry_price': 100.0,
                'entry_day_index': 3,
                'entry_date': 'not-a-date',
            }
        },
        trading_day_counter=6,
    )

    result = dashboard.compute_position_details(state, {'AAPL': 110.0})

    assert len(result) == 1
    assert result[0]['days_held'] == 4
    assert result[0]['days_remaining'] == 1
    assert result[0]['entry_date'] == 'not-a-date'


def test_compute_position_details_uses_defaults_when_position_meta_is_missing():
    state = make_state(
        positions={'AAPL': {'shares': 5, 'avg_cost': 100.0}},
        position_meta={},
        trading_day_counter=0,
    )

    result = dashboard.compute_position_details(state, {'AAPL': 110.0})

    assert len(result) == 1
    assert result[0]['entry_price'] == 100.0
    assert result[0]['high_price'] == 100.0
    assert result[0]['sector'] == 'Unknown'
    assert result[0]['days_held'] == 1
    assert result[0]['days_remaining'] == dashboard.COMPASS_CONFIG['HOLD_DAYS'] - 1


def test_compute_position_details_falls_back_to_entry_price_when_prices_are_missing():
    state = make_state(
        positions={'AAPL': {'shares': 10, 'avg_cost': 100.0}},
        position_meta={'AAPL': {'entry_price': 100.0, 'entry_day_index': 1}},
    )

    result = dashboard.compute_position_details(state, {})

    assert len(result) == 1
    assert result[0]['current_price'] == 100.0
    assert result[0]['market_value'] == 1000.0
    assert result[0]['pnl_pct'] == 0.0
    assert result[0]['today_change_pct'] == 0.0
    assert result[0]['prev_close'] is None
