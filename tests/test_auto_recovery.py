import pytest
import json
import os
from datetime import date, datetime
import pandas as pd
import math
from unittest.mock import patch, MagicMock

# Use a minimal mock of COMPASSLive that only has our methods
@pytest.fixture
def trader():
    from omnicapital_live import COMPASSLive
    with patch.object(COMPASSLive, '__init__', lambda self, *a, **kw: None):
        t = object.__new__(COMPASSLive)
    return t

# _trading_days_between tests:
def test_trading_days_same_day(trader):
    assert trader._trading_days_between(date(2026, 3, 20), date(2026, 3, 20)) == 0

def test_trading_days_one_weekday(trader):
    assert trader._trading_days_between(date(2026, 3, 19), date(2026, 3, 20)) == 1

def test_trading_days_over_weekend(trader):
    # Fri Mar 20 -> Mon Mar 23 = 1 trading day
    assert trader._trading_days_between(date(2026, 3, 20), date(2026, 3, 23)) == 1

def test_trading_days_full_week(trader):
    # Mon Mar 16 -> Fri Mar 20 = 4
    assert trader._trading_days_between(date(2026, 3, 16), date(2026, 3, 20)) == 4

def test_trading_days_two_weeks(trader):
    # Fri Mar 6 -> Fri Mar 20 = 10
    assert trader._trading_days_between(date(2026, 3, 6), date(2026, 3, 20)) == 10

# _recovery_price_dict tests:
def test_recovery_price_dict_multiindex(trader):
    arrays = [['Close', 'Close'], ['AAPL', 'MSFT']]
    cols = pd.MultiIndex.from_arrays(arrays)
    data = pd.DataFrame([[150.0, 300.0]], columns=cols)
    result = trader._recovery_price_dict(data, ['AAPL', 'MSFT'])
    assert result == {'AAPL': 150.0, 'MSFT': 300.0}

def test_recovery_price_dict_skips_nan(trader):
    arrays = [['Close', 'Close'], ['AAPL', 'MSFT']]
    cols = pd.MultiIndex.from_arrays(arrays)
    data = pd.DataFrame([[150.0, float('nan')]], columns=cols)
    result = trader._recovery_price_dict(data, ['AAPL', 'MSFT'])
    assert result == {'AAPL': 150.0}

def test_recovery_price_dict_skips_missing(trader):
    arrays = [['Close'], ['AAPL']]
    cols = pd.MultiIndex.from_arrays(arrays)
    data = pd.DataFrame([[150.0]], columns=cols)
    result = trader._recovery_price_dict(data, ['AAPL', 'GOOG'])
    assert result == {'AAPL': 150.0}


# _recovery_gap_baseline tests (Task 4):

def test_recovery_gap_baseline_set_on_load(tmp_path):
    from omnicapital_live import COMPASSLive

    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    state = {
        'version': '8.4', 'cash': 50000, 'peak_value': 100000,
        'portfolio_value': 50000, 'crash_cooldown': 0,
        'current_regime_score': 0.5, 'trading_day_counter': 10,
        'last_trading_date': '2026-03-15',
        'positions': {}, 'position_meta': {},
        'portfolio_values_history': [100000, 50000],
    }
    with open(state_dir / 'compass_state_latest.json', 'w') as f:
        json.dump(state, f)

    with patch.object(COMPASSLive, '__init__', lambda self, *a, **kw: None):
        t = object.__new__(COMPASSLive)

    t._recovery_gap_baseline = None

    # Patch _try_load_json to return our state, and stub out the rest of load_state
    # We only need to verify that _recovery_gap_baseline is set from raw state
    # before validators run. We do this by having _validate_state_before_write
    # capture the baseline at the point it's called.
    captured = {}

    original_validate = COMPASSLive._validate_state_before_write

    def spy_validate(self_inner, st):
        captured['baseline_at_validate_time'] = self_inner._recovery_gap_baseline
        return []

    with patch.object(COMPASSLive, '_validate_state_before_write', spy_validate), \
         patch.object(COMPASSLive, '_validate_state', return_value=(state, [])), \
         patch.object(COMPASSLive, '_validate_state_schema', return_value=[]), \
         patch.object(COMPASSLive, '_validate_position_meta', return_value={}), \
         patch.object(COMPASSLive, '_ensure_active_cycle'), \
         patch.object(COMPASSLive, '_cleanup_old_corrupted_backups'):
        t.config = {'PAPER_INITIAL_CASH': 100000}
        t.broker = MagicMock()
        t.broker.positions = {}
        t.broker.cash = 50000
        t.position_meta = {}
        t.current_universe = []
        t.universe_year = None
        t._universe_source = ''
        t._daily_open_done = False
        t._preclose_entries_done = False
        t._hydra_available = False
        t.rattle_positions = []
        t._state_positions_snapshot = {}
        t._state_cash_snapshot = 50000
        t._last_persisted_cycles_completed = None
        t._last_persisted_trading_day_counter = None
        t._cycles_completed = 0
        t._pre_rotation_positions_data = {}
        t._pre_rotation_cash = 50000
        t._pre_rotation_value = None

        original_dir = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            t.load_state()
        finally:
            os.chdir(original_dir)

    assert t._recovery_gap_baseline == '2026-03-15'
    assert captured['baseline_at_validate_time'] == '2026-03-15'


