import json
import logging
import subprocess
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


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding='utf-8')


def make_state(positions=None, universe=None):
    if positions is None:
        positions = {'AAPL': {'shares': 10, 'avg_cost': 100.0}}
    return {
        'portfolio_value': 105000.0,
        'peak_value': 106000.0,
        'cash': 5000.0,
        'positions': positions,
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
        'current_universe': universe or ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL'],
        'universe_year': 2026,
        'current_regime_score': 0.72,
        'current_regime': True,
        'regime_consecutive': 3,
        'trading_day_counter': 6,
        'last_trading_date': '2026-03-13',
        'stop_events': [],
        'timestamp': '2026-03-16T09:30:00',
        'stats': {'uptime_minutes': 42, 'cycles_completed': 5, 'engine_iterations': 42},
        'portfolio_values_history': [103000.0],
        'hydra': {
            'rattle_positions': [],
            'catalyst_positions': [],
        },
        'ml_error_counts': {
            'entry': 0,
            'exit': 0,
            'hold': 0,
            'skip': 0,
            'snapshot': 0,
        },
        'dd_leverage': 1.0,
        'crash_cooldown': 0,
    }


class FakeResponse:
    def __init__(self, status_code, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def isolate_dashboard(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'state' / 'ml_learning').mkdir(parents=True, exist_ok=True)

    before_request = list(dashboard.app.before_request_funcs.get(None, []))
    dashboard.app.before_request_funcs[None] = []

    monkeypatch.setattr(dashboard, '_maybe_regenerate_interpretation',
                        lambda *args, **kwargs: None)

    dashboard._price_cache = {}
    dashboard._prev_close_cache = {}
    dashboard._price_cache_time = None
    dashboard._yf_consecutive_failures = 0
    dashboard._yf_fail_count = 0
    dashboard._yf_circuit_open_until = 0
    dashboard._yf_session = None
    dashboard._yf_crumb = None
    dashboard._social_cache = {}
    dashboard._social_cache_time = None
    dashboard._trade_analytics_cache = None
    dashboard._montecarlo_cache = None
    dashboard._montecarlo_cache_signature = None
    dashboard._risk_cache = None
    dashboard._risk_cache_time = None
    dashboard._equity_df = None
    dashboard._spy_df = None
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


def test_api_state_returns_offline_when_state_missing(client):
    response = client.get('/api/state')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'offline'
    assert payload['error'] == 'No state file found'
    assert payload['engine']['running'] is False


def test_api_state_returns_starting_when_engine_thread_alive_and_state_missing(client):
    class AliveThread:
        def is_alive(self):
            return True

    dashboard._cloud_engine_started = True
    dashboard._cloud_engine_thread = AliveThread()

    response = client.get('/api/state')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'starting'
    assert payload['message'] == 'Engine initializing...'
    assert payload['engine']['thread_alive'] is True


def test_api_state_returns_enriched_payload_when_state_exists(client, monkeypatch):
    write_json(Path('state/compass_state_latest.json'), make_state())
    captured = {}

    def fake_prices(symbols):
        captured['symbols'] = set(symbols)
        return {'AAPL': 110.0, '^GSPC': 5000.0}

    monkeypatch.setattr(dashboard, 'fetch_live_prices', fake_prices)
    monkeypatch.setattr(dashboard, 'compute_position_details',
                        lambda state, prices: [{'symbol': 'AAPL', 'pnl_pct': 10.0}])
    monkeypatch.setattr(dashboard, 'compute_portfolio_metrics',
                        lambda state, prices: {'portfolio_value': 105000.0})
    monkeypatch.setattr(dashboard, 'compute_hydra_data',
                        lambda state, prices: {'status': 'ok'})

    response = client.get('/api/state')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'online'
    assert payload['portfolio']['portfolio_value'] == 105000.0
    assert payload['position_details'][0]['symbol'] == 'AAPL'
    assert payload['hydra']['status'] == 'ok'
    assert payload['state_recovery'] is None
    assert 'AAPL' in captured['symbols']
    assert 'SPY' in captured['symbols']


def test_compute_portfolio_metrics_exposes_dd_leverage_top_level():
    state = make_state()
    state['dd_leverage'] = 0.6
    state['crash_cooldown'] = 3

    metrics = dashboard.compute_portfolio_metrics(state, prices={'AAPL': 110.0})

    assert metrics['dd_leverage'] == 0.6
    assert metrics['recovery']['dd_leverage'] == 0.6


def test_api_state_handles_invalid_json_state_file(client):
    state_path = Path('state/compass_state_latest.json')
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text('{"broken": ', encoding='utf-8')

    response = client.get('/api/state')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'offline'
    assert 'error' in payload  # corrupt JSON treated as missing (read_state returns None)


def test_api_cycle_log_returns_empty_when_missing(client):
    response = client.get('/api/cycle-log')

    assert response.status_code == 200
    assert response.get_json() == []


def test_api_cycle_log_returns_empty_when_invalid_json(client):
    log_path = Path('state/cycle_log.json')
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text('not-json', encoding='utf-8')

    response = client.get('/api/cycle-log')

    assert response.status_code == 200
    assert response.get_json() == []


def test_api_cycle_log_returns_closed_cycles(client):
    cycles = [{
        'cycle': 1,
        'status': 'closed',
        'hydra_return': 1.23,
        'spy_return': 0.75,
    }]
    write_json(Path('state/cycle_log.json'), cycles)

    response = client.get('/api/cycle-log')

    assert response.status_code == 200
    assert response.get_json()[0]['cycle'] == 1
    assert response.get_json()[0]['status'] == 'closed'


def test_api_equity_returns_error_without_backtest_data(client):
    response = client.get('/api/equity')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['equity'] == []
    assert payload['error'] == 'No backtest data'


def test_api_equity_returns_equity_and_milestones_from_dataframe(client):
    dashboard._equity_df = pd.DataFrame({
        'date': pd.to_datetime(['2026-03-01', '2026-03-02', '2026-03-03']),
        'value': [100000.0, 1200000.0, 1500000.0],
    })

    response = client.get('/api/equity')

    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload['equity']) == 2
    assert any(item['type'] == 'ath' for item in payload['milestones'])
    assert any(item['label'] == '$1M' for item in payload['milestones'])


