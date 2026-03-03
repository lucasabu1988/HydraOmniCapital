"""
OmniCapital v8.5b COMPASS - Market Breadth ONLY (stop widening disabled)
==================================================================================
A/B test variant: ONLY breadth regime change, NO stop widening.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

# ============================================================================
# PARAMETROS
# ============================================================================

# Universe
TOP_N = 40
MIN_AGE_DAYS = 63

# Signal
MOMENTUM_LOOKBACK = 90      # Dias para momentum de medio plazo (H3 optimized)
MOMENTUM_SKIP = 5           # Dias recientes a excluir (reversal)
MIN_MOMENTUM_STOCKS = 20    # Minimo de stocks con score valido para operar

# Positions
NUM_POSITIONS = 5           # Posiciones en RISK_ON
NUM_POSITIONS_RISK_OFF = 2  # Posiciones en RISK_OFF
HOLD_DAYS = 5               # Dias de hold (trading days)

# Position-level risk
POSITION_STOP_LOSS = -0.08  # -8% por posicion
TRAILING_ACTIVATION = 0.05  # Activar trailing tras +5% (H3 optimized)
TRAILING_STOP_PCT = 0.03    # Trailing stop: -3% desde max (H3 optimized)

# Exit renewal (allow winners to extend hold)
HOLD_DAYS_MAX = 10                   # Hard cap: absolute max days (conservative)
RENEWAL_PROFIT_MIN = 0.04            # +4% min profit to renew (conservative)
MOMENTUM_RENEWAL_THRESHOLD = 0.85    # Top 85% of universe by score (conservative)

# Quality filter (for universe expansion)
QUALITY_VOL_MAX = 0.60          # Exclude stocks with vol > 60% annualized
QUALITY_VOL_LOOKBACK = 63       # 3-month window for vol calculation
QUALITY_MAX_SINGLE_DAY = 0.50   # Exclude if single-day move > 50% (data corruption)

# Smooth drawdown scaling (replaces binary portfolio stop)
DD_SCALE_TIER1 = -0.10      # Start reducing leverage at -10% (H3: widened from -5%)
DD_SCALE_TIER2 = -0.20      # Medium drawdown (H3: widened from -15%)
DD_SCALE_TIER3 = -0.35      # Deep drawdown floor (H3: widened from -25%)
LEV_FULL       = 1.0        # Full leverage (no reduction)
LEV_MID        = 0.60       # Medium drawdown leverage (H3: raised from 0.50)
LEV_FLOOR      = 0.30       # Hard floor (H3: raised from 0.20)
CRASH_VEL_5D   = -0.06      # 5-day crash velocity threshold
CRASH_VEL_10D  = -0.10      # 10-day crash velocity threshold
CRASH_LEVERAGE = 0.15       # Leverage during crash cooldown
CRASH_COOLDOWN = 10         # Days of crash cooldown

# Leverage & Vol targeting
TARGET_VOL = 0.15           # 15% anualizado
LEVERAGE_MAX = 1.0          # Production: no leverage (broker margin destroys value)
VOL_LOOKBACK = 20           # Dias para calcular realized vol

# Costs
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06          # 6% anual sobre borrowed
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.035         # Fallback fijo (usado si FRED no disponible)
CASH_YIELD_SOURCE = 'AAA'       # Moody's Aaa Corporate Bond Yield (FRED)

# ============================================================================
# v8.4 IMPROVEMENT 1: Bull Market Override (Regime Recalibration)
# ============================================================================
# When SPY is clearly above SMA200, add +1 position floor to prevent
# false risk-off from vol spikes during bull markets.
# Analysis: 864 false risk-off days (37% of all risk-off) had SPY > SMA200.
# 83% caused by vol component dragging score below 0.50.
BULL_OVERRIDE_THRESHOLD = 0.03  # SPY > SMA200 * 1.03 -> bump +1 position
BULL_OVERRIDE_MIN_SCORE = 0.40  # Only override if regime_score > this

# ============================================================================
# v8.4 IMPROVEMENT 2: Adaptive Stops (Vol-Scaled)
# ============================================================================
STOP_DAILY_VOL_MULT = 2.5      # Stop = -2.5 * daily_vol (using daily vol for differentiation)
STOP_FLOOR = -0.06             # Tightest stop for low-vol stocks (-6%)
STOP_CEILING = -0.15           # Widest stop for high-vol stocks (-15%)
TRAILING_VOL_BASELINE = 0.25   # Baseline annualized vol (25%) for trailing stop scaling

# ============================================================================
# v8.4 IMPROVEMENT 3: Sector Concentration Limits
# ============================================================================
MAX_PER_SECTOR = 3  # Maximum open positions per GICS sector

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
    # Consumer (Discretionary + Staples)
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
# v8.5 IMPROVEMENT 1: Regime-Conditional Stop Widening
# ============================================================================
STOP_BULL_MULT = 1.4        # Stop 40% wider when regime >= 0.65
STOP_MILD_BULL_MULT = 1.2   # Stop 20% wider when regime >= 0.50

# ============================================================================
# v8.5 IMPROVEMENT 2: Market Breadth in Regime Score
# ============================================================================
REGIME_TREND_WEIGHT = 0.45     # Was 0.60 in v84
REGIME_VOL_WEIGHT = 0.30       # Was 0.40 in v84
REGIME_BREADTH_WEIGHT = 0.25   # New component
BREADTH_SMA_WINDOW = 50        # SMA50 for breadth calculation
BREADTH_SIGMOID_K = 8.0        # Sensitivity around 50% threshold

# Data
START_DATE = '2000-01-01'
END_DATE = '2027-01-01'  # Far-future so yfinance always returns latest available data

# Broad pool (~113 S&P 500 stocks)
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

print("=" * 80)
print("OMNICAPITAL v8.5 COMPASS - Stop Widening + Market Breadth")
print("Bull Override | Adaptive Stops | Sector Limits | Breadth Regime | Stop Widening")
print("=" * 80)
print(f"\nBroad pool: {len(BROAD_POOL)} stocks | Top-{TOP_N} annual rotation")
print(f"Signal: Momentum {MOMENTUM_LOOKBACK}d (skip {MOMENTUM_SKIP}d) + Inverse Vol sizing")
print(f"Regime: Sigmoid + bull override (SPY > SMA200*{1+BULL_OVERRIDE_THRESHOLD:.0%} -> +1 pos)")
print(f"Stops: Adaptive {STOP_FLOOR:.0%} to {STOP_CEILING:.0%} (vol-scaled) | Sector max: {MAX_PER_SECTOR}/sector")
print(f"Hold: {HOLD_DAYS}d | DD tiers: {DD_SCALE_TIER1}/{DD_SCALE_TIER2}/{DD_SCALE_TIER3}")
print(f"Cash yield: Moody's Aaa IG Corporate (FRED, variable)")
print()


# ============================================================================
# DATA FUNCTIONS
# ============================================================================

def download_broad_pool() -> Dict[str, pd.DataFrame]:
    """Download/load cached data for the broad pool"""
    cache_file = f'data_cache/broad_pool_{START_DATE}_{END_DATE}.pkl'

    if os.path.exists(cache_file):
        print("[Cache] Loading broad pool data...")
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception:
            print("[Cache] Failed to load, re-downloading...")

    print(f"[Download] Downloading {len(BROAD_POOL)} symbols...")
    data = {}
    failed = []

    for i, symbol in enumerate(BROAD_POOL):
        try:
            df = yf.download(symbol, start=START_DATE, end=END_DATE, progress=False)
            if not df.empty and len(df) > 100:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                data[symbol] = df
                if (i + 1) % 20 == 0:
                    print(f"  [{i+1}/{len(BROAD_POOL)}] Downloaded {len(data)} symbols...")
            else:
                failed.append(symbol)
        except Exception:
            failed.append(symbol)

    print(f"[Download] {len(data)} symbols valid, {len(failed)} failed")
    if failed:
        print(f"  Failed: {failed}")

    os.makedirs('data_cache', exist_ok=True)
    with open(cache_file, 'wb') as f:
        pickle.dump(data, f)

    return data


def download_spy() -> pd.DataFrame:
    """Download SPY data for regime filter"""
    cache_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'

    if os.path.exists(cache_file):
        print("[Cache] Loading SPY data...")
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        return df

    print("[Download] Downloading SPY...")
    df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def download_cash_yield() -> pd.Series:
    """Download Moody's Aaa Corporate Bond Yield from FRED.
    Returns a daily Series of yield rates (annual %, forward-filled from monthly).
    Falls back to fixed CASH_YIELD_RATE if FRED unavailable."""
    cache_file = 'data_cache/moody_aaa_yield.csv'

    if os.path.exists(cache_file):
        print("[Cache] Loading Moody's Aaa yield data...")
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        daily = df['yield_pct'].resample('D').ffill()
        print(f"  {len(daily)} daily rates, avg {daily.mean():.2f}%")
        return daily

    print("[Download] Downloading Moody's Aaa yield from FRED...")
    try:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA&cosd=1999-01-01&coed=2026-12-31'
        df = pd.read_csv(url, parse_dates=['observation_date'], index_col='observation_date')
        df.columns = ['yield_pct']
        os.makedirs('data_cache', exist_ok=True)
        df.to_csv(cache_file)
        daily = df['yield_pct'].resample('D').ffill()
        print(f"  {len(daily)} daily rates, avg {daily.mean():.2f}%")
        return daily
    except Exception as e:
        print(f"  FRED download failed: {e}. Using fixed {CASH_YIELD_RATE:.1%}")
        return None


def compute_annual_top40(price_data: Dict[str, pd.DataFrame]) -> Dict[int, List[str]]:
    """For each year, compute top-40 by avg daily dollar volume (prior year data)"""
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}

    for year in years:
        if year == years[0]:
            ranking_end = pd.Timestamp(f'{year}-02-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            ranking_start = pd.Timestamp(f'{year-1}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
        else:
            ranking_end = pd.Timestamp(f'{year}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            ranking_start = pd.Timestamp(f'{year-1}-01-01', tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)

        scores = {}
        for symbol, df in price_data.items():
            mask = (df.index >= ranking_start) & (df.index < ranking_end)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            dollar_vol = (window['Close'] * window['Volume']).mean()
            scores[symbol] = dollar_vol

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top_n = [s for s, _ in ranked[:TOP_N]]
        annual_universe[year] = top_n

        if year > years[0] and year - 1 in annual_universe:
            prev = set(annual_universe[year - 1])
            curr = set(top_n)
            added = curr - prev
            removed = prev - curr
            if added or removed:
                print(f"  {year}: Top-{TOP_N} | +{len(added)} added, -{len(removed)} removed")
        else:
            print(f"  {year}: Initial top-{TOP_N} = {len(top_n)} stocks")

    return annual_universe


# ============================================================================
# SIGNAL & REGIME FUNCTIONS
# ============================================================================

def get_spy_trend_data(spy_data: pd.DataFrame, date: pd.Timestamp) -> Optional[Tuple[float, float]]:
    """
    v8.4: Extract SPY close price and SMA200 for a given date.
    Returns (spy_close, sma200) or None if insufficient data.
    """
    date_n = pd.Timestamp(date)
    if hasattr(date_n, 'tz') and date_n.tz is not None:
        date_n = date_n.tz_localize(None)

    spy = spy_data
    spy_idx_loc = spy.index
    if hasattr(spy_idx_loc, 'tz') and spy_idx_loc.tz is not None:
        date_n = date_n.tz_localize(spy_idx_loc.tz)

    if date_n not in spy.index:
        return None

    spy_idx = spy.index.get_loc(date_n)
    if spy_idx < 200:
        return None

    spy_close = float(spy['Close'].iloc[spy_idx])
    sma200 = float(spy['Close'].iloc[spy_idx - 199:spy_idx + 1].mean())

    return (spy_close, sma200)


def _sigmoid(x: float, k: float = 15.0) -> float:
    """Logistic sigmoid: maps (-inf, +inf) -> (0, 1)."""
    z = float(np.clip(k * x, -20.0, 20.0))
    return 1.0 / (1.0 + np.exp(-z))


def compute_regime_score(spy_data: pd.DataFrame, date: pd.Timestamp, price_data: Optional[Dict[str, pd.DataFrame]] = None, tradeable_symbols: Optional[List[str]] = None) -> float:
    """
    Compute continuous market regime score [0.0, 1.0].
    0.0 = extreme bear, 1.0 = strong bull.

    Components:
      Trend (60%): sigmoid of price vs SMA200 + SMA50/SMA200 cross + 20d momentum
      Volatility (40%): inverted percentile rank of 10d vol in 252d distribution
    """
    date_n = pd.Timestamp(date)
    if hasattr(date_n, 'tz') and date_n.tz is not None:
        date_n = date_n.tz_localize(None)

    spy = spy_data.copy()
    if hasattr(spy.index, 'tz') and spy.index.tz is not None:
        spy.index = spy.index.tz_localize(None)

    if date_n not in spy.index:
        return 0.5

    spy_idx = spy.index.get_loc(date_n)
    if spy_idx < 252:
        return 0.5

    spy_close = spy['Close'].iloc[:spy_idx + 1]
    current = float(spy_close.iloc[-1])

    # Trend (60%)
    sma200 = float(spy_close.iloc[-200:].mean())
    sma50 = float(spy_close.iloc[-50:].mean())

    if sma200 <= 0:
        return 0.5

    dist_200 = (current / sma200) - 1.0
    sig_200 = _sigmoid(dist_200, k=15.0)

    if sma200 > 0:
        cross = (sma50 / sma200) - 1.0
        sig_cross = _sigmoid(cross, k=30.0)
    else:
        sig_cross = 0.5

    if len(spy_close) >= 21:
        price_20d_ago = float(spy_close.iloc[-21])
        if price_20d_ago > 0:
            mom_20d = (current / price_20d_ago) - 1.0
            sig_mom = _sigmoid(mom_20d, k=15.0)
        else:
            sig_mom = 0.5
    else:
        sig_mom = 0.5

    trend_score = (sig_200 + sig_cross + sig_mom) / 3.0

    # Volatility (40%)
    returns = spy_close.pct_change().dropna()
    vol_score = 0.5

    if len(returns) >= 262:
        current_vol = float(returns.iloc[-10:].std() * np.sqrt(252))
        hist_returns = returns.iloc[-252:]
        rolling_vol = hist_returns.rolling(window=10).std() * np.sqrt(252)
        rolling_vol = rolling_vol.dropna()

        if len(rolling_vol) >= 20 and current_vol > 0:
            pct_rank = float((rolling_vol <= current_vol).sum()) / len(rolling_vol)
            vol_score = 1.0 - pct_rank

    # v8.5: Add breadth component if data available
    if price_data is not None and tradeable_symbols is not None:
        breadth = compute_breadth_score(price_data, tradeable_symbols, date)
        composite = (REGIME_TREND_WEIGHT * trend_score +
                     REGIME_VOL_WEIGHT * vol_score +
                     REGIME_BREADTH_WEIGHT * breadth)
    else:
        composite = 0.60 * trend_score + 0.40 * vol_score

    return float(np.clip(composite, 0.0, 1.0))


def compute_breadth_score(price_data: Dict[str, pd.DataFrame],
                          tradeable_symbols: List[str],
                          date: pd.Timestamp) -> float:
    """
    v8.5: Compute market breadth score from fraction of stocks above SMA50.
    Returns sigmoid-transformed score [0, 1]. 0.5 = exactly 50% above SMA50.
    """
    above = 0
    total = 0
    for symbol in tradeable_symbols:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        try:
            idx = df.index.get_loc(date)
        except KeyError:
            continue
        if idx < BREADTH_SMA_WINDOW:
            continue
        current = float(df['Close'].iloc[idx])
        sma = float(df['Close'].iloc[idx - BREADTH_SMA_WINDOW + 1:idx + 1].mean())
        total += 1
        if current > sma:
            above += 1
    if total == 0:
        return 0.5
    breadth_pct = above / total
    return float(_sigmoid(breadth_pct - 0.50, k=BREADTH_SIGMOID_K))


def regime_score_to_positions(regime_score: float,
                               num_positions: int = NUM_POSITIONS,
                               num_positions_risk_off: int = NUM_POSITIONS_RISK_OFF,
                               spy_close: Optional[float] = None,
                               sma200: Optional[float] = None) -> int:
    """
    Convert continuous regime score to number of positions.
    v8.4: Bull market override -- when SPY is >3% above SMA200 and score > 0.40,
    bump positions by +1 (capped at max). This prevents vol spikes from
    reducing positions during confirmed uptrends.

      >= 0.65: 5 positions (strong bull)
      >= 0.50: 4 positions (mild bull)
      >= 0.35: 3 positions (mild bear)
      <  0.35: 2 positions (bear)
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
            and sma200 > 0 and regime_score > BULL_OVERRIDE_MIN_SCORE):
        pct_above = (spy_close / sma200) - 1.0
        if pct_above >= BULL_OVERRIDE_THRESHOLD:
            base = min(base + 1, num_positions)

    return base


