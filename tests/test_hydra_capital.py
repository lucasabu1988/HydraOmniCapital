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

    def test_buy_efa_moves_cash_from_rattle_account_into_efa_bucket(self):
        manager = HydraCapitalManager(total_capital=100_000)

        manager.buy_efa(5_000)

        assert manager.rattle_account == pytest.approx(37_500)
        assert manager.efa_value == pytest.approx(5_000)
        assert manager.total_capital == pytest.approx(100_000)

    def test_sell_efa_returns_requested_amount_or_full_balance(self):
        manager = HydraCapitalManager(total_capital=100_000)
        manager.buy_efa(5_000)

        partial = manager.sell_efa(2_000)
        remainder = manager.sell_efa()

        assert partial == pytest.approx(2_000)
        assert remainder == pytest.approx(3_000)
        assert manager.efa_value == pytest.approx(0.0)
        assert manager.rattle_account == pytest.approx(42_500)

    def test_update_accounts_after_day_applies_compass_return_to_recycled_cash(self):
        manager = HydraCapitalManager(total_capital=100_000)

        manager.update_accounts_after_day(
            compass_return=0.10,
            rattle_return=0.02,
            rattle_exposure=0.0,
        )

        assert manager.compass_account == pytest.approx(46_750)
        assert manager.rattle_account == pytest.approx(45_950)
        assert manager.catalyst_account == pytest.approx(15_000)
        assert manager.total_capital == pytest.approx(107_700)

    def test_to_dict_and_from_dict_preserve_accounts_allocations_and_tracking(self):
        manager = HydraCapitalManager(total_capital=100_000)
        manager.compute_allocation(rattle_exposure=0.4)
        manager.record_compass_trade(250.0)
        manager.record_rattle_trade(-100.0)
        manager.update_catalyst_value(0.10)
        manager.buy_efa(2_500)

        restored = HydraCapitalManager.from_dict(manager.to_dict())

        assert restored.compass_account == pytest.approx(manager.compass_account)
        assert restored.rattle_account == pytest.approx(manager.rattle_account)
        assert restored.catalyst_account == pytest.approx(manager.catalyst_account)
        assert restored.efa_value == pytest.approx(manager.efa_value)
        assert restored.base_compass_alloc == pytest.approx(manager.base_compass_alloc)
        assert restored.base_rattle_alloc == pytest.approx(manager.base_rattle_alloc)
        assert restored.base_catalyst_alloc == pytest.approx(manager.base_catalyst_alloc)
        assert restored.max_compass_alloc == pytest.approx(manager.max_compass_alloc)
        assert restored.total_days == manager.total_days
        assert restored.total_recycled_days == manager.total_recycled_days
        assert restored.total_capital == pytest.approx(manager.total_capital)

    def test_zero_capital_compute_allocation_and_status_avoid_division_by_zero(self):
        manager = HydraCapitalManager(total_capital=0)

        alloc = manager.compute_allocation(rattle_exposure=0.0)
        status = manager.get_status()

        assert alloc['compass_budget'] == pytest.approx(0.0)
        assert alloc['rattle_budget'] == pytest.approx(0.0)
        assert alloc['catalyst_budget'] == pytest.approx(0.0)
        assert alloc['recycled_amount'] == pytest.approx(0.0)
        assert alloc['recycled_pct'] == pytest.approx(0.0)
        assert alloc['compass_alloc'] == pytest.approx(0.425)
        assert alloc['rattle_alloc'] == pytest.approx(0.425)
        assert alloc['catalyst_alloc'] == pytest.approx(0.15)
        assert status['total_capital'] == pytest.approx(0.0)
        assert status['compass_pct'] == pytest.approx(0.0)
        assert status['rattle_pct'] == pytest.approx(0.0)
        assert status['catalyst_pct'] == pytest.approx(0.0)
        assert status['efa_pct'] == pytest.approx(0.0)
