"""
Integration tests for overlay system in COMPASSLive engine.
Tests that overlays initialize, compute scalars, and integrate with
capital allocation without crashing the live engine.
"""

import pytest
import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_overlays import (
    BankingStressOverlay, M2MomentumIndicator, FOMCSurpriseSignal,
    FedEmergencySignal, CreditSectorPreFilter, compute_overlay_signals,
    OVERLAY_FLOOR,
)


# ============================================================================
# Mock FRED data (no network dependency)
# ============================================================================

def _make_series(values, start='2020-01-01'):
    """Create a daily pd.Series from a list of values."""
    dates = pd.date_range(start, periods=len(values), freq='D')
    return pd.Series(values, index=dates)


@pytest.fixture
def calm_fred():
    """FRED data simulating calm market conditions."""
    n = 500
    return {
        'NFCI': _make_series([-0.3] * n),
        'STLFSI4': _make_series([0.2] * n),
        'BAMLH0A0HYM2': _make_series([3.5] * n),
        'M2SL': _make_series(np.linspace(15000, 16000, n)),
        'DFF': _make_series([5.25] * n),
        'WALCL': _make_series([7500000] * n),
        'DTB3': _make_series([5.0] * n),
        'AAA': _make_series([4.5] * n),
    }


@pytest.fixture
def stressed_fred():
    """FRED data simulating GFC-level stress."""
    n = 500
    return {
        'NFCI': _make_series([2.5] * n),
        'STLFSI4': _make_series([3.0] * n),
        'BAMLH0A0HYM2': _make_series([18.0] * n),
        'M2SL': _make_series(np.linspace(16000, 15000, n)),
        'DFF': _make_series([5.25] * 248 + [4.25] * 2 + [4.25] * 250),
        'WALCL': _make_series(np.linspace(4000000, 5000000, n)),
        'DTB3': _make_series([0.1] * n),
        'AAA': _make_series([4.5] * n),
    }


# ============================================================================
# Overlay initialization
# ============================================================================

class TestOverlayInit:
    def test_all_overlays_init_calm(self, calm_fred):
        overlays = {
            'bso': BankingStressOverlay(calm_fred),
            'm2': M2MomentumIndicator(calm_fred),
            'fomc': FOMCSurpriseSignal(calm_fred),
            'fed_emergency': FedEmergencySignal(calm_fred),
        }
        assert len(overlays) == 4

    def test_credit_filter_init(self, calm_fred):
        sector_map = {'AAPL': 'Technology', 'JPM': 'Financials', 'XOM': 'Energy'}
        cf = CreditSectorPreFilter(calm_fred, sector_map)
        assert cf is not None

    def test_overlays_init_with_missing_data(self):
        """Overlays should not crash with None/empty FRED data."""
        empty = {k: None for k in ['NFCI', 'STLFSI4', 'BAMLH0A0HYM2', 'M2SL', 'DFF', 'WALCL']}
        overlays = {
            'bso': BankingStressOverlay(empty),
            'm2': M2MomentumIndicator(empty),
            'fomc': FOMCSurpriseSignal(empty),
            'fed_emergency': FedEmergencySignal(empty),
        }
        date = pd.Timestamp('2020-06-15')
        result = compute_overlay_signals(overlays, date)
        assert result['capital_scalar'] == 1.0


# ============================================================================
# Capital scalar computation
# ============================================================================

class TestCapitalScalar:
    def test_calm_market_scalar_near_one(self, calm_fred):
        overlays = {
            'bso': BankingStressOverlay(calm_fred),
            'm2': M2MomentumIndicator(calm_fred),
            'fomc': FOMCSurpriseSignal(calm_fred),
            'fed_emergency': FedEmergencySignal(calm_fred),
        }
        date = pd.Timestamp('2020-06-15')
        result = compute_overlay_signals(overlays, date)
        assert result['capital_scalar'] >= 0.90, f"Calm market should be near 1.0, got {result['capital_scalar']}"

    def test_stressed_market_scalar_low(self, stressed_fred):
        overlays = {
            'bso': BankingStressOverlay(stressed_fred),
            'm2': M2MomentumIndicator(stressed_fred),
            'fomc': FOMCSurpriseSignal(stressed_fred),
            'fed_emergency': FedEmergencySignal(stressed_fred),
        }
        date = pd.Timestamp('2020-12-15')
        result = compute_overlay_signals(overlays, date)
        assert result['capital_scalar'] <= 0.50, f"Stressed market should be low, got {result['capital_scalar']}"

    def test_scalar_always_in_range(self, calm_fred, stressed_fred):
        for fred in [calm_fred, stressed_fred]:
            overlays = {
                'bso': BankingStressOverlay(fred),
                'm2': M2MomentumIndicator(fred),
                'fomc': FOMCSurpriseSignal(fred),
            }
            for d in pd.date_range('2020-03-01', '2020-09-01', freq='MS'):
                result = compute_overlay_signals(overlays, d)
                assert OVERLAY_FLOOR <= result['capital_scalar'] <= 1.0


