"""
HYDRA v8.4 — Quarterly Audit Backtest
==================================================================================
EXPERIMENT: Every 90 trading days, audit the 40-stock pool.
If any stock has dropped >= 30% from its pool entry price, remove it and replace
with the next best candidate by dollar volume from the broad pool.

If the expelled stock has an open position, force sell and buy the replacement
with the same capital (1:1 swap).

Runs TWO variants side-by-side:
  1. BASE: Standard HYDRA v8.4 (no quarterly audit)
  2. AUDIT: HYDRA v8.4 + Quarterly Audit

All other parameters are IDENTICAL to production v8.4.
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from copy import deepcopy
import warnings
warnings.filterwarnings('ignore')

# NOTE: pickle is used here for data caching (same as other HYDRA backtests).
# All cached data is self-generated from yfinance downloads, never from
# untrusted sources.

# ============================================================================
# PARAMETERS (identical to v8.4)
# ============================================================================

# Universe
TOP_N = 40
MIN_AGE_DAYS = 63

# Signal
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
MIN_MOMENTUM_STOCKS = 20

# Positions
NUM_POSITIONS = 5
NUM_POSITIONS_RISK_OFF = 2
HOLD_DAYS = 5

# Exit renewal
HOLD_DAYS_MAX = 10
RENEWAL_PROFIT_MIN = 0.04
MOMENTUM_RENEWAL_THRESHOLD = 0.85

# Quality filter
QUALITY_VOL_MAX = 0.60
QUALITY_VOL_LOOKBACK = 63
QUALITY_MAX_SINGLE_DAY = 0.50

# Smooth drawdown scaling
DD_SCALE_TIER1 = -0.10
DD_SCALE_TIER2 = -0.20
DD_SCALE_TIER3 = -0.35
LEV_FULL       = 1.0
LEV_MID        = 0.60
LEV_FLOOR      = 0.30
CRASH_VEL_5D   = -0.06
CRASH_VEL_10D  = -0.10
CRASH_LEVERAGE  = 0.15
CRASH_COOLDOWN  = 10

# Leverage & Vol targeting
TARGET_VOL = 0.15
LEVERAGE_MAX = 1.0
VOL_LOOKBACK = 20

# Costs
INITIAL_CAPITAL = 100_000
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.001
CASH_YIELD_RATE = 0.035

# v8.4 Bull Market Override
BULL_OVERRIDE_THRESHOLD = 0.03
BULL_OVERRIDE_MIN_SCORE = 0.40

# v8.4 Adaptive Stops
STOP_DAILY_VOL_MULT = 2.5
STOP_FLOOR = -0.06
STOP_CEILING = -0.15
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03
TRAILING_VOL_BASELINE = 0.25

# v8.4 Sector Concentration
MAX_PER_SECTOR = 3

# ============================================================================
# QUARTERLY AUDIT PARAMETERS
# ============================================================================
AUDIT_INTERVAL_DAYS = 90       # Trading days between audits
AUDIT_DROP_THRESHOLD = -0.30   # -30% from pool entry price

# ============================================================================
# DATA
# ============================================================================
START_DATE = '2000-01-01'
END_DATE = '2027-01-01'

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
    # Utilities
    'NEE', 'DUK', 'SO', 'D', 'AEP',
    # Telecom
    'VZ', 'T', 'TMUS', 'CMCSA',
]

SECTOR_MAP = {
    'AAPL': 'Technology', 'MSFT': 'Technology', 'NVDA': 'Technology', 'GOOGL': 'Technology',
    'META': 'Technology', 'AVGO': 'Technology', 'ADBE': 'Technology', 'CRM': 'Technology',
    'AMD': 'Technology', 'INTC': 'Technology', 'CSCO': 'Technology', 'IBM': 'Technology',
    'TXN': 'Technology', 'QCOM': 'Technology', 'ORCL': 'Technology', 'ACN': 'Technology',
    'NOW': 'Technology', 'INTU': 'Technology', 'AMAT': 'Technology', 'MU': 'Technology',
    'LRCX': 'Technology', 'SNPS': 'Technology', 'CDNS': 'Technology', 'KLAC': 'Technology',
    'MRVL': 'Technology',
    'BRK-B': 'Financials', 'JPM': 'Financials', 'V': 'Financials', 'MA': 'Financials',
    'BAC': 'Financials', 'WFC': 'Financials', 'GS': 'Financials', 'MS': 'Financials',
    'AXP': 'Financials', 'BLK': 'Financials', 'SCHW': 'Financials', 'C': 'Financials',
    'USB': 'Financials', 'PNC': 'Financials', 'TFC': 'Financials', 'CB': 'Financials',
    'MMC': 'Financials', 'AIG': 'Financials',
    'UNH': 'Healthcare', 'JNJ': 'Healthcare', 'LLY': 'Healthcare', 'ABBV': 'Healthcare',
    'MRK': 'Healthcare', 'PFE': 'Healthcare', 'TMO': 'Healthcare', 'ABT': 'Healthcare',
    'DHR': 'Healthcare', 'AMGN': 'Healthcare', 'BMY': 'Healthcare', 'MDT': 'Healthcare',
    'ISRG': 'Healthcare', 'SYK': 'Healthcare', 'GILD': 'Healthcare', 'REGN': 'Healthcare',
    'VRTX': 'Healthcare', 'BIIB': 'Healthcare',
    'AMZN': 'Consumer', 'TSLA': 'Consumer', 'WMT': 'Consumer', 'HD': 'Consumer',
    'PG': 'Consumer', 'COST': 'Consumer', 'KO': 'Consumer', 'PEP': 'Consumer',
    'NKE': 'Consumer', 'MCD': 'Consumer', 'DIS': 'Consumer', 'SBUX': 'Consumer',
    'TGT': 'Consumer', 'LOW': 'Consumer', 'CL': 'Consumer', 'KMB': 'Consumer',
    'GIS': 'Consumer', 'EL': 'Consumer', 'MO': 'Consumer', 'PM': 'Consumer',
    'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'SLB': 'Energy',
    'EOG': 'Energy', 'OXY': 'Energy', 'MPC': 'Energy', 'PSX': 'Energy', 'VLO': 'Energy',
    'GE': 'Industrials', 'CAT': 'Industrials', 'BA': 'Industrials', 'HON': 'Industrials',
    'UNP': 'Industrials', 'RTX': 'Industrials', 'LMT': 'Industrials', 'DE': 'Industrials',
    'UPS': 'Industrials', 'FDX': 'Industrials', 'MMM': 'Industrials', 'GD': 'Industrials',
    'NOC': 'Industrials', 'EMR': 'Industrials',
    'NEE': 'Utilities', 'DUK': 'Utilities', 'SO': 'Utilities', 'D': 'Utilities', 'AEP': 'Utilities',
    'VZ': 'Telecom', 'T': 'Telecom', 'TMUS': 'Telecom', 'CMCSA': 'Telecom',
}

print("=" * 80)
print("HYDRA v8.4 — QUARTERLY AUDIT BACKTEST")
print("Base v8.4 vs Base v8.4 + Quarterly Pool Audit")
print("=" * 80)
print(f"\nBroad pool: {len(BROAD_POOL)} stocks | Top-{TOP_N} annual rotation")
print(f"Audit: Every {AUDIT_INTERVAL_DAYS} trading days | Threshold: {AUDIT_DROP_THRESHOLD:.0%} from pool entry")
print(f"Signal: Momentum {MOMENTUM_LOOKBACK}d (skip {MOMENTUM_SKIP}d) + Inverse Vol sizing")
print(f"Stops: Adaptive {STOP_FLOOR:.0%} to {STOP_CEILING:.0%} (vol-scaled) | Sector max: {MAX_PER_SECTOR}/sector")
print(f"Hold: {HOLD_DAYS}d | DD tiers: {DD_SCALE_TIER1}/{DD_SCALE_TIER2}/{DD_SCALE_TIER3}")
print()


# ============================================================================
# DATA FUNCTIONS (identical to v8.4)
# ============================================================================

def download_broad_pool() -> Dict[str, pd.DataFrame]:
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
    cache_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'

    if os.path.exists(cache_file):
        print("[Cache] Loading SPY data...")
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return df

    print("[Download] Downloading SPY...")
    df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def download_cash_yield() -> Optional[pd.Series]:
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


# ============================================================================
# ANNUAL TOP-40 SELECTION
# ============================================================================

def compute_annual_top40(price_data: Dict[str, pd.DataFrame]) -> Dict[int, List[str]]:
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    years = sorted(set(d.year for d in all_dates))

    annual_universe = {}

    for year in years:
        if year == years[0]:
            ranking_end = pd.Timestamp(f'{year}-02-01',
                tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            ranking_start = pd.Timestamp(f'{year-1}-01-01',
                tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
        else:
            ranking_end = pd.Timestamp(f'{year}-01-01',
                tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)
            ranking_start = pd.Timestamp(f'{year-1}-01-01',
                tz=all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None)

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


def compute_pool_entry_prices(price_data: Dict[str, pd.DataFrame],
                               annual_universe: Dict[int, List[str]]) -> Dict[int, Dict[str, float]]:
    """Compute the pool entry price for each stock in each year's top-40.
    Entry price = close on last trading day of the prior year."""
    pool_entry_prices = {}

    for year, symbols in annual_universe.items():
        entry_prices = {}
        for symbol in symbols:
            if symbol not in price_data:
                continue
            df = price_data[symbol]
            # Last trading day before Jan 1 of this year
            prior_year_end = pd.Timestamp(f'{year}-01-01',
                tz=df.index[0].tz if hasattr(df.index[0], 'tz') and df.index[0].tz else None)
            prior_data = df[df.index < prior_year_end]
            if len(prior_data) > 0:
                entry_prices[symbol] = float(prior_data['Close'].iloc[-1])
            elif len(df) > 0:
                # Fallback: first available price
                entry_prices[symbol] = float(df['Close'].iloc[0])
        pool_entry_prices[year] = entry_prices

    return pool_entry_prices


def compute_dollar_volume_scores(price_data: Dict[str, pd.DataFrame],
                                  date: pd.Timestamp,
                                  lookback_days: int = 252) -> Dict[str, float]:
    """Compute average daily dollar volume for ranking replacement candidates."""
    scores = {}
    for symbol, df in price_data.items():
        if date not in df.index:
            continue
        idx = df.index.get_loc(date)
        start_idx = max(0, idx - lookback_days)
        window = df.iloc[start_idx:idx + 1]
        if len(window) < 20:
            continue
        dollar_vol = (window['Close'] * window['Volume']).mean()
        scores[symbol] = dollar_vol
    return scores


# ============================================================================
# SIGNAL & REGIME FUNCTIONS (identical to v8.4)
# ============================================================================

def get_spy_trend_data(spy_data: pd.DataFrame, date: pd.Timestamp) -> Optional[Tuple[float, float]]:
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
    z = float(np.clip(k * x, -20.0, 20.0))
    return 1.0 / (1.0 + np.exp(-z))


def compute_regime_score(spy_data: pd.DataFrame, date: pd.Timestamp) -> float:
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

    composite = 0.60 * trend_score + 0.40 * vol_score
    return float(np.clip(composite, 0.0, 1.0))


def regime_score_to_positions(regime_score: float,
                               num_positions: int = NUM_POSITIONS,
                               num_positions_risk_off: int = NUM_POSITIONS_RISK_OFF,
                               spy_close: Optional[float] = None,
                               sma200: Optional[float] = None) -> int:
    if regime_score >= 0.65:
        base = num_positions
    elif regime_score >= 0.50:
        base = max(num_positions - 1, num_positions_risk_off + 1)
    elif regime_score >= 0.35:
        base = max(num_positions - 2, num_positions_risk_off + 1)
    else:
        base = num_positions_risk_off

    if (spy_close is not None and sma200 is not None
            and sma200 > 0 and regime_score > BULL_OVERRIDE_MIN_SCORE):
        pct_above = (spy_close / sma200) - 1.0
        if pct_above >= BULL_OVERRIDE_THRESHOLD:
            base = min(base + 1, num_positions)

    return base


# ============================================================================
# MOMENTUM SCORING (standard v8.4, NOT residual)
# ============================================================================

def compute_momentum_scores(price_data: Dict[str, pd.DataFrame],
                           tradeable: List[str],
                           date: pd.Timestamp,
                           all_dates: List[pd.Timestamp],
                           date_idx: int) -> Dict[str, float]:
    """Compute risk-adjusted cross-sectional momentum score (standard v8.4)."""
    scores = {}
    RISK_ADJ_VOL_WINDOW = 63

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

        momentum_raw = (close_skip / close_lookback) - 1.0
        skip_5d = (close_today / close_skip) - 1.0
        raw_score = momentum_raw - skip_5d

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


# ============================================================================
# REMAINING SIGNAL FUNCTIONS (identical to v8.4)
# ============================================================================

def compute_volatility_weights(price_data: Dict[str, pd.DataFrame],
                               selected: List[str],
                               date: pd.Timestamp) -> Dict[str, float]:
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
        returns = df['Close'].iloc[sym_idx - VOL_LOOKBACK:sym_idx + 1].pct_change().dropna()
        if len(returns) < VOL_LOOKBACK - 2:
            continue
        vol = returns.std() * np.sqrt(252)
        if vol > 0.01:
            vols[symbol] = vol

    if not vols:
        return {s: 1.0 / len(selected) for s in selected}

    raw_weights = {s: 1.0 / v for s, v in vols.items()}
    total = sum(raw_weights.values())
    return {s: w / total for s, w in raw_weights.items()}


def compute_entry_vol(price_data: Dict[str, pd.DataFrame],
                      symbol: str,
                      date: pd.Timestamp,
                      lookback: int = 20) -> Tuple[float, float]:
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
    raw_stop = -STOP_DAILY_VOL_MULT * entry_daily_vol
    return max(STOP_CEILING, min(STOP_FLOOR, raw_stop))


def compute_dynamic_leverage(spy_data: pd.DataFrame, date: pd.Timestamp) -> float:
    if date not in spy_data.index:
        return 1.0
    idx = spy_data.index.get_loc(date)
    if idx < VOL_LOOKBACK + 1:
        return 1.0
    returns = spy_data['Close'].iloc[idx - VOL_LOOKBACK:idx + 1].pct_change().dropna()
    if len(returns) < VOL_LOOKBACK - 2:
        return 1.0
    realized_vol = returns.std() * np.sqrt(252)
    if realized_vol < 0.01:
        return LEVERAGE_MAX
    leverage = TARGET_VOL / realized_vol
    return max(LEV_FLOOR, min(LEVERAGE_MAX, leverage))


def _dd_leverage(drawdown: float) -> float:
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


def get_tradeable_symbols(price_data: Dict[str, pd.DataFrame],
                         date: pd.Timestamp,
                         first_date: pd.Timestamp,
                         current_universe: List[str]) -> List[str]:
    eligible = set(current_universe)
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
    if total_days_held >= HOLD_DAYS_MAX:
        return False
    entry_price = pos.get('entry_price', current_price)
    if entry_price <= 0:
        return False
    pos_return = (current_price - entry_price) / entry_price
    if pos_return < RENEWAL_PROFIT_MIN:
        return False
    if not scores or symbol not in scores:
        return False
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


# ============================================================================
# QUARTERLY AUDIT LOGIC
# ============================================================================

def perform_quarterly_audit(current_universe: List[str],
                             pool_entry_prices: Dict[str, float],
                             price_data: Dict[str, pd.DataFrame],
                             date: pd.Timestamp,
                             all_dates: List[pd.Timestamp],
                             date_idx: int) -> Tuple[List[str], Dict[str, float], List[dict]]:
    """
    Check each stock in the pool against its entry price.
    If dropped >= 30%, replace with next best by dollar volume from broad pool.

    Returns:
        updated_universe: new list of 40 stocks
        updated_entry_prices: entry prices with replacements updated
        audit_events: list of dicts describing what happened
    """
    audit_events = []
    expelled = []

    # Check each stock in pool
    for symbol in current_universe:
        if symbol not in pool_entry_prices:
            continue
        entry_price = pool_entry_prices[symbol]
        if entry_price <= 0:
            continue

        # Get current price
        if symbol not in price_data or date not in price_data[symbol].index:
            continue
        current_price = float(price_data[symbol].loc[date, 'Close'])
        pct_change = (current_price / entry_price) - 1.0

        if pct_change <= AUDIT_DROP_THRESHOLD:
            expelled.append(symbol)
            audit_events.append({
                'date': date,
                'action': 'expelled',
                'symbol': symbol,
                'entry_price': entry_price,
                'current_price': current_price,
                'pct_change': pct_change,
            })

    if not expelled:
        return current_universe, pool_entry_prices, audit_events

    # Find replacements from broad pool (not already in universe)
    current_set = set(current_universe) - set(expelled)
    dollar_scores = compute_dollar_volume_scores(price_data, date)

    # Rank candidates not in current pool
    candidates = [(s, sc) for s, sc in dollar_scores.items()
                  if s in BROAD_POOL and s not in current_set]
    candidates.sort(key=lambda x: x[1], reverse=True)

    # Build updated universe
    updated_universe = [s for s in current_universe if s not in expelled]
    updated_entry_prices = {s: p for s, p in pool_entry_prices.items() if s not in expelled}

    replacements_made = 0
    for candidate, _ in candidates:
        if len(updated_universe) >= TOP_N:
            break
        if candidate not in price_data or date not in price_data[candidate].index:
            continue

        # Entry price for replacement = current price at audit date
        replacement_price = float(price_data[candidate].loc[date, 'Close'])
        updated_universe.append(candidate)
        updated_entry_prices[candidate] = replacement_price
        replacements_made += 1

        audit_events.append({
            'date': date,
            'action': 'replaced_by',
            'symbol': candidate,
            'entry_price': replacement_price,
            'current_price': replacement_price,
            'pct_change': 0.0,
        })

    print(f"  [AUDIT] {date.strftime('%Y-%m-%d')}: "
          f"Expelled {len(expelled)} ({', '.join(expelled)}) | "
          f"Replaced with {replacements_made} new stocks")

    return updated_universe, updated_entry_prices, audit_events


# ============================================================================
# CORE BACKTEST ENGINE
# ============================================================================

def run_backtest(price_data: Dict[str, pd.DataFrame],
                 annual_universe: Dict[int, List[str]],
                 spy_data: pd.DataFrame,
                 cash_yield_daily: Optional[pd.Series] = None,
                 enable_audit: bool = False,
                 pool_entry_prices_by_year: Optional[Dict[int, Dict[str, float]]] = None,
                 label: str = "BASE") -> Dict:

    print(f"\n{'=' * 80}")
    print(f"RUNNING {label} BACKTEST {'(with Quarterly Audit)' if enable_audit else '(no audit)'}")
    print(f"{'=' * 80}")

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")

    cash = float(INITIAL_CAPITAL)
    positions = {}
    portfolio_values = []
    trades = []
    stop_events = []
    audit_log = []

    peak_value = float(INITIAL_CAPITAL)
    crash_cooldown = 0

    risk_on_days = 0
    risk_off_days = 0

    current_year = None

    # Audit state
    current_universe_list = []
    current_pool_entry_prices = {}
    days_since_last_audit = 0
    total_audits = 0
    total_expelled = 0

    for i, date in enumerate(all_dates):
        # --- Year change: reset universe ---
        if date.year != current_year:
            current_year = date.year
            current_universe_list = list(annual_universe.get(current_year, []))
            if enable_audit and pool_entry_prices_by_year:
                current_pool_entry_prices = dict(pool_entry_prices_by_year.get(current_year, {}))
            days_since_last_audit = 0

        # --- Quarterly Audit (only in audit mode) ---
        if enable_audit and days_since_last_audit >= AUDIT_INTERVAL_DAYS:
            days_since_last_audit = 0
            total_audits += 1

            updated_universe, updated_prices, events = perform_quarterly_audit(
                current_universe_list, current_pool_entry_prices,
                price_data, date, all_dates, i
            )

            expelled_symbols = [e['symbol'] for e in events if e['action'] == 'expelled']
            replacement_symbols = [e['symbol'] for e in events if e['action'] == 'replaced_by']
            total_expelled += len(expelled_symbols)
            audit_log.extend(events)

            # Force sell positions in expelled stocks, 1:1 swap with replacements
            replacement_idx = 0
            for symbol in expelled_symbols:
                if symbol in positions:
                    pos = positions[symbol]
                    if symbol in price_data and date in price_data[symbol].index:
                        exit_price = float(price_data[symbol].loc[date, 'Close'])
                        shares = pos['shares']
                        proceeds = shares * exit_price
                        commission = shares * COMMISSION_PER_SHARE
                        cash += proceeds - commission
                        pnl = (exit_price - pos['entry_price']) * shares - commission

                        trades.append({
                            'symbol': symbol,
                            'entry_date': pos['entry_date'],
                            'exit_date': date,
                            'exit_reason': 'audit_expelled',
                            'pnl': pnl,
                            'return': pnl / (pos['entry_price'] * shares),
                        })

                        # 1:1 swap: buy replacement with same capital
                        if replacement_idx < len(replacement_symbols):
                            rep_symbol = replacement_symbols[replacement_idx]
                            replacement_idx += 1
                            if rep_symbol in price_data and date in price_data[rep_symbol].index:
                                swap_capital = proceeds - commission
                                rep_price = float(price_data[rep_symbol].loc[date, 'Close'])
                                if rep_price > 0 and swap_capital > 100:
                                    rep_shares = swap_capital / rep_price
                                    rep_cost = rep_shares * rep_price
                                    rep_commission = rep_shares * COMMISSION_PER_SHARE
                                    entry_vol, entry_daily_vol = compute_entry_vol(
                                        price_data, rep_symbol, date)

                                    positions[rep_symbol] = {
                                        'entry_price': rep_price,
                                        'shares': rep_shares,
                                        'entry_date': date,
                                        'entry_idx': i,
                                        'original_entry_idx': i,
                                        'high_price': rep_price,
                                        'entry_vol': entry_vol,
                                        'entry_daily_vol': entry_daily_vol,
                                        'sector': SECTOR_MAP.get(rep_symbol, 'Unknown'),
                                    }
                                    cash -= rep_cost + rep_commission

                        del positions[symbol]

            current_universe_list = updated_universe
            current_pool_entry_prices = updated_prices

        days_since_last_audit += 1

        tradeable_symbols = get_tradeable_symbols(price_data, date, first_date, current_universe_list)

        # --- Calculate portfolio value ---
        portfolio_value = cash
        for symbol, pos in list(positions.items()):
            if symbol in price_data and date in price_data[symbol].index:
                price = price_data[symbol].loc[date, 'Close']
                portfolio_value += pos['shares'] * price

        if portfolio_value > peak_value:
            peak_value = portfolio_value

        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        regime_score = compute_regime_score(spy_data, date)
        is_risk_on = regime_score >= 0.50
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        dd_leverage_val, crash_cooldown = compute_smooth_leverage(
            drawdown, portfolio_values, max(i - 1, 0), crash_cooldown
        )

        vol_leverage = compute_dynamic_leverage(spy_data, date)
        current_leverage = max(min(dd_leverage_val, vol_leverage), LEV_FLOOR)

        spy_trend = get_spy_trend_data(spy_data, date)
        if spy_trend is not None:
            spy_close_now, sma200_now = spy_trend
            max_positions = regime_score_to_positions(regime_score,
                                                      spy_close=spy_close_now,
                                                      sma200=sma200_now)
        else:
            max_positions = regime_score_to_positions(regime_score)

        # Daily costs
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            daily_margin = MARGIN_RATE / 252 * borrowed
            cash -= daily_margin

        if cash > 0:
            if cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

        quality_symbols = compute_quality_filter(price_data, tradeable_symbols, date)
        current_scores = compute_momentum_scores(price_data, quality_symbols, date, all_dates, i)

        # --- Close positions ---
        for symbol in list(positions.keys()):
            pos = positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue

            current_price = price_data[symbol].loc[date, 'Close']
            exit_reason = None

            days_held = i - pos['entry_idx']
            total_days_held = i - pos['original_entry_idx']
            if days_held >= HOLD_DAYS:
                if should_renew_position(symbol, pos, current_price,
                                        total_days_held, current_scores):
                    pos['entry_idx'] = i
                else:
                    exit_reason = 'hold_expired'

            pos_return = (current_price - pos['entry_price']) / pos['entry_price']
            adaptive_stop = compute_adaptive_stop(pos.get('entry_daily_vol', 0.016))
            if pos_return <= adaptive_stop:
                exit_reason = 'position_stop'

            if current_price > pos['high_price']:
                pos['high_price'] = current_price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                vol_ratio = pos.get('entry_vol', TRAILING_VOL_BASELINE) / TRAILING_VOL_BASELINE
                scaled_trailing = TRAILING_STOP_PCT * vol_ratio
                trailing_level = pos['high_price'] * (1 - scaled_trailing)
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'

            if exit_reason is None and len(positions) > max_positions:
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
            available_scores = {s: sc for s, sc in current_scores.items() if s not in positions}

            if len(current_scores) >= MIN_MOMENTUM_STOCKS and len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                sector_filtered = filter_by_sector_concentration(ranked, positions)
                selected = sector_filtered[:needed]

                weights = compute_volatility_weights(price_data, selected, date)
                effective_capital = cash * current_leverage * 0.95

                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue

                    entry_price = price_data[symbol].loc[date, 'Close']
                    if entry_price <= 0:
                        continue

                    weight = weights.get(symbol, 1.0 / len(selected))
                    position_value = effective_capital * weight

                    max_per_position = cash * 0.40
                    position_value = min(position_value, max_per_position)

                    shares = position_value / entry_price
                    cost = shares * entry_price
                    commission = shares * COMMISSION_PER_SHARE

                    if cost + commission <= cash * 0.90:
                        entry_vol, entry_daily_vol = compute_entry_vol(price_data, symbol, date)

                        positions[symbol] = {
                            'entry_price': entry_price,
                            'shares': shares,
                            'entry_date': date,
                            'entry_idx': i,
                            'original_entry_idx': i,
                            'high_price': entry_price,
                            'entry_vol': entry_vol,
                            'entry_daily_vol': entry_daily_vol,
                            'sector': SECTOR_MAP.get(symbol, 'Unknown'),
                        }
                        cash -= cost + commission

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

        if i % 252 == 0 and i > 0:
            year_num = i // 252
            regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
            prot_str = f" [DD_SCALE {dd_leverage_val:.0%}]" if dd_leverage_val < LEV_FULL else ""
            audit_str = f" | Audits: {total_audits}, Expelled: {total_expelled}" if enable_audit else ""
            print(f"  Year {year_num}: ${portfolio_value:,.0f} | DD: {drawdown:.1%} | "
                  f"Lev: {current_leverage:.2f}x | {regime_str}{prot_str} | "
                  f"Pos: {len(positions)}{audit_str}")

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'trades': pd.DataFrame(trades) if trades else pd.DataFrame(),
        'stop_events': pd.DataFrame(stop_events) if stop_events else pd.DataFrame(),
        'final_value': portfolio_values[-1]['value'] if portfolio_values else INITIAL_CAPITAL,
        'annual_universe': annual_universe,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
        'audit_log': audit_log,
        'total_audits': total_audits,
        'total_expelled': total_expelled,
    }


# ============================================================================
# METRICS
# ============================================================================

def calculate_metrics(results: Dict) -> Dict:
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

    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else volatility
    sortino = cagr / downside_vol if downside_vol > 0 else 0

    win_rate = (trades_df['pnl'] > 0).mean() if len(trades_df) > 0 else 0
    avg_trade = trades_df['pnl'].mean() if len(trades_df) > 0 else 0
    avg_winner = trades_df.loc[trades_df['pnl'] > 0, 'pnl'].mean() if len(trades_df) > 0 and (trades_df['pnl'] > 0).any() else 0
    avg_loser = trades_df.loc[trades_df['pnl'] < 0, 'pnl'].mean() if len(trades_df) > 0 and (trades_df['pnl'] < 0).any() else 0

    exit_reasons = trades_df['exit_reason'].value_counts().to_dict() if 'exit_reason' in trades_df.columns and len(trades_df) > 0 else {}

    protection_days = df['in_protection'].sum()

    risk_off_pct = results['risk_off_days'] / max(1, results['risk_on_days'] + results['risk_off_days']) * 100

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
        'risk_off_pct': risk_off_pct,
        'annual_returns': annual_returns,
        'best_year': annual_returns.max() if len(annual_returns) > 0 else 0,
        'worst_year': annual_returns.min() if len(annual_returns) > 0 else 0,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    # 1. Download / load data
    price_data = download_broad_pool()
    print(f"\nSymbols available: {len(price_data)}")

    spy_data = download_spy()
    print(f"SPY data: {len(spy_data)} trading days")

    cash_yield_daily = download_cash_yield()

    # 2. Compute annual top-40
    print("\n--- Computing Annual Top-40 ---")
    annual_universe = compute_annual_top40(price_data)

    # 3. Compute pool entry prices for audit
    print("\n--- Computing Pool Entry Prices ---")
    pool_entry_prices = compute_pool_entry_prices(price_data, annual_universe)
    for year in sorted(pool_entry_prices.keys())[:5]:
        n = len(pool_entry_prices[year])
        print(f"  {year}: {n} stocks with entry prices")
    print(f"  ... ({len(pool_entry_prices)} years total)")

    # 4. Run BASE backtest (no audit)
    results_base = run_backtest(
        price_data, annual_universe, spy_data, cash_yield_daily,
        enable_audit=False, label="BASE"
    )
    metrics_base = calculate_metrics(results_base)

    # 5. Run AUDIT backtest
    results_audit = run_backtest(
        price_data, annual_universe, spy_data, cash_yield_daily,
        enable_audit=True, pool_entry_prices_by_year=pool_entry_prices,
        label="AUDIT"
    )
    metrics_audit = calculate_metrics(results_audit)

    # 6. Print comparison
    print("\n" + "=" * 80)
    print("RESULTS — BASE vs QUARTERLY AUDIT COMPARISON")
    print("=" * 80)

    print(f"\n{'Metric':<25} {'BASE (no audit)':>18} {'AUDIT (quarterly)':>18} {'Delta':>12}")
    print("-" * 75)
    print(f"{'CAGR':<25} {metrics_base['cagr']:>17.2%} {metrics_audit['cagr']:>17.2%} {metrics_audit['cagr']-metrics_base['cagr']:>+11.2%}")
    print(f"{'Sharpe':<25} {metrics_base['sharpe']:>18.3f} {metrics_audit['sharpe']:>18.3f} {metrics_audit['sharpe']-metrics_base['sharpe']:>+12.3f}")
    print(f"{'Sortino':<25} {metrics_base['sortino']:>18.3f} {metrics_audit['sortino']:>18.3f} {metrics_audit['sortino']-metrics_base['sortino']:>+12.3f}")
    print(f"{'Max Drawdown':<25} {metrics_base['max_drawdown']:>17.1%} {metrics_audit['max_drawdown']:>17.1%} {metrics_audit['max_drawdown']-metrics_base['max_drawdown']:>+11.1%}")
    print(f"{'Calmar':<25} {metrics_base['calmar']:>18.3f} {metrics_audit['calmar']:>18.3f} {metrics_audit['calmar']-metrics_base['calmar']:>+12.3f}")
    print(f"{'Final Value':<25} ${metrics_base['final_value']:>16,.0f} ${metrics_audit['final_value']:>16,.0f}")
    print(f"{'Volatility':<25} {metrics_base['volatility']:>17.2%} {metrics_audit['volatility']:>17.2%}")
    print(f"{'Trades':<25} {metrics_base['trades']:>18,} {metrics_audit['trades']:>18,}")
    print(f"{'Win Rate':<25} {metrics_base['win_rate']:>17.1%} {metrics_audit['win_rate']:>17.1%}")

    # Audit-specific stats
    print(f"\n--- Quarterly Audit Stats ---")
    print(f"Total audits performed:  {results_audit['total_audits']}")
    print(f"Total stocks expelled:   {results_audit['total_expelled']}")
    if results_audit['total_audits'] > 0:
        print(f"Avg expelled per audit:  {results_audit['total_expelled'] / results_audit['total_audits']:.1f}")

    # Exit reasons comparison
    print(f"\n--- Exit Reasons ---")
    all_reasons = set(list(metrics_base['exit_reasons'].keys()) + list(metrics_audit['exit_reasons'].keys()))
    for reason in sorted(all_reasons):
        base_count = metrics_base['exit_reasons'].get(reason, 0)
        audit_count = metrics_audit['exit_reasons'].get(reason, 0)
        print(f"  {reason:25s}: {base_count:>6,} vs {audit_count:>6,}")

    # Annual returns comparison
    print(f"\n--- Annual Returns ---")
    print(f"{'Year':<8} {'BASE':>10} {'AUDIT':>10} {'Delta':>10}")
    print("-" * 40)
    base_annual = metrics_base['annual_returns']
    audit_annual = metrics_audit['annual_returns']
    for year_dt in base_annual.index:
        y = year_dt.year
        b = base_annual.loc[year_dt]
        a = audit_annual.loc[year_dt] if year_dt in audit_annual.index else 0
        print(f"{y:<8} {b:>9.1%} {a:>9.1%} {a - b:>+9.1%}")

    # Audit event log
    if results_audit['audit_log']:
        print(f"\n--- Audit Event Log (first 20) ---")
        for event in results_audit['audit_log'][:20]:
            if event['action'] == 'expelled':
                print(f"  {event['date'].strftime('%Y-%m-%d')} EXPELLED {event['symbol']:6s} "
                      f"| Entry: ${event['entry_price']:>8.2f} -> ${event['current_price']:>8.2f} "
                      f"({event['pct_change']:+.1%})")
            else:
                print(f"  {event['date'].strftime('%Y-%m-%d')} REPLACED {event['symbol']:6s} "
                      f"| Entry: ${event['entry_price']:>8.2f}")

    # ================================================================
    # PHASE 2: HYDRA COMPLETE (COMPASS + Rattlesnake + EFA overlay)
    # Replicates exp60_hydra_efa.py logic to get full HYDRA comparison
    # ================================================================

    print(f"\n{'=' * 80}")
    print("PHASE 2: HYDRA COMPLETE OVERLAY (COMPASS + Rattlesnake + EFA)")
    print(f"{'=' * 80}")

    # Load Rattlesnake and EFA data
    rattle_path = 'backtests/rattlesnake_daily.csv'
    if not os.path.exists(rattle_path):
        print(f"  WARNING: {rattle_path} not found. Skipping HYDRA overlay.")
        print("  Run the Rattlesnake backtest first to enable full HYDRA comparison.")
    else:
        rattle = pd.read_csv(rattle_path, index_col=0, parse_dates=True)
        r_ret = rattle['value'].pct_change()
        r_exposure = rattle['exposure']

        # Load or download EFA
        efa_cache = 'data_cache/efa_daily.pkl'
        if os.path.exists(efa_cache):
            print("  [Cache] Loading EFA data...")
            with open(efa_cache, 'rb') as f:
                efa = pickle.load(f)
        else:
            print("  [Download] Downloading EFA data...")
            efa_raw = yf.download('EFA', start='2001-01-01', end='2027-01-01', progress=False)
            if isinstance(efa_raw.columns, pd.MultiIndex):
                efa_raw.columns = efa_raw.columns.get_level_values(0)
            efa = efa_raw[['Close']].rename(columns={'Close': 'close'})
            efa['ret'] = efa['close'].pct_change()
            efa['sma200'] = efa['close'].rolling(200).mean()
            os.makedirs('data_cache', exist_ok=True)
            with open(efa_cache, 'wb') as f:
                pickle.dump(efa, f)

        EFA_SMA_PERIOD = 200
        MAX_COMPASS_ALLOC = 0.75
        BASE_COMPASS_ALLOC = 0.50
        BASE_RATTLE_ALLOC = 0.50

        def run_hydra_overlay(compass_pv_df, label_name):
            """Run HYDRA overlay: COMPASS returns + Rattlesnake + EFA (regime-filtered)."""
            c_ret = compass_pv_df.set_index('date')['value'].pct_change()

            df_overlay = pd.DataFrame({
                'c_ret': c_ret,
                'r_ret': r_ret,
                'r_exposure': r_exposure,
            }).dropna()

            c_account = INITIAL_CAPITAL * BASE_COMPASS_ALLOC
            r_account = INITIAL_CAPITAL * BASE_RATTLE_ALLOC
            efa_value = 0.0

            portfolio_values_h = []

            for idx in range(len(df_overlay)):
                date = df_overlay.index[idx]
                r_exp = df_overlay['r_exposure'].iloc[idx]
                total_value = c_account + r_account + efa_value

                # Cash recycling (R -> C)
                r_idle = r_account * (1.0 - r_exp)
                max_c_account = total_value * MAX_COMPASS_ALLOC
                max_recyclable = max(0, max_c_account - c_account)
                recycle_amount = min(r_idle, max_recyclable)

                c_effective = c_account + recycle_amount
                r_effective = r_account - recycle_amount

                # Remaining idle cash for EFA
                r_still_idle = r_effective * (1.0 - r_exp)
                idle_cash = r_still_idle

                # EFA regime filter
                efa_eligible = True
                if date in efa.index:
                    sma = efa.loc[date, 'sma200']
                    close = efa.loc[date, 'close']
                    if pd.notna(sma) and close < sma:
                        efa_eligible = False

                target_efa = idle_cash if (date in efa.index and efa_eligible) else 0.0

                if target_efa > efa_value:
                    buy_amount = target_efa - efa_value
                    r_effective -= buy_amount
                    efa_value += buy_amount
                elif target_efa < efa_value:
                    sell_amount = efa_value - target_efa
                    efa_value -= sell_amount
                    r_effective += sell_amount

                # Apply daily returns
                c_r = df_overlay['c_ret'].iloc[idx]
                r_r = df_overlay['r_ret'].iloc[idx]
                efa_r = 0.0
                if date in efa.index and efa_value > 0:
                    efa_r = efa.loc[date, 'ret']
                    if pd.isna(efa_r):
                        efa_r = 0.0

                c_account_new = c_effective * (1 + c_r)
                r_account_new = r_effective * (1 + r_r)
                efa_value_new = efa_value * (1 + efa_r)

                recycled_after = recycle_amount * (1 + c_r)
                c_account = c_account_new - recycled_after
                r_account = r_account_new + recycled_after
                efa_value = efa_value_new

                total_new = c_account + r_account + efa_value
                portfolio_values_h.append({'date': date, 'value': total_new})

            pv = pd.DataFrame(portfolio_values_h).set_index('date')['value']
            years = len(pv) / 252
            final = pv.iloc[-1]
            cagr = (final / INITIAL_CAPITAL) ** (1 / years) - 1
            maxdd = (pv / pv.cummax() - 1).min()
            returns = pv.pct_change().dropna()
            sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
            vol = returns.std() * np.sqrt(252)
            downside = returns[returns < 0]
            sortino = returns.mean() / downside.std() * np.sqrt(252) if len(downside) > 0 and downside.std() > 0 else 0
            calmar = cagr / abs(maxdd) if maxdd != 0 else 0

            annual = pv.resample('YE').last().pct_change().dropna()

            return {
                'pv': pv,
                'cagr': cagr,
                'maxdd': maxdd,
                'sharpe': sharpe,
                'vol': vol,
                'sortino': sortino,
                'calmar': calmar,
                'final': final,
                'annual': annual,
            }

        # Run HYDRA overlay for both variants
        print("\n  Running HYDRA overlay for BASE COMPASS...")
        hydra_base = run_hydra_overlay(results_base['portfolio_values'], "BASE")
        print(f"    HYDRA BASE: CAGR={hydra_base['cagr']:.2%} | MaxDD={hydra_base['maxdd']:.2%} | Sharpe={hydra_base['sharpe']:.2f}")

        print("  Running HYDRA overlay for AUDIT COMPASS...")
        hydra_audit = run_hydra_overlay(results_audit['portfolio_values'], "AUDIT")
        print(f"    HYDRA AUDIT: CAGR={hydra_audit['cagr']:.2%} | MaxDD={hydra_audit['maxdd']:.2%} | Sharpe={hydra_audit['sharpe']:.2f}")

        # Print HYDRA complete comparison
        print(f"\n{'=' * 80}")
        print("RESULTS — HYDRA COMPLETE: BASE vs QUARTERLY AUDIT")
        print("(COMPASS + Rattlesnake + EFA regime-filtered)")
        print(f"{'=' * 80}")

        print(f"\n{'Metric':<25} {'HYDRA BASE':>18} {'HYDRA AUDIT':>18} {'Delta':>12}")
        print("-" * 75)
        print(f"{'CAGR':<25} {hydra_base['cagr']:>17.2%} {hydra_audit['cagr']:>17.2%} {hydra_audit['cagr']-hydra_base['cagr']:>+11.2%}")
        print(f"{'Sharpe':<25} {hydra_base['sharpe']:>18.3f} {hydra_audit['sharpe']:>18.3f} {hydra_audit['sharpe']-hydra_base['sharpe']:>+12.3f}")
        print(f"{'Sortino':<25} {hydra_base['sortino']:>18.3f} {hydra_audit['sortino']:>18.3f} {hydra_audit['sortino']-hydra_base['sortino']:>+12.3f}")
        print(f"{'Max Drawdown':<25} {hydra_base['maxdd']:>17.2%} {hydra_audit['maxdd']:>17.2%} {hydra_audit['maxdd']-hydra_base['maxdd']:>+11.2%}")
        print(f"{'Calmar':<25} {hydra_base['calmar']:>18.3f} {hydra_audit['calmar']:>18.3f} {hydra_audit['calmar']-hydra_base['calmar']:>+12.3f}")
        print(f"{'Final Value':<25} ${hydra_base['final']:>16,.0f} ${hydra_audit['final']:>16,.0f}")
        print(f"{'Volatility':<25} {hydra_base['vol']:>17.2%} {hydra_audit['vol']:>17.2%}")

        # Annual comparison (HYDRA level)
        print(f"\n--- HYDRA Annual Returns ---")
        print(f"{'Year':<8} {'HYDRA BASE':>12} {'HYDRA AUDIT':>12} {'Delta':>10}")
        print("-" * 44)
        for year_dt in hydra_base['annual'].index:
            y = year_dt.year
            b = hydra_base['annual'].loc[year_dt]
            a = hydra_audit['annual'].loc[year_dt] if year_dt in hydra_audit['annual'].index else 0
            print(f"{y:<8} {b:>11.1%} {a:>11.1%} {a - b:>+9.1%}")

        # Save HYDRA overlay results
        hydra_base['pv'].to_csv('backtests/quarterly_audit_hydra_base_daily.csv')
        hydra_audit['pv'].to_csv('backtests/quarterly_audit_hydra_audit_daily.csv')

    # ================================================================
    # SAVE ALL RESULTS
    # ================================================================

    os.makedirs('backtests', exist_ok=True)

    results_base['portfolio_values'].to_csv('backtests/quarterly_audit_base_daily.csv', index=False)
    results_audit['portfolio_values'].to_csv('backtests/quarterly_audit_audit_daily.csv', index=False)

    if len(results_audit['trades']) > 0:
        results_audit['trades'].to_csv('backtests/quarterly_audit_trades.csv', index=False)

    if results_audit['audit_log']:
        audit_df = pd.DataFrame(results_audit['audit_log'])
        audit_df.to_csv('backtests/quarterly_audit_event_log.csv', index=False)

    # Save combined results as pickle (self-generated data only)
    output_file = 'backtests/quarterly_audit_results.pkl'
    with open(output_file, 'wb') as f:
        pickle.dump({
            'base_metrics': metrics_base,
            'audit_metrics': metrics_audit,
            'base_portfolio': results_base['portfolio_values'],
            'audit_portfolio': results_audit['portfolio_values'],
            'audit_trades': results_audit['trades'],
            'audit_log': results_audit['audit_log'],
        }, f)

    print(f"\nResults saved:")
    print(f"  COMPASS Base daily:  backtests/quarterly_audit_base_daily.csv")
    print(f"  COMPASS Audit daily: backtests/quarterly_audit_audit_daily.csv")
    print(f"  Audit trades:        backtests/quarterly_audit_trades.csv")
    print(f"  Audit log:           backtests/quarterly_audit_event_log.csv")
    if os.path.exists(rattle_path):
        print(f"  HYDRA Base daily:    backtests/quarterly_audit_hydra_base_daily.csv")
        print(f"  HYDRA Audit daily:   backtests/quarterly_audit_hydra_audit_daily.csv")
    print(f"  Pickle:              {output_file}")

    print(f"\n{'=' * 80}")
    print("QUARTERLY AUDIT BACKTEST COMPLETE")
    print(f"{'=' * 80}")
