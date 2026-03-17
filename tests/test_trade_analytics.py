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


def make_populated_analytics(tmp_path):
    trades_path = tmp_path / 'backtests' / 'trades.csv'
    daily_path = tmp_path / 'backtests' / 'daily.csv'
    write_trades_csv(
        trades_path,
        [
            {
                'symbol': 'AAPL',
                'entry_date': '2025-01-06',
                'exit_date': '2025-01-10',
                'return': 0.05,
                'pnl': 500.0,
                'exit_reason': 'hold_expired',
            },
            {
                'symbol': 'MSFT',
                'entry_date': '2025-01-07',
                'exit_date': '2025-01-13',
                'return': -0.03,
                'pnl': -300.0,
                'exit_reason': 'position_stop',
            },
            {
                'symbol': 'JNJ',
                'entry_date': '2025-02-03',
                'exit_date': '2025-02-10',
                'return': 0.02,
                'pnl': 200.0,
                'exit_reason': 'hold_expired',
            },
            {
                'symbol': 'XOM',
                'entry_date': '2025-02-04',
                'exit_date': '2025-02-11',
                'return': 0.04,
                'pnl': 400.0,
                'exit_reason': 'momentum_exit',
            },
            {
                'symbol': 'JPM',
                'entry_date': '2026-03-02',
                'exit_date': '2026-03-09',
                'return': -0.01,
                'pnl': -100.0,
                'exit_reason': 'position_stop',
            },
            {
                'symbol': 'NVDA',
                'entry_date': '2026-03-03',
                'exit_date': '2026-03-10',
                'return': 0.06,
                'pnl': 600.0,
                'exit_reason': 'momentum_exit',
            },
            {
                'symbol': 'UNH',
                'entry_date': '2026-04-01',
                'exit_date': '2026-04-08',
                'return': 0.03,
                'pnl': 300.0,
                'exit_reason': 'max_hold',
            },
            {
                'symbol': 'KO',
                'entry_date': '2026-04-02',
                'exit_date': '2026-04-09',
                'return': -0.02,
                'pnl': -200.0,
                'exit_reason': 'position_stop',
            },
            {
                'symbol': 'NEE',
                'entry_date': '2026-04-03',
                'exit_date': '2026-04-10',
                'return': 0.01,
                'pnl': 100.0,
                'exit_reason': 'hold_expired',
            },
            {
                'symbol': 'VZ',
                'entry_date': '2026-04-06',
                'exit_date': '2026-04-13',
                'return': -0.04,
                'pnl': -400.0,
                'exit_reason': 'hold_expired',
            },
        ],
    )
    write_daily_csv(
        daily_path,
        [
            {'date': '2025-01-06', 'risk_on': True, 'leverage': 1.0, 'in_protection': False},
            {'date': '2025-01-07', 'risk_on': True, 'leverage': 0.9, 'in_protection': False},
            {'date': '2025-02-03', 'risk_on': False, 'leverage': 0.6, 'in_protection': True},
            {'date': '2025-02-04', 'risk_on': False, 'leverage': 0.5, 'in_protection': True},
            {'date': '2026-03-02', 'risk_on': True, 'leverage': 1.0, 'in_protection': False},
            {'date': '2026-03-03', 'risk_on': True, 'leverage': 0.8, 'in_protection': False},
            {'date': '2026-04-01', 'risk_on': False, 'leverage': 0.65, 'in_protection': True},
            {'date': '2026-04-02', 'risk_on': False, 'leverage': 0.6, 'in_protection': True},
            {'date': '2026-04-03', 'risk_on': True, 'leverage': 0.75, 'in_protection': False},
            {'date': '2026-04-06', 'risk_on': False, 'leverage': 0.5, 'in_protection': True},
        ],
    )

    analytics = COMPASSTradeAnalytics(
        trades_csv=str(trades_path),
        daily_csv=str(daily_path),
    )
    analytics.load_data()
    analytics.enrich_trades()
    return analytics


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


def test_trade_analytics_segments_trades_by_exit_reason_and_computes_stats(tmp_path):
    analytics = make_populated_analytics(tmp_path)

    segments = analytics.segment_by_exit_reason()
    tech_stats = analytics._compute_segment_stats(
        analytics.trades_df[analytics.trades_df['sector'] == 'Technology']
    )

    assert set(segments) == {'hold_expired', 'position_stop', 'momentum_exit', 'max_hold'}
    assert segments['hold_expired']['count'] == 4
    assert segments['hold_expired']['win_rate_pct'] == pytest.approx(75.0)
    assert segments['hold_expired']['avg_return_pct'] == pytest.approx(1.0)
    assert segments['position_stop']['count'] == 3
    assert segments['position_stop']['avg_return_pct'] == pytest.approx(-2.0)
    assert segments['momentum_exit']['count'] == 2
    assert segments['momentum_exit']['best_trade_pct'] == pytest.approx(6.0)
    assert segments['max_hold']['count'] == 1
    assert tech_stats['count'] == 3
    assert tech_stats['win_rate_pct'] == pytest.approx(66.7)
    assert tech_stats['avg_return_pct'] == pytest.approx(2.67)
    assert tech_stats['alpha_contribution_pct'] == pytest.approx(72.7)
    assert tech_stats['sharpe'] > 0


def test_trade_analytics_segments_by_regime_sector_year_dow_and_volatility(tmp_path):
    analytics = make_populated_analytics(tmp_path)

    regime = analytics.segment_by_regime()
    sector = analytics.segment_by_sector()
    year = analytics.segment_by_year()
    dow = analytics.segment_by_dow()
    vol = analytics.segment_by_vol_environment()

    assert regime['Risk-ON']['count'] == 5
    assert regime['Risk-ON']['avg_return_pct'] == pytest.approx(1.6)
    assert regime['Risk-OFF']['count'] == 5
    assert regime['Risk-OFF']['win_rate_pct'] == pytest.approx(60.0)
    assert sector['Technology']['count'] == 3
    assert sector['Healthcare']['count'] == 2
    assert sector['Technology']['best_trade_pct'] == pytest.approx(6.0)
    assert sector['Healthcare']['avg_return_pct'] == pytest.approx(2.5)
    assert set(year) == {'2025', '2026'}
    assert year['2025']['count'] == 4
    assert year['2025']['win_rate_pct'] == pytest.approx(75.0)
    assert year['2026']['count'] == 6
    assert year['2026']['avg_return_pct'] == pytest.approx(0.5)
    assert dow['Monday']['count'] == 4
    assert dow['Monday']['avg_return_pct'] == pytest.approx(0.5)
    assert dow['Tuesday']['count'] == 3
    assert dow['Tuesday']['win_rate_pct'] == pytest.approx(66.7)
    assert vol['Low Vol']['count'] == 5
    assert vol['Low Vol']['avg_return_pct'] == pytest.approx(1.6)
    assert vol['High Vol']['count'] == 5
    assert vol['High Vol']['avg_return_pct'] == pytest.approx(0.6)
