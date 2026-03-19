import json
import os
import sys
import time
import types
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import compass_dashboard_cloud as dashboard
import compass_dashboard as local_dashboard
from compass_api_models import (
    STATE_RESPONSE_REQUIRED_KEYS,
    CYCLE_LOG_ENTRY_REQUIRED_KEYS,
    MONTECARLO_RESPONSE_REQUIRED_KEYS,
    RISK_RESPONSE_REQUIRED_KEYS,
    HEALTH_RESPONSE_REQUIRED_KEYS,
    FAN_CHART_REQUIRED_KEYS,
)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


class FakeResponse:
    def __init__(self, status_code, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def make_state():
    return {
        'portfolio_value': 105000.0,
        'peak_value': 106000.0,
        'cash': 5000.0,
        'positions': {'AAPL': {'shares': 10, 'avg_cost': 100.0}},
        'position_meta': {
            'AAPL': {
                'entry_price': 100.0,
                'high_price': 110.0,
                'entry_day_index': 1,
                'entry_date': '2026-03-10',
                'sector': 'Technology',
                'entry_daily_vol': 0.02,
            }
        },
        'current_universe': ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META'],
        'universe_year': 2026,
        'current_regime_score': 0.72,
        'trading_day_counter': 6,
        'last_trading_date': '2026-03-13',
        'timestamp': '2026-03-16T09:30:00',
        'hydra': {'rattle_positions': [], 'catalyst_positions': []},
        'stats': {'cycles_completed': 5, 'engine_iterations': 42},
        'ml_error_counts': {
            'entry': 0,
            'exit': 0,
            'hold': 0,
            'skip': 0,
            'snapshot': 0,
        },
    }


@pytest.fixture(autouse=True)
def isolate_dashboard(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'state' / 'ml_learning').mkdir(parents=True, exist_ok=True)

    before_request = list(dashboard.app.before_request_funcs.get(None, []))
    dashboard.app.before_request_funcs[None] = []

    dashboard._price_cache = {}
    dashboard._prev_close_cache = {}
    dashboard._price_cache_time = None
    dashboard._yf_consecutive_failures = 0
    dashboard._montecarlo_cache = None
    dashboard._montecarlo_cache_signature = None
    dashboard._risk_cache = None
    dashboard._risk_cache_time = None
    dashboard._ultimate_risk_cache = None
    dashboard._ultimate_risk_cache_time = None
    dashboard._cloud_engine = None
    dashboard._cloud_engine_thread = None
    dashboard._cloud_engine_started = False
    dashboard._self_ping_started = False
    dashboard.STATE_DIR = 'state'
    dashboard.STATE_FILE = str(tmp_path / 'state' / 'compass_state_latest.json')
    dashboard._engine_lock = os.path.join(dashboard.STATE_DIR, '.cloud_engine.lock')
    dashboard._engine_status = {
        'running': False,
        'started_at': None,
        'error': None,
        'cycles': 0,
        'startup_started_at': None,
        'last_git_pull': None,
        'state_recovery': None,
        'crash_count': 0,
        'last_crash_at': None,
        'last_crash_error': None,
        'restarts': [],
    }

    yield tmp_path

    dashboard.app.before_request_funcs[None] = before_request


@pytest.fixture
def client():
    return dashboard.app.test_client()


@pytest.fixture
def local_isolate(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'state' / 'ml_learning').mkdir(parents=True, exist_ok=True)

    local_dashboard.STATE_FILE = str(tmp_path / 'state' / 'compass_state_latest.json')
    local_dashboard.STATE_DIR = 'state'
    local_dashboard.LOG_DIR = 'logs'
    local_dashboard._price_cache = {}
    local_dashboard._prev_close_cache = {}
    local_dashboard._price_cache_time = None
    local_dashboard._price_fetch_timestamp = 0
    local_dashboard._live_engine = None
    local_dashboard._engine_status = {
        'running': False,
        'started_at': None,
        'error': None,
        'cycles': 0,
    }

    yield tmp_path


@pytest.fixture
def local_client():
    return local_dashboard.app.test_client()


def test_api_state_contract_exposes_required_top_level_fields(client, monkeypatch):
    write_json(Path('state/compass_state_latest.json'), make_state())
    monkeypatch.setattr(dashboard, 'fetch_live_prices', lambda symbols: {'AAPL': 110.0, 'SPY': 500.0})
    monkeypatch.setattr(dashboard, 'compute_position_details', lambda state, prices: [{'symbol': 'AAPL'}])
    monkeypatch.setattr(dashboard, 'compute_portfolio_metrics', lambda state, prices: {
        'portfolio_value': 105000.0,
        'cash': 5000.0,
    })
    monkeypatch.setattr(dashboard, 'compute_hydra_data', lambda state, prices: {})

    response = client.get('/api/state')

    assert response.status_code == 200
    payload = response.get_json()
    missing = STATE_RESPONSE_REQUIRED_KEYS - payload.keys()
    assert not missing, f"StateResponse missing keys: {missing}"
    assert isinstance(payload['positions'], dict)
    assert isinstance(payload['cash'], float)
    assert isinstance(payload['portfolio_value'], float)
    assert isinstance(payload['regime_score'], float)
    assert isinstance(payload['trading_day_counter'], int)
    assert payload['_data_freshness']['status'] in {'live', 'stale', 'offline'}
    assert isinstance(payload['_data_freshness']['engine_alive'], bool)


def test_api_cycle_log_contract_exposes_cycle_number_alias(client):
    write_json(Path('state/cycle_log.json'), [{
        'cycle': 1,
        'status': 'closed',
        'start_date': '2026-03-10',
        'end_date': '2026-03-16',
        'cycle_return_pct': 2.5,
    }])

    response = client.get('/api/cycle-log')

    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, list)
    entry = payload[0]
    missing = CYCLE_LOG_ENTRY_REQUIRED_KEYS - entry.keys()
    assert not missing, f"CycleLogEntry missing keys: {missing}"
    assert isinstance(entry['cycle_number'], int)
    assert isinstance(entry['start_date'], str)
    assert isinstance(entry['end_date'], str)
    assert isinstance(entry['cycle_return_pct'], float)


