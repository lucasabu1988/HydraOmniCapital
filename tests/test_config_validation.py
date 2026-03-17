"""
Config parameter validation tests for COMPASSLive._validate_config
"""

import pytest
import sys
import os
from copy import deepcopy
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from omnicapital_live import CONFIG


def _make_engine(config_overrides=None):
    """Build a COMPASSLive with mocked externals, applying config overrides."""
    from omnicapital_live import COMPASSLive
    cfg = deepcopy(CONFIG)
    if config_overrides:
        cfg.update(config_overrides)

    with patch('omnicapital_live.YahooDataFeed'), \
         patch('omnicapital_live.PaperBroker') as mock_broker, \
         patch('omnicapital_live.DataValidator'), \
         patch('omnicapital_live._hydra_available', False), \
         patch('omnicapital_live._ml_available', False), \
         patch('omnicapital_live._overlay_available', False):
        mock_broker.return_value.set_price_feed = MagicMock()
        engine = COMPASSLive(cfg)
    return engine


class TestConfigValidation:

    def test_valid_config_no_exception(self):
        _make_engine()

    def test_leverage_max_above_one_raises(self):
        with pytest.raises(ValueError, match="LEVERAGE_MAX"):
            _make_engine({'LEVERAGE_MAX': 1.5})

    def test_hold_days_zero_raises(self):
        with pytest.raises(ValueError, match="HOLD_DAYS"):
            _make_engine({'HOLD_DAYS': 0})

    def test_num_positions_too_high_raises(self):
        with pytest.raises(ValueError, match="NUM_POSITIONS"):
            _make_engine({'NUM_POSITIONS': 25})

    def test_num_positions_zero_raises(self):
        with pytest.raises(ValueError, match="NUM_POSITIONS"):
            _make_engine({'NUM_POSITIONS': 0})

    def test_stop_floor_too_negative_raises(self):
        with pytest.raises(ValueError, match="STOP_FLOOR"):
            _make_engine({'STOP_FLOOR': -0.25})

    def test_stop_floor_positive_raises(self):
        with pytest.raises(ValueError, match="STOP_FLOOR"):
            _make_engine({'STOP_FLOOR': 0.01})

    def test_stop_ceiling_below_limit_raises(self):
        with pytest.raises(ValueError, match="STOP_CEILING"):
            _make_engine({'STOP_CEILING': -0.35})

    def test_stop_ceiling_above_floor_raises(self):
        with pytest.raises(ValueError, match="STOP_CEILING"):
            _make_engine({'STOP_FLOOR': -0.10, 'STOP_CEILING': -0.05})

    def test_trailing_activation_zero_raises(self):
        with pytest.raises(ValueError, match="TRAILING_ACTIVATION"):
            _make_engine({'TRAILING_ACTIVATION': 0})

    def test_trailing_activation_negative_raises(self):
        with pytest.raises(ValueError, match="TRAILING_ACTIVATION"):
            _make_engine({'TRAILING_ACTIVATION': -0.01})

    def test_leverage_max_zero_raises(self):
        with pytest.raises(ValueError, match="LEVERAGE_MAX"):
            _make_engine({'LEVERAGE_MAX': 0})

    def test_hold_days_float_raises(self):
        with pytest.raises(ValueError, match="HOLD_DAYS"):
            _make_engine({'HOLD_DAYS': 5.5})
