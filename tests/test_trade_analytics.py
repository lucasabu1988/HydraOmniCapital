import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from compass_trade_analytics import COMPASSTradeAnalytics


def write_trades_csv(path, rows):
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(
            columns=['symbol', 'entry_date', 'exit_date', 'return', 'pnl', 'exit_reason']
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def write_daily_csv(path, rows):
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(columns=['date', 'risk_on', 'leverage', 'in_protection'])
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def test_trade_analytics_handles_empty_trade_log(tmp_path):
    trades_path = tmp_path / 'backtests' / 'trades.csv'
    daily_path = tmp_path / 'backtests' / 'daily.csv'
    write_trades_csv(trades_path, [])
    write_daily_csv(
        daily_path,
        [{'date': '2026-01-02', 'risk_on': True, 'leverage': 1.0, 'in_protection': False}],
    )

    summary = COMPASSTradeAnalytics(
        trades_csv=str(trades_path),
        daily_csv=str(daily_path),
    ).run_all()

    assert summary['overall']['total_trades'] == 0
    assert summary['overall']['total_pnl'] == 0.0
    assert summary['overall']['date_range'] is None
    assert all(segment == {} for segment in summary['segments'].values())


def test_trade_analytics_summarizes_single_completed_trade(tmp_path):
    trades_path = tmp_path / 'backtests' / 'trades.csv'
    daily_path = tmp_path / 'backtests' / 'daily.csv'
    write_trades_csv(
        trades_path,
        [{
            'symbol': 'AAPL',
            'entry_date': '2026-01-02',
            'exit_date': '2026-01-07',
            'return': 0.05,
            'pnl': 500.0,
            'exit_reason': 'hold_expired',
        }],
    )
    write_daily_csv(
        daily_path,
        [{'date': '2026-01-02', 'risk_on': True, 'leverage': 1.0, 'in_protection': False}],
    )

    summary = COMPASSTradeAnalytics(
        trades_csv=str(trades_path),
        daily_csv=str(daily_path),
    ).run_all()

    assert summary['overall']['total_trades'] == 1
    assert summary['overall']['win_rate_pct'] == 100.0
    assert summary['overall']['date_range'] == '2026-01-02 to 2026-01-07'
    assert summary['segments']['exit_reason']['hold_expired']['count'] == 1
    assert summary['segments']['exit_reason']['hold_expired']['sharpe'] == 0.0


def test_trade_analytics_all_losing_trades_report_zero_win_rate(tmp_path):
    trades_path = tmp_path / 'backtests' / 'trades.csv'
    daily_path = tmp_path / 'backtests' / 'daily.csv'
    write_trades_csv(
        trades_path,
        [
            {
                'symbol': 'AAPL',
                'entry_date': '2026-01-02',
                'exit_date': '2026-01-07',
                'return': -0.04,
                'pnl': -400.0,
                'exit_reason': 'position_stop',
            },
            {
                'symbol': 'MSFT',
                'entry_date': '2026-01-03',
                'exit_date': '2026-01-08',
                'return': -0.02,
                'pnl': -200.0,
                'exit_reason': 'position_stop',
            },
        ],
    )
    write_daily_csv(
        daily_path,
        [
            {'date': '2026-01-02', 'risk_on': False, 'leverage': 0.6, 'in_protection': True},
            {'date': '2026-01-03', 'risk_on': False, 'leverage': 0.6, 'in_protection': True},
        ],
    )

    summary = COMPASSTradeAnalytics(
        trades_csv=str(trades_path),
        daily_csv=str(daily_path),
    ).run_all()

    assert summary['overall']['total_trades'] == 2
    assert summary['overall']['win_rate_pct'] == 0.0
    assert summary['overall']['avg_return_pct'] < 0
    assert summary['segments']['exit_reason']['position_stop']['worst_trade_pct'] == -4.0
    assert summary['segments']['regime']['Risk-OFF']['count'] == 2
