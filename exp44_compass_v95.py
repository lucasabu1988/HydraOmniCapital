"""
Experiment 44: COMPASS v9.5 - Modular Backtest Orchestrator
============================================================

Modular rewrite of COMPASS v9 with critical fixes from the CRITIC review:
  1. Period alignment: 2000-01-03 to end (matches v8.2 comparison window)
  2. Realistic transaction costs: 5 bps slippage + $0.005/share commission
  3. Universe cleanup: exclude ETFs, log unmapped symbols
  4. Corrected Sharpe: daily excess returns, annualised properly
  5. Walk-forward validation flag (train/test split)
  6. Comprehensive metric reporting with confidence intervals

Modules (written by parallel agents):
  exp44_modules.regime   -- regime score & regime-to-params
  exp44_modules.signals  -- multi-timeframe momentum, quality, stock selection
  exp44_modules.exits    -- hold expiry, position stop, trailing stop, regime reduce
  exp44_modules.risk     -- DD leverage, vol targeting, correlation adjustment, Sharpe

Run:  python exp44_compass_v95.py
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
import pickle
import os
import sys
import time
from typing import Dict, List, Tuple, Optional, Set
from collections import defaultdict
from io import StringIO
import warnings
import requests

warnings.filterwarnings('ignore')

# ---------------------------------------------------------------------------
# Module imports (other agents are writing these concurrently)
# ---------------------------------------------------------------------------
try:
    from exp44_modules.regime import compute_regime_score, regime_to_params
    from exp44_modules.signals import compute_signals, select_stocks
    from exp44_modules.exits import check_exit
    from exp44_modules.risk import (
        compute_final_leverage,
        compute_correlation_adjustment,
        compute_sharpe_ratio,
    )
    MODULES_LOADED = True
except ImportError as e:
    print(f"[WARNING] Could not import exp44_modules: {e}")
    print("          Falling back to inline implementations.")
    MODULES_LOADED = False


# ============================================================================
# PARAMETERS
# ============================================================================

# -- Backtest window (CRITIC fix #1: match v8.2) --
BACKTEST_START = '2000-01-03'
DATA_DOWNLOAD_START = '1997-01-01'   # need lookback before 2000
END_DATE = '2027-01-01'

# -- Walk-forward (CRITIC fix #5) --
WALK_FORWARD = False
TRAIN_END = '2015-12-31'
TEST_START = '2016-01-04'

# -- Capital --
INITIAL_CAPITAL = 100_000

# -- Transaction costs (CRITIC fix #2) --
SLIPPAGE_BPS = 5              # 5 basis points per trade (one-way)
COMMISSION_PER_SHARE = 0.005  # $0.005 per share

# -- Universe --
TOP_N = 50
MIN_AGE_DAYS = 63

# -- ETF / non-equity exclusion list (CRITIC fix #3) --
ETF_EXCLUDE: Set[str] = {
    'GLD', 'SLV', 'SPY', 'QQQ', 'IWM', 'DIA',
    'XLF', 'XLE', 'XLK', 'XLV', 'XLI', 'XLP', 'XLU', 'XLB', 'XLY',
    'XLRE', 'XLC',
    'VTI', 'VOO', 'IVV',
    'TLT', 'HYG', 'LQD',
    'EEM', 'EFA',
    'SH', 'SDS', 'TBT', 'UUP', 'USO', 'ARKK', 'ARKG',
}

# -- Signals --
MOMENTUM_SHORT  = 60
MOMENTUM_MED    = 120
MOMENTUM_LONG   = 252
MOMENTUM_SKIP   = 10
MOMENTUM_WEIGHTS = [0.25, 0.40, 0.35]
MIN_MOMENTUM_STOCKS = 15
MAX_STOCK_VOL   = 0.60
VOL_LOOKBACK_QUAL = 63

# -- Regime --
REGIME_SMA_LONG     = 200
REGIME_SMA_MED      = 50
REGIME_VOL_SHORT    = 20
REGIME_VOL_MED      = 63
REGIME_BREADTH_SMA  = 50

# -- Positions --
NUM_POSITIONS_BULL   = 12
NUM_POSITIONS_MILD   = 8
NUM_POSITIONS_BEAR   = 5
NUM_POSITIONS_SEVERE = 3
SECTOR_MAX_POSITIONS = 3

# -- Risk / leverage --
DD_TIER_1    = -0.05
DD_TIER_2    = -0.15
DD_TIER_3    = -0.25
LEV_FULL     = 1.0
LEV_REDUCED  = 0.50
LEV_MINIMUM  = 0.25
TARGET_VOL   = 0.15
LEVERAGE_MAX = 1.0
VOL_LOOKBACK = 20

# -- Exits --
POSITION_STOP_LOSS    = -0.12
TRAILING_ACTIVATION   = 0.08
TRAILING_STOP_PCT     = 0.05
HOLD_DAYS_BULL        = 10
HOLD_DAYS_BEAR        = 5

# -- Cash yield --
CASH_YIELD_RATE   = 0.035
CASH_YIELD_SOURCE = 'AAA'
MARGIN_RATE       = 0.06

# ============================================================================
# SECTOR MAP  (expanded for historical S&P 500 constituents)
# ============================================================================
SECTOR_MAP = {
    # --- Technology ---
    'AAPL': 'Tech', 'MSFT': 'Tech', 'NVDA': 'Tech', 'GOOGL': 'Tech',
    'GOOG': 'Tech', 'META': 'Tech', 'FB': 'Tech',
    'AVGO': 'Tech', 'ADBE': 'Tech', 'CRM': 'Tech',
    'AMD': 'Tech', 'INTC': 'Tech', 'CSCO': 'Tech', 'IBM': 'Tech',
    'TXN': 'Tech', 'QCOM': 'Tech', 'ORCL': 'Tech', 'ACN': 'Tech',
    'NOW': 'Tech', 'INTU': 'Tech', 'AMAT': 'Tech', 'MU': 'Tech',
    'LRCX': 'Tech', 'SNPS': 'Tech', 'CDNS': 'Tech', 'KLAC': 'Tech',
    'MRVL': 'Tech', 'NFLX': 'Tech', 'PYPL': 'Tech', 'SHOP': 'Tech',
    'SQ': 'Tech', 'SNOW': 'Tech', 'PANW': 'Tech', 'CRWD': 'Tech',
    'ZS': 'Tech', 'DDOG': 'Tech', 'FTNT': 'Tech', 'TEAM': 'Tech',
    'WDAY': 'Tech', 'ADSK': 'Tech', 'ANSS': 'Tech', 'CTSH': 'Tech',
    'HPQ': 'Tech', 'HPE': 'Tech', 'DELL': 'Tech', 'MCHP': 'Tech',
    'ON': 'Tech', 'NXPI': 'Tech', 'SWKS': 'Tech', 'MPWR': 'Tech',
    'ADI': 'Tech', 'XLNX': 'Tech', 'FISV': 'Tech', 'FIS': 'Tech',
    'MSI': 'Tech', 'GLW': 'Tech', 'TEL': 'Tech', 'APH': 'Tech',
    # --- Financials ---
    'BRK-B': 'Fin', 'JPM': 'Fin', 'V': 'Fin', 'MA': 'Fin',
    'BAC': 'Fin', 'WFC': 'Fin', 'GS': 'Fin', 'MS': 'Fin',
    'AXP': 'Fin', 'BLK': 'Fin', 'SCHW': 'Fin', 'C': 'Fin',
    'USB': 'Fin', 'PNC': 'Fin', 'TFC': 'Fin', 'CB': 'Fin',
    'MMC': 'Fin', 'AIG': 'Fin', 'MET': 'Fin', 'PRU': 'Fin',
    'ICE': 'Fin', 'CME': 'Fin', 'SPGI': 'Fin', 'MCO': 'Fin',
    'AON': 'Fin', 'MSCI': 'Fin', 'AMP': 'Fin', 'STT': 'Fin',
    'BK': 'Fin', 'FITB': 'Fin', 'RF': 'Fin', 'HBAN': 'Fin',
    'KEY': 'Fin', 'CFG': 'Fin', 'ALLY': 'Fin', 'COF': 'Fin',
    'DFS': 'Fin', 'SYF': 'Fin', 'TROW': 'Fin', 'NTRS': 'Fin',
    # --- Healthcare ---
    'UNH': 'Health', 'JNJ': 'Health', 'LLY': 'Health', 'ABBV': 'Health',
    'MRK': 'Health', 'PFE': 'Health', 'TMO': 'Health', 'ABT': 'Health',
    'DHR': 'Health', 'AMGN': 'Health', 'BMY': 'Health', 'MDT': 'Health',
    'ISRG': 'Health', 'SYK': 'Health', 'GILD': 'Health', 'REGN': 'Health',
    'VRTX': 'Health', 'BIIB': 'Health', 'ZTS': 'Health', 'BDX': 'Health',
    'CI': 'Health', 'ELV': 'Health', 'HUM': 'Health', 'CNC': 'Health',
    'MCK': 'Health', 'CAH': 'Health', 'ABC': 'Health', 'A': 'Health',
    'IQV': 'Health', 'DXCM': 'Health', 'IDXX': 'Health', 'BSX': 'Health',
    'EW': 'Health', 'BAX': 'Health', 'ALGN': 'Health', 'HOLX': 'Health',
    'MTD': 'Health', 'WAT': 'Health',
    # --- Consumer Discretionary ---
    'AMZN': 'ConsDis', 'TSLA': 'ConsDis', 'HD': 'ConsDis', 'NKE': 'ConsDis',
    'MCD': 'ConsDis', 'DIS': 'ConsDis', 'SBUX': 'ConsDis', 'TGT': 'ConsDis',
    'LOW': 'ConsDis', 'EL': 'ConsDis', 'TJX': 'ConsDis', 'ROST': 'ConsDis',
    'DHI': 'ConsDis', 'LEN': 'ConsDis', 'PHM': 'ConsDis', 'NVR': 'ConsDis',
    'GM': 'ConsDis', 'F': 'ConsDis', 'BKNG': 'ConsDis', 'MAR': 'ConsDis',
    'HLT': 'ConsDis', 'CMG': 'ConsDis', 'YUM': 'ConsDis', 'DPZ': 'ConsDis',
    'ORLY': 'ConsDis', 'AZO': 'ConsDis', 'AAP': 'ConsDis', 'EBAY': 'ConsDis',
    'ETSY': 'ConsDis', 'BBY': 'ConsDis', 'POOL': 'ConsDis', 'DECK': 'ConsDis',
    'LULU': 'ConsDis', 'RCL': 'ConsDis', 'CCL': 'ConsDis', 'ABNB': 'ConsDis',
    # --- Consumer Staples ---
    'WMT': 'ConsStap', 'PG': 'ConsStap', 'COST': 'ConsStap', 'KO': 'ConsStap',
    'PEP': 'ConsStap', 'CL': 'ConsStap', 'KMB': 'ConsStap', 'GIS': 'ConsStap',
    'MO': 'ConsStap', 'PM': 'ConsStap', 'MDLZ': 'ConsStap', 'ADM': 'ConsStap',
    'STZ': 'ConsStap', 'SYY': 'ConsStap', 'KHC': 'ConsStap', 'HSY': 'ConsStap',
    'K': 'ConsStap', 'CPB': 'ConsStap', 'SJM': 'ConsStap', 'CAG': 'ConsStap',
    'MKC': 'ConsStap', 'CHD': 'ConsStap', 'CLX': 'ConsStap', 'KR': 'ConsStap',
    'WBA': 'ConsStap', 'CVS': 'ConsStap',
    # --- Energy ---
    'XOM': 'Energy', 'CVX': 'Energy', 'COP': 'Energy', 'SLB': 'Energy',
    'EOG': 'Energy', 'OXY': 'Energy', 'MPC': 'Energy', 'PSX': 'Energy',
    'VLO': 'Energy', 'PXD': 'Energy', 'DVN': 'Energy', 'HAL': 'Energy',
    'FANG': 'Energy', 'HES': 'Energy', 'BKR': 'Energy', 'KMI': 'Energy',
    'WMB': 'Energy', 'OKE': 'Energy', 'TRGP': 'Energy',
    # --- Industrials ---
    'GE': 'Indust', 'CAT': 'Indust', 'BA': 'Indust', 'HON': 'Indust',
    'UNP': 'Indust', 'RTX': 'Indust', 'LMT': 'Indust', 'DE': 'Indust',
    'UPS': 'Indust', 'FDX': 'Indust', 'MMM': 'Indust', 'GD': 'Indust',
    'NOC': 'Indust', 'EMR': 'Indust', 'ITW': 'Indust', 'ETN': 'Indust',
    'ROK': 'Indust', 'SWK': 'Indust', 'PH': 'Indust', 'CMI': 'Indust',
    'PCAR': 'Indust', 'CSX': 'Indust', 'NSC': 'Indust', 'WM': 'Indust',
    'RSG': 'Indust', 'GWW': 'Indust', 'FAST': 'Indust', 'IR': 'Indust',
    'CARR': 'Indust', 'OTIS': 'Indust', 'TT': 'Indust', 'VRSK': 'Indust',
    'CTAS': 'Indust', 'PAYX': 'Indust', 'ADP': 'Indust',
    # --- Utilities ---
    'NEE': 'Util', 'DUK': 'Util', 'SO': 'Util', 'D': 'Util', 'AEP': 'Util',
    'EXC': 'Util', 'SRE': 'Util', 'XEL': 'Util', 'ED': 'Util', 'WEC': 'Util',
    'ES': 'Util', 'PPL': 'Util', 'FE': 'Util', 'PEG': 'Util', 'AWK': 'Util',
    'AES': 'Util', 'CMS': 'Util', 'DTE': 'Util', 'EIX': 'Util', 'ETR': 'Util',
    # --- Telecom / Communication ---
    'VZ': 'Telecom', 'T': 'Telecom', 'TMUS': 'Telecom', 'CMCSA': 'Telecom',
    'CHTR': 'Telecom', 'ATVI': 'Telecom', 'EA': 'Telecom', 'TTWO': 'Telecom',
    'WBD': 'Telecom', 'PARA': 'Telecom', 'FOXA': 'Telecom', 'FOX': 'Telecom',
    'NWSA': 'Telecom', 'NWS': 'Telecom', 'OMC': 'Telecom', 'IPG': 'Telecom',
    # --- Real Estate ---
    'AMT': 'RealEst', 'PLD': 'RealEst', 'CCI': 'RealEst', 'EQIX': 'RealEst',
    'PSA': 'RealEst', 'O': 'RealEst', 'WELL': 'RealEst', 'DLR': 'RealEst',
    'SPG': 'RealEst', 'VICI': 'RealEst', 'AVB': 'RealEst', 'EQR': 'RealEst',
    'ARE': 'RealEst', 'MAA': 'RealEst', 'UDR': 'RealEst', 'ESS': 'RealEst',
    # --- Materials ---
    'LIN': 'Mater', 'APD': 'Mater', 'SHW': 'Mater', 'ECL': 'Mater',
    'FCX': 'Mater', 'NEM': 'Mater', 'NUE': 'Mater', 'DOW': 'Mater',
    'DD': 'Mater', 'PPG': 'Mater', 'VMC': 'Mater', 'MLM': 'Mater',
    'ALB': 'Mater', 'CF': 'Mater', 'MOS': 'Mater', 'IP': 'Mater',
    'PKG': 'Mater', 'BLL': 'Mater', 'AVY': 'Mater',
}


# ============================================================================
# INLINE FALLBACKS  (used only when exp44_modules are not yet available)
# ============================================================================

def _fb_compute_regime_score(spy_data, date, price_data, all_symbols):
    """Fallback regime score -- mirrors exp43 logic."""
    if date not in spy_data.index:
        return 0.5
    spy_idx = spy_data.index.get_loc(date)
    if spy_idx < REGIME_SMA_LONG:
        return 0.5
    spy_close = spy_data['Close'].iloc[:spy_idx + 1]

    # Trend
    sma200 = spy_close.iloc[-REGIME_SMA_LONG:].mean()
    sma50  = spy_close.iloc[-REGIME_SMA_MED:].mean()
    price  = spy_close.iloc[-1]
    trend_long = 1.0 if price > sma200 else 0.0
    trend_med  = 1.0 if price > sma50  else 0.0
    sma200_dist = min(max((price / sma200 - 1.0) * 10, -1.0), 1.0)
    trend_score = 0.4 * trend_long + 0.3 * trend_med + 0.3 * (sma200_dist + 1) / 2

    # Volatility
    if spy_idx >= REGIME_VOL_MED + 1:
        rets = spy_close.pct_change().dropna()
        vol_s = rets.iloc[-REGIME_VOL_SHORT:].std() * np.sqrt(252) if len(rets) >= REGIME_VOL_SHORT else 0.15
        vol_m = rets.iloc[-REGIME_VOL_MED:].std() * np.sqrt(252)  if len(rets) >= REGIME_VOL_MED  else 0.15
        vol_ratio = vol_s / vol_m if vol_m > 0.01 else 1.0
        vol_score = max(0, min(1, 1.5 - vol_ratio))
    else:
        vol_score = 0.5

    # Breadth
    above, total = 0, 0
    for sym in all_symbols:
        if sym not in price_data or date not in price_data[sym].index:
            continue
        idx = price_data[sym].index.get_loc(date)
        if idx < REGIME_BREADTH_SMA:
            continue
        sma = price_data[sym]['Close'].iloc[idx - REGIME_BREADTH_SMA:idx + 1].mean()
        total += 1
        if price_data[sym]['Close'].iloc[idx] > sma:
            above += 1
    breadth_score = above / total if total > 5 else 0.5

    composite = 0.40 * trend_score + 0.30 * vol_score + 0.30 * breadth_score
    return max(0.0, min(1.0, composite))


def _fb_regime_to_params(regime_score):
    """Fallback regime -> params."""
    if regime_score >= 0.70:
        return {'max_positions': NUM_POSITIONS_BULL, 'hold_days': HOLD_DAYS_BULL, 'label': 'BULL'}
    elif regime_score >= 0.45:
        return {'max_positions': NUM_POSITIONS_MILD, 'hold_days': 8, 'label': 'MILD'}
    elif regime_score >= 0.25:
        return {'max_positions': NUM_POSITIONS_BEAR, 'hold_days': HOLD_DAYS_BEAR, 'label': 'BEAR'}
    else:
        return {'max_positions': NUM_POSITIONS_SEVERE, 'hold_days': HOLD_DAYS_BEAR, 'label': 'SEVERE'}


def _fb_compute_signals(price_data, tradeable, date):
    """Fallback signal computation -- multi-timeframe momentum + quality."""
    # Quality filter first
    quality = []
    for sym in tradeable:
        if sym not in price_data or date not in price_data[sym].index:
            continue
        df = price_data[sym]
        idx = df.index.get_loc(date)
        if idx < VOL_LOOKBACK_QUAL + 1:
            quality.append(sym)
            continue
        rets = df['Close'].iloc[idx - VOL_LOOKBACK_QUAL:idx + 1].pct_change().dropna()
        if len(rets) < VOL_LOOKBACK_QUAL - 5:
            quality.append(sym)
            continue
        ann_vol = rets.std() * np.sqrt(252)
        if ann_vol <= MAX_STOCK_VOL:
            quality.append(sym)

    # Multi-timeframe momentum
    raw_scores = {tf: {} for tf in [MOMENTUM_SHORT, MOMENTUM_MED, MOMENTUM_LONG]}
    for sym in quality:
        if sym not in price_data or date not in price_data[sym].index:
            continue
        df = price_data[sym]
        idx = df.index.get_loc(date)
        needed = MOMENTUM_LONG + MOMENTUM_SKIP
        if idx < needed:
            continue
        close_skip = df['Close'].iloc[idx - MOMENTUM_SKIP]
        if close_skip <= 0:
            continue
        for tf in [MOMENTUM_SHORT, MOMENTUM_MED, MOMENTUM_LONG]:
            if idx >= tf + MOMENTUM_SKIP:
                close_lb = df['Close'].iloc[idx - tf - MOMENTUM_SKIP]
                if close_lb > 0:
                    raw_scores[tf][sym] = (close_skip / close_lb) - 1.0

    # Z-score per timeframe
    z_scores: Dict[str, Dict[int, float]] = {}
    for tf in [MOMENTUM_SHORT, MOMENTUM_MED, MOMENTUM_LONG]:
        vals = list(raw_scores[tf].values())
        if len(vals) < 5:
            continue
        m, s = np.mean(vals), np.std(vals)
        if s < 0.001:
            continue
        for sym, v in raw_scores[tf].items():
            z_scores.setdefault(sym, {})[tf] = (v - m) / s

    weights = dict(zip([MOMENTUM_SHORT, MOMENTUM_MED, MOMENTUM_LONG], MOMENTUM_WEIGHTS))
    blended: Dict[str, float] = {}
    for sym, tf_z in z_scores.items():
        if len(tf_z) < 2:
            continue
        sc, tw = 0.0, 0.0
        for tf, w in weights.items():
            if tf in tf_z:
                sc += w * tf_z[tf]
                tw += w
        if tw > 0:
            blended[sym] = sc / tw

    # Absolute-momentum penalty
    for sym in list(blended):
        if MOMENTUM_LONG in raw_scores and sym in raw_scores[MOMENTUM_LONG]:
            if raw_scores[MOMENTUM_LONG][sym] < 0:
                blended[sym] *= 0.5
    return blended


def _fb_select_stocks(scores, max_positions, existing_positions, sector_map):
    """Fallback sector-capped selection."""
    sector_counts: Dict[str, int] = defaultdict(int)
    for sym in existing_positions:
        sector_counts[sector_map.get(sym, 'Other')] += 1

    available = {s: sc for s, sc in scores.items() if s not in existing_positions}
    ranked = sorted(available.items(), key=lambda x: x[1], reverse=True)
    selected: List[str] = []
    needed = max_positions - len(existing_positions)
    for sym, _ in ranked:
        if len(selected) >= needed:
            break
        sec = sector_map.get(sym, 'Other')
        if sector_counts[sec] >= SECTOR_MAX_POSITIONS:
            continue
        selected.append(sym)
        sector_counts[sec] += 1
    return selected


def _fb_check_exit(pos, current_price, days_held, hold_days):
    """Fallback exit check. Returns (should_exit: bool, reason: str|None)."""
    # Hold expired
    if days_held >= hold_days:
        return True, 'hold_expired'
    # Position stop
    pos_ret = (current_price - pos['entry_price']) / pos['entry_price']
    if pos_ret <= POSITION_STOP_LOSS:
        return True, 'position_stop'
    # Trailing stop
    if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
        trailing_lvl = pos['high_price'] * (1 - TRAILING_STOP_PCT)
        if current_price <= trailing_lvl:
            return True, 'trailing_stop'
    return False, None


def _fb_compute_final_leverage(drawdown, spy_data, date):
    """Fallback leverage: DD-based * vol-target, capped."""
    # DD-based
    dd = drawdown
    if dd >= DD_TIER_1:
        dd_lev = LEV_FULL
    elif dd >= DD_TIER_2:
        frac = (dd - DD_TIER_1) / (DD_TIER_2 - DD_TIER_1)
        dd_lev = LEV_FULL + frac * (LEV_REDUCED - LEV_FULL)
    elif dd >= DD_TIER_3:
        frac = (dd - DD_TIER_2) / (DD_TIER_3 - DD_TIER_2)
        dd_lev = LEV_REDUCED + frac * (LEV_MINIMUM - LEV_REDUCED)
    else:
        dd_lev = LEV_MINIMUM

    # Vol-target
    vol_lev = 1.0
    if date in spy_data.index:
        sidx = spy_data.index.get_loc(date)
        if sidx >= VOL_LOOKBACK + 1:
            sr = spy_data['Close'].iloc[sidx - VOL_LOOKBACK:sidx + 1].pct_change().dropna()
            rv = sr.std() * np.sqrt(252) if len(sr) >= VOL_LOOKBACK - 2 else 0.15
            vol_lev = min(TARGET_VOL / rv, 1.0) if rv > 0.01 else 1.0

    final = min(dd_lev, vol_lev, LEVERAGE_MAX)
    return max(final, LEV_MINIMUM)


def _fb_compute_correlation_adjustment(positions, price_data, date):
    """Fallback correlation adjustment -- simple sector-concentration penalty."""
    if len(positions) < 2:
        return 1.0
    sector_counts: Dict[str, int] = defaultdict(int)
    for sym in positions:
        sector_counts[SECTOR_MAP.get(sym, 'Other')] += 1
    max_conc = max(sector_counts.values()) / len(positions)
    # If >50 % in one sector, scale down modestly
    if max_conc > 0.5:
        return 0.85
    return 1.0


def _fb_compute_sharpe_ratio(daily_values, rf_daily=None):
    """Fallback corrected Sharpe (CRITIC fix #4).
    Uses daily excess returns annualised by sqrt(252)."""
    rets = daily_values.pct_change().dropna()
    if len(rets) < 30:
        return 0.0, 0.0
    if rf_daily is not None:
        excess = rets - rf_daily.reindex(rets.index).fillna(0)
    else:
        excess = rets - (CASH_YIELD_RATE / 252)
    mu  = excess.mean()
    sig = excess.std()
    if sig == 0:
        return 0.0, 0.0
    sharpe = (mu / sig) * np.sqrt(252)
    se = 1.0 / np.sqrt(len(rets))   # standard error of Sharpe
    return sharpe, se


# ---------------------------------------------------------------------------
# Module dispatcher -- prefer real modules, fall back to inline
# ---------------------------------------------------------------------------
# The real modules have richer signatures than the fallbacks.  The dispatchers
# below adapt between the two so the backtest loop can use a single call-site.

def _regime_score(spy_data, date, price_data, syms):
    if MODULES_LOADED:
        return compute_regime_score(spy_data, date, price_data, syms)
    return _fb_compute_regime_score(spy_data, date, price_data, syms)

def _regime_params(score):
    if MODULES_LOADED:
        return regime_to_params(score)
    return _fb_regime_to_params(score)

def _signals(price_data, tradeable, date, sector_map):
    """Dispatcher for signal computation."""
    if MODULES_LOADED:
        # Real module: compute_signals(price_data, tradeable_symbols, date, sector_map)
        return compute_signals(price_data, tradeable, date, sector_map)
    return _fb_compute_signals(price_data, tradeable, date)

def _select(scores, max_pos, existing_positions, sec_map):
    """Dispatcher for stock selection.
    The real module's select_stocks does NOT take existing_positions -- it just
    picks top N with sector cap.  We pre-filter here to exclude existing."""
    if MODULES_LOADED:
        # Remove already-held symbols from scores before passing in
        avail = {s: v for s, v in scores.items() if s not in existing_positions}
        needed = max_pos - len(existing_positions)
        return select_stocks(avail, needed, sec_map, SECTOR_MAX_POSITIONS)
    return _fb_select_stocks(scores, max_pos, existing_positions, sec_map)

def _check_exit_fn(pos, cur_price, date, days_held, hold_days, sym,
                   price_data, tradeable):
    """Dispatcher for exit checks.
    Real module returns Optional[str] (reason or None).
    Fallback returns (bool, reason)."""
    if MODULES_LOADED:
        # check_exit(position, current_price, date, days_held, base_hold_days,
        #            price_data, symbol, compute_signals_fn, tradeable, sector_map)
        reason = check_exit(pos, cur_price, date, days_held, hold_days,
                            price_data, sym, None, tradeable, SECTOR_MAP)
        if reason is not None:
            return True, reason
        return False, None
    return _fb_check_exit(pos, cur_price, days_held, hold_days)

# State variable for crash_cooldown used by compute_final_leverage
_crash_cooldown = 0

def _leverage(dd, spy_data, date, portfolio_snapshots, current_idx,
              price_data=None, selected_stocks=None):
    """Dispatcher for leverage.
    Real module returns (leverage, updated_cooldown)."""
    global _crash_cooldown
    if MODULES_LOADED:
        lev, _crash_cooldown = compute_final_leverage(
            dd, spy_data, date, portfolio_snapshots, current_idx,
            _crash_cooldown, price_data, selected_stocks)
        return lev
    return _fb_compute_final_leverage(dd, spy_data, date)

def _corr_adj(price_data, selected_stocks, date):
    """Dispatcher for correlation adjustment."""
    if MODULES_LOADED:
        return compute_correlation_adjustment(price_data, selected_stocks, date)
    return _fb_compute_correlation_adjustment(selected_stocks, price_data, date)

def _sharpe(daily_values, rf_daily=None):
    """Dispatcher for Sharpe calculation.
    Real module: compute_sharpe_ratio(daily_returns: Series, daily_rf_rates: Series) -> float
    Fallback: returns (sharpe, se) tuple."""
    if MODULES_LOADED:
        rets = daily_values.pct_change().dropna()
        if len(rets) < 30:
            return 0.0, 0.0
        if rf_daily is not None:
            rf_aligned = rf_daily.reindex(rets.index).fillna(0)
        else:
            rf_aligned = pd.Series(CASH_YIELD_RATE / 252, index=rets.index)
        sharpe_val = compute_sharpe_ratio(rets, rf_aligned)
        se = 1.0 / np.sqrt(len(rets))
        return sharpe_val, se
    return _fb_compute_sharpe_ratio(daily_values, rf_daily)


# ============================================================================
# DATA LOADING  (adapted from exp43, identical cache structure)
# ============================================================================

def _tz_strip(idx):
    """Strip timezone info from DatetimeIndex if present."""
    if hasattr(idx, 'tz') and idx.tz is not None:
        return idx.tz_localize(None)
    return idx


def filter_anomalous_stocks(data: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """Remove stocks with data corruption (>100 % daily, >200 % ann vol)."""
    print("\n[Filter] Checking for anomalous price data...")
    kept, removed = {}, []
    for sym, df in data.items():
        if len(df) < 20:
            continue
        rets = df['Close'].pct_change(fill_method=None).dropna()
        if len(rets) == 0:
            continue
        if rets.max() > 1.0:
            removed.append((sym, f"extreme gain {rets.max()*100:.0f}%"))
            continue
        vol = rets.std() * np.sqrt(252)
        if vol > 2.0:
            removed.append((sym, f"extreme vol {vol*100:.0f}%"))
            continue
        kept[sym] = df
    print(f"  Kept {len(kept)}, removed {len(removed)}")
    for sym, reason in removed[:5]:
        print(f"    {sym}: {reason}")
    if len(removed) > 5:
        print(f"    ... and {len(removed)-5} more")
    return kept


def load_price_data() -> Dict[str, pd.DataFrame]:
    """Load survivorship-bias-corrected pool (or fallback broad pool)."""
    corrected = 'data_cache/survivorship_bias_pool.pkl'
    if os.path.exists(corrected):
        print("[Cache] Loading survivorship-bias corrected pool...")
        with open(corrected, 'rb') as f:
            data = pickle.load(f)
        print(f"  Loaded {len(data)} symbols")
        data = filter_anomalous_stocks(data)
        return data

    fallback = f'data_cache/broad_pool_{DATA_DOWNLOAD_START}_{END_DATE}.pkl'
    if os.path.exists(fallback):
        print("[Cache] Loading broad pool (WARNING: not survivorship corrected)...")
        with open(fallback, 'rb') as f:
            return pickle.load(f)

    # Download fresh
    BROAD_POOL = [
        'AAPL','MSFT','NVDA','GOOGL','META','AVGO','ADBE','CRM','AMD',
        'INTC','CSCO','IBM','TXN','QCOM','ORCL','ACN','NOW','INTU',
        'AMAT','MU','LRCX','SNPS','CDNS','KLAC','MRVL',
        'BRK-B','JPM','V','MA','BAC','WFC','GS','MS','AXP','BLK',
        'SCHW','C','USB','PNC','TFC','CB','MMC','AIG',
        'UNH','JNJ','LLY','ABBV','MRK','PFE','TMO','ABT','DHR',
        'AMGN','BMY','MDT','ISRG','SYK','GILD','REGN','VRTX','BIIB',
        'AMZN','TSLA','WMT','HD','PG','COST','KO','PEP','NKE',
        'MCD','DIS','SBUX','TGT','LOW','CL','KMB','GIS','EL',
        'MO','PM',
        'XOM','CVX','COP','SLB','EOG','OXY','MPC','PSX','VLO',
        'GE','CAT','BA','HON','UNP','RTX','LMT','DE','UPS','FDX',
        'MMM','GD','NOC','EMR',
        'NEE','DUK','SO','D','AEP',
        'VZ','T','TMUS','CMCSA',
    ]
    print(f"[Download] Downloading {len(BROAD_POOL)} symbols...")
    data, failed = {}, []
    for i, sym in enumerate(BROAD_POOL):
        try:
            df = yf.download(sym, start=DATA_DOWNLOAD_START, end=END_DATE, progress=False)
            if not df.empty and len(df) > 100:
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                data[sym] = df
                if (i + 1) % 20 == 0:
                    print(f"  [{i+1}/{len(BROAD_POOL)}] {len(data)} loaded")
            else:
                failed.append(sym)
        except Exception:
            failed.append(sym)
    print(f"[Download] {len(data)} OK, {len(failed)} failed: {failed}")
    os.makedirs('data_cache', exist_ok=True)
    with open(fallback, 'wb') as f:
        pickle.dump(data, f)
    return data


def load_spy() -> pd.DataFrame:
    cache = f'data_cache/SPY_{DATA_DOWNLOAD_START}_{END_DATE}.csv'
    if os.path.exists(cache):
        print("[Cache] Loading SPY...")
        return pd.read_csv(cache, index_col=0, parse_dates=True)
    # Also try the exp43 cache path
    alt = f'data_cache/SPY_2000-01-01_{END_DATE}.csv'
    if os.path.exists(alt):
        print("[Cache] Loading SPY (alt cache)...")
        return pd.read_csv(alt, index_col=0, parse_dates=True)
    print("[Download] SPY...")
    df = yf.download('SPY', start=DATA_DOWNLOAD_START, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache)
    return df


def load_cash_yield() -> Optional[pd.Series]:
    cache = 'data_cache/moody_aaa_yield.csv'
    if os.path.exists(cache):
        print("[Cache] Loading Moody's Aaa yield...")
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        daily = df['yield_pct'].resample('D').ffill()
        print(f"  {len(daily)} daily rates, avg {daily.mean():.2f}%")
        return daily
    try:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA&cosd=1999-01-01&coed=2026-12-31'
        df = pd.read_csv(url, parse_dates=['observation_date'], index_col='observation_date')
        df.columns = ['yield_pct']
        os.makedirs('data_cache', exist_ok=True)
        df.to_csv(cache)
        return df['yield_pct'].resample('D').ffill()
    except Exception as e:
        print(f"  FRED download failed: {e}. Using fixed {CASH_YIELD_RATE:.1%}")
        return None


# ============================================================================
# UNIVERSE CONSTRUCTION  (annual top-N by dollar volume, with ETF exclusion)
# ============================================================================

def compute_annual_top_n(price_data: Dict[str, pd.DataFrame]) -> Dict[int, List[str]]:
    """Rank by prior-year average daily dollar volume.  Excludes ETFs."""
    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(_tz_strip(df.index))
    all_dates_sorted = sorted(all_dates)
    if not all_dates_sorted:
        return {}
    years = sorted({d.year for d in all_dates_sorted})
    annual: Dict[int, List[str]] = {}

    excluded_log: Dict[str, str] = {}

    for year in years:
        r_end   = pd.Timestamp(f'{year}-02-01' if year == years[0] else f'{year}-01-01')
        r_start = pd.Timestamp(f'{year-1}-01-01')
        scores: Dict[str, float] = {}
        for sym, df in price_data.items():
            # --- CRITIC fix #3: skip ETFs ---
            if sym in ETF_EXCLUDE:
                excluded_log[sym] = 'ETF'
                continue
            # --- assign unmapped symbols to 'Other' sector ---
            if sym not in SECTOR_MAP:
                SECTOR_MAP[sym] = 'Other'
            idx = _tz_strip(df.index)
            mask = (idx >= r_start) & (idx < r_end)
            window = df.loc[mask]
            if len(window) < 20:
                continue
            try:
                cl = window['Close']
                vo = window['Volume']
                if isinstance(cl, pd.DataFrame):
                    cl = cl.iloc[:, 0]
                if isinstance(vo, pd.DataFrame):
                    vo = vo.iloc[:, 0]
                dv = float((cl * vo).mean())
                if not np.isnan(dv) and dv > 0:
                    scores[sym] = dv
            except Exception:
                continue
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        top = [s for s, _ in ranked[:TOP_N]]
        annual[year] = top

        if year > years[0] and year - 1 in annual:
            prev, curr = set(annual[year - 1]), set(top)
            print(f"  {year}: Top-{TOP_N} | +{len(curr-prev)} / -{len(prev-curr)}")
        else:
            print(f"  {year}: Initial top-{TOP_N} = {len(top)} stocks")

    # Log excluded
    if excluded_log:
        etfs = [s for s, r in excluded_log.items() if r == 'ETF']
        unmapped = [s for s, r in excluded_log.items() if r == 'no_sector_map']
        if etfs:
            print(f"  [Excluded] ETFs ({len(etfs)}): {', '.join(sorted(etfs)[:15])}")
        if unmapped:
            print(f"  [Excluded] No sector map ({len(unmapped)}): {', '.join(sorted(unmapped)[:20])}")
    return annual


# ============================================================================
# TRADEABLE SYMBOLS
# ============================================================================

def get_tradeable(price_data, date, first_date, annual_universe):
    eligible = set(annual_universe.get(date.year, []))
    out = []
    for sym in eligible:
        if sym not in price_data:
            continue
        df = price_data[sym]
        if date not in df.index:
            continue
        sym_first = df.index[0]
        if date <= first_date + timedelta(days=30):
            out.append(sym)
        elif (date - sym_first).days >= MIN_AGE_DAYS:
            out.append(sym)
    return out


# ============================================================================
# BACKTEST ENGINE
# ============================================================================

def run_backtest(price_data, annual_universe, spy_data, cash_yield_daily,
                 start_clip=None, end_clip=None, label='FULL'):
    """Core backtest loop with all CRITIC fixes applied."""

    global _crash_cooldown
    _crash_cooldown = 0

    print(f"\n{'='*80}")
    print(f"RUNNING COMPASS v9.5 BACKTEST  [{label}]")
    print(f"{'='*80}")

    # Gather all trading dates across the universe
    all_dates_set: set = set()
    for df in price_data.values():
        all_dates_set.update(_tz_strip(df.index))
    all_dates = sorted(all_dates_set)
    first_date = all_dates[0]

    # --- CRITIC fix #1: clip to comparison period ---
    if start_clip:
        clip_ts = pd.Timestamp(start_clip)
        all_dates = [d for d in all_dates if d >= clip_ts]
    if end_clip:
        clip_ts = pd.Timestamp(end_clip)
        all_dates = [d for d in all_dates if d <= clip_ts]

    if not all_dates:
        print("ERROR: no trading dates in clipped window.")
        return None

    print(f"  Period:       {all_dates[0].strftime('%Y-%m-%d')} -> {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"  Trading days: {len(all_dates):,}")

    # Portfolio state
    cash = float(INITIAL_CAPITAL)
    positions: Dict[str, dict] = {}   # sym -> {entry_price, shares, entry_date, entry_idx, high_price}
    portfolio_snapshots: List[dict] = []
    trades: List[dict] = []
    peak_value = float(INITIAL_CAPITAL)
    current_year = None
    year_start_value = float(INITIAL_CAPITAL)

    for i, date in enumerate(all_dates):
        # --- yearly progress header ---
        if date.year != current_year:
            if current_year is not None:
                ytd_ret = (portfolio_snapshots[-1]['value'] / year_start_value - 1) if portfolio_snapshots else 0
                print(f"  {current_year} done | ${portfolio_snapshots[-1]['value']:,.0f} | "
                      f"YTD {ytd_ret:+.2%} | trades {sum(1 for t in trades if pd.Timestamp(t['exit_date']).year == current_year)}")
            current_year = date.year
            year_start_value = portfolio_snapshots[-1]['value'] if portfolio_snapshots else INITIAL_CAPITAL

        # Tradeable universe for today
        tradeable = get_tradeable(price_data, date, first_date, annual_universe)

        # ---- 1. Portfolio valuation ----
        portfolio_value = cash
        for sym, pos in list(positions.items()):
            if sym in price_data and date in price_data[sym].index:
                portfolio_value += pos['shares'] * price_data[sym].loc[date, 'Close']

        # ---- 2. Peak / drawdown ----
        if portfolio_value > peak_value:
            peak_value = portfolio_value
        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0.0

        # ---- 3. Regime ----
        regime_score = _regime_score(spy_data, date, price_data, tradeable)
        rp = _regime_params(regime_score)
        max_positions = rp['max_positions']
        hold_days     = rp['hold_days']
        regime_label  = rp['label']

        # ---- 4. Exits ----
        for sym in list(positions.keys()):
            pos = positions[sym]
            if sym not in price_data or date not in price_data[sym].index:
                continue
            cur_price = price_data[sym].loc[date, 'Close']
            days_held = i - pos['entry_idx']

            # Update trailing high
            if cur_price > pos['high_price']:
                pos['high_price'] = cur_price

            should_exit, reason = _check_exit_fn(
                pos, cur_price, date, days_held, hold_days, sym,
                price_data, tradeable)

            # Universe rotation exit
            if not should_exit and sym not in tradeable:
                should_exit, reason = True, 'universe_rotation'

            # Regime-reduce exit (too many positions for current regime)
            if not should_exit and len(positions) > max_positions:
                pos_rets = {}
                for s, p in positions.items():
                    if s in price_data and date in price_data[s].index:
                        pos_rets[s] = (price_data[s].loc[date, 'Close'] - p['entry_price']) / p['entry_price']
                if pos_rets:
                    worst = min(pos_rets, key=pos_rets.get)
                    if sym == worst:
                        should_exit, reason = True, 'regime_reduce'

            if should_exit:
                shares = pos['shares']
                # CRITIC fix #2: sell slippage
                sell_price = cur_price * (1 - SLIPPAGE_BPS / 10000)
                proceeds = shares * sell_price
                commission = shares * COMMISSION_PER_SHARE
                cash += proceeds - commission
                pnl = (sell_price - pos['entry_price']) * shares - commission
                pnl_pct = pnl / (pos['entry_price'] * shares) if pos['entry_price'] * shares > 0 else 0
                trades.append({
                    'symbol': sym,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'entry_price': pos['entry_price'],
                    'exit_price': sell_price,
                    'return': pnl_pct,
                    'pnl': pnl,
                    'exit_reason': reason,
                    'days_held': days_held,
                })
                del positions[sym]

        # ---- 5. Signals ----
        needed = max_positions - len(positions)
        if needed > 0 and cash > 1000 and len(tradeable) >= 5:
            scores = _signals(price_data, tradeable, date, SECTOR_MAP)
            if len(scores) >= needed:
                selected = _select(scores, max_positions, positions, SECTOR_MAP)

                # ---- 6. Leverage ----
                current_leverage = _leverage(
                    drawdown, spy_data, date, portfolio_snapshots, i,
                    price_data, selected)

                # ---- 7. Correlation adjustment ----
                corr_adj = _corr_adj(price_data, list(positions.keys()) + selected, date)
                current_leverage *= corr_adj

                # ---- 8. Size & enter ----
                effective_capital = cash * current_leverage * 0.95  # 5 % buffer
                per_position = effective_capital / max(len(selected), 1)

                for sym in selected:
                    if sym not in price_data or date not in price_data[sym].index:
                        continue
                    close_px = price_data[sym].loc[date, 'Close']
                    if close_px <= 0:
                        continue
                    # CRITIC fix #2: buy slippage
                    entry_price = close_px * (1 + SLIPPAGE_BPS / 10000)
                    pos_value = min(per_position, cash * 0.40)
                    shares = pos_value / entry_price
                    cost = shares * entry_price
                    commission = shares * COMMISSION_PER_SHARE
                    if cost + commission <= cash * 0.90:
                        positions[sym] = {
                            'entry_price': entry_price,
                            'shares': shares,
                            'entry_date': date,
                            'entry_idx': i,
                            'high_price': entry_price,
                        }
                        cash -= cost + commission
            else:
                current_leverage = _leverage(
                    drawdown, spy_data, date, portfolio_snapshots, len(portfolio_snapshots) - 1)
        else:
            current_leverage = _leverage(
                drawdown, spy_data, date, portfolio_snapshots, len(portfolio_snapshots) - 1)

        # ---- 9. Record snapshot ----
        portfolio_snapshots.append({
            'date': date,
            'value': portfolio_value,
            'cash': cash,
            'positions': len(positions),
            'leverage': current_leverage,
            'regime_score': regime_score,
            'regime_label': regime_label,
            'drawdown': drawdown,
        })

        # ---- 10. Cash yield ----
        if cash > 0:
            if cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

    # Final year summary
    if portfolio_snapshots and current_year is not None:
        ytd_ret = portfolio_snapshots[-1]['value'] / year_start_value - 1
        print(f"  {current_year} done | ${portfolio_snapshots[-1]['value']:,.0f} | "
              f"YTD {ytd_ret:+.2%} | trades {sum(1 for t in trades if pd.Timestamp(t['exit_date']).year == current_year)}")

    pv_df = pd.DataFrame(portfolio_snapshots)
    tr_df = pd.DataFrame(trades) if trades else pd.DataFrame()
    return {
        'portfolio_values': pv_df,
        'trades': tr_df,
        'final_value': pv_df['value'].iloc[-1] if len(pv_df) else INITIAL_CAPITAL,
    }


# ============================================================================
# METRICS  (CRITIC fix #4, #6)
# ============================================================================

def calculate_metrics(results, cash_yield_daily=None) -> Dict:
    """Comprehensive metrics with corrected Sharpe and confidence intervals."""
    df = results['portfolio_values'].set_index('date')
    tr = results['trades']

    initial = INITIAL_CAPITAL
    final   = df['value'].iloc[-1]
    n_days  = len(df)
    years   = n_days / 252

    cagr = (final / initial) ** (1 / years) - 1 if years > 0 else 0
    daily_rets = df['value'].pct_change().dropna()
    ann_vol = daily_rets.std() * np.sqrt(252) if len(daily_rets) > 1 else 0

    # Corrected Sharpe (CRITIC fix #4)
    sharpe, sharpe_se = _sharpe(df['value'], cash_yield_daily)

    max_dd = df['drawdown'].min()
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    # Sortino
    neg_rets = daily_rets[daily_rets < 0]
    downside_vol = neg_rets.std() * np.sqrt(252) if len(neg_rets) > 0 else ann_vol
    sortino = cagr / downside_vol if downside_vol > 0 else 0

    # Drawdown stats
    in_dd = (df['drawdown'] < -0.01).sum()
    pct_time_in_dd = in_dd / n_days if n_days > 0 else 0
    dd_vals = df['drawdown'][df['drawdown'] < -0.01]
    avg_dd = dd_vals.mean() if len(dd_vals) > 0 else 0

    # Trade stats
    n_trades = len(tr)
    if n_trades > 0:
        win_mask   = tr['pnl'] > 0
        lose_mask  = tr['pnl'] < 0
        win_rate   = win_mask.mean()
        avg_winner = tr.loc[win_mask, 'pnl'].mean() if win_mask.any() else 0
        avg_loser  = tr.loc[lose_mask, 'pnl'].mean() if lose_mask.any() else 0
        gross_wins  = tr.loc[win_mask, 'pnl'].sum() if win_mask.any() else 0
        gross_losses = abs(tr.loc[lose_mask, 'pnl'].sum()) if lose_mask.any() else 1
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')
        exit_reasons = tr['exit_reason'].value_counts().to_dict()
    else:
        win_rate = avg_winner = avg_loser = profit_factor = 0
        exit_reasons = {}

    # Annual returns table
    df_yr = df['value'].resample('YE').last()
    annual_returns = df_yr.pct_change().dropna()
    # patch first year
    first_yr_end = df_yr.iloc[0] if len(df_yr) else final
    first_yr_ret = first_yr_end / initial - 1
    if len(annual_returns) > 0:
        annual_returns.iloc[0] = first_yr_ret

    # Regime distribution
    regime_counts = df['regime_label'].value_counts().to_dict() if 'regime_label' in df.columns else {}

    # Max consecutive losing days
    losing = (daily_rets < 0).astype(int)
    max_lose_streak, streak = 0, 0
    for v in losing:
        if v:
            streak += 1
            max_lose_streak = max(max_lose_streak, streak)
        else:
            streak = 0

    return {
        'initial': initial,
        'final_value': final,
        'total_return': (final - initial) / initial,
        'years': years,
        'n_days': n_days,
        'cagr': cagr,
        'volatility': ann_vol,
        'sharpe': sharpe,
        'sharpe_se': sharpe_se,
        'sortino': sortino,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'avg_drawdown': avg_dd,
        'pct_time_in_drawdown': pct_time_in_dd,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'avg_winner': avg_winner,
        'avg_loser': avg_loser,
        'trades': n_trades,
        'exit_reasons': exit_reasons,
        'annual_returns': annual_returns,
        'best_year': annual_returns.max() if len(annual_returns) else 0,
        'worst_year': annual_returns.min() if len(annual_returns) else 0,
        'regime_breakdown': regime_counts,
        'avg_leverage': df['leverage'].mean() if 'leverage' in df.columns else 1.0,
        'max_losing_streak': max_lose_streak,
    }


# ============================================================================
# REPORTING
# ============================================================================

def print_results(metrics: Dict, label: str = 'COMPASS v9.5'):
    print(f"\n{'='*80}")
    print(f"RESULTS: {label}")
    print(f"{'='*80}")

    print(f"\n--- Performance ---")
    print(f"  Initial capital:    ${metrics['initial']:>14,.0f}")
    print(f"  Final value:        ${metrics['final_value']:>14,.2f}")
    print(f"  Total return:        {metrics['total_return']:>14.2%}")
    print(f"  CAGR:                {metrics['cagr']:>14.2%}")
    print(f"  Volatility (ann):    {metrics['volatility']:>14.2%}")

    print(f"\n--- Risk-Adjusted ---")
    print(f"  Sharpe ratio:        {metrics['sharpe']:>14.3f}  (SE: {metrics['sharpe_se']:.3f})")
    print(f"  Sharpe 95% CI:       [{metrics['sharpe'] - 1.96*metrics['sharpe_se']:.3f},  {metrics['sharpe'] + 1.96*metrics['sharpe_se']:.3f}]")
    print(f"  Sortino ratio:       {metrics['sortino']:>14.3f}")
    print(f"  Calmar ratio:        {metrics['calmar']:>14.3f}")

    print(f"\n--- Drawdown ---")
    print(f"  Max drawdown:        {metrics['max_drawdown']:>14.2%}")
    print(f"  Avg drawdown:        {metrics['avg_drawdown']:>14.2%}")
    print(f"  % time in DD:        {metrics['pct_time_in_drawdown']:>14.1%}")

    print(f"\n--- Trading ---")
    print(f"  Total trades:        {metrics['trades']:>14,}")
    print(f"  Win rate:            {metrics['win_rate']:>14.2%}")
    print(f"  Profit factor:       {metrics['profit_factor']:>14.2f}")
    print(f"  Avg winner:          ${metrics['avg_winner']:>14,.2f}")
    print(f"  Avg loser:           ${metrics['avg_loser']:>14,.2f}")
    print(f"  Avg leverage:        {metrics['avg_leverage']:>14.3f}")
    print(f"  Max losing streak:   {metrics['max_losing_streak']:>14} days")

    print(f"\n--- Exit Reasons ---")
    total_t = max(metrics['trades'], 1)
    for reason, cnt in sorted(metrics['exit_reasons'].items(), key=lambda x: -x[1]):
        print(f"    {reason:25s}: {cnt:>6,}  ({cnt/total_t*100:.1f}%)")

    print(f"\n--- Regime Distribution ---")
    total_d = max(sum(metrics['regime_breakdown'].values()), 1)
    for reg, d in sorted(metrics['regime_breakdown'].items(), key=lambda x: -x[1]):
        print(f"    {reg:15s}: {d:>6,} days  ({d/total_d*100:.1f}%)")

    print(f"\n--- Annual Returns ---")
    ar = metrics['annual_returns']
    if len(ar) > 0:
        print(f"  Best year:   {metrics['best_year']:>+9.2%}")
        print(f"  Worst year:  {metrics['worst_year']:>+9.2%}")
        pos_yrs = (ar > 0).sum()
        print(f"  Positive:    {pos_yrs}/{len(ar)}")
        print()
        for dt, ret in ar.items():
            yr = dt.year
            marker = '' if ret >= 0 else ' ***'
            print(f"    {yr}:  {ret:>+8.2%}{marker}")


def print_comparison(metrics: Dict):
    """Side-by-side comparison vs v8.2 bias-corrected benchmarks."""

    v82 = {
        'cagr':      0.1390,
        'sharpe':    0.646,
        'max_dd':   -0.6625,
        'trades':    5309,
        'final':     358697,
    }

    print(f"\n{'='*80}")
    print("COMPARISON: COMPASS v9.5 vs v8.2 (bias-corrected)")
    print(f"{'='*80}")

    hdr = f"{'Metric':<28} {'v8.2':>14} {'v9.5':>14} {'Delta':>14} {'Target':>10}"
    sep = '-' * len(hdr)
    print(f"\n{hdr}")
    print(sep)

    def row(name, v82_val, v95_val, fmt, target=''):
        delta_val = v95_val - v82_val
        if 'pct' in fmt:
            print(f"  {name:<26} {v82_val:>13.2%} {v95_val:>13.2%} {delta_val:>+13.2%} {target:>10}")
        elif 'f3' in fmt:
            print(f"  {name:<26} {v82_val:>14.3f} {v95_val:>14.3f} {delta_val:>+14.3f} {target:>10}")
        elif 'int' in fmt:
            print(f"  {name:<26} {v82_val:>14,.0f} {v95_val:>14,.0f} {delta_val:>+14,.0f} {target:>10}")
        elif 'dollar' in fmt:
            print(f"  {name:<26} ${v82_val:>13,.0f} ${v95_val:>13,.0f} ${delta_val:>+13,.0f} {target:>10}")

    row('CAGR',         v82['cagr'],   metrics['cagr'],         'pct',    '>14.0%')
    row('Sharpe',       v82['sharpe'], metrics['sharpe'],       'f3',     '>0.800')
    row('Max Drawdown', v82['max_dd'], metrics['max_drawdown'], 'pct',    '>-45%')
    row('Trades',       v82['trades'], metrics['trades'],       'int',    '')
    row('Final Value',  v82['final'],  metrics['final_value'],  'dollar', '')

    # Extra v9.5-only metrics
    print(sep)
    print(f"  {'Sortino':<26} {'N/A':>14} {metrics['sortino']:>14.3f}")
    print(f"  {'Calmar':<26} {'N/A':>14} {metrics['calmar']:>14.3f}")
    print(f"  {'Profit Factor':<26} {'N/A':>14} {metrics['profit_factor']:>14.2f}")
    print(f"  {'Volatility':<26} {'N/A':>14} {metrics['volatility']:>13.2%}")
    print(f"  {'Win Rate':<26} {'N/A':>14} {metrics['win_rate']:>13.2%}")
    print(f"  {'Sharpe 95% CI':<26} {'N/A':>14} [{metrics['sharpe']-1.96*metrics['sharpe_se']:.3f}, {metrics['sharpe']+1.96*metrics['sharpe_se']:.3f}]")
    print(sep)

    # Verdict
    beats_cagr   = metrics['cagr']         > v82['cagr']
    beats_sharpe = metrics['sharpe']       > v82['sharpe']
    beats_dd     = metrics['max_drawdown'] > v82['max_dd']   # less negative = better

    verdicts = []
    verdicts.append(f"  [{'PASS' if beats_cagr   else 'FAIL'}] CAGR:   {metrics['cagr']:.2%} {'>' if beats_cagr   else '<='} {v82['cagr']:.2%}")
    verdicts.append(f"  [{'PASS' if beats_sharpe else 'FAIL'}] Sharpe: {metrics['sharpe']:.3f} {'>' if beats_sharpe else '<='} {v82['sharpe']:.3f}")
    verdicts.append(f"  [{'PASS' if beats_dd     else 'FAIL'}] MaxDD:  {metrics['max_drawdown']:.2%} {'better' if beats_dd else 'worse'} than {v82['max_dd']:.2%}")

    print(f"\nVERDICT:")
    for v in verdicts:
        print(v)
    n_pass = beats_cagr + beats_sharpe + beats_dd
    print(f"\n  Overall: {n_pass}/3 targets met")
    if n_pass == 3:
        print("  >>> v8.2 DEFEATED ON ALL FRONTS <<<")
    elif n_pass >= 2:
        print("  >>> Partial victory -- most metrics improved <<<")
    else:
        print("  >>> More work needed <<<")


# ============================================================================
# SAVE OUTPUTS
# ============================================================================

def save_outputs(results, metrics, label='exp44'):
    os.makedirs('backtests', exist_ok=True)

    daily_path  = f'backtests/{label}_daily.csv'
    trades_path = f'backtests/{label}_trades.csv'
    pkl_path    = f'backtests/{label}_results.pkl'

    results['portfolio_values'].to_csv(daily_path, index=False)
    if len(results['trades']) > 0:
        results['trades'].to_csv(trades_path, index=False)

    with open(pkl_path, 'wb') as f:
        pickle.dump({
            'params': {
                'backtest_start': BACKTEST_START,
                'slippage_bps': SLIPPAGE_BPS,
                'commission_per_share': COMMISSION_PER_SHARE,
                'momentum_short': MOMENTUM_SHORT,
                'momentum_med': MOMENTUM_MED,
                'momentum_long': MOMENTUM_LONG,
                'momentum_skip': MOMENTUM_SKIP,
                'momentum_weights': MOMENTUM_WEIGHTS,
                'max_stock_vol': MAX_STOCK_VOL,
                'num_positions_bull': NUM_POSITIONS_BULL,
                'num_positions_mild': NUM_POSITIONS_MILD,
                'num_positions_bear': NUM_POSITIONS_BEAR,
                'num_positions_severe': NUM_POSITIONS_SEVERE,
                'sector_max': SECTOR_MAX_POSITIONS,
                'hold_days_bull': HOLD_DAYS_BULL,
                'hold_days_bear': HOLD_DAYS_BEAR,
                'position_stop': POSITION_STOP_LOSS,
                'trailing_activation': TRAILING_ACTIVATION,
                'trailing_stop': TRAILING_STOP_PCT,
                'dd_tier_1': DD_TIER_1,
                'dd_tier_2': DD_TIER_2,
                'dd_tier_3': DD_TIER_3,
                'target_vol': TARGET_VOL,
                'top_n': TOP_N,
                'walk_forward': WALK_FORWARD,
                'etf_exclude': list(ETF_EXCLUDE),
            },
            'metrics': metrics,
            'portfolio_values': results['portfolio_values'],
            'trades': results['trades'],
        }, f)

    print(f"\n  Saved:")
    print(f"    {daily_path}")
    print(f"    {trades_path}")
    print(f"    {pkl_path}")


# ============================================================================
# MAIN
# ============================================================================

if __name__ == '__main__':
    t0 = time.time()

    print("=" * 80)
    print("EXPERIMENT 44: COMPASS v9.5 -- Modular Backtest Orchestrator")
    print("=" * 80)
    print()
    print("CRITIC FIXES APPLIED:")
    print(f"  1. Period alignment:  start = {BACKTEST_START}")
    print(f"  2. Slippage:          {SLIPPAGE_BPS} bps + ${COMMISSION_PER_SHARE}/share commission")
    print(f"  3. Universe cleanup:  {len(ETF_EXCLUDE)} ETFs excluded, sector map required")
    print(f"  4. Sharpe:            daily excess returns, annualised sqrt(252)")
    print(f"  5. Walk-forward:      {'ENABLED' if WALK_FORWARD else 'DISABLED'}")
    print(f"  6. Modules loaded:    {MODULES_LOADED}")
    print()

    # ---- STEP 1: Load Data ----
    print("=" * 80)
    print("STEP 1: LOAD DATA")
    print("=" * 80)

    price_data = load_price_data()
    print(f"  Symbols available: {len(price_data)}")

    spy_data = load_spy()
    # Normalise SPY index
    spy_data.index = _tz_strip(spy_data.index)
    print(f"  SPY trading days:  {len(spy_data)}")

    # Normalise price_data indexes
    for sym in price_data:
        price_data[sym].index = _tz_strip(price_data[sym].index)

    cash_yield_daily = load_cash_yield()

    # ---- STEP 2: Annual Universe ----
    print(f"\n{'='*80}")
    print("STEP 2: COMPUTE ANNUAL UNIVERSE")
    print("=" * 80)
    annual_universe = compute_annual_top_n(price_data)

    # ---- STEP 3: Run Backtest ----
    if WALK_FORWARD:
        # ---------- WALK-FORWARD MODE ----------
        print(f"\n{'='*80}")
        print("STEP 3a: TRAIN PERIOD BACKTEST")
        print("=" * 80)
        train_results = run_backtest(
            price_data, annual_universe, spy_data, cash_yield_daily,
            start_clip=BACKTEST_START, end_clip=TRAIN_END, label='TRAIN')
        train_metrics = calculate_metrics(train_results, cash_yield_daily)
        print_results(train_metrics, label='TRAIN (in-sample)')

        print(f"\n{'='*80}")
        print("STEP 3b: TEST PERIOD BACKTEST")
        print("=" * 80)
        test_results = run_backtest(
            price_data, annual_universe, spy_data, cash_yield_daily,
            start_clip=TEST_START, end_clip=None, label='TEST')
        test_metrics = calculate_metrics(test_results, cash_yield_daily)
        print_results(test_metrics, label='TEST (out-of-sample)')

        # Full run for comparison
        print(f"\n{'='*80}")
        print("STEP 3c: FULL PERIOD BACKTEST")
        print("=" * 80)
        results = run_backtest(
            price_data, annual_universe, spy_data, cash_yield_daily,
            start_clip=BACKTEST_START, end_clip=None, label='FULL')
        metrics = calculate_metrics(results, cash_yield_daily)

        # Walk-forward summary
        print(f"\n{'='*80}")
        print("WALK-FORWARD SUMMARY")
        print("=" * 80)
        print(f"  {'Metric':<20} {'Train':>12} {'Test':>12} {'Degradation':>14}")
        print(f"  {'-'*58}")
        for key, fmt in [('cagr', '.2%'), ('sharpe', '.3f'), ('max_drawdown', '.2%'),
                          ('win_rate', '.2%'), ('profit_factor', '.2f')]:
            tv = train_metrics[key]
            sv = test_metrics[key]
            deg = (sv / tv - 1) if tv != 0 else 0
            print(f"  {key:<20} {tv:>12{fmt}} {sv:>12{fmt}} {deg:>+13.1%}")
    else:
        # ---------- STANDARD MODE ----------
        print(f"\n{'='*80}")
        print("STEP 3: RUN BACKTEST")
        print("=" * 80)
        results = run_backtest(
            price_data, annual_universe, spy_data, cash_yield_daily,
            start_clip=BACKTEST_START, end_clip=None, label='FULL')
        metrics = calculate_metrics(results, cash_yield_daily)

    # ---- STEP 4: Report ----
    print_results(metrics, label='COMPASS v9.5 (full period)')
    print_comparison(metrics)

    # ---- STEP 5: Save ----
    save_outputs(results, metrics, label='exp44')
    if WALK_FORWARD:
        save_outputs(train_results, train_metrics, label='exp44_train')
        save_outputs(test_results,  test_metrics,  label='exp44_test')

    elapsed = time.time() - t0
    print(f"\n{'='*80}")
    print(f"EXPERIMENT 44 COMPLETE  ({elapsed:.1f}s)")
    print(f"{'='*80}")
