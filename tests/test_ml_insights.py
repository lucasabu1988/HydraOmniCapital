import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import compass_ml_learning as ml


def write_jsonl_lines(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '\n'.join(json.dumps(row) for row in rows) + ('\n' if rows else ''),
        encoding='utf-8',
    )


class StubEngine:
    def __init__(self, phase, results):
        self._phase = phase
        self._results = results

    def get_phase(self):
        return self._phase

    def run(self):
        return self._results


class StubStopOptimizer:
    def __init__(self, result):
        self._result = result

    def analyze(self):
        return self._result


@pytest.fixture(autouse=True)
def isolate_ml_paths(monkeypatch, tmp_path):
    ml_dir = tmp_path / 'state' / 'ml_learning'
    models_dir = ml_dir / 'models'
    ml_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ml, 'DECISIONS_FILE', str(ml_dir / 'decisions.jsonl'))
    monkeypatch.setattr(ml, 'OUTCOMES_FILE', str(ml_dir / 'outcomes.jsonl'))
    monkeypatch.setattr(ml, 'SNAPSHOTS_FILE', str(ml_dir / 'daily_snapshots.jsonl'))
    monkeypatch.setattr(ml, 'INSIGHTS_FILE', str(ml_dir / 'insights.json'))
    monkeypatch.setattr(ml, 'MODELS_DIR', str(models_dir))

    return ml_dir


def test_insight_reporter_generate_returns_summary_and_persists_report(isolate_ml_paths):
    decision_rows = [
        {'decision_id': f'd-{idx}', 'decision_type': 'entry' if idx < 20 else ('hold' if idx < 28 else 'skip')}
        for idx in range(30)
    ]
    outcome_rows = [
        {'outcome_id': f'o-{idx}', 'gross_return': 0.01 * ((idx % 3) - 1), 'outcome_label': 'weak_win'}
        for idx in range(12)
    ]
    snapshot_rows = [
        {'date': f'2026-03-{idx + 1:02d}', 'portfolio_value': 100000.0 + (idx * 1500.0)}
        for idx in range(5)
    ]
    write_jsonl_lines(Path(ml.DECISIONS_FILE), decision_rows)
    write_jsonl_lines(Path(ml.OUTCOMES_FILE), outcome_rows)
    write_jsonl_lines(Path(ml.SNAPSHOTS_FILE), snapshot_rows)

    feature_store = ml.FeatureStore(str(isolate_ml_paths))
    engine = StubEngine(
        phase=2,
        results={
            'phase1': {'overall': {'mean_return': 0.0123}},
            'phase2': {'ridge_r2_cv': 0.11, 'n_samples': 12},
        },
    )
    stop_optimizer = StubStopOptimizer({
        'n_outcomes': 12,
        'suggestions': [{'parameter': 'STOP_FLOOR'}],
        'warnings': ['sample warning'],
    })

    reporter = ml.InsightReporter(engine, stop_optimizer, feature_store, trading_days=84)
    report = reporter.generate()
    saved = json.loads(Path(ml.INSIGHTS_FILE).read_text(encoding='utf-8'))

    assert report['learning_phase'] == 2
    assert report['data_summary']['total_decisions'] == 30
    assert report['data_summary']['completed_trades'] == 12
    assert report['data_summary']['daily_snapshots'] == 5
    assert report['data_summary']['decisions_by_type'] == {'entry': 20, 'hold': 8, 'skip': 2}
    assert report['trade_analytics']['overall']['mean_return'] == pytest.approx(0.0123)
    assert report['ml_models']['ridge_r2_cv'] == pytest.approx(0.11)
    assert report['portfolio_analytics']['n_days'] == 5
    assert report['portfolio_analytics']['start_value'] == 100000.0
    assert report['portfolio_analytics']['current_value'] == 106000.0
    assert report['portfolio_analytics']['total_return'] == pytest.approx(0.06)
    assert report['parameter_suggestions'] == [{'parameter': 'STOP_FLOOR'}]
    assert report['warnings'] == ['sample warning']
    assert 'Phase 3 full ML begins' in report['next_milestone']
    assert saved['data_summary'] == report['data_summary']
    assert saved['portfolio_analytics'] == report['portfolio_analytics']


def test_insight_reporter_data_summary_matches_jsonl_counts(isolate_ml_paths):
    write_jsonl_lines(
        Path(ml.DECISIONS_FILE),
        [
            {'decision_id': 'd1', 'decision_type': 'entry'},
            {'decision_id': 'd2', 'decision_type': 'skip'},
            {'decision_id': 'd3', 'decision_type': 'hold'},
            {'decision_id': 'd4', 'decision_type': 'entry'},
        ],
    )
    write_jsonl_lines(
        Path(ml.OUTCOMES_FILE),
        [
            {'outcome_id': 'o1', 'gross_return': 0.04},
            {'outcome_id': 'o2', 'gross_return': -0.02},
        ],
    )
    write_jsonl_lines(
        Path(ml.SNAPSHOTS_FILE),
        [
            {'date': '2026-03-01', 'portfolio_value': 100000.0},
            {'date': '2026-03-02', 'portfolio_value': 100500.0},
            {'date': '2026-03-03', 'portfolio_value': 101000.0},
        ],
    )

    feature_store = ml.FeatureStore(str(isolate_ml_paths))
    reporter = ml.InsightReporter(
        StubEngine(phase=1, results={'phase1': {}}),
        StubStopOptimizer({'suggestions': [], 'warnings': []}),
        feature_store,
        trading_days=3,
    )

    summary = reporter._data_summary()

    assert summary == {
        'total_decisions': 4,
        'completed_trades': 2,
        'daily_snapshots': 3,
        'decisions_by_type': {'entry': 2, 'skip': 1, 'hold': 1},
    }


@pytest.mark.parametrize(
    'phase,trading_days,expected_fragment',
    [
        (1, 10, 'Phase 2 ML begins in ~53 trading days'),
        (2, 84, 'Phase 3 full ML begins in ~168 trading days'),
        (3, 300, 'Phase 3 full ML active'),
    ],
)
def test_insight_reporter_next_milestone_messages(
    isolate_ml_paths,
    phase,
    trading_days,
    expected_fragment,
):
    reporter = ml.InsightReporter(
        StubEngine(phase=phase, results={'phase1': {}}),
        StubStopOptimizer({'suggestions': [], 'warnings': []}),
        ml.FeatureStore(str(isolate_ml_paths)),
        trading_days=trading_days,
    )

    assert expected_fragment in reporter._next_milestone(phase)


def test_insight_reporter_generate_handles_empty_feature_store(isolate_ml_paths):
    feature_store = ml.FeatureStore(str(isolate_ml_paths))
    reporter = ml.InsightReporter(
        StubEngine(phase=1, results={'phase1': {'status': 'no_completed_trades_yet'}}),
        StubStopOptimizer({'status': 'insufficient_data', 'suggestions': [], 'warnings': []}),
        feature_store,
        trading_days=8,
    )

    report = reporter.generate()

    assert report['data_summary']['total_decisions'] == 0
    assert report['data_summary']['completed_trades'] == 0
    assert report['data_summary']['daily_snapshots'] == 0
    assert report['data_summary']['decisions_by_type'] == {}
    assert report['portfolio_analytics'] == {}
    assert report['stop_analysis']['status'] == 'insufficient_data'
    assert 'Phase 2 ML begins' in report['next_milestone']
    assert Path(ml.INSIGHTS_FILE).exists()
