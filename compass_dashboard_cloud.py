"""
HYDRA v8.4 — Cloud Dashboard
==========================================
Full-featured Flask dashboard for Render.com deployment.
Shows live prices, backtest equity curves, trade analytics,
execution microstructure, social feed, and research paper.

Modes (set via HYDRA_MODE env var):
  - showcase (default): read-only dashboard, no engine
  - live: dashboard + HYDRA engine with PaperBroker

Deploy: git push to GitHub → auto-deploy on Render.
"""

from flask import Flask, jsonify, render_template, request
import gzip
import json
import os
import glob
import math
import re
import numpy as np
import pandas as pd
import logging
import time as time_module
import tempfile
import shutil
from datetime import datetime, date, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional
import threading

from compass_portfolio_risk import compute_portfolio_risk

# Optional imports (graceful if missing)
try:
    import yfinance as yf
    logging.getLogger('yfinance').setLevel(logging.CRITICAL)
    _HAS_YFINANCE = True
except ImportError:
    logging.getLogger(__name__).warning(
        'yfinance import unavailable in cloud dashboard',
        exc_info=True,
    )
    _HAS_YFINANCE = False

try:
    import requests as http_requests
    _HAS_REQUESTS = True
except ImportError:
    logging.getLogger(__name__).warning(
        'requests import unavailable in cloud dashboard',
        exc_info=True,
    )
    _HAS_REQUESTS = False

try:
    import anthropic
    _HAS_ANTHROPIC = bool(os.environ.get('ANTHROPIC_API_KEY'))
except ImportError:
    logging.getLogger(__name__).warning(
        'anthropic import unavailable in cloud dashboard',
        exc_info=True,
    )
    _HAS_ANTHROPIC = False

# HYDRA engine (cloud paper trading — runs when local is offline)
_ENGINE_IMPORT_ERROR = None
try:
    from omnicapital_live import COMPASSLive, CONFIG as ENGINE_CONFIG
    _HAS_ENGINE = True
except ImportError as e:
    _HAS_ENGINE = False
    _ENGINE_IMPORT_ERROR = f'{type(e).__name__}: {e}'
    logging.getLogger(__name__).error(
        'Failed to import omnicapital_live for cloud engine startup',
        exc_info=True,
    )

app = Flask(__name__)
logger = logging.getLogger(__name__)

# Env vars whose values must be masked in logs
_SECRET_ENV_VARS = {'ANTHROPIC_API_KEY', 'GIT_TOKEN', 'SECRET_KEY', 'API_KEY'}


def _validate_environment():
    hydra_mode = os.environ.get('HYDRA_MODE')
    compass_mode = os.environ.get('COMPASS_MODE')
    port = os.environ.get('PORT')

    if hydra_mode is not None and hydra_mode not in ('live', 'paper', 'backtest', 'showcase'):
        logger.warning("HYDRA_MODE='%s' is not a recognized value (expected live|paper|backtest|showcase)", hydra_mode)

    if compass_mode is not None and compass_mode not in ('live', 'cloud'):
        logger.warning("COMPASS_MODE='%s' is not a recognized value (expected live|cloud)", compass_mode)

    if port is not None:
        if not port.isdigit():
            logger.warning("PORT='%s' is not numeric", port)

    env_vars_to_log = ['HYDRA_MODE', 'COMPASS_MODE', 'PORT', 'STATE_DIR',
                       'ANTHROPIC_API_KEY', 'GIT_TOKEN', 'RENDER_EXTERNAL_URL',
                       'SEC_USER_AGENT']
    parts = []
    for name in env_vars_to_log:
        val = os.environ.get(name)
        if val is None:
            parts.append(f"{name}=<unset>")
        elif name in _SECRET_ENV_VARS:
            parts.append(f"{name}=****")
        else:
            parts.append(f"{name}={val}")
    logger.info("Cloud dashboard env: %s", ', '.join(parts))


_validate_environment()


def _load_json_with_invalid_constants(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.loads(f.read(), parse_constant=lambda _constant: None)


@app.errorhandler(500)
def handle_500(e):
    logger.error(f"500 error (worker {os.getpid()}): {e}", exc_info=True)
    return jsonify({
        'status': 'offline',
        'error': 'Internal server error',
        'server_time': datetime.now().isoformat(),
    }), 200


@app.errorhandler(Exception)
def handle_exception(e):
    logger.error(f"Unhandled exception (worker {os.getpid()}): {e}", exc_info=True)
    return jsonify({
        'status': 'offline',
        'error': 'Internal server error',
        'server_time': datetime.now().isoformat(),
    }), 200


@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
        "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'"
    )
    # Prevent Cloudflare/CDN from caching API responses (stale prices)
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['CDN-Cache-Control'] = 'no-store'
        response.headers['Cloudflare-CDN-Cache-Control'] = 'no-store'
    return response

# ============================================================================
# HYDRA v8.4 PARAMETERS (read-only reference — ALGORITHM LOCKED)
# ============================================================================

HYDRA_CONFIG = {
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
STATE_DIR = os.environ.get('STATE_DIR', 'state')
LOG_DIR = os.environ.get('LOG_DIR', 'logs')
DATA_CACHE_DIR = os.environ.get('DATA_CACHE_DIR', 'data_cache')
ENGINE_RUNTIME_STATUS_BASENAME = 'cloud_engine_runtime.json'
ENGINE_HEARTBEAT_INTERVAL_SECONDS = 15
ENGINE_HEARTBEAT_STALE_SECONDS = 45
SPY_BENCHMARK_CSV = os.path.join('backtests', 'spy_benchmark.csv')
GITHUB_STATE_URL = 'https://raw.githubusercontent.com/lucasabu1988/HydraOmniCapital/main/state/compass_state_latest.json'

# Rattlesnake parameters (mirrored from rattlesnake_signals.py for dashboard)
R_VIX_PANIC = 35
R_BASE_HYDRA_ALLOC = 0.425
R_BASE_RATTLE_ALLOC = 0.425
R_BASE_CATALYST_ALLOC = 0.15
R_MAX_HYDRA_ALLOC = 0.75

PRICE_CACHE_SECONDS = 60  # legacy ref (use PRICE_CACHE_SECONDS_NORMAL)

# Live test — positions entered at close on Mar 16, 2026
LIVE_TEST_START_DATE = '2026-03-16'
LIVE_TEST_PORTFOLIO_START = 100_000  # initial capital at start
_spy_start_price = None

# Last-known-good portfolio metrics — prevents wild swings from stale Yahoo data
_last_good_portfolio: Optional[dict] = None
_last_good_portfolio_time: Optional[datetime] = None
_portfolio_metrics_lock = threading.Lock()

# Showcase mode keeps the dashboard online with static/read-only data and the engine disabled.
SHOWCASE_MODE = os.environ.get('HYDRA_MODE', 'live') == 'showcase'

# Real engine status tracking
_engine_status = {
    'running': False,
    'started_at': None,
    'error': 'Showcase mode — set HYDRA_MODE=live to enable engine' if SHOWCASE_MODE else None,
    'cycles': 0,
    'startup_started_at': None,
    'last_git_pull': None,
    'state_recovery': None,
    'crash_count': 0,
    'last_crash_at': None,
    'last_crash_error': None,
    'restarts': [],
}
_engine_status_lock = threading.Lock()
_engine_heartbeat_thread = None

_risk_cache = None
_risk_cache_time = None
RISK_CACHE_SECONDS = 300

_hydra_regime_cache = None
_hydra_regime_cache_time = None
_hydra_regime_lock = threading.Lock()
HYDRA_REGIME_CACHE_SECONDS = 60
_risk_cache_lock = threading.Lock()
_montecarlo_lock = threading.Lock()
_data_quality_cache = None
_data_quality_cache_time = None
DATA_QUALITY_CACHE_SECONDS = 1800

# ============================================================================
# DATA PRELOAD (at import time — shared across gunicorn workers via --preload)
# ============================================================================

_equity_df = None
_spy_df = None


def _preload_data():
    """Load CSV data at startup (not on first request)."""
    global _equity_df, _spy_df
    # HYDRA multi-strategy data (HYDRA + Rattlesnake with cash recycling)
    csv_path = os.path.join('backtests', 'hydra_clean_daily.csv')
    if os.path.exists(csv_path):
        try:
            _equity_df = pd.read_csv(csv_path, parse_dates=['date'])
        except Exception as e:
            logger.warning(f"_preload_data failed: {e}")
    spy_path = SPY_BENCHMARK_CSV
    if os.path.exists(spy_path):
        try:
            _spy_df = pd.read_csv(spy_path, parse_dates=['date'])
        except Exception as e:
            logger.warning(f"_preload_data failed: {e}")


_preload_data()

# ============================================================================
# PRICE CACHE (all live prices from Yahoo Finance v8 API)
# ============================================================================

_price_cache: Dict[str, float] = {}
_prev_close_cache: Dict[str, float] = {}
_price_cache_time: Optional[datetime] = None
_price_cache_lock = threading.Lock()
_yf_session_lock = threading.Lock()
_yf_consecutive_failures: int = 0
_yf_fail_count: int = 0
_yf_circuit_open_until: float = 0

# Shared price cache file — ensures all gunicorn workers serve identical prices
_SHARED_PRICE_CACHE_FILE = os.path.join(STATE_DIR, '.price_cache_shared.json')

PRICE_CACHE_SECONDS_NORMAL = 60   # 1 min default
PRICE_CACHE_SECONDS_BACKOFF = 300  # 5 min after repeated failures

_YF_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
}


def _write_shared_price_cache(prices: Dict[str, float], prev_closes: Dict[str, float]):
    """Write price cache to shared file so all gunicorn workers use identical prices."""
    try:
        payload = {
            'ts': datetime.now().isoformat(),
            'prices': prices,
            'prev_closes': prev_closes,
        }
        _atomic_write_json_simple(_SHARED_PRICE_CACHE_FILE, payload)
    except Exception as e:
        logger.warning('Failed to write shared price cache: %s', e)


def _read_shared_price_cache(max_age_seconds: float) -> Optional[dict]:
    """Read shared price cache if fresh enough. Returns dict with prices/prev_closes or None."""
    try:
        if not os.path.exists(_SHARED_PRICE_CACHE_FILE):
            return None
        with open(_SHARED_PRICE_CACHE_FILE, 'r') as f:
            data = json.load(f)
        ts = datetime.fromisoformat(data['ts'])
        age = (datetime.now() - ts).total_seconds()
        if age > max_age_seconds:
            return None
        return data
    except Exception as e:
        logger.warning('Failed to read shared price cache: %s', e)
        return None


def _atomic_write_json_simple(path, payload):
    """Minimal atomic JSON write (no tempfile import needed — uses rename)."""
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(payload, f)
    os.replace(tmp, path)


# Yahoo Finance v8 crumb/cookie session (reused across requests)
_yf_session: Optional['http_requests.Session'] = None
_yf_crumb: Optional[str] = None


def _yf_reset_session():
    global _yf_session, _yf_crumb
    with _yf_session_lock:
        _yf_session = None
        _yf_crumb = None


def _yf_get_session():
    """Get or create a Yahoo Finance session with valid crumb."""
    global _yf_session, _yf_crumb
    with _yf_session_lock:
        if _yf_session and _yf_crumb:
            return _yf_session, _yf_crumb
        try:
            s = http_requests.Session()
            s.headers.update(_YF_HEADERS)
            # Get cookie
            s.get('https://fc.yahoo.com', timeout=5)
            # Get crumb
            r = s.get('https://query2.finance.yahoo.com/v1/test/getcrumb', timeout=5)
            if r.status_code == 200 and r.text:
                _yf_session = s
                _yf_crumb = r.text
                logger.info('Yahoo Finance session established (crumb obtained)')
                return _yf_session, _yf_crumb
        except Exception as e:
            logger.warning('Failed to get Yahoo Finance crumb: %s', e, exc_info=True)
        return None, None


def _yf_fetch_batch(symbols: List[str]) -> Dict[str, dict]:
    """Fetch multiple symbols in ONE request via Yahoo Finance v7 quote API.
    Returns {symbol: {'price': float, 'prev_close': float}}."""
    global _yf_fail_count, _yf_circuit_open_until

    if not _HAS_REQUESTS or not symbols:
        return {}

    # Circuit breaker: skip fetch if circuit is open
    if time_module.time() < _yf_circuit_open_until:
        logger.warning('yfinance circuit breaker OPEN — skipping fetch until %.0f',
                       _yf_circuit_open_until)
        return {}

    results = {}

    # Try v7 batch quote first (single request for all symbols)
    # Per-symbol staleness: reject only stale symbols, not the entire batch.
    # Previously, ONE stale symbol caused ALL v7 results to be discarded,
    # forcing v8 fallback which returns yesterday's close for indices.
    session, crumb = _yf_get_session()
    if session and crumb:
        try:
            url = 'https://query2.finance.yahoo.com/v7/finance/quote'
            params = {
                'symbols': ','.join(symbols),
                'fields': 'regularMarketPrice,regularMarketPreviousClose,regularMarketTime,symbol',
                'crumb': crumb,
            }
            r = session.get(url, params=params, timeout=15)
            if r.status_code == 200:
                data = r.json()
                stale_syms = []
                for quote in data.get('quoteResponse', {}).get('result', []):
                    sym = quote.get('symbol')
                    price = quote.get('regularMarketPrice')
                    prev = quote.get('regularMarketPreviousClose')
                    mkt_time = quote.get('regularMarketTime', 0)
                    if sym and price and price > 0:
                        if mkt_time and (time_module.time() - mkt_time) > 21600:
                            stale_syms.append(sym)
                            continue  # skip this symbol, don't poison the batch
                        out = {'price': float(price)}
                        if prev and prev > 0:
                            out['prev_close'] = float(prev)
                        results[sym] = out
                if stale_syms:
                    logger.info('Yahoo v7: skipped %d stale symbols: %s', len(stale_syms),
                                stale_syms[:10])
                if results:
                    # Only fall through to v8 for symbols NOT already fetched
                    v8_needed = [s for s in symbols if s not in results]
                    if not v8_needed:
                        return results
                    # Fetch remaining via v8 below
                    symbols = v8_needed
            elif r.status_code in (401, 403):
                _yf_reset_session()
                logger.info('Yahoo Finance crumb expired, will refresh next call')
        except Exception as e:
            logger.warning('Yahoo Finance v7 batch failed: %s', e, exc_info=True)

    # Fallback: v8 chart API (one request per symbol, with spacing)
    # Only fetch symbols not already resolved by v7 above.
    for sym in symbols:
        if sym in results:
            continue
        try:
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{sym}'
            params = {'range': '1d', 'interval': '1m'}  # 1m interval for fresher regularMarketPrice
            r = http_requests.get(url, params=params, headers=_YF_HEADERS, timeout=10)
            if r.status_code == 429:
                logger.warning('Yahoo Finance rate-limited (429), stopping batch')
                break
            if r.status_code != 200:
                logger.warning(f'Yahoo Finance {sym} returned {r.status_code}')
                continue
            data = r.json()
            result_data = data.get('chart', {}).get('result', [])
            if not result_data:
                continue
            meta = result_data[0].get('meta', {})
            price = meta.get('regularMarketPrice')
            prev_close = meta.get('chartPreviousClose') or meta.get('previousClose')
            if price and price > 0:
                # Guard: reject if v8 price equals prev_close (stale echo)
                if prev_close and abs(price - prev_close) < 0.001:
                    logger.info('Yahoo v8 %s: price %.2f == prev_close (stale echo), skipping',
                                sym, price)
                    continue
                out = {'price': float(price)}
                if prev_close and prev_close > 0:
                    out['prev_close'] = float(prev_close)
                results[sym] = out
            time_module.sleep(0.15)
        except Exception as e:
            logger.warning('Yahoo Finance %s fetch failed: %s', sym, e, exc_info=True)

    # Circuit breaker: track consecutive failures
    if results:
        _yf_fail_count = 0
    else:
        _yf_fail_count += 1
        if _yf_fail_count >= 5:
            _yf_circuit_open_until = time_module.time() + 300
            logger.error('yfinance circuit breaker OPENED after %d consecutive failures — '
                         'backing off for 300s', _yf_fail_count)

    return results


def _get_yf_consecutive_failures():
    with _price_cache_lock:
        return _yf_consecutive_failures


