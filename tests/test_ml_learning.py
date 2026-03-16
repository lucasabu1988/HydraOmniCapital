import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import compass_ml_learning as ml


def read_jsonl(path):
    records = []
    if not path.exists():
        return records
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


class StubFeatureStore:
    def __init__(self, decisions=None, outcomes=None, snapshots=None):
        self._decisions = pd.DataFrame(decisions or [])
        self._outcomes = pd.DataFrame(outcomes or [])
        self._snapshots = pd.DataFrame(snapshots or [])

    def load_decisions(self, decision_type=None):
        if self._decisions.empty:
            return pd.DataFrame()
        if decision_type is None:
            return self._decisions.copy()
        return self._decisions[self._decisions['decision_type'] == decision_type].copy()

    def load_outcomes(self):
        return self._outcomes.copy()

    def load_snapshots(self):
        return self._snapshots.copy()


class StubEngine:
    def __init__(self, phase=1, results=None):
        self.phase = phase
        self.results = results or {'phase1': {}}

    def get_phase(self):
        return self.phase

    def run(self):
        return self.results


class StubStopOptimizer:
    def __init__(self, result):
        self.result = result

    def analyze(self):
        return self.result


def make_feature_matrix(n_rows):
    idx = np.arange(n_rows)
    target_return = np.where(idx % 2 == 0, 0.02, -0.015) + (idx * 0.0001)

    return pd.DataFrame({
        'feat_momentum_score': np.linspace(0.2, 0.9, n_rows),
        'feat_regime_score': np.where(idx % 3 == 0, 0.7, 0.45),
        'feat_entry_daily_vol': np.linspace(0.01, 0.03, n_rows),
        'feat_spy_vs_sma200': np.where(idx % 2 == 0, 0.015, -0.01),
        'target_return': target_return,
    })


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


@pytest.fixture
def logger(isolate_ml_paths):
    return ml.DecisionLogger(str(isolate_ml_paths))


def test_log_entry_writes_valid_jsonl_record(logger):
    decision_id = logger.log_entry(
        symbol='AAPL',
        sector='Technology',
        momentum_score=0.91,
        momentum_rank=0.95,
        entry_vol_ann=0.22,
        entry_daily_vol=0.014,
        adaptive_stop_pct=-0.08,
        trailing_stop_pct=0.03,
        regime_score=0.7,
        max_positions_target=5,
        current_n_positions=2,
        portfolio_value=100000.0,
        portfolio_drawdown=-0.01,
        current_leverage=1.0,
        crash_cooldown=0,
        trading_day=12,
    )

    records = read_jsonl(Path(ml.DECISIONS_FILE))

    assert len(records) == 1
    assert records[0]['decision_id'] == decision_id
    assert records[0]['decision_type'] == 'entry'
    assert records[0]['symbol'] == 'AAPL'
    assert records[0]['momentum_score'] == 0.91


def test_log_exit_writes_exit_and_outcome_records(logger):
    entry_id = logger.log_entry(
        symbol='AAPL',
        sector='Technology',
        momentum_score=0.91,
        momentum_rank=0.95,
        entry_vol_ann=0.22,
        entry_daily_vol=0.014,
        adaptive_stop_pct=-0.08,
        trailing_stop_pct=0.03,
        regime_score=0.7,
        max_positions_target=5,
        current_n_positions=2,
        portfolio_value=100000.0,
        portfolio_drawdown=-0.01,
        current_leverage=1.0,
        crash_cooldown=0,
        trading_day=12,
    )

    logger.log_exit(
        symbol='AAPL',
        sector='Technology',
        exit_reason='hold_expired',
        entry_price=100.0,
        exit_price=108.0,
        pnl_usd=800.0,
        days_held=5,
        high_price=110.0,
        entry_vol_ann=0.22,
        entry_daily_vol=0.014,
        adaptive_stop_pct=-0.08,
        entry_momentum_score=0.91,
        entry_momentum_rank=0.95,
        regime_score=0.7,
        max_positions_target=5,
        current_n_positions=1,
        portfolio_value=108000.0,
        portfolio_drawdown=-0.005,
        current_leverage=1.0,
        crash_cooldown=0,
        trading_day=17,
        spy_return_during_hold=0.01,
    )

    decision_records = read_jsonl(Path(ml.DECISIONS_FILE))
    outcome_records = read_jsonl(Path(ml.OUTCOMES_FILE))

    assert len(decision_records) == 2
    assert decision_records[-1]['decision_type'] == 'exit'
    assert len(outcome_records) == 1
    assert outcome_records[0]['entry_decision_id'] == entry_id
    assert outcome_records[0]['outcome_label'] == 'strong_win'
    assert outcome_records[0]['alpha_vs_spy'] == 0.07


