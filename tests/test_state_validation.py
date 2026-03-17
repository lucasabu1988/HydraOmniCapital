import json
import os
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import compass_dashboard
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
            'cycles_completed': 0,
            'engine_iterations': 1,
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


def configure_run_once_after_recovery(monkeypatch, trader):
    monkeypatch.setattr(trader, 'is_market_open', lambda: True)
    monkeypatch.setattr(trader, 'is_new_trading_day', lambda: False)
    monkeypatch.setattr(trader, 'is_preclose_window', lambda: False)
    monkeypatch.setattr(trader, 'execute_trading_logic', lambda prices: None)
    monkeypatch.setattr(trader, 'log_status', lambda prices: None)

    trader.current_universe = ['AAPL']
    trader.config['STATE_SAVE_INTERVAL'] = 0
    trader.validator.validate_batch = lambda raw_prices: raw_prices
    trader.data_feed.get_prices = lambda symbols: {'AAPL': 150.0} if 'AAPL' in symbols else {}
    trader._last_state_save = datetime.now() - timedelta(seconds=5)


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
    assert state['stats']['engine_iterations'] == 2
    assert state['stats']['cycles_completed'] == 0


def test_save_state_tracks_closed_cycles_separately_from_engine_iterations(trader, tmp_path):
    write_json(
        tmp_path / 'state' / 'cycle_log.json',
        [
            {'cycle': 1, 'status': 'closed'},
            {'cycle': 2, 'status': 'active'},
        ],
    )
    trader.trading_day_counter = 5
    trader._cycles_completed = 384

    trader.save_state()

    state = read_json(tmp_path / 'state' / 'compass_state_latest.json')
    assert state['stats']['cycles_completed'] == 1
    assert state['stats']['engine_iterations'] == 384


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


def test_load_state_caps_unreasonably_high_peak_in_early_days(trader, tmp_path):
    latest_state = make_state(
        trading_day_counter=1,
        portfolio_value=100000.0,
        peak_value=125000.0,
        positions={'AAPL': {'shares': 10, 'avg_cost': 150.0}},
        position_meta={
            'AAPL': {
                'entry_price': 150.0,
                'entry_date': '2026-03-16',
                'entry_day_index': 1,
                'original_entry_day_index': 1,
                'high_price': 150.0,
                'sector': 'Technology',
            }
        },
    )
    write_json(tmp_path / 'state' / 'compass_state_latest.json', latest_state)

    trader.load_state()

    assert trader.peak_value == pytest.approx(100000.0)


def test_load_state_caps_peak_at_exact_early_day_threshold(trader, tmp_path):
    latest_state = make_state(
        trading_day_counter=1,
        portfolio_value=100000.0,
        peak_value=120000.0,
        positions={'AAPL': {'shares': 10, 'avg_cost': 150.0}},
        position_meta={
            'AAPL': {
                'entry_price': 150.0,
                'entry_date': '2026-03-16',
                'entry_day_index': 1,
                'original_entry_day_index': 1,
                'high_price': 150.0,
                'sector': 'Technology',
            }
        },
    )
    write_json(tmp_path / 'state' / 'compass_state_latest.json', latest_state)

    trader.load_state()

    assert trader.peak_value == pytest.approx(100000.0)


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


def test_try_load_json_returns_none_for_invalid_json(trader, tmp_path):
    state_path = tmp_path / 'state' / 'compass_state_latest.json'
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text('{"cash": ', encoding='utf-8')

    assert trader._try_load_json(state_path) is None


def test_load_state_repairs_missing_cash_with_default_balance(trader, tmp_path):
    latest_state = make_state()
    del latest_state['cash']
    write_json(tmp_path / 'state' / 'compass_state_latest.json', latest_state)

    trader.load_state()

    assert trader.broker.cash == pytest.approx(trader.config['PAPER_INITIAL_CASH'])
    assert trader._state_cash_snapshot == pytest.approx(trader.config['PAPER_INITIAL_CASH'])


def test_load_state_repairs_missing_positions_with_empty_dict(trader, tmp_path):
    latest_state = make_state(cash=76543.21)
    del latest_state['positions']
    write_json(tmp_path / 'state' / 'compass_state_latest.json', latest_state)

    trader.load_state()

    assert trader.broker.cash == pytest.approx(76543.21)
    assert trader.broker.positions == {}
    assert trader._state_positions_snapshot == {}


