import pytest
from datetime import date
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