def fetch_live_prices(symbols: List[str]) -> Dict[str, float]:
    """Fetch all live prices from Yahoo Finance.
    Returns {symbol: price_float}. Previous closes in _prev_close_cache.
    Uses a shared file cache so all gunicorn workers serve identical prices."""
    global _price_cache, _prev_close_cache, _price_cache_time, _yf_consecutive_failures

    if not symbols:
        return {}

    with _price_cache_lock:
        # Adaptive cache TTL: back off when Yahoo is rate-limiting
        cache_ttl = PRICE_CACHE_SECONDS_BACKOFF if _yf_consecutive_failures >= 3 else PRICE_CACHE_SECONDS_NORMAL
        now = datetime.now()
        if _price_cache_time and (now - _price_cache_time).total_seconds() < cache_ttl:
            missing = [s for s in symbols if s not in _price_cache]
            if not missing:
                return {s: _price_cache[s] for s in symbols if s in _price_cache}
        else:
            # DON'T clear cache — keep stale prices as fallback
            missing = symbols

    # Before hitting Yahoo, check if another worker already has fresh prices
    shared = _read_shared_price_cache(max_age_seconds=cache_ttl)
    if shared:
        shared_prices = shared.get('prices', {})
        shared_prev = shared.get('prev_closes', {})
        still_missing = [s for s in missing if s not in shared_prices]
        if not still_missing:
            with _price_cache_lock:
                _price_cache.update({s: shared_prices[s] for s in symbols if s in shared_prices})
                _prev_close_cache.update(shared_prev)
                _price_cache_time = datetime.fromisoformat(shared['ts'])
            return {s: _price_cache[s] for s in symbols if s in _price_cache}
        missing = still_missing

    if missing:
        yf_results = _yf_fetch_batch(missing)
        fetch_completed = datetime.now()
        with _price_cache_lock:
            if yf_results:
                _yf_consecutive_failures = 0
                for sym, result in yf_results.items():
                    new_price = result['price']
                    old_price = _price_cache.get(sym)
                    # Guard: don't overwrite a recent price with one that matches
                    # the old prev_close (stale echo from Yahoo CDN).
                    old_prev = _prev_close_cache.get(sym)
                    if (old_price and old_prev
                            and abs(new_price - old_prev) < 0.01
                            and abs(old_price - old_prev) > 0.01
                            and _price_cache_time
                            and (fetch_completed - _price_cache_time).total_seconds() < 120):
                        logger.info('Rejected stale price for %s: new=%.2f == old prev_close=%.2f, '
                                    'keeping cached=%.2f', sym, new_price, old_prev, old_price)
                        continue
                    _price_cache[sym] = new_price
                    if 'prev_close' in result:
                        _prev_close_cache[sym] = result['prev_close']
                _price_cache_time = fetch_completed
                # Write to shared file so other workers get the same prices
                _write_shared_price_cache(dict(_price_cache), dict(_prev_close_cache))
            else:
                _yf_consecutive_failures += 1
                if _yf_consecutive_failures >= 3:
                    logger.warning(f'Yahoo Finance: {_yf_consecutive_failures} consecutive failures, '
                                  f'backing off to {PRICE_CACHE_SECONDS_BACKOFF}s cache TTL')
                # On failure: set short TTL so we retry soon (15s), not full cache duration
                _price_cache_time = fetch_completed - timedelta(seconds=max(0, cache_ttl - 15))
    return {s: _price_cache[s] for s in symbols if s in _price_cache}


# ============================================================================
# STATE READER
# ============================================================================

def read_state() -> Optional[dict]:
    """Read latest state from JSON file (with retry on decode error from concurrent write)."""
    for attempt in range(2):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r') as f:
                    return json.load(f)
            except json.JSONDecodeError:
                if attempt == 0:
                    time_module.sleep(0.1)
                    continue
                logger.warning('State file exists but contains invalid JSON after retry: %s', STATE_FILE)
            except IOError:
                logger.error('Failed to read state file %s', STATE_FILE, exc_info=True)
                break
    return None


def _engine_thread_is_alive():
    return bool(_cloud_engine_thread and _cloud_engine_thread.is_alive())


def _engine_is_operational(engine=None):
    snapshot = engine or _engine_snapshot()
    return bool(snapshot.get('running') and snapshot.get('thread_alive'))


def _engine_runtime_status_path():
    return os.path.join(STATE_DIR, ENGINE_RUNTIME_STATUS_BASENAME)


def _write_engine_runtime_status(engine=None, heartbeat_at=None):
    snapshot = engine or _engine_status
    thread_alive = _engine_thread_is_alive()
    payload = {
        'pid': os.getpid(),
        'running': bool(snapshot.get('running') and thread_alive),
        'thread_alive': thread_alive,
        'started_at': _coerce_health_timestamp(snapshot.get('started_at')),
        'startup_started_at': _coerce_health_timestamp(snapshot.get('startup_started_at')),
        'error': snapshot.get('error'),
        'cycles': int(
            getattr(_cloud_engine, '_cycles_completed', 0)
            if _cloud_engine else snapshot.get('cycles', 0)
        ),
        'crash_count': int(snapshot.get('crash_count') or 0),
        'last_crash_at': _coerce_health_timestamp(snapshot.get('last_crash_at')),
        'last_crash_error': snapshot.get('last_crash_error'),
        'restarts': list(snapshot.get('restarts') or []),
        'heartbeat_at': _coerce_health_timestamp(heartbeat_at or datetime.now()),
    }
    try:
        _atomic_write_json(_engine_runtime_status_path(), payload)
    except OSError:
        logger.warning('Failed to write shared engine runtime status', exc_info=True)
    return payload


def _read_engine_runtime_status(now=None):
    now = now or datetime.now()
    status_path = _engine_runtime_status_path()
    if not os.path.exists(status_path):
        return None

    try:
        with open(status_path, 'r', encoding='utf-8') as status_file:
            payload = json.load(status_file)
    except Exception:
        logger.warning('Failed to read shared engine runtime status from %s', status_path, exc_info=True)
        return None

    if not isinstance(payload, dict):
        logger.warning('Ignoring malformed shared engine runtime status from %s', status_path)
        return None

    owner_pid = payload.get('pid')
    try:
        owner_pid = int(owner_pid) if owner_pid is not None else None
    except (TypeError, ValueError):
        logger.warning('Shared engine runtime status has invalid pid=%r', owner_pid, exc_info=True)
        owner_pid = None

    heartbeat_dt = _parse_health_datetime(payload.get('heartbeat_at'))
    heartbeat_age_seconds = None
    if heartbeat_dt is not None:
        heartbeat_age_seconds = round((now - heartbeat_dt).total_seconds(), 1)

    owner_alive = bool(owner_pid is not None and _engine_lock_owner_is_alive(owner_pid))
    heartbeat_fresh = bool(
        heartbeat_age_seconds is not None and heartbeat_age_seconds <= ENGINE_HEARTBEAT_STALE_SECONDS
    )
    thread_alive = bool(payload.get('thread_alive')) and owner_alive and heartbeat_fresh
    running = bool(payload.get('running')) and thread_alive

    payload['pid'] = owner_pid
    payload['owner_alive'] = owner_alive
    payload['heartbeat_at'] = heartbeat_dt.isoformat() if heartbeat_dt is not None else None
    payload['heartbeat_age_seconds'] = heartbeat_age_seconds
    payload['thread_alive'] = thread_alive
    payload['running'] = running
    payload['engine_alive'] = running
    payload['cycles'] = int(payload.get('cycles') or 0)
    payload['crash_count'] = int(payload.get('crash_count') or 0)
    return payload


def _ensure_engine_runtime_heartbeat():
    global _engine_heartbeat_thread
    if _engine_heartbeat_thread and _engine_heartbeat_thread.is_alive():
        return
    _engine_heartbeat_thread = threading.Thread(
        target=_engine_runtime_heartbeat_loop,
        daemon=True,
        name='CloudEngineHeartbeat',
    )
    _engine_heartbeat_thread.start()


def _engine_runtime_heartbeat_loop():
    while True:
        try:
            snapshot = _write_engine_runtime_status()
        except Exception:
            logger.warning('Shared engine heartbeat loop failed to persist status', exc_info=True)
            snapshot = {'running': False}

        if not _engine_thread_is_alive() and not snapshot.get('running'):
            return
        time_module.sleep(ENGINE_HEARTBEAT_INTERVAL_SECONDS)


def _market_is_open(now_et=None):
    ET = ZoneInfo('America/New_York')
    now_et = now_et or datetime.now(ET)
    if now_et.weekday() >= 5:
        return False
    return dtime(9, 30) <= now_et.time() < dtime(16, 0)


def _price_freshness_snapshot():
    with _price_cache_lock:
        cache_time = _price_cache_time
        cache_size = len(_price_cache)
    # Fallback to the shared file cache when the in-memory value is absent.
    # Under gunicorn --preload, each worker has its own _price_cache_time; only
    # the engine-owning worker actually calls _fetch_prices_internal, so the
    # serving worker's in-memory value stays None forever and /api/state.data_freshness
    # reports 'stale' even when prices are fresh on disk. Reading the shared
    # cache file here makes freshness reflect reality regardless of which
    # worker serves the request.
    if cache_time is None:
        try:
            shared_path = os.path.join(STATE_DIR, '.price_cache_shared.json')
            if os.path.exists(shared_path):
                with open(shared_path, 'r') as _f:
                    _shared = json.load(_f)
                cache_time = datetime.fromisoformat(_shared['ts'])
                if cache_size == 0:
                    cache_size = len(_shared.get('prices', {}))
        except Exception as _e:
            logger.debug('price freshness fallback read failed: %s', _e)
    last_price_update = cache_time.isoformat() if cache_time else None
    price_age_seconds = None
    if cache_time:
        price_age_seconds = round((datetime.now() - cache_time).total_seconds(), 1)
    return {
        'last_price_update': last_price_update,
        'price_age_seconds': price_age_seconds,
        'cache_size': cache_size,
    }


def _engine_is_starting():
    if AGENT_MODE or SHOWCASE_MODE:
        return False
    if _engine_status.get('error'):
        return False
    if _cloud_engine:
        return False
    # Only "starting" if the thread is actually alive; _cloud_engine_started alone
    # is not enough — the thread may have died without setting an error
    return _engine_thread_is_alive()


def _engine_snapshot():
    with _engine_status_lock:
        snapshot = dict(_engine_status)
    snapshot['thread_alive'] = _engine_thread_is_alive()
    snapshot['cycles'] = (
        getattr(_cloud_engine, '_cycles_completed', 0)
        if _cloud_engine else _engine_status['cycles']
    )
    shared = _read_engine_runtime_status()
    if (not snapshot.get('running') or not snapshot.get('thread_alive')) and shared and shared.get('engine_alive'):
        snapshot['running'] = True
        snapshot['thread_alive'] = True
        snapshot['error'] = None
        snapshot['started_at'] = shared.get('started_at') or snapshot.get('started_at')
        snapshot['startup_started_at'] = shared.get('startup_started_at') or snapshot.get('startup_started_at')
        snapshot['cycles'] = max(int(snapshot.get('cycles') or 0), int(shared.get('cycles') or 0))
        snapshot['crash_count'] = max(int(snapshot.get('crash_count') or 0), int(shared.get('crash_count') or 0))
        snapshot['last_crash_at'] = shared.get('last_crash_at') or snapshot.get('last_crash_at')
        snapshot['last_crash_error'] = shared.get('last_crash_error') or snapshot.get('last_crash_error')
        if shared.get('restarts'):
            snapshot['restarts'] = list(shared.get('restarts') or [])
        snapshot['owner_pid'] = shared.get('pid')
        snapshot['heartbeat_at'] = shared.get('heartbeat_at')
        snapshot['heartbeat_age_seconds'] = shared.get('heartbeat_age_seconds')
        snapshot['owner_alive'] = shared.get('owner_alive')
    else:
        snapshot['owner_pid'] = shared.get('pid') if shared else None
        snapshot['heartbeat_at'] = shared.get('heartbeat_at') if shared else None
        snapshot['heartbeat_age_seconds'] = shared.get('heartbeat_age_seconds') if shared else None
        snapshot['owner_alive'] = shared.get('owner_alive') if shared else None
    snapshot['engine_alive'] = _engine_is_operational(snapshot)
    return snapshot


def _coerce_health_timestamp(value):
    if not value:
        return None
    parsed = _parse_health_datetime(value)
    if parsed is not None:
        return parsed.isoformat()
    return str(value)


def _parse_health_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, dtime.min)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            logger.warning('Failed to parse datetime value=%r', value, exc_info=True)
            try:
                return datetime.combine(date.fromisoformat(value), dtime.min)
            except ValueError:
                logger.warning('Failed to parse date value=%r', value, exc_info=True)
                return None
    return None


def _read_health_jsonl_stats(path, timestamp_keys):
    count = 0
    last_timestamp = None
    last_dt = None
    if not os.path.exists(path):
        return count, last_timestamp, last_dt

    try:
        with open(path, 'r', encoding='utf-8') as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                count += 1
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning('Skipping malformed ML health line from %s', path, exc_info=True)
                    continue
                if not isinstance(record, dict):
                    continue
                for key in timestamp_keys:
                    if not record.get(key):
                        continue
                    parsed = _parse_health_datetime(record.get(key))
                    if parsed is not None and (last_dt is None or parsed >= last_dt):
                        last_dt = parsed
                        last_timestamp = parsed.isoformat()
                    break
    except OSError:
        logger.warning('Failed to read ML health file %s', path, exc_info=True)

    return count, last_timestamp, last_dt


def _build_ml_health_snapshot(now=None):
    now = now or datetime.now()
    ml_dir = os.path.join(STATE_DIR, 'ml_learning')
    decisions_path = os.path.join(ml_dir, 'decisions.jsonl')
    outcomes_path = os.path.join(ml_dir, 'outcomes.jsonl')

    decisions_count, last_decision_at, last_decision_dt = _read_health_jsonl_stats(
        decisions_path,
        ('timestamp', 'date'),
    )
    outcomes_count, last_outcome_at, last_outcome_dt = _read_health_jsonl_stats(
        outcomes_path,
        ('timestamp', 'date', 'exit_date', 'entry_date'),
    )

    outcome_completion_rate = (
        round(outcomes_count / decisions_count, 4)
        if decisions_count > 0 else 0.0
    )

    reference_dt = last_outcome_dt or last_decision_dt
    days_without_outcome = None
    if reference_dt is not None:
        days_without_outcome = max(0, (now.date() - reference_dt.date()).days)

    if decisions_count == 0:
        status = 'healthy'
    elif outcome_completion_rate < 0.2 or (
        days_without_outcome is not None and days_without_outcome > 7
    ):
        status = 'degraded'
    elif outcome_completion_rate <= 0.5 or (
        days_without_outcome is not None and days_without_outcome >= 3
    ):
        status = 'warning'
    else:
        status = 'healthy'

    return {
        'decisions_count': decisions_count,
        'outcomes_count': outcomes_count,
        'outcome_completion_rate': outcome_completion_rate,
        'last_decision_at': last_decision_at,
        'last_outcome_at': last_outcome_at,
        'days_without_outcome': days_without_outcome,
        'status': status,
    }


def _health_uptime_seconds(engine, state):
    stats = state.get('stats', {}) if state else {}
    uptime = stats.get('uptime_minutes')
    if uptime is not None:
        return max(0, int(round(float(uptime) * 60)))

    started_at = None
    if engine:
        started_at = engine.get('started_at')
    if not started_at:
        started_at = _engine_status.get('started_at')
    if started_at:
        try:
            started = datetime.fromisoformat(started_at)
            return max(0, int(round((datetime.now() - started).total_seconds())))
        except (TypeError, ValueError):
            logger.warning('Failed to parse engine started_at=%r', started_at, exc_info=True)
            return None
    return None


def _closed_cycle_count_from_log():
    cycle_log_path = os.path.join(STATE_DIR, 'cycle_log.json')
    if not os.path.exists(cycle_log_path):
        return 0
    try:
        with open(cycle_log_path, 'r', encoding='utf-8') as cycle_file:
            cycles = json.load(cycle_file)
        if not isinstance(cycles, list):
            return 0
        return sum(1 for cycle in cycles if isinstance(cycle, dict) and cycle.get('status') == 'closed')
    except Exception as e:
        logger.warning(f"_closed_cycle_count_from_log failed: {e}")
        return 0


def _health_cycle_counts(state, engine):
    stats = state.get('stats', {}) if state else {}
    closed_from_log = _closed_cycle_count_from_log()
    has_engine_iterations = 'engine_iterations' in stats

    cycles_completed = stats.get('cycles_completed')
    if has_engine_iterations:
        cycles_completed = closed_from_log if cycles_completed is None else cycles_completed
    elif closed_from_log > 0:
        cycles_completed = closed_from_log

    engine_iterations = stats.get('engine_iterations')
    if engine_iterations is None:
        engine_iterations = engine.get('cycles', 0) if engine else _engine_status.get('cycles', 0)

    return int(cycles_completed or 0), int(engine_iterations or 0)


def _snap_weekend_to_monday(date_str):
    """If date_str falls on Sat/Sun, return next Monday. Otherwise pass through."""
    if not date_str or not isinstance(date_str, str):
        return date_str
    try:
        d = date.fromisoformat(date_str[:10])
        if d.weekday() >= 5:
            d += timedelta(days=(7 - d.weekday()))
        return d.isoformat()
    except (ValueError, TypeError):
        logger.warning(f"_snap_weekend_to_monday: invalid date_str={date_str!r}")
        return date_str


def _last_cycle_close_timestamp(state):
    if state:
        for key in ('last_cycle_close', 'last_cycle_close_at'):
            if state.get(key):
                return _coerce_health_timestamp(state.get(key))
        stats = state.get('stats', {})
        for key in ('last_cycle_close', 'last_cycle_close_at'):
            if stats.get(key):
                return _coerce_health_timestamp(stats.get(key))

    cycle_log_path = os.path.join(STATE_DIR, 'cycle_log.json')
    if not os.path.exists(cycle_log_path):
        return None

    try:
        with open(cycle_log_path, 'r', encoding='utf-8') as cycle_file:
            cycles = json.load(cycle_file)
    except Exception as e:
        logger.warning(f"_last_cycle_close_timestamp failed: {e}")
        return None

    if not isinstance(cycles, list):
        return None

    for cycle in reversed(cycles):
        if not isinstance(cycle, dict) or cycle.get('status') != 'closed':
            continue
        for key in ('closed_at', 'end_timestamp', 'end_date'):
            if cycle.get(key):
                return _coerce_health_timestamp(cycle.get(key))
    return None


