import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from compass_trade_analytics import COMPASSTradeAnalytics, SECTOR_MAP


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


# ---------------------------------------------------------------------------
# Helper: build analytics from synthetic trades + daily data
# ---------------------------------------------------------------------------

def _build_analytics(tmp_path, trades, daily=None):
    trades_path = tmp_path / 'backtests' / 'trades.csv'
    daily_path = tmp_path / 'backtests' / 'daily.csv'
    write_trades_csv(trades_path, trades)
    if daily is None:
        # Generate one daily row per unique entry_date
        dates = sorted(set(t['entry_date'] for t in trades))
        daily = [
            {'date': d, 'risk_on': True, 'leverage': 1.0, 'in_protection': False}
            for d in dates
        ]
    write_daily_csv(daily_path, daily)
    analytics = COMPASSTradeAnalytics(
        trades_csv=str(trades_path),
        daily_csv=str(daily_path),
    )
    analytics.load_data()
    analytics.enrich_trades()
    return analytics


# ---------------------------------------------------------------------------
# 1. Equity curve computation from trade log
# ---------------------------------------------------------------------------

def test_equity_curve_from_cumulative_pnl(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'MSFT', 'entry_date': '2025-01-13', 'exit_date': '2025-01-17',
         'return': -0.03, 'pnl': -300.0, 'exit_reason': 'position_stop'},
        {'symbol': 'GOOGL', 'entry_date': '2025-01-20', 'exit_date': '2025-01-24',
         'return': 0.04, 'pnl': 400.0, 'exit_reason': 'hold_expired'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    df = analytics.trades_df.sort_values('exit_date')
    equity = df['pnl'].cumsum().tolist()
    assert equity == [500.0, 200.0, 600.0]


def test_equity_curve_monotonic_for_all_winners(tmp_path):
    base = pd.Timestamp('2025-01-06')
    trades = [
        {'symbol': 'AAPL', 'entry_date': (base + pd.Timedelta(days=i*7)).strftime('%Y-%m-%d'),
         'exit_date': (base + pd.Timedelta(days=i*7+4)).strftime('%Y-%m-%d'),
         'return': 0.02, 'pnl': 200.0, 'exit_reason': 'hold_expired'}
        for i in range(5)
    ]
    analytics = _build_analytics(tmp_path, trades)
    df = analytics.trades_df.sort_values('exit_date')
    equity = df['pnl'].cumsum().tolist()
    assert all(equity[i] <= equity[i+1] for i in range(len(equity)-1))


# ---------------------------------------------------------------------------
# 2. Profit factor calculation (gross wins / gross losses)
# ---------------------------------------------------------------------------

def test_profit_factor_mixed_trades(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 1000.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'MSFT', 'entry_date': '2025-01-07', 'exit_date': '2025-01-11',
         'return': 0.03, 'pnl': 600.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'GOOGL', 'entry_date': '2025-01-08', 'exit_date': '2025-01-12',
         'return': -0.04, 'pnl': -400.0, 'exit_reason': 'position_stop'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    df = analytics.trades_df
    gross_wins = df.loc[df['pnl'] > 0, 'pnl'].sum()
    gross_losses = abs(df.loc[df['pnl'] < 0, 'pnl'].sum())
    profit_factor = gross_wins / gross_losses
    assert profit_factor == pytest.approx(4.0)


def test_profit_factor_equal_wins_and_losses(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'MSFT', 'entry_date': '2025-01-07', 'exit_date': '2025-01-11',
         'return': -0.05, 'pnl': -500.0, 'exit_reason': 'position_stop'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    df = analytics.trades_df
    gross_wins = df.loc[df['pnl'] > 0, 'pnl'].sum()
    gross_losses = abs(df.loc[df['pnl'] < 0, 'pnl'].sum())
    assert gross_wins / gross_losses == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 3. Max consecutive wins/losses
# ---------------------------------------------------------------------------

def test_max_consecutive_wins(tmp_path):
    # W W W L W W
    returns = [0.02, 0.03, 0.01, -0.02, 0.04, 0.01]
    base = pd.Timestamp('2025-01-06')
    trades = [
        {'symbol': 'AAPL', 'entry_date': (base + pd.Timedelta(days=i*7)).strftime('%Y-%m-%d'),
         'exit_date': (base + pd.Timedelta(days=i*7+4)).strftime('%Y-%m-%d'),
         'return': r, 'pnl': r * 10000, 'exit_reason': 'hold_expired'}
        for i, r in enumerate(returns)
    ]
    analytics = _build_analytics(tmp_path, trades)
    df = analytics.trades_df.sort_values('exit_date')
    wins = df['win'].tolist()
    max_consec = 0
    current = 0
    for w in wins:
        if w:
            current += 1
            max_consec = max(max_consec, current)
        else:
            current = 0
    assert max_consec == 3


def test_max_consecutive_losses(tmp_path):
    # L L L W L
    returns = [-0.02, -0.03, -0.01, 0.02, -0.04]
    base = pd.Timestamp('2025-02-03')
    trades = [
        {'symbol': 'MSFT', 'entry_date': (base + pd.Timedelta(days=i*7)).strftime('%Y-%m-%d'),
         'exit_date': (base + pd.Timedelta(days=i*7+4)).strftime('%Y-%m-%d'),
         'return': r, 'pnl': r * 10000, 'exit_reason': 'position_stop'}
        for i, r in enumerate(returns)
    ]
    analytics = _build_analytics(tmp_path, trades)
    df = analytics.trades_df.sort_values('exit_date')
    losses = (~df['win']).tolist()
    max_consec = 0
    current = 0
    for l in losses:
        if l:
            current += 1
            max_consec = max(max_consec, current)
        else:
            current = 0
    assert max_consec == 3


# ---------------------------------------------------------------------------
# 4. Sharpe ratio computation
# ---------------------------------------------------------------------------

def test_sharpe_positive_for_winning_strategy(tmp_path):
    base = pd.Timestamp('2025-01-06')
    trades = [
        {'symbol': 'AAPL', 'entry_date': (base + pd.Timedelta(days=i*7)).strftime('%Y-%m-%d'),
         'exit_date': (base + pd.Timedelta(days=i*7+4)).strftime('%Y-%m-%d'),
         'return': 0.03 + i * 0.005, 'pnl': 300 + i * 50,
         'exit_reason': 'hold_expired'}
        for i in range(4)
    ]
    analytics = _build_analytics(tmp_path, trades)
    stats = analytics._compute_segment_stats(analytics.trades_df)
    assert stats['sharpe'] > 0


def test_sharpe_zero_for_single_trade(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    stats = analytics._compute_segment_stats(analytics.trades_df)
    assert stats['sharpe'] == 0.0


def test_sharpe_zero_for_constant_returns(tmp_path):
    base = pd.Timestamp('2025-01-06')
    trades = [
        {'symbol': 'AAPL', 'entry_date': (base + pd.Timedelta(days=i*7)).strftime('%Y-%m-%d'),
         'exit_date': (base + pd.Timedelta(days=i*7+4)).strftime('%Y-%m-%d'),
         'return': 0.03, 'pnl': 300.0, 'exit_reason': 'hold_expired'}
        for i in range(3)
    ]
    analytics = _build_analytics(tmp_path, trades)
    stats = analytics._compute_segment_stats(analytics.trades_df)
    assert stats['sharpe'] == 0.0


def test_sharpe_negative_for_losing_strategy(tmp_path):
    base = pd.Timestamp('2025-01-06')
    trades = [
        {'symbol': 'AAPL', 'entry_date': (base + pd.Timedelta(days=i*7)).strftime('%Y-%m-%d'),
         'exit_date': (base + pd.Timedelta(days=i*7+4)).strftime('%Y-%m-%d'),
         'return': -0.03 - i * 0.005, 'pnl': -300 - i * 50,
         'exit_reason': 'position_stop'}
        for i in range(4)
    ]
    analytics = _build_analytics(tmp_path, trades)
    stats = analytics._compute_segment_stats(analytics.trades_df)
    assert stats['sharpe'] < 0


# ---------------------------------------------------------------------------
# 5. Sector breakdown with missing sectors
# ---------------------------------------------------------------------------

def test_sector_unknown_for_unmapped_symbols(tmp_path):
    trades = [
        {'symbol': 'ZZZZ', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'YYYY', 'entry_date': '2025-01-07', 'exit_date': '2025-01-11',
         'return': -0.02, 'pnl': -200.0, 'exit_reason': 'position_stop'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    sector = analytics.segment_by_sector()
    assert 'Other' in sector
    assert sector['Other']['count'] == 2


def test_sector_mix_of_known_and_unknown(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'UNKNOWN_TICKER', 'entry_date': '2025-01-07', 'exit_date': '2025-01-11',
         'return': 0.02, 'pnl': 200.0, 'exit_reason': 'hold_expired'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    sector = analytics.segment_by_sector()
    assert 'Technology' in sector
    assert 'Other' in sector
    assert sector['Technology']['count'] == 1
    assert sector['Other']['count'] == 1


def test_sector_no_missing_sectors_all_mapped(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'JPM', 'entry_date': '2025-01-07', 'exit_date': '2025-01-11',
         'return': 0.03, 'pnl': 300.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'XOM', 'entry_date': '2025-01-08', 'exit_date': '2025-01-12',
         'return': 0.02, 'pnl': 200.0, 'exit_reason': 'hold_expired'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    sector = analytics.segment_by_sector()
    assert 'Other' not in sector
    assert set(sector.keys()) == {'Technology', 'Financials', 'Energy'}


# ---------------------------------------------------------------------------
# 6. Mixed win/loss trades comprehensive
# ---------------------------------------------------------------------------

def test_mixed_trades_overall_stats(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.08, 'pnl': 800.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'MSFT', 'entry_date': '2025-01-07', 'exit_date': '2025-01-11',
         'return': -0.03, 'pnl': -300.0, 'exit_reason': 'position_stop'},
        {'symbol': 'GOOGL', 'entry_date': '2025-01-08', 'exit_date': '2025-01-14',
         'return': 0.02, 'pnl': 200.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'AMZN', 'entry_date': '2025-01-09', 'exit_date': '2025-01-15',
         'return': -0.05, 'pnl': -500.0, 'exit_reason': 'position_stop'},
        {'symbol': 'META', 'entry_date': '2025-01-10', 'exit_date': '2025-01-16',
         'return': 0.06, 'pnl': 600.0, 'exit_reason': 'momentum_exit'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    overall = analytics.get_overall_stats()
    assert overall['total_trades'] == 5
    assert overall['win_rate_pct'] == pytest.approx(60.0)
    assert overall['total_pnl'] == pytest.approx(800.0)
    assert overall['unique_symbols'] == 5
    avg_ret = (0.08 - 0.03 + 0.02 - 0.05 + 0.06) / 5 * 100
    assert overall['avg_return_pct'] == pytest.approx(avg_ret)


def test_mixed_trades_segment_stats_keys(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'MSFT', 'entry_date': '2025-01-07', 'exit_date': '2025-01-11',
         'return': -0.02, 'pnl': -200.0, 'exit_reason': 'position_stop'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    stats = analytics._compute_segment_stats(analytics.trades_df)
    expected_keys = {
        'count', 'total_pnl', 'avg_pnl', 'avg_return_pct', 'win_rate_pct',
        'avg_holding_days', 'alpha_contribution_pct', 'best_trade_pct',
        'worst_trade_pct', 'sharpe',
    }
    assert set(stats.keys()) == expected_keys


# ---------------------------------------------------------------------------
# 7. Single trade edge case
# ---------------------------------------------------------------------------

def test_single_losing_trade(tmp_path):
    trades = [
        {'symbol': 'MSFT', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': -0.04, 'pnl': -400.0, 'exit_reason': 'position_stop'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    overall = analytics.get_overall_stats()
    assert overall['total_trades'] == 1
    assert overall['win_rate_pct'] == 0.0
    assert overall['total_pnl'] == -400.0


def test_single_trade_alpha_contribution_is_100(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    stats = analytics._compute_segment_stats(analytics.trades_df)
    assert stats['alpha_contribution_pct'] == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# 8. Large trade log (100+ trades) performance
# ---------------------------------------------------------------------------

def test_large_trade_log_performance(tmp_path):
    np.random.seed(666)
    symbols = ['AAPL', 'JPM', 'XOM', 'UNH', 'GE', 'NEE', 'VZ', 'AMZN', 'MSFT', 'KO']
    n = 150
    trades = []
    base_date = pd.Timestamp('2024-01-02')
    for i in range(n):
        sym = symbols[i % len(symbols)]
        entry = base_date + pd.Timedelta(days=i * 3)
        exit_ = entry + pd.Timedelta(days=5)
        ret = np.random.normal(0.01, 0.05)
        trades.append({
            'symbol': sym,
            'entry_date': entry.strftime('%Y-%m-%d'),
            'exit_date': exit_.strftime('%Y-%m-%d'),
            'return': round(ret, 4),
            'pnl': round(ret * 10000, 2),
            'exit_reason': np.random.choice(['hold_expired', 'position_stop', 'momentum_exit']),
        })

    start = time.time()
    analytics = _build_analytics(tmp_path, trades)
    summary = analytics.get_summary()
    elapsed = time.time() - start

    assert summary['overall']['total_trades'] == 150
    assert elapsed < 5.0  # should be well under 1 second
    assert len(summary['segments']['sector']) > 1
    assert len(summary['segments']['year']) >= 1


def test_large_trade_log_all_segments_populated(tmp_path):
    np.random.seed(666)
    symbols = ['AAPL', 'JPM', 'XOM', 'UNH', 'GE', 'VZ', 'AMZN']
    n = 100
    trades = []
    base_date = pd.Timestamp('2024-01-02')
    for i in range(n):
        sym = symbols[i % len(symbols)]
        entry = base_date + pd.Timedelta(days=i * 4)
        exit_ = entry + pd.Timedelta(days=5)
        ret = 0.03 if i % 3 != 0 else -0.02
        trades.append({
            'symbol': sym,
            'entry_date': entry.strftime('%Y-%m-%d'),
            'exit_date': exit_.strftime('%Y-%m-%d'),
            'return': ret,
            'pnl': ret * 10000,
            'exit_reason': ['hold_expired', 'position_stop', 'momentum_exit'][i % 3],
        })
    analytics = _build_analytics(tmp_path, trades)
    summary = analytics.get_summary()
    for seg_name in ['exit_reason', 'sector', 'year']:
        assert len(summary['segments'][seg_name]) >= 2


# ---------------------------------------------------------------------------
# 9. Trades with zero return
# ---------------------------------------------------------------------------

def test_zero_return_trade_is_not_a_win(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.0, 'pnl': 0.0, 'exit_reason': 'hold_expired'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    assert analytics.trades_df['win'].iloc[0] == False
    overall = analytics.get_overall_stats()
    assert overall['win_rate_pct'] == 0.0


def test_zero_return_among_mixed_trades(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'MSFT', 'entry_date': '2025-01-07', 'exit_date': '2025-01-11',
         'return': 0.0, 'pnl': 0.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'GOOGL', 'entry_date': '2025-01-08', 'exit_date': '2025-01-12',
         'return': -0.03, 'pnl': -300.0, 'exit_reason': 'position_stop'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    overall = analytics.get_overall_stats()
    # Only AAPL is a win (1 of 3)
    assert overall['win_rate_pct'] == pytest.approx(33.3, abs=0.1)


def test_all_zero_return_trades(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.0, 'pnl': 0.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'MSFT', 'entry_date': '2025-01-07', 'exit_date': '2025-01-11',
         'return': 0.0, 'pnl': 0.0, 'exit_reason': 'hold_expired'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    overall = analytics.get_overall_stats()
    assert overall['win_rate_pct'] == 0.0
    assert overall['total_pnl'] == 0.0


# ---------------------------------------------------------------------------
# 10. All winning trades -> infinite profit factor handling
# ---------------------------------------------------------------------------

def test_all_winning_trades_infinite_profit_factor(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'MSFT', 'entry_date': '2025-01-07', 'exit_date': '2025-01-11',
         'return': 0.03, 'pnl': 300.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'GOOGL', 'entry_date': '2025-01-08', 'exit_date': '2025-01-12',
         'return': 0.04, 'pnl': 400.0, 'exit_reason': 'momentum_exit'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    df = analytics.trades_df
    gross_losses = abs(df.loc[df['pnl'] < 0, 'pnl'].sum())
    assert gross_losses == 0.0
    overall = analytics.get_overall_stats()
    assert overall['win_rate_pct'] == 100.0
    assert overall['total_pnl'] > 0


def test_all_winning_trades_stats_coherent(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'NVDA', 'entry_date': '2025-01-07', 'exit_date': '2025-01-11',
         'return': 0.08, 'pnl': 800.0, 'exit_reason': 'hold_expired'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    stats = analytics._compute_segment_stats(analytics.trades_df)
    assert stats['win_rate_pct'] == 100.0
    assert stats['worst_trade_pct'] > 0
    assert stats['best_trade_pct'] >= stats['worst_trade_pct']


# ---------------------------------------------------------------------------
# 11. All losing trades -> zero profit factor
# ---------------------------------------------------------------------------

def test_all_losing_trades_zero_profit_factor(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': -0.04, 'pnl': -400.0, 'exit_reason': 'position_stop'},
        {'symbol': 'MSFT', 'entry_date': '2025-01-07', 'exit_date': '2025-01-11',
         'return': -0.02, 'pnl': -200.0, 'exit_reason': 'position_stop'},
        {'symbol': 'GOOGL', 'entry_date': '2025-01-08', 'exit_date': '2025-01-12',
         'return': -0.06, 'pnl': -600.0, 'exit_reason': 'position_stop'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    df = analytics.trades_df
    gross_wins = df.loc[df['pnl'] > 0, 'pnl'].sum()
    assert gross_wins == 0.0
    overall = analytics.get_overall_stats()
    assert overall['win_rate_pct'] == 0.0
    assert overall['total_pnl'] < 0


def test_all_losing_trades_stats(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': -0.03, 'pnl': -300.0, 'exit_reason': 'position_stop'},
        {'symbol': 'MSFT', 'entry_date': '2025-01-07', 'exit_date': '2025-01-11',
         'return': -0.05, 'pnl': -500.0, 'exit_reason': 'position_stop'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    stats = analytics._compute_segment_stats(analytics.trades_df)
    assert stats['win_rate_pct'] == 0.0
    assert stats['best_trade_pct'] < 0
    assert stats['avg_return_pct'] < 0


# ---------------------------------------------------------------------------
# Additional edge case tests
# ---------------------------------------------------------------------------

def test_get_summary_has_all_segment_keys(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    summary = analytics.get_summary()
    assert 'generated_at' in summary
    assert 'overall' in summary
    assert set(summary['segments'].keys()) == {
        'exit_reason', 'regime', 'sector', 'year', 'dow', 'vol_environment',
    }


def test_vol_environment_segmentation_with_leverage(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'MSFT', 'entry_date': '2025-01-07', 'exit_date': '2025-01-11',
         'return': -0.02, 'pnl': -200.0, 'exit_reason': 'position_stop'},
    ]
    daily = [
        {'date': '2025-01-06', 'risk_on': True, 'leverage': 1.0, 'in_protection': False},
        {'date': '2025-01-07', 'risk_on': False, 'leverage': 0.5, 'in_protection': True},
    ]
    analytics = _build_analytics(tmp_path, trades, daily)
    vol = analytics.segment_by_vol_environment()
    assert 'Low Vol' in vol
    assert 'High Vol' in vol
    assert vol['Low Vol']['count'] == 1
    assert vol['High Vol']['count'] == 1


def test_regime_risk_on_off_mapping(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'MSFT', 'entry_date': '2025-01-07', 'exit_date': '2025-01-11',
         'return': -0.02, 'pnl': -200.0, 'exit_reason': 'position_stop'},
    ]
    daily = [
        {'date': '2025-01-06', 'risk_on': True, 'leverage': 1.0, 'in_protection': False},
        {'date': '2025-01-07', 'risk_on': False, 'leverage': 0.6, 'in_protection': True},
    ]
    analytics = _build_analytics(tmp_path, trades, daily)
    regime = analytics.segment_by_regime()
    assert 'Risk-ON' in regime
    assert 'Risk-OFF' in regime


def test_holding_days_calculation(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    assert analytics.trades_df['holding_days'].iloc[0] == 4


def test_year_segmentation_multi_year(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2023-06-01', 'exit_date': '2023-06-05',
         'return': 0.03, 'pnl': 300.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'MSFT', 'entry_date': '2024-06-01', 'exit_date': '2024-06-05',
         'return': 0.04, 'pnl': 400.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'GOOGL', 'entry_date': '2025-06-01', 'exit_date': '2025-06-05',
         'return': -0.02, 'pnl': -200.0, 'exit_reason': 'position_stop'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    year = analytics.segment_by_year()
    assert set(year.keys()) == {'2023', '2024', '2025'}
    assert year['2023']['count'] == 1
    assert year['2024']['count'] == 1
    assert year['2025']['count'] == 1


def test_compute_segment_stats_returns_none_for_empty(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    empty_df = analytics.trades_df.iloc[0:0]
    result = analytics._compute_segment_stats(empty_df)
    assert result is None


def test_alpha_contribution_sums_to_100_for_full_dataset(tmp_path):
    trades = [
        {'symbol': 'AAPL', 'entry_date': '2025-01-06', 'exit_date': '2025-01-10',
         'return': 0.05, 'pnl': 500.0, 'exit_reason': 'hold_expired'},
        {'symbol': 'JPM', 'entry_date': '2025-01-07', 'exit_date': '2025-01-11',
         'return': -0.02, 'pnl': -200.0, 'exit_reason': 'position_stop'},
        {'symbol': 'XOM', 'entry_date': '2025-01-08', 'exit_date': '2025-01-12',
         'return': 0.03, 'pnl': 300.0, 'exit_reason': 'momentum_exit'},
    ]
    analytics = _build_analytics(tmp_path, trades)
    by_exit = analytics.segment_by_exit_reason()
    total_alpha = sum(s['alpha_contribution_pct'] for s in by_exit.values())
    assert total_alpha == pytest.approx(100.0, abs=0.5)
