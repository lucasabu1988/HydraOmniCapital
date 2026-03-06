"""
COMPASS v8.4 — Cloud Dashboard (Showcase)
==========================================
Full-featured Flask dashboard for Render.com deployment.
Shows live prices, backtest equity curves, trade analytics,
execution microstructure, social feed, and research paper.
NO live trading engine — showcase/portfolio mode.

Deploy: git push to GitHub → auto-deploy on Render.
"""

from flask import Flask, jsonify, render_template
import json
import os
import glob
import numpy as np
import pandas as pd
import logging
import time as time_module
from datetime import datetime, date, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional
import threading

# Optional imports (graceful if missing)
try:
    import yfinance as yf
    logging.getLogger('yfinance').setLevel(logging.CRITICAL)
    _HAS_YFINANCE = True
except ImportError:
    _HAS_YFINANCE = False

try:
    import requests as http_requests
    import xml.etree.ElementTree as XmlET
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False

# anthropic SDK removed — terminal replaced with WhatsApp contact

app = Flask(__name__)
logger = logging.getLogger(__name__)


@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

# ============================================================================
# COMPASS v8.4 PARAMETERS (read-only reference — ALGORITHM LOCKED)
# ============================================================================

COMPASS_CONFIG = {
    'HOLD_DAYS': 5,
    'NUM_POSITIONS': 5,
    'NUM_POSITIONS_RISK_OFF': 2,
    'TARGET_VOL': 0.15,
    'LEVERAGE_MAX': 1.0,       # No leverage in production
    'INITIAL_CAPITAL': 100_000,
    'COMMISSION_PER_SHARE': 0.001,
    'ORDER_TIMEOUT_SECONDS': 300,
    'MAX_FILL_DEVIATION': 0.02,
    'MAX_PRICE_CHANGE_PCT': 0.20,
    # --- v8.4 Adaptive Stops (volatility-scaled) ---
    'STOP_DAILY_VOL_MULT': 2.5,
    'STOP_FLOOR': -0.06,
    'STOP_CEILING': -0.15,
    'TRAILING_ACTIVATION': 0.05,
    'TRAILING_STOP_PCT': 0.03,
    'TRAILING_VOL_BASELINE': 0.25,
    # --- v8.4 Bull Market Override ---
    'BULL_OVERRIDE_THRESHOLD': 0.03,
    'BULL_OVERRIDE_MIN_SCORE': 0.40,
    # --- v8.4 Sector Concentration ---
    'MAX_PER_SECTOR': 3,
    # --- Smooth DD Scaling ---
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
    # --- Exit Renewal ---
    'HOLD_DAYS_MAX': 10,
    'RENEWAL_PROFIT_MIN': 0.04,
    'MOMENTUM_RENEWAL_THRESHOLD': 0.85,
    # --- Quality Filter ---
    'QUALITY_VOL_MAX': 0.60,
    'QUALITY_VOL_LOOKBACK': 63,
    'QUALITY_MAX_SINGLE_DAY': 0.50,
}

STATE_FILE = 'state/compass_state_latest.json'
STATE_DIR = 'state'
SPY_BENCHMARK_CSV = os.path.join('backtests', 'spy_benchmark.csv')

# Rattlesnake parameters (mirrored from rattlesnake_signals.py for dashboard)
R_VIX_PANIC = 35
R_BASE_COMPASS_ALLOC = 0.50
R_BASE_RATTLE_ALLOC = 0.50
R_MAX_COMPASS_ALLOC = 0.75

PRICE_CACHE_SECONDS = 30
SOCIAL_CACHE_SECONDS = 300  # 5 minutes

# Live test started Mar 6, 2026 — ^GSPC prev close on that date
LIVE_TEST_START_DATE = '2026-03-06'
LIVE_TEST_SPY_START = 6830.71  # ^GSPC prev close on 2026-03-06
LIVE_TEST_PORTFOLIO_START = 100_000  # initial capital at start
_spy_start_price = None

SHOWCASE_MODE = os.environ.get('COMPASS_MODE', 'showcase') == 'showcase'

# ============================================================================
# DATA PRELOAD (at import time — shared across gunicorn workers via --preload)
# ============================================================================

_equity_df = None
_spy_df = None


def _preload_data():
    """Load CSV data at startup (not on first request)."""
    global _equity_df, _spy_df
    # HYDRA multi-strategy data (COMPASS + Rattlesnake with cash recycling)
    csv_path = os.path.join('backtests', 'exp60_hydra_efa_filtered.csv')
    if os.path.exists(csv_path):
        try:
            _equity_df = pd.read_csv(csv_path, parse_dates=['date'])
        except Exception:
            pass
    spy_path = SPY_BENCHMARK_CSV
    if os.path.exists(spy_path):
        try:
            _spy_df = pd.read_csv(spy_path, parse_dates=['date'])
        except Exception:
            pass


_preload_data()

# ============================================================================
# PRICE CACHE (all live prices from Yahoo Finance v8 API)
# ============================================================================

_price_cache: Dict[str, float] = {}
_prev_close_cache: Dict[str, float] = {}
_price_cache_time: Optional[datetime] = None
_price_cache_lock = threading.Lock()

_YF_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
}


def _yf_fetch_quote(symbol: str) -> Optional[dict]:
    """Fetch a single symbol from Yahoo Finance v8 chart API.
    Returns {'price': float, 'prev_close': float} or None."""
    try:
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
        params = {'range': '1d', 'interval': '1d'}
        r = http_requests.get(url, params=params, headers=_YF_HEADERS, timeout=10)
        if r.status_code != 200:
            logger.warning(f'Yahoo Finance {symbol} returned {r.status_code}')
            return None
        data = r.json()
        result_data = data.get('chart', {}).get('result', [])
        if not result_data:
            return None
        meta = result_data[0].get('meta', {})
        price = meta.get('regularMarketPrice')
        prev_close = meta.get('chartPreviousClose') or meta.get('previousClose')
        if price and price > 0:
            out = {'price': float(price)}
            if prev_close and prev_close > 0:
                out['prev_close'] = float(prev_close)
            return out
    except Exception as e:
        logger.warning(f'Yahoo Finance {symbol} fetch failed: {e}')
    return None


def _fetch_yahoo_prices(symbols: List[str]) -> Dict[str, dict]:
    """Fetch live prices from Yahoo Finance v8 API.
    Returns {symbol: {'price': float, 'prev_close': float}}."""
    if not _HAS_REQUESTS:
        return {}
    results = {}
    for sym in symbols:
        quote = _yf_fetch_quote(sym)
        if quote:
            results[sym] = quote
    return results


def fetch_live_prices(symbols: List[str]) -> Dict[str, float]:
    """Fetch all live prices from Yahoo Finance.
    Returns {symbol: price_float}. Previous closes in _prev_close_cache."""
    global _price_cache, _prev_close_cache, _price_cache_time

    if not symbols:
        return {}

    with _price_cache_lock:
        now = datetime.now()
        if _price_cache_time and (now - _price_cache_time).total_seconds() < PRICE_CACHE_SECONDS:
            missing = [s for s in symbols if s not in _price_cache]
            if not missing:
                return {s: _price_cache[s] for s in symbols if s in _price_cache}
        else:
            missing = symbols
            _price_cache = {}
            _prev_close_cache = {}

    if missing:
        yf_results = _fetch_yahoo_prices(missing)
        for sym, result in yf_results.items():
            _price_cache[sym] = result['price']
            if 'prev_close' in result:
                _prev_close_cache[sym] = result['prev_close']

    with _price_cache_lock:
        _price_cache_time = now
    return {s: _price_cache[s] for s in symbols if s in _price_cache}


# ============================================================================
# STATE READER
# ============================================================================

