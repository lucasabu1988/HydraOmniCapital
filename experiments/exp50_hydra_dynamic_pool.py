#!/usr/bin/env python3
"""
EXP 50 — HYDRA Full Integrated Backtest (Point-in-Time S&P 500)
================================================================

HYDRA architecture (single capital pool, NOT split 50/50):
  1. COMPASS v8.4 runs first — uses all available capital for 5 momentum positions
  2. Rattlesnake runs on IDLE CASH left over after COMPASS entries
  3. EFA buys with remaining idle cash (regime filter: EFA > SMA200)
  4. Cash Recycling: HydraCapitalManager tracks logical accounts

Daily cycle (mirrors omnicapital_live.py):
  1. COMPASS exits (adaptive stops, trailing, hold expired, regime reduce)
  2. Rattlesnake exits (profit target +4%, stop -5%, time 8d)
  3. Liquidate EFA if COMPASS needs capital for new entries
  4. COMPASS entries (momentum rotation)
  5. Rattlesnake entries (RSI<25 dip-buying on oversold stocks)
  6. EFA purchase with remaining idle cash

Universe (survivorship-bias-free):
  - Point-in-time S&P 500 from fja05680/sp500 repo
  - Each year: all S&P 500 members with avg dollar volume > $10M/day -> top 40 by momentum
  - No intermediate 113-stock pool — liquidity floor replaces arbitrary cutoff
  - Rattlesnake: all liquid S&P 500 members (same liquidity floor)
"""

import pandas as pd
import numpy as np
import yfinance as yf
import os
import sys
import json
import pickle
import time
import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict

warnings.filterwarnings('ignore')

SEED = 666
np.random.seed(SEED)

# ============================================================================
# CONSTANTS
# ============================================================================

START_DATE = '1999-01-01'
END_DATE = '2027-01-01'
BACKTEST_START_YEAR = 2001

CONSTITUENTS_FILE = 'data_cache/sp500_snapshots.csv'
SECTOR_CACHE_FILE = 'data_cache/sp500_sector_map.json'
PRICE_CACHE_PKL = 'data_cache/exp50_universe_prices.pkl'

MIN_DOLLAR_VOLUME = 10_000_000  # $10M avg daily dollar volume floor
TOP_N = 40
INITIAL_CAPITAL = 100_000

# --- COMPASS v8.4 parameters ---
MOMENTUM_LOOKBACK = 90
MOMENTUM_SKIP = 5
MIN_MOMENTUM_STOCKS = 20
MIN_AGE_DAYS = 63
NUM_POSITIONS = 5
NUM_POSITIONS_RISK_OFF = 2
HOLD_DAYS = 5
HOLD_DAYS_MAX = 10
RENEWAL_PROFIT_MIN = 0.04
MOMENTUM_RENEWAL_THRESHOLD = 0.85
POSITION_STOP_LOSS = -0.08
STOP_FLOOR = -0.06
STOP_CEILING = -0.15
STOP_DAILY_VOL_MULT = 3.5
TRAILING_ACTIVATION = 0.05
TRAILING_STOP_PCT = 0.03
TRAILING_VOL_BASELINE = 0.25
PORTFOLIO_STOP_LOSS = -0.15
DD_SCALE_TIER1 = -0.10
DD_SCALE_TIER2 = -0.20
DD_SCALE_TIER3 = -0.35
LEV_FULL = 1.0
LEV_MID = 0.50
LEV_FLOOR = 0.15
TARGET_VOL = 0.15
VOL_LOOKBACK = 20
LEVERAGE_MAX = 1.0
MARGIN_RATE = 0.06
COMMISSION_PER_SHARE = 0.005
CASH_YIELD_RATE = 0.035
BULL_OVERRIDE_THRESHOLD = 0.03
BULL_OVERRIDE_MIN_SCORE = 0.40
MAX_PER_SECTOR = 3
QUALITY_VOL_MAX = 0.80
CRASH_VEL_5D = -0.06
CRASH_VEL_10D = -0.10
CRASH_LEVERAGE = 0.15
CRASH_COOLDOWN = 10

# --- Rattlesnake parameters ---
R_DROP_THRESHOLD = -0.08
R_DROP_LOOKBACK = 5
R_RSI_PERIOD = 5
R_RSI_THRESHOLD = 25
R_TREND_SMA = 200
R_PROFIT_TARGET = 0.04
R_MAX_HOLD = 8
R_STOP_LOSS = -0.05
R_MAX_POS = 5
R_POS_SIZE = 0.20
R_MAX_POS_RISK_OFF = 2
R_VIX_PANIC = 35
R_COMMISSION_BPS = 5

# --- EFA parameters ---
EFA_TICKER = 'EFA'
EFA_SMA_PERIOD = 200
EFA_MIN_BUY = 1000

# Ticker renames
TICKER_RENAMES = {'FB': 'META', 'GOOG': 'GOOGL', 'BRK.B': 'BRK-B', 'BF.B': 'BF-B'}

# Sector map (will be loaded from cache or v84)
SECTOR_MAP = {}

YFINANCE_SECTOR_MAP = {
    'Technology': 'Technology', 'Information Technology': 'Technology',
    'Communication Services': 'Telecom', 'Telecommunications': 'Telecom',
    'Financial Services': 'Financials', 'Financials': 'Financials',
    'Healthcare': 'Healthcare', 'Health Care': 'Healthcare',
    'Consumer Cyclical': 'Consumer', 'Consumer Defensive': 'Consumer',
    'Consumer Discretionary': 'Consumer', 'Consumer Staples': 'Consumer',
    'Energy': 'Energy', 'Industrials': 'Industrials',
    'Utilities': 'Utilities', 'Real Estate': 'Utilities',
    'Basic Materials': 'Industrials', 'Materials': 'Industrials',
}

