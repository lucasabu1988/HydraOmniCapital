"""
Tests for IBKRBroker mock mode.
Validates all IBKR behavior simulation without TWS.
"""

import os
import sys
import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from omnicapital_broker import (
    IBKRBroker, Order, Position, Portfolio,
    IBKRCommissionModel, ConnectionManager, ConnectionState,
)


# ======================================================================
# IBKRCommissionModel
# ======================================================================

class TestIBKRCommissionModel:
    """Test IBKR tiered commission calculations."""

    def test_normal_order(self):
        # 100 shares @ $150 = $15,000 trade
        # base: 100 * 0.0035 = 0.35, exchange: 100 * 0.0003 = 0.03
        commission = IBKRCommissionModel.calculate(100, 150.0)
        assert commission == 0.38

    def test_minimum_commission(self):
        # 1 share @ $150: base=0.0035, exchange=0.0003 = 0.0038
        # Min $0.35 applies
        commission = IBKRCommissionModel.calculate(1, 150.0)
        assert commission == 0.35

    def test_small_order_minimum(self):
        # 10 shares @ $150: base=0.035, exchange=0.003 = 0.038
        # Min $0.35 applies
        commission = IBKRCommissionModel.calculate(10, 150.0)
        assert commission == 0.35

    def test_large_order(self):
        # 1000 shares @ $150 = $150,000
        # base: 1000 * 0.0035 = 3.50, exchange: 1000 * 0.0003 = 0.30
        # total = 3.80, max cap = 150000 * 0.01 = 1500 (not hit)
        commission = IBKRCommissionModel.calculate(1000, 150.0)
        assert commission == 3.80

    def test_max_cap_penny_stock(self):
        # 10000 shares @ $0.10 = $1000 trade
        # base: 10000 * 0.0035 = 35, exchange: 10000 * 0.0003 = 3
        # total = 38, but max 1% of $1000 = $10
        commission = IBKRCommissionModel.calculate(10000, 0.10)
        assert commission == 10.0


# ======================================================================
# ConnectionManager
# ======================================================================

class TestConnectionManager:
    """Test connection lifecycle."""

    def test_mock_connect_succeeds(self):
        cm = ConnectionManager('127.0.0.1', 7497, 1, mock=True)
        result = cm.connect()
        assert result is True
        assert cm.state == ConnectionState.CONNECTED

    def test_mock_disconnect(self):
        cm = ConnectionManager('127.0.0.1', 7497, 1, mock=True)
        cm.connect()
        cm.disconnect()
        assert cm.state == ConnectionState.DISCONNECTED

    def test_mock_is_connected(self):
        cm = ConnectionManager('127.0.0.1', 7497, 1, mock=True)
        assert cm.is_connected() is False
        cm.connect()
        assert cm.is_connected() is True
        cm.disconnect()
        assert cm.is_connected() is False

    def test_paper_trading_port_7497_accepted(self):
        cm = ConnectionManager('127.0.0.1', 7497, 1, mock=True)
        assert cm.verify_paper_trading() is True

    def test_live_trading_port_7496_rejected(self):
        cm = ConnectionManager('127.0.0.1', 7496, 1, mock=True)
        assert cm.verify_paper_trading() is False

    def test_initial_state_disconnected(self):
        cm = ConnectionManager('127.0.0.1', 7497, 1, mock=True)
        assert cm.state == ConnectionState.DISCONNECTED


# ======================================================================
# IBKRBroker Mock Mode — Core Operations
# ======================================================================

