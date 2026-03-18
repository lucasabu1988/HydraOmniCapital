import ast
import gzip
import json
import logging
import os
import subprocess
import sys
import types
from unittest import mock
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import compass_dashboard as local_dashboard
import compass_dashboard_cloud as dashboard


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


def write_jsonl(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record) for record in records]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding='utf-8')


def set_file_mtime(path, when):
    ts = when.timestamp()
    os.utime(path, (ts, ts))


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


def prime_health_endpoint(state=None):
    write_json(Path('state/compass_state_latest.json'), state or make_state())
    dashboard._cloud_engine_thread = types.SimpleNamespace(is_alive=lambda: True)
    dashboard._engine_status.update({
        'running': True,
        'started_at': '2026-03-16T09:00:00',
        'error': None,
        'cycles': 5,
    })
    dashboard._price_cache = {'AAPL': 110.0, 'SPY': 505.0}
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=15)
    dashboard._yf_consecutive_failures = 0


def _handler_has_logging(handler):
    module = ast.Module(body=handler.body, type_ignores=[])
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in {'debug', 'info', 'warning', 'error', 'critical', 'exception'}:
            continue
        if isinstance(func.value, ast.Name) and func.value.id == 'logger':
            return True
        if isinstance(func.value, ast.Call):
            callee = func.value.func
            if (
                isinstance(callee, ast.Attribute)
                and callee.attr == 'getLogger'
                and isinstance(callee.value, ast.Name)
                and callee.value.id == 'logging'
            ):
                return True
    return False


def _except_audit(path):
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    bare = []
    missing_logs = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            if handler.type is None:
                bare.append(handler.lineno)
            if not _handler_has_logging(handler):
                missing_logs.append(handler.lineno)
    return bare, missing_logs


def _route_paths(app):
    return {
        rule.rule
        for rule in app.url_map.iter_rules()
        if rule.endpoint != 'static'
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
    dashboard._data_quality_cache = None
    dashboard._data_quality_cache_time = None
    dashboard._equity_df = None
    dashboard._spy_df = None
    dashboard._cloud_engine = None
    dashboard._cloud_engine_thread = None
    dashboard._cloud_engine_started = False
    dashboard._engine_heartbeat_thread = None
    dashboard._self_ping_started = False
    dashboard.STATE_DIR = 'state'
    dashboard.STATE_FILE = os.path.join('state', 'compass_state_latest.json')
    dashboard._engine_lock = os.path.join(dashboard.STATE_DIR, '.cloud_engine.lock')
    dashboard.LOG_DIR = 'logs'
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


@pytest.mark.parametrize('route', sorted(_route_paths(dashboard.app)))
def test_local_dashboard_exposes_all_cloud_routes(route):
    assert route in _route_paths(local_dashboard.app)


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
    dashboard._cloud_engine_thread = types.SimpleNamespace(is_alive=lambda: True)
    dashboard._engine_status.update({'running': True})
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=45)

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
    assert payload['_data_freshness']['status'] == 'live'
    assert payload['_data_freshness']['engine_alive'] is True
    assert 'AAPL' in captured['symbols']
    assert 'SPY' in captured['symbols']


def test_api_state_includes_offline_data_freshness_when_engine_is_down(client, monkeypatch):
    write_json(Path('state/compass_state_latest.json'), make_state())
    dashboard._engine_status.update({'running': False, 'error': 'engine down'})
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=600)

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
    assert payload['_data_freshness']['status'] == 'offline'
    assert payload['_data_freshness']['engine_alive'] is False


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


def test_api_logs_returns_filtered_recent_entries(client):
    log_path = Path('logs') / f"compass_live_{datetime.now().strftime('%Y%m%d')}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "\n".join([
            '2026-03-16 09:30:00 - INFO - Engine started',
            '2026-03-16 09:31:00 - INFO - \"GET /api/state HTTP/1.1\" 200 -',
            '2026-03-16 09:32:00 - WARNING - Risk spike detected',
        ]) + "\n",
        encoding='utf-8',
    )

    response = client.get('/api/logs')

    assert response.status_code == 200
    payload = response.get_json()
    assert [item['message'] for item in payload['logs']] == ['Engine started', 'Risk spike detected']
    assert payload['logs'][1]['level'] == 'WARNING'


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


