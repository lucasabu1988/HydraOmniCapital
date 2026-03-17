import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import compass_dashboard as dashboard


@pytest.fixture(autouse=True)
def isolate_dashboard(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'state' / 'ml_learning').mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(
        dashboard,
        '_maybe_regenerate_interpretation',
        lambda *args, **kwargs: None,
    )
    yield tmp_path


@pytest.fixture
def client():
    return dashboard.app.test_client()


@pytest.mark.parametrize('constant', ['NaN', 'Infinity', '-Infinity'])
def test_api_ml_learning_sanitizes_invalid_constants_in_local_insights(client, constant):
    Path('state/ml_learning/insights.json').write_text(
        (
            '{"trading_days": 5, "learning_phase": 1, '
            '"stop_analysis": {"avg_return_when_not_stopped": '
            f'{constant}'  # deliberately invalid JSON constants from legacy files
            '}}'
        ),
        encoding='utf-8',
    )

    response = client.get('/api/ml-learning')

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['insights']['stop_analysis']['avg_return_when_not_stopped'] is None


def test_api_state_includes_price_data_age_seconds(client, monkeypatch, isolate_dashboard):
    import json
    tmp_path = isolate_dashboard
    state_file = tmp_path / 'state' / 'compass_state_latest.json'
    state_file.write_text(json.dumps({
        'positions': {},
        'cash': 10000.0,
        'portfolio_value': 10000.0,
        'current_regime_score': 0.5,
        'trading_day_counter': 1,
    }), encoding='utf-8')
    monkeypatch.setattr(dashboard, 'STATE_FILE', str(state_file))
    monkeypatch.setattr(dashboard, 'fetch_live_prices', lambda symbols: {})
    monkeypatch.setattr(dashboard, 'compute_position_details', lambda s, p, pc: [])
    monkeypatch.setattr(dashboard, 'compute_portfolio_metrics', lambda s, p: {
        'cash': 10000.0, 'portfolio_value': 10000.0,
    })

    response = client.get('/api/state')

    assert response.status_code == 200
    payload = response.get_json()
    assert 'price_data_age_seconds' in payload
    assert isinstance(payload['price_data_age_seconds'], int)
