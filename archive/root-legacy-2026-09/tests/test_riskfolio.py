import pytest
import pandas as pd
import numpy as np


def _make_hist_data(symbols, days=100, seed=666):
    np.random.seed(seed)
    hist = {}
    for i, sym in enumerate(symbols):
        dates = pd.bdate_range("2025-12-01", periods=days)
        base_price = 100 + i * 50
        returns = np.random.normal(0.0005, 0.01 + i * 0.005, days)
        prices = base_price * np.cumprod(1 + returns)
        hist[sym] = pd.DataFrame({"Close": prices}, index=dates)
    return hist


class TestOptimizeWeights:
    def test_cascade_returns_valid_weights(self):
        from compass_riskfolio import optimize_weights
        symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "META"]
        hist = _make_hist_data(symbols)
        result = optimize_weights(symbols, hist_data=hist)
        assert "weights" in result
        assert "method_used" in result
        weights = result["weights"]
        assert abs(sum(weights.values()) - 1.0) < 1e-6
        for w in weights.values():
            assert 0.05 - 1e-6 <= w <= 0.40 + 1e-6

    def test_cascade_method_is_recorded(self):
        from compass_riskfolio import optimize_weights
        symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "META"]
        hist = _make_hist_data(symbols)
        result = optimize_weights(symbols, hist_data=hist)
        assert result["method_used"] in ("min_cvar", "risk_parity", "inv_vol")

    def test_inv_vol_method_directly(self):
        from compass_riskfolio import optimize_weights
        symbols = ["AAPL", "MSFT", "GOOGL"]
        hist = _make_hist_data(symbols)
        result = optimize_weights(symbols, hist_data=hist, method="inv_vol")
        assert result["method_used"] == "inv_vol"
        assert abs(sum(result["weights"].values()) - 1.0) < 1e-6

    def test_fallback_to_risk_parity_when_cvar_fails(self):
        from compass_riskfolio import optimize_weights
        from unittest.mock import patch
        symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "META"]
        hist = _make_hist_data(symbols)
        with patch("compass_riskfolio._try_min_cvar", side_effect=Exception("solver fail")):
            result = optimize_weights(symbols, hist_data=hist)
        assert result["method_used"] in ("risk_parity", "inv_vol")
        assert abs(sum(result["weights"].values()) - 1.0) < 1e-6

    def test_fallback_to_inv_vol_on_failure(self):
        from compass_riskfolio import optimize_weights
        from unittest.mock import patch
        symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "META"]
        hist = _make_hist_data(symbols)
        with patch("compass_riskfolio._try_min_cvar", side_effect=Exception("solver fail")):
            with patch("compass_riskfolio._try_risk_parity", side_effect=Exception("solver fail")):
                result = optimize_weights(symbols, hist_data=hist)
        assert result["method_used"] == "inv_vol"
        assert abs(sum(result["weights"].values()) - 1.0) < 1e-6


class TestEdgeCases:
    def test_single_symbol(self):
        from compass_riskfolio import optimize_weights
        hist = _make_hist_data(["AAPL"])
        result = optimize_weights(["AAPL"], hist_data=hist)
        assert result["weights"]["AAPL"] == pytest.approx(1.0)

    def test_two_symbols(self):
        from compass_riskfolio import optimize_weights
        symbols = ["AAPL", "MSFT"]
        hist = _make_hist_data(symbols)
        result = optimize_weights(symbols, hist_data=hist)
        weights = result["weights"]
        assert abs(sum(weights.values()) - 1.0) < 1e-6
        for w in weights.values():
            assert 0.05 - 1e-6 <= w <= 0.95 + 1e-6

    def test_missing_symbol_data(self):
        from compass_riskfolio import optimize_weights
        symbols = ["AAPL", "MSFT", "MISSING"]
        hist = _make_hist_data(["AAPL", "MSFT"])
        result = optimize_weights(symbols, hist_data=hist)
        assert "MISSING" not in result["weights"]
        assert abs(sum(result["weights"].values()) - 1.0) < 1e-6


class TestRiskContribution:
    def test_risk_contribution_sums_to_one(self):
        from compass_riskfolio import optimize_weights, compute_risk_contribution
        symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "META"]
        hist = _make_hist_data(symbols)
        result = optimize_weights(symbols, hist_data=hist)
        rc = compute_risk_contribution(symbols, result["weights"], hist_data=hist)
        total_rc = sum(v["risk_contribution"] for v in rc.values())
        assert abs(total_rc - 1.0) < 0.01