def test_log_skip_writes_skip_record(logger):
    logger.log_skip(
        symbol='MSFT',
        sector='Technology',
        skip_reason='not_top_n',
        universe_rank=7,
        momentum_score=0.64,
        regime_score=0.58,
        trading_day=13,
        portfolio_value=101000.0,
        portfolio_drawdown=-0.02,
        current_n_positions=5,
        max_positions_target=5,
        spy_price=505.0,
        spy_sma200=500.0,
        spy_regime_score=0.61,
    )

    records = read_jsonl(Path(ml.DECISIONS_FILE))

    assert len(records) == 1
    assert records[0]['decision_type'] == 'skip'
    assert records[0]['skip_reason'] == 'not_top_n'
    assert records[0]['skip_universe_rank'] == 7
    assert records[0]['spy_price'] == 505.0
    assert records[0]['spy_sma200'] == 500.0
    assert records[0]['spy_vs_sma200_pct'] == pytest.approx(0.01)
    assert records[0]['regime_score'] == 0.61


def test_log_hold_writes_hold_record(logger):
    logger.log_hold(
        symbol='NVDA',
        sector='Technology',
        days_held=3,
        current_return=0.045,
        drawdown_from_high=-0.02,
        entry_daily_vol=0.018,
        adaptive_stop_pct=-0.07,
        regime_score=0.62,
        trading_day=14,
        portfolio_value=103000.0,
        portfolio_drawdown=-0.01,
        spy_price=498.0,
        spy_sma200=500.0,
        spy_regime_score=0.57,
    )

    records = read_jsonl(Path(ml.DECISIONS_FILE))

    assert len(records) == 1
    assert records[0]['decision_type'] == 'hold'
    assert records[0]['days_held'] == 3
    assert records[0]['current_return'] == 0.045
    assert records[0]['spy_price'] == 498.0
    assert records[0]['spy_sma200'] == 500.0
    assert records[0]['spy_vs_sma200_pct'] == pytest.approx(-0.004)
    assert records[0]['regime_score'] == 0.57


def test_jsonl_lines_are_independently_valid_json(logger):
    logger.log_skip(
        symbol='MSFT',
        sector='Technology',
        skip_reason='sector_limit',
        universe_rank=8,
        momentum_score=0.61,
        regime_score=0.58,
        trading_day=13,
        portfolio_value=101000.0,
        portfolio_drawdown=-0.02,
        current_n_positions=4,
        max_positions_target=5,
    )
    logger.log_hold(
        symbol='NVDA',
        sector='Technology',
        days_held=2,
        current_return=0.03,
        drawdown_from_high=-0.01,
        entry_daily_vol=0.02,
        adaptive_stop_pct=-0.07,
        regime_score=0.6,
        trading_day=14,
        portfolio_value=102000.0,
        portfolio_drawdown=-0.015,
    )

    raw_lines = Path(ml.DECISIONS_FILE).read_text(encoding='utf-8').splitlines()

    assert len(raw_lines) == 2
    assert all(isinstance(json.loads(line), dict) for line in raw_lines)


def test_build_entry_feature_matrix_returns_empty_without_outcomes(isolate_ml_paths):
    feature_store = ml.FeatureStore(str(isolate_ml_paths))

    matrix = feature_store.build_entry_feature_matrix()

    assert matrix.empty


