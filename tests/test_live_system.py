"""
OmniCapital v8.2 COMPASS - Live System Tests
=============================================
Tests for the COMPASS v8.2 live trading system.
"""

import unittest
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from unittest.mock import MagicMock, patch
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from omnicapital_live import (
    COMPASSLive, CONFIG, BROAD_POOL,
    compute_momentum_scores, compute_volatility_weights,
    compute_dynamic_leverage, compute_live_regime_score,
    filter_by_sector_concentration,
)
from omnicapital_broker import PaperBroker, Order, Position
from omnicapital_notifications import EmailNotifier


class TestMomentumScoring(unittest.TestCase):
    """Test cross-sectional momentum scoring"""

    def setUp(self):
        dates = pd.date_range('2024-01-01', periods=120, freq='B')
        self.hist_data = {}
        np.random.seed(666)
        prices_a = 100 * np.cumprod(1 + np.random.normal(0.002, 0.01, 120))
        self.hist_data['STOCK_A'] = pd.DataFrame({'Close': prices_a}, index=dates)
        prices_b = 100 * np.cumprod(1 + np.random.normal(-0.002, 0.01, 120))
        self.hist_data['STOCK_B'] = pd.DataFrame({'Close': prices_b}, index=dates)
        prices_c = 100 * np.cumprod(1 + np.random.normal(0, 0.005, 120))
        self.hist_data['STOCK_C'] = pd.DataFrame({'Close': prices_c}, index=dates)

    def test_momentum_returns_scores(self):
        scores = compute_momentum_scores(
            self.hist_data, ['STOCK_A', 'STOCK_B', 'STOCK_C'], lookback=90, skip=5
        )
        self.assertEqual(len(scores), 3)
        for s in scores.values():
            self.assertIsInstance(s, float)

    def test_uptrend_has_higher_score(self):
        scores = compute_momentum_scores(
            self.hist_data, ['STOCK_A', 'STOCK_B'], lookback=90, skip=5
        )
        self.assertIn('STOCK_A', scores)
        self.assertIn('STOCK_B', scores)

    def test_insufficient_data_excluded(self):
        short_data = {'SHORT': pd.DataFrame({'Close': [100, 101, 102]},
                      index=pd.date_range('2024-01-01', periods=3, freq='B'))}
        scores = compute_momentum_scores(short_data, ['SHORT'], lookback=90, skip=5)
        self.assertEqual(len(scores), 0)

    def test_empty_tradeable_list(self):
        scores = compute_momentum_scores(self.hist_data, [], lookback=90, skip=5)
        self.assertEqual(len(scores), 0)


class TestVolatilityWeights(unittest.TestCase):
    """Test inverse-volatility weighting"""

    def setUp(self):
        dates = pd.date_range('2024-01-01', periods=30, freq='B')
        self.hist_data = {}
        np.random.seed(666)
        prices_low = 100 + np.cumsum(np.random.normal(0, 0.5, 30))
        self.hist_data['LOW_VOL'] = pd.DataFrame({'Close': prices_low}, index=dates)
        prices_high = 100 + np.cumsum(np.random.normal(0, 3.0, 30))
        self.hist_data['HIGH_VOL'] = pd.DataFrame({'Close': prices_high}, index=dates)

    def test_weights_sum_to_one(self):
        weights = compute_volatility_weights(self.hist_data, ['LOW_VOL', 'HIGH_VOL'], vol_lookback=20)
        total = sum(weights.values())
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_low_vol_gets_higher_weight(self):
        weights = compute_volatility_weights(self.hist_data, ['LOW_VOL', 'HIGH_VOL'], vol_lookback=20)
        if 'LOW_VOL' in weights and 'HIGH_VOL' in weights:
            self.assertGreater(weights['LOW_VOL'], weights['HIGH_VOL'])

    def test_single_stock_weight_is_one(self):
        weights = compute_volatility_weights(self.hist_data, ['LOW_VOL'], vol_lookback=20)
        self.assertAlmostEqual(weights.get('LOW_VOL', 0), 1.0, places=5)