def test_api_data_quality_runs_pipeline_and_caches_result(client, monkeypatch):
    calls = {'count': 0}

    class FakeDataPipeline:
        def __init__(self):
            calls['count'] += 1

        def run_all(self):
            return {'score': 97, 'checks': {'prices': 'ok'}}

    monkeypatch.setitem(
        sys.modules,
        'compass_data_pipeline',
        types.SimpleNamespace(COMPASSDataPipeline=FakeDataPipeline),
    )

    first = client.get('/api/data-quality')
    second = client.get('/api/data-quality')

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.get_json() == {'score': 97, 'checks': {'prices': 'ok'}}
    assert second.get_json() == {'score': 97, 'checks': {'prices': 'ok'}}
    assert calls['count'] == 1


def test_api_data_quality_returns_error_when_pipeline_fails(client, monkeypatch):
    class BrokenDataPipeline:
        def run_all(self):
            raise RuntimeError('pipeline boom')

    monkeypatch.setitem(
        sys.modules,
        'compass_data_pipeline',
        types.SimpleNamespace(COMPASSDataPipeline=BrokenDataPipeline),
    )

    response = client.get('/api/data-quality')

    assert response.status_code == 200
    assert response.get_json() == {'error': 'pipeline boom'}


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


def test_yf_fetch_batch_logs_request_failures(monkeypatch, caplog):
    class BrokenSession:
        def get(self, url, params=None, timeout=None):
            raise RuntimeError('v7 boom')

    monkeypatch.setattr(dashboard, '_HAS_REQUESTS', True)
    monkeypatch.setattr(dashboard, '_yf_get_session', lambda: (BrokenSession(), 'crumb'))
    monkeypatch.setattr(
        dashboard.http_requests,
        'get',
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('v8 boom')),
    )

    with caplog.at_level(logging.WARNING, logger='compass_dashboard_cloud'):
        result = dashboard._yf_fetch_batch(['AAPL'])

    assert result == {}
    assert any('Yahoo Finance v7 batch failed' in record.message for record in caplog.records)
    assert any('Yahoo Finance AAPL fetch failed' in record.message for record in caplog.records)


def test_read_state_logs_ioerror(monkeypatch, caplog):
    monkeypatch.setattr(dashboard.os.path, 'exists', lambda path: True)

    with mock.patch('builtins.open', side_effect=IOError('disk boom')):
        with caplog.at_level(logging.ERROR, logger='compass_dashboard_cloud'):
            state = dashboard.read_state()

    assert state is None
    assert any('Failed to read state file' in record.message for record in caplog.records)


def test_dashboard_files_have_logged_typed_except_handlers():
    repo_root = Path(__file__).resolve().parent.parent
    for path_str in ['compass_dashboard_cloud.py', 'compass_dashboard.py']:
        bare, missing_logs = _except_audit(repo_root / path_str)
        assert bare == [], f'{path_str} has bare except handlers at {bare}'
        assert missing_logs == [], f'{path_str} has except handlers without logging at {missing_logs}'


def test_run_cloud_engine_sets_error_when_engine_unavailable(monkeypatch):
    monkeypatch.setattr(dashboard, '_HAS_ENGINE', False)
    monkeypatch.setattr(dashboard, '_ENGINE_IMPORT_ERROR', 'ImportError: missing dependency')

    dashboard._run_cloud_engine()

    assert 'omnicapital_live import failed' in dashboard._engine_status['error']
    assert 'missing dependency' in dashboard._engine_status['error']


def test_cleanup_data_cache_deletes_only_old_legacy_files(isolate_dashboard):
    now = datetime(2026, 3, 17, 12, 0, 0)
    cache_dir = isolate_dashboard / 'data_cache'
    parquet_dir = isolate_dashboard / 'data_cache_parquet'
    cache_dir.mkdir(parents=True, exist_ok=True)
    parquet_dir.mkdir(parents=True, exist_ok=True)

    old_csv = cache_dir / 'old_prices.csv'
    old_pkl = cache_dir / 'old_prices.pkl'
    recent_csv = cache_dir / 'recent_prices.csv'
    active_parquet = parquet_dir / 'active.parquet'
    for path in (old_csv, old_pkl, recent_csv, active_parquet):
        path.write_text('cached', encoding='utf-8')

    set_file_mtime(old_csv, now - timedelta(days=91))
    set_file_mtime(old_pkl, now - timedelta(days=120))
    set_file_mtime(recent_csv, now - timedelta(days=10))
    set_file_mtime(active_parquet, now - timedelta(days=200))

    deleted = dashboard._cleanup_data_cache(now=now)
    old_csv_rel = str(Path('data_cache/old_prices.csv'))
    old_pkl_rel = str(Path('data_cache/old_prices.pkl'))

    assert old_csv_rel in deleted
    assert old_pkl_rel in deleted
    assert not old_csv.exists()
    assert not old_pkl.exists()
    assert recent_csv.exists()
    assert active_parquet.exists()


