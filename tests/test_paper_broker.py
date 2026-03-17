import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from omnicapital_broker import Order, PaperBroker


class StaticPriceFeed:
    def __init__(self, prices=None):
        self.prices = dict(prices or {})

    def get_price(self, symbol):
        return self.prices.get(symbol)

    def set_price(self, symbol, price):
        self.prices[symbol] = price


class DivergentFillPaperBroker(PaperBroker):
    def __init__(self, fill_price, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._fill_price = fill_price

    def _get_fill_price(self, symbol, action):
        return self._fill_price


def make_broker(initial_cash=10_000, commission_per_share=0.0, prices=None):
    broker = PaperBroker(
        initial_cash=initial_cash,
        commission_per_share=commission_per_share,
        fill_delay=0,
    )
    feed = StaticPriceFeed(prices or {'AAPL': 100.0, 'MSFT': 200.0, 'TSLA': 300.0})
    broker.set_price_feed(feed)
    broker.connect()
    return broker, feed


def test_initializes_with_starting_cash_and_empty_state():
    broker = PaperBroker(initial_cash=12_345, commission_per_share=0.0, fill_delay=0)

    assert broker.cash == 12_345
    assert broker.initial_cash == 12_345
    assert broker.positions == {}
    assert broker.orders == {}
    assert broker.order_history == []
    assert broker.is_connected() is False


def test_connect_and_disconnect_toggle_connection_state():
    broker = PaperBroker(fill_delay=0)

    assert broker.connect() is True
    assert broker.is_connected() is True

    broker.disconnect()

    assert broker.is_connected() is False


def test_submit_order_requires_connection():
    broker = PaperBroker(fill_delay=0)
    broker.set_price_feed(StaticPriceFeed({'AAPL': 100.0}))

    with pytest.raises(ConnectionError):
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))


def test_buy_order_reduces_cash_and_creates_position():
    broker, _ = make_broker(initial_cash=5_000)

    result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))

    assert result.status == 'FILLED'
    assert result.filled_price == 100.0
    assert broker.cash == 4_000
    assert broker.positions['AAPL'].shares == 10
    assert broker.positions['AAPL'].avg_cost == 100.0


def test_buy_order_records_commission():
    broker, _ = make_broker(initial_cash=5_000, commission_per_share=0.01)

    result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))

    assert result.commission == pytest.approx(0.1)
    assert broker.cash == pytest.approx(3_999.9)


def test_sell_order_increases_cash_and_removes_position():
    broker, feed = make_broker(initial_cash=5_000)
    broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
    feed.set_price('AAPL', 120.0)

    result = broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=10))

    assert result.status == 'FILLED'
    assert result.filled_price == 120.0
    assert broker.cash == 5_200
    assert 'AAPL' not in broker.positions


def test_multiple_buys_average_cost_across_prices():
    broker, feed = make_broker(initial_cash=5_000)
    broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
    feed.set_price('AAPL', 120.0)

    broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=5))

    assert broker.positions['AAPL'].shares == 15
    assert broker.positions['AAPL'].avg_cost == pytest.approx((10 * 100 + 5 * 120) / 15)


def test_sell_more_than_held_returns_error_without_mutation():
    broker, _ = make_broker(initial_cash=5_000)
    broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=5))
    cash_before = broker.cash

    result = broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=6))

    assert result.status == 'ERROR'
    assert broker.cash == cash_before
    assert broker.positions['AAPL'].shares == 5


def test_sell_without_position_returns_error():
    broker, _ = make_broker(initial_cash=5_000)

    result = broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=1))

    assert result.status == 'ERROR'
    assert broker.positions == {}


def test_buy_rejects_when_cash_would_go_negative():
    broker, _ = make_broker(initial_cash=500)
    cash_before = broker.cash

    result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=6))

    assert result.status == 'ERROR'
    assert broker.cash == cash_before
    assert broker.positions == {}


def test_partial_sell_leaves_remaining_shares_and_realized_pnl():
    broker, feed = make_broker(initial_cash=5_000)
    broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
    feed.set_price('AAPL', 115.0)

    result = broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=4))
    position = broker.positions['AAPL']

    assert result.status == 'FILLED'
    assert position.shares == 6
    assert position.avg_cost == 100.0
    assert position.realized_pnl == pytest.approx(60.0)
    assert broker.cash == 4_460


def test_missing_price_returns_error():
    broker, feed = make_broker(initial_cash=5_000)
    feed.prices.clear()

    result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))

    assert result.status == 'ERROR'
    assert broker.positions == {}


def test_circuit_breaker_rejects_fill_far_from_reference():
    broker = DivergentFillPaperBroker(
        fill_price=80.0,
        initial_cash=5_000,
        commission_per_share=0.0,
        fill_delay=0,
        max_fill_deviation=0.02,
    )
    broker.set_price_feed(StaticPriceFeed({'AAPL': 100.0}))
    broker.connect()

    result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))

    assert result.status == 'ERROR'
    assert broker.cash == 5_000
    assert broker.positions == {}


def test_get_positions_updates_market_data_from_feed():
    broker, feed = make_broker(initial_cash=5_000)
    broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
    feed.set_price('AAPL', 125.0)

    positions = broker.get_positions()

    assert positions['AAPL'].market_price == 125.0
    assert positions['AAPL'].market_value == 1_250.0
    assert positions['AAPL'].unrealized_pnl == 250.0
    assert positions['AAPL'].high_price == 125.0


