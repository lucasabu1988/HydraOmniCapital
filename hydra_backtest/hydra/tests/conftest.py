"""Shared fixtures for hydra_backtest.hydra tests."""
import numpy as np
import pytest


@pytest.fixture(autouse=True)
def fixed_seed():
    """Force deterministic numpy RNG for every test."""
    np.random.seed(666)


@pytest.fixture
def hydra_minimal_config():
    """Smallest valid HYDRA config — superset of the four pillar configs.

    Used by engine tests that need to call apply_*_wrapper functions
    or run_hydra_backtest end-to-end on synthetic data.
    """
    return {
        # Capital
        'INITIAL_CAPITAL': 100_000,
        'COMMISSION_PER_SHARE': 0.0035,
        # COMPASS
        'NUM_POSITIONS': 5,
        'NUM_POSITIONS_RISK_OFF': 2,
        'MOMENTUM_LOOKBACK': 90,
        'MOMENTUM_SKIP': 5,
        'HOLD_DAYS': 5,
        'MIN_AGE_DAYS': 220,
        'MIN_MOMENTUM_STOCKS': 5,
        'QUALITY_VOL_MAX': 0.55,
        'QUALITY_VOL_LOOKBACK': 60,
        'QUALITY_MAX_SINGLE_DAY': 0.18,
        'MAX_PER_SECTOR': 3,
        'POSITION_STOP_PCT': -0.06,
        'TRAILING_STOP_ACTIVATE': 0.05,
        'TRAILING_STOP_DROP': 0.03,
        'PORTFOLIO_STOP_PCT': -0.15,
        'CRASH_BRAKE_5D': -0.06,
        'CRASH_BRAKE_10D': -0.10,
        'CRASH_LEVERAGE': 0.15,
        'LEVERAGE_MAX': 1.0,
        'LEVERAGE_MIN': 0.3,
        'VOL_TARGET': 0.15,
        'MARGIN_RATE': 0.06,
        # HYDRA-specific
        'BASE_COMPASS_ALLOC': 0.425,
        'BASE_RATTLE_ALLOC': 0.425,
        'BASE_CATALYST_ALLOC': 0.15,
        'MAX_COMPASS_ALLOC': 0.75,
        'EFA_LIQUIDATION_CASH_THRESHOLD_PCT': 0.20,
    }
