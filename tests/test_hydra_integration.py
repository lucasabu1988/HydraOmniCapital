# tests/test_hydra_integration.py
"""Integration tests for HYDRA agent — verifies end-to-end flow
with mocked Anthropic API and PaperBroker."""

import os
import json
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime

from hydra_scratchpad import HydraScratchpad
from hydra_tools import HydraToolExecutor, TOOL_DEFINITIONS
from hydra_prompts import build_system_prompt
from hydra_agent import HydraAgent


class TestEndToEnd:

    @pytest.fixture
    def setup(self, tmp_path):
        """Full agent stack with mocked engine"""
        engine = MagicMock()
        engine.broker = MagicMock()
        engine.broker.cash = 50000.0
        aapl_pos = MagicMock()
        aapl_pos.shares = 10
        aapl_pos.avg_cost = 200.0
        aapl_pos.market_price = 215.0
        aapl_pos.unrealized_pnl = 150.0

        msft_pos = MagicMock()
        msft_pos.shares = 5
        msft_pos.avg_cost = 400.0
        msft_pos.market_price = 410.0
        msft_pos.unrealized_pnl = 50.0

        engine.broker.positions = {
            'AAPL': aapl_pos,
            'MSFT': msft_pos,
        }
        engine.current_regime_score = 0.7
        engine.peak_value = 100000.0
        engine.crash_cooldown = 0
        engine.trading_day_counter = 42
        engine.position_meta = {
            'AAPL': {'entry_daily_vol': 0.02, 'sector': 'Technology', 'days_held': 3},
            'MSFT': {'entry_daily_vol': 0.015, 'sector': 'Technology', 'days_held': 6},
        }
        engine.broker.get_portfolio = MagicMock(
            return_value=MagicMock(total_value=54000.0)
        )
        engine.data_feed = MagicMock()
        engine.data_feed.get_price = MagicMock(side_effect=lambda sym: {'AAPL': 215.0, 'MSFT': 410.0}.get(sym))
        engine.save_state = MagicMock()
        engine.config = {'STOP_DAILY_VOL_MULT': 2.5, 'STOP_FLOOR': -0.06, 'STOP_CEILING': -0.15}

        scratchpad = HydraScratchpad(state_dir=str(tmp_path))
        tools = HydraToolExecutor(engine=engine, scratchpad=scratchpad)

        return {'engine': engine, 'scratchpad': scratchpad, 'tools': tools}

    def test_full_portfolio_state(self, setup):
        result = json.loads(setup['tools'].dispatch('get_portfolio_state', {}))
        assert result['cash'] == 50000.0
        # tool returns 'position_count', not 'n_positions'
        assert result['position_count'] == 2
        assert 'AAPL' in result['positions']

    def test_prompt_builds_with_real_state(self, setup):
        state = json.loads(setup['tools'].dispatch('get_portfolio_state', {}))
        prompt = build_system_prompt(
            phase='PRE_CLOSE_DECISION',
            portfolio_state=state,
            scratchpad_summary='No entries.',
        )
        assert 'PRE_CLOSE_DECISION' in prompt

    def test_tool_definitions_match_executor(self, setup):
        """Every defined tool has a handler in the executor"""
        for tool_def in TOOL_DEFINITIONS:
            handler = getattr(setup['tools'], f"_tool_{tool_def['name']}", None)
            assert handler is not None, f"Missing handler for tool: {tool_def['name']}"

    def test_trade_then_save_flow(self, setup):
        """Simulate: execute trade → save state"""
        fill = MagicMock()
        fill.filled_price = 170.0
        fill.order_id = 'ORD-001'
        fill.status = 'FILLED'
        setup['engine'].broker.submit_order = MagicMock(return_value=fill)

        with patch('hydra_tools._get_et_now') as mock_now:
            mock_now.return_value = datetime(2026, 3, 13, 15, 35, 0)  # 15:35 ET
            result = json.loads(setup['tools'].dispatch('execute_trade', {
                'symbol': 'GOOG', 'action': 'BUY', 'shares': 5
            }))
            assert result.get('status') == 'FILLED' or 'error' not in result

        save_result = json.loads(setup['tools'].dispatch('save_state', {}))
        # tool returns {'saved': True} on success
        assert save_result.get('saved') is True or save_result.get('status') == 'ok'
        setup['engine'].save_state.assert_called_once()

    def test_scratchpad_records_all_tool_calls(self, setup):
        """Every tool dispatch is recorded"""
        setup['tools'].dispatch('get_portfolio_state', {})
        with patch('hydra_tools._check_yfinance_health') as mock_yf:
            mock_yf.return_value = {'spy_fresh': True, 'spy_price': 550.0, 'yfinance_ok': True}
            setup['tools'].dispatch('validate_data_feeds', {})
        entries = setup['scratchpad'].read_today()
        tool_calls = [e for e in entries if e['type'] == 'tool_call']
        assert len(tool_calls) == 2

    def test_soul_loaded(self):
        """SOUL.md is loaded into prompts"""
        prompt = build_system_prompt(
            phase='PRE_MARKET_BRIEFING',
            portfolio_state={'cash': 0, 'positions': {}},
            scratchpad_summary='',
        )
        assert '62 experiments' in prompt
