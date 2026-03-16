import numpy as np
import pandas as pd
import pytest

from omnicapital_live import _sigmoid, compute_live_regime_score, regime_score_to_positions


class TestSigmoid:

    def test_sigmoid_of_zero_is_half(self):
        assert _sigmoid(0) == pytest.approx(0.5)

    def test_sigmoid_of_large_positive_approaches_one(self):
        assert _sigmoid(5.0) == pytest.approx(1.0, abs=0.01)

    def test_sigmoid_of_large_negative_approaches_zero(self):
        assert _sigmoid(-5.0) == pytest.approx(0.0, abs=0.01)

    def test_sigmoid_clips_extreme_inputs_without_overflow(self):
        assert 0.0 <= _sigmoid(100.0) <= 1.0
        assert 0.0 <= _sigmoid(-100.0) <= 1.0
        assert 0.0 <= _sigmoid(1e10) <= 1.0
        assert 0.0 <= _sigmoid(-1e10) <= 1.0


def _make_spy_hist(closes):
    index = pd.date_range('2024-01-01', periods=len(closes), freq='D')
    return pd.DataFrame({'Close': closes}, index=index)


class TestComputeLiveRegimeScore:

    def test_strong_bull_data_yields_score_above_065(self):
        closes = np.linspace(100, 150, 300)
        score = compute_live_regime_score(_make_spy_hist(closes))
        assert score > 0.65

    def test_bear_data_yields_score_below_035(self):
        rng = np.random.RandomState(666)
        base = np.linspace(150, 100, 300)
        noise = np.zeros(300)
        noise[-15:] = rng.normal(0, 3, 15)
        closes = np.maximum(base + noise, 1.0)
        score = compute_live_regime_score(_make_spy_hist(closes))
        assert score < 0.35

    def test_insufficient_history_returns_half(self):
        closes = np.linspace(100, 110, 200)
        score = compute_live_regime_score(_make_spy_hist(closes))
        assert score == pytest.approx(0.5)

    def test_sma200_zero_guard_returns_half(self):
        closes = np.zeros(300)
        score = compute_live_regime_score(_make_spy_hist(closes))
        assert score == pytest.approx(0.5)

    def test_trend_vol_composite_is_60_40_weighted(self):
        closes = np.linspace(100, 150, 300)
        score = compute_live_regime_score(_make_spy_hist(closes))
        # Smooth uptrend: trend_score ~0.8+, vol_score ~1.0 (near-zero vol)
        # composite = 0.60 * ~0.8 + 0.40 * ~1.0 => ~0.88
        assert 0.65 < score < 1.0


class TestRegimeScoreToPositions:

    def test_score_070_maps_to_5_positions(self):
        assert regime_score_to_positions(0.70) == 5

    def test_score_055_maps_to_4_positions(self):
        assert regime_score_to_positions(0.55) == 4

    def test_score_040_maps_to_3_positions(self):
        assert regime_score_to_positions(0.40) == 3

    def test_score_020_maps_to_2_positions(self):
        assert regime_score_to_positions(0.20) == 2

    def test_bull_override_adds_one_position(self):
        result = regime_score_to_positions(
            0.55, spy_close=103.5, sma200=100.0,
        )
        assert result == 5

    def test_bull_override_capped_at_num_positions(self):
        result = regime_score_to_positions(
            0.70, spy_close=103.5, sma200=100.0,
        )
        assert result == 5

    def test_bull_override_requires_score_strictly_above_040(self):
        result = regime_score_to_positions(
            0.40, spy_close=103.5, sma200=100.0,
        )
        assert result == 3
