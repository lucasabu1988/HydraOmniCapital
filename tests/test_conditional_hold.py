"""
Unit tests for conditional hold period by regime.
Tests the get_hold_days_for_regime() helper function.
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_conditional_hold_backtest import get_hold_days_for_regime

DEFAULT_CONFIG = {'bull': 7, 'mild_bull': 5, 'mild_bear': 4, 'bear': 3}


class TestGetHoldDaysForRegime:

    def test_bull_regime(self):
        assert get_hold_days_for_regime(0.70, DEFAULT_CONFIG) == 7

    def test_mild_bull_regime(self):
        assert get_hold_days_for_regime(0.55, DEFAULT_CONFIG) == 5

    def test_mild_bear_regime(self):
        assert get_hold_days_for_regime(0.40, DEFAULT_CONFIG) == 4

    def test_bear_regime(self):
        assert get_hold_days_for_regime(0.20, DEFAULT_CONFIG) == 3

    def test_boundary_065(self):
        """0.65 is exactly bull threshold."""
        assert get_hold_days_for_regime(0.65, DEFAULT_CONFIG) == 7

    def test_boundary_below_065(self):
        assert get_hold_days_for_regime(0.6499, DEFAULT_CONFIG) == 5

    def test_boundary_050(self):
        assert get_hold_days_for_regime(0.50, DEFAULT_CONFIG) == 5

    def test_boundary_below_050(self):
        assert get_hold_days_for_regime(0.4999, DEFAULT_CONFIG) == 4

    def test_boundary_035(self):
        assert get_hold_days_for_regime(0.35, DEFAULT_CONFIG) == 4

    def test_boundary_below_035(self):
        assert get_hold_days_for_regime(0.3499, DEFAULT_CONFIG) == 3

    def test_extreme_zero(self):
        assert get_hold_days_for_regime(0.0, DEFAULT_CONFIG) == 3

    def test_extreme_one(self):
        assert get_hold_days_for_regime(1.0, DEFAULT_CONFIG) == 7

    def test_clamped_to_max(self):
        """Hold days should never exceed max_hold (default 10)."""
        big_config = {'bull': 15, 'mild_bull': 5, 'mild_bear': 4, 'bear': 3}
        assert get_hold_days_for_regime(0.70, big_config, max_hold=10) == 10

    def test_clamped_to_min(self):
        """Hold days should never go below 1."""
        tiny_config = {'bull': 7, 'mild_bull': 5, 'mild_bear': 4, 'bear': 0}
        assert get_hold_days_for_regime(0.20, tiny_config) == 1

    def test_default_fallback(self):
        """Missing key in config uses default=5."""
        incomplete = {'bull': 7}
        assert get_hold_days_for_regime(0.20, incomplete) == 5  # 'bear' missing

    def test_custom_config(self):
        custom = {'bull': 8, 'mild_bull': 6, 'mild_bear': 4, 'bear': 2}
        assert get_hold_days_for_regime(0.70, custom) == 8
        assert get_hold_days_for_regime(0.55, custom) == 6
        assert get_hold_days_for_regime(0.40, custom) == 4
        assert get_hold_days_for_regime(0.20, custom) == 2

    def test_fixed_5d_config(self):
        """A config where all regimes use 5 should behave like fixed hold."""
        fixed = {'bull': 5, 'mild_bull': 5, 'mild_bear': 5, 'bear': 5}
        for score in [0.10, 0.35, 0.50, 0.65, 0.90]:
            assert get_hold_days_for_regime(score, fixed) == 5

    def test_monotonicity_preserved(self):
        """Bull hold >= mild_bull >= mild_bear >= bear in all valid configs."""
        for score, expected in [(0.70, 7), (0.55, 5), (0.40, 4), (0.20, 3)]:
            assert get_hold_days_for_regime(score, DEFAULT_CONFIG) == expected
        # Verify monotonicity
        vals = [
            get_hold_days_for_regime(0.70, DEFAULT_CONFIG),
            get_hold_days_for_regime(0.55, DEFAULT_CONFIG),
            get_hold_days_for_regime(0.40, DEFAULT_CONFIG),
            get_hold_days_for_regime(0.20, DEFAULT_CONFIG),
        ]
        assert vals == sorted(vals, reverse=True)
