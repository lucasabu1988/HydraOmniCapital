"""
OmniCapital HYDRA - Live Trading System (4 Strategies)
=======================================================
Multi-strategy system: COMPASS v8.4 (momentum) + Rattlesnake v1.0
(mean-reversion) + Catalyst (cross-asset trend + gold) + EFA (international).

COMPASS: Risk-adjusted cross-sectional momentum (90d return / 63d vol)
Rattlesnake: RSI<25 dip-buying on S&P 100 (uptrend filter)
Catalyst: Cross-asset trend (TLT/ZROZ/GLD/DBC above SMA200)
HYDRA: Cash recycling between COMPASS and Rattlesnake (cap 75%)

Results (backtest 2000-2026):
  CAGR 15.62% | MaxDD -21.7% | Sharpe 1.08
"""

import math
import re
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, time, date, timedelta
import logging
from logging.handlers import RotatingFileHandler
import json
import os
import sys
import glob
import tempfile
import copy
import signal
import threading
from collections import defaultdict
from typing import Dict, List, Optional, Tuple
import warnings
import time as time_module
from zoneinfo import ZoneInfo

warnings.filterwarnings('ignore')

# Importar modulos propios
from omnicapital_data_feed import YahooDataFeed
from omnicapital_broker import PaperBroker, IBKRBroker, Order, Position

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

# ML Learning System (non-blocking, optional)
try:
    from compass_ml_learning import COMPASSMLOrchestrator
    _ml_available = True
except ImportError:
    _ml_available = False

_ml_error_counts = {
    'entry': 0,
    'exit': 0,
    'hold': 0,
    'skip': 0,
    'snapshot': 0,
}

# HYDRA: Rattlesnake + Cash Recycling (non-blocking, optional)
try:
    from rattlesnake_signals import (  # noqa: F401 - optional dependency availability gate
        R_UNIVERSE, R_MAX_POSITIONS, R_POSITION_SIZE, R_MAX_POS_RISK_OFF,
        find_rattlesnake_candidates, check_rattlesnake_exit,
        check_rattlesnake_regime, compute_rattlesnake_exposure,
    )
    from hydra_capital import HydraCapitalManager
    _hydra_available = True
except ImportError:
    _hydra_available = False

try:
    from catalyst_signals import (  # noqa: F401 - optional dependency availability gate
        compute_catalyst_targets, compute_trend_holdings,
        CATALYST_TREND_ASSETS, CATALYST_REBALANCE_DAYS,
    )
    _catalyst_available = True
except ImportError:
    _catalyst_available = False

# Overlay system (v3: BSO + M2 + FOMC + FedEmergency + CreditFilter)
try:
    from compass_fred_data import download_all_overlay_data
    from compass_overlays import (  # noqa: F401 - optional dependency availability gate
        BankingStressOverlay, M2MomentumIndicator, FOMCSurpriseSignal,
        FedEmergencySignal, CreditSectorPreFilter, compute_overlay_signals,
        OVERLAY_FLOOR,
    )
    _overlay_available = True
except ImportError:
    _overlay_available = False

# ============================================================================
# LOGGING
# ============================================================================

os.makedirs('logs', exist_ok=True)
_log_format = '%(asctime)s - %(levelname)s - %(message)s'
_log_formatter = logging.Formatter(_log_format)

_file_handler = RotatingFileHandler(
    f'logs/compass_live_{datetime.now().strftime("%Y%m%d")}.log',
    maxBytes=50 * 1024 * 1024,  # 50 MB
    backupCount=5,
    encoding='utf-8',
)
_file_handler.setFormatter(_log_formatter)

_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setFormatter(_log_formatter)

logging.basicConfig(
    level=logging.INFO,
    format=_log_format,
    handlers=[_file_handler, _stream_handler]
)
logger = logging.getLogger(__name__)

# ============================================================================
# COMPASS v8.4 PARAMETERS (identical to backtest)
# ============================================================================

CONFIG = {
    # Signal
    'MOMENTUM_LOOKBACK': 90,
    'MOMENTUM_SKIP': 5,
    'MIN_MOMENTUM_STOCKS': 20,

    # Positions
    'NUM_POSITIONS': 5,
    'NUM_POSITIONS_RISK_OFF': 2,
    'HOLD_DAYS': 5,

    # Position-level risk (v8.4: adaptive stops)
    'POSITION_STOP_LOSS': -0.08,           # Fallback if no entry_daily_vol available
    'TRAILING_ACTIVATION': 0.05,
    'TRAILING_STOP_PCT': 0.03,

    # v8.4: Adaptive stops (vol-scaled)
    'STOP_DAILY_VOL_MULT': 2.5,            # Stop = -2.5 * daily_vol
    'STOP_FLOOR': -0.06,                   # Tightest stop for low-vol stocks
    'STOP_CEILING': -0.15,                 # Widest stop for high-vol stocks
    'TRAILING_VOL_BASELINE': 0.25,         # Baseline annualized vol for trailing scaling

    # v8.4: Bull market override (regime recalibration)
    'BULL_OVERRIDE_THRESHOLD': 0.03,       # SPY > SMA200 * 1.03 -> bump +1 position
    'BULL_OVERRIDE_MIN_SCORE': 0.40,       # Only override if regime_score > this

    # v8.4: Sector concentration limits
    'MAX_PER_SECTOR': 3,                   # Max open positions per sector

    # Smooth drawdown scaling
    'DD_SCALE_TIER1': -0.10,
    'DD_SCALE_TIER2': -0.20,
    'DD_SCALE_TIER3': -0.35,
    'LEV_FULL': 1.0,
    'LEV_MID': 0.60,
    'LEV_FLOOR': 0.30,
    'CRASH_VEL_5D': -0.06,
    'CRASH_VEL_10D': -0.10,
    'CRASH_LEVERAGE': 0.15,
    'CRASH_COOLDOWN': 10,

    # Exit renewal
    'HOLD_DAYS_MAX': 10,
    'RENEWAL_PROFIT_MIN': 0.04,
    'MOMENTUM_RENEWAL_THRESHOLD': 0.85,

    # Quality filter
    'QUALITY_VOL_MAX': 0.60,
    'QUALITY_VOL_LOOKBACK': 63,
    'QUALITY_MAX_SINGLE_DAY': 0.50,

    # Leverage & Vol targeting
    'TARGET_VOL': 0.15,
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
    'IBKR_HOST': '127.0.0.1',
    'IBKR_PORT': 7497,       # 7497=paper, 7496=live
    'IBKR_CLIENT_ID': 1,
    'IBKR_MOCK': True,       # Start mock, switch to live later
    'MAX_ORDER_VALUE': 50_000,

    # Data feed
    'DATA_FEED': 'YAHOO',
    'PRICE_UPDATE_INTERVAL': 60,
    'DATA_CACHE_DURATION': 60,
    'PRICE_STALE_WARN_SECONDS': 120,
    'PRICE_STALE_SKIP_SECONDS': 300,
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

# US market holidays (NYSE/NASDAQ closed) — update annually
US_MARKET_HOLIDAYS = {
    # 2026
    date(2026, 1, 1),   # New Year's Day
    date(2026, 1, 19),  # MLK Day
    date(2026, 2, 16),  # Presidents' Day
    date(2026, 4, 3),   # Good Friday
    date(2026, 5, 25),  # Memorial Day
    date(2026, 6, 19),  # Juneteenth
    date(2026, 7, 3),   # Independence Day (observed)
    date(2026, 9, 7),   # Labor Day
    date(2026, 11, 26), # Thanksgiving
    date(2026, 12, 25), # Christmas
    # 2027 (cover full year ahead)
    date(2027, 1, 1),   # New Year's Day
    date(2027, 1, 18),  # MLK Day
    date(2027, 2, 15),  # Presidents' Day
    date(2027, 3, 26),  # Good Friday
    date(2027, 5, 31),  # Memorial Day
    date(2027, 6, 18),  # Juneteenth (observed Fri)
    date(2027, 7, 5),   # Independence Day (observed Mon)
    date(2027, 9, 6),   # Labor Day
    date(2027, 11, 25), # Thanksgiving
    date(2027, 12, 24), # Christmas (observed Fri)
}

# EFA Third Pillar (HYDRA: idle cash → international developed markets)
EFA_SYMBOL = 'EFA'
EFA_SMA_PERIOD = 200
EFA_MIN_BUY = 1000  # Minimum idle cash to trigger EFA purchase

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

# v8.4: Sector map for concentration limits
SECTOR_MAP = {
    # Technology
    'AAPL': 'Technology', 'MSFT': 'Technology', 'NVDA': 'Technology', 'GOOGL': 'Technology',
    'META': 'Technology', 'AVGO': 'Technology', 'ADBE': 'Technology', 'CRM': 'Technology',
    'AMD': 'Technology', 'INTC': 'Technology', 'CSCO': 'Technology', 'IBM': 'Technology',
    'TXN': 'Technology', 'QCOM': 'Technology', 'ORCL': 'Technology', 'ACN': 'Technology',
    'NOW': 'Technology', 'INTU': 'Technology', 'AMAT': 'Technology', 'MU': 'Technology',
    'LRCX': 'Technology', 'SNPS': 'Technology', 'CDNS': 'Technology', 'KLAC': 'Technology',
    'MRVL': 'Technology', 'GOOG': 'Technology', 'PLTR': 'Technology', 'APP': 'Technology',
    'SMCI': 'Technology', 'CRWD': 'Technology',
    # Financials
    'BRK-B': 'Financials', 'JPM': 'Financials', 'V': 'Financials', 'MA': 'Financials',
    'BAC': 'Financials', 'WFC': 'Financials', 'GS': 'Financials', 'MS': 'Financials',
    'AXP': 'Financials', 'BLK': 'Financials', 'SCHW': 'Financials', 'C': 'Financials',
    'USB': 'Financials', 'PNC': 'Financials', 'TFC': 'Financials', 'CB': 'Financials',
    'MMC': 'Financials', 'AIG': 'Financials', 'HOOD': 'Financials', 'COIN': 'Financials',
    # Healthcare
    'UNH': 'Healthcare', 'JNJ': 'Healthcare', 'LLY': 'Healthcare', 'ABBV': 'Healthcare',
    'MRK': 'Healthcare', 'PFE': 'Healthcare', 'TMO': 'Healthcare', 'ABT': 'Healthcare',
    'DHR': 'Healthcare', 'AMGN': 'Healthcare', 'BMY': 'Healthcare', 'MDT': 'Healthcare',
    'ISRG': 'Healthcare', 'SYK': 'Healthcare', 'GILD': 'Healthcare', 'REGN': 'Healthcare',
    'VRTX': 'Healthcare', 'BIIB': 'Healthcare',
    # Consumer
    'AMZN': 'Consumer', 'TSLA': 'Consumer', 'WMT': 'Consumer', 'HD': 'Consumer',
    'PG': 'Consumer', 'COST': 'Consumer', 'KO': 'Consumer', 'PEP': 'Consumer',
    'NKE': 'Consumer', 'MCD': 'Consumer', 'DIS': 'Consumer', 'SBUX': 'Consumer',
    'TGT': 'Consumer', 'LOW': 'Consumer', 'CL': 'Consumer', 'KMB': 'Consumer',
    'GIS': 'Consumer', 'EL': 'Consumer', 'MO': 'Consumer', 'PM': 'Consumer',
    'NFLX': 'Consumer', 'UBER': 'Consumer',
    # Energy
    'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'SLB': 'Energy',
    'EOG': 'Energy', 'OXY': 'Energy', 'MPC': 'Energy', 'PSX': 'Energy', 'VLO': 'Energy',
    # Industrials
    'GE': 'Industrials', 'CAT': 'Industrials', 'BA': 'Industrials', 'HON': 'Industrials',
    'UNP': 'Industrials', 'RTX': 'Industrials', 'LMT': 'Industrials', 'DE': 'Industrials',
    'UPS': 'Industrials', 'FDX': 'Industrials', 'MMM': 'Industrials', 'GD': 'Industrials',
    'NOC': 'Industrials', 'EMR': 'Industrials', 'GEV': 'Industrials',
    # Utilities
    'NEE': 'Utilities', 'DUK': 'Utilities', 'SO': 'Utilities', 'D': 'Utilities', 'AEP': 'Utilities',
    # Telecom
    'VZ': 'Telecom', 'T': 'Telecom', 'TMUS': 'Telecom', 'CMCSA': 'Telecom',
}


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
# UTILITIES
# ============================================================================

def _sanitize_nan(obj):
    """Replace float NaN/Inf with None in nested dicts/lists (in-place)."""
    if isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, float) and not math.isfinite(v):
                obj[i] = None
            elif isinstance(v, (dict, list)):
                _sanitize_nan(v)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, float) and not math.isfinite(v):
                obj[k] = None
            elif isinstance(v, (dict, list)):
                _sanitize_nan(v)


# ============================================================================
# COMPASS v8.4 SIGNAL FUNCTIONS
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


_VALID_SYMBOL_RE = re.compile(r'^[A-Z]{1,5}$')
_CATALYST_EFA_TICKERS = {'TLT', 'GLD', 'DBC', 'EFA'}


def validate_universe(symbols):
    seen = set()
    validated = []
    for sym in symbols:
        if sym in seen:
            logger.warning(f"Universe validation: removing duplicate '{sym}'")
            continue
        seen.add(sym)
        if not _VALID_SYMBOL_RE.match(sym):
            logger.warning(f"Universe validation: rejecting invalid symbol '{sym}'")
            continue
        if sym in _CATALYST_EFA_TICKERS:
            logger.warning(f"Universe validation: excluding Catalyst/EFA ticker '{sym}' from COMPASS universe")
            continue
        validated.append(sym)
    return validated


def _sigmoid(x: float, k: float = 15.0) -> float:
    """Logistic sigmoid: maps (-inf, +inf) -> (0, 1)."""
    z = float(np.clip(k * x, -20.0, 20.0))
    return 1.0 / (1.0 + np.exp(-z))


def compute_live_regime_score(spy_hist: pd.DataFrame) -> float:
    """
    Compute continuous market regime score [0.0, 1.0] from SPY history.
    0.0 = extreme bear, 1.0 = strong bull.
    """
    if len(spy_hist) < 252:
        return 0.5

    spy_close = spy_hist['Close']
    current = float(spy_close.iloc[-1])

    sma200 = float(spy_close.iloc[-200:].mean())
    sma50 = float(spy_close.iloc[-50:].mean())

    if sma200 <= 0:
        return 0.5

    dist_200 = (current / sma200) - 1.0
    sig_200 = _sigmoid(dist_200, k=15.0)

    cross = (sma50 / sma200) - 1.0 if sma200 > 0 else 0.0
    sig_cross = _sigmoid(cross, k=30.0)

    if len(spy_close) >= 21:
        price_20d_ago = float(spy_close.iloc[-21])
        sig_mom = _sigmoid((current / price_20d_ago) - 1.0, k=15.0) if price_20d_ago > 0 else 0.5
    else:
        sig_mom = 0.5

    trend_score = (sig_200 + sig_cross + sig_mom) / 3.0

    returns = spy_close.pct_change().dropna()
    vol_score = 0.5
    if len(returns) >= 262:
        current_vol = float(returns.iloc[-10:].std() * np.sqrt(252))
        rolling_vol = returns.iloc[-252:].rolling(window=10).std() * np.sqrt(252)
        rolling_vol = rolling_vol.dropna()
        if len(rolling_vol) >= 20 and current_vol > 0:
            pct_rank = float((rolling_vol <= current_vol).sum()) / len(rolling_vol)
            vol_score = 1.0 - pct_rank

    composite = 0.60 * trend_score + 0.40 * vol_score
    return float(np.clip(composite, 0.0, 1.0))


def regime_score_to_positions(regime_score: float,
                               num_positions: int = 5,
                               num_positions_risk_off: int = 2,
                               spy_close: Optional[float] = None,
                               sma200: Optional[float] = None,
                               bull_threshold: float = 0.03,
                               bull_min_score: float = 0.40) -> int:
    """Convert continuous regime score to number of positions.
    v8.4: Bull market override -- when SPY is >3% above SMA200 and score > 0.40,
    bump positions by +1 (capped at max). Prevents vol spikes from
    reducing positions during confirmed uptrends.
    """
    if regime_score >= 0.65:
        base = num_positions
    elif regime_score >= 0.50:
        base = max(num_positions - 1, num_positions_risk_off + 1)
    elif regime_score >= 0.35:
        base = max(num_positions - 2, num_positions_risk_off + 1)
    else:
        base = num_positions_risk_off

    # v8.4 Bull override: +1 position when SPY clearly above SMA200
    if (spy_close is not None and sma200 is not None
            and sma200 > 0 and regime_score > bull_min_score):
        pct_above = (spy_close / sma200) - 1.0
        if pct_above >= bull_threshold:
            base = min(base + 1, num_positions)

    return base


def compute_momentum_scores(hist_data: Dict[str, pd.DataFrame],
                            tradeable: List[str],
                            lookback: int = 90,
                            skip: int = 5) -> Dict[str, float]:
    """Compute risk-adjusted momentum score (return / realized vol)."""
    scores = {}
    needed = lookback + skip
    RISK_ADJ_VOL_WINDOW = 63

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

        momentum_raw = (close_skip / close_lookback) - 1.0
        skip_5d = (close_today / close_skip) - 1.0
        raw_score = momentum_raw - skip_5d

        # Risk adjustment
        vol_window = min(RISK_ADJ_VOL_WINDOW, len(df) - 2)
        if vol_window >= 20:
            returns = df['Close'].iloc[-(vol_window + 1):].pct_change().dropna()
            if len(returns) >= 15:
                ann_vol = float(returns.std() * (252 ** 0.5))
                if ann_vol > 0.01:
                    val = raw_score / ann_vol
                else:
                    val = raw_score
            else:
                val = raw_score
            
            # Ensure finite score
            if np.isfinite(val):
                scores[symbol] = float(val)
            else:
                scores[symbol] = 0.0
        else:
            if np.isfinite(raw_score):
                scores[symbol] = float(raw_score)
            else:
                scores[symbol] = 0.0

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


def compute_quality_filter(hist_data: Dict[str, pd.DataFrame],
                           tradeable: List[str],
                           vol_max: float = 0.60,
                           vol_lookback: int = 63,
                           max_single_day: float = 0.50) -> List[str]:
    """Filter out stocks with extreme vol or data corruption."""
    passed = []
    for symbol in tradeable:
        if symbol not in hist_data:
            continue
        df = hist_data[symbol]
        if len(df) < vol_lookback + 2:
            passed.append(symbol)
            continue
        rets = df['Close'].iloc[-(vol_lookback + 1):].pct_change().dropna()
        if len(rets) < vol_lookback - 5:
            passed.append(symbol)
            continue
        if float(rets.abs().max()) > max_single_day:
            continue
        ann_vol = float(rets.std() * np.sqrt(252))
        if ann_vol <= vol_max:
            passed.append(symbol)
    if len(passed) < 5:
        return tradeable
    return passed


# ============================================================================
# v8.4: ADAPTIVE STOPS
# ============================================================================

def compute_adaptive_stop(entry_daily_vol: float, config: Dict) -> float:
    """
    v8.4: Compute adaptive position stop loss based on entry-time daily volatility.
    Stop = max(CEILING, min(FLOOR, -MULT * daily_vol))

    Examples (MULT=2.5, FLOOR=-6%, CEILING=-15%):
      Low-vol  (daily_vol=1.0%):  stop = -6.0%  (FLOOR)
      Med-vol  (daily_vol=2.5%):  stop = -6.25%
      Typical  (daily_vol=3.5%):  stop = -8.75%
      High-vol (daily_vol=4.5%):  stop = -11.25%
      Very-high (daily_vol=6%+):  stop = -15.0% (CEILING)
    """
    if entry_daily_vol is None:
        return config['STOP_FLOOR']

    try:
        entry_daily_vol = float(entry_daily_vol)
    except (TypeError, ValueError):
        return config['STOP_FLOOR']

    if not math.isfinite(entry_daily_vol) or entry_daily_vol <= 0:
        return config['STOP_FLOOR']

    raw_stop = -config['STOP_DAILY_VOL_MULT'] * entry_daily_vol
    return max(config['STOP_CEILING'], min(config['STOP_FLOOR'], raw_stop))


def compute_entry_vol(hist_data: Dict[str, pd.DataFrame],
                      symbol: str, lookback: int = 20) -> Tuple[float, float]:
    """
    v8.4: Compute volatility for a stock at entry time using most recent data.
    Returns (annualized_vol, daily_vol).
    Daily vol is used for adaptive stop calculation.
    Falls back to (0.25, 0.016) if insufficient data.
    """
    DEFAULT_ANN = 0.25
    DEFAULT_DAILY = DEFAULT_ANN / np.sqrt(252)

    if symbol not in hist_data:
        return (DEFAULT_ANN, DEFAULT_DAILY)
    df = hist_data[symbol]
    if len(df) < lookback + 2:
        return (DEFAULT_ANN, DEFAULT_DAILY)

    returns = df['Close'].iloc[-(lookback + 1):].pct_change().dropna()
    if len(returns) < lookback - 2:
        return (DEFAULT_ANN, DEFAULT_DAILY)

    daily_vol = float(returns.std())
    ann_vol = daily_vol * np.sqrt(252)
    return (max(ann_vol, 0.05), max(daily_vol, 0.003))


def filter_by_sector_concentration(ranked_candidates: List[Tuple[str, float]],
                                    current_positions: dict,
                                    max_per_sector: int = 3) -> List[str]:
    """
    v8.4: Filter ranked candidates by sector concentration limits.
    Iterates through ranked candidates and only selects those whose sector
    has room (< max_per_sector positions).
    """
    sector_counts: Dict[str, int] = defaultdict(int)
    for sym in current_positions:
        sector = SECTOR_MAP.get(sym, 'Unknown')
        sector_counts[sector] += 1

    selected = []
    for symbol, score in ranked_candidates:
        sector = SECTOR_MAP.get(symbol, 'Unknown')
        if sector_counts[sector] < max_per_sector:
            selected.append(symbol)
            sector_counts[sector] += 1

    return selected


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


def _dd_leverage(drawdown: float, config: Dict) -> float:
    """Piecewise-linear drawdown leverage scaling."""
    dd = drawdown
    t1, t2, t3 = config['DD_SCALE_TIER1'], config['DD_SCALE_TIER2'], config['DD_SCALE_TIER3']
    lf, lm, lfl = config['LEV_FULL'], config['LEV_MID'], config['LEV_FLOOR']
    if dd >= t1:
        return lf
    elif dd >= t2:
        frac = (dd - t1) / (t2 - t1)
        return lf + frac * (lm - lf)
    elif dd >= t3:
        frac = (dd - t2) / (t3 - t2)
        return lm + frac * (lfl - lm)
    else:
        return lfl


