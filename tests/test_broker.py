import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from omnicapital_broker import MAX_FILL_DEVIATION, Order, PaperBroker, Position, Portfolio


class StaticPriceFeed:
    def __init__(self, prices=None):
        self.prices = dict(prices or {})

    def get_price(self, symbol):
        return self.prices.get(symbol)

    def set_price(self, symbol, price):
        self.prices[symbol] = price


def make_broker(initial_cash=100_000, commission_per_share=0.0, prices=None):
    broker = PaperBroker(
        initial_cash=initial_cash,
        commission_per_share=commission_per_share,
        fill_delay=0,
    )
    feed = StaticPriceFeed(prices or {'AAPL': 150.0, 'MSFT': 300.0, 'GOOGL': 140.0, 'TSLA': 250.0})
    broker.set_price_feed(feed)
    broker.connect()
    return broker, feed


# =====================================================================
# 1. PaperBroker initialization
# =====================================================================

class TestPaperBrokerInit:

    def test_default_cash_100k(self):
        broker = PaperBroker(fill_delay=0)
        assert broker.cash == 100_000
        assert broker.initial_cash == 100_000

    def test_custom_initial_cash(self):
        broker = PaperBroker(initial_cash=50_000, fill_delay=0)
        assert broker.cash == 50_000

    def test_empty_positions_on_init(self):
        broker = PaperBroker(fill_delay=0)
        assert broker.positions == {}

    def test_empty_orders_on_init(self):
        broker = PaperBroker(fill_delay=0)
        assert broker.orders == {}
        assert broker.order_history == []

    def test_not_connected_on_init(self):
        broker = PaperBroker(fill_delay=0)
        assert broker.is_connected() is False

    def test_connect_returns_true(self):
        broker = PaperBroker(fill_delay=0)
        assert broker.connect() is True
        assert broker.is_connected() is True

    def test_disconnect(self):
        broker = PaperBroker(fill_delay=0)
        broker.connect()
        broker.disconnect()
        assert broker.is_connected() is False

    def test_default_commission(self):
        broker = PaperBroker(fill_delay=0)
        assert broker.commission_per_share == 0.001

    def test_default_max_fill_deviation(self):
        broker = PaperBroker(fill_delay=0)
        assert broker.max_fill_deviation == MAX_FILL_DEVIATION

    def test_price_feed_none_on_init(self):
        broker = PaperBroker(fill_delay=0)
        assert broker.price_feed is None


# =====================================================================
# 2. Buy order execution
# =====================================================================

class TestBuyOrderExecution:

    def test_buy_reduces_cash(self):
        broker, _ = make_broker(initial_cash=100_000)
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        assert broker.cash == pytest.approx(100_000 - 10 * 150.0)

    def test_buy_creates_position(self):
        broker, _ = make_broker()
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=5))
        assert 'AAPL' in broker.positions
        assert broker.positions['AAPL'].shares == 5
        assert broker.positions['AAPL'].avg_cost == 150.0

    def test_buy_order_status_filled(self):
        broker, _ = make_broker()
        result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))
        assert result.status == 'FILLED'
        assert result.filled_quantity == 1
        assert result.filled_price == 150.0

    def test_buy_order_gets_id(self):
        broker, _ = make_broker()
        result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))
        assert result.order_id is not None
        assert result.order_id.startswith('PAPER_')

    def test_buy_with_commission(self):
        broker, _ = make_broker(commission_per_share=0.01)
        result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=100))
        assert result.commission == pytest.approx(1.0)
        # cash = 100000 - (100 * 150 + 1.0) = 84999.0
        assert broker.cash == pytest.approx(84_999.0)

    def test_buy_stored_in_order_history(self):
        broker, _ = make_broker()
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))
        assert len(broker.order_history) == 1
        assert broker.order_history[0].action == 'BUY'


# =====================================================================
# 3. Sell order execution
# =====================================================================

class TestSellOrderExecution:

    def test_sell_increases_cash(self):
        broker, feed = make_broker(initial_cash=100_000)
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        cash_after_buy = broker.cash
        feed.set_price('AAPL', 160.0)
        broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=10))
        assert broker.cash > cash_after_buy

    def test_sell_all_removes_position(self):
        broker, _ = make_broker()
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=10))
        assert 'AAPL' not in broker.positions

    def test_partial_sell_leaves_remainder(self):
        broker, _ = make_broker()
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=3))
        assert broker.positions['AAPL'].shares == 7

    def test_sell_with_profit_cash_correct(self):
        broker, feed = make_broker(initial_cash=100_000)
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        # bought at 150, sell at 200
        feed.set_price('AAPL', 200.0)
        broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=10))
        # cash = (100000 - 1500) + (10 * 200) = 100500
        assert broker.cash == pytest.approx(100_500.0)

    def test_sell_with_loss(self):
        broker, feed = make_broker(initial_cash=100_000)
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        feed.set_price('AAPL', 100.0)
        broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=10))
        # cash = (100000 - 1500) + (10 * 100) = 99500
        assert broker.cash == pytest.approx(99_500.0)

    def test_sell_with_commission(self):
        broker, _ = make_broker(initial_cash=100_000, commission_per_share=0.01)
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        result = broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=10))
        assert result.commission == pytest.approx(0.1)


