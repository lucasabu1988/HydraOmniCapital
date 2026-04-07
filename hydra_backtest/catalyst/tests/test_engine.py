"""Unit tests for hydra_backtest.catalyst.engine."""
import numpy as np
import pandas as pd
import pytest

from hydra_backtest.catalyst.engine import (
    _has_enough_history,
    apply_catalyst_rebalance,
    run_catalyst_backtest,
)
from hydra_backtest.engine import BacktestState


def _make_asset(
    start: str = '2020-01-01',
    n_days: int = 400,
    drift: float = 0.0005,
    start_price: float = 100.0,
) -> pd.DataFrame:
    """Generate a deterministic geometric-drift OHLCV DataFrame for testing."""
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


@pytest.fixture
def four_assets_uptrend():
    """4 trending-up ETFs with enough history to satisfy SMA200."""
    return {
        'TLT': _make_asset(start_price=95),
        'ZROZ': _make_asset(start_price=85),
        'GLD': _make_asset(start_price=180),
        'DBC': _make_asset(start_price=25),
    }


@pytest.fixture
def cash_yield_zero():
    return pd.Series(0.0, index=pd.bdate_range('2020-01-01', periods=400))


def test_has_enough_history_true(four_assets_uptrend):
    last_date = four_assets_uptrend['TLT'].index[-1]
    assert _has_enough_history(four_assets_uptrend, 'TLT', last_date) is True


def test_has_enough_history_false_early(four_assets_uptrend):
    early_date = four_assets_uptrend['TLT'].index[50]
    assert _has_enough_history(four_assets_uptrend, 'TLT', early_date) is False


def test_has_enough_history_missing_ticker(four_assets_uptrend):
    last_date = four_assets_uptrend['TLT'].index[-1]
    assert _has_enough_history(four_assets_uptrend, 'NOPE', last_date) is False


def test_apply_rebalance_buys_all_four_when_uptrending(
    four_assets_uptrend, catalyst_minimal_config
):
    last_date = four_assets_uptrend['TLT'].index[-1]
    state = BacktestState(
        cash=100_000.0, positions={}, peak_value=100_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    all_dates = sorted(four_assets_uptrend['TLT'].index)
    new_state, trades, decisions = apply_catalyst_rebalance(
        state, last_date, len(all_dates) - 1, four_assets_uptrend,
        catalyst_minimal_config, 'same_close', all_dates,
    )
    assert len(new_state.positions) == 4
    assert {'TLT', 'ZROZ', 'GLD', 'DBC'} == set(new_state.positions.keys())
    # All four are new entries (no exit trades)
    assert all(d['action'] == 'ENTRY' for d in decisions)
    assert trades == []
    # Cash should be ~95% deployed (4 equal slots, integer share rounding)
    assert new_state.cash < 10_000.0


def test_apply_rebalance_sells_when_asset_drops_below_sma(catalyst_minimal_config):
    """One asset crashes below SMA200 — should be sold with CATALYST_TREND_OFF."""
    n = 250
    base = _make_asset(n_days=n, drift=0.001)
    # TLT crashes -50% over the last 30 days (firmly below SMA200)
    tlt = base.copy()
    crash_tail = np.linspace(
        tlt['Close'].iloc[-31], tlt['Close'].iloc[-31] * 0.5, 31
    )
    tlt.iloc[-31:, tlt.columns.get_loc('Close')] = crash_tail
    tlt['Open'] = tlt['Close']
    tlt['High'] = tlt['Close'] * 1.005
    tlt['Low'] = tlt['Close'] * 0.995

    assets = {
        'TLT': tlt,
        'ZROZ': base.copy(),
        'GLD': base.copy(),
        'DBC': base.copy(),
    }
    last_date = tlt.index[-1]
    all_dates = sorted(tlt.index)

    # Pre-seed state with TLT held
    state = BacktestState(
        cash=50_000.0,
        positions={
            'TLT': {
                'symbol': 'TLT', 'entry_price': 100.0, 'shares': 100,
                'entry_date': tlt.index[0], 'entry_idx': 0, 'days_held': 200,
                'sub_strategy': 'trend', 'sector': 'Catalyst',
                'entry_vol': 0.0, 'entry_daily_vol': 0.0, 'high_price': 110.0,
            },
        },
        peak_value=100_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    new_state, trades, _ = apply_catalyst_rebalance(
        state, last_date, len(all_dates) - 1, assets,
        catalyst_minimal_config, 'same_close', all_dates,
    )
    assert 'TLT' not in new_state.positions
    assert any(t['exit_reason'] == 'CATALYST_TREND_OFF' and t['symbol'] == 'TLT'
               for t in trades)


def test_apply_rebalance_no_downsize_when_target_smaller(
    four_assets_uptrend, catalyst_minimal_config
):
    """Existing position with current_shares > target_shares should NOT be sold down."""
    last_date = four_assets_uptrend['TLT'].index[-1]
    # Pre-seed with a giant TLT position (way more shares than equal-weight target)
    state = BacktestState(
        cash=10_000.0,
        positions={
            'TLT': {
                'symbol': 'TLT', 'entry_price': 50.0, 'shares': 9999,
                'entry_date': four_assets_uptrend['TLT'].index[0],
                'entry_idx': 0, 'days_held': 200,
                'sub_strategy': 'trend', 'sector': 'Catalyst',
                'entry_vol': 0.0, 'entry_daily_vol': 0.0, 'high_price': 100.0,
            },
        },
        peak_value=1_000_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    all_dates = sorted(four_assets_uptrend['TLT'].index)
    new_state, trades, _ = apply_catalyst_rebalance(
        state, last_date, len(all_dates) - 1, four_assets_uptrend,
        catalyst_minimal_config, 'same_close', all_dates,
    )
    # TLT still held with at least the original shares
    assert 'TLT' in new_state.positions
    assert new_state.positions['TLT']['shares'] >= 9999
    # No CATALYST_TREND_OFF exit for TLT
    assert not any(
        t['symbol'] == 'TLT' and t['exit_reason'] == 'CATALYST_TREND_OFF'
        for t in trades
    )


def test_run_backtest_smoke(four_assets_uptrend, cash_yield_zero,
                             catalyst_minimal_config):
    start = four_assets_uptrend['TLT'].index[210]
    end = four_assets_uptrend['TLT'].index[-1]
    result = run_catalyst_backtest(
        catalyst_minimal_config, four_assets_uptrend, cash_yield_zero,
        start, end, execution_mode='same_close',
    )
    assert not result.daily_values.empty
    assert 'rebalance_today' in result.daily_values.columns
    assert (result.daily_values['n_positions'] >= 0).all()
    assert (result.daily_values['n_positions'] <= 4).all()
    # Should have synthetic-end exits (4 positions held at end)
    assert len(result.trades) >= 4
    end_exits = result.trades[result.trades['exit_reason'] == 'CATALYST_BACKTEST_END']
    assert len(end_exits) == 4
