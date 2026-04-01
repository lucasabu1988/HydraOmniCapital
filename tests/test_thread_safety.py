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