def test_get_portfolio_returns_empty_cash_only_state():
    broker, _ = make_broker(initial_cash=7_500)

    portfolio = broker.get_portfolio()

    assert portfolio.cash == 7_500
    assert portfolio.positions == {}
    assert portfolio.total_value == 7_500
    assert portfolio.buying_power == 7_500


def test_get_portfolio_uses_live_market_value_and_no_margin():
    broker, feed = make_broker(initial_cash=5_000)
    broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
    feed.set_price('AAPL', 130.0)

    portfolio = broker.get_portfolio()

    assert portfolio.cash == 4_000
    assert portfolio.total_value == 5_300
    assert portfolio.buying_power == 4_000


def test_order_fill_uses_current_price_feed_value():
    broker, feed = make_broker(initial_cash=5_000)
    feed.set_price('AAPL', 123.45)

    result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=2))

    assert result.filled_price == pytest.approx(123.45)
    assert broker.positions['AAPL'].avg_cost == pytest.approx(123.45)


def test_position_survives_multi_operation_sequence():
    broker, feed = make_broker(initial_cash=5_000)
    broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
    feed.set_price('AAPL', 110.0)
    broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
    feed.set_price('AAPL', 130.0)
    broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=8))

    portfolio = broker.get_portfolio()
    position = broker.positions['AAPL']

    assert position.shares == 12
    assert position.avg_cost == pytest.approx(105.0)
    assert broker.cash == 3_940
    assert portfolio.total_value == 5_500


def test_get_order_status_returns_recorded_order():
    broker, _ = make_broker(initial_cash=5_000)
    order = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))

    stored = broker.get_order_status(order.order_id)

    assert stored is order
    assert broker.get_order_status('missing-order') is None


def test_cancel_order_returns_false_for_filled_and_unknown_orders():
    broker, _ = make_broker(initial_cash=5_000)
    order = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))

    assert broker.cancel_order(order.order_id) is False
    assert broker.cancel_order('missing-order') is False


def test_order_history_tracks_each_fill_in_sequence():
    broker, feed = make_broker(initial_cash=5_000)
    broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))
    feed.set_price('AAPL', 110.0)
    broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=1))

    assert len(broker.order_history) == 2
    assert [order.action for order in broker.order_history] == ['BUY', 'SELL']


def test_check_stale_orders_cancels_old_submitted_orders():
    broker, _ = make_broker(initial_cash=5_000)
    order = Order(symbol='AAPL', action='BUY', quantity=1)
    order.order_id = 'STALE_1'
    order.status = 'SUBMITTED'
    order.submitted_at = datetime.now() - timedelta(seconds=400)
    broker.orders['STALE_1'] = order

    stale = broker.check_stale_orders(max_age=300)

    assert len(stale) == 1
    assert stale[0].symbol == 'AAPL'
    assert stale[0].status == 'CANCELLED'


def test_check_stale_orders_ignores_recent_orders():
    broker, _ = make_broker(initial_cash=5_000)
    order = Order(symbol='AAPL', action='BUY', quantity=1)
    order.order_id = 'FRESH_1'
    order.status = 'SUBMITTED'
    order.submitted_at = datetime.now() - timedelta(seconds=10)
    broker.orders['FRESH_1'] = order

    stale = broker.check_stale_orders(max_age=300)

    assert len(stale) == 0
    assert order.status == 'SUBMITTED'


# --- Fill price validation tests ---


def test_fill_price_within_2pct_of_market_accepted():
    """Fill price within 2% of reference → order fills successfully."""
    broker = DivergentFillPaperBroker(
        fill_price=101.5,  # 1.5% above reference of 100
        initial_cash=10_000,
        commission_per_share=0.0,
        fill_delay=0,
        max_fill_deviation=0.02,
    )
    broker.set_price_feed(StaticPriceFeed({'AAPL': 100.0}))
    broker.connect()

    result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))

    assert result.status == 'FILLED'
    assert result.filled_price == pytest.approx(101.5)


def test_fill_price_5pct_from_market_rejected():
    """Fill price 5% away from reference → rejected by circuit breaker."""
    broker = DivergentFillPaperBroker(
        fill_price=105.0,  # 5% above reference of 100
        initial_cash=10_000,
        commission_per_share=0.0,
        fill_delay=0,
        max_fill_deviation=0.02,
    )
    broker.set_price_feed(StaticPriceFeed({'AAPL': 100.0}))
    broker.connect()

    result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))

    assert result.status == 'ERROR'
    assert broker.cash == 10_000
    assert broker.positions == {}


def test_fill_price_zero_rejected():
    """Fill price of 0 → rejected."""
    broker = DivergentFillPaperBroker(
        fill_price=0.0,
        initial_cash=10_000,
        commission_per_share=0.0,
        fill_delay=0,
        max_fill_deviation=0.02,
    )
    broker.set_price_feed(StaticPriceFeed({'AAPL': 100.0}))
    broker.connect()

    result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))

    assert result.status == 'ERROR'
    assert broker.cash == 10_000
    assert broker.positions == {}


def test_fill_price_negative_rejected():
    """Negative fill price → rejected."""
    broker = DivergentFillPaperBroker(
        fill_price=-5.0,
        initial_cash=10_000,
        commission_per_share=0.0,
        fill_delay=0,
        max_fill_deviation=0.02,
    )
    broker.set_price_feed(StaticPriceFeed({'AAPL': 100.0}))
    broker.connect()

    result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))

    assert result.status == 'ERROR'
    assert broker.cash == 10_000
    assert broker.positions == {}