print("=" * 80)
print("EXP 50b — HYDRA Integrated Backtest (S&P 500, no 113-pool, liquidity floor)")
print("COMPASS v8.4 + Rattlesnake + EFA + Cash Recycling (single capital pool)")
print("=" * 80)


# ============================================================================
# DATA LOADING (reuse from previous exp50 run)
# ============================================================================

def load_constituents():
    print(f"\n[Constituents] Loading from {CONSTITUENTS_FILE}...")
    if not os.path.exists(CONSTITUENTS_FILE):
        print(f"  ERROR: {CONSTITUENTS_FILE} not found!")
        sys.exit(1)
    df = pd.read_csv(CONSTITUENTS_FILE)
    constituents = {}
    for _, row in df.iterrows():
        date_str = str(row['date'])
        tickers = set()
        for t in str(row['tickers']).split(','):
            t = t.strip()
            if not t:
                continue
            t = TICKER_RENAMES.get(t, t)
            if '.' in t and t not in ('BRK-B', 'BF-B'):
                continue
            tickers.add(t)
        constituents[date_str] = tickers
    dates_sorted = sorted(constituents.keys())
    print(f"  {len(dates_sorted)} snapshots | {len(set().union(*constituents.values()))} unique tickers")
    return constituents


def get_constituents_for_date(constituents, date):
    if isinstance(date, (pd.Timestamp, datetime)):
        date_str = date.strftime('%Y-%m-%d')
    else:
        date_str = str(date)
    best = None
    for d in sorted(constituents.keys()):
        if d <= date_str:
            best = d
        else:
            break
    return constituents.get(best, set()) if best else set()


def download_universe():
    # Note: pickle used for consistency with existing caching pattern
    if os.path.exists(PRICE_CACHE_PKL):
        print(f"\n[Cache] Loading from {PRICE_CACHE_PKL}...")
        try:
            with open(PRICE_CACHE_PKL, 'rb') as f:
                data = pickle.load(f)
            print(f"  {len(data)} symbols loaded")
            return data
        except Exception as e:
            print(f"  Failed: {e}")
    print("  ERROR: No cached data. Run exp50 first to download.")
    sys.exit(1)


def download_vix():
    cache_file = 'data_cache/VIX_exp50.csv'
    if os.path.exists(cache_file):
        df = pd.read_csv(cache_file, index_col=0, parse_dates=True)
        return df['Close']
    print("\n[Download] Downloading ^VIX...")
    df = yf.download('^VIX', start=START_DATE, end=END_DATE, progress=False)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    os.makedirs('data_cache', exist_ok=True)
    df.to_csv(cache_file)
    return df['Close']


def load_sector_map(price_data):
    global SECTOR_MAP
    if os.path.exists(SECTOR_CACHE_FILE):
        with open(SECTOR_CACHE_FILE, 'r') as f:
            SECTOR_MAP = json.load(f)
        print(f"\n[Sectors] Loaded {len(SECTOR_MAP)} entries")
    return SECTOR_MAP


# ============================================================================
# ANNUAL UNIVERSE (S&P 500 -> liquidity floor -> top 40)
# ============================================================================

def compute_annual_universe(price_data, constituents):
    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    years = [y for y in sorted(set(d.year for d in all_dates)) if y >= BACKTEST_START_YEAR]

    annual_liquid_pool = {}
    annual_universe_40 = {}
    annual_rattle_pool = {}

    print(f"\n--- Dynamic Universe (Point-in-Time, liquidity floor ${MIN_DOLLAR_VOLUME/1e6:.0f}M/day) ---")
    tz = all_dates[0].tz if hasattr(all_dates[0], 'tz') and all_dates[0].tz else None

    for year in years:
        sp500_members = get_constituents_for_date(constituents, f'{year}-01-01')
        available = [t for t in sp500_members if t in price_data]
        ranking_end = pd.Timestamp(f'{year}-01-01', tz=tz)
        ranking_start = pd.Timestamp(f'{year-1}-01-01', tz=tz)

        scores = {}
        for symbol in available:
            df = price_data[symbol]
            window = df.loc[(df.index >= ranking_start) & (df.index < ranking_end)]
            if len(window) < 20:
                continue
            avg_dv = (window['Close'] * window['Volume']).mean()
            if avg_dv >= MIN_DOLLAR_VOLUME:
                scores[symbol] = avg_dv

        # All liquid stocks become the pool — no arbitrary size cutoff
        liquid_pool = sorted(scores.keys())
        ranked_by_volume = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        annual_liquid_pool[year] = liquid_pool
        # Top 40 by dollar volume for COMPASS (momentum will re-rank daily)
        annual_universe_40[year] = [s for s, _ in ranked_by_volume[:TOP_N]]
        # Rattlesnake gets the full liquid pool
        annual_rattle_pool[year] = liquid_pool

        turnover = ""
        if year > years[0] and year - 1 in annual_universe_40:
            prev = set(annual_universe_40[year - 1])
            curr = set(annual_universe_40[year])
            added = len(curr - prev)
            turnover = f"+{added} -{added}"
        else:
            turnover = "Initial"
        print(f"  {year}: SP500={len(sp500_members)} liquid={len(liquid_pool)} Top40 | {turnover}")

    return annual_liquid_pool, annual_universe_40, annual_rattle_pool


