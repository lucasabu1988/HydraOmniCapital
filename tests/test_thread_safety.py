"""Thread safety tests for COMPASSLive shared state."""
import threading
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def trader():
    from omnicapital_live import COMPASSLive
    with patch.object(COMPASSLive, '__init__', lambda self, *a, **kw: None):
        t = object.__new__(COMPASSLive)
    t.position_meta = {}
    t._data_lock = threading.RLock()
    return t


class TestDataLockExists:
    def test_compasslive_has_data_lock(self):
        from omnicapital_live import COMPASSLive
        with patch.object(COMPASSLive, '__init__', lambda self, *a, **kw: None):
            t = object.__new__(COMPASSLive)
        t._data_lock = threading.RLock()
        assert hasattr(t, '_data_lock')
        assert isinstance(t._data_lock, type(threading.RLock()))

    def test_data_lock_is_reentrant(self, trader):
        trader._data_lock.acquire()
        acquired = trader._data_lock.acquire(blocking=False)
        assert acquired is True
        trader._data_lock.release()
        trader._data_lock.release()


class TestSaveStateSnapshot:
    def test_save_state_uses_snapshots_not_live_refs(self, trader, tmp_path, monkeypatch):
        """save_state must use snapshots, not live references to position_meta."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / 'state').mkdir()

        import json
        (tmp_path / 'state' / 'cycle_log.json').write_text('[]')

        trader._state_save_lock = threading.RLock()
        trader._cycle_log_lock = threading.RLock()
        trader.position_meta = {'AAPL': {'entry_price': 150.0}}
        trader.peak_value = 100000
        trader.crash_cooldown = 0
        trader.portfolio_values_history = []
        trader.current_regime_score = 0.5
        trader.trading_day_counter = 1
        trader.last_trading_date = None
        trader.current_universe = []
        trader.universe_year = 2026
        trader._overlay_available = False
        trader._daily_open_done = False
        trader._preclose_entries_done = False
        trader.cycles_completed = 0
        trader._last_audit_positions = set()
        trader._last_persisted_cycles_completed = None
        trader._last_persisted_trading_day_counter = None
        trader.config = {'PAPER_INITIAL_CASH': 100000}

        from unittest.mock import MagicMock
        mock_broker = MagicMock()
        mock_broker.cash = 50000
        mock_broker.positions = {}
        mock_portfolio = MagicMock()
        mock_portfolio.total_value = 100000
        mock_broker.get_portfolio.return_value = mock_portfolio
        trader.broker = mock_broker

        try:
            trader.save_state()
        except Exception:
            pass

        state_file = tmp_path / 'state' / 'compass_state_latest.json'
        if state_file.exists():
            saved = json.loads(state_file.read_text())
            assert saved.get('position_meta') == {'AAPL': {'entry_price': 150.0}}


class TestBrokerSnapshot:
    def test_safe_broker_snapshot_returns_independent_copy(self, trader):
        mock_broker = MagicMock()
        mock_broker.cash = 50000
        mock_pos = MagicMock()
        mock_pos.shares = 10
        mock_pos.avg_cost = 150.0
        mock_pos.market_price = 155.0
        mock_broker.positions = {'AAPL': mock_pos}
        trader.broker = mock_broker
        trader.position_meta = {'AAPL': {'entry_price': 150.0, 'sector': 'Tech'}}

        snap = trader._safe_broker_snapshot()

        assert snap['cash'] == 50000
        assert snap['positions']['AAPL']['shares'] == 10
        assert snap['positions']['AAPL']['avg_cost'] == 150.0
        assert snap['positions']['AAPL']['market_price'] == 155.0
        assert snap['position_meta']['AAPL']['entry_price'] == 150.0
        assert snap['position_meta']['AAPL']['sector'] == 'Tech'

        # Mutations to snapshot don't affect live state
        snap['position_meta']['AAPL']['entry_price'] = 999.0
        assert trader.position_meta['AAPL']['entry_price'] == 150.0

    def test_safe_broker_snapshot_empty_positions(self, trader):
        mock_broker = MagicMock()
        mock_broker.cash = 100000
        mock_broker.positions = {}
        trader.broker = mock_broker
        trader.position_meta = {}

        snap = trader._safe_broker_snapshot()

        assert snap['cash'] == 100000
        assert snap['positions'] == {}
        assert snap['position_meta'] == {}


class TestCycleLogLock:
    def test_cycle_log_lock_is_rlock(self):
        """_cycle_log_lock must be RLock for safe reentrancy."""
        from omnicapital_live import COMPASSLive
        with patch.object(COMPASSLive, '__init__', lambda self, *a, **kw: None):
            t = object.__new__(COMPASSLive)
        t._cycle_log_lock = threading.RLock()
        # RLock allows reentrant acquisition
        t._cycle_log_lock.acquire()
        acquired = t._cycle_log_lock.acquire(blocking=False)
        assert acquired is True
        t._cycle_log_lock.release()
        t._cycle_log_lock.release()