class TestIBKRBrokerMockMode:
    """Test IBKRBroker in mock mode."""

    @pytest.fixture
    def broker(self):
        b = IBKRBroker(mock=True, max_order_value=50_000)
        mock_feed = MagicMock()
        mock_feed.get_price.return_value = 150.0
        b.set_price_feed(mock_feed)
        b._mock_cash = 100_000
        b.connect()
        return b

    def test_connect_succeeds(self, broker):
        assert broker.is_connected() is True

    def test_buy_fills_correctly(self, broker):
        order = Order(symbol='AAPL', action='BUY', quantity=10,
                      order_type='MARKET')
        result = broker.submit_order(order)
        assert result.status == 'FILLED'
        assert result.filled_quantity == 10
        assert result.filled_price is not None
        assert result.commission > 0
        assert result.order_id.startswith('IBKR_MOCK_')

    def test_sell_fills_correctly(self, broker):
        # Buy first
        buy = Order(symbol='AAPL', action='BUY', quantity=10,
                    order_type='MARKET')
        broker.submit_order(buy)
        # Then sell
        sell = Order(symbol='AAPL', action='SELL', quantity=10,
                     order_type='MARKET')
        result = broker.submit_order(sell)
        assert result.status == 'FILLED'
        assert 'AAPL' not in broker._mock_positions

    def test_moc_order_fills(self, broker):
        order = Order(symbol='AAPL', action='BUY', quantity=10,
                      order_type='MOC')
        with patch.object(broker, '_check_moc_deadline', return_value=False):
            result = broker.submit_order(order)
        assert result.status == 'FILLED'
        assert result.order_type == 'MOC'

    def test_insufficient_funds_rejected(self, broker):
        # 10000 shares @ $150 = $1.5M > $100K cash
        order = Order(symbol='AAPL', action='BUY', quantity=10000,
                      order_type='MARKET')
        result = broker.submit_order(order)
        assert result.status == 'ERROR'

    def test_sell_no_position_rejected(self, broker):
        order = Order(symbol='TSLA', action='SELL', quantity=10,
                      order_type='MARKET')
        result = broker.submit_order(order)
        assert result.status == 'ERROR'

    def test_sell_excess_quantity_rejected(self, broker):
        buy = Order(symbol='AAPL', action='BUY', quantity=5,
                    order_type='MARKET')
        broker.submit_order(buy)
        sell = Order(symbol='AAPL', action='SELL', quantity=10,
                     order_type='MARKET')
        result = broker.submit_order(sell)
        assert result.status == 'ERROR'

    def test_order_size_guard(self, broker):
        # 500 shares @ $150 = $75,000 > $50,000 max
        order = Order(symbol='AAPL', action='BUY', quantity=500,
                      order_type='MARKET')
        result = broker.submit_order(order)
        assert result.status == 'ERROR'

    def test_ibkr_commission_model_used(self, broker):
        order = Order(symbol='AAPL', action='BUY', quantity=100,
                      order_type='MARKET')
        result = broker.submit_order(order)
        # IBKR commission for 100 shares: $0.38
        assert result.commission == pytest.approx(0.38, abs=0.01)

    def test_cash_decreases_on_buy(self, broker):
        initial = broker.cash
        order = Order(symbol='AAPL', action='BUY', quantity=10,
                      order_type='MARKET')
        broker.submit_order(order)
        assert broker.cash < initial

    def test_cash_increases_on_sell(self, broker):
        buy = Order(symbol='AAPL', action='BUY', quantity=10,
                    order_type='MARKET')
        broker.submit_order(buy)
        before_sell = broker.cash
        sell = Order(symbol='AAPL', action='SELL', quantity=10,
                     order_type='MARKET')
        broker.submit_order(sell)
        assert broker.cash > before_sell

    def test_position_created_on_buy(self, broker):
        order = Order(symbol='AAPL', action='BUY', quantity=10,
                      order_type='MARKET')
        broker.submit_order(order)
        assert 'AAPL' in broker.positions
        assert broker.positions['AAPL'].shares == 10

    def test_position_averaging(self, broker):
        buy1 = Order(symbol='AAPL', action='BUY', quantity=10,
                     order_type='MARKET')
        broker.submit_order(buy1)
        buy2 = Order(symbol='AAPL', action='BUY', quantity=10,
                     order_type='MARKET')
        broker.submit_order(buy2)
        assert broker.positions['AAPL'].shares == 20

    def test_portfolio_tracking(self, broker):
        order = Order(symbol='AAPL', action='BUY', quantity=10,
                      order_type='MARKET')
        broker.submit_order(order)
        portfolio = broker.get_portfolio()
        assert portfolio.cash < 100_000
        assert 'AAPL' in portfolio.positions
        # Total should be roughly $100K (minus small slippage + commission)
        assert portfolio.total_value == pytest.approx(100_000, abs=100)

    def test_account_info(self, broker):
        info = broker.get_account_info()
        assert info['broker_type'] == 'IBKR'
        assert info['mock_mode'] is True
        assert info['connection_state'] == 'CONNECTED'
        assert info['cash'] == 100_000


# ======================================================================
# Safety Guards
# ======================================================================

class TestSafetyGuards:
    """Test safety guard mechanisms."""

    @pytest.fixture
    def broker(self):
        b = IBKRBroker(mock=True, max_order_value=50_000)
        mock_feed = MagicMock()
        mock_feed.get_price.return_value = 150.0
        b.set_price_feed(mock_feed)
        b._mock_cash = 100_000
        b.connect()
        return b

    def test_not_connected_raises(self, broker):
        broker.disconnect()
        order = Order(symbol='AAPL', action='BUY', quantity=10)
        with pytest.raises(ConnectionError):
            broker.submit_order(order)

    def test_kill_switch_raises(self, broker):
        kill_file = 'STOP_TRADING'
        try:
            with open(kill_file, 'w') as f:
                f.write('test')
            order = Order(symbol='AAPL', action='BUY', quantity=10)
            with pytest.raises(RuntimeError, match="Kill switch"):
                broker.submit_order(order)
        finally:
            if os.path.exists(kill_file):
                os.remove(kill_file)

    def test_moc_rejected_after_deadline(self, broker):
        with patch.object(broker, '_check_moc_deadline', return_value=True):
            order = Order(symbol='AAPL', action='BUY', quantity=10,
                          order_type='MOC')
            result = broker.submit_order(order)
            assert result.status == 'ERROR'

    def test_moc_accepted_before_deadline(self, broker):
        with patch.object(broker, '_check_moc_deadline', return_value=False):
            order = Order(symbol='AAPL', action='BUY', quantity=10,
                          order_type='MOC')
            result = broker.submit_order(order)
            assert result.status == 'FILLED'

    def test_paper_trading_port_guard(self):
        # Port 7496 (live) should fail to connect
        broker = IBKRBroker(mock=True, port=7496)
        result = broker.connect()
        assert result is False


