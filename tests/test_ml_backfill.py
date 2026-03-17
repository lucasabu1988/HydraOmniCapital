import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import compass_ml_learning as ml


def write_state(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')


def test_backfill_from_state_files_reconstructs_entries_exits_and_snapshots(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state_dir = tmp_path / 'state'
    write_state(
        state_dir / 'compass_state_20260310.json',
        {
            'trading_day_counter': 1,
            'current_regime_score': 0.60,
            'portfolio_value': 100000.0,
            'peak_value': 100000.0,
            'cash': 100000.0,
            'positions': {},
            'position_meta': {},
            'crash_cooldown': 0,
        },
    )
    write_state(
        state_dir / 'compass_state_20260311.json',
        {
            'trading_day_counter': 2,
            'current_regime_score': 0.62,
            'portfolio_value': 101000.0,
            'peak_value': 101000.0,
            'cash': 80000.0,
            'positions': {'AAPL': {'shares': 10}},
            'position_meta': {
                'AAPL': {'sector': 'Technology', 'entry_vol': 0.22, 'entry_daily_vol': 0.015}
            },
            'crash_cooldown': 0,
        },
    )
    write_state(
        state_dir / 'compass_state_20260312.json',
        {
            'trading_day_counter': 3,
            'current_regime_score': 0.65,
            'portfolio_value': 102000.0,
            'peak_value': 102000.0,
            'cash': 60000.0,
            'positions': {'AAPL': {'shares': 10}, 'MSFT': {'shares': 8}},
            'position_meta': {
                'AAPL': {'sector': 'Technology', 'entry_vol': 0.22, 'entry_daily_vol': 0.015},
                'MSFT': {'sector': 'Technology', 'entry_vol': 0.24, 'entry_daily_vol': 0.016},
            },
            'crash_cooldown': 1,
        },
    )
    write_state(
        state_dir / 'compass_state_latest.json',
        {
            'stop_events': [
                {'symbol': 'GS', 'entry_price': 100.0, 'exit_price': 94.0, 'pnl': -600.0}
            ]
        },
    )

    result = ml.backfill_from_state_files(str(state_dir))

    decisions_path = tmp_path / 'state' / 'ml_learning' / 'decisions.jsonl'
    outcomes_path = tmp_path / 'state' / 'ml_learning' / 'outcomes.jsonl'
    snapshots_path = tmp_path / 'state' / 'ml_learning' / 'daily_snapshots.jsonl'

    assert result['state_files_processed'] == 3
    assert result['entry_decisions'] == 2
    assert result['exit_outcomes'] == 1
    assert result['daily_snapshots'] == 3
    assert 'momentum_score and momentum_rank' in result['notes'][0]
    assert len(decisions_path.read_text(encoding='utf-8').splitlines()) == 3
    assert len(outcomes_path.read_text(encoding='utf-8').splitlines()) == 1
    assert len(snapshots_path.read_text(encoding='utf-8').splitlines()) == 3


def test_backfill_from_state_files_skips_corrupted_historical_json(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state_dir = tmp_path / 'state'
    write_state(
        state_dir / 'compass_state_20260310.json',
        {
            'trading_day_counter': 1,
            'portfolio_value': 100000.0,
            'peak_value': 100000.0,
            'cash': 100000.0,
            'positions': {},
            'position_meta': {},
        },
    )
    write_state(
        state_dir / 'compass_state_20260311.json',
        {
            'trading_day_counter': 2,
            'portfolio_value': 101000.0,
            'peak_value': 101000.0,
            'cash': 90000.0,
            'positions': {'AAPL': {'shares': 10}},
            'position_meta': {'AAPL': {'sector': 'Technology', 'entry_daily_vol': 0.015}},
        },
    )
    (state_dir / 'compass_state_20260312.json').write_text('{bad json', encoding='utf-8')
    write_state(state_dir / 'compass_state_latest.json', {'stop_events': []})

    result = ml.backfill_from_state_files(str(state_dir))

    assert result['state_files_processed'] == 3
    assert result['entry_decisions'] == 1
    assert result['exit_outcomes'] == 0
    assert result['daily_snapshots'] == 2


def test_backfill_from_state_files_returns_zero_counts_for_empty_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state_dir = tmp_path / 'state'
    state_dir.mkdir(parents=True, exist_ok=True)

    result = ml.backfill_from_state_files(str(state_dir))

    assert result['state_files_processed'] == 0
    assert result['entry_decisions'] == 0
    assert result['exit_outcomes'] == 0
    assert result['daily_snapshots'] == 0
    assert result['notes']


def test_backfill_from_state_files_handles_missing_positions_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state_dir = tmp_path / 'state'
    write_state(
        state_dir / 'compass_state_20260310.json',
        {
            'trading_day_counter': 1,
            'portfolio_value': 100000.0,
            'peak_value': 100000.0,
            'cash': 100000.0,
            'position_meta': {},
        },
    )
    write_state(state_dir / 'compass_state_latest.json', {'stop_events': []})

    result = ml.backfill_from_state_files(str(state_dir))

    assert result['state_files_processed'] == 1
    assert result['entry_decisions'] == 0
    assert result['exit_outcomes'] == 0
    assert result['daily_snapshots'] == 1
