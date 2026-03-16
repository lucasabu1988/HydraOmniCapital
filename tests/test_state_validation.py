import json
import sys
import threading
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


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def make_state(**overrides):
    payload = {
        'version': '8.4',
        'timestamp': '2026-03-16T10:00:00',
        'cash': 100000.0,
        'peak_value': 100000.0,
        'portfolio_value': 100000.0,
        'crash_cooldown': 0,
        'portfolio_values_history': [],
        'current_regime_score': 0.5,
        'trading_day_counter': 5,
        'last_trading_date': '2026-03-16',
        'positions': {},
        'position_meta': {},
        'current_universe': ['AAPL', 'MSFT'],
        'universe_year': 2026,
        '_universe_source': '',
        '_daily_open_done': False,
        '_preclose_entries_done': False,
        'overlay': {},
        'hydra': {
            'available': False,
            'rattle_positions': [],
            'rattle_regime': 'RISK_ON',
            'vix_current': None,
            'efa_position': None,
            'catalyst_positions': [],
            'catalyst_day_counter': 0,
            'capital_manager': None,
        },
        '_pre_rotation_positions_data': {},
        '_pre_rotation_cash': None,
        '_pre_rotation_value': None,
        'stats': {
            'cycles_completed': 1,
            'uptime_minutes': 5,
        },
        'ml_error_counts': {
            'entry': 0,
            'exit': 0,
            'hold': 0,
            'skip': 0,
            'snapshot': 0,
        },
    }
    payload.update(overrides)
    return payload


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
    trader.last_trading_date = date(2026, 3, 16)
    return trader


def test_save_state_raises_peak_to_current_portfolio(trader, tmp_path):
    trader.trading_day_counter = 5
    trader.peak_value = 90000

    trader.save_state()

    state = read_json(tmp_path / 'state' / 'compass_state_latest.json')
    assert state['peak_value'] == pytest.approx(100000.0)


def test_save_state_caps_peak_to_sanity_limit(trader, tmp_path):
    trader.trading_day_counter = 5
    trader.peak_value = 700000

    trader.save_state()

    state = read_json(tmp_path / 'state' / 'compass_state_latest.json')
    assert state['peak_value'] == pytest.approx(500000.0)


def test_save_state_resets_early_peak_without_positions(trader, tmp_path):
    trader.trading_day_counter = 1
    trader.peak_value = 120000

    trader.save_state()

    state = read_json(tmp_path / 'state' / 'compass_state_latest.json')
    assert state['peak_value'] == pytest.approx(100000.0)


def test_save_state_clamps_negative_cash_and_writes_backup(trader, tmp_path):
    trader.trading_day_counter = 5
    trader.broker.cash = -50

    trader.save_state()

    state = read_json(tmp_path / 'state' / 'compass_state_latest.json')
    backups = list((tmp_path / 'state').glob('compass_state_CORRUPTED_*.json'))

    assert state['cash'] == 0.0
    assert backups


def test_save_state_repairs_non_positive_portfolio_value(trader, tmp_path):
    trader.trading_day_counter = 5
    trader.broker.cash = 0

    trader.save_state()

    state = read_json(tmp_path / 'state' / 'compass_state_latest.json')
    assert state['portfolio_value'] == pytest.approx(100000.0)


def test_save_state_caps_cycles_completed_jump_between_saves(trader, tmp_path):
    trader.trading_day_counter = 5
    trader._cycles_completed = 1
    trader.save_state()

    trader._cycles_completed = 20
    trader.save_state()

    state = read_json(tmp_path / 'state' / 'compass_state_latest.json')
    assert state['stats']['cycles_completed'] == 2


def test_save_state_prevents_trading_day_counter_decrease(trader, tmp_path):
    trader.trading_day_counter = 3
    trader.save_state()

    trader.trading_day_counter = 1
    trader.save_state()

    state = read_json(tmp_path / 'state' / 'compass_state_latest.json')
    assert state['trading_day_counter'] == 3
    assert trader.trading_day_counter == 3