def test_load_state_sanitizes_nan_portfolio_values(trader, tmp_path):
    latest_state = make_state(
        portfolio_value=float('nan'),
        peak_value=float('nan'),
    )
    write_json(tmp_path / 'state' / 'compass_state_latest.json', latest_state)

    trader.load_state()

    assert trader.peak_value == pytest.approx(trader.config['PAPER_INITIAL_CASH'])
    assert trader.broker.cash == pytest.approx(trader.config['PAPER_INITIAL_CASH'])


def test_validate_state_flags_negative_cash(trader):
    repaired_state, violations = trader._validate_state(
        make_state(cash=-25.0),
        source='load',
    )

    assert repaired_state['cash'] == 0.0
    assert any('cash=-25.00 cannot be negative' in violation for violation in violations)


def test_load_state_recovers_from_corrupt_latest_and_run_once_succeeds(trader, tmp_path, monkeypatch):
    dated_state = make_state(
        cash=54321.0,
        current_universe=['AAPL'],
    )
    write_json(tmp_path / 'state' / 'compass_state_20260315.json', dated_state)

    latest_path = tmp_path / 'state' / 'compass_state_latest.json'
    latest_path.write_text('{"cash": ', encoding='utf-8')

    trader.load_state()

    assert trader.broker.cash == pytest.approx(54321.0)

    configure_run_once_after_recovery(monkeypatch, trader)
    result = trader.run_once()

    assert result is True
    latest_state = read_json(latest_path)
    assert latest_state['cash'] == pytest.approx(54321.0)
    assert latest_state['positions'] == {}


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
    assert state['stats']['engine_iterations'] == 3


def test_state_file_remains_valid_during_concurrent_save_and_read(trader, tmp_path, monkeypatch):
    state_dir = tmp_path / 'state'
    latest_path = state_dir / 'compass_state_latest.json'

    monkeypatch.setattr(compass_dashboard, 'STATE_DIR', str(state_dir))
    monkeypatch.setattr(compass_dashboard, 'STATE_FILE', str(latest_path))
    monkeypatch.setattr(compass_dashboard.time_module, 'sleep', lambda _: None)

    trader.trading_day_counter = 7
    trader.current_universe = ['AAPL']
    trader.save_state()

    errors = []
    read_results = []
    barrier = threading.Barrier(10)

    def writer(writer_idx):
        base_cash = 100000 + (writer_idx * 1000)
        try:
            for iteration in range(10):
                barrier.wait(timeout=5)
                trader.broker.cash = base_cash + iteration
                trader.peak_value = max(trader.peak_value, trader.broker.cash)
                trader.save_state()
        except Exception as exc:
            errors.append(exc)

    def dashboard_reader():
        try:
            for _ in range(10):
                barrier.wait(timeout=5)
                state = compass_dashboard.read_state()
                if not isinstance(state, dict):
                    errors.append(RuntimeError('dashboard reader returned non-dict state'))
                    continue
                read_results.append(state.get('cash'))
        except Exception as exc:
            errors.append(exc)

    def engine_reader():
        try:
            for _ in range(10):
                barrier.wait(timeout=5)
                state = trader._try_load_json(latest_path)
                if not isinstance(state, dict):
                    errors.append(RuntimeError('engine reader returned non-dict state'))
                    continue
                read_results.append(state.get('cash'))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=writer, args=(idx,)) for idx in range(5)]
    threads.extend(threading.Thread(target=dashboard_reader) for _ in range(3))
    threads.extend(threading.Thread(target=engine_reader) for _ in range(2))

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    final_state = read_json(latest_path)

    assert errors == []
    assert len(read_results) == 50
    assert isinstance(final_state, dict)
    assert 'cash' in final_state
    assert 'positions' in final_state


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


# --- State schema validation tests ---

def _valid_schema_state():
    return {
        'cash': 50000.0,
        'positions': {'AAPL': {'shares': 10, 'avg_cost': 150.0}},
        'portfolio_value': 51500.0,
        'peak_value': 52000.0,
        'trading_day_counter': 5,
    }


