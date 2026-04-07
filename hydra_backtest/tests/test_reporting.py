"""Tests for hydra_backtest.reporting."""
import json
from datetime import datetime

import pandas as pd

from hydra_backtest.engine import BacktestResult
from hydra_backtest.methodology import WaterfallReport, WaterfallTier
from hydra_backtest.reporting import (
    format_summary_table,
    write_daily_csv,
    write_trades_csv,
    write_waterfall_json,
)


def _mock_result():
    dates = pd.date_range('2020-01-01', periods=10)
    daily = pd.DataFrame({
        'date': dates,
        'portfolio_value': [100_000 + i * 100 for i in range(10)],
        'cash': [50_000] * 10,
        'n_positions': [5] * 10,
        'leverage': [0.8] * 10,
        'drawdown': [0.0] * 10,
        'regime_score': [0.7] * 10,
        'crash_active': [False] * 10,
        'max_positions': [5] * 10,
    })
    trades = pd.DataFrame([{
        'symbol': 'AAPL',
        'entry_date': dates[0],
        'exit_date': dates[5],
        'exit_reason': 'hold_expired',
        'entry_price': 100.0,
        'exit_price': 105.0,
        'shares': 10.0,
        'pnl': 50.0,
        'return': 0.05,
        'sector': 'Tech',
    }])
    return BacktestResult(
        config={},
        daily_values=daily,
        trades=trades,
        decisions=[],
        exit_events=[],
        universe_size={2020: 40},
        started_at=datetime.now(),
        finished_at=datetime.now(),
        git_sha='abc',
        data_inputs_hash='def',
    )


def test_write_daily_csv(tmp_path):
    path = tmp_path / 'daily.csv'
    write_daily_csv(_mock_result(), str(path))
    df = pd.read_csv(path)
    assert 'date' in df.columns
    assert 'portfolio_value' in df.columns
    assert len(df) == 10


def test_write_trades_csv(tmp_path):
    path = tmp_path / 'trades.csv'
    write_trades_csv(_mock_result(), str(path))
    df = pd.read_csv(path)
    assert 'symbol' in df.columns
    assert len(df) == 1


def test_write_waterfall_json(tmp_path):
    tier = WaterfallTier(
        name='baseline', description='baseline', cagr=0.12, sharpe=0.85,
        sortino=1.1, calmar=0.4, max_drawdown=-0.30, volatility=0.14,
        final_value=2_000_000,
    )
    report = WaterfallReport(
        tiers=[tier],
        baseline_result=_mock_result(),
        net_honest_result=_mock_result(),
    )
    path = tmp_path / 'waterfall.json'
    write_waterfall_json(report, str(path))
    with open(path) as f:
        data = json.load(f)
    assert 'tiers' in data
    assert data['tiers'][0]['name'] == 'baseline'
    assert 'metadata' in data
    assert 'git_sha' in data['metadata']


def test_format_summary_table():
    tier = WaterfallTier(
        name='baseline', description='live', cagr=0.1234, sharpe=0.85,
        sortino=1.1, calmar=0.4, max_drawdown=-0.30, volatility=0.14,
        final_value=2_000_000,
    )
    report = WaterfallReport(
        tiers=[tier],
        baseline_result=_mock_result(),
        net_honest_result=_mock_result(),
    )
    text = format_summary_table(report)
    assert 'baseline' in text
    assert '12.34' in text  # CAGR as %
