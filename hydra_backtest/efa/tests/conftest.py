"""Shared fixtures for hydra_backtest.efa tests."""
import numpy as np
import pytest


@pytest.fixture(autouse=True)
def fixed_seed():
    """Force deterministic numpy RNG for every test."""
    np.random.seed(666)


@pytest.fixture
def efa_minimal_config():
    """Smallest valid EFA config — even simpler than Catalyst.

    No leverage, no DD scaling, no rebalance cadence, no position
    bounds (max is 1 by definition since the universe is 1 ticker).
    """
    return {
        'INITIAL_CAPITAL': 100_000,
        'COMMISSION_PER_SHARE': 0.0035,
    }
