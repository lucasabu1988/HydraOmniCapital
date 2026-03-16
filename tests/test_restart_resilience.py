import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import omnicapital_live as live
from omnicapital_broker import Position


class MutableFeed:
    def __init__(self, prices=None):
        self.prices = dict(prices or {})

    def get_prices(self, symbols):
        return {symbol: self.prices[symbol] for symbol in symbols if symbol in self.prices}

    def get_price(self, symbol):
        return self.prices.get(symbol)

    def get_cache_age_seconds(self):
        return 0


def build_meta(symbol, entry_price, day_index, sector):
    return {
        'entry_price': entry_price,
        'entry_date': '2026-03-16',
        'entry_day_index': day_index,
        'original_entry_day_index': day_index,
        'high_price': entry_price,
        'entry_vol': 0.25,
        'entry_daily_vol': 0.016,
        'sector': sector,
    }


@pytest.fixture
def engine_factory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(live, '_git_sync_available', False, raising=False)
    monkeypatch.setattr(live, '_ml_available', False, raising=False)
    monkeypatch.setattr(live, '_hydra_available', False, raising=False)
    monkeypatch.setattr(live, '_overlay_available', False, raising=False)
    monkeypatch.setattr(live.COMPASSLive, '_ensure_active_cycle', lambda self: None)

    created_feeds = []

    def factory(prices):
        feed = MutableFeed(prices)
        created_feeds.append(feed)
        monkeypatch.setattr(live, 'YahooDataFeed', lambda cache_duration: feed)

        config = live.CONFIG.copy()
        config['BROKER_TYPE'] = 'PAPER'
        config['PAPER_INITIAL_CASH'] = 100000
        config['STOP_CHECK_INTERVAL'] = 999999
        config['STATE_SAVE_INTERVAL'] = 999999

        trader = live.COMPASSLive(config)
        trader.broker.connect()
        trader.broker.fill_delay = 0
        trader.validator.validate_batch = lambda raw_prices: raw_prices
        trader.log_status = lambda prices: None
        return trader

    return factory


def seed_positions(trader):
    trader.broker.cash = 90950.0
    trader.broker.positions = {
        'AAPL': Position('AAPL', 10, 150.0),
        'MSFT': Position('MSFT', 8, 200.0),
        'JNJ': Position('JNJ', 5, 149.0),
    }
    trader.position_meta = {
        'AAPL': build_meta('AAPL', 150.0, 3, 'Technology'),
        'MSFT': build_meta('MSFT', 200.0, 3, 'Technology'),
        'JNJ': build_meta('JNJ', 149.0, 3, 'Healthcare'),
    }
    trader.current_universe = ['AAPL', 'MSFT', 'JNJ']
    trader.universe_year = 2026
    trader.peak_value = 100000.0


def test_restart_restores_mid_cycle_state_without_double_trading(engine_factory, monkeypatch):
    prices = {'AAPL': 151.0, 'MSFT': 202.0, 'JNJ': 150.0, 'SPY': 505.0}
    first_engine = engine_factory(prices)
    seed_positions(first_engine)
    first_engine.trading_day_counter = 3
    first_engine.last_trading_date = date(2026, 3, 16)
    first_engine._daily_open_done = True
    first_engine._preclose_entries_done = True
    first_engine.save_state()

    restarted = engine_factory(prices)
    restarted.load_state()

    assert set(restarted.broker.positions) == {'AAPL', 'MSFT', 'JNJ'}
    assert restarted.broker.cash == pytest.approx(90950.0)
    assert restarted.trading_day_counter == 3
    assert restarted._daily_open_done is True
    assert restarted._preclose_entries_done is True

    fixed_now = datetime(2026, 3, 16, 15, 35, tzinfo=restarted.et_tz)
    restarted.get_et_now = lambda: fixed_now
    restarted.is_market_open = lambda: True
    restarted.is_preclose_window = lambda: True

    open_calls = []
    preclose_calls = []
    original_daily_open = restarted.daily_open

    def tracked_daily_open():
        open_calls.append('daily_open')
        return original_daily_open()

    restarted.daily_open = tracked_daily_open
    restarted.execute_preclose_entries = lambda prices: preclose_calls.append('preclose')
    restarted._last_stop_check = datetime.now()
    restarted._last_state_save = datetime.now()

    result = restarted.run_once()

    assert result is True
    assert open_calls == []
    assert preclose_calls == []


def test_restart_calls_daily_open_when_previous_day_state_was_incomplete(engine_factory):
    prices = {'AAPL': 151.0, 'MSFT': 202.0, 'JNJ': 150.0, 'SPY': 505.0}
    first_engine = engine_factory(prices)
    seed_positions(first_engine)
    first_engine.trading_day_counter = 3
    first_engine.last_trading_date = date(2026, 3, 15)
    first_engine._daily_open_done = False
    first_engine._preclose_entries_done = False
    first_engine.save_state()

    restarted = engine_factory(prices)
    restarted.load_state()

    fixed_now = datetime(2026, 3, 16, 10, 0, tzinfo=restarted.et_tz)
    restarted.get_et_now = lambda: fixed_now
    restarted.is_market_open = lambda: True
    restarted.is_preclose_window = lambda: False

    open_calls = []
    logic_calls = []
    original_daily_open = restarted.daily_open

    def tracked_daily_open():
        open_calls.append('daily_open')
        return original_daily_open()

    def tracked_execute_trading_logic(prices):
        logic_calls.append('execute_trading_logic')
        restarted._daily_open_done = True

    restarted.daily_open = tracked_daily_open
    restarted.execute_trading_logic = tracked_execute_trading_logic
    restarted.log_status = lambda prices: None
    restarted._last_stop_check = datetime.now() - timedelta(seconds=1)
    restarted._last_state_save = datetime.now()

    result = restarted.run_once()

    assert result is True
    assert open_calls == ['daily_open']
    assert logic_calls == ['execute_trading_logic']
    assert restarted.trading_day_counter == 4
    assert restarted.last_trading_date == date(2026, 3, 16)
