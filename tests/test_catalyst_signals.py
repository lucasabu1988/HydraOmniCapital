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


class TestComputeTrendHoldings:

    def test_tlt_above_sma200_included(self):
        holdings = catalyst.compute_trend_holdings({
            'TLT': _make_hist(120.0),
            'GLD': _make_hist(80.0),
            'DBC': _make_hist(80.0),
        })
        assert 'TLT' in holdings

    def test_tlt_below_sma200_excluded(self):
        holdings = catalyst.compute_trend_holdings({
            'TLT': _make_hist(80.0),
            'GLD': _make_hist(80.0),
            'DBC': _make_hist(80.0),
        })
        assert 'TLT' not in holdings

    def test_gld_above_sma200_included_in_trend(self):
        holdings = catalyst.compute_trend_holdings({
            'TLT': _make_hist(80.0),
            'GLD': _make_hist(120.0),
            'DBC': _make_hist(80.0),
        })
        assert 'GLD' in holdings

    def test_dbc_below_sma200_excluded(self):
        holdings = catalyst.compute_trend_holdings({
            'TLT': _make_hist(120.0),
            'GLD': _make_hist(120.0),
            'DBC': _make_hist(80.0),
        })
        assert 'DBC' not in holdings

    def test_dbc_above_sma200_included(self):
        holdings = catalyst.compute_trend_holdings({
            'TLT': _make_hist(80.0),
            'GLD': _make_hist(80.0),
            'DBC': _make_hist(120.0),
        })
        assert 'DBC' in holdings

    def test_all_below_sma200_returns_empty(self):
        holdings = catalyst.compute_trend_holdings({
            'TLT': _make_hist(80.0),
            'GLD': _make_hist(80.0),
            'DBC': _make_hist(80.0),
        })
        assert holdings == []

    def test_all_above_sma200_returns_all_three(self):
        holdings = catalyst.compute_trend_holdings({
            'TLT': _make_hist(120.0),
            'GLD': _make_hist(120.0),
            'DBC': _make_hist(120.0),
        })
        assert set(holdings) == {'TLT', 'GLD', 'DBC'}

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
            # GLD and DBC missing entirely
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
        # NaN comparison: NaN > sma is False, so TLT excluded
        assert 'TLT' not in holdings
        assert 'GLD' in holdings

    def test_price_exactly_at_sma_not_included(self):
        # last_close == base_close == SMA → not strictly above
        holdings = catalyst.compute_trend_holdings({
            'TLT': _make_hist(100.0, base_close=100.0),
        })
        assert 'TLT' not in holdings

    def test_ordering_matches_catalyst_trend_assets(self):
        holdings = catalyst.compute_trend_holdings({
            'DBC': _make_hist(120.0),
            'TLT': _make_hist(120.0),
            'GLD': _make_hist(120.0),
        })
        assert holdings == catalyst.CATALYST_TREND_ASSETS