# ============================================================================
# SIGNAL FUNCTIONS (v8.4 — from backtest_quarterly_audit.py)
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
    sig_200 = _sigmoid((current / sma200) - 1.0, 15.0)
    sig_cross = _sigmoid((sma50 / sma200) - 1.0, 30.0) if sma200 > 0 else 0.5
    sig_mom = 0.5
    if len(spy_close) >= 21:
        p20 = float(spy_close.iloc[-21])
        if p20 > 0:
            sig_mom = _sigmoid((current / p20) - 1.0, 15.0)
    trend_score = (sig_200 + sig_cross + sig_mom) / 3.0
    vol_score = 0.5
    returns = spy_close.pct_change().dropna()
    if len(returns) >= 262:
        cv = float(returns.iloc[-10:].std() * np.sqrt(252))
        rv = returns.iloc[-252:].rolling(10).std() * np.sqrt(252)
        rv = rv.dropna()
        if len(rv) >= 20 and cv > 0:
            vol_score = 1.0 - float((rv <= cv).sum()) / len(rv)
    return float(np.clip(0.60 * trend_score + 0.40 * vol_score, 0.0, 1.0))


def get_spy_trend_data(spy_data, date):
    date_n = pd.Timestamp(date)
    if hasattr(date_n, 'tz') and date_n.tz is not None:
        date_n = date_n.tz_localize(None)
    spy = spy_data
    spy_idx = spy.index
    if hasattr(spy_idx, 'tz') and spy_idx.tz is not None:
        date_n = date_n.tz_localize(spy_idx.tz)
    if date_n not in spy.index:
        return None
    idx = spy.index.get_loc(date_n)
    if idx < 200:
        return None
    return (float(spy['Close'].iloc[idx]), float(spy['Close'].iloc[idx-199:idx+1].mean()))


def regime_score_to_positions(regime_score, spy_close=None, sma200=None):
    if regime_score >= 0.65:
        base = NUM_POSITIONS
    elif regime_score >= 0.50:
        base = max(NUM_POSITIONS - 1, NUM_POSITIONS_RISK_OFF + 1)
    elif regime_score >= 0.35:
        base = max(NUM_POSITIONS - 2, NUM_POSITIONS_RISK_OFF + 1)
    else:
        base = NUM_POSITIONS_RISK_OFF
    if (spy_close and sma200 and sma200 > 0 and regime_score > BULL_OVERRIDE_MIN_SCORE):
        if (spy_close / sma200) - 1.0 >= BULL_OVERRIDE_THRESHOLD:
            base = min(base + 1, NUM_POSITIONS)
    return base


def compute_momentum_scores(price_data, tradeable, date):
    scores = {}
    for symbol in tradeable:
        if symbol not in price_data:
            continue
        df = price_data[symbol]
        if date not in df.index:
            continue
        sym_idx = df.index.get_loc(date)
        needed = MOMENTUM_LOOKBACK + MOMENTUM_SKIP
        if sym_idx < needed:
            continue
        c_today = df['Close'].iloc[sym_idx]
        c_skip = df['Close'].iloc[sym_idx - MOMENTUM_SKIP]
        c_look = df['Close'].iloc[sym_idx - MOMENTUM_LOOKBACK]
        if c_look <= 0 or c_skip <= 0 or c_today <= 0:
            continue
        raw = (c_skip / c_look) - 1.0 - ((c_today / c_skip) - 1.0)
        vol_w = min(63, sym_idx - 1)
        if vol_w >= 20:
            rets = df['Close'].iloc[sym_idx - vol_w:sym_idx + 1].pct_change().dropna()
            if len(rets) >= 15:
                av = float(rets.std() * (252 ** 0.5))
                scores[symbol] = raw / av if av > 0.01 else raw
            else:
                scores[symbol] = raw
        else:
            scores[symbol] = raw
    return scores


def compute_volatility_weights(price_data, selected, date):
    vols = {}
    for symbol in selected:
        if symbol not in price_data or date not in price_data[symbol].index:
            continue
        df = price_data[symbol]
        idx = df.index.get_loc(date)
        if idx < VOL_LOOKBACK + 1:
            continue
        rets = df['Close'].iloc[idx - VOL_LOOKBACK:idx + 1].pct_change().dropna()
        if len(rets) < VOL_LOOKBACK - 2:
            continue
        v = rets.std() * np.sqrt(252)
        if v > 0.01:
            vols[symbol] = v
    if not vols:
        return {s: 1.0 / len(selected) for s in selected}
    raw = {s: 1.0 / v for s, v in vols.items()}
    total = sum(raw.values())
    return {s: w / total for s, w in raw.items()}


def compute_entry_vol(price_data, symbol, date, lookback=20):
    D_ANN, D_DAILY = 0.25, 0.25 / np.sqrt(252)
    if symbol not in price_data or date not in price_data[symbol].index:
        return (D_ANN, D_DAILY)
    df = price_data[symbol]
    idx = df.index.get_loc(date)
    if idx < lookback + 1:
        return (D_ANN, D_DAILY)
    rets = df['Close'].iloc[idx - lookback:idx + 1].pct_change().dropna()
    if len(rets) < lookback - 2:
        return (D_ANN, D_DAILY)
    dv = float(rets.std())
    return (max(dv * np.sqrt(252), 0.05), max(dv, 0.003))


