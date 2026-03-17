import json
import logging
import sys
import uuid
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


def write_jsonl_lines(path, lines):
    rendered = []
    for line in lines:
        if isinstance(line, str):
            rendered.append(line)
        else:
            rendered.append(json.dumps(line))
    path.write_text('\n'.join(rendered) + '\n', encoding='utf-8')


def assert_uuid4_hex(value):
    parsed = uuid.UUID(value)

    assert parsed.hex == value
    assert parsed.version == 4


def assert_decision_record_shape(record, expected_type):
    assert set(record) == set(ml.DecisionRecord.__dataclass_fields__)
    assert_uuid4_hex(record['decision_id'])
    assert record['decision_type'] == expected_type
    assert isinstance(record['timestamp'], str)
    assert isinstance(record['trading_day'], int)
    assert isinstance(record['date'], str)
    assert isinstance(record['symbol'], str)
    assert isinstance(record['sector'], str)
    assert isinstance(record['portfolio_value'], float)
    assert isinstance(record['portfolio_drawdown'], float)


def assert_outcome_record_shape(record):
    assert set(record) == set(ml.OutcomeRecord.__dataclass_fields__)
    assert_uuid4_hex(record['outcome_id'])
    assert isinstance(record['entry_decision_id'], str)
    assert isinstance(record['symbol'], str)
    assert isinstance(record['gross_return'], float)
    assert isinstance(record['pnl_usd'], float)
    assert isinstance(record['trading_days_held'], int)
    assert isinstance(record['outcome_label'], str)
    assert isinstance(record['beat_spy'], bool)


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


@pytest.fixture
def orchestrator(isolate_ml_paths):
    return ml.COMPASSMLOrchestrator(str(isolate_ml_paths))


def test_log_entry_writes_valid_jsonl_record(logger, isolate_ml_paths):
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
    restored_logger = ml.DecisionLogger(str(isolate_ml_paths))
    restored_open_entries = restored_logger._load_open_entries()

    assert len(records) == 1
    assert_decision_record_shape(records[0], 'entry')
    assert records[0]['decision_id'] == decision_id
    assert records[0]['symbol'] == 'AAPL'
    assert records[0]['momentum_score'] == 0.91
    assert records[0]['momentum_rank'] == 0.95
    assert records[0]['current_leverage'] == 1.0
    assert records[0]['spy_price'] is None
    assert records[0]['exit_reason'] is None
    assert restored_open_entries['AAPL']['decision_id'] == decision_id
    assert restored_open_entries['AAPL']['entry_date'] == records[0]['date']
    assert restored_open_entries['AAPL']['entry_regime_score'] == 0.7
    assert restored_open_entries['AAPL']['entry_portfolio_drawdown'] == -0.01


def test_log_exit_writes_exit_and_outcome_records(logger, isolate_ml_paths):
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
    restored_logger = ml.DecisionLogger(str(isolate_ml_paths))

    assert len(decision_records) == 2
    assert_decision_record_shape(decision_records[-1], 'exit')
    assert decision_records[-1]['current_return'] == pytest.approx(0.08)
    assert decision_records[-1]['drawdown_from_high'] == pytest.approx(-0.01818181818181818)
    assert decision_records[-1]['exit_reason'] == 'hold_expired'
    assert len(outcome_records) == 1
    assert_outcome_record_shape(outcome_records[0])
    assert outcome_records[0]['entry_decision_id'] == entry_id
    assert outcome_records[0]['gross_return'] == pytest.approx(0.08)
    assert outcome_records[0]['pnl_usd'] == 800.0
    assert outcome_records[0]['trading_days_held'] == 5
    assert outcome_records[0]['outcome_label'] == 'strong_win'
    assert outcome_records[0]['alpha_vs_spy'] == 0.07
    assert restored_logger._load_open_entries() == {}


def test_log_exit_without_open_entry_logs_warning_and_uses_fallback_context(logger, caplog):
    with caplog.at_level(logging.WARNING, logger=ml.logger.name):
        logger.log_exit(
            symbol='MSFT',
            sector='Technology',
            exit_reason='hold_expired',
            entry_price=200.0,
            exit_price=190.0,
            pnl_usd=-1000.0,
            days_held=4,
            high_price=210.0,
            entry_vol_ann=0.18,
            entry_daily_vol=0.012,
            adaptive_stop_pct=-0.07,
            entry_momentum_score=0.67,
            entry_momentum_rank=0.8,
            regime_score=0.55,
            max_positions_target=5,
            current_n_positions=4,
            portfolio_value=99000.0,
            portfolio_drawdown=-0.03,
            current_leverage=1.0,
            crash_cooldown=0,
            trading_day=11,
            spy_return_during_hold=-0.01,
        )

    outcome_records = read_jsonl(Path(ml.OUTCOMES_FILE))

    assert 'no matching open entry' in caplog.text
    assert len(outcome_records) == 1
    assert outcome_records[0]['entry_decision_id'] == 'unknown'
    assert outcome_records[0]['entry_regime_score'] == 0.55
    assert outcome_records[0]['entry_spy_vs_sma200'] == 0.0
    assert outcome_records[0]['gross_return'] == pytest.approx(-0.05)
    assert outcome_records[0]['outcome_label'] == 'weak_loss'