class TestDynamicLeverage(unittest.TestCase):
    """Test volatility-targeting leverage"""

    def _make_spy(self, daily_vol):
        np.random.seed(666)
        dates = pd.date_range('2024-01-01', periods=30, freq='B')
        returns = np.random.normal(0, daily_vol, 30)
        prices = 400 * np.cumprod(1 + returns)
        return pd.DataFrame({'Close': prices}, index=dates)

    def test_low_vol_high_leverage(self):
        spy = self._make_spy(0.005)
        lev = compute_dynamic_leverage(spy, target_vol=0.15, vol_lookback=20, lev_max=2.0)
        self.assertGreater(lev, 1.0)

    def test_high_vol_low_leverage(self):
        spy = self._make_spy(0.03)
        lev = compute_dynamic_leverage(spy, target_vol=0.15, vol_lookback=20)
        self.assertLess(lev, 1.0)

    def test_leverage_clipped_to_max(self):
        spy = self._make_spy(0.002)
        lev = compute_dynamic_leverage(spy, target_vol=0.15, vol_lookback=20, lev_max=2.0)
        self.assertLessEqual(lev, 2.0)

    def test_leverage_clipped_to_min(self):
        spy = self._make_spy(0.05)
        lev = compute_dynamic_leverage(spy, target_vol=0.15, vol_lookback=20, lev_min=0.3)
        self.assertGreaterEqual(lev, 0.3)


class TestRegimeDetection(unittest.TestCase):
    """Test SPY SMA200 regime filter"""

    def _make_spy_above_sma(self, days=300):
        dates = pd.date_range('2023-01-01', periods=days, freq='B')
        prices = np.linspace(380, 500, days)
        return pd.DataFrame({'Close': prices}, index=dates)

    def _make_spy_below_sma(self, days=300):
        dates = pd.date_range('2023-01-01', periods=days, freq='B')
        prices = np.linspace(500, 380, days)
        return pd.DataFrame({'Close': prices}, index=dates)

    def test_uptrend_is_risk_on(self):
        spy = self._make_spy_above_sma()
        score = compute_live_regime_score(spy)
        self.assertGreater(score, 0.5)

    def test_downtrend_is_risk_off(self):
        spy = self._make_spy_below_sma()
        score = compute_live_regime_score(spy)
        self.assertLess(score, 0.5)

    def test_insufficient_data_defaults_neutral(self):
        dates = pd.date_range('2024-01-01', periods=50, freq='B')
        spy = pd.DataFrame({'Close': np.linspace(400, 410, 50)}, index=dates)
        score = compute_live_regime_score(spy)
        self.assertEqual(score, 0.5)


class TestSectorConcentrationFiltering(unittest.TestCase):
    """Test v8.4 sector concentration guard."""

    def test_existing_two_positions_allow_only_one_more_from_same_sector(self):
        ranked_candidates = [
            ('NVDA', 0.95),
            ('GOOGL', 0.93),
            ('META', 0.91),
            ('AMD', 0.89),
            ('ORCL', 0.87),
        ]
        current_positions = {'AAPL': {}, 'MSFT': {}}

        selected = filter_by_sector_concentration(ranked_candidates, current_positions)

        self.assertEqual(selected, ['NVDA'])

    def test_different_sectors_all_pass_in_original_order(self):
        ranked_candidates = [
            ('AAPL', 0.95),
            ('JPM', 0.90),
            ('XOM', 0.85),
        ]

        selected = filter_by_sector_concentration(ranked_candidates, {})

        self.assertEqual(selected, ['AAPL', 'JPM', 'XOM'])

    def test_same_sector_without_existing_positions_keeps_top_three_only(self):
        ranked_candidates = [
            ('AAPL', 0.98),
            ('MSFT', 0.96),
            ('NVDA', 0.94),
            ('GOOGL', 0.92),
        ]

        selected = filter_by_sector_concentration(ranked_candidates, {})

        self.assertEqual(selected, ['AAPL', 'MSFT', 'NVDA'])

    def test_empty_candidates_returns_empty_list(self):
        selected = filter_by_sector_concentration([], {'AAPL': {}})

        self.assertEqual(selected, [])

    def test_unknown_sector_positions_are_counted_and_order_is_preserved(self):
        ranked_candidates = [
            ('UNK3', 0.95),
            ('UNK4', 0.90),
            ('AAPL', 0.85),
        ]
        current_positions = {'UNK1': {}, 'UNK2': {}}

        selected = filter_by_sector_concentration(ranked_candidates, current_positions)

        self.assertEqual(selected, ['UNK3', 'AAPL'])


