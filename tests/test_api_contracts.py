import json
import sys
import types
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import compass_dashboard_cloud as dashboard


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


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
    dashboard._cloud_engine = None
    dashboard._cloud_engine_thread = None
    dashboard._cloud_engine_started = False
    dashboard._self_ping_started = False
    dashboard._engine_status = {
        'running': False,
        'started_at': None,
        'error': None,
        'cycles': 0,
        'startup_started_at': None,
        'last_git_pull': None,
        'state_recovery': None,
    }

    yield tmp_path

    dashboard.app.before_request_funcs[None] = before_request


@pytest.fixture
def client():
    return dashboard.app.test_client()


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
    assert isinstance(payload['positions'], dict)
    assert isinstance(payload['cash'], float)
    assert isinstance(payload['portfolio_value'], float)
    assert isinstance(payload['regime_score'], float)
    assert isinstance(payload['trading_day_counter'], int)


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
    assert isinstance(payload[0]['cycle_number'], int)
    assert isinstance(payload[0]['start_date'], str)
    assert isinstance(payload[0]['end_date'], str)
    assert isinstance(payload[0]['cycle_return_pct'], float)


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
            'p25': [100000.0, 99500.0],
            'p50': [100000.0, 101000.0],
            'p75': [100000.0, 102500.0],
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
    assert set(data['fan_chart']) == {'days', 'p5', 'p25', 'p50', 'p75', 'p95'}
    assert isinstance(data['summary'], dict)
    assert data['seed'] == 666


def test_api_health_contract_exposes_top_level_aliases(client):
    write_json(Path('state/compass_state_latest.json'), make_state())
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
    assert isinstance(payload['status'], str)
    assert isinstance(payload['engine_running'], bool)
    assert isinstance(payload['price_freshness'], float)
    assert payload['engine_running'] is True
    assert payload['price_freshness'] < 60
