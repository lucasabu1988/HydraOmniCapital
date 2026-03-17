import numpy as np
import pandas as pd
import pytest

import rattlesnake_signals as rattlesnake


def make_history(recent_closes, trend_start, trend_end=None, volume=1_000_000):
    trend_end = recent_closes[0] if trend_end is None else trend_end
    base_len = rattlesnake.R_TREND_SMA + 10 - len(recent_closes)
    base = np.linspace(trend_start, trend_end, base_len)
    closes = np.concatenate([base, np.array(recent_closes, dtype=float)])
    index = pd.date_range('2025-01-01', periods=len(closes), freq='D')
    return pd.DataFrame({
        'Close': closes,
        'Volume': np.full(len(closes), volume, dtype=float),
    }, index=index)


def make_spy_history(last_close, base_close=100.0, days=None):
    days = rattlesnake.R_TREND_SMA if days is None else days
    closes = [base_close] * (days - 1) + [last_close]
    index = pd.date_range('2025-01-01', periods=len(closes), freq='D')
    return pd.DataFrame({'Close': closes}, index=index)


class TestRattlesnakeSignals:

    def test_compute_rsi_matches_hand_calculation_for_known_series(self):
        prices = pd.Series([100.0, 102.0, 101.0, 103.0, 102.0, 104.0])

        rsi = rattlesnake.compute_rsi(prices, period=5)

        assert rsi == pytest.approx(75.0)

    def test_compute_rsi_returns_neutral_for_flat_prices(self):
        prices = pd.Series([100.0, 100.0, 100.0, 100.0, 100.0, 100.0])

        rsi = rattlesnake.compute_rsi(prices, period=5)

        assert rsi == pytest.approx(50.0)

    def test_compute_rsi_approaches_one_hundred_for_all_up_days(self):
        prices = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])

        rsi = rattlesnake.compute_rsi(prices, period=5)

        assert rsi > 99.9

    def test_compute_rsi_approaches_zero_for_all_down_days(self):
        prices = pd.Series([105.0, 104.0, 103.0, 102.0, 101.0, 100.0])

        rsi = rattlesnake.compute_rsi(prices, period=5)

        assert rsi < 0.1

    @pytest.mark.parametrize(
        'prices',
        [
            pd.Series(dtype=float),
            pd.Series([100.0, 101.0, 102.0]),
        ],
    )
    def test_compute_rsi_returns_neutral_for_empty_or_short_series(self, prices):
        rsi = rattlesnake.compute_rsi(prices, period=5)

        assert rsi == pytest.approx(50.0)

    def test_regime_is_risk_on_above_sma_without_vix_panic(self):
        regime = rattlesnake.check_rattlesnake_regime(
            make_spy_history(110.0),
            vix_current=20.0,
        )

        assert regime == {
            'regime': 'RISK_ON',
            'vix_panic': False,
            'entries_allowed': True,
            'max_positions': rattlesnake.R_MAX_POSITIONS,
        }

    def test_regime_is_risk_off_below_sma_and_uses_risk_off_position_cap(self):
        regime = rattlesnake.check_rattlesnake_regime(
            make_spy_history(90.0),
            vix_current=20.0,
        )

        assert regime['regime'] == 'RISK_OFF'
        assert regime['vix_panic'] is False
        assert regime['entries_allowed'] is True
        assert regime['max_positions'] == rattlesnake.R_MAX_POS_RISK_OFF

    def test_vix_panic_blocks_entries_even_when_spy_is_above_sma(self):
        regime = rattlesnake.check_rattlesnake_regime(
            make_spy_history(110.0),
            vix_current=rattlesnake.R_VIX_PANIC + 1,
        )

        assert regime['regime'] == 'RISK_ON'
        assert regime['vix_panic'] is True
        assert regime['entries_allowed'] is False
        assert regime['max_positions'] == rattlesnake.R_MAX_POSITIONS

    def test_short_spy_history_defaults_to_risk_on(self):
        regime = rattlesnake.check_rattlesnake_regime(
            make_spy_history(90.0, days=50),
            vix_current=20.0,
        )

        assert regime['regime'] == 'RISK_ON'
        assert regime['entries_allowed'] is True
        assert regime['max_positions'] == rattlesnake.R_MAX_POSITIONS

    def test_nan_vix_is_treated_as_non_panic(self):
        regime = rattlesnake.check_rattlesnake_regime(
            make_spy_history(110.0),
            vix_current=float('nan'),
        )

        assert regime['vix_panic'] is False
        assert regime['entries_allowed'] is True

    def test_buy_signal_fires_for_oversold_stock_above_sma200(self, monkeypatch):
        monkeypatch.setattr(rattlesnake, 'R_UNIVERSE', ['AAPL'])
        history = make_history([140, 137, 134, 131, 128, 126], trend_start=100)

        candidates = rattlesnake.find_rattlesnake_candidates(
            hist_data={'AAPL': history},
            current_prices={'AAPL': 126.0},
            held_symbols=set(),
        )

        assert len(candidates) == 1
        assert candidates[0]['symbol'] == 'AAPL'
        assert candidates[0]['drop_pct'] == pytest.approx(-0.10)
        assert candidates[0]['rsi'] < rattlesnake.R_RSI_THRESHOLD
        assert candidates[0]['price'] > history['Close'].iloc[-rattlesnake.R_TREND_SMA:].mean()

    def test_no_signal_when_drop_is_less_than_threshold(self, monkeypatch):
        monkeypatch.setattr(rattlesnake, 'R_UNIVERSE', ['AAPL'])
        history = make_history([140, 139, 138, 137, 136, 133], trend_start=100)

        drop = 133.0 / 140.0 - 1.0
        rsi = rattlesnake.compute_rsi(history['Close'], rattlesnake.R_RSI_PERIOD)

        candidates = rattlesnake.find_rattlesnake_candidates(
            hist_data={'AAPL': history},
            current_prices={'AAPL': 133.0},
            held_symbols=set(),
        )

        assert drop > rattlesnake.R_DROP_THRESHOLD
        assert rsi < rattlesnake.R_RSI_THRESHOLD
        assert 133.0 > history['Close'].iloc[-rattlesnake.R_TREND_SMA:].mean()
        assert candidates == []

    def test_no_signal_when_rsi_is_not_oversold(self, monkeypatch):
        monkeypatch.setattr(rattlesnake, 'R_UNIVERSE', ['AAPL'])
        history = make_history([140, 132, 138, 132, 136, 128], trend_start=100)

        drop = 128.0 / 140.0 - 1.0
        rsi = rattlesnake.compute_rsi(history['Close'], rattlesnake.R_RSI_PERIOD)

        candidates = rattlesnake.find_rattlesnake_candidates(
            hist_data={'AAPL': history},
            current_prices={'AAPL': 128.0},
            held_symbols=set(),
        )

        assert drop <= rattlesnake.R_DROP_THRESHOLD
        assert rsi > rattlesnake.R_RSI_THRESHOLD
        assert 128.0 > history['Close'].iloc[-rattlesnake.R_TREND_SMA:].mean()
        assert candidates == []

    def test_no_signal_when_price_is_below_sma200(self, monkeypatch):
        monkeypatch.setattr(rattlesnake, 'R_UNIVERSE', ['AAPL'])
        history = make_history([150, 147, 144, 141, 138, 135], trend_start=170)

        drop = 135.0 / 150.0 - 1.0
        rsi = rattlesnake.compute_rsi(history['Close'], rattlesnake.R_RSI_PERIOD)

        candidates = rattlesnake.find_rattlesnake_candidates(
            hist_data={'AAPL': history},
            current_prices={'AAPL': 135.0},
            held_symbols=set(),
        )

        assert drop <= rattlesnake.R_DROP_THRESHOLD
        assert rsi < rattlesnake.R_RSI_THRESHOLD
        assert 135.0 < history['Close'].iloc[-rattlesnake.R_TREND_SMA:].mean()
        assert candidates == []

    def test_exit_hits_profit_target_at_four_percent(self):
        reason = rattlesnake.check_rattlesnake_exit(
            symbol='AAPL',
            entry_price=100.0,
            current_price=104.0,
            days_held=3,
        )

        assert reason == 'PROFIT'

    def test_exit_hits_stop_loss_at_negative_five_percent(self):
        reason = rattlesnake.check_rattlesnake_exit(
            symbol='AAPL',
            entry_price=100.0,
            current_price=95.0,
            days_held=3,
        )

        assert reason == 'STOP'

    def test_exit_hits_time_stop_at_eight_days(self):
        reason = rattlesnake.check_rattlesnake_exit(
            symbol='AAPL',
            entry_price=100.0,
            current_price=101.0,
            days_held=8,
        )

        assert reason == 'TIME'

    def test_rattlesnake_exposure_sums_position_market_values(self):
        positions = [
            {'symbol': 'AAPL', 'shares': 100},
            {'symbol': 'MSFT', 'shares': 50},
            {'symbol': 'GOOG', 'shares': 10},
        ]
        current_prices = {'AAPL': 100.0, 'MSFT': 200.0, 'GOOG': 300.0}

        exposure = rattlesnake.compute_rattlesnake_exposure(
            positions, current_prices, account_value=50_000.0
        )

        assert exposure == pytest.approx(0.46)

    def test_rattlesnake_exposure_is_zero_for_empty_positions(self):
        exposure = rattlesnake.compute_rattlesnake_exposure(
            [], {'AAPL': 100.0}, account_value=50_000.0
        )

        assert exposure == 0.0

    def test_multiple_candidates_are_ranked_by_largest_drop_first(self, monkeypatch):
        monkeypatch.setattr(rattlesnake, 'R_UNIVERSE', ['AAPL', 'MSFT', 'GOOG'])
        histories = {
            'AAPL': make_history([140, 137, 134, 131, 128, 126], trend_start=100),
            'MSFT': make_history([200, 195, 190, 185, 180, 176], trend_start=120),
            'GOOG': make_history([160, 156, 152, 148, 144, 142], trend_start=110),
        }
        current_prices = {'AAPL': 126.0, 'MSFT': 176.0, 'GOOG': 142.0}

        candidates = rattlesnake.find_rattlesnake_candidates(
            hist_data=histories,
            current_prices=current_prices,
            held_symbols=set(),
            max_candidates=3,
        )

        assert [candidate['symbol'] for candidate in candidates] == ['MSFT', 'GOOG', 'AAPL']
        assert [candidate['score'] for candidate in candidates] == pytest.approx([0.12, 0.1125, 0.10])

    def test_empty_universe_returns_no_candidates(self, monkeypatch):
        monkeypatch.setattr(rattlesnake, 'R_UNIVERSE', [])

        candidates = rattlesnake.find_rattlesnake_candidates(
            hist_data={},
            current_prices={},
            held_symbols=set(),
        )

        assert candidates == []
