import numpy as np
import pandas as pd
import pytest

import catalyst_signals as catalyst


def _make_hist(last_close, base_close=100.0, periods=None):
    """Build a synthetic Close DataFrame with SMA200-compatible length."""
    if periods is None:
        periods = catalyst.CATALYST_SMA_PERIOD
    closes = [base_close] * (periods - 1) + [last_close]
    index = pd.date_range('2024-01-01', periods=len(closes), freq='D')
    return pd.DataFrame({'Close': closes}, index=index)


def _prices(**kwargs):
    return kwargs


def _all_hist(last_close):
    return {sym: _make_hist(last_close) for sym in catalyst.CATALYST_TREND_ASSETS}


class TestComputeTrendHoldings:

    def test_tlt_above_sma200_included(self):
        hist = _all_hist(80.0)
        hist['TLT'] = _make_hist(120.0)
        holdings = catalyst.compute_trend_holdings(hist)
        assert 'TLT' in holdings

    def test_tlt_below_sma200_excluded(self):
        holdings = catalyst.compute_trend_holdings(_all_hist(80.0))
        assert 'TLT' not in holdings

    def test_gld_above_sma200_included_in_trend(self):
        hist = _all_hist(80.0)
        hist['GLD'] = _make_hist(120.0)
        holdings = catalyst.compute_trend_holdings(hist)
        assert 'GLD' in holdings

    def test_dbc_below_sma200_excluded(self):
        hist = _all_hist(120.0)
        hist['DBC'] = _make_hist(80.0)
        holdings = catalyst.compute_trend_holdings(hist)
        assert 'DBC' not in holdings

    def test_dbc_above_sma200_included(self):
        hist = _all_hist(80.0)
        hist['DBC'] = _make_hist(120.0)
        holdings = catalyst.compute_trend_holdings(hist)
        assert 'DBC' in holdings

    def test_zroz_above_sma200_included(self):
        hist = _all_hist(80.0)
        hist['ZROZ'] = _make_hist(120.0)
        holdings = catalyst.compute_trend_holdings(hist)
        assert 'ZROZ' in holdings

    def test_zroz_below_sma200_excluded(self):
        holdings = catalyst.compute_trend_holdings(_all_hist(80.0))
        assert 'ZROZ' not in holdings

    def test_all_below_sma200_returns_empty(self):
        holdings = catalyst.compute_trend_holdings(_all_hist(80.0))
        assert holdings == []

    def test_all_above_sma200_returns_all(self):
        holdings = catalyst.compute_trend_holdings(_all_hist(120.0))
        assert set(holdings) == set(catalyst.CATALYST_TREND_ASSETS)

    def test_empty_hist_data_returns_empty(self):
        holdings = catalyst.compute_trend_holdings({})
        assert holdings == []

    def test_insufficient_data_skipped(self):
        short_df = _make_hist(120.0, periods=50)
        holdings = catalyst.compute_trend_holdings({'TLT': short_df})
        assert holdings == []

    def test_missing_ticker_data_skipped_gracefully(self):
        holdings = catalyst.compute_trend_holdings({
            'TLT': _make_hist(120.0),
        })
        assert holdings == ['TLT']

    def test_none_value_in_hist_data_skipped(self):
        holdings = catalyst.compute_trend_holdings({
            'TLT': None,
            'GLD': _make_hist(120.0),
            'DBC': _make_hist(120.0),
        })
        assert 'TLT' not in holdings
        assert 'GLD' in holdings

    def test_return_type_is_list(self):
        holdings = catalyst.compute_trend_holdings({
            'TLT': _make_hist(120.0),
        })
        assert isinstance(holdings, list)

    def test_nan_close_prices_excluded(self):
        df = _make_hist(120.0)
        df.iloc[-1, df.columns.get_loc('Close')] = np.nan
        holdings = catalyst.compute_trend_holdings({'TLT': df, 'GLD': _make_hist(120.0)})
        assert 'TLT' not in holdings
        assert 'GLD' in holdings

    def test_price_exactly_at_sma_not_included(self):
        holdings = catalyst.compute_trend_holdings({
            'TLT': _make_hist(100.0, base_close=100.0),
        })
        assert 'TLT' not in holdings

    def test_ordering_matches_catalyst_trend_assets(self):
        holdings = catalyst.compute_trend_holdings(_all_hist(120.0))
        assert holdings == catalyst.CATALYST_TREND_ASSETS