# =====================================================================
# 4. Fill price validation
# =====================================================================

class TestFillPriceValidation:

    def test_positive_fill_price_accepted(self):
        broker, _ = make_broker()
        assert broker.validate_fill_price('AAPL', 150.0, 150.0) is True

    def test_fill_price_zero_rejected(self):
        broker, _ = make_broker()
        assert broker.validate_fill_price('AAPL', 0.0, 150.0) is False

    def test_fill_price_negative_rejected(self):
        broker, _ = make_broker()
        assert broker.validate_fill_price('AAPL', -10.0, 150.0) is False

    def test_reference_price_zero_rejected(self):
        broker, _ = make_broker()
        assert broker.validate_fill_price('AAPL', 150.0, 0.0) is False

    def test_fill_within_deviation_accepted(self):
        broker, _ = make_broker()
        # 1% deviation, within default 2%
        assert broker.validate_fill_price('AAPL', 151.5, 150.0) is True

    def test_fill_beyond_deviation_rejected(self):
        broker, _ = make_broker()
        # 5% deviation, beyond default 2%
        assert broker.validate_fill_price('AAPL', 157.5, 150.0) is False

    def test_custom_max_deviation(self):
        broker, _ = make_broker()
        # 3% deviation, within custom 5%
        assert broker.validate_fill_price('AAPL', 154.5, 150.0, max_deviation=0.05) is True
        # 3% deviation, beyond custom 1%
        assert broker.validate_fill_price('AAPL', 154.5, 150.0, max_deviation=0.01) is False


# =====================================================================
# 5. Insufficient funds rejection
# =====================================================================

class TestInsufficientFunds:

    def test_buy_exceeding_cash_rejected(self):
        broker, _ = make_broker(initial_cash=1_000)
        result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        # 10 * 150 = 1500 > 1000
        assert result.status == 'ERROR'

    def test_cash_unchanged_after_rejection(self):
        broker, _ = make_broker(initial_cash=1_000)
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        assert broker.cash == 1_000

    def test_no_position_created_after_rejection(self):
        broker, _ = make_broker(initial_cash=1_000)
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        assert broker.positions == {}

    def test_exact_cash_buy_succeeds(self):
        # 10 shares * 150 = 1500 exactly
        broker, _ = make_broker(initial_cash=1_500)
        result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        assert result.status == 'FILLED'
        assert broker.cash == pytest.approx(0.0)


# =====================================================================
# 6. Position sizing — can't sell more than owned
# =====================================================================

class TestPositionSizing:

    def test_sell_more_than_owned_rejected(self):
        broker, _ = make_broker()
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=5))
        result = broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=10))
        assert result.status == 'ERROR'

    def test_sell_nonexistent_position_rejected(self):
        broker, _ = make_broker()
        result = broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=1))
        assert result.status == 'ERROR'

    def test_position_unchanged_after_failed_sell(self):
        broker, _ = make_broker()
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=5))
        broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=10))
        assert broker.positions['AAPL'].shares == 5


# =====================================================================
# 7. Multiple buys of same symbol — position averaging
# =====================================================================

class TestPositionAveraging:

    def test_two_buys_average_cost(self):
        broker, feed = make_broker()
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        feed.set_price('AAPL', 200.0)
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        pos = broker.positions['AAPL']
        assert pos.shares == 20
        assert pos.avg_cost == pytest.approx((10 * 150 + 10 * 200) / 20)

    def test_three_buys_average_cost(self):
        broker, feed = make_broker()
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=5))
        feed.set_price('AAPL', 160.0)
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=5))
        feed.set_price('AAPL', 170.0)
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        pos = broker.positions['AAPL']
        assert pos.shares == 20
        expected_avg = (5 * 150 + 5 * 160 + 10 * 170) / 20
        assert pos.avg_cost == pytest.approx(expected_avg)

    def test_avg_cost_preserved_after_partial_sell(self):
        broker, _ = make_broker()
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=5))
        assert broker.positions['AAPL'].avg_cost == 150.0


# =====================================================================
# 8. Account balance calculations (total portfolio value)
# =====================================================================

