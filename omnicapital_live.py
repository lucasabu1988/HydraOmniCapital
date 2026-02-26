"""
OmniCapital v8.2 COMPASS - Live Trading System
================================================
Sistema de trading en vivo basado en COMPASS v8.2.
Porta fielmente la logica del backtest a ejecucion en tiempo real.

Signal: Cross-sectional momentum (90d) + short-term reversal (5d skip)
Regime: SPY > SMA200 = RISK_ON, SPY < SMA200 = RISK_OFF
Sizing: Inverse volatility weighting
Leverage: Volatility targeting (auto-reduce en crisis)
Exits: Hold time (5d) + position stop (-8%) + trailing stop (3% desde max)
Recovery: Gradual en 3 etapas
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta, time, date
import logging
import json
import os
import sys
from typing import Dict, List, Optional, Set, Tuple
import warnings
import time as time_module
from zoneinfo import ZoneInfo

warnings.filterwarnings('ignore')

# Importar modulos propios
from omnicapital_data_feed import YahooDataFeed, MarketDataManager, HistoricalDataLoader
from omnicapital_broker import PaperBroker, Order, Broker, Position

# Git auto-sync (non-blocking, optional)
try:
    from git_sync import git_sync_async, git_sync_rotation
    _git_sync_available = True
except ImportError:
    try:
        from compass.git_sync import git_sync_async, git_sync_rotation
        _git_sync_available = True
    except ImportError:
        _git_sync_available = False

# ============================================================================
# LOGGING
# ============================================================================

os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'logs/compass_live_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# COMPASS v8.2 PARAMETERS (identical to backtest)
# ============================================================================

CONFIG = {
    # Signal
    'MOMENTUM_LOOKBACK': 90,
    'MOMENTUM_SKIP': 5,
    'MIN_MOMENTUM_STOCKS': 20,

    # Regime
    'REGIME_SMA_PERIOD': 200,
    'REGIME_CONFIRM_DAYS': 3,

    # Positions
    'NUM_POSITIONS': 5,
    'NUM_POSITIONS_RISK_OFF': 2,
    'HOLD_DAYS': 5,

    # Position-level risk
    'POSITION_STOP_LOSS': -0.08,
    'TRAILING_ACTIVATION': 0.05,
    'TRAILING_STOP_PCT': 0.03,

    # Portfolio-level risk
    'PORTFOLIO_STOP_LOSS': -0.15,

    # Recovery stages (time-based with regime confirmation)
    'RECOVERY_STAGE_1_DAYS': 63,
    'RECOVERY_STAGE_2_DAYS': 126,

    # Leverage & Vol targeting
    'TARGET_VOL': 0.15,
    'LEVERAGE_MIN': 0.3,
    'LEVERAGE_MAX': 1.0,          # Production: no leverage (broker margin destroys value)
    'VOL_LOOKBACK': 20,

    # Universe
    'TOP_N': 40,
    'MIN_AGE_DAYS': 63,

    # Costs
    'INITIAL_CAPITAL': 100_000,
    'MARGIN_RATE': 0.06,
    'COMMISSION_PER_SHARE': 0.001,

    # Market hours (ET)
    'MARKET_OPEN': time(9, 30),
    'MARKET_CLOSE': time(16, 0),

    # Pre-close execution: compute signal at 15:30, submit MOC before 15:50
    # Recovers ~0.79% CAGR vs next-day MOC (see chassis_preclose_analysis.py)
    'PRECLOSE_SIGNAL_TIME': time(15, 30),   # Compute signal at 15:30 ET
    'MOC_DEADLINE': time(15, 50),           # NYSE MOC deadline

    # Broker
    'BROKER_TYPE': 'PAPER',
    'PAPER_INITIAL_CASH': 100_000,

    # Data feed
    'DATA_FEED': 'YAHOO',
    'PRICE_UPDATE_INTERVAL': 60,
    'DATA_CACHE_DURATION': 60,
    'MAX_PRICE_AGE_SECONDS': 300,

    # Data validation
    'MIN_VALID_PRICE': 0.01,
    'MAX_VALID_PRICE': 50000,
    'MAX_PRICE_CHANGE_PCT': 0.20,

    # Order management
    'ORDER_TIMEOUT_SECONDS': 300,  # 5 min max for pending orders
    'MAX_FILL_DEVIATION': 0.02,  # 2% max fill price deviation

    # Monitoring intervals
    'STOP_CHECK_INTERVAL': 900,  # 15 min - check stops during market hours
    'STATE_SAVE_INTERVAL': 300,  # 5 min
}

# Broad pool (113 S&P 500 stocks) - identical to backtest
BROAD_POOL = [
    # Technology
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AVGO', 'ADBE', 'CRM', 'AMD',
    'INTC', 'CSCO', 'IBM', 'TXN', 'QCOM', 'ORCL', 'ACN', 'NOW', 'INTU',
    'AMAT', 'MU', 'LRCX', 'SNPS', 'CDNS', 'KLAC', 'MRVL',
    # Financials
    'BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'AXP', 'BLK',
    'SCHW', 'C', 'USB', 'PNC', 'TFC', 'CB', 'MMC', 'AIG',
    # Healthcare
    'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
    'AMGN', 'BMY', 'MDT', 'ISRG', 'SYK', 'GILD', 'REGN', 'VRTX', 'BIIB',
    # Consumer
    'AMZN', 'TSLA', 'WMT', 'HD', 'PG', 'COST', 'KO', 'PEP', 'NKE',
    'MCD', 'DIS', 'SBUX', 'TGT', 'LOW', 'CL', 'KMB', 'GIS', 'EL',
    'MO', 'PM',
    # Energy
    'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'OXY', 'MPC', 'PSX', 'VLO',
    # Industrials
    'GE', 'CAT', 'BA', 'HON', 'UNP', 'RTX', 'LMT', 'DE', 'UPS', 'FDX',
    'MMM', 'GD', 'NOC', 'EMR',
    # Utilities & Real Estate
    'NEE', 'DUK', 'SO', 'D', 'AEP',
    # Telecom
    'VZ', 'T', 'TMUS', 'CMCSA',
]


# ============================================================================
# DATA VALIDATION
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
            logger.warning(f"Price out of range for {symbol}: ${price:.2f}")
            return False

        # Sharp change check (only if we have history)
        if symbol in self._price_history and self._price_history[symbol]:
            last_prices = [p for _, p in self._price_history[symbol][-3:]]
            if last_prices:
                avg_last = np.mean(last_prices)
                if avg_last > 0:
                    change_pct = abs(price - avg_last) / avg_last
                    if change_pct > self.config['MAX_PRICE_CHANGE_PCT']:
                        logger.warning(f"Sharp price change rejected for {symbol}: "
                                      f"${price:.2f} vs avg ${avg_last:.2f} "
                                      f"({change_pct:.1%} > {self.config['MAX_PRICE_CHANGE_PCT']:.0%})")
                        return False
        return True

    def validate_price_freshness(self, symbol: str,
                                  max_age_seconds: int = 300) -> bool:
        """Check if our last recorded price is fresh enough to trust"""
        if symbol in self._price_history and self._price_history[symbol]:
            last_time, _ = self._price_history[symbol][-1]
            age = (datetime.now() - last_time).total_seconds()
            if age > max_age_seconds:
                logger.warning(f"Stale price for {symbol}: {age:.0f}s old "
                             f"(max {max_age_seconds}s)")
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
            logger.warning(f"Data validation rejected {len(rejected)}/{len(prices)} prices: "
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
# COMPASS v8.2 SIGNAL FUNCTIONS
# ============================================================================

def compute_annual_top40(broad_pool: List[str], top_n: int = 40) -> List[str]:
    """
    Compute current year's top-N stocks by avg daily dollar volume.
    Uses prior year's data, downloaded via yfinance.
    """
    current_year = datetime.now().year
    start = f'{current_year - 1}-01-01'
    end = f'{current_year}-01-01'

    logger.info(f"Computing top-{top_n} universe using {current_year - 1} data...")

    scores = {}
    for symbol in broad_pool:
        try:
            df = yf.download(symbol, start=start, end=end, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            if len(df) < 20:
                continue
            dollar_vol = (df['Close'] * df['Volume']).mean()
            scores[symbol] = dollar_vol
        except Exception as e:
            logger.debug(f"Failed to get data for {symbol}: {e}")
            continue

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top_n_symbols = [s for s, _ in ranked[:top_n]]
    logger.info(f"Universe: {len(top_n_symbols)} stocks selected from {len(scores)} with data")
    return top_n_symbols


def compute_live_regime(spy_hist: pd.DataFrame, sma_period: int = 200,
                        confirm_days: int = 3) -> Tuple[bool, int, bool]:
    """
    Compute current market regime from SPY history.
    Returns: (is_risk_on, consecutive_count, last_raw_signal)
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


