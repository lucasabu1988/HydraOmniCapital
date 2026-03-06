"""
HYDRA Capital Manager — Cash Recycling Between Strategies
==========================================================
Manages segregated accounts for COMPASS, Rattlesnake, and EFA (third pillar)
with dynamic cash recycling. When one strategy has idle cash, it
flows to the other (capped at 75% max to COMPASS). Remaining idle cash
after recycling can be parked in EFA for passive international-equity exposure.

Used by omnicapital_live.py for live capital allocation decisions.
"""

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ============================================================================
# PARAMETERS
# ============================================================================
BASE_COMPASS_ALLOC = 0.50
BASE_RATTLE_ALLOC = 0.50
MAX_COMPASS_ALLOC = 0.75  # Cap: max COMPASS can receive with recycling
EFA_MIN_BUY = 1000        # Minimum idle cash to trigger EFA buy


class HydraCapitalManager:
    """
    Manages capital allocation between COMPASS, Rattlesnake, and EFA.

    Architecture:
    - Each strategy has a logical account (not a separate brokerage account)
    - Cash recycling transfers idle R cash to C's budget
    - Remaining idle cash after recycling can be allocated to EFA (third pillar)
    - Position sizing for each strategy uses its allocated budget
    """

    def __init__(self, total_capital: float,
                 compass_alloc: float = BASE_COMPASS_ALLOC,
                 rattle_alloc: float = BASE_RATTLE_ALLOC,
                 max_compass_alloc: float = MAX_COMPASS_ALLOC):
        self.base_compass_alloc = compass_alloc
        self.base_rattle_alloc = rattle_alloc
        self.max_compass_alloc = max_compass_alloc

        # Logical accounts
        self.compass_account = total_capital * compass_alloc
        self.rattle_account = total_capital * rattle_alloc

        # EFA (third pillar)
        self.efa_value = 0.0

        # Tracking
        self.current_recycled = 0.0
        self.total_recycled_days = 0
        self.total_days = 0

    @property
    def total_capital(self) -> float:
        return self.compass_account + self.rattle_account + self.efa_value

    def compute_allocation(self, rattle_exposure: float) -> Dict[str, float]:
        """
        Compute dynamic allocation based on Rattlesnake's current exposure.

        Args:
            rattle_exposure: Fraction of Rattlesnake account currently invested (0-1)

        Returns:
            Dict with compass_budget, rattle_budget, recycled_amount, effective_allocs
        """
        total = self.total_capital

        # How much of Rattlesnake's account is idle?
        r_idle = self.rattle_account * (1.0 - rattle_exposure)

        # Max we can lend to COMPASS
        max_c = total * self.max_compass_alloc - self.compass_account
        max_c = max(0, max_c)

        recycle_amount = min(r_idle, max_c)

        c_effective = self.compass_account + recycle_amount
        r_effective = self.rattle_account - recycle_amount

        self.current_recycled = recycle_amount
        self.total_days += 1
        if recycle_amount > 0:
            self.total_recycled_days += 1

        # Remaining idle cash after recycling (available for EFA)
        r_still_idle = r_effective * (1.0 - rattle_exposure)
        efa_idle = r_still_idle + self.efa_value  # include current EFA value as available

        return {
            'compass_budget': c_effective,
            'rattle_budget': r_effective,
            'recycled_amount': recycle_amount,
            'recycled_pct': recycle_amount / total if total > 0 else 0,
            'compass_alloc': c_effective / total if total > 0 else 0.5,
            'rattle_alloc': r_effective / total if total > 0 else 0.5,
            'efa_idle': efa_idle,
        }

    def update_accounts_after_day(self, compass_return: float, rattle_return: float,
                                   rattle_exposure: float):
        """
        Update logical accounts after a trading day.
        Recycled cash earns COMPASS returns.

        Args:
            compass_return: COMPASS daily return (e.g., 0.005 for +0.5%)
            rattle_return: Rattlesnake daily return
            rattle_exposure: Rattlesnake exposure fraction
        """
        alloc = self.compute_allocation(rattle_exposure)
        recycled = alloc['recycled_amount']

        # Apply returns
        c_effective = alloc['compass_budget']
        r_effective = alloc['rattle_budget']

        c_new = c_effective * (1 + compass_return)
        r_new = r_effective * (1 + rattle_return)

        # Settle recycled amount (it earned COMPASS returns)
        recycled_after = recycled * (1 + compass_return)
        self.compass_account = c_new - recycled_after
        self.rattle_account = r_new + recycled_after

    def buy_efa(self, amount: float):
        """Move idle cash into EFA allocation."""
        self.rattle_account -= amount
        self.efa_value += amount
        logger.info(f"EFA: bought ${amount:,.0f} (total EFA: ${self.efa_value:,.0f})")

    def sell_efa(self, amount: float = None) -> float:
        """Liquidate EFA (partially or fully) to free capital. Returns amount freed."""
        if self.efa_value <= 0:
            return 0.0
        sell = min(amount, self.efa_value) if amount else self.efa_value
        self.efa_value -= sell
        self.rattle_account += sell
        logger.info(f"EFA: sold ${sell:,.0f} (remaining EFA: ${self.efa_value:,.0f})")
        return sell

    def update_efa_value(self, efa_return: float):
        """Apply EFA daily return to the EFA allocation."""
        if self.efa_value > 0 and efa_return != 0:
            self.efa_value *= (1 + efa_return)

    def record_compass_trade(self, pnl: float):
        """Record a COMPASS trade P&L to its account."""
        self.compass_account += pnl

    def record_rattle_trade(self, pnl: float):
        """Record a Rattlesnake trade P&L to its account."""
        self.rattle_account += pnl

    def get_status(self) -> Dict:
        """Get current status for logging/dashboard."""
        total = self.total_capital
        return {
            'total_capital': total,
            'compass_account': self.compass_account,
            'rattle_account': self.rattle_account,
            'compass_pct': self.compass_account / total if total > 0 else 0,
            'rattle_pct': self.rattle_account / total if total > 0 else 0,
            'current_recycled': self.current_recycled,
            'recycled_pct': self.current_recycled / total if total > 0 else 0,
            'recycling_frequency': self.total_recycled_days / max(self.total_days, 1),
            'efa_value': self.efa_value,
            'efa_pct': self.efa_value / total if total > 0 else 0,
        }

    def to_dict(self) -> Dict:
        """Serialize state for persistence."""
        return {
            'compass_account': self.compass_account,
            'rattle_account': self.rattle_account,
            'base_compass_alloc': self.base_compass_alloc,
            'base_rattle_alloc': self.base_rattle_alloc,
            'max_compass_alloc': self.max_compass_alloc,
            'total_recycled_days': self.total_recycled_days,
            'total_days': self.total_days,
            'efa_value': self.efa_value,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> 'HydraCapitalManager':
        """Restore from persisted state."""
        total = d['compass_account'] + d['rattle_account']
        mgr = cls(total, d['base_compass_alloc'], d['base_rattle_alloc'],
                  d['max_compass_alloc'])
        mgr.compass_account = d['compass_account']
        mgr.rattle_account = d['rattle_account']
        mgr.total_recycled_days = d.get('total_recycled_days', 0)
        mgr.total_days = d.get('total_days', 0)
        mgr.efa_value = d.get('efa_value', 0.0)
        return mgr