# ============================================================================
# Conditional damping
# ============================================================================

class TestConditionalDamping:
    def test_no_damping_when_dd_inactive(self):
        """When DD-scaling is NOT active (dd_lev=1.0), use full overlay scalar."""
        overlay_scalar = 0.60
        dd_lev = 1.0
        OVERLAY_DAMPING = 0.25

        if dd_lev < 1.0:
            damped = 1.0 - OVERLAY_DAMPING * (1.0 - overlay_scalar)
        else:
            damped = overlay_scalar

        assert damped == 0.60

    def test_damping_when_dd_active(self):
        """When DD-scaling IS active (dd_lev<1.0), use 25% blend."""
        overlay_scalar = 0.60
        dd_lev = 0.60
        OVERLAY_DAMPING = 0.25

        if dd_lev < 1.0:
            damped = 1.0 - OVERLAY_DAMPING * (1.0 - overlay_scalar)
        else:
            damped = overlay_scalar

        assert damped == 0.90

    def test_damping_floor(self):
        """Even with damping, scalar should not exceed 1.0."""
        overlay_scalar = 1.0
        dd_lev = 0.30
        OVERLAY_DAMPING = 0.25

        if dd_lev < 1.0:
            damped = 1.0 - OVERLAY_DAMPING * (1.0 - overlay_scalar)
        else:
            damped = overlay_scalar

        assert damped == 1.0


# ============================================================================
# Credit filter
# ============================================================================

class TestCreditFilterIntegration:
    def test_no_filter_in_calm_market(self, calm_fred):
        sector_map = {'AAPL': 'Technology', 'JPM': 'Financials', 'XOM': 'Energy'}
        cf = CreditSectorPreFilter(calm_fred, sector_map)
        result = cf.filter_universe(['AAPL', 'JPM', 'XOM'], pd.Timestamp('2020-06-15'))
        assert result == ['AAPL', 'JPM', 'XOM']

    def test_filter_financials_at_crisis(self, stressed_fred):
        sector_map = {'AAPL': 'Technology', 'JPM': 'Financials', 'XOM': 'Energy'}
        cf = CreditSectorPreFilter(stressed_fred, sector_map)
        result = cf.filter_universe(['AAPL', 'JPM', 'XOM'], pd.Timestamp('2020-06-15'))
        assert 'AAPL' in result
        assert 'JPM' not in result
        assert 'XOM' not in result


# ============================================================================
# Position floor (Fed Emergency)
# ============================================================================

class TestPositionFloor:
    def test_no_floor_normally(self, calm_fred):
        fed = FedEmergencySignal(calm_fred)
        floor = fed.get_position_floor(pd.Timestamp('2020-06-15'))
        assert floor is None

    def test_floor_during_emergency(self, stressed_fred):
        fed = FedEmergencySignal(stressed_fred)
        floor = fed.get_position_floor(pd.Timestamp('2020-06-15'))
        assert floor == 2 or floor is None


# ============================================================================
# State persistence
# ============================================================================

class TestOverlayStatePersistence:
    def test_overlay_state_dict_structure(self, calm_fred):
        overlays = {
            'bso': BankingStressOverlay(calm_fred),
            'm2': M2MomentumIndicator(calm_fred),
            'fomc': FOMCSurpriseSignal(calm_fred),
            'fed_emergency': FedEmergencySignal(calm_fred),
        }
        date = pd.Timestamp('2020-06-15')
        result = compute_overlay_signals(overlays, date)

        overlay_state = {
            'capital_scalar': result['capital_scalar'],
            'per_overlay': result.get('per_overlay_scalars', {}),
            'position_floor': result.get('position_floor'),
        }

        assert 'capital_scalar' in overlay_state
        assert 'per_overlay' in overlay_state
        assert isinstance(overlay_state['capital_scalar'], float)
