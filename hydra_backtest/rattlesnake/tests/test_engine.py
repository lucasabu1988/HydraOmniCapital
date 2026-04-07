"""Tests for hydra_backtest.rattlesnake.engine."""
import pandas as pd
import pytest

import numpy as np

from hydra_backtest.engine import BacktestResult, BacktestState
from hydra_backtest.rattlesnake.engine import (
    _apply_rattlesnake_daily_costs,
    _resolve_rattlesnake_universe,
    apply_rattlesnake_entries,
    apply_rattlesnake_exits,
    run_rattlesnake_backtest,
)


# -- _resolve_rattlesnake_universe -------------------------------------------

def test_resolve_universe_intersects_with_pit():
    from rattlesnake_signals import R_UNIVERSE
    sample = R_UNIVERSE[:5]  # take 5 real R_UNIVERSE tickers
    pit_universe = {2010: list(sample) + ['NOTINR'], 2021: list(sample[:3])}
    result_2010 = _resolve_rattlesnake_universe(pit_universe, 2010)
    for t in sample:
        assert t in result_2010
    assert 'NOTINR' not in result_2010
    assert result_2010 == sorted(result_2010)


def test_resolve_universe_returns_empty_for_missing_year():
    result = _resolve_rattlesnake_universe({}, 2010)
    assert result == []


# -- helpers for exit/entry tests --------------------------------------------

def _make_rattle_position(entry_price, shares, entry_idx=0, days_held=0):
    return {
        'symbol': 'AAPL',
        'entry_price': float(entry_price),
        'shares': float(shares),
        'entry_date': pd.Timestamp('2020-01-02'),
        'entry_idx': entry_idx,
        'days_held': days_held,
        'sector': 'Unknown',
        'entry_vol': 0.0,
        'entry_daily_vol': 0.0,
        'high_price': float(entry_price),
    }


def _make_minimal_config():
    return {
        'INITIAL_CAPITAL': 100_000,
        'COMMISSION_PER_SHARE': 0.0035,
    }


# -- apply_rattlesnake_exits -------------------------------------------------

