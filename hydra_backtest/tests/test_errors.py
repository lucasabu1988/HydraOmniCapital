"""Tests for the hydra_backtest.errors exception hierarchy."""
from hydra_backtest.errors import (
    HydraBacktestError,
    HydraDataError,
    HydraBacktestValidationError,
    HydraBacktestLookaheadError,
)


def test_base_error_inherits_exception():
    assert issubclass(HydraBacktestError, Exception)


def test_data_error_inherits_base():
    assert issubclass(HydraDataError, HydraBacktestError)


def test_validation_error_inherits_base():
    assert issubclass(HydraBacktestValidationError, HydraBacktestError)


def test_lookahead_error_inherits_validation():
    assert issubclass(HydraBacktestLookaheadError, HydraBacktestValidationError)


def test_errors_carry_message():
    err = HydraDataError("missing ticker XYZ")
    assert "XYZ" in str(err)