class TestAccountBalance:

    def test_portfolio_value_cash_only(self):
        broker, _ = make_broker(initial_cash=100_000)
        portfolio = broker.get_portfolio()
        assert portfolio.total_value == 100_000
        assert portfolio.cash == 100_000
        assert portfolio.buying_power == 100_000

    def test_portfolio_value_with_positions(self):
        broker, feed = make_broker(initial_cash=100_000)
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        feed.set_price('AAPL', 200.0)
        portfolio = broker.get_portfolio()
        # cash = 100000 - 1500 = 98500, positions = 10 * 200 = 2000
        assert portfolio.total_value == pytest.approx(100_500.0)
        assert portfolio.cash == pytest.approx(98_500.0)

    def test_get_account_info_keys(self):
        broker, _ = make_broker()
        info = broker.get_account_info()
        expected_keys = {'cash', 'total_value', 'buying_power', 'num_positions', 'unrealized_pnl', 'realized_pnl'}
        assert set(info.keys()) == expected_keys

    def test_account_info_no_positions(self):
        broker, _ = make_broker(initial_cash=100_000)
        info = broker.get_account_info()
        assert info['cash'] == 100_000
        assert info['total_value'] == 100_000
        assert info['num_positions'] == 0
        assert info['unrealized_pnl'] == 0
        assert info['realized_pnl'] == 0

    def test_account_info_with_positions(self):
        broker, feed = make_broker(initial_cash=100_000)
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        feed.set_price('AAPL', 160.0)
        info = broker.get_account_info()
        assert info['num_positions'] == 1
        assert info['unrealized_pnl'] == pytest.approx(100.0)

    def test_buying_power_equals_cash(self):
        broker, _ = make_broker(initial_cash=100_000)
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        portfolio = broker.get_portfolio()
        # LEVERAGE_MAX = 1.0 means buying power = cash
        assert portfolio.buying_power == portfolio.cash

    def test_portfolio_multiple_positions(self):
        broker, feed = make_broker(initial_cash=100_000)
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        broker.submit_order(Order(symbol='MSFT', action='BUY', quantity=5))
        feed.set_price('AAPL', 160.0)
        feed.set_price('MSFT', 320.0)
        portfolio = broker.get_portfolio()
        # cash = 100000 - 1500 - 1500 = 97000
        # positions = 10*160 + 5*320 = 1600 + 1600 = 3200
        assert portfolio.total_value == pytest.approx(100_200.0)
        assert portfolio.cash == pytest.approx(97_000.0)


# =====================================================================
# 9. Order with zero shares — rejection (via missing price)
# =====================================================================

class TestZeroQuantityOrder:

    def test_buy_zero_shares_fills_at_zero_cost(self):
        # PaperBroker doesn't explicitly reject quantity=0; it fills with 0 cost
        broker, _ = make_broker()
        result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=0))
        assert result.status == 'FILLED'
        assert broker.cash == 100_000  # no cost


# =====================================================================
# 10. Position P&L tracking
# =====================================================================

class TestPositionPnL:

    def test_unrealized_pnl_gain(self):
        broker, feed = make_broker()
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        feed.set_price('AAPL', 170.0)
        positions = broker.get_positions()
        assert positions['AAPL'].unrealized_pnl == pytest.approx(200.0)

    def test_unrealized_pnl_loss(self):
        broker, feed = make_broker()
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        feed.set_price('AAPL', 130.0)
        positions = broker.get_positions()
        assert positions['AAPL'].unrealized_pnl == pytest.approx(-200.0)

    def test_realized_pnl_on_sell(self):
        broker, feed = make_broker()
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        feed.set_price('AAPL', 170.0)
        broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=5))
        pos = broker.positions['AAPL']
        # realized = (170 - 150) * 5 = 100
        assert pos.realized_pnl == pytest.approx(100.0)

    def test_realized_pnl_accumulates(self):
        broker, feed = make_broker()
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        feed.set_price('AAPL', 170.0)
        broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=3))
        broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=3))
        pos = broker.positions['AAPL']
        # realized = (170-150)*3 + (170-150)*3 = 60 + 60 = 120
        assert pos.realized_pnl == pytest.approx(120.0)

    def test_realized_pnl_in_account_info(self):
        broker, feed = make_broker()
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        feed.set_price('AAPL', 170.0)
        broker.submit_order(Order(symbol='AAPL', action='SELL', quantity=10))
        info = broker.get_account_info()
        assert info['realized_pnl'] == 0  # position removed, so no realized_pnl tracked

    def test_market_value_updates(self):
        broker, feed = make_broker()
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        feed.set_price('AAPL', 200.0)
        positions = broker.get_positions()
        assert positions['AAPL'].market_value == pytest.approx(2000.0)
        assert positions['AAPL'].market_price == 200.0

    def test_high_price_tracking(self):
        broker, feed = make_broker()
        broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=10))
        feed.set_price('AAPL', 200.0)
        broker.get_positions()  # triggers update
        feed.set_price('AAPL', 180.0)
        broker.get_positions()  # triggers update
        pos = broker.positions['AAPL']
        # high_price should be 200 (watermark)
        assert pos.high_price == 200.0