class TestCOMPASSLive(unittest.TestCase):
    """Test the live trading system (v8.4 interface)"""

    def setUp(self):
        self.config = CONFIG.copy()
        self.config['PAPER_INITIAL_CASH'] = 100_000

    def _make_spy_hist(self, last_close, base_close=100.0, days=200):
        dates = pd.date_range('2024-01-01', periods=days, freq='B')
        closes = [base_close] * (days - 1) + [last_close]
        return pd.DataFrame({'Close': closes}, index=dates)

    @patch('omnicapital_live.YahooDataFeed')
    def test_initialization(self, mock_feed):
        mock_feed.return_value = MagicMock()
        trader = COMPASSLive(self.config)
        self.assertEqual(trader.peak_value, 100_000)
        self.assertEqual(trader.current_regime_score, 0.5)
        self.assertEqual(trader.trading_day_counter, 0)
        self.assertEqual(len(trader.position_meta), 0)

    @patch('omnicapital_live.YahooDataFeed')
    def test_max_positions_high_regime(self, mock_feed):
        mock_feed.return_value = MagicMock()
        trader = COMPASSLive(self.config)
        trader.current_regime_score = 0.8
        max_pos = trader.get_max_positions()
        self.assertGreaterEqual(max_pos, 4)

    @patch('omnicapital_live.YahooDataFeed')
    def test_max_positions_low_regime(self, mock_feed):
        mock_feed.return_value = MagicMock()
        trader = COMPASSLive(self.config)
        trader.current_regime_score = 0.1
        max_pos = trader.get_max_positions()
        self.assertLessEqual(max_pos, 3)

    @patch('omnicapital_live.YahooDataFeed')
    def test_get_max_positions_applies_bull_override_when_spy_confirmed(self, mock_feed):
        mock_feed.return_value = MagicMock()
        trader = COMPASSLive(self.config)
        trader.current_regime_score = 0.55
        trader._spy_hist = self._make_spy_hist(last_close=104.0)

        max_pos = trader.get_max_positions()

        self.assertEqual(max_pos, 5)

    @patch('omnicapital_live.YahooDataFeed')
    def test_get_max_positions_skips_bull_override_below_spy_threshold(self, mock_feed):
        mock_feed.return_value = MagicMock()
        trader = COMPASSLive(self.config)
        trader.current_regime_score = 0.55
        trader._spy_hist = self._make_spy_hist(last_close=102.5)

        max_pos = trader.get_max_positions()

        self.assertEqual(max_pos, 4)

    @patch('omnicapital_live.YahooDataFeed')
    def test_get_max_positions_bull_override_score_boundaries(self, mock_feed):
        mock_feed.return_value = MagicMock()
        expected_positions = {
            0.39: 3,
            0.40: 3,
            0.41: 4,
        }

        for regime_score, expected in expected_positions.items():
            with self.subTest(regime_score=regime_score):
                trader = COMPASSLive(self.config)
                trader.current_regime_score = regime_score
                trader._spy_hist = self._make_spy_hist(last_close=104.0)

                self.assertEqual(trader.get_max_positions(), expected)


class TestPaperBroker(unittest.TestCase):
    """Test paper broker operations"""

    def test_buy_and_sell(self):
        broker = PaperBroker(initial_cash=100000)
        broker.connect()
        mock_feed = MagicMock()
        mock_feed.get_price.return_value = 150.0
        broker.set_price_feed(mock_feed)
        broker.fill_delay = 0

        order = Order(symbol='AAPL', action='BUY', quantity=10)
        result = broker.submit_order(order)
        self.assertEqual(result.status, 'FILLED')
        self.assertIn('AAPL', broker.positions)

        order = Order(symbol='AAPL', action='SELL', quantity=10)
        result = broker.submit_order(order)
        self.assertEqual(result.status, 'FILLED')
        self.assertNotIn('AAPL', broker.positions)

    def test_insufficient_funds(self):
        broker = PaperBroker(initial_cash=100)
        broker.connect()
        mock_feed = MagicMock()
        mock_feed.get_price.return_value = 150.0
        broker.set_price_feed(mock_feed)
        broker.fill_delay = 0

        order = Order(symbol='AAPL', action='BUY', quantity=100)
        result = broker.submit_order(order)
        self.assertEqual(result.status, 'ERROR')

    def test_high_price_tracking(self):
        pos = Position(symbol='AAPL', shares=10, avg_cost=150.0)
        self.assertEqual(pos.high_price, 150.0)
        pos.update_market_data(160.0)
        self.assertEqual(pos.high_price, 160.0)
        pos.update_market_data(155.0)
        self.assertEqual(pos.high_price, 160.0)