def test_compass_ml_orchestrator_runs_full_lifecycle(orchestrator):
    entry_id = orchestrator.on_entry(
        symbol='AAPL',
        sector='Technology',
        momentum_score=0.92,
        momentum_rank=0.97,
        entry_vol_ann=0.21,
        entry_daily_vol=0.013,
        adaptive_stop_pct=-0.08,
        trailing_stop_pct=0.03,
        regime_score=0.69,
        max_positions_target=5,
        current_n_positions=2,
        portfolio_value=100000.0,
        portfolio_drawdown=-0.01,
        current_leverage=0.95,
        crash_cooldown=0,
        trading_day=1,
    )

    orchestrator.on_hold(
        symbol='AAPL',
        sector='Technology',
        days_held=1,
        current_return=0.01,
        drawdown_from_high=-0.005,
        entry_daily_vol=0.013,
        adaptive_stop_pct=-0.08,
        regime_score=0.69,
        trading_day=2,
        portfolio_value=101000.0,
        portfolio_drawdown=-0.009,
        spy_price=502.0,
        spy_sma200=500.0,
        spy_regime_score=0.66,
    )
    orchestrator.on_hold(
        symbol='AAPL',
        sector='Technology',
        days_held=2,
        current_return=0.025,
        drawdown_from_high=-0.007,
        entry_daily_vol=0.013,
        adaptive_stop_pct=-0.08,
        regime_score=0.69,
        trading_day=3,
        portfolio_value=102500.0,
        portfolio_drawdown=-0.008,
        spy_price=503.0,
        spy_sma200=500.0,
        spy_regime_score=0.67,
    )
    orchestrator.on_hold(
        symbol='AAPL',
        sector='Technology',
        days_held=3,
        current_return=0.04,
        drawdown_from_high=-0.01,
        entry_daily_vol=0.013,
        adaptive_stop_pct=-0.08,
        regime_score=0.69,
        trading_day=4,
        portfolio_value=104000.0,
        portfolio_drawdown=-0.006,
        spy_price=504.0,
        spy_sma200=500.0,
        spy_regime_score=0.68,
    )
    orchestrator.on_exit(
        symbol='AAPL',
        sector='Technology',
        exit_reason='hold_expired',
        entry_price=100.0,
        exit_price=105.0,
        pnl_usd=500.0,
        days_held=4,
        high_price=106.0,
        entry_vol_ann=0.21,
        entry_daily_vol=0.013,
        adaptive_stop_pct=-0.08,
        entry_momentum_score=0.92,
        entry_momentum_rank=0.97,
        regime_score=0.69,
        max_positions_target=5,
        current_n_positions=1,
        portfolio_value=105000.0,
        portfolio_drawdown=-0.005,
        current_leverage=0.9,
        crash_cooldown=0,
        trading_day=5,
        spy_return_during_hold=0.02,
    )
    orchestrator.on_skip(
        symbol='MSFT',
        sector='Technology',
        skip_reason='sector_limit',
        universe_rank=6,
        momentum_score=0.74,
        regime_score=0.69,
        trading_day=5,
        portfolio_value=105000.0,
        portfolio_drawdown=-0.005,
        current_n_positions=1,
        max_positions_target=5,
        spy_price=505.0,
        spy_sma200=500.0,
        spy_regime_score=0.68,
    )
    orchestrator.on_end_of_day(
        trading_day=5,
        portfolio_value=105000.0,
        cash=105000.0,
        peak_value=105000.0,
        n_positions=0,
        leverage=0.0,
        crash_cooldown=0,
        regime_score=0.69,
        max_positions_target=5,
        positions=[],
        position_meta={},
        prev_portfolio_value=100000.0,
    )

    report = orchestrator.run_learning()
    decision_records = read_jsonl(Path(ml.DECISIONS_FILE))
    outcome_records = read_jsonl(Path(ml.OUTCOMES_FILE))
    snapshot_records = read_jsonl(Path(ml.SNAPSHOTS_FILE))
    saved_insights = json.loads(Path(ml.INSIGHTS_FILE).read_text(encoding='utf-8'))

    assert entry_id
    assert len(decision_records) == 6
    assert [record['decision_type'] for record in decision_records] == [
        'entry', 'hold', 'hold', 'hold', 'exit', 'skip',
    ]
    assert len(outcome_records) == 1
    assert len(snapshot_records) == 1
    assert outcome_records[0]['entry_decision_id'] == entry_id
    assert outcome_records[0]['gross_return'] == pytest.approx(0.05)
    assert outcome_records[0]['alpha_vs_spy'] == pytest.approx(0.03)
    assert snapshot_records[0]['portfolio_value'] == 105000.0
    assert snapshot_records[0]['daily_pnl_pct'] == pytest.approx(0.05)
    assert report['learning_phase'] == 1
    assert report['trading_days'] == 5
    assert report['data_summary']['total_decisions'] == 6
    assert report['data_summary']['completed_trades'] == 1
    assert report['data_summary']['daily_snapshots'] == 1
    assert report['data_summary']['decisions_by_type'] == {
        'hold': 3, 'entry': 1, 'exit': 1, 'skip': 1,
    }
    assert report['trade_analytics']['n_completed_trades'] == 1
    assert report['trade_analytics']['overall']['n'] == 1
    assert report['trade_analytics']['overall']['mean_return'] == pytest.approx(0.05)
    assert report['stop_analysis']['status'] == 'insufficient_data'
    assert saved_insights['data_summary']['total_decisions'] == 6
    assert saved_insights['learning_phase'] == 1


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