def test_api_trade_analytics_returns_cached_payload(client):
    dashboard._trade_analytics_cache = {'win_rate': 0.6, 'profit_factor': 1.8}

    response = client.get('/api/trade-analytics')

    assert response.status_code == 200
    assert response.get_json()['profit_factor'] == 1.8


def test_api_trade_analytics_returns_error_on_failure(client, monkeypatch):
    class BrokenAnalytics:
        def run_all(self):
            raise RuntimeError('boom')

    monkeypatch.setitem(sys.modules, 'compass_trade_analytics',
                        types.SimpleNamespace(COMPASSTradeAnalytics=BrokenAnalytics))

    response = client.get('/api/trade-analytics')

    assert response.status_code == 200
    assert 'Trade analytics unavailable' in response.get_json()['error']


def test_api_risk_returns_low_risk_when_state_missing(client):
    response = client.get('/api/risk')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['risk_score'] == 0.0
    assert payload['risk_label'] == 'LOW'
    assert payload['error'] == 'No state file found'


def test_api_risk_returns_computed_payload(client, monkeypatch):
    write_json(Path('state/compass_state_latest.json'), make_state())
    monkeypatch.setattr(
        dashboard,
        'fetch_live_prices',
        lambda symbols: {'AAPL': 112.0, 'SPY': 500.0},
    )
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
    assert payload['num_positions'] == 1
    assert payload['max_position_pct'] > 0
    assert payload['risk_label'] in {'LOW', 'MODERATE', 'HIGH', 'EXTREME'}


def test_api_risk_uses_cache_until_ttl_expires(client, monkeypatch):
    write_json(Path('state/compass_state_latest.json'), make_state())
    call_count = {'prices': 0}

    def fake_prices(symbols):
        call_count['prices'] += 1
        return {'AAPL': 110.0, 'SPY': 500.0}

    monkeypatch.setattr(dashboard, 'fetch_live_prices', fake_prices)
    monkeypatch.setattr(
        dashboard,
        '_fetch_risk_histories',
        lambda symbols: {
            'AAPL': pd.DataFrame({'Close': [100.0, 101.0, 102.0, 103.0]}),
            'SPY': pd.DataFrame({'Close': [400.0, 401.0, 402.0, 403.0]}),
        },
    )

    first = client.get('/api/risk')
    second = client.get('/api/risk')

    assert first.status_code == 200
    assert second.status_code == 200
    assert call_count['prices'] == 1