def _build_data_freshness(engine):
    price_freshness = _price_freshness_snapshot()
    engine_alive = _engine_is_operational(engine)
    price_age_seconds = price_freshness['price_age_seconds']

    if not engine_alive:
        status = 'offline'
    elif price_age_seconds is None or price_age_seconds > 300:
        status = 'market_closed' if not _market_is_open() else 'stale'
    else:
        status = 'live'

    return {
        'status': status,
        'price_age_seconds': price_age_seconds,
        'engine_alive': engine_alive,
        'last_price_update': price_freshness['last_price_update'],
    }


def _build_health_payload(engine, state):
    ml_errors = {
        'entry': 0,
        'exit': 0,
        'hold': 0,
        'skip': 0,
        'snapshot': 0,
    }
    if state:
        ml_errors.update(state.get('ml_error_counts', {}))

    portfolio_value = 0.0
    cash = 0.0
    drawdown_pct = None
    num_positions = 0
    if state:
        portfolio_value = float(state.get('portfolio_value', 0.0) or 0.0)
        cash = float(state.get('cash', 0.0) or 0.0)
        peak_value = float(state.get('peak_value', portfolio_value) or portfolio_value or 0.0)
        if peak_value > 0:
            drawdown_pct = round((portfolio_value - peak_value) / peak_value * 100, 2)
        num_positions = len(state.get('positions', {}))

    state_exists = os.path.exists(STATE_FILE)
    state_last_modified = None
    if state_exists:
        try:
            state_last_modified = datetime.fromtimestamp(os.path.getmtime(STATE_FILE)).isoformat()
        except OSError:
            logger.warning('Failed to read state mtime for %s', STATE_FILE, exc_info=True)
            state_last_modified = None

    price_freshness = _price_freshness_snapshot()
    freshness = _build_data_freshness(engine)
    price_age_seconds = freshness['price_age_seconds']
    last_price_update = freshness['last_price_update']
    engine_alive = freshness['engine_alive']
    uptime_seconds = _health_uptime_seconds(engine, state)
    ml_error_total = sum(abs(int(value or 0)) for value in ml_errors.values())
    if engine_alive and price_age_seconds is not None and price_age_seconds <= 300 and ml_error_total == 0:
        overall_status = 'healthy'
    elif not engine_alive and _market_is_open():
        overall_status = 'down'
    else:
        overall_status = 'degraded'

    git_sync_enabled = False  # Always disabled on cloud — state persists via Render disk
    cycles_completed, engine_iterations = _health_cycle_counts(state, engine)
    crash_count = int(engine.get('crash_count') or 0)
    last_crash_at = _coerce_health_timestamp(engine.get('last_crash_at'))
    last_crash_error = engine.get('last_crash_error')
    restarts = list(engine.get('restarts') or [])
    last_cycle_close = _last_cycle_close_timestamp(state)
    owner_pid = engine.get('owner_pid')
    heartbeat_at = _coerce_health_timestamp(engine.get('heartbeat_at'))
    heartbeat_age_seconds = engine.get('heartbeat_age_seconds')
    ml_health = _build_ml_health_snapshot()

    payload = {
        'status': overall_status,
        'timestamp': datetime.now().isoformat(),
        'engine_alive': engine_alive,
        'last_price_update': last_price_update,
        'price_age_seconds': price_age_seconds,
        'last_cycle_close': last_cycle_close,
        'uptime_seconds': uptime_seconds,
        'positions_count': num_positions,
        'portfolio_value': round(portfolio_value, 2),
        'crash_count': crash_count,
        'last_crash_at': last_crash_at,
        'last_crash_error': last_crash_error,
        'restarts': restarts,
        'engine_owner_pid': owner_pid,
        'engine_heartbeat_at': heartbeat_at,
        'engine_heartbeat_age_seconds': heartbeat_age_seconds,
        'ml_health': ml_health,
        'engine_running': engine_alive,
        'price_freshness': price_age_seconds,
        'engine': {
            'running': engine_alive,
            'uptime_minutes': round(uptime_seconds / 60, 2) if uptime_seconds is not None else None,
            'cycles_completed': cycles_completed,
            'engine_iterations': engine_iterations,
            'last_cycle_at': last_cycle_close,
            'ml_errors': ml_errors,
            'crash_count': crash_count,
            'last_crash_at': last_crash_at,
            'last_crash_error': last_crash_error,
            'restarts': restarts,
            'owner_pid': owner_pid,
            'heartbeat_at': heartbeat_at,
            'heartbeat_age_seconds': heartbeat_age_seconds,
        },
        'data_feed': {
            'last_price_update': last_price_update,
            'price_age_seconds': price_age_seconds,
            'consecutive_failures': _get_yf_consecutive_failures(),
            'cache_size': price_freshness['cache_size'],
        },
        'portfolio': {
            'value': round(portfolio_value, 2),
            'num_positions': num_positions,
            'cash': round(cash, 2),
            'drawdown_pct': drawdown_pct,
        },
        'state': {
            'file_exists': state_exists,
            'last_modified': state_last_modified,
            'recovered_from': (
                state.get('_recovered_from') if state else None
            ) or engine.get('state_recovery'),
        },
        'git_sync': {
            'enabled': git_sync_enabled,
            'last_push_at': None,
        },
    }
    if ml_error_total > 0:
        payload['engine']['ml_error_total'] = ml_error_total
    return payload


def _read_engine_lock_owner(lock_file):
    with open(lock_file, 'r', encoding='utf-8') as lock_handle:
        return int(lock_handle.read().strip())


def _engine_lock_owner_is_alive(owner_pid):
    try:
        os.kill(owner_pid, 0)
        return True
    except PermissionError:
        logger.warning('Permission denied probing engine lock owner pid=%s', owner_pid, exc_info=True)
        return True
    except (OSError, ProcessLookupError):
        logger.warning('Engine lock owner pid=%s is not alive', owner_pid, exc_info=True)
        return False


def _claim_engine_lock(lock_file):
    os.makedirs(STATE_DIR, exist_ok=True)
    fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, str(os.getpid()).encode())
    finally:
        os.close(fd)


# ============================================================================
# CLEANUP
# ============================================================================

def _cleanup_data_cache(now=None, cache_dir=None, max_age_days=90):
    now = now or datetime.now()
    cache_dir = cache_dir or DATA_CACHE_DIR
    if not os.path.isdir(cache_dir):
        return []

    cutoff = now - timedelta(days=max_age_days)
    deleted = []
    for pattern in ('*.csv', '*.pkl'):
        for path in glob.glob(os.path.join(cache_dir, pattern)):
            try:
                modified = datetime.fromtimestamp(os.path.getmtime(path))
            except OSError:
                logger.warning('Failed to inspect cache file %s', path, exc_info=True)
                continue
            if modified >= cutoff:
                continue
            try:
                os.unlink(path)
                deleted.append(path)
                logger.info('Deleted stale cache file %s', path)
            except OSError:
                logger.warning('Failed to delete stale cache file %s', path, exc_info=True)
    return deleted


def _trim_log_file(path, max_bytes):
    try:
        size = os.path.getsize(path)
    except OSError:
        logger.warning('Failed to inspect log file size for %s', path, exc_info=True)
        return False

    if size <= max_bytes:
        return False

    try:
        with open(path, 'rb') as handle:
            handle.seek(-max_bytes, os.SEEK_END)
            data = handle.read()
        newline_idx = data.find(b'\n')
        if newline_idx >= 0 and newline_idx + 1 < len(data):
            data = data[newline_idx + 1:]
        tmp_path = path + '.tmp'
        with open(tmp_path, 'wb') as handle:
            handle.write(data)
        os.replace(tmp_path, path)
        logger.info('Trimmed oversized log file %s to %s bytes', path, len(data))
        return True
    except OSError:
        logger.warning('Failed to trim oversized log file %s', path, exc_info=True)
        return False


def _compress_log_file(path):
    gz_path = path + '.gz'
    try:
        modified = os.path.getmtime(path)
        with open(path, 'rb') as src, gzip.open(gz_path, 'wb') as dst:
            shutil.copyfileobj(src, dst)
        os.utime(gz_path, (modified, modified))
        os.unlink(path)
        logger.info('Compressed old log file %s -> %s', path, gz_path)
        return gz_path
    except OSError:
        logger.warning('Failed to compress old log file %s', path, exc_info=True)
        try:
            if os.path.exists(gz_path):
                os.unlink(gz_path)
        except OSError:
            logger.warning('Failed to remove partial compressed log %s', gz_path, exc_info=True)
        return None


def _cleanup_logs(now=None, log_dir=None, compress_after_days=3, delete_after_days=14,
                  max_bytes=50 * 1024 * 1024):
    now = now or datetime.now()
    log_dir = log_dir or LOG_DIR
    if not os.path.isdir(log_dir):
        return {'compressed': [], 'deleted': [], 'trimmed': []}

    compress_cutoff = now - timedelta(days=compress_after_days)
    delete_cutoff = now - timedelta(days=delete_after_days)
    compressed = []
    deleted = []
    trimmed = []

    for path in glob.glob(os.path.join(log_dir, '*.log')):
        try:
            modified = datetime.fromtimestamp(os.path.getmtime(path))
        except OSError:
            logger.warning('Failed to inspect log file %s', path, exc_info=True)
            continue

        if modified < compress_cutoff:
            gz_path = _compress_log_file(path)
            if gz_path:
                compressed.append(gz_path)
            continue

        if _trim_log_file(path, max_bytes):
            trimmed.append(path)

    for path in glob.glob(os.path.join(log_dir, '*.gz')):
        try:
            modified = datetime.fromtimestamp(os.path.getmtime(path))
        except OSError:
            logger.warning('Failed to inspect compressed log %s', path, exc_info=True)
            continue
        if modified >= delete_cutoff:
            continue
        try:
            os.unlink(path)
            deleted.append(path)
            logger.info('Deleted expired compressed log %s', path)
        except OSError:
            logger.warning('Failed to delete expired compressed log %s', path, exc_info=True)

    return {
        'compressed': compressed,
        'deleted': deleted,
        'trimmed': trimmed,
    }


def _cleanup_corrupted_states(now=None, state_dir=None, corrupted_max_age_days=7, keep_backups=3):
    now = now or datetime.now()
    state_dir = state_dir or STATE_DIR
    if not os.path.isdir(state_dir):
        return {'deleted_corrupted': [], 'deleted_backups': []}

    corrupted_cutoff = now - timedelta(days=corrupted_max_age_days)
    deleted_corrupted = []
    deleted_backups = []

    for path in glob.glob(os.path.join(state_dir, 'compass_state_CORRUPTED_*.json')):
        try:
            modified = datetime.fromtimestamp(os.path.getmtime(path))
        except OSError:
            logger.warning('Failed to inspect corrupted state file %s', path, exc_info=True)
            continue
        if modified >= corrupted_cutoff:
            continue
        try:
            os.unlink(path)
            deleted_corrupted.append(path)
            logger.info('Deleted stale corrupted state file %s', path)
        except OSError:
            logger.warning('Failed to delete stale corrupted state file %s', path, exc_info=True)

    backups = []
    for path in glob.glob(os.path.join(state_dir, 'compass_state_*.json')):
        name = os.path.basename(path)
        match = re.fullmatch(r'compass_state_(\d{8})\.json', name)
        if match:
            backups.append((match.group(1), path))

    backups.sort(key=lambda item: item[0], reverse=True)
    for _, path in backups[keep_backups:]:
        try:
            os.unlink(path)
            deleted_backups.append(path)
            logger.info('Deleted old state backup %s', path)
        except OSError:
            logger.warning('Failed to delete old state backup %s', path, exc_info=True)

    return {
        'deleted_corrupted': deleted_corrupted,
        'deleted_backups': deleted_backups,
    }


# ============================================================================
# LOG READER
# ============================================================================

def read_recent_logs(max_lines: int = 50) -> List[dict]:
    """Read recent log entries from today's log file."""
    today_str = datetime.now().strftime('%Y%m%d')
    log_file = os.path.join(LOG_DIR, f'compass_live_{today_str}.log')

    if not os.path.exists(log_file):
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
        log_file = os.path.join(LOG_DIR, f'compass_live_{yesterday}.log')
        if not os.path.exists(log_file):
            files = glob.glob(os.path.join(LOG_DIR, 'compass_live_*.log'))
            if not files:
                return []
            log_file = max(files, key=os.path.getmtime)

    try:
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        noise_patterns = (
            '"GET /', '"POST /', '"PUT /', '"DELETE /',
            'HTTP/1.', 'Running on', 'Press CTRL+C',
            'WARNING: This is a development server',
            'Use a production WSGI server',
            'Restarting with', 'Debugger is',
        )

        entries = []
        for line in lines[-max_lines * 3:]:
            line = line.strip()
            if not line:
                continue

            entry = {'raw': line, 'level': 'INFO', 'message': line, 'timestamp': ''}

            parts = line.split(' - ', 2)
            if len(parts) >= 3:
                entry['timestamp'] = parts[0].strip()
                entry['level'] = parts[1].strip()
                entry['message'] = parts[2].strip()
            elif len(parts) == 2:
                entry['timestamp'] = parts[0].strip()
                entry['message'] = parts[1].strip()

            msg = entry['message']
            if any(pat in line for pat in noise_patterns):
                continue
            if msg.startswith('/api/') or ' 200 ' in msg or ' 304 ' in msg:
                continue

            entries.append(entry)

        return entries[-max_lines:]
    except Exception as e:
        logger.warning(f"read_recent_logs failed: {e}")
        return []


# ============================================================================
# DERIVED CALCULATIONS
# ============================================================================

def compute_position_details(state: dict, prices: Dict[str, float] = None, prev_closes: Dict[str, float] = None) -> List[dict]:
    """Compute enriched position data for display."""
    positions = state.get('positions', {})
    position_meta = state.get('position_meta', {})
    trading_day = state.get('trading_day_counter', 0)
    prices = prices or {}
    prev_closes = prev_closes or {}

    results = []
    for symbol, pos_data in positions.items():
        meta = position_meta.get(symbol, {})
        entry_price = meta.get('entry_price', pos_data.get('avg_cost', 0))
        high_price = meta.get('high_price', entry_price)
        entry_day_index = meta.get('entry_day_index', 0)
        entry_date = _snap_weekend_to_monday(meta.get('entry_date', ''))
        shares = pos_data.get('shares', 0)
        current_price = prices.get(symbol, entry_price)

        # If position was opened today AND market hasn't opened yet,
        # use entry_price to avoid phantom PnL from after-hours prices.
        # During market hours, show real live prices.
        if entry_date:
            try:
                ET = ZoneInfo('America/New_York')
                now_et = datetime.now(ET)
                today_et = now_et.date()
                market_open = (now_et.weekday() < 5 and now_et.time() >= dtime(9, 30))
                if date.fromisoformat(entry_date) == today_et and not market_open:
                    current_price = entry_price
            except Exception as e:
                logger.warning(f"compute_position_details failed: {e}")

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
            except Exception as e:
                logger.warning(f"compute_position_details failed: {e}")
                days_held = trading_day - entry_day_index
        else:
            days_held = trading_day - entry_day_index
        days_remaining = max(0, HYDRA_CONFIG['HOLD_DAYS'] - days_held)

        # v8.4: Adaptive trailing stop (vol-scaled)
        trailing_active = high_price > entry_price * (1 + HYDRA_CONFIG['TRAILING_ACTIVATION'])
        if trailing_active:
            entry_vol = meta.get('entry_vol', HYDRA_CONFIG.get('TRAILING_VOL_BASELINE', 0.25))
            vol_ratio = entry_vol / HYDRA_CONFIG.get('TRAILING_VOL_BASELINE', 0.25)
            scaled_trailing = HYDRA_CONFIG['TRAILING_STOP_PCT'] * vol_ratio
            trailing_stop_level = high_price * (1 - scaled_trailing)
        else:
            trailing_stop_level = None

        # v8.4: Adaptive position stop (vol-scaled)
        entry_daily_vol = meta.get('entry_daily_vol')
        if entry_daily_vol is not None:
            raw_stop = -HYDRA_CONFIG['STOP_DAILY_VOL_MULT'] * entry_daily_vol
            adaptive_stop = max(HYDRA_CONFIG['STOP_CEILING'], min(HYDRA_CONFIG['STOP_FLOOR'], raw_stop))
        else:
            adaptive_stop = HYDRA_CONFIG['STOP_FLOOR']  # fallback to floor
        position_stop_level = entry_price * (1 + adaptive_stop)

        sector = meta.get('sector', 'Unknown')

        # Classify strategy from hydra sub-system data when position_meta is missing
        strategy = meta.get('strategy', '')
        if not strategy:
            hydra_state = state.get('hydra', {})
            cat_syms = {cp['symbol']: cp.get('sub_strategy', 'trend')
                        for cp in hydra_state.get('catalyst_positions', [])}
            efa_pos = hydra_state.get('efa_position')
            efa_sym = efa_pos.get('symbol') if isinstance(efa_pos, dict) else None
            rattle_syms = {rp.get('symbol') for rp in hydra_state.get('rattle_positions', [])}

            if symbol in cat_syms:
                strategy = 'catalyst'
                sub = cat_syms[symbol]
                sector = f'Catalyst ({sub})' if sector == 'Unknown' else sector
            elif symbol == 'EFA' or symbol == efa_sym:
                strategy = 'efa'
                sector = 'International Equity' if sector == 'Unknown' else sector
            elif symbol in rattle_syms:
                strategy = 'rattlesnake'
            else:
                strategy = 'momentum'

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
            'strategy': strategy,
            'prev_close': prev_closes.get(symbol),
        })

    results.sort(key=lambda x: x['pnl_pct'], reverse=True)
    return results