def test_log_skip_sanitizes_nan_momentum_score(logger):
    logger.log_skip(
        symbol='AMD',
        sector='Technology',
        skip_reason='nan_momentum',
        universe_rank=11,
        momentum_score=float('nan'),
        regime_score=0.55,
        trading_day=15,
        portfolio_value=102500.0,
        portfolio_drawdown=-0.03,
        current_n_positions=4,
        max_positions_target=5,
    )

    records = read_jsonl(Path(ml.DECISIONS_FILE))

    assert len(records) == 1
    assert records[0]['decision_type'] == 'skip'
    assert records[0]['momentum_score'] is None


def test_log_regime_change_records_transition_event(logger):
    logger.log_regime_change(
        old_score=0.32,
        new_score=0.67,
        old_regime='bear',
        new_regime='bull',
        trading_day=16,
        portfolio_value=104000.0,
    )

    records = read_jsonl(Path(ml.DECISIONS_FILE))

    assert len(records) == 1
    assert records[0]['decision_type'] == 'regime_change'
    assert records[0]['symbol'] == ''
    assert records[0]['sector'] == ''
    assert records[0]['regime_score'] == pytest.approx(0.67)
    assert records[0]['regime_bucket'] == 'bull'
    assert records[0]['portfolio_value'] == 104000.0
    assert records[0]['skip_reason'] is None
    assert records[0]['current_return'] is None


def test_log_daily_snapshot_records_portfolio_state(logger):
    position_meta = {
        'AAPL': {'sector': 'Technology', 'entry_daily_vol': 0.02, 'entry_day_index': 15},
        'MSFT': {'sector': 'Technology', 'entry_daily_vol': 0.01, 'entry_day_index': 14},
        'NVDA': {'sector': 'Semiconductors', 'entry_daily_vol': 0.03, 'entry_day_index': 16},
    }
    logger.log_daily_snapshot(
        trading_day=17,
        portfolio_value=105500.0,
        cash=12500.0,
        peak_value=108000.0,
        n_positions=3,
        leverage=0.9,
        positions=['AAPL', 'MSFT', 'NVDA'],
        position_meta=position_meta,
        regime_score=0.63,
        crash_cooldown=1,
        max_positions_target=5,
        prev_portfolio_value=104250.0,
    )

    snapshots = read_jsonl(Path(ml.SNAPSHOTS_FILE))

    assert len(snapshots) == 1
    assert snapshots[0]['trading_day'] == 17
    assert snapshots[0]['portfolio_value'] == 105500.0
    assert snapshots[0]['cash'] == 12500.0
    assert snapshots[0]['positions'] == ['AAPL', 'MSFT', 'NVDA']
    assert snapshots[0]['n_positions'] == 3
    assert snapshots[0]['leverage'] == 0.9
    assert snapshots[0]['drawdown'] == pytest.approx((105500.0 - 108000.0) / 108000.0)
    assert snapshots[0]['regime_score'] == 0.63
    assert set(snapshots[0]['sectors_held']) == {'Technology', 'Semiconductors'}
    assert snapshots[0]['avg_entry_vol'] == pytest.approx(0.02)
    assert snapshots[0]['avg_days_held'] == pytest.approx(3.0)
    assert snapshots[0]['daily_pnl_pct'] == pytest.approx((105500.0 / 104250.0) - 1.0)


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


