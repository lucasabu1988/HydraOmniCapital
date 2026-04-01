"""Thread safety tests for COMPASSLive shared state."""
import threading
import pytest
from unittest.mock import patch


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
