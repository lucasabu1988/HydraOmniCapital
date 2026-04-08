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


def update_accounts_after_day_pure(
    capital: HydraCapitalState,
    compass_return: float,
    rattle_return: float,
    rattle_exposure: float,
) -> HydraCapitalState:
    """Pure equivalent of HydraCapitalManager.update_accounts_after_day
    (hydra_capital.py:113-138).

    Settles recycled cash (which earns COMPASS returns) back into the
    rattle account at end-of-day. Returns a NEW HydraCapitalState.
    """
    alloc = compute_allocation_pure(capital, rattle_exposure)
    recycled = alloc['recycled_amount']

    c_effective = alloc['compass_budget']
    r_effective = alloc['rattle_budget']

    c_new = c_effective * (1 + compass_return)
    r_new = r_effective * (1 + rattle_return)

    # Settle recycled amount (it earned COMPASS returns)
    recycled_after = recycled * (1 + compass_return)

    return capital._replace(
        compass_account=c_new - recycled_after,
        rattle_account=r_new + recycled_after,
    )


def update_efa_value_pure(
    capital: HydraCapitalState,
    efa_return: float,
) -> HydraCapitalState:
    """Apply daily EFA return to the efa_value bucket.

    Mirrors HydraCapitalManager.update_efa_value (hydra_capital.py:155-158).
    """
    if capital.efa_value > 0 and efa_return != 0:
        return capital._replace(efa_value=capital.efa_value * (1 + efa_return))
    return capital


def compute_budgets_from_snapshot(
    positions: dict,
    cash: float,
    prices: Dict[str, float],
    nav: float,
    config: dict,
) -> Dict[str, float]:
    """Option C — NAV-derived budget computation.

    This is the replacement for compute_allocation_pure as the budget
    source in the v1.4 orchestrator. It depends only on the current
    economic snapshot (positions + cash + prices + nav) and never on
    accumulated HydraCapitalState buckets. That eliminates the v1.4 T19
    feedback loop where the derived-bucket model fed back into budget
    sizing day-over-day.

    Returns the SAME dict keys as compute_allocation_pure so the
    orchestrator can swap them one-for-one:
        compass_budget, rattle_budget, catalyst_budget,
        recycled_amount, recycled_pct,
        compass_alloc, rattle_alloc, catalyst_alloc,
        efa_idle.

    Semantics:
      - compass_budget  = BASE_C * NAV + recycled  (capped at MAX_C * NAV)
      - rattle_budget   = BASE_R * NAV - recycled  (rattle gives up the lent share)
      - catalyst_budget = BASE_CAT * NAV
      - recycled        = min(rattle_idle, compass_room)
      - efa_idle        = leftover rattle free budget after recycling

    where:
      - rattle_idle     = max(0, BASE_R * NAV - rattle_positions_value)
      - compass_room    = max(0, MAX_C * NAV - compass_positions_value)
                          (so compass cannot exceed its hard cap)
    """
    base_c = float(config.get('BASE_COMPASS_ALLOC', BASE_COMPASS_ALLOC))
    base_r = float(config.get('BASE_RATTLE_ALLOC', BASE_RATTLE_ALLOC))
    base_cat = float(config.get('BASE_CATALYST_ALLOC', BASE_CATALYST_ALLOC))
    max_c = float(config.get('MAX_COMPASS_ALLOC', MAX_COMPASS_ALLOC))

    compass_pos_value = 0.0
    rattle_pos_value = 0.0
    catalyst_pos_value = 0.0
    for sym, pos in positions.items():
        strat = pos.get('_strategy')
        shares = pos.get('shares', 0)
        if shares == 0:
            continue
        price = prices.get(sym, pos.get('entry_price', 0.0))
        mv = shares * price
        if strat == 'compass':
            compass_pos_value += mv
        elif strat == 'rattle':
            rattle_pos_value += mv
        elif strat == 'catalyst':
            catalyst_pos_value += mv
        # efa excluded — it's a separate bucket fed from rattle idle

    # Base targets from NAV
    compass_target = base_c * nav
    rattle_target = base_r * nav
    catalyst_target = base_cat * nav

    # Idle rattle budget (free, not invested)
    rattle_idle = max(0.0, rattle_target - rattle_pos_value)

    # Compass headroom up to MAX_C
    compass_room = max(0.0, max_c * nav - compass_pos_value)
    # Compass can only accept recycled on top of its base target
    compass_extra_room = max(0.0, compass_room - max(0.0, compass_target - compass_pos_value))

    recycled = min(rattle_idle, compass_extra_room)

    compass_budget = compass_target + recycled
    rattle_budget = rattle_target - recycled
    catalyst_budget = catalyst_target

    # Leftover rattle idle (after recycling) is available for EFA
    efa_idle = max(0.0, rattle_idle - recycled)

    return {
        'compass_budget': compass_budget,
        'rattle_budget': rattle_budget,
        'catalyst_budget': catalyst_budget,
        'recycled_amount': recycled,
        'recycled_pct': recycled / nav if nav > 0 else 0.0,
        'compass_alloc': compass_budget / nav if nav > 0 else base_c,
        'rattle_alloc': rattle_budget / nav if nav > 0 else base_r,
        'catalyst_alloc': catalyst_budget / nav if nav > 0 else base_cat,
        'efa_idle': efa_idle,
    }


def update_catalyst_value_pure(
    capital: HydraCapitalState,
    catalyst_return: float,
) -> HydraCapitalState:
    """Apply daily Catalyst return to the catalyst_account bucket.

    Mirrors HydraCapitalManager.update_catalyst_value (hydra_capital.py:172-175).
    """
    if catalyst_return != 0:
        return capital._replace(
            catalyst_account=capital.catalyst_account * (1 + catalyst_return)
        )
    return capital