def test_cleanup_logs_compresses_prunes_and_trims(isolate_dashboard):
    now = datetime(2026, 3, 17, 12, 0, 0)
    log_dir = isolate_dashboard / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)

    old_log = log_dir / 'compass_live_20260310.log'
    old_log.write_text('old-line\n' * 5, encoding='utf-8')
    set_file_mtime(old_log, now - timedelta(days=5))

    recent_log = log_dir / 'compass_live_20260317.log'
    recent_log.write_text('fresh-line\n', encoding='utf-8')
    set_file_mtime(recent_log, now - timedelta(days=1))

    oversized_log = log_dir / 'oversized.log'
    oversized_log.write_text('line-1\nline-2\nline-3\nline-4\nline-5\n', encoding='utf-8')
    set_file_mtime(oversized_log, now - timedelta(hours=1))

    expired_gz = log_dir / 'expired.log.gz'
    with gzip.open(expired_gz, 'wt', encoding='utf-8') as handle:
        handle.write('expired\n')
    set_file_mtime(expired_gz, now - timedelta(days=20))

    result = dashboard._cleanup_logs(now=now, max_bytes=18)
    compressed_old_log = Path(str(old_log) + '.gz')
    compressed_old_log_rel = str(Path('logs/compass_live_20260310.log.gz'))
    expired_gz_rel = str(Path('logs/expired.log.gz'))
    oversized_log_rel = str(Path('logs/oversized.log'))

    assert compressed_old_log_rel in result['compressed']
    assert compressed_old_log.exists()
    assert not old_log.exists()
    assert recent_log.exists()
    assert expired_gz_rel in result['deleted']
    assert not expired_gz.exists()
    assert oversized_log_rel in result['trimmed']
    assert oversized_log.stat().st_size <= 18
    assert 'line-5' in oversized_log.read_text(encoding='utf-8')


def test_cleanup_corrupted_states_prunes_old_files_and_backups(isolate_dashboard):
    now = datetime(2026, 3, 17, 12, 0, 0)
    state_dir = isolate_dashboard / 'state'

    old_corrupted = state_dir / 'compass_state_CORRUPTED_old.json'
    recent_corrupted = state_dir / 'compass_state_CORRUPTED_recent.json'
    old_corrupted.write_text('{}', encoding='utf-8')
    recent_corrupted.write_text('{}', encoding='utf-8')
    set_file_mtime(old_corrupted, now - timedelta(days=8))
    set_file_mtime(recent_corrupted, now - timedelta(days=2))

    backups = []
    for date_str in ('20260310', '20260311', '20260312', '20260313'):
        backup = state_dir / f'compass_state_{date_str}.json'
        backup.write_text('{}', encoding='utf-8')
        backups.append(backup)

    result = dashboard._cleanup_corrupted_states(now=now)
    old_corrupted_rel = str(Path('state/compass_state_CORRUPTED_old.json'))
    oldest_backup_rel = str(Path('state/compass_state_20260310.json'))

    assert old_corrupted_rel in result['deleted_corrupted']
    assert not old_corrupted.exists()
    assert recent_corrupted.exists()
    assert oldest_backup_rel in result['deleted_backups']
    assert not backups[0].exists()
    assert backups[1].exists()
    assert backups[2].exists()
    assert backups[3].exists()