def _get_previous_day_portfolio_value() -> Optional[float]:
    """Read the most recent PRIOR-day state file for yesterday's portfolio value.
    Used as fallback when portfolio_values_history is empty (e.g. after cloud restart)."""
    try:
        today_str = date.today().strftime('%Y%m%d')
        pattern = os.path.join(STATE_DIR, 'compass_state_2*.json')
        state_files = sorted(
            (f for f in glob.glob(pattern)
             if 'pre_rotation' not in f and 'latest' not in f),
            reverse=True
        )
        for sf in state_files:
            basename = os.path.basename(sf)
            # Extract date from filename: compass_state_YYYYMMDD.json
            file_date = basename.replace('compass_state_', '').replace('.json', '')
            if file_date >= today_str:
                continue  # Skip today's file, we want yesterday's
            with open(sf, 'r') as f:
                s = json.load(f)
            val = s.get('portfolio_value')
            if val and val > 0:
                return float(val)
        return None
    except Exception as e:
        logger.warning("_get_previous_day_portfolio_value failed: %s", e, exc_info=True)
        return None


def get_spy_start_price() -> Optional[float]:
    """Get SPY price at live test start. Tries cycle_log first cycle,
    then falls back to current ^GSPC price (for fresh start / reset)."""
    global _spy_start_price
    if _spy_start_price is not None:
        return _spy_start_price

    # Try cycle_log first
    log_file = os.path.join(STATE_DIR, 'cycle_log.json')
    if os.path.exists(log_file):
        try:
            with open(log_file, 'r') as f:
                cycles = json.load(f)
            if cycles:
                first_spy = cycles[0].get('spy_start')
                if first_spy and first_spy > 0:
                    _spy_start_price = float(first_spy)
                    return _spy_start_price
        except Exception as e:
            logger.warning("get_spy_start_price cycle_log failed: %s", e, exc_info=True)

    # Fallback: use prev_close as baseline — but do NOT cache it, because
    # prev_close changes daily and would freeze spy_cumulative == spy_daily
    try:
        batch = _yf_fetch_batch(['^GSPC'])
        gspc = batch.get('^GSPC', {})
        price = gspc.get('prev_close') or gspc.get('price')
        if price and price > 0:
            logger.info("SPY start price fallback (uncached) from prev_close: %.2f", price)
            return float(price)
    except Exception as e:
        logger.warning("get_spy_start_price live fallback failed: %s", e, exc_info=True)

    return None


def _atomic_write_json(path, payload):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f'.{os.path.basename(path)}.',
        suffix='.tmp',
        dir=os.path.dirname(path) or '.',
    )
    replaced = False
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as tmp_file:
            json.dump(payload, tmp_file, indent=2)
        os.replace(tmp_path, path)
        replaced = True
    finally:
        if not replaced and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                logger.warning('Failed to delete temporary file %s', tmp_path, exc_info=True)


def _validate_recovered_state(state, source):
    if not isinstance(state, dict):
        logger.error('Recovered state from %s is not a JSON object', source)
        return None
    if not isinstance(state.get('positions'), dict):
        logger.error('Recovered state from %s is missing a valid positions map', source)
        return None
    cash = state.get('cash')
    if (not isinstance(cash, (int, float)) or isinstance(cash, bool)
            or not math.isfinite(float(cash))):
        logger.error('Recovered state from %s is missing numeric cash', source)
        return None
    portfolio_value = state.get('portfolio_value')
    if (not isinstance(portfolio_value, (int, float)) or isinstance(portfolio_value, bool)
            or not math.isfinite(float(portfolio_value))):
        logger.error('Recovered state from %s is missing finite portfolio_value', source)
        return None
    peak_value = state.get('peak_value')
    if (not isinstance(peak_value, (int, float)) or isinstance(peak_value, bool)
            or not math.isfinite(float(peak_value))):
        logger.error('Recovered state from %s is missing finite peak_value', source)
        return None
    trading_day_counter = state.get('trading_day_counter')
    if (not isinstance(trading_day_counter, int) or isinstance(trading_day_counter, bool)
            or trading_day_counter < 0):
        logger.error('Recovered state from %s is missing integer trading_day_counter', source)
        return None
    return state


def _prepare_recovered_state(state, source):
    recovered = dict(state)
    recovered['_recovered_from'] = source
    recovered['_recovered_at'] = datetime.now().isoformat()
    return recovered


def _build_default_state():
    initial_cash = HYDRA_CONFIG['INITIAL_CAPITAL']
    return {
        'portfolio_value': initial_cash,
        'peak_value': initial_cash,
        'cash': initial_cash,
        'positions': {},
        'position_meta': {},
        'current_universe': [],
        'universe_year': None,
        'current_regime_score': 0.5,
        'current_regime': False,
        'regime_consecutive': 0,
        'trading_day_counter': 0,
        'last_trading_date': None,
        'stop_events': [],
        'timestamp': datetime.now().isoformat(),
        'stats': {},
        'portfolio_values_history': [],
        'hydra': {
            'rattle_positions': [],
            'catalyst_positions': [],
        },
        'dd_leverage': 1.0,
        'crash_cooldown': 0,
    }


def _fetch_state_from_github():
    if not _HAS_REQUESTS:
        logger.warning('Cloud state recovery fallback unavailable: requests is not installed')
        return None
    try:
        response = http_requests.get(GITHUB_STATE_URL, timeout=15)
        if response.status_code != 200:
            logger.warning('GitHub state fallback returned HTTP %s', response.status_code)
            return None
        return response.json()
    except Exception as e:
        logger.warning('GitHub state fallback failed: %s', e, exc_info=True)
        return None


def _recover_cloud_state(git_pull_result=None):
    local_state = read_state()
    if local_state:
        source = local_state.get('_recovered_from') or 'git_pull'
        if _validate_recovered_state(local_state, source):
            recovered = _prepare_recovered_state(local_state, source)
            # Only rewrite if we actually tagged it (avoid unnecessary state file churn)
            if local_state.get('_recovered_from') != recovered.get('_recovered_from'):
                _atomic_write_json(STATE_FILE, recovered)
            logger.info('Cloud state recovery ready from %s', recovered['_recovered_from'])
            return recovered
        logger.error('State file present but failed validation, attempting fallback recovery')

    github_state = _fetch_state_from_github()
    if github_state and _validate_recovered_state(github_state, 'github_api'):
        recovered = _prepare_recovered_state(github_state, 'github_api')
        _atomic_write_json(STATE_FILE, recovered)
        logger.info('Cloud state recovered from GitHub fallback')
        return recovered

    recovered = _prepare_recovered_state(_build_default_state(), 'default')
    _atomic_write_json(STATE_FILE, recovered)
    if git_pull_result and not git_pull_result.get('ok'):
        logger.error(
            'Cloud state recovery fell back to default state after git pull failure: %s',
            git_pull_result.get('message'),
        )
    else:
        logger.warning('Cloud state recovery fell back to default state')
    return recovered


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
    except Exception as e:
        logger.warning(f"_compute_real_trading_day failed: {e}")
        return saved_day


def compute_portfolio_metrics(state: dict, prices: Dict[str, float] = None) -> dict:
    """Compute portfolio-level dashboard metrics."""
    portfolio_value = state.get('portfolio_value', 0)
    peak_value = state.get('peak_value', 0)
    cash = state.get('cash', 0)
    initial_capital = HYDRA_CONFIG['INITIAL_CAPITAL']
    prices = prices or {}

    # Recompute invested value with live prices if available
    invested = 0
    positions = state.get('positions', {})
    position_meta = state.get('position_meta', {})
    today_et = datetime.now(ZoneInfo('America/New_York')).date()
    for sym, pos in positions.items():
        meta = position_meta.get(sym, {})
        entry_date = _snap_weekend_to_monday(meta.get('entry_date', ''))
        entry_price = meta.get('entry_price', pos.get('avg_cost', 0))
        # Use entry_price on entry day only before market open (pre-market)
        # During market hours, use live prices even on entry day
        if entry_date:
            try:
                ET = ZoneInfo('America/New_York')
                now_et = datetime.now(ET)
                market_open = (now_et.weekday() < 5 and now_et.time() >= dtime(9, 30))
                if date.fromisoformat(entry_date) == today_et and not market_open:
                    price = entry_price
                else:
                    price = prices.get(sym, entry_price)
            except Exception as e:
                logger.warning(f"compute_portfolio_metrics failed: {e}")
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
    if dd_leverage < HYDRA_CONFIG['LEV_FULL'] or crash_cooldown > 0:
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
    leverage = dd_leverage if dd_leverage < HYDRA_CONFIG['LEV_FULL'] else None

    # v8.4: Positions from regime score (thresholds match local dashboard)
    if regime_score >= 0.65:
        max_pos = HYDRA_CONFIG['NUM_POSITIONS']
    elif regime_score >= 0.50:
        max_pos = HYDRA_CONFIG['NUM_POSITIONS'] - 1
    elif regime_score >= 0.35:
        max_pos = HYDRA_CONFIG['NUM_POSITIONS'] - 2
    else:
        max_pos = HYDRA_CONFIG['NUM_POSITIONS_RISK_OFF']

    # S&P 500 daily return (today's change from previous close)
    # When market hasn't opened yet (weekend or pre-market), force 0%
    # because Yahoo returns Friday's close vs Thursday's previousClose
    ET = ZoneInfo('America/New_York')
    now_et = datetime.now(ET)
    market_has_opened_today = (now_et.weekday() < 5 and now_et.time() >= dtime(9, 30))
    spy_current = prices.get('^GSPC') if prices else None
    spy_prev = _prev_close_cache.get('^GSPC')
    # Fallback: if prev_close missing, fetch ^GSPC directly
    if not spy_prev and spy_current:
        batch = _yf_fetch_batch(['^GSPC'])
        gspc_quote = batch.get('^GSPC')
        if gspc_quote and 'prev_close' in gspc_quote:
            spy_prev = gspc_quote['prev_close']
            _prev_close_cache['^GSPC'] = spy_prev
    if not market_has_opened_today:
        spy_daily = 0.0
    elif spy_current and spy_prev and spy_prev > 0:
        spy_daily = round((spy_current - spy_prev) / spy_prev * 100, 2)
    else:
        spy_daily = None

    # S&P 500 cumulative return (since live test start)
    spy_start = get_spy_start_price()
    if spy_current and spy_start and spy_start > 0:
        spy_cumulative = round((spy_current - spy_start) / spy_start * 100, 2)
    else:
        spy_cumulative = None

    # HYDRA cumulative return (since live test start)
    cumulative_return = round(total_return * 100, 2)

    # Trading days elapsed (used for display)
    live_start = date.fromisoformat(LIVE_TEST_START_DATE)
    live_days = sum(1 for d in range((date.today() - live_start).days + 1)
                    if (live_start + timedelta(days=d)).weekday() < 5)

    # HYDRA daily return: reconstruct yesterday's portfolio from prev_closes
    # (robust to cloud restarts — does not depend on portfolio_values_history)
    # Gate with market_has_opened_today to match SPY — avoids showing stale
    # Friday return on weekends and prevents worker cache divergence from
    # causing visible oscillation between live and prev_close values.
    if not market_has_opened_today:
        daily_return = 0.0
    else:
        prev_close_portfolio = cash
        for sym, pos in positions.items():
            pc = _prev_close_cache.get(sym)
            if pc and pc > 0:
                prev_close_portfolio += pos.get('shares', 0) * pc
            else:
                meta_ep = position_meta.get(sym, {}).get('entry_price', pos.get('avg_cost', 0))
                prev_close_portfolio += pos.get('shares', 0) * meta_ep
        if prev_close_portfolio > 0 and portfolio_value > 0:
            daily_return = round((portfolio_value - prev_close_portfolio) / prev_close_portfolio * 100, 2)
        else:
            daily_return = 0.0

    # Don't show SPY benchmark until HYDRA has actual positions
    if not positions:
        spy_cumulative = None
        spy_daily = None

    return {
        'portfolio_value': round(portfolio_value, 2),
        'cash': round(cash, 2),
        'invested': round(invested, 2),
        'peak_value': round(peak_value, 2),
        'drawdown': round(drawdown * 100, 2),
        'total_return': cumulative_return,
        'spy_daily_return': spy_daily,
        'spy_cumulative': spy_cumulative,
        'daily_return': daily_return,
        'initial_capital': initial_capital,
        'num_positions': len(positions),
        'max_positions': max_pos,
        'regime': regime_str,
        'regime_consecutive': state.get('regime_consecutive', 0),
        'in_protection': dd_leverage < HYDRA_CONFIG['LEV_FULL'],
        'regime_score': round(regime_score, 3),
        'dd_leverage': round(dd_leverage, 3) if dd_leverage is not None else None,
        'leverage': leverage,
        'recovery': recovery,
        'trading_day': live_days,
        'last_trading_date': state.get('last_trading_date'),
        'stop_events': state.get('stop_events', []),
        'timestamp': state.get('timestamp', ''),
        'uptime_minutes': state.get('stats', {}).get('uptime_minutes', 0),
    }


def _fetch_risk_histories(symbols):
    if not _HAS_YFINANCE or not symbols:
        return {}

    unique_symbols = sorted({symbol for symbol in symbols if symbol})
    if not unique_symbols:
        return {}

    try:
        history = yf.download(
            unique_symbols,
            period='3mo',
            progress=False,
            auto_adjust=False,
            group_by='ticker',
            threads=False,
        )
    except Exception as e:
        logger.warning(f"Risk history download failed: {e}")
        return {}

    if history is None or len(history) == 0:
        return {}

    result = {}
    if isinstance(history.columns, pd.MultiIndex):
        level_zero = set(history.columns.get_level_values(0))
        for symbol in unique_symbols:
            if symbol not in level_zero:
                continue
            df = history[symbol].dropna(how='all')
            if len(df) > 1:
                result[symbol] = df
    elif len(unique_symbols) == 1:
        result[unique_symbols[0]] = history.dropna(how='all')
    return result


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

    # --- VIX + Rattlesnake regime (cached 60s to avoid uncached yf calls per request) ---
    global _hydra_regime_cache, _hydra_regime_cache_time
    vix_current = prices.get('^VIX')
    rattle_regime = 'RISK_ON'

    with _hydra_regime_lock:
        now = datetime.now()
        if (_hydra_regime_cache_time and
                (now - _hydra_regime_cache_time).total_seconds() < HYDRA_REGIME_CACHE_SECONDS):
            vix_current = _hydra_regime_cache.get('vix', vix_current)
            rattle_regime = _hydra_regime_cache.get('regime', rattle_regime)
        else:
            if not vix_current:
                try:
                    vix_hist = yf.Ticker('^VIX').history(period='5d')
                    if len(vix_hist) > 0:
                        vix_current = float(vix_hist['Close'].iloc[-1])
                except Exception as e:
                    logger.warning(f"compute_hydra_data VIX fetch failed: {e}")
            try:
                spy_hist = yf.Ticker('SPY').history(period='1y')
                if len(spy_hist) >= 200:
                    spy_close = float(spy_hist['Close'].iloc[-1])
                    spy_sma200 = float(spy_hist['Close'].iloc[-200:].mean())
                    if spy_close < spy_sma200:
                        rattle_regime = 'RISK_OFF'
            except Exception as e:
                logger.warning(f"compute_hydra_data SPY regime fetch failed: {e}")
            _hydra_regime_cache = {'vix': vix_current, 'regime': rattle_regime}
            _hydra_regime_cache_time = now

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

    # --- Catalyst positions from state ---
    catalyst_positions_raw = hydra_state.get('catalyst_positions', [])
    catalyst_positions = []
    for cp in catalyst_positions_raw:
        symbol = cp.get('symbol', '')
        entry_price = cp.get('entry_price', 0)
        current_price = prices.get(symbol, entry_price)
        pnl_pct = (current_price / entry_price - 1.0) if entry_price > 0 else 0
        catalyst_positions.append({
            'symbol': symbol,
            'entry_price': round(entry_price, 2),
            'current_price': round(current_price, 2),
            'pnl_pct': round(pnl_pct, 4),
            'shares': cp.get('shares', 0),
            'sub_strategy': cp.get('sub_strategy', 'trend'),
        })

    # --- Capital allocation (cash recycling) ---
    portfolio_value = state.get('portfolio_value', HYDRA_CONFIG['INITIAL_CAPITAL'])
    cap_state = hydra_state.get('capital_manager')
    if cap_state:
        hydra_account = cap_state.get('compass_account', portfolio_value * R_BASE_HYDRA_ALLOC)
        rattle_account = cap_state.get('rattle_account', portfolio_value * R_BASE_RATTLE_ALLOC)
        catalyst_account = cap_state.get('catalyst_account', 0)
    else:
        hydra_account = portfolio_value * R_BASE_HYDRA_ALLOC
        rattle_account = portfolio_value * R_BASE_RATTLE_ALLOC
        catalyst_account = portfolio_value * 0.15

    # EFA passive pillar
    efa_value = 0.0
    efa_position = hydra_state.get('efa_position')
    if efa_position and efa_position.get('shares', 0) > 0:
        efa_value = efa_position.get('current_value', 0)
    if cap_state:
        efa_value = max(efa_value, cap_state.get('efa_value', 0))

    total = hydra_account + rattle_account + catalyst_account + efa_value
    if total <= 0:
        total = portfolio_value or HYDRA_CONFIG['INITIAL_CAPITAL']
        hydra_account = total * R_BASE_HYDRA_ALLOC
        rattle_account = total * R_BASE_RATTLE_ALLOC

    # Cash recycling: idle Rattlesnake cash flows to HYDRA (capped at 75%)
    rattle_invested = sum(
        rp.get('shares', 0) * prices.get(rp.get('symbol', ''), rp.get('entry_price', 0))
        for rp in rattle_positions_raw
    )
    rattle_exposure = rattle_invested / rattle_account if rattle_account > 0 else 0
    r_idle = rattle_account * (1.0 - rattle_exposure)
    max_recycle = max(0, total * R_MAX_HYDRA_ALLOC - hydra_account)
    recycled = min(r_idle, max_recycle)
    c_effective = hydra_account + recycled
    r_effective = rattle_account - recycled

    return {
        'available': True,
        'rattle_positions': rattle_positions,
        'catalyst_positions': catalyst_positions,
        'rattle_regime': rattle_regime,
        'vix_current': round(vix_current, 2) if vix_current else None,
        'vix_panic': vix_panic,
        'efa_position': {
            'shares': efa_position.get('shares', 0) if efa_position else 0,
            'value': round(efa_value, 2),
            'avg_cost': round(efa_position.get('avg_cost', 0), 2) if efa_position else 0,
        } if efa_position and efa_position.get('shares', 0) > 0 else None,
        'capital': {
            'hydra_account': round(c_effective, 2),
            'rattle_account': round(r_effective, 2),
            'catalyst_account': round(catalyst_account, 2),
            'efa_value': round(efa_value, 2),
            'hydra_pct': round(c_effective / total, 4) if total > 0 else 0.425,
            'rattle_pct': round(r_effective / total, 4) if total > 0 else 0.425,
            'catalyst_pct': round(catalyst_account / total, 4) if total > 0 else 0.15,
            'efa_pct': round(efa_value / total, 4) if total > 0 else 0,
            'recycled_pct': round(recycled / total, 4) if total > 0 else 0,
        },
    }




