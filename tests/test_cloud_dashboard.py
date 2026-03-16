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
        'stats': {'uptime_minutes': 42},
        'portfolio_values_history': [103000.0],
        'hydra': {
            'rattle_positions': [],
            'catalyst_positions': [],
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
    dashboard._yf_session = None
    dashboard._yf_crumb = None
    dashboard._social_cache = {}
    dashboard._social_cache_time = None
    dashboard._trade_analytics_cache = None
    dashboard._montecarlo_cache = None
    dashboard._equity_df = None
    dashboard._spy_df = None
    dashboard._cloud_engine = None
    dashboard._cloud_engine_started = False
    dashboard._self_ping_started = False
    dashboard._engine_status = {
        'running': False,
        'started_at': None,
        'error': None,
        'cycles': 0,
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

    dashboard._run_cloud_engine()

    assert 'omnicapital_live import failed' in dashboard._engine_status['error']


def test_ensure_cloud_engine_acquires_lock_and_starts_thread(monkeypatch):
    started = {}

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            started['target'] = target
            started['daemon'] = daemon

        def start(self):
            started['started'] = True

    monkeypatch.setattr(dashboard, 'AGENT_MODE', False)
    monkeypatch.setattr(dashboard, 'SHOWCASE_MODE', False)
    monkeypatch.setattr(dashboard.threading, 'Thread', FakeThread)
    monkeypatch.setattr(dashboard, '_run_cloud_engine', lambda: None)

    dashboard._ensure_cloud_engine()

    assert started['daemon'] is True
    assert started['started'] is True
    assert Path('state/.cloud_engine.lock').exists()


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