# =====================================================================
# 11. Market hours / connection checks
# =====================================================================

class TestMarketHoursAndConnection:

    def test_submit_order_requires_connection(self):
        broker = PaperBroker(fill_delay=0)
        broker.set_price_feed(StaticPriceFeed({'AAPL': 150.0}))
        with pytest.raises(ConnectionError):
            broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))

    def test_reconnect_allows_trading(self):
        broker, _ = make_broker()
        broker.disconnect()
        broker.connect()
        result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))
        assert result.status == 'FILLED'

    def test_no_price_feed_returns_error(self):
        broker = PaperBroker(initial_cash=100_000, fill_delay=0)
        broker.connect()
        result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))
        assert result.status == 'ERROR'

    def test_missing_symbol_in_feed_returns_error(self):
        broker, _ = make_broker()
        result = broker.submit_order(Order(symbol='UNKNOWN', action='BUY', quantity=1))
        assert result.status == 'ERROR'


# =====================================================================
# Additional: stale orders, order status, cancel
# =====================================================================

class TestOrderManagement:

    def test_get_order_status(self):
        broker, _ = make_broker()
        result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))
        stored = broker.get_order_status(result.order_id)
        assert stored is result

    def test_get_order_status_missing(self):
        broker, _ = make_broker()
        assert broker.get_order_status('NONEXISTENT') is None

    def test_cancel_filled_order_returns_false(self):
        broker, _ = make_broker()
        result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))
        assert broker.cancel_order(result.order_id) is False

    def test_cancel_unknown_order_returns_false(self):
        broker, _ = make_broker()
        assert broker.cancel_order('NONEXISTENT') is False

    def test_stale_order_cancelled(self):
        broker, _ = make_broker()
        order = Order(symbol='AAPL', action='BUY', quantity=1)
        order.order_id = 'STALE_TEST'
        order.status = 'SUBMITTED'
        order.submitted_at = datetime.now() - timedelta(seconds=600)
        broker.orders['STALE_TEST'] = order
        stale = broker.check_stale_orders(max_age=300)
        assert len(stale) == 1
        assert stale[0].status == 'CANCELLED'

    def test_fresh_order_not_stale(self):
        broker, _ = make_broker()
        order = Order(symbol='AAPL', action='BUY', quantity=1)
        order.order_id = 'FRESH_TEST'
        order.status = 'SUBMITTED'
        order.submitted_at = datetime.now() - timedelta(seconds=10)
        broker.orders['FRESH_TEST'] = order
        stale = broker.check_stale_orders(max_age=300)
        assert len(stale) == 0


# =====================================================================
# Additional: Position and Order dataclass tests
# =====================================================================

class TestDataclasses:

    def test_order_auto_timestamp(self):
        order = Order(symbol='AAPL', action='BUY', quantity=1)
        assert order.timestamp is not None
        assert isinstance(order.timestamp, datetime)

    def test_order_is_stale_no_submitted_at(self):
        order = Order(symbol='AAPL', action='BUY', quantity=1)
        assert order.is_stale() is False

    def test_position_update_market_data(self):
        pos = Position(symbol='AAPL', shares=10, avg_cost=100.0)
        pos.update_market_data(120.0)
        assert pos.market_price == 120.0
        assert pos.market_value == 1200.0
        assert pos.unrealized_pnl == 200.0
        assert pos.high_price == 120.0

    def test_position_high_price_watermark(self):
        pos = Position(symbol='AAPL', shares=10, avg_cost=100.0)
        pos.update_market_data(120.0)
        pos.update_market_data(110.0)
        assert pos.high_price == 120.0  # does not decrease

    def test_portfolio_gross_value(self):
        pos = Position(symbol='AAPL', shares=10, avg_cost=100.0, market_price=120.0)
        portfolio = Portfolio(cash=5000, positions={'AAPL': pos}, total_value=6200, buying_power=5000)
        assert portfolio.gross_value == pytest.approx(6200.0)


# =====================================================================
# Additional: set_price_feed
# =====================================================================

class TestPriceFeed:

    def test_set_price_feed(self):
        broker = PaperBroker(fill_delay=0)
        feed = StaticPriceFeed({'AAPL': 100.0})
        broker.set_price_feed(feed)
        assert broker.price_feed is feed

    def test_price_feed_used_for_fill(self):
        broker, feed = make_broker()
        feed.set_price('AAPL', 123.45)
        result = broker.submit_order(Order(symbol='AAPL', action='BUY', quantity=1))
        assert result.filled_price == pytest.approx(123.45)