# ============================================================================
# ANALYTICS CACHES (lazy-import, compute once, cache forever until restart)
# ============================================================================

_montecarlo_cache = None
_montecarlo_cache_signature = None
_trade_analytics_cache = None
_trade_analytics_lock = threading.Lock()


def _montecarlo_signature():
    cycle_log_path = os.path.join('state', 'cycle_log.json')
    backtest_path = os.path.join('backtests', 'hydra_clean_daily.csv')
    signature = []
    for path in (cycle_log_path, backtest_path):
        if os.path.exists(path):
            signature.append(os.path.getmtime(path))
        else:
            signature.append(None)
    return tuple(signature)


# ============================================================================
# FLASK ROUTES
# ============================================================================

@app.route('/')
def index():
    return render_template('dashboard.html')


def _stabilize_portfolio_metrics(portfolio: dict) -> dict:
    """Reject portfolio metrics that swing wildly between refreshes.

    If SPY daily return flips sign AND the swing is >1pp within 2 minutes,
    keep the last-known-good metrics.  This catches stale Yahoo data that
    slipped past the per-symbol guards in _yf_fetch_batch.
    """
    global _last_good_portfolio, _last_good_portfolio_time

    spy_daily = portfolio.get('spy_daily_return')
    pv = portfolio.get('portfolio_value')
    now = datetime.now()

    with _portfolio_metrics_lock:
        if _last_good_portfolio is not None and _last_good_portfolio_time is not None:
            age = (now - _last_good_portfolio_time).total_seconds()
            old_spy = _last_good_portfolio.get('spy_daily_return')
            old_pv = _last_good_portfolio.get('portfolio_value')

            # Detect impossible swing: SPY flips sign by >1pp within 2 min
            if (age < 120 and spy_daily is not None and old_spy is not None
                    and old_spy * spy_daily < 0  # sign flip
                    and abs(spy_daily - old_spy) > 1.0):
                logger.warning(
                    'Portfolio stabilizer: SPY daily flipped %.2f→%.2f in %.0fs, '
                    'rejecting stale data (pv %.2f→%.2f)',
                    old_spy, spy_daily, age, old_pv or 0, pv or 0,
                )
                return dict(_last_good_portfolio)

        # Accept this as the new good baseline
        _last_good_portfolio = dict(portfolio)
        _last_good_portfolio_time = now
    return portfolio


@app.route('/api/state')
def api_state():
    """Return enriched state data with live prices."""
    try:
        state = read_state()
        engine = _engine_snapshot()
        freshness = _build_data_freshness(engine)

        if not state:
            if _engine_is_starting():
                return jsonify({
                    'status': 'starting',
                    'message': 'Engine initializing...',
                    'positions': {},
                    'cash': 0.0,
                    'portfolio_value': 0.0,
                    'regime_score': None,
                    'trading_day_counter': 0,
                    '_data_freshness': freshness,
                    'price_data_age_seconds': freshness['price_age_seconds'],
                    'server_time': datetime.now().isoformat(),
                    'engine': engine,
                })
            return jsonify({
                'status': 'offline',
                'error': engine.get('error') or 'No state file found',
                'positions': {},
                'cash': 0.0,
                'portfolio_value': 0.0,
                'regime_score': None,
                'trading_day_counter': 0,
                '_data_freshness': freshness,
                'price_data_age_seconds': freshness['price_age_seconds'],
                'server_time': datetime.now().isoformat(),
                'engine': engine,
            })

        # Fetch live prices for positions + SPY + ES Futures + VIX + Rattlesnake + Catalyst held
        rattle_syms = [p.get('symbol') for p in state.get('hydra', {}).get('rattle_positions', []) if p.get('symbol')]
        catalyst_syms = [p.get('symbol') for p in state.get('hydra', {}).get('catalyst_positions', []) if p.get('symbol')]
        symbols = ['SPY', '^GSPC', 'ES=F', '^VIX', 'EFA', 'TLT', 'GLD', 'DBC'] + list(state.get('positions', {}).keys()) + rattle_syms + catalyst_syms
        symbols = list(set(symbols))
        prices = fetch_live_prices(symbols)

        position_details = compute_position_details(state, prices, _prev_close_cache)
        portfolio = compute_portfolio_metrics(state, prices)

        # Consistency guard: reject portfolio metrics that swing wildly between
        # refreshes — this catches stale Yahoo prices that slipped past other guards.
        portfolio = _stabilize_portfolio_metrics(portfolio)

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
            'positions': state.get('positions', {}),
            'cash': float(portfolio.get('cash', state.get('cash', 0.0) or 0.0)),
            'portfolio_value': float(
                portfolio.get('portfolio_value', state.get('portfolio_value', 0.0) or 0.0)
            ),
            'regime_score': state.get('current_regime_score'),
            'trading_day_counter': int(state.get('trading_day_counter', 0) or 0),
            'portfolio': portfolio,
            'position_details': position_details,
            'prices': prices,
            'prev_closes': dict(_prev_close_cache),
            'universe': state.get('current_universe', []),
            'universe_year': state.get('universe_year'),
            'config': {},  # Algorithm parameters are confidential
            'chassis': {},
            'preclose': preclose_status,
            'hydra': hydra_data,
            'implementation_shortfall': {'available': False},
            'state_recovery': state.get('_recovered_from'),
            '_data_freshness': freshness,
            'price_data_age_seconds': freshness['price_age_seconds'],
            'server_time': datetime.now().isoformat(),
            'engine': {
                **engine,
                'state_recovery': state.get('_recovered_from') or engine.get('state_recovery'),
            },
        })
    except Exception as e:
        import traceback
        freshness = _build_data_freshness(_engine_snapshot())
        logger.error(f"/api/state crashed: {e}", exc_info=True)
        return jsonify({
            'status': 'offline',
            'error': f'Worker {os.getpid()} crashed: {type(e).__name__}: {e}',
            'traceback': traceback.format_exc(),
            '_data_freshness': freshness,
            'price_data_age_seconds': freshness['price_age_seconds'],
            'server_time': datetime.now().isoformat(),
            'engine': _engine_snapshot(),
        }), 200  # Return 200 so frontend can display the error




@app.route('/api/cycle-log')
def api_cycle_log():
    """Return the 5-day cycle performance log (HYDRA vs SPY).

    Active cycles are enriched with live prices so the dashboard
    shows real-time HYDRA return, SPY return, and alpha.
    """
    log_file = os.path.join(STATE_DIR, 'cycle_log.json')
    if not os.path.exists(log_file):
        return jsonify([])
    try:
        with open(log_file, 'r') as f:
            cycles = json.load(f)
    except Exception as e:
        logger.warning(f"api_cycle_log failed: {e}")
        return jsonify([])

    # Enrich active cycles with live metrics
    for c in cycles:
        c.setdefault('cycle_number', c.get('cycle'))
        c.setdefault('cycle_return_pct', None)
        c.setdefault('start_date', None)
        c.setdefault('end_date', None)
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
                c['hydra_return'] = 0.0
                c['spy_return'] = 0.0
                c['alpha'] = 0.0
                c['portfolio_end'] = c.get('portfolio_start')
                c['spy_end'] = c.get('spy_start')
                continue

            # Current holdings from state
            positions = state.get('positions', {})
            position_meta = state.get('position_meta', {})
            symbols = list(positions.keys()) + ['^GSPC']
            prices = fetch_live_prices(symbols)

            # Sync positions_current with actual state holdings
            c['positions_current'] = sorted(positions.keys())

            # Holdings-only return: compare stock picks vs SPY (no cash dilution)
            invested_now = 0
            invested_at_cost = 0
            for sym, pos in positions.items():
                shares = pos.get('shares', 0)
                meta = position_meta.get(sym, {})
                entry_price = meta.get('entry_price', pos.get('avg_cost', 0))
                price = prices.get(sym)
                if not price:
                    price = entry_price
                invested_now += shares * price
                invested_at_cost += shares * entry_price

            if invested_at_cost > 0:
                c['hydra_return'] = round((invested_now / invested_at_cost - 1) * 100, 2)

            # S&P 500 index return over same period (spy_start is ^GSPC, not SPY ETF)
            spy_price = prices.get('^GSPC')
            spy_start = c.get('spy_start')
            if spy_price and spy_start and spy_start > 0:
                c['spy_end'] = round(spy_price, 2)
                c['spy_return'] = round((spy_price / spy_start - 1) * 100, 2)

            # Alpha: holdings return vs SPY
            if c.get('hydra_return') is not None and c.get('spy_return') is not None:
                c['alpha'] = round(c['hydra_return'] - c['spy_return'], 2)
        except Exception as e:
            logger.warning(f"api_cycle_log failed: {e}")

    return jsonify(cycles)


@app.route('/api/live-chart')
def api_live_chart():
    """Return daily HYDRA vs S&P 500 indexed performance since live test start.

    Reads historical state files for HYDRA portfolio values and
    fetches SPY data from yfinance. Both series are indexed
    to 100 on the start date for easy visual comparison.
    """
    # 1. Read HYDRA daily values — baseline file first, then state files overlay
    #    The baseline contains pre-computed history that survives Render deploys.
    #    State files from the running engine overlay (and may update) recent dates.
    first_value = HYDRA_CONFIG['INITIAL_CAPITAL']
    hydra_data = {}  # date_str -> portfolio_value

    baseline_path = os.path.join(STATE_DIR, 'live_chart_baseline.json')
    if os.path.exists(baseline_path):
        try:
            with open(baseline_path, 'r') as f:
                bl = json.load(f)
            for dt, val in zip(bl.get('dates', []), bl.get('values', [])):
                hydra_data[dt] = val
        except Exception as e:
            logger.warning(f"api_live_chart baseline read failed: {e}")

    pattern = os.path.join(STATE_DIR, 'compass_state_2*.json')
    state_files = sorted(f for f in glob.glob(pattern)
                         if 'pre_rotation' not in f and 'latest' not in f)

    if not state_files and not hydra_data:
        return jsonify({'dates': [], 'hydra': [], 'spy': []})

    # State files overlay: only EXTEND the baseline forward. Baseline is
    # authoritative for any date it already covers (it contains curated
    # mark-to-market history). State files can only add dates strictly
    # newer than the latest baseline date — this prevents the live engine
    # from clobbering historical entries with stale post-restart values.
    baseline_max_date = max(hydra_data.keys()) if hydra_data else ''
    for sf in state_files:
        try:
            with open(sf, 'r') as f:
                s = json.load(f)
            dt = s.get('last_trading_date')
            val = s.get('portfolio_value')
            n_pos = len(s.get('positions', {}))
            # Skip reset/corrupt state files (0 positions with ~$100K = engine restart)
            if dt and val and val > 0 and n_pos > 0 and dt > baseline_max_date:
                hydra_data[dt] = val
        except Exception as e:
            logger.warning(f"api_live_chart failed: {e}")
            continue

    if not hydra_data:
        return jsonify({'dates': [], 'hydra': [], 'spy': []})

    # Filter: only live test dates, weekdays only, no reset states
    def _is_valid_chart_date(dt_str):
        if dt_str < LIVE_TEST_START_DATE:
            return False
        try:
            d = date.fromisoformat(dt_str)
            return d.weekday() < 5  # skip weekends
        except ValueError as e:
            logger.warning('Invalid chart date %s: %s', dt_str, e)
            return False

    data_dates = sorted(d for d in hydra_data.keys() if _is_valid_chart_date(d))
    if not data_dates:
        return jsonify({'dates': [], 'hydra': [], 'spy': []})

    # Ensure Day 1 = initial capital (positions entered at close, no P&L yet)
    hydra_data[LIVE_TEST_START_DATE] = first_value

    # Build complete weekday timeline from start to last date, filling gaps
    # with carry-forward values and marking update periods.
    last_date = date.fromisoformat(data_dates[-1])
    dates = []
    update_days = []  # indices of days with no data (algorithm updates)
    d = date.fromisoformat(LIVE_TEST_START_DATE)
    last_known_val = first_value
    while d <= last_date:
        if d.weekday() < 5:  # weekday
            dt_str = d.isoformat()
            dates.append(dt_str)
            if dt_str in hydra_data:
                last_known_val = hydra_data[dt_str]
            else:
                # Gap: carry forward last known value, mark as update
                hydra_data[dt_str] = last_known_val
                update_days.append(len(dates) - 1)
        d += timedelta(days=1)

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
                except Exception as e:
                    logger.warning(f"api_live_chart failed: {e}")
                    continue
            if hist is not None and len(hist) > 0:
                # Flatten multi-level columns (yfinance returns MultiIndex)
                if isinstance(hist.columns, pd.MultiIndex):
                    hist.columns = hist.columns.droplevel('Ticker')
                for idx, row in hist.iterrows():
                    dt_str = idx.strftime('%Y-%m-%d')
                    spy_data[dt_str] = float(row['Close'])
        except Exception as e:
            logger.warning(f"api_live_chart failed: {e}")

    # Use live S&P 500 price for today — but ONLY if we have a spy_first
    # from the same source (yfinance). Mixing yfinance historical with
    # live Yahoo v8 prices corrupts the indexing (different price scales
    # if yfinance downloaded SPY ETF but live returns ^GSPC index).
    today_str = date.today().strftime('%Y-%m-%d')
    if today_str in [d for d in dates] and spy_data:
        try:
            # Use the same symbol that yfinance downloaded
            dl_sym = 'SPY' if max(spy_data.values()) < 1000 else '^GSPC'
            live_spy = fetch_live_prices([dl_sym])
            if dl_sym in live_spy:
                spy_data[today_str] = live_spy[dl_sym]
        except Exception as e:
            logger.warning(f"api_live_chart failed: {e}")

    # 3. Build aligned series indexed to 100
    spy_first = spy_data.get(start_date)
    result_dates = []
    result_hydra = []
    result_spy = []

    for dt in dates:
        hydra_val = hydra_data[dt]
        hydra_indexed = (hydra_val / first_value) * 100

        result_dates.append(dt)
        result_hydra.append(round(hydra_indexed, 2))

        spy_val = spy_data.get(dt)
        if spy_val and spy_first:
            result_spy.append(round((spy_val / spy_first) * 100, 2))
        else:
            # Interpolate: use last known value
            result_spy.append(result_spy[-1] if result_spy else 100.0)

    return jsonify({
        'dates': result_dates,
        'hydra': result_hydra,
        'spy': result_spy,
        'start_date': start_date,
        'update_days': update_days,
    })