# ======================================================================
# Position Reconciliation
# ======================================================================

class TestPositionReconciliation:
    """Test position reconciliation logic."""

    @pytest.fixture
    def broker(self):
        b = IBKRBroker(mock=True)
        mock_feed = MagicMock()
        mock_feed.get_price.return_value = 150.0
        b.set_price_feed(mock_feed)
        b._mock_cash = 100_000
        b.connect()
        return b

    def test_matching_positions(self, broker):
        broker._mock_positions['AAPL'] = Position('AAPL', 10, 150.0)
        json_state = {'AAPL': {'shares': 10, 'avg_cost': 150.0}}
        report = broker.reconcile_positions(json_state)
        assert report['AAPL']['status'] == 'match'

    def test_json_only_position(self, broker):
        json_state = {'AAPL': {'shares': 10, 'avg_cost': 150.0}}
        report = broker.reconcile_positions(json_state)
        assert report['AAPL']['status'] == 'json_only'

    def test_broker_only_position(self, broker):
        broker._mock_positions['AAPL'] = Position('AAPL', 10, 150.0)
        report = broker.reconcile_positions({})
        assert report['AAPL']['status'] == 'broker_only'

    def test_quantity_mismatch(self, broker):
        broker._mock_positions['AAPL'] = Position('AAPL', 15, 150.0)
        json_state = {'AAPL': {'shares': 10, 'avg_cost': 150.0}}
        report = broker.reconcile_positions(json_state)
        assert report['AAPL']['status'] == 'quantity_mismatch'

    def test_multiple_positions_mixed(self, broker):
        broker._mock_positions['AAPL'] = Position('AAPL', 10, 150.0)
        broker._mock_positions['MSFT'] = Position('MSFT', 20, 300.0)
        json_state = {
            'AAPL': {'shares': 10, 'avg_cost': 150.0},  # match
            'NVDA': {'shares': 5, 'avg_cost': 500.0},    # json_only
        }
        report = broker.reconcile_positions(json_state)
        assert report['AAPL']['status'] == 'match'
        assert report['MSFT']['status'] == 'broker_only'
        assert report['NVDA']['status'] == 'json_only'

    def test_empty_reconciliation(self, broker):
        report = broker.reconcile_positions({})
        assert len(report) == 0


# ======================================================================
# Cash & Positions Properties (COMPASSLive compatibility)
# ======================================================================

class TestCOMPASSLiveCompatibility:
    """Test that IBKRBroker.cash and .positions work like PaperBroker."""

    def test_cash_property_get(self):
        broker = IBKRBroker(mock=True)
        broker._mock_cash = 100_000
        assert broker.cash == 100_000

    def test_cash_property_set(self):
        broker = IBKRBroker(mock=True)
        broker.cash = 50_000
        assert broker._mock_cash == 50_000
        assert broker.cash == 50_000

    def test_positions_property_returns_mutable(self):
        broker = IBKRBroker(mock=True)
        broker._mock_positions['AAPL'] = Position('AAPL', 10, 150.0)
        # COMPASSLive does: self.broker.positions[symbol] = Position(...)
        broker.positions['MSFT'] = Position('MSFT', 5, 300.0)
        assert 'MSFT' in broker._mock_positions

    def test_positions_property_set(self):
        broker = IBKRBroker(mock=True)
        new_pos = {'AAPL': Position('AAPL', 10, 150.0)}
        broker.positions = new_pos
        assert broker._mock_positions == new_pos


# ======================================================================
# Audit Trail
# ======================================================================

