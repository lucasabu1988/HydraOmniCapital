#!/usr/bin/env python3
"""
EXP59: HYDRA — COMPASS + Rattlesnake with Cash Recycling
=========================================================
Integrated backtest running both strategies simultaneously with a shared
capital pool. When Rattlesnake has idle cash, it flows to COMPASS (capped
at 75% total allocation to COMPASS).

Architecture:
  - Single capital pool ($100K)
  - Base allocation: 50% COMPASS, 50% Rattlesnake
  - Cash recycling: Rattlesnake idle cash -> COMPASS (cap 75% max)
  - Each strategy manages its own positions independently
  - Daily rebalancing of available capital

Target (from proxy simulation):
  CAGR ~12.9%, MaxDD ~-24%, Sharpe ~1.02
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle  # required for loading existing cached data files
import os
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

SEED = 666
np.random.seed(SEED)

# ============================================================================
# SHARED PARAMETERS
# ============================================================================
INITIAL_CAPITAL = 100_000
COMMISSION_PER_SHARE = 0.001  # COMPASS uses per-share
COMMISSION_BPS = 5            # Rattlesnake uses BPS

# Cash recycling
BASE_COMPASS_ALLOC = 0.50     # Base allocation to COMPASS
BASE_RATTLE_ALLOC = 0.50      # Base allocation to Rattlesnake
MAX_COMPASS_ALLOC = 0.75      # Cap: max COMPASS can get with recycling
CASH_YIELD_RATE = 0.035       # Fallback cash yield

# Data
START_DATE = '2000-01-01'
END_DATE = '2027-01-01'

# ============================================================================
# COMPASS PARAMETERS (from v8.4 / exp55_baseline_774)
# ============================================================================
C_TOP_N = 40
C_MIN_AGE_DAYS = 63
C_MOMENTUM_LOOKBACK = 90
C_MOMENTUM_SKIP = 5
C_MIN_MOMENTUM_STOCKS = 20
C_NUM_POSITIONS = 5
C_NUM_POSITIONS_RISK_OFF = 2
C_HOLD_DAYS = 5
C_POSITION_STOP_LOSS = -0.08
C_TRAILING_ACTIVATION = 0.05
C_TRAILING_STOP_PCT = 0.03
C_HOLD_DAYS_MAX = 10
C_RENEWAL_PROFIT_MIN = 0.04
C_MOMENTUM_RENEWAL_THRESHOLD = 0.85
C_QUALITY_VOL_MAX = 0.60
C_QUALITY_VOL_LOOKBACK = 63
C_QUALITY_MAX_SINGLE_DAY = 0.50
C_DD_SCALE_TIER1 = -0.10
C_DD_SCALE_TIER2 = -0.20
C_DD_SCALE_TIER3 = -0.35
C_LEV_FULL = 1.0
C_LEV_MID = 0.60
C_LEV_FLOOR = 0.30
C_CRASH_VEL_5D = -0.06
C_CRASH_VEL_10D = -0.10
C_CRASH_LEVERAGE = 0.15
C_CRASH_COOLDOWN = 10
C_TARGET_VOL = 0.15
C_LEVERAGE_MAX = 1.0
C_VOL_LOOKBACK = 20
C_BULL_OVERRIDE_THRESHOLD = 0.03
C_BULL_OVERRIDE_MIN_SCORE = 0.40
C_STOP_DAILY_VOL_MULT = 2.5
C_STOP_FLOOR = -0.06
C_STOP_CEILING = -0.15
C_TRAILING_VOL_BASELINE = 0.25
C_MAX_PER_SECTOR = 3
C_MARGIN_RATE = 0.06

# ============================================================================
# RATTLESNAKE PARAMETERS (from rattlesnake_v1)
# ============================================================================
R_DROP_THRESHOLD = -0.08
R_DROP_LOOKBACK = 5
R_RSI_PERIOD = 5
R_RSI_THRESHOLD = 25
R_TREND_SMA = 200
R_PROFIT_TARGET = 0.04
R_MAX_HOLD_DAYS = 8
R_STOP_LOSS = -0.05
R_MAX_POSITIONS = 5
R_POSITION_SIZE = 0.20
R_REGIME_SMA = 200
R_REGIME_CONFIRM = 3
R_MAX_POS_RISK_OFF = 2
R_VIX_PANIC = 35

# ============================================================================
# COMPASS SECTOR MAP
# ============================================================================
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

# Rattlesnake universe
R_UNIVERSE = [
    'AAPL', 'ABBV', 'ABT', 'ACN', 'ADBE', 'AIG', 'AMGN', 'AMT', 'AMZN', 'AVGO',
    'AXP', 'BA', 'BAC', 'BK', 'BKNG', 'BLK', 'BMY', 'BRK-B', 'C', 'CAT',
    'CHTR', 'CL', 'CMCSA', 'COF', 'COP', 'COST', 'CRM', 'CSCO', 'CVS', 'CVX',
    'DE', 'DHR', 'DIS', 'DOW', 'DUK', 'EMR', 'EXC', 'F', 'FDX', 'GD',
    'GE', 'GILD', 'GM', 'GOOG', 'GS', 'HD', 'HON', 'IBM', 'INTC', 'INTU',
    'JNJ', 'JPM', 'KHC', 'KO', 'LIN', 'LLY', 'LMT', 'LOW', 'MA', 'MCD',
    'MDLZ', 'MDT', 'MET', 'META', 'MMM', 'MO', 'MRK', 'MS', 'MSFT', 'NEE',
    'NFLX', 'NKE', 'NVDA', 'ORCL', 'PEP', 'PFE', 'PG', 'PM', 'PYPL', 'QCOM',
    'RTX', 'SBUX', 'SCHW', 'SO', 'SPG', 'T', 'TGT', 'TMO', 'TMUS', 'TSLA',
    'TXN', 'UNH', 'UNP', 'UPS', 'USB', 'V', 'VZ', 'WBA', 'WFC', 'WMT', 'XOM',
]


# ============================================================================
# COMPASS FUNCTIONS (from exp55_baseline_774)
# ============================================================================

def _sigmoid(x, k=15.0):
    z = float(np.clip(k * x, -20.0, 20.0))
    return 1.0 / (1.0 + np.exp(-z))


def compute_regime_score(spy_data, date):
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
    sma200 = float(spy_close.iloc[-200:].mean())
    sma50 = float(spy_close.iloc[-50:].mean())
    if sma200 <= 0:
        return 0.5
    dist_200 = (current / sma200) - 1.0
    sig_200 = _sigmoid(dist_200, k=15.0)
    cross = (sma50 / sma200) - 1.0 if sma200 > 0 else 0
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
        hist_returns = returns.iloc[-252:]
        rolling_vol = hist_returns.rolling(window=10).std() * np.sqrt(252)
        rolling_vol = rolling_vol.dropna()
        if len(rolling_vol) >= 20 and current_vol > 0:
            pct_rank = float((rolling_vol <= current_vol).sum()) / len(rolling_vol)
            vol_score = 1.0 - pct_rank
    composite = 0.60 * trend_score + 0.40 * vol_score
    return float(np.clip(composite, 0.0, 1.0))


def get_spy_trend_data(spy_data, date):
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


def regime_score_to_positions(regime_score, spy_close=None, sma200=None):
    if regime_score >= 0.65:
        base = C_NUM_POSITIONS
    elif regime_score >= 0.50:
        base = max(C_NUM_POSITIONS - 1, C_NUM_POSITIONS_RISK_OFF + 1)
    elif regime_score >= 0.35:
        base = max(C_NUM_POSITIONS - 2, C_NUM_POSITIONS_RISK_OFF + 1)
    else:
        base = C_NUM_POSITIONS_RISK_OFF
    if (spy_close is not None and sma200 is not None
            and sma200 > 0 and regime_score > C_BULL_OVERRIDE_MIN_SCORE):
        pct_above = (spy_close / sma200) - 1.0
        if pct_above >= C_BULL_OVERRIDE_THRESHOLD:
            base = min(base + 1, C_NUM_POSITIONS)
    return base


def compute_momentum_scores(price_data, tradeable, date, all_dates, date_idx):
    scores = {}
    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        needed = C_MOMENTUM_LOOKBACK + C_MOMENTUM_SKIP
        try:
            sym_idx = df.index.get_loc(date)
        except KeyError:
            continue
        if sym_idx < needed:
            continue
        close_today = df['Close'].iloc[sym_idx]
        close_skip = df['Close'].iloc[sym_idx - C_MOMENTUM_SKIP]
        close_lookback = df['Close'].iloc[sym_idx - C_MOMENTUM_LOOKBACK]
        if close_lookback <= 0 or close_skip <= 0 or close_today <= 0:
            continue
        momentum_raw = (close_skip / close_lookback) - 1.0
        skip_5d = (close_today / close_skip) - 1.0
        raw_score = momentum_raw - skip_5d
        vol_window = min(63, sym_idx - 1)
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


def compute_volatility_weights(price_data, selected, date):
    vols = {}
    for symbol in selected:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        sym_idx = df.index.get_loc(date)
        if sym_idx < C_VOL_LOOKBACK + 1:
            continue
        returns = df['Close'].iloc[sym_idx - C_VOL_LOOKBACK:sym_idx + 1].pct_change().dropna()
        if len(returns) < C_VOL_LOOKBACK - 2:
            continue
        vol = returns.std() * np.sqrt(252)
        if vol > 0.01:
            vols[symbol] = vol
    if not vols:
        return {s: 1.0 / len(selected) for s in selected}
    raw_weights = {s: 1.0 / v for s, v in vols.items()}
    total = sum(raw_weights.values())
    return {s: w / total for s, w in raw_weights.items()}


def compute_entry_vol(price_data, symbol, date, lookback=20):
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


def compute_adaptive_stop(entry_daily_vol):
    raw_stop = -C_STOP_DAILY_VOL_MULT * entry_daily_vol
    return max(C_STOP_CEILING, min(C_STOP_FLOOR, raw_stop))


def compute_dynamic_leverage(spy_data, date):
    if date not in spy_data.index:
        return 1.0
    idx = spy_data.index.get_loc(date)
    if idx < C_VOL_LOOKBACK + 1:
        return 1.0
    returns = spy_data['Close'].iloc[idx - C_VOL_LOOKBACK:idx + 1].pct_change().dropna()
    if len(returns) < C_VOL_LOOKBACK - 2:
        return 1.0
    realized_vol = returns.std() * np.sqrt(252)
    if realized_vol < 0.01:
        return C_LEVERAGE_MAX
    leverage = C_TARGET_VOL / realized_vol
    return max(C_LEV_FLOOR, min(C_LEVERAGE_MAX, leverage))


def _dd_leverage(drawdown):
    dd = drawdown
    if dd >= C_DD_SCALE_TIER1:
        return C_LEV_FULL
    elif dd >= C_DD_SCALE_TIER2:
        frac = (dd - C_DD_SCALE_TIER1) / (C_DD_SCALE_TIER2 - C_DD_SCALE_TIER1)
        return C_LEV_FULL + frac * (C_LEV_MID - C_LEV_FULL)
    elif dd >= C_DD_SCALE_TIER3:
        frac = (dd - C_DD_SCALE_TIER2) / (C_DD_SCALE_TIER3 - C_DD_SCALE_TIER2)
        return C_LEV_MID + frac * (C_LEV_FLOOR - C_LEV_MID)
    else:
        return C_LEV_FLOOR


def compute_smooth_leverage(drawdown, portfolio_values, current_idx, crash_cooldown):
    def _val(entry):
        if isinstance(entry, dict):
            return float(entry.get('value', 0.0))
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
            if ret_5d <= C_CRASH_VEL_5D:
                in_crash = True
        if not in_crash and current_idx >= 10:
            val_10d = _val(portfolio_values[current_idx - 10])
            if val_10d > 0:
                ret_10d = (current_val / val_10d) - 1.0
                if ret_10d <= C_CRASH_VEL_10D:
                    in_crash = True
        if in_crash:
            updated_cooldown = C_CRASH_COOLDOWN - 1
    if in_crash:
        dd_lev = _dd_leverage(drawdown)
        crash_lev = min(C_CRASH_LEVERAGE, dd_lev)
        return (crash_lev, updated_cooldown)
    return (_dd_leverage(drawdown), updated_cooldown)


def compute_quality_filter(price_data, tradeable, date):
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
        if sym_idx < C_QUALITY_VOL_LOOKBACK + 1:
            passed.append(symbol)
            continue
        prices = df['Close'].iloc[sym_idx - C_QUALITY_VOL_LOOKBACK:sym_idx + 1]
        rets = prices.pct_change().dropna()
        if len(rets) < C_QUALITY_VOL_LOOKBACK - 5:
            passed.append(symbol)
            continue
        max_abs_ret = float(rets.abs().max())
        if max_abs_ret > C_QUALITY_MAX_SINGLE_DAY:
            continue
        ann_vol = float(rets.std() * np.sqrt(252))
        if ann_vol <= C_QUALITY_VOL_MAX:
            passed.append(symbol)
    if len(passed) < 5:
        return tradeable
    return passed


def filter_by_sector_concentration(ranked_candidates, current_positions, max_per_sector=C_MAX_PER_SECTOR):
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


def should_renew_position(symbol, pos, current_price, total_days_held, scores):
    if total_days_held >= C_HOLD_DAYS_MAX:
        return False
    entry_price = pos.get('entry_price', current_price)
    if entry_price <= 0:
        return False
    pos_return = (current_price - entry_price) / entry_price
    if pos_return < C_RENEWAL_PROFIT_MIN:
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
    return percentile >= C_MOMENTUM_RENEWAL_THRESHOLD


# ============================================================================
# RATTLESNAKE FUNCTIONS
# ============================================================================

def compute_rsi(prices_series, period=5):
    delta = prices_series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


# ============================================================================
# DATA LOADING
# ============================================================================

def load_compass_data():
    """Load COMPASS expanded pool (774 stocks, survivorship-free)"""
    expanded_cache = 'data_cache/exp40_expanded_pool.pkl'
    if not os.path.exists(expanded_cache):
        print("[ERROR] exp40_expanded_pool.pkl not found!")
        return None
    print("[Cache] Loading COMPASS expanded pool (774 stocks)...")
    with open(expanded_cache, 'rb') as f:  # trusted local cache file
        price_data = pickle.load(f)
    # Filter corrupted stocks
    bad_symbols = []
    for sym, df in price_data.items():
        rets = df['Close'].pct_change().abs()
        if (rets > 5.0).any():
            bad_symbols.append(sym)
    for sym in bad_symbols:
        del price_data[sym]
    if bad_symbols:
        print(f"  Removed {len(bad_symbols)} corrupted stocks")
    print(f"  Clean symbols: {len(price_data)}")
    return price_data


def load_rattlesnake_data():
    """Load Rattlesnake data (S&P 100 + SPY + VIX)"""
    cache_file = 'rattlesnake_cache.pkl'
    if os.path.exists(cache_file):
        print("[Cache] Loading Rattlesnake data...")
        with open(cache_file, 'rb') as f:  # trusted local cache file
            return pickle.load(f)
    print("[Download] Downloading Rattlesnake universe...")
    all_tickers = R_UNIVERSE + ['SPY', '^VIX']
    data = {}
    volume_data = {}
    for ticker in all_tickers:
        try:
            df = yf.download(ticker, start='1999-01-01', end='2026-02-21',
                           auto_adjust=True, progress=False)
            if len(df) > 0:
                close = df['Close']
                if isinstance(close, pd.DataFrame):
                    close = close.iloc[:, 0]
                data[ticker] = close.squeeze()
                if 'Volume' in df.columns:
                    vol = df['Volume']
                    if isinstance(vol, pd.DataFrame):
                        vol = vol.iloc[:, 0]
                    volume_data[ticker] = vol.squeeze()
        except Exception:
            pass
    prices = pd.DataFrame(data).ffill()
    volumes = pd.DataFrame(volume_data).ffill()
    result = {'prices': prices, 'volumes': volumes}
    with open(cache_file, 'wb') as f:  # trusted local cache file
        pickle.dump(result, f)
    return result


def download_spy():
    cache_file = f'data_cache/SPY_{START_DATE}_{END_DATE}.csv'
    if os.path.exists(cache_file):
        return pd.read_csv(cache_file, index_col=0, parse_dates=True)
    df = yf.download('SPY', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df


def download_cash_yield():
    cache_file = 'data_cache/moody_aaa_yield.csv'
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        daily = df['yield_pct'].resample('D').ffill()
        return daily
    try:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA&cosd=1999-01-01&coed=2026-12-31'
        df = pd.read_csv(url, parse_dates=['observation_date'], index_col='observation_date')
        df.columns = ['yield_pct']
        os.makedirs('data_cache', exist_ok=True)
        df.to_csv(cache_file)
        return df['yield_pct'].resample('D').ffill()
    except Exception:
        return None


def compute_annual_top40(price_data):
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
        top_n = [s for s, _ in ranked[:C_TOP_N]]
        annual_universe[year] = top_n
    return annual_universe


# ============================================================================
# INTEGRATED HYDRA BACKTEST
# ============================================================================

def run_hydra_backtest(compass_data, rattle_data, annual_universe, spy_data,
                       cash_yield_daily=None):
    """
    Run COMPASS + Rattlesnake simultaneously with cash recycling.
    Single capital pool, dynamic allocation based on Rattlesnake exposure.
    """
    print("\n" + "=" * 80)
    print("HYDRA BACKTEST: COMPASS + Rattlesnake with Cash Recycling")
    print(f"Base allocation: {BASE_COMPASS_ALLOC:.0%} / {BASE_RATTLE_ALLOC:.0%}")
    print(f"Max COMPASS allocation (with recycling): {MAX_COMPASS_ALLOC:.0%}")
    print("=" * 80)

    # Build aligned date index from COMPASS data
    all_dates = set()
    for df in compass_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    rattle_prices = rattle_data['prices']
    rattle_volumes = rattle_data['volumes']
    rattle_dates = rattle_prices.index

    # Pre-compute RSI for Rattlesnake stocks
    print("  Pre-computing Rattlesnake RSI...")
    rsi_data = {}
    for ticker in R_UNIVERSE:
        if ticker in rattle_prices.columns:
            rsi_data[ticker] = compute_rsi(rattle_prices[ticker], R_RSI_PERIOD)

    print(f"  Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"  Trading days: {len(all_dates)}")

    # Shared state
    total_cash = float(INITIAL_CAPITAL)

    # COMPASS state
    c_positions = {}
    c_peak_value = float(INITIAL_CAPITAL) * BASE_COMPASS_ALLOC
    c_crash_cooldown = 0

    # Rattlesnake state
    r_positions = []
    r_regime = 'RISK_ON'
    r_regime_counter = 0

    # Tracking
    portfolio_values = []
    c_trades = []
    r_trades = []

    min_history = max(R_TREND_SMA, R_DROP_LOOKBACK + R_RSI_PERIOD, 252) + 50

    print("  Running simulation...")

    for i, date in enumerate(all_dates):
        # ── COMPUTE PORTFOLIO VALUE ──
        c_invested = 0.0
        for symbol, pos in list(c_positions.items()):
            if symbol in compass_data and date in compass_data[symbol].index:
                price = compass_data[symbol].loc[date, 'Close']
                c_invested += pos['shares'] * price

        r_invested = 0.0
        r_date_idx = None
        if date in rattle_prices.index:
            r_date_idx = rattle_prices.index.get_loc(date)
        elif len(rattle_prices) > 0:
            diffs = abs(rattle_prices.index - date)
            nearest_idx = diffs.argmin()
            if diffs[nearest_idx].days <= 3:
                r_date_idx = nearest_idx

        if r_date_idx is not None:
            for pos in r_positions:
                t = pos['ticker']
                if t in rattle_prices.columns and not pd.isna(rattle_prices[t].iloc[r_date_idx]):
                    r_invested += pos['shares'] * float(rattle_prices[t].iloc[r_date_idx])

        portfolio_value = total_cash + c_invested + r_invested

        if i < min_history:
            portfolio_values.append({
                'date': date, 'value': portfolio_value,
                'c_invested': c_invested, 'r_invested': r_invested,
                'cash': total_cash, 'c_positions': len(c_positions),
                'r_positions': len(r_positions),
                'c_alloc': BASE_COMPASS_ALLOC, 'r_alloc': BASE_RATTLE_ALLOC,
            })
            continue

        # ── CASH RECYCLING: DYNAMIC ALLOCATION ──
        r_base_capital = portfolio_value * BASE_RATTLE_ALLOC
        r_exposure = r_invested / r_base_capital if r_base_capital > 0 else 0.0
        r_idle_cash_frac = max(0.0, 1.0 - r_exposure)
        extra_to_compass = BASE_RATTLE_ALLOC * r_idle_cash_frac
        c_alloc = min(BASE_COMPASS_ALLOC + extra_to_compass, MAX_COMPASS_ALLOC)
        r_alloc = 1.0 - c_alloc
        c_target_capital = portfolio_value * c_alloc
        r_target_capital = portfolio_value * r_alloc

        # ── CASH YIELD ──
        if total_cash > 0:
            if cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            total_cash += total_cash * daily_rate

        # ── COMPASS: REGIME & DD SCALING ──
        regime_score = compute_regime_score(spy_data, date)
        is_risk_on = regime_score >= 0.50

        c_value = total_cash * (c_alloc / (c_alloc + r_alloc)) + c_invested
        if c_value > c_peak_value:
            c_peak_value = c_value
        c_drawdown = (c_value - c_peak_value) / c_peak_value if c_peak_value > 0 else 0

        dd_leverage_val, c_crash_cooldown = compute_smooth_leverage(
            c_drawdown, portfolio_values, max(i - 1, 0), c_crash_cooldown
        )
        vol_leverage = compute_dynamic_leverage(spy_data, date)
        current_leverage = max(min(dd_leverage_val, vol_leverage), C_LEV_FLOOR)

        spy_trend = get_spy_trend_data(spy_data, date)
        if spy_trend is not None:
            spy_close_now, sma200_now = spy_trend
            max_positions = regime_score_to_positions(regime_score,
                                                      spy_close=spy_close_now,
                                                      sma200=sma200_now)
        else:
            max_positions = regime_score_to_positions(regime_score)

        # COMPASS tradeable universe
        tradeable_symbols = []
        eligible = set(annual_universe.get(date.year, []))
        for symbol in eligible:
            if symbol not in compass_data:
                continue
            df = compass_data[symbol]
            if date not in df.index:
                continue
            symbol_first_date = df.index[0]
            days_since_start = (date - symbol_first_date).days
            if date <= first_date + timedelta(days=30):
                tradeable_symbols.append(symbol)
            elif days_since_start >= C_MIN_AGE_DAYS:
                tradeable_symbols.append(symbol)

        quality_symbols = compute_quality_filter(compass_data, tradeable_symbols, date)
        current_scores = compute_momentum_scores(compass_data, quality_symbols, date, all_dates, i)

        # ── COMPASS EXITS ──
        for symbol in list(c_positions.keys()):
            pos = c_positions[symbol]
            if symbol not in compass_data or date not in compass_data[symbol].index:
                continue
            current_price = compass_data[symbol].loc[date, 'Close']
            exit_reason = None

            days_held = i - pos['entry_idx']
            total_days_held = i - pos['original_entry_idx']
            if days_held >= C_HOLD_DAYS:
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
            if pos['high_price'] > pos['entry_price'] * (1 + C_TRAILING_ACTIVATION):
                vol_ratio = pos.get('entry_vol', C_TRAILING_VOL_BASELINE) / C_TRAILING_VOL_BASELINE
                scaled_trailing = C_TRAILING_STOP_PCT * vol_ratio
                trailing_level = pos['high_price'] * (1 - scaled_trailing)
                if current_price <= trailing_level:
                    exit_reason = 'trailing_stop'

            if symbol not in tradeable_symbols:
                exit_reason = 'universe_rotation'

            if exit_reason is None and len(c_positions) > max_positions:
                pos_returns = {}
                for s, p in c_positions.items():
                    if s in compass_data and date in compass_data[s].index:
                        cp = compass_data[s].loc[date, 'Close']
                        pos_returns[s] = (cp - p['entry_price']) / p['entry_price']
                if pos_returns:
                    worst = min(pos_returns, key=pos_returns.get)
                    if symbol == worst:
                        exit_reason = 'regime_reduce'

            if exit_reason:
                shares = pos['shares']
                proceeds = shares * current_price
                commission = shares * COMMISSION_PER_SHARE
                total_cash += proceeds - commission
                c_trades.append({
                    'symbol': symbol, 'strategy': 'COMPASS',
                    'entry_date': pos['entry_date'], 'exit_date': date,
                    'exit_reason': exit_reason,
                    'pnl': (current_price - pos['entry_price']) * shares - commission,
                    'return': (current_price - pos['entry_price']) / pos['entry_price'],
                })
                del c_positions[symbol]

        # ── COMPASS ENTRIES ──
        needed = max_positions - len(c_positions)
        c_available_cash = max(0, c_target_capital - c_invested)
        c_available_cash = min(c_available_cash, total_cash * 0.95)

        if needed > 0 and c_available_cash > 1000 and len(tradeable_symbols) >= 5:
            available_scores = {s: sc for s, sc in current_scores.items() if s not in c_positions}
            if len(current_scores) >= C_MIN_MOMENTUM_STOCKS and len(available_scores) >= needed:
                ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
                sector_filtered = filter_by_sector_concentration(ranked, c_positions)
                selected = sector_filtered[:needed]
                weights = compute_volatility_weights(compass_data, selected, date)
                effective_capital = c_available_cash * current_leverage * 0.95

                for symbol in selected:
                    if symbol not in compass_data or date not in compass_data[symbol].index:
                        continue
                    entry_price = compass_data[symbol].loc[date, 'Close']
                    if entry_price <= 0:
                        continue
                    weight = weights.get(symbol, 1.0 / len(selected))
                    position_value = effective_capital * weight
                    max_per_position = c_available_cash * 0.40
                    position_value = min(position_value, max_per_position)
                    shares = position_value / entry_price
                    cost = shares * entry_price
                    commission = shares * COMMISSION_PER_SHARE
                    if cost + commission <= total_cash * 0.90:
                        entry_vol, entry_daily_vol = compute_entry_vol(compass_data, symbol, date)
                        c_positions[symbol] = {
                            'entry_price': entry_price, 'shares': shares,
                            'entry_date': date, 'entry_idx': i,
                            'original_entry_idx': i, 'high_price': entry_price,
                            'entry_vol': entry_vol, 'entry_daily_vol': entry_daily_vol,
                            'sector': SECTOR_MAP.get(symbol, 'Unknown'),
                        }
                        total_cash -= cost + commission

        # ── RATTLESNAKE: REGIME, EXITS, ENTRIES ──
        if r_date_idx is not None and r_date_idx >= min_history:
            # Regime
            if 'SPY' in rattle_prices.columns and not pd.isna(rattle_prices['SPY'].iloc[r_date_idx]):
                if r_date_idx >= R_REGIME_SMA:
                    spy_price = float(rattle_prices['SPY'].iloc[r_date_idx])
                    spy_sma = float(rattle_prices['SPY'].iloc[r_date_idx - R_REGIME_SMA + 1:r_date_idx + 1].mean())
                    if spy_price > spy_sma:
                        if r_regime != 'RISK_ON':
                            r_regime_counter += 1
                            if r_regime_counter >= R_REGIME_CONFIRM:
                                r_regime = 'RISK_ON'
                                r_regime_counter = 0
                        else:
                            r_regime_counter = 0
                    else:
                        if r_regime != 'RISK_OFF':
                            r_regime_counter += 1
                            if r_regime_counter >= R_REGIME_CONFIRM:
                                r_regime = 'RISK_OFF'
                                r_regime_counter = 0
                        else:
                            r_regime_counter = 0

            vix_panic = False
            if '^VIX' in rattle_prices.columns and not pd.isna(rattle_prices['^VIX'].iloc[r_date_idx]):
                if float(rattle_prices['^VIX'].iloc[r_date_idx]) > R_VIX_PANIC:
                    vix_panic = True

            # Rattlesnake exits
            for pos in list(r_positions):
                t = pos['ticker']
                if t not in rattle_prices.columns or pd.isna(rattle_prices[t].iloc[r_date_idx]):
                    continue
                current_price = float(rattle_prices[t].iloc[r_date_idx])
                entry_price = pos['entry_price']
                pnl_pct = (current_price / entry_price) - 1.0
                hold_days = r_date_idx - pos['entry_date_idx']
                exit_reason = None
                if pnl_pct >= R_PROFIT_TARGET:
                    exit_reason = 'PROFIT'
                elif pnl_pct <= R_STOP_LOSS:
                    exit_reason = 'STOP'
                elif hold_days >= R_MAX_HOLD_DAYS:
                    exit_reason = 'TIME'
                if exit_reason:
                    proceeds = pos['shares'] * current_price
                    comm = proceeds * COMMISSION_BPS / 10000
                    total_cash += proceeds - comm
                    r_trades.append({
                        'symbol': t, 'strategy': 'RATTLESNAKE',
                        'entry_date': rattle_dates[pos['entry_date_idx']] if pos['entry_date_idx'] < len(rattle_dates) else date,
                        'exit_date': date, 'exit_reason': exit_reason,
                        'pnl_pct': pnl_pct, 'hold_days': hold_days,
                    })
                    r_positions.remove(pos)

            # Rattlesnake entries
            r_max_pos = R_MAX_POSITIONS if r_regime == 'RISK_ON' else R_MAX_POS_RISK_OFF
            r_open_slots = r_max_pos - len(r_positions)
            r_available_cash = max(0, r_target_capital - r_invested)
            r_available_cash = min(r_available_cash, total_cash * 0.95)

            if r_open_slots > 0 and not vix_panic and r_available_cash > 1000:
                held_tickers = set(p['ticker'] for p in r_positions)
                held_tickers.update(c_positions.keys())

                candidates = []
                for ticker in R_UNIVERSE:
                    if ticker in held_tickers:
                        continue
                    if ticker not in rattle_prices.columns or pd.isna(rattle_prices[ticker].iloc[r_date_idx]):
                        continue
                    current_price = float(rattle_prices[ticker].iloc[r_date_idx])
                    if r_date_idx < R_DROP_LOOKBACK:
                        continue
                    past_price = float(rattle_prices[ticker].iloc[r_date_idx - R_DROP_LOOKBACK])
                    if pd.isna(past_price) or past_price <= 0:
                        continue
                    drop = (current_price / past_price) - 1.0
                    if drop > R_DROP_THRESHOLD:
                        continue
                    if ticker not in rsi_data or pd.isna(rsi_data[ticker].iloc[r_date_idx]):
                        continue
                    rsi_val = rsi_data[ticker].iloc[r_date_idx]
                    if rsi_val > R_RSI_THRESHOLD:
                        continue
                    if r_date_idx < R_TREND_SMA:
                        continue
                    sma_val = float(rattle_prices[ticker].iloc[r_date_idx - R_TREND_SMA + 1:r_date_idx + 1].mean())
                    if current_price < sma_val:
                        continue
                    if ticker in rattle_volumes.columns and r_date_idx >= 20:
                        avg_vol = rattle_volumes[ticker].iloc[r_date_idx-20:r_date_idx].mean()
                        if pd.isna(avg_vol) or avg_vol < 500_000:
                            continue
                    score = -drop
                    candidates.append((ticker, score, drop, rsi_val))

                candidates.sort(key=lambda x: x[1], reverse=True)

                for ticker, score, drop, rsi_val in candidates[:r_open_slots]:
                    buy_price = float(rattle_prices[ticker].iloc[r_date_idx])
                    if buy_price <= 0:
                        continue
                    target_val = r_target_capital * R_POSITION_SIZE
                    target_val = min(target_val, r_available_cash * 0.90)
                    shares = int(target_val / buy_price)
                    if shares <= 0:
                        continue
                    cost = shares * buy_price
                    comm = cost * COMMISSION_BPS / 10000
                    if cost + comm <= total_cash * 0.90:
                        total_cash -= cost + comm
                        r_positions.append({
                            'ticker': ticker, 'entry_price': buy_price,
                            'entry_date_idx': r_date_idx, 'shares': shares,
                        })

        # ── RECORD DAILY SNAPSHOT ──
        c_invested_after = sum(
            c_positions[s]['shares'] * compass_data[s].loc[date, 'Close']
            for s in c_positions
            if s in compass_data and date in compass_data[s].index
        )
        r_invested_after = 0.0
        if r_date_idx is not None:
            r_invested_after = sum(
                pos['shares'] * float(rattle_prices[pos['ticker']].iloc[r_date_idx])
                for pos in r_positions
                if pos['ticker'] in rattle_prices.columns and not pd.isna(rattle_prices[pos['ticker']].iloc[r_date_idx])
            )

        final_value = total_cash + c_invested_after + r_invested_after

        portfolio_values.append({
            'date': date, 'value': final_value,
            'c_invested': c_invested_after, 'r_invested': r_invested_after,
            'cash': total_cash, 'c_positions': len(c_positions),
            'r_positions': len(r_positions),
            'c_alloc': c_alloc, 'r_alloc': r_alloc,
        })

        if i % 252 == 0 and i > 0:
            year_num = i // 252
            print(f"  Year {year_num}: ${final_value:,.0f} | "
                  f"C:{len(c_positions)}pos ${c_invested_after:,.0f} | "
                  f"R:{len(r_positions)}pos ${r_invested_after:,.0f} | "
                  f"Cash: ${total_cash:,.0f} | "
                  f"Alloc: {c_alloc:.0%}/{r_alloc:.0%}")

    # Close remaining positions
    last_date = all_dates[-1]
    for symbol, pos in c_positions.items():
        if symbol in compass_data and last_date in compass_data[symbol].index:
            price = compass_data[symbol].loc[last_date, 'Close']
            total_cash += pos['shares'] * price
    if r_date_idx is not None:
        for pos in r_positions:
            t = pos['ticker']
            if t in rattle_prices.columns and not pd.isna(rattle_prices[t].iloc[r_date_idx]):
                total_cash += pos['shares'] * float(rattle_prices[t].iloc[r_date_idx])

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'compass_trades': pd.DataFrame(c_trades) if c_trades else pd.DataFrame(),
        'rattle_trades': pd.DataFrame(r_trades) if r_trades else pd.DataFrame(),
    }


# ============================================================================
# METRICS & OUTPUT
# ============================================================================

def print_results(results):
    df = results['portfolio_values'].set_index('date')
    df = df[df['value'] > 0]

    initial = INITIAL_CAPITAL
    final_value = df['value'].iloc[-1]
    years = len(df) / 252
    cagr = (final_value / initial) ** (1 / years) - 1
    returns = df['value'].pct_change().dropna()
    volatility = returns.std() * np.sqrt(252)
    sharpe = cagr / volatility if volatility > 0 else 0

    cummax = df['value'].cummax()
    dd = (df['value'] / cummax) - 1
    max_dd = dd.min()
    max_dd_date = dd.idxmin()

    downside = returns[returns < 0].std() * np.sqrt(252)
    sortino = cagr / downside if downside > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    annual = df['value'].resample('YE').last().pct_change().dropna()

    print(f"\n{'='*70}")
    print(f"  HYDRA v1.0 -- COMPASS + Rattlesnake with Cash Recycling")
    print(f"{'='*70}")
    print(f"  Period:       {df.index[0].strftime('%Y-%m-%d')} -> {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Years:        {years:.1f}")
    print(f"")
    print(f"  -- PORTFOLIO --")
    print(f"  Initial:      ${initial:>12,.0f}")
    print(f"  Final:        ${final_value:>12,.0f}")
    print(f"  CAGR:         {cagr:>11.2%}")
    print(f"  Annual Vol:   {volatility:>11.2%}")
    print(f"  Max Drawdown: {max_dd:>11.2%} ({max_dd_date.strftime('%Y-%m-%d')})")
    print(f"")
    print(f"  -- RATIOS --")
    print(f"  Sharpe:       {sharpe:>11.2f}")
    print(f"  Sortino:      {sortino:>11.2f}")
    print(f"  Calmar:       {calmar:>11.2f}")

    c_trades = results['compass_trades']
    r_trades = results['rattle_trades']
    print(f"")
    print(f"  -- TRADING --")
    print(f"  COMPASS trades:    {len(c_trades):>6}")
    print(f"  Rattlesnake trades:{len(r_trades):>6}")
    if len(c_trades) > 0 and 'return' in c_trades.columns:
        c_wr = (c_trades['return'] > 0).mean()
        print(f"  COMPASS win rate:  {c_wr:>10.1%}")
    if len(r_trades) > 0 and 'pnl_pct' in r_trades.columns:
        r_wr = (r_trades['pnl_pct'] > 0).mean()
        print(f"  Rattle win rate:   {r_wr:>10.1%}")

    print(f"")
    print(f"  -- ALLOCATION --")
    print(f"  Avg COMPASS alloc: {df['c_alloc'].mean():>10.1%}")
    print(f"  Avg Rattle alloc:  {df['r_alloc'].mean():>10.1%}")
    print(f"  Days at max ({MAX_COMPASS_ALLOC:.0%}):  {(df['c_alloc'] >= MAX_COMPASS_ALLOC - 0.001).sum():>6} / {len(df)} ({(df['c_alloc'] >= MAX_COMPASS_ALLOC - 0.001).mean()*100:.1f}%)")

    print(f"")
    print(f"  -- ANNUAL RETURNS --")
    for idx, ret in annual.items():
        yr = idx.year
        bar = ('+' if ret > 0 else '-') * min(int(abs(ret) * 100), 50)
        print(f"  {yr}  {ret:>+6.1%}  {bar}")

    print(f"")
    print(f"  {'METRIC':<18} {'HYDRA':>10} {'COMPASS':>10} {'50/50 static':>12}")
    print(f"  {'-'*52}")
    print(f"  {'CAGR':<18} {cagr:>9.2%} {'12.27%':>10} {'11.87%':>12}")
    print(f"  {'Sharpe':<18} {sharpe:>10.2f} {'0.85':>10} {'1.09':>12}")
    print(f"  {'Max DD':<18} {max_dd:>9.2%} {'-32.10%':>10} {'-18.57%':>12}")
    print(f"  {'Volatility':<18} {volatility:>9.2%} {'~14%':>10} {'~10%':>12}")
    print(f"")
    print(f"{'='*70}")

    return {
        'cagr': cagr, 'sharpe': sharpe, 'max_dd': max_dd,
        'sortino': sortino, 'calmar': calmar,
        'final_value': final_value, 'volatility': volatility,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    print("HYDRA v1.0 - COMPASS + Rattlesnake with Cash Recycling")
    print("=" * 60)

    compass_data = load_compass_data()
    if compass_data is None:
        exit(1)

    rattle_data = load_rattlesnake_data()
    spy_data = download_spy()
    cash_yield_daily = download_cash_yield()

    print("\n--- Computing Annual Top-40 ---")
    annual_universe = compute_annual_top40(compass_data)

    results = run_hydra_backtest(compass_data, rattle_data, annual_universe,
                                 spy_data, cash_yield_daily)

    metrics = print_results(results)

    os.makedirs('backtests', exist_ok=True)
    results['portfolio_values'].to_csv('backtests/hydra_daily.csv', index=False)
    if len(results['compass_trades']) > 0:
        results['compass_trades'].to_csv('backtests/hydra_compass_trades.csv', index=False)
    if len(results['rattle_trades']) > 0:
        results['rattle_trades'].to_csv('backtests/hydra_rattle_trades.csv', index=False)

    print(f"\nSaved: backtests/hydra_daily.csv")
    print("HYDRA BACKTEST COMPLETE")
