import json
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

    def get_prices(self, symbols):
        return {symbol: self.prices[symbol] for symbol in symbols if symbol in self.prices}

    def get_price(self, symbol):
        return self.prices.get(symbol)


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