def compute_momentum_scores(price_data: Dict[str, pd.DataFrame],
                           tradeable: List[str],
                           date: pd.Timestamp,
                           all_dates: List[pd.Timestamp],
                           date_idx: int) -> Dict[str, float]:
    """
    Compute RISK-ADJUSTED cross-sectional momentum score.
    Score = raw_momentum / realized_vol (Barroso-Santa-Clara 2015)

    This de-emphasizes high-vol stocks with noisy large moves and up-weights
    low-vol stocks with steady positive momentum (better signal-to-noise).
    """
    scores = {}
    RISK_ADJ_VOL_WINDOW = 63  # 3-month vol for risk adjustment

    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue

        needed = MOMENTUM_LOOKBACK + MOMENTUM_SKIP
        try:
            sym_idx = df.index.get_loc(date)
        except KeyError:
            continue

        if sym_idx < needed:
            continue

        close_today = df['Close'].iloc[sym_idx]
        close_skip = df['Close'].iloc[sym_idx - MOMENTUM_SKIP]
        close_lookback = df['Close'].iloc[sym_idx - MOMENTUM_LOOKBACK]

        if close_lookback <= 0 or close_skip <= 0 or close_today <= 0:
            continue

        # Raw momentum (same as v8.2)
        momentum_raw = (close_skip / close_lookback) - 1.0
        skip_5d = (close_today / close_skip) - 1.0
        raw_score = momentum_raw - skip_5d

        # Risk adjustment: divide by realized vol
        vol_window = min(RISK_ADJ_VOL_WINDOW, sym_idx - 1)
        if vol_window >= 20:
            returns = df['Close'].iloc[sym_idx - vol_window:sym_idx + 1].pct_change().dropna()
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