def test_feature_store_load_decisions_reads_all_rows_and_filters_by_type(isolate_ml_paths):
    decision_rows = [
        {'decision_id': 'd1', 'decision_type': 'entry', 'symbol': 'AAPL', 'trading_day': 1},
        {'decision_id': 'd2', 'decision_type': 'skip', 'symbol': 'MSFT', 'trading_day': 1},
        {'decision_id': 'd3', 'decision_type': 'entry', 'symbol': 'NVDA', 'trading_day': 2},
        {'decision_id': 'd4', 'decision_type': 'hold', 'symbol': 'AMD', 'trading_day': 2},
        {'decision_id': 'd5', 'decision_type': 'entry', 'symbol': 'LLY', 'trading_day': 3},
    ]
    write_jsonl_lines(Path(ml.DECISIONS_FILE), decision_rows)

    feature_store = ml.FeatureStore(str(isolate_ml_paths))
    decisions = feature_store.load_decisions()
    entries = feature_store.load_decisions('entry')

    assert len(decisions) == 5
    assert list(entries['decision_id']) == ['d1', 'd3', 'd5']
    assert set(entries['decision_type']) == {'entry'}
    assert {'decision_id', 'decision_type', 'symbol', 'trading_day'}.issubset(decisions.columns)


def test_feature_store_load_outcomes_reads_rows_and_preserves_labels(isolate_ml_paths):
    outcome_rows = [
        {'outcome_id': 'o1', 'entry_decision_id': 'd1', 'outcome_label': 'strong_win', 'beat_spy': True},
        {'outcome_id': 'o2', 'entry_decision_id': 'd2', 'outcome_label': 'weak_win', 'beat_spy': True},
        {'outcome_id': 'o3', 'entry_decision_id': 'd3', 'outcome_label': 'flat', 'beat_spy': False},
        {'outcome_id': 'o4', 'entry_decision_id': 'd4', 'outcome_label': 'weak_loss', 'beat_spy': False},
        {'outcome_id': 'o5', 'entry_decision_id': 'd5', 'outcome_label': 'stop_loss', 'beat_spy': False},
    ]
    write_jsonl_lines(Path(ml.OUTCOMES_FILE), outcome_rows)

    feature_store = ml.FeatureStore(str(isolate_ml_paths))
    outcomes = feature_store.load_outcomes()

    assert len(outcomes) == 5
    assert list(outcomes['outcome_id']) == ['o1', 'o2', 'o3', 'o4', 'o5']
    assert set(outcomes['outcome_label']) == {
        'strong_win', 'weak_win', 'flat', 'weak_loss', 'stop_loss'
    }
    assert int(outcomes['beat_spy'].sum()) == 2


def test_feature_store_skips_corrupted_jsonl_lines(isolate_ml_paths):
    write_jsonl_lines(
        Path(ml.DECISIONS_FILE),
        [
            {'decision_id': 'd1', 'decision_type': 'entry', 'symbol': 'AAPL'},
            '{"decision_id": "broken"',
            {'decision_id': 'd2', 'decision_type': 'entry', 'symbol': 'MSFT'},
        ],
    )
    write_jsonl_lines(
        Path(ml.OUTCOMES_FILE),
        [
            {'outcome_id': 'o1', 'entry_decision_id': 'd1', 'gross_return': 0.04},
            '{"outcome_id": "broken"',
            {'outcome_id': 'o2', 'entry_decision_id': 'd2', 'gross_return': -0.01},
        ],
    )

    feature_store = ml.FeatureStore(str(isolate_ml_paths))
    decisions = feature_store.load_decisions('entry')
    outcomes = feature_store.load_outcomes()

    assert len(decisions) == 2
    assert list(decisions['decision_id']) == ['d1', 'd2']
    assert len(outcomes) == 2
    assert list(outcomes['outcome_id']) == ['o1', 'o2']


def test_feature_store_returns_empty_dataframes_for_empty_files(isolate_ml_paths):
    Path(ml.DECISIONS_FILE).write_text('', encoding='utf-8')
    Path(ml.OUTCOMES_FILE).write_text('', encoding='utf-8')

    feature_store = ml.FeatureStore(str(isolate_ml_paths))

    assert feature_store.load_decisions().empty
    assert feature_store.load_outcomes().empty
    assert feature_store.build_entry_feature_matrix().empty


