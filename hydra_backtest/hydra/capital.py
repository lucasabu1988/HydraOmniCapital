"""hydra_backtest.hydra.capital — pure-function port of HydraCapitalManager.

Mirrors hydra_capital.py:29-227 line-by-line. The live class is mutable
and tracks state across days; the pure version takes a state in and
returns a new state out, never mutating.

These constants mirror hydra_capital.py:22-26. If live ever changes
them, this duplication is the only contract surface to update.
"""
from dataclasses import dataclass, replace
from typing import Dict


BASE_COMPASS_ALLOC = 0.425
BASE_RATTLE_ALLOC = 0.425
BASE_CATALYST_ALLOC = 0.15
MAX_COMPASS_ALLOC = 0.75
EFA_MIN_BUY = 1000.0
EFA_DEPLOYMENT_CAP = 0.90  # only deploy 90% of available idle cash to EFA


@dataclass(frozen=True)
class HydraCapitalState:
    """Logical accounting for the four HYDRA pillars.

    Does NOT hold cash. The shared broker cash lives in
    HydraBacktestState.cash. These four numbers track how much each
    pillar 'owns' of total_value.
    """
    compass_account: float
    rattle_account: float
    catalyst_account: float
    efa_value: float

    base_compass_alloc: float = BASE_COMPASS_ALLOC
    base_rattle_alloc: float = BASE_RATTLE_ALLOC
    base_catalyst_alloc: float = BASE_CATALYST_ALLOC
    max_compass_alloc: float = MAX_COMPASS_ALLOC

    @property
    def total_capital(self) -> float:
        return (
            self.compass_account
            + self.rattle_account
            + self.catalyst_account
            + self.efa_value
        )

    def _replace(self, **kwargs) -> 'HydraCapitalState':
        return replace(self, **kwargs)


def compute_allocation_pure(
    capital: HydraCapitalState,
    rattle_exposure: float,
) -> Dict[str, float]:
    """Pure equivalent of HydraCapitalManager.compute_allocation
    (hydra_capital.py:68-111).

    Args:
        capital: current HydraCapitalState
        rattle_exposure: fraction of Rattlesnake account currently
            invested (0.0-1.0)

    Returns:
        Dict with compass_budget, rattle_budget, catalyst_budget,
        recycled_amount, recycled_pct, compass_alloc, rattle_alloc,
        catalyst_alloc, efa_idle.
    """
    total = capital.total_capital

    # How much of Rattlesnake's account is idle?
    r_idle = capital.rattle_account * (1.0 - rattle_exposure)

    # Max we can lend to COMPASS
    max_c = total * capital.max_compass_alloc - capital.compass_account
    max_c = max(0.0, max_c)

    recycle_amount = min(r_idle, max_c)

    c_effective = capital.compass_account + recycle_amount
    r_effective = capital.rattle_account - recycle_amount

    # Remaining idle cash after recycling (available for NEW EFA buys)
    r_still_idle = r_effective * (1.0 - rattle_exposure)
    efa_idle = r_still_idle  # only truly idle cash

    return {
        'compass_budget': c_effective,
        'rattle_budget': r_effective,
        'catalyst_budget': capital.catalyst_account,
        'recycled_amount': recycle_amount,
        'recycled_pct': recycle_amount / total if total > 0 else 0.0,
        'compass_alloc': (
            c_effective / total if total > 0 else BASE_COMPASS_ALLOC
        ),
        'rattle_alloc': (
            r_effective / total if total > 0 else BASE_RATTLE_ALLOC
        ),
        'catalyst_alloc': (
            capital.catalyst_account / total if total > 0 else BASE_CATALYST_ALLOC
        ),
        'efa_idle': efa_idle,
    }