def compute_volatility_weights(price_data: Dict[str, pd.DataFrame],
                               selected: List[str],
                               date: pd.Timestamp) -> Dict[str, float]:
    """
    Compute inverse-volatility weights for selected stocks.
    Lower vol stocks get higher weight.
    """
    vols = {}

    for symbol in selected:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue

        sym_idx = df.index.get_loc(date)
        if sym_idx < VOL_LOOKBACK + 1:
            continue

        # 20-day realized volatility
        returns = df['Close'].iloc[sym_idx - VOL_LOOKBACK:sym_idx + 1].pct_change().dropna()
        if len(returns) < VOL_LOOKBACK - 2:
            continue

        vol = returns.std() * np.sqrt(252)
        if vol > 0.01:  # Minimum vol to avoid division issues
            vols[symbol] = vol

    if not vols:
        # Fallback: equal weight
        return {s: 1.0 / len(selected) for s in selected}

    # Inverse vol weights
    raw_weights = {s: 1.0 / v for s, v in vols.items()}
    total = sum(raw_weights.values())
    return {s: w / total for s, w in raw_weights.items()}


def compute_entry_vol(price_data: Dict[str, pd.DataFrame],
                      symbol: str,
                      date: pd.Timestamp,
                      lookback: int = 20) -> Tuple[float, float]:
    """
    v8.4: Compute volatility for a stock at entry time.
    Returns (annualized_vol, daily_vol).
    Daily vol is used for adaptive stop calculation.
    Falls back to (0.25, 0.016) if insufficient data.
    """
    DEFAULT_ANN = 0.25
    DEFAULT_DAILY = DEFAULT_ANN / np.sqrt(252)

    if symbol not in price_data:
        return (DEFAULT_ANN, DEFAULT_DAILY)
    df = price_data[symbol]
    if date not in df.index:
        return (DEFAULT_ANN, DEFAULT_DAILY)

    sym_idx = df.index.get_loc(date)
    if sym_idx < lookback + 1:
        return (DEFAULT_ANN, DEFAULT_DAILY)

    returns = df['Close'].iloc[sym_idx - lookback:sym_idx + 1].pct_change().dropna()
    if len(returns) < lookback - 2:
        return (DEFAULT_ANN, DEFAULT_DAILY)

    daily_vol = float(returns.std())
    ann_vol = daily_vol * np.sqrt(252)
    return (max(ann_vol, 0.05), max(daily_vol, 0.003))


