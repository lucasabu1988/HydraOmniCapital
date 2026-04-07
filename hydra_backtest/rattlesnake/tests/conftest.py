"""Shared fixtures for hydra_backtest.rattlesnake tests."""
import numpy as np
import pytest


@pytest.fixture(autouse=True)
def fixed_seed():
    """Force deterministic numpy RNG for every test."""
    np.random.seed(666)


@pytest.fixture
def rattlesnake_minimal_config():
    """Smallest valid Rattlesnake config — subset of COMPASS config schema.

    Excludes COMPASS-only keys (CRASH_LEVERAGE, LEV_FLOOR, etc.) since
    Rattlesnake uses no leverage and no DD scaling.
    """
    return {
        # Capital
        'INITIAL_CAPITAL': 100_000,
        # Trade costs
        'COMMISSION_PER_SHARE': 0.0035,
        # Position bounds
        'NUM_POSITIONS': 5,            # = R_MAX_POSITIONS
        'NUM_POSITIONS_RISK_OFF': 2,   # = R_MAX_POS_RISK_OFF
        # Universe age requirement (ensures stocks have enough history for SMA200)
        'MIN_AGE_DAYS': 220,           # > R_TREND_SMA (200) so SMA200 is computable
    }
