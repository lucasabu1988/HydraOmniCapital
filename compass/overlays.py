"""
COMPASS v8.4 — Monetary/Financial Overlay Logic
6 overlays that scale capital allocation based on macro indicators.
None of these modify the locked algorithm — they only produce scalars.

Threshold sources (NOT fitted to COMPASS data):
- NFCI: 0 is long-run mean by Chicago Fed normalization (above 0 = stress)
- HY OAS 500bps: ~75th percentile historically (Barclays/ICE data)
- M2MI -1.5pp: significant monetary deceleration (Werner, Keen)
- WALCL +5%/month: emergency facility threshold (2009, 2020 precedent)
- DFF 25bps/3d: non-scheduled rate move threshold
"""

import numpy as np
import pandas as pd
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Floor: never reduce below 25% of capital
OVERLAY_FLOOR = 0.25


def _get_latest(series: Optional[pd.Series], date: pd.Timestamp) -> Optional[float]:
    """Get the most recent observation on or before date."""
    if series is None or len(series) == 0:
        return None
    date_n = pd.Timestamp(date).normalize()
    prior = series[series.index <= date_n]
    if len(prior) == 0:
        return None
    return float(prior.iloc[-1])


# ============================================================================
# OVERLAY 1: Banking Stress Overlay (BSO)
# ============================================================================

class BankingStressOverlay:
    """Composite banking stress using NFCI + STLFSI + HY spread.

    Gradual scaling (no point thresholds) to avoid front-running.
    """

    def __init__(self, fred_data: dict):
        self.nfci = fred_data.get('NFCI')
        self.stlfsi = fred_data.get('STLFSI4')
        self.hy_oas = fred_data.get('BAMLH0A0HYM2')

    def compute_scalar(self, date: pd.Timestamp) -> float:
        nfci_val = _get_latest(self.nfci, date)
        stlfsi_val = _get_latest(self.stlfsi, date)
        hy_pct = _get_latest(self.hy_oas, date)

        # NFCI: 0 = normal, positive = tightening. Only act on genuine stress.
        # Mean=-0.35, P95=0.57. Start reducing at 0.5 (top 5% of readings).
        # Scale: <=0.5 -> 1.0, 1.5 -> 0.60, >=3.0 -> 0.25
        nfci_scalar = 1.0
        if nfci_val is not None and nfci_val > 0.5:
            nfci_scalar = max(OVERLAY_FLOOR, 1.0 - (nfci_val - 0.5) / 2.5 * 0.75)

        # STLFSI: 0 = normal, positive = stress. P90=0.94.
        # Start reducing at 1.0 (top ~9% of readings).
        # Scale: <=1.0 -> 1.0, 3.0 -> 0.25
        stlfsi_scalar = 1.0
        if stlfsi_val is not None and stlfsi_val > 1.0:
            stlfsi_scalar = max(OVERLAY_FLOOR, 1.0 - (stlfsi_val - 1.0) / 2.67 * 0.75)

        # HY OAS: FRED reports in pct (3.50 = 350bps). Convert to bps.
        # Median=456bps, P75=638bps, P90=820bps. Start at 700bps (~P85).
        # Scale: <=700bps -> 1.0, 1000bps -> 0.60, >=1500bps -> 0.25
        hy_scalar = 1.0
        if hy_pct is not None:
            hy_bps = hy_pct * 100
            if hy_bps > 700:
                hy_scalar = max(OVERLAY_FLOOR, 1.0 - (hy_bps - 700) / 1066.67 * 0.75)

        # Composite: weighted average
        composite = 0.40 * nfci_scalar + 0.25 * stlfsi_scalar + 0.35 * hy_scalar
        return float(np.clip(composite, OVERLAY_FLOOR, 1.0))

    def get_diagnostics(self, date: pd.Timestamp) -> dict:
        return {
            'nfci': _get_latest(self.nfci, date),
            'stlfsi': _get_latest(self.stlfsi, date),
            'hy_pct': _get_latest(self.hy_oas, date),
            'scalar': self.compute_scalar(date),
        }


# ============================================================================
# OVERLAY 2: M2 Momentum Indicator
# ============================================================================