def compute_momentum_scores(hist_data: Dict[str, pd.DataFrame],
                            tradeable: List[str],
                            lookback: int = 90,
                            skip: int = 5) -> Dict[str, float]:
    """
    Compute cross-sectional momentum score for each stock.
    Score = momentum_90d - skip_5d (high = strong trend + recent pullback)
    """
    scores = {}
    needed = lookback + skip

    for symbol in tradeable:
        if symbol not in hist_data:
            continue
        df = hist_data[symbol]
        if len(df) < needed:
            continue

        close_today = df['Close'].iloc[-1]
        close_skip = df['Close'].iloc[-skip - 1]
        close_lookback = df['Close'].iloc[-lookback - 1]

        if close_lookback <= 0 or close_skip <= 0 or close_today <= 0:
            continue

        momentum_90d = (close_skip / close_lookback) - 1.0
        skip_5d = (close_today / close_skip) - 1.0
        scores[symbol] = momentum_90d - skip_5d

    return scores


def compute_volatility_weights(hist_data: Dict[str, pd.DataFrame],
                               selected: List[str],
                               vol_lookback: int = 20) -> Dict[str, float]:
    """
    Inverse-volatility weights for selected stocks.
    Lower vol stocks get higher weight.
    """
    vols = {}
    for symbol in selected:
        if symbol not in hist_data:
            continue
        df = hist_data[symbol]
        if len(df) < vol_lookback + 2:
            continue
        returns = df['Close'].iloc[-(vol_lookback + 1):].pct_change().dropna()
        if len(returns) < vol_lookback - 2:
            continue
        vol = returns.std() * np.sqrt(252)
        if vol > 0.01:
            vols[symbol] = vol

    if not vols:
        return {s: 1.0 / len(selected) for s in selected}

    raw_weights = {s: 1.0 / v for s, v in vols.items()}
    total = sum(raw_weights.values())
    return {s: w / total for s, w in raw_weights.items()}


def compute_dynamic_leverage(spy_hist: pd.DataFrame, target_vol: float = 0.15,
                             vol_lookback: int = 20,
                             lev_min: float = 0.3, lev_max: float = 1.0) -> float:
    """
    Leverage = target_vol / realized_vol(SPY), clipped to [min, max]
    """
    if len(spy_hist) < vol_lookback + 2:
        return 1.0
    returns = spy_hist['Close'].iloc[-(vol_lookback + 1):].pct_change().dropna()
    if len(returns) < vol_lookback - 2:
        return 1.0
    realized_vol = returns.std() * np.sqrt(252)
    if realized_vol < 0.01:
        return lev_max
    leverage = target_vol / realized_vol
    return max(lev_min, min(lev_max, leverage))


# ============================================================================
# LIVE TRADING SYSTEM
# ============================================================================

