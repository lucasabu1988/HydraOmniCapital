"""Unit tests for hydra_backtest.hydra.capital pure functions.

The most important test in v1.4: byte-identity vs the live
HydraCapitalManager class over a synthetic 100-day random sequence.
"""
import numpy as np
import pytest

from hydra_backtest.hydra.capital import (
    BASE_CATALYST_ALLOC,
    BASE_COMPASS_ALLOC,
    BASE_RATTLE_ALLOC,
    MAX_COMPASS_ALLOC,
    HydraCapitalState,
    compute_allocation_pure,
    compute_budgets_from_snapshot,
    update_accounts_after_day_pure,
    update_catalyst_value_pure,
    update_efa_value_pure,
)
from hydra_capital import HydraCapitalManager


def _make_pair(initial: float = 100_000.0):
    """Build matched live HCM + pure HCS pair for round-trip tests."""
    live = HydraCapitalManager(initial)
    pure = HydraCapitalState(
        compass_account=initial * BASE_COMPASS_ALLOC,
        rattle_account=initial * BASE_RATTLE_ALLOC,
        catalyst_account=initial * BASE_CATALYST_ALLOC,
        efa_value=0.0,
    )
    return live, pure


def test_compute_allocation_matches_live_initial_state():
    live, pure = _make_pair()
    live_alloc = live.compute_allocation(rattle_exposure=0.5)
    pure_alloc = compute_allocation_pure(pure, rattle_exposure=0.5)
    for key in ['compass_budget', 'rattle_budget', 'catalyst_budget',
                'recycled_amount', 'efa_idle']:
        assert pure_alloc[key] == pytest.approx(live_alloc[key]), (
            f"{key} mismatch: pure={pure_alloc[key]} live={live_alloc[key]}"
        )


def test_compute_allocation_full_idle_rattle_caps_at_75pct():
    """When Rattlesnake is 100% idle, COMPASS budget should hit the 0.75 cap."""
    _, pure = _make_pair()
    alloc = compute_allocation_pure(pure, rattle_exposure=0.0)
    # max compass = 0.75 * total = 75_000; base compass = 42_500
    # so recycled = min(42_500 idle rattle, 32_500 max recycle) = 32_500
    assert alloc['compass_budget'] == pytest.approx(75_000.0)
    assert alloc['recycled_amount'] == pytest.approx(32_500.0)
    assert alloc['rattle_budget'] == pytest.approx(10_000.0)


def test_compute_allocation_zero_idle_rattle():
    """When Rattlesnake is 100% deployed, no recycling."""
    _, pure = _make_pair()
    alloc = compute_allocation_pure(pure, rattle_exposure=1.0)
    assert alloc['recycled_amount'] == 0.0
    assert alloc['compass_budget'] == pytest.approx(42_500.0)


def test_update_accounts_after_day_byte_identical_100d():
    """Run 100 random days through both implementations and compare.

    This is the most important test in v1.4: it proves that the pure
    accounting math matches the live HCM exactly. If this fails, the
    sub-account sum invariant in T8 will fail and v1.4 is broken.
    """
    np.random.seed(666)
    live, pure = _make_pair()
    for day in range(100):
        c_ret = float(np.random.normal(0.0005, 0.01))
        r_ret = float(np.random.normal(0.0003, 0.008))
        r_exp = float(np.random.uniform(0, 1))
        live.update_accounts_after_day(c_ret, r_ret, r_exp)
        pure = update_accounts_after_day_pure(pure, c_ret, r_ret, r_exp)
        assert pure.compass_account == pytest.approx(
            live.compass_account, rel=1e-12
        ), f"day {day}: compass diverged"
        assert pure.rattle_account == pytest.approx(
            live.rattle_account, rel=1e-12
        ), f"day {day}: rattle diverged"


def test_update_efa_value_pure_applies_return():
    pure = HydraCapitalState(
        compass_account=42_500, rattle_account=42_500,
        catalyst_account=15_000, efa_value=10_000,
    )
    pure2 = update_efa_value_pure(pure, 0.05)
    assert pure2.efa_value == pytest.approx(10_500)


def test_update_efa_value_pure_skips_when_zero():
    pure = HydraCapitalState(
        compass_account=42_500, rattle_account=42_500,
        catalyst_account=15_000, efa_value=0.0,
    )
    pure2 = update_efa_value_pure(pure, 0.05)
    assert pure2.efa_value == 0.0


