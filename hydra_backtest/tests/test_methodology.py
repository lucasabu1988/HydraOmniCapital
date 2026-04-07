"""Tests for hydra_backtest.methodology module."""
from datetime import datetime

import pandas as pd
import pytest

from hydra_backtest.engine import BacktestResult
from hydra_backtest.methodology import (
    WaterfallReport,
    WaterfallTier,
    apply_slippage_postprocess,
    build_waterfall,
    compute_metrics,
)


# -- compute_metrics ----------------------------------------------------------

def test_compute_metrics_steady_5pct_growth():
    """A perfectly steady 5% annual growth should give CAGR ≈ 5%.

    Uses log-linear interpolation between start and a target final value
    that corresponds exactly to 5% CAGR over the elapsed calendar years,
    so the test is robust to trading-day vs calendar-day arithmetic.
    """
    dates = pd.date_range('2020-01-01', periods=252 * 3)
    years = (dates[-1] - dates[0]).days / 365.25
    target_final = 100_000 * (1.05 ** years)
    n = len(dates)
    values = [
        100_000 * (target_final / 100_000) ** (i / (n - 1))
        for i in range(n)
    ]
    daily = pd.DataFrame({'date': dates, 'portfolio_value': values})
    m = compute_metrics(daily, risk_free_rate_annual=0.0)
    assert abs(m['cagr'] - 0.05) < 0.001


def test_compute_metrics_max_drawdown():
    dates = pd.date_range('2020-01-01', periods=100)
    values = [100_000.0] * 50 + [50_000.0] * 50  # -50% drawdown
    daily = pd.DataFrame({'date': dates, 'portfolio_value': values})
    m = compute_metrics(daily, risk_free_rate_annual=0.0)
    assert abs(m['max_drawdown'] - (-0.5)) < 1e-9


def test_compute_metrics_sharpe_rf_adjustment():
    """Sharpe should decrease when rf is increased (excess return drops)."""
    dates = pd.date_range('2020-01-01', periods=252 * 2)
    values = [100_000 * (1 + 0.10 / 252) ** i for i in range(len(dates))]
    daily = pd.DataFrame({'date': dates, 'portfolio_value': values})
    m0 = compute_metrics(daily, risk_free_rate_annual=0.0)
    m3 = compute_metrics(daily, risk_free_rate_annual=0.03)
    assert m3['sharpe'] < m0['sharpe']


def test_compute_metrics_empty_daily():
    m = compute_metrics(pd.DataFrame(), risk_free_rate_annual=0.0)
    assert m['cagr'] == 0.0
    assert m['sharpe'] == 0.0


# -- Helpers ------------------------------------------------------------------

def _fake_result(cagr_target=0.10, with_trades=True):
    """Build a fake BacktestResult with a given CAGR."""
    dates = pd.date_range('2020-01-01', periods=252 * 3)
    values = [100_000 * (1 + cagr_target / 252) ** i for i in range(len(dates))]
    daily = pd.DataFrame({
        'date': dates,
        'portfolio_value': values,
        'cash': values,
        'n_positions': [5] * len(dates),
        'leverage': [1.0] * len(dates),
        'drawdown': [0.0] * len(dates),
        'regime_score': [0.7] * len(dates),
        'crash_active': [False] * len(dates),
        'max_positions': [5] * len(dates),
    })
    if with_trades:
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
    else:
        trades = pd.DataFrame(columns=[
            'symbol', 'entry_date', 'exit_date', 'exit_reason',
            'entry_price', 'exit_price', 'shares', 'pnl', 'return', 'sector',
        ])
    return BacktestResult(
        config={},
        daily_values=daily,
        trades=trades,
        decisions=[],
        exit_events=[],
        universe_size={2020: 30},
        started_at=datetime(2026, 4, 6),
        finished_at=datetime(2026, 4, 6),
        git_sha='test',
        data_inputs_hash='test',
    )


# -- apply_slippage_postprocess -----------------------------------------------

def test_apply_slippage_postprocess_reduces_pnl():
    result = _fake_result(cagr_target=0.12)
    adjusted = apply_slippage_postprocess(result, slippage_bps=2.0, half_spread_bps=0.5)
    assert adjusted.trades['pnl'].iloc[0] < 50.0
    assert len(adjusted.trades) == len(result.trades)


def test_apply_slippage_postprocess_affects_equity_curve():
    result = _fake_result(cagr_target=0.12)
    adjusted = apply_slippage_postprocess(result, slippage_bps=5.0, half_spread_bps=2.0)
    assert (
        adjusted.daily_values['portfolio_value'].iloc[-1]
        < result.daily_values['portfolio_value'].iloc[-1]
    )


def test_apply_slippage_postprocess_no_trades_is_identity():
    result = _fake_result(cagr_target=0.12, with_trades=False)
    adjusted = apply_slippage_postprocess(result, slippage_bps=5.0, half_spread_bps=2.0)
    pd.testing.assert_frame_equal(
        adjusted.daily_values.reset_index(drop=True),
        result.daily_values.reset_index(drop=True),
    )


# -- build_waterfall ----------------------------------------------------------

def test_build_waterfall_returns_five_tiers():
    """build_waterfall takes 3 results (tier 0, 1, 2) and post-processes tier 3,
    then appends net_honest as an alias tier, for 5 total."""
    r0 = _fake_result(cagr_target=0.12)
    r1 = _fake_result(cagr_target=0.11)
    r2 = _fake_result(cagr_target=0.105)
    report = build_waterfall(
        tier_0=r0, tier_1=r1, tier_2=r2,
        t_bill_rf=0.03, slippage_bps=2.0, half_spread_bps=0.5,
    )
    assert len(report.tiers) == 5
    names = [t.name for t in report.tiers]
    assert names == ['baseline', 't_bill', 'next_open', 'real_costs', 'net_honest']


def test_build_waterfall_deltas_populated():
    r0 = _fake_result(cagr_target=0.12)
    r1 = _fake_result(cagr_target=0.11)
    r2 = _fake_result(cagr_target=0.10)
    report = build_waterfall(
        tier_0=r0, tier_1=r1, tier_2=r2,
        t_bill_rf=0.03, slippage_bps=2.0, half_spread_bps=0.5,
    )
    # Tier 0 has no delta (first tier)
    assert report.tiers[0].delta_cagr_bps == 0.0
    # Subsequent tiers have non-zero delta
    assert report.tiers[1].delta_cagr_bps != 0.0
    assert report.tiers[2].delta_cagr_bps != 0.0
