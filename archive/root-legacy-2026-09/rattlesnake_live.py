"""
RATTLESNAKE v1.0 - Live Trading System
=======================================
Reversion After Temporary Turbulence, Leveraging Extreme
Statistical Negativity And Kontrarean Entries

Live trading engine for the RATTLESNAKE mean-reversion strategy.
Mirrors the COMPASSLive class structure from omnicapital_live.py,
using the same broker/data feed infrastructure.

Signal: 5-day drop >= 8% + RSI(5) < 25 + Price > SMA(200) + Volume > 500K
Exit: Profit target +4% OR Stop loss -5% OR 8-day max hold
Regime: SPY SMA(200) risk-on/off, VIX > 35 panic mode
Positions: Max 5 (risk-on), Max 2 (risk-off), equal weight 20%
No leverage (1.0x always). Cash earns 3% annual.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta, time, date
import logging
import json
import os
import sys
from typing import Dict, List, Optional, Tuple
import warnings
import time as time_module
from zoneinfo import ZoneInfo

warnings.filterwarnings('ignore')

# Import shared infrastructure
from omnicapital_data_feed import YahooDataFeed, MarketDataManager, HistoricalDataLoader
from omnicapital_broker import PaperBroker, Order, Broker, Position

# ============================================================================
# LOGGING
# ============================================================================

os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'logs/rattlesnake_live_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# RATTLESNAKE v1.0 PARAMETERS (identical to backtest)
# ============================================================================

CONFIG = {
    # Entry signal
    'DROP_THRESHOLD': -0.08,        # Stock dropped >= 8% in lookback window
    'DROP_LOOKBACK': 5,             # Days to measure the drop
    'RSI_PERIOD': 5,                # Short RSI for oversold detection
    'RSI_THRESHOLD': 25,            # RSI must be below this
    'TREND_SMA': 200,               # Must be above 200-day SMA (uptrend)
    'MIN_AVG_VOLUME': 500_000,      # Minimum 20-day average volume
    'VOLUME_LOOKBACK': 20,          # Days for average volume calculation

    # Exit rules
    'PROFIT_TARGET': 0.04,          # Take profit at +4%
    'STOP_LOSS': -0.05,             # Stop loss at -5%
    'MAX_HOLD_DAYS': 8,             # Maximum hold period in trading days

    # Portfolio
    'MAX_POSITIONS': 5,             # Maximum simultaneous positions (risk-on)
    'MAX_POSITIONS_RISK_OFF': 2,    # Fewer positions in risk-off
    'POSITION_WEIGHT': 0.20,        # 20% per position (equal weight)

    # Regime
    'REGIME_SMA_PERIOD': 200,       # SPY regime filter
    'REGIME_CONFIRM_DAYS': 3,       # Days to confirm regime change
    'VIX_PANIC_LEVEL': 35,          # VIX above this = no new entries

    # Cash yield
    'CASH_YIELD_RATE': 0.03,        # 3% annual on uninvested cash

    # No leverage
    'LEVERAGE': 1.0,                # Fixed at 1.0x always

    # Capital
    'INITIAL_CAPITAL': 50_000,      # Half of combined portfolio ($50K)

    # Costs
    'COMMISSION_PER_SHARE': 0.001,

    # Market hours (ET)
    'MARKET_OPEN': time(9, 30),
    'MARKET_CLOSE': time(16, 0),

    # Broker
    'BROKER_TYPE': 'PAPER',
    'PAPER_INITIAL_CASH': 50_000,

    # Data feed
    'DATA_FEED': 'YAHOO',
    'PRICE_UPDATE_INTERVAL': 60,    # Seconds between price refreshes
    'DATA_CACHE_DURATION': 60,      # Seconds to cache individual prices
    'MAX_PRICE_AGE_SECONDS': 300,

    # Data validation
    'MIN_VALID_PRICE': 0.01,
    'MAX_VALID_PRICE': 50000,
    'MAX_PRICE_CHANGE_PCT': 0.20,

    # Order management
    'ORDER_TIMEOUT_SECONDS': 300,   # 5 min max for pending orders
    'MAX_FILL_DEVIATION': 0.02,     # 2% max fill price deviation

    # Monitoring intervals
    'STOP_CHECK_INTERVAL': 900,     # 15 min - check exits during market hours
    'STATE_SAVE_INTERVAL': 300,     # 5 min
}

# Fixed S&P 100 universe (identical to backtest)
UNIVERSE = [
    'AAPL', 'ABBV', 'ABT', 'ACN', 'ADBE', 'AIG', 'AMGN', 'AMT', 'AMZN', 'AVGO',
    'AXP', 'BA', 'BAC', 'BK', 'BKNG', 'BLK', 'BMY', 'BRK-B', 'C', 'CAT',
    'CHTR', 'CL', 'CMCSA', 'COF', 'COP', 'COST', 'CRM', 'CSCO', 'CVS', 'CVX',
    'DE', 'DHR', 'DIS', 'DOW', 'DUK', 'EMR', 'EXC', 'F', 'FDX', 'GD',
    'GE', 'GILD', 'GM', 'GOOG', 'GS', 'HD', 'HON', 'IBM', 'INTC', 'INTU',
    'JNJ', 'JPM', 'KHC', 'KO', 'LIN', 'LLY', 'LMT', 'LOW', 'MA', 'MCD',
    'MDLZ', 'MDT', 'MET', 'META', 'MMM', 'MO', 'MRK', 'MS', 'MSFT', 'NEE',
    'NFLX', 'NKE', 'NVDA', 'ORCL', 'PEP', 'PFE', 'PG', 'PM', 'PYPL', 'QCOM',
    'RTX', 'SBUX', 'SCHW', 'SO', 'SPG', 'T', 'TGT', 'TMO', 'TMUS', 'TSLA',
    'TXN', 'UNH', 'UNP', 'UPS', 'USB', 'V', 'VZ', 'WFC', 'WMT', 'XOM',
]


# ============================================================================
# DATA VALIDATION (identical pattern to COMPASSLive)
# ============================================================================

class DataValidator:
    """Validates market data quality and consistency.
    Rejects outlier prices, NaN values, and stale data."""

    def __init__(self, config: Dict):
        self.config = config
        self._price_history: Dict[str, List[tuple]] = {}
        self._max_history = 20
        self._rejection_count = 0
        self._total_validated = 0

    def is_valid_price(self, symbol: str, price: float) -> bool:
        """Validate a single price. Returns False if price is invalid."""
        # Range check
        if not (self.config['MIN_VALID_PRICE'] <= price <= self.config['MAX_VALID_PRICE']):
            logger.warning(f"[rattlesnake] Price out of range for {symbol}: ${price:.2f}")
            return False

        # Sharp change check (only if we have history)
        if symbol in self._price_history and self._price_history[symbol]:
            last_prices = [p for _, p in self._price_history[symbol][-3:]]
            if last_prices:
                avg_last = np.mean(last_prices)
                if avg_last > 0:
                    change_pct = abs(price - avg_last) / avg_last
                    if change_pct > self.config['MAX_PRICE_CHANGE_PCT']:
                        logger.warning(f"[rattlesnake] Sharp price change rejected for {symbol}: "
                                       f"${price:.2f} vs avg ${avg_last:.2f} "
                                       f"({change_pct:.1%} > {self.config['MAX_PRICE_CHANGE_PCT']:.0%})")
                        return False
        return True

    def validate_batch(self, prices: Dict[str, float]) -> Dict[str, float]:
        """Filter a price dict, keeping only valid prices. Returns clean dict.
        Records valid prices automatically."""
        valid = {}
        rejected = []

        for symbol, price in prices.items():
            self._total_validated += 1

            # NaN / None check
            if price is None:
                rejected.append((symbol, 'None'))
                continue
            try:
                if np.isnan(price):
                    rejected.append((symbol, 'NaN'))
                    continue
            except (TypeError, ValueError):
                rejected.append((symbol, 'invalid_type'))
                continue

            # Range + sharp change check
            if not self.is_valid_price(symbol, price):
                rejected.append((symbol, 'outlier'))
                self._rejection_count += 1
                continue

            valid[symbol] = price
            self.record_price(symbol, price)

        if rejected:
            logger.warning(f"[rattlesnake] Data validation rejected {len(rejected)}/{len(prices)} prices: "
                           f"{', '.join(f'{s}({r})' for s, r in rejected[:5])}"
                           + (f" ... +{len(rejected)-5} more" if len(rejected) > 5 else ""))
        return valid

    def record_price(self, symbol: str, price: float):
        """Record a validated price for future comparison"""
        if symbol not in self._price_history:
            self._price_history[symbol] = []
        self._price_history[symbol].append((datetime.now(), price))
        if len(self._price_history[symbol]) > self._max_history:
            self._price_history[symbol] = self._price_history[symbol][-self._max_history:]

    def get_stats(self) -> Dict:
        """Get validation statistics"""
        return {
            'total_validated': self._total_validated,
            'total_rejected': self._rejection_count,
            'rejection_rate': self._rejection_count / max(1, self._total_validated),
            'symbols_tracked': len(self._price_history),
        }


# ============================================================================
# RATTLESNAKE SIGNAL FUNCTIONS
# ============================================================================

def compute_rsi(prices_series: pd.Series, period: int = 5) -> pd.Series:
    """Compute RSI (Relative Strength Index) for a price series.
    Uses standard Wilder smoothing (rolling mean for simplicity)."""
    delta = prices_series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def compute_live_regime(spy_hist: pd.DataFrame, sma_period: int = 200,
                        confirm_days: int = 3) -> Tuple[bool, int, bool]:
    """
    Compute current market regime from SPY history.
    Returns: (is_risk_on, consecutive_count, last_raw_signal)
    Identical to COMPASSLive regime logic.
    """
    if len(spy_hist) < sma_period + confirm_days:
        return True, 0, True  # Default RISK_ON

    close = spy_hist['Close']
    sma = close.rolling(sma_period).mean()

    # Get last N+1 days to compute confirmation
    raw_signals = (close > sma).iloc[-confirm_days - 5:]

    current_regime = True
    consecutive = 0
    last_raw = True

    for val in raw_signals:
        if pd.isna(val):
            continue
        raw = bool(val)
        if raw == last_raw:
            consecutive += 1
        else:
            consecutive = 1
            last_raw = raw
        if raw != current_regime and consecutive >= confirm_days:
            current_regime = raw

    return current_regime, consecutive, last_raw


# ============================================================================
# LIVE TRADING SYSTEM
# ============================================================================

class RATTLESNAKELive:
    """RATTLESNAKE v1.0 Live Trading System — Mean-Reversion Contrarian"""

    def __init__(self, config: Dict):
        self.config = config
        self.validator = DataValidator(config)
        self.et_tz = ZoneInfo('America/New_York')

        # Data feed (same infrastructure as COMPASS)
        self.data_feed = YahooDataFeed(cache_duration=config['DATA_CACHE_DURATION'])

        # Broker (PaperBroker with $50K initial capital)
        self.broker = PaperBroker(
            initial_cash=config['PAPER_INITIAL_CASH'],
            commission_per_share=config['COMMISSION_PER_SHARE'],
            max_fill_deviation=config.get('MAX_FILL_DEVIATION', 0.02)
        )
        self.broker.set_price_feed(self.data_feed)

        # ---- RATTLESNAKE State ----
        # Regime
        self.current_regime = True  # True = RISK_ON
        self.regime_consecutive = 0
        self.regime_last_raw = True

        # VIX
        self.vix_level = 0.0
        self.vix_panic = False      # True when VIX > VIX_PANIC_LEVEL

        # Trading day counter (incremented each market day the system runs)
        self.trading_day_counter = 0
        self.last_trading_date = None

        # Position metadata (beyond what broker tracks)
        # Each entry: {entry_price, entry_date, entry_day_index}
        # No high_price needed since RATTLESNAKE has no trailing stop
        self.position_meta: Dict[str, dict] = {}

        # Historical data cache (refreshed daily)
        self._hist_cache: Dict[str, pd.DataFrame] = {}
        self._volume_cache: Dict[str, pd.Series] = {}
        self._rsi_cache: Dict[str, pd.Series] = {}
        self._spy_hist: Optional[pd.DataFrame] = None
        self._hist_date: Optional[date] = None

        # Tracking
        self.trades_today = []
        self._start_time = datetime.now()
        self._cycles_completed = 0
        self._consecutive_errors = 0
        self._max_consecutive_errors = 5
        self._last_stop_check = datetime.now()
        self._last_state_save = datetime.now()
        self._daily_open_done = False

        # Notifications (set externally, same interface as COMPASS)
        self.notifier = None

        logger.info("=" * 70)
        logger.info("RATTLESNAKE v1.0 - LIVE MEAN-REVERSION TRADING")
        logger.info("=" * 70)
        logger.info(f"Signal: 5d drop >= {abs(config['DROP_THRESHOLD']):.0%} + "
                     f"RSI({config['RSI_PERIOD']}) < {config['RSI_THRESHOLD']} + "
                     f"SMA({config['TREND_SMA']})")
        logger.info(f"Exit: Profit +{config['PROFIT_TARGET']:.0%} | "
                     f"Stop {config['STOP_LOSS']:.0%} | "
                     f"Time {config['MAX_HOLD_DAYS']}d")
        logger.info(f"Regime: SPY SMA{config['REGIME_SMA_PERIOD']} | "
                     f"VIX panic: {config['VIX_PANIC_LEVEL']}")
        logger.info(f"Positions: {config['MAX_POSITIONS']} risk-on / "
                     f"{config['MAX_POSITIONS_RISK_OFF']} risk-off | "
                     f"Weight: {config['POSITION_WEIGHT']:.0%}")
        logger.info(f"Capital: ${config['PAPER_INITIAL_CASH']:,.0f} | "
                     f"Leverage: {config['LEVERAGE']:.1f}x (fixed) | "
                     f"Cash yield: {config['CASH_YIELD_RATE']:.0%}")
        logger.info(f"Universe: {len(UNIVERSE)} S&P 100 stocks (fixed)")

    # ------------------------------------------------------------------
    # Market hours
    # ------------------------------------------------------------------

    def get_et_now(self) -> datetime:
        """Get current time in Eastern Time"""
        return datetime.now(self.et_tz)

    def is_market_open(self) -> bool:
        """Check if US market is currently open (ET)"""
        now_et = self.get_et_now()
        if now_et.weekday() >= 5:
            return False
        current_time = now_et.time()
        return self.config['MARKET_OPEN'] <= current_time <= self.config['MARKET_CLOSE']

    def is_market_day(self) -> bool:
        """Check if today is a weekday (potential market day)"""
        return self.get_et_now().weekday() < 5

    def is_new_trading_day(self) -> bool:
        """Check if this is a new trading day"""
        today = self.get_et_now().date()
        return self.last_trading_date is None or today > self.last_trading_date

    # ------------------------------------------------------------------
    # Data refresh (called once per trading day)
    # ------------------------------------------------------------------

    def refresh_daily_data(self):
        """Download fresh historical data for all signals. Called at market open.
        Downloads ~2 years of data for SMA(200) and RSI computation."""
        today = self.get_et_now().date()
        if self._hist_date == today:
            return  # Already refreshed today

        logger.info("[rattlesnake] Refreshing daily historical data...")

        # SPY for regime detection
        try:
            spy = yf.download('SPY', period='2y', progress=False)
            if isinstance(spy.columns, pd.MultiIndex):
                spy.columns = [c[0] for c in spy.columns]
            self._spy_hist = spy
            logger.info(f"[rattlesnake] SPY data: {len(spy)} days")
        except Exception as e:
            logger.error(f"[rattlesnake] Failed to download SPY: {e}")

        # VIX for panic detection
        try:
            vix_df = yf.download('^VIX', period='5d', progress=False)
            if isinstance(vix_df.columns, pd.MultiIndex):
                vix_df.columns = [c[0] for c in vix_df.columns]
            if len(vix_df) > 0:
                self.vix_level = float(vix_df['Close'].iloc[-1])
                self.vix_panic = self.vix_level > self.config['VIX_PANIC_LEVEL']
                logger.info(f"[rattlesnake] VIX: {self.vix_level:.1f} "
                            f"{'(PANIC - no new entries)' if self.vix_panic else '(normal)'}")
        except Exception as e:
            logger.error(f"[rattlesnake] Failed to download VIX: {e}")

        # Universe stocks: need enough history for SMA(200) + RSI + drop calc
        symbols_needed = set(UNIVERSE) | set(self.position_meta.keys())
        for symbol in symbols_needed:
            try:
                df = yf.download(symbol, period='2y', progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] for c in df.columns]
                if len(df) > 50:
                    self._hist_cache[symbol] = df

                    # Cache volume series
                    if 'Volume' in df.columns:
                        self._volume_cache[symbol] = df['Volume']

                    # Pre-compute RSI(5)
                    self._rsi_cache[symbol] = compute_rsi(df['Close'], self.config['RSI_PERIOD'])
            except Exception as e:
                logger.debug(f"[rattlesnake] Failed to download {symbol}: {e}")

        logger.info(f"[rattlesnake] Historical data refreshed: {len(self._hist_cache)} stocks, "
                     f"RSI computed for {len(self._rsi_cache)} stocks")
        self._hist_date = today

    # ------------------------------------------------------------------
    # RSI computation (for ad-hoc use if needed)
    # ------------------------------------------------------------------

    def compute_rsi_for_symbol(self, symbol: str, period: int = 5) -> Optional[float]:
        """Get the latest RSI value for a symbol from the pre-computed cache.
        Returns None if not available."""
        if symbol in self._rsi_cache:
            rsi_series = self._rsi_cache[symbol]
            if len(rsi_series) > 0:
                val = rsi_series.iloc[-1]
                if not pd.isna(val):
                    return float(val)
        return None

    # ------------------------------------------------------------------
    # Regime detection
    # ------------------------------------------------------------------

    def update_regime(self):
        """Update market regime based on SPY vs SMA200.
        Identical logic to COMPASSLive."""
        if self._spy_hist is None or len(self._spy_hist) < self.config['REGIME_SMA_PERIOD']:
            return

        old_regime = self.current_regime
        self.current_regime, self.regime_consecutive, self.regime_last_raw = \
            compute_live_regime(
                self._spy_hist,
                self.config['REGIME_SMA_PERIOD'],
                self.config['REGIME_CONFIRM_DAYS']
            )

        if self.current_regime != old_regime:
            regime_str = "RISK_ON" if self.current_regime else "RISK_OFF"
            logger.info(f"[rattlesnake] REGIME CHANGE -> {regime_str}")
            if self.notifier:
                spy_price = self._spy_hist['Close'].iloc[-1]
                sma = self._spy_hist['Close'].rolling(self.config['REGIME_SMA_PERIOD']).mean().iloc[-1]
                self.notifier.send_regime_change_alert(self.current_regime, spy_price, sma)

    def fetch_vix(self):
        """Fetch current VIX level and update panic flag.
        Called during daily_open and optionally intraday."""
        try:
            vix_df = yf.download('^VIX', period='5d', progress=False)
            if isinstance(vix_df.columns, pd.MultiIndex):
                vix_df.columns = [c[0] for c in vix_df.columns]
            if len(vix_df) > 0:
                self.vix_level = float(vix_df['Close'].iloc[-1])
                self.vix_panic = self.vix_level > self.config['VIX_PANIC_LEVEL']
        except Exception as e:
            logger.warning(f"[rattlesnake] VIX fetch failed: {e}")

    # ------------------------------------------------------------------
    # Position sizing
    # ------------------------------------------------------------------

    def get_max_positions(self) -> int:
        """Determine max positions based on regime"""
        if not self.current_regime:  # RISK_OFF
            return self.config['MAX_POSITIONS_RISK_OFF']
        return self.config['MAX_POSITIONS']

    # ------------------------------------------------------------------
    # Exit logic: profit target, stop loss, time stop
    # ------------------------------------------------------------------

    def check_exits(self, prices: Dict[str, float]):
        """Check exit conditions for each open position.
        Three exit triggers (from backtest):
          1. Profit target: current_price / entry_price - 1 >= +4%
          2. Stop loss: current_price / entry_price - 1 <= -5%
          3. Time stop: days_held >= 8 trading days
        Also handles regime-reduce when positions exceed max for current regime."""
        positions = self.broker.get_positions()
        max_positions = self.get_max_positions()

        for symbol in list(positions.keys()):
            price = prices.get(symbol)
            if not price:
                continue

            meta = self.position_meta.get(symbol)
            if not meta:
                continue

            exit_reason = None

            # Current P&L from entry
            pos_return = (price - meta['entry_price']) / meta['entry_price']

            # 1. Profit target (+4%)
            if pos_return >= self.config['PROFIT_TARGET']:
                exit_reason = 'profit_target'

            # 2. Stop loss (-5%)
            if pos_return <= self.config['STOP_LOSS']:
                exit_reason = 'stop_loss'

            # 3. Time stop (8 trading days)
            days_held = self.trading_day_counter - meta['entry_day_index']
            if days_held >= self.config['MAX_HOLD_DAYS']:
                exit_reason = 'time_stop'

            # 4. Regime reduce: if we have more positions than allowed
            if exit_reason is None and len(positions) > max_positions:
                # Close the worst performer among excess positions
                pos_returns = {}
                for s, p in positions.items():
                    pr = prices.get(s)
                    m = self.position_meta.get(s)
                    if pr and m:
                        pos_returns[s] = (pr - m['entry_price']) / m['entry_price']
                if pos_returns:
                    worst = min(pos_returns, key=pos_returns.get)
                    if symbol == worst:
                        exit_reason = 'regime_reduce'

            # Execute exit
            if exit_reason:
                pos = positions[symbol]
                order = Order(symbol=symbol, action='SELL',
                              quantity=pos.shares, order_type='MARKET')
                result = self.broker.submit_order(order)

                if result.status == 'FILLED':
                    pnl = (result.filled_price - meta['entry_price']) * pos.shares - result.commission
                    ret = pnl / (meta['entry_price'] * pos.shares) if meta['entry_price'] * pos.shares > 0 else 0
                    self.position_meta.pop(symbol, None)

                    self.trades_today.append({
                        'symbol': symbol, 'action': 'SELL',
                        'exit_reason': exit_reason, 'pnl': pnl, 'return': ret,
                        'price': result.filled_price,
                        'days_held': days_held,
                    })
                    logger.info(f"[rattlesnake] EXIT [{exit_reason}] {symbol} "
                                f"@ ${result.filled_price:.2f} | "
                                f"PnL: ${pnl:+,.0f} ({ret:+.1%}) | "
                                f"Held: {days_held}d")

                    if self.notifier:
                        self.notifier.send_trade_alert('SELL', symbol, pos.shares,
                                                       result.filled_price, exit_reason, pnl)

                # Refresh positions for remaining checks
                positions = self.broker.get_positions()

    # ------------------------------------------------------------------
    # Entry scanning: find oversold candidates
    # ------------------------------------------------------------------

    def scan_entries(self, prices: Dict[str, float]) -> List[Dict]:
        """Scan universe for mean-reversion entry signals.
        Returns list of candidate dicts sorted by most oversold (biggest drop first).

        Entry criteria (all must be true):
          1. 5-day price drop >= 8% (DROP_THRESHOLD)
          2. RSI(5) < 25 (deeply oversold)
          3. Price > SMA(200) (uptrend — buying dips, not falling knives)
          4. 20-day average volume > 500K (liquidity)
        """
        positions = self.broker.get_positions()
        held_tickers = set(positions.keys())

        candidates = []

        for symbol in UNIVERSE:
            # Skip stocks already in portfolio
            if symbol in held_tickers:
                continue

            # Need current price
            current_price = prices.get(symbol)
            if not current_price or current_price <= 0:
                continue

            # Need historical data
            if symbol not in self._hist_cache:
                continue
            hist = self._hist_cache[symbol]
            if len(hist) < self.config['TREND_SMA'] + 10:
                continue

            close = hist['Close']

            # 1. Drop threshold: stock fell >= DROP_THRESHOLD in last DROP_LOOKBACK days
            if len(close) < self.config['DROP_LOOKBACK'] + 1:
                continue
            past_price = float(close.iloc[-(self.config['DROP_LOOKBACK'] + 1)])
            if past_price <= 0:
                continue
            # Use the last close from historical data for the drop calculation
            # (more reliable than intraday price for this signal)
            latest_close = float(close.iloc[-1])
            drop = (latest_close / past_price) - 1.0
            if drop > self.config['DROP_THRESHOLD']:  # Not dropped enough (drop is negative)
                continue

            # 2. RSI check: RSI(5) must be below threshold
            rsi_val = self.compute_rsi_for_symbol(symbol)
            if rsi_val is None or rsi_val > self.config['RSI_THRESHOLD']:
                continue

            # 3. Trend filter: price must be above SMA(200)
            if len(close) < self.config['TREND_SMA']:
                continue
            sma_200 = float(close.iloc[-self.config['TREND_SMA']:].mean())
            if latest_close < sma_200:
                continue  # Below trend -- falling knife, skip

            # 4. Volume filter: 20-day average volume > 500K
            if symbol in self._volume_cache:
                vol_series = self._volume_cache[symbol]
                if len(vol_series) >= self.config['VOLUME_LOOKBACK']:
                    avg_vol = float(vol_series.iloc[-self.config['VOLUME_LOOKBACK']:].mean())
                    if avg_vol < self.config['MIN_AVG_VOLUME']:
                        continue
                else:
                    continue  # Not enough volume data
            else:
                continue  # No volume data

            # All filters passed — add as candidate
            candidates.append({
                'symbol': symbol,
                'drop': drop,
                'rsi': rsi_val,
                'sma_200': sma_200,
                'avg_volume': avg_vol,
                'price': current_price,
                'score': -drop,  # Bigger drop = higher score (more oversold)
            })

        # Sort by most oversold first (biggest drop = highest priority)
        candidates.sort(key=lambda x: x['score'], reverse=True)

        if candidates:
            logger.info(f"[rattlesnake] Entry scan: {len(candidates)} candidates found")
            for c in candidates[:5]:
                logger.info(f"  {c['symbol']}: drop={c['drop']:.1%}, RSI={c['rsi']:.0f}, "
                            f"price=${c['price']:.2f}")

        return candidates

    # ------------------------------------------------------------------
    # Position entry
    # ------------------------------------------------------------------

    def open_new_positions(self, candidates: List[Dict], prices: Dict[str, float]):
        """Open new positions for top candidates up to available slots.
        Position size: 20% of total portfolio value per position (equal weight)."""
        positions = self.broker.get_positions()
        max_positions = self.get_max_positions()
        open_slots = max_positions - len(positions)

        if open_slots <= 0:
            return

        portfolio = self.broker.get_portfolio()
        if portfolio.cash <= 500:
            return

        for candidate in candidates[:open_slots]:
            symbol = candidate['symbol']
            price = prices.get(symbol)
            if not price or price <= 0:
                continue

            # Position size: POSITION_WEIGHT (20%) of total portfolio value
            target_value = portfolio.total_value * self.config['POSITION_WEIGHT']

            # Don't exceed available cash
            target_value = min(target_value, portfolio.cash * 0.95)

            # Calculate shares (whole shares for cleaner execution)
            shares = int(target_value / price)
            if shares <= 0:
                continue

            cost = shares * price
            commission = shares * self.config['COMMISSION_PER_SHARE']

            if cost + commission > portfolio.cash * 0.95:
                continue

            order = Order(symbol=symbol, action='BUY',
                          quantity=shares, order_type='MARKET')
            result = self.broker.submit_order(order)

            if result.status == 'FILLED':
                self.position_meta[symbol] = {
                    'entry_price': result.filled_price,
                    'entry_date': self.get_et_now().date().isoformat(),
                    'entry_day_index': self.trading_day_counter,
                }

                self.trades_today.append({
                    'symbol': symbol, 'action': 'BUY',
                    'price': result.filled_price,
                    'shares': shares, 'value': cost,
                    'drop': candidate['drop'],
                    'rsi': candidate['rsi'],
                })
                logger.info(f"[rattlesnake] ENTRY {symbol}: {shares} shares "
                            f"@ ${result.filled_price:.2f} (${cost:,.0f}) | "
                            f"Drop: {candidate['drop']:.1%} | RSI: {candidate['rsi']:.0f}")

                if self.notifier:
                    self.notifier.send_trade_alert('BUY', symbol, shares,
                                                   result.filled_price, None, None)

                # Update portfolio for next iteration
                portfolio = self.broker.get_portfolio()

    # ------------------------------------------------------------------
    # Main trading logic
    # ------------------------------------------------------------------

    def execute_trading_logic(self, prices: Dict[str, float]):
        """Main trading logic: exits first, then entries (if not in VIX panic)."""
        # 1. Check all exit conditions
        self.check_exits(prices)

        # 2. Scan for new entries and open positions (only if VIX not in panic)
        if self.vix_panic:
            logger.info(f"[rattlesnake] VIX PANIC ({self.vix_level:.1f} > "
                        f"{self.config['VIX_PANIC_LEVEL']}): no new entries")
            return

        candidates = self.scan_entries(prices)
        if candidates:
            self.open_new_positions(candidates, prices)

    # ------------------------------------------------------------------
    # Daily open routine
    # ------------------------------------------------------------------

    def daily_open(self):
        """Execute at market open each trading day.
        Refreshes data, computes RSI, updates regime, fetches VIX."""
        if not self.is_new_trading_day():
            return

        today = self.get_et_now().date()
        self.last_trading_date = today
        self.trading_day_counter += 1
        self.trades_today = []
        self._daily_open_done = False

        logger.info(f"\n{'='*60}")
        logger.info(f"[rattlesnake] TRADING DAY {self.trading_day_counter} | {today}")
        logger.info(f"{'='*60}")

        # 1. Refresh historical data (includes RSI pre-compute and VIX fetch)
        self.refresh_daily_data()

        # 2. Update regime (SPY SMA200)
        self.update_regime()

        # 3. Accrue cash yield (3% annual on positive cash balance)
        if self.broker.cash > 0:
            daily_yield = self.broker.cash * self.config['CASH_YIELD_RATE'] / 252
            self.broker.cash += daily_yield
            logger.debug(f"[rattlesnake] Cash yield: +${daily_yield:.2f} "
                         f"(cash: ${self.broker.cash:,.0f})")

        # Log status
        regime_str = "RISK_ON" if self.current_regime else "RISK_OFF"
        max_pos = self.get_max_positions()
        vix_str = f" [VIX PANIC {self.vix_level:.0f}]" if self.vix_panic else ""

        portfolio = self.broker.get_portfolio()
        logger.info(f"[rattlesnake] Portfolio: ${portfolio.total_value:,.0f} | "
                     f"Cash: ${portfolio.cash:,.0f} | "
                     f"Regime: {regime_str}{vix_str} | "
                     f"VIX: {self.vix_level:.1f} | "
                     f"Positions: {len(self.broker.positions)}/{max_pos}")

    # ------------------------------------------------------------------
    # Status logging
    # ------------------------------------------------------------------

    def log_status(self, prices: Dict[str, float]):
        """Log current portfolio and position status"""
        portfolio = self.broker.get_portfolio()
        regime_str = "RISK_ON" if self.current_regime else "RISK_OFF"
        vix_str = f" [VIX:{self.vix_level:.0f}]" if self.vix_panic else ""

        positions = self.broker.get_positions()
        pos_details = []
        for s, m in self.position_meta.items():
            if s in positions:
                p = prices.get(s, m.get('entry_price', 0))
                entry = m.get('entry_price', 1)
                ret = (p - entry) / entry if entry > 0 else 0
                days = self.trading_day_counter - m.get('entry_day_index', self.trading_day_counter)
                pos_details.append(f"{s}({ret:+.1%}/{days}d)")
        pos_str = ", ".join(pos_details)

        logger.info(f"[rattlesnake] STATUS: ${portfolio.total_value:,.0f} | "
                     f"{regime_str}{vix_str} | "
                     f"Pos: {len(positions)}/{self.get_max_positions()} | "
                     f"[{pos_str}]")

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def save_state(self):
        """Save full system state to JSON.
        Saves to both dated file and 'latest' symlink."""
        portfolio = self.broker.get_portfolio()
        state = {
            'version': 'rattlesnake_1.0',
            'timestamp': datetime.now().isoformat(),

            # Portfolio
            'cash': self.broker.cash,
            'portfolio_value': portfolio.total_value,

            # Regime
            'current_regime': self.current_regime,
            'regime_consecutive': self.regime_consecutive,
            'regime_last_raw': self.regime_last_raw,

            # VIX
            'vix_level': self.vix_level,
            'vix_panic': self.vix_panic,

            # Counters
            'trading_day_counter': self.trading_day_counter,
            'last_trading_date': self.last_trading_date.isoformat() if self.last_trading_date else None,

            # Positions (broker state)
            'positions': {
                s: {
                    'shares': p.shares,
                    'avg_cost': p.avg_cost,
                }
                for s, p in self.broker.positions.items()
            },

            # Position metadata (RATTLESNAKE-specific)
            'position_meta': self.position_meta,

            # Stats
            'stats': {
                'cycles_completed': self._cycles_completed,
                'uptime_minutes': (datetime.now() - self._start_time).total_seconds() / 60,
            }
        }

        os.makedirs('state', exist_ok=True)
        filename = f'state/rattlesnake_state_{datetime.now().strftime("%Y%m%d")}.json'
        latest = 'state/rattlesnake_state_latest.json'

        for f in [filename, latest]:
            with open(f, 'w') as fp:
                json.dump(state, fp, indent=2, default=str)

        logger.info(f"[rattlesnake] State saved: {filename}")

    def load_state(self):
        """Load previous state from JSON file.
        Tries 'latest' first, then falls back to most recent dated file."""
        latest = 'state/rattlesnake_state_latest.json'
        if not os.path.exists(latest):
            # Try dated files
            import glob
            files = glob.glob('state/rattlesnake_state_*.json')
            files = [f for f in files if 'latest' not in f]
            if not files:
                logger.info("[rattlesnake] No previous state found, starting fresh")
                return
            latest = max(files, key=os.path.getctime)

        try:
            with open(latest, 'r') as f:
                state = json.load(f)

            # Restore portfolio state
            self.broker.cash = state.get('cash', self.config['PAPER_INITIAL_CASH'])

            # Restore regime
            self.current_regime = state.get('current_regime', True)
            self.regime_consecutive = state.get('regime_consecutive', 0)
            self.regime_last_raw = state.get('regime_last_raw', True)

            # Restore VIX
            self.vix_level = state.get('vix_level', 0.0)
            self.vix_panic = state.get('vix_panic', False)

            # Restore counters
            self.trading_day_counter = state.get('trading_day_counter', 0)
            ltd = state.get('last_trading_date')
            self.last_trading_date = date.fromisoformat(ltd) if ltd else None

            # Restore positions
            for symbol, data in state.get('positions', {}).items():
                self.broker.positions[symbol] = Position(
                    symbol=symbol,
                    shares=data['shares'],
                    avg_cost=data['avg_cost']
                )

            # Restore position metadata
            self.position_meta = state.get('position_meta', {})

            regime_str = "RISK_ON" if self.current_regime else "RISK_OFF"
            logger.info(f"[rattlesnake] State loaded from {latest}")
            logger.info(f"  Cash: ${self.broker.cash:,.0f} | "
                        f"Positions: {len(self.broker.positions)} | "
                        f"Day: {self.trading_day_counter}")
            logger.info(f"  Regime: {regime_str} | VIX: {self.vix_level:.1f}")

        except Exception as e:
            logger.error(f"[rattlesnake] Error loading state: {e}")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_once(self) -> bool:
        """Execute one trading cycle. Returns True if market is active, False otherwise.
        Logic:
          - Return quickly if market closed
          - On new day: daily_open() (refresh data, regime, VIX)
          - First execution of day: full trading logic (exits + entries)
          - Intraday: check exits every STOP_CHECK_INTERVAL (15 min)
          - Save state every STATE_SAVE_INTERVAL (5 min)
        """
        self._cycles_completed += 1

        try:
            if not self.is_market_open():
                return False

            # New trading day setup
            if self.is_new_trading_day():
                self.daily_open()

            # Get current prices (async fetch + batch validation)
            symbols_needed = list(set(UNIVERSE) | set(self.position_meta.keys()))
            raw_prices = self.data_feed.get_prices(symbols_needed)
            prices = self.validator.validate_batch(raw_prices)

            if not prices:
                logger.warning("[rattlesnake] No valid prices obtained after validation")
                self._consecutive_errors += 1
                return False

            self._consecutive_errors = 0

            # Update broker positions with current prices
            for symbol, price in prices.items():
                if symbol in self.broker.positions:
                    self.broker.positions[symbol].update_market_data(price)

            # Execute trading logic (at open) or check exits (intraday)
            if not self._daily_open_done:
                self.execute_trading_logic(prices)
                self._daily_open_done = True
                self.log_status(prices)
            else:
                # Intraday: only check exits (profit target / stop loss / time)
                now = datetime.now()
                if (now - self._last_stop_check).total_seconds() >= self.config['STOP_CHECK_INTERVAL']:
                    self.check_exits(prices)
                    self._last_stop_check = now

            # Check for stale orders (order timeout)
            if hasattr(self.broker, 'check_stale_orders'):
                stale = self.broker.check_stale_orders(
                    self.config.get('ORDER_TIMEOUT_SECONDS', 300)
                )
                if stale:
                    logger.warning(f"[rattlesnake] Cancelled {len(stale)} stale orders: "
                                   f"{', '.join(o.symbol for o in stale)}")

            # Periodic state save
            now = datetime.now()
            if (now - self._last_state_save).total_seconds() >= self.config['STATE_SAVE_INTERVAL']:
                self.save_state()
                self._last_state_save = now

            return True

        except Exception as e:
            logger.error(f"[rattlesnake] Error in trading cycle: {e}", exc_info=True)
            self._consecutive_errors += 1

            if self._consecutive_errors >= self._max_consecutive_errors:
                logger.critical(f"[rattlesnake] Too many consecutive errors "
                                f"({self._consecutive_errors}). Stopping.")
                if self.notifier:
                    self.notifier.send_error_alert(str(e), "")
                raise RuntimeError("Too many consecutive errors")

            return False

    def run(self, interval: int = 60):
        """Main trading loop. Runs indefinitely until kill switch or KeyboardInterrupt.

        Args:
            interval: Seconds between cycles when market is open (default: 60)
        """
        logger.info("[rattlesnake] Starting RATTLESNAKE v1.0 live trading loop...")

        # Kill switch file (shared with COMPASS)
        kill_file = 'STOP_TRADING'

        try:
            while True:
                # Kill switch
                if os.path.exists(kill_file):
                    logger.warning("[rattlesnake] KILL SWITCH activated (STOP_TRADING file found)")
                    break

                try:
                    success = self.run_once()

                    if success:
                        time_module.sleep(interval)
                    else:
                        # Market closed or error: sleep longer
                        if not self.is_market_open():
                            time_module.sleep(300)  # 5 min when market closed
                        else:
                            time_module.sleep(max(10, interval // 6))

                except Exception as e:
                    logger.error(f"[rattlesnake] Error in loop: {e}", exc_info=True)
                    time_module.sleep(10)

        except KeyboardInterrupt:
            logger.info("[rattlesnake] Trading stopped by user")

        # Final save
        self.save_state()

        # Send daily summary if notifier available
        if self.notifier and self.trades_today:
            portfolio = self.broker.get_portfolio()
            self.notifier.send_daily_summary(
                portfolio.total_value, len(self.broker.positions),
                0, self.trades_today, self.current_regime, 1.0
            )

        uptime = datetime.now() - self._start_time
        logger.info(f"[rattlesnake] Session stats: {self._cycles_completed} cycles, "
                     f"uptime: {uptime.total_seconds() / 60:.0f} min")


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main entry point for standalone execution"""
    # Load external config if available
    config = CONFIG.copy()
    config_file = 'omnicapital_config.json'
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                ext_config = json.load(f)
            # Merge email, broker, paths (don't override algorithm params)
            logger.info(f"[rattlesnake] External config loaded: {config_file}")
        except Exception as e:
            logger.warning(f"[rattlesnake] Failed to load external config: {e}")

    # Create system
    trader = RATTLESNAKELive(config)

    # Load previous state
    trader.load_state()

    # Try to load notifications
    try:
        from omnicapital_notifications import EmailNotifier
        if os.path.exists(config_file):
            with open(config_file, 'r') as f:
                ext = json.load(f)
            email_cfg = ext.get('email', {})
            if email_cfg.get('smtp_server'):
                trader.notifier = EmailNotifier(**email_cfg)
                logger.info("[rattlesnake] Email notifications enabled")
    except ImportError:
        logger.info("[rattlesnake] Notifications module not found, running without email alerts")

    # Connect broker
    trader.broker.connect()

    # Verify data feed
    logger.info("[rattlesnake] Verifying data feed connection...")
    if not trader.data_feed.is_connected():
        logger.error("[rattlesnake] Data feed not connected")
        return

    test_prices = trader.data_feed.get_prices(['AAPL', 'MSFT', 'SPY'])
    logger.info(f"[rattlesnake] Price test: {len(test_prices)} symbols")
    for sym, price in list(test_prices.items())[:3]:
        logger.info(f"  {sym}: ${price:.2f}")

    # Start trading
    trader.run(interval=config['PRICE_UPDATE_INTERVAL'])


if __name__ == "__main__":
    main()
