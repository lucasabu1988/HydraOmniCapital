import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import compass_dashboard_cloud as dashboard


class FakeResponse:
    def __init__(self, status_code, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({
            'url': url,
            'params': params,
            'timeout': timeout,
        })
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def isolate_yahoo(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    dashboard._price_cache = {}
    dashboard._prev_close_cache = {}
    dashboard._price_cache_time = None
    dashboard._yf_consecutive_failures = 0
    dashboard._yf_session = None
    dashboard._yf_crumb = None
    monkeypatch.setattr(dashboard, '_HAS_REQUESTS', True)


def test_fetch_live_prices_returns_cached_when_fresh(monkeypatch):
    dashboard._price_cache = {'AAPL': 123.45}
    dashboard._price_cache_time = datetime.now()

    def should_not_fetch(symbols):
        raise AssertionError('Yahoo fetch should not run for a fresh cache hit')

    monkeypatch.setattr(dashboard, '_yf_fetch_batch', should_not_fetch)

    prices = dashboard.fetch_live_prices(['AAPL'])

    assert prices == {'AAPL': 123.45}


def test_fetch_live_prices_fetches_when_cache_expired(monkeypatch):
    dashboard._price_cache = {'AAPL': 120.0}
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=120)
    called = {}

    def fake_fetch(symbols):
        called['symbols'] = list(symbols)
        return {'AAPL': {'price': 150.0, 'prev_close': 149.0}}

    monkeypatch.setattr(dashboard, '_yf_fetch_batch', fake_fetch)

    prices = dashboard.fetch_live_prices(['AAPL'])

    assert prices == {'AAPL': 150.0}
    assert called['symbols'] == ['AAPL']
    assert dashboard._prev_close_cache['AAPL'] == 149.0


def test_fetch_live_prices_keeps_stale_on_failure(monkeypatch):
    dashboard._price_cache = {'AAPL': 121.0}
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=120)
    monkeypatch.setattr(dashboard, '_yf_fetch_batch', lambda symbols: {})

    prices = dashboard.fetch_live_prices(['AAPL'])

    assert prices == {'AAPL': 121.0}
    assert dashboard._yf_consecutive_failures == 1


def test_consecutive_failures_increases_cache_ttl(monkeypatch):
    dashboard._price_cache = {'AAPL': 122.0}
    dashboard._price_cache_time = datetime.now() - timedelta(seconds=120)
    dashboard._yf_consecutive_failures = 3

    def should_not_fetch(symbols):
        raise AssertionError('Backoff TTL should keep cached price fresh enough')

    monkeypatch.setattr(dashboard, '_yf_fetch_batch', should_not_fetch)

    prices = dashboard.fetch_live_prices(['AAPL'])

    assert prices == {'AAPL': 122.0}


def test_yf_fetch_batch_parses_valid_response(monkeypatch):
    session = FakeSession([
        FakeResponse(200, {
            'quoteResponse': {
                'result': [
                    {
                        'symbol': 'AAPL',
                        'regularMarketPrice': 187.5,
                        'regularMarketPreviousClose': 185.25,
                    }
                ]
            }
        })
    ])
    monkeypatch.setattr(dashboard, '_yf_get_session', lambda: (session, 'crumb-123'))

    result = dashboard._yf_fetch_batch(['AAPL'])

    assert result == {'AAPL': {'price': 187.5, 'prev_close': 185.25}}
    assert session.calls[0]['params']['crumb'] == 'crumb-123'


def test_yf_fetch_batch_uses_v8_fallback_when_session_unavailable(monkeypatch):
    called = []
    monkeypatch.setattr(dashboard, '_yf_get_session', lambda: (None, None))

    def fake_get(url, params=None, headers=None, timeout=None):
        called.append(url)
        return FakeResponse(200, {
            'chart': {
                'result': [{
                    'meta': {
                        'regularMarketPrice': 201.0,
                        'chartPreviousClose': 199.5,
                    }
                }]
            }
        })

    monkeypatch.setattr(dashboard.http_requests, 'get', fake_get)
    monkeypatch.setattr(dashboard.time_module, 'sleep', lambda seconds: None)

    result = dashboard._yf_fetch_batch(['MSFT'])

    assert result == {'MSFT': {'price': 201.0, 'prev_close': 199.5}}
    assert called and called[0].endswith('/MSFT')


def test_yf_fetch_batch_handles_401_resets_session(monkeypatch):
    session = FakeSession([FakeResponse(401)])
    monkeypatch.setattr(dashboard, '_yf_get_session', lambda: (session, 'expired-crumb'))
    monkeypatch.setattr(dashboard.http_requests, 'get',
                        lambda *args, **kwargs: FakeResponse(429))
    dashboard._yf_session = object()
    dashboard._yf_crumb = 'expired-crumb'

    result = dashboard._yf_fetch_batch(['AAPL'])

    assert result == {}
    assert dashboard._yf_session is None
    assert dashboard._yf_crumb is None


def test_yf_fetch_batch_handles_rate_limit(monkeypatch):
    calls = []
    monkeypatch.setattr(dashboard, '_yf_get_session', lambda: (None, None))

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(url)
        return FakeResponse(429)

    monkeypatch.setattr(dashboard.http_requests, 'get', fake_get)

    result = dashboard._yf_fetch_batch(['AAPL', 'MSFT'])

    assert result == {}
    assert len(calls) == 1
    assert calls[0].endswith('/AAPL')


def test_yf_get_session_creates_session_with_crumb(monkeypatch):
    session = FakeSession([
        FakeResponse(200),
        FakeResponse(200, text='crumb-token'),
    ])
    monkeypatch.setattr(dashboard.http_requests, 'Session', lambda: session)

    created_session, crumb = dashboard._yf_get_session()

    assert created_session is session
    assert crumb == 'crumb-token'
    assert dashboard._yf_session is session
    assert dashboard._yf_crumb == 'crumb-token'
    assert 'User-Agent' in session.headers


def test_yf_reset_session_clears_globals():
    dashboard._yf_session = object()
    dashboard._yf_crumb = 'crumb-token'

    dashboard._yf_reset_session()

    assert dashboard._yf_session is None
    assert dashboard._yf_crumb is None


def test_fetch_live_prices_returns_empty_dict_for_empty_symbols():
    assert dashboard.fetch_live_prices([]) == {}


def test_yf_fetch_batch_returns_empty_dict_for_empty_symbols():
    assert dashboard._yf_fetch_batch([]) == {}