def test_api_montecarlo_returns_expected_shape(client, monkeypatch):
    payload = {
        'fan_chart': {
            'days': [0, 5],
            'p5': [100000.0, 98000.0],
            'p50': [100000.0, 101000.0],
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
    assert data['fan_chart'] == payload['fan_chart']
    assert data['summary'] == payload['summary']
    assert data['seed'] == 666
    assert data['source'] == 'live_cycle_log'


def test_api_montecarlo_returns_error_on_failure(client, monkeypatch):
    class BrokenMonteCarlo:
        def run_all(self):
            raise RuntimeError('sim failure')

    monkeypatch.setattr(dashboard, '_montecarlo_signature', lambda: ('stable',))
    monkeypatch.setitem(
        sys.modules,
        'compass_montecarlo',
        types.SimpleNamespace(COMPASSMonteCarlo=BrokenMonteCarlo),
    )

    response = client.get('/api/montecarlo')

    assert response.status_code == 200
    data = response.get_json()
    assert 'error' in data
    assert 'sim failure' in data['error']


def test_api_montecarlo_uses_cache_on_second_call(client, monkeypatch):
    calls = {'count': 0}
    payload = {
        'fan_chart': {
            'days': [0, 5],
            'p5': [100000.0, 99000.0],
            'p50': [100000.0, 101500.0],
            'p95': [100000.0, 104500.0],
        },
        'summary': {'median_outcome': 101500.0},
        'seed': 666,
        'source': 'backtest_fallback',
    }

    class FakeMonteCarlo:
        def __init__(self):
            calls['count'] += 1

        def run_all(self):
            return payload

    monkeypatch.setattr(dashboard, '_montecarlo_signature', lambda: ('stable',))
    monkeypatch.setitem(
        sys.modules,
        'compass_montecarlo',
        types.SimpleNamespace(COMPASSMonteCarlo=FakeMonteCarlo),
    )

    first = client.get('/api/montecarlo')
    second = client.get('/api/montecarlo')

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.get_json() == second.get_json()
    assert calls['count'] == 1


def test_api_social_feed_uses_open_positions(client, monkeypatch):
    write_json(Path('state/compass_state_latest.json'), make_state())
    captured = {}

    def fake_feed(symbols):
        captured['symbols'] = symbols
        return [{'source': 'news', 'symbol': symbols[0]}]

    monkeypatch.setattr(dashboard, 'fetch_social_feed', fake_feed)

    response = client.get('/api/social-feed')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['symbols'] == ['AAPL']
    assert payload['messages'][0]['source'] == 'news'
    assert captured['symbols'] == ['AAPL']


def test_api_social_feed_falls_back_to_universe_when_no_positions(client, monkeypatch):
    state = make_state(positions={}, universe=['MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL', 'LLY'])
    write_json(Path('state/compass_state_latest.json'), state)
    monkeypatch.setattr(dashboard, 'fetch_social_feed',
                        lambda symbols: [{'source': 'reddit', 'count': len(symbols)}])

    response = client.get('/api/social-feed')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['symbols'] == ['MSFT', 'NVDA', 'AMZN', 'META', 'GOOGL']
    assert payload['messages'][0]['count'] == 5


@pytest.mark.parametrize('route', ['/api/ml', '/api/ml-learning'])
def test_api_ml_returns_kpis_structure(client, route):
    write_jsonl(Path('state/ml_learning/decisions.jsonl'), [
        {
            'decision_type': 'entry',
            'timestamp': '2026-03-10T15:30:00',
            'source': 'live',
        },
        {
            'decision_type': 'exit',
            'timestamp': '2026-03-11T15:30:00',
            'source': 'live',
        },
    ])
    write_jsonl(Path('state/ml_learning/outcomes.jsonl'), [{
        'timestamp': '2026-03-11T15:35:00',
        'gross_return': 0.05,
        'was_stopped': False,
        'alpha_vs_spy': 0.02,
        'pnl_usd': 500.0,
    }])
    write_jsonl(Path('state/ml_learning/daily_snapshots.jsonl'), [{
        'timestamp': '2026-03-11T16:00:00',
        'portfolio_value': 105000.0,
    }])
    write_json(Path('state/ml_learning/insights.json'), {
        'trading_days': 10,
        'learning_phase': 1,
    })

    response = client.get(route)

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['kpis']['total_decisions'] == 2
    assert payload['kpis']['total_outcomes'] == 1
    assert payload['kpis']['trading_days'] == 10
    assert payload['kpis']['avg_return'] == 0.05


def test_api_ml_learning_sanitizes_invalid_constants_in_insights(client):
    Path('state/ml_learning').mkdir(parents=True, exist_ok=True)
    Path('state/ml_learning/insights.json').write_text(
        '{"trading_days": 5, "learning_phase": 1, "stop_analysis": {"avg_return_when_not_stopped": NaN}}',
        encoding='utf-8'
    )

    response = client.get('/api/ml-learning')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['insights']['stop_analysis']['avg_return_when_not_stopped'] is None


def test_fetch_live_prices_returns_cached_values_without_fetch(monkeypatch):
    dashboard._price_cache = {'AAPL': 123.45}
    dashboard._price_cache_time = datetime.now()

    def should_not_run(symbols):
        raise AssertionError('Yahoo fetch should not be called on cache hit')

    monkeypatch.setattr(dashboard, '_yf_fetch_batch', should_not_run)

    prices = dashboard.fetch_live_prices(['AAPL'])

    assert prices == {'AAPL': 123.45}


def test_fetch_live_prices_populates_cache_and_prev_close(monkeypatch):
    monkeypatch.setattr(dashboard, '_yf_fetch_batch', lambda symbols: {
        'AAPL': {'price': 150.0, 'prev_close': 148.5}
    })

    prices = dashboard.fetch_live_prices(['AAPL'])

    assert prices == {'AAPL': 150.0}
    assert dashboard._price_cache['AAPL'] == 150.0
    assert dashboard._prev_close_cache['AAPL'] == 148.5
    assert dashboard._yf_consecutive_failures == 0


def test_fetch_live_prices_failure_preserves_stale_cache(monkeypatch):
    dashboard._price_cache = {'AAPL': 120.0}
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=120)
    monkeypatch.setattr(dashboard, '_yf_fetch_batch', lambda symbols: {})

    prices = dashboard.fetch_live_prices(['AAPL'])

    assert prices == {'AAPL': 120.0}
    assert dashboard._yf_consecutive_failures == 1
    assert dashboard._price_cache_time is not None


def test_yf_fetch_batch_resets_session_after_auth_failure(monkeypatch):
    class FakeSession:
        def get(self, url, params=None, timeout=None):
            return FakeResponse(401)

    monkeypatch.setattr(dashboard, '_HAS_REQUESTS', True)
    monkeypatch.setattr(dashboard, '_yf_get_session', lambda: (FakeSession(), 'crumb'))
    monkeypatch.setattr(dashboard.http_requests, 'get',
                        lambda *args, **kwargs: FakeResponse(429))
    dashboard._yf_session = object()
    dashboard._yf_crumb = 'crumb'

    result = dashboard._yf_fetch_batch(['AAPL'])

    assert result == {}
    assert dashboard._yf_session is None
    assert dashboard._yf_crumb is None


def test_run_cloud_engine_sets_error_when_engine_unavailable(monkeypatch):
    monkeypatch.setattr(dashboard, '_HAS_ENGINE', False)
    monkeypatch.setattr(dashboard, '_ENGINE_IMPORT_ERROR', 'ImportError: missing dependency')

    dashboard._run_cloud_engine()

    assert 'omnicapital_live import failed' in dashboard._engine_status['error']
    assert 'missing dependency' in dashboard._engine_status['error']


def test_git_pull_latest_marks_auth_failures(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ['git', 'remote', 'set-url']:
            return types.SimpleNamespace(returncode=0, stdout='', stderr='')
        if cmd[:2] == ['git', 'pull']:
            return types.SimpleNamespace(
                returncode=1,
                stdout='',
                stderr='fatal: Authentication failed for https://github.com/lucasabu1988/NuevoProyecto.git',
            )
        raise AssertionError(f'unexpected git command: {cmd}')

    monkeypatch.setenv('GIT_TOKEN', 'secret-token')
    monkeypatch.setattr(subprocess, 'run', fake_run)

    result = dashboard._git_pull_latest()

    assert result['ok'] is False
    assert result['auth_failed'] is True
    assert 'Authentication failed' in result['message']
    assert 'secret-token' not in result['message']
    assert any(cmd[:2] == ['git', 'pull'] for cmd in calls)


def test_recover_cloud_state_marks_git_pull_state(tmp_path):
    write_json(Path('state/compass_state_latest.json'), make_state())

    recovered = dashboard._recover_cloud_state({'ok': True, 'message': 'Already up to date.'})
    stored = json.loads(Path('state/compass_state_latest.json').read_text(encoding='utf-8'))

    assert recovered['_recovered_from'] == 'git_pull'
    assert stored['_recovered_from'] == 'git_pull'
    assert stored['cash'] == 5000.0


def test_recover_cloud_state_uses_github_fallback_when_state_missing(monkeypatch):
    monkeypatch.setattr(dashboard, '_HAS_REQUESTS', True)
    monkeypatch.setattr(
        dashboard.http_requests,
        'get',
        lambda *args, **kwargs: FakeResponse(200, payload=make_state()),
    )

    recovered = dashboard._recover_cloud_state({'ok': False, 'message': 'auth failed'})

    assert recovered['_recovered_from'] == 'github_api'
    assert json.loads(Path('state/compass_state_latest.json').read_text(encoding='utf-8'))['_recovered_from'] == 'github_api'


def test_recover_cloud_state_falls_back_to_default_when_sources_invalid(monkeypatch):
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


def test_api_state_exposes_state_recovery_source(client, monkeypatch):
    state = make_state()
    state['_recovered_from'] = 'github_api'
    write_json(Path('state/compass_state_latest.json'), state)

    monkeypatch.setattr(dashboard, 'fetch_live_prices', lambda symbols: {'AAPL': 110.0, '^GSPC': 5000.0})
    monkeypatch.setattr(dashboard, 'compute_position_details',
                        lambda state, prices: [{'symbol': 'AAPL', 'pnl_pct': 10.0}])
    monkeypatch.setattr(dashboard, 'compute_portfolio_metrics',
                        lambda state, prices: {'portfolio_value': 105000.0})
    monkeypatch.setattr(dashboard, 'compute_hydra_data',
                        lambda state, prices: {'status': 'ok'})

    response = client.get('/api/state')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['state_recovery'] == 'github_api'
    assert payload['engine']['state_recovery'] == 'github_api'


def test_api_health_reports_healthy_when_engine_running_and_prices_fresh(client):
    state = make_state()
    write_json(Path('state/compass_state_latest.json'), state)
    dashboard._engine_status.update({
        'running': True,
        'started_at': '2026-03-16T09:00:00',
        'error': None,
        'cycles': 5,
        'state_recovery': None,
    })
    dashboard._price_cache = {'AAPL': 110.0, 'SPY': 505.0}
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=15)
    dashboard._yf_consecutive_failures = 0

    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'healthy'
    assert payload['engine']['running'] is True
    assert payload['engine']['cycles_completed'] == 5
    assert payload['data_feed']['price_age_seconds'] < 60
    assert payload['portfolio']['num_positions'] == 1


def test_api_health_degrades_when_price_cache_is_stale(client):
    state = make_state()
    write_json(Path('state/compass_state_latest.json'), state)
    dashboard._engine_status.update({
        'running': True,
        'started_at': '2026-03-16T09:00:00',
        'error': None,
        'cycles': 5,
    })
    dashboard._price_cache = {'AAPL': 110.0}
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=120)

    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'degraded'
    assert payload['data_feed']['price_age_seconds'] > 60