@app.route('/api/equity')
def api_equity():
    """Return HYDRA equity curve data (full period from 2000)."""
    df = _equity_df
    if df is None:
        csv_path = os.path.join('backtests', 'hydra_clean_daily.csv')
        if not os.path.exists(csv_path):
            return jsonify({'equity': [], 'milestones': [], 'error': 'No backtest data'})
        try:
            df = pd.read_csv(csv_path, parse_dates=['date'])
        except Exception as e:
            logger.warning(f"api_equity failed: {e}")
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
    """Return HYDRA vs S&P 500 vs Net comparison data (full period from 2000)."""
    df = _equity_df
    spy_df = _spy_df

    if df is None:
        csv_path = os.path.join('backtests', 'hydra_clean_daily.csv')
        if not os.path.exists(csv_path):
            return jsonify({'error': 'No backtest data'})
        try:
            df = pd.read_csv(csv_path, parse_dates=['date'])
        except Exception as e:
            logger.error('Failed to read equity CSV %s', csv_path, exc_info=True)
            return jsonify({'error': f'Failed to read CSV: {str(e)}'})

    if spy_df is None:
        if not os.path.exists(SPY_BENCHMARK_CSV):
            return jsonify({'error': 'No SPY benchmark data'})
        try:
            spy_df = pd.read_csv(SPY_BENCHMARK_CSV, parse_dates=['date'])
        except Exception as e:
            logger.error('Failed to read SPY benchmark CSV %s', SPY_BENCHMARK_CSV, exc_info=True)
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

    hydra_start = float(merged[val_col].iloc[0])
    spy_start = float(merged['close'].iloc[0])

    merged['hydra_val'] = merged[val_col]
    merged['spy_val'] = merged['close'] / spy_start * hydra_start

    hydra_final = float(merged['hydra_val'].iloc[-1])
    spy_final = float(merged['spy_val'].iloc[-1])
    first_date = merged['date_key'].iloc[0]
    last_date = merged['date_key'].iloc[-1]
    years = (last_date - first_date).days / 365.25

    hydra_cagr = (pow(hydra_final / hydra_start, 1 / years) - 1) * 100 if years > 0 else 0
    spy_cagr = (pow(spy_final / hydra_start, 1 / years) - 1) * 100 if years > 0 else 0

    # Net equity curve (Signal - 1.0% fixed annual execution costs)
    EXECUTION_COST = 0.01
    daily_growth_signal = hydra_cagr / 100.0
    net_cagr_decimal = daily_growth_signal - EXECUTION_COST
    days_elapsed = (merged['date_key'] - first_date).dt.days.values
    years_elapsed = days_elapsed / 365.25
    if daily_growth_signal > 0:
        adjustment = ((1 + net_cagr_decimal) / (1 + daily_growth_signal)) ** years_elapsed
    else:
        adjustment = np.ones(len(merged))
    merged['net_val'] = merged['hydra_val'].values * adjustment

    net_final = float(merged['net_val'].iloc[-1])
    net_cagr = (pow(net_final / hydra_start, 1 / years) - 1) * 100 if years > 0 else 0

    # Downsample every 10 rows, always include last row
    sampled = merged.iloc[::10]
    if merged.index[-1] not in sampled.index:
        sampled = pd.concat([sampled, merged.iloc[[-1]]])
    result = []
    for _, row in sampled.iterrows():
        result.append({
            'date': row['date_key'].strftime('%Y-%m-%d'),
            'hydra': round(float(row['hydra_val']), 0),
            'spy': round(float(row['spy_val']), 0),
            'net': round(float(row['net_val']), 0),
        })

    return jsonify({
        'data': result,
        'hydra_cagr': round(hydra_cagr, 2),
        'spy_cagr': round(spy_cagr, 2),
        'net_cagr': round(net_cagr, 2),
        'hydra_final': round(hydra_final, 0),
        'spy_final': round(spy_final, 0),
        'net_final': round(net_final, 0),
        'years': round(years, 1),
    })


@app.route('/api/annual-returns')
def api_annual_returns():
    """Return HYDRA vs S&P 500 annual returns for bar chart."""
    df = _equity_df
    spy_df = _spy_df

    if df is None:
        csv_path = os.path.join('backtests', 'hydra_clean_daily.csv')
        if not os.path.exists(csv_path):
            return jsonify({'error': 'No backtest data'})
        try:
            df = pd.read_csv(csv_path, parse_dates=['date'])
        except Exception as e:
            logger.warning(f"api_annual_returns failed: {e}")
            return jsonify({'error': 'Failed to read CSV'})

    val_col = 'portfolio_value' if 'portfolio_value' in df.columns else 'value'
    df_copy = df[['date', val_col]].copy()
    df_copy['year'] = df_copy['date'].dt.year

    # HYDRA annual returns: last value of year / first value of year - 1
    hydra_annual = []
    for year, grp in df_copy.groupby('year'):
        start_val = float(grp[val_col].iloc[0])
        end_val = float(grp[val_col].iloc[-1])
        ret = ((end_val / start_val) - 1) * 100 if start_val > 0 else 0
        hydra_annual.append({'year': int(year), 'return': round(ret, 2)})

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
    for item in hydra_annual:
        yr = item['year']
        spy_ret = spy_annual.get(yr)
        if item['return'] > 0:
            positive_years += 1
        result.append({
            'year': yr,
            'hydra': item['return'],
            'spy': spy_ret,
        })

    return jsonify({
        'data': result,
        'positive_years': positive_years,
        'total_years': len(hydra_annual),
    })


@app.route('/api/backtest/status')
def api_backtest_status():
    return jsonify({
        'running': False,
        'last_result': 'showcase mode',
        'last_run_date': None,
    })






# ============================================================================
# ANALYTICS ENDPOINTS (lazy import — compute once, cache forever)
# ============================================================================

@app.route('/api/risk')
def api_risk():
    """Return portfolio risk metrics (cached for 5 minutes)."""
    global _risk_cache, _risk_cache_time

    now = datetime.now()
    with _risk_cache_lock:
        if _risk_cache is not None and _risk_cache_time is not None:
            if (now - _risk_cache_time).total_seconds() < RISK_CACHE_SECONDS:
                return jsonify(_risk_cache)

    state = read_state()
    if not state:
        payload = {
            'error': 'No state file found',
            'risk_score': 0.0,
            'risk_label': 'LOW',
            'num_positions': 0,
        }
        with _risk_cache_lock:
            _risk_cache = payload
            _risk_cache_time = now
        return jsonify(payload)

    symbols = list(state.get('positions', {}).keys())
    price_symbols = list(symbols)
    hist_symbols = list(symbols)
    if symbols:
        price_symbols.append('SPY')
        hist_symbols.append('SPY')

    prices = fetch_live_prices(price_symbols)
    # NEVER fall back to ^GSPC for SPY — the index quote (~$6,592) is ~10x
    # the SPY ETF quote (~$659), so aliasing would inflate any SPY position's
    # market value 10x in compute_portfolio_risk (line ~63). If SPY is missing
    # from the live price feed, leave it absent: compute_portfolio_risk falls
    # back to entry_price for any position whose live quote is missing.

    hist_data = _fetch_risk_histories(hist_symbols)
    payload = compute_portfolio_risk(state, prices, hist_data)
    with _risk_cache_lock:
        _risk_cache = payload
        _risk_cache_time = now
    return jsonify(payload)


@app.route('/api/montecarlo')
def api_montecarlo():
    """Return Monte Carlo simulation results."""
    global _montecarlo_cache, _montecarlo_cache_signature
    signature = _montecarlo_signature()
    with _montecarlo_lock:
        if _montecarlo_cache is not None and _montecarlo_cache_signature == signature:
            return jsonify(_montecarlo_cache)
    try:
        from compass_montecarlo import COMPASSMonteCarlo
        mc = COMPASSMonteCarlo()
        results = mc.run_all()
        with _montecarlo_lock:
            _montecarlo_cache = results
            _montecarlo_cache_signature = signature
        return jsonify(results)
    except Exception as e:
        logger.error('Monte Carlo endpoint failed', exc_info=True)
        return jsonify({'error': f'Monte Carlo unavailable: {str(e)}'})


@app.route('/api/trade-analytics')
def api_trade_analytics():
    """Return trade segmentation analytics."""
    global _trade_analytics_cache
    if _trade_analytics_cache is not None:
        return jsonify(_trade_analytics_cache)
    with _trade_analytics_lock:
        if _trade_analytics_cache is not None:
            return jsonify(_trade_analytics_cache)
        try:
            from compass_trade_analytics import COMPASSTradeAnalytics
            ta = COMPASSTradeAnalytics()
            _trade_analytics_cache = ta.run_all()
            return jsonify(_trade_analytics_cache)
        except Exception as e:
            logger.error('Trade analytics endpoint failed', exc_info=True)
            return jsonify({'error': f'Trade analytics unavailable: {str(e)}'})






# ============================================================================
# FUND COMPARISON (HYDRA vs real-world momentum funds)
# ============================================================================

def _load_fund_comparison_data():
    """Load fund comparison from pre-generated JSON (scripts/generate_fund_comparison.py)."""
    json_path = os.path.join('backtests', 'fund_comparison_data.json')
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                data = json.load(f)
            # Convert annual_returns keys from string to int (JSON keys are always strings)
            for fund in data.get('funds', []):
                if 'annual_returns' in fund:
                    fund['annual_returns'] = {
                        int(k): v for k, v in fund['annual_returns'].items()
                    }
            logger.info(f"Loaded fund comparison data: {len(data.get('funds', []))} funds")
            return data
        except Exception as e:
            logger.warning(f"Failed to load fund comparison JSON: {e}")
    logger.warning("Fund comparison JSON not found — returning empty data")
    return {'funds': [], 'crisis_periods': [], 'notes': ['Fund comparison data not generated yet. Run: python scripts/generate_fund_comparison.py']}


_FUND_COMPARISON_DATA = _load_fund_comparison_data()


@app.route('/api/fund-comparison')
def api_fund_comparison():
    return jsonify(_FUND_COMPARISON_DATA)


# ============================================================================
# INPUT VALIDATION
# ============================================================================

def _validate_param(value, pattern, name):
    if value is not None and not re.fullmatch(pattern, value):
        return jsonify({'error': f'invalid parameter: {name}'}), 400
    return None


# ============================================================================
# ENGINE CONTROL
# ============================================================================

@app.route('/api/price-debug')
def api_price_debug():
    """Diagnostic endpoint — test Yahoo Finance connectivity from cloud."""
    test_sym = request.args.get('symbol', 'AAPL')
    err = _validate_param(test_sym, r'^[A-Z]{1,5}$', 'symbol')
    if err:
        return err
    diag = {
        'server_time': datetime.now().isoformat(),
        'has_requests': _HAS_REQUESTS,
        'consecutive_failures': _yf_consecutive_failures,
        'cache_age_seconds': None,
        'cached_symbols': list(_price_cache.keys()),
        'showcase_mode': SHOWCASE_MODE,
        'tests': {},
    }
    if _price_cache_time:
        diag['cache_age_seconds'] = round((datetime.now() - _price_cache_time).total_seconds(), 1)

    # Test v7 batch API
    try:
        session, crumb = _yf_get_session()
        diag['tests']['crumb_obtained'] = bool(crumb)
        if session and crumb:
            url = 'https://query2.finance.yahoo.com/v7/finance/quote'
            params = {'symbols': test_sym, 'fields': 'regularMarketPrice,symbol', 'crumb': crumb}
            r = session.get(url, params=params, timeout=10)
            diag['tests']['v7_status'] = r.status_code
            if r.status_code == 200:
                data = r.json()
                quotes = data.get('quoteResponse', {}).get('result', [])
                if quotes:
                    diag['tests']['v7_price'] = quotes[0].get('regularMarketPrice')
                else:
                    diag['tests']['v7_price'] = None
                    diag['tests']['v7_raw'] = str(data)[:500]
            else:
                diag['tests']['v7_body'] = r.text[:300]
    except Exception as e:
        logger.warning('Yahoo v7 diagnostics request failed', exc_info=True)
        diag['tests']['v7_error'] = str(e)

    # Test v8 chart API fallback
    try:
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{test_sym}'
        r = http_requests.get(url, params={'range': '1d', 'interval': '1d'}, headers=_YF_HEADERS, timeout=10)
        diag['tests']['v8_status'] = r.status_code
        if r.status_code == 200:
            data = r.json()
            meta = data.get('chart', {}).get('result', [{}])[0].get('meta', {})
            diag['tests']['v8_price'] = meta.get('regularMarketPrice')
        else:
            diag['tests']['v8_body'] = r.text[:300]
    except Exception as e:
        logger.warning('Yahoo v8 diagnostics request failed', exc_info=True)
        diag['tests']['v8_error'] = str(e)

    return jsonify(diag)


@app.route('/api/engine/start', methods=['POST'])
def api_engine_start():
    # Cloud engine auto-starts — manual start not needed
    running = _cloud_engine is not None
    return jsonify({'ok': running, 'message': 'Cloud engine auto-managed' if running else 'Engine not started yet'})


@app.route('/api/engine/stop', methods=['POST'])
def api_engine_stop():
    return jsonify({'ok': False, 'message': 'Cloud engine cannot be stopped via API (auto-managed)'})


@app.route('/api/engine/status')
def api_engine_status():
    engine = _cloud_engine
    if engine:
        closed_cycles = _closed_cycle_count_from_log()
        return jsonify({
            'running': True,
            'started_at': engine._start_time.isoformat() if hasattr(engine, '_start_time') else None,
            'error': None,
            'cycles': engine._cycles_completed if hasattr(engine, '_cycles_completed') else 0,
            'engine_iterations': engine._cycles_completed if hasattr(engine, '_cycles_completed') else 0,
            'cycles_completed': closed_cycles,
            'mode': 'cloud-live',
        })
    if AGENT_MODE:
        status_msg = 'AGENT_MODE — engine disabled (Worker is sole state writer)'
    elif _cloud_engine_started:
        status_msg = 'Engine starting...'
    else:
        status_msg = 'Engine not initialized'
    return jsonify({
        'running': False,
        'started_at': None,
        'error': status_msg,
        'cycles': 0,
        'mode': 'agent' if AGENT_MODE else 'cloud-live',
    })


@app.route('/api/preflight')
def api_preflight():
    engine = _cloud_engine
    return jsonify({
        'ready': engine is not None,
        'checks': {'mode': 'cloud-live', 'engine': engine is not None, 'git_sync': bool(os.environ.get('GIT_TOKEN'))},
        'server_time': datetime.now().isoformat(),
    })


@app.route('/api/health')
def api_health():
    state = read_state()
    engine = _engine_snapshot()
    payload = _build_health_payload(engine, state)
    status_code = 503 if payload.get('status') == 'down' else 200
    return jsonify(payload), status_code


@app.route('/api/logs')
def api_logs():
    """Return recent log entries."""
    logs = read_recent_logs(max_lines=80)
    return jsonify({'logs': logs})


@app.route('/api/data-quality')
def api_data_quality():
    """Return data pipeline quality scorecard."""
    global _data_quality_cache, _data_quality_cache_time
    now = datetime.now()
    if _data_quality_cache and _data_quality_cache_time and \
       (now - _data_quality_cache_time).total_seconds() < DATA_QUALITY_CACHE_SECONDS:
        return jsonify(_data_quality_cache)
    try:
        from compass_data_pipeline import COMPASSDataPipeline
        dp = COMPASSDataPipeline()
        results = dp.run_all()
        _data_quality_cache = results
        _data_quality_cache_time = now
        return jsonify(results)
    except Exception as e:
        logger.error('Data quality endpoint failed to run pipeline', exc_info=True)
        return jsonify({'error': str(e)})


@app.route('/api/execution-microstructure')
def api_execution_microstructure():
    """Execution microstructure analysis — stub for showcase mode."""
    return jsonify({
        'mode': 'showcase',
        'message': 'Execution microstructure analysis available in live deployment only.',
        'results': {},
    })


@app.route('/api/execution-stats')
def api_execution_stats():
    try:
        state = read_state()
        order_history = state.get('order_history', []) if state else []

        # Try audit logs if state has no order data
        if not order_history:
            audit_pattern = os.path.join(STATE_DIR, '..', 'logs', 'ibkr_audit_*.json')
            audit_files = sorted(glob.glob(audit_pattern))
            for af in audit_files[-5:]:
                try:
                    with open(af, 'r') as f:
                        data = json.load(f)
                    if isinstance(data, list):
                        order_history.extend(data)
                    elif isinstance(data, dict) and 'orders' in data:
                        order_history.extend(data['orders'])
                except (json.JSONDecodeError, IOError):
                    logger.warning('Skipping unreadable audit order file %s', af, exc_info=True)
                    continue

        total_orders = len(order_history)
        filled = [o for o in order_history if o.get('status') == 'filled']
        fill_rate = len(filled) / total_orders if total_orders > 0 else 0.0

        deviations = []
        for o in filled:
            expected = o.get('expected_price')
            actual = o.get('fill_price')
            if expected and actual and expected != 0:
                deviations.append(abs(actual - expected) / expected * 100)
        avg_deviation = sum(deviations) / len(deviations) if deviations else 0.0

        stale_cancelled = sum(
            1 for o in order_history
            if o.get('status') == 'cancelled' and o.get('reason') == 'stale'
        )

        return jsonify({
            'total_orders': total_orders,
            'fill_rate': round(fill_rate, 4),
            'avg_fill_deviation_pct': round(avg_deviation, 4),
            'stale_orders_cancelled': stale_cancelled,
        })
    except Exception as e:
        logger.error('Error in /api/execution-stats: %s', e)
        return jsonify({
            'total_orders': 0,
            'fill_rate': 0.0,
            'avg_fill_deviation_pct': 0.0,
            'stale_orders_cancelled': 0,
        })


@app.route('/api/overlay-status')
def api_overlay_status():
    """Return current overlay signals and diagnostics."""
    engine = _cloud_engine
    overlay = {}
    if engine and hasattr(engine, '_overlay_available'):
        overlay = {
            'available': engine._overlay_available,
            'capital_scalar': engine._overlay_result.get('capital_scalar', 1.0) if engine._overlay_result else 1.0,
            'per_overlay': engine._overlay_result.get('per_overlay_scalars', {}) if engine._overlay_result else {},
            'position_floor': engine._overlay_result.get('position_floor') if engine._overlay_result else None,
            'diagnostics': engine._overlay_result.get('diagnostics', {}) if engine._overlay_result else {},
        }
    else:
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

