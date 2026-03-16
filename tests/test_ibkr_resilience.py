import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from omnicapital_broker import IBKRBroker, Order, Portfolio, Position


def make_ib_position(symbol='AAPL', shares=10, avg_cost=150.0):
    return SimpleNamespace(
        contract=SimpleNamespace(symbol=symbol),
        position=shares,
        avgCost=avg_cost,
    )


def make_account_summary(cash='95000', buying_power='95000'):
    return [
        SimpleNamespace(tag='AvailableFunds', value=cash),
        SimpleNamespace(tag='BuyingPower', value=buying_power),
    ]


@pytest.fixture
def live_broker(monkeypatch):
    broker = IBKRBroker(mock=False)
    broker.connection = MagicMock()
    broker.connection.verify_paper_trading.return_value = True
    broker.connection.connect.return_value = True
    broker.connection.disconnect.return_value = None
    broker.connection.is_connected.return_value = True
    broker.connection.ib = MagicMock()
    broker.price_feed = MagicMock()
    broker.price_feed.get_price.return_value = 150.0
    monkeypatch.setattr(broker, '_sleep_backoff', lambda seconds: None)
    assert broker.connect() is True
    broker.connection.connect.reset_mock()
    broker.connection.disconnect.reset_mock()
    return broker


def test_connect_sets_connected_state_and_health(monkeypatch):
    broker = IBKRBroker(mock=False)
    broker.connection = MagicMock()
    broker.connection.verify_paper_trading.return_value = True
    broker.connection.connect.return_value = True
    broker.connection.is_connected.return_value = True
    broker.connection.ib = MagicMock()
    monkeypatch.setattr(broker, '_sleep_backoff', lambda seconds: None)

    assert broker.connect() is True

    health = broker.health_check()
    assert health['state'] == 'connected'
    assert health['connected'] is True


def test_disconnect_sets_disconnected_state(live_broker):
    live_broker.disconnect()

    assert live_broker.health_check()['state'] == 'disconnected'


def test_get_positions_recovers_after_connection_error(live_broker):
    live_broker.connection.ib.positions.side_effect = [
        ConnectionError('socket dropped'),
        [make_ib_position('AAPL', 10, 150.0)],
    ]

    positions = live_broker.get_positions()

    assert positions['AAPL'].shares == 10
    assert live_broker.health_check()['state'] == 'connected'
    assert live_broker.connection.connect.call_count == 1


def test_get_positions_enters_degraded_after_repeated_failures(live_broker):
    live_broker.connection.ib.positions.side_effect = ConnectionError('still down')
    live_broker.connection.connect.return_value = False
    live_broker.connection.is_connected.return_value = False

    with pytest.raises(ConnectionError):
        live_broker.get_positions()

    health = live_broker.health_check()
    assert health['state'] == 'degraded'
    assert live_broker.connection.connect.call_count == 3


def test_get_positions_returns_cached_snapshot_when_degraded(live_broker):
    live_broker._cache_positions_snapshot({'AAPL': Position('AAPL', 5, 123.0)})
    live_broker.connection.ib = None
    live_broker.connection.connect.return_value = False
    live_broker.connection.is_connected.return_value = False
    live_broker._set_broker_state('degraded', 'test')

    positions = live_broker.get_positions()

    assert positions['AAPL'].shares == 5
    assert live_broker.health_check()['state'] == 'degraded'


def test_submit_order_blocks_new_orders_in_degraded_mode(live_broker):
    live_broker._set_broker_state('degraded', 'manual')
    order = Order(symbol='AAPL', action='BUY', quantity=10)

    with pytest.raises(RuntimeError, match='degraded mode'):
        live_broker.submit_order(order)


def test_submit_order_live_recovers_after_timeout(live_broker):
    order = Order(symbol='AAPL', action='BUY', quantity=10)

    def fill(_order):
        _order.status = 'FILLED'
        _order.filled_quantity = _order.quantity
        _order.filled_price = 150.0
        _order.commission = 0.35
        return _order

    calls = {'count': 0}

    def flaky_submit(_order):
        calls['count'] += 1
        if calls['count'] == 1:
            raise asyncio.TimeoutError()
        return fill(_order)

    live_broker._submit_live_once = flaky_submit

    result = live_broker.submit_order(order)

    assert result.status == 'FILLED'
    assert result.filled_price == pytest.approx(150.0)
    assert live_broker.connection.connect.call_count == 1


def test_get_portfolio_recovers_after_account_summary_failure(live_broker):
    live_broker.connection.ib.accountSummary.side_effect = [
        ConnectionError('account summary unavailable'),
        make_account_summary(),
    ]
    live_broker.connection.ib.positions.return_value = [make_ib_position('AAPL', 10, 150.0)]

    portfolio = live_broker.get_portfolio()

    assert isinstance(portfolio, Portfolio)
    assert portfolio.cash == pytest.approx(95000.0)
    assert portfolio.total_value == pytest.approx(96500.0)
    assert live_broker.connection.connect.call_count == 1


def test_health_check_records_last_successful_call_and_latency(live_broker):
    live_broker.connection.ib.positions.return_value = [make_ib_position('AAPL', 10, 150.0)]

    live_broker.get_positions()

    health = live_broker.health_check()
    assert health['state'] == 'connected'
    assert health['latency_ms'] is not None
    assert health['last_successful_call_at'] is not None


def test_get_account_info_reports_broker_state(live_broker):
    live_broker.connection.ib.accountSummary.return_value = make_account_summary()
    live_broker.connection.ib.positions.return_value = [make_ib_position('AAPL', 10, 150.0)]

    info = live_broker.get_account_info()

    assert info['connection_state'] == 'CONNECTED'
    assert info['broker_type'] == 'IBKR'
    assert info['mock_mode'] is False


def test_cancel_order_recovers_after_connection_error(live_broker):
    order = Order(symbol='AAPL', action='BUY', quantity=10, order_id='123', status='SUBMITTED')
    live_broker.orders['123'] = order
    trade = SimpleNamespace(order=SimpleNamespace(orderId='123'))
    live_broker.connection.ib.trades.side_effect = [
        ConnectionError('trades unavailable'),
        [trade],
    ]

    result = live_broker.cancel_order('123')

    assert result is True
    assert live_broker.connection.ib.cancelOrder.called
    assert live_broker.connection.connect.call_count == 1


def test_health_check_preserves_last_error_when_degraded(live_broker):
    live_broker.connection.ib.positions.side_effect = ConnectionError('fatal disconnect')
    live_broker.connection.connect.return_value = False

    with pytest.raises(ConnectionError):
        live_broker.get_positions()

    health = live_broker.health_check()
    assert health['state'] == 'degraded'
    assert 'fatal disconnect' in health['last_error']
