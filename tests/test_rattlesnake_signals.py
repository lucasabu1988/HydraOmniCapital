"""
Unit tests for rattlesnake_signals.py — mean-reversion strategy module.

Covers: compute_rsi, find_rattlesnake_candidates, check_rattlesnake_exit,
check_rattlesnake_regime, compute_rattlesnake_exposure.
"""

import math
import numpy as np
import pandas as pd
import pytest

import rattlesnake_signals as rs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hist(closes, trend_start=100.0, volume=1_000_000):
    """Build a DataFrame long enough for SMA200 + padding."""
    n_needed = rs.R_TREND_SMA + 10
    base_len = max(n_needed - len(closes), 0)
    base = np.linspace(trend_start, closes[0], base_len).tolist()
    all_closes = base + list(closes)
    idx = pd.date_range('2024-01-01', periods=len(all_closes), freq='D')
    return pd.DataFrame({
        'Close': all_closes,
        'Volume': np.full(len(all_closes), volume, dtype=float),
    }, index=idx)


def _oversold_closes(start=140.0, pct_drop=0.10, n=6):
    """Generate a linearly declining series with total pct_drop over n points."""
    end = start * (1 - pct_drop)
    return np.linspace(start, end, n).tolist()


# =========================================================================
# 1. compute_rsi — known values / manual calculation
# =========================================================================

class TestComputeRsiKnownValues:

    def test_hand_calculated_rsi_period5(self):
        # 5 deltas: +2, -1, +2, -1, +2 => gains=[2,0,2,0,2] losses=[0,1,0,1,0]
        # avg_gain=6/5=1.2, avg_loss=2/5=0.4, RS=3, RSI=100-100/4=75
        prices = pd.Series([100.0, 102.0, 101.0, 103.0, 102.0, 104.0])
        assert rs.compute_rsi(prices, period=5) == pytest.approx(75.0)

    def test_rsi_period14_trending_up(self):
        prices = pd.Series([44, 44.34, 44.09, 43.61, 44.33, 44.83, 45.10,
                            45.42, 45.84, 46.08, 45.89, 46.03, 45.61,
                            46.28, 46.28])
        rsi = rs.compute_rsi(prices, period=14)
        assert 60.0 < rsi < 80.0  # well-known Wilder example range

    def test_rsi_pure_gain_series(self):
        prices = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        rsi = rs.compute_rsi(prices, period=5)
        assert rsi == pytest.approx(100.0)

    def test_rsi_pure_loss_series(self):
        prices = pd.Series([105.0, 104.0, 103.0, 102.0, 101.0, 100.0])
        rsi = rs.compute_rsi(prices, period=5)
        assert rsi == pytest.approx(0.0, abs=0.1)


# =========================================================================
# 2. RSI bounds clamping [0, 100]  (TASK-054)
# =========================================================================

class TestRsiBoundsClamping:

    def test_clamped_at_100_for_monotone_rise(self):
        prices = pd.Series([100 + i for i in range(30)])
        rsi = rs.compute_rsi(prices, period=5)
        assert 0.0 <= rsi <= 100.0

    def test_clamped_at_0_for_monotone_decline(self):
        prices = pd.Series([200 - i for i in range(30)])
        rsi = rs.compute_rsi(prices, period=5)
        assert 0.0 <= rsi <= 100.0

    def test_bounds_with_extreme_spike(self):
        prices = pd.Series([100.0, 100.0, 100.0, 100.0, 100.0, 1_000_000.0])
        rsi = rs.compute_rsi(prices, period=5)
        assert 0.0 <= rsi <= 100.0

    def test_bounds_with_extreme_crash(self):
        prices = pd.Series([100.0, 100.0, 100.0, 100.0, 100.0, 0.001])
        rsi = rs.compute_rsi(prices, period=5)
        assert 0.0 <= rsi <= 100.0


# =========================================================================
# 3. RSI with NaN input handling
# =========================================================================

class TestRsiNanHandling:

    def test_nan_at_start_returns_valid(self):
        prices = pd.Series([float('nan'), 100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        rsi = rs.compute_rsi(prices, period=5)
        assert 0.0 <= rsi <= 100.0

    def test_nan_in_middle_returns_valid(self):
        prices = pd.Series([100.0, 101.0, float('nan'), 103.0, 104.0, 105.0, 106.0])
        rsi = rs.compute_rsi(prices, period=5)
        assert 0.0 <= rsi <= 100.0

    def test_all_nan_returns_neutral(self):
        prices = pd.Series([float('nan')] * 10)
        rsi = rs.compute_rsi(prices, period=5)
        assert rsi == 50.0

    def test_nan_at_end_returns_neutral(self):
        prices = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, float('nan')])
        rsi = rs.compute_rsi(prices, period=5)
        assert rsi == 50.0


