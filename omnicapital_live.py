"""
OmniCapital HYDRA - Live Trading System (COMPASS + Rattlesnake)
================================================================
Multi-strategy system combining COMPASS v8.4 (momentum) with
Rattlesnake v1.0 (mean-reversion) and cash recycling.

COMPASS: Risk-adjusted cross-sectional momentum (90d return / 63d vol)
Rattlesnake: RSI<25 dip-buying on S&P 100 (uptrend filter)
HYDRA: Cash recycling — idle Rattlesnake cash flows to COMPASS (cap 75%)

Results (backtest 2000-2026):
  CAGR 13.28% | MaxDD -23.49% | Sharpe 1.04
  vs COMPASS solo: +1.01% CAGR, +8.61% MaxDD, +0.19 Sharpe
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

# ML Learning System (non-blocking, optional)
try:
    from compass_ml_learning import COMPASSMLOrchestrator
    _ml_available = True
except ImportError:
    _ml_available = False

# HYDRA: Rattlesnake + Cash Recycling (non-blocking, optional)
try:
    from rattlesnake_signals import (
        R_UNIVERSE, R_MAX_POSITIONS, R_POSITION_SIZE, R_MAX_POS_RISK_OFF,
        find_rattlesnake_candidates, check_rattlesnake_exit,
        check_rattlesnake_regime, compute_rattlesnake_exposure,
    )
    from hydra_capital import HydraCapitalManager
    _hydra_available = True
except ImportError:
    _hydra_available = False

# Overlay system (v3: BSO + M2 + FOMC + FedEmergency + CreditFilter)
try:
    from compass_fred_data import download_all_overlay_data
    from compass_overlays import (
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

# v8.4: Sector map for concentration limits
SECTOR_MAP = {
    # Technology
    'AAPL': 'Technology', 'MSFT': 'Technology', 'NVDA': 'Technology', 'GOOGL': 'Technology',
    'META': 'Technology', 'AVGO': 'Technology', 'ADBE': 'Technology', 'CRM': 'Technology',
    'AMD': 'Technology', 'INTC': 'Technology', 'CSCO': 'Technology', 'IBM': 'Technology',
    'TXN': 'Technology', 'QCOM': 'Technology', 'ORCL': 'Technology', 'ACN': 'Technology',
    'NOW': 'Technology', 'INTU': 'Technology', 'AMAT': 'Technology', 'MU': 'Technology',
    'LRCX': 'Technology', 'SNPS': 'Technology', 'CDNS': 'Technology', 'KLAC': 'Technology',
    'MRVL': 'Technology',
    # Financials
    'BRK-B': 'Financials', 'JPM': 'Financials', 'V': 'Financials', 'MA': 'Financials',
    'BAC': 'Financials', 'WFC': 'Financials', 'GS': 'Financials', 'MS': 'Financials',
    'AXP': 'Financials', 'BLK': 'Financials', 'SCHW': 'Financials', 'C': 'Financials',
    'USB': 'Financials', 'PNC': 'Financials', 'TFC': 'Financials', 'CB': 'Financials',
    'MMC': 'Financials', 'AIG': 'Financials',
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
    # Energy
    'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'SLB': 'Energy',
    'EOG': 'Energy', 'OXY': 'Energy', 'MPC': 'Energy', 'PSX': 'Energy', 'VLO': 'Energy',
    # Industrials
    'GE': 'Industrials', 'CAT': 'Industrials', 'BA': 'Industrials', 'HON': 'Industrials',
    'UNP': 'Industrials', 'RTX': 'Industrials', 'LMT': 'Industrials', 'DE': 'Industrials',
    'UPS': 'Industrials', 'FDX': 'Industrials', 'MMM': 'Industrials', 'GD': 'Industrials',
    'NOC': 'Industrials', 'EMR': 'Industrials',
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
# COMPASS v8.3 SIGNAL FUNCTIONS
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
                    scores[symbol] = raw_score / ann_vol
                else:
                    scores[symbol] = raw_score
            else:
                scores[symbol] = raw_score
        else:
            scores[symbol] = raw_score

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
    from collections import defaultdict
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
    """COMPASS v8.3 Live Trading System"""

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

        # ---- COMPASS v8.3 State ----
        # Portfolio
        self.peak_value = float(config['PAPER_INITIAL_CASH'])
        self.crash_cooldown = 0
        self.portfolio_values_history = []  # For crash velocity tracking

        # Regime (continuous sigmoid score)
        self.current_regime_score = 0.5

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

        # HYDRA: Rattlesnake + Cash Recycling
        self._hydra_available = _hydra_available
        self.rattle_positions: List[dict] = []  # {symbol, entry_price, entry_date, shares, days_held}
        self.rattle_regime = 'RISK_ON'
        self._vix_current: Optional[float] = None
        self.hydra_capital = None
        if _hydra_available:
            try:
                self.hydra_capital = HydraCapitalManager(config['PAPER_INITIAL_CASH'])
                logger.info("HYDRA multi-strategy: ACTIVE (COMPASS + Rattlesnake + Cash Recycling)")
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
        logger.info(f"Universe: {len(BROAD_POOL)} broad pool -> top {config['TOP_N']}")
        logger.info(f"Execution: Pre-close signal @ {config['PRECLOSE_SIGNAL_TIME'].strftime('%H:%M')} ET "
                     f"-> same-day MOC (deadline {config['MOC_DEADLINE'].strftime('%H:%M')} ET)")
        logger.info(f"Chassis: async fetch | order timeout {config.get('ORDER_TIMEOUT_SECONDS', 300)}s | "
                     f"fill breaker {config.get('MAX_FILL_DEVIATION', 0.02):.0%} | data validation")
        if self._overlay_available:
            logger.info(f"Overlays: BSO + M2 + FOMC + FedEmergency + CreditFilter (damping={self._overlay_damping})")
        else:
            logger.info("Overlays: DISABLED (FRED data unavailable)")

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

            logger.info(f"Historical data refreshed: {len(self._hist_cache)} stocks (COMPASS + Rattlesnake)")

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
        """Update market regime using continuous sigmoid score"""
        if self._spy_hist is None or len(self._spy_hist) < 252:
            return
        old_score = self.current_regime_score
        self.current_regime_score = compute_live_regime_score(self._spy_hist)
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

        # Crash velocity check
        if self.crash_cooldown > 0:
            dd_lev = min(self.config['CRASH_LEVERAGE'], dd_lev)
            self.crash_cooldown -= 1
        elif len(self.portfolio_values_history) >= 5:
            current_val = pv
            val_5d = self.portfolio_values_history[-5]
            if val_5d > 0:
                ret_5d = (current_val / val_5d) - 1.0
                if ret_5d <= self.config['CRASH_VEL_5D']:
                    dd_lev = min(self.config['CRASH_LEVERAGE'], dd_lev)
                    self.crash_cooldown = self.config['CRASH_COOLDOWN'] - 1
            if self.crash_cooldown == 0 and len(self.portfolio_values_history) >= 10:
                val_10d = self.portfolio_values_history[-10]
                if val_10d > 0:
                    ret_10d = (current_val / val_10d) - 1.0
                    if ret_10d <= self.config['CRASH_VEL_10D']:
                        dd_lev = min(self.config['CRASH_LEVERAGE'], dd_lev)
                        self.crash_cooldown = self.config['CRASH_COOLDOWN'] - 1

        # Vol targeting
        vol_lev = 1.0
        if self._spy_hist is not None:
            vol_lev = compute_dynamic_leverage(
                self._spy_hist, self.config['TARGET_VOL'],
                self.config['VOL_LOOKBACK'],
                self.config['LEV_FLOOR'], self.config['LEVERAGE_MAX']
            )

        return max(min(dd_lev, vol_lev), self.config['LEV_FLOOR'])

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

        for symbol in list(positions.keys()):
            price = prices.get(symbol)
            if not price:
                continue

            meta = self.position_meta.get(symbol)
            if not meta:
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
            pos_return = (price - meta['entry_price']) / meta['entry_price']
            entry_daily_vol = meta.get('entry_daily_vol')
            if entry_daily_vol is not None:
                adaptive_stop = compute_adaptive_stop(entry_daily_vol, self.config)
            else:
                adaptive_stop = self.config['POSITION_STOP_LOSS']  # fallback for pre-v8.4 positions
            if pos_return <= adaptive_stop:
                exit_reason = 'position_stop'

            # 3. Trailing stop (v8.4: vol-scaled)
            if price > meta['high_price']:
                meta['high_price'] = price
            if meta['high_price'] > meta['entry_price'] * (1 + self.config['TRAILING_ACTIVATION']):
                baseline = self.config['TRAILING_VOL_BASELINE']
                entry_vol = meta.get('entry_vol', baseline)
                vol_ratio = entry_vol / baseline
                scaled_trailing = self.config['TRAILING_STOP_PCT'] * vol_ratio
                trailing_level = meta['high_price'] * (1 - scaled_trailing)
                if price <= trailing_level:
                    exit_reason = 'trailing_stop'

            # 4. Universe rotation
            if symbol not in self.current_universe:
                exit_reason = 'universe_rotation'

            # 5. Regime reduce (excess COMPASS positions)
            compass_count = sum(1 for s in positions if s in self.position_meta)
            if exit_reason is None and compass_count > max_positions:
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
                                entry_momentum_score=self._current_scores.get(symbol, 0.0),
                                entry_momentum_rank=0.5,
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
                            logger.warning(f"ML exit logging failed for {symbol}: {e}")

                    self.position_meta.pop(symbol, None)

                    self.trades_today.append({
                        'symbol': symbol, 'action': 'SELL',
                        'exit_reason': exit_reason, 'pnl': pnl, 'return': ret,
                        'price': result.filled_price, 'is_bps': result.is_bps
                    })

                    # Track stop exits for cycle log update when replacement enters
                    if exit_reason in ('position_stop', 'trailing_stop'):
                        if not hasattr(self, '_pending_stop_exits'):
                            self._pending_stop_exits = []
                        self._pending_stop_exits.append({
                            'symbol': symbol, 'reason': exit_reason, 'return': ret
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
        positions = self.broker.get_positions()
        # HYDRA: Only count COMPASS positions (those with position_meta)
        compass_positions = {s: p for s, p in positions.items() if s in self.position_meta}
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
        ranked = sorted(available.items(), key=lambda x: x[1], reverse=True)
        sector_filtered = filter_by_sector_concentration(
            ranked, positions, self.config['MAX_PER_SECTOR']
        )
        selected = sector_filtered[:needed]

        # ML: log skipped candidates (top-10 not selected)
        if self.ml:
            try:
                selected_set = set(selected)
                drawdown = (portfolio.total_value - self.peak_value) / self.peak_value if self.peak_value > 0 else 0
                sector_filtered_set = set(sector_filtered)
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
                    )
            except Exception as e:
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

        effective_capital = compass_cash * current_leverage * 0.95 * damped_scalar

        for symbol in selected:
            price = prices.get(symbol)
            if not price or price <= 0:
                continue

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

                self.position_meta[symbol] = {
                    'entry_price': result.filled_price,
                    'entry_date': self.get_et_now().date().isoformat(),
                    'entry_day_index': self.trading_day_counter,
                    'original_entry_day_index': self.trading_day_counter,
                    'high_price': result.filled_price,
                    'entry_vol': entry_vol,              # v8.4: annualized vol
                    'entry_daily_vol': entry_daily_vol,  # v8.4: daily vol for stop calc
                    'sector': SECTOR_MAP.get(symbol, 'Unknown'),  # v8.4: sector tracking
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
                        )
                    except Exception as e:
                        logger.warning(f"ML entry logging failed for {symbol}: {e}")

                # Cycle log: link this entry as replacement for a pending stop exit
                if hasattr(self, '_pending_stop_exits') and self._pending_stop_exits:
                    stop_exit = self._pending_stop_exits.pop(0)
                    try:
                        self._update_cycle_log_stop(
                            stopped_symbol=stop_exit['symbol'],
                            replacement_symbol=symbol,
                            exit_reason=stop_exit['reason'],
                            stop_return=stop_exit['return'],
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
            logger.info(f"Rattlesnake entries blocked: VIX panic")
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
            return

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
                    'entry_date': self.get_et_now().date().isoformat(),
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
        # Deep copy position data for close-price reconstruction in _update_cycle_log
        self._pre_rotation_positions_data = {
            sym: {'shares': pos.shares, 'avg_cost': pos.avg_cost}
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

    def execute_preclose_entries(self, prices: Dict[str, float]):
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

        # 2. Open new positions using momentum scores from historical data
        # The _hist_cache contains data up to yesterday's close (refreshed at open)
        # This is exactly the Close[T-1] signal validated in the backtest
        self.open_new_positions(prices)

        # HYDRA: Rattlesnake entries (after COMPASS, uses separate budget)
        if self._hydra_available:
            self._open_rattlesnake_positions(prices)

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

                # Update broker's avg_cost too
                if symbol in self.broker.positions:
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
            for sym, pos in positions_dict.items():
                shares = pos.get('shares', 0)
                try:
                    if len(symbols) == 1:
                        close = float(data['Close'].iloc[-1])
                    else:
                        close = float(data['Close'][sym].iloc[-1])
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
            if len(gspc) > 0:
                return float(gspc['Close'].iloc[-1].iloc[0])
        except Exception as e:
            logger.warning(f"Could not fetch S&P 500 close: {e}")
        return None

    def _update_cycle_log(self, prices: Dict[str, float]):
        """Close the active cycle and open a new one in cycle_log.json.

        Called automatically after a rotation (hold_expired sells + new buys).
        Uses close prices for all values: portfolio end = cash + sum(shares * close),
        SPY benchmark = SPY close. Cycle N+1 start = Cycle N end (no gaps).
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
                cycle['compass_return'] = round(
                    (close_portfolio_value - cycle['portfolio_start'])
                    / cycle['portfolio_start'] * 100, 2)
                if cycle.get('compass_return') is not None and cycle.get('spy_return') is not None:
                    cycle['alpha'] = round(cycle['compass_return'] - cycle['spy_return'], 2)

                status_str = 'WIN' if cycle.get('alpha', 0) >= 0 else 'LOSS'
                logger.info(f"CYCLE #{cycle['cycle']} CLOSED: "
                           f"COMPASS {cycle['compass_return']:+.2f}% | "
                           f"S&P {cycle.get('spy_return', 0):+.2f}% | "
                           f"Alpha {cycle.get('alpha', 0):+.2f}pp | {status_str}")
                break

        # New cycle start = old cycle end (close-to-close, no gaps)
        new_start_value = close_portfolio_value
        new_spy_start = spy_close

        # Open new cycle
        new_positions = list(self.broker.positions.keys())
        next_cycle = max((c.get('cycle', 0) for c in cycles), default=0) + 1

        cycles.append({
            'cycle': next_cycle,
            'start_date': today,
            'end_date': None,
            'status': 'active',
            'portfolio_start': round(new_start_value, 2),
            'portfolio_end': None,
            'spy_start': round(new_spy_start, 2) if new_spy_start else None,
            'spy_end': None,
            'positions': new_positions,
            'positions_current': list(new_positions),
            'compass_return': None,
            'spy_return': None,
            'alpha': None,
            'stop_events': [],
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
        spy_price = None
        try:
            spy = yf.download('SPY', period='5d', progress=False)
            if len(spy) > 0:
                spy_price = float(spy['Close'].iloc[-1].iloc[0])
        except Exception:
            pass

        next_cycle = max((c.get('cycle', 0) for c in cycles), default=0) + 1
        today = self.last_trading_date.isoformat() if self.last_trading_date else date.today().isoformat()

        current_positions = list(self.broker.positions.keys())
        cycles.append({
            'cycle': next_cycle,
            'start_date': today,
            'end_date': None,
            'status': 'active',
            'portfolio_start': round(portfolio.total_value, 2),
            'portfolio_end': None,
            'spy_start': round(spy_price, 2) if spy_price else None,
            'spy_end': None,
            'positions': current_positions,
            'positions_current': list(current_positions),
            'compass_return': None,
            'spy_return': None,
            'alpha': None,
            'stop_events': [],
        })

        os.makedirs('state', exist_ok=True)
        with open(log_file, 'w') as f:
            json.dump(cycles, f, indent=2)

        logger.info(f"CYCLE #{next_cycle} initialized on startup: "
                    f"{list(self.broker.positions.keys())}")

    def _update_cycle_log_stop(self, stopped_symbol: str, replacement_symbol: str,
                                exit_reason: str, stop_return: float):
        """Update the active cycle when a mid-cycle stop fires and a replacement enters.

        Records the stop event and updates positions_current so the dashboard
        shows the actual current holdings, not just the cycle-start snapshot.
        """
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
            c['stop_events'].append({
                'date': today,
                'stopped': stopped_symbol,
                'replacement': replacement_symbol,
                'reason': exit_reason,
                'return': round(stop_return * 100, 1),
            })

            current = c['positions_current']
            if stopped_symbol in current:
                current.remove(stopped_symbol)
            if replacement_symbol and replacement_symbol not in current:
                current.append(replacement_symbol)
            c['positions_current'] = current
            break

        try:
            with open(log_file, 'w') as f:
                json.dump(cycles, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to update cycle log stop: {e}")

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def save_state(self):
        """Save full system state to JSON"""
        portfolio = self.broker.get_portfolio()
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

            # Events
            'stop_events': self.stop_events,

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
                'capital_manager': self.hydra_capital.to_dict() if self.hydra_capital else None,
            },

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

        # Restore drawdown / crash state
        self.crash_cooldown = state.get('crash_cooldown', 0)
        self.portfolio_values_history = state.get('portfolio_values_history', [])

        # Restore regime
        self.current_regime_score = state.get('current_regime_score', 0.5)

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

        # Restore HYDRA state
        hydra_state = state.get('hydra', {})
        if hydra_state and self._hydra_available:
            self.rattle_positions = hydra_state.get('rattle_positions', [])
            self.rattle_regime = hydra_state.get('rattle_regime', 'RISK_ON')
            self._vix_current = hydra_state.get('vix_current')
            cap_state = hydra_state.get('capital_manager')
            if cap_state:
                self.hydra_capital = HydraCapitalManager.from_dict(cap_state)
                logger.info(f"  HYDRA restored: R_pos={len(self.rattle_positions)} | "
                           f"C_acct=${self.hydra_capital.compass_account:,.0f} | "
                           f"R_acct=${self.hydra_capital.rattle_account:,.0f}")

        regime_str = f"score={self.current_regime_score:.2f}"

        logger.info(f"State loaded from {loaded_from}")
        logger.info(f"  Cash: ${self.broker.cash:,.0f} | Peak: ${self.peak_value:,.0f}")
        logger.info(f"  Positions: {len(self.broker.positions)} (COMPASS) + {len(self.rattle_positions)} (Rattlesnake) | Day: {self.trading_day_counter}")
        logger.info(f"  Regime: {regime_str} | Crash cooldown: {self.crash_cooldown}")
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
            if not self.is_market_open():
                return False

            # New trading day setup
            if self.is_new_trading_day():
                self.daily_open()

            # Get current prices (async fetch + batch validation)
            symbols_needed = set(self.current_universe) | set(self.position_meta.keys())
            # HYDRA: include Rattlesnake held symbols + universe for candidate scanning
            if self._hydra_available:
                symbols_needed |= {p['symbol'] for p in self.rattle_positions}
                symbols_needed |= set(R_UNIVERSE)
            symbols_needed = list(symbols_needed)
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
                    self.check_position_exits(prices)
                    # HYDRA: also check Rattlesnake exits intraday
                    if self._hydra_available and self.rattle_positions:
                        self._check_rattlesnake_exits(prices)
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
        logger.info("Starting COMPASS v8.3 live trading loop...")

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