def test_recovery_gap_baseline_none_when_missing(tmp_path):
    from omnicapital_live import COMPASSLive

    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    state = {
        'version': '8.4', 'cash': 50000, 'peak_value': 100000,
        'portfolio_value': 50000, 'crash_cooldown': 0,
        'current_regime_score': 0.5, 'trading_day_counter': 10,
        'positions': {}, 'position_meta': {},
        'portfolio_values_history': [100000, 50000],
    }
    with open(state_dir / 'compass_state_latest.json', 'w') as f:
        json.dump(state, f)

    with patch.object(COMPASSLive, '__init__', lambda self, *a, **kw: None):
        t = object.__new__(COMPASSLive)

    t._recovery_gap_baseline = None

    with patch.object(COMPASSLive, '_validate_state_before_write', return_value=[]), \
         patch.object(COMPASSLive, '_validate_state', return_value=(state, [])), \
         patch.object(COMPASSLive, '_validate_state_schema', return_value=[]), \
         patch.object(COMPASSLive, '_validate_position_meta', return_value={}), \
         patch.object(COMPASSLive, '_ensure_active_cycle'), \
         patch.object(COMPASSLive, '_cleanup_old_corrupted_backups'):
        t.config = {'PAPER_INITIAL_CASH': 100000}
        t.broker = MagicMock()
        t.broker.positions = {}
        t.broker.cash = 50000
        t.position_meta = {}
        t.current_universe = []
        t.universe_year = None
        t._universe_source = ''
        t._daily_open_done = False
        t._preclose_entries_done = False
        t._hydra_available = False
        t.rattle_positions = []
        t._state_positions_snapshot = {}
        t._state_cash_snapshot = 50000
        t._last_persisted_cycles_completed = None
        t._last_persisted_trading_day_counter = None
        t._cycles_completed = 0
        t._pre_rotation_positions_data = {}
        t._pre_rotation_cash = 50000
        t._pre_rotation_value = None

        original_dir = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            t.load_state()
        finally:
            os.chdir(original_dir)

    assert t._recovery_gap_baseline is None


# _recovery_mode in execute_preclose_entries tests (Task 5):

def test_execute_preclose_recovery_skips_strategies(trader):
    trader._preclose_entries_done = False
    trader._hydra_available = True
    trader._recovery_mode = False
    trader._recovery_spy_close = None
    trader.trades_today = []
    trader.broker = MagicMock()
    trader.broker.positions = {'AAPL': MagicMock()}
    trader.get_et_now = MagicMock(return_value=datetime(2026, 3, 20, 15, 35))
    trader.check_position_exits = MagicMock()
    trader._liquidate_efa_for_capital = MagicMock()
    trader.open_new_positions = MagicMock()
    trader._open_rattlesnake_positions = MagicMock()
    trader._manage_catalyst_positions = MagicMock()
    trader._manage_efa_position = MagicMock()
    trader.save_state = MagicMock()

    prices = {'AAPL': 150.0}
    trader.execute_preclose_entries(prices, _recovery_mode=True)

    trader._open_rattlesnake_positions.assert_not_called()
    trader._manage_catalyst_positions.assert_not_called()
    trader._manage_efa_position.assert_not_called()
    trader._liquidate_efa_for_capital.assert_not_called()
    # Core COMPASS logic still runs
    trader.check_position_exits.assert_called_once()
    trader.open_new_positions.assert_called_once()


def test_execute_preclose_normal_calls_strategies(trader):
    trader._preclose_entries_done = False
    trader._hydra_available = True
    trader._recovery_mode = False
    trader._recovery_spy_close = None
    trader.trades_today = []
    trader.broker = MagicMock()
    trader.broker.positions = {'AAPL': MagicMock()}
    trader.get_et_now = MagicMock(return_value=datetime(2026, 3, 20, 15, 35))
    trader.check_position_exits = MagicMock()
    trader._liquidate_efa_for_capital = MagicMock()
    trader.open_new_positions = MagicMock()
    trader._open_rattlesnake_positions = MagicMock()
    trader._manage_catalyst_positions = MagicMock()
    trader._manage_efa_position = MagicMock()
    trader.save_state = MagicMock()

    prices = {'AAPL': 150.0}
    trader.execute_preclose_entries(prices, _recovery_mode=False)

    trader._open_rattlesnake_positions.assert_called_once()
    trader._manage_efa_position.assert_called_once()


