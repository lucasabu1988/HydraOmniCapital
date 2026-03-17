import math

import numpy as np
import pandas as pd
import pytest

from compass_portfolio_risk import (
    RISK_LOOKBACK_DAYS,
    VAR_Z_95,
    _coerce_price,
    _extract_close_series,
    _label_for_score,
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


# ---------------------------------------------------------------------------
# 1. Empty portfolio returns safe defaults
# ---------------------------------------------------------------------------

def test_empty_portfolio_returns_low_risk():
    risk = compute_portfolio_risk(
        {'cash': 100000.0, 'portfolio_value': 100000.0, 'positions': {}, 'position_meta': {}},
        {},
        {},
    )

    assert risk['risk_score'] == 0.0
    assert risk['risk_label'] == 'LOW'
    assert risk['num_positions'] == 0


def test_empty_portfolio_all_risk_metrics_zero():
    risk = compute_portfolio_risk(
        {'cash': 50000.0, 'positions': None, 'position_meta': None},
        None,
        None,
    )

    assert risk['concentration_risk'] == 0.0
    assert risk['sector_concentration'] == 0.0
    assert risk['correlation_risk'] == 0.0
    assert risk['var_95'] == 0.0
    assert risk['var_95_pct'] == 0.0
    assert risk['max_position_pct'] == 0.0
    assert risk['beta'] == 0.0


def test_empty_portfolio_preserves_cash():
    risk = compute_portfolio_risk(
        {'cash': 75000.0, 'positions': {}, 'position_meta': {}},
        {},
        {},
    )

    assert risk['cash'] == 75000.0
    assert risk['portfolio_value'] == 75000.0


# ---------------------------------------------------------------------------
# 2. Single position portfolio
# ---------------------------------------------------------------------------

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


def test_single_position_num_positions_is_one():
    state, prices = make_state({'AAPL': (50, 200.0)}, cash=0.0)

    risk = compute_portfolio_risk(state, prices, {})

    assert risk['num_positions'] == 1


def test_single_position_no_correlation():
    state, prices = make_state({'GOOG': (20, 150.0)}, cash=0.0)
    hist = make_history(150.0, [0.01, -0.005, 0.008, 0.003, -0.002, 0.007, 0.01, -0.004])

    risk = compute_portfolio_risk(state, prices, {'GOOG': hist})

    assert risk['correlation_risk'] == 0.0


# ---------------------------------------------------------------------------
# 3. Diversified 5-position portfolio
# ---------------------------------------------------------------------------

def test_diversified_five_position_portfolio():
    state, prices = make_state(
        {
            'AAPL': (100, 100.0),
            'XOM': (100, 100.0),
            'JNJ': (100, 100.0),
            'JPM': (100, 100.0),
            'PG': (100, 100.0),
        },
        cash=50000.0,
        sectors={
            'AAPL': 'Tech',
            'XOM': 'Energy',
            'JNJ': 'Healthcare',
            'JPM': 'Financials',
            'PG': 'Consumer',
        },
    )

    risk = compute_portfolio_risk(state, prices, {})

    assert risk['num_positions'] == 5
    assert risk['concentration_risk'] < 0.25
    assert risk['max_position_pct'] < 15.0
    assert risk['sector_concentration'] <= 15.0


def test_diversified_portfolio_lower_risk_than_concentrated():
    diversified_state, div_prices = make_state(
        {
            'AAPL': (100, 100.0),
            'XOM': (100, 100.0),
            'JNJ': (100, 100.0),
            'JPM': (100, 100.0),
            'PG': (100, 100.0),
        },
        cash=0.0,
        sectors={
            'AAPL': 'Tech',
            'XOM': 'Energy',
            'JNJ': 'Healthcare',
            'JPM': 'Financials',
            'PG': 'Consumer',
        },
    )

    concentrated_state, conc_prices = make_state(
        {'NVDA': (500, 100.0)},
        cash=0.0,
        sectors={'NVDA': 'Tech'},
    )

    div_risk = compute_portfolio_risk(diversified_state, div_prices, {})
    conc_risk = compute_portfolio_risk(concentrated_state, conc_prices, {})

    assert div_risk['concentration_risk'] < conc_risk['concentration_risk']
    assert div_risk['risk_score'] < conc_risk['risk_score']


# ---------------------------------------------------------------------------
# 4. Concentrated portfolio (>50% one stock)
# ---------------------------------------------------------------------------

def test_concentrated_portfolio_over_50_pct():
    state, prices = make_state(
        {'TSLA': (800, 100.0), 'AAPL': (100, 100.0), 'MSFT': (100, 100.0)},
        cash=0.0,
        sectors={'TSLA': 'Consumer', 'AAPL': 'Tech', 'MSFT': 'Tech'},
    )

    risk = compute_portfolio_risk(state, prices, {})

    assert risk['max_position_pct'] == pytest.approx(80.0, rel=1e-3)
    assert risk['concentration_risk'] > 0.5


def test_concentrated_portfolio_triggers_floor():
    state, prices = make_state(
        {'TSLA': (900, 100.0), 'AAPL': (100, 100.0)},
        cash=0.0,
        sectors={'TSLA': 'Consumer', 'AAPL': 'Tech'},
    )

    risk = compute_portfolio_risk(state, prices, {})

    assert risk['max_position_pct'] >= 80.0
    assert risk['risk_score'] >= 65.0


# ---------------------------------------------------------------------------
# 5. Output keys
# ---------------------------------------------------------------------------

EXPECTED_KEYS = {
    'computed_at', 'portfolio_value', 'cash', 'num_positions',
    'lookback_days', 'concentration_risk', 'sector_concentration',
    'correlation_risk', 'var_95', 'var_95_pct', 'max_position_pct',
    'beta', 'risk_score', 'risk_label',
}


def test_output_keys_empty_portfolio():
    risk = compute_portfolio_risk(
        {'cash': 10000.0, 'positions': {}, 'position_meta': {}},
        {},
        {},
    )

    assert set(risk.keys()) == EXPECTED_KEYS


def test_output_keys_with_positions():
    state, prices = make_state({'AAPL': (10, 150.0)}, cash=1000.0)

    risk = compute_portfolio_risk(state, prices, {})

    assert set(risk.keys()) == EXPECTED_KEYS


# ---------------------------------------------------------------------------
# 6. All values are floats and within expected ranges
# ---------------------------------------------------------------------------

def test_all_numeric_values_are_float():
    state, prices = make_state(
        {'AAPL': (100, 150.0), 'MSFT': (50, 300.0)},
        cash=5000.0,
        sectors={'AAPL': 'Tech', 'MSFT': 'Tech'},
    )
    hist = {
        'AAPL': make_history(150.0, [0.01, -0.005, 0.008, 0.003, -0.002, 0.007, 0.01, -0.004]),
        'MSFT': make_history(300.0, [0.008, -0.003, 0.006, 0.005, -0.001, 0.009, 0.008, -0.002]),
        'SPY': make_history(400.0, [0.005, -0.002, 0.004, 0.003, -0.001, 0.005, 0.006, -0.001]),
    }

    risk = compute_portfolio_risk(state, prices, hist)

    for key in ['concentration_risk', 'sector_concentration', 'correlation_risk',
                'var_95', 'var_95_pct', 'max_position_pct', 'beta', 'risk_score',
                'portfolio_value', 'cash']:
        assert isinstance(risk[key], float), f"{key} should be float, got {type(risk[key])}"
        assert math.isfinite(risk[key]), f"{key} should be finite"


def test_risk_score_bounded_0_to_100():
    state, prices = make_state({'AAPL': (100, 100.0)}, cash=0.0)

    risk = compute_portfolio_risk(state, prices, {})

    assert 0.0 <= risk['risk_score'] <= 100.0


def test_concentration_risk_bounded():
    state, prices = make_state(
        {'A': (100, 100.0), 'B': (100, 100.0)},
        cash=0.0,
    )

    risk = compute_portfolio_risk(state, prices, {})

    assert 0.0 <= risk['concentration_risk'] <= 1.0


def test_max_position_pct_bounded():
    state, prices = make_state(
        {'A': (100, 100.0), 'B': (200, 100.0)},
        cash=0.0,
    )

    risk = compute_portfolio_risk(state, prices, {})

    assert 0.0 <= risk['max_position_pct'] <= 100.0


# ---------------------------------------------------------------------------
# 7. Missing price data handling
# ---------------------------------------------------------------------------

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


def test_missing_price_uses_avg_cost():
    state = {
        'cash': 0.0,
        'positions': {'AAPL': {'shares': 10, 'avg_cost': 200.0}},
        'position_meta': {'AAPL': {'sector': 'Tech'}},
    }

    risk = compute_portfolio_risk(state, {}, {})

    assert risk['num_positions'] == 1
    assert risk['portfolio_value'] == pytest.approx(2000.0)


def test_partial_history_only_some_symbols():
    state, prices = make_state(
        {'AAPL': (100, 100.0), 'MSFT': (100, 100.0)},
        cash=0.0,
    )
    aapl_hist = make_history(100.0, [0.01, -0.005, 0.008, 0.003, -0.002, 0.007, 0.01, -0.004])

    risk = compute_portfolio_risk(state, prices, {'AAPL': aapl_hist})

    assert risk['correlation_risk'] == 0.0
    assert risk['var_95'] > 0.0


def test_empty_dataframe_history():
    state, prices = make_state({'AAPL': (100, 100.0)}, cash=0.0)
    empty_df = pd.DataFrame({'Close': []})

    risk = compute_portfolio_risk(state, prices, {'AAPL': empty_df})

    assert risk['var_95'] == 0.0


# ---------------------------------------------------------------------------
# 8. Zero portfolio value edge case
# ---------------------------------------------------------------------------

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


def test_zero_cash_zero_portfolio_no_positions():
    risk = compute_portfolio_risk(
        {'cash': 0.0, 'portfolio_value': 0.0, 'positions': {}, 'position_meta': {}},
        {},
        {},
    )

    assert risk['portfolio_value'] == 1.0  # fallback to 1.0 to avoid division by zero
    assert risk['risk_score'] == 0.0


# ---------------------------------------------------------------------------
# Additional coverage: helpers, equal-weight, sector, var, beta
# ---------------------------------------------------------------------------

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


def test_label_for_score_boundaries():
    assert _label_for_score(0) == 'LOW'
    assert _label_for_score(29.9) == 'LOW'
    assert _label_for_score(30) == 'MODERATE'
    assert _label_for_score(59.9) == 'MODERATE'
    assert _label_for_score(60) == 'HIGH'
    assert _label_for_score(79.9) == 'HIGH'
    assert _label_for_score(80) == 'EXTREME'
    assert _label_for_score(100) == 'EXTREME'


def test_coerce_price_handles_invalid_values():
    assert _coerce_price(None) == 0.0
    assert _coerce_price('abc') == 0.0
    assert _coerce_price(float('inf')) == 0.0
    assert _coerce_price(float('nan')) == 0.0
    assert _coerce_price(42.5) == 42.5
    assert _coerce_price('100.0') == 100.0


def test_extract_close_series_adj_close_preferred():
    df = pd.DataFrame({
        'Close': [100.0, 101.0, 102.0],
        'Adj Close': [99.0, 100.0, 101.0],
    })

    series = _extract_close_series(df)

    assert series is not None
    assert series.iloc[0] == pytest.approx(99.0)


def test_extract_close_series_none_on_empty():
    assert _extract_close_series(None) is None
    assert _extract_close_series(pd.DataFrame()) is None
    assert _extract_close_series(pd.DataFrame({'Volume': [100, 200]})) is None


def test_non_dict_position_ignored():
    state = {
        'cash': 0.0,
        'positions': {'AAPL': 'invalid', 'MSFT': {'shares': 10, 'avg_cost': 100.0}},
        'position_meta': {'MSFT': {'sector': 'Tech'}},
    }

    risk = compute_portfolio_risk(state, {'MSFT': 100.0}, {})

    assert risk['num_positions'] == 1


def test_negative_shares_ignored():
    state = {
        'cash': 5000.0,
        'positions': {'AAPL': {'shares': -10, 'avg_cost': 100.0}},
        'position_meta': {},
    }

    risk = compute_portfolio_risk(state, {'AAPL': 100.0}, {})

    assert risk['num_positions'] == 0


def test_risk_label_matches_risk_score():
    state, prices = make_state({'AAPL': (100, 100.0)}, cash=0.0)

    risk = compute_portfolio_risk(state, prices, {})

    score = risk['risk_score']
    if score < 30:
        assert risk['risk_label'] == 'LOW'
    elif score < 60:
        assert risk['risk_label'] == 'MODERATE'
    elif score < 80:
        assert risk['risk_label'] == 'HIGH'
    else:
        assert risk['risk_label'] == 'EXTREME'


def test_lookback_days_constant():
    risk = compute_portfolio_risk(
        {'cash': 1000.0, 'positions': {}, 'position_meta': {}},
        {},
        {},
    )

    assert risk['lookback_days'] == RISK_LOOKBACK_DAYS
    assert risk['lookback_days'] == 30