def test_build_entry_feature_matrix_merges_manual_jsonl_records(isolate_ml_paths):
    sectors = ['Technology', 'Healthcare', 'Energy', 'Utilities', 'Telecom']
    regime_buckets = ['bull', 'mild_bull', 'mild_bear', 'bear', 'bull']
    decision_rows = []
    outcome_rows = []

    for idx in range(5):
        decision_rows.append({
            'decision_id': f'entry-{idx}',
            'decision_type': 'entry',
            'spy_10d_vol': 0.01 + (idx * 0.001),
            'spy_vs_sma200_pct': 0.02 - (idx * 0.005),
            'spy_20d_return': 0.03 - (idx * 0.004),
            'portfolio_drawdown': -0.01 * idx,
            'current_leverage': 1.0 - (idx * 0.1),
            'crash_cooldown': idx % 2,
        })
        outcome_rows.append({
            'outcome_id': f'outcome-{idx}',
            'entry_decision_id': f'entry-{idx}',
            'symbol': f'SYM{idx}',
            'sector': sectors[idx],
            'gross_return': 0.05 - (idx * 0.02),
            'outcome_label': 'strong_win' if idx == 0 else 'weak_loss',
            'beat_spy': idx < 2,
            'exit_reason': 'hold_expired' if idx % 2 == 0 else 'position_stop',
            'trading_days_held': 5 + idx,
            'entry_date': f'2026-03-0{idx + 1}',
            'exit_date': f'2026-03-1{idx + 1}',
            'entry_momentum_score': 0.5 + (idx * 0.1),
            'entry_momentum_rank': 0.9 - (idx * 0.1),
            'entry_daily_vol': 0.01 + (idx * 0.01),
            'entry_vol_ann': 0.2 + (idx * 0.02),
            'entry_adaptive_stop': -0.06 - (idx * 0.01),
            'entry_regime_score': 0.7 - (idx * 0.1),
            'entry_spy_vs_sma200': 0.015 - (idx * 0.01),
            'entry_regime_bucket': regime_buckets[idx],
            'entry_portfolio_drawdown': -0.01 * idx,
        })

    write_jsonl_lines(Path(ml.DECISIONS_FILE), decision_rows)
    write_jsonl_lines(Path(ml.OUTCOMES_FILE), outcome_rows)

    feature_store = ml.FeatureStore(str(isolate_ml_paths))
    matrix = feature_store.build_entry_feature_matrix()

    assert len(matrix) == 5
    assert {
        'feat_momentum_score',
        'feat_spy_10d_vol',
        'feat_leverage',
        'feat_sector_technology',
        'target_return',
        'target_label',
    }.issubset(matrix.columns)
    assert matrix.iloc[0]['symbol'] == 'SYM0'
    assert matrix.iloc[0]['feat_spy_10d_vol'] == pytest.approx(0.01)
    assert matrix.iloc[0]['feat_leverage'] == pytest.approx(1.0)
    assert matrix.iloc[0]['feat_sector_technology'] == 1
    assert matrix.iloc[1]['feat_sector_healthcare'] == 1
    assert matrix.iloc[0]['target_return'] == pytest.approx(0.05)
    assert matrix.iloc[0]['target_label'] == 'strong_win'


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


@pytest.mark.parametrize(
    'gross_return,exit_reason,expected',
    [
        (0.0, 'hold_expired', 'flat'),
        (float('nan'), 'hold_expired', 'unknown'),
        (float('inf'), 'hold_expired', 'unknown'),
        (float('-inf'), 'hold_expired', 'unknown'),
        (0.05, None, 'strong_win'),
        (0.05, '', 'strong_win'),
        (-0.02, None, 'weak_loss'),
        (-0.02, '', 'weak_loss'),
        (None, 'hold_expired', 'unknown'),
    ],
)
def test_classify_outcome_edge_cases(gross_return, exit_reason, expected):
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


def test_append_jsonl_thread_safety(logger, tmp_path):
    import threading

    target_file = tmp_path / "thread_test.jsonl"
    threads = []
    for i in range(10):
        record = {"thread_id": i, "value": f"record_{i}"}
        t = threading.Thread(target=logger._append_jsonl, args=(target_file, record))
        threads.append(t)

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = target_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 10
    parsed = [json.loads(line) for line in lines]
    thread_ids = sorted(r["thread_id"] for r in parsed)
    assert thread_ids == list(range(10))