def test_recovery_mode_flag_set_and_cleared_around_cycle_log(trader):
    trader._preclose_entries_done = False
    trader._hydra_available = False
    trader._recovery_mode = False
    trader._recovery_spy_close = None
    trader.broker = MagicMock()
    trader.broker.positions = {'AAPL': MagicMock()}
    trader.get_et_now = MagicMock(return_value=datetime(2026, 3, 20, 15, 35))
    trader.check_position_exits = MagicMock()
    trader.open_new_positions = MagicMock()
    trader.save_state = MagicMock()

    # Simulate rotation: trades_today has both SELL and BUY
    trader.trades_today = [
        {'action': 'SELL', 'symbol': 'MSFT'},
        {'action': 'BUY', 'symbol': 'AAPL'},
    ]

    captured_flag = {}

    def mock_update_cycle_log(prices):
        captured_flag['during'] = trader._recovery_mode

    trader._update_cycle_log = mock_update_cycle_log

    trader.execute_preclose_entries({'AAPL': 150.0}, _recovery_mode=True)

    assert captured_flag['during'] is True
    assert trader._recovery_mode is False  # Cleared in finally


def test_recovery_spy_close_used_in_cycle_log_inner(trader):
    import threading
    trader._recovery_mode = True
    trader._recovery_spy_close = 520.0
    trader._cycle_log_lock = threading.Lock()
    trader._pre_rotation_positions_data = {}
    trader._pre_rotation_cash = 50000
    trader._pre_rotation_value = 50000
    trader._pre_rotation_positions = []
    trader.broker = MagicMock()
    trader.broker.positions = {'AAPL': MagicMock()}
    trader.broker.cash = 50000
    trader.get_et_now = MagicMock(return_value=datetime(2026, 3, 20, 15, 35))
    trader._reconstruct_close_portfolio = MagicMock(return_value=50000)
    trader._get_spy_close = MagicMock(return_value=999.0)  # Should NOT be called
    trader._new_cycle_log_entry = MagicMock(return_value={
        'cycle': 1, 'start_date': '2026-03-20', 'status': 'active',
        'positions': ['AAPL'],
    })
    trader._append_cycle_log_entry = MagicMock(return_value=True)
    trader.notifier = None

    with patch('builtins.open', MagicMock()), \
         patch('os.path.exists', return_value=False), \
         patch('os.makedirs'), \
         patch('tempfile.mkstemp', return_value=(0, 'tmp')), \
         patch('os.fdopen', MagicMock()), \
         patch('os.replace'):
        trader._update_cycle_log({'AAPL': 150.0})

    trader._get_spy_close.assert_not_called()
    # Verify the new_cycle_log_entry was called with our recovery spy_close
    call_args = trader._new_cycle_log_entry.call_args
    assert call_args[0][3] == 520.0  # new_spy_start = spy_close = 520.0


def test_recovery_mode_adds_reconstructed_tag(trader):
    import threading
    trader._recovery_mode = True
    trader._recovery_spy_close = 520.0
    trader._cycle_log_lock = threading.Lock()
    trader._pre_rotation_positions_data = {}
    trader._pre_rotation_cash = 50000
    trader._pre_rotation_value = 50000
    trader._pre_rotation_positions = []
    trader.broker = MagicMock()
    trader.broker.positions = {'AAPL': MagicMock()}
    trader.broker.cash = 50000
    trader.get_et_now = MagicMock(return_value=datetime(2026, 3, 20, 15, 35))
    trader._reconstruct_close_portfolio = MagicMock(return_value=50000)
    trader._get_spy_close = MagicMock(return_value=999.0)
    trader.notifier = None

    created_entry = {
        'cycle': 1, 'start_date': '2026-03-20', 'status': 'active',
        'positions': ['AAPL'],
    }
    trader._new_cycle_log_entry = MagicMock(return_value=created_entry)
    trader._append_cycle_log_entry = MagicMock(return_value=True)

    with patch('builtins.open', MagicMock()), \
         patch('os.path.exists', return_value=False), \
         patch('os.makedirs'), \
         patch('tempfile.mkstemp', return_value=(0, 'tmp')), \
         patch('os.fdopen', MagicMock()), \
         patch('os.replace'):
        trader._update_cycle_log({'AAPL': 150.0})

    assert created_entry['reconstructed'] is True
    assert 'recovery_date' in created_entry