class TestComputeCatalystTargets:

    def test_no_targets_when_all_below_sma(self):
        hist = _all_hist(80.0)
        prices = {sym: 100.0 for sym in catalyst.CATALYST_TREND_ASSETS}
        targets = catalyst.compute_catalyst_targets(hist, 30_000.0, prices)
        assert targets == []

    def test_gld_above_sma_gets_trend_allocation(self):
        hist = _all_hist(80.0)
        hist['GLD'] = _make_hist(120.0)
        targets = catalyst.compute_catalyst_targets(
            hist, 30_000.0, _prices(GLD=10.0),
        )
        gld = next(t for t in targets if t['symbol'] == 'GLD')
        assert gld['sub_strategy'] == 'trend'

    def test_zero_price_guard_skips_ticker(self):
        hist = _all_hist(120.0)
        prices = {sym: 50.0 for sym in catalyst.CATALYST_TREND_ASSETS}
        prices['TLT'] = 0
        targets = catalyst.compute_catalyst_targets(hist, 30_000.0, prices)
        symbols = [t['symbol'] for t in targets]
        assert 'TLT' not in symbols

    def test_negative_price_guard_skips_ticker(self):
        hist = _all_hist(120.0)
        prices = {sym: 50.0 for sym in catalyst.CATALYST_TREND_ASSETS}
        prices['TLT'] = -5.0
        targets = catalyst.compute_catalyst_targets(hist, 30_000.0, prices)
        symbols = [t['symbol'] for t in targets]
        assert 'TLT' not in symbols

    def test_return_shape_has_required_keys(self):
        hist = _all_hist(120.0)
        prices = {sym: 50.0 for sym in catalyst.CATALYST_TREND_ASSETS}
        targets = catalyst.compute_catalyst_targets(hist, 30_000.0, prices)
        required_keys = {'symbol', 'target_shares', 'target_value', 'sub_strategy'}
        for t in targets:
            assert required_keys.issubset(t.keys())

    def test_return_symbols_are_strings(self):
        hist = _all_hist(120.0)
        prices = {sym: 50.0 for sym in catalyst.CATALYST_TREND_ASSETS}
        targets = catalyst.compute_catalyst_targets(hist, 10_000.0, prices)
        for t in targets:
            assert isinstance(t['symbol'], str)

    def test_target_shares_are_integers(self):
        hist = _all_hist(120.0)
        prices = {sym: 50.0 for sym in catalyst.CATALYST_TREND_ASSETS}
        targets = catalyst.compute_catalyst_targets(hist, 30_000.0, prices)
        for t in targets:
            assert isinstance(t['target_shares'], int)

    def test_empty_price_data_returns_empty(self):
        hist = _all_hist(120.0)
        targets = catalyst.compute_catalyst_targets(hist, 30_000.0, {})
        assert targets == []

    def test_budget_zero_returns_no_targets(self):
        hist = _all_hist(120.0)
        prices = {sym: 50.0 for sym in catalyst.CATALYST_TREND_ASSETS}
        targets = catalyst.compute_catalyst_targets(hist, 0.0, prices)
        assert targets == []

    def test_very_high_price_yields_zero_shares_excluded(self):
        hist = _all_hist(80.0)
        hist['GLD'] = _make_hist(120.0)
        targets = catalyst.compute_catalyst_targets(
            hist, 100.0, _prices(GLD=99999.0),
        )
        assert targets == []

    def test_nan_in_hist_close_excludes_from_trend(self):
        df = _make_hist(120.0)
        df.iloc[-1, df.columns.get_loc('Close')] = np.nan
        hist = _all_hist(80.0)
        hist['TLT'] = df
        prices = {sym: 50.0 for sym in catalyst.CATALYST_TREND_ASSETS}
        targets = catalyst.compute_catalyst_targets(hist, 30_000.0, prices)
        symbols = [t['symbol'] for t in targets]
        assert 'TLT' not in symbols

    def test_equal_weight_across_qualifying_assets(self):
        hist = _all_hist(120.0)
        prices = {sym: 10.0 for sym in catalyst.CATALYST_TREND_ASSETS}
        budget = 40_000.0
        targets = catalyst.compute_catalyst_targets(hist, budget, prices)
        values = {t['symbol']: t['target_value'] for t in targets}
        per_asset = budget / len(catalyst.CATALYST_TREND_ASSETS)
        for sym in catalyst.CATALYST_TREND_ASSETS:
            assert values[sym] == pytest.approx(per_asset, rel=0.01)

    def test_all_targets_have_trend_substrategy(self):
        hist = _all_hist(120.0)
        prices = {sym: 10.0 for sym in catalyst.CATALYST_TREND_ASSETS}
        targets = catalyst.compute_catalyst_targets(hist, 30_000.0, prices)
        assert all(t['sub_strategy'] == 'trend' for t in targets)


class TestConstants:

    def test_catalyst_trend_assets_list(self):
        assert catalyst.CATALYST_TREND_ASSETS == ['TLT', 'ZROZ', 'GLD', 'DBC']

    def test_gold_symbol_is_none(self):
        assert catalyst.CATALYST_GOLD_SYMBOL is None

    def test_sma_period_is_200(self):
        assert catalyst.CATALYST_SMA_PERIOD == 200

    def test_trend_weight_is_one(self):
        assert catalyst.CATALYST_TREND_WEIGHT == 1.0

    def test_gold_weight_is_zero(self):
        assert catalyst.CATALYST_GOLD_WEIGHT == 0.0

    def test_weights_sum_to_one(self):
        total = catalyst.CATALYST_TREND_WEIGHT + catalyst.CATALYST_GOLD_WEIGHT
        assert total == pytest.approx(1.0)
