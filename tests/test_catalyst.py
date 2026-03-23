import pandas as pd
import pytest

import catalyst_signals as catalyst


def make_history(last_close, base_close=100.0):
    closes = [base_close] * (catalyst.CATALYST_SMA_PERIOD - 1) + [last_close]
    index = pd.date_range('2025-01-01', periods=len(closes), freq='D')
    return pd.DataFrame({'Close': closes}, index=index)


def _all_hist(last_close):
    return {sym: make_history(last_close) for sym in catalyst.CATALYST_TREND_ASSETS}


class TestCatalystSignals:

    def test_all_trend_assets_above_sma200_are_returned_in_config_order(self):
        holdings = catalyst.compute_trend_holdings(_all_hist(110.0))
        assert holdings == catalyst.CATALYST_TREND_ASSETS

    def test_one_trend_asset_below_sma200_returns_only_remaining_assets(self):
        hist = _all_hist(110.0)
        hist['GLD'] = make_history(90.0)
        holdings = catalyst.compute_trend_holdings(hist)
        assert 'GLD' not in holdings
        assert 'TLT' in holdings

    def test_tlt_signal_includes_only_when_above_sma200(self):
        hist_above = _all_hist(90.0)
        hist_above['TLT'] = make_history(110.0)
        hist_below = _all_hist(90.0)

        assert 'TLT' in catalyst.compute_trend_holdings(hist_above)
        assert 'TLT' not in catalyst.compute_trend_holdings(hist_below)

    def test_zroz_is_in_trend_assets(self):
        assert 'ZROZ' in catalyst.CATALYST_TREND_ASSETS

    def test_gld_above_sma200_gets_full_trend_allocation(self):
        budget = 30_000.0
        hist = _all_hist(90.0)
        hist['GLD'] = make_history(110.0)
        prices = {sym: 10.0 for sym in catalyst.CATALYST_TREND_ASSETS}

        targets = catalyst.compute_catalyst_targets(hist, budget, prices)
        gld_target = next(t for t in targets if t['symbol'] == 'GLD')

        assert gld_target['sub_strategy'] == 'trend'
        assert gld_target['target_value'] == pytest.approx(budget, rel=0.01)

    def test_dbc_signal_is_included_when_above_sma200(self):
        hist = _all_hist(90.0)
        hist['DBC'] = make_history(110.0)
        holdings = catalyst.compute_trend_holdings(hist)
        assert holdings == ['DBC']

    def test_no_permanent_gold_when_all_below_sma200(self):
        budget = 30_000.0
        hist = _all_hist(90.0)
        prices = {sym: 10.0 for sym in catalyst.CATALYST_TREND_ASSETS}

        targets = catalyst.compute_catalyst_targets(hist, budget, prices)
        assert targets == []

    def test_all_below_sma200_returns_empty_holdings(self):
        holdings = catalyst.compute_trend_holdings(_all_hist(90.0))
        assert holdings == []

    def test_missing_historical_data_is_skipped_gracefully(self):
        holdings = catalyst.compute_trend_holdings({
            'TLT': make_history(110.0),
            'GLD': make_history(110.0),
        })
        assert 'TLT' in holdings
        assert 'GLD' in holdings

    def test_equal_weight_allocation_across_qualifying_assets(self):
        budget = 30_000.0
        hist = _all_hist(110.0)
        prices = {sym: 10.0 for sym in catalyst.CATALYST_TREND_ASSETS}

        targets = catalyst.compute_catalyst_targets(hist, budget, prices)
        values = {t['symbol']: t['target_value'] for t in targets}
        per_asset = budget / len(catalyst.CATALYST_TREND_ASSETS)

        for sym in catalyst.CATALYST_TREND_ASSETS:
            assert values[sym] == pytest.approx(per_asset, rel=0.01)

    def test_target_allocations_sum_to_budget_with_round_friendly_prices(self):
        budget = 30_000.0
        hist = _all_hist(110.0)
        prices = {sym: 10.0 for sym in catalyst.CATALYST_TREND_ASSETS}

        targets = catalyst.compute_catalyst_targets(hist, budget, prices)
        total_allocated = sum(t['target_value'] for t in targets)
        assert total_allocated / budget == pytest.approx(1.0, rel=0.01)

    def test_zero_price_ticker_is_skipped(self):
        budget = 30_000.0
        hist = _all_hist(110.0)
        prices = {sym: 100.0 for sym in catalyst.CATALYST_TREND_ASSETS}
        prices['TLT'] = 0

        targets = catalyst.compute_catalyst_targets(hist, budget, prices)
        symbols = [t['symbol'] for t in targets]
        assert 'TLT' not in symbols

    def test_zero_budget_returns_no_targets(self):
        hist = _all_hist(110.0)
        prices = {sym: 10.0 for sym in catalyst.CATALYST_TREND_ASSETS}
        targets = catalyst.compute_catalyst_targets(hist, 0.0, prices)
        assert targets == []

    def test_gold_weight_is_zero(self):
        assert catalyst.CATALYST_GOLD_WEIGHT == 0.0

    def test_trend_weight_is_one(self):
        assert catalyst.CATALYST_TREND_WEIGHT == 1.0

    def test_weights_sum_to_one(self):
        total = catalyst.CATALYST_TREND_WEIGHT + catalyst.CATALYST_GOLD_WEIGHT
        assert total == pytest.approx(1.0)

    def test_catalyst_trend_assets_includes_zroz(self):
        assert catalyst.CATALYST_TREND_ASSETS == ['TLT', 'ZROZ', 'GLD', 'DBC']

    def test_all_targets_are_trend_substrategy(self):
        budget = 30_000.0
        hist = _all_hist(110.0)
        prices = {sym: 10.0 for sym in catalyst.CATALYST_TREND_ASSETS}
        targets = catalyst.compute_catalyst_targets(hist, budget, prices)
        assert all(t['sub_strategy'] == 'trend' for t in targets)