# ============================================================================
# AI INTERPRETATION (Claude-powered, once per cycle)
# ============================================================================

_interp_lock = threading.Lock()
_interp_last_cycle = None  # track last interpreted cycle number


def _get_last_closed_cycle_num():
    """Return the highest closed cycle number from cycle_log.json, or None."""
    log_file = os.path.join('state', 'cycle_log.json')
    if not os.path.exists(log_file):
        return None
    try:
        with open(log_file, 'r') as f:
            cycles = json.load(f)
        closed = [c['cycle'] for c in cycles if c.get('status') == 'closed']
        return max(closed) if closed else None
    except Exception as e:
        logger.warning(f"_get_last_closed_cycle_num failed: {e}")
        return None


def _should_regenerate_interpretation():
    """Check if interpretation needs regeneration: startup or new closed cycle."""
    global _interp_last_cycle
    live_path = os.path.join('state', 'ml_learning', 'interpretation_live.md')

    # First call (startup): regenerate if file missing or we haven't tracked yet
    if _interp_last_cycle is None:
        if not os.path.exists(live_path):
            return True
        try:
            age_hours = (time_module.time() - os.path.getmtime(live_path)) / 3600
            if age_hours > 24:
                return True
        except OSError:
            logger.warning('Failed to inspect live interpretation mtime at %s', live_path, exc_info=True)
            return True
        return False

    # Subsequent calls: regenerate only when a new cycle has closed
    last_closed = _get_last_closed_cycle_num()
    if last_closed is not None and last_closed > _interp_last_cycle:
        return True
    return False


_LIVE_MIN_DECISIONS = 10  # minimum live decisions before generating live analysis


def _generate_backtest_interpretation(bt_stats):
    """Call Claude API to generate backtest data analysis."""
    if not _HAS_ANTHROPIC or not bt_stats:
        return None

    data_json = json.dumps({'backtest_stats': bt_stats}, indent=2, default=str)

    system_prompt = """You are the AI analyst for HYDRA, an automated momentum-based stock rotation system
trading 40 US large-cap stocks in 5-day cycles. Analyze the BACKTEST results only.

Write in Spanish. Use ### headers. Be concise but insightful.

Structure:
### Resumen del Backtest — period, CAGR, Sharpe, max drawdown, total return
### Fortalezas — what the backtest shows the system does well
### Riesgos Identificados — drawdown periods, volatility concerns, regime sensitivity
### Contexto Historico — what market conditions drove the results

Focus on genuine insights about the strategy's historical behavior. Keep under 300 words."""

    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=768,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": f"Analyze HYDRA backtest results:\n\n{data_json}"
            }]
        )
        return message.content[0].text
    except Exception as e:
        logger.error(f"Claude API backtest interpretation failed: {e}")
        return None


def _generate_live_interpretation(entries, cycle_data):
    """Call Claude API to generate live paper trading analysis."""
    if not _HAS_ANTHROPIC:
        return None

    live_decisions = [e for e in entries if e.get('_type') == 'decision' and e.get('source') == 'live']
    if len(live_decisions) < _LIVE_MIN_DECISIONS:
        return None  # not enough data yet

    recent = entries[-50:] if len(entries) > 50 else entries
    summary = []
    for r in recent:
        clean = {k: v for k, v in r.items() if k not in ('_type',) and v is not None}
        clean['type'] = r.get('_type', 'unknown')
        summary.append(clean)

    data_payload = {
        'live_entries': summary,
        'total_live_decisions': len(live_decisions),
        'cycle_log': cycle_data,
    }
    data_json = json.dumps(data_payload, indent=2, default=str)

    system_prompt = """You are the AI analyst for HYDRA, an automated momentum-based stock rotation system
trading 40 US large-cap stocks in 5-day cycles. Analyze LIVE PAPER TRADING data only.

Write in Spanish. Use ### headers. Be concise but insightful.

Structure:
### Estado del Paper Trading — days active, cycles completed, current positions
### Analisis de Operaciones — entry/exit patterns, sectors, momentum scores
### Rendimiento Actual — P&L, win rate, alpha vs benchmark (if enough data)
### Observaciones Clave — anomalies, slippage vs backtest, regime behavior
### Proximo Ciclo — what to watch for

All entries are real paper trading decisions (source=live). Focus on execution quality,
regime adherence, and how live behavior compares to backtest expectations.
Keep under 400 words."""

    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": f"Analyze HYDRA live paper trading data:\n\n{data_json}"
            }]
        )
        return message.content[0].text
    except Exception as e:
        logger.error(f"Claude API live interpretation failed: {e}")
        return None


def _maybe_regenerate_interpretation(ml_dir, entries, insights, bt_stats=None):
    global _interp_last_cycle
    bt_path = os.path.join(ml_dir, 'interpretation_backtest.md')
    live_path = os.path.join(ml_dir, 'interpretation_live.md')

    if not _should_regenerate_interpretation():
        if _interp_last_cycle is None:
            _interp_last_cycle = _get_last_closed_cycle_num() or 0
        return

    if not _interp_lock.acquire(blocking=False):
        return

    try:
        os.makedirs(ml_dir, exist_ok=True)
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M')

        # Load cycle log for live analysis
        cycle_data = []
        log_file = os.path.join('state', 'cycle_log.json')
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r') as f:
                    cycle_data = json.load(f)
            except Exception as e:
                logger.warning(f"_maybe_regenerate_interpretation failed: {e}")

        # 1) Backtest analysis — regenerate weekly or if missing
        if bt_stats and (not os.path.exists(bt_path) or
                (time_module.time() - os.path.getmtime(bt_path)) / 3600 > 168):
            logger.info("Generating backtest interpretation...")
            bt_md = _generate_backtest_interpretation(bt_stats)
            if bt_md:
                bt_md += f'\n\n---\n*Generado por Claude el {now_str}. Se actualiza semanalmente.*'
            elif not _HAS_ANTHROPIC:
                bt_md = (f"### Analisis de Backtest No Disponible\n\n"
                         f"La API de Claude no esta configurada (`ANTHROPIC_API_KEY`). "
                         f"El analisis automatico se activara cuando se configure la clave.\n\n"
                         f"---\n*{now_str}*")
            else:
                logger.warning("Backtest interpretation API call returned None — keeping stale file")
            if bt_md:
                tmp = bt_path + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    f.write(bt_md)
                os.replace(tmp, bt_path)
                logger.info("Backtest interpretation saved")

        # 2) Live paper trading analysis — regenerate per cycle
        live_decisions = [e for e in entries if e.get('_type') == 'decision' and e.get('source') == 'live']
        if len(live_decisions) >= _LIVE_MIN_DECISIONS:
            logger.info("Generating live paper trading interpretation...")
            live_md = _generate_live_interpretation(entries, cycle_data)
            if live_md:
                live_md += f'\n\n---\n*Generado por Claude el {now_str}. Se actualiza al cierre de cada ciclo.*'
            elif not _HAS_ANTHROPIC:
                live_md = (f"### Analisis Live No Disponible\n\n"
                           f"La API de Claude no esta configurada (`ANTHROPIC_API_KEY`). "
                           f"Hay **{len(live_decisions)}** decisiones registradas, listas para analizar "
                           f"cuando se configure la clave.\n\n"
                           f"---\n*{now_str}*")
            else:
                logger.warning("Live interpretation API call returned None — keeping stale file")
            if live_md:
                tmp = live_path + '.tmp'
                with open(tmp, 'w', encoding='utf-8') as f:
                    f.write(live_md)
                os.replace(tmp, live_path)
                logger.info("Live interpretation saved")
        else:
            not_enough = (f"### Datos Insuficientes\n\n"
                          f"El paper trading lleva **{len(live_decisions)}** decisiones registradas. "
                          f"Se necesitan al menos **{_LIVE_MIN_DECISIONS}** para generar un analisis significativo.\n\n"
                          f"El sistema continuara recopilando datos automaticamente en cada ciclo de 5 dias.\n\n"
                          f"---\n*Actualizado el {now_str}.*")
            tmp = live_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                f.write(not_enough)
            os.replace(tmp, live_path)

        _interp_last_cycle = _get_last_closed_cycle_num() or 0
    except Exception as e:
        logger.error(f"Interpretation generation error: {e}")
        _interp_last_cycle = _get_last_closed_cycle_num() or 0
    finally:
        _interp_lock.release()