class M2MomentumIndicator:
    """M2 money supply 3-month acceleration/deceleration.

    M2MI = [M2 YoY now] - [M2 YoY 3 months ago]
    Negative M2MI = monetary deceleration = headwind for momentum.
    """

    def __init__(self, fred_data: dict):
        self.m2 = fred_data.get('M2SL')

    def compute_scalar(self, date: pd.Timestamp) -> float:
        if self.m2 is None or len(self.m2) == 0:
            return 1.0

        date_n = pd.Timestamp(date).normalize()
        prior = self.m2[self.m2.index <= date_n]
        if len(prior) < 460:  # need ~15 months of daily data
            return 1.0

        idx = len(prior) - 1
        current_m2 = prior.iloc[idx]

        # YoY growth rate: now vs 365 days ago
        idx_12m = max(0, idx - 365)
        m2_12m_ago = prior.iloc[idx_12m]
        if m2_12m_ago <= 0:
            return 1.0
        yoy_now = (current_m2 / m2_12m_ago - 1.0) * 100  # percentage points

        # YoY growth rate: 3 months ago vs 15 months ago
        idx_3m = max(0, idx - 90)
        idx_15m = max(0, idx - 90 - 365)
        m2_3m = prior.iloc[idx_3m]
        m2_15m = prior.iloc[idx_15m]
        if m2_15m <= 0:
            return 1.0
        yoy_3m_ago = (m2_3m / m2_15m - 1.0) * 100

        m2mi = yoy_now - yoy_3m_ago  # 3-month change in YoY growth

        # M2MI thresholds (from monetary economics, not COMPASS data)
        if m2mi < -3.0:
            return 0.40
        elif m2mi < -1.5:
            # Linear: -1.5 -> 0.60, -3.0 -> 0.40
            return 0.60 + (m2mi + 3.0) / 1.5 * 0.20
        else:
            return 1.0

    def get_diagnostics(self, date: pd.Timestamp) -> dict:
        return {'scalar': self.compute_scalar(date)}


# ============================================================================
# OVERLAY 3: FOMC Surprise Signal
# ============================================================================

class FOMCSurpriseSignal:
    """Detects surprise Fed Funds rate moves and applies temporary caution.

    Uses DFF (effective fed funds rate) 3-day changes.
    Scalar decays linearly over 10 trading days back to 1.0.
    """

    def __init__(self, fred_data: dict):
        self.dff = fred_data.get('DFF')
        self._last_surprise_date = None
        self._last_surprise_scalar = 1.0

    def compute_scalar(self, date: pd.Timestamp) -> float:
        if self.dff is None or len(self.dff) == 0:
            return 1.0

        date_n = pd.Timestamp(date).normalize()
        prior = self.dff[self.dff.index <= date_n]
        if len(prior) < 10:
            return 1.0

        current_rate = prior.iloc[-1]
        rate_3d_ago = prior.iloc[max(0, len(prior) - 4)]  # 3 business days back

        surprise_bps = abs(current_rate - rate_3d_ago) * 100  # to bps

        # New surprise detected?
        if surprise_bps > 50:
            self._last_surprise_date = date_n
            self._last_surprise_scalar = 0.50
        elif surprise_bps > 25:
            self._last_surprise_date = date_n
            self._last_surprise_scalar = 0.75

        # Decay existing surprise over 10 trading days (~14 calendar days)
        if self._last_surprise_date is not None:
            days_since = (date_n - self._last_surprise_date).days
            if days_since > 14:
                self._last_surprise_date = None
                return 1.0
            # Linear decay: scalar at day 0, 1.0 at day 14
            fraction_remaining = max(0.0, 1.0 - days_since / 14.0)
            return 1.0 - fraction_remaining * (1.0 - self._last_surprise_scalar)

        return 1.0

    def get_diagnostics(self, date: pd.Timestamp) -> dict:
        return {
            'scalar': self.compute_scalar(date),
            'surprise_active': self._last_surprise_date is not None,
        }


# ============================================================================
# OVERLAY 4: Fed Emergency Signal
# ============================================================================

class FedEmergencySignal:
    """Detects emergency Fed balance sheet expansion (QE, BTFP, etc.).

    When WALCL jumps >5% in 30 days, marks a regime floor (not a capital scalar).
    The emergency floor stays active for 90 calendar days.
    """

    JUMP_THRESHOLD = 0.05   # 5% in 30 days
    ACTIVE_DAYS = 90        # calendar days

    def __init__(self, fred_data: dict):
        self.walcl = fred_data.get('WALCL')
        self._emergency_start = None

    def is_emergency_active(self, date: pd.Timestamp) -> bool:
        """Returns True if an emergency intervention is currently active."""
        if self.walcl is None or len(self.walcl) == 0:
            return False

        date_n = pd.Timestamp(date).normalize()
        prior = self.walcl[self.walcl.index <= date_n]
        if len(prior) < 35:
            return False

        current = prior.iloc[-1]
        val_30d_ago = prior.iloc[max(0, len(prior) - 31)]

        if val_30d_ago > 0:
            pct_change = (current / val_30d_ago) - 1.0
            if pct_change > self.JUMP_THRESHOLD:
                self._emergency_start = date_n

        # Check if still within active window
        if self._emergency_start is not None:
            days_since = (date_n - self._emergency_start).days
            if days_since <= self.ACTIVE_DAYS:
                return True
            else:
                self._emergency_start = None

        return False

    def get_position_floor(self, date: pd.Timestamp) -> Optional[int]:
        """Returns minimum position count during emergency, or None."""
        if self.is_emergency_active(date):
            return 2  # maintain at least 2 positions
        return None

    def get_diagnostics(self, date: pd.Timestamp) -> dict:
        return {
            'emergency_active': self.is_emergency_active(date),
            'position_floor': self.get_position_floor(date),
        }


