import math

import pandas as pd
import pytest

from compass_portfolio_risk import (
    RISK_LOOKBACK_DAYS,
    VAR_Z_95,
    compute_portfolio_risk,
)


def make_history(start, daily_returns):
    prices = [start]
    for daily_return in daily_returns:
        prices.append(prices[-1] * (1 + daily_return))
    dates = pd.date_range('2026-01-01', periods=len(prices), freq='B')
    return pd.DataFrame({'Close': prices}, index=dates)


def make_state(positions, cash=0.0, portfolio_value=None, sectors=None):
    sectors = sectors or {}
    positions_dict = {}
    position_meta = {}
    prices = {}

    total_value = cash
    for symbol, (shares, price) in positions.items():
        positions_dict[symbol] = {'shares': shares, 'avg_cost': price}
        position_meta[symbol] = {'sector': sectors.get(symbol, 'Unknown')}
        prices[symbol] = price
        total_value += shares * price

    return {
        'cash': cash,
        'portfolio_value': portfolio_value or total_value,
        'positions': positions_dict,
        'position_meta': position_meta,
    }, prices


def test_empty_portfolio_returns_low_risk():
    risk = compute_portfolio_risk(
        {'cash': 100000.0, 'portfolio_value': 100000.0, 'positions': {}, 'position_meta': {}},
        {},
        {},
    )

    assert risk['risk_score'] == 0.0
    assert risk['risk_label'] == 'LOW'
    assert risk['num_positions'] == 0


def test_equal_weight_portfolio_has_expected_concentration():
    state, prices = make_state(
        {'AAPL': (100, 100.0), 'MSFT': (100, 100.0), 'NVDA': (100, 100.0), 'META': (100, 100.0)},
        cash=60000.0,
        sectors={'AAPL': 'Tech', 'MSFT': 'Tech', 'NVDA': 'Tech', 'META': 'Tech'},
    )

    risk = compute_portfolio_risk(state, prices, {})

    assert risk['concentration_risk'] == pytest.approx(0.04, rel=1e-3)
    assert risk['max_position_pct'] == pytest.approx(10.0, rel=1e-3)


def test_sector_concentration_aggregates_position_meta():
    state, prices = make_state(
        {'AAPL': (100, 100.0), 'XOM': (100, 100.0), 'CVX': (100, 100.0)},
        cash=10000.0,
        sectors={'AAPL': 'Tech', 'XOM': 'Energy', 'CVX': 'Energy'},
    )

    risk = compute_portfolio_risk(state, prices, {})

    assert risk['sector_concentration'] == pytest.approx(50.0, rel=1e-3)


def test_correlation_and_beta_use_historical_returns():
    state, prices = make_state(
        {'AAPL': (200, 100.0), 'MSFT': (150, 100.0)},
        cash=50000.0,
        sectors={'AAPL': 'Tech', 'MSFT': 'Tech'},
    )
    aapl_hist = make_history(100.0, [0.01, -0.002, 0.008, 0.012, -0.004, 0.009, 0.01, -0.003])
    msft_hist = make_history(100.0, [0.009, -0.001, 0.007, 0.011, -0.003, 0.008, 0.011, -0.002])
    spy_hist = make_history(400.0, [0.008, -0.001, 0.006, 0.009, -0.002, 0.007, 0.008, -0.001])

    risk = compute_portfolio_risk(
        state,
        prices,
        {'AAPL': aapl_hist, 'MSFT': msft_hist, 'SPY': spy_hist},
    )

    assert risk['correlation_risk'] > 0.9
    assert risk['beta'] > 0
    assert risk['var_95'] > 0
    assert risk['var_95_pct'] > 0


def test_single_stock_portfolio_scores_as_high_or_extreme():
    state, prices = make_state(
        {'NVDA': (1000, 100.0)},
        cash=0.0,
        sectors={'NVDA': 'Tech'},
    )
    nvda_hist = make_history(100.0, [0.04, -0.035, 0.05, -0.03, 0.045, -0.04, 0.05, -0.025])
    spy_hist = make_history(400.0, [0.01, -0.008, 0.011, -0.007, 0.01, -0.009, 0.012, -0.006])

    risk = compute_portfolio_risk(
        state,
        prices,
        {'NVDA': nvda_hist, 'SPY': spy_hist},
    )

    assert risk['concentration_risk'] == pytest.approx(1.0, rel=1e-3)
    assert risk['sector_concentration'] == pytest.approx(100.0, rel=1e-3)
    assert risk['max_position_pct'] == pytest.approx(100.0, rel=1e-3)
    assert risk['risk_label'] in {'HIGH', 'EXTREME'}


def test_missing_history_gracefully_falls_back_to_static_metrics():
    state, prices = make_state(
        {'JNJ': (50, 150.0), 'MRK': (50, 150.0)},
        cash=85000.0,
        sectors={'JNJ': 'Healthcare', 'MRK': 'Healthcare'},
    )

    risk = compute_portfolio_risk(state, prices, {'SPY': make_history(400.0, [0.001] * 8)})

    assert risk['correlation_risk'] == 0.0
    assert risk['var_95'] == 0.0
    assert risk['beta'] == 0.0
    assert risk['risk_score'] >= 0.0


def test_var_95_scales_to_30_day_horizon():
    state, prices = make_state(
        {'AAPL': (100, 100.0)},
        cash=0.0,
        sectors={'AAPL': 'Tech'},
    )
    aapl_hist = make_history(100.0, [0.01, -0.02, 0.015, -0.005, 0.012, 0.008, -0.011, 0.006])

    risk = compute_portfolio_risk(state, prices, {'AAPL': aapl_hist})

    daily_returns = aapl_hist['Close'].pct_change().dropna()
    one_day_vol = float(daily_returns.std(ddof=0))
    expected_pct = one_day_vol * VAR_Z_95 * math.sqrt(RISK_LOOKBACK_DAYS) * 100.0
    expected_value = state['portfolio_value'] * one_day_vol * VAR_Z_95 * math.sqrt(RISK_LOOKBACK_DAYS)

    assert risk['var_95_pct'] == pytest.approx(expected_pct, abs=0.01)
    assert risk['var_95'] == pytest.approx(expected_value, abs=0.01)


def test_zero_portfolio_value_falls_back_to_live_position_value():
    state = {
        'cash': 0.0,
        'portfolio_value': 0.0,
        'positions': {'AAPL': {'shares': 10, 'avg_cost': 100.0}},
        'position_meta': {'AAPL': {'sector': 'Tech'}},
    }

    risk = compute_portfolio_risk(state, {'AAPL': 100.0}, {})

    assert risk['portfolio_value'] == pytest.approx(1000.0)
    assert risk['num_positions'] == 1
    assert risk['max_position_pct'] == pytest.approx(100.0)
    assert math.isfinite(risk['risk_score'])