def test_api_health_degrades_when_ml_errors_are_present(client):
    state = make_state()
    state['ml_error_counts']['hold'] = 2
    write_json(Path('state/compass_state_latest.json'), state)
    dashboard._engine_status.update({
        'running': True,
        'started_at': '2026-03-16T09:00:00',
        'error': None,
        'cycles': 5,
    })
    dashboard._price_cache = {'AAPL': 110.0}
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=10)

    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'degraded'
    assert payload['engine']['ml_errors']['hold'] == 2


def test_api_health_is_critical_when_engine_is_not_running(client):
    state = make_state()
    write_json(Path('state/compass_state_latest.json'), state)
    dashboard._engine_status.update({
        'running': False,
        'started_at': None,
        'error': 'engine down',
        'cycles': 0,
    })
    dashboard._price_cache = {'AAPL': 110.0}
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=5)

    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'critical'
    assert payload['engine']['running'] is False


def test_api_health_is_critical_when_data_is_very_stale(client):
    state = make_state()
    write_json(Path('state/compass_state_latest.json'), state)
    dashboard._engine_status.update({
        'running': True,
        'started_at': '2026-03-16T09:00:00',
        'error': None,
        'cycles': 5,
    })
    dashboard._price_cache = {'AAPL': 110.0}
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=360)

    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'critical'
    assert payload['data_feed']['price_age_seconds'] > 300