def test_update_catalyst_value_pure():
    pure = HydraCapitalState(
        compass_account=42_500, rattle_account=42_500,
        catalyst_account=15_000, efa_value=0.0,
    )
    pure2 = update_catalyst_value_pure(pure, 0.02)
    assert pure2.catalyst_account == pytest.approx(15_300)


def test_total_capital_property():
    pure = HydraCapitalState(
        compass_account=10_000, rattle_account=20_000,
        catalyst_account=5_000, efa_value=15_000,
    )
    assert pure.total_capital == 50_000


def test_replace_returns_new_instance():
    pure = HydraCapitalState(
        compass_account=10_000, rattle_account=20_000,
        catalyst_account=5_000, efa_value=15_000,
    )
    pure2 = pure._replace(compass_account=99_000)
    assert pure.compass_account == 10_000  # original unchanged
    assert pure2.compass_account == 99_000
    assert pure2.rattle_account == 20_000


# ============================================================
# Option C — compute_budgets_from_snapshot tests
# ============================================================

_CFG = {
    'BASE_COMPASS_ALLOC': BASE_COMPASS_ALLOC,
    'BASE_RATTLE_ALLOC': BASE_RATTLE_ALLOC,
    'BASE_CATALYST_ALLOC': BASE_CATALYST_ALLOC,
    'MAX_COMPASS_ALLOC': MAX_COMPASS_ALLOC,
}


def test_budgets_from_snapshot_empty_portfolio():
    """At t=0 with all cash and no positions, rattle is fully idle so
    recycling is active — compass gets its full MAX_C cap (mirrors
    live HCM behavior: idle rattle budget flows to compass)."""
    b = compute_budgets_from_snapshot(
        positions={}, cash=100_000.0, prices={}, nav=100_000.0, config=_CFG,
    )
    # compass_target = 42.5k, rattle_idle = 42.5k, compass_extra_room = 32.5k
    # recycled = 32.5k, compass_budget = 75k (MAX_C cap)
    assert b['compass_budget'] == pytest.approx(75_000)
    assert b['rattle_budget'] == pytest.approx(10_000)   # 42.5 - 32.5
    assert b['catalyst_budget'] == pytest.approx(15_000)
    assert b['recycled_amount'] == pytest.approx(32_500)
    assert b['efa_idle'] == pytest.approx(10_000)        # 42.5 idle - 32.5 recycled


def test_budgets_sum_to_nav():
    """compass + rattle + catalyst must equal NAV (ignoring EFA which
    is funded from rattle idle)."""
    b = compute_budgets_from_snapshot(
        positions={}, cash=50_000.0, prices={}, nav=200_000.0, config=_CFG,
    )
    total = b['compass_budget'] + b['rattle_budget'] + b['catalyst_budget']
    assert total == pytest.approx(200_000)


def test_budgets_no_feedback_loop():
    """REPLAY DETERMINISM: calling twice with the same snapshot must
    yield identical budgets. This is the canary for the v1.4 T19
    feedback loop — if budgets ever depended on prior state, a second
    call would drift."""
    positions = {
        'AAPL': {'_strategy': 'compass', 'shares': 100, 'entry_price': 150.0},
        'MSFT': {'_strategy': 'compass', 'shares': 50, 'entry_price': 300.0},
    }
    prices = {'AAPL': 160.0, 'MSFT': 310.0}
    cash = 40_000.0
    nav = cash + 100*160 + 50*310  # 71,500
    b1 = compute_budgets_from_snapshot(positions, cash, prices, nav, _CFG)
    b2 = compute_budgets_from_snapshot(positions, cash, prices, nav, _CFG)
    for k in b1:
        assert b1[k] == b2[k], f"Budget {k} not deterministic: {b1[k]} vs {b2[k]}"