def test_validate_state_schema_valid_state(trader):
    violations = trader._validate_state_schema(_valid_schema_state())
    assert violations == []


def test_validate_state_schema_negative_cash(trader):
    state = _valid_schema_state()
    state['cash'] = -500.0
    violations = trader._validate_state_schema(state)
    assert len(violations) == 1
    assert "'cash' must be >= 0" in violations[0]


def test_validate_state_schema_missing_positions(trader):
    state = _valid_schema_state()
    del state['positions']
    violations = trader._validate_state_schema(state)
    assert len(violations) == 1
    assert "missing required field 'positions'" in violations[0]


def test_validate_state_schema_nan_portfolio_value(trader):
    state = _valid_schema_state()
    state['portfolio_value'] = float('nan')
    violations = trader._validate_state_schema(state)
    assert len(violations) == 1
    assert "'portfolio_value' must be finite" in violations[0]


def test_cleanup_corrupted_backups_keeps_max_files(trader, tmp_path):
    state_dir = tmp_path / 'state'
    state_dir.mkdir(parents=True, exist_ok=True)
    for idx in range(15):
        fpath = state_dir / f'compass_state_CORRUPTED_20260316_120000_{idx:06d}.json'
        fpath.write_text('{}', encoding='utf-8')

    trader._cleanup_old_corrupted_backups(max_age_days=365, max_files=10)

    remaining = sorted(state_dir.glob('compass_state_CORRUPTED_*.json'))
    assert len(remaining) == 10
    assert remaining[0].name == 'compass_state_CORRUPTED_20260316_120000_000005.json'


def test_cycle_log_write_is_thread_safe(trader, tmp_path):
    state_dir = tmp_path / 'state'
    state_dir.mkdir(parents=True, exist_ok=True)
    log_file = state_dir / 'cycle_log.json'
    # Seed with one active cycle
    initial_cycle = [{
        'cycle': 1,
        'start_date': '2026-03-10',
        'end_date': None,
        'status': 'active',
        'portfolio_start': 100000.0,
        'portfolio_end': None,
        'spy_start': 5000.0,
        'spy_end': None,
        'positions': ['AAPL'],
        'positions_current': ['AAPL'],
        'hydra_return': None,
        'spy_return': None,
        'alpha': None,
        'stop_events': [],
        'positions_detail': [],
        'sector_breakdown': {},
        'exits_by_reason': {},
        'cycle_return_pct': None,
        'spy_return_pct': None,
        'alpha_pct': None,
    }]
    log_file.write_text(json.dumps(initial_cycle, indent=2), encoding='utf-8')

    errors = []

    def worker(idx):
        try:
            trader._update_cycle_log_stop(
                stopped_symbol=f'SYM{idx}',
                replacement_symbol=f'REP{idx}',
                exit_reason='position_stop',
                stop_return=-0.05,
                stop_details={'exit_price': 95.0, 'entry_price': 100.0,
                              'sector': 'Technology', 'days_held': 3},
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    # File must be valid JSON after all concurrent writes
    data = json.loads(log_file.read_text(encoding='utf-8'))
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]['status'] == 'active'
    # All 5 stop events should be recorded
    assert len(data[0]['stop_events']) == 5


def test_cleanup_corrupted_backups_deletes_old_files_first(trader, tmp_path):
    state_dir = tmp_path / 'state'
    state_dir.mkdir(parents=True, exist_ok=True)
    old_time = time.time() - (8 * 86400)
    recent_time = time.time()

    for idx in range(5):
        fpath = state_dir / f'compass_state_CORRUPTED_20260301_120000_{idx:06d}.json'
        fpath.write_text('{}', encoding='utf-8')
        os.utime(str(fpath), (old_time, old_time))

    for idx in range(5):
        fpath = state_dir / f'compass_state_CORRUPTED_20260316_120000_{idx:06d}.json'
        fpath.write_text('{}', encoding='utf-8')
        os.utime(str(fpath), (recent_time, recent_time))

    trader._cleanup_old_corrupted_backups(max_age_days=7, max_files=10)

    remaining = sorted(state_dir.glob('compass_state_CORRUPTED_*.json'))
    assert len(remaining) == 5
    for f in remaining:
        assert '20260316' in f.name