def test_api_health_reports_state_recovery_and_git_sync_metadata(client, monkeypatch):
    state = make_state()
    state['_recovered_from'] = 'git_pull'
    write_json(Path('state/compass_state_latest.json'), state)
    dashboard._engine_status.update({
        'running': True,
        'started_at': '2026-03-16T09:00:00',
        'error': None,
        'cycles': 5,
        'state_recovery': 'git_pull',
    })
    dashboard._price_cache = {'AAPL': 110.0}
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=20)
    monkeypatch.setenv('GIT_TOKEN', 'test-token')

    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['state']['file_exists'] is True
    assert payload['state']['last_modified'] is not None
    assert payload['state']['recovered_from'] == 'git_pull'
    assert payload['git_sync']['enabled'] is True


def test_ensure_cloud_engine_acquires_lock_and_starts_thread(monkeypatch):
    started = {}

    class FakeThread:
        def __init__(self, target=None, daemon=None, name=None):
            started['target'] = target
            started['daemon'] = daemon
            started['name'] = name

        def start(self):
            started['started'] = True

    monkeypatch.setattr(dashboard, 'AGENT_MODE', False)
    monkeypatch.setattr(dashboard, 'SHOWCASE_MODE', False)
    monkeypatch.setattr(dashboard.threading, 'Thread', FakeThread)
    monkeypatch.setattr(dashboard, '_run_cloud_engine', lambda: None)

    dashboard._ensure_cloud_engine()

    assert started['daemon'] is True
    assert started['name'] == 'CloudHydraEngine'
    assert started['started'] is True
    assert Path('state/.cloud_engine.lock').exists()


