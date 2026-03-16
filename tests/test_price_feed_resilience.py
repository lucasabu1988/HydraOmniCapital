import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import omnicapital_live as live


class MutableFeed:
    def __init__(self, prices=None, cache_age_seconds=0):
        self.prices = dict(prices or {})
        self.cache_age_seconds = cache_age_seconds

    def get_prices(self, symbols):
        return {symbol: self.prices[symbol] for symbol in symbols if symbol in self.prices}

    def get_price(self, symbol):
        return self.prices.get(symbol)

    def get_cache_age_seconds(self):
        return self.cache_age_seconds


def make_hist(start_price, step, periods=220):
    import pandas as pd

    dates = pd.date_range('2025-01-01', periods=periods, freq='B')
    prices = [start_price + (idx * step) for idx in range(periods)]
    return pd.DataFrame({'Close': prices}, index=dates)


@pytest.fixture
def trader(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(live, '_git_sync_available', False, raising=False)
    monkeypatch.setattr(live, '_ml_available', False, raising=False)
    monkeypatch.setattr(live, '_hydra_available', False, raising=False)
    monkeypatch.setattr(live, '_overlay_available', False, raising=False)

    feed = MutableFeed({'AAPL': 125.0, 'MSFT': 119.0, 'SPY': 505.0})
    monkeypatch.setattr(live, 'YahooDataFeed', lambda cache_duration: feed)

    config = live.CONFIG.copy()
    config['BROKER_TYPE'] = 'PAPER'
    config['PAPER_INITIAL_CASH'] = 100000
    config['STATE_SAVE_INTERVAL'] = 999999
    config['STOP_CHECK_INTERVAL'] = 999999

    trader = live.COMPASSLive(config)
    trader.broker.connect()
    trader.broker.fill_delay = 0
    trader.validator.validate_batch = lambda raw_prices: raw_prices
    trader.is_market_open = lambda: True
    trader.is_new_trading_day = lambda: False
    trader.is_preclose_window = lambda: False
    trader.log_status = lambda prices: None
    trader._daily_open_done = True
    trader.current_universe = ['AAPL', 'MSFT']
    trader._hist_cache = {
        'AAPL': make_hist(100.0, 0.2),
        'MSFT': make_hist(90.0, 0.15),
    }
    trader._spy_hist = make_hist(430.0, 0.3, periods=260)
    trader.test_feed = feed
    return trader


def test_run_once_tolerates_repeated_empty_price_cycles_without_trading(trader):
    trader.test_feed.prices = {}
    trader._max_consecutive_errors = 6

    for expected_errors in range(1, 6):
        result = trader.run_once()
        assert result is False
        assert trader._consecutive_errors == expected_errors
        assert trader.trades_today == []
        assert trader.broker.positions == {}


def test_stale_price_guard_skips_cycle_when_cache_is_older_than_five_minutes(trader, caplog):
    trader.test_feed.cache_age_seconds = 360

    with caplog.at_level(logging.ERROR, logger=live.logger.name):
        result = trader.run_once()

    assert result is False
    assert trader._stale_price_guard_triggered(360) is True
    assert trader.trades_today == []
    assert any('Skipping trading cycle due to stale market data' in record.message
               for record in caplog.records)


def test_run_once_raises_after_max_consecutive_empty_price_failures(trader):
    trader.test_feed.prices = {}

    for _ in range(trader._max_consecutive_errors - 1):
        assert trader.run_once() is False

    with pytest.raises(RuntimeError, match='Too many consecutive errors'):
        trader.run_once()

    assert trader.trades_today == []
    assert trader.broker.positions == {}