class TestComputeCatalystTargets:

    def test_gold_always_present_even_when_below_sma(self):
        hist_data = {
            'TLT': _make_hist(80.0),
            'GLD': _make_hist(80.0),
            'DBC': _make_hist(80.0),
        }
        targets = catalyst.compute_catalyst_targets(
            hist_data, 30_000.0, _prices(GLD=100.0, TLT=100.0, DBC=100.0),
        )
        symbols = [t['symbol'] for t in targets]
        assert 'GLD' in symbols

    def test_gold_sub_strategy_is_gold_when_below_sma(self):
        hist_data = {
            'TLT': _make_hist(80.0),
            'GLD': _make_hist(80.0),
            'DBC': _make_hist(80.0),
        }
        targets = catalyst.compute_catalyst_targets(
            hist_data, 30_000.0, _prices(GLD=100.0),
        )
        gld = next(t for t in targets if t['symbol'] == 'GLD')
        assert gld['sub_strategy'] == 'gold'

    def test_gld_above_sma_gets_trend_plus_gold_strategy(self):
        hist_data = {
            'TLT': _make_hist(80.0),
            'GLD': _make_hist(120.0),
            'DBC': _make_hist(80.0),
        }
        targets = catalyst.compute_catalyst_targets(
            hist_data, 30_000.0, _prices(GLD=10.0),
        )
        gld = next(t for t in targets if t['symbol'] == 'GLD')
        assert gld['sub_strategy'] == 'trend+gold'

    def test_zero_price_guard_skips_ticker(self):
        hist_data = {
            'TLT': _make_hist(120.0),
            'GLD': _make_hist(120.0),
            'DBC': _make_hist(120.0),
        }
        targets = catalyst.compute_catalyst_targets(
            hist_data, 30_000.0, _prices(TLT=0, GLD=50.0, DBC=50.0),
        )
        symbols = [t['symbol'] for t in targets]
        assert 'TLT' not in symbols

    def test_negative_price_guard_skips_ticker(self):
        hist_data = {
            'TLT': _make_hist(120.0),
            'GLD': _make_hist(120.0),
            'DBC': _make_hist(120.0),
        }
        targets = catalyst.compute_catalyst_targets(
            hist_data, 30_000.0, _prices(TLT=-5.0, GLD=50.0, DBC=50.0),
        )
        symbols = [t['symbol'] for t in targets]
        assert 'TLT' not in symbols

    def test_zero_gold_price_returns_empty(self):
        hist_data = {
            'TLT': _make_hist(80.0),
            'GLD': _make_hist(80.0),
            'DBC': _make_hist(80.0),
        }
        targets = catalyst.compute_catalyst_targets(
            hist_data, 30_000.0, _prices(GLD=0),
        )
        assert targets == []

    def test_return_shape_has_required_keys(self):
        hist_data = {
            'TLT': _make_hist(120.0),
            'GLD': _make_hist(120.0),
            'DBC': _make_hist(120.0),
        }
        targets = catalyst.compute_catalyst_targets(
            hist_data, 30_000.0, _prices(TLT=50.0, GLD=50.0, DBC=50.0),
        )
        required_keys = {'symbol', 'target_shares', 'target_value', 'sub_strategy'}
        for t in targets:
            assert required_keys.issubset(t.keys())

    def test_return_symbols_are_strings(self):
        hist_data = {'GLD': _make_hist(80.0)}
        targets = catalyst.compute_catalyst_targets(
            hist_data, 10_000.0, _prices(GLD=50.0),
        )
        for t in targets:
            assert isinstance(t['symbol'], str)

    def test_target_shares_are_integers(self):
        hist_data = {
            'TLT': _make_hist(120.0),
            'GLD': _make_hist(120.0),
        }
        targets = catalyst.compute_catalyst_targets(
            hist_data, 30_000.0, _prices(TLT=50.0, GLD=50.0),
        )
        for t in targets:
            assert isinstance(t['target_shares'], int)

    def test_empty_price_data_returns_empty(self):
        hist_data = {
            'TLT': _make_hist(120.0),
            'GLD': _make_hist(120.0),
            'DBC': _make_hist(120.0),
        }
        targets = catalyst.compute_catalyst_targets(hist_data, 30_000.0, {})
        assert targets == []

    def test_all_below_sma_only_gold_remains(self):
        hist_data = {
            'TLT': _make_hist(80.0),
            'GLD': _make_hist(80.0),
            'DBC': _make_hist(80.0),
        }
        targets = catalyst.compute_catalyst_targets(
            hist_data, 30_000.0, _prices(TLT=50.0, GLD=50.0, DBC=50.0),
        )
        assert len(targets) == 1
        assert targets[0]['symbol'] == 'GLD'

    def test_budget_zero_returns_no_targets(self):
        hist_data = {
            'TLT': _make_hist(120.0),
            'GLD': _make_hist(120.0),
        }
        targets = catalyst.compute_catalyst_targets(
            hist_data, 0.0, _prices(TLT=50.0, GLD=50.0),
        )
        assert targets == []

    def test_very_high_price_yields_zero_shares_excluded(self):
        hist_data = {'GLD': _make_hist(80.0)}
        targets = catalyst.compute_catalyst_targets(
            hist_data, 100.0, _prices(GLD=99999.0),
        )
        # budget too small for even 1 share at that price
        assert targets == []

    def test_nan_in_hist_close_excludes_from_trend(self):
        df = _make_hist(120.0)
        df.iloc[-1, df.columns.get_loc('Close')] = np.nan
        hist_data = {'TLT': df, 'GLD': _make_hist(80.0), 'DBC': _make_hist(80.0)}
        targets = catalyst.compute_catalyst_targets(
            hist_data, 30_000.0, _prices(TLT=50.0, GLD=50.0, DBC=50.0),
        )
        symbols = [t['symbol'] for t in targets]
        assert 'TLT' not in symbols
        assert 'GLD' in symbols


class TestConstants:

    def test_catalyst_trend_assets_list(self):
        assert catalyst.CATALYST_TREND_ASSETS == ['TLT', 'GLD', 'DBC']

    def test_gold_symbol_matches(self):
        assert catalyst.CATALYST_GOLD_SYMBOL == 'GLD'

    def test_sma_period_is_200(self):
        assert catalyst.CATALYST_SMA_PERIOD == 200

    def test_weights_sum_to_one(self):
        total = catalyst.CATALYST_TREND_WEIGHT + catalyst.CATALYST_GOLD_WEIGHT
        assert total == pytest.approx(1.0)
