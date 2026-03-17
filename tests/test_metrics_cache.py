import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import compass_dashboard as dashboard


@pytest.fixture(autouse=True)
def reset_cache(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'state').mkdir(parents=True, exist_ok=True)
    dashboard._metrics_cache = None
    dashboard._metrics_cache_time = None
    dashboard._metrics_cache_mtime = None
    yield tmp_path
    dashboard._metrics_cache = None
    dashboard._metrics_cache_time = None
    dashboard._metrics_cache_mtime = None


def _write_state(tmp_path, state):
    state_file = tmp_path / 'state' / 'compass_state_latest.json'
    state_file.write_text(json.dumps(state))
    return state_file


def _minimal_state():
    return {
        'portfolio_value': 100000,
        'peak_value': 100000,
        'cash': 50000,
        'positions': {},
        'position_meta': {},
        'current_regime': True,
        'current_regime_score': 0.8,
        'trading_day_counter': 10,
        'stats': {},
    }


def test_cache_returns_same_result_within_ttl(reset_cache, monkeypatch):
    tmp_path = reset_cache
    _write_state(tmp_path, _minimal_state())
    monkeypatch.setattr(dashboard, 'STATE_FILE',
                        str(tmp_path / 'state' / 'compass_state_latest.json'))

    state = _minimal_state()
    prices = {'SPY': 500.0}

    result1 = dashboard.compute_portfolio_metrics(state, prices)
    result2 = dashboard.compute_portfolio_metrics(state, prices)

    assert result1 is result2, "Second call should return cached object"


def test_cache_invalidates_on_state_file_change(reset_cache, monkeypatch):
    tmp_path = reset_cache
    state_path = _write_state(tmp_path, _minimal_state())
    monkeypatch.setattr(dashboard, 'STATE_FILE', str(state_path))

    state = _minimal_state()
    prices = {'SPY': 500.0}

    result1 = dashboard.compute_portfolio_metrics(state, prices)

    # Touch the state file to change mtime
    time.sleep(0.05)
    state_path.write_text(json.dumps(_minimal_state()))

    result2 = dashboard.compute_portfolio_metrics(state, prices)

    assert result1 is not result2, "Should recompute after state file change"


def test_cache_invalidates_after_ttl(reset_cache, monkeypatch):
    tmp_path = reset_cache
    state_path = _write_state(tmp_path, _minimal_state())
    monkeypatch.setattr(dashboard, 'STATE_FILE', str(state_path))

    state = _minimal_state()
    prices = {'SPY': 500.0}

    result1 = dashboard.compute_portfolio_metrics(state, prices)

    # Simulate TTL expiry by backdating cache time
    dashboard._metrics_cache_time -= 31

    result2 = dashboard.compute_portfolio_metrics(state, prices)

    assert result1 is not result2, "Should recompute after TTL expires"