def test_build_entry_feature_matrix_returns_empty_without_entries(isolate_ml_paths):
    outcomes = [{
        'entry_decision_id': 'missing',
        'symbol': 'AAPL',
        'sector': 'Technology',
        'gross_return': 0.05,
        'outcome_label': 'strong_win',
        'beat_spy': True,
        'exit_reason': 'hold_expired',
        'trading_days_held': 5,
        'entry_date': '2026-03-10',
        'exit_date': '2026-03-15',
    }]
    Path(ml.OUTCOMES_FILE).write_text(json.dumps(outcomes[0]) + '\n', encoding='utf-8')
    feature_store = ml.FeatureStore(str(isolate_ml_paths))

    matrix = feature_store.build_entry_feature_matrix()

    assert matrix.empty


def test_build_entry_feature_matrix_populated_from_logged_trade(logger, isolate_ml_paths):
    entry_id = logger.log_entry(
        symbol='AAPL',
        sector='Technology',
        momentum_score=0.88,
        momentum_rank=0.91,
        entry_vol_ann=0.24,
        entry_daily_vol=0.016,
        adaptive_stop_pct=-0.08,
        trailing_stop_pct=0.03,
        regime_score=0.72,
        max_positions_target=5,
        current_n_positions=2,
        portfolio_value=100000.0,
        portfolio_drawdown=-0.01,
        current_leverage=0.9,
        crash_cooldown=0,
        trading_day=10,
    )
    logger.log_exit(
        symbol='AAPL',
        sector='Technology',
        exit_reason='hold_expired',
        entry_price=100.0,
        exit_price=104.0,
        pnl_usd=400.0,
        days_held=5,
        high_price=106.0,
        entry_vol_ann=0.24,
        entry_daily_vol=0.016,
        adaptive_stop_pct=-0.08,
        entry_momentum_score=0.88,
        entry_momentum_rank=0.91,
        regime_score=0.72,
        max_positions_target=5,
        current_n_positions=1,
        portfolio_value=104000.0,
        portfolio_drawdown=-0.008,
        current_leverage=0.9,
        crash_cooldown=0,
        trading_day=15,
        spy_return_during_hold=0.02,
    )

    feature_store = ml.FeatureStore(str(isolate_ml_paths))
    matrix = feature_store.build_entry_feature_matrix()

    assert len(matrix) == 1
    assert matrix.iloc[0]['symbol'] == 'AAPL'
    assert matrix.iloc[0]['target_return'] == 0.04
    assert matrix.iloc[0]['target_beat_spy'] == 1
    assert matrix.iloc[0]['feat_momentum_score'] == 0.88
    assert matrix.iloc[0]['feat_spy_vs_sma200'] == 0.0
    assert entry_id in read_jsonl(Path(ml.OUTCOMES_FILE))[0]['entry_decision_id']


def test_sanitize_for_json_recursively_handles_nested_nan_and_inf():
    payload = {
        'alpha': np.nan,
        'nested': [1.0, np.inf, {'beta': -np.inf}],
    }

    sanitized = ml._sanitize_for_json(payload)

    assert sanitized == {
        'alpha': None,
        'nested': [1.0, None, {'beta': None}],
    }


def test_insight_reporter_generate_writes_valid_json(isolate_ml_paths):
    feature_store = StubFeatureStore(
        decisions=[{'decision_type': 'entry'}, {'decision_type': 'exit'}],
        outcomes=[{'gross_return': 0.03}],
        snapshots=[
            {'portfolio_value': 100000.0},
            {'portfolio_value': 101500.0},
        ],
    )
    engine = StubEngine(
        phase=1,
        results={'phase1': {'overall': {'mean_return': 0.03}}},
    )
    stop_optimizer = StubStopOptimizer({
        'status': 'ok',
        'suggestions': [],
        'warnings': [],
    })

    reporter = ml.InsightReporter(engine, stop_optimizer, feature_store, trading_days=12)
    report = reporter.generate()
    saved = json.loads(Path(ml.INSIGHTS_FILE).read_text(encoding='utf-8'))

    assert report['learning_phase'] == 1
    assert saved['data_summary']['total_decisions'] == 2
    assert saved['portfolio_analytics']['current_value'] == 101500.0


