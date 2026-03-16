import pandas as pd
import pytest

import catalyst_signals as catalyst


def make_history(last_close, base_close=100.0):
    closes = [base_close] * (catalyst.CATALYST_SMA_PERIOD - 1) + [last_close]
    index = pd.date_range('2025-01-01', periods=len(closes), freq='D')
    return pd.DataFrame({'Close': closes}, index=index)


class TestCatalystSignals:

    def test_tlt_signal_includes_only_when_above_sma200(self):
        above = catalyst.compute_trend_holdings({
            'TLT': make_history(110.0),
            'GLD': make_history(90.0),
            'DBC': make_history(90.0),
        })
        below = catalyst.compute_trend_holdings({
            'TLT': make_history(90.0),
            'GLD': make_history(90.0),
            'DBC': make_history(90.0),
        })

        assert 'TLT' in above
        assert 'TLT' not in below

    def test_gld_above_sma200_is_included_and_receives_trend_plus_gold_allocation(self):
        budget = 30_000.0
        hist_data = {
            'TLT': make_history(90.0),
            'GLD': make_history(110.0),
            'DBC': make_history(90.0),
        }
        current_prices = {'TLT': 10.0, 'GLD': 10.0, 'DBC': 10.0}

        holdings = catalyst.compute_trend_holdings(hist_data)
        targets = catalyst.compute_catalyst_targets(hist_data, budget, current_prices)
        gld_target = next(target for target in targets if target['symbol'] == 'GLD')

        assert holdings == ['GLD']
        assert gld_target['sub_strategy'] == 'trend+gold'
        assert gld_target['target_value'] == pytest.approx(budget)

    def test_dbc_signal_is_included_when_above_sma200(self):
        holdings = catalyst.compute_trend_holdings({
            'TLT': make_history(90.0),
            'GLD': make_history(90.0),
            'DBC': make_history(110.0),
        })

        assert holdings == ['DBC']

    def test_permanent_gold_floor_applies_even_when_gld_is_below_sma200(self):
        budget = 30_000.0
        hist_data = {
            'TLT': make_history(90.0),
            'GLD': make_history(90.0),
            'DBC': make_history(90.0),
        }

        targets = catalyst.compute_catalyst_targets(
            hist_data=hist_data,
            catalyst_budget=budget,
            current_prices={'GLD': 10.0},
        )

        assert len(targets) == 1
        assert targets[0]['symbol'] == 'GLD'
        assert targets[0]['sub_strategy'] == 'gold'
        assert targets[0]['target_value'] == pytest.approx(
            budget * catalyst.CATALYST_GOLD_WEIGHT
        )

    def test_all_etfs_below_sma200_yield_minimal_defensive_positioning(self):
        budget = 30_000.0
        hist_data = {
            'TLT': make_history(90.0),
            'GLD': make_history(90.0),
            'DBC': make_history(90.0),
        }

        holdings = catalyst.compute_trend_holdings(hist_data)
        targets = catalyst.compute_catalyst_targets(
            hist_data=hist_data,
            catalyst_budget=budget,
            current_prices={'TLT': 10.0, 'GLD': 10.0, 'DBC': 10.0},
        )

        assert holdings == []
        assert [target['symbol'] for target in targets] == ['GLD']

    def test_capital_is_allocated_across_active_signals_using_catalyst_weights(self):
        budget = 30_000.0
        hist_data = {
            'TLT': make_history(110.0),
            'GLD': make_history(110.0),
            'DBC': make_history(110.0),
        }
        current_prices = {'TLT': 10.0, 'GLD': 10.0, 'DBC': 10.0}

        targets = catalyst.compute_catalyst_targets(hist_data, budget, current_prices)
        values = {target['symbol']: target['target_value'] for target in targets}
        trend_per_asset = budget * catalyst.CATALYST_TREND_WEIGHT / 3
        gold_floor = budget * catalyst.CATALYST_GOLD_WEIGHT

        assert values['TLT'] == pytest.approx(trend_per_asset)
        assert values['DBC'] == pytest.approx(trend_per_asset)
        assert values['GLD'] == pytest.approx(trend_per_asset + gold_floor)
        assert values['TLT'] / budget == pytest.approx(0.22233333333333333)
        assert values['DBC'] / budget == pytest.approx(0.22233333333333333)
        assert values['GLD'] / budget == pytest.approx(0.5553333333333333)