def compute_adaptive_stop(entry_daily_vol: float) -> float:
    """
    v8.4: Compute adaptive position stop loss based on entry-time daily volatility.
    Stop = max(STOP_CEILING, min(STOP_FLOOR, -STOP_DAILY_VOL_MULT * daily_vol))

    Examples (with STOP_DAILY_VOL_MULT=2.5, STOP_FLOOR=-6%, STOP_CEILING=-15%):
      Low-vol stock (daily_vol=1.0%):  stop = -6.0% (STOP_FLOOR)
      Med-vol stock (daily_vol=2.5%):  stop = -6.25%
      Typical stock (daily_vol=3.5%):  stop = -8.75% (~current v8.3 level)
      High-vol stock (daily_vol=4.5%): stop = -11.25% (wider, less whipsaw)
      Very high-vol (daily_vol=6%+):   stop = -15.0% (STOP_CEILING)
    """
    raw_stop = -STOP_DAILY_VOL_MULT * entry_daily_vol
    return max(STOP_CEILING, min(STOP_FLOOR, raw_stop))


def compute_dynamic_leverage(spy_data: pd.DataFrame, date: pd.Timestamp) -> float:
    """
    Compute leverage via volatility targeting.
    leverage = target_vol / realized_vol, clipped to [min, max]
    """
    if date not in spy_data.index:
        return 1.0

    idx = spy_data.index.get_loc(date)
    if idx < VOL_LOOKBACK + 1:
        return 1.0

    # Use SPY realized vol as portfolio vol proxy
    returns = spy_data['Close'].iloc[idx - VOL_LOOKBACK:idx + 1].pct_change().dropna()
    if len(returns) < VOL_LOOKBACK - 2:
        return 1.0

    realized_vol = returns.std() * np.sqrt(252)
    if realized_vol < 0.01:
        return LEVERAGE_MAX

    leverage = TARGET_VOL / realized_vol
    return max(LEV_FLOOR, min(LEVERAGE_MAX, leverage))


# ============================================================================
# SMOOTH DRAWDOWN SCALING
# ============================================================================

def _dd_leverage(drawdown: float) -> float:
    """
    Smooth piecewise-linear drawdown leverage scaling.
    DD tiers:
      0%   to -5%:  1.0x (no reduction)
      -5%  to -15%: 1.0x -> 0.50x (linear)
      -15% to -25%: 0.50x -> 0.20x (linear)
      < -25%:       0.20x (hard floor)
    """
    dd = drawdown
    if dd >= DD_SCALE_TIER1:
        return LEV_FULL
    elif dd >= DD_SCALE_TIER2:
        frac = (dd - DD_SCALE_TIER1) / (DD_SCALE_TIER2 - DD_SCALE_TIER1)
        return LEV_FULL + frac * (LEV_MID - LEV_FULL)
    elif dd >= DD_SCALE_TIER3:
        frac = (dd - DD_SCALE_TIER2) / (DD_SCALE_TIER3 - DD_SCALE_TIER2)
        return LEV_MID + frac * (LEV_FLOOR - LEV_MID)
    else:
        return LEV_FLOOR