def test_api_risk_contract_shape(client, monkeypatch):
    write_json(Path('state/compass_state_latest.json'), make_state())
    monkeypatch.setattr(dashboard, 'fetch_live_prices', lambda symbols: {'AAPL': 112.0, 'SPY': 500.0})
    monkeypatch.setattr(
        dashboard,
        '_fetch_risk_histories',
        lambda symbols: {
            'AAPL': pd.DataFrame({'Close': [100.0, 102.0, 101.0, 103.0]}),
            'SPY': pd.DataFrame({'Close': [400.0, 401.0, 403.0, 404.0]}),
        },
    )

    response = client.get('/api/risk')

    assert response.status_code == 200
    payload = response.get_json()
    missing = RISK_RESPONSE_REQUIRED_KEYS - payload.keys()
    assert not missing, f"RiskResponse missing keys: {missing}"
    assert isinstance(payload['risk_score'], float)
    assert isinstance(payload['risk_label'], str)
    assert isinstance(payload['var_95'], float)
    assert isinstance(payload['beta'], float)
    assert isinstance(payload['concentration_risk'], float)


def test_api_montecarlo_contract_shape(client, monkeypatch):
    payload = {
        'fan_chart': {
            'days': [0, 5],
            'p5': [100000.0, 98000.0],
            'p10': [100000.0, 98800.0],
            'p25': [100000.0, 99500.0],
            'p50': [100000.0, 101000.0],
            'p75': [100000.0, 102500.0],
            'p90': [100000.0, 103500.0],
            'p95': [100000.0, 104000.0],
        },
        'summary': {'median_outcome': 101000.0},
        'seed': 666,
        'source': 'live_cycle_log',
    }

    class FakeMonteCarlo:
        def run_all(self):
            return payload

    monkeypatch.setattr(dashboard, '_montecarlo_signature', lambda: ('stable',))
    monkeypatch.setitem(
        sys.modules,
        'compass_montecarlo',
        types.SimpleNamespace(COMPASSMonteCarlo=FakeMonteCarlo),
    )

    response = client.get('/api/montecarlo')

    assert response.status_code == 200
    data = response.get_json()
    missing = MONTECARLO_RESPONSE_REQUIRED_KEYS - data.keys()
    assert not missing, f"MonteCarloResponse missing keys: {missing}"
    assert set(data['fan_chart']) == FAN_CHART_REQUIRED_KEYS
    assert isinstance(data['summary'], dict)
    assert data['seed'] == 666


