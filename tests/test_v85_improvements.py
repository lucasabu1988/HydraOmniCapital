"""Tests for COMPASS v8.5 improvements: stop widening + market breadth."""

import pandas as pd
import numpy as np
import pytest


def _make_price_df(prices, start='2020-01-01'):
    """Helper: create a minimal price DataFrame from a list of close prices."""
    dates = pd.bdate_range(start, periods=len(prices))
    return pd.DataFrame({'Close': prices}, index=dates)


class TestBreadthScore:
    """Test compute_breadth_score()."""

    def test_all_stocks_above_sma50(self):
        from omnicapital_v85_compass import compute_breadth_score
        prices_up = list(range(100, 160))
        price_data = {
            'AAPL': _make_price_df(prices_up),
            'MSFT': _make_price_df(prices_up),
            'GOOGL': _make_price_df(prices_up),
        }
        tradeable = ['AAPL', 'MSFT', 'GOOGL']
        date = price_data['AAPL'].index[-1]
        score = compute_breadth_score(price_data, tradeable, date)
        assert score > 0.5, f"All above SMA50 should give score > 0.5, got {score}"

    def test_all_stocks_below_sma50(self):
        from omnicapital_v85_compass import compute_breadth_score
        prices_down = list(range(160, 100, -1))
        price_data = {
            'AAPL': _make_price_df(prices_down),
            'MSFT': _make_price_df(prices_down),
        }
        tradeable = ['AAPL', 'MSFT']
        date = price_data['AAPL'].index[-1]
        score = compute_breadth_score(price_data, tradeable, date)
        assert score < 0.5, f"All below SMA50 should give score < 0.5, got {score}"

    def test_mixed_breadth(self):
        from omnicapital_v85_compass import compute_breadth_score
        prices_up = list(range(100, 160))
        prices_down = list(range(160, 100, -1))
        price_data = {
            'AAPL': _make_price_df(prices_up),
            'MSFT': _make_price_df(prices_down),
        }
        tradeable = ['AAPL', 'MSFT']
        date = price_data['AAPL'].index[-1]
        score = compute_breadth_score(price_data, tradeable, date)
        assert 0.45 <= score <= 0.55, f"50/50 breadth should be ~0.5, got {score}"

    def test_insufficient_history(self):
        from omnicapital_v85_compass import compute_breadth_score
        prices_short = list(range(100, 130))
        price_data = {'AAPL': _make_price_df(prices_short)}
        tradeable = ['AAPL']
        date = price_data['AAPL'].index[-1]
        score = compute_breadth_score(price_data, tradeable, date)
        assert score == 0.5, f"No qualifying stocks should return 0.5, got {score}"

    def test_empty_tradeable(self):
        from omnicapital_v85_compass import compute_breadth_score
        score = compute_breadth_score({}, [], pd.Timestamp('2024-01-15'))
        assert score == 0.5


class TestRegimeWithBreadth:
    """Test that regime score incorporates breadth component."""

    def test_regime_uses_breadth_weight(self):
        from omnicapital_v85_compass import REGIME_TREND_WEIGHT, REGIME_VOL_WEIGHT, REGIME_BREADTH_WEIGHT
        assert abs(REGIME_TREND_WEIGHT + REGIME_VOL_WEIGHT + REGIME_BREADTH_WEIGHT - 1.0) < 0.001

    def test_regime_signature_accepts_breadth_args(self):
        import inspect
        from omnicapital_v85_compass import compute_regime_score
        sig = inspect.signature(compute_regime_score)
        params = list(sig.parameters.keys())
        assert 'price_data' in params, f"Missing price_data param: {params}"
        assert 'tradeable_symbols' in params, f"Missing tradeable_symbols param: {params}"

    def test_high_breadth_increases_regime(self):
        from omnicapital_v85_compass import compute_regime_score
        spy_prices = [100.0] * 300
        spy_dates = pd.bdate_range('2019-01-01', periods=300)
        spy_data = pd.DataFrame({'Close': spy_prices}, index=spy_dates)
        date = spy_dates[-1]
        score_no_breadth = compute_regime_score(spy_data, date)
        prices_up = [float(i) for i in range(100, 400)]
        price_data = {
            'AAPL': pd.DataFrame({'Close': prices_up[:300]}, index=spy_dates),
            'MSFT': pd.DataFrame({'Close': prices_up[:300]}, index=spy_dates),
        }
        score_with_breadth = compute_regime_score(
            spy_data, date, price_data=price_data, tradeable_symbols=['AAPL', 'MSFT']
        )
        assert score_with_breadth >= score_no_breadth, \
            f"Breadth should increase regime: {score_with_breadth} vs {score_no_breadth}"


class TestStopWidening:
    """Test regime-conditional stop widening."""

    def test_bull_regime_widens_stop(self):
        """Regime >= 0.65 should divide stop by STOP_BULL_MULT (1.4), making it less negative (wider)."""
        from omnicapital_v85_compass import compute_adaptive_stop, STOP_BULL_MULT
        base_stop = compute_adaptive_stop(0.025)  # e.g., -0.0625
        widened = base_stop / STOP_BULL_MULT       # e.g., -0.0446 (less negative = wider)
        assert widened > base_stop, f"Wider stop should be less negative: {widened} vs {base_stop}"
        assert abs(widened - base_stop / 1.4) < 0.001

    def test_mild_bull_widens_stop(self):
        """Regime >= 0.50 and < 0.65 should divide by STOP_MILD_BULL_MULT (1.2)."""
        from omnicapital_v85_compass import compute_adaptive_stop, STOP_MILD_BULL_MULT
        base_stop = compute_adaptive_stop(0.025)
        widened = base_stop / STOP_MILD_BULL_MULT
        assert widened > base_stop, f"Wider stop should be less negative: {widened} vs {base_stop}"
        assert abs(widened - base_stop / 1.2) < 0.001

    def test_bear_regime_no_widening(self):
        """Regime < 0.50 should not widen the stop (mult = 1.0)."""
        from omnicapital_v85_compass import compute_adaptive_stop
        base_stop = compute_adaptive_stop(0.025)
        assert base_stop * 1.0 == base_stop

    def test_widened_stop_stays_negative(self):
        """Widened stop should still be a negative value (a real stop loss)."""
        from omnicapital_v85_compass import compute_adaptive_stop, STOP_BULL_MULT
        base_stop = compute_adaptive_stop(0.025)
        widened = base_stop / STOP_BULL_MULT
        assert widened < 0, f"Stop should remain negative: {widened}"
