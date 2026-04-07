"""Shared fixtures for hydra_backtest.catalyst tests."""
import numpy as np
import pytest


@pytest.fixture(autouse=True)
def fixed_seed():
    """Force deterministic numpy RNG for every test."""
    np.random.seed(666)


@pytest.fixture
def catalyst_minimal_config():
    """Smallest valid Catalyst config — even simpler than Rattlesnake.

    No leverage, no DD scaling, no position bounds (max is set by the
    universe size of CATALYST_TREND_ASSETS = 4).
    """
    return {
        'INITIAL_CAPITAL': 100_000,
        'COMMISSION_PER_SHARE': 0.0035,
    }