def test_budgets_idle_rattle_recycles_to_compass():
    """When rattle has no positions and compass has some, recycling
    should increase compass budget up to MAX_C * NAV."""
    positions = {
        'AAPL': {'_strategy': 'compass', 'shares': 100, 'entry_price': 100.0},
    }
    # AAPL worth 10k, cash 90k -> NAV 100k
    b = compute_budgets_from_snapshot(
        positions=positions, cash=90_000.0, prices={'AAPL': 100.0},
        nav=100_000.0, config=_CFG,
    )
    # BASE_C = 42.5k, compass_pos = 10k -> compass_target - pos = 32.5k base room
    # compass_extra_room = MAX_C*NAV - compass_pos - base_room = 75k - 10k - 32.5k = 32.5k
    # rattle_idle = BASE_R*NAV - 0 = 42.5k
    # recycled = min(42.5k, 32.5k) = 32.5k
    assert b['recycled_amount'] == pytest.approx(32_500)
    assert b['compass_budget'] == pytest.approx(75_000)  # BASE_C + recycled
    assert b['rattle_budget'] == pytest.approx(10_000)   # BASE_R - recycled
    assert b['efa_idle'] == pytest.approx(10_000)        # leftover rattle idle


def test_budgets_fully_invested_no_recycling():
    """When rattle is fully invested to its target, no recycling
    happens and compass gets only its base share."""
    positions = {
        'AAPL': {'_strategy': 'compass', 'shares': 100, 'entry_price': 100.0},
        'RATTLE1': {'_strategy': 'rattle', 'shares': 100, 'entry_price': 425.0},
    }
    prices = {'AAPL': 100.0, 'RATTLE1': 425.0}
    # compass 10k, rattle 42.5k, cash 47.5k -> NAV 100k
    b = compute_budgets_from_snapshot(
        positions=positions, cash=47_500.0, prices=prices,
        nav=100_000.0, config=_CFG,
    )
    assert b['recycled_amount'] == pytest.approx(0.0)
    assert b['compass_budget'] == pytest.approx(42_500)
    assert b['rattle_budget'] == pytest.approx(42_500)
    assert b['efa_idle'] == pytest.approx(0.0)


def test_budgets_compass_at_max_cap():
    """If compass already exceeds its base target (via prior recycling),
    recycling should respect MAX_C cap and not double-lend."""
    positions = {
        'AAPL': {'_strategy': 'compass', 'shares': 100, 'entry_price': 500.0},
    }
    # compass = 50k (> base 42.5k), NAV 100k -> MAX_C room = 75k - 50k = 25k
    b = compute_budgets_from_snapshot(
        positions=positions, cash=50_000.0, prices={'AAPL': 500.0},
        nav=100_000.0, config=_CFG,
    )
    # compass_target = 42.5k, compass_pos = 50k already > target
    # base_room = max(0, 42.5k - 50k) = 0
    # compass_extra_room = max(0, 25k - 0) = 25k
    # rattle_idle = 42.5k, recycled = min(42.5k, 25k) = 25k
    assert b['recycled_amount'] == pytest.approx(25_000)
    assert b['compass_budget'] == pytest.approx(67_500)  # 42.5 + 25
    # rattle base - recycled, then efa_idle gets the rest
    assert b['rattle_budget'] == pytest.approx(17_500)   # 42.5 - 25
    assert b['efa_idle'] == pytest.approx(17_500)        # 42.5 idle - 25 recycled


def test_budgets_nav_growth_scales_proportionally():
    """If NAV doubles, budgets must double (no path dependence)."""
    b1 = compute_budgets_from_snapshot(
        positions={}, cash=100_000.0, prices={}, nav=100_000.0, config=_CFG,
    )
    b2 = compute_budgets_from_snapshot(
        positions={}, cash=200_000.0, prices={}, nav=200_000.0, config=_CFG,
    )
    assert b2['compass_budget'] == pytest.approx(2 * b1['compass_budget'])
    assert b2['rattle_budget'] == pytest.approx(2 * b1['rattle_budget'])
    assert b2['catalyst_budget'] == pytest.approx(2 * b1['catalyst_budget'])


def test_budgets_ignore_capital_state():
    """CRITICAL: the function signature does NOT accept HydraCapitalState.
    It should derive everything from positions + cash + prices + nav.
    This test just confirms the call works without any bucket input."""
    # Same snapshot, called from different 'worlds' with no state carryover
    positions = {
        'AAPL': {'_strategy': 'compass', 'shares': 10, 'entry_price': 150.0},
    }
    b = compute_budgets_from_snapshot(
        positions=positions, cash=50_000.0, prices={'AAPL': 150.0},
        nav=51_500.0, config=_CFG,
    )
    # Must produce a valid result with just the snapshot
    assert b['compass_budget'] > 0
    assert b['rattle_budget'] > 0
    assert b['catalyst_budget'] > 0
