import sys
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from omnicapital_live import COMPASSLive, CONFIG


@patch('omnicapital_live.YahooDataFeed')
def test_shutdown_flag_initialised_false(mock_feed):
    mock_feed.return_value = MagicMock()
    config = CONFIG.copy()
    config['PAPER_INITIAL_CASH'] = 100_000
    trader = COMPASSLive(config)
    assert trader._shutdown_requested is False


@patch('omnicapital_live.YahooDataFeed')
def test_run_once_returns_with_shutdown_flag(mock_feed):
    mock_feed.return_value = MagicMock()
    config = CONFIG.copy()
    config['PAPER_INITIAL_CASH'] = 100_000
    trader = COMPASSLive(config)
    trader._shutdown_requested = True
    # run_once() should complete without error regardless of shutdown flag
    # (the flag only controls the run() loop, not run_once)
    # We mock is_market_open to avoid real market checks
    trader.is_market_open = MagicMock(return_value=False)
    result = trader.run_once()
    # When market is closed, run_once returns False
    assert result is False


@patch('omnicapital_live.YahooDataFeed')
def test_run_loop_exits_on_shutdown_flag(mock_feed):
    mock_feed.return_value = MagicMock()
    config = CONFIG.copy()
    config['PAPER_INITIAL_CASH'] = 100_000
    trader = COMPASSLive(config)
    trader._run_startup_self_test_once = MagicMock()
    trader.save_state = MagicMock()
    trader.notifier = None
    trader.trades_today = []
    # Set shutdown before run() so it breaks immediately
    trader._shutdown_requested = True
    trader.run(interval=1)
    trader.save_state.assert_called_once()
