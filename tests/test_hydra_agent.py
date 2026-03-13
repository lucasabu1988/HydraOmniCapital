# tests/test_hydra_agent.py
import os
import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime

from hydra_agent import HydraAgent, SCHEDULE


def test_schedule_defined():
    """4 phases with ET times"""
    assert len(SCHEDULE) == 4
    phases = {s['phase'] for s in SCHEDULE}
    assert 'PRE_MARKET_BRIEFING' in phases
    assert 'INTRADAY_MONITOR' in phases
    assert 'PRE_CLOSE_DECISION' in phases
    assert 'POST_CLOSE_SUMMARY' in phases


class TestHydraAgent:

    @pytest.fixture
    def agent(self, tmp_path):
        with patch.dict(os.environ, {
            'ANTHROPIC_API_KEY': 'test-key',
            'STATE_DIR': str(tmp_path),
            'BROKER_TYPE': 'PAPER',
        }):
            with patch('hydra_agent.anthropic'):
                with patch('hydra_agent.HydraAgent._init_engine'):
                    with patch('hydra_agent.HydraAgent._init_notifier', return_value=None):
                        a = HydraAgent(state_dir=str(tmp_path))
                        a.engine = MagicMock()
                        a.engine.broker = MagicMock()
                        a.engine.broker.cash = 50000.0
                        a.engine.broker.positions = {}
                        a.engine.current_regime_score = 0.7
                        a.engine.peak_value = 100000.0
                        a.engine.crash_cooldown = 0
                        a.engine.trading_day_counter = 42
                        a.engine.position_meta = {}
                        a.engine.portfolio_values_history = [100000.0]
                        a.engine.broker.get_portfolio = MagicMock(
                            return_value=MagicMock(total_value=50000.0)
                        )
                        a.engine.data_feed = None
                        a.engine.config = {'STOP_DAILY_VOL_MULT': 2.5, 'STOP_FLOOR': -0.06, 'STOP_CEILING': -0.15}
                        # Re-init tools with mock engine
                        from hydra_tools import HydraToolExecutor
                        a.tools = HydraToolExecutor(engine=a.engine, scratchpad=a.scratchpad)
                        return a

    def test_kill_switch(self, agent, tmp_path):
        """STOP_TRADING file halts execution"""
        stop_file = os.path.join(str(tmp_path), 'STOP_TRADING')
        with open(stop_file, 'w') as f:
            f.write('halt')
        assert agent._check_kill_switch() is True

    def test_no_kill_switch(self, agent):
        assert agent._check_kill_switch() is False

    def test_should_run_phase_weekday(self, agent):
        """Phases run only on weekdays"""
        with patch('hydra_agent._get_et_now') as mock_now:
            mock_now.return_value = datetime(2026, 3, 16, 6, 0, 0)  # Monday
            assert agent._is_trading_day() is True
            mock_now.return_value = datetime(2026, 3, 14, 6, 0, 0)  # Saturday
            assert agent._is_trading_day() is False

    def test_intraday_stop_auto_execution(self, agent):
        """Stops execute in Python, Claude only logs post-hoc"""
        agent.engine.broker.positions = {'AAPL': MagicMock(shares=10, avg_cost=200.0)}
        agent.engine.position_meta = {'AAPL': {'entry_daily_vol': 0.02}}
        stop_result = {
            'symbol': 'AAPL',
            'stop_triggered': True,
            'return_pct': -7.5,
        }
        with patch.object(agent, '_execute_immediate_stop') as mock_stop:
            agent._check_and_execute_stops([stop_result])
            mock_stop.assert_called_once_with('AAPL')

    def test_daily_loss_halt(self, agent):
        """If portfolio drops >3% intraday, halt entries"""
        agent.engine.portfolio_values_history = [100000.0]
        agent.engine.broker.get_portfolio = MagicMock(
            return_value=MagicMock(total_value=96500.0)  # -3.5%
        )
        assert agent._check_daily_loss_halt() is True

    def test_partial_rotation_recovery(self, agent):
        """Agent detects partial rotation on restart"""
        agent.scratchpad.log('decision', {'action': 'SELL', 'symbol': 'AAPL', 'reason': 'rotation'})
        agent.scratchpad.log('trade', {'symbol': 'AAPL', 'action': 'SELL', 'shares': 10, 'price': 200.0})
        agent.scratchpad.log('decision', {'action': 'SELL', 'symbol': 'MSFT', 'reason': 'rotation'})
        agent.scratchpad.log('trade', {'symbol': 'MSFT', 'action': 'SELL', 'shares': 5, 'price': 400.0})
        status = agent._detect_partial_rotation()
        assert status['sells'] == 2
        assert status['buys'] == 0
        assert status['partial'] is True
