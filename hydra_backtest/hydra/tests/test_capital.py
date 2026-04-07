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
    HydraCapitalState,
    compute_allocation_pure,
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
