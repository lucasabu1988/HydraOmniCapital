import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import omnicapital_live as live


class StubPriceFeed:
    def __init__(self, prices):
        self.prices = dict(prices)
        self.cache_age_seconds = 0

    def get_prices(self, symbols):
        return {symbol: self.prices[symbol] for symbol in symbols if symbol in self.prices}

    def get_price(self, symbol):
        return self.prices.get(symbol)

    def get_cache_age_seconds(self):
        return self.cache_age_seconds


class MultiDayPriceFeed:
    def __init__(self, prices_by_day, clock):
        self.prices_by_day = dict(prices_by_day)
        self.clock = clock

    def _current_prices(self):
        current_day = self.clock.current.date().isoformat()
        return self.prices_by_day[current_day]

    def get_prices(self, symbols):
        prices = self._current_prices()
        return {symbol: prices[symbol] for symbol in symbols if symbol in prices}

    def get_price(self, symbol):
        return self._current_prices().get(symbol)

    def get_cache_age_seconds(self):
        return 0


class FrozenDateTime(datetime):
    current = datetime(2026, 3, 10, 15, 35)

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            current = cls.current
            if current.tzinfo is None:
                current = current.replace(tzinfo=tz)
            else:
                current = current.astimezone(tz)
            return cls(
                current.year, current.month, current.day,
                current.hour, current.minute, current.second, current.microsecond,
                tzinfo=current.tzinfo,
            )
        current = cls.current.replace(tzinfo=None)
        return cls(
            current.year, current.month, current.day,
            current.hour, current.minute, current.second, current.microsecond,
        )


class FailingML:
    def __init__(self, fail_on):
        self.fail_on = fail_on

    def on_entry(self, **kwargs):
        if self.fail_on == 'entry':
            raise RuntimeError('entry failed')

    def on_exit(self, **kwargs):
        if self.fail_on == 'exit':
            raise RuntimeError('exit failed')

    def on_hold(self, **kwargs):
        if self.fail_on == 'hold':
            raise RuntimeError('hold failed')

    def on_skip(self, **kwargs):
        if self.fail_on == 'skip':
            raise RuntimeError('skip failed')

    def on_end_of_day(self, **kwargs):
        if self.fail_on == 'snapshot':
            raise RuntimeError('snapshot failed')

    def run_learning(self):
        return {'phase': 1}


def make_hist(start_price, step, periods=220):
    dates = pd.date_range('2025-01-01', periods=periods, freq='B')
    prices = [start_price + (idx * step) for idx in range(periods)]
    return pd.DataFrame({'Close': prices}, index=dates)