def test_ensure_cloud_engine_sets_error_when_thread_launch_fails(monkeypatch):
    class BrokenThread:
        def __init__(self, target=None, daemon=None, name=None):
            pass

        def start(self):
            raise RuntimeError('thread boom')

    monkeypatch.setattr(dashboard, 'AGENT_MODE', False)
    monkeypatch.setattr(dashboard, 'SHOWCASE_MODE', False)
    monkeypatch.setattr(dashboard.threading, 'Thread', BrokenThread)

    dashboard._ensure_cloud_engine()

    assert dashboard._cloud_engine_started is False
    assert 'Engine thread launch failed' in dashboard._engine_status['error']
    assert not Path('state/.cloud_engine.lock').exists()


def test_ensure_cloud_engine_skips_when_lock_already_exists(monkeypatch):
    lock_path = Path('state/.cloud_engine.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text('1234', encoding='utf-8')

    class FailThread:
        def __init__(self, *args, **kwargs):
            raise AssertionError('Thread should not start when lock exists')

    monkeypatch.setattr(dashboard, 'AGENT_MODE', False)
    monkeypatch.setattr(dashboard, 'SHOWCASE_MODE', False)
    monkeypatch.setattr(dashboard.threading, 'Thread', FailThread)

    dashboard._ensure_cloud_engine()

    assert dashboard._cloud_engine_started is True


def test_validate_environment_warns_on_invalid_hydra_mode(monkeypatch, caplog):
    monkeypatch.setenv('HYDRA_MODE', 'invalid')
    monkeypatch.delenv('COMPASS_MODE', raising=False)
    monkeypatch.delenv('PORT', raising=False)

    with caplog.at_level(logging.WARNING, logger='compass_dashboard_cloud'):
        dashboard._validate_environment()

    assert any("HYDRA_MODE='invalid'" in msg for msg in caplog.messages)


def test_validate_environment_no_warning_on_valid_hydra_mode(monkeypatch, caplog):
    monkeypatch.setenv('HYDRA_MODE', 'live')
    monkeypatch.delenv('COMPASS_MODE', raising=False)
    monkeypatch.delenv('PORT', raising=False)

    with caplog.at_level(logging.WARNING, logger='compass_dashboard_cloud'):
        dashboard._validate_environment()

    assert not any("HYDRA_MODE" in msg and "not a recognized" in msg for msg in caplog.messages)


def test_price_debug_rejects_xss_symbol(client):
    response = client.get('/api/price-debug?symbol=<script>')

    assert response.status_code == 400
    payload = response.get_json()
    assert payload['error'] == 'invalid parameter: symbol'


def test_price_debug_accepts_valid_symbol(client, monkeypatch):
    monkeypatch.setattr(dashboard, '_HAS_REQUESTS', False)
    monkeypatch.setattr(dashboard, '_yf_get_session', lambda: (None, None))

    response = client.get('/api/price-debug?symbol=AAPL')

    assert response.status_code != 400


def test_yf_circuit_breaker_opens_after_5_failures_and_blocks_6th(monkeypatch):
    fetch_attempts = {'count': 0}

    def fake_get_session():
        fetch_attempts['count'] += 1
        return None, None

    monkeypatch.setattr(dashboard, '_HAS_REQUESTS', True)
    monkeypatch.setattr(dashboard, '_yf_get_session', fake_get_session)
    monkeypatch.setattr(dashboard.http_requests, 'get',
                        lambda *args, **kwargs: FakeResponse(500))

    # First 5 calls should attempt fetch (and fail)
    for i in range(5):
        result = dashboard._yf_fetch_batch(['AAPL'])
        assert result == {}
        assert dashboard._yf_fail_count == i + 1

    # After 5 failures, circuit should be open
    assert dashboard._yf_circuit_open_until > 0

    # 6th call should NOT attempt fetch at all (circuit open)
    fetch_attempts['count'] = 0
    result = dashboard._yf_fetch_batch(['AAPL'])
    assert result == {}
    assert fetch_attempts['count'] == 0


def test_api_ml_diagnostics_with_ml_files(client, isolate_dashboard):
    ml_dir = isolate_dashboard / 'state' / 'ml_learning'
    decisions = [
        {'timestamp': '2026-03-15T10:00:00', 'action': 'entry', 'symbol': 'AAPL'},
        {'timestamp': '2026-03-16T10:00:00', 'action': 'hold', 'symbol': 'MSFT'},
    ]
    outcomes = [
        {'date': '2026-03-15', 'symbol': 'AAPL', 'pnl': 120.0},
    ]
    write_jsonl(ml_dir / 'decisions.jsonl', decisions)
    write_jsonl(ml_dir / 'outcomes.jsonl', outcomes)

    resp = client.get('/api/ml-diagnostics')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['phase'] == 1
    assert data['total_decisions'] == 2
    assert data['total_outcomes'] == 1
    assert data['last_decision_date'] == '2026-03-16'
    assert data['files_ok'] is True


def test_api_ml_diagnostics_no_ml_directory(client, isolate_dashboard):
    import shutil
    ml_dir = isolate_dashboard / 'state' / 'ml_learning'
    shutil.rmtree(ml_dir)

    resp = client.get('/api/ml-diagnostics')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['phase'] == 0
    assert data['error'] == 'ML not initialized'


def test_security_headers_include_content_security_policy(client):
    response = client.get('/api/state')

    assert response.status_code == 200
    csp = response.headers.get('Content-Security-Policy')
    assert csp is not None
    assert "default-src 'self'" in csp
    assert "script-src 'self' https://cdn.jsdelivr.net" in csp
    assert "style-src 'self' https://fonts.googleapis.com" in csp
    assert "font-src 'self' https://fonts.gstatic.com" in csp
    assert "img-src 'self' data:" in csp
    assert "connect-src 'self'" in csp
    assert 'unsafe-eval' not in csp


def test_execution_stats_returns_200_with_expected_keys(client, tmp_path):
    write_json(tmp_path / 'state' / 'compass_state_latest.json', make_state())
    dashboard.STATE_FILE = str(tmp_path / 'state' / 'compass_state_latest.json')

    response = client.get('/api/execution-stats')
    assert response.status_code == 200
    data = response.get_json()
    assert 'total_orders' in data
    assert 'fill_rate' in data
    assert 'avg_fill_deviation_pct' in data
    assert 'stale_orders_cancelled' in data
    assert data['total_orders'] == 0
    assert data['fill_rate'] == 0.0
