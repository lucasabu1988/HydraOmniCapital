# tests/test_hydra_tools.py
import os
import json
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from hydra_tools import (
    TOOL_DEFINITIONS,
    HydraToolExecutor,
)


def test_tool_definitions_valid_anthropic_format():
    """All tools must have name, description, input_schema"""
    assert len(TOOL_DEFINITIONS) >= 15
    for tool in TOOL_DEFINITIONS:
        assert 'name' in tool
        assert 'description' in tool
        assert 'input_schema' in tool
        assert tool['input_schema']['type'] == 'object'


def test_tool_names_unique():
    names = [t['name'] for t in TOOL_DEFINITIONS]
    assert len(names) == len(set(names))


def test_trading_core_tools_present():
    names = {t['name'] for t in TOOL_DEFINITIONS}
    expected = {
        'get_momentum_signals', 'check_regime', 'check_position_stops',
        'execute_trade', 'get_portfolio_state', 'save_state', 'update_cycle_log'
    }
    assert expected.issubset(names)


def test_market_intel_tools_present():
    names = {t['name'] for t in TOOL_DEFINITIONS}
    expected = {
        'get_earnings_calendar', 'get_macro_data',
        'get_insider_trades', 'get_financial_metrics', 'get_news_headlines'
    }
    assert expected.issubset(names)


def test_operations_tools_present():
    names = {t['name'] for t in TOOL_DEFINITIONS}
    expected = {'send_notification', 'log_decision', 'validate_data_feeds'}
    assert expected.issubset(names)


class TestToolExecutor:

    @pytest.fixture
    def executor(self, tmp_path):
        engine = MagicMock()
        engine.broker = MagicMock()
        engine.broker.cash = 50000.0
        engine.broker.positions = {}
        engine.current_regime_score = 0.7
        engine.save_state = MagicMock()

        from hydra_scratchpad import HydraScratchpad
        scratchpad = HydraScratchpad(state_dir=str(tmp_path))

        return HydraToolExecutor(engine=engine, scratchpad=scratchpad)

    def test_dispatch_unknown_tool(self, executor):
        result = executor.dispatch('unknown_tool', {})
        assert 'error' in result.lower() or 'unknown' in result.lower()

    def test_get_portfolio_state(self, executor):
        executor.engine.broker.cash = 75000.0
        executor.engine.broker.positions = {}
        executor.engine.current_regime_score = 0.8
        executor.engine.peak_value = 100000.0
        executor.engine.crash_cooldown = 0
        executor.engine.trading_day_counter = 42
        executor.engine.position_meta = {}
        executor.engine.broker.get_portfolio = MagicMock(
            return_value=MagicMock(total_value=75000.0)
        )
        result = executor.dispatch('get_portfolio_state', {})
        data = json.loads(result)
        assert data['cash'] == 75000.0
        assert data['regime_score'] == 0.8

    def test_execute_trade_idempotency(self, executor):
        """If same trade already in scratchpad, return existing fill"""
        executor.scratchpad.log('trade', {
            'symbol': 'AAPL', 'action': 'BUY', 'shares': 10, 'price': 200.0
        })
        result = executor.dispatch('execute_trade', {
            'symbol': 'AAPL', 'action': 'BUY', 'shares': 10
        })
        data = json.loads(result)
        assert data.get('idempotent') is True or 'already executed' in result.lower()

    def test_execute_trade_blocked_after_moc_deadline(self, executor):
        """Trades rejected after 15:50 ET"""
        with patch('hydra_tools._get_et_now') as mock_now:
            mock_now.return_value = datetime(2026, 3, 13, 16, 0, 0)  # 16:00 ET
            result = executor.dispatch('execute_trade', {
                'symbol': 'AAPL', 'action': 'BUY', 'shares': 10
            })
            assert 'reject' in result.lower() or 'deadline' in result.lower()

    def test_execute_trade_daily_limit(self, executor):
        """Max 10 round-trips per day"""
        for i in range(11):
            sym = f'STOCK{i}'
            executor.scratchpad.log('trade', {'symbol': sym, 'action': 'BUY', 'shares': 1, 'price': 100.0})
            executor.scratchpad.log('trade', {'symbol': sym, 'action': 'SELL', 'shares': 1, 'price': 101.0})
        result = executor.dispatch('execute_trade', {
            'symbol': 'NEW', 'action': 'BUY', 'shares': 10
        })
        assert 'limit' in result.lower() or 'halt' in result.lower()

    def test_log_decision_tool(self, executor):
        result = executor.dispatch('log_decision', {
            'action': 'SKIP',
            'symbol': 'TSLA',
            'reason': 'earnings in 12h',
            'alternative': 'MSFT'
        })
        entries = executor.scratchpad.read_today()
        decisions = [e for e in entries if e['type'] == 'decision']
        assert len(decisions) == 1
        assert decisions[0]['data']['symbol'] == 'TSLA'

    def test_validate_data_feeds(self, executor):
        with patch('hydra_tools._check_yfinance_health') as mock_yf:
            mock_yf.return_value = {'spy_fresh': True, 'spy_price': 550.0, 'yfinance_ok': True}
            result = executor.dispatch('validate_data_feeds', {})
            data = json.loads(result)
            assert data['spy_fresh'] is True