class TestEmailNotifier(unittest.TestCase):
    """Test email notification module"""

    def test_disabled_without_credentials(self):
        notifier = EmailNotifier()
        self.assertFalse(notifier._enabled)

    def test_enabled_with_credentials(self):
        notifier = EmailNotifier(sender='test@test.com', password='pass', recipients=['u@t.com'])
        self.assertTrue(notifier._enabled)

    def test_send_skipped_when_disabled(self):
        notifier = EmailNotifier()
        notifier.send_trade_alert('BUY', 'AAPL', 10, 150.0)
        notifier.send_portfolio_stop_alert(90000, -0.10, 100000)
        notifier.send_daily_summary(100000, 5, -0.05, [], True, 1.5)

    @patch('omnicapital_notifications.smtplib.SMTP')
    def test_daily_summary_formats_positions_pnl_and_drawdown(self, mock_smtp):
        notifier = EmailNotifier(
            sender='test@test.com',
            password='pass',
            recipients=['u@t.com'],
        )
        smtp_server = mock_smtp.return_value.__enter__.return_value
        trades_today = [
            {'action': 'BUY', 'symbol': 'AAPL'},
            {'action': 'SELL', 'symbol': 'MSFT', 'exit_reason': 'stop_loss', 'pnl': -1234.56},
        ]

        notifier.send_daily_summary(98765.43, 2, -0.1234, trades_today, False, 0.6)

        smtp_server.starttls.assert_called_once()
        smtp_server.login.assert_called_once_with('test@test.com', 'pass')
        message = smtp_server.send_message.call_args[0][0]
        payload = message.as_string()

        self.assertEqual(message['Subject'], 'COMPASS Daily: $98,765 | RISK_OFF | 2 trades')
        self.assertIn('Portfolio Value:', payload)
        self.assertIn('$98,765', payload)
        self.assertIn('Drawdown:', payload)
        self.assertIn('-12.3%', payload)
        self.assertIn('Positions:</b></td><td>2', payload)
        self.assertIn("Today's Trades", payload)
        self.assertIn('MSFT', payload)
        self.assertIn('stop_loss', payload)
        self.assertIn('$-1,235', payload)

    @patch('omnicapital_notifications.smtplib.SMTP')
    def test_error_alert_includes_error_message_and_traceback(self, mock_smtp):
        notifier = EmailNotifier(
            sender='test@test.com',
            password='pass',
            recipients=['u@t.com'],
        )
        smtp_server = mock_smtp.return_value.__enter__.return_value
        traceback_str = 'Traceback (most recent call last):\nValueError: boom'

        notifier.send_error_alert('boom', traceback_str)

        message = smtp_server.send_message.call_args[0][0]
        payload = message.as_string()

        self.assertEqual(message['Subject'], 'COMPASS ERROR: boom')
        self.assertEqual(message['X-Priority'], '1')
        self.assertIn('System Error', payload)
        self.assertIn('boom', payload)
        self.assertIn(traceback_str, payload)

    @patch('omnicapital_notifications.smtplib.SMTP')
    def test_daily_summary_and_error_alert_are_noops_when_disabled(self, mock_smtp):
        notifier = EmailNotifier()

        notifier.send_daily_summary(
            100000,
            3,
            -0.05,
            [{'action': 'SELL', 'symbol': 'AAPL', 'pnl': -250.0}],
            True,
            1.0,
        )
        notifier.send_error_alert('network timeout', 'Traceback...')

        mock_smtp.assert_not_called()


class TestStatePersistence(unittest.TestCase):
    """Test state save/load (v8.4)"""

    @patch('omnicapital_live.YahooDataFeed')
    def test_save_and_load(self, mock_feed):
        mock_feed.return_value = MagicMock()
        config = CONFIG.copy()

        # Backup production state if it exists
        latest = 'state/compass_state_latest.json'
        had_backup = os.path.exists(latest)
        backup_data = None
        if had_backup:
            with open(latest) as f:
                backup_data = f.read()

        try:
            trader = COMPASSLive(config)
            trader.trading_day_counter = 42
            trader.current_regime_score = 0.35
            trader.peak_value = 95000
            trader.current_universe = ['AAPL', 'MSFT']
            trader.universe_year = 2026
            trader.last_trading_date = date(2026, 2, 19)

            trader.save_state()

            trader2 = COMPASSLive(config)
            trader2.load_state()

            self.assertEqual(trader2.trading_day_counter, 42)
            self.assertAlmostEqual(trader2.current_regime_score, 0.35, places=2)
            self.assertEqual(trader2.peak_value, 100000)
            self.assertEqual(trader2.current_universe, ['AAPL', 'MSFT'])
            self.assertEqual(trader2.universe_year, 2026)
        finally:
            # Restore production state
            if had_backup and backup_data:
                with open(latest, 'w') as f:
                    f.write(backup_data)


if __name__ == '__main__':
    unittest.main(verbosity=2)