def test_save_state_creates_missing_position_meta(trader, tmp_path):
    trader.trading_day_counter = 5
    trader.broker.positions['AAPL'] = Position('AAPL', 10, 150.0)
    trader.position_meta = {}

    trader.save_state()

    state = read_json(tmp_path / 'state' / 'compass_state_latest.json')
    assert 'AAPL' in state['position_meta']
    assert state['position_meta']['AAPL']['entry_price'] == pytest.approx(150.0)
    assert state['position_meta']['AAPL']['sector'] == 'Technology'


def test_load_state_repairs_invalid_fields_from_disk(trader, tmp_path):
    invalid_state = make_state(
        cash=-25.0,
        peak_value=1000.0,
        portfolio_value=-10.0,
        positions={'AAPL': {'shares': 10, 'avg_cost': 150.0}},
        position_meta={},
    )
    write_json(tmp_path / 'state' / 'compass_state_latest.json', invalid_state)

    trader.load_state()

    assert trader.broker.cash == 0.0
    assert trader.peak_value == pytest.approx(1500.0)
    assert trader.position_meta['AAPL']['entry_price'] == pytest.approx(150.0)


def test_load_state_caps_cycle_jump_using_previous_fallback_state(trader, tmp_path):
    previous_state = make_state(stats={'cycles_completed': 2, 'uptime_minutes': 1})
    latest_state = make_state(stats={'cycles_completed': 10, 'uptime_minutes': 5})
    write_json(tmp_path / 'state' / 'compass_state_20260315.json', previous_state)
    write_json(tmp_path / 'state' / 'compass_state_latest.json', latest_state)

    trader.load_state()

    assert trader._last_persisted_cycles_completed == 3


def test_load_state_prevents_trading_day_counter_decrease_vs_previous_file(trader, tmp_path):
    previous_state = make_state(trading_day_counter=4)
    latest_state = make_state(trading_day_counter=1)
    write_json(tmp_path / 'state' / 'compass_state_20260315.json', previous_state)
    write_json(tmp_path / 'state' / 'compass_state_latest.json', latest_state)

    trader.load_state()

    assert trader.trading_day_counter == 4


def test_load_state_resets_non_dict_sections(trader, tmp_path):
    invalid_state = make_state(
        positions=[],
        position_meta='bad',
        stats='broken',
    )
    write_json(tmp_path / 'state' / 'compass_state_latest.json', invalid_state)

    trader.load_state()

    assert trader.position_meta == {}
    assert trader.broker.positions == {}
    assert trader._last_persisted_cycles_completed == 0


def test_save_state_is_thread_safe_under_concurrent_calls(trader, tmp_path):
    trader.trading_day_counter = 7
    trader._cycles_completed = 3
    trader.broker.positions['AAPL'] = Position('AAPL', 10, 150.0)
    trader.position_meta['AAPL'] = {
        'entry_price': 150.0,
        'entry_date': '2026-03-16',
        'entry_day_index': 7,
        'original_entry_day_index': 7,
        'high_price': 150.0,
        'sector': 'Technology',
    }

    errors = []

    def worker():
        try:
            for _ in range(10):
                trader.save_state()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    state = read_json(tmp_path / 'state' / 'compass_state_latest.json')

    assert errors == []
    assert trader._last_persisted_trading_day_counter == 7
    assert trader._last_persisted_cycles_completed == 3
    assert state['trading_day_counter'] == 7
    assert state['stats']['cycles_completed'] == 3


def test_write_corrupted_state_backup_prunes_old_files(trader, tmp_path):
    state_dir = tmp_path / 'state'
    state_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(25):
        backup_path = state_dir / f'compass_state_CORRUPTED_20260316_120000_{idx:06d}.json'
        backup_path.write_text('{}', encoding='utf-8')

    backup_path = trader._write_corrupted_state_backup(make_state(cash=-1.0), ['cash invalid'])
    backups = sorted(state_dir.glob('compass_state_CORRUPTED_*.json'))

    assert backup_path is not None
    assert len(backups) == 20
    assert backups[0].name == 'compass_state_CORRUPTED_20260316_120000_000006.json'