def test_apply_rattlesnake_exits_profit_target():
    """+4% triggers R_PROFIT exit."""
    pos = _make_rattle_position(100.0, 10, days_held=2)
    state = BacktestState(
        cash=50_000.0, positions={'AAPL': pos}, peak_value=51_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame(
        {'Open': [100.0, 105.0], 'Close': [100.0, 105.0]},
        index=pd.date_range('2020-01-02', periods=2),
    )
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    config = _make_minimal_config()
    new_state, trades, _ = apply_rattlesnake_exits(
        state, all_dates[1], 1, price_data, config,
        execution_mode='same_close', all_dates=all_dates,
    )
    assert 'AAPL' not in new_state.positions
    assert len(trades) == 1
    assert trades[0]['exit_reason'] == 'R_PROFIT'
    assert trades[0]['exit_price'] == 105.0


def test_apply_rattlesnake_exits_stop_loss():
    """-5% triggers R_STOP exit."""
    pos = _make_rattle_position(100.0, 10, days_held=2)
    state = BacktestState(
        cash=50_000.0, positions={'AAPL': pos}, peak_value=51_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame(
        {'Open': [100.0, 95.0], 'Close': [100.0, 95.0]},
        index=pd.date_range('2020-01-02', periods=2),
    )
    all_dates = list(df.index)
    new_state, trades, _ = apply_rattlesnake_exits(
        state, all_dates[1], 1, {'AAPL': df}, _make_minimal_config(),
        execution_mode='same_close', all_dates=all_dates,
    )
    assert 'AAPL' not in new_state.positions
    assert trades[0]['exit_reason'] == 'R_STOP'


def test_apply_rattlesnake_exits_time_limit():
    """days_held >= R_MAX_HOLD_DAYS (=8) triggers R_TIME exit."""
    from rattlesnake_signals import R_MAX_HOLD_DAYS
    pos = _make_rattle_position(100.0, 10, days_held=R_MAX_HOLD_DAYS)
    state = BacktestState(
        cash=50_000.0, positions={'AAPL': pos}, peak_value=51_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame(
        {'Open': [100.0, 100.0], 'Close': [100.0, 100.0]},
        index=pd.date_range('2020-01-02', periods=2),
    )
    all_dates = list(df.index)
    new_state, trades, _ = apply_rattlesnake_exits(
        state, all_dates[1], 1, {'AAPL': df}, _make_minimal_config(),
        execution_mode='same_close', all_dates=all_dates,
    )
    assert trades[0]['exit_reason'] == 'R_TIME'


def test_apply_rattlesnake_exits_no_exit_holds_position():
    """Within hold window, within profit/stop bounds → position carries."""
    pos = _make_rattle_position(100.0, 10, days_held=3)
    state = BacktestState(
        cash=50_000.0, positions={'AAPL': pos}, peak_value=51_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame(
        {'Open': [100.0, 102.0], 'Close': [100.0, 102.0]},
        index=pd.date_range('2020-01-02', periods=2),
    )
    all_dates = list(df.index)
    new_state, trades, _ = apply_rattlesnake_exits(
        state, all_dates[1], 1, {'AAPL': df}, _make_minimal_config(),
        execution_mode='same_close', all_dates=all_dates,
    )
    assert 'AAPL' in new_state.positions
    assert len(trades) == 0


def test_apply_rattlesnake_exits_next_open_mode_uses_next_open():
    """In next_open mode, exit fills at Open[T+1] not Close[T]."""
    pos = _make_rattle_position(100.0, 10, days_held=2)
    state = BacktestState(
        cash=50_000.0, positions={'AAPL': pos}, peak_value=51_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame({
        'Open': [100.0, 105.0, 103.0],
        'Close': [100.0, 105.0, 105.0],
    }, index=pd.date_range('2020-01-02', periods=3))
    all_dates = list(df.index)
    new_state, trades, _ = apply_rattlesnake_exits(
        state, all_dates[1], 1, {'AAPL': df}, _make_minimal_config(),
        execution_mode='next_open', all_dates=all_dates,
    )
    assert trades[0]['exit_reason'] == 'R_PROFIT'
    assert trades[0]['exit_price'] == 103.0


# -- apply_rattlesnake_entries -----------------------------------------------

def _make_candidate(symbol, price, drop_pct=-0.10, rsi=20.0):
    return {
        'symbol': symbol,
        'score': -drop_pct,
        'drop_pct': drop_pct,
        'rsi': rsi,
        'price': price,
    }


def test_apply_rattlesnake_entries_opens_positions_up_to_max():
    state = BacktestState(
        cash=100_000.0, positions={}, peak_value=100_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    candidates = [
        _make_candidate('AAA', 100.0),
        _make_candidate('BBB', 50.0),
        _make_candidate('CCC', 200.0),
    ]
    dates = pd.date_range('2020-01-02', periods=2)
    price_data = {
        'AAA': pd.DataFrame({'Open': [100.0, 100.0], 'Close': [100.0, 100.0]}, index=dates),
        'BBB': pd.DataFrame({'Open': [50.0, 50.0], 'Close': [50.0, 50.0]}, index=dates),
        'CCC': pd.DataFrame({'Open': [200.0, 200.0], 'Close': [200.0, 200.0]}, index=dates),
    }
    config = _make_minimal_config()
    new_state, decisions = apply_rattlesnake_entries(
        state, dates[0], 0, price_data, candidates,
        max_positions=5, config=config,
        execution_mode='same_close', all_dates=list(dates),
    )
    assert len(new_state.positions) == 3
    assert all(s in new_state.positions for s in ['AAA', 'BBB', 'CCC'])


def test_apply_rattlesnake_entries_uses_fixed_initial_cash_for_sizing():
    """All entries in one call must size against the SAME snapshot of cash,
    not against the residual cash that decreases as positions are opened.
    Mirrors omnicapital_live.py:2151."""
    from rattlesnake_signals import R_POSITION_SIZE
    state = BacktestState(
        cash=100_000.0, positions={}, peak_value=100_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    candidates = [_make_candidate('AAA', 100.0), _make_candidate('BBB', 100.0)]
    dates = pd.date_range('2020-01-02', periods=2)
    price_data = {
        sym: pd.DataFrame({'Open': [100.0, 100.0], 'Close': [100.0, 100.0]}, index=dates)
        for sym in ['AAA', 'BBB']
    }
    config = _make_minimal_config()
    new_state, _ = apply_rattlesnake_entries(
        state, dates[0], 0, price_data, candidates,
        max_positions=5, config=config,
        execution_mode='same_close', all_dates=list(dates),
    )
    # Both positions target $20K (= $100K initial * 0.20), 200 shares each
    expected_shares = int(100_000 * R_POSITION_SIZE / 100.0)
    assert new_state.positions['AAA']['shares'] == expected_shares
    assert new_state.positions['BBB']['shares'] == expected_shares


def test_apply_rattlesnake_entries_uses_integer_shares():
    """Rattlesnake uses integer shares (omnicapital_live.py:2152)."""
    state = BacktestState(
        cash=100_000.0, positions={}, peak_value=100_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    candidates = [_make_candidate('AAA', 137.50)]
    dates = pd.date_range('2020-01-02', periods=2)
    price_data = {
        'AAA': pd.DataFrame({'Open': [137.50, 137.50], 'Close': [137.50, 137.50]}, index=dates),
    }
    new_state, _ = apply_rattlesnake_entries(
        state, dates[0], 0, price_data, candidates, max_positions=5,
        config=_make_minimal_config(), execution_mode='same_close',
        all_dates=list(dates),
    )
    shares = new_state.positions['AAA']['shares']
    assert shares == int(shares)
    # 100_000 * 0.20 / 137.50 = 145.45 → int → 145
    assert shares == 145


def test_apply_rattlesnake_entries_skips_when_no_slots():
    state = BacktestState(
        cash=100_000.0,
        positions={f'P{i}': _make_rattle_position(100.0, 10) for i in range(5)},
        peak_value=100_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    candidates = [_make_candidate('AAA', 100.0)]
    dates = pd.date_range('2020-01-02', periods=2)
    new_state, _ = apply_rattlesnake_entries(
        state, dates[0], 0, {}, candidates, max_positions=5,
        config=_make_minimal_config(), execution_mode='same_close',
        all_dates=list(dates),
    )
    assert 'AAA' not in new_state.positions
    assert len(new_state.positions) == 5


def test_apply_rattlesnake_entries_skips_when_cash_insufficient():
    state = BacktestState(
        cash=500.0, positions={}, peak_value=500.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    candidates = [_make_candidate('AAA', 100.0)]
    dates = pd.date_range('2020-01-02', periods=2)
    new_state, _ = apply_rattlesnake_entries(
        state, dates[0], 0, {}, candidates, max_positions=5,
        config=_make_minimal_config(), execution_mode='same_close',
        all_dates=list(dates),
    )
    assert len(new_state.positions) == 0


def test_apply_rattlesnake_entries_skips_zero_share_positions():
    """When position_value < entry_price, shares=0 → skip."""
    state = BacktestState(
        cash=1500.0, positions={}, peak_value=1500.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    candidates = [_make_candidate('AAA', 5000.0)]  # very expensive ticker
    dates = pd.date_range('2020-01-02', periods=2)
    price_data = {
        'AAA': pd.DataFrame({'Open': [5000.0, 5000.0], 'Close': [5000.0, 5000.0]}, index=dates),
    }
    # 1500 * 0.20 / 5000 = 0.06 → int → 0 → skip
    new_state, _ = apply_rattlesnake_entries(
        state, dates[0], 0, price_data, candidates, max_positions=5,
        config=_make_minimal_config(), execution_mode='same_close',
        all_dates=list(dates),
    )
    assert len(new_state.positions) == 0


# -- _apply_rattlesnake_daily_costs ------------------------------------------

def test_daily_costs_rattlesnake_cash_yield_only():
    state = BacktestState(
        cash=10_000.0, positions={}, peak_value=10_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    new_state = _apply_rattlesnake_daily_costs(state, cash_yield_annual_pct=3.5)
    expected = 10_000.0 * (1 + 0.035 / 252)
    assert abs(new_state.cash - expected) < 1e-6


def test_daily_costs_rattlesnake_zero_cash():
    state = BacktestState(
        cash=0.0, positions={}, peak_value=0.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    new_state = _apply_rattlesnake_daily_costs(state, cash_yield_annual_pct=3.5)
    assert new_state.cash == 0.0


def test_daily_costs_rattlesnake_negative_yield_ignored():
    state = BacktestState(
        cash=10_000.0, positions={}, peak_value=10_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    new_state = _apply_rattlesnake_daily_costs(state, cash_yield_annual_pct=-0.10)
    assert new_state.cash == 10_000.0


# -- run_rattlesnake_backtest integration ------------------------------------

def test_run_rattlesnake_backtest_smoke():
    """Minimal 400-day backtest with synthetic data. Verify it returns
    a valid BacktestResult without crashing."""
    dates = pd.date_range('2020-01-02', periods=400)

    # Build 30 synthetic tickers with normal returns
    price_data = {}
    for k in range(30):
        base = 100.0 + k
        returns = np.random.normal(0.0005, 0.020, 400)
        closes = base * np.exp(np.cumsum(returns))
        price_data[f'T{k:02d}'] = pd.DataFrame({
            'Open': closes,
            'High': closes * 1.005,
            'Low': closes * 0.995,
            'Close': closes,
            'Volume': [1_500_000] * 400,
        }, index=dates)

    spy_returns = np.random.normal(0.0005, 0.012, 400)
    spy_close = 300.0 * np.exp(np.cumsum(spy_returns))
    spy_data = pd.DataFrame({'Close': spy_close}, index=dates)
    vix_data = pd.Series([15.0] * 400, index=dates, name='vix')

    # Override R_UNIVERSE to make synthetic tickers eligible
    import rattlesnake_signals as rs
    original_universe = rs.R_UNIVERSE
    rs.R_UNIVERSE = [f'T{k:02d}' for k in range(30)]
    try:
        pit_universe = {
            2020: [f'T{k:02d}' for k in range(30)],
            2021: [f'T{k:02d}' for k in range(30)],
        }
        cash_yield = pd.Series([3.5] * 400, index=dates)
        config = {
            'INITIAL_CAPITAL': 100_000,
            'COMMISSION_PER_SHARE': 0.0035,
            'NUM_POSITIONS': 5,
            'NUM_POSITIONS_RISK_OFF': 2,
            'MIN_AGE_DAYS': 220,
        }
        result = run_rattlesnake_backtest(
            config=config, price_data=price_data, pit_universe=pit_universe,
            spy_data=spy_data, vix_data=vix_data, cash_yield_daily=cash_yield,
            start_date=dates[0], end_date=dates[-1],
            execution_mode='same_close',
        )
    finally:
        rs.R_UNIVERSE = original_universe

    assert isinstance(result, BacktestResult)
    assert len(result.daily_values) == 400
    assert 'portfolio_value' in result.daily_values.columns
    assert result.daily_values['portfolio_value'].iloc[0] > 0
    assert len(result.git_sha) > 0


def test_run_rattlesnake_backtest_days_held_increments():
    """Smoke test verifying the days_held counter doesn't crash and the
    backtest completes when a single ticker is in the universe."""
    dates = pd.date_range('2020-01-02', periods=300)

    closes = ([100.0] * 250 + [90.0] * 5 + [91.0] * 45)
    price_data = {
        'AAA': pd.DataFrame({
            'Open': closes, 'High': [c * 1.01 for c in closes],
            'Low': [c * 0.99 for c in closes], 'Close': closes,
            'Volume': [2_000_000] * 300,
        }, index=dates),
    }
    spy_data = pd.DataFrame({'Close': [300.0] * 300}, index=dates)
    vix_data = pd.Series([15.0] * 300, index=dates, name='vix')

    import rattlesnake_signals as rs
    original_universe = rs.R_UNIVERSE
    rs.R_UNIVERSE = ['AAA']
    try:
        pit_universe = {2020: ['AAA']}
        config = {
            'INITIAL_CAPITAL': 100_000,
            'COMMISSION_PER_SHARE': 0.0035,
            'NUM_POSITIONS': 5,
            'NUM_POSITIONS_RISK_OFF': 2,
            'MIN_AGE_DAYS': 220,
        }
        result = run_rattlesnake_backtest(
            config=config, price_data=price_data, pit_universe=pit_universe,
            spy_data=spy_data, vix_data=vix_data,
            cash_yield_daily=pd.Series([0.0] * 300, index=dates),
            start_date=dates[0], end_date=dates[-1],
            execution_mode='same_close',
        )
    finally:
        rs.R_UNIVERSE = original_universe

    # Just verify the backtest completed without error
    assert isinstance(result, BacktestResult)
    assert len(result.daily_values) == 300
