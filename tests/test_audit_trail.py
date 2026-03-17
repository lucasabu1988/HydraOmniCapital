import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import omnicapital_live as live
from omnicapital_broker import Position


class StubPriceFeed:
    def __init__(self, prices):
        self.prices = dict(prices)

    def get_prices(self, symbols):
        return {s: self.prices[s] for s in symbols if s in self.prices}

    def get_price(self, symbol):
        return self.prices.get(symbol)

    def get_cache_age_seconds(self):
        return 0


@pytest.fixture
def temp_runtime(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(live, '_git_sync_available', False, raising=False)
    live._ml_error_counts = {
        'entry': 0, 'exit': 0, 'hold': 0, 'skip': 0, 'snapshot': 0,
    }
    return tmp_path


@pytest.fixture
def trader(monkeypatch, temp_runtime):
    feed = StubPriceFeed({'AAPL': 150.0, 'MSFT': 300.0, 'SPY': 500.0})
    monkeypatch.setattr(live, 'YahooDataFeed', lambda cache_duration: feed)

    config = live.CONFIG.copy()
    config['BROKER_TYPE'] = 'PAPER'
    config['PAPER_INITIAL_CASH'] = 100_000
    config['MIN_MOMENTUM_STOCKS'] = 1
    config['STATE_SAVE_INTERVAL'] = 0
    config['STOP_CHECK_INTERVAL'] = 0

    engine = live.COMPASSLive(config)
    engine.broker.connect()
    engine.broker.fill_delay = 0
    engine.validator.validate_batch = lambda raw_prices: raw_prices
    engine._hydra_available = False
    return engine


def test_audit_log_on_position_change(trader, temp_runtime):
    audit_path = temp_runtime / 'state' / 'audit_log.jsonl'

    # First save — no prior positions, no changes expected
    trader.save_state()
    assert not audit_path.exists() or audit_path.read_text().strip() == ''

    # Add a position and save
    trader.broker.positions['AAPL'] = Position('AAPL', 10, 150.0)
    trader.save_state()

    assert audit_path.exists()
    lines = [l for l in audit_path.read_text().splitlines() if l.strip()]
    assert len(lines) == 1

    entry = json.loads(lines[0])
    assert entry['event_type'] == 'position_change'
    assert 'AAPL' in entry['details']['added']
    assert entry['details']['removed'] == []
    assert 'timestamp' in entry
    assert 'portfolio_value' in entry
    assert 'num_positions' in entry

    # Remove AAPL, add MSFT
    del trader.broker.positions['AAPL']
    trader.broker.positions['MSFT'] = Position('MSFT', 5, 300.0)
    trader.save_state()

    lines = [l for l in audit_path.read_text().splitlines() if l.strip()]
    assert len(lines) == 2
    entry2 = json.loads(lines[1])
    assert 'MSFT' in entry2['details']['added']
    assert 'AAPL' in entry2['details']['removed']


def test_audit_log_no_entry_when_no_change(trader, temp_runtime):
    audit_path = temp_runtime / 'state' / 'audit_log.jsonl'

    trader.broker.positions['AAPL'] = Position('AAPL', 10, 150.0)
    trader.save_state()  # records the add

    trader.save_state()  # no change — should not add another line

    lines = [l for l in audit_path.read_text().splitlines() if l.strip()]
    assert len(lines) == 1


def test_audit_log_caps_at_10000(trader, temp_runtime):
    audit_path = temp_runtime / 'state' / 'audit_log.jsonl'
    os.makedirs(temp_runtime / 'state', exist_ok=True)

    # Pre-fill with 10,000 lines
    with open(audit_path, 'w') as f:
        for i in range(10_000):
            f.write(json.dumps({'event_type': 'filler', 'i': i}) + '\n')

    # Trigger one more audit line
    trader.broker.positions['AAPL'] = Position('AAPL', 10, 150.0)
    trader.save_state()

    lines = [l for l in audit_path.read_text().splitlines() if l.strip()]
    assert len(lines) == 10_000
    # Last line should be the real position_change
    last = json.loads(lines[-1])
    assert last['event_type'] == 'position_change'
