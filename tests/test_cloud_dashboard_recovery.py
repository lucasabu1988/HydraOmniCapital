import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import compass_dashboard_cloud as dashboard


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


def make_state():
    return {
        'portfolio_value': 105000.0,
        'peak_value': 106000.0,
        'cash': 5000.0,
        'positions': {'AAPL': {'shares': 10, 'avg_cost': 100.0}},
        'position_meta': {},
        'current_universe': ['AAPL', 'MSFT'],
        'universe_year': 2026,
        'current_regime_score': 0.72,
        'current_regime': True,
        'regime_consecutive': 3,
        'trading_day_counter': 6,
        'last_trading_date': '2026-03-13',
        'timestamp': '2026-03-16T09:30:00',
    }


@pytest.fixture(autouse=True)
def isolate_dashboard(monkeypatch, tmp_path):
    state_dir = tmp_path / 'state'
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dashboard, 'STATE_DIR', str(state_dir))
    monkeypatch.setattr(dashboard, 'STATE_FILE', str(state_dir / 'compass_state_latest.json'))
    dashboard._engine_status['state_recovery'] = None
    yield tmp_path


def test_validate_recovered_state_accepts_valid_payload():
    state = make_state()

    recovered = dashboard._validate_recovered_state(state, 'git_pull')

    assert recovered == state


def test_validate_recovered_state_rejects_missing_cash():
    state = make_state()
    del state['cash']

    recovered = dashboard._validate_recovered_state(state, 'git_pull')

    assert recovered is None


def test_validate_recovered_state_rejects_nan_portfolio_value():
    state = make_state()
    state['portfolio_value'] = float('nan')

    recovered = dashboard._validate_recovered_state(state, 'github_api')

    assert recovered is None


def test_build_default_state_returns_required_bootstrap_keys():
    state = dashboard._build_default_state()

    assert state['cash'] == dashboard.HYDRA_CONFIG['INITIAL_CAPITAL']
    assert state['portfolio_value'] == dashboard.HYDRA_CONFIG['INITIAL_CAPITAL']
    assert state['peak_value'] == dashboard.HYDRA_CONFIG['INITIAL_CAPITAL']
    assert state['positions'] == {}
    assert state['position_meta'] == {}
    assert state['trading_day_counter'] == 0
    assert '_recovered_from' not in state


def test_recover_cloud_state_uses_local_state_when_valid():
    state = make_state()
    write_json(Path(dashboard.STATE_FILE), state)

    recovered = dashboard._recover_cloud_state({'ok': True, 'message': 'Already up to date.'})

    assert recovered['_recovered_from'] == 'git_pull'
    assert recovered['cash'] == state['cash']
    assert recovered['positions'] == state['positions']


def test_recover_cloud_state_uses_github_fallback_when_local_state_is_invalid(monkeypatch):
    invalid_state = make_state()
    invalid_state['portfolio_value'] = float('nan')
    write_json(Path(dashboard.STATE_FILE), invalid_state)
    monkeypatch.setattr(dashboard, '_HAS_REQUESTS', True)
    monkeypatch.setattr(
        dashboard.http_requests,
        'get',
        lambda *args, **kwargs: FakeResponse(200, payload=make_state()),
    )

    recovered = dashboard._recover_cloud_state({'ok': False, 'message': 'auth failed'})

    assert recovered['_recovered_from'] == 'github_api'
    assert recovered['cash'] == 5000.0
    stored = json.loads(Path(dashboard.STATE_FILE).read_text(encoding='utf-8'))
    assert stored['_recovered_from'] == 'github_api'


def test_recover_cloud_state_falls_back_to_default_when_all_sources_are_invalid(monkeypatch):
    invalid_state = make_state()
    invalid_state['cash'] = float('inf')
    write_json(Path(dashboard.STATE_FILE), invalid_state)
    monkeypatch.setattr(dashboard, '_HAS_REQUESTS', True)
    monkeypatch.setattr(
        dashboard.http_requests,
        'get',
        lambda *args, **kwargs: FakeResponse(200, payload={'cash': 'bad'}),
    )

    recovered = dashboard._recover_cloud_state({'ok': False, 'message': 'auth failed'})

    assert recovered['_recovered_from'] == 'default'
    assert recovered['cash'] == dashboard.HYDRA_CONFIG['INITIAL_CAPITAL']
    assert recovered['positions'] == {}
    assert recovered['trading_day_counter'] == 0