# ============================================================================
# OVERLAY 5: Cash Optimization
# ============================================================================

class CashOptimization:
    """Replaces Moody's Aaa yield with T-bill rate for idle cash.

    Uses DTB3 (3-month T-bill) which is a more appropriate risk-free rate.
    """

    def __init__(self, fred_data: dict):
        self.dtb3 = fred_data.get('DTB3')

    def get_daily_cash_rate(self, date: pd.Timestamp) -> Optional[float]:
        """Returns daily cash rate (annual rate / 252)."""
        rate_pct = _get_latest(self.dtb3, date)
        if rate_pct is None:
            return None
        return rate_pct / 100.0 / 252  # FRED DTB3 is in percent, annualized

    def get_diagnostics(self, date: pd.Timestamp) -> dict:
        rate = _get_latest(self.dtb3, date)
        return {
            'dtb3_pct': rate,
            'daily_rate': self.get_daily_cash_rate(date),
        }


# ============================================================================
# OVERLAY 6: Credit Sector Pre-Filter
# ============================================================================

class CreditSectorPreFilter:
    """Excludes high-credit-risk sectors when HY spread is at crisis levels.

    HY > 1000bps: exclude Financials (~P95, true crisis only)
    HY > 1500bps: exclude Financials + Energy (GFC-level stress)
    """

    def __init__(self, fred_data: dict, sector_map: Optional[dict] = None):
        self.hy_oas = fred_data.get('BAMLH0A0HYM2')
        self.sector_map = sector_map or {}

    def filter_universe(self, symbols: list, date: pd.Timestamp) -> list:
        """Remove symbols from excluded sectors."""
        hy_pct = _get_latest(self.hy_oas, date)
        if hy_pct is None:
            return symbols

        hy_bps = hy_pct * 100  # convert to bps

        excluded_sectors = set()
        if hy_bps > 1500:
            excluded_sectors = {'Financials', 'Energy'}
        elif hy_bps > 1000:
            excluded_sectors = {'Financials'}

        if not excluded_sectors:
            return symbols

        return [s for s in symbols
                if self.sector_map.get(s, 'Unknown') not in excluded_sectors]

    def get_diagnostics(self, date: pd.Timestamp) -> dict:
        hy_pct = _get_latest(self.hy_oas, date)
        return {
            'hy_bps': hy_pct * 100 if hy_pct else None,
            'excluded': self._get_excluded(date),
        }

    def _get_excluded(self, date):
        hy_pct = _get_latest(self.hy_oas, date)
        if hy_pct is None:
            return []
        hy_bps = hy_pct * 100
        if hy_bps > 1500:
            return ['Financials', 'Energy']
        elif hy_bps > 1000:
            return ['Financials']
        return []


# ============================================================================
# AGGREGATION
# ============================================================================

def compute_overlay_signals(overlays: dict, date: pd.Timestamp,
                            credit_prefilter: Optional[CreditSectorPreFilter] = None
                            ) -> dict:
    """Compute all overlay signals for a given date.

    Returns:
        {
            'capital_scalar': float [0.25, 1.0],
            'position_floor': int or None,
            'cash_rate_override': float or None,
            'diagnostics': {overlay_name: {...}},
        }
    """
    capital_scalars = {}
    diagnostics = {}
    position_floor = None
    cash_rate = None

    for name, overlay in overlays.items():
        if isinstance(overlay, CashOptimization):
            cash_rate = overlay.get_daily_cash_rate(date)
            diagnostics[name] = overlay.get_diagnostics(date)
            continue

        if isinstance(overlay, FedEmergencySignal):
            position_floor = overlay.get_position_floor(date)
            diagnostics[name] = overlay.get_diagnostics(date)
            continue

        # All other overlays produce capital scalars
        scalar = overlay.compute_scalar(date)
        capital_scalars[name] = scalar
        diagnostics[name] = overlay.get_diagnostics(date)

    # Multiplicative aggregation with floor
    combined = 1.0
    for s in capital_scalars.values():
        combined *= s
    combined = max(OVERLAY_FLOOR, min(1.0, combined))

    return {
        'capital_scalar': combined,
        'position_floor': position_floor,
        'cash_rate_override': cash_rate,
        'per_overlay_scalars': capital_scalars,
        'diagnostics': diagnostics,
    }