# ============================================================================
# LIVE TRADING SYSTEM
# ============================================================================

class COMPASSLive:
    """COMPASS v8.4 Live Trading System"""

    def __init__(self, config: Dict):
        self.config = config
        self.validator = DataValidator(config)
        self.et_tz = ZoneInfo('America/New_York')

        # Data feed
        self.data_feed = YahooDataFeed(cache_duration=config['DATA_CACHE_DURATION'])

        # Broker (factory based on config)
        broker_type = config.get('BROKER_TYPE', 'PAPER').upper()
        if broker_type == 'IBKR':
            self.broker = IBKRBroker(
                host=config.get('IBKR_HOST', '127.0.0.1'),
                port=config.get('IBKR_PORT', 7497),
                client_id=config.get('IBKR_CLIENT_ID', 1),
                mock=config.get('IBKR_MOCK', True),
                max_order_value=config.get('MAX_ORDER_VALUE', 50_000),
                price_feed=self.data_feed,
            )
        else:
            self.broker = PaperBroker(
                initial_cash=config['PAPER_INITIAL_CASH'],
                commission_per_share=config['COMMISSION_PER_SHARE'],
                max_fill_deviation=config.get('MAX_FILL_DEVIATION', 0.02)
            )
            self.broker.set_price_feed(self.data_feed)
        logger.info(f"Broker: {broker_type} ({'mock' if getattr(self.broker, 'mock', True) else 'LIVE'})")

        # Execution strategy (chassis improvement — OFF by default)
        # Set to ExecutionStrategy instance to activate TWAP/VWAP/Passive
        # None = current MOC behavior preserved exactly
        self.execution_strategy = None

        # ---- COMPASS v8.4 State ----
        # Portfolio
        self.peak_value = float(config['PAPER_INITIAL_CASH'])
        self.crash_cooldown = 0
        self.portfolio_values_history = []  # For crash velocity tracking

        # Regime (continuous sigmoid score)
        self.current_regime_score = 0.5
        self._last_regime_refresh = None  # timestamp of last regime recomputation

        # Trading day counter (incremented each market day the system runs)
        self.trading_day_counter = 0
        self.last_trading_date = None

        # Position metadata (beyond what broker tracks)
        self.position_meta: Dict[str, dict] = {}
        # Each: {entry_price, entry_date, entry_day_index, original_entry_day_index, high_price}

        # Cached momentum scores (for exit renewal checks)
        self._current_scores: Dict[str, float] = {}

        # Universe
        self.current_universe: List[str] = []
        self.universe_year = None

        # Historical data cache (refreshed daily)
        self._hist_cache: Dict[str, pd.DataFrame] = {}
        self._spy_hist: Optional[pd.DataFrame] = None
        self._hist_date: Optional[date] = None

        # Tracking
        self.trades_today = []
        self._block_new_entries = False  # Set True if SPY data unavailable
        self._pending_stop_exits = []   # Stop-exit-to-entry linkage
        self._start_time = datetime.now()
        self._cycles_completed = 0
        self._consecutive_errors = 0
        self._max_consecutive_errors = 5
        self._last_stop_check = datetime.now()
        self._last_state_save = datetime.now()
        self._last_persisted_cycles_completed = None
        self._last_persisted_trading_day_counter = None
        self._state_save_lock = threading.RLock()
        self._cycle_log_lock = threading.Lock()
        self._state_positions_snapshot = {}
        self._state_cash_snapshot = float(config['PAPER_INITIAL_CASH'])
        self._last_audit_positions = set()
        self._daily_open_done = False
        self._preclose_entries_done = False   # Pre-close entries for today
        self._missed_preclose = False         # Catch-up flag for missed pre-close
        self._startup_self_test_done = False
        self._shutdown_requested = False
        self._recovery_gap_baseline = None
        self._recovery_mode = False
        self._recovery_spy_close = None

        # Cycle log tracking
        self._pre_rotation_value = None   # portfolio value before exits
        self._pre_rotation_positions = []  # tickers before exits
        self._rotation_sells_today = False # did we sell hold_expired today?

        # Notifications (set externally)
        self.notifier = None

        # HYDRA: Rattlesnake + Cash Recycling
        self._hydra_available = _hydra_available
        self.rattle_positions: List[dict] = []  # {symbol, entry_price, entry_date, shares, days_held}
        self.rattle_regime = 'RISK_ON'
        self._vix_current: Optional[float] = None
        self.hydra_capital = None
        self._efa_hist: Optional[pd.DataFrame] = None
        # Catalyst 4th pillar
        self.catalyst_positions: List[dict] = []  # {symbol, shares, entry_price, sub_strategy}
        self._catalyst_hist: Dict[str, pd.DataFrame] = {}
        self._catalyst_day_counter = 0
        if _hydra_available:
            try:
                self.hydra_capital = HydraCapitalManager(config['PAPER_INITIAL_CASH'])
                logger.info("HYDRA multi-strategy: ACTIVE (Momentum + Rattlesnake + Catalyst + EFA + Cash Recycling)")
            except Exception as e:
                logger.warning(f"HYDRA init failed (running COMPASS-only): {e}")
                self._hydra_available = False

        # ML Learning System
        self.ml = None
        if _ml_available:
            try:
                self.ml = COMPASSMLOrchestrator()
                logger.info("ML Learning System: ACTIVE")
            except Exception as e:
                logger.warning(f"ML Learning System failed to init: {e}")

        # Overlay system (v3 config: BSO + M2 + FOMC + FedEmergency + CreditFilter)
        # Cash Optimization DISABLED (loses ~1% CAGR during ZIRP)
        self._overlay_available = False
        self._fred_data = {}
        self._overlays = {}
        self._credit_filter = None
        self._overlay_result = {}  # Latest overlay diagnostics
        self._overlay_damping = 0.25  # Conditional damping factor

        if _overlay_available:
            try:
                self._fred_data = download_all_overlay_data()
                self._overlays = {
                    'bso': BankingStressOverlay(self._fred_data),
                    'm2': M2MomentumIndicator(self._fred_data),
                    'fomc': FOMCSurpriseSignal(self._fred_data),
                    'fed_emergency': FedEmergencySignal(self._fred_data),
                }
                self._credit_filter = CreditSectorPreFilter(self._fred_data, SECTOR_MAP)
                self._overlay_available = True
                logger.info("Overlay System (v3): ACTIVE — BSO + M2 + FOMC + FedEmergency + CreditFilter")
            except Exception as e:
                logger.warning(f"Overlay system failed to init (degrading to scalar=1.0): {e}")

        # Validate config parameters (fail fast on startup)
        self._validate_config()

        logger.info("=" * 70)
        if self._hydra_available:
            logger.info("OMNICAPITAL HYDRA - LIVE TRADING (COMPASS + Rattlesnake)")
        else:
            logger.info("OMNICAPITAL v8.4 COMPASS - LIVE TRADING")
        logger.info("=" * 70)
        logger.info(f"Signal: Risk-adj momentum {config['MOMENTUM_LOOKBACK']}d (skip {config['MOMENTUM_SKIP']}d)")
        logger.info(f"Regime: Sigmoid composite score | Vol target: {config['TARGET_VOL']:.0%}")
        logger.info(f"Hold: {config['HOLD_DAYS']}d | Adaptive stop: {config['STOP_FLOOR']:.0%} to {config['STOP_CEILING']:.0%} (vol-scaled)")
        logger.info(f"Trailing: +{config['TRAILING_ACTIVATION']:.0%} / -{config['TRAILING_STOP_PCT']:.0%} (vol-scaled)")
        logger.info(f"Bull override: SPY > SMA200*{1+config['BULL_OVERRIDE_THRESHOLD']:.0%} & score>{config['BULL_OVERRIDE_MIN_SCORE']:.0%} -> +1 pos")
        logger.info(f"Sector limit: max {config['MAX_PER_SECTOR']} positions per sector")
        logger.info(f"DD tiers: T1={config['DD_SCALE_TIER1']:.0%} T2={config['DD_SCALE_TIER2']:.0%} T3={config['DD_SCALE_TIER3']:.0%}")
        logger.info(f"Crash brake: 5d={config['CRASH_VEL_5D']:.0%} 10d={config['CRASH_VEL_10D']:.0%} -> {config['CRASH_LEVERAGE']:.0%} lev")
        logger.info(f"Exit renewal: max {config['HOLD_DAYS_MAX']}d | min profit {config['RENEWAL_PROFIT_MIN']:.0%} | mom pctl {config['MOMENTUM_RENEWAL_THRESHOLD']:.0%}")
        logger.info(f"Quality filter: vol_max={config['QUALITY_VOL_MAX']:.0%} | max_single_day={config['QUALITY_MAX_SINGLE_DAY']:.0%}")
        logger.info(f"Leverage: max {config['LEVERAGE_MAX']:.1f}x (no leverage -- broker margin destroys value)")
        logger.info(f"Universe: dynamic S&P 500 -> top {config['TOP_N']}")
        logger.info(f"Execution: Pre-close signal @ {config['PRECLOSE_SIGNAL_TIME'].strftime('%H:%M')} ET "
                     f"-> same-day MOC (deadline {config['MOC_DEADLINE'].strftime('%H:%M')} ET)")
        logger.info(f"Chassis: async fetch | order timeout {config.get('ORDER_TIMEOUT_SECONDS', 300)}s | "
                     f"fill breaker {config.get('MAX_FILL_DEVIATION', 0.02):.0%} | data validation")
        if self._overlay_available:
            logger.info(f"Overlays: BSO + M2 + FOMC + FedEmergency + CreditFilter (damping={self._overlay_damping})")
        else:
            logger.info("Overlays: DISABLED (FRED data unavailable)")

        self._log_startup_report()

    def _log_startup_report(self):
        logger.info("=== HYDRA Engine Startup Report ===")
        logger.info(f"  Positions: {self.config.get('NUM_POSITIONS', '?')}")
        logger.info(f"  Hold days: {self.config.get('HOLD_DAYS', '?')}")
        logger.info(f"  Leverage max: {self.config.get('LEVERAGE_MAX', '?')}")
        logger.info(f"  Stop range: [{self.config.get('STOP_FLOOR', '?')}, {self.config.get('STOP_CEILING', '?')}]")
        logger.info(f"  State file: {getattr(self, 'state_file', '?')}")
        logger.info(f"  ML available: {getattr(self, '_ml_available', '?')}")
        logger.info(f"  Python: {sys.version.split()[0]}")
        logger.info("=================================")

    # ------------------------------------------------------------------
    # Config validation
    # ------------------------------------------------------------------

    def _validate_config(self):
        c = self.config
        errors = []

        # HOLD_DAYS: int >= 1
        if not isinstance(c.get('HOLD_DAYS'), int) or c['HOLD_DAYS'] < 1:
            errors.append(f"HOLD_DAYS must be int >= 1, got {c.get('HOLD_DAYS')!r}")

        # NUM_POSITIONS: int in [1, 20]
        if not isinstance(c.get('NUM_POSITIONS'), int) or not (1 <= c['NUM_POSITIONS'] <= 20):
            errors.append(f"NUM_POSITIONS must be int in [1, 20], got {c.get('NUM_POSITIONS')!r}")

        # LEVERAGE_MAX: float in (0, 1.0]
        lev = c.get('LEVERAGE_MAX')
        if not isinstance(lev, (int, float)) or lev <= 0 or lev > 1.0:
            errors.append(f"LEVERAGE_MAX must be float in (0, 1.0], got {lev!r}")

        # STOP_FLOOR: float in [-0.20, 0]
        sf = c.get('STOP_FLOOR')
        if not isinstance(sf, (int, float)) or sf < -0.20 or sf > 0:
            errors.append(f"STOP_FLOOR must be float in [-0.20, 0], got {sf!r}")

        # STOP_CEILING: float in [-0.30, STOP_FLOOR]
        sc = c.get('STOP_CEILING')
        sf_val = sf if isinstance(sf, (int, float)) else 0
        if not isinstance(sc, (int, float)) or sc < -0.30 or sc > sf_val:
            errors.append(f"STOP_CEILING must be float in [-0.30, {sf_val}], got {sc!r}")

        # TRAILING_ACTIVATION: float > 0
        ta = c.get('TRAILING_ACTIVATION')
        if not isinstance(ta, (int, float)) or ta <= 0:
            errors.append(f"TRAILING_ACTIVATION must be float > 0, got {ta!r}")

        if errors:
            for err in errors:
                logger.error(f"Config validation failed: {err}")
            raise ValueError(f"Invalid config: {'; '.join(errors)}")

    # ------------------------------------------------------------------
    # Market hours
    # ------------------------------------------------------------------

    def get_et_now(self) -> datetime:
        """Get current time in Eastern Time"""
        return datetime.now(self.et_tz)

    def _get_trading_date_str(self) -> str:
        d = self.get_et_now().date()
        while d.weekday() >= 5 or d in US_MARKET_HOLIDAYS:
            d += timedelta(days=1)
        return d.isoformat()

    def is_market_holiday(self, d=None) -> bool:
        if d is None:
            d = self.get_et_now().date()
        return d in US_MARKET_HOLIDAYS

    def is_market_open(self) -> bool:
        now_et = self.get_et_now()
        if now_et.weekday() >= 5 or self.is_market_holiday(now_et.date()):
            return False
        current_time = now_et.time()
        return self.config['MARKET_OPEN'] <= current_time <= self.config['MARKET_CLOSE']

    def is_new_trading_day(self) -> bool:
        today = self.get_et_now().date()
        if today.weekday() >= 5 or self.is_market_holiday(today):
            return False
        return self.last_trading_date is None or today > self.last_trading_date

    def _get_price_cache_age_seconds(self):
        getter = getattr(self.data_feed, 'get_cache_age_seconds', None)
        if not callable(getter):
            return None
        try:
            return getter()
        except Exception as e:
            logger.warning(f"Could not determine data cache age: {e}")
            return None

    def _stale_price_guard_triggered(self, cache_age_seconds: Optional[float]) -> bool:
        if cache_age_seconds is None:
            return False

        warn_age = float(self.config.get('PRICE_STALE_WARN_SECONDS', 120) or 120)
        skip_age = float(self.config.get('PRICE_STALE_SKIP_SECONDS', 300) or 300)
        if skip_age < warn_age:
            skip_age = warn_age

        if cache_age_seconds <= warn_age:
            return False

        message = (
            f"Skipping trading cycle due to stale market data: cache age "
            f"{cache_age_seconds:.1f}s (warn>{warn_age:.0f}s, critical>{skip_age:.0f}s)"
        )
        if cache_age_seconds > skip_age:
            logger.error(message)
        else:
            logger.warning(message)
        return True

    # ------------------------------------------------------------------
    # Data refresh (called once per trading day)
    # ------------------------------------------------------------------

    def refresh_daily_data(self):
        """Download fresh historical data for all signals. Called at market open."""
        today = self.get_et_now().date()
        if self._hist_date == today:
            return  # Already refreshed today

        logger.info("Refreshing daily historical data...")

        # Prune stale symbols from data validator (prevents unbounded memory growth)
        if hasattr(self, 'validator'):
            active_symbols = set(self.current_universe) | set(self.position_meta.keys())
            stale = [s for s in self.validator._price_history if s not in active_symbols]
            for s in stale:
                del self.validator._price_history[s]
            if stale:
                logger.debug(f"Pruned {len(stale)} stale symbols from data validator")

        # SPY for regime and vol targeting
        try:
            spy = yf.download('SPY', period='2y', progress=False)
            if isinstance(spy.columns, pd.MultiIndex):
                spy.columns = [c[0] for c in spy.columns]
            self._spy_hist = spy
            logger.info(f"SPY data: {len(spy)} days")
        except Exception as e:
            logger.error(f"Failed to download SPY: {e}")
            if self._spy_hist is None:
                logger.critical("No SPY data available -- regime unknown, blocking new entries today")
                self._block_new_entries = True

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

        logger.info(f"Historical data refreshed: {len(self._hist_cache)} stocks (COMPASS)")

        # HYDRA: Download Rattlesnake universe + VIX
        if self._hydra_available:
            r_symbols_needed = set(R_UNIVERSE) - set(self._hist_cache.keys())
            # Also re-download held Rattlesnake symbols
            r_symbols_needed |= {p['symbol'] for p in self.rattle_positions}
            for symbol in r_symbols_needed:
                try:
                    df = yf.download(symbol, period='1y', progress=False)
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = [c[0] for c in df.columns]
                    if len(df) > 20:
                        self._hist_cache[symbol] = df
                except Exception as e:
                    logger.debug(f"Failed to download {symbol} (Rattlesnake): {e}")

            # VIX for panic filter
            try:
                vix = yf.download('^VIX', period='5d', progress=False)
                if isinstance(vix.columns, pd.MultiIndex):
                    vix.columns = [c[0] for c in vix.columns]
                if len(vix) > 0:
                    self._vix_current = float(vix['Close'].iloc[-1])
                    logger.info(f"VIX: {self._vix_current:.1f}")
                else:
                    self._vix_current = None
            except Exception as e:
                logger.warning(f"Failed to download VIX: {e}")
                self._vix_current = None

            # EFA for third pillar
            try:
                efa_df = yf.download(EFA_SYMBOL, period='1y', progress=False)
                if isinstance(efa_df.columns, pd.MultiIndex):
                    efa_df.columns = [c[0] for c in efa_df.columns]
                if len(efa_df) >= EFA_SMA_PERIOD:
                    self._efa_hist = efa_df
                    efa_sma = float(efa_df['Close'].iloc[-EFA_SMA_PERIOD:].mean())
                    efa_price = float(efa_df['Close'].iloc[-1])
                    logger.info(f"EFA: ${efa_price:.2f} | SMA200: ${efa_sma:.2f} | "
                               f"{'ABOVE' if efa_price > efa_sma else 'BELOW'}")
                else:
                    logger.warning(f"EFA: insufficient data ({len(efa_df)} days, need {EFA_SMA_PERIOD})")
            except Exception as e:
                logger.warning(f"Failed to download EFA: {e}")

            # Catalyst 4th pillar data
            if _catalyst_available:
                for cat_sym in CATALYST_TREND_ASSETS:
                    try:
                        cat_df = yf.download(cat_sym, period='1y', progress=False)
                        if isinstance(cat_df.columns, pd.MultiIndex):
                            cat_df.columns = [c[0] for c in cat_df.columns]
                        if len(cat_df) >= 200:
                            self._catalyst_hist[cat_sym] = cat_df
                    except Exception as e:
                        logger.warning(f"Catalyst: failed to download {cat_sym}: {e}")
                above = compute_trend_holdings(self._catalyst_hist) if self._catalyst_hist else []
                logger.info(f"Catalyst: {len(above)}/{len(CATALYST_TREND_ASSETS)} assets above SMA200: {above}")

            logger.info(f"Historical data refreshed: {len(self._hist_cache)} stocks (COMPASS + Rattlesnake + Catalyst)")

        self._hist_date = today

        # Refresh overlay FRED data (daily, uses cache if network fails)
        if self._overlay_available:
            try:
                self._fred_data = download_all_overlay_data(force_refresh=True)
                self._overlays = {
                    'bso': BankingStressOverlay(self._fred_data),
                    'm2': M2MomentumIndicator(self._fred_data),
                    'fomc': FOMCSurpriseSignal(self._fred_data),
                    'fed_emergency': FedEmergencySignal(self._fred_data),
                }
                self._credit_filter = CreditSectorPreFilter(self._fred_data, SECTOR_MAP)
                logger.info("FRED overlay data refreshed")
            except Exception as e:
                logger.warning(f"FRED refresh failed, using cached data: {e}")

    def _startup_self_test(self):
        total_checks = 5
        passed = 0
        warnings = []

        if _catalyst_available:
            passed += 1
        else:
            warnings.append("Catalyst unavailable")

        if self._hydra_available:
            passed += 1
        else:
            warnings.append("HYDRA unavailable")

        spy_price = 0.0
        try:
            if hasattr(self.data_feed, 'get_price'):
                spy_price = self._coerce_float(self.data_feed.get_price('SPY'), 0.0)
            if spy_price <= 0 and hasattr(self.data_feed, 'get_prices'):
                spy_price = self._coerce_float(
                    (self.data_feed.get_prices(['SPY']) or {}).get('SPY'),
                    0.0,
                )
        except Exception as e:
            warnings.append(f"SPY price check failed: {e}")
        else:
            if spy_price > 0:
                passed += 1
            else:
                warnings.append("SPY price check failed: no valid price returned")

        if _catalyst_available:
            missing_assets = [
                symbol for symbol in CATALYST_TREND_ASSETS
                if symbol not in self._catalyst_hist
                or self._catalyst_hist.get(symbol) is None
                or len(self._catalyst_hist.get(symbol)) == 0
            ]
            if not missing_assets:
                passed += 1
            else:
                detail = ", ".join(missing_assets[:4])
                if len(missing_assets) > 4:
                    detail += ", ..."
                warnings.append(f"Catalyst history missing for {detail}")
        else:
            warnings.append("Catalyst history check skipped because Catalyst is unavailable")

        if self.current_universe:
            passed += 1
        else:
            warnings.append("Current universe is empty")

        if warnings:
            logger.warning(
                "HYDRA startup self-test: %s/%s checks passed - %s",
                passed,
                total_checks,
                " | ".join(warnings),
            )
        else:
            logger.info("HYDRA startup self-test: %s/%s checks passed", passed, total_checks)

        return {
            'passed': passed,
            'total': total_checks,
            'warnings': warnings,
        }

    def _run_startup_self_test_once(self):
        if self._startup_self_test_done:
            return None
        try:
            return self._startup_self_test()
        except Exception as e:
            logger.warning(f"HYDRA startup self-test crashed unexpectedly: {e}", exc_info=True)
            return {
                'passed': 0,
                'total': 5,
                'warnings': [str(e)],
            }
        finally:
            self._startup_self_test_done = True

    def refresh_universe(self):
        """Refresh top-N universe if new year (dynamic S&P 500 constituents)"""
        current_year = self.get_et_now().year
        needs_refresh = self.universe_year != current_year
        # Retry if previous attempt fell back to cached/hardcoded
        if not needs_refresh and getattr(self, '_universe_source', '') == 'fallback':
            days_into_year = (self.get_et_now() - datetime(current_year, 1, 1)).days
            needs_refresh = days_into_year <= 7

        if needs_refresh:
            logger.info(f"Computing {current_year} universe...")
            from compass.sp500_universe import refresh_constituents
            broad_pool, source = refresh_constituents(fallback_pool=BROAD_POOL)
            _PIT_SOURCES = ('github', 'wikipedia', 'cached', 'pit_snapshot')
            self._universe_source = source if source in _PIT_SOURCES else 'fallback'
            if self._universe_source == 'fallback':
                logger.error(f"Universe using HARDCODED fallback ({len(BROAD_POOL)} stocks) — "
                             f"ALL PIT sources failed. Results have survivorship bias.")
            raw_universe = compute_annual_top40(
                broad_pool, self.config['TOP_N']
            )
            self.current_universe = validate_universe(raw_universe)
            self.universe_year = current_year
            logger.info(f"Universe updated: {len(self.current_universe)} stocks from "
                        f"{len(broad_pool)} constituents (source: {source}, PIT: {source in _PIT_SOURCES})")

    # ------------------------------------------------------------------
    # Regime detection
    # ------------------------------------------------------------------

    def update_regime(self):
        """Update market regime using continuous sigmoid score"""
        if self._spy_hist is None or len(self._spy_hist) < 252:
            return
        old_score = self.current_regime_score
        self.current_regime_score = compute_live_regime_score(self._spy_hist)
        self._last_regime_refresh = datetime.now()
        old_risk_on = old_score >= 0.50
        new_risk_on = self.current_regime_score >= 0.50
        if old_risk_on != new_risk_on:
            regime_str = "RISK_ON" if new_risk_on else "RISK_OFF"
            logger.info(f"REGIME CHANGE -> {regime_str} (score: {self.current_regime_score:.2f})")
            if self.notifier:
                spy_price = self._spy_hist['Close'].iloc[-1]
                sma = self._spy_hist['Close'].rolling(200).mean().iloc[-1]
                self.notifier.send_regime_change_alert(new_risk_on, spy_price, sma)

    # ------------------------------------------------------------------
    # Leverage computation
    # ------------------------------------------------------------------

    def get_current_leverage(self) -> float:
        """Determine current leverage: min(dd_scaling, vol_targeting)"""
        portfolio = self.broker.get_portfolio()
        pv = portfolio.total_value

        # Update peak
        if pv > self.peak_value:
            self.peak_value = pv

        drawdown = (pv - self.peak_value) / self.peak_value if self.peak_value > 0 else 0

        # DD scaling
        dd_lev = _dd_leverage(drawdown, self.config)
        crash_brake_active = False

        # Crash velocity check
        if self.crash_cooldown > 0:
            dd_lev = min(self.config['CRASH_LEVERAGE'], dd_lev)
            crash_brake_active = True
        elif len(self.portfolio_values_history) >= 5:
            current_val = pv
            val_5d = self.portfolio_values_history[-5]
            if val_5d > 0:
                ret_5d = (current_val / val_5d) - 1.0
                if ret_5d <= self.config['CRASH_VEL_5D']:
                    dd_lev = min(self.config['CRASH_LEVERAGE'], dd_lev)
                    self.crash_cooldown = self.config['CRASH_COOLDOWN'] - 1
                    crash_brake_active = True
            if (not crash_brake_active and self.crash_cooldown == 0
                    and len(self.portfolio_values_history) >= 10):
                val_10d = self.portfolio_values_history[-10]
                if val_10d > 0:
                    ret_10d = (current_val / val_10d) - 1.0
                    if ret_10d <= self.config['CRASH_VEL_10D']:
                        dd_lev = min(self.config['CRASH_LEVERAGE'], dd_lev)
                        self.crash_cooldown = self.config['CRASH_COOLDOWN'] - 1
                        crash_brake_active = True

        # Vol targeting
        vol_lev = 1.0
        if self._spy_hist is not None:
            vol_lev = compute_dynamic_leverage(
                self._spy_hist, self.config['TARGET_VOL'],
                self.config['VOL_LOOKBACK'],
                self.config['LEV_FLOOR'], self.config['LEVERAGE_MAX']
            )

        target_lev = min(dd_lev, vol_lev)
        if crash_brake_active:
            return target_lev
        return max(target_lev, self.config['LEV_FLOOR'])

    def get_max_positions(self) -> int:
        """Determine max positions from regime score (v8.4: with bull override)"""
        spy_close = None
        sma200 = None
        if self._spy_hist is not None and len(self._spy_hist) >= 200:
            spy_close = float(self._spy_hist['Close'].iloc[-1])
            sma200 = float(self._spy_hist['Close'].iloc[-200:].mean())
        max_pos = regime_score_to_positions(
            self.current_regime_score,
            self.config['NUM_POSITIONS'],
            self.config['NUM_POSITIONS_RISK_OFF'],
            spy_close=spy_close,
            sma200=sma200,
            bull_threshold=self.config['BULL_OVERRIDE_THRESHOLD'],
            bull_min_score=self.config['BULL_OVERRIDE_MIN_SCORE']
        )

        # Overlay: Fed Emergency position floor
        if self._overlay_available and self._overlay_result:
            floor = self._overlay_result.get('position_floor')
            if floor is not None and floor > max_pos:
                logger.info(f"Fed Emergency floor: {max_pos} -> {floor} positions")
                max_pos = floor

        return max_pos

    def _get_ml_spy_context(self):
        spy_price = None
        spy_sma200 = None
        try:
            if self._spy_hist is not None and len(self._spy_hist) >= 200:
                close = self._spy_hist['Close']
                spy_price = float(close.iloc[-1])
                spy_sma200 = float(close.iloc[-200:].mean())
        except Exception:
            spy_price = None
            spy_sma200 = None

        return {
            'spy_price': spy_price,
            'spy_sma200': spy_sma200,
            'spy_regime_score': self.current_regime_score,
        }

    # ------------------------------------------------------------------
    # Position exit logic (5 conditions from backtest)
    # ------------------------------------------------------------------

    def check_position_exits(self, prices: Dict[str, float],
                             include_hold_expired: bool = False):
        """Check exit conditions for each position.
        Hold-expired exits only run at pre-close (15:30 ET), not at open.
        Stops and trailing run at open + intraday.
        """
        positions = self.broker.get_positions()
        max_positions = self.get_max_positions()
        self._regime_reduce_done = False  # Only allow one regime-reduce sell per call
        ml_spy_ctx = self._get_ml_spy_context() if self.ml else None

        for symbol in list(positions.keys()):
            price = prices.get(symbol)
            if not price:
                continue

            meta = self.position_meta.get(symbol)
            if not meta:
                continue

            # Skip Catalyst positions — managed by _manage_catalyst_positions
            if meta.get('_catalyst'):
                continue

            # Skip EFA position — managed by _manage_efa_position
            if symbol == EFA_SYMBOL or meta.get('_efa'):
                continue

            exit_reason = None

            # 1. Hold time expired (entry day counts as day 1)
            #    Only checked at pre-close (15:30 ET) — sells + new entries together
            days_held = self.trading_day_counter - meta['entry_day_index'] + 1
            total_days_held = self.trading_day_counter - meta.get('original_entry_day_index', meta['entry_day_index']) + 1
            if include_hold_expired and days_held >= self.config['HOLD_DAYS']:
                # Check renewal for winners
                if self._should_renew(symbol, meta, price, total_days_held):
                    meta['entry_day_index'] = self.trading_day_counter
                    logger.info(f"RENEWAL {symbol} @ ${price:.2f} | total days: {total_days_held}")
                else:
                    exit_reason = 'hold_expired'

            # 2. Position stop loss (v8.4: adaptive, vol-scaled)
            #    Stops override hold_expired (risk events take priority)
            pos_return = (price - meta['entry_price']) / meta['entry_price']
            entry_daily_vol = meta.get('entry_daily_vol')
            if entry_daily_vol is not None:
                adaptive_stop = compute_adaptive_stop(entry_daily_vol, self.config)
            else:
                adaptive_stop = self.config['POSITION_STOP_LOSS']  # fallback for pre-v8.4 positions
            if pos_return <= adaptive_stop:
                exit_reason = 'position_stop'

            # 3. Trailing stop (v8.4: vol-scaled)
            #    Only if not already flagged for a harder stop
            if price > meta['high_price']:
                meta['high_price'] = price
            if exit_reason != 'position_stop' and meta['high_price'] > meta['entry_price'] * (1 + self.config['TRAILING_ACTIVATION']):
                baseline = self.config['TRAILING_VOL_BASELINE']
                entry_vol = meta.get('entry_vol', baseline)
                vol_ratio = entry_vol / baseline
                scaled_trailing = self.config['TRAILING_STOP_PCT'] * vol_ratio
                trailing_level = meta['high_price'] * (1 - scaled_trailing)
                if price <= trailing_level:
                    exit_reason = 'trailing_stop'

            # 4. Universe rotation (only if no stop already triggered)
            #    Never rotate out EFA or Catalyst — they're managed by their own pillars
            is_pillar = (symbol == EFA_SYMBOL
                         or meta.get('_efa')
                         or meta.get('_catalyst')
                         or (_catalyst_available and symbol in CATALYST_TREND_ASSETS))
            if exit_reason is None and symbol not in self.current_universe and not is_pillar:
                exit_reason = 'universe_rotation'

            # 5. Regime reduce (excess COMPASS positions)
            #    Only sell one per check_position_exits call to prevent double-sell
            #    Exclude Catalyst, EFA, and Rattlesnake positions from count
            def _is_compass_position(sym):
                m = self.position_meta.get(sym, {})
                return (sym in self.position_meta
                        and not m.get('_catalyst')
                        and not m.get('_efa')
                        and sym != EFA_SYMBOL
                        and not any(rp['symbol'] == sym for rp in self.rattle_positions))

            compass_count = sum(1 for s in positions if _is_compass_position(s))
            if exit_reason is None and compass_count > max_positions and not self._regime_reduce_done:
                pos_returns = {}
                for s, p in positions.items():
                    pr = prices.get(s)
                    if pr and _is_compass_position(s):
                        m = self.position_meta[s]
                        pos_returns[s] = (pr - m['entry_price']) / m['entry_price']
                if pos_returns:
                    worst = min(pos_returns, key=pos_returns.get)
                    if symbol == worst:
                        exit_reason = 'regime_reduce'
                        self._regime_reduce_done = True

            if exit_reason is None and self.ml:
                try:
                    portfolio_now = self.broker.get_portfolio()
                    drawdown = (
                        (portfolio_now.total_value - self.peak_value) / self.peak_value
                        if self.peak_value > 0 else 0
                    )
                    drawdown_from_high = (
                        (price - meta['high_price']) / meta['high_price']
                        if meta['high_price'] > 0 else 0.0
                    )
                    self.ml.on_hold(
                        symbol=symbol,
                        sector=SECTOR_MAP.get(symbol, meta.get('sector', 'Unknown')),
                        days_held=days_held,
                        current_return=pos_return,
                        drawdown_from_high=drawdown_from_high,
                        entry_daily_vol=meta.get('entry_daily_vol', 0.016),
                        adaptive_stop_pct=adaptive_stop,
                        regime_score=self.current_regime_score,
                        trading_day=self.trading_day_counter,
                        portfolio_value=portfolio_now.total_value,
                        portfolio_drawdown=drawdown,
                        spy_price=ml_spy_ctx['spy_price'] if ml_spy_ctx else None,
                        spy_sma200=ml_spy_ctx['spy_sma200'] if ml_spy_ctx else None,
                        spy_regime_score=ml_spy_ctx['spy_regime_score'] if ml_spy_ctx else None,
                    )
                except Exception as e:
                    _ml_error_counts['hold'] += 1
                    logger.warning(f"ML hold logging failed for {symbol}: {e}")

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

                    # HYDRA: Record COMPASS trade P&L to logical account
                    if self.hydra_capital:
                        try:
                            self.hydra_capital.record_compass_trade(pnl)
                        except Exception as e:
                            logger.warning(f"HYDRA record_compass_trade failed: {e}")

                    # ML: log exit decision (before meta is popped)
                    if self.ml:
                        try:
                            portfolio_now = self.broker.get_portfolio()
                            drawdown = (portfolio_now.total_value - self.peak_value) / self.peak_value if self.peak_value > 0 else 0
                            self.ml.on_exit(
                                symbol=symbol,
                                sector=SECTOR_MAP.get(symbol, meta.get('sector', 'Unknown')),
                                exit_reason=exit_reason,
                                entry_price=meta['entry_price'],
                                exit_price=result.filled_price,
                                pnl_usd=pnl,
                                days_held=days_held,
                                high_price=meta['high_price'],
                                entry_vol_ann=meta.get('entry_vol', 0.25),
                                entry_daily_vol=meta.get('entry_daily_vol', 0.016),
                                adaptive_stop_pct=adaptive_stop,
                                entry_momentum_score=meta.get('entry_momentum_score', 0.0),
                                entry_momentum_rank=meta.get('entry_momentum_rank', 0.5),
                                regime_score=self.current_regime_score,
                                max_positions_target=max_positions,
                                current_n_positions=len(positions),
                                portfolio_value=portfolio_now.total_value,
                                portfolio_drawdown=drawdown,
                                current_leverage=self.get_current_leverage(),
                                crash_cooldown=self.crash_cooldown,
                                trading_day=self.trading_day_counter,
                                spy_hist=self._spy_hist,
                            )
                        except Exception as e:
                            _ml_error_counts['exit'] += 1
                            logger.warning(f"ML exit logging failed for {symbol}: {e}")

                    # Only remove metadata if position is fully closed
                    # and not owned by another strategy
                    if symbol not in self.broker.positions:
                        in_catalyst = any(cp['symbol'] == symbol for cp in self.catalyst_positions)
                        in_rattle = any(rp['symbol'] == symbol for rp in self.rattle_positions)
                        if not in_catalyst and not in_rattle and symbol != EFA_SYMBOL:
                            self.position_meta.pop(symbol, None)

                    self.trades_today.append({
                        'symbol': symbol, 'action': 'SELL',
                        'exit_reason': exit_reason, 'pnl': pnl, 'return': ret,
                        'price': result.filled_price, 'is_bps': result.is_bps
                    })

                    # Track stop exits for cycle log update when replacement enters
                    if exit_reason in ('position_stop', 'trailing_stop'):
                        self._pending_stop_exits.append({
                            'symbol': symbol,
                            'reason': exit_reason,
                            'return': ret,
                            'exit_price': result.filled_price,
                            'entry_price': meta.get('entry_price', pos.avg_cost),
                            'sector': SECTOR_MAP.get(symbol, meta.get('sector', 'Unknown')),
                            'days_held': total_days_held,
                        })

                    stop_info = ""
                    if exit_reason == 'position_stop':
                        stop_info = f" | stop={adaptive_stop:.1%}"
                    elif exit_reason == 'trailing_stop':
                        stop_info = f" | trail_lvl=${trailing_level:.2f}"
                    logger.info(f"EXIT [{exit_reason}] {symbol} @ ${result.filled_price:.2f} | "
                                f"PnL: ${pnl:+,.0f} ({ret:+.1%}){stop_info}")

                    if self.notifier:
                        self.notifier.send_trade_alert('SELL', symbol, pos.shares,
                                                       result.filled_price, exit_reason, pnl)

                    # Save state immediately after fill (crash protection)
                    self.save_state()

                # Refresh positions for remaining checks
                positions = self.broker.get_positions()

    def _should_renew(self, symbol: str, meta: dict, price: float, total_days: int) -> bool:
        """Check if position should renew instead of closing."""
        if total_days >= self.config['HOLD_DAYS_MAX']:
            return False
        entry_price = meta.get('entry_price', price)
        if entry_price <= 0:
            return False
        pos_return = (price - entry_price) / entry_price
        if pos_return < self.config['RENEWAL_PROFIT_MIN']:
            return False
        if not hasattr(self, '_current_scores') or not self._current_scores:
            return False
        if symbol not in self._current_scores:
            return False
        all_scores = sorted(self._current_scores.values(), reverse=True)
        n = len(all_scores)
        if n < 3:
            return False
        rank_above = sum(1 for s in all_scores if s > self._current_scores[symbol])
        percentile = 1.0 - (rank_above / n)
        return percentile >= self.config['MOMENTUM_RENEWAL_THRESHOLD']

    # ------------------------------------------------------------------
    # Position entry logic
    # ------------------------------------------------------------------

    def open_new_positions(self, prices: Dict[str, float]):
        """Open new positions using momentum scoring + inverse-vol sizing"""
        if self._block_new_entries:
            logger.warning("New entries blocked (no SPY data for regime)")
            return
        positions = self.broker.get_positions()
        # HYDRA: Only count COMPASS positions (exclude EFA, Catalyst, Rattlesnake)
        compass_positions = {
            s: p for s, p in positions.items()
            if s in self.position_meta
            and not self.position_meta.get(s, {}).get('_catalyst')
            and not self.position_meta.get(s, {}).get('_efa')
            and s != EFA_SYMBOL
            and not any(rp['symbol'] == s for rp in self.rattle_positions)
        }
        max_positions = self.get_max_positions()
        needed = max_positions - len(compass_positions)

        if needed <= 0:
            return

        portfolio = self.broker.get_portfolio()
        if portfolio.cash <= 1000:
            return

        # Get tradeable symbols from universe with valid data
        tradeable = [s for s in self.current_universe
                     if s in self._hist_cache and s in prices]
        # Quality filter
        tradeable = compute_quality_filter(
            self._hist_cache, tradeable,
            self.config['QUALITY_VOL_MAX'],
            self.config['QUALITY_VOL_LOOKBACK'],
            self.config['QUALITY_MAX_SINGLE_DAY']
        )

        # Overlay: credit sector pre-filter (exclude Financials/Energy at crisis HY levels)
        if self._overlay_available and self._credit_filter is not None:
            try:
                today = pd.Timestamp(self.get_et_now().date())
                pre_filter_count = len(tradeable)
                tradeable = self._credit_filter.filter_universe(tradeable, today)
                if len(tradeable) < pre_filter_count:
                    excluded = pre_filter_count - len(tradeable)
                    logger.info(f"Overlay credit filter: excluded {excluded} stocks from stressed sectors")
            except Exception as e:
                logger.warning(f"Credit filter failed (skipping): {e}")

        if len(tradeable) < self.config['MIN_MOMENTUM_STOCKS']:
            logger.debug(f"Not enough tradeable stocks: {len(tradeable)}")
            return

        # Compute momentum scores
        scores = compute_momentum_scores(
            self._hist_cache, tradeable,
            self.config['MOMENTUM_LOOKBACK'],
            self.config['MOMENTUM_SKIP']
        )
        self._current_scores = scores  # Cache for renewal checks

        # Filter out stocks already in portfolio
        available = {s: sc for s, sc in scores.items() if s not in positions}

        if len(available) < needed:
            return

        # v8.4: Select top N by score WITH sector concentration limits
        # Only count COMPASS positions for sector limits (not EFA/Catalyst/Rattlesnake)
        ranked = sorted(available.items(), key=lambda x: x[1], reverse=True)
        sector_filtered = filter_by_sector_concentration(
            ranked, compass_positions, self.config['MAX_PER_SECTOR']
        )
        selected = sector_filtered[:needed]

        # ML: log skipped candidates (top-10 not selected)
        if self.ml:
            try:
                selected_set = set(selected)
                drawdown = (portfolio.total_value - self.peak_value) / self.peak_value if self.peak_value > 0 else 0
                sector_filtered_set = set(sector_filtered)
                ml_spy_ctx = self._get_ml_spy_context()
                for rank_idx, (sym, sc) in enumerate(ranked[:20]):
                    if sym in selected_set:
                        continue
                    skip_reason = 'sector_limit' if sym not in sector_filtered_set else 'not_top_n'
                    self.ml.on_skip(
                        symbol=sym,
                        sector=SECTOR_MAP.get(sym, 'Unknown'),
                        skip_reason=skip_reason,
                        universe_rank=rank_idx + 1,
                        momentum_score=sc,
                        regime_score=self.current_regime_score,
                        trading_day=self.trading_day_counter,
                        portfolio_value=portfolio.total_value,
                        portfolio_drawdown=drawdown,
                        current_n_positions=len(positions),
                        max_positions_target=max_positions,
                        spy_price=ml_spy_ctx['spy_price'] if ml_spy_ctx else None,
                        spy_sma200=ml_spy_ctx['spy_sma200'] if ml_spy_ctx else None,
                        spy_regime_score=ml_spy_ctx['spy_regime_score'] if ml_spy_ctx else None,
                    )
            except Exception as e:
                _ml_error_counts['skip'] += 1
                logger.warning(f"ML skip logging failed: {e}")

        # Compute inverse-vol weights
        weights = compute_volatility_weights(
            self._hist_cache, selected, self.config['VOL_LOOKBACK']
        )

        # Effective capital with leverage
        current_leverage = self.get_current_leverage()

        # Overlay: compute capital scalar with conditional damping
        overlay_scalar = 1.0
        damped_scalar = 1.0
        if self._overlay_available and self._overlays:
            try:
                today = pd.Timestamp(self.get_et_now().date())
                self._overlay_result = compute_overlay_signals(
                    self._overlays, today, self._credit_filter
                )
                overlay_scalar = self._overlay_result.get('capital_scalar', 1.0)

                # Conditional damping: avoid double-counting with DD-scaling
                portfolio_val = self.broker.get_portfolio().total_value
                drawdown = (portfolio_val - self.peak_value) / self.peak_value if self.peak_value > 0 else 0
                dd_lev = _dd_leverage(drawdown, self.config)

                if dd_lev < 1.0:
                    # DD-scaling active: only apply 25% of overlay reduction
                    damped_scalar = 1.0 - self._overlay_damping * (1.0 - overlay_scalar)
                else:
                    # DD-scaling inactive: full overlay signal (early warning)
                    damped_scalar = overlay_scalar

                if damped_scalar < 1.0:
                    logger.info(f"Overlay scalar={overlay_scalar:.3f} damped={damped_scalar:.3f} "
                                f"(dd_lev={dd_lev:.2f})")
            except Exception as e:
                logger.warning(f"Overlay computation failed (using scalar=1.0): {e}")
                damped_scalar = 1.0

        # HYDRA: Use cash recycling budget for COMPASS if available
        compass_cash = portfolio.cash
        if self._hydra_available and self.hydra_capital:
            r_exposure = compute_rattlesnake_exposure(
                self.rattle_positions, prices, self.hydra_capital.rattle_account
            )
            alloc = self.hydra_capital.compute_allocation(r_exposure)
            compass_cash = min(portfolio.cash, alloc['compass_budget'])
            logger.info(f"HYDRA budget: COMPASS=${alloc['compass_budget']:,.0f} | "
                       f"Rattlesnake=${alloc['rattle_budget']:,.0f} | "
                       f"recycled=${alloc['recycled_amount']:,.0f} ({alloc['recycled_pct']:.0%})")

        for symbol in selected:
            price = prices.get(symbol)
            if not price or price <= 0:
                continue

            # Recalculate available capital each iteration (prior fills reduce cash)
            portfolio = self.broker.get_portfolio()
            compass_cash = portfolio.cash
            if self._hydra_available and self.hydra_capital:
                r_exposure = compute_rattlesnake_exposure(
                    self.rattle_positions, prices, self.hydra_capital.rattle_account
                )
                alloc = self.hydra_capital.compute_allocation(r_exposure)
                compass_cash = min(portfolio.cash, alloc['compass_budget'])
            effective_capital = compass_cash * current_leverage * 0.95 * damped_scalar

            weight = weights.get(symbol, 1.0 / len(selected))
            position_value = effective_capital * weight
            max_per_position = compass_cash * 0.40
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
                # v8.4: Compute entry-time vol for adaptive stops
                entry_vol, entry_daily_vol = compute_entry_vol(
                    self._hist_cache, symbol, self.config['VOL_LOOKBACK']
                )
                adaptive_stop = compute_adaptive_stop(entry_daily_vol, self.config)

                # Compute entry momentum rank for ML persistence
                all_scores_sorted = sorted(scores.values(), reverse=True)
                n_scores = len(all_scores_sorted)
                rank_above = sum(1 for s in all_scores_sorted if s > scores.get(symbol, 0))
                entry_momentum_rank = 1.0 - (rank_above / max(1, n_scores))

                self.position_meta[symbol] = {
                    'entry_price': result.filled_price,
                    'entry_date': self._get_trading_date_str(),
                    'entry_day_index': self.trading_day_counter,
                    'original_entry_day_index': self.trading_day_counter,
                    'high_price': result.filled_price,
                    'entry_vol': entry_vol,              # v8.4: annualized vol
                    'entry_daily_vol': entry_daily_vol,  # v8.4: daily vol for stop calc
                    'sector': SECTOR_MAP.get(symbol, 'Unknown'),  # v8.4: sector tracking
                    'entry_momentum_score': scores.get(symbol, 0.0),
                    'entry_momentum_rank': entry_momentum_rank,
                }

                self.trades_today.append({
                    'symbol': symbol, 'action': 'BUY',
                    'price': result.filled_price,
                    'shares': shares, 'value': cost,
                    'is_bps': result.is_bps
                })
                logger.info(f"ENTRY {symbol}: {shares:.1f} shares @ ${result.filled_price:.2f} "
                            f"(${cost:,.0f} | wt={weight:.1%} | lev={current_leverage:.2f}x | "
                            f"stop={adaptive_stop:.1%})")

                if self.notifier:
                    self.notifier.send_trade_alert('BUY', symbol, shares,
                                                   result.filled_price, None, None)

                # ML: log entry decision
                if self.ml:
                    try:
                        all_scores_sorted = sorted(scores.values(), reverse=True)
                        n_scores = len(all_scores_sorted)
                        rank_above = sum(1 for s in all_scores_sorted if s > scores.get(symbol, 0))
                        momentum_rank = 1.0 - (rank_above / max(1, n_scores))
                        drawdown = (portfolio.total_value - self.peak_value) / self.peak_value if self.peak_value > 0 else 0

                        self.ml.on_entry(
                            symbol=symbol,
                            sector=SECTOR_MAP.get(symbol, 'Unknown'),
                            momentum_score=scores.get(symbol, 0.0),
                            momentum_rank=momentum_rank,
                            entry_vol_ann=entry_vol,
                            entry_daily_vol=entry_daily_vol,
                            adaptive_stop_pct=adaptive_stop,
                            trailing_stop_pct=self.config['TRAILING_STOP_PCT'],
                            regime_score=self.current_regime_score,
                            max_positions_target=max_positions,
                            current_n_positions=len(self.broker.get_positions()),
                            portfolio_value=portfolio.total_value,
                            portfolio_drawdown=drawdown,
                            current_leverage=current_leverage,
                            crash_cooldown=self.crash_cooldown,
                            trading_day=self.trading_day_counter,
                            spy_hist=self._spy_hist,
                            stock_hist=self._hist_cache.get(symbol),
                        )
                    except Exception as e:
                        _ml_error_counts['entry'] += 1
                        logger.warning(f"ML entry logging failed for {symbol}: {e}")

                # Cycle log: link this entry as replacement for a pending stop exit
                if self._pending_stop_exits:
                    stop_exit = self._pending_stop_exits.pop(0)
                    try:
                        self._update_cycle_log_stop(
                            stopped_symbol=stop_exit['symbol'],
                            replacement_symbol=symbol,
                            exit_reason=stop_exit['reason'],
                            stop_return=stop_exit['return'],
                            stop_details=stop_exit,
                        )
                    except Exception as e:
                        logger.warning(f"Cycle log stop update failed: {e}")

                # Save state immediately after fill (crash protection)
                self.save_state()

                # Update portfolio for next iteration
                portfolio = self.broker.get_portfolio()

    # ------------------------------------------------------------------
    # HYDRA: Rattlesnake position management
    # ------------------------------------------------------------------

    def _check_rattlesnake_exits(self, prices: Dict[str, float]):
        """Check exit conditions for Rattlesnake positions."""
        if not self.rattle_positions:
            return

        exits = []
        for pos in self.rattle_positions:
            symbol = pos['symbol']
            price = prices.get(symbol)
            if not price:
                continue

            reason = check_rattlesnake_exit(
                symbol, pos['entry_price'], price, pos.get('days_held', 0)
            )
            if reason:
                exits.append((pos, price, reason))

        for pos, price, reason in exits:
            symbol = pos['symbol']
            shares = pos.get('shares', 0)
            pnl = (price - pos['entry_price']) * shares

            # Execute sell through broker
            order = Order(symbol=symbol, action='SELL',
                          quantity=shares, order_type='MARKET',
                          decision_price=price)
            result = self._submit_order(order, prices)

            if result.status == 'FILLED':
                actual_pnl = (result.filled_price - pos['entry_price']) * shares - result.commission
                ret = actual_pnl / (pos['entry_price'] * shares) if pos['entry_price'] * shares > 0 else 0

                # Record P&L to Rattlesnake account
                if self.hydra_capital:
                    self.hydra_capital.record_rattle_trade(actual_pnl)

                self.rattle_positions.remove(pos)
                self.trades_today.append({
                    'symbol': symbol, 'action': 'SELL',
                    'exit_reason': f'R_{reason}', 'pnl': actual_pnl, 'return': ret,
                    'price': result.filled_price, 'strategy': 'Rattlesnake',
                })
                logger.info(f"R_EXIT [{reason}] {symbol} @ ${result.filled_price:.2f} | "
                           f"PnL: ${actual_pnl:+,.0f} ({ret:+.1%}) | "
                           f"days={pos.get('days_held', 0)}")

                if self.notifier:
                    self.notifier.send_trade_alert('SELL', symbol, shares,
                                                   result.filled_price, f'R_{reason}', actual_pnl)
                self.save_state()

    def _open_rattlesnake_positions(self, prices: Dict[str, float]):
        """Find and open Rattlesnake mean-reversion entries."""
        if not self._hydra_available or not self.hydra_capital:
            return

        # Check regime
        regime_info = check_rattlesnake_regime(
            self._spy_hist, self._vix_current
        ) if self._spy_hist is not None else {'entries_allowed': True, 'max_positions': R_MAX_POSITIONS}

        if not regime_info['entries_allowed']:
            logger.info("Rattlesnake entries blocked: VIX panic")
            return

        max_r_pos = regime_info['max_positions']
        r_slots = max_r_pos - len(self.rattle_positions)
        if r_slots <= 0:
            return

        # Symbols already held by either strategy
        held = set(self.broker.positions.keys()) | {p['symbol'] for p in self.rattle_positions}

        # Find candidates
        candidates = find_rattlesnake_candidates(
            self._hist_cache, prices, held, max_candidates=r_slots
        )

        if not candidates:
            logger.info(
                "Rattlesnake: no qualifying entries | held=%d | slots=%d | price_symbols=%d",
                len(held),
                r_slots,
                len(prices),
            )
            return

        top = candidates[0]
        logger.info(
            "Rattlesnake candidates: %d | top=%s drop=%.1f%% RSI=%.1f",
            len(candidates),
            top.get('symbol'),
            top.get('drop_pct', 0.0) * 100,
            top.get('rsi', 0.0),
        )

        # Compute Rattlesnake budget
        r_exposure = compute_rattlesnake_exposure(
            self.rattle_positions, prices, self.hydra_capital.rattle_account
        )
        alloc = self.hydra_capital.compute_allocation(r_exposure)
        r_budget = alloc['rattle_budget']

        for cand in candidates:
            symbol = cand['symbol']
            price = cand['price']
            if price <= 0:
                continue

            # Position size: R_POSITION_SIZE of Rattlesnake budget
            position_value = r_budget * R_POSITION_SIZE
            shares = int(position_value / price)
            if shares < 1:
                continue
            cost = shares * price

            # Check broker has enough cash
            portfolio = self.broker.get_portfolio()
            if cost > portfolio.cash * 0.90:
                continue

            order = Order(symbol=symbol, action='BUY',
                          quantity=shares, order_type='MARKET',
                          decision_price=price)
            result = self._submit_order(order, prices)

            if result.status == 'FILLED':
                self.rattle_positions.append({
                    'symbol': symbol,
                    'entry_price': result.filled_price,
                    'entry_date': self._get_trading_date_str(),
                    'shares': shares,
                    'days_held': 0,
                })
                self.trades_today.append({
                    'symbol': symbol, 'action': 'BUY',
                    'price': result.filled_price, 'shares': shares,
                    'value': cost, 'strategy': 'Rattlesnake',
                })
                logger.info(f"R_ENTRY {symbol}: {shares} shares @ ${result.filled_price:.2f} "
                           f"(${cost:,.0f} | drop={cand['drop_pct']:.1%} | RSI={cand['rsi']:.0f})")

                if self.notifier:
                    self.notifier.send_trade_alert('BUY', symbol, shares,
                                                   result.filled_price, 'R_ENTRY', None)
                self.save_state()

    # ------------------------------------------------------------------
    # EFA Third Pillar
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Catalyst 4th Pillar (Cross-Asset Trend)
    # ------------------------------------------------------------------

    def _manage_catalyst_positions(self, prices: Dict[str, float]):
        """Manage Catalyst 4th pillar: rebalance every 5 days.

        Cross-asset trend (15% of portfolio): equal-weight among TLT/ZROZ/GLD/DBC
        above their SMA200. No permanent gold — GLD participates via trend filter.
        """
        if not _catalyst_available or not self.hydra_capital:
            return

        self._catalyst_day_counter += 1

        # Only rebalance every CATALYST_REBALANCE_DAYS (or on first run)
        if self._catalyst_day_counter < CATALYST_REBALANCE_DAYS and self.catalyst_positions:
            return

        self._catalyst_day_counter = 0

        # Augment prices with historical close for Catalyst assets
        # (live feed may not include TLT/GLD/DBC in validated batch)
        catalyst_prices = dict(prices)
        for cat_sym in CATALYST_TREND_ASSETS:
            if cat_sym not in catalyst_prices or catalyst_prices[cat_sym] <= 0:
                hist = self._catalyst_hist.get(cat_sym)
                if hist is not None and len(hist) > 0:
                    fallback = float(hist['Close'].iloc[-1])
                    if fallback > 0:
                        catalyst_prices[cat_sym] = fallback
                        logger.info(f"Catalyst: using historical close for {cat_sym}: ${fallback:.2f}")

        # Compute targets
        targets = compute_catalyst_targets(
            self._catalyst_hist,
            self.hydra_capital.catalyst_account,
            catalyst_prices,
        )
        target_map = {t['symbol']: t for t in targets}

        positions = self.broker.get_positions()

        # 1. Sell catalyst positions no longer in targets (or adjust down)
        for cp in list(self.catalyst_positions):
            sym = cp['symbol']
            pos = positions.get(sym)
            if not pos:
                self.catalyst_positions.remove(cp)
                continue

            if sym not in target_map:
                # Sell all shares of this catalyst position
                order = Order(symbol=sym, action='SELL',
                              quantity=cp['shares'], order_type='MARKET',
                              decision_price=catalyst_prices.get(sym, pos.avg_cost))
                result = self._submit_order(order, catalyst_prices)
                if result.status == 'FILLED':
                    pnl = (result.filled_price - cp['entry_price']) * cp['shares']
                    logger.info(f"CATALYST SELL {sym}: {cp['shares']} shares @ ${result.filled_price:.2f} (PnL: ${pnl:+,.0f})")
                    self.hydra_capital.record_catalyst_trade(pnl)
                    self.catalyst_positions.remove(cp)
                    # Remove from position_meta only if no other strategy holds it
                    in_rattle = any(rp['symbol'] == sym for rp in self.rattle_positions)
                    in_compass = sym in self.position_meta and not self.position_meta.get(sym, {}).get('_catalyst')
                    if not in_rattle and not in_compass:
                        self.position_meta.pop(sym, None)

        # 2. Buy new targets or adjust up
        for sym, target in target_map.items():
            current_shares = 0
            for cp in self.catalyst_positions:
                if cp['symbol'] == sym:
                    current_shares = cp['shares']
                    break

            needed = target['target_shares'] - current_shares
            if needed <= 0:
                continue

            price = catalyst_prices.get(sym, 0)
            if price <= 0:
                logger.warning(f"Catalyst: cannot buy {sym} — no price available")
                continue

            # Enforce ring-fenced budget: min(broker cash, catalyst budget)
            broker_cash = self.broker.get_portfolio().cash
            catalyst_remaining = self.hydra_capital.catalyst_account - sum(
                cp['shares'] * catalyst_prices.get(cp['symbol'], cp['entry_price'])
                for cp in self.catalyst_positions
            )
            available_cash = min(broker_cash, max(catalyst_remaining, 0)) * 0.95
            cost = needed * price
            if cost > available_cash:
                needed = int(available_cash / price)
                if needed <= 0:
                    continue

            order = Order(symbol=sym, action='BUY',
                          quantity=needed, order_type='MARKET',
                          decision_price=price)
            result = self._submit_order(order, catalyst_prices)
            if result.status == 'FILLED':
                fill_price = result.filled_price
                logger.info(f"CATALYST BUY {sym}: {needed} shares @ ${fill_price:.2f} ({target['sub_strategy']})")

                # Update catalyst_positions list
                existing = [cp for cp in self.catalyst_positions if cp['symbol'] == sym]
                if existing:
                    old = existing[0]
                    total_shares = old['shares'] + needed
                    old['entry_price'] = (old['entry_price'] * old['shares'] + fill_price * needed) / total_shares
                    old['shares'] = total_shares
                else:
                    self.catalyst_positions.append({
                        'symbol': sym,
                        'shares': needed,
                        'entry_price': fill_price,
                        'entry_date': self._get_trading_date_str(),
                        'sub_strategy': target['sub_strategy'],
                    })

                # Mark in position_meta
                self.position_meta[sym] = {
                    'entry_price': fill_price,
                    'entry_date': self._get_trading_date_str(),
                    'entry_day_index': self.trading_day_counter,
                    'original_entry_day_index': self.trading_day_counter,
                    'high_price': fill_price,
                    'entry_vol': 0.15,
                    'entry_daily_vol': 0.0095,
                    'sector': f'Catalyst ({target["sub_strategy"]})',
                    '_catalyst': True,
                    '_entry_reconciled': True,
                }

    def _efa_above_sma200(self) -> bool:
        """Check if EFA is above its 200-day SMA (regime filter for third pillar)."""
        if self._efa_hist is None or len(self._efa_hist) < EFA_SMA_PERIOD:
            return False
        efa_close = float(self._efa_hist['Close'].iloc[-1])
        efa_sma = float(self._efa_hist['Close'].iloc[-EFA_SMA_PERIOD:].mean())
        return efa_close > efa_sma

    def _sync_efa_runtime_state(self, prices: Dict[str, float] = None, reason: str = ''):
        if not self._hydra_available or not self.hydra_capital:
            return 0.0

        prices = prices or {}
        efa_pos = self.broker.get_positions().get(EFA_SYMBOL)
        efa_price = self._coerce_float(prices.get(EFA_SYMBOL), 0.0)
        if efa_price <= 0 and self._efa_hist is not None and len(self._efa_hist) > 0:
            efa_price = self._coerce_float(self._efa_hist['Close'].iloc[-1], 0.0)

        if efa_pos and getattr(efa_pos, 'shares', 0) > 0:
            if efa_price <= 0:
                efa_price = self._coerce_float(getattr(efa_pos, 'market_price', None), 0.0)
            if efa_price <= 0:
                efa_price = self._coerce_float(getattr(efa_pos, 'avg_cost', None), 0.0)
            target_value = self._coerce_float(efa_pos.shares, 0.0) * max(efa_price, 0.0)
        else:
            target_value = 0.0

        current_value = self._coerce_float(getattr(self.hydra_capital, 'efa_value', 0.0), 0.0)
        delta = target_value - current_value
        if abs(delta) > 0.01:
            self.hydra_capital.efa_value = target_value
            self.hydra_capital.rattle_account = self._coerce_float(
                getattr(self.hydra_capital, 'rattle_account', 0.0),
                0.0,
            ) - delta
            if target_value <= 0:
                logger.warning(
                    "EFA sync%s: cleared stale allocation $%.2f with no broker position",
                    f" ({reason})" if reason else "",
                    current_value,
                )
            else:
                logger.info(
                    "EFA sync%s: aligned allocation to broker market value $%.2f",
                    f" ({reason})" if reason else "",
                    target_value,
                )

        if target_value > 0 and efa_pos:
            meta = copy.deepcopy(self.position_meta.get(EFA_SYMBOL, {}))
            meta['entry_price'] = self._coerce_float(
                meta.get('entry_price'),
                self._coerce_float(getattr(efa_pos, 'avg_cost', None), efa_price),
            ) or max(efa_price, 0.0)
            meta['entry_date'] = meta.get('entry_date') or self._get_trading_date_str()
            meta['entry_day_index'] = self._coerce_int(meta.get('entry_day_index'), self.trading_day_counter)
            meta['original_entry_day_index'] = self._coerce_int(
                meta.get('original_entry_day_index'),
                meta['entry_day_index'],
            )
            meta['high_price'] = max(
                self._coerce_float(meta.get('high_price'), meta['entry_price']),
                max(efa_price, 0.0),
                meta['entry_price'],
            )
            meta['entry_vol'] = self._coerce_float(meta.get('entry_vol'), 0.15)
            meta['entry_daily_vol'] = self._coerce_float(meta.get('entry_daily_vol'), 0.0095)
            meta['sector'] = 'International Equity'
            meta['_efa'] = True
            meta['_entry_reconciled'] = bool(meta.get('_entry_reconciled', False))
            self.position_meta[EFA_SYMBOL] = meta
        elif target_value <= 0 and EFA_SYMBOL not in (self.broker.get_positions() if hasattr(self, 'broker') else {}):
            # Only pop if broker confirms no EFA shares (not a timing issue)
            self.position_meta.pop(EFA_SYMBOL, None)

        return target_value

    def _manage_efa_position(self, prices: Dict[str, float]):
        """Manage EFA third pillar: buy with idle cash, sell when needed.

        Called at the END of pre-close cycle, after all Momentum and Rattlesnake
        entries have been filled. Only truly idle cash flows to EFA.
        Uses _submit_order() for proper commission, audit trail, and IBKR compatibility.
        """
        if not self._hydra_available or not self.hydra_capital:
            return

        self._sync_efa_runtime_state(prices, reason='pre_manage')
        efa_price = prices.get(EFA_SYMBOL)
        if not efa_price or efa_price <= 0:
            if self._efa_hist is not None and len(self._efa_hist) > 0:
                efa_price = float(self._efa_hist['Close'].iloc[-1])
            else:
                logger.info("EFA: skipped (no live price and no historical fallback)")
                return

        # Current EFA position from broker
        positions = self.broker.get_positions()
        efa_pos = positions.get(EFA_SYMBOL)
        efa_shares = efa_pos.shares if efa_pos else 0

        efa_sma = None
        if self._efa_hist is not None and len(self._efa_hist) >= EFA_SMA_PERIOD:
            efa_sma = float(self._efa_hist['Close'].iloc[-EFA_SMA_PERIOD:].mean())
        efa_above_sma = bool(efa_sma is not None and efa_price > efa_sma)
        logger.info(
            "EFA decision: price=$%.2f | SMA200=%s | shares=%s | above_sma=%s",
            efa_price,
            f"${efa_sma:.2f}" if efa_sma is not None else "n/a",
            int(efa_shares) if efa_shares else 0,
            efa_above_sma,
        )

        # Check if we should sell (EFA below SMA200)
        if efa_shares > 0 and not efa_above_sma:
            order = Order(symbol=EFA_SYMBOL, action='SELL',
                          quantity=efa_shares, order_type='MARKET',
                          decision_price=efa_price)
            result = self._submit_order(order, prices)
            if result.status == 'FILLED':
                proceeds = result.filled_price * efa_shares
                logger.info(f"EFA SELL (below SMA200): {efa_shares} shares @ ${result.filled_price:.2f} = ${proceeds:,.0f}")
                self._sync_efa_runtime_state(prices, reason='sell_fill')
            return

        # Check if we should buy (idle cash available and EFA above SMA200)
        if not efa_above_sma:
            logger.info("EFA: skipped (below SMA200)")
            return

        # Use capital manager to determine truly idle cash (after recycling)
        r_exposure = compute_rattlesnake_exposure(
            self.rattle_positions, prices, self.hydra_capital.rattle_account
        )
        alloc = self.hydra_capital.compute_allocation(r_exposure)
        portfolio = self.broker.get_portfolio()
        # efa_idle = remaining Rattlesnake idle cash after recycling to COMPASS
        # Cap by actual broker cash to avoid over-allocation
        idle_cash = min(alloc['efa_idle'], portfolio.cash) * 0.90
        logger.info(
            "EFA budget: idle=$%.2f | portfolio_cash=$%.2f | efa_alloc=$%.2f",
            idle_cash,
            portfolio.cash,
            alloc.get('efa_idle', 0.0),
        )

        if idle_cash < EFA_MIN_BUY:
            logger.info(f"EFA: skipped (idle=${idle_cash:,.0f} < min=${EFA_MIN_BUY})")
            return

        shares = int(idle_cash / efa_price)
        if shares < 1:
            return

        order = Order(symbol=EFA_SYMBOL, action='BUY',
                      quantity=shares, order_type='MARKET',
                      decision_price=efa_price)
        result = self._submit_order(order, prices)
        if result.status == 'FILLED':
            cost = result.filled_price * shares
            logger.info(f"EFA BUY: {shares} shares @ ${result.filled_price:.2f} = ${cost:,.0f}")
            self.position_meta[EFA_SYMBOL] = {
                'entry_price': result.filled_price,
                'entry_date': self._get_trading_date_str(),
                'entry_day_index': self.trading_day_counter,
                'original_entry_day_index': self.trading_day_counter,
                'high_price': result.filled_price,
                'entry_vol': 0.15,
                'entry_daily_vol': 0.0095,
                'sector': 'International Equity',
                '_efa': True,
                '_entry_reconciled': True,  # MARKET order fill = real price, no reconciliation needed
            }
            self._sync_efa_runtime_state(prices, reason='buy_fill')

    def _liquidate_efa_for_capital(self, prices: Dict[str, float]):
        """Sell EFA to free capital for active strategies. Called BEFORE entries."""
        positions = self.broker.get_positions()
        efa_pos = positions.get(EFA_SYMBOL)
        if not efa_pos or efa_pos.shares <= 0:
            return

        efa_price = prices.get(EFA_SYMBOL)
        if not efa_price or efa_price <= 0:
            if self._efa_hist is not None and len(self._efa_hist) > 0:
                efa_price = float(self._efa_hist['Close'].iloc[-1])
            else:
                return

        # Check if COMPASS needs capital (exclude EFA, Catalyst, Rattlesnake)
        max_positions = self.get_max_positions()
        compass_positions = {
            s: p for s, p in positions.items()
            if s in self.position_meta
            and not self.position_meta.get(s, {}).get('_catalyst')
            and not self.position_meta.get(s, {}).get('_efa')
            and s != EFA_SYMBOL
            and not any(rp['symbol'] == s for rp in self.rattle_positions)
        }
        compass_needed = max_positions - len(compass_positions)

        # Check if Rattlesnake needs capital (has signals pending)
        rattle_needed = False
        if self._hydra_available and self.hydra_capital:
            rattle_count = len(self.rattle_positions)
            regime_info = check_rattlesnake_regime(
                self._spy_hist, self._vix_current
            ) if self._spy_hist is not None else {'max_positions': R_MAX_POSITIONS}
            max_r = regime_info['max_positions']
            if rattle_count < max_r:
                rattle_needed = True

        if compass_needed <= 0 and not rattle_needed:
            return  # No strategies need capital, keep EFA

        portfolio = self.broker.get_portfolio()
        avg_position_cost = portfolio.total_value * 0.20
        if portfolio.cash >= avg_position_cost:
            return  # Enough cash already, keep EFA

        # Liquidate EFA
        shares = efa_pos.shares
        pnl = (efa_price - efa_pos.avg_cost) * shares
        reason = "COMPASS" if compass_needed > 0 else "Rattlesnake"
        order = Order(symbol=EFA_SYMBOL, action='SELL',
                      quantity=shares, order_type='MARKET',
                      decision_price=efa_price)
        result = self._submit_order(order, prices)
        if result.status == 'FILLED':
            proceeds = result.filled_price * shares
            logger.info(f"EFA LIQUIDATE ({reason} needs capital): {shares} shares @ ${result.filled_price:.2f} = ${proceeds:,.0f} (PnL: ${pnl:+,.0f})")
            self.position_meta.pop(EFA_SYMBOL, None)
            if self.hydra_capital:
                self.hydra_capital.sell_efa(proceeds)

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
    # Auto-recovery: replay missed trading days
    # ------------------------------------------------------------------

    def _recover_missed_days(self):
        raw_date = self._recovery_gap_baseline
        if not raw_date:
            return 0

        try:
            last_date = date.fromisoformat(str(raw_date)[:10])
        except (ValueError, TypeError):
            return 0

        today = self.get_et_now().date()
        gap = self._trading_days_between(last_date, today)

        if gap <= 1:
            return 0

        if gap > 5:
            logger.critical(
                "Engine missed %d trading days (max 5 for auto-recovery). "
                "Manual intervention required.", gap
            )
            return 0

        logger.warning("[RECOVERY] Detected %d missed trading days (%s → %s)",
                       gap - 1, last_date, today)

        recovered = 0
        current = last_date + timedelta(days=1)

        while current < today:
            if current.weekday() >= 5 or current in US_MARKET_HOLIDAYS:
                current += timedelta(days=1)
                continue

            saved = {
                '_spy_hist': getattr(self, '_spy_hist', None),
                '_hist_date': getattr(self, '_hist_date', None),
                '_preclose_entries_done': self._preclose_entries_done,
                '_daily_open_done': self._daily_open_done,
            }
            try:
                self._preclose_entries_done = False
                self._daily_open_done = False
                self._hist_date = None

                missed_str = current.isoformat()
                next_day = (current + timedelta(days=1)).isoformat()

                # Step 1: Fetch historical closes
                symbols = list(self.broker.positions.keys())
                if hasattr(self, 'current_universe') and self.current_universe:
                    symbols = list(set(symbols + list(self.current_universe)))
                if not symbols:
                    logger.info("[RECOVERY] No symbols to fetch for %s, skipping", missed_str)
                    current += timedelta(days=1)
                    continue

                data = yf.download(symbols, start=missed_str, end=next_day, progress=False)
                if data is None or len(data) == 0:
                    logger.info("[RECOVERY] No market data for %s (holiday?), skipping", missed_str)
                    current += timedelta(days=1)
                    continue

                prices = self._recovery_price_dict(data, symbols)
                if not prices:
                    logger.info("[RECOVERY] No valid prices for %s, skipping", missed_str)
                    current += timedelta(days=1)
                    continue

                # Step 2: Reconstruct regime score
                try:
                    spy_hist = yf.download('SPY', end=next_day, period='2y', progress=False)
                    if isinstance(spy_hist.columns, pd.MultiIndex):
                        spy_hist.columns = [c[0] for c in spy_hist.columns]
                    if len(spy_hist) >= 252:
                        self._spy_hist = spy_hist
                        self.current_regime_score = compute_live_regime_score(spy_hist)
                except Exception as e:
                    logger.warning("[RECOVERY] Regime reconstruction failed for %s: %s", missed_str, e)

                # Step 3: Fetch ^GSPC close for cycle log
                try:
                    gspc = yf.download('^GSPC', start=missed_str, end=next_day, progress=False)
                    if isinstance(gspc.columns, pd.MultiIndex):
                        gspc.columns = [c[0] for c in gspc.columns]
                    if len(gspc) > 0:
                        self._recovery_spy_close = float(gspc['Close'].iloc[-1])
                    else:
                        self._recovery_spy_close = None
                except Exception as e:
                    logger.warning("[RECOVERY] GSPC fetch failed for %s: %s", missed_str, e)
                    self._recovery_spy_close = None

                # Step 4: Run rotation or stops
                hold_days = self.config.get('HOLD_DAYS', 5) if hasattr(self, 'config') else 5
                next_counter = self.trading_day_counter + 1
                is_rotation = (next_counter % hold_days == 0)

                self.trades_today = []
                if is_rotation:
                    self._preclose_entries_done = False
                    self.execute_preclose_entries(prices, _recovery_mode=True)
                else:
                    self.check_position_exits(prices)

                # Step 5: Increment state
                self.trading_day_counter += 1
                self.last_trading_date = current
                self.save_state()
                recovered += 1
                logger.info("[RECOVERY] Replayed %s (day %d, regime=%.3f%s)",
                            missed_str, self.trading_day_counter,
                            self.current_regime_score,
                            " ROTATION" if is_rotation else "")

            except Exception as e:
                logger.error("[RECOVERY] Failed on %s: %s", current, e, exc_info=True)
                break
            finally:
                self._spy_hist = saved['_spy_hist']
                self._hist_date = saved['_hist_date']
                self._daily_open_done = saved['_daily_open_done']

            current += timedelta(days=1)

        if recovered:
            logger.info("[RECOVERY] Complete: %d days recovered", recovered)
        self._recovery_gap_baseline = None
        return recovered

    # ------------------------------------------------------------------
    # Daily open routine
    # ------------------------------------------------------------------

    def daily_open(self):
        """Execute at market open each trading day"""
        if not self.is_new_trading_day():
            return

        today = self.get_et_now().date()

        # Detect if yesterday's pre-close was missed (e.g., Render cold start)
        # If _preclose_entries_done is still False from yesterday, we missed it
        self._missed_preclose = (not self._preclose_entries_done
                                  and self.trading_day_counter >= 1)
        if self._missed_preclose:
            logger.warning(f"[CATCH-UP] Pre-close was missed on day {self.trading_day_counter} "
                           f"(last_trading_date={self.last_trading_date})")

        self.last_trading_date = today
        self.trading_day_counter += 1
        self.trades_today = []
        self._daily_open_done = False
        self._preclose_entries_done = False

        # Decrement crash cooldown once per trading day (not per leverage call)
        if self.crash_cooldown > 0:
            self.crash_cooldown -= 1
        self._block_new_entries = False  # Reset daily; refresh_daily_data may re-set if SPY fails
        self._rotation_sells_today = False

        # Snapshot portfolio before any exits (for cycle log)
        portfolio = self.broker.get_portfolio()
        self._pre_rotation_value = portfolio.total_value
        self._pre_rotation_positions = list(self.broker.positions.keys())
        # Deep copy position data for close-price reconstruction in _update_cycle_log
        self._pre_rotation_positions_data = {
            sym: {
                'shares': pos.shares,
                'avg_cost': pos.avg_cost,
                'entry_price': self.position_meta.get(sym, {}).get('entry_price', pos.avg_cost),
                'sector': self.position_meta.get(sym, {}).get('sector', SECTOR_MAP.get(sym, 'Unknown')),
                'entry_day_index': self.position_meta.get(sym, {}).get('entry_day_index', self.trading_day_counter),
                'entry_date': self.position_meta.get(sym, {}).get('entry_date'),
            }
            for sym, pos in self.broker.positions.items()
        }
        self._pre_rotation_cash = self.broker.cash

        logger.info(f"\n{'='*60}")
        logger.info(f"TRADING DAY {self.trading_day_counter} | {today}")
        logger.info(f"{'='*60}")

        # 1. Refresh universe (if new year)
        self.refresh_universe()

        # 2. Refresh historical data
        self.refresh_daily_data()

        # 2b. Reconcile entry prices to actual close prices
        # Pre-close entries fill at ~15:30-15:50 ET intraday prices.
        # This adjusts them to the real close, preventing cumulative drift.
        self._reconcile_entry_prices()

        # 3. Update regime
        self.update_regime()

        # 4. Track portfolio value for crash velocity
        portfolio = self.broker.get_portfolio()
        self.portfolio_values_history.append(portfolio.total_value)
        # Trim in-memory to prevent unbounded growth (only need last 30 for crash velocity)
        if len(self.portfolio_values_history) > 30:
            self.portfolio_values_history = self.portfolio_values_history[-30:]

        # Log status
        current_leverage = self.get_current_leverage()
        max_pos = self.get_max_positions()
        regime_str = f"score={self.current_regime_score:.2f}"

        drawdown = (portfolio.total_value - self.peak_value) / self.peak_value \
            if self.peak_value > 0 else 0

        logger.info(f"Portfolio: ${portfolio.total_value:,.0f} | DD: {drawdown:.1%} | "
                     f"Regime: {regime_str} | "
                     f"Leverage: {current_leverage:.2f}x | "
                     f"Positions: {len(self.broker.positions)}/{max_pos}")

        # HYDRA: Update Rattlesnake regime + increment days held
        if self._hydra_available and self._spy_hist is not None:
            regime_info = check_rattlesnake_regime(self._spy_hist, self._vix_current)
            self.rattle_regime = regime_info['regime']
            # Increment days_held for all Rattlesnake positions
            for pos in self.rattle_positions:
                pos['days_held'] = pos.get('days_held', 0) + 1
            # Log HYDRA status
            hydra_str = f"HYDRA: R_regime={self.rattle_regime} | R_pos={len(self.rattle_positions)}"
            if self.hydra_capital:
                status = self.hydra_capital.get_status()
                hydra_str += (f" | C_acct=${status['compass_account']:,.0f} "
                             f"({status['compass_pct']:.0%}) | "
                             f"R_acct=${status['rattle_account']:,.0f} "
                             f"({status['rattle_pct']:.0%})")
                if status['current_recycled'] > 0:
                    hydra_str += f" | recycled=${status['current_recycled']:,.0f} ({status['recycled_pct']:.0%})"
            logger.info(hydra_str)

        # HYDRA: Sync logical accounts with actual portfolio performance
        # In exp60 backtest, update_accounts_after_day() and update_efa_value()
        # run every day to keep logical accounts aligned with real returns.
        if self._hydra_available and self.hydra_capital:
            try:
                # Fetch current prices for HYDRA sync (not yet available from run_once)
                sync_symbols = set(self.position_meta.keys())
                sync_symbols |= {p['symbol'] for p in self.rattle_positions}
                sync_symbols.discard(EFA_SYMBOL)
                raw_sync = self.data_feed.get_prices(list(sync_symbols))
                prices = self.validator.validate_batch(raw_sync) if raw_sync else {}

                # Compute daily returns for each strategy from portfolio history
                if len(self.portfolio_values_history) >= 2:
                    prev_total = self.portfolio_values_history[-2]
                    curr_total = portfolio.total_value
                    if prev_total > 0:
                        # Approximate COMPASS return from its positions
                        compass_invested = sum(
                            pos.shares * prices.get(sym, pos.avg_cost)
                            for sym, pos in self.broker.positions.items()
                            if sym in self.position_meta and sym != EFA_SYMBOL
                        )
                        compass_prev_invested = sum(
                            pos.shares * self.position_meta[sym].get('entry_price', pos.avg_cost)
                            for sym, pos in self.broker.positions.items()
                            if sym in self.position_meta and sym != EFA_SYMBOL
                        )
                        c_ret = (compass_invested / compass_prev_invested - 1) if compass_prev_invested > 0 else 0.0

                        # Approximate Rattlesnake return from its positions
                        r_invested = sum(
                            pos.get('shares', 0) * prices.get(pos['symbol'], pos['entry_price'])
                            for pos in self.rattle_positions
                        )
                        r_prev_invested = sum(
                            pos.get('shares', 0) * pos['entry_price']
                            for pos in self.rattle_positions
                        )
                        r_ret = (r_invested / r_prev_invested - 1) if r_prev_invested > 0 else 0.0

                        # Update logical accounts with daily returns
                        r_exposure = compute_rattlesnake_exposure(
                            self.rattle_positions, prices, self.hydra_capital.rattle_account
                        )
                        self.hydra_capital.update_accounts_after_day(c_ret, r_ret, r_exposure)

                # Update EFA value with daily return
                if self._efa_hist is not None and len(self._efa_hist) >= 2:
                    efa_prices = self._efa_hist['Close']
                    if len(efa_prices) >= 2:
                        efa_ret = float(efa_prices.iloc[-1] / efa_prices.iloc[-2] - 1)
                        self.hydra_capital.update_efa_value(efa_ret)

                self._sync_efa_runtime_state(prices, reason='daily_open')

                logger.info(f"HYDRA accounts synced: C=${self.hydra_capital.compass_account:,.0f} | "
                           f"R=${self.hydra_capital.rattle_account:,.0f} | "
                           f"EFA=${self.hydra_capital.efa_value:,.0f}")
            except Exception as e:
                logger.warning(f"HYDRA account sync failed (non-blocking): {e}")

        # ML: end-of-day snapshot
        if self.ml:
            try:
                prev_pv = self.portfolio_values_history[-2] if len(self.portfolio_values_history) >= 2 else None
                self.ml.on_end_of_day(
                    trading_day=self.trading_day_counter,
                    portfolio_value=portfolio.total_value,
                    cash=self.broker.cash,
                    peak_value=self.peak_value,
                    n_positions=len(self.broker.positions),
                    leverage=current_leverage,
                    crash_cooldown=self.crash_cooldown,
                    regime_score=self.current_regime_score,
                    max_positions_target=max_pos,
                    positions=list(self.broker.positions.keys()),
                    position_meta=self.position_meta,
                    spy_hist=self._spy_hist,
                    prev_portfolio_value=prev_pv,
                )
            except Exception as e:
                _ml_error_counts['snapshot'] += 1
                logger.warning(f"ML daily snapshot failed: {e}")

        # ML: weekly learning run (every 5 trading days)
        if self.ml and self.trading_day_counter % 5 == 0:
            try:
                insights = self.ml.run_learning()
                logger.info(f"ML learning run complete (phase {insights.get('phase', '?')}). "
                           f"Check state/ml_learning/insights.json")
            except Exception as e:
                logger.warning(f"ML learning run failed (non-blocking): {e}")

    def execute_trading_logic(self, prices: Dict[str, float]):
        """Daily open trading logic: exits only.
        Entries happen at pre-close (15:30 ET) via execute_preclose_entries().
        """
        # Check individual position exits (DD scaling handles risk continuously)
        self.check_position_exits(prices)

        # HYDRA: Check Rattlesnake exits (profit target, stop loss, time)
        if self._hydra_available and self.rattle_positions:
            self._check_rattlesnake_exits(prices)

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

    def execute_preclose_entries(self, prices: Dict[str, float], _recovery_mode=False):
        """Pre-close rotation: sell hold-expired positions, then open new ones.

        Called once per day during the 15:30-15:50 ET window.
        Sells (hold_expired) and buys happen together at pre-close/MOC.
        Signal uses yesterday's close (from _hist_cache), execution at
        current price (close to today's final close via MOC).

        Backtest validation: chassis_preclose_analysis.py variant C
        shows +0.79% CAGR and -7.8pp MaxDD improvement vs next-day MOC.
        """
        if self._preclose_entries_done:
            return

        logger.info(f"[PRE-CLOSE] Computing entry signal at {self.get_et_now().strftime('%H:%M:%S')} ET")

        # Capture positions before rotation
        positions_before = set(self.broker.positions.keys())

        # 1. Sell hold-expired positions first (frees cash for new entries)
        self.check_position_exits(prices, include_hold_expired=True)

        # 2. Liquidate EFA if active strategies need capital
        if self._hydra_available and not _recovery_mode:
            self._liquidate_efa_for_capital(prices)

        # 3. Open new positions using momentum scores from historical data
        # The _hist_cache contains data up to yesterday's close (refreshed at open)
        # This is exactly the Close[T-1] signal validated in the backtest
        self.open_new_positions(prices)

        # HYDRA: Rattlesnake entries (after COMPASS, uses separate budget)
        if self._hydra_available and not _recovery_mode:
            self._open_rattlesnake_positions(prices)

        # HYDRA: Catalyst 4th pillar (cross-asset trend + gold, rebalances every 5 days)
        if self._hydra_available and _catalyst_available and not _recovery_mode:
            try:
                self._manage_catalyst_positions(prices)
            except Exception as e:
                logger.warning(f"Catalyst management failed (non-blocking): {e}")

        # HYDRA: EFA passive pillar (after all active strategies, uses remaining idle cash)
        if self._hydra_available and not _recovery_mode:
            self._manage_efa_position(prices)

        # Detect rotation: if we had sells today (hold_expired OR stops) AND new buys
        positions_after = set(self.broker.positions.keys())
        had_sells = any(t['action'] == 'SELL' for t in self.trades_today)
        had_buys = any(t['action'] == 'BUY' for t in self.trades_today)
        if had_sells and had_buys:
            self._recovery_mode = _recovery_mode
            try:
                self._update_cycle_log(prices)
            finally:
                self._recovery_mode = False

        self._preclose_entries_done = True
        self.save_state()
        logger.info("[PRE-CLOSE] Entry signal complete")

    # ------------------------------------------------------------------
    # Entry price reconciliation (close-price alignment)
    # ------------------------------------------------------------------

    def _reconcile_entry_prices(self):
        """Reconcile entry prices with actual close prices from historical data.

        Pre-close entries (15:30-15:50 ET) fill at intraday prices that differ
        from the official close. This creates cumulative drift vs benchmarks
        that use close prices. We fix this at next-day open by updating
        entry_price and avg_cost to the real close of the entry date.
        """
        if not self._hist_cache:
            return

        reconciled = []
        for symbol, meta in self.position_meta.items():
            entry_date = meta.get('entry_date')
            if not entry_date:
                continue

            # Only reconcile entries from the previous trading day
            # (entries from today haven't closed yet)
            today = self.get_et_now().date()
            try:
                entry_dt = date.fromisoformat(entry_date)
            except (ValueError, TypeError):
                continue
            if entry_dt >= today:
                continue

            # Already reconciled?
            if meta.get('_entry_reconciled'):
                continue

            # Get close price on entry date from historical data
            hist = self._hist_cache.get(symbol)
            if hist is None or len(hist) == 0:
                continue

            try:
                entry_close = None
                for idx_date, row in hist.iterrows():
                    row_date = idx_date.date() if hasattr(idx_date, 'date') else idx_date
                    if str(row_date) == entry_date:
                        entry_close = float(row['Close'])
                        break

                if entry_close is None or entry_close <= 0:
                    continue

                old_price = meta['entry_price']
                diff = abs(old_price - entry_close)
                if diff < 0.005:
                    # Already matches (within half a cent)
                    meta['_entry_reconciled'] = True
                    continue

                # Update entry price
                meta['entry_price'] = entry_close
                meta['high_price'] = max(meta.get('high_price', entry_close), entry_close)
                meta['_entry_reconciled'] = True

                # Update broker's avg_cost (PaperBroker only — IBKR positions are read-only)
                if isinstance(self.broker, PaperBroker) and symbol in self.broker.positions:
                    self.broker.positions[symbol].avg_cost = entry_close

                diff_pct = (entry_close / old_price - 1) * 100
                reconciled.append(f"{symbol}: ${old_price:.2f} -> ${entry_close:.2f} ({diff_pct:+.2f}%)")

            except Exception as e:
                logger.debug(f"Entry reconciliation failed for {symbol}: {e}")

        if reconciled:
            logger.info(f"Entry price reconciliation: {len(reconciled)} positions adjusted to close prices")
            for r in reconciled:
                logger.info(f"  {r}")
            self.save_state()

    # ------------------------------------------------------------------
    # Cycle log (automatic 5-day rotation tracking)
    # ------------------------------------------------------------------

    def _reconstruct_close_portfolio(self, positions_dict, cash):
        """Reconstruct portfolio value using today's close prices.

        Called after rotation to compute accurate end-of-cycle value.
        Uses yfinance close prices for the positions that were just sold.
        """
        try:
            symbols = list(positions_dict.keys())
            if not symbols:
                return cash
            data = yf.download(symbols + ['SPY'], period='2d', progress=False)
            if len(data) == 0:
                return None
            total = cash
            is_multi = isinstance(data.columns, pd.MultiIndex)
            for sym, pos in positions_dict.items():
                shares = pos.get('shares', 0)
                try:
                    if is_multi:
                        close = float(data['Close'][sym].iloc[-1])
                    else:
                        # Single-symbol fallback: verify it's our symbol, not SPY
                        if len(symbols) == 1:
                            close = float(data['Close'].iloc[-1])
                        else:
                            raise KeyError(f"{sym} not individually accessible in flat DataFrame")
                    total += shares * close
                except Exception:
                    total += shares * pos.get('avg_cost', 0)
            return total
        except Exception as e:
            logger.warning(f"Could not reconstruct close portfolio: {e}")
            return None

    def _get_spy_close(self):
        """Get S&P 500 index close price for today (or latest available)."""
        try:
            gspc = yf.download('^GSPC', period='2d', progress=False)
            if isinstance(gspc.columns, pd.MultiIndex):
                gspc.columns = [c[0] for c in gspc.columns]
            if len(gspc) > 0:
                return float(gspc['Close'].iloc[-1])
        except Exception as e:
            logger.warning(f"Could not fetch S&P 500 close: {e}")
        return None

    def _trading_days_between(self, start_date, end_date):
        if start_date >= end_date:
            return 0
        count = 0
        current = start_date + timedelta(days=1)
        while current <= end_date:
            if current.weekday() < 5:
                count += 1
            current += timedelta(days=1)
        return count

    def _recovery_price_dict(self, data, symbols):
        prices = {}
        is_multi = isinstance(data.columns, pd.MultiIndex)
        for sym in symbols:
            try:
                if is_multi:
                    close = float(data['Close'][sym].iloc[-1])
                else:
                    close = float(data['Close'].iloc[-1])
                if not math.isnan(close) and close > 0:
                    prices[sym] = close
            except (KeyError, IndexError):
                continue
        return prices

    def _new_cycle_log_entry(self, cycle_number: int, start_date: str,
                             portfolio_start: float, spy_start: Optional[float],
                             positions: List[str]):
        return {
            'cycle': cycle_number,
            'start_date': start_date,
            'end_date': None,
            'status': 'active',
            'portfolio_start': round(portfolio_start, 2),
            'portfolio_end': None,
            'spy_start': round(spy_start, 2) if spy_start else None,
            'spy_end': None,
            'positions': list(positions),
            'positions_current': list(positions),
            'hydra_return': None,
            'spy_return': None,
            'alpha': None,
            'stop_events': [],
            'positions_detail': [],
            'sector_breakdown': {},
            'exits_by_reason': {},
            'cycle_return_pct': None,
            'spy_return_pct': None,
            'alpha_pct': None,
        }

    def _validate_cycle_log_entry(self, entry: dict) -> bool:
        issues = []
        cycle_number = self._coerce_int(entry.get('cycle'), 0)
        if cycle_number <= 0:
            issues.append(f"cycle={cycle_number} must be > 0")

        start_date = entry.get('start_date')
        try:
            date.fromisoformat(start_date)
        except Exception:
            issues.append(f"start_date={start_date!r} is not a valid ISO date")

        end_date = entry.get('end_date')
        if end_date not in (None, ''):
            try:
                date.fromisoformat(end_date)
            except Exception:
                issues.append(f"end_date={end_date!r} is not a valid ISO date")

        cycle_return_pct = entry.get('cycle_return_pct')
        if cycle_return_pct is not None:
            try:
                cycle_return_pct = float(cycle_return_pct)
            except (TypeError, ValueError):
                issues.append(f"cycle_return_pct={cycle_return_pct!r} is not numeric")
            else:
                if not math.isfinite(cycle_return_pct):
                    issues.append(f"cycle_return_pct={cycle_return_pct!r} is not finite")

        if issues:
            logger.warning(
                "Skipping invalid cycle log entry %s: %s",
                entry.get('cycle', '?'),
                " | ".join(issues),
            )
            return False
        return True

    def _append_cycle_log_entry(self, cycles: List[dict], entry: dict) -> bool:
        if not self._validate_cycle_log_entry(entry):
            return False
        cycles.append(entry)
        return True

    def _cycle_exit_reason_bucket(self, exit_reason: Optional[str]) -> Optional[str]:
        mapping = {
            'position_stop': 'stop_loss',
            'trailing_stop': 'trailing',
            'hold_expired': 'rotation',
            'universe_rotation': 'rotation',
        }
        return mapping.get(exit_reason, exit_reason)

    def _build_cycle_positions_detail(self, cycle: dict,
                                      pre_rot_positions: dict,
                                      prices: Dict[str, float]) -> List[dict]:
        details = []
        stop_events = {
            event.get('stopped'): event
            for event in cycle.get('stop_events', [])
            if event.get('stopped')
        }
        sell_trades = {}
        for trade in self.trades_today:
            if trade.get('action') == 'SELL' and trade.get('symbol'):
                sell_trades.setdefault(trade['symbol'], trade)

        symbols = list(dict.fromkeys(
            list(cycle.get('positions', []))
            + list(cycle.get('positions_current', []))
            + list(stop_events.keys())
        ))
        carried_symbols = set(self.broker.positions.keys()) & set(symbols)

        for symbol in symbols:
            base = pre_rot_positions.get(symbol, {})
            stop_event = stop_events.get(symbol)
            sell_trade = sell_trades.get(symbol)
            current_meta = self.position_meta.get(symbol, {})
            current_pos = self.broker.positions.get(symbol)

            entry_price = (
                base.get('entry_price')
                or (stop_event.get('entry_price') if stop_event else None)
                or current_meta.get('entry_price')
                or base.get('avg_cost')
                or (current_pos.avg_cost if current_pos else None)
            )
            if not entry_price:
                continue

            sector = (
                base.get('sector')
                or (stop_event.get('sector') if stop_event else None)
                or current_meta.get('sector')
                or SECTOR_MAP.get(symbol, 'Unknown')
            )

            exit_reason = None
            exit_price = None
            pnl_pct = None
            days_held = None

            if sell_trade:
                exit_reason = sell_trade.get('exit_reason')
                exit_price = sell_trade.get('price')
                pnl_pct = ((exit_price - entry_price) / entry_price * 100) if exit_price else None
                entry_day_index = base.get('entry_day_index', self.trading_day_counter)
                days_held = self.trading_day_counter - entry_day_index + 1
            elif stop_event:
                exit_reason = stop_event.get('reason')
                exit_price = stop_event.get('exit_price')
                if exit_price:
                    pnl_pct = (exit_price - entry_price) / entry_price * 100
                elif stop_event.get('return') is not None:
                    pnl_pct = stop_event.get('return')
                days_held = stop_event.get('days_held')
            elif symbol in carried_symbols and current_pos:
                exit_reason = 'carried_forward'
                exit_price = prices.get(symbol, current_pos.avg_cost)
                pnl_pct = (exit_price - entry_price) / entry_price * 100 if exit_price else None
                entry_day_index = current_meta.get('entry_day_index', self.trading_day_counter)
                days_held = self.trading_day_counter - entry_day_index + 1
            else:
                continue

            details.append({
                'symbol': symbol,
                'entry_price': round(entry_price, 2),
                'exit_price': round(exit_price, 2) if exit_price is not None else None,
                'pnl_pct': round(pnl_pct, 2) if pnl_pct is not None else None,
                'exit_reason': exit_reason,
                'sector': sector,
                'days_held': int(days_held) if days_held is not None else None,
            })

        return details

    def _enrich_cycle_summary(self, cycle: dict, pre_rot_positions: dict,
                              prices: Dict[str, float]):
        defaults = {
            'positions_detail': [],
            'sector_breakdown': {},
            'exits_by_reason': {},
            'cycle_return_pct': None,
            'spy_return_pct': cycle.get('spy_return'),
            'alpha_pct': None,
        }

        try:
            positions_detail = self._build_cycle_positions_detail(
                cycle, pre_rot_positions, prices
            )
            sector_breakdown = {}
            exits_by_reason = {}
            for detail in positions_detail:
                sector = detail.get('sector') or 'Unknown'
                sector_breakdown[sector] = sector_breakdown.get(sector, 0) + 1
                exit_bucket = self._cycle_exit_reason_bucket(detail.get('exit_reason'))
                if exit_bucket and exit_bucket != 'carried_forward':
                    exits_by_reason[exit_bucket] = exits_by_reason.get(exit_bucket, 0) + 1

            cycle_return_pct = None
            portfolio_start = cycle.get('portfolio_start')
            portfolio_end = cycle.get('portfolio_end')
            if portfolio_start and portfolio_end is not None:
                cycle_return_pct = round(
                    (portfolio_end - portfolio_start) / portfolio_start * 100, 2
                )

            spy_return_pct = cycle.get('spy_return')
            alpha_pct = None
            if cycle_return_pct is not None and spy_return_pct is not None:
                alpha_pct = round(cycle_return_pct - spy_return_pct, 2)

            cycle.update({
                'positions_detail': positions_detail,
                'sector_breakdown': sector_breakdown,
                'exits_by_reason': exits_by_reason,
                'cycle_return_pct': cycle_return_pct,
                'spy_return_pct': spy_return_pct,
                'alpha_pct': alpha_pct,
            })
        except Exception as e:
            logger.warning(f"Cycle log enrichment failed: {e}")
            cycle.update(defaults)

    def _update_cycle_log(self, prices: Dict[str, float]):
        """Close the active cycle and open a new one in cycle_log.json.

        Called automatically after a rotation (hold_expired sells + new buys).
        Uses close prices for all values: portfolio end = cash + sum(shares * close),
        SPY benchmark = SPY close. Cycle N+1 start = Cycle N end (no gaps).
        """
        with self._cycle_log_lock:
            self._update_cycle_log_inner(prices)

    def _update_cycle_log_inner(self, prices: Dict[str, float]):
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

        # Reconstruct close-price portfolio value from pre-rotation positions
        # _pre_rotation_positions_data is set in execute_new_day() with full position dicts
        pre_rot_positions = getattr(self, '_pre_rotation_positions_data', {})
        pre_rot_cash = getattr(self, '_pre_rotation_cash', self.broker.cash)

        close_portfolio_value = self._reconstruct_close_portfolio(pre_rot_positions, pre_rot_cash)
        if close_portfolio_value is None:
            # Fallback: use the pre-rotation snapshot (less accurate but better than nothing)
            close_portfolio_value = self._pre_rotation_value
            logger.warning("Could not reconstruct close portfolio, using pre-rotation snapshot")

        # SPY close price (today's close — same timing as position closes)
        if getattr(self, '_recovery_mode', False) and getattr(self, '_recovery_spy_close', None) is not None:
            spy_close = self._recovery_spy_close
        else:
            spy_close = self._get_spy_close()

        # Close the active cycle
        for cycle in cycles:
            if cycle.get('status') == 'active':
                cycle['end_date'] = today
                cycle['status'] = 'closed'
                cycle['portfolio_end'] = round(close_portfolio_value, 2)
                if spy_close and cycle.get('spy_start'):
                    cycle['spy_end'] = round(spy_close, 2)
                    cycle['spy_return'] = round(
                        (spy_close - cycle['spy_start']) / cycle['spy_start'] * 100, 2)
                # Holdings-only return (excludes cash, direct comparison vs SPY)
                invested_now = sum(p['shares'] * prices.get(s, p['avg_cost'])
                                   for s, p in pre_rot_positions.items())
                invested_at_cost = sum(p['shares'] * p['avg_cost']
                                       for p in pre_rot_positions.values())
                if invested_at_cost > 0:
                    cycle['hydra_return'] = round(
                        (invested_now / invested_at_cost - 1) * 100, 2)
                else:
                    cycle['hydra_return'] = 0.0
                if cycle.get('hydra_return') is not None and cycle.get('spy_return') is not None:
                    cycle['alpha'] = round(cycle['hydra_return'] - cycle['spy_return'], 2)

                self._enrich_cycle_summary(cycle, pre_rot_positions, prices)

                status_str = 'WIN' if cycle.get('alpha', 0) >= 0 else 'LOSS'
                logger.info(f"CYCLE #{cycle['cycle']} CLOSED: "
                           f"HYDRA {cycle['hydra_return']:+.2f}% | "
                           f"S&P {cycle.get('spy_return', 0):+.2f}% | "
                           f"Alpha {cycle.get('alpha', 0):+.2f}pp | {status_str}")
                break

        # New cycle start = old cycle end (close-to-close, no gaps)
        new_start_value = close_portfolio_value
        new_spy_start = spy_close

        # Open new cycle
        new_positions = list(self.broker.positions.keys())
        next_cycle = max((c.get('cycle', 0) for c in cycles), default=0) + 1

        new_cycle_entry = self._new_cycle_log_entry(
            next_cycle, today, new_start_value, new_spy_start, new_positions
        )
        if getattr(self, '_recovery_mode', False):
            new_cycle_entry['reconstructed'] = True
            new_cycle_entry['recovery_date'] = datetime.now().strftime('%Y-%m-%d')
        new_cycle_opened = self._append_cycle_log_entry(cycles, new_cycle_entry)

        # Save (atomic write to prevent corruption on crash)
        # Sanitize NaN/Inf → None (NaN is invalid JSON, breaks JS parsers)
        _sanitize_nan(cycles)
        os.makedirs('state', exist_ok=True)
        try:
            fd, tmp_path = tempfile.mkstemp(dir='state', suffix='.json.tmp')
            with os.fdopen(fd, 'w') as fp:
                json.dump(cycles, fp, indent=2, allow_nan=False)
            os.replace(tmp_path, log_file)
        except Exception as e:
            logger.error(f"Atomic cycle log write failed: {e}")
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if new_cycle_opened:
            logger.info(f"CYCLE #{next_cycle} OPENED: {', '.join(new_positions)} | "
                        f"${new_start_value:,.0f}")

        # WhatsApp/Email notification on rotation
        if self.notifier and hasattr(self.notifier, 'send_rotation_alert'):
            try:
                closed_cycle_data = next((c for c in cycles if c.get('cycle') == next_cycle - 1), {})
                self.notifier.send_rotation_alert(
                    cycle_num=next_cycle - 1,
                    closed_positions=self._pre_rotation_positions,
                    new_positions=new_positions,
                    hydra_return=closed_cycle_data.get('hydra_return', 0.0),
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
                    closed_return = c.get('hydra_return', 0.0)
                    closed_status = 'WIN' if closed_return >= 0 else 'LOSS'
                    break
            try:
                git_sync_rotation(closed_cycle, closed_return, closed_status)
            except Exception as e:
                logger.warning(f"git sync rotation failed: {e}")

    def _ensure_active_cycle(self):
        """On startup, ensure cycle_log.json has an active cycle if we hold positions."""
        with self._cycle_log_lock:
            self._ensure_active_cycle_inner()

    def _ensure_active_cycle_inner(self):
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
        spy_price = None
        try:
            spy = yf.download('^GSPC', period='5d', progress=False)
            if isinstance(spy.columns, pd.MultiIndex):
                spy.columns = [c[0] for c in spy.columns]
            if len(spy) > 0:
                spy_price = float(spy['Close'].iloc[-1])
        except Exception:
            pass

        next_cycle = max((c.get('cycle', 0) for c in cycles), default=0) + 1
        today = self.last_trading_date.isoformat() if self.last_trading_date else date.today().isoformat()

        # Use last closed cycle's portfolio_end as start value (more accurate than current market price)
        last_closed = [c for c in cycles if c.get('status') == 'closed' and c.get('portfolio_end')]
        if last_closed:
            start_value = last_closed[-1]['portfolio_end']
        else:
            start_value = round(portfolio.total_value, 2)

        current_positions = list(self.broker.positions.keys())
        new_cycle_entry = self._new_cycle_log_entry(
            next_cycle, today, start_value, spy_price, current_positions
        )
        if not self._append_cycle_log_entry(cycles, new_cycle_entry):
            return

        os.makedirs('state', exist_ok=True)
        try:
            fd, tmp_path = tempfile.mkstemp(dir='state', suffix='.json.tmp')
            with os.fdopen(fd, 'w') as fp:
                json.dump(cycles, fp, indent=2)
            os.replace(tmp_path, log_file)
        except Exception as e:
            logger.error(f"Atomic cycle log write failed: {e}")
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        logger.info(f"CYCLE #{next_cycle} initialized on startup: "
                    f"{list(self.broker.positions.keys())}")

    def _update_cycle_log_stop(self, stopped_symbol: str, replacement_symbol: str,
                                exit_reason: str, stop_return: float,
                                stop_details: dict = None):
        """Update the active cycle when a mid-cycle stop fires and a replacement enters.

        Records the stop event and updates positions_current so the dashboard
        shows the actual current holdings, not just the cycle-start snapshot.
        """
        with self._cycle_log_lock:
            self._update_cycle_log_stop_inner(
                stopped_symbol, replacement_symbol, exit_reason,
                stop_return, stop_details)

    def _update_cycle_log_stop_inner(self, stopped_symbol: str, replacement_symbol: str,
                                      exit_reason: str, stop_return: float,
                                      stop_details: dict = None):
        log_file = os.path.join('state', 'cycle_log.json')
        if not os.path.exists(log_file):
            return
        try:
            with open(log_file, 'r') as f:
                cycles = json.load(f)
        except Exception:
            return

        for c in cycles:
            if c.get('status') != 'active':
                continue
            if 'stop_events' not in c:
                c['stop_events'] = []
            if 'positions_current' not in c:
                c['positions_current'] = list(c.get('positions', []))

            today = self.get_et_now().date().isoformat()
            event = {
                'date': today,
                'stopped': stopped_symbol,
                'replacement': replacement_symbol,
                'reason': exit_reason,
            }
            if stop_details:
                if stop_details.get('exit_price') is not None:
                    event['exit_price'] = round(stop_details['exit_price'], 2)
                if stop_details.get('entry_price') is not None:
                    event['entry_price'] = round(stop_details['entry_price'], 2)
                if stop_details.get('sector'):
                    event['sector'] = stop_details['sector']
                if stop_details.get('days_held') is not None:
                    event['days_held'] = int(stop_details['days_held'])
            event_return = stop_return
            if (stop_details and stop_details.get('entry_price')
                    and stop_details.get('exit_price') is not None):
                entry_price = stop_details['entry_price']
                if entry_price:
                    event_return = (
                        (stop_details['exit_price'] - entry_price) / entry_price
                    )
            event['return'] = round(event_return * 100, 1)
            c['stop_events'].append(event)

            current = c['positions_current']
            if stopped_symbol in current:
                current.remove(stopped_symbol)
            if replacement_symbol and replacement_symbol not in current:
                current.append(replacement_symbol)
            c['positions_current'] = current
            break

        try:
            fd, tmp_path = tempfile.mkstemp(dir='state', suffix='.json.tmp')
            with os.fdopen(fd, 'w') as fp:
                json.dump(cycles, fp, indent=2)
            os.replace(tmp_path, log_file)
        except Exception as e:
            logger.warning(f"Failed to update cycle log stop: {e}")
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _coerce_float(self, value, default=0.0):
        try:
            number = float(value)
            if np.isnan(number) or np.isinf(number):
                return float(default)
            return number
        except (TypeError, ValueError):
            return float(default)

    def _coerce_int(self, value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return int(default)

    def _estimate_state_positions_value(self, positions: Dict[str, dict]) -> float:
        total = 0.0
        for data in (positions or {}).values():
            if not isinstance(data, dict):
                continue
            shares = self._coerce_float(data.get('shares'), 0.0)
            avg_cost = self._coerce_float(data.get('avg_cost'), 0.0)
            if shares > 0 and avg_cost > 0:
                total += shares * avg_cost
        return total

    def _get_state_reference_date(self, state) -> date:
        if isinstance(state, dict):
            timestamp = state.get('timestamp')
            if isinstance(timestamp, str) and timestamp:
                normalized = timestamp.strip()
                if normalized.endswith('Z'):
                    normalized = f"{normalized[:-1]}+00:00"
                try:
                    return datetime.fromisoformat(normalized).date()
                except ValueError:
                    pass
        return date.today()

    def _validate_position_meta(self, meta, positions):
        cleaned = {}
        today_str = self._get_trading_date_str()
        for symbol, entry in meta.items():
            if symbol not in positions:
                # Preserve strategy-flagged entries (may be temporarily out of sync)
                if isinstance(entry, dict) and (entry.get('_catalyst') or entry.get('_efa') or symbol == EFA_SYMBOL):
                    logger.info(f"position_meta: preserving {symbol} (strategy-flagged, not yet in broker)")
                    cleaned[symbol] = entry
                else:
                    logger.warning(f"position_meta: removing stale symbol {symbol} (not in positions)")
                continue
            if not isinstance(entry, dict):
                entry = {}
            # entry_price
            try:
                ep = float(entry.get('entry_price', 0))
                if ep <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                logger.warning(f"position_meta[{symbol}]: invalid entry_price={entry.get('entry_price')!r}, resetting to 0.0")
                ep = 0.0
            entry['entry_price'] = ep
            # entry_date
            ed = entry.get('entry_date')
            try:
                if not isinstance(ed, str) or not ed:
                    raise ValueError
                parsed_ed = date.fromisoformat(ed)
                # Snap weekend dates to next Monday
                if parsed_ed.weekday() >= 5:
                    days_ahead = 7 - parsed_ed.weekday()  # Mon=0..Sun=6
                    corrected = parsed_ed + timedelta(days=days_ahead)
                    logger.warning(f"position_meta[{symbol}]: entry_date={ed} is a weekend, snapping to {corrected.isoformat()}")
                    entry['entry_date'] = corrected.isoformat()
            except (TypeError, ValueError):
                logger.warning(f"position_meta[{symbol}]: invalid entry_date={ed!r}, resetting to {today_str}")
                entry['entry_date'] = today_str
            # sector
            sector = entry.get('sector')
            if not isinstance(sector, str) or not sector.strip():
                logger.warning(f"position_meta[{symbol}]: invalid sector={sector!r}, resetting to 'Unknown'")
                entry['sector'] = 'Unknown'
            # entry_vol
            if 'entry_vol' in entry:
                try:
                    ev = float(entry['entry_vol'])
                    if ev < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    logger.warning(f"position_meta[{symbol}]: invalid entry_vol={entry['entry_vol']!r}, resetting to 0.01")
                    entry['entry_vol'] = 0.01
            # entry_daily_vol
            if 'entry_daily_vol' in entry:
                try:
                    edv = float(entry['entry_daily_vol'])
                    if edv < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    logger.warning(f"position_meta[{symbol}]: invalid entry_daily_vol={entry['entry_daily_vol']!r}, resetting to 0.01")
                    entry['entry_daily_vol'] = 0.01
            cleaned[symbol] = entry
        return cleaned

    def _build_position_meta_defaults(self, symbol: str, data: dict,
                                      trading_day_counter: int,
                                      entry_date: Optional[str]) -> dict:
        avg_cost = self._coerce_float((data or {}).get('avg_cost'), 0.0)
        entry_day_index = max(0, trading_day_counter)
        return {
            'entry_price': avg_cost,
            'high_price': avg_cost,
            'entry_day_index': entry_day_index,
            'original_entry_day_index': entry_day_index,
            'entry_date': entry_date,
            'sector': SECTOR_MAP.get(symbol, 'Unknown'),
        }

    def _write_corrupted_state_backup(self, state: dict, violations: List[str]) -> Optional[str]:
        os.makedirs('state', exist_ok=True)
        backup_path = os.path.join(
            'state',
            f"compass_state_CORRUPTED_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
        )
        payload = copy.deepcopy(state)
        payload['_validation_errors'] = list(violations)
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(dir='state', suffix='.json.tmp')
            with os.fdopen(fd, 'w') as fp:
                json.dump(payload, fp, indent=2, default=str)
            os.replace(tmp_path, backup_path)
            backup_files = sorted(glob.glob(os.path.join('state', 'compass_state_CORRUPTED_*.json')))
            if len(backup_files) > 20:
                prune_count = len(backup_files) - 20
                for old_path in backup_files[:prune_count]:
                    try:
                        os.unlink(old_path)
                    except OSError as prune_err:
                        logger.warning(f"Failed to prune corrupted state backup {old_path}: {prune_err}")
                logger.warning(f"Pruned {prune_count} old corrupted state backups")
            return backup_path
        except Exception as backup_err:
            logger.error(f"Failed to persist corrupted state backup: {backup_err}")
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        return None

    def _cleanup_old_corrupted_backups(self, max_age_days=7, max_files=10):
        pattern = os.path.join('state', 'compass_state_CORRUPTED_*.json')
        files = sorted(glob.glob(pattern), key=os.path.getmtime)
        now = time_module.time()
        max_age_seconds = max_age_days * 86400
        remaining = []
        for fpath in files:
            try:
                age = now - os.path.getmtime(fpath)
                if age > max_age_seconds:
                    os.unlink(fpath)
                    logger.info(f"Deleted old corrupted backup (age={age / 86400:.1f}d): {fpath}")
                else:
                    remaining.append(fpath)
            except OSError as e:
                logger.warning(f"Failed to delete corrupted backup {fpath}: {e}")
                remaining.append(fpath)
        if len(remaining) > max_files:
            to_delete = remaining[:len(remaining) - max_files]
            for fpath in to_delete:
                try:
                    os.unlink(fpath)
                    logger.info(f"Deleted excess corrupted backup: {fpath}")
                except OSError as e:
                    logger.warning(f"Failed to delete corrupted backup {fpath}: {e}")

    def _validate_state(self, state, source='save', previous_state=None):
        state = copy.deepcopy(state or {})
        violations = []
        initial_capital = self._coerce_float(
            self.config.get('PAPER_INITIAL_CASH', self.config.get('INITIAL_CAPITAL', 100_000)),
            100_000.0,
        )

        positions = state.get('positions')
        if not isinstance(positions, dict):
            violations.append("positions must be a dict; resetting to empty")
            positions = {}
        state['positions'] = positions

        position_meta = state.get('position_meta')
        if not isinstance(position_meta, dict):
            violations.append("position_meta must be a dict; resetting to empty")
            position_meta = {}
        state['position_meta'] = position_meta

        if source == 'load':
            cleaned_positions = {}
            invalid_position_symbols = []
            for symbol, data in positions.items():
                if not isinstance(data, dict):
                    violations.append(f"positions[{symbol}] must be a dict; removing invalid position")
                    invalid_position_symbols.append(symbol)
                    continue

                shares = self._coerce_float(data.get('shares'), 0.0)
                avg_cost = self._coerce_float(data.get('avg_cost'), 0.0)
                if shares <= 0 or avg_cost <= 0:
                    violations.append(
                        f"positions[{symbol}] has invalid shares/avg_cost ({shares}, {avg_cost}); removing invalid position"
                    )
                    invalid_position_symbols.append(symbol)
                    continue

                cleaned_positions[symbol] = {
                    'shares': shares,
                    'avg_cost': avg_cost,
                }

            if invalid_position_symbols:
                for symbol in invalid_position_symbols:
                    if symbol in position_meta:
                        violations.append(
                            f"position_meta[{symbol}] removed because the position payload was invalid"
                        )
                        position_meta.pop(symbol, None)

            positions = cleaned_positions
            state['positions'] = positions

        trading_day_counter = self._coerce_int(state.get('trading_day_counter'), 0)
        if trading_day_counter < 0:
            violations.append(f"trading_day_counter={trading_day_counter} cannot be negative")
            if source == 'load':
                trading_day_counter = 0
        if trading_day_counter > 100000:
            violations.append(f"trading_day_counter={trading_day_counter} exceeds max supported value")
            if source == 'load':
                trading_day_counter = 100000

        prev_trading_day = None
        if previous_state is not None:
            prev_trading_day = self._coerce_int(previous_state.get('trading_day_counter'), trading_day_counter)
        elif self._last_persisted_trading_day_counter is not None:
            prev_trading_day = self._last_persisted_trading_day_counter
        if prev_trading_day is not None and trading_day_counter < prev_trading_day:
            violations.append(
                f"trading_day_counter decreased from {prev_trading_day} to {trading_day_counter}; keeping {prev_trading_day}"
            )
            trading_day_counter = prev_trading_day
        state['trading_day_counter'] = trading_day_counter

        stats = state.get('stats')
        if not isinstance(stats, dict):
            violations.append("stats must be a dict; resetting to empty")
            stats = {}
        legacy_cycles_completed = self._coerce_int(stats.get('cycles_completed'), 0)
        engine_iterations = self._coerce_int(
            stats.get('engine_iterations'),
            legacy_cycles_completed,
        )
        if engine_iterations < 0:
            violations.append(f"engine_iterations={engine_iterations} cannot be negative; resetting to 0")
            engine_iterations = 0
        cycles_completed = self._coerce_int(
            stats.get('cycles_completed'),
            self._get_closed_cycle_count(),
        )
        if 'engine_iterations' not in stats and source == 'load':
            cycles_completed = self._get_closed_cycle_count()
        if cycles_completed < 0:
            violations.append(f"cycles_completed={cycles_completed} cannot be negative; resetting to 0")
            cycles_completed = 0

        prev_cycles = None
        if previous_state is not None:
            prev_cycles = self._coerce_int(
                (previous_state.get('stats') or {}).get('engine_iterations'),
                self._coerce_int(
                    (previous_state.get('stats') or {}).get('cycles_completed'),
                    engine_iterations,
                ),
            )
        elif self._last_persisted_cycles_completed is not None:
            prev_cycles = self._last_persisted_cycles_completed
        if prev_cycles is not None and engine_iterations > prev_cycles + 1:
            violations.append(
                f"engine_iterations jumped from {prev_cycles} to {engine_iterations}; capping to {prev_cycles + 1}"
            )
            engine_iterations = prev_cycles + 1
        stats['cycles_completed'] = cycles_completed
        stats['engine_iterations'] = engine_iterations
        state['stats'] = stats

        cash = self._coerce_float(state.get('cash'), initial_capital)
        if cash < 0:
            violations.append(f"cash={cash:.2f} cannot be negative")
            if source == 'load':
                cash = 0.0
        state['cash'] = cash

        estimated_positions_value = self._estimate_state_positions_value(positions)
        portfolio_value = self._coerce_float(state.get('portfolio_value'), cash + estimated_positions_value)
        if portfolio_value <= 0:
            fallback_portfolio = cash + estimated_positions_value
            if fallback_portfolio <= 0:
                fallback_portfolio = initial_capital
            violations.append(
                f"portfolio_value={portfolio_value:.2f} must be positive; resetting to {fallback_portfolio:.2f}"
            )
            portfolio_value = fallback_portfolio
        state['portfolio_value'] = portfolio_value

        peak_value = self._coerce_float(state.get('peak_value'), max(portfolio_value, initial_capital))
        if peak_value < portfolio_value:
            violations.append(
                f"peak_value={peak_value:.2f} below portfolio_value={portfolio_value:.2f}; raising to current portfolio"
            )
            peak_value = portfolio_value

        peak_cap = initial_capital * 5
        if peak_value > peak_cap and portfolio_value <= peak_cap:
            violations.append(
                f"peak_value={peak_value:.2f} exceeds sanity cap {peak_cap:.2f}; capping"
            )
            peak_value = peak_cap

        early_peak_cap = initial_capital * 1.20
        if (
            source == 'load'
            and trading_day_counter <= 5
            and peak_value >= early_peak_cap
        ):
            violations.append(
                f"peak_value={peak_value:.2f} unreasonably high for early day {trading_day_counter}; capping to portfolio_value={portfolio_value:.2f}"
            )
            peak_value = portfolio_value

        if trading_day_counter <= 1 and not positions and abs(peak_value - initial_capital) > 0.01:
            violations.append(
                f"peak_value={peak_value:.2f} invalid for day {trading_day_counter} with no positions; resetting to initial capital"
            )
            peak_value = initial_capital
            if portfolio_value <= 0:
                portfolio_value = initial_capital
                state['portfolio_value'] = portfolio_value

        if peak_value < portfolio_value:
            violations.append(
                f"peak_value={peak_value:.2f} still below portfolio_value={portfolio_value:.2f}; aligning with portfolio"
            )
            peak_value = portfolio_value
        state['peak_value'] = peak_value

        reference_date = self._get_state_reference_date(state)
        reference_date_str = reference_date.isoformat()
        last_trading_date = state.get('last_trading_date')
        allow_missing_last_trading_date = trading_day_counter == 0 and not positions
        if last_trading_date in (None, ''):
            if not allow_missing_last_trading_date:
                if source == 'save':
                    violations.append(
                        f"last_trading_date missing; resetting to {reference_date_str}"
                    )
                    state['last_trading_date'] = reference_date_str
                elif source == 'load':
                    violations.append("last_trading_date missing; resetting to None")
                    state['last_trading_date'] = None
        else:
            try:
                parsed_last_trading_date = date.fromisoformat(str(last_trading_date))
            except (TypeError, ValueError):
                if source == 'save':
                    violations.append(
                        f"last_trading_date={last_trading_date!r} is invalid; resetting to {reference_date_str}"
                    )
                    state['last_trading_date'] = reference_date_str
                else:
                    violations.append(f"last_trading_date={last_trading_date!r} is invalid")
                    state['last_trading_date'] = None
            else:
                stale_days = (reference_date - parsed_last_trading_date).days
                if stale_days > 7:
                    if source == 'save':
                        violations.append(
                            f"last_trading_date={parsed_last_trading_date.isoformat()} is stale by {stale_days} days; resetting to {reference_date_str}"
                        )
                        state['last_trading_date'] = reference_date_str
                    else:
                        violations.append(
                            f"last_trading_date={parsed_last_trading_date.isoformat()} is stale by {stale_days} days"
                        )
                        state['last_trading_date'] = None
                else:
                    state['last_trading_date'] = parsed_last_trading_date.isoformat()

        if source == 'load':
            entry_date = state.get('last_trading_date')
            for symbol, data in positions.items():
                if symbol not in position_meta:
                    violations.append(f"position_meta missing {symbol}; creating default metadata")
                    position_meta[symbol] = self._build_position_meta_defaults(
                        symbol,
                        data if isinstance(data, dict) else {},
                        trading_day_counter,
                        entry_date,
                    )

        return state, violations

    def _validate_state_before_write(self, state):
        violations = []
        if not isinstance(state, dict):
            return ["state payload must be a dict"]

        initial_capital = self._coerce_float(
            self.config.get('PAPER_INITIAL_CASH', self.config.get('INITIAL_CAPITAL', 100_000)),
            100_000.0,
        )
        reference_date = self._get_state_reference_date(state)

        def parse_finite_number(field_name):
            value = state.get(field_name)
            try:
                number = float(value)
            except (TypeError, ValueError):
                violations.append(f"{field_name} must be numeric, got {value!r}")
                return None
            if not math.isfinite(number):
                violations.append(f"{field_name} must be finite, got {value!r}")
                return None
            return number

        cash = parse_finite_number('cash')
        if cash is not None and cash < 0:
            violations.append(f"cash must be >= 0, got {cash:.2f}")

        portfolio_value = parse_finite_number('portfolio_value')
        if portfolio_value is not None:
            if portfolio_value <= 0:
                violations.append(f"portfolio_value must be > 0, got {portfolio_value:.2f}")
            if portfolio_value >= initial_capital * 5:
                violations.append(
                    f"portfolio_value={portfolio_value:.2f} exceeds sanity bound {(initial_capital * 5):.2f}"
                )

        peak_value = parse_finite_number('peak_value')
        if peak_value is not None and portfolio_value is not None:
            if peak_value < portfolio_value:
                violations.append(
                    f"peak_value={peak_value:.2f} must be >= portfolio_value={portfolio_value:.2f}"
                )
        if peak_value is not None and peak_value > initial_capital * 3:
            violations.append(
                f"peak_value={peak_value:.2f} exceeds sanity bound {(initial_capital * 3):.2f}"
            )

        try:
            trading_day_counter = int(state.get('trading_day_counter'))
        except (TypeError, ValueError):
            trading_day_counter = None
            violations.append(
                f"trading_day_counter must be an integer, got {state.get('trading_day_counter')!r}"
            )
        if trading_day_counter is not None and not (0 <= trading_day_counter <= 100000):
            violations.append(
                f"trading_day_counter must be between 0 and 100000, got {trading_day_counter}"
            )

        positions = state.get('positions')
        if not isinstance(positions, dict):
            violations.append(f"positions must be a dict, got {type(positions).__name__}")
            positions = {}

        position_meta = state.get('position_meta')
        if not isinstance(position_meta, dict):
            violations.append(f"position_meta must be a dict, got {type(position_meta).__name__}")
            position_meta = {}

        allow_missing_last_trading_date = trading_day_counter == 0 and not positions
        last_trading_date = state.get('last_trading_date')
        if last_trading_date in (None, ''):
            if not allow_missing_last_trading_date:
                violations.append("last_trading_date must be a valid ISO date string")
        else:
            try:
                parsed_last_trading_date = date.fromisoformat(str(last_trading_date))
            except (TypeError, ValueError):
                violations.append(f"last_trading_date must be a valid ISO date string, got {last_trading_date!r}")
            else:
                stale_days = (reference_date - parsed_last_trading_date).days
                if stale_days > 7:
                    violations.append(
                        f"last_trading_date={parsed_last_trading_date.isoformat()} is stale by {stale_days} days"
                    )

        pos_keys = set(positions.keys())
        meta_keys = set(position_meta.keys())
        if pos_keys != meta_keys:
            # Strategy positions (EFA, Catalyst) may lag in position_meta — warn, don't block
            extra_in_meta = meta_keys - pos_keys
            extra_in_pos = pos_keys - meta_keys
            if extra_in_pos:
                violations.append(f"positions has symbols missing from position_meta: {extra_in_pos}")
            if extra_in_meta:
                logger.warning("position_meta has extra keys not in positions (strategy lag): %s", extra_in_meta)

        for symbol, data in positions.items():
            if not isinstance(data, dict):
                violations.append(f"positions[{symbol}] must be a dict")
                continue

            try:
                shares = float(data.get('shares'))
            except (TypeError, ValueError):
                shares = None
                violations.append(f"positions[{symbol}].shares must be numeric, got {data.get('shares')!r}")
            if shares is not None:
                if not math.isfinite(shares) or shares <= 0:
                    violations.append(f"positions[{symbol}].shares must be > 0, got {shares!r}")

            try:
                avg_cost = float(data.get('avg_cost'))
            except (TypeError, ValueError):
                avg_cost = None
                violations.append(f"positions[{symbol}].avg_cost must be numeric, got {data.get('avg_cost')!r}")
            if avg_cost is not None:
                if not math.isfinite(avg_cost) or avg_cost <= 0:
                    violations.append(f"positions[{symbol}].avg_cost must be > 0, got {avg_cost!r}")

        return violations

    def _validate_state_schema(self, state):
        violations = []
        import math

        # cash: must exist, finite float >= 0
        if 'cash' not in state:
            violations.append("missing required field 'cash'")
        else:
            cash = state['cash']
            if not isinstance(cash, (int, float)):
                violations.append(f"'cash' must be a number, got {type(cash).__name__}")
            elif not math.isfinite(cash):
                violations.append(f"'cash' must be finite, got {cash}")
            elif cash < 0:
                violations.append(f"'cash' must be >= 0, got {cash}")

        # positions: must exist and be dict
        if 'positions' not in state:
            violations.append("missing required field 'positions'")
        elif not isinstance(state['positions'], dict):
            violations.append(f"'positions' must be a dict, got {type(state['positions']).__name__}")

        # portfolio_value: must exist, finite float > 0
        if 'portfolio_value' not in state:
            violations.append("missing required field 'portfolio_value'")
        else:
            pv = state['portfolio_value']
            if not isinstance(pv, (int, float)):
                violations.append(f"'portfolio_value' must be a number, got {type(pv).__name__}")
            elif not math.isfinite(pv):
                violations.append(f"'portfolio_value' must be finite, got {pv}")
            elif pv <= 0:
                violations.append(f"'portfolio_value' must be > 0, got {pv}")

        # peak_value: must exist, finite float
        if 'peak_value' not in state:
            violations.append("missing required field 'peak_value'")
        else:
            pk = state['peak_value']
            if not isinstance(pk, (int, float)):
                violations.append(f"'peak_value' must be a number, got {type(pk).__name__}")
            elif not math.isfinite(pk):
                violations.append(f"'peak_value' must be finite, got {pk}")

        # trading_day_counter: int >= 0
        if 'trading_day_counter' in state:
            tdc = state['trading_day_counter']
            if not isinstance(tdc, int):
                violations.append(f"'trading_day_counter' must be an int, got {type(tdc).__name__}")
            elif tdc < 0:
                violations.append(f"'trading_day_counter' must be >= 0, got {tdc}")

        # regime: if present, must be str
        if 'regime' in state and not isinstance(state['regime'], str):
            violations.append(f"'regime' must be a str, got {type(state['regime']).__name__}")

        return violations

    def _snapshot_positions(self, positions=None):
        if positions is None:
            positions = self.broker.get_positions()
        snapshot = {}
        for symbol, pos in (positions or {}).items():
            snapshot[symbol] = {
                'shares': round(self._coerce_float(getattr(pos, 'shares', 0.0), 0.0), 8),
                'avg_cost': round(self._coerce_float(getattr(pos, 'avg_cost', 0.0), 0.0), 8),
            }
        return snapshot

    def _build_reconciled_position_meta(self, symbol, broker_pos, current_meta=None):
        current_meta = copy.deepcopy(current_meta or {})
        entry_date = current_meta.get('entry_date')
        if not entry_date:
            if self.last_trading_date:
                entry_date = self.last_trading_date.isoformat()
            else:
                entry_date = self._get_trading_date_str()

        defaults = self._build_position_meta_defaults(
            symbol,
            {'avg_cost': getattr(broker_pos, 'avg_cost', 0.0)},
            self.trading_day_counter,
            entry_date,
        )
        merged = defaults
        merged.update(current_meta)

        avg_cost = self._coerce_float(getattr(broker_pos, 'avg_cost', 0.0), defaults['entry_price'])
        market_price = self._coerce_float(
            getattr(broker_pos, 'market_price', None),
            avg_cost,
        )
        merged['entry_price'] = self._coerce_float(merged.get('entry_price'), avg_cost) or avg_cost
        merged['high_price'] = max(
            self._coerce_float(merged.get('high_price'), merged['entry_price']),
            market_price,
            merged['entry_price'],
        )
        merged['entry_day_index'] = self._coerce_int(
            merged.get('entry_day_index'),
            self.trading_day_counter,
        )
        merged['original_entry_day_index'] = self._coerce_int(
            merged.get('original_entry_day_index'),
            merged['entry_day_index'],
        )

        if symbol == EFA_SYMBOL:
            merged['sector'] = 'International Equity'
            merged['_efa'] = True
        elif merged.get('_catalyst'):
            merged['sector'] = merged.get('sector', defaults['sector'])
        else:
            merged['sector'] = merged.get('sector') or defaults['sector']
        merged['entry_date'] = merged.get('entry_date') or entry_date
        return merged

    def _append_reconciliation_log(self, payload):
        os.makedirs('state', exist_ok=True)
        log_path = os.path.join('state', 'reconciliation_log.jsonl')
        try:
            with open(log_path, 'a', encoding='utf-8') as log_file:
                log_file.write(json.dumps(payload, default=str) + '\n')
        except Exception as e:
            logger.error(f"Failed to write reconciliation log: {e}")

    def _get_closed_cycle_count(self):
        cycle_log_path = os.path.join('state', 'cycle_log.json')
        if not os.path.exists(cycle_log_path):
            return 0
        try:
            with open(cycle_log_path, 'r', encoding='utf-8') as cycle_file:
                cycles = json.load(cycle_file)
            if not isinstance(cycles, list):
                return 0
            return sum(
                1 for cycle in cycles
                if isinstance(cycle, dict) and cycle.get('status') == 'closed'
            )
        except Exception as e:
            logger.debug(f"Failed to read cycle log count: {e}")
            return 0

    def _reconcile_runtime_state(self):
        skip_flag = os.environ.get('SKIP_RECONCILIATION', '')
        if skip_flag.strip().lower() in ('1', 'true', 'yes', 'on'):
            logger.info("Position reconciliation skipped via SKIP_RECONCILIATION=%s", skip_flag)
            return False

        broker_positions = self.broker.get_positions()
        broker_snapshot = self._snapshot_positions(broker_positions)
        state_snapshot = copy.deepcopy(self._state_positions_snapshot or {})
        state_cash = self._coerce_float(self._state_cash_snapshot, self.broker.cash)
        broker_cash = self._coerce_float(getattr(self.broker, 'cash', state_cash), state_cash)

        mismatches = []
        for symbol in sorted(set(state_snapshot.keys()) | set(broker_snapshot.keys())):
            state_pos = state_snapshot.get(symbol)
            broker_pos = broker_snapshot.get(symbol)

            if state_pos and not broker_pos:
                mismatches.append({
                    'symbol': symbol,
                    'status': 'phantom_state_position',
                    'state_shares': state_pos.get('shares', 0.0),
                    'broker_shares': 0.0,
                })
                continue
            if broker_pos and not state_pos:
                mismatches.append({
                    'symbol': symbol,
                    'status': 'broker_only_position',
                    'state_shares': 0.0,
                    'broker_shares': broker_pos.get('shares', 0.0),
                })
                continue

            state_shares = self._coerce_float(state_pos.get('shares'), 0.0)
            broker_shares = self._coerce_float(broker_pos.get('shares'), 0.0)
            if abs(state_shares - broker_shares) > 0.01:
                mismatches.append({
                    'symbol': symbol,
                    'status': 'share_count_mismatch',
                    'state_shares': state_shares,
                    'broker_shares': broker_shares,
                })
                continue

            state_avg_cost = self._coerce_float(state_pos.get('avg_cost'), 0.0)
            broker_avg_cost = self._coerce_float(broker_pos.get('avg_cost'), 0.0)
            if abs(state_avg_cost - broker_avg_cost) > 0.01:
                mismatches.append({
                    'symbol': symbol,
                    'status': 'avg_cost_mismatch',
                    'state_avg_cost': state_avg_cost,
                    'broker_avg_cost': broker_avg_cost,
                })

        cash_mismatch = abs(state_cash - broker_cash) > 1.0
        if cash_mismatch:
            mismatches.append({
                'symbol': '__cash__',
                'status': 'cash_mismatch',
                'state_cash': round(state_cash, 2),
                'broker_cash': round(broker_cash, 2),
            })

        if not mismatches:
            self._state_positions_snapshot = broker_snapshot
            self._state_cash_snapshot = broker_cash
            return False

        event = {
            'timestamp': datetime.now().isoformat(),
            'trading_day_counter': self.trading_day_counter,
            'action': 'trust_broker_and_resave_state',
            'mismatch_count': len(mismatches),
            'mismatches': mismatches,
            'state_cash': round(state_cash, 2),
            'broker_cash': round(broker_cash, 2),
        }
        logger.critical(f"POSITION RECONCILIATION CRITICAL: {event}")

        preserved_meta = copy.deepcopy(self.position_meta)
        rebuilt_meta = {}
        for symbol, broker_pos in broker_positions.items():
            rebuilt_meta[symbol] = self._build_reconciled_position_meta(
                symbol,
                broker_pos,
                preserved_meta.get(symbol),
            )
        self.position_meta = rebuilt_meta

        self.rattle_positions = [
            {
                **pos,
                'shares': broker_positions[pos['symbol']].shares,
                'entry_price': pos.get('entry_price') or broker_positions[pos['symbol']].avg_cost,
            }
            for pos in self.rattle_positions
            if pos.get('symbol') in broker_positions
        ]
        self.catalyst_positions = [
            {
                **pos,
                'shares': broker_positions[pos['symbol']].shares,
                'entry_price': pos.get('entry_price') or broker_positions[pos['symbol']].avg_cost,
            }
            for pos in self.catalyst_positions
            if pos.get('symbol') in broker_positions
        ]
        self._sync_efa_runtime_state(reason='reconciliation')

        self._state_positions_snapshot = broker_snapshot
        self._state_cash_snapshot = broker_cash
        self._append_reconciliation_log(event)
        self.save_state()
        self._last_state_save = datetime.now()
        return True

    def _append_audit_log(self, event_type, details):
        try:
            os.makedirs('state', exist_ok=True)
            audit_path = 'state/audit_log.jsonl'
            portfolio = self.broker.get_portfolio()
            entry = json.dumps({
                'timestamp': datetime.now().isoformat(),
                'event_type': event_type,
                'details': details,
                'portfolio_value': portfolio.total_value,
                'num_positions': len(self.broker.positions),
            }, default=str)
            with open(audit_path, 'a') as f:
                f.write(entry + '\n')
            # Cap at 10,000 lines
            try:
                with open(audit_path, 'r') as f:
                    lines = f.readlines()
                if len(lines) > 10_000:
                    with open(audit_path, 'w') as f:
                        f.writelines(lines[-10_000:])
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"Audit log write failed: {e}")

    def save_state(self):
        """Save full system state to JSON"""
        with self._state_save_lock:
            portfolio = self.broker.get_portfolio()
            closed_cycles = self._get_closed_cycle_count()

            # Audit trail: detect position changes
            current_positions = set(self.broker.positions.keys())
            added = sorted(current_positions - self._last_audit_positions)
            removed = sorted(self._last_audit_positions - current_positions)
            if added or removed:
                self._append_audit_log('position_change', {'added': added, 'removed': removed})
            self._last_audit_positions = set(current_positions)

            state = {
                'version': '8.4',
                'timestamp': datetime.now().isoformat(),

                # Portfolio
                'cash': self.broker.cash,
                'peak_value': self.peak_value,
                'portfolio_value': portfolio.total_value,

                # Drawdown / Crash state
                'crash_cooldown': self.crash_cooldown,
                'portfolio_values_history': self.portfolio_values_history[-30:],  # Keep last 30 days

                # Regime
                'current_regime_score': self.current_regime_score,

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
                '_universe_source': getattr(self, '_universe_source', ''),

                # Intraday flags (prevents duplicate trades after mid-day restart)
                '_daily_open_done': getattr(self, '_daily_open_done', False),
                '_preclose_entries_done': getattr(self, '_preclose_entries_done', False),

                # Overlay diagnostics
                'overlay': {
                    'available': self._overlay_available,
                    'capital_scalar': self._overlay_result.get('capital_scalar', 1.0) if self._overlay_result else 1.0,
                    'per_overlay': self._overlay_result.get('per_overlay_scalars', {}) if self._overlay_result else {},
                    'position_floor': self._overlay_result.get('position_floor') if self._overlay_result else None,
                    'diagnostics': self._overlay_result.get('diagnostics', {}) if self._overlay_result else {},
                },

                # HYDRA state
                'hydra': {
                    'available': self._hydra_available,
                    'rattle_positions': self.rattle_positions,
                    'rattle_regime': self.rattle_regime,
                    'vix_current': self._vix_current,
                    'efa_position': None,  # deprecated: EFA now tracked in broker.positions
                    'catalyst_positions': self.catalyst_positions,
                    'catalyst_day_counter': self._catalyst_day_counter,
                    'capital_manager': self.hydra_capital.to_dict() if self.hydra_capital else None,
                },

                # Pre-rotation snapshot (survives restart between execute_new_day and _update_cycle_log)
                '_pre_rotation_positions_data': getattr(self, '_pre_rotation_positions_data', {}),
                '_pre_rotation_cash': getattr(self, '_pre_rotation_cash', None),
                '_pre_rotation_value': getattr(self, '_pre_rotation_value', None),

                # Stats
                'stats': {
                    'cycles_completed': closed_cycles,
                    'engine_iterations': self._cycles_completed,
                    'uptime_minutes': (datetime.now() - self._start_time).total_seconds() / 60
                },

                # ML fail-safe observability
                'ml_error_counts': dict(_ml_error_counts),
            }
            previous_state = {
                'trading_day_counter': self._last_persisted_trading_day_counter,
                'stats': {'engine_iterations': self._last_persisted_cycles_completed},
            }
            state, violations = self._validate_state(
                state,
                source='save',
                previous_state=previous_state if self._last_persisted_trading_day_counter is not None
                or self._last_persisted_cycles_completed is not None else None,
            )
            blocking_violations = self._validate_state_before_write(state)
            if blocking_violations:
                logger.error(
                    "STATE SAVE SKIPPED due to validation blockers: %s",
                    "; ".join(violations + blocking_violations),
                )
                return
            if violations:
                logger.warning(
                    "State repaired before save: %s",
                    "; ".join(violations),
                )
                self.peak_value = state['peak_value']
                self.trading_day_counter = state['trading_day_counter']
                self.position_meta = copy.deepcopy(state['position_meta'])
                if state.get('cash', 0) >= 0:
                    try:
                        self.broker.cash = state['cash']
                    except Exception:
                        pass

            os.makedirs('state', exist_ok=True)
            filename = f'state/compass_state_{datetime.now().strftime("%Y%m%d")}.json'
            latest = 'state/compass_state_latest.json'

            # Atomic write: temp file + rename (prevents corruption on crash)
            write_results = {}
            for target in [filename, latest]:
                written = False
                for attempt in range(2):
                    try:
                        fd, tmp_path = tempfile.mkstemp(dir='state', suffix='.json.tmp')
                        with os.fdopen(fd, 'w') as fp:
                            json.dump(state, fp, indent=2, default=str)
                        os.replace(tmp_path, target)
                        written = True
                        break
                    except Exception as write_err:
                        logger.error(f"Atomic write failed for {target} (attempt {attempt+1}): {write_err}")
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
                if not written:
                    logger.error(f"STATE SAVE FAILED for {target} after 2 attempts")
                write_results[target] = written

            if any(write_results.values()):
                self._last_persisted_cycles_completed = self._coerce_int(
                    (state.get('stats') or {}).get('engine_iterations'),
                    self._cycles_completed,
                )
                self._last_persisted_trading_day_counter = self._coerce_int(
                    state.get('trading_day_counter'),
                    self.trading_day_counter,
                )
                self._state_positions_snapshot = copy.deepcopy(state.get('positions', {}))
                self._state_cash_snapshot = self._coerce_float(state.get('cash'), self.broker.cash)
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
            if not isinstance(state, dict):
                logger.warning(f"State file {filepath} did not contain a JSON object")
                return None
            return state
        except (json.JSONDecodeError, IOError, OSError) as e:
            logger.warning(f"Failed to load {filepath}: {e}")
            return None

    def load_state(self):
        """Load previous state with fallback chain: latest -> dated -> HALT."""

        # Build candidate list: latest first, then dated files newest-first
        candidates = []
        latest = 'state/compass_state_latest.json'
        if os.path.exists(latest):
            candidates.append(latest)
        dated_files = sorted(
            [f for f in glob.glob('state/compass_state_2*.json') if 'latest' not in f],
            key=os.path.getmtime, reverse=True
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

        self._recovery_gap_baseline = state.get('last_trading_date')

        pre_repair_violations = self._validate_state_before_write(state)
        for violation in pre_repair_violations:
            logger.warning(f"State validation issue detected on load: {violation}")

        previous_state = None
        if len(candidates) > 1 and loaded_from == candidates[0]:
            for fallback_candidate in candidates[1:]:
                previous_state = self._try_load_json(fallback_candidate)
                if previous_state is not None:
                    break

        state, violations = self._validate_state(
            state,
            source='load',
            previous_state=previous_state,
        )
        for violation in violations:
            logger.warning(f"State validation repaired on load: {violation}")

        post_repair_violations = self._validate_state_before_write(state)
        for violation in post_repair_violations:
            logger.warning(f"State validation warning after load repair: {violation}")

        schema_violations = self._validate_state_schema(state)
        for sv in schema_violations:
            logger.warning(f"State schema violation on load: {sv}")

        # Restore portfolio state
        self.peak_value = state.get('peak_value', self.config['PAPER_INITIAL_CASH'])

        # Restore drawdown / crash state
        self.crash_cooldown = state.get('crash_cooldown', 0)
        self.portfolio_values_history = state.get('portfolio_values_history', [])

        # Restore regime
        self.current_regime_score = state.get('current_regime_score', 0.5)

        # Restore counters
        self.trading_day_counter = state.get('trading_day_counter', 0)
        ltd = state.get('last_trading_date')
        self.last_trading_date = date.fromisoformat(ltd) if ltd else None

        # Restore positions — PaperBroker restores from JSON; IBKR uses broker as truth
        is_paper = isinstance(self.broker, PaperBroker)
        if is_paper:
            self.broker.cash = state.get('cash', self.config['PAPER_INITIAL_CASH'])
            for symbol, data in state.get('positions', {}).items():
                self.broker.positions[symbol] = Position(
                    symbol=symbol,
                    shares=data['shares'],
                    avg_cost=data['avg_cost']
                )
        else:
            # IBKR mode: broker has real positions, just log comparison
            broker_cash = self.broker.cash
            json_cash = state.get('cash', 0)
            if abs(broker_cash - json_cash) > 100:
                logger.warning(f"Cash mismatch: broker=${broker_cash:,.0f} vs state=${json_cash:,.0f}")

        # Restore position metadata (validated and cleaned)
        raw_meta = state.get('position_meta', {})
        active_positions = self.broker.get_positions() if not is_paper else self.broker.positions
        self.position_meta = self._validate_position_meta(raw_meta, active_positions)

        # Restore universe
        self.current_universe = state.get('current_universe', [])
        self.universe_year = state.get('universe_year')
        self._universe_source = state.get('_universe_source', '')

        # Restore intraday flags (prevents duplicate trades after mid-day restart)
        self._daily_open_done = state.get('_daily_open_done', False)
        self._preclose_entries_done = state.get('_preclose_entries_done', False)

        # Restore HYDRA state
        hydra_state = state.get('hydra', {})
        if hydra_state and self._hydra_available:
            self.rattle_positions = hydra_state.get('rattle_positions', [])
            self.rattle_regime = hydra_state.get('rattle_regime', 'RISK_ON')
            self._vix_current = hydra_state.get('vix_current')
            self.catalyst_positions = hydra_state.get('catalyst_positions', [])
            self._catalyst_day_counter = hydra_state.get('catalyst_day_counter', 0)

            # Reconcile: if broker has positions marked _catalyst in position_meta
            # but catalyst_positions list is empty, restore them
            raw_meta = state.get('position_meta', {})
            cat_syms_in_list = {cp['symbol'] for cp in self.catalyst_positions}
            for sym, meta in raw_meta.items():
                if meta.get('_catalyst') and sym not in cat_syms_in_list:
                    pos_data = state.get('positions', {}).get(sym)
                    if pos_data:
                        self.catalyst_positions.append({
                            'symbol': sym,
                            'shares': pos_data['shares'],
                            'entry_price': meta.get('entry_price', pos_data['avg_cost']),
                            'sub_strategy': 'trend',
                        })
                        logger.warning(f"Reconciled orphan catalyst position: {sym} "
                                      f"({pos_data['shares']}sh @ ${meta.get('entry_price', 0):.2f})")
            if self.catalyst_positions and self._catalyst_day_counter == 0:
                self._catalyst_day_counter = max(1, self.trading_day_counter)

            cap_state = hydra_state.get('capital_manager')
            if cap_state:
                self.hydra_capital = HydraCapitalManager.from_dict(cap_state)
                efa_pos = self.broker.get_positions().get(EFA_SYMBOL)
                efa_str = f" | EFA={efa_pos.shares}sh" if efa_pos and efa_pos.shares > 0 else ""
                cat_str = f" | Cat_pos={len(self.catalyst_positions)}" if self.catalyst_positions else ""
                logger.info(f"  HYDRA restored: R_pos={len(self.rattle_positions)}{cat_str}{efa_str} | "
                           f"C_acct=${self.hydra_capital.compass_account:,.0f} | "
                           f"R_acct=${self.hydra_capital.rattle_account:,.0f} | "
                           f"Cat_acct=${self.hydra_capital.catalyst_account:,.0f}")
                self._sync_efa_runtime_state(reason='load_state')

        # Restore pre-rotation snapshot (survives restart between rotation and cycle log update)
        saved_pre_rot = state.get('_pre_rotation_positions_data')
        if saved_pre_rot:
            self._pre_rotation_positions_data = saved_pre_rot
            self._pre_rotation_cash = state.get('_pre_rotation_cash', self.broker.cash)
            self._pre_rotation_value = state.get('_pre_rotation_value')

        regime_str = f"score={self.current_regime_score:.2f}"

        logger.info(f"State loaded from {loaded_from}")
        logger.info(f"  Cash: ${self.broker.cash:,.0f} | Peak: ${self.peak_value:,.0f}")
        logger.info(f"  Positions: {len(self.broker.positions)} (COMPASS) + {len(self.rattle_positions)} (Rattlesnake) | Day: {self.trading_day_counter}")
        logger.info(f"  Regime: {regime_str} | Crash cooldown: {self.crash_cooldown}")
        if loaded_from != latest:
            logger.warning(f"  Loaded from FALLBACK file (not latest): {loaded_from}")

        self._state_positions_snapshot = copy.deepcopy(state.get('positions', {}))
        self._state_cash_snapshot = self._coerce_float(
            state.get('cash'),
            getattr(self.broker, 'cash', self.config['PAPER_INITIAL_CASH']),
        )
        self._last_persisted_cycles_completed = self._coerce_int(
            (state.get('stats') or {}).get('engine_iterations'),
            self._cycles_completed,
        )
        self._last_persisted_trading_day_counter = self._coerce_int(
            state.get('trading_day_counter'),
            self.trading_day_counter,
        )

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

        # Cleanup old corrupted state backups
        try:
            self._cleanup_old_corrupted_backups()
        except Exception as e:
            logger.warning(f"Corrupted backup cleanup failed (non-fatal): {e}")

    # ------------------------------------------------------------------
    # Status logging
    # ------------------------------------------------------------------

    def log_status(self, prices: Dict[str, float]):
        """Log current status"""
        portfolio = self.broker.get_portfolio()
        drawdown = (portfolio.total_value - self.peak_value) / self.peak_value \
            if self.peak_value > 0 else 0
        leverage = self.get_current_leverage()
        regime_str = f"score={self.current_regime_score:.2f}"

        positions = self.broker.get_positions()
        pos_parts = []
        for s, m in self.position_meta.items():
            if s not in positions:
                continue
            ret = (prices.get(s, m.get('entry_price', 0)) - m.get('entry_price', 0)) / m.get('entry_price', 1)
            edv = m.get('entry_daily_vol')
            stop = compute_adaptive_stop(edv, self.config) if edv else self.config['POSITION_STOP_LOSS']
            pos_parts.append(f"{s}({ret:.1%}|stop={stop:.0%})")
        pos_str = ", ".join([
            p for p in pos_parts
        ])

        hydra_str = ""
        if self._hydra_available:
            r_pos_parts = []
            for rp in self.rattle_positions:
                s = rp['symbol']
                rp_ret = (prices.get(s, rp['entry_price']) - rp['entry_price']) / rp['entry_price']
                r_pos_parts.append(f"{s}({rp_ret:.1%}|d{rp.get('days_held', 0)})")
            hydra_str = f" | R:{len(self.rattle_positions)} [{','.join(r_pos_parts)}]"
            efa_pos = self.broker.get_positions().get(EFA_SYMBOL)
            if efa_pos and efa_pos.shares > 0:
                hydra_str += f" | EFA:{efa_pos.shares}sh"

        logger.info(f"STATUS: ${portfolio.total_value:,.0f} | DD:{drawdown:.1%} | "
                     f"{regime_str} | Lev:{leverage:.2f}x | "
                     f"C:{len(positions)}/{self.get_max_positions()}{hydra_str} | "
                     f"[{pos_str}]")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_once(self) -> bool:
        """Execute one trading cycle"""
        self._cycles_completed += 1

        try:
            # New trading day setup
            if self.is_new_trading_day():
                if self.is_market_open() or self.get_et_now().weekday() < 5:
                    # Run daily_open() even if market just closed (late deploy),
                    # but NOT on weekends to avoid phantom trading day increments
                    self._recover_missed_days()
                    self.daily_open()
                    self.save_state()
                    try:
                        self._reconcile_runtime_state()
                    except Exception as reconcile_err:
                        logger.error(f"Automated reconciliation failed: {reconcile_err}", exc_info=True)
            elif self._last_regime_refresh is None or \
                    (datetime.now() - self._last_regime_refresh).total_seconds() > 14400:
                # Periodic regime refresh (every 4h) — catches stale scores after
                # mid-day restarts where daily_open() already ran for today
                try:
                    self.refresh_daily_data()
                    self.update_regime()
                    self.save_state()
                    logger.info(f"Periodic regime refresh: score={self.current_regime_score:.4f}")
                except Exception as e:
                    logger.warning(f"Periodic regime refresh failed: {e}")

            if not self.is_market_open():
                return False

            # Get current prices (async fetch + batch validation)
            symbols_needed = set(self.current_universe) | set(self.position_meta.keys())
            # HYDRA: include Rattlesnake held symbols + universe for candidate scanning
            if self._hydra_available:
                symbols_needed |= {p['symbol'] for p in self.rattle_positions}
                symbols_needed |= set(R_UNIVERSE)
                symbols_needed.add(EFA_SYMBOL)
                if _catalyst_available:
                    symbols_needed |= set(CATALYST_TREND_ASSETS)
            symbols_needed = list(symbols_needed)
            raw_prices = self.data_feed.get_prices(symbols_needed)
            prices = self.validator.validate_batch(raw_prices)

            if not prices:
                logger.warning("No valid prices obtained after validation")
                self._consecutive_errors += 1
                if self._consecutive_errors >= self._max_consecutive_errors:
                    logger.critical(f"Too many consecutive errors ({self._consecutive_errors}). Stopping.")
                    if self.notifier:
                        self.notifier.send_error_alert("No valid prices obtained after validation", "")
                    raise RuntimeError("Too many consecutive errors")
                return False

            self._consecutive_errors = 0
            cache_age_seconds = self._get_price_cache_age_seconds()
            if self._stale_price_guard_triggered(cache_age_seconds):
                return False

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
                # Catch-up: if yesterday's pre-close was missed (Render cold start),
                # run entries using yesterday's close prices (MOC) from _hist_cache
                if self._missed_preclose:
                    moc_prices = {}
                    for sym, df in self._hist_cache.items():
                        if df is not None and len(df) > 0:
                            moc_prices[sym] = float(df['Close'].iloc[-1])
                    if moc_prices:
                        logger.warning("[CATCH-UP] Yesterday's pre-close was missed — "
                                       f"running entries at yesterday's MOC prices ({len(moc_prices)} symbols)")
                        self.execute_preclose_entries(moc_prices)
                    else:
                        logger.warning("[CATCH-UP] No historical data available for MOC catch-up, skipping")
                    self._missed_preclose = False
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
                    self.check_position_exits(prices)
                    # HYDRA: also check Rattlesnake exits intraday
                    if self._hydra_available and self.rattle_positions:
                        self._check_rattlesnake_exits(prices)
                    self._last_stop_check = now

            # Check for stale orders (order timeout)
            try:
                stale = self.broker.check_stale_orders()
                if stale:
                    logger.warning(f"Cancelled {len(stale)} stale orders: {[o.symbol for o in stale]}")
            except Exception as e:
                logger.warning(f"check_stale_orders failed: {e}")

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
        logger.info("Starting COMPASS v8.4 live trading loop...")
        self._run_startup_self_test_once()

        # Register graceful shutdown handlers (only works in main thread)
        def _graceful_shutdown(signum, frame):
            logger.info(f"Received signal {signum}, saving state and shutting down...")
            self._shutdown_requested = True
        try:
            signal.signal(signal.SIGTERM, _graceful_shutdown)
            signal.signal(signal.SIGINT, _graceful_shutdown)
        except ValueError:
            # signal.signal() only works in main thread — skip on cloud (daemon thread)
            logger.info("Signal handlers skipped (not main thread)")

        # Kill switch check
        kill_file = 'STOP_TRADING'

        try:
            while True:
                # Graceful shutdown
                if self._shutdown_requested:
                    logger.info("Graceful shutdown requested, exiting loop...")
                    break

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
                drawdown, self.trades_today, self.current_regime_score >= 0.50,
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
            # Merge chassis/broker keys only (never override algorithm params)
            safe_keys = {
                'BROKER_TYPE', 'IBKR_HOST', 'IBKR_PORT', 'IBKR_CLIENT_ID',
                'IBKR_MOCK', 'PRICE_UPDATE_INTERVAL', 'PAPER_INITIAL_CASH',
                'LOG_LEVEL', 'STATE_DIR',
                'PRICE_STALE_WARN_SECONDS', 'PRICE_STALE_SKIP_SECONDS',
            }
            for k, v in ext_config.items():
                if k in safe_keys:
                    config[k] = v
                    logger.info(f"  Config override: {k}={v}")
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
