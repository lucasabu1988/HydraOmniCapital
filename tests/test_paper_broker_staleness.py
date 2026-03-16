import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from omnicapital_broker import Order, PaperBroker


class TimestampedPriceFeed:
    def __init__(self, price, price_timestamp=None):
        self.price = price
        self.price_timestamp = price_timestamp

    def get_price(self, symbol):
        return self.price

    def get_price_timestamp(self, symbol):
        return self.price_timestamp


@pytest.fixture
def broker():
    broker = PaperBroker(initial_cash=100000)
    broker.connect()
    broker.fill_delay = 0
    return broker


def test_submit_order_flags_stale_price_in_result(broker, caplog):
    stale_timestamp = datetime.now() - timedelta(minutes=10)
    broker.set_price_feed(TimestampedPriceFeed(150.0, stale_timestamp))

    with caplog.at_level('WARNING'):
        result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))

    assert result.status == 'FILLED'
    assert result.is_stale_price is True
    assert result.price_timestamp == stale_timestamp
    assert result.price_age_seconds > 300
    assert 'Stale price used for AAPL' in caplog.text


def test_submit_order_keeps_fresh_price_unflagged(broker):
    fresh_timestamp = datetime.now() - timedelta(minutes=2)
    broker.set_price_feed(TimestampedPriceFeed(150.0, fresh_timestamp))

    result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))

    assert result.status == 'FILLED'
    assert result.is_stale_price is False
    assert result.price_timestamp == fresh_timestamp
    assert result.price_age_seconds < 300


def test_submit_order_allows_missing_price_timestamp(broker):
    broker.set_price_feed(TimestampedPriceFeed(150.0, None))

    result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))

    assert result.status == 'FILLED'
    assert result.is_stale_price is False
    assert result.price_timestamp is None
    assert result.price_age_seconds is None