def compute_adaptive_stop(entry_daily_vol):
    raw = -STOP_DAILY_VOL_MULT * entry_daily_vol
    return max(STOP_CEILING, min(STOP_FLOOR, raw))


def compute_dynamic_leverage(spy_data, date):
    if date not in spy_data.index:
        return 1.0
    idx = spy_data.index.get_loc(date)
    if idx < VOL_LOOKBACK + 1:
        return 1.0
    rets = spy_data['Close'].iloc[idx - VOL_LOOKBACK:idx + 1].pct_change().dropna()
    if len(rets) < VOL_LOOKBACK - 2:
        return 1.0
    rv = rets.std() * np.sqrt(252)
    if rv < 0.01:
        return LEVERAGE_MAX
    return max(LEV_FLOOR, min(LEVERAGE_MAX, TARGET_VOL / rv))


def _dd_leverage(drawdown):
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


def compute_smooth_leverage(drawdown, portfolio_values, current_idx, crash_cooldown):
    def _val(e):
        return float(e.get('value', 0.0)) if isinstance(e, dict) else float(e)
    in_crash = False
    updated = crash_cooldown
    if crash_cooldown > 0:
        in_crash = True
        updated = crash_cooldown - 1
    elif current_idx >= 5 and len(portfolio_values) > current_idx:
        cv = _val(portfolio_values[current_idx])
        v5 = _val(portfolio_values[current_idx - 5])
        if v5 > 0 and (cv / v5) - 1.0 <= CRASH_VEL_5D:
            in_crash = True
        if not in_crash and current_idx >= 10:
            v10 = _val(portfolio_values[current_idx - 10])
            if v10 > 0 and (cv / v10) - 1.0 <= CRASH_VEL_10D:
                in_crash = True
        if in_crash:
            updated = CRASH_COOLDOWN - 1
    if in_crash:
        return (min(CRASH_LEVERAGE, _dd_leverage(drawdown)), updated)
    return (_dd_leverage(drawdown), updated)


def get_tradeable_symbols(price_data, date, first_date, universe):
    tradeable = []
    for symbol in universe:
        if symbol not in price_data or date not in price_data[symbol].index:
            continue
        days = (date - price_data[symbol].index[0]).days
        if date <= first_date + timedelta(days=30) or days >= MIN_AGE_DAYS:
            tradeable.append(symbol)
    return tradeable


def should_renew_position(symbol, pos, price, total_days, scores):
    if total_days >= HOLD_DAYS_MAX:
        return False
    ep = pos.get('entry_price', price)
    if ep <= 0 or (price - ep) / ep < RENEWAL_PROFIT_MIN:
        return False
    if not scores or symbol not in scores:
        return False
    vals = sorted(scores.values(), reverse=True)
    if len(vals) < 3:
        return False
    rank = sum(1 for s in vals if s > scores[symbol])
    return (1.0 - rank / len(vals)) >= MOMENTUM_RENEWAL_THRESHOLD


def compute_quality_filter(price_data, tradeable, date):
    passed = []
    for symbol in tradeable:
        if symbol not in price_data or date not in price_data[symbol].index:
            continue
        df = price_data[symbol]
        idx = df.index.get_loc(date)
        if idx < 62:
            passed.append(symbol)
            continue
        rets = df['Close'].iloc[idx - 59:idx + 1].pct_change().dropna()
        if len(rets) < 20:
            passed.append(symbol)
            continue
        if rets.std() * np.sqrt(252) <= QUALITY_VOL_MAX:
            passed.append(symbol)
    return passed if len(passed) >= 5 else tradeable


def filter_by_sector_concentration(ranked, positions, max_per=MAX_PER_SECTOR):
    sc = defaultdict(int)
    for s, p in positions.items():
        sc[p.get('sector', SECTOR_MAP.get(s, 'Unknown'))] += 1
    selected = []
    for sym, score in ranked:
        sector = SECTOR_MAP.get(sym, 'Unknown')
        if sc[sector] < max_per:
            selected.append(sym)
            sc[sector] += 1
    return selected


# ============================================================================
# RATTLESNAKE SIGNAL FUNCTIONS
# ============================================================================

def compute_rsi(prices_series, period=5):
    delta = prices_series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_g = gain.rolling(window=period, min_periods=period).mean()
    avg_l = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_g / avg_l
    rsi = 100 - (100 / (1 + rs))
    return rsi


def find_rattlesnake_candidates(price_data, rattle_pool, date, held_symbols, vix_val):
    if vix_val is not None and vix_val > R_VIX_PANIC:
        return []

    candidates = []
    for ticker in rattle_pool:
        if ticker in held_symbols or ticker not in price_data:
            continue
        df = price_data[ticker]
        if date not in df.index:
            continue
        idx = df.index.get_loc(date)
        if idx < R_TREND_SMA + 10:
            continue

        current_price = float(df['Close'].iloc[idx])
        if current_price <= 0 or idx < R_DROP_LOOKBACK:
            continue

        past_price = float(df['Close'].iloc[idx - R_DROP_LOOKBACK])
        if past_price <= 0:
            continue
        drop = (current_price / past_price) - 1.0
        if drop > R_DROP_THRESHOLD:
            continue

        # RSI
        rsi_series = compute_rsi(df['Close'].iloc[:idx + 1], R_RSI_PERIOD)
        rsi_val = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else 50.0
        if rsi_val > R_RSI_THRESHOLD:
            continue

        # Trend filter
        sma = float(df['Close'].iloc[idx - R_TREND_SMA + 1:idx + 1].mean())
        if current_price < sma:
            continue

        # Volume filter
        if 'Volume' in df.columns and idx >= 20:
            avg_vol = df['Volume'].iloc[idx - 20:idx].mean()
            if pd.isna(avg_vol) or avg_vol < 500_000:
                continue

        candidates.append({'symbol': ticker, 'score': -drop, 'price': current_price,
                          'drop': drop, 'rsi': rsi_val})

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates


# ============================================================================
# INTEGRATED HYDRA BACKTEST
# ============================================================================

def run_hydra_backtest(price_data, annual_universe_40, annual_rattle_pool,
                       spy_data, cash_yield_daily, vix_series, efa_data):

    print(f"\n{'=' * 80}")
    print("RUNNING HYDRA INTEGRATED BACKTEST (single capital pool)")
    print(f"{'=' * 80}")

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    all_dates = sorted(list(all_dates))
    first_date = all_dates[0]

    print(f"Period: {all_dates[0].strftime('%Y-%m-%d')} to {all_dates[-1].strftime('%Y-%m-%d')}")
    print(f"Trading days: {len(all_dates)}")

    # State
    cash = float(INITIAL_CAPITAL)
    compass_positions = {}    # {symbol: {entry_price, shares, entry_idx, ...}}
    rattle_positions = []     # [{symbol, entry_price, entry_idx, shares}]
    efa_shares = 0
    efa_avg_cost = 0.0

    portfolio_values = []
    compass_trades = []
    rattle_trades = []

    peak_value = float(INITIAL_CAPITAL)
    crash_cooldown = 0
    risk_on_days = 0
    risk_off_days = 0
    current_year = None
    current_universe = []

    # Rattlesnake regime
    r_regime = 'RISK_ON'

    for i, date in enumerate(all_dates):
        # --- Year change ---
        if date.year != current_year:
            current_year = date.year
            current_universe = list(annual_universe_40.get(current_year, []))

        rattle_pool = annual_rattle_pool.get(current_year, [])

        # --- Portfolio value ---
        portfolio_value = cash
        for sym, pos in compass_positions.items():
            if sym in price_data and date in price_data[sym].index:
                portfolio_value += pos['shares'] * float(price_data[sym].loc[date, 'Close'])
        for pos in rattle_positions:
            sym = pos['symbol']
            if sym in price_data and date in price_data[sym].index:
                portfolio_value += pos['shares'] * float(price_data[sym].loc[date, 'Close'])
        if efa_shares > 0 and efa_data is not None and date in efa_data.index:
            portfolio_value += efa_shares * float(efa_data.loc[date, 'Close'])

        if portfolio_value > peak_value:
            peak_value = portfolio_value
        drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0

        # --- Regime ---
        regime_score = compute_regime_score(spy_data, date)
        is_risk_on = regime_score >= 0.50
        if is_risk_on:
            risk_on_days += 1
        else:
            risk_off_days += 1

        dd_lev, crash_cooldown = compute_smooth_leverage(
            drawdown, portfolio_values, max(i - 1, 0), crash_cooldown)
        vol_lev = compute_dynamic_leverage(spy_data, date)
        current_leverage = max(min(dd_lev, vol_lev), LEV_FLOOR)

        spy_trend = get_spy_trend_data(spy_data, date)
        if spy_trend:
            max_pos = regime_score_to_positions(regime_score, spy_close=spy_trend[0], sma200=spy_trend[1])
        else:
            max_pos = regime_score_to_positions(regime_score)

        # --- Daily costs ---
        if current_leverage > 1.0:
            borrowed = portfolio_value * (current_leverage - 1) / current_leverage
            cash -= MARGIN_RATE / 252 * borrowed
        if cash > 0:
            if cash_yield_daily is not None and date in cash_yield_daily.index:
                daily_rate = cash_yield_daily.loc[date] / 100 / 252
            else:
                daily_rate = CASH_YIELD_RATE / 252
            cash += cash * daily_rate

        # --- VIX ---
        vix_val = None
        if vix_series is not None and date in vix_series.index:
            vix_val = float(vix_series.loc[date])

        # === STEP 1: COMPASS EXITS ===
        tradeable = get_tradeable_symbols(price_data, date, first_date, current_universe)
        quality = compute_quality_filter(price_data, tradeable, date)
        scores = compute_momentum_scores(price_data, quality, date)

        for symbol in list(compass_positions.keys()):
            pos = compass_positions[symbol]
            if symbol not in price_data or date not in price_data[symbol].index:
                continue
            price = float(price_data[symbol].loc[date, 'Close'])
            exit_reason = None

            days_held = i - pos['entry_idx']
            total_days = i - pos['original_entry_idx']
            if days_held >= HOLD_DAYS:
                if should_renew_position(symbol, pos, price, total_days, scores):
                    pos['entry_idx'] = i
                else:
                    exit_reason = 'hold_expired'

            pos_return = (price - pos['entry_price']) / pos['entry_price']
            astop = compute_adaptive_stop(pos.get('entry_daily_vol', 0.016))
            if pos_return <= astop:
                exit_reason = 'position_stop'

            if price > pos['high_price']:
                pos['high_price'] = price
            if pos['high_price'] > pos['entry_price'] * (1 + TRAILING_ACTIVATION):
                vr = pos.get('entry_vol', TRAILING_VOL_BASELINE) / TRAILING_VOL_BASELINE
                tl = pos['high_price'] * (1 - TRAILING_STOP_PCT * vr)
                if price <= tl:
                    exit_reason = 'trailing_stop'

            if symbol not in tradeable:
                exit_reason = 'universe_rotation'

            if exit_reason is None and len(compass_positions) > max_pos:
                prs = {}
                for s, p in compass_positions.items():
                    if s in price_data and date in price_data[s].index:
                        prs[s] = (float(price_data[s].loc[date, 'Close']) - p['entry_price']) / p['entry_price']
                if prs and symbol == min(prs, key=prs.get):
                    exit_reason = 'regime_reduce'

            if exit_reason:
                shares = pos['shares']
                proceeds = shares * price
                commission = shares * COMMISSION_PER_SHARE
                cash += proceeds - commission
                pnl = (price - pos['entry_price']) * shares - commission
                compass_trades.append({
                    'symbol': symbol, 'entry_date': pos['entry_date'],
                    'exit_date': date, 'exit_reason': exit_reason,
                    'pnl': pnl, 'return': pnl / (pos['entry_price'] * shares)
                })
                del compass_positions[symbol]

        # === STEP 2: RATTLESNAKE EXITS ===
        for pos in list(rattle_positions):
            sym = pos['symbol']
            if sym not in price_data or date not in price_data[sym].index:
                continue
            price = float(price_data[sym].loc[date, 'Close'])
            pnl_pct = (price / pos['entry_price']) - 1.0
            hold_days = i - pos['entry_idx']

            exit_reason = None
            if pnl_pct >= R_PROFIT_TARGET:
                exit_reason = 'R_PROFIT'
            elif pnl_pct <= R_STOP_LOSS:
                exit_reason = 'R_STOP'
            elif hold_days >= R_MAX_HOLD:
                exit_reason = 'R_TIME'

            if exit_reason:
                proceeds = pos['shares'] * price
                comm = proceeds * R_COMMISSION_BPS / 10000
                cash += proceeds - comm
                rattle_trades.append({
                    'date': date, 'symbol': sym, 'reason': exit_reason,
                    'pnl_pct': pnl_pct, 'hold_days': hold_days
                })
                rattle_positions.remove(pos)

        # === STEP 3: LIQUIDATE EFA IF COMPASS NEEDS CAPITAL ===
        needed_compass = max_pos - len(compass_positions)
        if needed_compass > 0 and efa_shares > 0 and efa_data is not None and date in efa_data.index:
            avg_pos_cost = portfolio_value * 0.20
            if cash < avg_pos_cost:
                efa_price = float(efa_data.loc[date, 'Close'])
                efa_proceeds = efa_shares * efa_price
                cash += efa_proceeds
                efa_shares = 0
                efa_avg_cost = 0.0

        # === STEP 4: COMPASS ENTRIES ===
        needed = max_pos - len(compass_positions)
        if needed > 0 and cash > 1000 and len(scores) >= MIN_MOMENTUM_STOCKS:
            all_held = set(compass_positions.keys()) | {p['symbol'] for p in rattle_positions}
            available = {s: sc for s, sc in scores.items() if s not in all_held}
            if len(available) >= needed:
                ranked = sorted(available.items(), key=lambda x: x[1], reverse=True)
                sector_filtered = filter_by_sector_concentration(ranked, compass_positions)
                selected = sector_filtered[:needed]
                weights = compute_volatility_weights(price_data, selected, date)
                effective_capital = cash * current_leverage * 0.95

                for symbol in selected:
                    if symbol not in price_data or date not in price_data[symbol].index:
                        continue
                    entry_price = float(price_data[symbol].loc[date, 'Close'])
                    if entry_price <= 0:
                        continue
                    weight = weights.get(symbol, 1.0 / len(selected))
                    pos_value = min(effective_capital * weight, cash * 0.40)
                    shares = pos_value / entry_price
                    cost = shares * entry_price
                    commission = shares * COMMISSION_PER_SHARE
                    if cost + commission <= cash * 0.90:
                        ev, edv = compute_entry_vol(price_data, symbol, date)
                        compass_positions[symbol] = {
                            'entry_price': entry_price, 'shares': shares,
                            'entry_date': date, 'entry_idx': i,
                            'original_entry_idx': i, 'high_price': entry_price,
                            'entry_vol': ev, 'entry_daily_vol': edv,
                            'sector': SECTOR_MAP.get(symbol, 'Unknown'),
                        }
                        cash -= cost + commission

        # === STEP 5: RATTLESNAKE ENTRIES (on idle cash) ===
        # Rattlesnake regime
        if spy_trend:
            spy_c, spy_sma = spy_trend
            r_regime = 'RISK_ON' if spy_c > spy_sma else 'RISK_OFF'

        r_max = R_MAX_POS if r_regime == 'RISK_ON' else R_MAX_POS_RISK_OFF
        r_slots = r_max - len(rattle_positions)

        if r_slots > 0 and i >= R_TREND_SMA + 50:
            all_held = set(compass_positions.keys()) | {p['symbol'] for p in rattle_positions}
            candidates = find_rattlesnake_candidates(price_data, rattle_pool, date, all_held, vix_val)

            for cand in candidates[:r_slots]:
                sym = cand['symbol']
                price = cand['price']
                # Rattlesnake uses idle cash * R_POS_SIZE
                target_val = cash * R_POS_SIZE
                shares = int(target_val / price)
                if shares < 1:
                    continue
                cost = shares * price
                comm = cost * R_COMMISSION_BPS / 10000
                if cost + comm <= cash * 0.50:  # Don't use more than 50% of remaining cash
                    cash -= cost + comm
                    rattle_positions.append({
                        'symbol': sym, 'entry_price': price,
                        'entry_idx': i, 'shares': shares
                    })
                    rattle_trades.append({
                        'date': date, 'symbol': sym, 'reason': 'R_ENTRY',
                        'pnl_pct': 0, 'hold_days': 0
                    })

        # === STEP 6: EFA WITH REMAINING IDLE CASH ===
        if efa_data is not None and date in efa_data.index and cash > EFA_MIN_BUY:
            efa_price = float(efa_data.loc[date, 'Close'])
            # Check EFA > SMA200
            if efa_price > 0:
                efa_idx = efa_data.index.get_loc(date)
                efa_above_sma = False
                if efa_idx >= EFA_SMA_PERIOD:
                    efa_sma = float(efa_data['Close'].iloc[efa_idx - EFA_SMA_PERIOD + 1:efa_idx + 1].mean())
                    efa_above_sma = efa_price > efa_sma

                if efa_above_sma and cash > EFA_MIN_BUY * 2:
                    # Use up to 30% of idle cash for EFA
                    efa_budget = cash * 0.30
                    new_shares = int(efa_budget / efa_price)
                    if new_shares >= 1:
                        cost = new_shares * efa_price
                        cash -= cost
                        if efa_shares > 0:
                            total_cost = efa_avg_cost * efa_shares + cost
                            efa_shares += new_shares
                            efa_avg_cost = total_cost / efa_shares
                        else:
                            efa_shares = new_shares
                            efa_avg_cost = efa_price

                # Sell EFA if below SMA200
                elif not efa_above_sma and efa_shares > 0:
                    cash += efa_shares * efa_price
                    efa_shares = 0
                    efa_avg_cost = 0.0

        # --- Record portfolio value ---
        # Recompute after all trades
        pv = cash
        for sym, pos in compass_positions.items():
            if sym in price_data and date in price_data[sym].index:
                pv += pos['shares'] * float(price_data[sym].loc[date, 'Close'])
        for pos in rattle_positions:
            sym = pos['symbol']
            if sym in price_data and date in price_data[sym].index:
                pv += pos['shares'] * float(price_data[sym].loc[date, 'Close'])
        efa_val = 0
        if efa_shares > 0 and efa_data is not None and date in efa_data.index:
            efa_val = efa_shares * float(efa_data.loc[date, 'Close'])
            pv += efa_val

        portfolio_values.append({
            'date': date, 'value': pv, 'cash': cash,
            'compass_pos': len(compass_positions),
            'rattle_pos': len(rattle_positions),
            'efa_value': efa_val,
            'drawdown': drawdown, 'leverage': current_leverage,
            'in_protection': dd_lev < LEV_FULL,
            'risk_on': is_risk_on,
        })

        if i % 252 == 0 and i > 0:
            year_num = i // 252
            regime_str = "RISK_ON" if is_risk_on else "RISK_OFF"
            prot = f" [DD {dd_lev:.0%}]" if dd_lev < LEV_FULL else ""
            print(f"  Year {year_num}: ${pv:,.0f} | DD: {drawdown:.1%} | Lev: {current_leverage:.2f}x | "
                  f"{regime_str}{prot} | C:{len(compass_positions)} R:{len(rattle_positions)} "
                  f"EFA:${efa_val:,.0f}")

    # Close remaining positions
    last_date = all_dates[-1]
    for sym, pos in list(compass_positions.items()):
        if sym in price_data and last_date in price_data[sym].index:
            price = float(price_data[sym].loc[last_date, 'Close'])
            cash += pos['shares'] * price
    for pos in list(rattle_positions):
        sym = pos['symbol']
        if sym in price_data and last_date in price_data[sym].index:
            cash += pos['shares'] * float(price_data[sym].loc[last_date, 'Close'])
    if efa_shares > 0 and efa_data is not None and last_date in efa_data.index:
        cash += efa_shares * float(efa_data.loc[last_date, 'Close'])

    return {
        'portfolio_values': pd.DataFrame(portfolio_values),
        'compass_trades': pd.DataFrame(compass_trades) if compass_trades else pd.DataFrame(),
        'rattle_trades': rattle_trades,
        'risk_on_days': risk_on_days,
        'risk_off_days': risk_off_days,
    }