def compute_smooth_leverage(drawdown: float,
                             portfolio_values: list,
                             current_idx: int,
                             crash_cooldown: int) -> tuple:
    """
    Compute leverage via smooth drawdown scaling + crash velocity circuit breaker.
    Replaces: in_protection_mode, protection_stage, stop_loss_day_index,
    PORTFOLIO_STOP_LOSS trigger, and Recovery Stage 1/2.
    """
    def _val(entry):
        if isinstance(entry, dict):
            return float(entry.get('value', entry.get('portfolio_value', 0.0)))
        return float(entry)

    in_crash = False
    updated_cooldown = crash_cooldown

    if crash_cooldown > 0:
        in_crash = True
        updated_cooldown = crash_cooldown - 1
    elif current_idx >= 5 and len(portfolio_values) > current_idx:
        current_val = _val(portfolio_values[current_idx])
        val_5d = _val(portfolio_values[current_idx - 5])
        if val_5d > 0:
            ret_5d = (current_val / val_5d) - 1.0
            if ret_5d <= CRASH_VEL_5D:
                in_crash = True
        if not in_crash and current_idx >= 10:
            val_10d = _val(portfolio_values[current_idx - 10])
            if val_10d > 0:
                ret_10d = (current_val / val_10d) - 1.0
                if ret_10d <= CRASH_VEL_10D:
                    in_crash = True
        if in_crash:
            updated_cooldown = CRASH_COOLDOWN - 1

    if in_crash:
        dd_lev = _dd_leverage(drawdown)
        crash_lev = min(CRASH_LEVERAGE, dd_lev)
        return (crash_lev, updated_cooldown)

    return (_dd_leverage(drawdown), updated_cooldown)


# ============================================================================
# BACKTEST
# ============================================================================

def get_tradeable_symbols(price_data: Dict[str, pd.DataFrame],
                         date: pd.Timestamp,
                         first_date: pd.Timestamp,
                         annual_universe: Dict[int, List[str]]) -> List[str]:
    """Return tradeable symbols from top-40 for that year"""
    eligible = set(annual_universe.get(date.year, []))
    tradeable = []
    for symbol in eligible:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        symbol_first_date = df.index[0]
        days_since_start = (date - symbol_first_date).days
        if date <= first_date + timedelta(days=30):
            tradeable.append(symbol)
        elif days_since_start >= MIN_AGE_DAYS:
            tradeable.append(symbol)
    return tradeable


def should_renew_position(symbol: str, pos: dict, current_price: float,
                          total_days_held: int, scores: dict) -> bool:
    """
    Determine if a position should renew instead of closing at hold expiry.
    Uses total_days_held (from original_entry_idx) for HOLD_DAYS_MAX check.
    """
    # Hard cap: never exceed maximum
    if total_days_held >= HOLD_DAYS_MAX:
        return False

    # Minimum profit required
    entry_price = pos.get('entry_price', current_price)
    if entry_price <= 0:
        return False
    pos_return = (current_price - entry_price) / entry_price
    if pos_return < RENEWAL_PROFIT_MIN:
        return False

    # Score must be valid
    if not scores or symbol not in scores:
        return False

    # Percentile rank in universe
    all_score_values = sorted(scores.values(), reverse=True)
    n = len(all_score_values)
    if n < 3:
        return False

    symbol_score = scores[symbol]
    rank_above = sum(1 for s in all_score_values if s > symbol_score)
    percentile = 1.0 - (rank_above / n)

    return percentile >= MOMENTUM_RENEWAL_THRESHOLD


def compute_quality_filter(price_data: Dict[str, pd.DataFrame],
                           tradeable: List[str],
                           date: pd.Timestamp) -> List[str]:
    """
    Filter out stocks unsuitable for momentum strategies.
    Excludes: stocks with 63d vol > 60% and single-day moves > 50%.
    Fallback: returns full list if < 5 stocks pass.
    """
    passed = []
    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        try:
            sym_idx = df.index.get_loc(date)
        except KeyError:
            continue

        if sym_idx < QUALITY_VOL_LOOKBACK + 1:
            passed.append(symbol)
            continue

        prices = df['Close'].iloc[sym_idx - QUALITY_VOL_LOOKBACK:sym_idx + 1]
        rets = prices.pct_change().dropna()

        if len(rets) < QUALITY_VOL_LOOKBACK - 5:
            passed.append(symbol)
            continue

        max_abs_ret = float(rets.abs().max())
        if max_abs_ret > QUALITY_MAX_SINGLE_DAY:
            continue

        ann_vol = float(rets.std() * np.sqrt(252))
        if ann_vol <= QUALITY_VOL_MAX:
            passed.append(symbol)

    if len(passed) < 5:
        return tradeable
    return passed


def filter_by_sector_concentration(ranked_candidates: List[Tuple[str, float]],
                                    current_positions: Dict[str, dict],
                                    max_per_sector: int = MAX_PER_SECTOR) -> List[str]:
    """
    v8.4: Filter ranked candidates by sector concentration limits.
    Iterates through ranked candidates and only selects those whose sector
    has room (< max_per_sector positions).
    """
    sector_counts = defaultdict(int)
    for sym, pos in current_positions.items():
        sector = pos.get('sector', SECTOR_MAP.get(sym, 'Unknown'))
        sector_counts[sector] += 1

    selected = []
    for symbol, score in ranked_candidates:
        sector = SECTOR_MAP.get(symbol, 'Unknown')
        if sector_counts[sector] < max_per_sector:
            selected.append(symbol)
            sector_counts[sector] += 1

    return selected