def test_insight_reporter_generate_sanitizes_nan_values(isolate_ml_paths):
    feature_store = StubFeatureStore(
        decisions=[{'decision_type': 'entry'}],
        outcomes=[{'gross_return': 0.01}],
        snapshots=[
            {'portfolio_value': 100000.0},
            {'portfolio_value': 101000.0},
        ],
    )
    engine = StubEngine(
        phase=1,
        results={'phase1': {'overall': {'mean_return': np.nan}}},
    )
    stop_optimizer = StubStopOptimizer({
        'status': 'ok',
        'suggestions': [{'threshold': np.inf}],
        'warnings': [np.nan],
    })

    reporter = ml.InsightReporter(engine, stop_optimizer, feature_store, trading_days=8)
    report = reporter.generate()
    raw_text = Path(ml.INSIGHTS_FILE).read_text(encoding='utf-8')
    saved = json.loads(raw_text)

    assert report['trade_analytics']['overall']['mean_return'] is None
    assert saved['parameter_suggestions'][0]['threshold'] is None
    assert saved['warnings'] == [None]
    assert 'NaN' not in raw_text
    assert 'Infinity' not in raw_text


@pytest.mark.parametrize(
    'gross_return,exit_reason,expected',
    [
        (-0.08, 'position_stop', 'stop_loss'),
        (0.041, 'hold_expired', 'strong_win'),
        (0.02, 'hold_expired', 'weak_win'),
        (0.0, 'hold_expired', 'flat'),
        (-0.01, 'hold_expired', 'flat'),
        (-0.0101, 'hold_expired', 'weak_loss'),
    ],
)
def test_classify_outcome_boundaries(gross_return, exit_reason, expected):
    assert ml.DecisionLogger._classify_outcome(gross_return, exit_reason) == expected


def test_learning_engine_run_stays_in_phase1_below_63_days(isolate_ml_paths):
    feature_store = ml.FeatureStore(str(isolate_ml_paths))
    engine = ml.LearningEngine(feature_store, trading_days_available=62)

    result = engine.run()

    assert result['phase'] == 1
    assert 'phase2' not in result
    assert 'phase3' not in result


def test_learning_engine_phase1_handles_empty_outcomes(isolate_ml_paths):
    feature_store = ml.FeatureStore(str(isolate_ml_paths))
    engine = ml.LearningEngine(feature_store, trading_days_available=10)

    result = engine.run()

    assert result['phase1']['status'] == 'no_completed_trades_yet'


def test_learning_engine_enters_phase2_at_63_days(isolate_ml_paths, monkeypatch):
    pytest.importorskip('sklearn')
    feature_store = ml.FeatureStore(str(isolate_ml_paths))
    monkeypatch.setattr(
        feature_store,
        'build_entry_feature_matrix',
        lambda: make_feature_matrix(20),
    )
    engine = ml.LearningEngine(feature_store, trading_days_available=63)

    result = engine.run()

    assert result['phase'] == 2
    assert result['phase2']['n_samples'] == 20
    assert 'top_features_by_coef' in result['phase2']
    assert Path(ml.MODELS_DIR, 'phase2_ridge_meta.json').exists()


def test_learning_engine_phase2_insufficient_data(isolate_ml_paths):
    feature_store = ml.FeatureStore(str(isolate_ml_paths))
    engine = ml.LearningEngine(feature_store, trading_days_available=63)

    result = engine.run()

    assert result['phase'] == 2
    assert result['phase2']['status'] == 'insufficient_data'
    assert result['phase2']['required'] == 20


def test_learning_engine_enters_phase3_at_252_days(isolate_ml_paths, monkeypatch):
    pytest.importorskip('sklearn')
    feature_store = ml.FeatureStore(str(isolate_ml_paths))
    monkeypatch.setattr(
        feature_store,
        'build_entry_feature_matrix',
        lambda: make_feature_matrix(100),
    )
    engine = ml.LearningEngine(feature_store, trading_days_available=252)

    result = engine.run()

    assert result['phase'] == 3
    assert result['phase2']['n_samples'] == 100
    assert result['phase3']['n_samples'] == 100
    assert result['phase3']['model_type'] in {'RandomForest', 'LightGBM'}
