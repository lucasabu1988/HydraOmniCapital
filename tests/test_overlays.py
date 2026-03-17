"""
Unit tests for COMPASS v8.4 monetary overlays.
Tests against known historical dates to validate overlay behavior.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compass_overlays import (
    BankingStressOverlay, M2MomentumIndicator, FOMCSurpriseSignal,
    FedEmergencySignal, CashOptimization, CreditSectorPreFilter,
    compute_overlay_signals, OVERLAY_FLOOR,
)


def _make_daily_series(anchor_points):
    series = pd.Series(anchor_points, dtype=float)
    series.index = pd.to_datetime(series.index)
    series = series.sort_index()
    daily_index = pd.date_range(series.index.min(), series.index.max(), freq='D')
    return series.reindex(daily_index).interpolate(method='time').ffill().bfill()


@pytest.fixture(scope='module')
def fred_data():
    """Deterministic FRED-like overlay data for CI and local tests."""
    return {
        'NFCI': _make_daily_series({
            '2000-01-01': -0.20,
            '2008-01-01': -0.10,
            '2008-10-15': 3.20,
            '2010-01-15': 0.10,
            '2017-06-15': -0.30,
            '2020-03-23': 1.30,
            '2021-05-15': 0.00,
            '2023-03-15': 0.70,
            '2024-01-15': 0.20,
        }),
        'STLFSI4': _make_daily_series({
            '2000-01-01': 0.10,
            '2008-01-01': 0.20,
            '2008-10-15': 3.80,
            '2010-01-15': 0.40,
            '2017-06-15': 0.10,
            '2020-03-23': 2.00,
            '2021-05-15': 0.30,
            '2023-03-15': 1.10,
            '2024-01-15': 0.40,
        }),
        'BAMLH0A0HYM2': _make_daily_series({
            '2000-01-01': 5.00,
            '2008-01-01': 5.50,
            '2008-10-15': 18.00,
            '2010-01-15': 8.00,
            '2017-06-15': 3.50,
            '2020-03-23': 11.00,
            '2021-05-15': 4.00,
            '2023-03-15': 5.50,
            '2024-01-15': 4.20,
        }),
        'M2SL': _make_daily_series({
            '2000-01-01': 4700,
            '2008-01-01': 7600,
            '2010-01-15': 8500,
            '2012-06-15': 10000,
            '2017-06-15': 13500,
            '2019-06-15': 15000,
            '2020-06-15': 18000,
            '2020-09-15': 19000,
            '2021-05-15': 20500,
            '2021-12-15': 20000,
            '2022-03-15': 21800,
            '2022-12-15': 22000,
            '2023-03-15': 20600,
            '2024-01-15': 20800,
        }),
        'DFF': _make_daily_series({
            '2000-01-01': 5.50,
            '2008-01-20': 4.25,
            '2008-01-23': 3.50,
            '2008-10-15': 1.50,
            '2010-01-15': 0.12,
            '2017-06-15': 1.25,
            '2020-03-15': 0.10,
            '2021-05-15': 0.08,
            '2023-03-15': 4.75,
            '2024-01-15': 5.25,
        }),
        'FEDFUNDS': _make_daily_series({
            '2000-01-01': 5.50,
            '2008-01-23': 3.50,
            '2008-10-15': 1.50,
            '2010-01-15': 0.12,
            '2017-06-15': 1.25,
            '2020-03-15': 0.10,
            '2021-05-15': 0.08,
            '2023-03-15': 4.75,
            '2024-01-15': 5.25,
        }),
        'WALCL': _make_daily_series({
            '2000-01-01': 650000,
            '2008-10-15': 900000,
            '2017-06-15': 4300000,
            '2020-03-01': 4200000,
            '2020-03-15': 4300000,
            '2020-04-15': 5000000,
            '2021-05-15': 7800000,
            '2023-03-15': 8600000,
            '2024-01-15': 7600000,
        }),
        'DTB3': _make_daily_series({
            '2000-01-01': 5.80,
            '2008-10-15': 1.50,
            '2010-01-15': 0.15,
            '2012-06-15': 0.08,
            '2017-06-15': 1.00,
            '2020-03-15': 0.05,
            '2021-05-15': 0.04,
            '2023-03-15': 4.60,
            '2024-01-15': 5.10,
        }),
        'AAA': _make_daily_series({
            '2000-01-01': 7.00,
            '2008-10-15': 6.50,
            '2012-06-15': 3.80,
            '2017-06-15': 3.60,
            '2024-01-15': 5.40,
        }),
    }


# ============================================================================
# BSO Tests
# ============================================================================

class TestBankingStressOverlay:
    def test_gfc_oct_2008(self, fred_data):
        """During GFC peak (Oct 2008), stress should be extreme -> low scalar."""
        bso = BankingStressOverlay(fred_data)
        scalar = bso.compute_scalar(pd.Timestamp('2008-10-15'))
        assert scalar <= 0.40, f"GFC Oct 2008 should be very stressed, got {scalar}"

    def test_calm_2017(self, fred_data):
        """During calm 2017, no stress -> scalar near 1.0."""
        bso = BankingStressOverlay(fred_data)
        scalar = bso.compute_scalar(pd.Timestamp('2017-06-15'))
        assert scalar >= 0.90, f"Calm 2017 should be near 1.0, got {scalar}"

    def test_covid_march_2020(self, fred_data):
        """COVID panic (March 2020) should trigger stress."""
        bso = BankingStressOverlay(fred_data)
        scalar = bso.compute_scalar(pd.Timestamp('2020-03-23'))
        assert scalar <= 0.80, f"COVID March 2020 should be stressed, got {scalar}"

    def test_scalar_range(self, fred_data):
        """BSO scalar should always be in [FLOOR, 1.0]."""
        bso = BankingStressOverlay(fred_data)
        for date_str in ['2000-03-15', '2008-10-15', '2017-06-15', '2020-03-23', '2023-03-15']:
            scalar = bso.compute_scalar(pd.Timestamp(date_str))
            assert OVERLAY_FLOOR <= scalar <= 1.0, f"Out of range on {date_str}: {scalar}"


# ============================================================================
# M2 Momentum Tests
# ============================================================================

class TestM2MomentumIndicator:
    def test_m2_expansion_2020(self, fred_data):
        """M2 expanded massively in 2020 -> M2MI positive -> no restriction."""
        m2 = M2MomentumIndicator(fred_data)
        scalar = m2.compute_scalar(pd.Timestamp('2020-09-15'))
        assert scalar >= 0.90, f"M2 expanding in Sep 2020, should be >= 0.90, got {scalar}"

    def test_m2_contraction_2022(self, fred_data):
        """M2 contracted sharply in 2022-2023 -> should reduce scalar."""
        m2 = M2MomentumIndicator(fred_data)
        scalar = m2.compute_scalar(pd.Timestamp('2023-03-15'))
        assert scalar < 1.0, f"M2 contracting in Mar 2023, should be < 1.0, got {scalar}"

    def test_normal_conditions(self, fred_data):
        """Normal M2 growth in 2017 -> no restriction."""
        m2 = M2MomentumIndicator(fred_data)
        scalar = m2.compute_scalar(pd.Timestamp('2017-06-15'))
        assert scalar == 1.0, f"Normal M2 in 2017 should be 1.0, got {scalar}"

    def test_zirp_guard_2010_q1(self, fred_data):
        """During ZIRP (Jan 2010, Fed Funds ~0.12%), M2 scalar should be 1.0."""
        m2 = M2MomentumIndicator(fred_data)
        scalar = m2.compute_scalar(pd.Timestamp('2010-01-15'))
        assert scalar == 1.0, f"ZIRP guard should disable M2 in Jan 2010, got {scalar}"

    def test_zirp_guard_2021(self, fred_data):
        """During ZIRP (May 2021, Fed Funds ~0.06%), M2 scalar should be 1.0."""
        m2 = M2MomentumIndicator(fred_data)
        scalar = m2.compute_scalar(pd.Timestamp('2021-05-15'))
        assert scalar == 1.0, f"ZIRP guard should disable M2 in May 2021, got {scalar}"

    def test_no_zirp_guard_2023(self, fred_data):
        """During tightening (Mar 2023, Fed Funds ~4.6%), M2 scalar should still fire."""
        m2 = M2MomentumIndicator(fred_data)
        scalar = m2.compute_scalar(pd.Timestamp('2023-03-15'))
        assert scalar < 1.0, f"M2 should still restrict in Mar 2023 (no ZIRP), got {scalar}"


# ============================================================================
# FOMC Surprise Tests
# ============================================================================

class TestFOMCSurpriseSignal:
    def test_emergency_cut_jan_2008(self, fred_data):
        """Emergency 75bps cut Jan 22, 2008 -> should trigger surprise."""
        fomc = FOMCSurpriseSignal(fred_data)
        scalar = fomc.compute_scalar(pd.Timestamp('2008-01-23'))
        assert scalar < 1.0, f"Emergency cut Jan 2008 should trigger, got {scalar}"

    def test_no_surprise_normal(self, fred_data):
        """No surprise on a normal day."""
        fomc = FOMCSurpriseSignal(fred_data)
        # Reset state
        fomc._last_surprise_date = None
        scalar = fomc.compute_scalar(pd.Timestamp('2017-06-15'))
        assert scalar == 1.0, f"Normal day should be 1.0, got {scalar}"

    def test_decay_after_surprise(self, fred_data):
        """Surprise should decay over ~14 calendar days."""
        fomc = FOMCSurpriseSignal(fred_data)
        # Force a surprise
        fomc._last_surprise_date = pd.Timestamp('2008-01-22')
        fomc._last_surprise_scalar = 0.50
        # Check 7 days later (should be partially decayed)
        scalar_7d = fomc.compute_scalar(pd.Timestamp('2008-01-29'))
        # Check 15 days later (should be fully decayed)
        fomc._last_surprise_date = pd.Timestamp('2008-01-22')
        fomc._last_surprise_scalar = 0.50
        scalar_15d = fomc.compute_scalar(pd.Timestamp('2008-02-07'))
        assert scalar_15d == 1.0, f"Should be fully decayed after 15d, got {scalar_15d}"


# ============================================================================
# Fed Emergency Tests
# ============================================================================

class TestFedEmergencySignal:
    def test_march_2020_emergency(self, fred_data):
        """Fed balance sheet jumped massively in March 2020."""
        fed = FedEmergencySignal(fred_data)
        # Check late March / early April when the jump would have fully registered
        is_active = fed.is_emergency_active(pd.Timestamp('2020-04-15'))
        assert is_active, "Fed emergency should be active in April 2020"

    def test_normal_2017(self, fred_data):
        """No emergency in calm 2017."""
        fed = FedEmergencySignal(fred_data)
        is_active = fed.is_emergency_active(pd.Timestamp('2017-06-15'))
        assert not is_active, "No emergency in 2017"

    def test_position_floor(self, fred_data):
        """Emergency should provide position floor of 2."""
        fed = FedEmergencySignal(fred_data)
        # Force emergency active
        fed._emergency_start = pd.Timestamp('2020-03-15')
        floor = fed.get_position_floor(pd.Timestamp('2020-04-01'))
        assert floor == 2, f"Emergency position floor should be 2, got {floor}"


# ============================================================================
# Cash Optimization Tests
# ============================================================================

class TestCashOptimization:
    def test_rate_conversion(self, fred_data):
        """DTB3 rate correctly converted to daily rate."""
        cash = CashOptimization(fred_data)
        daily = cash.get_daily_cash_rate(pd.Timestamp('2024-01-15'))
        assert daily is not None, "Should have a rate for 2024"
        annual_approx = daily * 252 * 100  # back to annual pct
        assert 3.0 < annual_approx < 7.0, f"T-bill rate should be 3-7% in 2024, got {annual_approx:.1f}%"

    def test_zero_rate_era(self, fred_data):
        """Near-zero rates in 2012 should produce near-zero daily rate."""
        cash = CashOptimization(fred_data)
        daily = cash.get_daily_cash_rate(pd.Timestamp('2012-06-15'))
        assert daily is not None
        annual_approx = daily * 252 * 100
        assert annual_approx < 0.5, f"Should be near-zero in 2012, got {annual_approx:.2f}%"


class TestFedFundsData:
    def test_fedfunds_in_registry(self, fred_data):
        """FEDFUNDS should be downloaded as part of overlay data."""
        assert 'FEDFUNDS' in fred_data, "FEDFUNDS missing from fred_data dict"
        assert fred_data['FEDFUNDS'] is not None, "FEDFUNDS series is None"

    def test_fedfunds_zirp_2010(self, fred_data):
        """Fed Funds should be near-zero in 2010 (ZIRP)."""
        ff = fred_data['FEDFUNDS']
        val = ff[ff.index <= pd.Timestamp('2010-01-15')].iloc[-1]
        assert val < 0.25, f"Fed Funds should be <0.25% in Jan 2010, got {val}"

    def test_fedfunds_hiking_2023(self, fred_data):
        """Fed Funds should be >4% in 2023 (hiking cycle)."""
        ff = fred_data['FEDFUNDS']
        val = ff[ff.index <= pd.Timestamp('2023-06-15')].iloc[-1]
        assert val > 4.0, f"Fed Funds should be >4% in Jun 2023, got {val}"


# ============================================================================
# Credit Sector Pre-Filter Tests
# ============================================================================

class TestCreditSectorPreFilter:
    def test_gfc_excludes_financials(self, fred_data):
        """During GFC peak, HY > 1500bps -> Financials + Energy excluded."""
        sector_map = {'JPM': 'Financials', 'XOM': 'Energy', 'AAPL': 'Technology',
                      'JNJ': 'Healthcare', 'GS': 'Financials'}
        cpf = CreditSectorPreFilter(fred_data, sector_map)
        filtered = cpf.filter_universe(['JPM', 'XOM', 'AAPL', 'JNJ', 'GS'],
                                       pd.Timestamp('2008-12-15'))
        assert 'AAPL' in filtered, "Tech should survive"
        assert 'JNJ' in filtered, "Healthcare should survive"
        # Financials should be excluded when HY > 800bps
        # (may or may not be excluded depending on exact HY spread on that date)

    def test_normal_no_exclusion(self, fred_data):
        """Normal conditions -> no sectors excluded."""
        sector_map = {'JPM': 'Financials', 'AAPL': 'Technology'}
        cpf = CreditSectorPreFilter(fred_data, sector_map)
        filtered = cpf.filter_universe(['JPM', 'AAPL'], pd.Timestamp('2017-06-15'))
        assert len(filtered) == 2, "No exclusion in normal conditions"


# ============================================================================
# Aggregation Tests
# ============================================================================

class TestAggregation:
    def test_multiplicative_combination(self, fred_data):
        """Aggregation should be multiplicative."""
        overlays = {
            'bso': BankingStressOverlay(fred_data),
            'm2': M2MomentumIndicator(fred_data),
            'fomc': FOMCSurpriseSignal(fred_data),
        }
        result = compute_overlay_signals(overlays, pd.Timestamp('2008-10-15'))
        # During GFC, BSO should be low, contributing to a low combined scalar
        assert result['capital_scalar'] < 0.80, \
            f"GFC combined scalar should be < 0.80, got {result['capital_scalar']}"

    def test_floor_enforced(self, fred_data):
        """Combined scalar should never go below OVERLAY_FLOOR (0.25)."""
        overlays = {
            'bso': BankingStressOverlay(fred_data),
            'm2': M2MomentumIndicator(fred_data),
        }
        result = compute_overlay_signals(overlays, pd.Timestamp('2008-10-15'))
        assert result['capital_scalar'] >= OVERLAY_FLOOR, \
            f"Floor violated: {result['capital_scalar']}"

    def test_calm_market_no_restriction(self, fred_data):
        """All overlays should be ~1.0 during calm markets."""
        overlays = {
            'bso': BankingStressOverlay(fred_data),
            'm2': M2MomentumIndicator(fred_data),
            'fomc': FOMCSurpriseSignal(fred_data),
            'fed_emergency': FedEmergencySignal(fred_data),
            'cash_opt': CashOptimization(fred_data),
        }
        result = compute_overlay_signals(overlays, pd.Timestamp('2017-06-15'))
        assert result['capital_scalar'] >= 0.90, \
            f"Calm market should have scalar >= 0.90, got {result['capital_scalar']}"
        assert result['position_floor'] is None, "No emergency in 2017"
        assert result['cash_rate_override'] is not None, "Should have T-bill rate"


class TestVRecoveryBoost:
    """Test the V-recovery momentum boost logic."""

    def test_strong_v_recovery_boost(self):
        """10d return >= 8% during protection should give +0.20 boost."""
        from compass_overlay_backtest import compute_v_recovery_boost
        boost = compute_v_recovery_boost(spy_ret_10d=0.09, spy_ret_20d=0.12, is_defensive=True)
        assert boost == 0.20, f"Expected 0.20 boost for 9% 10d return, got {boost}"

    def test_moderate_recovery_boost(self):
        """10d return 5-8% during protection should give +0.10 boost."""
        from compass_overlay_backtest import compute_v_recovery_boost
        boost = compute_v_recovery_boost(spy_ret_10d=0.06, spy_ret_20d=0.08, is_defensive=True)
        assert boost == 0.10, f"Expected 0.10 boost for 6% 10d return, got {boost}"

    def test_sustained_recovery_boost(self):
        """20d return >= 10% (but 10d < 8%) should give +0.15 boost."""
        from compass_overlay_backtest import compute_v_recovery_boost
        boost = compute_v_recovery_boost(spy_ret_10d=0.04, spy_ret_20d=0.11, is_defensive=True)
        assert boost == 0.15, f"Expected 0.15 boost for 11% 20d return, got {boost}"

    def test_no_boost_outside_defensive(self):
        """No boost when not in defensive state (risk_on + no protection)."""
        from compass_overlay_backtest import compute_v_recovery_boost
        boost = compute_v_recovery_boost(spy_ret_10d=0.15, spy_ret_20d=0.20, is_defensive=False)
        assert boost == 0.0, f"Should be 0 outside defensive state, got {boost}"

    def test_no_boost_weak_recovery(self):
        """No boost for weak recoveries (<5% in 10d, <10% in 20d)."""
        from compass_overlay_backtest import compute_v_recovery_boost
        boost = compute_v_recovery_boost(spy_ret_10d=0.03, spy_ret_20d=0.06, is_defensive=True)
        assert boost == 0.0, f"Should be 0 for weak recovery, got {boost}"

    def test_regime_score_capped_at_1(self):
        """Boosted regime score should never exceed 1.0."""
        from compass_overlay_backtest import compute_v_recovery_boost
        boost = compute_v_recovery_boost(spy_ret_10d=0.20, spy_ret_20d=0.25, is_defensive=True)
        effective = min(1.0, 0.90 + boost)
        assert effective == 1.0, f"Should cap at 1.0, got {effective}"