def test_api_health_contract_exposes_top_level_aliases(client):
    write_json(Path('state/compass_state_latest.json'), make_state())
    dashboard._cloud_engine_thread = types.SimpleNamespace(is_alive=lambda: True)
    dashboard._engine_status.update({
        'running': True,
        'started_at': '2026-03-16T09:00:00',
        'error': None,
        'cycles': 5,
    })
    dashboard._price_cache = {'AAPL': 110.0}
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=15)

    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.get_json()
    missing = HEALTH_RESPONSE_REQUIRED_KEYS - payload.keys()
    assert not missing, f"HealthResponse missing keys: {missing}"
    assert isinstance(payload['status'], str)
    assert isinstance(payload['engine_alive'], bool)
    assert isinstance(payload['price_age_seconds'], float)
    assert payload['engine_alive'] is True
    assert payload['price_age_seconds'] < 60
    assert isinstance(payload['crash_count'], int)
    assert isinstance(payload['restarts'], list)


def test_local_price_debug_contract_shape(local_client, local_isolate, monkeypatch):
    class FakeTicker:
        def __init__(self, symbol):
            self.fast_info = {'last_price': 123.45}

    monkeypatch.setattr(local_dashboard.yf, 'Ticker', FakeTicker)
    monkeypatch.setattr(
        local_dashboard.http_requests,
        'get',
        lambda *args, **kwargs: FakeResponse(
            200,
            payload={'chart': {'result': [{'meta': {'regularMarketPrice': 123.45}}]}},
        ),
    )

    response = local_client.get('/api/price-debug?symbol=AAPL')

    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload['server_time'], str)
    assert isinstance(payload['has_requests'], bool)
    assert isinstance(payload['cached_symbols'], list)
    assert payload['showcase_mode'] is False
    assert payload['tests']['v7_status'] == 200
    assert payload['tests']['v8_status'] == 200


def test_local_execution_stats_contract_shape(local_client, local_isolate):
    write_json(Path('state/compass_state_latest.json'), {
        **make_state(),
        'order_history': [
            {
                'status': 'filled',
                'expected_price': 100.0,
                'fill_price': 101.0,
            },
            {
                'status': 'cancelled',
                'reason': 'stale',
            },
        ],
    })

    response = local_client.get('/api/execution-stats')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['total_orders'] == 2
    assert isinstance(payload['fill_rate'], float)
    assert isinstance(payload['avg_fill_deviation_pct'], float)
    assert payload['stale_orders_cancelled'] == 1


def test_local_ml_diagnostics_contract_shape(local_client, local_isolate):
    ml_dir = Path('state/ml_learning')
    (ml_dir / 'decisions.jsonl').write_text(
        json.dumps({'timestamp': '2026-03-16T10:00:00', 'action': 'entry'}) + "\n",
        encoding='utf-8',
    )
    (ml_dir / 'outcomes.jsonl').write_text(
        json.dumps({'date': '2026-03-16', 'pnl': 120.0}) + "\n",
        encoding='utf-8',
    )

    response = local_client.get('/api/ml-diagnostics')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['phase'] == 1
    assert payload['total_decisions'] == 1
    assert payload['total_outcomes'] == 1
    assert payload['last_decision_date'] == '2026-03-16'
    assert payload['files_ok'] is True


@pytest.mark.parametrize('malicious_date', [
    '../../../etc/passwd',
    '2026-03-16; rm -rf /',
    '2026-03-16\x00.evil',
    '....//....//etc/passwd',
    '20260316',
    '',
    'not-a-date',
])
def test_agent_scratchpad_rejects_malicious_date(client, malicious_date):
    response = client.get(f'/api/agent-scratchpad?date={malicious_date}')
    assert response.status_code == 400
    payload = response.get_json()
    assert 'error' in payload