def run_backtest(price_data: Dict[str, pd.DataFrame],
                 annual_universe: Dict[int, List[str]],
                 spy_data: pd.DataFrame,
                 cash_yield_daily: Optional[pd.Series] = None) -> Dict:
    """Run COMPASS backtest"""

    print("\n" + "=" * 80)
    print("RUNNING COMPASS BACKTEST")
    print("=" * 80)

    # Get all trading dates
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    print("\nUsing continuous sigmoid regime filter...")

    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")

    # Portfolio state
    cash = float(INITIAL_CAPITAL)
    positions = {}  # symbol -> {entry_price, shares, entry_date, entry_idx, original_entry_idx, high_price}
    portfolio_values = []
    trades = []
    stop_events = []

    peak_value = float(INITIAL_CAPITAL)
    crash_cooldown = 0

    risk_on_days = 0
    risk_off_days = 0

    current_year = None

    for i, date in enumerate(all_dates):
        # Annual rotation check
        if date.year != current_year:
            current_year = date.year

        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, annual_universe)

        # --- Calculate portfolio value ---
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        # --- Update peak ---
        if portfolio_value > peak_value:
            peak_value = portfolio_value

        # --- Drawdown ---
        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # --- Regime (continuous sigmoid) ---
        regime_score = compute_regime_score(spy_data, date, price_data=price_data, tradeable_symbols=tradeable_symbols)
        is_risk_on = regime_score >= 0.50
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        # --- Smooth drawdown leverage ---
        dd_leverage_val, crash_cooldown = compute_smooth_leverage(
            drawdown, portfolio_values, max(i - 1, 0), crash_cooldown
        )

        # Vol targeting
        vol_leverage = compute_dynamic_leverage(spy_data, date)

        # Final leverage: minimum of DD scaling and vol targeting
        current_leverage = max(min(dd_leverage_val, vol_leverage), LEV_FLOOR)

        # Max positions from regime score (v8.4: with bull override)
        spy_trend = get_spy_trend_data(spy_data, date)
        if spy_trend is not None:
            spy_close_now, sma200_now = spy_trend
            max_positions = regime_score_to_positions(regime_score,
                                                      spy_close=spy_close_now,
                                                      sma200=sma200_now)
        else:
            max_positions = regime_score_to_positions(regime_score)

        # --- Daily costs (margin on borrowed amount) ---
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        # --- Cash yield (Moody's Aaa corporate bond yield on uninvested cash) ---
        if cash > 0:
            if cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

        # --- Quality filter (before momentum scores) ---
        quality_symbols = compute_quality_filter(price_data, tradeable_symbols, date)

        # --- Compute scores ONCE (used for both renewal checks and new positions) ---
        current_scores = compute_momentum_scores(price_data, quality_symbols, date, all_dates, i)

        # --- Close positions ---
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue

            current_price = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            # 1. Hold time check (with renewal for winners)
            days_held = i - pos['entry_idx']
            total_days_held = i - pos['original_entry_idx']
            if days_held >= HOLD_DAYS:
                if should_renew_position(symbol, pos, current_price,
                                        total_days_held, current_scores):
                    # Renew: reset hold counter but keep original_entry_idx
                    pos['entry_idx'] = i
                    # high_price NOT reset: trailing continues from max reached
                else:
                    exit_reason = 'hold_expired'

            # 2. Position stop loss (v8.4: adaptive, vol-scaled — stop widening DISABLED)
            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            adaptive_stop = compute_adaptive_stop(pos.get('entry_daily_vol', 0.016))
            if pos_return <= adaptive_stop:
                exit_reason = 'position_stop'

            # 3. Trailing stop (v8.4: vol-scaled)
            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                vol_ratio = pos.get('entry_vol', TRAILING_VOL_BASELINE) / TRAILING_VOL_BASELINE
                scaled_trailing = TRAILING_STOP_PCT * vol_ratio
                trailing_level = pos['high_price'] * (1 - scaled_trailing)
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            # 4. Stock no longer in top-40
            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'

            # 5. Excess positions (regime changed to risk_off or protection)
            if exit_reason is None and len(positions) > max_positions:
                # Close the worst-performing position
                pos_returns = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        cp = price_data[s].loc[date, 'Close']
                        pos_returns[s] = (cp - p['entry_price']) / p['entry_price']
                worst = min(pos_returns, key=pos_returns.get)
                if symbol == worst:
                    exit_reason = 'regime_reduce'

            if exit_reason:
                shares = pos['shares']
                proceeds = shares * current_price
                commission = shares * COMMISSION_PER_SHARE
                cash += proceeds - commission
                pnl = (current_price - pos['entry_price']) * shares - commission
                trades.append({
                    'symbol': symbol,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'exit_reason': exit_reason,
                    'pnl': pnl,
                    'return': pnl / (pos['entry_price'] * shares)
                })
                del positions[symbol]

        # --- Open new positions ---
        needed = max_positions - len(positions)

        if needed > 0 and cash > 1000 and len(tradeable_symbols) >= 5:
            # Reuse scores computed earlier
            available_scores = {s: sc for s, sc in current_scores.items() if s not in positions}

            if len(current_scores) >= MIN_MOMENTUM_STOCKS and len(available_scores) >= needed:
                # v8.4: Select top N by score WITH sector concentration limits
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                sector_filtered = filter_by_sector_concentration(ranked, positions)
                selected = sector_filtered[:needed]

                # Compute inverse-vol weights
                weights = compute_volatility_weights(price_data, selected, date)

                # Effective capital with leverage
                effective_capital = cash * current_leverage * 0.95  # 5% buffer

                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue

                    entry_price = price_data[symbol].loc[date, 'Close']
                    if entry_price <= 0:
                        continue

                    weight = weights.get(symbol, 1.0 / len(selected))
                    position_value = effective_capital * weight

                    # Cap at a reasonable fraction
                    max_per_position = cash * 0.40
                    position_value = min(position_value, max_per_position)

                    shares = position_value / entry_price
                    cost = shares * entry_price
                    commission = shares * COMMISSION_PER_SHARE

                    if cost + commission <= cash * 0.90:
                        # v8.4: Compute entry-time vol for adaptive stops
                        entry_vol, entry_daily_vol = compute_entry_vol(price_data, symbol, date)

                        positions[symbol] = {
                            'entry_price': entry_price,
                            'shares': shares,
                            'entry_date': date,
                            'entry_idx': i,
                            'original_entry_idx': i,
                            'high_price': entry_price,
                            'entry_vol': entry_vol,              # v8.4: annualized vol
                            'entry_daily_vol': entry_daily_vol,  # v8.4: daily vol for stop calc
                            'sector': SECTOR_MAP.get(symbol, 'Unknown'),  # v8.4: sector tracking
                        }
                        cash -= cost + commission

        # --- Record daily snapshot ---
        portfolio_values.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'drawdown': drawdown,
            'leverage': current_leverage,
            'in_protection': dd_leverage_val < LEV_FULL,
            'risk_on': is_risk_on,
            'regime_score': regime_score,
            'universe_size': len(tradeable_symbols),
        })

        # Annual progress log
        if i % 252 == 0 and i > 0:
            year_num = i // 252
            regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
            prot_str = f" [DD_SCALE {dd_leverage_val:.0%}]" if dd_leverage_val < LEV_FULL else ""
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | DD: {drawdown:.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_str}{prot_str} | "
                  f"Pos: {len(positions)}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'annual_universe': annual_universe,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
    }


# ============================================================================
# METRICS
# ============================================================================

