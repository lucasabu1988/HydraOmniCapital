"""Tests for hydra_backtest.engine module."""
from datetime import datetime

import pandas as pd
import pytest

import numpy as np

from hydra_backtest.engine import (
    BacktestResult,
    BacktestState,
    _get_exec_price,
    _mark_to_market,
    apply_daily_costs,
    apply_entries,
    apply_exits,
    get_current_leverage_pure,
    get_max_positions_pure,
    get_tradeable_symbols,
    run_backtest,
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


# -- get_current_leverage_pure -----------------------------------------------

def _synthetic_spy(n=260, start_price=100.0, daily_return=0.0003):
    """Build a realistic SPY price series for leverage tests."""
    import numpy as np
    prices = [start_price]
    for _ in range(n - 1):
        prices.append(prices[-1] * (1 + daily_return))
    return pd.DataFrame(
        {'Close': prices},
        index=pd.date_range('2019-01-01', periods=n),
    )


def test_leverage_normal_regime(minimal_config):
    spy = _synthetic_spy()
    lev, cooldown, crash_active = get_current_leverage_pure(
        drawdown=0.0,
        portfolio_value_history=(100_000.0,) * 20,
        crash_cooldown=0,
        config=minimal_config,
        spy_hist=spy,
    )
    assert minimal_config['LEV_FLOOR'] - 1e-9 <= lev <= minimal_config['LEVERAGE_MAX'] + 1e-9
    assert not crash_active


def test_leverage_dd_scaling(minimal_config):
    spy = _synthetic_spy()
    # -25% drawdown → DD scaling tier2 territory
    lev, cooldown, crash_active = get_current_leverage_pure(
        drawdown=-0.25,
        portfolio_value_history=(100_000.0,) * 20,
        crash_cooldown=0,
        config=minimal_config,
        spy_hist=spy,
    )
    assert lev < minimal_config['LEV_FULL']
    assert not crash_active


def test_crash_brake_fires_on_5d_drop(minimal_config):
    spy = _synthetic_spy()
    # 5-day return of -8% triggers CRASH_VEL_5D (-6%).
    # history[-5] = 100000, history[-1] = 92000 → (92000/100000 - 1) = -8% ≤ -6%
    history = (100_000.0, 100_000.0, 100_000.0, 100_000.0, 92_000.0)
    lev, cooldown, crash_active = get_current_leverage_pure(
        drawdown=-0.08,
        portfolio_value_history=history,
        crash_cooldown=0,
        config=minimal_config,
        spy_hist=spy,
    )
    assert crash_active
    assert lev <= minimal_config['CRASH_LEVERAGE'] + 1e-9
    assert cooldown == minimal_config['CRASH_COOLDOWN'] - 1


def test_crash_brake_bypasses_lev_floor(minimal_config):
    """When the crash brake fires, the returned leverage must be BELOW
    LEV_FLOOR (0.15 < 0.30). Mirrors omnicapital_live.py:1444-1446."""
    spy = _synthetic_spy()
    history = (100_000.0,) * 4 + (92_000.0,)
    lev, _, crash_active = get_current_leverage_pure(
        drawdown=-0.08,
        portfolio_value_history=history,
        crash_cooldown=0,
        config=minimal_config,
        spy_hist=spy,
    )
    assert crash_active
    assert lev < minimal_config['LEV_FLOOR'], (
        f"Crash brake bypass failed: leverage {lev} should be < LEV_FLOOR "
        f"{minimal_config['LEV_FLOOR']} when brake is active"
    )


def test_crash_cooldown_persists(minimal_config):
    """If we're already in cooldown, leverage stays at CRASH_LEVERAGE
    regardless of current portfolio trajectory."""
    spy = _synthetic_spy()
    lev, _, crash_active = get_current_leverage_pure(
        drawdown=-0.02,
        portfolio_value_history=(100_000.0,) * 20,
        crash_cooldown=5,
        config=minimal_config,
        spy_hist=spy,
    )
    assert crash_active
    assert lev <= minimal_config['CRASH_LEVERAGE'] + 1e-9


# -- get_max_positions_pure --------------------------------------------------

def test_max_positions_risk_on(minimal_config):
    spy = _synthetic_spy()
    mp = get_max_positions_pure(regime_score=0.8, spy_hist=spy, config=minimal_config)
    assert mp >= minimal_config['NUM_POSITIONS']


def test_max_positions_risk_off(minimal_config):
    spy = pd.DataFrame(
        {'Close': [100.0] * 250},
        index=pd.date_range('2019-01-01', periods=250),
    )
    mp = get_max_positions_pure(regime_score=0.20, spy_hist=spy, config=minimal_config)
    assert mp == minimal_config['NUM_POSITIONS_RISK_OFF']


def test_max_positions_bull_override(minimal_config):
    """SPY > 1.03 * SMA200 AND score > 0.40 → attempt +1 (capped at max)."""
    spy_prices = [100.0] * 200 + [110.0] * 50
    spy = pd.DataFrame(
        {'Close': spy_prices},
        index=pd.date_range('2019-01-01', periods=250),
    )
    mp = get_max_positions_pure(regime_score=0.70, spy_hist=spy, config=minimal_config)
    # Regime score 0.70 → base = NUM_POSITIONS (5). Bull override caps at max, so still 5.
    assert mp == minimal_config['NUM_POSITIONS']


# -- apply_daily_costs -------------------------------------------------------

def test_daily_cash_yield_positive(minimal_config):
    state = BacktestState(
        cash=10_000.0, positions={}, peak_value=10_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    new_state = apply_daily_costs(
        state, leverage=1.0, cash_yield_annual_pct=3.5,
        portfolio_value=10_000.0, config=minimal_config,
    )
    expected = 10_000.0 * (1 + 0.035 / 252)
    assert abs(new_state.cash - expected) < 1e-6


def test_daily_cash_yield_zero_when_no_cash(minimal_config):
    state = BacktestState(
        cash=0.0, positions={}, peak_value=0.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    new_state = apply_daily_costs(
        state, leverage=1.0, cash_yield_annual_pct=3.5,
        portfolio_value=0.0, config=minimal_config,
    )
    assert new_state.cash == 0.0


def test_margin_cost_when_leveraged(minimal_config):
    state = BacktestState(
        cash=-20_000.0, positions={}, peak_value=100_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    new_state = apply_daily_costs(
        state, leverage=1.2, cash_yield_annual_pct=0.0,
        portfolio_value=100_000.0, config=minimal_config,
    )
    expected_borrowed = 100_000.0 * (0.2 / 1.2)
    expected_margin = expected_borrowed * (0.06 / 252)
    assert abs(new_state.cash - (-20_000.0 - expected_margin)) < 1e-6


# -- _get_exec_price ---------------------------------------------------------

def test_get_exec_price_same_close():
    df = pd.DataFrame(
        {'Open': [100.0, 101.0], 'Close': [100.5, 101.5]},
        index=pd.date_range('2020-01-02', periods=2),
    )
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    p = _get_exec_price('AAPL', all_dates[0], 0, all_dates, price_data, 'same_close')
    assert p == 100.5


def test_get_exec_price_next_open():
    df = pd.DataFrame(
        {'Open': [100.0, 101.0], 'Close': [100.5, 101.5]},
        index=pd.date_range('2020-01-02', periods=2),
    )
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    p = _get_exec_price('AAPL', all_dates[0], 0, all_dates, price_data, 'next_open')
    assert p == 101.0


def test_get_exec_price_next_open_last_bar_returns_none():
    df = pd.DataFrame(
        {'Open': [100.0], 'Close': [100.5]},
        index=pd.date_range('2020-01-02', periods=1),
    )
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    p = _get_exec_price('AAPL', all_dates[0], 0, all_dates, price_data, 'next_open')
    assert p is None


def test_get_exec_price_unknown_mode_raises():
    df = pd.DataFrame({'Close': [100.0]}, index=pd.date_range('2020-01-02', periods=1))
    with pytest.raises(ValueError, match="execution_mode"):
        _get_exec_price('AAPL', df.index[0], 0, list(df.index),
                        {'AAPL': df}, 'weird_mode')


# -- apply_exits -------------------------------------------------------------

def test_apply_exits_hold_expired(minimal_config):
    state = BacktestState(
        cash=50_000.0,
        positions={'AAPL': _make_position(100.0, 10, entry_idx=0)},
        peak_value=51_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame(
        {'Open': [100.0] * 10, 'Close': [100.0] * 10},
        index=pd.date_range('2020-01-02', periods=10),
    )
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    # i=5: days_held = 5 - 0 = 5 ≥ HOLD_DAYS → exit as hold_expired
    new_state, trades, _ = apply_exits(
        state, all_dates[5], 5, price_data, scores={}, tradeable=['AAPL'],
        max_positions=5, config=minimal_config, sector_map={'AAPL': 'Tech'},
        execution_mode='same_close', all_dates=all_dates,
    )
    assert 'AAPL' not in new_state.positions
    assert len(trades) == 1
    assert trades[0]['exit_reason'] == 'hold_expired'


def test_apply_exits_position_stop_fires(minimal_config):
    state = BacktestState(
        cash=50_000.0,
        positions={'AAPL': _make_position(100.0, 10, entry_idx=0)},
        peak_value=51_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame(
        {'Open': [90.0, 90.0], 'Close': [100.0, 90.0]},
        index=pd.date_range('2020-01-02', periods=2),
    )
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    new_state, trades, _ = apply_exits(
        state, all_dates[1], 1, price_data, scores={}, tradeable=['AAPL'],
        max_positions=5, config=minimal_config, sector_map={'AAPL': 'Tech'},
        execution_mode='same_close', all_dates=all_dates,
    )
    assert 'AAPL' not in new_state.positions
    assert trades[0]['exit_reason'] == 'position_stop'


def test_apply_exits_trailing_stop_fires(minimal_config):
    """Entry at 100, high at 110, drop to 105 → trailing stop fires."""
    pos = _make_position(100.0, 10, entry_idx=0, high_price=110.0)
    state = BacktestState(
        cash=50_000.0, positions={'AAPL': pos},
        peak_value=51_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame(
        {'Open': [100.0, 105.0], 'Close': [100.0, 105.0]},
        index=pd.date_range('2020-01-02', periods=2),
    )
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    new_state, trades, _ = apply_exits(
        state, all_dates[1], 1, price_data, scores={}, tradeable=['AAPL'],
        max_positions=5, config=minimal_config, sector_map={'AAPL': 'Tech'},
        execution_mode='same_close', all_dates=all_dates,
    )
    assert 'AAPL' not in new_state.positions
    assert trades[0]['exit_reason'] == 'trailing_stop'


def test_apply_exits_universe_rotation(minimal_config):
    state = BacktestState(
        cash=50_000.0,
        positions={'AAPL': _make_position(100.0, 10, entry_idx=0)},
        peak_value=51_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame(
        {'Open': [100.0, 100.0], 'Close': [100.0, 100.0]},
        index=pd.date_range('2020-01-02', periods=2),
    )
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    new_state, trades, _ = apply_exits(
        state, all_dates[1], 1, price_data, scores={}, tradeable=[],
        max_positions=5, config=minimal_config, sector_map={'AAPL': 'Tech'},
        execution_mode='same_close', all_dates=all_dates,
    )
    assert 'AAPL' not in new_state.positions
    assert trades[0]['exit_reason'] == 'universe_rotation'


def test_apply_exits_next_open_mode_captures_gap(minimal_config):
    state = BacktestState(
        cash=50_000.0,
        positions={'AAPL': _make_position(100.0, 10, entry_idx=0)},
        peak_value=51_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame({
        'Open': [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 95.0],
        'Close': [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
    }, index=pd.date_range('2020-01-02', periods=7))
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    # i=5: hold_expired fires, next_open mode fills at Open[6]=95 (gap down captured)
    new_state, trades, _ = apply_exits(
        state, all_dates[5], 5, price_data, scores={}, tradeable=['AAPL'],
        max_positions=5, config=minimal_config, sector_map={'AAPL': 'Tech'},
        execution_mode='next_open', all_dates=all_dates,
    )
    assert trades[0]['exit_reason'] == 'hold_expired'
    assert trades[0]['exit_price'] == 95.0


# -- apply_entries -----------------------------------------------------------

def _make_extended_prices(symbols, start='2019-08-15', periods=150):
    """Build OHLCV dataframes long enough for compute_entry_vol."""
    index = pd.date_range(start, periods=periods)
    return {
        sym: pd.DataFrame({
            'Open': [100.0 + i * 0.1 for i in range(periods)],
            'High': [100.5 + i * 0.1 for i in range(periods)],
            'Low': [99.5 + i * 0.1 for i in range(periods)],
            'Close': [100.0 + i * 0.1 for i in range(periods)],
            'Volume': [1_000_000] * periods,
        }, index=index)
        for sym in symbols
    }


def test_apply_entries_opens_positions_up_to_max(minimal_config):
    # Lower MIN_MOMENTUM_STOCKS so the early-exit gate doesn't block this
    # small synthetic fixture. Real backtests have 20+ tradeable symbols.
    minimal_config['MIN_MOMENTUM_STOCKS'] = 5
    symbols = ['A', 'B', 'C', 'D', 'E', 'F']
    price_data = _make_extended_prices(symbols)
    sector_map = {s: f'Sector{i}' for i, s in enumerate(symbols)}
    scores = {s: 1.0 - i * 0.1 for i, s in enumerate(symbols)}
    all_dates = list(price_data['A'].index)
    state = BacktestState(
        cash=100_000.0, positions={}, peak_value=100_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    new_state, _ = apply_entries(
        state, all_dates[-1], len(all_dates) - 1, price_data, scores,
        tradeable=symbols, max_positions=5, leverage=1.0,
        config=minimal_config, sector_map=sector_map, all_dates=all_dates,
        execution_mode='same_close',
    )
    assert len(new_state.positions) == 5


def test_apply_entries_respects_sector_limit(minimal_config):
    minimal_config['MAX_PER_SECTOR'] = 2
    symbols = ['A', 'B', 'C', 'D', 'E']
    price_data = _make_extended_prices(symbols)
    sector_map = {s: 'Tech' for s in symbols}  # all same sector
    scores = {s: 1.0 - i * 0.1 for i, s in enumerate(symbols)}
    all_dates = list(price_data['A'].index)
    state = BacktestState(
        cash=100_000.0, positions={}, peak_value=100_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    new_state, _ = apply_entries(
        state, all_dates[-1], len(all_dates) - 1, price_data, scores,
        tradeable=symbols, max_positions=5, leverage=1.0,
        config=minimal_config, sector_map=sector_map, all_dates=all_dates,
        execution_mode='same_close',
    )
    assert len(new_state.positions) <= 2


def test_apply_entries_skips_if_cash_insufficient(minimal_config):
    symbols = ['A', 'B', 'C', 'D', 'E']
    price_data = _make_extended_prices(symbols)
    sector_map = {s: f'S{i}' for i, s in enumerate(symbols)}
    scores = {s: 1.0 - i * 0.1 for i, s in enumerate(symbols)}
    all_dates = list(price_data['A'].index)
    state = BacktestState(
        cash=500.0, positions={}, peak_value=500.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    new_state, _ = apply_entries(
        state, all_dates[-1], len(all_dates) - 1, price_data, scores,
        tradeable=symbols, max_positions=5, leverage=1.0,
        config=minimal_config, sector_map=sector_map, all_dates=all_dates,
        execution_mode='same_close',
    )
    assert len(new_state.positions) == 0  # cash < 1000 threshold


# -- run_backtest integration -----------------------------------------------

def test_run_backtest_smoke(minimal_config):
    """Minimal 200-day backtest with 30 synthetic tickers. Verify it returns
    a valid BacktestResult without crashing."""
    dates = pd.date_range('2020-01-02', periods=200)

    price_data = {}
    for k in range(30):
        base = 100.0 + k
        returns = np.random.normal(0.0005, 0.015, 200)
        closes = base * np.exp(np.cumsum(returns))
        price_data[f'T{k:02d}'] = pd.DataFrame({
            'Open': closes, 'High': closes * 1.005, 'Low': closes * 0.995,
            'Close': closes, 'Volume': [1_000_000] * 200,
        }, index=dates)

    spy_returns = np.random.normal(0.0005, 0.01, 200)
    spy_close = 100.0 * np.exp(np.cumsum(spy_returns))
    spy_data = pd.DataFrame({'Close': spy_close}, index=dates)

    pit_universe = {2020: [f'T{k:02d}' for k in range(30)]}
    sector_map = {f'T{k:02d}': f'Sector{k % 5}' for k in range(30)}
    cash_yield = pd.Series([3.5] * 200, index=dates)

    result = run_backtest(
        config=minimal_config, price_data=price_data, pit_universe=pit_universe,
        spy_data=spy_data, cash_yield_daily=cash_yield, sector_map=sector_map,
        start_date=dates[0], end_date=dates[-1], execution_mode='same_close',
    )
    assert isinstance(result, BacktestResult)
    assert len(result.daily_values) == 200
    assert 'portfolio_value' in result.daily_values.columns
    assert result.daily_values['portfolio_value'].iloc[0] > 0
    assert len(result.git_sha) > 0