@app.route('/api/ml-diagnostics')
def api_ml_diagnostics():
    ml_dir = os.path.join('state', 'ml_learning')
    try:
        if not os.path.isdir(ml_dir):
            return jsonify({'phase': 0, 'error': 'ML not initialized'}), 200

        decisions_path = os.path.join(ml_dir, 'decisions.jsonl')
        outcomes_path = os.path.join(ml_dir, 'outcomes.jsonl')

        total_decisions = 0
        last_decision_date = None
        if os.path.exists(decisions_path):
            with open(decisions_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rec = json.loads(line)
                            ts = rec.get('timestamp', rec.get('date', ''))
                            rec_date = str(ts)[:10] if ts else ''
                            if rec_date < LIVE_TEST_START_DATE:
                                continue
                            total_decisions += 1
                            if rec_date:
                                last_decision_date = rec_date
                        except Exception:
                            logger.warning('Skipping malformed ML decision line while building /api/ml', exc_info=True)

        total_outcomes = 0
        if os.path.exists(outcomes_path):
            with open(outcomes_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rec = json.loads(line)
                            rec_date = str(rec.get('entry_date') or rec.get('exit_date') or '')[:10]
                            if rec_date >= LIVE_TEST_START_DATE:
                                total_outcomes += 1
                        except Exception:
                            logger.debug('Skipping malformed outcome record in /api/ml-diagnostics')

        files_ok = os.path.exists(decisions_path) and os.path.exists(outcomes_path)

        if total_decisions >= 252:
            phase = 3
        elif total_decisions >= 63:
            phase = 2
        else:
            phase = 1

        return jsonify({
            'phase': phase,
            'total_decisions': total_decisions,
            'total_outcomes': total_outcomes,
            'last_decision_date': last_decision_date,
            'files_ok': files_ok,
        }), 200
    except Exception as e:
        logger.error(f"/api/ml-diagnostics error: {e}", exc_info=True)
        return jsonify({'phase': 0, 'error': str(e)}), 200


@app.route('/api/ml')
@app.route('/api/ml-learning')
def api_ml_learning():
    try:
        return _api_ml_learning_impl()
    except Exception as e:
        logger.error(f"/api/ml-learning crashed: {e}", exc_info=True)
        return jsonify({'log_entries': [], 'insights': {}, 'interpretation': '',
                        'interpretation_backtest': '', 'interpretation_live': '',
                        'kpis': {}, 'error': str(e)}), 200


def _api_ml_learning_impl():
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
                            # Only show data from current live test start
                            rec_date = rec.get('date', rec.get('timestamp', ''))[:10]
                            if rec_date < LIVE_TEST_START_DATE:
                                continue
                            rec['_type'] = etype
                            entries.append(rec)
            except Exception as e:
                logger.warning(f"_api_ml_learning_impl failed: {e}")
    entries.sort(key=lambda r: r.get('timestamp', r.get('date', '')))
    insights = {}
    insights_path = os.path.join(ml_dir, 'insights.json')
    if os.path.exists(insights_path):
        try:
            insights = _load_json_with_invalid_constants(insights_path)
        except Exception as e:
            logger.warning(f"_api_ml_learning_impl failed: {e}")
    # Load backtest daily data (HYDRA + EFA/MSCI World)
    backtest_entries = []
    bt_stats = {}
    bt_csv = os.path.join('backtests', 'hydra_clean_daily.csv')
    if os.path.exists(bt_csv):
        try:
            import csv
            with open(bt_csv, 'r') as f:
                reader = csv.DictReader(f)
                bt_rows = list(reader)
            if bt_rows:
                for row in bt_rows:
                    pv = float(row.get('value', 0))
                    backtest_entries.append({
                        '_type': 'backtest',
                        'date': row.get('date', ''),
                        'portfolio_value': round(pv, 2),
                        'c_alloc': round(float(row.get('c_alloc', 0)), 4),
                        'r_alloc': round(float(row.get('r_alloc', 0)), 4),
                        'efa_alloc': round(float(row.get('efa_alloc', 0)), 4),
                    })
                # Compute backtest summary stats (from initial capital $100k)
                values = [float(r['value']) for r in bt_rows]
                start_val = 100000.0
                end_val = values[-1]
                n_days = len(values)
                years = n_days / 252.0
                total_return = (end_val / start_val) - 1
                cagr = (end_val / start_val) ** (1 / years) - 1 if years > 0 else 0
                import numpy as np_bt
                daily_returns = np_bt.diff(values) / np_bt.array(values[:-1])
                sharpe = float(np_bt.mean(daily_returns) / np_bt.std(daily_returns) * np_bt.sqrt(252)) if np_bt.std(daily_returns) > 0 else 0
                peak = np_bt.maximum.accumulate(values)
                dd = (np_bt.array(values) - peak) / peak
                max_dd = float(dd.min())
                bt_stats = {
                    'start_date': bt_rows[0].get('date', ''),
                    'end_date': bt_rows[-1].get('date', ''),
                    'trading_days': n_days,
                    'years': round(years, 1),
                    'start_value': round(start_val, 0),
                    'end_value': round(end_val, 0),
                    'total_return': round(total_return, 4),
                    'cagr': round(cagr, 4),
                    'sharpe': round(sharpe, 3),
                    'max_drawdown': round(max_dd, 4),
                }
        except Exception as e:
            logger.warning(f"_api_ml_learning_impl failed: {e}")

    # Merge backtest + live entries, sorted by date
    all_entries = backtest_entries + entries
    all_entries.sort(key=lambda r: r.get('timestamp', r.get('date', '')))

    # Trigger interpretation regeneration in background if needed
    global _interp_last_cycle
    if _should_regenerate_interpretation() and not _interp_lock.locked():
        threading.Thread(
            target=_maybe_regenerate_interpretation,
            args=(ml_dir, list(entries), dict(insights), dict(bt_stats) if bt_stats else None),
            daemon=True,
        ).start()
    elif _interp_last_cycle is None:
        _interp_last_cycle = _get_last_closed_cycle_num() or 0

    # Compute KPIs from loaded data
    outcomes = [r for r in entries if r.get('_type') == 'outcome']
    decisions = [r for r in entries if r.get('_type') == 'decision']
    snapshots = [r for r in entries if r.get('_type') == 'snapshot']
    n_entries = sum(1 for d in decisions if d.get('decision_type') == 'entry')
    n_exits = sum(1 for d in decisions if d.get('decision_type') == 'exit')

    trading_days = insights.get('trading_days') or 0
    phase = insights.get('learning_phase') or 1
    days_to_phase2 = max(0, 63 - trading_days)

    kpis = {
        'total_decisions': len(decisions),
        'total_entries': n_entries,
        'total_exits': n_exits,
        'total_outcomes': len(outcomes),
        'total_snapshots': len(snapshots),
        'trading_days': trading_days,
        'phase': phase,
        'days_to_phase2': days_to_phase2,
        'phase2_progress_pct': round(min(100, trading_days / 63 * 100), 1),
        'backtest': bt_stats,
    }
    try:
        if outcomes:
            returns = [float(o.get('gross_return', 0)) for o in outcomes
                       if o.get('gross_return') is not None]
            if returns:
                kpis['win_rate'] = round(sum(1 for r in returns if r > 0) / len(returns), 3)
                kpis['avg_return'] = round(sum(returns) / len(returns), 4)
                kpis['best_trade'] = round(max(returns), 4)
                kpis['worst_trade'] = round(min(returns), 4)
            stop_count = sum(1 for o in outcomes if o.get('was_stopped'))
            kpis['stop_rate'] = round(stop_count / len(outcomes), 3) if len(outcomes) > 0 else 0
            alphas = [float(a) for a in (o.get('alpha_vs_spy') for o in outcomes) if a is not None]
            kpis['avg_alpha'] = round(sum(alphas) / len(alphas), 4) if alphas else None
            pnls = [float(o.get('pnl_usd') or 0) for o in outcomes]
            kpis['total_pnl'] = round(sum(pnls), 2)
    except Exception as e:
        logger.warning(f"KPI calculation error: {e}")

    # Read interpretation files (backtest + live, generated by Claude AI)
    interp_backtest = ''
    interp_live = ''
    try:
        with open(os.path.join(ml_dir, 'interpretation_backtest.md'), 'r', encoding='utf-8') as f:
            interp_backtest = f.read()
    except FileNotFoundError:
        logger.warning(
            'ML interpretation file missing: %s',
            os.path.join(ml_dir, 'interpretation_backtest.md'),
            exc_info=True,
        )
    try:
        with open(os.path.join(ml_dir, 'interpretation_live.md'), 'r', encoding='utf-8') as f:
            interp_live = f.read()
    except FileNotFoundError:
        logger.warning(
            'ML interpretation file missing: %s',
            os.path.join(ml_dir, 'interpretation_live.md'),
            exc_info=True,
        )

    # Backwards compat: also read old single interpretation file
    interpretation = ''
    try:
        with open(os.path.join(ml_dir, 'interpretation.md'), 'r', encoding='utf-8') as f:
            interpretation = f.read()
    except FileNotFoundError:
        logger.warning(
            'ML interpretation file missing: %s',
            os.path.join(ml_dir, 'interpretation.md'),
            exc_info=True,
        )

    return jsonify({
        'log_entries': all_entries,
        'insights': insights,
        'interpretation': interpretation,
        'interpretation_backtest': interp_backtest,
        'interpretation_live': interp_live,
        'kpis': kpis,
    })


@app.route('/robots.txt')
def robots_txt():
    return app.response_class(
        "User-agent: *\nAllow: /\nSitemap: https://omnicapital.onrender.com/sitemap.xml\n",
        mimetype='text/plain'
    )


@app.route('/api/agent-scratchpad')
@app.route('/api/agent/scratchpad')
def api_agent_scratchpad():
    """Return HYDRA agent scratchpad entries."""
    today = datetime.now().strftime('%Y-%m-%d')
    day = request.args.get('date', today)
    err = _validate_param(day, r'^\d{4}-\d{2}-\d{2}$', 'date')
    if err:
        return err
    sp_dir = os.path.join(STATE_DIR, 'agent_scratchpad')
    sp_path = os.path.join(sp_dir, f'{day}.jsonl')
    entries = []
    if os.path.exists(sp_path):
        try:
            with open(sp_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except Exception as e:
            logger.warning(f"api_agent_scratchpad failed: {e}")

    available = []
    if os.path.isdir(sp_dir):
        available = sorted(
            [
                f.replace('.jsonl', '')
                for f in os.listdir(sp_dir)
                if f.endswith('.jsonl')
            ],
            reverse=True,
        )

    return jsonify({
        'date': day,
        'entries': entries,
        'available_dates': available[:30],
    })


@app.route('/api/agent-heartbeat')
def api_agent_heartbeat():
    """Return HYDRA agent heartbeat status."""
    hb_path = os.path.join(STATE_DIR, 'agent_heartbeat.json')
    if not os.path.exists(hb_path):
        return jsonify({'alive': False, 'message': 'No heartbeat file found'})
    try:
        with open(hb_path, 'r') as f:
            data = json.load(f)
        ts = data.get('ts', '')
        if ts:
            last_beat = datetime.fromisoformat(ts)
            age_seconds = (datetime.now() - last_beat).total_seconds()
            data['alive'] = age_seconds < 120
            data['age_seconds'] = round(age_seconds)
        else:
            data['alive'] = False
        return jsonify(data)
    except Exception as e:
        logger.error('Engine status endpoint failed', exc_info=True)
        return jsonify({'alive': False, 'error': str(e)})


@app.route('/sitemap.xml')
def sitemap_xml():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://omnicapital.onrender.com/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>
</urlset>"""
    return app.response_class(xml, mimetype='application/xml')


# ============================================================================
# SHARED DATA FEED (engine reuses dashboard's batch fetcher — no duplicate Yahoo requests)
# ============================================================================


class SharedYahooDataFeed:
    """DataFeed adapter that reuses the dashboard's _yf_fetch_batch and price cache.
    Implements the same interface as YahooDataFeed so COMPASSLive can use it."""

    def __init__(self):
        self.data = {}
        self.last_update = None

    def get_price(self, symbol: str) -> Optional[float]:
        prices = fetch_live_prices([symbol])
        return prices.get(symbol)

    def get_prices(self, symbols: List[str], max_workers: int = None) -> Dict[str, float]:
        return fetch_live_prices(symbols)

    def is_connected(self) -> bool:
        try:
            prices = fetch_live_prices(['^GSPC'])
            return bool(prices)
        except Exception as e:
            logger.warning(f"is_connected failed: {e}")
            return False


# AGENT_MODE: disabled — hydra-agent worker was removed.
# Cloud engine runs directly in the dashboard process.
AGENT_MODE = False


# ============================================================================
# CLOUD HYDRA ENGINE (paper trading — keeps system running when local is offline)
# ============================================================================

_cloud_engine: Optional['COMPASSLive'] = None
_cloud_engine_thread = None
_cloud_engine_started = False

_engine_lock = os.path.join(STATE_DIR, '.cloud_engine.lock')
# Stale engine locks are reclaimed inside _ensure_cloud_engine() to avoid worker races.


def _git_pull_latest():
    """Pull latest state from GitHub before engine starts.
    Ensures cloud picks up any state changes pushed from local."""
    import subprocess
    repo_dir = os.path.dirname(os.path.abspath(__file__))
    git_token = os.environ.get('GIT_TOKEN', '')
    pull_result = {
        'ok': False,
        'auth_failed': False,
        'message': None,
    }

    def _redact_git_output(text):
        if not text:
            return ''
        if git_token:
            text = text.replace(git_token, '***')
        return text.strip()

    if git_token:
        # Configure HTTPS auth for push/pull
        repo_url = f'https://x-access-token:{git_token}@github.com/lucasabu1988/HydraOmniCapital.git'
        try:
            remote_result = subprocess.run(
                ['git', 'remote', 'set-url', 'origin', repo_url],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if remote_result.returncode != 0:
                logger.warning(
                    'git remote set-url failed before pull: %s',
                    _redact_git_output(remote_result.stderr or remote_result.stdout)[:300],
                )
        except Exception as e:
            logger.warning('git remote set-url failed before pull: %s: %s', type(e).__name__, e)

    try:
        result = subprocess.run(
            ['git', 'pull', '--ff-only', 'origin', 'main'],
            cwd=repo_dir, capture_output=True, text=True, timeout=60
        )
        stdout = _redact_git_output(result.stdout)
        stderr = _redact_git_output(result.stderr)
        combined = ' '.join(part for part in [stdout, stderr] if part).lower()
        if result.returncode == 0:
            pull_result['ok'] = True
            pull_result['message'] = stdout or 'Already up to date.'
            logger.info('git pull succeeded: %s', pull_result['message'])
        else:
            pull_result['message'] = (stderr or stdout or f'git pull failed with exit code {result.returncode}')[:300]
            pull_result['auth_failed'] = any(marker in combined for marker in [
                'authentication failed',
                'could not read username',
                'could not read password',
                'permission denied',
                'repository not found',
            ])
            if pull_result['auth_failed']:
                logger.warning('git pull authentication failed: %s', pull_result['message'])
            else:
                logger.warning('git pull failed: %s', pull_result['message'])
    except Exception as e:
        pull_result['message'] = f'{type(e).__name__}: {e}'
        logger.warning('git pull error: %s', pull_result['message'], exc_info=True)
    return pull_result


def _run_cloud_engine():
    """Run the full HYDRA engine with PaperBroker in the cloud.
    Uses Yahoo Finance for all data — no IB dependency.
    The engine saves state files that the dashboard reads directly.
    Git sync enabled: pulls latest state on start, pushes state after trades."""
    global _cloud_engine

    if not _HAS_ENGINE:
        detail = _ENGINE_IMPORT_ERROR or 'ImportError during omnicapital_live import'
        _engine_status['running'] = False
        _engine_status['error'] = f'HYDRA engine not available — omnicapital_live import failed: {detail}'
        _write_engine_runtime_status()
        logger.warning('HYDRA engine not available — cloud trading disabled: %s', detail)
        return

    while True:
        try:
            restart_at = datetime.now().isoformat()
            _cloud_engine = None
            with _engine_status_lock:
                _engine_status['running'] = False
                _engine_status['error'] = None
                _engine_status['startup_started_at'] = restart_at
                restarts = list(_engine_status.get('restarts') or [])
                restarts.append(restart_at)
                _engine_status['restarts'] = restarts[-5:]
            logger.info('Cloud HYDRA engine startup beginning (worker %s)', os.getpid())
            _ensure_engine_runtime_heartbeat()
            _cleanup_data_cache()
            _cleanup_logs()
            _cleanup_corrupted_states()

            # Pull latest state from GitHub (picks up local changes)
            _engine_status['last_git_pull'] = _git_pull_latest()
            if not _engine_status['last_git_pull']['ok']:
                logger.warning(
                    'Cloud engine startup continuing after git pull issue: %s',
                    _engine_status['last_git_pull']['message'],
                )
            recovered_state = _recover_cloud_state(_engine_status['last_git_pull'])
            _engine_status['state_recovery'] = recovered_state.get('_recovered_from')

            # Enable git sync on cloud if GIT_TOKEN is set
            import omnicapital_live as _engine_mod
            if os.environ.get('GIT_TOKEN'):
                _engine_mod._git_sync_available = True
                os.environ.pop('DISABLE_GIT_SYNC', None)
                logger.info("Cloud git sync ENABLED (GIT_TOKEN set)")
            else:
                _engine_mod._git_sync_available = False
                logger.warning("Cloud git sync DISABLED (no GIT_TOKEN — state won't persist across deploys)")

            cloud_config = dict(ENGINE_CONFIG)
            cloud_config['PAPER_INITIAL_CASH'] = HYDRA_CONFIG['INITIAL_CAPITAL']

            _cloud_engine = COMPASSLive(cloud_config)
            # Replace engine's own YahooDataFeed with shared feed
            # so engine + dashboard share one Yahoo session and cache
            shared_feed = SharedYahooDataFeed()
            _cloud_engine.data_feed = shared_feed
            _cloud_engine.broker.set_price_feed(shared_feed)
            logger.info('Cloud engine created, loading state from %s', STATE_FILE)
            _cloud_engine.load_state()
            logger.info('Cloud engine load_state completed (state exists=%s)', os.path.exists(STATE_FILE))

            _engine_status['running'] = True
            _engine_status['started_at'] = restart_at
            _engine_status['error'] = None
            _write_engine_runtime_status()

            logger.info("Cloud HYDRA engine started (SharedYahooDataFeed — no duplicate requests)")
            logger.info(f"  Positions: {list(_cloud_engine.broker.positions.keys())}")
            logger.info(f"  Cash: ${_cloud_engine.broker.cash:,.2f}")

            # Force regime refresh on startup so we never serve a stale score.
            # Done AFTER setting engine status to 'running' so the dashboard
            # is responsive while data downloads (can take 3-5 min).
            try:
                _cloud_engine.refresh_daily_data()
                _cloud_engine.update_regime()
                _cloud_engine.save_state()
                logger.info('Post-startup regime refresh: score=%.4f', _cloud_engine.current_regime_score)
            except Exception as e:
                logger.warning('Post-startup regime refresh failed (will retry at next daily_open): %s', e)

            # run() is a blocking loop: 60s interval, sleeps when market closed
            _cloud_engine.run(interval=60)

        except Exception as e:
            crash_at = datetime.now().isoformat()
            _cloud_engine = None
            with _engine_status_lock:
                _engine_status['running'] = False
                _engine_status['error'] = f'Engine crashed: {e}'
                _engine_status['crash_count'] = int(_engine_status.get('crash_count') or 0) + 1
                _engine_status['last_crash_at'] = crash_at
                _engine_status['last_crash_error'] = str(e)
            _write_engine_runtime_status()
            logger.error(f"Cloud engine crashed: {e}", exc_info=True)
            # Sleep and retry after 5 minutes (loop, not recursion)
            time_module.sleep(300)


def _ensure_cloud_engine():
    """Start the cloud engine thread once. Uses a file lock so only one
    gunicorn worker runs the engine (avoids duplicate trades).
    Also recovers from dead threads by reclaiming the lock."""
    global _cloud_engine_started, _cloud_engine_thread

    if AGENT_MODE:
        _cloud_engine_started = True
        return

    if SHOWCASE_MODE:
        _cloud_engine_started = True
        return

    # If we already started the thread, check if it's still alive
    if _cloud_engine_started:
        if _cloud_engine_thread and _cloud_engine_thread.is_alive():
            return  # Thread is healthy, nothing to do
        # Thread died — reset and try to reclaim
        if _cloud_engine_thread and not _cloud_engine_thread.is_alive():
            logger.warning("Cloud engine thread died — attempting restart")
            _cloud_engine_started = False
            _cloud_engine_thread = None
            lock_file = os.path.join(STATE_DIR, '.cloud_engine.lock')
            try:
                os.unlink(lock_file)
            except OSError:
                logger.warning('Failed to remove stale cloud engine lock %s', lock_file, exc_info=True)
        else:
            lock_file = os.path.join(STATE_DIR, '.cloud_engine.lock')
            try:
                owner_pid = _read_engine_lock_owner(lock_file)
                if _engine_lock_owner_is_alive(owner_pid):
                    return  # Another worker still owns the engine
            except (ValueError, OSError, ProcessLookupError):
                logger.warning('Failed to verify existing cloud engine lock owner for %s', lock_file, exc_info=True)
            logger.warning("Cloud engine lock owner missing/dead — attempting takeover")
            _cloud_engine_started = False

    # File-based lock: first worker to create the file wins
    lock_file = os.path.join(STATE_DIR, '.cloud_engine.lock')
    try:
        _claim_engine_lock(lock_file)
        _cloud_engine_started = True
    except FileExistsError:
        logger.info('Cloud engine lock already exists, inspecting current owner')
        # Check if the owning PID is still alive
        try:
            owner_pid = _read_engine_lock_owner(lock_file)
            if not _engine_lock_owner_is_alive(owner_pid):
                raise ProcessLookupError(owner_pid)
            # PID is alive — another worker owns the engine
            _cloud_engine_started = True
            logger.info("Cloud engine running in worker %s, skipping", owner_pid)
            return
        except (ValueError, OSError, ProcessLookupError):
            # Stale lock — owner PID is dead, reclaim
            logger.warning("Stale engine lock (dead PID) — reclaiming")
            claimed = False
            for _attempt in range(2):
                try:
                    os.unlink(lock_file)
                except FileNotFoundError:
                    logger.warning('Cloud engine lock %s disappeared during reclaim', lock_file, exc_info=True)
                except OSError as e:
                    _engine_status['error'] = f'Engine lock reclaim failed: {e}'
                    logger.error('Cloud engine lock reclaim failed: %s', e, exc_info=True)
                    return

                try:
                    _claim_engine_lock(lock_file)
                    claimed = True
                    break
                except FileExistsError:
                    _cloud_engine_started = True
                    logger.info("Cloud engine lock reclaim lost race to another worker")
                    return
                except OSError as e:
                    _engine_status['error'] = f'Engine lock reclaim failed: {e}'
                    logger.error('Cloud engine lock reclaim failed: %s', e, exc_info=True)
                    return

            if not claimed:
                _cloud_engine_started = True
                return
            _cloud_engine_started = True
    except OSError as e:
        _engine_status['error'] = f'Engine lock acquisition failed: {e}'
        logger.error('Cloud engine lock acquisition failed: %s', e, exc_info=True)
        return

    try:
        _cloud_engine_thread = threading.Thread(
            target=_run_cloud_engine,
            daemon=True,
            name='CloudHydraEngine',
        )
        _cloud_engine_thread.start()
        logger.info("Cloud HYDRA engine thread launched")
    except Exception as e:
        _cloud_engine_thread = None
        _cloud_engine_started = False
        _engine_status['error'] = f'Engine thread launch failed: {e}'
        logger.error('Cloud engine thread launch failed: %s', e, exc_info=True)
        try:
            os.unlink(lock_file)
        except OSError:
            logger.warning('Failed to clean up cloud engine lock %s after launch failure', lock_file, exc_info=True)


@app.before_request
def _start_background_tasks():
    _ensure_cloud_engine()
    _ensure_self_ping()


# ============================================================================
# SELF-PING (keep Render free tier awake)
# ============================================================================

_self_ping_started = False

def _self_ping_loop():
    """Ping our own /api/preflight to prevent Render sleep.
    Every 5 min during market hours (14:00-16:30 ET), every 10 min otherwise."""
    import urllib.request
    url = os.environ.get('RENDER_EXTERNAL_URL', 'https://omnicapital.onrender.com')
    ping_url = f"{url}/api/preflight"
    logger.info(f"Self-ping started: {ping_url} (5 min market hours, 10 min off-hours)")

    while True:
        # Determine interval based on time of day (ET)
        try:
            from zoneinfo import ZoneInfo
            now_et = datetime.now(ZoneInfo('America/New_York'))
            hour = now_et.hour
            is_weekday = now_et.weekday() < 5
            # Critical window: 14:00-16:30 ET (covers pre-close + buffer)
            is_critical = is_weekday and 14 <= hour < 17
            interval = 300 if is_critical else 600  # 5 min vs 10 min
        except Exception as e:
            logger.debug("Self-ping interval calc failed: %s", e)
            interval = 600

        time_module.sleep(interval)
        try:
            resp = urllib.request.urlopen(ping_url, timeout=15)
            logger.debug(f"Self-ping OK: {resp.status} (interval={interval}s)")
        except Exception as e:
            logger.warning(f"Self-ping failed: {e}")


def _ensure_self_ping():
    global _self_ping_started
    if _self_ping_started:
        return
    _self_ping_started = True
    t = threading.Thread(target=_self_ping_loop, daemon=True)
    t.start()


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 60)
    print(f"HYDRA v8.4 \u2014 Cloud Dashboard ({'Showcase' if SHOWCASE_MODE else 'Live'})")
    print("=" * 60)
    print(f"Port: {port}")
    print(f"Mode: {'SHOWCASE' if SHOWCASE_MODE else 'local'}")
    print(f"yfinance: {'available' if _HAS_YFINANCE else 'NOT available'}")
    print(f"requests: {'available' if _HAS_REQUESTS else 'NOT available'}")
    print(f"Equity data: {'loaded' if _equity_df is not None else 'NOT loaded'}")
    print(f"SPY data: {'loaded' if _spy_df is not None else 'NOT loaded'}")
    print("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