class TestAuditTrail:
    """Test audit log functionality."""

    @pytest.fixture
    def broker(self):
        b = IBKRBroker(mock=True, max_order_value=50_000)
        mock_feed = MagicMock()
        mock_feed.get_price.return_value = 150.0
        b.set_price_feed(mock_feed)
        b._mock_cash = 100_000
        b.connect()
        return b

    def test_audit_log_populated_on_fill(self, broker):
        order = Order(symbol='AAPL', action='BUY', quantity=10,
                      order_type='MARKET')
        broker.submit_order(order)
        log = broker.get_audit_log()
        assert len(log) > 0
        assert log[-1]['symbol'] == 'AAPL'
        assert log[-1]['event'] == 'order_completed'
        assert log[-1]['mock'] is True

    def test_audit_log_on_rejection(self, broker):
        # Order size guard
        order = Order(symbol='AAPL', action='BUY', quantity=500,
                      order_type='MARKET')
        broker.submit_order(order)
        log = broker.get_audit_log()
        rejected = [e for e in log if e['event'] == 'submit_rejected']
        assert len(rejected) == 1
        assert rejected[0]['reason'] == 'order_size_exceeded'

    def test_audit_log_save(self, broker, tmp_path):
        order = Order(symbol='AAPL', action='BUY', quantity=10,
                      order_type='MARKET')
        broker.submit_order(order)
        filepath = str(tmp_path / 'test_audit.json')
        broker.save_audit_log(filepath)
        assert os.path.exists(filepath)
        with open(filepath, 'r') as f:
            data = json.load(f)
        assert len(data) > 0

    def test_empty_audit_log_no_save(self, broker, tmp_path):
        filepath = str(tmp_path / 'empty_audit.json')
        broker.save_audit_log(filepath)
        assert not os.path.exists(filepath)


# ======================================================================
# Order Lifecycle
# ======================================================================

class TestOrderLifecycle:
    """Test order tracking and management."""

    @pytest.fixture
    def broker(self):
        b = IBKRBroker(mock=True, max_order_value=50_000)
        mock_feed = MagicMock()
        mock_feed.get_price.return_value = 150.0
        b.set_price_feed(mock_feed)
        b._mock_cash = 100_000
        b.connect()
        return b

    def test_order_id_incrementing(self, broker):
        o1 = Order(symbol='AAPL', action='BUY', quantity=10,
                   order_type='MARKET')
        r1 = broker.submit_order(o1)
        o2 = Order(symbol='MSFT', action='BUY', quantity=10,
                   order_type='MARKET')
        r2 = broker.submit_order(o2)
        assert r1.order_id == 'IBKR_MOCK_1'
        assert r2.order_id == 'IBKR_MOCK_2'

    def test_order_history_tracked(self, broker):
        for _ in range(3):
            order = Order(symbol='AAPL', action='BUY', quantity=5,
                          order_type='MARKET')
            broker.submit_order(order)
        assert len(broker.order_history) == 3

    def test_get_order_status(self, broker):
        order = Order(symbol='AAPL', action='BUY', quantity=10,
                      order_type='MARKET')
        result = broker.submit_order(order)
        status = broker.get_order_status(result.order_id)
        assert status is not None
        assert status.status == 'FILLED'

    def test_get_order_status_unknown(self, broker):
        assert broker.get_order_status('FAKE_123') is None

    def test_submitted_at_populated(self, broker):
        order = Order(symbol='AAPL', action='BUY', quantity=10,
                      order_type='MARKET')
        result = broker.submit_order(order)
        assert result.submitted_at is not None


# ======================================================================
# Limit Orders (Mock)
# ======================================================================

class TestLimitOrders:
    """Test limit order behavior in mock mode."""

    @pytest.fixture
    def broker(self):
        b = IBKRBroker(mock=True, max_order_value=50_000)
        mock_feed = MagicMock()
        mock_feed.get_price.return_value = 150.0
        b.set_price_feed(mock_feed)
        b._mock_cash = 100_000
        b.connect()
        return b

    def test_limit_buy_marketable_fills(self, broker):
        # Limit at $151 > market $150: fills (within 2% circuit breaker)
        order = Order(symbol='AAPL', action='BUY', quantity=10,
                      order_type='LIMIT', limit_price=151.0)
        result = broker.submit_order(order)
        assert result.status == 'FILLED'
        assert result.filled_price == 151.0

    def test_limit_buy_below_market_no_fill(self, broker):
        # Limit at $140 < market $150: doesn't fill
        order = Order(symbol='AAPL', action='BUY', quantity=10,
                      order_type='LIMIT', limit_price=140.0)
        result = broker.submit_order(order)
        assert result.status == 'ERROR'  # No fill price available

    def test_limit_sell_marketable_fills(self, broker):
        # Buy first
        buy = Order(symbol='AAPL', action='BUY', quantity=10,
                    order_type='MARKET')
        broker.submit_order(buy)
        # Limit sell at $149 < market $150: fills (within 2% circuit breaker)
        sell = Order(symbol='AAPL', action='SELL', quantity=10,
                     order_type='LIMIT', limit_price=149.0)
        result = broker.submit_order(sell)
        assert result.status == 'FILLED'
        assert result.filled_price == 149.0