def test_run_cloud_engine_increments_crash_count_on_exception(monkeypatch):
    class FakeBroker:
        def __init__(self):
            self.positions = {}
            self.cash = 100000.0

        def set_price_feed(self, feed):
            self.feed = feed

    class FakeEngine:
        def __init__(self, config):
            self.broker = FakeBroker()
            self.data_feed = None

        def load_state(self):
            return None

        def run(self, interval=60):
            raise RuntimeError('loop exploded')

    class StopLoop(Exception):
        pass

    monkeypatch.setattr(dashboard, '_HAS_ENGINE', True)
    monkeypatch.setattr(dashboard, 'COMPASSLive', FakeEngine)
    monkeypatch.setattr(dashboard, '_git_pull_latest', lambda: {'ok': True, 'message': 'ok', 'auth_failed': False})
    monkeypatch.setattr(dashboard, '_recover_cloud_state', lambda pull: {'_recovered_from': 'git_pull'})
    monkeypatch.setattr(dashboard, '_ensure_engine_runtime_heartbeat', lambda: None)
    monkeypatch.setenv('GIT_TOKEN', '')
    monkeypatch.setattr(dashboard.time_module, 'sleep', lambda seconds: (_ for _ in ()).throw(StopLoop()))

    with pytest.raises(StopLoop):
        dashboard._run_cloud_engine()

    assert dashboard._engine_status['crash_count'] == 1
    assert dashboard._engine_status['last_crash_error'] == 'loop exploded'
    assert dashboard._engine_status['last_crash_at'] is not None


def test_run_cloud_engine_runs_cleanup_once_on_startup(monkeypatch):
    calls = []

    class StopLoop(Exception):
        pass

    monkeypatch.setattr(dashboard, '_HAS_ENGINE', True)
    monkeypatch.setattr(dashboard, '_ensure_engine_runtime_heartbeat', lambda: None)
    monkeypatch.setattr(dashboard, '_cleanup_data_cache', lambda: calls.append('cache'))
    monkeypatch.setattr(dashboard, '_cleanup_logs', lambda: calls.append('logs'))
    monkeypatch.setattr(dashboard, '_cleanup_corrupted_states', lambda: calls.append('states'))
    monkeypatch.setattr(dashboard, '_git_pull_latest', lambda: (_ for _ in ()).throw(RuntimeError('stop after cleanup')))
    monkeypatch.setattr(dashboard.time_module, 'sleep', lambda seconds: (_ for _ in ()).throw(StopLoop()))

    with pytest.raises(StopLoop):
        dashboard._run_cloud_engine()

    assert calls == ['cache', 'logs', 'states']


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
    dashboard._cloud_engine_thread = types.SimpleNamespace(is_alive=lambda: True)
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
    assert payload['engine_alive'] is True
    assert payload['engine']['running'] is True
    assert payload['engine']['cycles_completed'] == 5
    assert payload['price_age_seconds'] < 60
    assert payload['positions_count'] == 1
    assert payload['crash_count'] == 0


def test_api_overlay_status_prefers_live_cloud_engine_over_state_file(client):
    write_json(Path('state/compass_state_latest.json'), {
        'overlay': {
            'available': True,
            'capital_scalar': 0.95,
            'per_overlay': {'bso': 0.95, 'm2': 0.95, 'fomc': 0.95},
            'diagnostics': {'credit_filter': {'hy_bps': 350, 'excluded': ['Energy']}},
        }
    })
    dashboard._cloud_engine = types.SimpleNamespace(
        _overlay_available=True,
        _overlay_result={
            'capital_scalar': 0.55,
            'per_overlay_scalars': {'bso': 0.5, 'm2': 0.7, 'fomc': 1.0},
            'position_floor': 1,
            'diagnostics': {'credit_filter': {'hy_bps': 610, 'excluded': ['Financials']}},
        },
    )

    response = client.get('/api/overlay-status')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['capital_scalar'] == 0.55
    assert payload['scalar_label'] == 'Stressed'
    assert payload['per_overlay']['bso'] == 0.5
    assert payload['credit_filter']['hy_bps'] == 610
    assert payload['credit_filter']['excluded_sectors'] == ['Financials']


def test_api_agent_scratchpad_supports_alias_and_date_query(client):
    scratchpad_dir = Path('state/agent_scratchpad')
    scratchpad_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(scratchpad_dir / '2026-03-15.jsonl', [{'note': 'older'}])
    write_jsonl(scratchpad_dir / '2026-03-16.jsonl', [{'note': 'latest'}])

    response = client.get('/api/agent-scratchpad?date=2026-03-15')
    alias_response = client.get('/api/agent/scratchpad?date=2026-03-15')

    assert response.status_code == 200
    assert alias_response.status_code == 200
    assert response.get_json() == alias_response.get_json()
    payload = response.get_json()
    assert payload['date'] == '2026-03-15'
    assert payload['entries'] == [{'note': 'older'}]
    assert payload['available_dates'][:2] == ['2026-03-16', '2026-03-15']