@pytest.mark.parametrize('malicious_date', [
    '../../../etc/passwd',
    '2026-03-16; rm -rf /',
    '2026-03-16\x00.evil',
    '....//....//etc/passwd',
    '20260316',
    '',
    'not-a-date',
])
def test_local_agent_scratchpad_rejects_malicious_date(local_client, local_isolate, malicious_date):
    response = local_client.get(f'/api/agent-scratchpad?date={malicious_date}')
    assert response.status_code == 400
    payload = response.get_json()
    assert 'error' in payload


def test_agent_scratchpad_accepts_valid_date(client):
    response = client.get('/api/agent-scratchpad?date=2026-03-16')
    assert response.status_code == 200


# ============================================================================
# ERROR RECOVERY TESTS — verify endpoints return valid JSON on data failures
# ============================================================================

def test_api_state_missing_state_file_returns_fallback_json(client):
    # No state file written — read_state() returns None
    response = client.get('/api/state')

    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict)
    missing = STATE_RESPONSE_REQUIRED_KEYS - payload.keys()
    assert not missing, f"StateResponse fallback missing keys: {missing}"
    assert payload['status'] in ('offline', 'starting')
    assert isinstance(payload['positions'], dict)
    assert payload['cash'] == 0.0
    assert payload['portfolio_value'] == 0.0
    assert payload['trading_day_counter'] == 0
    assert payload['_data_freshness']['status'] in {'stale', 'offline'}


def test_api_cycle_log_corrupted_file_returns_empty_list(client, isolate_dashboard):
    log_path = isolate_dashboard / 'state' / 'cycle_log.json'
    log_path.write_text('NOT VALID JSON {{{{', encoding='utf-8')

    response = client.get('/api/cycle-log')

    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, list)
    assert payload == []


def test_api_montecarlo_import_failure_returns_error_json(client, monkeypatch):
    monkeypatch.setattr(dashboard, '_montecarlo_signature', lambda: ('sig',))

    # Remove compass_montecarlo from sys.modules so import fails
    monkeypatch.delitem(sys.modules, 'compass_montecarlo', raising=False)

    # Inject a module whose COMPASSMonteCarlo raises on run_all
    class BrokenMonteCarlo:
        def run_all(self):
            raise RuntimeError('simulation exploded')

    monkeypatch.setitem(
        sys.modules,
        'compass_montecarlo',
        types.SimpleNamespace(COMPASSMonteCarlo=BrokenMonteCarlo),
    )

    response = client.get('/api/montecarlo')

    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict)
    assert 'error' in payload
    assert 'simulation exploded' in payload['error']


def test_api_health_missing_state_file_returns_valid_health(client):
    # No state file — health should still return valid JSON
    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict)
    missing = HEALTH_RESPONSE_REQUIRED_KEYS - payload.keys()
    assert not missing, f"HealthResponse fallback missing keys: {missing}"
    assert isinstance(payload['status'], str)
    assert isinstance(payload['engine_alive'], bool)


def test_api_annual_returns_missing_backtest_csv_returns_error_json(client, monkeypatch):
    # Ensure no cached equity_df and no CSV file exists
    monkeypatch.setattr(dashboard, '_equity_df', None)
    monkeypatch.setattr(dashboard, '_spy_df', None)

    response = client.get('/api/annual-returns')

    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict)
    assert 'error' in payload


def test_api_trade_analytics_computation_failure_returns_error_json(client, monkeypatch):
    # Clear cache so endpoint attempts fresh computation
    monkeypatch.setattr(dashboard, '_trade_analytics_cache', None)

    # Remove compass_trade_analytics from sys.modules so import fails
    monkeypatch.delitem(sys.modules, 'compass_trade_analytics', raising=False)

    class BrokenAnalytics:
        def run_all(self):
            raise ValueError('analytics computation failed')

    monkeypatch.setitem(
        sys.modules,
        'compass_trade_analytics',
        types.SimpleNamespace(COMPASSTradeAnalytics=BrokenAnalytics),
    )

    response = client.get('/api/trade-analytics')

    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, dict)
    assert 'error' in payload
    assert 'analytics computation failed' in payload['error']