# =========================================================================
# 4. RSI with constant prices
# =========================================================================

class TestRsiConstantPrices:

    def test_constant_prices_return_neutral(self):
        prices = pd.Series([50.0] * 10)
        rsi = rs.compute_rsi(prices, period=5)
        assert rsi == pytest.approx(50.0)

    def test_constant_then_single_uptick(self):
        prices = pd.Series([50.0] * 9 + [51.0])
        rsi = rs.compute_rsi(prices, period=5)
        assert rsi > 50.0  # slightly bullish


# =========================================================================
# 5. find_rattlesnake_candidates — dip detection (>= 8% drop in 5d)
# =========================================================================

class TestDipDetection:

    def test_exactly_8pct_drop_qualifies(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        # Build a clean 8% drop: price 6 days ago = 100, current = 91.5 (~8.5% to clear threshold)
        # The function checks current_price / past_price - 1 <= -0.08
        closes = [100.0, 98.0, 96.0, 94.0, 92.0, 91.5]
        hist = _make_hist(closes, trend_start=70)
        candidates = rs.find_rattlesnake_candidates(
            hist_data={'AAPL': hist},
            current_prices={'AAPL': 91.5},
            held_symbols=set(),
        )
        assert len(candidates) == 1
        assert candidates[0]['drop_pct'] <= rs.R_DROP_THRESHOLD

    def test_7pct_drop_does_not_qualify(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        closes = _oversold_closes(100.0, pct_drop=0.07, n=6)
        hist = _make_hist(closes, trend_start=70)
        candidates = rs.find_rattlesnake_candidates(
            hist_data={'AAPL': hist},
            current_prices={'AAPL': closes[-1]},
            held_symbols=set(),
        )
        assert candidates == []

    def test_15pct_crash_qualifies(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        closes = _oversold_closes(100.0, pct_drop=0.15, n=6)
        hist = _make_hist(closes, trend_start=60)
        candidates = rs.find_rattlesnake_candidates(
            hist_data={'AAPL': hist},
            current_prices={'AAPL': closes[-1]},
            held_symbols=set(),
        )
        assert len(candidates) == 1
        assert candidates[0]['drop_pct'] < -0.14


# =========================================================================
# 6. RSI < 25 filter works
# =========================================================================

class TestRsiFilter:

    def test_rsi_above_25_excluded(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        # Zig-zag pattern gives higher RSI despite net drop
        closes = [140.0, 132.0, 138.0, 132.0, 136.0, 128.0]
        hist = _make_hist(closes, trend_start=100)
        rsi = rs.compute_rsi(hist['Close'], rs.R_RSI_PERIOD)
        candidates = rs.find_rattlesnake_candidates(
            hist_data={'AAPL': hist},
            current_prices={'AAPL': 128.0},
            held_symbols=set(),
        )
        assert rsi > rs.R_RSI_THRESHOLD
        assert candidates == []

    def test_rsi_below_25_included(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        closes = _oversold_closes(140.0, pct_drop=0.10, n=6)
        hist = _make_hist(closes, trend_start=100)
        rsi = rs.compute_rsi(hist['Close'], rs.R_RSI_PERIOD)
        candidates = rs.find_rattlesnake_candidates(
            hist_data={'AAPL': hist},
            current_prices={'AAPL': closes[-1]},
            held_symbols=set(),
        )
        assert rsi < rs.R_RSI_THRESHOLD
        assert len(candidates) == 1


# =========================================================================
# 7. SMA200 trend check (only buy above trend)
# =========================================================================

class TestSmaTrendFilter:

    def test_price_below_sma200_rejected(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        closes = _oversold_closes(150.0, pct_drop=0.10, n=6)
        # trend_start=170 puts SMA200 well above current price
        hist = _make_hist(closes, trend_start=170)
        candidates = rs.find_rattlesnake_candidates(
            hist_data={'AAPL': hist},
            current_prices={'AAPL': closes[-1]},
            held_symbols=set(),
        )
        assert candidates == []

    def test_price_above_sma200_accepted(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        closes = _oversold_closes(140.0, pct_drop=0.10, n=6)
        # trend_start=100 puts SMA200 below current price
        hist = _make_hist(closes, trend_start=100)
        candidates = rs.find_rattlesnake_candidates(
            hist_data={'AAPL': hist},
            current_prices={'AAPL': closes[-1]},
            held_symbols=set(),
        )
        assert len(candidates) == 1


# =========================================================================
# 8. Volume filter
# =========================================================================

class TestVolumeFilter:

    def test_low_volume_stock_excluded(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        closes = _oversold_closes(140.0, pct_drop=0.10, n=6)
        hist = _make_hist(closes, trend_start=100, volume=100_000)  # below R_MIN_AVG_VOLUME
        candidates = rs.find_rattlesnake_candidates(
            hist_data={'AAPL': hist},
            current_prices={'AAPL': closes[-1]},
            held_symbols=set(),
        )
        assert candidates == []

    def test_sufficient_volume_accepted(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        closes = _oversold_closes(140.0, pct_drop=0.10, n=6)
        hist = _make_hist(closes, trend_start=100, volume=2_000_000)
        candidates = rs.find_rattlesnake_candidates(
            hist_data={'AAPL': hist},
            current_prices={'AAPL': closes[-1]},
            held_symbols=set(),
        )
        assert len(candidates) == 1

    def test_nan_volume_excluded(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        closes = _oversold_closes(140.0, pct_drop=0.10, n=6)
        hist = _make_hist(closes, trend_start=100, volume=2_000_000)
        # Set last 20 volumes to NaN
        hist.loc[hist.index[-20:], 'Volume'] = float('nan')
        candidates = rs.find_rattlesnake_candidates(
            hist_data={'AAPL': hist},
            current_prices={'AAPL': closes[-1]},
            held_symbols=set(),
        )
        assert candidates == []


# =========================================================================
# 9. max_candidates limit respected
# =========================================================================

class TestMaxCandidates:

    def test_max_candidates_truncates_result(self, monkeypatch):
        tickers = ['S1', 'S2', 'S3', 'S4']
        monkeypatch.setattr(rs, 'R_UNIVERSE', tickers)
        histories = {}
        prices = {}
        for i, t in enumerate(tickers):
            drop = 0.10 + i * 0.02
            closes = _oversold_closes(140.0, pct_drop=drop, n=6)
            histories[t] = _make_hist(closes, trend_start=100)
            prices[t] = closes[-1]
        candidates = rs.find_rattlesnake_candidates(
            hist_data=histories,
            current_prices=prices,
            held_symbols=set(),
            max_candidates=2,
        )
        assert len(candidates) == 2

    def test_max_candidates_keeps_best_scores(self, monkeypatch):
        tickers = ['S1', 'S2', 'S3']
        monkeypatch.setattr(rs, 'R_UNIVERSE', tickers)
        drops = [0.10, 0.12, 0.15]
        histories = {}
        prices = {}
        for t, d in zip(tickers, drops):
            closes = _oversold_closes(140.0, pct_drop=d, n=6)
            histories[t] = _make_hist(closes, trend_start=100)
            prices[t] = closes[-1]
        all_candidates = rs.find_rattlesnake_candidates(
            hist_data=histories,
            current_prices=prices,
            held_symbols=set(),
            max_candidates=10,
        )
        truncated = rs.find_rattlesnake_candidates(
            hist_data=histories,
            current_prices=prices,
            held_symbols=set(),
            max_candidates=1,
        )
        assert len(truncated) == 1
        # The single returned candidate should be the top-ranked one
        assert truncated[0]['symbol'] == all_candidates[0]['symbol']
        assert truncated[0]['score'] >= all_candidates[-1]['score']


# =========================================================================
# 10. No candidates when market is calm
# =========================================================================

class TestCalmMarket:

    def test_flat_market_produces_no_candidates(self, monkeypatch):
        tickers = ['AAPL', 'MSFT', 'GOOG']
        monkeypatch.setattr(rs, 'R_UNIVERSE', tickers)
        histories = {}
        prices = {}
        for t in tickers:
            closes = [150.0] * 6  # flat
            histories[t] = _make_hist(closes, trend_start=100)
            prices[t] = 150.0
        candidates = rs.find_rattlesnake_candidates(
            hist_data=histories,
            current_prices=prices,
            held_symbols=set(),
        )
        assert candidates == []

    def test_slight_dip_not_enough(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        closes = _oversold_closes(100.0, pct_drop=0.03, n=6)
        hist = _make_hist(closes, trend_start=70)
        candidates = rs.find_rattlesnake_candidates(
            hist_data={'AAPL': hist},
            current_prices={'AAPL': closes[-1]},
            held_symbols=set(),
        )
        assert candidates == []


# =========================================================================
# 11. Empty universe -> empty result
# =========================================================================

class TestEmptyUniverse:

    def test_empty_hist_data_returns_empty(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        candidates = rs.find_rattlesnake_candidates(
            hist_data={},
            current_prices={'AAPL': 100.0},
            held_symbols=set(),
        )
        assert candidates == []

    def test_empty_current_prices_returns_empty(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        closes = _oversold_closes(140.0, pct_drop=0.10, n=6)
        hist = _make_hist(closes, trend_start=100)
        candidates = rs.find_rattlesnake_candidates(
            hist_data={'AAPL': hist},
            current_prices={},
            held_symbols=set(),
        )
        assert candidates == []

    def test_empty_universe_returns_empty(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', [])
        candidates = rs.find_rattlesnake_candidates(
            hist_data={},
            current_prices={},
            held_symbols=set(),
        )
        assert candidates == []


# =========================================================================
# 12. Short price history -> graceful skip
# =========================================================================

class TestShortHistory:

    def test_history_shorter_than_sma200_skipped(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        closes = _oversold_closes(140.0, pct_drop=0.10, n=6)
        idx = pd.date_range('2024-01-01', periods=len(closes), freq='D')
        hist = pd.DataFrame({
            'Close': closes,
            'Volume': [1_000_000] * len(closes),
        }, index=idx)
        candidates = rs.find_rattlesnake_candidates(
            hist_data={'AAPL': hist},
            current_prices={'AAPL': closes[-1]},
            held_symbols=set(),
        )
        assert candidates == []

    def test_compute_rsi_short_series_returns_neutral(self):
        prices = pd.Series([100.0, 101.0])
        rsi = rs.compute_rsi(prices, period=5)
        assert rsi == 50.0

    def test_history_exactly_sma200_plus_10_accepted(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        closes = _oversold_closes(140.0, pct_drop=0.10, n=6)
        hist = _make_hist(closes, trend_start=100)
        assert len(hist) == rs.R_TREND_SMA + 10
        candidates = rs.find_rattlesnake_candidates(
            hist_data={'AAPL': hist},
            current_prices={'AAPL': closes[-1]},
            held_symbols=set(),
        )
        assert len(candidates) == 1


# =========================================================================
# Extra coverage: held symbols, zero price, exit logic, exposure
# =========================================================================

class TestHeldSymbolsExcluded:

    def test_held_symbol_excluded_from_candidates(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        closes = _oversold_closes(140.0, pct_drop=0.10, n=6)
        hist = _make_hist(closes, trend_start=100)
        candidates = rs.find_rattlesnake_candidates(
            hist_data={'AAPL': hist},
            current_prices={'AAPL': closes[-1]},
            held_symbols={'AAPL'},
        )
        assert candidates == []


class TestZeroPrice:

    def test_zero_current_price_skipped(self, monkeypatch):
        monkeypatch.setattr(rs, 'R_UNIVERSE', ['AAPL'])
        closes = _oversold_closes(140.0, pct_drop=0.10, n=6)
        hist = _make_hist(closes, trend_start=100)
        candidates = rs.find_rattlesnake_candidates(
            hist_data={'AAPL': hist},
            current_prices={'AAPL': 0.0},
            held_symbols=set(),
        )
        assert candidates == []


class TestExitLogic:

    def test_no_exit_within_bounds(self):
        assert rs.check_rattlesnake_exit('AAPL', 100.0, 101.0, 3) is None

    def test_profit_exit(self):
        assert rs.check_rattlesnake_exit('AAPL', 100.0, 104.5, 2) == 'PROFIT'

    def test_stop_exit(self):
        assert rs.check_rattlesnake_exit('AAPL', 100.0, 94.5, 2) == 'STOP'

    def test_time_exit(self):
        assert rs.check_rattlesnake_exit('AAPL', 100.0, 100.5, 8) == 'TIME'

    def test_profit_takes_priority_over_time(self):
        assert rs.check_rattlesnake_exit('AAPL', 100.0, 106.0, 10) == 'PROFIT'

    def test_stop_takes_priority_over_time(self):
        assert rs.check_rattlesnake_exit('AAPL', 100.0, 93.0, 10) == 'STOP'


class TestExposure:

    def test_exposure_capped_at_1(self):
        positions = [{'symbol': 'AAPL', 'shares': 1000}]
        exposure = rs.compute_rattlesnake_exposure(
            positions, {'AAPL': 1000.0}, account_value=100.0
        )
        assert exposure == 1.0

    def test_exposure_zero_account_returns_zero(self):
        positions = [{'symbol': 'AAPL', 'shares': 100}]
        exposure = rs.compute_rattlesnake_exposure(
            positions, {'AAPL': 100.0}, account_value=0.0
        )
        assert exposure == 0.0

    def test_exposure_missing_symbol_treated_as_zero(self):
        positions = [{'symbol': 'AAPL', 'shares': 100}]
        exposure = rs.compute_rattlesnake_exposure(
            positions, {}, account_value=50_000.0
        )
        assert exposure == 0.0


class TestRegime:

    def test_zero_vix_is_non_panic(self):
        spy = pd.DataFrame({'Close': [110.0] * rs.R_TREND_SMA})
        regime = rs.check_rattlesnake_regime(spy, vix_current=0.0)
        assert regime['vix_panic'] is False
        assert regime['entries_allowed'] is True

    def test_none_vix_is_non_panic(self):
        spy = pd.DataFrame({'Close': [110.0] * rs.R_TREND_SMA})
        regime = rs.check_rattlesnake_regime(spy, vix_current=None)
        assert regime['vix_panic'] is False
        assert regime['entries_allowed'] is True
