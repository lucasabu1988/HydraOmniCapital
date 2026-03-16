import pytest

from hydra_capital import HydraCapitalManager


class TestHydraCapitalManager:

    def test_initial_allocation_splits_capital_by_base_weights(self):
        manager = HydraCapitalManager(total_capital=100_000)

        assert manager.compass_account == pytest.approx(42_500)
        assert manager.rattle_account == pytest.approx(42_500)
        assert manager.catalyst_account == pytest.approx(15_000)
        assert manager.total_capital == pytest.approx(100_000)

    def test_compute_allocation_recycles_idle_rattle_cash_up_to_compass_cap(self):
        manager = HydraCapitalManager(total_capital=100_000)

        alloc = manager.compute_allocation(rattle_exposure=0.0)

        assert alloc['recycled_amount'] == pytest.approx(32_500)
        assert alloc['compass_budget'] == pytest.approx(75_000)
        assert alloc['rattle_budget'] == pytest.approx(10_000)
        assert alloc['catalyst_budget'] == pytest.approx(15_000)
        assert alloc['compass_alloc'] == pytest.approx(0.75)
        assert alloc['recycled_pct'] == pytest.approx(0.325)
        assert manager.current_recycled == pytest.approx(32_500)
        assert manager.total_days == 1
        assert manager.total_recycled_days == 1

    def test_recycled_cash_returns_to_rattle_account_when_it_needs_capital_back(self):
        manager = HydraCapitalManager(total_capital=100_000)

        manager.update_accounts_after_day(
            compass_return=0.10,
            rattle_return=0.0,
            rattle_exposure=0.0,
        )
        alloc = manager.compute_allocation(rattle_exposure=1.0)

        assert manager.compass_account == pytest.approx(46_750)
        assert manager.rattle_account == pytest.approx(45_750)
        assert alloc['recycled_amount'] == pytest.approx(0.0)
        assert alloc['compass_budget'] == pytest.approx(46_750)
        assert alloc['rattle_budget'] == pytest.approx(45_750)
        assert manager.total_capital == pytest.approx(107_500)

    def test_compute_allocation_with_full_rattle_exposure_has_no_idle_cash(self):
        manager = HydraCapitalManager(total_capital=100_000)

        alloc = manager.compute_allocation(rattle_exposure=1.0)

        assert alloc['recycled_amount'] == pytest.approx(0.0)
        assert alloc['compass_budget'] == pytest.approx(42_500)
        assert alloc['rattle_budget'] == pytest.approx(42_500)
        assert alloc['efa_idle'] == pytest.approx(0.0)
        assert manager.current_recycled == pytest.approx(0.0)
        assert manager.total_days == 1
        assert manager.total_recycled_days == 0

    def test_negative_returns_can_reduce_an_account_below_zero(self):
        manager = HydraCapitalManager(total_capital=100_000)

        manager.update_accounts_after_day(
            compass_return=-2.0,
            rattle_return=0.0,
            rattle_exposure=1.0,
        )
        status = manager.get_status()

        assert manager.compass_account == pytest.approx(-42_500)
        assert manager.rattle_account == pytest.approx(42_500)
        assert manager.catalyst_account == pytest.approx(15_000)
        assert status['total_capital'] == pytest.approx(15_000)
        assert status['compass_pct'] == pytest.approx(-42_500 / 15_000)

    def test_compute_allocation_rebalances_after_rattle_position_exits(self):
        manager = HydraCapitalManager(total_capital=100_000)

        fully_deployed = manager.compute_allocation(rattle_exposure=1.0)
        after_exits = manager.compute_allocation(rattle_exposure=0.5)

        assert fully_deployed['recycled_amount'] == pytest.approx(0.0)
        assert after_exits['recycled_amount'] == pytest.approx(21_250)
        assert after_exits['compass_budget'] == pytest.approx(63_750)
        assert after_exits['rattle_budget'] == pytest.approx(21_250)
        assert after_exits['efa_idle'] == pytest.approx(10_625)

    def test_compute_allocation_reports_effective_budgets_per_strategy(self):
        manager = HydraCapitalManager(total_capital=100_000)

        alloc = manager.compute_allocation(rattle_exposure=0.6)

        assert alloc['compass_budget'] == pytest.approx(59_500)
        assert alloc['rattle_budget'] == pytest.approx(25_500)
        assert alloc['catalyst_budget'] == pytest.approx(15_000)
        assert alloc['compass_alloc'] == pytest.approx(0.595)
        assert alloc['rattle_alloc'] == pytest.approx(0.255)
        assert alloc['catalyst_alloc'] == pytest.approx(0.15)