# ============================================================================
# RESPONSE TIMING TESTS — verify endpoints respond within acceptable limits
# ============================================================================

@pytest.mark.xfail(reason="CI runners may be slow")
def test_api_state_timing(client, monkeypatch):
    write_json(Path('state/compass_state_latest.json'), make_state())
    monkeypatch.setattr(dashboard, 'fetch_live_prices', lambda symbols: {'AAPL': 110.0, 'SPY': 500.0})
    monkeypatch.setattr(dashboard, 'compute_position_details', lambda state, prices: [{'symbol': 'AAPL'}])
    monkeypatch.setattr(dashboard, 'compute_portfolio_metrics', lambda state, prices: {
        'portfolio_value': 105000.0,
        'cash': 5000.0,
    })
    monkeypatch.setattr(dashboard, 'compute_hydra_data', lambda state, prices: {})

    start = time.time()
    response = client.get('/api/state')
    elapsed = time.time() - start

    assert response.status_code == 200
    assert elapsed < 2.0, f"/api/state responded in {elapsed:.3f}s (limit 2.0s)"


@pytest.mark.xfail(reason="CI runners may be slow")
def test_api_cycle_log_timing(client):
    write_json(Path('state/cycle_log.json'), [{
        'cycle': 1,
        'status': 'closed',
        'start_date': '2026-03-10',
        'end_date': '2026-03-16',
        'cycle_return_pct': 2.5,
    }])

    start = time.time()
    response = client.get('/api/cycle-log')
    elapsed = time.time() - start

    assert response.status_code == 200
    assert elapsed < 2.0, f"/api/cycle-log responded in {elapsed:.3f}s (limit 2.0s)"


@pytest.mark.xfail(reason="CI runners may be slow")
def test_api_montecarlo_timing(client, monkeypatch):
    payload = {
        'fan_chart': {
            'days': [0, 5],
            'p5': [100000.0, 98000.0],
            'p10': [100000.0, 98800.0],
            'p25': [100000.0, 99500.0],
            'p50': [100000.0, 101000.0],
            'p75': [100000.0, 102500.0],
            'p90': [100000.0, 103500.0],
            'p95': [100000.0, 104000.0],
        },
        'summary': {'median_outcome': 101000.0},
        'seed': 666,
        'source': 'live_cycle_log',
    }

    class FakeMonteCarlo:
        def run_all(self):
            return payload

    monkeypatch.setattr(dashboard, '_montecarlo_signature', lambda: ('stable',))
    monkeypatch.setitem(
        sys.modules,
        'compass_montecarlo',
        types.SimpleNamespace(COMPASSMonteCarlo=FakeMonteCarlo),
    )

    start = time.time()
    response = client.get('/api/montecarlo')
    elapsed = time.time() - start

    assert response.status_code == 200
    assert elapsed < 2.0, f"/api/montecarlo responded in {elapsed:.3f}s (limit 2.0s)"


@pytest.mark.xfail(reason="CI runners may be slow")
def test_api_health_timing(client):
    write_json(Path('state/compass_state_latest.json'), make_state())
    dashboard._cloud_engine_thread = types.SimpleNamespace(is_alive=lambda: True)
    dashboard._engine_status.update({
        'running': True,
        'started_at': '2026-03-16T09:00:00',
        'error': None,
        'cycles': 5,
    })
    dashboard._price_cache = {'AAPL': 110.0}
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=15)

    start = time.time()
    response = client.get('/api/health')
    elapsed = time.time() - start

    assert response.status_code == 200
    assert elapsed < 2.0, f"/api/health responded in {elapsed:.3f}s (limit 2.0s)"


@pytest.mark.xfail(reason="CI runners may be slow")
def test_api_annual_returns_timing(client, monkeypatch):
    monkeypatch.setattr(dashboard, '_equity_df', None)
    monkeypatch.setattr(dashboard, '_spy_df', None)

    start = time.time()
    response = client.get('/api/annual-returns')
    elapsed = time.time() - start

    assert response.status_code == 200
    assert elapsed < 2.0, f"/api/annual-returns responded in {elapsed:.3f}s (limit 2.0s)"