def test_api_agent_heartbeat_reports_alive_status(client):
    write_json(Path('state/agent_heartbeat.json'), {
        'ts': datetime.now().isoformat(),
        'agent': 'hydra',
    })

    response = client.get('/api/agent-heartbeat')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['alive'] is True
    assert payload['agent'] == 'hydra'
    assert payload['age_seconds'] <= 1


def test_api_health_degrades_when_price_cache_is_stale(client):
    state = make_state()
    write_json(Path('state/compass_state_latest.json'), state)
    dashboard._cloud_engine_thread = types.SimpleNamespace(is_alive=lambda: True)
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
    assert payload['status'] == 'degraded'
    assert payload['price_age_seconds'] > 300


def test_api_health_degrades_when_ml_errors_are_present(client):
    state = make_state()
    state['ml_error_counts']['hold'] = 2
    write_json(Path('state/compass_state_latest.json'), state)
    dashboard._cloud_engine_thread = types.SimpleNamespace(is_alive=lambda: True)
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


def test_api_health_returns_down_when_engine_is_not_running_during_market_hours(client, monkeypatch):
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
    monkeypatch.setattr(dashboard, '_market_is_open', lambda now_et=None: True)

    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'down'
    assert payload['engine_alive'] is False


def test_api_health_degrades_when_engine_is_not_running_outside_market_hours(client, monkeypatch):
    state = make_state()
    write_json(Path('state/compass_state_latest.json'), state)
    dashboard._engine_status.update({
        'running': False,
        'started_at': None,
        'error': 'engine down',
        'cycles': 0,
    })
    dashboard._price_cache = {'AAPL': 110.0}
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=360)
    monkeypatch.setattr(dashboard, '_market_is_open', lambda now_et=None: False)

    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'degraded'
    assert payload['engine_alive'] is False
    assert payload['price_age_seconds'] > 300


def test_api_health_reports_state_recovery_and_git_sync_metadata(client, monkeypatch):
    state = make_state()
    state['_recovered_from'] = 'git_pull'
    write_json(Path('state/compass_state_latest.json'), state)
    dashboard._cloud_engine_thread = types.SimpleNamespace(is_alive=lambda: True)
    dashboard._engine_status.update({
        'running': True,
        'started_at': '2026-03-16T09:00:00',
        'error': None,
        'cycles': 5,
        'state_recovery': 'git_pull',
        'crash_count': 2,
        'last_crash_at': '2026-03-16T08:30:00',
        'last_crash_error': 'boom',
        'restarts': ['2026-03-16T08:35:00', '2026-03-16T09:00:00'],
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
    assert payload['crash_count'] == 2
    assert payload['last_crash_error'] == 'boom'
    assert payload['restarts'][-1] == '2026-03-16T09:00:00'


def test_api_health_uses_shared_runtime_status_from_owner_worker(client, monkeypatch):
    state = make_state()
    write_json(Path('state/compass_state_latest.json'), state)
    write_json(Path('state/cloud_engine_runtime.json'), {
        'pid': 4242,
        'running': True,
        'thread_alive': True,
        'started_at': '2026-03-17T09:00:00',
        'startup_started_at': '2026-03-17T09:00:00',
        'cycles': 11,
        'crash_count': 0,
        'last_crash_at': None,
        'last_crash_error': None,
        'restarts': ['2026-03-17T09:00:00'],
        'heartbeat_at': datetime.now().isoformat(),
    })
    dashboard._engine_status.update({
        'running': False,
        'started_at': None,
        'error': 'not my worker',
        'cycles': 0,
    })
    dashboard._price_cache = {'AAPL': 110.0}
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=10)
    monkeypatch.setattr(dashboard, '_engine_lock_owner_is_alive', lambda pid: True)

    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'healthy'
    assert payload['engine_alive'] is True
    assert payload['engine']['running'] is True
    assert payload['engine']['owner_pid'] == 4242
    assert payload['engine']['heartbeat_age_seconds'] is not None


def test_api_health_reports_down_when_shared_runtime_status_is_stale(client, monkeypatch):
    state = make_state()
    write_json(Path('state/compass_state_latest.json'), state)
    write_json(Path('state/cloud_engine_runtime.json'), {
        'pid': 4242,
        'running': True,
        'thread_alive': True,
        'started_at': '2026-03-17T09:00:00',
        'startup_started_at': '2026-03-17T09:00:00',
        'cycles': 11,
        'crash_count': 0,
        'last_crash_at': None,
        'last_crash_error': None,
        'restarts': ['2026-03-17T09:00:00'],
        'heartbeat_at': (datetime.now() - timedelta(seconds=dashboard.ENGINE_HEARTBEAT_STALE_SECONDS + 30)).isoformat(),
    })
    dashboard._engine_status.update({
        'running': False,
        'started_at': None,
        'error': 'not my worker',
        'cycles': 0,
    })
    dashboard._price_cache = {'AAPL': 110.0}
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=10)
    monkeypatch.setattr(dashboard, '_engine_lock_owner_is_alive', lambda pid: True)
    monkeypatch.setattr(dashboard, '_market_is_open', lambda now_et=None: True)

    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['status'] == 'down'
    assert payload['engine_alive'] is False
    assert payload['engine']['running'] is False


