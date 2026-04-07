"""Shared fixtures for hydra_backtest tests."""
import numpy as np
import pytest


@pytest.fixture(autouse=True)
def fixed_seed():
    """Force deterministic numpy RNG for every test."""
    np.random.seed(666)


@pytest.fixture
def minimal_config():
    """Smallest valid COMPASS config — matches live CONFIG schema."""
    return {
        'MOMENTUM_LOOKBACK': 90,
        'MOMENTUM_SKIP': 5,
        'MIN_MOMENTUM_STOCKS': 20,
        'NUM_POSITIONS': 5,
        'NUM_POSITIONS_RISK_OFF': 2,
        'HOLD_DAYS': 5,
        'HOLD_DAYS_MAX': 10,
        'RENEWAL_PROFIT_MIN': 0.04,
        'MOMENTUM_RENEWAL_THRESHOLD': 0.85,
        'POSITION_STOP_LOSS': -0.08,
        'TRAILING_ACTIVATION': 0.05,
        'TRAILING_STOP_PCT': 0.03,
        'STOP_DAILY_VOL_MULT': 2.5,
        'STOP_FLOOR': -0.06,
        'STOP_CEILING': -0.15,
        'TRAILING_VOL_BASELINE': 0.25,
        'BULL_OVERRIDE_THRESHOLD': 0.03,
        'BULL_OVERRIDE_MIN_SCORE': 0.40,
        'MAX_PER_SECTOR': 3,
        'DD_SCALE_TIER1': -0.10,
        'DD_SCALE_TIER2': -0.20,
        'DD_SCALE_TIER3': -0.35,
        'LEV_FULL': 1.0,
        'LEV_MID': 0.60,
        'LEV_FLOOR': 0.30,
        'CRASH_VEL_5D': -0.06,
        'CRASH_VEL_10D': -0.10,
        'CRASH_LEVERAGE': 0.15,
        'CRASH_COOLDOWN': 10,
        'QUALITY_VOL_MAX': 0.60,
        'QUALITY_VOL_LOOKBACK': 63,
        'QUALITY_MAX_SINGLE_DAY': 0.50,
        'TARGET_VOL': 0.15,
        'LEVERAGE_MAX': 1.0,
        'VOL_LOOKBACK': 20,
        'TOP_N': 40,
        'MIN_AGE_DAYS': 63,
        'INITIAL_CAPITAL': 100_000,
        'MARGIN_RATE': 0.06,
        'COMMISSION_PER_SHARE': 0.001,
    }