def read_state() -> Optional[dict]:
    """Read latest state from JSON file (bundled with deploy)."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return None


# ============================================================================
# DERIVED CALCULATIONS
# ============================================================================

def compute_position_details(state: dict, prices: Dict[str, float] = None) -> List[dict]:
    """Compute enriched position data for display."""
    positions = state.get('positions', {})
    position_meta = state.get('position_meta', {})
    trading_day = state.get('trading_day_counter', 0)
    prices = prices or {}

    results = []
    for symbol, pos_data in positions.items():
        meta = position_meta.get(symbol, {})
        entry_price = meta.get('entry_price', pos_data.get('avg_cost', 0))
        high_price = meta.get('high_price', entry_price)
        entry_day_index = meta.get('entry_day_index', 0)
        entry_date = meta.get('entry_date', '')
        shares = pos_data.get('shares', 0)
        current_price = prices.get(symbol, entry_price)

        # If position was opened today, use entry_price to avoid phantom PnL
        # from after-hours last_price vs MOC fill price mismatch
        if entry_date:
            try:
                today_et = datetime.now(ZoneInfo('America/New_York')).date()
                if date.fromisoformat(entry_date) == today_et:
                    current_price = entry_price
            except Exception:
                pass

        if current_price and entry_price and entry_price > 0:
            pnl_pct = (current_price - entry_price) / entry_price
            pnl_dollar = (current_price - entry_price) * shares
            market_value = current_price * shares
        else:
            pnl_pct = 0
            pnl_dollar = 0
            market_value = entry_price * shares if entry_price else 0
            current_price = current_price or entry_price or 0

        # Compute days held from actual entry_date (not stale trading_day_counter)
        # Must match production logic: days_held = trading_day - entry_day_index
        # On entry day: days_held = 0, next trading day: days_held = 1, etc.
        # Exit when days_held >= HOLD_DAYS (5)
        if entry_date:
            try:
                entry_dt = date.fromisoformat(entry_date)
                today = date.today()
                # Count weekdays AFTER entry date (exclusive of entry day)
                total_days = (today - entry_dt).days
                days_held = sum(1 for d in range(1, total_days + 1)
                                if (entry_dt + timedelta(days=d)).weekday() < 5)
            except Exception:
                days_held = trading_day - entry_day_index
        else:
            days_held = trading_day - entry_day_index
        days_remaining = max(0, COMPASS_CONFIG['HOLD_DAYS'] - days_held)

        # v8.4: Adaptive trailing stop (vol-scaled)
        trailing_active = high_price > entry_price * (1 + COMPASS_CONFIG['TRAILING_ACTIVATION'])
        if trailing_active:
            entry_vol = meta.get('entry_vol', COMPASS_CONFIG.get('TRAILING_VOL_BASELINE', 0.25))
            vol_ratio = entry_vol / COMPASS_CONFIG.get('TRAILING_VOL_BASELINE', 0.25)
            scaled_trailing = COMPASS_CONFIG['TRAILING_STOP_PCT'] * vol_ratio
            trailing_stop_level = high_price * (1 - scaled_trailing)
        else:
            trailing_stop_level = None

        # v8.4: Adaptive position stop (vol-scaled)
        entry_daily_vol = meta.get('entry_daily_vol')
        if entry_daily_vol is not None:
            raw_stop = -COMPASS_CONFIG['STOP_DAILY_VOL_MULT'] * entry_daily_vol
            adaptive_stop = max(COMPASS_CONFIG['STOP_CEILING'], min(COMPASS_CONFIG['STOP_FLOOR'], raw_stop))
        else:
            adaptive_stop = COMPASS_CONFIG['STOP_FLOOR']  # fallback to floor
        position_stop_level = entry_price * (1 + adaptive_stop)

        sector = meta.get('sector', 'Unknown')

        near_stop = False
        if current_price:
            if trailing_stop_level and current_price < trailing_stop_level * 1.01:
                near_stop = True
            if current_price < position_stop_level * 1.01:
                near_stop = True

        results.append({
            'symbol': symbol,
            'shares': round(shares, 1),
            'entry_price': round(entry_price, 2),
            'current_price': round(current_price, 2),
            'market_value': round(market_value, 0),
            'pnl_dollar': round(pnl_dollar, 0),
            'pnl_pct': round(pnl_pct * 100, 2),
            'days_held': days_held,
            'days_remaining': days_remaining,
            'high_price': round(high_price, 2),
            'trailing_active': trailing_active,
            'trailing_stop_level': round(trailing_stop_level, 2) if trailing_stop_level else None,
            'position_stop_level': round(position_stop_level, 2),
            'adaptive_stop_pct': round(adaptive_stop * 100, 2),
            'entry_date': entry_date,
            'near_stop': near_stop,
            'sector': sector,
        })

    results.sort(key=lambda x: x['pnl_pct'], reverse=True)
    return results


def get_spy_start_price() -> Optional[float]:
    """Get S&P 500 index close price on live test start date (cached)."""
    global _spy_start_price
    if _spy_start_price is not None:
        return _spy_start_price

    # Use hardcoded value (verified ^GSPC close on live test start date)
    _spy_start_price = LIVE_TEST_SPY_START
    return _spy_start_price


def _compute_real_trading_day(state: dict) -> int:
    """Compute real trading day from last_trading_date (state counter may be stale)."""
    saved_day = state.get('trading_day_counter', 0)
    last_date_str = state.get('last_trading_date')
    if not last_date_str:
        return saved_day
    try:
        last_dt = date.fromisoformat(last_date_str)
        today = date.today()
        if today <= last_dt:
            return saved_day
        extra = sum(1 for d in range(1, (today - last_dt).days + 1)
                    if (last_dt + timedelta(days=d)).weekday() < 5)
        return saved_day + extra
    except Exception:
        return saved_day


def compute_portfolio_metrics(state: dict, prices: Dict[str, float] = None) -> dict:
    """Compute portfolio-level dashboard metrics."""
    portfolio_value = state.get('portfolio_value', 0)
    peak_value = state.get('peak_value', 0)
    cash = state.get('cash', 0)
    initial_capital = COMPASS_CONFIG['INITIAL_CAPITAL']
    prices = prices or {}

    # Recompute invested value with live prices if available
    invested = 0
    positions = state.get('positions', {})
    position_meta = state.get('position_meta', {})
    today_et = datetime.now(ZoneInfo('America/New_York')).date()
    for sym, pos in positions.items():
        meta = position_meta.get(sym, {})
        entry_date = meta.get('entry_date', '')
        entry_price = meta.get('entry_price', pos.get('avg_cost', 0))
        # Use entry_price on entry day to avoid phantom PnL from after-hours prices
        if entry_date:
            try:
                if date.fromisoformat(entry_date) == today_et:
                    price = entry_price
                else:
                    price = prices.get(sym, entry_price)
            except Exception:
                price = prices.get(sym, entry_price)
        else:
            price = prices.get(sym, pos.get('avg_cost', 0))
        invested += pos.get('shares', 0) * price

    # If we have live prices, update portfolio_value
    if prices and invested > 0:
        portfolio_value = cash + invested
        if portfolio_value > peak_value:
            peak_value = portfolio_value

    drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0
    total_return = (portfolio_value - initial_capital) / initial_capital if initial_capital > 0 else 0

    # v8.4: Smooth DD scaling info (no binary stop/recovery)
    recovery = None
    dd_leverage = state.get('dd_leverage', 1.0)
    crash_cooldown = state.get('crash_cooldown', 0)
    if dd_leverage < COMPASS_CONFIG['LEV_FULL'] or crash_cooldown > 0:
        recovery = {
            'dd_leverage': round(dd_leverage, 3),
            'crash_cooldown': crash_cooldown,
            'regime_score': round(state.get('current_regime_score', 1.0 if state.get('current_regime', True) else 0.0), 3),
        }

    # v8.4: Continuous regime score
    regime_score = state.get('current_regime_score', 1.0 if state.get('current_regime', True) else 0.0)
    regime_str = 'RISK_ON' if regime_score >= 0.65 else 'RISK_OFF'

    # v8.4: DD leverage (smooth scaling)
    dd_leverage = state.get('dd_leverage', 1.0)
    leverage = dd_leverage if dd_leverage < COMPASS_CONFIG['LEV_FULL'] else None

    # v8.4: Positions from regime score (thresholds match local dashboard)
    if regime_score >= 0.65:
        max_pos = COMPASS_CONFIG['NUM_POSITIONS']
    elif regime_score >= 0.50:
        max_pos = COMPASS_CONFIG['NUM_POSITIONS'] - 1
    elif regime_score >= 0.35:
        max_pos = COMPASS_CONFIG['NUM_POSITIONS'] - 2
    else:
        max_pos = COMPASS_CONFIG['NUM_POSITIONS_RISK_OFF']

    # S&P 500 daily return (today's change from previous close)
    spy_current = prices.get('^GSPC') if prices else None
    spy_prev = _prev_close_cache.get('^GSPC')
    if spy_current and spy_prev and spy_prev > 0:
        spy_daily = round((spy_current - spy_prev) / spy_prev * 100, 2)
    else:
        spy_daily = None

    # S&P 500 cumulative return (since live test start)
    spy_start = get_spy_start_price()
    if spy_current and spy_start and spy_start > 0:
        spy_cumulative = round((spy_current - spy_start) / spy_start * 100, 2)
    else:
        spy_cumulative = None

    # HYDRA daily return (current portfolio vs yesterday's close value)
    # history[-1] is today's open snapshot, [-2] is yesterday's close
    pv_hist = state.get('portfolio_values_history', [])
    if len(pv_hist) >= 2 and portfolio_value > 0:
        yesterday_value = pv_hist[-2]
        daily_return = round((portfolio_value - yesterday_value) / yesterday_value * 100, 2)
    else:
        daily_return = None

    # HYDRA cumulative return (since live test start)
    cumulative_return = round(total_return * 100, 2)

    trading_days_elapsed = _compute_real_trading_day(state)

    return {
        'portfolio_value': round(portfolio_value, 2),
        'cash': round(cash, 2),
        'invested': round(invested, 2),
        'peak_value': round(peak_value, 2),
        'drawdown': round(drawdown * 100, 2),
        'total_return': cumulative_return,
        'spy_return': spy_daily,
        'spy_cumulative': spy_cumulative,
        'daily_return': daily_return,
        'initial_capital': initial_capital,
        'num_positions': len(positions),
        'max_positions': max_pos,
        'regime': regime_str,
        'regime_consecutive': state.get('regime_consecutive', 0),
        'in_protection': dd_leverage < COMPASS_CONFIG['LEV_FULL'],
        'regime_score': round(regime_score, 3),
        'leverage': leverage,
        'recovery': recovery,
        'trading_day': trading_days_elapsed,
        'last_trading_date': state.get('last_trading_date'),
        'stop_events': state.get('stop_events', []),
        'timestamp': state.get('timestamp', ''),
        'uptime_minutes': state.get('stats', {}).get('uptime_minutes', 0),
    }


# ============================================================================
# HYDRA: Rattlesnake regime + capital allocation (live computation)
# ============================================================================

def compute_hydra_data(state: dict, prices: Dict[str, float]) -> dict:
    """Compute HYDRA multi-strategy data for the dashboard.

    Fetches VIX live, determines Rattlesnake regime (SPY vs SMA200),
    reads any Rattlesnake positions from state, and computes capital
    allocation with cash recycling.
    """
    if not _HAS_YFINANCE:
        return {'available': False}

    # --- VIX (reuse from price cache if available) ---
    vix_current = prices.get('^VIX')
    if not vix_current:
        try:
            vix_hist = yf.Ticker('^VIX').history(period='5d')
            if len(vix_hist) > 0:
                vix_current = float(vix_hist['Close'].iloc[-1])
        except Exception:
            pass

    # --- Rattlesnake regime: SPY vs SMA(200) ---
    rattle_regime = 'RISK_ON'
    try:
        spy_hist = yf.Ticker('SPY').history(period='1y')
        if len(spy_hist) >= 200:
            spy_close = float(spy_hist['Close'].iloc[-1])
            spy_sma200 = float(spy_hist['Close'].iloc[-200:].mean())
            if spy_close < spy_sma200:
                rattle_regime = 'RISK_OFF'
    except Exception:
        pass

    vix_panic = vix_current > R_VIX_PANIC if vix_current else False

    # --- Rattlesnake positions from state (if live engine writes them) ---
    hydra_state = state.get('hydra', {})
    rattle_positions_raw = hydra_state.get('rattle_positions', [])

    # Enrich with live prices + P&L
    rattle_positions = []
    for rp in rattle_positions_raw:
        symbol = rp.get('symbol', '')
        entry_price = rp.get('entry_price', 0)
        current_price = prices.get(symbol, entry_price)
        pnl_pct = (current_price / entry_price - 1.0) if entry_price > 0 else 0
        rattle_positions.append({
            'symbol': symbol,
            'entry_price': round(entry_price, 2),
            'current_price': round(current_price, 2),
            'pnl_pct': round(pnl_pct, 4),
            'shares': rp.get('shares', 0),
            'days_held': rp.get('days_held', 0),
        })

    # --- Capital allocation (cash recycling) ---
    portfolio_value = state.get('portfolio_value', COMPASS_CONFIG['INITIAL_CAPITAL'])
    # If hydra capital manager state exists, use it
    cap_state = hydra_state.get('capital_manager')
    if cap_state:
        compass_account = cap_state.get('compass_account', portfolio_value * R_BASE_COMPASS_ALLOC)
        rattle_account = cap_state.get('rattle_account', portfolio_value * R_BASE_RATTLE_ALLOC)
    else:
        # No persisted HYDRA state — compute from current portfolio
        # Rattlesnake has 0 exposure when no positions → all idle cash recycles to COMPASS
        compass_account = portfolio_value * R_BASE_COMPASS_ALLOC
        rattle_account = portfolio_value * R_BASE_RATTLE_ALLOC

    total = compass_account + rattle_account
    if total <= 0:
        total = portfolio_value or COMPASS_CONFIG['INITIAL_CAPITAL']
        compass_account = total * R_BASE_COMPASS_ALLOC
        rattle_account = total * R_BASE_RATTLE_ALLOC

    # Cash recycling: idle Rattlesnake cash flows to COMPASS (capped at 75%)
    rattle_invested = sum(
        rp.get('shares', 0) * prices.get(rp.get('symbol', ''), rp.get('entry_price', 0))
        for rp in rattle_positions_raw
    )
    rattle_exposure = rattle_invested / rattle_account if rattle_account > 0 else 0
    r_idle = rattle_account * (1.0 - rattle_exposure)
    max_recycle = max(0, total * R_MAX_COMPASS_ALLOC - compass_account)
    recycled = min(r_idle, max_recycle)
    c_effective = compass_account + recycled
    r_effective = rattle_account - recycled

    return {
        'available': True,
        'rattle_positions': rattle_positions,
        'rattle_regime': rattle_regime,
        'vix_current': round(vix_current, 2) if vix_current else None,
        'vix_panic': vix_panic,
        'capital': {
            'compass_account': round(c_effective, 2),
            'rattle_account': round(r_effective, 2),
            'compass_pct': round(c_effective / total, 4) if total > 0 else 0.5,
            'rattle_pct': round(r_effective / total, 4) if total > 0 else 0.5,
            'recycled_pct': round(recycled / total, 4) if total > 0 else 0,
        },
    }


# ============================================================================
# SOCIAL FEED (6 sources: yfinance, Reddit, Seeking Alpha, SEC, Google, MW)
# ============================================================================

_social_cache: Dict[str, list] = {}
_social_cache_time: Optional[datetime] = None


def _fetch_yfinance_news(symbols: List[str], max_per: int = 3) -> List[dict]:
    """Fetch news from yfinance for holdings."""
    if not _HAS_YFINANCE:
        return []
    items = []
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            raw_news = ticker.news or []
            for item in raw_news[:max_per]:
                content = item.get('content', {})
                title = content.get('title', '')
                if not title:
                    continue
                pub_date = content.get('pubDate', '')
                provider = content.get('provider', {}).get('displayName', '')
                summary = content.get('summary', '')
                url = ''
                canon = content.get('canonicalUrl', {})
                if canon and canon.get('url'):
                    url = canon['url']
                click = content.get('clickThroughUrl', {})
                if not url and click and click.get('url'):
                    url = click['url']
                if len(summary) > 150:
                    summary = summary[:150].rsplit(' ', 1)[0] + '...'
                items.append({
                    'symbol': symbol,
                    'body': title,
                    'detail': summary,
                    'user': provider or 'Yahoo Finance',
                    'time': pub_date,
                    'url': url,
                    'source': 'news',
                    'sentiment': None,
                })
        except Exception:
            pass
    return items


def _fetch_reddit_posts(symbols: List[str], max_per: int = 2) -> List[dict]:
    """Fetch recent Reddit posts mentioning stock tickers."""
    if not _HAS_REQUESTS:
        return []
    items = []
    headers = {'User-Agent': 'COMPASS-Dashboard/1.0'}
    for symbol in symbols:
        try:
            r = http_requests.get(
                'https://www.reddit.com/search.json',
                params={'q': f'{symbol} stock', 'sort': 'new', 'limit': max_per, 't': 'week'},
                headers=headers,
                timeout=8
            )
            if r.status_code != 200:
                continue
            posts = r.json().get('data', {}).get('children', [])
            for p in posts:
                d = p.get('data', {})
                title = d.get('title', '')
                if not title:
                    continue
                score = d.get('score', 0)
                ratio = d.get('upvote_ratio', 0.5)
                sentiment = 'bullish' if (score > 10 and ratio > 0.7) else 'bearish' if ratio < 0.4 else None
                created = d.get('created_utc', 0)
                pub_iso = datetime.utcfromtimestamp(created).isoformat() + 'Z' if created else ''
                sub = d.get('subreddit', '')
                permalink = d.get('permalink', '')
                if len(title) > 150:
                    title = title[:150].rsplit(' ', 1)[0] + '...'
                items.append({
                    'symbol': symbol,
                    'body': title,
                    'detail': f'r/{sub} \u2022 {score} pts',
                    'user': f'r/{sub}',
                    'time': pub_iso,
                    'url': f'https://reddit.com{permalink}' if permalink else '',
                    'source': 'reddit',
                    'sentiment': sentiment,
                })
        except Exception:
            pass
    return items


def _fetch_seekingalpha_news(symbols: List[str], max_per: int = 2) -> List[dict]:
    """Fetch analysis from Seeking Alpha RSS for holdings."""
    if not _HAS_REQUESTS:
        return []
    items = []
    headers = {'User-Agent': 'COMPASS-Dashboard/1.0'}
    for symbol in symbols:
        try:
            rss_url = f'https://seekingalpha.com/api/sa/combined/{symbol}.xml'
            r = http_requests.get(rss_url, headers=headers, timeout=8)
            if r.status_code != 200:
                continue
            root = XmlET.fromstring(r.content)
            count = 0
            for item_el in root.iter('item'):
                if count >= max_per:
                    break
                title = item_el.findtext('title', '').strip()
                if not title:
                    continue
                link = item_el.findtext('link', '').strip()
                pub_date_raw = item_el.findtext('pubDate', '').strip()
                author = ''
                for child in item_el:
                    if 'author_name' in child.tag or 'creator' in child.tag:
                        author = (child.text or '').strip()
                        break
                pub_iso = ''
                if pub_date_raw:
                    try:
                        from email.utils import parsedate_to_datetime
                        dt = parsedate_to_datetime(pub_date_raw)
                        pub_iso = dt.isoformat()
                    except Exception:
                        pub_iso = pub_date_raw
                if len(title) > 150:
                    title = title[:150].rsplit(' ', 1)[0] + '...'
                items.append({
                    'symbol': symbol,
                    'body': title,
                    'detail': author or '',
                    'user': author or 'Seeking Alpha',
                    'time': pub_iso,
                    'url': link,
                    'source': 'seekingalpha',
                    'sentiment': None,
                })
                count += 1
        except Exception:
            pass
    return items


def _fetch_sec_filings(symbols: List[str], max_per: int = 2) -> List[dict]:
    """Fetch recent SEC EDGAR filings via EFTS full-text search."""
    if not _HAS_REQUESTS:
        return []
    items = []
    headers = {'User-Agent': os.environ.get('SEC_USER_AGENT', 'COMPASS-Dashboard contact@omnicapital.com')}
    start_date = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    end_date = datetime.now().strftime('%Y-%m-%d')
    for symbol in symbols:
        try:
            r = http_requests.get(
                'https://efts.sec.gov/LATEST/search-index',
                params={
                    'q': f'"{symbol}"',
                    'forms': '10-K,10-Q,8-K,4',
                    'dateRange': 'custom',
                    'startdt': start_date,
                    'enddt': end_date,
                },
                headers=headers,
                timeout=8
            )
            if r.status_code != 200:
                continue
            data = r.json()
            hits = data.get('hits', {}).get('hits', [])
            count = 0
            for hit in hits:
                if count >= max_per:
                    break
                src = hit.get('_source', {})
                form_type = src.get('forms', src.get('form_type', ''))
                if isinstance(form_type, list):
                    form_type = form_type[0] if form_type else ''
                file_date = src.get('file_date', '')
                display_names = src.get('display_names', [])
                entity_name = display_names[0] if display_names else symbol
                title = f'{entity_name} \u2014 {form_type} filing'
                link = f'https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={symbol}&type={form_type}&dateb=&owner=include&count=5'
                pub_iso = ''
                if file_date:
                    try:
                        pub_iso = datetime.strptime(file_date, '%Y-%m-%d').isoformat()
                    except Exception:
                        pub_iso = file_date
                if len(title) > 150:
                    title = title[:150].rsplit(' ', 1)[0] + '...'
                items.append({
                    'symbol': symbol,
                    'body': title,
                    'detail': form_type or 'SEC Filing',
                    'user': 'SEC EDGAR',
                    'time': pub_iso,
                    'url': link,
                    'source': 'sec',
                    'sentiment': None,
                })
                count += 1
        except Exception:
            pass
    return items


def _fetch_google_news(symbols: List[str], max_per: int = 2) -> List[dict]:
    """Fetch stock news from Google News RSS."""
    if not _HAS_REQUESTS:
        return []
    items = []
    headers = {'User-Agent': 'COMPASS-Dashboard/1.0'}
    for symbol in symbols:
        try:
            query = f'{symbol}+stock+market'
            rss_url = f'https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en'
            r = http_requests.get(rss_url, headers=headers, timeout=8)
            if r.status_code != 200:
                continue
            root = XmlET.fromstring(r.content)
            count = 0
            for item_el in root.iter('item'):
                if count >= max_per:
                    break
                title = item_el.findtext('title', '').strip()
                if not title:
                    continue
                link = item_el.findtext('link', '').strip()
                pub_date_raw = item_el.findtext('pubDate', '').strip()
                source_name = item_el.findtext('source', '').strip()
                pub_iso = ''
                if pub_date_raw:
                    try:
                        from email.utils import parsedate_to_datetime
                        dt = parsedate_to_datetime(pub_date_raw)
                        pub_iso = dt.isoformat()
                    except Exception:
                        pub_iso = pub_date_raw
                if ' - ' in title and source_name:
                    title = title.rsplit(' - ', 1)[0].strip()
                if len(title) > 150:
                    title = title[:150].rsplit(' ', 1)[0] + '...'
                items.append({
                    'symbol': symbol,
                    'body': title,
                    'detail': source_name or '',
                    'user': source_name or 'Google News',
                    'time': pub_iso,
                    'url': link,
                    'source': 'google',
                    'sentiment': None,
                })
                count += 1
        except Exception:
            pass
    return items


def _fetch_marketwatch_news(max_items: int = 5) -> List[dict]:
    """Fetch top market headlines from MarketWatch RSS."""
    if not _HAS_REQUESTS:
        return []
    items = []
    headers = {'User-Agent': 'COMPASS-Dashboard/1.0'}
    try:
        rss_url = 'https://feeds.marketwatch.com/marketwatch/topstories/'
        r = http_requests.get(rss_url, headers=headers, timeout=8)
        if r.status_code != 200:
            return items
        root = XmlET.fromstring(r.content)
        count = 0
        for item_el in root.iter('item'):
            if count >= max_items:
                break
            title = item_el.findtext('title', '').strip()
            if not title:
                continue
            link = item_el.findtext('link', '').strip()
            pub_date_raw = item_el.findtext('pubDate', '').strip()
            pub_iso = ''
            if pub_date_raw:
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(pub_date_raw)
                    pub_iso = dt.isoformat()
                except Exception:
                    pub_iso = pub_date_raw
            if len(title) > 150:
                title = title[:150].rsplit(' ', 1)[0] + '...'
            items.append({
                'symbol': 'MKT',
                'body': title,
                'detail': '',
                'user': 'MarketWatch',
                'time': pub_iso,
                'url': link,
                'source': 'marketwatch',
                'sentiment': None,
            })
            count += 1
    except Exception:
        pass
    return items


def fetch_social_feed(symbols: List[str]) -> List[dict]:
    """Fetch combined social feed for holdings (6 sources)."""
    global _social_cache, _social_cache_time

    now = datetime.now()
    cache_key = ','.join(sorted(symbols))
    if _social_cache_time and (now - _social_cache_time).total_seconds() < SOCIAL_CACHE_SECONDS:
        cached = _social_cache.get(cache_key)
        if cached is not None:
            return cached

    news_items = _fetch_yfinance_news(symbols, max_per=3)
    reddit_items = _fetch_reddit_posts(symbols, max_per=2)
    sa_items = _fetch_seekingalpha_news(symbols, max_per=2)
    sec_items = _fetch_sec_filings(symbols, max_per=2)
    google_items = _fetch_google_news(symbols, max_per=2)
    mw_items = _fetch_marketwatch_news(max_items=5)

    all_items = news_items + reddit_items + sa_items + sec_items + google_items + mw_items
    all_items.sort(key=lambda x: x.get('time', ''), reverse=True)
    result = all_items[:50]

    _social_cache[cache_key] = result
    _social_cache_time = now
    return result


# ============================================================================
# ANALYTICS CACHES (lazy-import, compute once, cache forever until restart)
# ============================================================================

_montecarlo_cache = None
_trade_analytics_cache = None


# ============================================================================
# FLASK ROUTES
# ============================================================================

@app.route('/')
def index():
    return render_template('dashboard.html')


@app.route('/api/state')
def api_state():
    """Return enriched state data with live prices."""
    state = read_state()

    if not state:
        return jsonify({
            'status': 'offline',
            'error': 'No state file found',
            'server_time': datetime.now().isoformat(),
            'engine': {
                'running': False,
                'started_at': None,
                'error': 'Showcase mode \u2014 view only',
                'cycles': 0,
            },
        })

    # Fetch live prices for positions + SPY + ES Futures + VIX + Rattlesnake held
    rattle_syms = [p.get('symbol') for p in state.get('hydra', {}).get('rattle_positions', []) if p.get('symbol')]
    symbols = ['SPY', '^GSPC', 'ES=F', '^VIX'] + list(state.get('positions', {}).keys()) + rattle_syms
    symbols = list(set(symbols))
    prices = fetch_live_prices(symbols)

    position_details = compute_position_details(state, prices)
    portfolio = compute_portfolio_metrics(state, prices)

    # HYDRA: Rattlesnake + Cash Recycling data
    hydra_data = compute_hydra_data(state, prices)

    # Pre-close status (computed from real ET time)
    ET = ZoneInfo('America/New_York')
    now_et = datetime.now(ET)
    is_weekday = now_et.weekday() < 5
    current_time = now_et.time()
    if not is_weekday or current_time < dtime(9, 30) or current_time >= dtime(16, 0):
        preclose_phase = 'market_closed'
    elif current_time < dtime(15, 30):
        preclose_phase = 'waiting'
    elif current_time <= dtime(15, 50):
        preclose_phase = 'window_open'
    else:
        preclose_phase = 'entries_done'

    preclose_status = {
        'phase': preclose_phase,
        'signal_time': '15:30 ET',
        'moc_deadline': '15:50 ET',
        'current_time_et': now_et.strftime('%H:%M:%S'),
        'entries_done': preclose_phase == 'entries_done',
    }

    return jsonify({
        'status': 'online',
        'portfolio': portfolio,
        'position_details': position_details,
        'prices': prices,
        'prev_closes': _prev_close_cache,
        'universe': state.get('current_universe', []),
        'universe_year': state.get('universe_year'),
        'config': COMPASS_CONFIG,
        'chassis': {},
        'preclose': preclose_status,
        'hydra': hydra_data,
        'implementation_shortfall': {'available': False},
        'server_time': datetime.now().isoformat(),
        'engine': {
            'running': False,
            'started_at': None,
            'error': 'Showcase mode \u2014 view only',
            'cycles': 0,
        },
    })




@app.route('/api/cycle-log')
def api_cycle_log():
    """Return the 5-day cycle performance log (COMPASS vs SPY).

    Active cycles are enriched with live prices so the dashboard
    shows real-time COMPASS return, SPY return, and alpha.
    """
    log_file = os.path.join(STATE_DIR, 'cycle_log.json')
    if not os.path.exists(log_file):
        return jsonify([])
    try:
        with open(log_file, 'r') as f:
            cycles = json.load(f)
    except Exception:
        return jsonify([])

    # Enrich active cycles with live metrics
    for c in cycles:
        if c.get('status') != 'active':
            continue
        try:
            state = read_state()
            if not state:
                continue

            # Check if this is the first day of the cycle (just opened today)
            # On the first day, positions were bought at close — no real PnL yet
            cycle_start = c.get('start_date')
            last_trading = state.get('last_trading_date')
            is_first_day = (cycle_start == last_trading) if cycle_start and last_trading else False

            if is_first_day:
                c['compass_return'] = 0.0
                c['spy_return'] = 0.0
                c['alpha'] = 0.0
                c['portfolio_end'] = c.get('portfolio_start')
                c['spy_end'] = c.get('spy_start')
                continue

            # Current portfolio value from state (updated by live engine)
            positions = state.get('positions', {})
            position_meta = state.get('position_meta', {})
            # Fetch S&P 500 index — benchmark with global P&L
            symbols = list(positions.keys()) + ['^GSPC']
            prices = fetch_live_prices(symbols)

            # Sync positions_current with actual state holdings
            c['positions_current'] = sorted(positions.keys())

            # Portfolio value = sum(shares * current_price) + cash
            portfolio_now = state.get('cash', 0)
            for sym, pos in positions.items():
                price = prices.get(sym)
                if price:
                    portfolio_now += pos.get('shares', 0) * price
                else:
                    # Fallback to entry price
                    meta = position_meta.get(sym, {})
                    portfolio_now += pos.get('shares', 0) * meta.get('entry_price', pos.get('avg_cost', 0))

            port_start = c.get('portfolio_start')
            if port_start and port_start > 0:
                c['portfolio_end'] = round(portfolio_now, 2)
                c['compass_return'] = round((portfolio_now / port_start - 1) * 100, 2)

            # S&P 500 index return (benchmark)
            spy_price = prices.get('^GSPC')
            spy_start = c.get('spy_start')
            if spy_price and spy_start and spy_start > 0:
                c['spy_end'] = round(spy_price, 2)
                c['spy_return'] = round((spy_price / spy_start - 1) * 100, 2)

            # Alpha
            if c.get('compass_return') is not None and c.get('spy_return') is not None:
                c['alpha'] = round(c['compass_return'] - c['spy_return'], 2)
        except Exception:
            pass

    return jsonify(cycles)


@app.route('/api/live-chart')
def api_live_chart():
    """Return daily COMPASS vs S&P 500 indexed performance since live test start.

    Reads historical state files for COMPASS portfolio values and
    fetches SPY data from yfinance. Both series are indexed
    to 100 on the start date for easy visual comparison.
    """
    # 1. Read all dated state files for COMPASS daily values
    pattern = os.path.join(STATE_DIR, 'compass_state_2*.json')
    state_files = sorted(f for f in glob.glob(pattern)
                         if 'pre_rotation' not in f and 'latest' not in f)

    if not state_files:
        return jsonify({'dates': [], 'compass': [], 'spy': []})

    compass_data = {}  # date_str -> portfolio_value
    first_value = None
    for sf in state_files:
        try:
            with open(sf, 'r') as f:
                s = json.load(f)
            dt = s.get('last_trading_date')
            val = s.get('portfolio_value')
            if dt and val:
                compass_data[dt] = val
                if first_value is None:
                    first_value = val
        except Exception:
            continue

    if not compass_data or first_value is None:
        return jsonify({'dates': [], 'compass': [], 'spy': []})

    # Add today's live value from latest state, recalculated with live prices
    try:
        state = read_state()
        if state:
            today_str = state.get('last_trading_date')
            if today_str:
                # Recalculate with live prices (same as banner)
                pos_symbols = list(state.get('positions', {}).keys())
                if pos_symbols:
                    live_prices = fetch_live_prices(pos_symbols)
                    cash = state.get('cash', 0)
                    invested = sum(
                        state['positions'][s].get('shares', 0) * live_prices.get(s, state['positions'][s].get('avg_cost', 0))
                        for s in state.get('positions', {})
                    )
                    today_val = cash + invested if invested > 0 else state.get('portfolio_value')
                else:
                    today_val = state.get('portfolio_value')
                if today_val:
                    compass_data[today_str] = today_val
    except Exception:
        pass

    dates = sorted(compass_data.keys())
    start_date = dates[0]

    # 2. Fetch S&P 500 index data for the same period (try ^GSPC, fallback SPY)
    spy_data = {}
    if _HAS_YFINANCE:
        try:
            end_dt = date.today() + timedelta(days=1)
            hist = None
            for dl_sym in ['^GSPC', 'SPY']:
                try:
                    hist = yf.download(dl_sym, start=start_date,
                                     end=end_dt.isoformat(),
                                     progress=False, auto_adjust=True)
                    if len(hist) > 0:
                        break
                except Exception:
                    continue
            if hist is not None and len(hist) > 0:
                # Flatten multi-level columns (yfinance returns MultiIndex)
                if isinstance(hist.columns, pd.MultiIndex):
                    hist.columns = hist.columns.droplevel('Ticker')
                for idx, row in hist.iterrows():
                    dt_str = idx.strftime('%Y-%m-%d')
                    spy_data[dt_str] = float(row['Close'])
        except Exception:
            pass

    # Use live S&P 500 index price for today (from TradingView)
    today_str = date.today().strftime('%Y-%m-%d')
    if today_str in [d for d in dates]:
        try:
            live_spy = fetch_live_prices(['^GSPC'])
            if '^GSPC' in live_spy:
                spy_data[today_str] = live_spy['^GSPC']
        except Exception:
            pass

    # 3. Build aligned series indexed to 100
    spy_first = spy_data.get(start_date)
    result_dates = []
    result_compass = []
    result_spy = []

    for dt in dates:
        compass_val = compass_data[dt]
        compass_indexed = (compass_val / first_value) * 100

        result_dates.append(dt)
        result_compass.append(round(compass_indexed, 2))

        spy_val = spy_data.get(dt)
        if spy_val and spy_first:
            result_spy.append(round((spy_val / spy_first) * 100, 2))
        else:
            # Interpolate: use last known value
            result_spy.append(result_spy[-1] if result_spy else 100.0)

    return jsonify({
        'dates': result_dates,
        'compass': result_compass,
        'spy': result_spy,
        'start_date': start_date,
    })


@app.route('/api/equity')
def api_equity():
    """Return COMPASS equity curve data (full period from 2000)."""
    df = _equity_df
    if df is None:
        csv_path = os.path.join('backtests', 'v84_overlay_daily.csv')
        if not os.path.exists(csv_path):
            return jsonify({'equity': [], 'milestones': [], 'error': 'No backtest data'})
        try:
            df = pd.read_csv(csv_path, parse_dates=['date'])
        except Exception:
            return jsonify({'equity': [], 'milestones': [], 'error': 'Failed to read CSV'})

    val_col = 'portfolio_value' if 'portfolio_value' in df.columns else 'value'
    # Full period from 2000 — NO filter to 2016

    milestones = []
    vals = df[val_col]

    for target in [1_000_000, 2_000_000, 3_000_000, 4_000_000, 5_000_000]:
        crossed = df[vals >= target]
        if len(crossed) > 0:
            row = crossed.iloc[0]
            milestones.append({
                'date': row['date'].strftime('%Y-%m-%d'),
                'value': round(float(row[val_col]), 0),
                'label': f'${target/1e6:.0f}M',
                'type': 'milestone',
            })

    peak = vals.expanding().max()
    dd = (vals - peak) / peak
    in_dd = False
    dd_events = []
    dd_start_idx = None
    for idx in df.index:
        if dd[idx] < -0.15 and not in_dd:
            in_dd = True
            dd_start_idx = idx
        elif dd[idx] >= -0.02 and in_dd:
            in_dd = False
            mask = (df.index >= dd_start_idx) & (df.index <= idx)
            worst_idx = dd[mask].idxmin()
            worst_row = df.loc[worst_idx]
            worst_dd = dd[worst_idx]
            dd_events.append({
                'date': worst_row['date'].strftime('%Y-%m-%d'),
                'value': round(float(worst_row[val_col]), 0),
                'dd_pct': round(float(worst_dd * 100), 1),
            })

    for ev in dd_events:
        d = ev['date']
        if '2020-03' in d:
            ev['label'] = f'COVID Crash {ev["dd_pct"]}%'
        elif '2023' in d:
            ev['label'] = f'Max Drawdown {ev["dd_pct"]}%'
        elif '2024-08' in d or '2024-09' in d:
            ev['label'] = f'Correction {ev["dd_pct"]}%'
        elif '2025' in d:
            ev['label'] = f'Tariff Crisis {ev["dd_pct"]}%'
        elif '2001' in d or '2002' in d:
            ev['label'] = f'Dot-Com {ev["dd_pct"]}%'
        elif '2008' in d or '2009' in d:
            ev['label'] = f'GFC {ev["dd_pct"]}%'
        else:
            ev['label'] = f'Drawdown {ev["dd_pct"]}%'
        ev['type'] = 'drawdown'
        milestones.append(ev)

    ath_idx = vals.idxmax()
    ath_row = df.loc[ath_idx]
    milestones.append({
        'date': ath_row['date'].strftime('%Y-%m-%d'),
        'value': round(float(ath_row[val_col]), 0),
        'label': f'ATH ${ath_row[val_col]/1e6:.1f}M',
        'type': 'ath',
    })

    # Downsample every 10 rows (full 26yr period)
    sampled = df.iloc[::10]
    if df.index[-1] not in sampled.index:
        sampled = pd.concat([sampled, df.iloc[[-1]]])
    equity = []
    for _, row in sampled.iterrows():
        equity.append({
            'date': row['date'].strftime('%Y-%m-%d'),
            'value': round(float(row[val_col]), 0),
        })

    return jsonify({'equity': equity, 'milestones': milestones})


@app.route('/api/equity-comparison')
def api_equity_comparison():
    """Return COMPASS vs S&P 500 vs Net comparison data (full period from 2000)."""
    df = _equity_df
    spy_df = _spy_df

    if df is None:
        csv_path = os.path.join('backtests', 'v84_overlay_daily.csv')
        if not os.path.exists(csv_path):
            return jsonify({'error': 'No backtest data'})
        try:
            df = pd.read_csv(csv_path, parse_dates=['date'])
        except Exception as e:
            return jsonify({'error': f'Failed to read CSV: {str(e)}'})

    if spy_df is None:
        if not os.path.exists(SPY_BENCHMARK_CSV):
            return jsonify({'error': 'No SPY benchmark data'})
        try:
            spy_df = pd.read_csv(SPY_BENCHMARK_CSV, parse_dates=['date'])
        except Exception as e:
            return jsonify({'error': f'Failed to read SPY CSV: {str(e)}'})

    val_col = 'portfolio_value' if 'portfolio_value' in df.columns else 'value'

    df_copy = df.copy()
    spy_copy = spy_df.copy()
    df_copy['date_key'] = df_copy['date'].dt.normalize()
    spy_copy['date_key'] = spy_copy['date'].dt.normalize()

    merged = pd.merge(df_copy[['date_key', val_col]], spy_copy[['date_key', 'close']],
                       on='date_key', how='inner')

    if merged.empty:
        return jsonify({'error': 'No overlapping dates'})

    # Full period from 2000 — NO filter to 2016

    compass_start = float(merged[val_col].iloc[0])
    spy_start = float(merged['close'].iloc[0])

    merged['compass_val'] = merged[val_col]
    merged['spy_val'] = merged['close'] / spy_start * compass_start

    compass_final = float(merged['compass_val'].iloc[-1])
    spy_final = float(merged['spy_val'].iloc[-1])
    first_date = merged['date_key'].iloc[0]
    last_date = merged['date_key'].iloc[-1]
    years = (last_date - first_date).days / 365.25

    compass_cagr = (pow(compass_final / compass_start, 1 / years) - 1) * 100 if years > 0 else 0
    spy_cagr = (pow(spy_final / compass_start, 1 / years) - 1) * 100 if years > 0 else 0

    # Net equity curve (Signal - 2.0% fixed annual execution costs)
    EXECUTION_COST = 0.02
    daily_growth_signal = compass_cagr / 100.0
    net_cagr_decimal = daily_growth_signal - EXECUTION_COST
    days_elapsed = (merged['date_key'] - first_date).dt.days.values
    years_elapsed = days_elapsed / 365.25
    if daily_growth_signal > 0:
        adjustment = ((1 + net_cagr_decimal) / (1 + daily_growth_signal)) ** years_elapsed
    else:
        adjustment = np.ones(len(merged))
    merged['net_val'] = merged['compass_val'].values * adjustment

    net_final = float(merged['net_val'].iloc[-1])
    net_cagr = (pow(net_final / compass_start, 1 / years) - 1) * 100 if years > 0 else 0

    # Downsample every 10 rows, always include last row
    sampled = merged.iloc[::10]
    if merged.index[-1] not in sampled.index:
        sampled = pd.concat([sampled, merged.iloc[[-1]]])
    result = []
    for _, row in sampled.iterrows():
        result.append({
            'date': row['date_key'].strftime('%Y-%m-%d'),
            'compass': round(float(row['compass_val']), 0),
            'spy': round(float(row['spy_val']), 0),
            'net': round(float(row['net_val']), 0),
        })

    return jsonify({
        'data': result,
        'compass_cagr': round(compass_cagr, 2),
        'spy_cagr': round(spy_cagr, 2),
        'net_cagr': round(net_cagr, 2),
        'compass_final': round(compass_final, 0),
        'spy_final': round(spy_final, 0),
        'net_final': round(net_final, 0),
        'years': round(years, 1),
    })


@app.route('/api/annual-returns')
def api_annual_returns():
    """Return COMPASS vs S&P 500 annual returns for bar chart."""
    df = _equity_df
    spy_df = _spy_df

    if df is None:
        csv_path = os.path.join('backtests', 'v84_overlay_daily.csv')
        if not os.path.exists(csv_path):
            return jsonify({'error': 'No backtest data'})
        try:
            df = pd.read_csv(csv_path, parse_dates=['date'])
        except Exception:
            return jsonify({'error': 'Failed to read CSV'})

    val_col = 'portfolio_value' if 'portfolio_value' in df.columns else 'value'
    df_copy = df[['date', val_col]].copy()
    df_copy['year'] = df_copy['date'].dt.year

    # COMPASS annual returns: last value of year / first value of year - 1
    compass_annual = []
    for year, grp in df_copy.groupby('year'):
        start_val = float(grp[val_col].iloc[0])
        end_val = float(grp[val_col].iloc[-1])
        ret = ((end_val / start_val) - 1) * 100 if start_val > 0 else 0
        compass_annual.append({'year': int(year), 'return': round(ret, 2)})

    # SPY annual returns
    spy_annual = {}
    if spy_df is not None:
        spy_copy = spy_df[['date', 'close']].copy()
        spy_copy['year'] = spy_copy['date'].dt.year
        for year, grp in spy_copy.groupby('year'):
            start_val = float(grp['close'].iloc[0])
            end_val = float(grp['close'].iloc[-1])
            ret = ((end_val / start_val) - 1) * 100 if start_val > 0 else 0
            spy_annual[int(year)] = round(ret, 2)

    result = []
    positive_years = 0
    for item in compass_annual:
        yr = item['year']
        spy_ret = spy_annual.get(yr)
        if item['return'] > 0:
            positive_years += 1
        result.append({
            'year': yr,
            'compass': item['return'],
            'spy': spy_ret,
        })

    return jsonify({
        'data': result,
        'positive_years': positive_years,
        'total_years': len(compass_annual),
    })


@app.route('/api/backtest/status')
def api_backtest_status():
    return jsonify({
        'running': False,
        'last_result': 'showcase mode',
        'last_run_date': None,
    })


@app.route('/api/social-feed')
def api_social_feed():
    """Return social feed (news + reddit + SEC + analysis) for current holdings."""
    state = read_state()
    symbols = []
    if state:
        symbols = list(state.get('positions', {}).keys())
    if not symbols:
        universe = state.get('current_universe', []) if state else []
        symbols = universe[:5] if universe else ['SPY']

    messages = fetch_social_feed(symbols)
    return jsonify({'messages': messages, 'symbols': symbols})


@app.route('/api/news')
def api_news():
    """Legacy news endpoint."""
    return api_social_feed()


# ============================================================================
# ANALYTICS ENDPOINTS (lazy import — compute once, cache forever)
# ============================================================================

@app.route('/api/montecarlo')
def api_montecarlo():
    """Return Monte Carlo simulation results."""
    global _montecarlo_cache
    if _montecarlo_cache is not None:
        return jsonify(_montecarlo_cache)
    try:
        from compass_montecarlo import COMPASSMonteCarlo
        mc = COMPASSMonteCarlo()
        _montecarlo_cache = mc.run_all()
        return jsonify(_montecarlo_cache)
    except Exception as e:
        return jsonify({'error': f'Monte Carlo unavailable: {str(e)}'})


@app.route('/api/trade-analytics')
def api_trade_analytics():
    """Return trade segmentation analytics."""
    global _trade_analytics_cache
    if _trade_analytics_cache is not None:
        return jsonify(_trade_analytics_cache)
    try:
        from compass_trade_analytics import COMPASSTradeAnalytics
        ta = COMPASSTradeAnalytics()
        _trade_analytics_cache = ta.run_all()
        return jsonify(_trade_analytics_cache)
    except Exception as e:
        return jsonify({'error': f'Trade analytics unavailable: {str(e)}'})






# ============================================================================
# ENGINE CONTROL (disabled in showcase mode)
# ============================================================================

@app.route('/api/engine/start', methods=['POST'])
def api_engine_start():
    return jsonify({'ok': False, 'message': 'Engine disabled in showcase mode'})


@app.route('/api/engine/stop', methods=['POST'])
def api_engine_stop():
    return jsonify({'ok': False, 'message': 'Engine disabled in showcase mode'})


@app.route('/api/engine/status')
def api_engine_status():
    return jsonify({
        'running': False,
        'started_at': None,
        'error': 'Showcase mode \u2014 view only',
        'cycles': 0,
    })


@app.route('/api/preflight')
def api_preflight():
    return jsonify({
        'ready': False,
        'checks': {'mode': 'showcase'},
        'server_time': datetime.now().isoformat(),
    })


@app.route('/api/data-quality')
def api_data_quality():
    """Data quality scorecard — stub for showcase mode."""
    return jsonify({
        'mode': 'showcase',
        'message': 'Data quality monitoring available in live deployment only.',
        'checks': {},
    })


@app.route('/api/execution-microstructure')
def api_execution_microstructure():
    """Execution microstructure analysis — stub for showcase mode."""
    return jsonify({
        'mode': 'showcase',
        'message': 'Execution microstructure analysis available in live deployment only.',
        'results': {},
    })


@app.route('/api/overlay-status')
def api_overlay_status():
    """Return current overlay signals and diagnostics."""
    state = read_state()
    if not state:
        return jsonify({'available': False, 'error': 'No state file'})

    overlay = state.get('overlay', {})

    # Color coding for scalar
    scalar = overlay.get('capital_scalar', 1.0)
    if scalar >= 0.90:
        scalar_color = 'green'
        scalar_label = 'Normal'
    elif scalar >= 0.60:
        scalar_color = 'yellow'
        scalar_label = 'Cautious'
    else:
        scalar_color = 'red'
        scalar_label = 'Stressed'

    per_overlay = overlay.get('per_overlay', {})
    diag = overlay.get('diagnostics', {})

    return jsonify({
        'available': overlay.get('available', False),
        'capital_scalar': scalar,
        'scalar_color': scalar_color,
        'scalar_label': scalar_label,
        'position_floor': overlay.get('position_floor'),
        'per_overlay': {
            'bso': per_overlay.get('bso', 1.0),
            'm2': per_overlay.get('m2', 1.0),
            'fomc': per_overlay.get('fomc', 1.0),
        },
        'fed_emergency_active': bool(overlay.get('position_floor')),
        'credit_filter': {
            'hy_bps': diag.get('credit_filter', {}).get('hy_bps'),
            'excluded_sectors': diag.get('credit_filter', {}).get('excluded', []),
        },
    })


# Terminal removed — replaced with WhatsApp contact FAB


def _maybe_regenerate_interpretation(ml_dir, entries, insights):
    interp_path = os.path.join(ml_dir, 'interpretation.md')
    try:
        mtime = os.path.getmtime(interp_path)
        age_days = (time_module.time() - mtime) / 86400
        if age_days < 5:
            return
    except OSError:
        pass

    n_entries = sum(1 for r in entries if r.get('_type') == 'decision' and r.get('decision_type') == 'entry')
    n_exits = sum(1 for r in entries if r.get('_type') == 'decision' and r.get('decision_type') == 'exit')
    n_skips = sum(1 for r in entries if r.get('_type') == 'decision' and r.get('decision_type') == 'skip')
    n_snapshots = sum(1 for r in entries if r.get('_type') == 'snapshot')
    n_outcomes = sum(1 for r in entries if r.get('_type') == 'outcome')
    n_decisions = n_entries + n_exits + n_skips

    phase = insights.get('learning_phase', 1)
    trading_days = insights.get('trading_days', 0)
    days_to_phase2 = max(0, 63 - trading_days)

    pa = insights.get('portfolio_analytics', {})
    current_value = pa.get('current_value', 0)
    total_return = pa.get('total_return', 0)
    max_dd = pa.get('max_drawdown', 0)
    daily_sharpe = pa.get('daily_sharpe_annualized')

    ta = insights.get('trade_analytics', {})
    overall = ta.get('overall', {})
    n_trades = overall.get('n', 0)
    win_rate = overall.get('win_rate')
    mean_return = overall.get('mean_return')
    stop_rate = overall.get('stop_rate')
    avg_days = overall.get('avg_days_held')
    best_trade = overall.get('best')
    worst_trade = overall.get('worst')

    regime_counts = {}
    snapshots = [r for r in entries if r.get('_type') == 'snapshot']
    for s in snapshots:
        bucket = s.get('regime_bucket', 'unknown')
        regime_counts[bucket] = regime_counts.get(bucket, 0) + 1

    by_exit = ta.get('by_exit_reason', {})
    decisions = [r for r in entries if r.get('_type') == 'decision']
    recent = decisions[-5:] if len(decisions) > 5 else decisions
    outcomes = [r for r in entries if r.get('_type') == 'outcome']

    lines = []
    lines.append(f'### System Status\n')
    lines.append(f'COMPASS ML Learning is in **Phase {phase}** (data collection). {trading_days} trading days logged.')
    if phase < 2:
        lines.append(f' ML models activate at Phase 2 (~{days_to_phase2} trading days remaining).\n')
    else:
        lines.append('\n')

    lines.append(f'### Data Summary\n')
    lines.append(f'- **{n_decisions} decisions** logged: {n_entries} entries, {n_exits} exits, {n_skips} skips')
    lines.append(f'- **{n_snapshots} daily snapshots** tracking portfolio evolution')
    lines.append(f'- **{n_outcomes} completed trades** with full outcome data\n')

    lines.append(f'### Portfolio Performance\n')
    if current_value:
        lines.append(f'- Current value: **${current_value:,.0f}**')
        lines.append(f'- Total return: **{total_return * 100:+.2f}%**')
        lines.append(f'- Max drawdown: **{max_dd * 100:.2f}%**')
        if daily_sharpe is not None:
            lines.append(f'- Daily Sharpe (annualized): **{daily_sharpe:.2f}**')
    else:
        lines.append(f'- Insufficient data')
    lines.append('')

    lines.append(f'### Trade Analysis\n')
    if n_trades > 0:
        lines.append(f'- Completed trades: **{n_trades}**')
        if win_rate is not None:
            lines.append(f'- Win rate: **{win_rate * 100:.0f}%**')
        if mean_return is not None:
            lines.append(f'- Average return: **{mean_return * 100:+.1f}%**')
        if stop_rate is not None:
            lines.append(f'- Stop rate: **{stop_rate * 100:.0f}%**')
        if avg_days is not None:
            lines.append(f'- Average holding period: **{avg_days:.1f} days**')
        if best_trade is not None and worst_trade is not None:
            lines.append(f'- Best trade: **{best_trade * 100:+.1f}%** / Worst: **{worst_trade * 100:+.1f}%**')
        if outcomes:
            lines.append('')
            wins = [o for o in outcomes if (o.get('gross_return') or 0) > 0]
            losses = [o for o in outcomes if (o.get('gross_return') or 0) <= 0]
            if wins:
                win_str = ', '.join(f"{o['symbol']} {o['gross_return']*100:+.1f}%" for o in wins)
                lines.append(f'- Winners: {win_str}')
            if losses:
                loss_str = ', '.join(f"{o['symbol']} {o['gross_return']*100:+.1f}%" for o in losses)
                lines.append(f'- Losers: {loss_str}')
    else:
        lines.append(f'- No completed trades yet')
    lines.append('')

    lines.append(f'### Regime Observations\n')
    if regime_counts:
        total_snaps = sum(regime_counts.values())
        for bucket, count in sorted(regime_counts.items(), key=lambda x: -x[1]):
            pct = count / total_snaps * 100
            lines.append(f'- **{bucket}**: {count} days ({pct:.0f}%)')
    else:
        lines.append(f'- No regime data yet')
    lines.append('')

    if by_exit:
        lines.append(f'### Exit Reason Breakdown\n')
        for reason, stats in by_exit.items():
            n = stats.get('n', 0)
            mr = stats.get('mean_return')
            wr = stats.get('win_rate')
            reason_label = reason.replace('_', ' ').replace('position stop adaptive', 'adaptive stop').title()
            mr_str = f'{mr * 100:+.1f}%' if mr is not None else '--'
            wr_str = f'{wr * 100:.0f}%' if wr is not None else '--'
            lines.append(f'- **{reason_label}** ({n} trades): avg return {mr_str}, win rate {wr_str}')
        lines.append('')

    lines.append(f'### Recent Activity\n')
    if recent:
        for r in recent:
            ts = (r.get('timestamp') or r.get('date', ''))[:16]
            dtype = r.get('decision_type', '?').upper()
            sym = r.get('symbol', '??')
            if dtype == 'EXIT':
                ret = r.get('current_return')
                ret_str = f' return={ret * 100:+.1f}%' if ret is not None else ''
                lines.append(f'- `{ts}` **{dtype}** {sym} — {r.get("exit_reason", "")}{ret_str}')
            elif dtype == 'ENTRY':
                regime = r.get('regime_bucket', '')
                lines.append(f'- `{ts}` **{dtype}** {sym} — regime={regime}')
            else:
                lines.append(f'- `{ts}` **{dtype}** {sym}')
    else:
        lines.append(f'- No recent decisions')
    lines.append('')

    lines.append(f'### Next Milestone\n')
    if phase < 2:
        lines.append(f'Phase 2 ML begins in ~{days_to_phase2} trading days. Continue collecting entry/exit decisions and completed trade outcomes.')
    else:
        lines.append(f'Phase {phase} active. ML models are being trained on accumulated data.')
    lines.append('')

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines.append(f'---\n*Auto-generated on {now_str}. Refreshes every 5 days.*')

    md = '\n'.join(lines)
    try:
        with open(interp_path, 'w', encoding='utf-8') as f:
            f.write(md)
    except Exception:
        pass


@app.route('/api/ml-learning')
def api_ml_learning():
    ml_dir = os.path.join('state', 'ml_learning')
    entries = []
    for fname, etype in [('decisions.jsonl', 'decision'), ('daily_snapshots.jsonl', 'snapshot'), ('outcomes.jsonl', 'outcome')]:
        fpath = os.path.join(ml_dir, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            rec = json.loads(line)
                            rec['_type'] = etype
                            entries.append(rec)
            except Exception:
                pass
    entries.sort(key=lambda r: r.get('timestamp', r.get('date', '')))
    insights = {}
    insights_path = os.path.join(ml_dir, 'insights.json')
    if os.path.exists(insights_path):
        try:
            with open(insights_path, 'r') as f:
                insights = json.load(f)
        except Exception:
            pass
    _maybe_regenerate_interpretation(ml_dir, entries, insights)
    interpretation = ''
    interp_path = os.path.join(ml_dir, 'interpretation.md')
    if os.path.exists(interp_path):
        try:
            with open(interp_path, 'r') as f:
                interpretation = f.read()
        except Exception:
            pass
    return jsonify({
        'log_entries': entries,
        'insights': insights,
        'interpretation': interpretation,
    })


@app.route('/robots.txt')
def robots_txt():
    return app.response_class(
        "User-agent: *\nAllow: /\nSitemap: https://omnicapital.onrender.com/sitemap.xml\n",
        mimetype='text/plain'
    )


@app.route('/sitemap.xml')
def sitemap_xml():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://omnicapital.onrender.com/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>
</urlset>"""
    return app.response_class(xml, mimetype='application/xml')


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 60)
    print("COMPASS v8.4 \u2014 Cloud Dashboard (Showcase)")
    print("=" * 60)
    print(f"Port: {port}")
    print(f"Mode: {'SHOWCASE' if SHOWCASE_MODE else 'local'}")
    print(f"yfinance: {'available' if _HAS_YFINANCE else 'NOT available'}")
    print(f"requests: {'available' if _HAS_REQUESTS else 'NOT available'}")
    print(f"Equity data: {'loaded' if _equity_df is not None else 'NOT loaded'}")
    print(f"SPY data: {'loaded' if _spy_df is not None else 'NOT loaded'}")
    print("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