def test_api_health_reports_healthy_ml_watchdog_status(client):
    now = datetime.now()
    prime_health_endpoint()
    write_jsonl(Path('state/ml_learning/decisions.jsonl'), [
        {'timestamp': (now - timedelta(days=4)).isoformat(), 'symbol': 'AAPL'},
        {'timestamp': (now - timedelta(days=3)).isoformat(), 'symbol': 'MSFT'},
        {'timestamp': (now - timedelta(days=2)).isoformat(), 'symbol': 'NVDA'},
        {'timestamp': (now - timedelta(days=1)).isoformat(), 'symbol': 'AMZN'},
    ])
    write_jsonl(Path('state/ml_learning/outcomes.jsonl'), [
        {'exit_date': (now - timedelta(days=2)).date().isoformat(), 'symbol': 'AAPL'},
        {'exit_date': (now - timedelta(days=1)).date().isoformat(), 'symbol': 'MSFT'},
        {'exit_date': now.date().isoformat(), 'symbol': 'NVDA'},
    ])

    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['ml_health']['decisions_count'] == 4
    assert payload['ml_health']['outcomes_count'] == 3
    assert payload['ml_health']['outcome_completion_rate'] == pytest.approx(0.75)
    assert payload['ml_health']['days_without_outcome'] == 0
    assert payload['ml_health']['status'] == 'healthy'


def test_api_health_reports_warning_ml_watchdog_status_for_partial_coverage(client):
    now = datetime.now()
    prime_health_endpoint()
    write_jsonl(Path('state/ml_learning/decisions.jsonl'), [
        {'timestamp': (now - timedelta(hours=12 * idx)).isoformat(), 'symbol': f'SYM{idx}'}
        for idx in range(10)
    ])
    write_jsonl(Path('state/ml_learning/outcomes.jsonl'), [
        {'exit_date': (now - timedelta(days=idx)).date().isoformat(), 'symbol': f'SYM{idx}'}
        for idx in range(3)
    ])

    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['ml_health']['outcome_completion_rate'] == pytest.approx(0.3)
    assert payload['ml_health']['status'] == 'warning'
    assert payload['ml_health']['last_decision_at'] is not None
    assert payload['ml_health']['last_outcome_at'] is not None


def test_api_health_reports_degraded_ml_watchdog_status_for_stale_outcomes(client):
    now = datetime.now()
    prime_health_endpoint()
    write_jsonl(Path('state/ml_learning/decisions.jsonl'), [
        {'timestamp': (now - timedelta(days=12)).isoformat(), 'symbol': 'AAPL'},
        {'timestamp': (now - timedelta(days=11)).isoformat(), 'symbol': 'MSFT'},
        {'timestamp': (now - timedelta(days=10)).isoformat(), 'symbol': 'NVDA'},
    ])
    write_jsonl(Path('state/ml_learning/outcomes.jsonl'), [
        {'exit_date': (now - timedelta(days=10)).date().isoformat(), 'symbol': 'AAPL'},
        {'exit_date': (now - timedelta(days=9)).date().isoformat(), 'symbol': 'MSFT'},
    ])

    response = client.get('/api/health')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['ml_health']['outcome_completion_rate'] == pytest.approx(2 / 3, rel=1e-3)
    assert payload['ml_health']['days_without_outcome'] == 9
    assert payload['ml_health']['status'] == 'degraded'


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
    monkeypatch.setattr(dashboard, '_read_engine_lock_owner', lambda path: 1234)
    monkeypatch.setattr(dashboard, '_engine_lock_owner_is_alive', lambda pid: True)

    dashboard._ensure_cloud_engine()

    assert dashboard._cloud_engine_started is True