class COMPASSLive:
    """COMPASS v8.2 Live Trading System"""

    def __init__(self, config: Dict):
        self.config = config
        self.validator = DataValidator(config)
        self.et_tz = ZoneInfo('America/New_York')

        # Data feed
        self.data_feed = YahooDataFeed(cache_duration=config['DATA_CACHE_DURATION'])

        # Broker
        self.broker = PaperBroker(
            initial_cash=config['PAPER_INITIAL_CASH'],
            commission_per_share=config['COMMISSION_PER_SHARE'],
            max_fill_deviation=config.get('MAX_FILL_DEVIATION', 0.02)
        )
        self.broker.set_price_feed(self.data_feed)

        # Execution strategy (chassis improvement — OFF by default)
        # Set to ExecutionStrategy instance to activate TWAP/VWAP/Passive
        # None = current MOC behavior preserved exactly
        self.execution_strategy = None

        # ---- COMPASS v8.2 State ----
        # Portfolio
        self.peak_value = float(config['PAPER_INITIAL_CASH'])
        self.in_protection = False
        self.protection_stage = 0  # 0=none, 1=stage1(0.3x), 2=stage2(1.0x)
        self.stop_loss_day_index = None
        self.post_stop_base = None

        # Regime
        self.current_regime = True  # True = RISK_ON
        self.regime_consecutive = 0
        self.regime_last_raw = True

        # Trading day counter (incremented each market day the system runs)
        self.trading_day_counter = 0
        self.last_trading_date = None

        # Position metadata (beyond what broker tracks)
        self.position_meta: Dict[str, dict] = {}
        # Each: {entry_price, entry_date, entry_day_index, high_price}

        # Universe
        self.current_universe: List[str] = []
        self.universe_year = None

        # Historical data cache (refreshed daily)
        self._hist_cache: Dict[str, pd.DataFrame] = {}
        self._spy_hist: Optional[pd.DataFrame] = None
        self._hist_date: Optional[date] = None

        # Tracking
        self.stop_events = []
        self.trades_today = []
        self._start_time = datetime.now()
        self._cycles_completed = 0
        self._consecutive_errors = 0
        self._max_consecutive_errors = 5
        self._last_stop_check = datetime.now()
        self._last_state_save = datetime.now()
        self._daily_open_done = False
        self._preclose_entries_done = False   # Pre-close entries for today

        # Cycle log tracking
        self._pre_rotation_value = None   # portfolio value before exits
        self._pre_rotation_positions = []  # tickers before exits
        self._rotation_sells_today = False # did we sell hold_expired today?

        # Notifications (set externally)
        self.notifier = None

        logger.info("=" * 70)
        logger.info("OMNICAPITAL v8.2 COMPASS - LIVE TRADING")
        logger.info("=" * 70)
        logger.info(f"Signal: Momentum {config['MOMENTUM_LOOKBACK']}d (skip {config['MOMENTUM_SKIP']}d)")
        logger.info(f"Regime: SPY SMA{config['REGIME_SMA_PERIOD']} | Vol target: {config['TARGET_VOL']:.0%}")
        logger.info(f"Hold: {config['HOLD_DAYS']}d | Pos stop: {config['POSITION_STOP_LOSS']:.0%}")
        logger.info(f"Trailing: +{config['TRAILING_ACTIVATION']:.0%} / -{config['TRAILING_STOP_PCT']:.0%}")
        logger.info(f"Portfolio stop: {config['PORTFOLIO_STOP_LOSS']:.0%}")
        logger.info(f"Leverage: max {config['LEVERAGE_MAX']:.1f}x (no leverage -- broker margin destroys value)")
        logger.info(f"Recovery: S1={config['RECOVERY_STAGE_1_DAYS']}d (0.3x), S2={config['RECOVERY_STAGE_2_DAYS']}d (1.0x)")
        logger.info(f"Universe: {len(BROAD_POOL)} broad pool -> top {config['TOP_N']}")
        logger.info(f"Execution: Pre-close signal @ {config['PRECLOSE_SIGNAL_TIME'].strftime('%H:%M')} ET "
                     f"-> same-day MOC (deadline {config['MOC_DEADLINE'].strftime('%H:%M')} ET)")
        logger.info(f"Chassis: async fetch | order timeout {config.get('ORDER_TIMEOUT_SECONDS', 300)}s | "
                     f"fill breaker {config.get('MAX_FILL_DEVIATION', 0.02):.0%} | data validation")

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

    def is_new_trading_day(self) -> bool:
        """Check if this is a new trading day"""
        today = self.get_et_now().date()
        return self.last_trading_date is None or today > self.last_trading_date

    # ------------------------------------------------------------------
    # Data refresh (called once per trading day)
    # ------------------------------------------------------------------

    def refresh_daily_data(self):
        """Download fresh historical data for all signals. Called at market open."""
        today = self.get_et_now().date()
        if self._hist_date == today:
            return  # Already refreshed today

        logger.info("Refreshing daily historical data...")

        # SPY for regime and vol targeting
        try:
            spy = yf.download('SPY', period='2y', progress=False)
            if isinstance(spy.columns, pd.MultiIndex):
                spy.columns = [c[0] for c in spy.columns]
            self._spy_hist = spy
            logger.info(f"SPY data: {len(spy)} days")
        except Exception as e:
            logger.error(f"Failed to download SPY: {e}")

        # Universe stocks for momentum scoring
        symbols_needed = set(self.current_universe) | set(self.position_meta.keys())
        for symbol in symbols_needed:
            try:
                df = yf.download(symbol, period='6mo', progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] for c in df.columns]
                if len(df) > 20:
                    self._hist_cache[symbol] = df
            except Exception as e:
                logger.debug(f"Failed to download {symbol}: {e}")

        logger.info(f"Historical data refreshed: {len(self._hist_cache)} stocks")
        self._hist_date = today

    def refresh_universe(self):
        """Refresh top-N universe if new year"""
        current_year = self.get_et_now().year
        if self.universe_year != current_year:
            logger.info(f"Computing {current_year} universe...")
            self.current_universe = compute_annual_top40(
                BROAD_POOL, self.config['TOP_N']
            )
            self.universe_year = current_year
            logger.info(f"Universe updated: {len(self.current_universe)} stocks")

    # ------------------------------------------------------------------
    # Regime detection
    # ------------------------------------------------------------------

    def update_regime(self):
        """Update market regime based on SPY vs SMA200"""
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
            logger.info(f"REGIME CHANGE -> {regime_str}")
            if self.notifier:
                spy_price = self._spy_hist['Close'].iloc[-1]
                sma = self._spy_hist['Close'].rolling(self.config['REGIME_SMA_PERIOD']).mean().iloc[-1]
                self.notifier.send_regime_change_alert(self.current_regime, spy_price, sma)

    # ------------------------------------------------------------------
    # Leverage computation
    # ------------------------------------------------------------------

    def get_current_leverage(self) -> float:
        """Determine current leverage based on protection/regime/vol"""
        if self.in_protection:
            if self.protection_stage == 1:
                return 0.3
            else:
                return 1.0
        elif not self.current_regime:  # RISK_OFF
            return 1.0
        else:  # RISK_ON, normal
            if self._spy_hist is not None:
                return compute_dynamic_leverage(
                    self._spy_hist,
                    self.config['TARGET_VOL'],
                    self.config['VOL_LOOKBACK'],
                    self.config['LEVERAGE_MIN'],
                    self.config['LEVERAGE_MAX']
                )
            return 1.0

    def get_max_positions(self) -> int:
        """Determine max positions based on regime/protection"""
        if self.in_protection:
            if self.protection_stage == 1:
                return 2
            else:
                return 3
        elif not self.current_regime:
            return self.config['NUM_POSITIONS_RISK_OFF']
        else:
            return self.config['NUM_POSITIONS']

    # ------------------------------------------------------------------
    # Recovery logic
    # ------------------------------------------------------------------

    def check_recovery(self):
        """Check and advance recovery stages (time-based + regime)"""
        if not self.in_protection or self.stop_loss_day_index is None:
            return

        days_since_stop = self.trading_day_counter - self.stop_loss_day_index

        if self.protection_stage == 1 and \
           days_since_stop >= self.config['RECOVERY_STAGE_1_DAYS'] and \
           self.current_regime:
            self.protection_stage = 2
            portfolio = self.broker.get_portfolio()
            logger.info(f"[RECOVERY S1] Stage 2 | Value: ${portfolio.total_value:,.0f}")
            if self.notifier:
                self.notifier.send_recovery_stage_alert(2, portfolio.total_value)

        if self.protection_stage == 2 and \
           days_since_stop >= self.config['RECOVERY_STAGE_2_DAYS'] and \
           self.current_regime:
            self.in_protection = False
            self.protection_stage = 0
            portfolio = self.broker.get_portfolio()
            self.peak_value = portfolio.total_value
            self.stop_loss_day_index = None
            self.post_stop_base = None
            logger.info(f"[RECOVERY S2] Full recovery | Value: ${portfolio.total_value:,.0f}")
            if self.notifier:
                self.notifier.send_recovery_stage_alert(0, portfolio.total_value)

    # ------------------------------------------------------------------
    # Portfolio stop loss
    # ------------------------------------------------------------------

    def check_portfolio_stop(self, prices: Dict[str, float]) -> bool:
        """Check and execute portfolio-level stop loss"""
        portfolio = self.broker.get_portfolio()
        pv = portfolio.total_value

        # Update peak (only when not in protection)
        if pv > self.peak_value and not self.in_protection:
            self.peak_value = pv

        drawdown = (pv - self.peak_value) / self.peak_value if self.peak_value > 0 else 0

        if drawdown <= self.config['PORTFOLIO_STOP_LOSS'] and not self.in_protection:
            logger.warning(f"[STOP LOSS] DD {drawdown:.1%} | Value: ${pv:,.0f}")

            # Close ALL positions
            positions = self.broker.get_positions()
            for symbol in list(positions.keys()):
                price = prices.get(symbol)
                if price:
                    pos = positions[symbol]
                    decision_px = prices.get(symbol, pos.avg_cost)
                    order = Order(symbol=symbol, action='SELL',
                                  quantity=pos.shares, order_type='MARKET',
                                  decision_price=decision_px)
                    result = self._submit_order(order, prices)
                    if result.status == 'FILLED':
                        meta = self.position_meta.pop(symbol, {})
                        entry_price = meta.get('entry_price', pos.avg_cost)
                        pnl = (result.filled_price - entry_price) * pos.shares - result.commission
                        self.trades_today.append({
                            'symbol': symbol, 'action': 'SELL',
                            'exit_reason': 'portfolio_stop', 'pnl': pnl,
                            'is_bps': result.is_bps
                        })
                        logger.info(f"  Closed {symbol}: PnL ${pnl:+,.0f}")

            # Enter protection
            self.in_protection = True
            self.protection_stage = 1
            self.stop_loss_day_index = self.trading_day_counter
            self.post_stop_base = self.broker.cash

            self.stop_events.append({
                'date': datetime.now().isoformat(),
                'portfolio_value': pv,
                'drawdown': drawdown
            })

            if self.notifier:
                self.notifier.send_portfolio_stop_alert(pv, drawdown, self.peak_value)

            self.save_state()
            return True

        return False

    # ------------------------------------------------------------------
    # Position exit logic (5 conditions from backtest)
    # ------------------------------------------------------------------

    def check_position_exits(self, prices: Dict[str, float]):
        """Check all 5 exit conditions for each position"""
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

            # 1. Hold time expired
            days_held = self.trading_day_counter - meta['entry_day_index']
            if days_held >= self.config['HOLD_DAYS']:
                exit_reason = 'hold_expired'

            # 2. Position stop loss (-8%)
            pos_return = (price - meta['entry_price']) / meta['entry_price']
            if pos_return <= self.config['POSITION_STOP_LOSS']:
                exit_reason = 'position_stop'

            # 3. Trailing stop
            if price > meta['high_price']:
                meta['high_price'] = price
            if meta['high_price'] > meta['entry_price'] * (1 + self.config['TRAILING_ACTIVATION']):
                trailing_level = meta['high_price'] * (1 - self.config['TRAILING_STOP_PCT'])
                if price <= trailing_level:
                    exit_reason = 'trailing_stop'

            # 4. Universe rotation
            if symbol not in self.current_universe:
                exit_reason = 'universe_rotation'

            # 5. Regime reduce (excess positions)
            if exit_reason is None and len(positions) > max_positions:
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
                decision_px = prices.get(symbol, meta.get('entry_price', pos.avg_cost))
                order = Order(symbol=symbol, action='SELL',
                              quantity=pos.shares, order_type='MARKET',
                              decision_price=decision_px)
                result = self._submit_order(order, prices)

                if result.status == 'FILLED':
                    pnl = (result.filled_price - meta['entry_price']) * pos.shares - result.commission
                    ret = pnl / (meta['entry_price'] * pos.shares) if meta['entry_price'] * pos.shares > 0 else 0
                    self.position_meta.pop(symbol, None)

                    self.trades_today.append({
                        'symbol': symbol, 'action': 'SELL',
                        'exit_reason': exit_reason, 'pnl': pnl, 'return': ret,
                        'price': result.filled_price, 'is_bps': result.is_bps
                    })
                    logger.info(f"EXIT [{exit_reason}] {symbol} @ ${result.filled_price:.2f} | "
                                f"PnL: ${pnl:+,.0f} ({ret:+.1%})")

                    if self.notifier:
                        self.notifier.send_trade_alert('SELL', symbol, pos.shares,
                                                       result.filled_price, exit_reason, pnl)

                    # Save state immediately after fill (crash protection)
                    self.save_state()

                # Refresh positions for remaining checks
                positions = self.broker.get_positions()

    # ------------------------------------------------------------------
    # Position entry logic
    # ------------------------------------------------------------------

    def open_new_positions(self, prices: Dict[str, float]):
        """Open new positions using momentum scoring + inverse-vol sizing"""
        positions = self.broker.get_positions()
        max_positions = self.get_max_positions()
        needed = max_positions - len(positions)

        if needed <= 0:
            return

        portfolio = self.broker.get_portfolio()
        if portfolio.cash <= 1000:
            return

        # Get tradeable symbols from universe with valid data
        tradeable = [s for s in self.current_universe
                     if s in self._hist_cache and s in prices]

        if len(tradeable) < self.config['MIN_MOMENTUM_STOCKS']:
            logger.debug(f"Not enough tradeable stocks: {len(tradeable)}")
            return

        # Compute momentum scores
        scores = compute_momentum_scores(
            self._hist_cache, tradeable,
            self.config['MOMENTUM_LOOKBACK'],
            self.config['MOMENTUM_SKIP']
        )

        # Filter out stocks already in portfolio
        available = {s: sc for s, sc in scores.items() if s not in positions}

        if len(available) < needed:
            return

        # Select top N by score
        ranked = sorted(available.items(), key=lambda x: x[1], reverse=True)
        selected = [s for s, _ in ranked[:needed]]

        # Compute inverse-vol weights
        weights = compute_volatility_weights(
            self._hist_cache, selected, self.config['VOL_LOOKBACK']
        )

        # Effective capital with leverage
        current_leverage = self.get_current_leverage()
        effective_capital = portfolio.cash * current_leverage * 0.95

        for symbol in selected:
            price = prices.get(symbol)
            if not price or price <= 0:
                continue

            weight = weights.get(symbol, 1.0 / len(selected))
            position_value = effective_capital * weight
            max_per_position = portfolio.cash * 0.40
            position_value = min(position_value, max_per_position)

            shares = int(position_value / price)  # whole shares only (IBKR requirement)
            if shares < 1:
                continue
            cost = shares * price
            commission = shares * self.config['COMMISSION_PER_SHARE']

            if cost + commission > portfolio.cash * 0.90:
                continue

            decision_px = price  # current price at signal time
            order = Order(symbol=symbol, action='BUY',
                          quantity=shares, order_type='MARKET',
                          decision_price=decision_px)
            result = self._submit_order(order, prices)

            if result.status == 'FILLED':
                self.position_meta[symbol] = {
                    'entry_price': result.filled_price,
                    'entry_date': self.get_et_now().date().isoformat(),
                    'entry_day_index': self.trading_day_counter,
                    'high_price': result.filled_price,
                }

                self.trades_today.append({
                    'symbol': symbol, 'action': 'BUY',
                    'price': result.filled_price,
                    'shares': shares, 'value': cost,
                    'is_bps': result.is_bps
                })
                logger.info(f"ENTRY {symbol}: {shares:.1f} shares @ ${result.filled_price:.2f} "
                            f"(${cost:,.0f} | wt={weight:.1%} | lev={current_leverage:.2f}x)")

                if self.notifier:
                    self.notifier.send_trade_alert('BUY', symbol, shares,
                                                   result.filled_price, None, None)

                # Save state immediately after fill (crash protection)
                self.save_state()

                # Update portfolio for next iteration
                portfolio = self.broker.get_portfolio()

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Order submission (with optional execution strategy)
    # ------------------------------------------------------------------

    def _submit_order(self, order: Order, prices: dict = None) -> Order:
        """Submit order through execution strategy if configured, else direct.

        Chassis hook: when self.execution_strategy is None (default),
        this is identical to self.broker.submit_order(order).
        When set, routes through TWAP/VWAP/Passive/Smart strategy.

        Implementation Shortfall (IS) is computed automatically on every fill
        when decision_price is available on the order.
        """
        if self.execution_strategy is not None and prices:
            price = prices.get(order.symbol, 0)
            market_data = {'price': price, 'volume': 0, 'adv': 0, 'spread_est': 0.001}
            result = self.execution_strategy.execute(self.broker, order, market_data)
        else:
            result = self.broker.submit_order(order)

        # --- Implementation Shortfall tracking ---
        if (result.status == 'FILLED' and result.filled_price
                and result.decision_price and result.decision_price > 0):
            if result.action == 'BUY':
                # BUY: paid more than decision = positive IS (cost)
                result.is_bps = (result.filled_price - result.decision_price) / result.decision_price * 10000
            else:
                # SELL: received less than decision = positive IS (cost)
                result.is_bps = (result.decision_price - result.filled_price) / result.decision_price * 10000

        return result

    # ------------------------------------------------------------------
    # Daily open routine
    # ------------------------------------------------------------------

    def daily_open(self):
        """Execute at market open each trading day"""
        if not self.is_new_trading_day():
            return

        today = self.get_et_now().date()
        self.last_trading_date = today
        self.trading_day_counter += 1
        self.trades_today = []
        self._daily_open_done = False
        self._preclose_entries_done = False
        self._rotation_sells_today = False

        # Snapshot portfolio before any exits (for cycle log)
        portfolio = self.broker.get_portfolio()
        self._pre_rotation_value = portfolio.total_value
        self._pre_rotation_positions = list(self.broker.positions.keys())

        logger.info(f"\n{'='*60}")
        logger.info(f"TRADING DAY {self.trading_day_counter} | {today}")
        logger.info(f"{'='*60}")

        # 1. Refresh universe (if new year)
        self.refresh_universe()

        # 2. Refresh historical data
        self.refresh_daily_data()

        # 3. Update regime
        self.update_regime()

        # 4. Check recovery
        self.check_recovery()

        # Log status
        current_leverage = self.get_current_leverage()
        max_pos = self.get_max_positions()
        regime_str = "RISK_ON" if self.current_regime else "RISK_OFF"
        prot_str = f" [PROTECTION S{self.protection_stage}]" if self.in_protection else ""

        portfolio = self.broker.get_portfolio()
        drawdown = (portfolio.total_value - self.peak_value) / self.peak_value \
            if self.peak_value > 0 else 0

        logger.info(f"Portfolio: ${portfolio.total_value:,.0f} | DD: {drawdown:.1%} | "
                     f"Regime: {regime_str}{prot_str} | "
                     f"Leverage: {current_leverage:.2f}x | "
                     f"Positions: {len(self.broker.positions)}/{max_pos}")

    def execute_trading_logic(self, prices: Dict[str, float]):
        """Daily open trading logic: exits only.
        Entries happen at pre-close (15:30 ET) via execute_preclose_entries().
        """
        # 1. Check portfolio stop loss
        if self.check_portfolio_stop(prices):
            return  # Stop triggered, no more trading today

        # 2. Check individual position exits
        self.check_position_exits(prices)

        # NOTE: Entries moved to execute_preclose_entries() at 15:30 ET
        # This recovers ~0.79% CAGR by using same-day MOC execution
        # instead of next-day execution (see chassis_preclose_analysis.py)

    def is_preclose_window(self) -> bool:
        """Check if we're in the pre-close entry window (15:30-15:50 ET)"""
        now_et = self.get_et_now()
        if now_et.weekday() >= 5:
            return False
        current_time = now_et.time()
        return (self.config['PRECLOSE_SIGNAL_TIME'] <= current_time
                <= self.config['MOC_DEADLINE'])

    def execute_preclose_entries(self, prices: Dict[str, float]):
        """Compute momentum signal and open new positions at pre-close.

        Called once per day during the 15:30-15:50 ET window.
        Signal uses yesterday's close (from _hist_cache), execution at
        current price (close to today's final close via MOC).

        Backtest validation: chassis_preclose_analysis.py variant C
        shows +0.79% CAGR and -7.8pp MaxDD improvement vs next-day MOC.
        """
        if self._preclose_entries_done:
            return

        logger.info(f"[PRE-CLOSE] Computing entry signal at {self.get_et_now().strftime('%H:%M:%S')} ET")

        # Check portfolio stop first (might have triggered intraday)
        if self.check_portfolio_stop(prices):
            self._preclose_entries_done = True
            return

        # Capture positions before new entries (to detect rotation)
        positions_before = set(self.broker.positions.keys())

        # Open new positions using momentum scores from historical data
        # The _hist_cache contains data up to yesterday's close (refreshed at open)
        # This is exactly the Close[T-1] signal validated in the backtest
        self.open_new_positions(prices)

        # Detect rotation: if we had sells (hold_expired) today AND new buys
        positions_after = set(self.broker.positions.keys())
        had_sells = any(t['action'] == 'SELL' and t.get('exit_reason') == 'hold_expired'
                        for t in self.trades_today)
        had_buys = any(t['action'] == 'BUY' for t in self.trades_today)
        if had_sells and had_buys:
            self._update_cycle_log(prices)

        self._preclose_entries_done = True
        self.save_state()
        logger.info(f"[PRE-CLOSE] Entry signal complete")

    # ------------------------------------------------------------------
    # Cycle log (automatic 5-day rotation tracking)
    # ------------------------------------------------------------------

    def _update_cycle_log(self, prices: Dict[str, float]):
        """Close the active cycle and open a new one in cycle_log.json.

        Called automatically after a rotation (hold_expired sells + new buys).
        Uses ^GSPC (S&P 500 index) for benchmark comparison.
        """
        log_file = os.path.join('state', 'cycle_log.json')
        today = self.get_et_now().date().isoformat()

        # Load existing log
        cycles = []
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r') as f:
                    cycles = json.load(f)
            except Exception:
                cycles = []

        # Get S&P 500 price for benchmark
        gspc_price = None
        try:
            gspc = yf.download('^GSPC', period='5d', progress=False)
            if len(gspc) > 0:
                gspc_price = float(gspc['Close'].iloc[-1].iloc[0])
        except Exception as e:
            logger.warning(f"Could not fetch ^GSPC for cycle log: {e}")

        # Portfolio value after rotation (new positions are in)
        portfolio = self.broker.get_portfolio()
        new_value = portfolio.total_value

        # Close the active cycle
        for cycle in cycles:
            if cycle.get('status') == 'active':
                cycle['end_date'] = today
                cycle['status'] = 'closed'
                cycle['portfolio_end'] = round(self._pre_rotation_value, 2)
                if gspc_price and cycle.get('spy_start'):
                    cycle['spy_end'] = round(gspc_price, 2)
                    cycle['spy_return'] = round(
                        (gspc_price - cycle['spy_start']) / cycle['spy_start'] * 100, 2)
                cycle['compass_return'] = round(
                    (self._pre_rotation_value - cycle['portfolio_start'])
                    / cycle['portfolio_start'] * 100, 2)
                if cycle.get('compass_return') is not None and cycle.get('spy_return') is not None:
                    cycle['alpha'] = round(cycle['compass_return'] - cycle['spy_return'], 2)

                status_str = 'WIN' if cycle['compass_return'] >= 0 else 'LOSS'
                logger.info(f"CYCLE #{cycle['cycle']} CLOSED: "
                           f"COMPASS {cycle['compass_return']:+.2f}% | "
                           f"S&P {cycle.get('spy_return', 0):+.2f}% | "
                           f"Alpha {cycle.get('alpha', 0):+.2f}pp | {status_str}")
                break

        # Open new cycle
        new_positions = list(self.broker.positions.keys())
        next_cycle = max((c.get('cycle', 0) for c in cycles), default=0) + 1

        cycles.append({
            'cycle': next_cycle,
            'start_date': today,
            'end_date': None,
            'status': 'active',
            'portfolio_start': round(new_value, 2),
            'portfolio_end': None,
            'spy_start': round(gspc_price, 2) if gspc_price else None,
            'spy_end': None,
            'positions': new_positions,
            'compass_return': None,
            'spy_return': None,
            'alpha': None,
        })

        # Save
        os.makedirs('state', exist_ok=True)
        with open(log_file, 'w') as f:
            json.dump(cycles, f, indent=2)

        logger.info(f"CYCLE #{next_cycle} OPENED: {', '.join(new_positions)} | "
                    f"${new_value:,.0f}")

        # WhatsApp/Email notification on rotation
        if self.notifier and hasattr(self.notifier, 'send_rotation_alert'):
            try:
                closed_cycle_data = next((c for c in cycles if c.get('cycle') == next_cycle - 1), {})
                self.notifier.send_rotation_alert(
                    cycle_num=next_cycle - 1,
                    closed_positions=self._pre_rotation_positions,
                    new_positions=new_positions,
                    compass_return=closed_cycle_data.get('compass_return', 0.0),
                    spy_return=closed_cycle_data.get('spy_return', 0.0),
                    alpha=closed_cycle_data.get('alpha', 0.0),
                )
            except Exception as e:
                logger.warning(f"Rotation notification failed: {e}")

        # Auto git sync: commit + push cycle log to Render
        if _git_sync_available:
            closed_cycle = next_cycle - 1
            closed_return = 0.0
            closed_status = 'WIN'
            for c in cycles:
                if c.get('cycle') == closed_cycle:
                    closed_return = c.get('compass_return', 0.0)
                    closed_status = 'WIN' if closed_return >= 0 else 'LOSS'
                    break
            try:
                git_sync_rotation(closed_cycle, closed_return, closed_status)
            except Exception as e:
                logger.warning(f"git sync rotation failed: {e}")

    def _ensure_active_cycle(self):
        """On startup, ensure cycle_log.json has an active cycle if we hold positions."""
        if not self.broker.positions:
            return

        log_file = os.path.join('state', 'cycle_log.json')
        cycles = []
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r') as f:
                    cycles = json.load(f)
            except Exception:
                cycles = []

        has_active = any(c.get('status') == 'active' for c in cycles)
        if has_active:
            return

        # No active cycle but we have positions — create one
        portfolio = self.broker.get_portfolio()
        gspc_price = None
        try:
            gspc = yf.download('^GSPC', period='5d', progress=False)
            if len(gspc) > 0:
                gspc_price = float(gspc['Close'].iloc[-1].iloc[0])
        except Exception:
            pass

        next_cycle = max((c.get('cycle', 0) for c in cycles), default=0) + 1
        today = self.last_trading_date.isoformat() if self.last_trading_date else date.today().isoformat()

        cycles.append({
            'cycle': next_cycle,
            'start_date': today,
            'end_date': None,
            'status': 'active',
            'portfolio_start': round(portfolio.total_value, 2),
            'portfolio_end': None,
            'spy_start': round(gspc_price, 2) if gspc_price else None,
            'spy_end': None,
            'positions': list(self.broker.positions.keys()),
            'compass_return': None,
            'spy_return': None,
            'alpha': None,
        })

        os.makedirs('state', exist_ok=True)
        with open(log_file, 'w') as f:
            json.dump(cycles, f, indent=2)

        logger.info(f"CYCLE #{next_cycle} initialized on startup: "
                    f"{list(self.broker.positions.keys())}")

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def save_state(self):
        """Save full system state to JSON"""
        portfolio = self.broker.get_portfolio()
        state = {
            'version': '8.2',
            'timestamp': datetime.now().isoformat(),

            # Portfolio
            'cash': self.broker.cash,
            'peak_value': self.peak_value,
            'portfolio_value': portfolio.total_value,

            # Protection / Recovery
            'in_protection': self.in_protection,
            'protection_stage': self.protection_stage,
            'stop_loss_day_index': self.stop_loss_day_index,
            'post_stop_base': self.post_stop_base,

            # Regime
            'current_regime': self.current_regime,
            'regime_consecutive': self.regime_consecutive,
            'regime_last_raw': self.regime_last_raw,

            # Counters
            'trading_day_counter': self.trading_day_counter,
            'last_trading_date': self.last_trading_date.isoformat() if self.last_trading_date else None,

            # Positions (broker)
            'positions': {
                s: {
                    'shares': p.shares,
                    'avg_cost': p.avg_cost,
                }
                for s, p in self.broker.positions.items()
            },

            # Position metadata (COMPASS)
            'position_meta': self.position_meta,

            # Universe
            'current_universe': self.current_universe,
            'universe_year': self.universe_year,

            # Events
            'stop_events': self.stop_events,

            # Intraday flags (prevents duplicate trades after mid-day restart)
            '_daily_open_done': getattr(self, '_daily_open_done', False),
            '_preclose_entries_done': getattr(self, '_preclose_entries_done', False),

            # Stats
            'stats': {
                'cycles_completed': self._cycles_completed,
                'uptime_minutes': (datetime.now() - self._start_time).total_seconds() / 60
            }
        }

        os.makedirs('state', exist_ok=True)
        filename = f'state/compass_state_{datetime.now().strftime("%Y%m%d")}.json'
        latest = 'state/compass_state_latest.json'

        # Atomic write: temp file + rename (prevents corruption on crash)
        import tempfile
        for target in [filename, latest]:
            try:
                fd, tmp_path = tempfile.mkstemp(dir='state', suffix='.json.tmp')
                with os.fdopen(fd, 'w') as fp:
                    json.dump(state, fp, indent=2, default=str)
                os.replace(tmp_path, target)
            except Exception as write_err:
                logger.error(f"Atomic write failed for {target}: {write_err}")
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

        logger.info(f"State saved: {filename}")

        # Auto git sync (non-blocking, never crashes engine)
        if _git_sync_available:
            try:
                git_sync_async(filename, latest)
            except Exception as e:
                logger.debug(f"git sync queue failed: {e}")

    def _try_load_json(self, filepath: str) -> dict:
        """Attempt to load and validate a state JSON file. Returns dict or None."""
        try:
            with open(filepath, 'r') as f:
                state = json.load(f)
            # Sanity check: must have critical fields
            if 'cash' not in state or 'positions' not in state:
                logger.warning(f"State file {filepath} missing critical fields")
                return None
            return state
        except (json.JSONDecodeError, IOError, OSError) as e:
            logger.warning(f"Failed to load {filepath}: {e}")
            return None

    def load_state(self):
        """Load previous state with fallback chain: latest -> dated -> HALT."""
        import glob

        # Build candidate list: latest first, then dated files newest-first
        candidates = []
        latest = 'state/compass_state_latest.json'
        if os.path.exists(latest):
            candidates.append(latest)
        dated_files = sorted(
            [f for f in glob.glob('state/compass_state_2*.json') if 'latest' not in f],
            key=os.path.getctime, reverse=True
        )
        candidates.extend(dated_files)

        if not candidates:
            logger.info("No previous state found, starting fresh")
            return

        # Try each candidate until one loads successfully
        state = None
        loaded_from = None
        for candidate in candidates:
            state = self._try_load_json(candidate)
            if state is not None:
                loaded_from = candidate
                break

        if state is None:
            logger.error("ALL state files corrupted or invalid — HALTING to prevent wrong trades")
            raise RuntimeError("Cannot load any valid state file. Manual intervention required.")

        # Restore portfolio state
        self.broker.cash = state.get('cash', self.config['PAPER_INITIAL_CASH'])
        self.peak_value = state.get('peak_value', self.config['PAPER_INITIAL_CASH'])

        # Restore protection/recovery
        self.in_protection = state.get('in_protection', False)
        self.protection_stage = state.get('protection_stage', 0)
        self.stop_loss_day_index = state.get('stop_loss_day_index')
        self.post_stop_base = state.get('post_stop_base')

        # Restore regime
        self.current_regime = state.get('current_regime', True)
        self.regime_consecutive = state.get('regime_consecutive', 0)
        self.regime_last_raw = state.get('regime_last_raw', True)

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

        # Restore universe
        self.current_universe = state.get('current_universe', [])
        self.universe_year = state.get('universe_year')

        # Restore events
        self.stop_events = state.get('stop_events', [])

        # Restore intraday flags (prevents duplicate trades after mid-day restart)
        self._daily_open_done = state.get('_daily_open_done', False)
        self._preclose_entries_done = state.get('_preclose_entries_done', False)

        regime_str = "RISK_ON" if self.current_regime else "RISK_OFF"
        prot_str = f" [PROTECTION S{self.protection_stage}]" if self.in_protection else ""

        logger.info(f"State loaded from {loaded_from}")
        logger.info(f"  Cash: ${self.broker.cash:,.0f} | Peak: ${self.peak_value:,.0f}")
        logger.info(f"  Positions: {len(self.broker.positions)} | Day: {self.trading_day_counter}")
        logger.info(f"  Regime: {regime_str}{prot_str}")
        if loaded_from != latest:
            logger.warning(f"  Loaded from FALLBACK file (not latest): {loaded_from}")

        # Position reconciliation (logs discrepancies vs broker)
        if hasattr(self.broker, 'reconcile_positions'):
            try:
                recon = self.broker.reconcile_positions(state.get('positions', {}))
                if recon.get('json_only') or recon.get('broker_only'):
                    logger.warning(f"POSITION RECONCILIATION MISMATCH: {recon}")
            except Exception as e:
                logger.warning(f"Position reconciliation failed: {e}")

        # Ensure cycle log has an active cycle if we have positions
        self._ensure_active_cycle()

    # ------------------------------------------------------------------
    # Status logging
    # ------------------------------------------------------------------

    def log_status(self, prices: Dict[str, float]):
        """Log current status"""
        portfolio = self.broker.get_portfolio()
        drawdown = (portfolio.total_value - self.peak_value) / self.peak_value \
            if self.peak_value > 0 else 0
        leverage = self.get_current_leverage()
        regime_str = "RISK_ON" if self.current_regime else "RISK_OFF"
        prot_str = f" [S{self.protection_stage}]" if self.in_protection else ""

        positions = self.broker.get_positions()
        pos_str = ", ".join([
            f"{s}({(prices.get(s, m.get('entry_price', 0)) - m.get('entry_price', 0)) / m.get('entry_price', 1):.1%})"
            for s, m in self.position_meta.items()
            if s in positions
        ])

        logger.info(f"STATUS: ${portfolio.total_value:,.0f} | DD:{drawdown:.1%} | "
                     f"{regime_str}{prot_str} | Lev:{leverage:.2f}x | "
                     f"Pos:{len(positions)}/{self.get_max_positions()} | "
                     f"[{pos_str}]")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_once(self) -> bool:
        """Execute one trading cycle"""
        self._cycles_completed += 1

        try:
            if not self.is_market_open():
                return False

            # New trading day setup
            if self.is_new_trading_day():
                self.daily_open()

            # Get current prices (async fetch + batch validation)
            symbols_needed = list(set(self.current_universe) |
                                  set(self.position_meta.keys()))
            raw_prices = self.data_feed.get_prices(symbols_needed)
            prices = self.validator.validate_batch(raw_prices)

            if not prices:
                logger.warning("No valid prices obtained after validation")
                self._consecutive_errors += 1
                return False

            self._consecutive_errors = 0

            # Update broker positions with current prices
            for symbol, price in prices.items():
                if symbol in self.broker.positions:
                    self.broker.positions[symbol].update_market_data(price)

            # Update high prices for trailing stops
            for symbol, meta in self.position_meta.items():
                price = prices.get(symbol)
                if price and price > meta.get('high_price', 0):
                    meta['high_price'] = price

            # Execute trading logic:
            # - At open: exits only (stops, hold expired, trailing, etc.)
            # - At 15:30 ET: new entries via pre-close signal + same-day MOC
            # - Intraday: check stops periodically
            if not self._daily_open_done:
                self.execute_trading_logic(prices)
                self._daily_open_done = True
                self.log_status(prices)

            # Pre-close entry window: 15:30-15:50 ET
            if not self._preclose_entries_done and self.is_preclose_window():
                self.execute_preclose_entries(prices)
                self.log_status(prices)

            # Intraday: check stops periodically
            if self._daily_open_done:
                now = datetime.now()
                if (now - self._last_stop_check).total_seconds() >= self.config['STOP_CHECK_INTERVAL']:
                    self.check_portfolio_stop(prices)
                    self.check_position_exits(prices)
                    self._last_stop_check = now

            # Check for stale orders (order timeout)
            if hasattr(self.broker, 'check_stale_orders'):
                stale = self.broker.check_stale_orders(
                    self.config.get('ORDER_TIMEOUT_SECONDS', 300)
                )
                if stale:
                    logger.warning(f"Cancelled {len(stale)} stale orders: "
                                  f"{', '.join(o.symbol for o in stale)}")

            # Periodic state save
            now = datetime.now()
            if (now - self._last_state_save).total_seconds() >= self.config['STATE_SAVE_INTERVAL']:
                self.save_state()
                self._last_state_save = now

            return True

        except Exception as e:
            logger.error(f"Error in trading cycle: {e}", exc_info=True)
            self._consecutive_errors += 1

            if self._consecutive_errors >= self._max_consecutive_errors:
                logger.critical(f"Too many consecutive errors ({self._consecutive_errors}). Stopping.")
                if self.notifier:
                    self.notifier.send_error_alert(str(e), "")
                raise RuntimeError("Too many consecutive errors")

            return False

    def run(self, interval: int = 60):
        """Main trading loop"""
        logger.info("Starting COMPASS v8.2 live trading loop...")

        # Kill switch check
        kill_file = 'STOP_TRADING'

        try:
            while True:
                # Kill switch
                if os.path.exists(kill_file):
                    logger.warning("KILL SWITCH activated (STOP_TRADING file found)")
                    break

                try:
                    success = self.run_once()

                    if success:
                        time_module.sleep(interval)
                    else:
                        # Market closed or error: sleep longer
                        if not self.is_market_open():
                            # Sleep until closer to market open
                            time_module.sleep(300)  # 5 min
                        else:
                            time_module.sleep(max(10, interval // 6))

                except Exception as e:
                    logger.error(f"Error in loop: {e}", exc_info=True)
                    time_module.sleep(10)

        except KeyboardInterrupt:
            logger.info("Trading stopped by user")

        # Final save
        self.save_state()

        # Send daily summary if notifier available
        if self.notifier and self.trades_today:
            portfolio = self.broker.get_portfolio()
            drawdown = (portfolio.total_value - self.peak_value) / self.peak_value \
                if self.peak_value > 0 else 0
            self.notifier.send_daily_summary(
                portfolio.total_value, len(self.broker.positions),
                drawdown, self.trades_today, self.current_regime,
                self.get_current_leverage()
            )

        uptime = datetime.now() - self._start_time
        logger.info(f"Session stats: {self._cycles_completed} cycles, "
                     f"uptime: {uptime.total_seconds() / 60:.0f} min")


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main entry point"""
    # Load external config if available
    config = CONFIG.copy()
    config_file = 'omnicapital_config.json'
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                ext_config = json.load(f)
            # Merge email, broker, paths (don't override algorithm params)
            logger.info(f"External config loaded: {config_file}")
        except Exception as e:
            logger.warning(f"Failed to load external config: {e}")

    # Create system
    trader = COMPASSLive(config)

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
                logger.info("Email notifications enabled")
    except ImportError:
        logger.info("Notifications module not found, running without email alerts")

    # Connect broker
    trader.broker.connect()

    # Verify data feed
    logger.info("Verifying data feed connection...")
    if not trader.data_feed.is_connected():
        logger.error("Data feed not connected")
        return

    test_prices = trader.data_feed.get_prices(['AAPL', 'MSFT', 'SPY'])
    logger.info(f"Price test: {len(test_prices)} symbols")
    for sym, price in list(test_prices.items())[:3]:
        logger.info(f"  {sym}: ${price:.2f}")

    # Start trading
    trader.run(interval=config['PRICE_UPDATE_INTERVAL'])


if __name__ == "__main__":
    main()