@pytest.fixture
def temp_runtime(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(live, '_git_sync_available', False, raising=False)
    live._ml_error_counts = {
        'entry': 0,
        'exit': 0,
        'hold': 0,
        'skip': 0,
        'snapshot': 0,
    }
    return tmp_path


@pytest.fixture
def trader(monkeypatch, temp_runtime):
    prices = {
        'AAPL': 125.0,
        'MSFT': 119.0,
        'SPY': 505.0,
    }
    feed = StubPriceFeed(prices)
    monkeypatch.setattr(live, 'YahooDataFeed', lambda cache_duration: feed)

    config = live.CONFIG.copy()
    config['BROKER_TYPE'] = 'PAPER'
    config['PAPER_INITIAL_CASH'] = 100000
    config['MIN_MOMENTUM_STOCKS'] = 1
    config['STATE_SAVE_INTERVAL'] = 0
    config['STOP_CHECK_INTERVAL'] = 0

    trader = live.COMPASSLive(config)
    trader.broker.connect()
    trader.broker.fill_delay = 0
    trader.validator.validate_batch = lambda raw_prices: raw_prices

    monkeypatch.setattr(trader, 'is_market_open', lambda: True)
    monkeypatch.setattr(trader, 'is_new_trading_day', lambda: True)
    monkeypatch.setattr(trader, 'is_preclose_window', lambda: True)
    monkeypatch.setattr(trader, 'refresh_universe', lambda: None)
    monkeypatch.setattr(trader, 'refresh_daily_data', lambda: None)
    monkeypatch.setattr(trader, '_reconcile_entry_prices', lambda: None)
    monkeypatch.setattr(trader, 'update_regime', lambda: None)
    monkeypatch.setattr(trader, 'log_status', lambda prices: None)
    monkeypatch.setattr(trader, 'get_max_positions', lambda: 1)

    trader._hydra_available = False
    trader.current_regime_score = 0.72
    trader.current_universe = ['AAPL', 'MSFT']
    trader._hist_cache = {
        'AAPL': make_hist(100.0, 0.35),
        'MSFT': make_hist(100.0, 0.10),
    }
    trader._spy_hist = make_hist(430.0, 0.35, periods=260)
    trader._last_stop_check = datetime.now() - timedelta(hours=1)
    trader._last_state_save = datetime.now() - timedelta(hours=1)

    return trader


def test_run_once_executes_full_cycle_and_persists_state(trader, temp_runtime):
    result = trader.run_once()

    assert result is True
    assert 'AAPL' in trader.broker.positions
    assert 'AAPL' in trader.position_meta

    latest_state = temp_runtime / 'state' / 'compass_state_latest.json'
    assert latest_state.exists()

    state = json.loads(latest_state.read_text(encoding='utf-8'))
    assert state['positions']['AAPL']['shares'] > 0
    assert state['position_meta']['AAPL']['entry_price'] > 0
    assert state['trading_day_counter'] == 1

    decisions_file = temp_runtime / 'state' / 'ml_learning' / 'decisions.jsonl'
    snapshots_file = temp_runtime / 'state' / 'ml_learning' / 'daily_snapshots.jsonl'
    assert decisions_file.exists()
    assert snapshots_file.exists()

    decisions = [
        json.loads(line)
        for line in decisions_file.read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    decision_types = {record['decision_type'] for record in decisions}

    assert 'entry' in decision_types
    assert 'hold' in decision_types
    assert any(record['symbol'] == 'AAPL' for record in decisions if record['decision_type'] == 'entry')
    assert any(record['symbol'] == 'AAPL' for record in decisions if record['decision_type'] == 'hold')


def test_run_once_returns_false_without_crashing_on_sparse_market_data(trader):
    trader.data_feed.prices = {}

    result = trader.run_once()

    assert result is False
    assert trader.broker.positions == {}


def test_run_once_skips_when_market_data_is_stale(trader, caplog):
    trader.data_feed.cache_age_seconds = 180

    with caplog.at_level(logging.WARNING):
        result = trader.run_once()

    assert result is False
    assert trader.broker.positions == {}
    assert any('Skipping trading cycle due to stale market data' in record.message
               for record in caplog.records)


def test_run_once_logs_error_when_market_data_is_critically_stale(trader, caplog):
    trader.data_feed.cache_age_seconds = 360

    with caplog.at_level(logging.ERROR):
        result = trader.run_once()

    assert result is False
    assert any(record.levelno >= logging.ERROR
               and 'Skipping trading cycle due to stale market data' in record.message
               for record in caplog.records)


def test_run_once_ignores_stale_guard_when_market_is_closed(trader, caplog, monkeypatch):
    trader.data_feed.cache_age_seconds = 360
    monkeypatch.setattr(trader, 'is_market_open', lambda: False)

    with caplog.at_level(logging.WARNING):
        result = trader.run_once()

    assert result is False
    assert not any('Skipping trading cycle due to stale market data' in record.message
                   for record in caplog.records)


@pytest.mark.parametrize('fail_on', ['entry', 'hold', 'skip', 'snapshot'])
def test_ml_fail_safe_counters_increment_without_crashing(trader, temp_runtime, fail_on):
    trader.ml = FailingML(fail_on)

    result = trader.run_once()

    assert result is True
    assert live._ml_error_counts[fail_on] == 1

    latest_state = temp_runtime / 'state' / 'compass_state_latest.json'
    state = json.loads(latest_state.read_text(encoding='utf-8'))
    assert state['ml_error_counts'][fail_on] == 1


def test_ml_exit_fail_safe_counter_increments(trader):
    trader.current_universe = []
    trader.ml = FailingML('exit')

    buy_order = live.Order(symbol='AAPL', action='BUY', quantity=5, order_type='MARKET')
    buy_result = trader.broker.submit_order(buy_order)
    trader.position_meta['AAPL'] = {
        'entry_price': buy_result.filled_price,
        'entry_date': trader.get_et_now().date().isoformat(),
        'entry_day_index': 1,
        'original_entry_day_index': 1,
        'high_price': buy_result.filled_price,
        'entry_vol': 0.25,
        'entry_daily_vol': 0.016,
        'sector': 'Technology',
    }

    trader.check_position_exits({'AAPL': 125.0})

    assert live._ml_error_counts['exit'] == 1


def test_multi_day_cycle_with_stop_exit(monkeypatch, temp_runtime):
    trading_days = [
        datetime(2026, 3, 10, 15, 35),
        datetime(2026, 3, 11, 15, 35),
        datetime(2026, 3, 12, 15, 35),
        datetime(2026, 3, 13, 15, 35),
        datetime(2026, 3, 16, 15, 35),
    ]
    prices_by_day = {
        '2026-03-10': {
            'AAPL': 125.0,
            'MSFT': 120.0,
            'NVDA': 115.0,
            'AMZN': 110.0,
            'LLY': 108.0,
            'META': 106.0,
            'GOOGL': 104.0,
            'GE': 102.0,
            'SPY': 505.0,
        },
        '2026-03-11': {
            'AAPL': 128.0,
            'MSFT': 123.0,
            'NVDA': 118.0,
            'AMZN': 111.0,
            'LLY': 109.0,
            'META': 107.0,
            'GOOGL': 105.0,
            'GE': 103.0,
            'SPY': 506.0,
        },
        '2026-03-12': {
            'AAPL': 131.0,
            'MSFT': 125.0,
            'NVDA': 120.0,
            'AMZN': 112.0,
            'LLY': 110.0,
            'META': 108.0,
            'GOOGL': 106.0,
            'GE': 104.0,
            'SPY': 507.0,
        },
        '2026-03-13': {
            'AAPL': 132.0,
            'MSFT': 109.0,
            'NVDA': 121.0,
            'AMZN': 114.0,
            'LLY': 111.0,
            'META': 109.0,
            'GOOGL': 107.0,
            'GE': 105.0,
            'SPY': 508.0,
        },
        '2026-03-16': {
            'AAPL': 134.0,
            'MSFT': 110.0,
            'NVDA': 123.0,
            'AMZN': 116.0,
            'LLY': 112.0,
            'META': 112.0,
            'GOOGL': 110.0,
            'GE': 106.0,
            'SPY': 510.0,
        },
    }
    universe_by_day = {
        '2026-03-10': ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'LLY'],
        '2026-03-11': ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'LLY'],
        '2026-03-12': ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'LLY'],
        '2026-03-13': ['AAPL', 'NVDA', 'AMZN', 'LLY', 'META'],
        '2026-03-16': ['AAPL', 'NVDA', 'AMZN', 'LLY', 'META'],
    }
    preclose_universe_by_day = {
        '2026-03-16': ['AMZN', 'META', 'GOOGL', 'LLY', 'GE'],
    }
    hist_cache = {
        'AAPL': make_hist(100.0, 0.60),
        'MSFT': make_hist(100.0, 0.55),
        'NVDA': make_hist(100.0, 0.50),
        'AMZN': make_hist(100.0, 0.30),
        'LLY': make_hist(100.0, 0.28),
        'META': make_hist(100.0, 0.25),
        'GOOGL': make_hist(100.0, 0.20),
        'GE': make_hist(100.0, 0.15),
    }

    FrozenDateTime.current = trading_days[0]
    monkeypatch.setattr(live, 'datetime', FrozenDateTime)

    feed = MultiDayPriceFeed(prices_by_day, FrozenDateTime)
    monkeypatch.setattr(live, 'YahooDataFeed', lambda cache_duration: feed)
    monkeypatch.setattr(live, '_git_sync_available', False, raising=False)
    monkeypatch.setattr(live, '_overlay_available', False, raising=False)
    monkeypatch.setattr(live.yf, 'download', lambda *args, **kwargs: pd.DataFrame({
        'Close': [5000.0, 5010.0]
    }))

    live._ml_error_counts = {
        'entry': 0,
        'exit': 0,
        'hold': 0,
        'skip': 0,
        'snapshot': 0,
    }

    config = live.CONFIG.copy()
    config['BROKER_TYPE'] = 'PAPER'
    config['PAPER_INITIAL_CASH'] = 100000
    config['MIN_MOMENTUM_STOCKS'] = 1
    config['STATE_SAVE_INTERVAL'] = 0
    config['STOP_CHECK_INTERVAL'] = 0

    trader = live.COMPASSLive(config)
    trader.broker.connect()
    trader.broker.fill_delay = 0
    trader.validator.validate_batch = lambda raw_prices: raw_prices

    monkeypatch.setattr(trader, 'is_market_open', lambda: True)
    monkeypatch.setattr(trader, 'refresh_universe', lambda: None)
    monkeypatch.setattr(trader, 'refresh_daily_data', lambda: None)
    monkeypatch.setattr(trader, '_reconcile_entry_prices', lambda: None)
    monkeypatch.setattr(trader, 'update_regime', lambda: None)
    monkeypatch.setattr(trader, 'log_status', lambda prices: None)
    monkeypatch.setattr(trader, 'get_max_positions', lambda: 3)
    monkeypatch.setattr(trader, '_should_renew', lambda *args, **kwargs: False)
    monkeypatch.setattr(trader, '_reconstruct_close_portfolio',
                        lambda positions, cash: trader._pre_rotation_value)
    monkeypatch.setattr(trader, '_get_spy_close', lambda: 5100.0)

    trader._hydra_available = False
    trader.current_regime_score = 0.72
    trader._hist_cache = hist_cache
    trader._spy_hist = make_hist(430.0, 0.35, periods=260)
    trader._last_stop_check = FrozenDateTime.now() - timedelta(hours=1)
    trader._last_state_save = FrozenDateTime.now() - timedelta(hours=1)

    original_execute_trading_logic = trader.execute_trading_logic

    def execute_trading_logic_with_rotation(prices):
        original_execute_trading_logic(prices)
        rotation_universe = preclose_universe_by_day.get(
            FrozenDateTime.current.date().isoformat()
        )
        if rotation_universe is not None:
            trader.current_universe = rotation_universe

    monkeypatch.setattr(trader, 'execute_trading_logic', execute_trading_logic_with_rotation)

    for idx, when in enumerate(trading_days):
        FrozenDateTime.current = when
        trader.current_universe = universe_by_day[when.date().isoformat()]
        trader._last_stop_check = FrozenDateTime.now() - timedelta(hours=1)
        trader._last_state_save = FrozenDateTime.now() - timedelta(hours=1)

        result = trader.run_once()

        assert result is True

        if idx == 0:
            trader._ensure_active_cycle()

    cycle_log = json.loads((temp_runtime / 'state' / 'cycle_log.json').read_text(encoding='utf-8'))
    decisions = [
        json.loads(line)
        for line in (temp_runtime / 'state' / 'ml_learning' / 'decisions.jsonl').read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]
    latest_state = json.loads((temp_runtime / 'state' / 'compass_state_latest.json').read_text(encoding='utf-8'))

    decision_types = {record['decision_type'] for record in decisions}
    closed_cycles = [cycle for cycle in cycle_log if cycle.get('status') == 'closed']
    exit_records = [record for record in decisions if record.get('decision_type') == 'exit']
    closed_cycle = closed_cycles[0]
    positions_detail = closed_cycle.get('positions_detail', [])
    stop_details = [detail for detail in positions_detail if 'stop' in (detail.get('exit_reason') or '')]

    assert closed_cycles
    assert {'entry', 'hold', 'exit', 'skip'}.issubset(decision_types)
    assert any('stop' in (record.get('exit_reason') or '') for record in exit_records)
    assert any(event.get('reason') == 'position_stop' for event in closed_cycle.get('stop_events', []))
    assert positions_detail
    assert all(
        {'symbol', 'entry_price', 'exit_price', 'pnl_pct', 'exit_reason', 'sector', 'days_held'}
        <= set(detail.keys())
        for detail in positions_detail
    )
    assert stop_details
    assert any(detail['pnl_pct'] < 0 and detail['pnl_pct'] > -100 for detail in stop_details)
    assert any(event.get('return', 0) < 0 for event in closed_cycle.get('stop_events', []))
    assert closed_cycle.get('exits_by_reason', {}).get('stop_loss', 0) >= 1
    assert closed_cycle.get('sector_breakdown')
    assert closed_cycle.get('cycle_return_pct') is not None
    assert closed_cycle.get('spy_return_pct') is not None
    assert closed_cycle.get('alpha_pct') == pytest.approx(
        closed_cycle['cycle_return_pct'] - closed_cycle['spy_return_pct']
    )
    assert latest_state['trading_day_counter'] >= 5
    assert latest_state['portfolio_value'] != pytest.approx(100000.0)
    assert 'AMZN' in latest_state['positions']
    assert 'META' in latest_state['positions'] or 'GOOGL' in latest_state['positions']
