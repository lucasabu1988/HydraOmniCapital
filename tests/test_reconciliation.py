import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import omnicapital_live as live
from omnicapital_broker import Position


class DummyFeed:
    def get_prices(self, symbols):
        return {}

    def get_price(self, symbol):
        return None

    def get_cache_age_seconds(self):
        return 0


def read_jsonl(path):
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding='utf-8').splitlines()
        if line.strip()
    ]


def meta_for(symbol, entry_price=150.0):
    return {
        'entry_price': entry_price,
        'entry_date': '2026-03-16',
        'entry_day_index': 5,
        'original_entry_day_index': 5,
        'high_price': entry_price,
        'sector': live.SECTOR_MAP.get(symbol, 'Unknown'),
    }


@pytest.fixture
def trader(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(live, '_git_sync_available', False, raising=False)
    monkeypatch.setattr(live, '_ml_available', False, raising=False)
    monkeypatch.setattr(live, '_hydra_available', False, raising=False)
    monkeypatch.setattr(live, '_overlay_available', False, raising=False)
    monkeypatch.setattr(live, 'YahooDataFeed', lambda cache_duration: DummyFeed())
    monkeypatch.setattr(live.COMPASSLive, '_ensure_active_cycle', lambda self: None)

    config = live.CONFIG.copy()
    config['BROKER_TYPE'] = 'PAPER'
    config['PAPER_INITIAL_CASH'] = 100000

    trader = live.COMPASSLive(config)
    trader.broker.connect()
    trader.broker.fill_delay = 0
    trader.last_trading_date = date(2026, 3, 16)
    trader.trading_day_counter = 5
    return trader


def test_reconcile_runtime_state_adds_broker_only_position_and_writes_log(trader, tmp_path):
    trader.broker.cash = 98500.0
    trader.broker.positions['AAPL'] = Position('AAPL', 10, 150.0)
    trader._state_positions_snapshot = {}
    trader._state_cash_snapshot = 100000.0

    changed = trader._reconcile_runtime_state()

    assert changed is True
    assert 'AAPL' in trader.position_meta
    latest_state = json.loads((tmp_path / 'state' / 'compass_state_latest.json').read_text(encoding='utf-8'))
    assert latest_state['positions']['AAPL']['shares'] == pytest.approx(10.0)

    records = read_jsonl(tmp_path / 'state' / 'reconciliation_log.jsonl')
    assert any(item['status'] == 'broker_only_position' for item in records[-1]['mismatches'])


def test_reconcile_runtime_state_removes_phantom_state_position(trader, tmp_path):
    trader.position_meta['AAPL'] = meta_for('AAPL')
    trader._state_positions_snapshot = {'AAPL': {'shares': 10.0, 'avg_cost': 150.0}}
    trader._state_cash_snapshot = 98500.0
    trader.broker.cash = 100000.0

    changed = trader._reconcile_runtime_state()

    assert changed is True
    assert 'AAPL' not in trader.position_meta
    latest_state = json.loads((tmp_path / 'state' / 'compass_state_latest.json').read_text(encoding='utf-8'))
    assert latest_state['positions'] == {}

    records = read_jsonl(tmp_path / 'state' / 'reconciliation_log.jsonl')
    assert any(item['status'] == 'phantom_state_position' for item in records[-1]['mismatches'])


def test_reconcile_runtime_state_updates_share_and_cash_mismatches(trader, tmp_path):
    trader.broker.cash = 98200.0
    trader.broker.positions['AAPL'] = Position('AAPL', 12, 150.0)
    trader.position_meta['AAPL'] = meta_for('AAPL')
    trader._state_positions_snapshot = {'AAPL': {'shares': 10.0, 'avg_cost': 150.0}}
    trader._state_cash_snapshot = 99500.0

    changed = trader._reconcile_runtime_state()

    assert changed is True
    assert trader._state_positions_snapshot['AAPL']['shares'] == pytest.approx(12.0)
    assert trader._state_cash_snapshot == pytest.approx(98200.0)

    records = read_jsonl(tmp_path / 'state' / 'reconciliation_log.jsonl')
    statuses = {item['status'] for item in records[-1]['mismatches']}
    assert 'share_count_mismatch' in statuses
    assert 'cash_mismatch' in statuses


def test_reconcile_runtime_state_skips_when_env_flag_is_set(trader, monkeypatch, tmp_path):
    monkeypatch.setenv('SKIP_RECONCILIATION', '1')
    trader.broker.cash = 98500.0
    trader.broker.positions['AAPL'] = Position('AAPL', 10, 150.0)
    trader._state_positions_snapshot = {}
    trader._state_cash_snapshot = 100000.0

    changed = trader._reconcile_runtime_state()

    assert changed is False
    assert not (tmp_path / 'state' / 'reconciliation_log.jsonl').exists()
    assert trader._state_positions_snapshot == {}


def test_reconcile_runtime_state_prunes_strategy_lists_when_positions_disappear(trader):
    trader.rattle_positions = [{'symbol': 'AAPL', 'shares': 10, 'entry_price': 150.0, 'days_held': 1}]
    trader.catalyst_positions = [{'symbol': 'GLD', 'shares': 5, 'entry_price': 200.0, 'sub_strategy': 'gold'}]
    trader._state_positions_snapshot = {
        'AAPL': {'shares': 10.0, 'avg_cost': 150.0},
        'GLD': {'shares': 5.0, 'avg_cost': 200.0},
    }
    trader._state_cash_snapshot = 97500.0
    trader.broker.cash = 100000.0

    changed = trader._reconcile_runtime_state()

    assert changed is True
    assert trader.rattle_positions == []
    assert trader.catalyst_positions == []


def test_run_once_triggers_reconciliation_after_daily_open(trader, monkeypatch):
    calls = []

    monkeypatch.setattr(trader, 'is_market_open', lambda: True)
    monkeypatch.setattr(trader, 'is_new_trading_day', lambda: True)
    monkeypatch.setattr(trader, 'daily_open', lambda: None)
    monkeypatch.setattr(trader, '_reconcile_runtime_state', lambda: calls.append('reconciled'))
    monkeypatch.setattr(trader.data_feed, 'get_prices', lambda symbols: {})
    trader.validator.validate_batch = lambda raw_prices: raw_prices

    result = trader.run_once()

    assert result is False
    assert calls == ['reconciled']