# ============================================================================
# METRICS
# ============================================================================

def calculate_metrics(results):
    df = results['portfolio_values'].set_index('date')
    initial = INITIAL_CAPITAL
    final = df['value'].iloc[-1]
    years = len(df) / 252
    cagr = (final / initial) ** (1 / years) - 1
    rets = df['value'].pct_change().dropna()
    vol = rets.std() * np.sqrt(252)
    max_dd = df['drawdown'].min()
    sharpe = cagr / vol if vol > 0 else 0
    ds = rets[rets < 0]
    ds_vol = ds.std() * np.sqrt(252) if len(ds) > 0 else vol
    sortino = cagr / ds_vol if ds_vol > 0 else 0
    calmar = cagr / abs(max_dd) if max_dd != 0 else 0

    ct = results['compass_trades']
    win_rate = (ct['pnl'] > 0).mean() if len(ct) > 0 else 0
    protection = df['in_protection'].sum()
    prot_pct = protection / len(df) * 100

    return {
        'initial': initial, 'final': final, 'cagr': cagr,
        'volatility': vol, 'sharpe': sharpe, 'sortino': sortino,
        'calmar': calmar, 'max_drawdown': max_dd,
        'compass_trades': len(ct), 'win_rate': win_rate,
        'protection_days': protection, 'protection_pct': prot_pct,
    }


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    t_start = time.time()

    constituents = load_constituents()
    price_data = download_universe()
    vix_series = download_vix()

    efa_data = price_data.get(EFA_TICKER)
    if efa_data is not None:
        print(f"\n  EFA: {len(efa_data)} trading days")

    load_sector_map(price_data)

    spy_data = price_data.get('SPY')
    if spy_data is None:
        print("ERROR: SPY not in price data!")
        sys.exit(1)
    print(f"  SPY: {len(spy_data)} trading days")

    # Cash yield
    _stdout = sys.stdout
    sys.stdout = open(os.devnull, 'w')
    try:
        import omnicapital_v84_compass as v84
        cash_yield_daily = v84.download_cash_yield()
    finally:
        sys.stdout = _stdout
    print(f"  Cash yield loaded")

    # Universe
    liquid_pool, universe_40, rattle_pool = compute_annual_universe(price_data, constituents)

    # Run HYDRA
    results = run_hydra_backtest(
        price_data, universe_40, rattle_pool,
        spy_data, cash_yield_daily, vix_series, efa_data
    )

    metrics = calculate_metrics(results)

    # Results
    print(f"\n{'=' * 80}")
    print("EXP 50b — HYDRA INTEGRATED (no 113-pool, $10M liquidity floor)")
    print(f"{'=' * 80}")
    print(f"\n  Initial:        ${metrics['initial']:>12,.0f}")
    print(f"  Final:          ${metrics['final']:>12,.0f}")
    print(f"  CAGR:           {metrics['cagr']:>12.2%}")
    print(f"  Volatility:     {metrics['volatility']:>12.2%}")
    print(f"  Sharpe:         {metrics['sharpe']:>12.2f}")
    print(f"  Sortino:        {metrics['sortino']:>12.2f}")
    print(f"  Max Drawdown:   {metrics['max_drawdown']:>12.2%}")
    print(f"  COMPASS trades: {metrics['compass_trades']:>12,}")
    print(f"  Win rate:       {metrics['win_rate']:>12.1%}")
    print(f"  Protection:     {metrics['protection_days']:>12,} days ({metrics['protection_pct']:.1f}%)")

    # Rattlesnake stats
    r_trades = results['rattle_trades']
    r_sells = [t for t in r_trades if t['reason'] != 'R_ENTRY']
    if r_sells:
        r_wins = sum(1 for t in r_sells if t['pnl_pct'] > 0)
        print(f"\n  --- Rattlesnake ---")
        print(f"  Trades:     {len(r_sells)}")
        print(f"  Win rate:   {r_wins/len(r_sells):.1%}")
        print(f"  Profit: {sum(1 for t in r_sells if t['reason']=='R_PROFIT')} | "
              f"Stop: {sum(1 for t in r_sells if t['reason']=='R_STOP')} | "
              f"Time: {sum(1 for t in r_sells if t['reason']=='R_TIME')}")

    # EFA stats
    pv_df = results['portfolio_values']
    efa_days = (pv_df['efa_value'] > 0).sum()
    max_efa = pv_df['efa_value'].max()
    print(f"\n  --- EFA ---")
    print(f"  Days held:  {efa_days} ({efa_days/len(pv_df)*100:.1f}%)")
    print(f"  Max value:  ${max_efa:,.0f}")

    # Comparison
    print(f"\n{'=' * 80}")
    print("COMPARISON WITH BASELINES")
    print(f"{'=' * 80}")
    baselines = [
        ('COMPASS v8.4 (static pool)', 0.1222, 0.73, -0.3199),
        ('COMPASS v8.2 corrected', 0.1337, 0.64, -0.442),
    ]
    print(f"\n  {'Metric':<30} {'HYDRA':>10} {'v8.4 base':>10} {'v8.2 corr':>10}")
    print(f"  {'-'*62}")
    print(f"  {'CAGR':<30} {metrics['cagr']:>9.2%} {baselines[0][1]:>9.2%} {baselines[1][1]:>9.2%}")
    print(f"  {'Sharpe':<30} {metrics['sharpe']:>10.2f} {baselines[0][2]:>10.2f} {baselines[1][2]:>10.2f}")
    print(f"  {'Max DD':<30} {metrics['max_drawdown']:>9.1%} {baselines[0][3]:>9.1%} {baselines[1][3]:>9.1%}")

    delta = metrics['cagr'] - baselines[1][1]
    print(f"\n  HYDRA vs v8.2 corrected: {delta:+.2%} CAGR")

    # Save
    os.makedirs('backtests', exist_ok=True)
    pv_df.to_csv('backtests/exp50_hydra_daily.csv', index=False)
    print(f"\n  Saved: backtests/exp50_hydra_daily.csv")

    elapsed = time.time() - t_start
    print(f"\n  Completed in {elapsed/60:.1f} minutes")

    # Verdict
    print(f"\n{'=' * 80}")
    if metrics['cagr'] > baselines[1][1] and metrics['sharpe'] > baselines[1][2]:
        print("VERDICT: HYDRA BEATS corrected baseline!")
    elif metrics['cagr'] > baselines[1][1]:
        print("VERDICT: HYDRA beats CAGR but not Sharpe")
    else:
        print(f"VERDICT: HYDRA ({metrics['cagr']:.2%}) vs corrected ({baselines[1][1]:.2%}) — "
              f"{'FAILED' if metrics['cagr'] < baselines[1][1] else 'MATCHED'}")
    print("=" * 80)