def test_ensure_cloud_engine_restarts_dead_thread_on_next_call(monkeypatch):
    started = {'count': 0}
    lock_path = Path('state/.cloud_engine.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(str(os.getpid()), encoding='utf-8')

    class DeadThread:
        def is_alive(self):
            return False

    class FakeThread:
        def __init__(self, target=None, daemon=None, name=None):
            started['target'] = target
            started['daemon'] = daemon
            started['name'] = name

        def start(self):
            started['count'] += 1

    monkeypatch.setattr(dashboard, 'AGENT_MODE', False)
    monkeypatch.setattr(dashboard, 'SHOWCASE_MODE', False)
    monkeypatch.setattr(dashboard, '_cloud_engine_started', True)
    monkeypatch.setattr(dashboard, '_cloud_engine_thread', DeadThread())
    monkeypatch.setattr(dashboard.threading, 'Thread', FakeThread)

    dashboard._ensure_cloud_engine()

    assert started['count'] == 1
    assert started['name'] == 'CloudHydraEngine'


def test_ensure_cloud_engine_reclaims_stale_lock_with_dead_pid(monkeypatch):
    started = {'count': 0}
    lock_path = Path('state/.cloud_engine.lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text('999999', encoding='utf-8')

    class FakeThread:
        def __init__(self, target=None, daemon=None, name=None):
            started['target'] = target
            started['name'] = name

        def start(self):
            started['count'] += 1

    monkeypatch.setattr(dashboard, 'AGENT_MODE', False)
    monkeypatch.setattr(dashboard, 'SHOWCASE_MODE', False)
    monkeypatch.setattr(dashboard.threading, 'Thread', FakeThread)
    monkeypatch.setattr(dashboard, '_read_engine_lock_owner', lambda path: 999999)
    monkeypatch.setattr(dashboard, '_engine_lock_owner_is_alive', lambda pid: False)

    dashboard._ensure_cloud_engine()

    assert started['count'] == 1
    assert lock_path.read_text(encoding='utf-8') == str(os.getpid())


def test_validate_environment_warns_on_invalid_hydra_mode(monkeypatch, caplog):
    monkeypatch.setenv('HYDRA_MODE', 'invalid')
    monkeypatch.delenv('COMPASS_MODE', raising=False)
    monkeypatch.delenv('PORT', raising=False)

    with caplog.at_level(logging.WARNING, logger='compass_dashboard_cloud'):
        dashboard._validate_environment()

    assert any("HYDRA_MODE='invalid'" in msg for msg in caplog.messages)


@pytest.mark.parametrize('hydra_mode', ['live', 'paper', 'backtest', 'showcase'])
def test_validate_environment_no_warning_on_valid_hydra_mode(monkeypatch, caplog, hydra_mode):
    monkeypatch.setenv('HYDRA_MODE', hydra_mode)
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


# ============================================================================
# ENGINE STARTUP LOCK MECHANISM
# ============================================================================

class TestEngineStartupLock:

    def _reset_engine_state(self, monkeypatch):
        monkeypatch.setattr(dashboard, '_cloud_engine_started', False)
        monkeypatch.setattr(dashboard, '_cloud_engine_thread', None)
        monkeypatch.setattr(dashboard, 'AGENT_MODE', False)
        monkeypatch.setattr(dashboard, 'SHOWCASE_MODE', False)

    def test_lock_file_created_on_engine_start(self, tmp_path, monkeypatch):
        self._reset_engine_state(monkeypatch)
        state_dir = str(tmp_path / 'state')
        monkeypatch.setattr(dashboard, 'STATE_DIR', state_dir)

        # Prevent actual thread from launching
        monkeypatch.setattr(dashboard.threading, 'Thread', lambda **kw: types.SimpleNamespace(start=lambda: None))

        dashboard._ensure_cloud_engine()

        lock_file = tmp_path / 'state' / '.cloud_engine.lock'
        assert lock_file.exists()

    def test_second_worker_skips_engine_when_lock_exists(self, tmp_path, monkeypatch):
        self._reset_engine_state(monkeypatch)
        state_dir = str(tmp_path / 'state')
        monkeypatch.setattr(dashboard, 'STATE_DIR', state_dir)

        # Pre-create lock file with a valid PID (simulate another worker)
        lock_path = tmp_path / 'state'
        lock_path.mkdir(parents=True, exist_ok=True)
        lock_file = lock_path / '.cloud_engine.lock'
        lock_file.write_text(str(os.getpid()))

        thread_started = []
        def fake_thread(**kw):
            thread_started.append(True)
            return types.SimpleNamespace(start=lambda: None)
        monkeypatch.setattr(dashboard.threading, 'Thread', fake_thread)

        dashboard._ensure_cloud_engine()

        # Engine thread should NOT have been created — lock already existed
        assert thread_started == []
        assert dashboard._cloud_engine_started is True

    def test_stale_lock_is_reclaimed_during_ensure(self, tmp_path, monkeypatch):
        self._reset_engine_state(monkeypatch)
        state_dir = str(tmp_path / 'state')
        monkeypatch.setattr(dashboard, 'STATE_DIR', state_dir)

        lock_dir = tmp_path / 'state'
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = lock_dir / '.cloud_engine.lock'
        lock_file.write_text('99999', encoding='utf-8')

        started = []

        def fake_thread(**kw):
            started.append(True)
            return types.SimpleNamespace(start=lambda: None)

        monkeypatch.setattr(dashboard.threading, 'Thread', fake_thread)
        monkeypatch.setattr(dashboard, '_read_engine_lock_owner', lambda path: 99999)
        monkeypatch.setattr(dashboard, '_engine_lock_owner_is_alive', lambda pid: False)

        dashboard._ensure_cloud_engine()

        assert started == [True]
        assert lock_file.read_text(encoding='utf-8') == str(os.getpid())

    def test_lock_file_contains_current_pid(self, tmp_path, monkeypatch):
        self._reset_engine_state(monkeypatch)
        state_dir = str(tmp_path / 'state')
        monkeypatch.setattr(dashboard, 'STATE_DIR', state_dir)

        fake_pid = 12345
        monkeypatch.setattr(os, 'getpid', lambda: fake_pid)
        monkeypatch.setattr(dashboard.threading, 'Thread', lambda **kw: types.SimpleNamespace(start=lambda: None))

        dashboard._ensure_cloud_engine()

        lock_file = tmp_path / 'state' / '.cloud_engine.lock'
        assert lock_file.read_text() == '12345'

    def test_engine_not_started_on_lock_acquisition_failure(self, tmp_path, monkeypatch):
        self._reset_engine_state(monkeypatch)
        state_dir = str(tmp_path / 'state')
        monkeypatch.setattr(dashboard, 'STATE_DIR', state_dir)

        original_os_open = os.open
        def failing_open(path, flags, *args, **kwargs):
            if '.cloud_engine.lock' in str(path):
                raise OSError('Permission denied')
            return original_os_open(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, 'open', failing_open)

        thread_started = []
        def fake_thread(**kw):
            thread_started.append(True)
            return types.SimpleNamespace(start=lambda: None)
        monkeypatch.setattr(dashboard.threading, 'Thread', fake_thread)

        dashboard._ensure_cloud_engine()

        assert thread_started == []
        assert dashboard._cloud_engine_started is False
        assert 'lock acquisition failed' in dashboard._engine_status.get('error', '').lower()

    def test_lock_file_removed_on_thread_launch_failure(self, tmp_path, monkeypatch):
        self._reset_engine_state(monkeypatch)
        state_dir = str(tmp_path / 'state')
        monkeypatch.setattr(dashboard, 'STATE_DIR', state_dir)

        def exploding_thread(**kw):
            raise RuntimeError('Thread creation failed')
        monkeypatch.setattr(dashboard.threading, 'Thread', exploding_thread)

        dashboard._ensure_cloud_engine()

        lock_file = tmp_path / 'state' / '.cloud_engine.lock'
        assert not lock_file.exists()
        assert dashboard._cloud_engine_started is False

    def test_lock_idempotent_when_already_started(self, tmp_path, monkeypatch):
        monkeypatch.setattr(dashboard, '_cloud_engine_started', True)
        monkeypatch.setattr(dashboard, '_cloud_engine_thread', types.SimpleNamespace(is_alive=lambda: True))

        thread_created = []
        def fake_thread(**kw):
            thread_created.append(True)
            return types.SimpleNamespace(start=lambda: None)
        monkeypatch.setattr(dashboard.threading, 'Thread', fake_thread)

        dashboard._ensure_cloud_engine()

        # Should return immediately without creating thread or lock
        assert thread_created == []