def calculate_metrics(results: Dict) -> Dict:
    """Calculate performance metrics"""
    df = results['portfolio_values'].set_index('date')
    trades_df = results['trades']
    stop_df = results['stop_events']

    initial = INITIAL_CAPITAL
    final_value = df['value'].iloc[-1]

    years = len(df) / 252
    cagr = (final_value / initial) ** (1 / years) - 1

    returns = df['value'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(252)

    max_dd = df['drawdown'].min()

    sharpe = cagr / volatility if volatility > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    # Sortino (downside only)
    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else volatility
    sortino = cagr / downside_vol if downside_vol > 0 else 0

    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    avg_trade = trades_df['pnl'].mean() if len(trades_df) > 0 else 0
    avg_winner = trades_df.loc[trades_df['pnl'] > 0, 'pnl'].mean() if (trades_df['pnl'] > 0).any() else 0
    avg_loser = trades_df.loc[trades_df['pnl'] < 0, 'pnl'].mean() if (trades_df['pnl'] < 0).any() else 0

    # Exit reason breakdown
    exit_reasons = trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in trades_df.columns and len(trades_df) > 0 else {}

    protection_days = df['in_protection'].sum()
    protection_pct = protection_days / len(df) * 100

    risk_off_pct = results['risk_off_days'] / (results['risk_on_days'] + results['risk_off_days']) * 100

    # Annual returns
    df_annual = df['value'].resample('YE').last()
    annual_returns = df_annual.pct_change().dropna()

    return {
        'initial': initial,
        'final_value': final_value,
        'total_return': (final_value - initial) / initial,
        'years': years,
        'cagr': cagr,
        'volatility': volatility,
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'win_rate': win_rate,
        'avg_trade': avg_trade,
        'avg_winner': avg_winner,
        'avg_loser': avg_loser,
        'trades': len(trades_df),
        'exit_reasons': exit_reasons,
        'stop_events': len(stop_df),
        'protection_days': protection_days,
        'protection_pct': protection_pct,
        'risk_off_pct': risk_off_pct,
        'annual_returns': annual_returns,
        'best_year': annual_returns.max() if len(annual_returns) > 0 else 0,
        'worst_year': annual_returns.min() if len(annual_returns) > 0 else 0,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    # 1. Download/load data
    price_data = download_broad_pool()
    print(f"\nSymbols available: {len(price_data)}")

    spy_data = download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    cash_yield_daily = download_cash_yield()

    # 2. Compute annual top-40
    print("\n--- Computing Annual Top-40 ---")
    annual_universe = compute_annual_top40(price_data)

    # 3. Run backtest
    results = run_backtest(price_data, annual_universe, spy_data, cash_yield_daily)

    # 4. Calculate metrics
    metrics = calculate_metrics(results)

    # 5. Print results
    print("\n" + "=" * 80)
    print("RESULTS - OMNICAPITAL v8.5 COMPASS")
    print("=" * 80)

    print(f"\n--- Performance ---")
    print(f"Initial capital:        ${metrics['initial']:>15,.0f}")
    print(f"Final value:            ${metrics['final_value']:>15,.2f}")
    print(f"Total return:           {metrics['total_return']:>15.2%}")
    print(f"CAGR:                   {metrics['cagr']:>15.2%}")
    print(f"Volatility (annual):    {metrics['volatility']:>15.2%}")

    print(f"\n--- Risk-Adjusted ---")
    print(f"Sharpe ratio:           {metrics['sharpe']:>15.2f}")
    print(f"Sortino ratio:          {metrics['sortino']:>15.2f}")
    print(f"Calmar ratio:           {metrics['calmar']:>15.2f}")
    print(f"Max drawdown:           {metrics['max_drawdown']:>15.2%}")

    print(f"\n--- Trading ---")
    print(f"Trades executed:        {metrics['trades']:>15,}")
    print(f"Win rate:               {metrics['win_rate']:>15.2%}")
    print(f"Avg P&L per trade:      ${metrics['avg_trade']:>15,.2f}")
    print(f"Avg winner:             ${metrics['avg_winner']:>15,.2f}")
    print(f"Avg loser:              ${metrics['avg_loser']:>15,.2f}")

    print(f"\n--- Exit Reasons ---")
    for reason, count in sorted(metrics['exit_reasons'].items(), key=lambda x: -x[1]):
        print(f"  {reason:25s}: {count:>6,} ({count/metrics['trades']*100:.1f}%)")

    print(f"\n--- Risk Management ---")
    print(f"Stop loss events:       {metrics['stop_events']:>15,}")
    print(f"Days in protection:     {metrics['protection_days']:>15,} ({metrics['protection_pct']:.1f}%)")
    print(f"Risk-off days:          {metrics['risk_off_pct']:>14.1f}%")

    print(f"\n--- Annual Returns ---")
    if len(metrics['annual_returns']) > 0:
        print(f"Best year:              {metrics['best_year']:>15.2%}")
        print(f"Worst year:             {metrics['worst_year']:>15.2%}")
        print(f"Positive years:         {(metrics['annual_returns'] > 0).sum()}/{len(metrics['annual_returns'])}")

    # 6. Comparison with v6
    print("\n" + "=" * 80)
    print("COMPARISON vs v6 TOP-40 ROTATION")
    print("=" * 80)
    print(f"{'Metric':<25} {'v6':>12} {'v8.5 COMPASS':>12} {'Change':>12}")
    print("-" * 65)
    v6_cagr = 0.054
    v6_sharpe = 0.22
    v6_maxdd = -0.594
    v6_stops = 9
    print(f"{'CAGR':<25} {v6_cagr:>11.2%} {metrics['cagr']:>11.2%} {metrics['cagr']-v6_cagr:>+11.2%}")
    print(f"{'Sharpe':<25} {v6_sharpe:>12.2f} {metrics['sharpe']:>12.2f} {metrics['sharpe']-v6_sharpe:>+12.2f}")
    print(f"{'Max Drawdown':<25} {v6_maxdd:>11.1%} {metrics['max_drawdown']:>11.1%} {metrics['max_drawdown']-v6_maxdd:>+11.1%}")
    print(f"{'Stop Events':<25} {v6_stops:>12} {metrics['stop_events']:>12}")

    # 7. Save results
    os.makedirs('backtests', exist_ok=True)
    results['portfolio_values'].to_csv('backtests/v85b_breadth_only_daily.csv', index=False)
    if len(results['trades']) > 0:
        results['trades'].to_csv('backtests/v85b_breadth_only_trades.csv', index=False)

    output_file = 'results_v85b_breadth_only.pkl'
    with open(output_file, 'wb') as f:  # pickle: same format as v8.3
        pickle.dump({
            'params': {
                'momentum_lookback': MOMENTUM_LOOKBACK,
                'momentum_skip': MOMENTUM_SKIP,
                'hold_days': HOLD_DAYS,
                'num_positions': NUM_POSITIONS,
                'target_vol': TARGET_VOL,
                'regime': 'sigmoid_continuous + bull_override + breadth',
                'position_stop': 'adaptive (vol-scaled, regime-widened)',
                'stop_range': (STOP_FLOOR, STOP_CEILING),
                'dd_scale_tiers': (DD_SCALE_TIER1, DD_SCALE_TIER2, DD_SCALE_TIER3),
                'trailing_activation': TRAILING_ACTIVATION,
                'trailing_stop': TRAILING_STOP_PCT,
                'max_per_sector': MAX_PER_SECTOR,
                'bull_override': BULL_OVERRIDE_THRESHOLD,
            },
            'metrics': metrics,
            'portfolio_values': results['portfolio_values'],
            'trades': results['trades'],
            'stop_events': results['stop_events'],
            'annual_universe': results['annual_universe']
        }, f)

    print(f"\nResults saved: {output_file}")
    print(f"Daily CSV: backtests/v85_compass_daily.csv")
    print(f"Trades CSV: backtests/v85_compass_trades.csv")

    # ==========================================================================
    # v8.5 IMPROVEMENT DIAGNOSTICS
    # ==========================================================================
    print("\n" + "=" * 80)
    print("v8.5 IMPROVEMENT DIAGNOSTICS")
    print("=" * 80)

    df_pv = results['portfolio_values']
    total_days = len(df_pv)

    # Imp 1: Bull override stats
    risk_on_days = int(df_pv['risk_on'].sum())
    risk_off_days = total_days - risk_on_days
    print(f"\n--- Improvement 1: Bull Market Override ---")
    print(f"Risk-ON days:               {risk_on_days:>6} / {total_days} ({risk_on_days/total_days*100:.1f}%)")
    print(f"Risk-OFF days:              {risk_off_days:>6} / {total_days} ({risk_off_days/total_days*100:.1f}%)")
    print(f"Override threshold:         SPY > SMA200 * {1+BULL_OVERRIDE_THRESHOLD:.0%} AND score > {BULL_OVERRIDE_MIN_SCORE}")

    # Imp 2: Adaptive stop stats
    trades_df = results['trades']
    print(f"\n--- Improvement 2: Adaptive Stops ---")
    if len(trades_df) > 0:
        stop_trades = trades_df[trades_df['exit_reason'] == 'position_stop']
        trailing_trades = trades_df[trades_df['exit_reason'] == 'trailing_stop']
        print(f"Position stop exits:        {len(stop_trades):>6} ({len(stop_trades)/len(trades_df)*100:.1f}%)")
        print(f"Trailing stop exits:        {len(trailing_trades):>6} ({len(trailing_trades)/len(trades_df)*100:.1f}%)")
        if len(stop_trades) > 0:
            print(f"Avg stop-out return:        {stop_trades['return'].mean():>6.2%}")

    # Imp 3: Sector concentration stats
    print(f"\n--- Improvement 3: Sector Concentration ---")
    print(f"Max per sector limit:       {MAX_PER_SECTOR}")
    if len(trades_df) > 0 and 'symbol' in trades_df.columns:
        trades_df_with_sector = trades_df.copy()
        trades_df_with_sector['sector'] = trades_df_with_sector['symbol'].map(SECTOR_MAP).fillna('Unknown')
        sector_counts = trades_df_with_sector.groupby('sector').size().sort_values(ascending=False)
        print(f"\nTrades by sector:")
        for sector, count in sector_counts.items():
            pct = count / len(trades_df) * 100
            print(f"  {sector:<20s}: {count:>5} ({pct:>5.1f}%)")

    # ==========================================================================
    # v8.5 vs v8.4 COMPARISON
    # ==========================================================================
    print("\n" + "=" * 80)
    print("COMPASS v8.5 vs v8.4 COMPARISON")
    print("=" * 80)

    # v8.4 baseline
    baseline_v84 = {
        'CAGR': 0.1202,
        'MaxDD': -0.326,
        'Sharpe': 0.88,
        'Calmar': 0.3687,
    }

    v85 = {
        'CAGR': metrics['cagr'],
        'MaxDD': metrics['max_drawdown'],
        'Sharpe': metrics['sharpe'],
        'Calmar': metrics['calmar'],
    }

    print(f"\n{'Metric':<20} {'v8.4 Baseline':>15} {'v8.5 Result':>15} {'Delta':>15}")
    print("-" * 65)
    for key in baseline_v84:
        b = baseline_v84[key]
        v = v85[key]
        print(f"{key:<20} {b:>15.2%} {v:>15.2%} {v - b:>+15.2%}")

    # v8.3 comparison (historical)
    print("\n" + "-" * 65)
    print(f"{'Metric':<20} {'v8.3 Baseline':>15} {'v8.5 Result':>15} {'Delta':>15}")
    print("-" * 65)
    baseline_v83 = {
        'CAGR': 0.1157,
        'MaxDD': -0.2962,
        'Sharpe': 0.7955,
        'Calmar': 0.3904,
    }
    for key in baseline_v83:
        b = baseline_v83[key]
        v = v85[key]
        print(f"{key:<20} {b:>15.2%} {v:>15.2%} {v - b:>+15.2%}")

    # Go/No-Go check
    print("\n--- Go/No-Go Gates ---")
    gates = [
        ('CAGR >= 15.0%', v85['CAGR'] >= 0.15),
        ('MaxDD > -55.0%', v85['MaxDD'] > -0.55),
        ('Sharpe >= 0.72', v85['Sharpe'] >= 0.72),
    ]
    all_pass = True
    for name, passed in gates:
        status = 'PASS' if passed else 'FAIL'
        if not passed:
            all_pass = False
        print(f"  {name}: {status}")

    print(f"\nOverall: {'ALL GATES PASSED' if all_pass else 'SOME GATES FAILED'}")

    print("\n" + "=" * 80)
    print("COMPASS v8.5 BACKTEST COMPLETE")
    print("=" * 80)
