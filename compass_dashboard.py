"""
COMPASS v8.4 — Live Dashboard + Trading Engine
================================================
All-in-one: Flask dashboard + COMPASSLive trading engine
running as a background thread. Single process, single launch.

v8.4 features: Adaptive stops (vol-scaled) | Bull market override | Sector concentration limits

Run:  python compass_dashboard.py
View: http://localhost:5000
"""

from flask import Flask, jsonify, render_template, request
import json
import os
import sys
import glob
import re
import subprocess
import threading
import time as time_module
from datetime import datetime, date, time as dtime, timedelta, timezone
from typing import Dict, Optional, List
from zoneinfo import ZoneInfo
import yfinance as yf
import numpy as np
import pandas as pd
import logging
from logging.handlers import RotatingFileHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests as http_requests  # for external APIs
import xml.etree.ElementTree as XmlET

from compass_portfolio_risk import compute_portfolio_risk

# Suppress yfinance noise
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True


def _load_json_with_invalid_constants(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.loads(f.read(), parse_constant=lambda _constant: None)


def _configure_local_git_sync():
    disabled = os.environ.get('DISABLE_GIT_SYNC')
    if disabled is None:
        # Local auto-sync is opt-in so frequent state snapshots do not pollute main branch history.
        os.environ['DISABLE_GIT_SYNC'] = '1'
        logger.info("Local git auto-sync disabled by default (set DISABLE_GIT_SYNC=0 to re-enable)")
        return
    if disabled.strip().lower() in ('1', 'true', 'yes', 'on'):
        logger.info("Local git auto-sync disabled via DISABLE_GIT_SYNC=%s", disabled)
    else:
        logger.info("Local git auto-sync enabled explicitly (DISABLE_GIT_SYNC=%s)", disabled)


def _validate_param(value, pattern, name):
    if not re.match(pattern, value or ''):
        return jsonify({'error': f'invalid parameter: {name}'}), 400
    return None

# ============================================================================
# COMPASS v8.4 PARAMETERS (read-only reference, must match omnicapital_live.py)
# ============================================================================

COMPASS_CONFIG = {
    # Algorithm (LOCKED)
    'HOLD_DAYS': 5,
    'POSITION_STOP_LOSS': -0.08,           # Fallback for pre-v8.4 positions
    'TRAILING_ACTIVATION': 0.05,
    'TRAILING_STOP_PCT': 0.03,
    'NUM_POSITIONS': 5,
    'NUM_POSITIONS_RISK_OFF': 2,
    'TARGET_VOL': 0.15,
    'LEVERAGE_MIN': 0.3,
    'LEVERAGE_MAX': 1.0,          # Production: no leverage (broker margin destroys value)
    'LEV_FULL': 1.0,
    'INITIAL_CAPITAL': 100_000,
    'CASH_YIELD_SOURCE': "Moody's Aaa IG Corporate (FRED)",

    # --- v8.4 Adaptive Stops (volatility-scaled) ---
    'STOP_DAILY_VOL_MULT': 2.5,
    'STOP_FLOOR': -0.06,                   # Tightest stop for low-vol stocks
    'STOP_CEILING': -0.15,                 # Widest stop for high-vol stocks
    'TRAILING_VOL_BASELINE': 0.25,

    # --- v8.4 Bull Market Override ---
    'BULL_OVERRIDE_THRESHOLD': 0.03,       # SPY > SMA200 * 1.03 -> +1 position
    'BULL_OVERRIDE_MIN_SCORE': 0.40,

    # --- v8.4 Sector Concentration ---
    'MAX_PER_SECTOR': 3,

    # --- Smooth DD Scaling (replaces binary portfolio stop) ---
    'DD_SCALE_TIER1': -0.10,
    'DD_SCALE_TIER2': -0.20,
    'DD_SCALE_TIER3': -0.35,

    # Chassis
    'ORDER_TIMEOUT_SECONDS': 300,
    'MAX_FILL_DEVIATION': 0.02,
    'MAX_PRICE_CHANGE_PCT': 0.20,

    # Recovery stages (days before advancing)
    'RECOVERY_STAGE_1_DAYS': 63,
    'RECOVERY_STAGE_2_DAYS': 126,
}

STATE_FILE = 'state/compass_state_latest.json'
STATE_DIR = 'state'
LOG_DIR = 'logs'
PRICE_CACHE_SECONDS = 30
KILL_FILE = 'STOP_TRADING'
ET = ZoneInfo('America/New_York')
MARKET_OPEN = dtime(9, 30)
MARKET_CLOSE = dtime(16, 0)

# SPY benchmark: cached start price for live test period return
_spy_start_price = None

# Portfolio metrics memoization cache (30s TTL + state file mtime invalidation)
_metrics_cache = None
_metrics_cache_time = None
_metrics_cache_mtime = None


# Broad pool (must match omnicapital_live.py)
BROAD_POOL = [
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'META', 'AVGO', 'ADBE', 'CRM', 'AMD',
    'INTC', 'CSCO', 'IBM', 'TXN', 'QCOM', 'ORCL', 'ACN', 'NOW', 'INTU',
    'AMAT', 'MU', 'LRCX', 'SNPS', 'CDNS', 'KLAC', 'MRVL',
    'BRK-B', 'JPM', 'V', 'MA', 'BAC', 'WFC', 'GS', 'MS', 'AXP', 'BLK',
    'SCHW', 'C', 'USB', 'PNC', 'TFC', 'CB', 'MMC', 'AIG',
    'UNH', 'JNJ', 'LLY', 'ABBV', 'MRK', 'PFE', 'TMO', 'ABT', 'DHR',
    'AMGN', 'BMY', 'MDT', 'ISRG', 'SYK', 'GILD', 'REGN', 'VRTX', 'BIIB',
    'AMZN', 'TSLA', 'WMT', 'HD', 'PG', 'COST', 'KO', 'PEP', 'NKE',
    'MCD', 'DIS', 'SBUX', 'TGT', 'LOW', 'CL', 'KMB', 'GIS', 'EL',
    'MO', 'PM',
    'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'OXY', 'MPC', 'PSX', 'VLO',
    'GE', 'CAT', 'BA', 'HON', 'UNP', 'RTX', 'LMT', 'DE', 'UPS', 'FDX',
    'MMM', 'GD', 'NOC', 'EMR',
    'NEE', 'DUK', 'SO', 'D', 'AEP',
    'VZ', 'T', 'TMUS', 'CMCSA',
]

# ============================================================================
# LIVE ENGINE MANAGEMENT
# ============================================================================

_live_engine = None          # COMPASSLive instance
_live_thread = None          # background thread
_live_thread_lock = threading.Lock()
_engine_status = {
    'running': False,
    'started_at': None,
    'error': None,
    'cycles': 0,
}

# ============================================================================
# BACKTEST AUTO-REFRESH SCHEDULER (includes parquet data refresh)
# ============================================================================

BACKTEST_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'omnicapital_v8_compass.py')
REFRESH_PARQUET_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'refresh_parquet_cache.py')
BACKTEST_CSV = os.path.join('backtests', 'hydra_clean_daily.csv')

_backtest_status = {
    'last_run_date': None,   # date string 'YYYY-MM-DD' of last run attempt
    'running': False,
    'last_result': None,     # 'success' or error message
    'started_at': None,
    'completed_at': None,
}
_backtest_thread = None


def _backtest_scheduler_loop():
    """Daemon thread: runs backtest daily after market close (16:15 ET on weekdays)."""
    global _backtest_status, _data_quality_cache, _data_quality_cache_time

    while True:
        try:
            now_et = datetime.now(ZoneInfo('America/New_York'))
            today_str = now_et.strftime('%Y-%m-%d')
            is_weekday = now_et.weekday() < 5
            after_close = now_et.hour > 16 or (now_et.hour == 16 and now_et.minute >= 15)

            if is_weekday and after_close and _backtest_status['last_run_date'] != today_str and not _backtest_status['running']:
                # Time to run daily refresh
                print(f"[Backtest Scheduler] Starting daily update at {now_et.strftime('%H:%M ET')}...")
                _backtest_status['running'] = True
                _backtest_status['started_at'] = datetime.now().isoformat()
                _backtest_status['last_run_date'] = today_str  # Set immediately to prevent duplicate runs

                try:
                    # Step 1: Refresh parquet data cache
                    print("[Backtest Scheduler] Step 1/2: Refreshing parquet data cache...")
                    pq_result = subprocess.run(
                        [sys.executable, REFRESH_PARQUET_SCRIPT],
                        capture_output=True, text=True,
                        timeout=1800,  # 30 min max for data download
                        cwd=os.path.dirname(os.path.abspath(__file__))
                    )
                    if pq_result.returncode == 0:
                        print("[Backtest Scheduler] Parquet cache refreshed successfully.")
                        # Clear data quality cache so dashboard picks up fresh scores
                        _data_quality_cache = None
                        _data_quality_cache_time = None
                    else:
                        print(f"[Backtest Scheduler] Parquet refresh failed (exit {pq_result.returncode}), continuing with backtest...")
                        if pq_result.stderr:
                            print(f"[Backtest Scheduler] stderr: {pq_result.stderr[:300]}")

                    # Step 2: Run backtest
                    print("[Backtest Scheduler] Step 2/2: Running backtest...")
                    result = subprocess.run(
                        [sys.executable, BACKTEST_SCRIPT],
                        capture_output=True, text=True,
                        timeout=3600,  # 1 hour max
                        cwd=os.path.dirname(os.path.abspath(__file__))
                    )
                    if result.returncode == 0:
                        _backtest_status['last_result'] = 'success'
                        print("[Backtest Scheduler] Daily update completed successfully.")
                    else:
                        _backtest_status['last_result'] = f'exit code {result.returncode}'
                        print(f"[Backtest Scheduler] Backtest failed: exit code {result.returncode}")
                        if result.stderr:
                            print(f"[Backtest Scheduler] stderr: {result.stderr[:500]}")
                except subprocess.TimeoutExpired:
                    _backtest_status['last_result'] = 'timeout (1h)'
                    print("[Backtest Scheduler] Daily update timed out.")
                except Exception as e:
                    _backtest_status['last_result'] = str(e)
                    print(f"[Backtest Scheduler] Error: {e}")
                finally:
                    _backtest_status['running'] = False
                    _backtest_status['completed_at'] = datetime.now().isoformat()

        except Exception as e:
            print(f"[Backtest Scheduler] Loop error: {e}")

        # Check every 5 minutes
        time_module.sleep(300)


def _check_csv_freshness():
    """Check if backtest CSV was already updated today (skip run on startup)."""
    global _backtest_status
    if os.path.exists(BACKTEST_CSV):
        mtime = os.path.getmtime(BACKTEST_CSV)
        mtime_dt = datetime.fromtimestamp(mtime)
        today = date.today()
        if mtime_dt.date() == today:
            _backtest_status['last_run_date'] = today.strftime('%Y-%m-%d')
            _backtest_status['last_result'] = 'success (pre-existing)'
            _backtest_status['completed_at'] = mtime_dt.isoformat()
            print(f"[Backtest Scheduler] CSV already fresh (modified today: {mtime_dt.strftime('%H:%M')})")


def start_backtest_scheduler():
    """Start the backtest auto-refresh scheduler as a daemon thread."""
    global _backtest_thread
    _check_csv_freshness()
    _backtest_thread = threading.Thread(target=_backtest_scheduler_loop, daemon=True, name='BacktestScheduler')
    _backtest_thread.start()
    print("[Backtest Scheduler] Scheduler started — runs daily after 16:15 ET on weekdays")


def _run_live_engine():
    """Background thread: import and run COMPASSLive."""
    global _live_engine, _engine_status

    try:
        _configure_local_git_sync()
        from omnicapital_live import COMPASSLive, CONFIG as LIVE_CONFIG

        config = LIVE_CONFIG.copy()

        # Load external config if available (merge chassis/broker keys only)
        config_file = 'omnicapital_config.json'
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    ext_config = json.load(f)
                safe_keys = {
                    'BROKER_TYPE', 'IBKR_HOST', 'IBKR_PORT', 'IBKR_CLIENT_ID',
                    'IBKR_MOCK', 'PRICE_UPDATE_INTERVAL', 'PAPER_INITIAL_CASH',
                    'LOG_LEVEL', 'STATE_DIR',
                }
                for k, v in ext_config.items():
                    if k in safe_keys:
                        config[k] = v
                        logger.info(f"  Config override: {k}={v}")
                logger.info(f"External config loaded: {config_file}")
            except Exception as e:
                logger.warning(f"Failed to load external config: {e}")

        trader = COMPASSLive(config)
        trader.load_state()
        trader._run_startup_self_test_once()

        # Try notifications (WhatsApp preferred, email fallback)
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    ext = json.load(f)

                # WhatsApp via CallMeBot (preferred)
                wa_cfg = ext.get('whatsapp', {})
                if wa_cfg.get('phone') and wa_cfg.get('apikey'):
                    try:
                        from compass.notifications import WhatsAppNotifier
                        trader.notifier = WhatsAppNotifier(**wa_cfg)
                        logger.info("WhatsApp notifications enabled")
                    except ImportError:
                        from omnicapital_notifications import WhatsAppNotifier
                        trader.notifier = WhatsAppNotifier(**wa_cfg)

                # Email fallback
                if trader.notifier is None:
                    email_cfg = ext.get('email', {})
                    if email_cfg.get('sender') and email_cfg.get('password'):
                        try:
                            from compass.notifications import EmailNotifier
                            trader.notifier = EmailNotifier(**email_cfg)
                        except ImportError:
                            from omnicapital_notifications import EmailNotifier
                            trader.notifier = EmailNotifier(**email_cfg)
        except Exception as e:
            logger.warning(f"Notification setup failed: {e}")

        # Connect broker
        trader.broker.connect()

        # Verify data feed (with retry and fallback)
        feed_ok = trader.data_feed.is_connected()
        if not feed_ok:
            # Fallback: try yfinance history instead of fast_info
            try:
                test = yf.download('SPY', period='5d', progress=False)
                feed_ok = len(test) > 0
            except Exception as e:
                logger.warning(f"_run_live_engine failed: {e}")
        if not feed_ok:
            _engine_status['error'] = 'Data feed not connected'
            _engine_status['running'] = False
            return

        _live_engine = trader
        _engine_status['running'] = True
        _engine_status['started_at'] = datetime.now().isoformat()
        _engine_status['error'] = None
        _engine_status['cycles'] = 0
        _engine_started_event.set()  # Signal that engine is running

        # Initial state save so overlay data and fresh state are immediately available
        try:
            trader.save_state()
        except Exception as e:
            logger.warning(f"Initial state save failed: {e}")

        # Main loop (same as omnicapital_live.py run(), but with stop flag)
        while _engine_status['running']:
            # Kill switch
            if os.path.exists(KILL_FILE):
                _engine_status['error'] = 'Kill switch activated'
                break

            try:
                success = trader.run_once()
                _engine_status['cycles'] = trader._cycles_completed

                if success:
                    time_module.sleep(config.get('PRICE_UPDATE_INTERVAL', 60))
                else:
                    if not trader.is_market_open():
                        time_module.sleep(300)
                    else:
                        time_module.sleep(10)

            except Exception as e:
                _engine_status['error'] = str(e)
                time_module.sleep(10)

        # Final save
        trader.save_state()

    except Exception as e:
        _engine_status['error'] = f'Engine crash: {str(e)}'
    finally:
        _engine_status['running'] = False
        _live_engine = None


_engine_started_event = threading.Event()

def start_engine():
    """Start the live engine in a background thread."""
    global _live_thread
    with _live_thread_lock:
        if _engine_status['running']:
            return False, 'Already running'
        _engine_status['error'] = None
        _engine_status['cycles'] = 0
        _engine_status['started_at'] = datetime.now().isoformat()
        _engine_status['running'] = True  # Guard against double-start; thread's finally block clears on exit
        _engine_started_event.clear()
        _live_thread = threading.Thread(target=_run_live_engine, daemon=True, name='COMPASS-Live')
        _live_thread.start()
        # Wait briefly for thread to confirm startup or fail
        if _engine_started_event.wait(timeout=5):
            return True, 'Started'
        if not _engine_status['running']:
            return False, _engine_status.get('error', 'Engine failed to start')
        return True, 'Starting'


def stop_engine():
    """Stop the live engine gracefully."""
    global _live_thread
    with _live_thread_lock:
        if not _engine_status['running']:
            return False, 'Not running'
        _engine_status['running'] = False
        # Thread will exit on next loop iteration
        return True, 'Stopping'


# ============================================================================
# PRICE CACHE (for dashboard API)
# ============================================================================

_price_cache: Dict[str, float] = {}
_prev_close_cache: Dict[str, float] = {}
_price_cache_time: Optional[datetime] = None
_price_fetch_timestamp = 0


def _fetch_single_price(symbol: str) -> tuple:
    """Fetch a single price (for use in ThreadPoolExecutor).
    Returns (symbol, {'price': float, 'prev_close': float}) or (symbol, None)."""
    try:
        ticker = yf.Ticker(symbol)
        price = None
        prev_close = None
        try:
            fi = ticker.fast_info
            price = fi.last_price
            prev_close = fi.previous_close
        except Exception as e:
            logger.warning(f"_fetch_single_price failed: {e}")
        if not price or price <= 0:
            hist = ticker.history(period='5d')
            if len(hist) > 0:
                price = float(hist['Close'].iloc[-1])
                if len(hist) > 1:
                    prev_close = float(hist['Close'].iloc[-2])
        if price and price > 0:
            result = {'price': float(price)}
            if prev_close and prev_close > 0:
                result['prev_close'] = float(prev_close)
            return (symbol, result)
    except Exception as e:
        logger.warning(f"_fetch_single_price failed: {e}")
    return (symbol, None)


def fetch_live_prices(symbols: List[str]) -> Dict[str, float]:
    """Fetch current prices via yfinance with 30-second cache (async).
    Returns {symbol: price_float} for backward compatibility.
    Previous close data stored in _prev_close_cache."""
    global _price_cache, _prev_close_cache, _price_cache_time, _price_fetch_timestamp

    now = datetime.now()
    if _price_cache_time and (now - _price_cache_time).total_seconds() < PRICE_CACHE_SECONDS:
        missing = [s for s in symbols if s not in _price_cache]
        if not missing:
            return {s: _price_cache[s] for s in symbols if s in _price_cache}
    else:
        missing = symbols
        _price_cache = {}
        # Don't clear _prev_close_cache — previous close is stable intraday

    # Async fetch for all missing symbols
    if missing:
        with ThreadPoolExecutor(max_workers=min(10, len(missing))) as executor:
            futures = {executor.submit(_fetch_single_price, sym): sym for sym in missing}
            for future in as_completed(futures):
                try:
                    sym, result = future.result(timeout=30)
                    if result is not None:
                        _price_cache[sym] = result['price']
                        if 'prev_close' in result:
                            _prev_close_cache[sym] = result['prev_close']
                except Exception as e:
                    logger.warning(f"fetch_live_prices failed: {e}")

    _price_cache_time = now
    _price_fetch_timestamp = time_module.time()
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
            except json.JSONDecodeError as e:
                if attempt == 0:
                    time_module.sleep(0.1)  # brief wait for atomic write to complete
                    continue
                logger.warning(f"State file corrupt ({STATE_FILE}): {e}")
            except IOError as e:
                logger.warning(f"State file read error ({STATE_FILE}): {e}")
                break

    pattern = os.path.join(STATE_DIR, 'compass_state_*.json')
    files = [f for f in glob.glob(pattern) if 'latest' not in f]
    if files:
        latest = max(files, key=os.path.getmtime)
        try:
            with open(latest, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Fallback state file corrupt ({latest}): {e}")

    return None


def _coerce_health_timestamp(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return datetime.combine(value, dtime.min).isoformat()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).isoformat()
        except ValueError:
            try:
                return datetime.combine(date.fromisoformat(value), dtime.min).isoformat()
            except ValueError:
                return value
    return str(value)


def _local_git_sync_enabled():
    value = os.environ.get('DISABLE_GIT_SYNC')
    if value is None:
        return False
    return value.strip().lower() not in ('1', 'true', 'yes', 'on')


def _health_uptime_minutes(state):
    stats = state.get('stats', {}) if state else {}
    uptime = stats.get('uptime_minutes')
    if uptime is not None:
        return round(float(uptime), 2)

    started_at = _engine_status.get('started_at')
    if started_at:
        try:
            started = datetime.fromisoformat(started_at)
            return round((datetime.now() - started).total_seconds() / 60, 2)
        except (TypeError, ValueError):
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


def _health_cycle_counts(state):
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
        engine_iterations = _engine_status.get('cycles', 0)

    return int(cycles_completed or 0), int(engine_iterations or 0)


def _build_health_payload(state):
    price_age_seconds = None
    last_price_update = None
    if _price_cache_time:
        last_price_update = _price_cache_time.isoformat()
        price_age_seconds = round((datetime.now() - _price_cache_time).total_seconds(), 1)

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
            state_last_modified = None

    engine_running = bool(_engine_status.get('running'))
    ml_error_total = sum(abs(int(value or 0)) for value in ml_errors.values())
    if not engine_running or (price_age_seconds is not None and price_age_seconds > 300):
        overall_status = 'critical'
    elif price_age_seconds is None or price_age_seconds > 60 or ml_error_total > 0:
        overall_status = 'degraded'
    else:
        overall_status = 'healthy'

    cycles_completed, engine_iterations = _health_cycle_counts(state)

    return {
        'status': overall_status,
        'timestamp': datetime.now().isoformat(),
        'engine_running': engine_running,
        'price_freshness': price_age_seconds,
        'engine': {
            'running': engine_running,
            'uptime_minutes': _health_uptime_minutes(state),
            'cycles_completed': cycles_completed,
            'engine_iterations': engine_iterations,
            'last_cycle_at': _coerce_health_timestamp(
                state.get('timestamp') if state else _engine_status.get('started_at')
            ),
            'ml_errors': ml_errors,
        },
        'data_feed': {
            'last_price_update': last_price_update,
            'price_age_seconds': price_age_seconds,
            'consecutive_failures': 0,
            'cache_size': len(_price_cache),
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
            'recovered_from': state.get('_recovered_from') if state else None,
        },
        'git_sync': {
            'enabled': _local_git_sync_enabled(),
            'last_push_at': None,
        },
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

        # Noise patterns to filter out (HTTP requests, Flask internals, etc.)
        noise_patterns = (
            '"GET /', '"POST /', '"PUT /', '"DELETE /',
            'HTTP/1.', 'Running on', 'Press CTRL+C',
            'WARNING: This is a development server',
            'Use a production WSGI server',
            'Restarting with', 'Debugger is',
        )

        entries = []
        for line in lines[-max_lines * 3:]:  # read more lines to compensate for filtered noise
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

            # Skip noise
            if any(p in entry['message'] for p in noise_patterns):
                continue

            msg = entry['message'].upper()
            if 'ENTRY' in msg and 'ENTRY' in entry['message']:
                entry['type'] = 'entry'
            elif 'EXIT' in msg:
                entry['type'] = 'exit'
            elif 'REGIME CHANGE' in msg:
                entry['type'] = 'regime'
            elif 'STOP LOSS' in msg:
                entry['type'] = 'stop'
            elif 'RECOVERY' in msg:
                entry['type'] = 'recovery'
            elif 'STATUS:' in msg:
                entry['type'] = 'status'
            elif entry['level'] == 'WARNING':
                entry['type'] = 'warning'
            elif entry['level'] == 'ERROR':
                entry['type'] = 'error'
            else:
                entry['type'] = 'info'

            entries.append(entry)

        return entries[-max_lines:]  # return only the last N after filtering

    except (IOError, OSError):
        return []


# ============================================================================
# DERIVED CALCULATIONS
# ============================================================================

def compute_position_details(state: dict, prices: Dict[str, float], prev_closes: Dict[str, float] = None) -> List[dict]:
    """Compute enriched position data for display."""
    if prev_closes is None:
        prev_closes = {}
    positions = state.get('positions', {})
    position_meta = state.get('position_meta', {})
    trading_day = state.get('trading_day_counter', 0)

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

        # Compute days held from actual entry_date (entry day counts as day 1)
        if entry_date:
            try:
                entry_dt = date.fromisoformat(entry_date)
                today = datetime.now(ZoneInfo('America/New_York')).date()
                total_days = (today - entry_dt).days
                # Count trading days from entry to today, inclusive of entry day (+1)
                days_held = 1 + sum(1 for d in range(1, total_days + 1)
                                    if (entry_dt + timedelta(days=d)).weekday() < 5)
            except Exception:
                days_held = trading_day - entry_day_index + 1
        else:
            days_held = trading_day - entry_day_index + 1
        days_remaining = max(0, COMPASS_CONFIG['HOLD_DAYS'] - days_held)

        # v8.4: Adaptive trailing stop (vol-scaled)
        trailing_active = high_price > entry_price * (1 + COMPASS_CONFIG['TRAILING_ACTIVATION'])
        if trailing_active:
            entry_vol = meta.get('entry_vol', COMPASS_CONFIG['TRAILING_VOL_BASELINE'])
            vol_ratio = entry_vol / COMPASS_CONFIG['TRAILING_VOL_BASELINE']
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
            adaptive_stop = COMPASS_CONFIG['POSITION_STOP_LOSS']  # fallback
        position_stop_level = entry_price * (1 + adaptive_stop)

        # Today's change: current price vs previous regular close (not post-market)
        prev_close = prev_closes.get(symbol)
        if prev_close and prev_close > 0 and current_price:
            today_change_pct = (current_price - prev_close) / prev_close * 100
            today_change_dollar = (current_price - prev_close) * shares
        else:
            today_change_pct = 0.0
            today_change_dollar = 0.0

        # Sector from meta
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
            'today_change_pct': round(today_change_pct, 2),
            'today_change_dollar': round(today_change_dollar, 0),
            'prev_close': round(prev_close, 2) if prev_close else None,
        })

    results.sort(key=lambda x: x['pnl_pct'], reverse=True)
    return results


def get_spy_start_price() -> Optional[float]:
    """Get SPY price at live test start from cycle_log first cycle.
    Returns None if no cycles exist yet (fresh start)."""
    global _spy_start_price
    if _spy_start_price is not None:
        return _spy_start_price

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
            logger.warning(f"get_spy_start_price failed: {e}")

    return None


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


def compute_portfolio_metrics(state: dict, prices: Dict[str, float]) -> dict:
    global _metrics_cache, _metrics_cache_time, _metrics_cache_mtime

    now = time_module.time()
    try:
        current_mtime = os.path.getmtime(STATE_FILE)
    except OSError:
        current_mtime = None

    if (_metrics_cache is not None
            and _metrics_cache_time is not None
            and now - _metrics_cache_time < 30
            and current_mtime is not None
            and _metrics_cache_mtime == current_mtime):
        return _metrics_cache

    result = _compute_portfolio_metrics_impl(state, prices)

    _metrics_cache = result
    _metrics_cache_time = now
    _metrics_cache_mtime = current_mtime

    return result


def _compute_portfolio_metrics_impl(state: dict, prices: Dict[str, float]) -> dict:
    portfolio_value = state.get('portfolio_value', 0)
    peak_value = state.get('peak_value', 0)
    cash = state.get('cash', 0)
    initial_capital = COMPASS_CONFIG['INITIAL_CAPITAL']

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

    recovery = None
    if state.get('in_protection') and state.get('stop_loss_day_index') is not None:
        days_since_stop = state['trading_day_counter'] - state['stop_loss_day_index']
        stage = state.get('protection_stage', 1)
        if stage == 1:
            target_days = COMPASS_CONFIG['RECOVERY_STAGE_1_DAYS']
            next_stage = 'Stage 2 (1.0x leverage, 3 positions)'
        else:
            target_days = COMPASS_CONFIG['RECOVERY_STAGE_2_DAYS']
            next_stage = 'Full Recovery (vol targeting)'
        pct = min(1.0, days_since_stop / target_days) if target_days > 0 else 0
        recovery = {
            'stage': stage,
            'days_elapsed': days_since_stop,
            'days_needed': target_days,
            'days_remaining': max(0, target_days - days_since_stop),
            'pct': round(pct * 100, 1),
            'next_stage': next_stage,
            'requires_risk_on': not state.get('current_regime', True),
        }

    regime_str = 'RISK_ON' if state.get('current_regime', True) else 'RISK_OFF'

    if state.get('in_protection'):
        if state.get('protection_stage') == 1:
            leverage = 0.3
        else:
            leverage = 1.0
    elif not state.get('current_regime', True):
        leverage = 1.0
    else:
        # Normal RISK_ON: vol-targeting capped at 1.0x
        leverage = 1.0

    dd_leverage = state.get('dd_leverage', 1.0)

    # v8.4: Positions from regime score (smooth, with bull override potential)
    regime_score = state.get('current_regime_score', 1.0 if state.get('current_regime', True) else 0.0)
    if regime_score >= 0.65:
        max_pos = COMPASS_CONFIG['NUM_POSITIONS']
    elif regime_score >= 0.50:
        max_pos = max(COMPASS_CONFIG['NUM_POSITIONS'] - 1, COMPASS_CONFIG['NUM_POSITIONS_RISK_OFF'] + 1)
    elif regime_score >= 0.35:
        max_pos = max(COMPASS_CONFIG['NUM_POSITIONS'] - 2, COMPASS_CONFIG['NUM_POSITIONS_RISK_OFF'] + 1)
    else:
        max_pos = COMPASS_CONFIG['NUM_POSITIONS_RISK_OFF']

    # SPY benchmark return over same live test period (cumulative)
    spy_start = get_spy_start_price()
    spy_current = prices.get('SPY')
    if spy_start and spy_current and spy_start > 0:
        spy_cumulative = round((spy_current - spy_start) / spy_start * 100, 2)
    else:
        spy_cumulative = None

    # Daily returns: today's change vs previous close (resets to 0% each morning)
    prev_close_portfolio = cash
    for sym, pos in positions.items():
        pc = _prev_close_cache.get(sym)
        if pc:
            prev_close_portfolio += pos.get('shares', 0) * pc
        else:
            prev_close_portfolio += pos.get('shares', 0) * pos.get('avg_cost', 0)

    if prev_close_portfolio > 0:
        daily_return = round((portfolio_value - prev_close_portfolio) / prev_close_portfolio * 100, 2)
    else:
        daily_return = 0.0

    spy_prev_close = _prev_close_cache.get('SPY')
    if spy_current and spy_prev_close and spy_prev_close > 0:
        spy_daily_return = round((spy_current - spy_prev_close) / spy_prev_close * 100, 2)
    else:
        spy_daily_return = None

    trading_days_elapsed = _compute_real_trading_day(state)

    # Don't show SPY benchmark until HYDRA has actual positions
    if not positions:
        spy_cumulative = None
        spy_daily_return = None

    return {
        'portfolio_value': round(portfolio_value, 2),
        'cash': round(cash, 2),
        'invested': round(invested, 2),
        'peak_value': round(peak_value, 2),
        'drawdown': round(drawdown * 100, 2),
        'total_return': round(total_return * 100, 2),
        'daily_return': daily_return,
        'spy_cumulative': spy_cumulative,
        'spy_daily_return': spy_daily_return,
        'initial_capital': initial_capital,
        'num_positions': len(positions),
        'max_positions': max_pos,
        'regime': regime_str,
        'regime_score': round(regime_score, 2),
        'regime_consecutive': state.get('regime_consecutive', 0),
        'in_protection': state.get('in_protection', False),
        'protection_stage': state.get('protection_stage', 0),
        'dd_leverage': round(dd_leverage, 3) if dd_leverage is not None else None,
        'leverage': leverage,
        'recovery': recovery,
        'trading_day': trading_days_elapsed,
        'last_trading_date': state.get('last_trading_date'),
        'stop_events': state.get('stop_events', []),
        'timestamp': state.get('timestamp', ''),
        'uptime_minutes': state.get('stats', {}).get('uptime_minutes', 0),
    }


def _fetch_risk_histories(symbols):
    if not symbols:
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
# FLASK ROUTES
# ============================================================================

@app.route('/')
def index():
    """Serve the main dashboard page."""
    state = read_state()
    return render_template('dashboard.html', has_state=state is not None)


@app.route('/api/state')
def api_state():
    """Return enriched state data as JSON."""
    engine = _live_engine  # Capture once to avoid TOCTOU race
    state = read_state()

    if not state:
        return jsonify({
            'status': 'offline',
            'error': 'No state file found',
            'positions': {},
            'cash': 0.0,
            'portfolio_value': 0.0,
            'regime_score': None,
            'trading_day_counter': 0,
            'server_time': datetime.now().isoformat(),
            'engine': _engine_status,
        })

    # Collect all symbols for price fetching (include Rattlesnake + Catalyst held)
    rattle_syms = [p.get('symbol') for p in state.get('hydra', {}).get('rattle_positions', []) if p.get('symbol')]
    catalyst_syms = [p.get('symbol') for p in state.get('hydra', {}).get('catalyst_positions', []) if p.get('symbol')]
    symbols = ['SPY', '^GSPC', 'ES=F', 'NQ=F', '^TNX', 'DX-Y.NYB', 'EFA', 'TLT', 'GLD', 'DBC'] + list(state.get('positions', {}).keys()) + rattle_syms + catalyst_syms
    symbols = list(set(symbols))
    prices = fetch_live_prices(symbols)

    position_details = compute_position_details(state, prices, _prev_close_cache)
    portfolio = compute_portfolio_metrics(state, prices)

    # Chassis status from COMPASS live engine
    chassis_status = {
        'async_fetching': True,
        'order_timeout_seconds': COMPASS_CONFIG['ORDER_TIMEOUT_SECONDS'],
        'max_fill_deviation': COMPASS_CONFIG['MAX_FILL_DEVIATION'],
        'data_validation': True,
        'max_price_change_pct': COMPASS_CONFIG['MAX_PRICE_CHANGE_PCT'],
    }

    if engine and hasattr(engine, 'validator'):
        try:
            chassis_status['validator_stats'] = engine.validator.get_stats()
        except Exception as e:
            logger.warning(f"api_state failed: {e}")

    if engine and hasattr(engine, 'broker'):
        try:
            stale = engine.broker.check_stale_orders(
                COMPASS_CONFIG['ORDER_TIMEOUT_SECONDS']
            )
            chassis_status['stale_orders'] = len(stale)
        except Exception as e:
            logger.warning(f"api_state failed: {e}")
            chassis_status['stale_orders'] = 0

    # Pre-close window status
    now_et = datetime.now(ET)
    is_weekday = now_et.weekday() < 5
    current_time = now_et.time()
    preclose_signal_time = dtime(15, 30)
    moc_deadline = dtime(15, 50)

    preclose_entries_done = False
    if engine and hasattr(engine, '_preclose_entries_done'):
        preclose_entries_done = engine._preclose_entries_done

    if not is_weekday or current_time < MARKET_OPEN:
        preclose_phase = 'market_closed'
    elif current_time < preclose_signal_time:
        preclose_phase = 'waiting'         # Market open, waiting for 15:30
    elif current_time <= moc_deadline:
        if preclose_entries_done:
            preclose_phase = 'entries_done' # Signal computed, MOC orders sent
        else:
            preclose_phase = 'window_open'  # In pre-close window
    elif current_time <= MARKET_CLOSE:
        preclose_phase = 'entries_done'     # Past deadline, entries should be done
    else:
        preclose_phase = 'market_closed'

    preclose_status = {
        'phase': preclose_phase,
        'signal_time': '15:30 ET',
        'moc_deadline': '15:50 ET',
        'current_time_et': now_et.strftime('%H:%M:%S'),
        'entries_done': preclose_entries_done,
    }

    # --- Implementation Shortfall (IS) metrics ---
    is_metrics = {'available': False}
    if engine and hasattr(engine, 'broker'):
        try:
            history = getattr(engine.broker, 'order_history', [])
            is_values = [o.is_bps for o in history
                         if getattr(o, 'is_bps', None) is not None]
            if is_values:
                buy_is = [o.is_bps for o in history
                          if getattr(o, 'is_bps', None) is not None and o.action == 'BUY']
                sell_is = [o.is_bps for o in history
                           if getattr(o, 'is_bps', None) is not None and o.action == 'SELL']
                is_metrics = {
                    'available': True,
                    'total_fills': len(is_values),
                    'avg_is_bps': round(sum(is_values) / len(is_values), 2),
                    'median_is_bps': round(sorted(is_values)[len(is_values) // 2], 2),
                    'max_is_bps': round(max(is_values), 2),
                    'min_is_bps': round(min(is_values), 2),
                    'avg_buy_is_bps': round(sum(buy_is) / len(buy_is), 2) if buy_is else None,
                    'avg_sell_is_bps': round(sum(sell_is) / len(sell_is), 2) if sell_is else None,
                    'total_buy_fills': len(buy_is),
                    'total_sell_fills': len(sell_is),
                }
                # Today's IS from trades_today
                today_is = [t.get('is_bps') for t in getattr(engine, 'trades_today', [])
                            if t.get('is_bps') is not None]
                if today_is:
                    is_metrics['today_avg_is_bps'] = round(sum(today_is) / len(today_is), 2)
                    is_metrics['today_fills'] = len(today_is)
        except Exception as e:
            logger.warning(f"api_state failed: {e}")

    # HYDRA status (Rattlesnake, Catalyst, EFA, cash recycling)
    hydra_status = state.get('hydra', {})

    # Enrich catalyst_positions with live prices
    catalyst_raw = hydra_status.get('catalyst_positions', [])
    catalyst_enriched = []
    for cp in catalyst_raw:
        sym = cp.get('symbol', '')
        ep = cp.get('entry_price', 0)
        cur = prices.get(sym, ep)
        pnl = (cur / ep - 1.0) if ep > 0 else 0
        catalyst_enriched.append({
            'symbol': sym, 'entry_price': round(ep, 2),
            'current_price': round(cur, 2), 'pnl_pct': round(pnl, 4),
            'shares': cp.get('shares', 0), 'sub_strategy': cp.get('sub_strategy', 'trend'),
        })
    hydra_status['catalyst_positions'] = catalyst_enriched

    if engine and hasattr(engine, 'hydra_capital') and engine.hydra_capital:
        try:
            hc = engine.hydra_capital.get_status()
            total = hc.get('total_capital', 1)
            hydra_status['capital'] = {
                'hydra_account': round(hc['compass_account'], 2),
                'rattle_account': round(hc['rattle_account'], 2),
                'catalyst_account': round(hc.get('catalyst_account', 0), 2),
                'efa_value': round(hc['efa_value'], 2),
                'hydra_pct': round(hc['compass_pct'], 4),
                'rattle_pct': round(hc['rattle_pct'], 4),
                'catalyst_pct': round(hc.get('catalyst_pct', 0), 4),
                'efa_pct': round(hc['efa_pct'], 4),
                'recycled_pct': round(hc['recycled_pct'], 4),
            }
        except Exception as e:
            logger.warning(f"api_state failed: {e}")

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
        'prev_closes': _prev_close_cache,
        'universe': state.get('current_universe', []),
        'universe_year': state.get('universe_year'),
        'config': {},  # Algorithm parameters are confidential
        'chassis': chassis_status,
        'preclose': preclose_status,
        'implementation_shortfall': is_metrics,
        'hydra': hydra_status,
        'price_data_age_seconds': int(time_module.time() - _price_fetch_timestamp),
        'server_time': datetime.now().isoformat(),
        'engine': _engine_status,
    })


@app.route('/api/health')
def api_health():
    state = read_state()
    return jsonify(_build_health_payload(state))


@app.route('/api/price-debug')
def api_price_debug():
    """Diagnostic endpoint — test Yahoo Finance connectivity locally."""
    test_sym = request.args.get('symbol', 'AAPL')
    err = _validate_param(test_sym, r'^[A-Z]{1,5}$', 'symbol')
    if err:
        return err

    diag = {
        'server_time': datetime.now().isoformat(),
        'has_requests': True,
        'consecutive_failures': 0,
        'cache_age_seconds': None,
        'cached_symbols': list(_price_cache.keys()),
        'showcase_mode': False,
        'tests': {},
    }
    if _price_cache_time:
        diag['cache_age_seconds'] = round((datetime.now() - _price_cache_time).total_seconds(), 1)

    try:
        ticker = yf.Ticker(test_sym)
        diag['tests']['crumb_obtained'] = False
        try:
            fast_info = ticker.fast_info
            price = getattr(fast_info, 'last_price', None)
            if price is None and isinstance(fast_info, dict):
                price = fast_info.get('last_price')
            diag['tests']['v7_status'] = 200 if price else None
            diag['tests']['v7_price'] = float(price) if price else None
        except Exception as e:
            diag['tests']['v7_error'] = str(e)
    except Exception as e:
        diag['tests']['v7_error'] = str(e)

    try:
        url = f'https://query1.finance.yahoo.com/v8/finance/chart/{test_sym}'
        r = http_requests.get(url, params={'range': '1d', 'interval': '1d'}, timeout=10)
        diag['tests']['v8_status'] = r.status_code
        if r.status_code == 200:
            data = r.json()
            meta = data.get('chart', {}).get('result', [{}])[0].get('meta', {})
            diag['tests']['v8_price'] = meta.get('regularMarketPrice')
        else:
            diag['tests']['v8_body'] = r.text[:300]
    except Exception as e:
        diag['tests']['v8_error'] = str(e)

    return jsonify(diag)


@app.route('/api/logs')
def api_logs():
    """Return recent log entries."""
    logs = read_recent_logs(max_lines=80)
    return jsonify({'logs': logs})


@app.route('/api/cycle-log')
def api_cycle_log():
    """Return the 5-day cycle performance log (COMPASS vs S&P 500).

    Active cycles are enriched with live prices so the dashboard
    shows real-time COMPASS return, SPY return, and alpha.
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

    # Enrich active cycles with live metrics (today-only return)
    now_et = datetime.now(ET)
    current_time = now_et.time()
    is_weekday = now_et.weekday() < 5
    market_is_open = is_weekday and MARKET_OPEN <= current_time <= MARKET_CLOSE
    state = read_state()  # Read once, reuse for all active cycles

    for c in cycles:
        c.setdefault('cycle_number', c.get('cycle'))
        c.setdefault('cycle_return_pct', None)
        c.setdefault('start_date', None)
        c.setdefault('end_date', None)
        if c.get('status') != 'active':
            continue
        try:
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

            positions = state.get('positions', {})
            position_meta = state.get('position_meta', {})
            symbols = list(positions.keys()) + ['SPY']
            prices = fetch_live_prices(symbols)

            # Holdings-only return: compare stock picks vs SPY (no cash dilution)
            invested_now = 0
            invested_at_cost = 0
            for sym, pos in positions.items():
                shares = pos.get('shares', 0)
                avg_cost = pos.get('avg_cost', 0)
                if market_is_open:
                    price = prices.get(sym)
                else:
                    price = _prev_close_cache.get(sym) or prices.get(sym)
                if not price:
                    price = avg_cost
                invested_now += shares * price
                invested_at_cost += shares * avg_cost

            if invested_at_cost > 0:
                c['hydra_return'] = round((invested_now / invested_at_cost - 1) * 100, 2)

            # SPY return over same period (from cycle start)
            spy_price = prices.get('SPY') if market_is_open else (_prev_close_cache.get('SPY') or prices.get('SPY'))
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


_live_chart_cache = None
_live_chart_cache_time = None

@app.route('/api/live-chart')
def api_live_chart():
    """Return daily COMPASS vs S&P 500 indexed performance since live test start."""
    global _live_chart_cache, _live_chart_cache_time
    now = datetime.now()
    if _live_chart_cache_time and (now - _live_chart_cache_time).total_seconds() < 60:
        return jsonify(_live_chart_cache)

    pattern = os.path.join(STATE_DIR, 'compass_state_2*.json')
    state_files = sorted(f for f in glob.glob(pattern)
                         if 'pre_rotation' not in f and 'latest' not in f)

    if not state_files:
        return jsonify({'dates': [], 'compass': [], 'spy': []})

    compass_data = {}
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
        except Exception as e:
            logger.warning(f"api_live_chart failed: {e}")
            continue

    if not compass_data or first_value is None:
        return jsonify({'dates': [], 'compass': [], 'spy': []})

    # Add today's live value from latest state, recalculated with live prices
    try:
        state = read_state()
        if state:
            today_str = state.get('last_trading_date')
            if today_str:
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
    except Exception as e:
        logger.warning(f"api_live_chart failed: {e}")

    dates = sorted(compass_data.keys())
    start_date = dates[0]

    spy_data = {}
    try:
        end_dt = date.today() + timedelta(days=1)
        hist = yf.download('SPY', start=start_date,
                         end=end_dt.isoformat(),
                         progress=False, auto_adjust=True)
        if len(hist) > 0:
            # Flatten multi-level columns (yfinance returns MultiIndex)
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.droplevel('Ticker')
            for idx, row in hist.iterrows():
                dt_str = idx.strftime('%Y-%m-%d')
                spy_data[dt_str] = float(row['Close'])
    except Exception as e:
        logger.warning(f"api_live_chart failed: {e}")

    # Use live SPY price for today (matches banner real-time value)
    today_str = date.today().strftime('%Y-%m-%d')
    if today_str in dates:
        try:
            live_spy = fetch_live_prices(['SPY'])
            if 'SPY' in live_spy:
                spy_data[today_str] = live_spy['SPY']
        except Exception as e:
            logger.warning(f"api_live_chart failed: {e}")

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
            result_spy.append(result_spy[-1] if result_spy else 100.0)

    result = {
        'dates': result_dates,
        'compass': result_compass,
        'spy': result_spy,
        'start_date': start_date,
    }
    _live_chart_cache = result
    _live_chart_cache_time = now
    return jsonify(result)


@app.route('/api/equity')
def api_equity():
    """Return HYDRA equity curve data."""
    csv_path = os.path.join('backtests', 'hydra_clean_daily.csv')
    if not os.path.exists(csv_path):
        csv_path = os.path.join('backtests', 'v8_compass_daily.csv')

    if not os.path.exists(csv_path):
        return jsonify({'equity': [], 'milestones': [], 'error': 'No backtest data'})

    try:
        df = pd.read_csv(csv_path, parse_dates=['date'])
    except Exception as e:
        logger.warning(f"api_equity failed: {e}")
        return jsonify({'equity': [], 'milestones': [], 'error': 'Failed to read CSV'})

    val_col = 'portfolio_value' if 'portfolio_value' in df.columns else 'value'
    # Full period from 2000 for accurate representation

    milestones = []
    vals = df[val_col]

    # Capital milestones
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

    # Major drawdowns (>15% from peak)
    peak = vals.expanding().max()
    dd = (vals - peak) / peak
    in_dd = False
    dd_events = []
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
        else:
            ev['label'] = f'Drawdown {ev["dd_pct"]}%'
        ev['type'] = 'drawdown'
        milestones.append(ev)

    # ATH
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
    equity = []
    for _, row in sampled.iterrows():
        equity.append({
            'date': row['date'].strftime('%Y-%m-%d'),
            'value': round(float(row[val_col]), 0),
        })

    return jsonify({
        'equity': equity,
        'milestones': milestones,
    })


# ---------- SPY benchmark for comparison chart ----------
SPY_BENCHMARK_CSV = os.path.join('backtests', 'spy_benchmark.csv')


@app.route('/api/equity-comparison')
def api_equity_comparison():
    """Return COMPASS vs S&P 500 comparison data (both normalised to $100K)."""
    csv_path = os.path.join('backtests', 'hydra_clean_daily.csv')
    if not os.path.exists(csv_path):
        csv_path = os.path.join('backtests', 'v8_compass_daily.csv')
    if not os.path.exists(csv_path):
        return jsonify({'error': 'No backtest data'})
    if not os.path.exists(SPY_BENCHMARK_CSV):
        return jsonify({'error': 'No SPY benchmark data (backtests/spy_benchmark.csv)'})

    try:
        df = pd.read_csv(csv_path, parse_dates=['date'])
        spy_df = pd.read_csv(SPY_BENCHMARK_CSV, parse_dates=['date'])
    except Exception as e:
        return jsonify({'error': f'Failed to read CSV: {str(e)}'})

    val_col = 'portfolio_value' if 'portfolio_value' in df.columns else 'value'

    # --- Merge on date ---
    df['date_key'] = df['date'].dt.normalize()
    spy_df['date_key'] = spy_df['date'].dt.normalize()

    merged = pd.merge(df[['date_key', val_col]], spy_df[['date_key', 'close']],
                       on='date_key', how='inner')

    if merged.empty:
        return jsonify({'error': 'No overlapping dates'})

    # --- Full period (from 2000) for accurate CAGR ---
    # Previously filtered from 2016 which inflated CAGR to ~28% for recent bull run

    # --- Use real COMPASS values; scale SPY to same starting point ---
    compass_start = float(merged[val_col].iloc[0])
    spy_start = float(merged['close'].iloc[0])

    # COMPASS: real portfolio values (matches equity chart Y-axis)
    # SPY: scaled so it starts at the same value as COMPASS
    merged['compass_val'] = merged[val_col]
    merged['spy_val'] = merged['close'] / spy_start * compass_start

    # --- Stats ---
    compass_final = float(merged['compass_val'].iloc[-1])
    spy_final = float(merged['spy_val'].iloc[-1])
    first_date = merged['date_key'].iloc[0]
    last_date = merged['date_key'].iloc[-1]
    years = (last_date - first_date).days / 365.25

    compass_cagr = (pow(compass_final / compass_start, 1 / years) - 1) * 100 if years > 0 else 0
    spy_cagr = (pow(spy_final / compass_start, 1 / years) - 1) * 100 if years > 0 else 0

    # --- Net equity curve (Signal - 1.0% fixed annual execution costs) ---
    # Net CAGR = Signal CAGR - 1.0%.  Synthesis: net(t) = signal(t) * ((1+net)/(1+signal))^t
    EXECUTION_COST = 0.01  # 1.0% annual (MOC slippage + commissions)
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

    # --- Downsample every 10 rows (full 26yr period) ---
    # Always include the last row so the chart reaches the final date
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
    csv_path = os.path.join('backtests', 'hydra_clean_daily.csv')
    if not os.path.exists(csv_path):
        csv_path = os.path.join('backtests', 'v84_overlay_daily.csv')
    if not os.path.exists(csv_path):
        csv_path = os.path.join('backtests', 'v84_compass_daily.csv')
    if not os.path.exists(csv_path):
        return jsonify({'error': 'No backtest data'})

    try:
        df = pd.read_csv(csv_path, parse_dates=['date'])
    except Exception as e:
        logger.warning(f"api_annual_returns failed: {e}")
        return jsonify({'error': 'Failed to read CSV'})

    val_col = 'portfolio_value' if 'portfolio_value' in df.columns else 'value'
    df['year'] = df['date'].dt.year

    # COMPASS annual returns
    compass_annual = []
    for year, grp in df.groupby('year'):
        start_val = float(grp[val_col].iloc[0])
        end_val = float(grp[val_col].iloc[-1])
        ret = ((end_val / start_val) - 1) * 100 if start_val > 0 else 0
        compass_annual.append({'year': int(year), 'return': round(ret, 2)})

    # SPY annual returns
    spy_annual = {}
    spy_csv = os.path.join('backtests', 'spy_benchmark.csv')
    if os.path.exists(spy_csv):
        try:
            spy_df = pd.read_csv(spy_csv, parse_dates=['date'])
            spy_df['year'] = spy_df['date'].dt.year
            for year, grp in spy_df.groupby('year'):
                start_val = float(grp['close'].iloc[0])
                end_val = float(grp['close'].iloc[-1])
                ret = ((end_val / start_val) - 1) * 100 if start_val > 0 else 0
                spy_annual[int(year)] = round(ret, 2)
        except Exception as e:
            logger.warning(f"api_annual_returns failed: {e}")

    result = []
    positive_years = 0
    for item in compass_annual:
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
        'total_years': len(compass_annual),
    })


@app.route('/api/fund-comparison')
def api_fund_comparison():
    """Return HYDRA vs real-world momentum funds comparison data."""
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
            return jsonify(data)
        except Exception as e:
            return jsonify({'error': f'Failed to load fund comparison: {str(e)}'})
    return jsonify({
        'funds': [], 'crisis_periods': [], 'notes': [
            'Fund comparison data not generated yet. Run: python scripts/generate_fund_comparison.py'
        ]
    })


@app.route('/api/backtest/status')
def api_backtest_status():
    """Return backtest data freshness and scheduler status."""
    bt = dict(_backtest_status)  # Snapshot to avoid partial reads from scheduler thread
    result = {
        'running': bt['running'],
        'last_result': bt['last_result'],
        'last_run_date': bt['last_run_date'],
        'started_at': bt['started_at'],
        'completed_at': bt['completed_at'],
        'csv_last_modified': None,
        'csv_age_hours': None,
        'next_scheduled_run': None,
    }

    # CSV freshness
    if os.path.exists(BACKTEST_CSV):
        mtime = os.path.getmtime(BACKTEST_CSV)
        mtime_dt = datetime.fromtimestamp(mtime)
        result['csv_last_modified'] = mtime_dt.isoformat()
        result['csv_age_hours'] = round((time_module.time() - mtime) / 3600, 2)

    # Next scheduled run: next weekday at 16:15 ET
    now_et = datetime.now(ZoneInfo('America/New_York'))
    target_time = now_et.replace(hour=16, minute=15, second=0, microsecond=0)
    if now_et >= target_time or now_et.weekday() >= 5:
        # Move to next weekday
        days_ahead = 1
        next_day = now_et + timedelta(days=days_ahead)
        while next_day.weekday() >= 5:
            days_ahead += 1
            next_day = now_et + timedelta(days=days_ahead)
        target_time = next_day.replace(hour=16, minute=15, second=0, microsecond=0)
    # Already run today? Advance to next weekday
    if _backtest_status['last_run_date'] == now_et.strftime('%Y-%m-%d'):
        days_ahead = 1
        next_day = now_et + timedelta(days=days_ahead)
        while next_day.weekday() >= 5:
            days_ahead += 1
            next_day = now_et + timedelta(days=days_ahead)
        target_time = next_day.replace(hour=16, minute=15, second=0, microsecond=0)

    result['next_scheduled_run'] = target_time.isoformat()

    return jsonify(result)


@app.route('/api/preflight')
def api_preflight():
    """Pre-market readiness checks for 9:30 ET open."""
    engine = _live_engine  # Capture once to avoid TOCTOU race
    now_et = datetime.now(ET)
    checks = {}

    current_time = now_et.time()
    is_weekday = now_et.weekday() < 5
    is_market_open = is_weekday and MARKET_OPEN <= current_time <= MARKET_CLOSE
    is_premarket = is_weekday and current_time < MARKET_OPEN

    if is_market_open:
        market_phase = 'OPEN'
        seconds_to_open = 0
    elif is_premarket:
        open_dt = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        seconds_to_open = int((open_dt - now_et).total_seconds())
        market_phase = 'PRE_MARKET'
    else:
        market_phase = 'CLOSED'
        # Calculate seconds to next market open
        next_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        if current_time >= MARKET_OPEN:
            # After market hours today -> next day
            next_open += timedelta(days=1)
        # Skip weekends
        while next_open.weekday() >= 5:  # Sat=5, Sun=6
            next_open += timedelta(days=1)
        seconds_to_open = int((next_open - now_et).total_seconds())

    checks['market'] = {
        'phase': market_phase,
        'time_et': now_et.strftime('%H:%M:%S'),
        'date_et': now_et.strftime('%Y-%m-%d %A'),
        'seconds_to_open': seconds_to_open,
        'is_weekday': is_weekday,
    }

    # Live system — now we check our own thread
    state = read_state()
    live_running = _engine_status['running']
    state_age_seconds = None
    if state and state.get('timestamp'):
        try:
            ts = datetime.fromisoformat(state['timestamp'])
            state_age_seconds = (datetime.now() - ts).total_seconds()
        except (ValueError, TypeError):
            pass

    checks['live_system'] = {
        'ok': live_running,
        'state_exists': state is not None,
        'state_age_seconds': round(state_age_seconds, 0) if state_age_seconds else None,
        'trading_day': state.get('trading_day_counter', 0) if state else 0,
        'engine_cycles': _engine_status.get('cycles', 0),
    }

    # Kill switch
    kill_active = os.path.exists(KILL_FILE)
    checks['kill_switch'] = {
        'ok': not kill_active,
        'active': kill_active,
    }

    # Data feed
    spy_price = None
    try:
        prices = fetch_live_prices(['SPY'])
        spy_price = prices.get('SPY')
    except Exception as e:
        logger.warning(f"api_preflight failed: {e}")
    data_ok = spy_price is not None and spy_price > 0

    checks['data_feed'] = {
        'ok': data_ok,
        'spy_price': round(spy_price, 2) if spy_price else None,
    }

    # State dir
    state_dir_exists = os.path.isdir(STATE_DIR)
    checks['state_dir'] = {'ok': state_dir_exists}

    # Config file
    config_exists = os.path.exists('omnicapital_config.json')
    checks['config'] = {'ok': config_exists}

    # SPY regime
    regime_data = None
    try:
        spy_df = yf.download('SPY', period='1y', progress=False)
        if isinstance(spy_df.columns, pd.MultiIndex):
            spy_df.columns = [c[0] for c in spy_df.columns]
        if len(spy_df) >= 200:
            sma200 = spy_df['Close'].rolling(200).mean().iloc[-1]
            spy_close = spy_df['Close'].iloc[-1]
            above_sma = float(spy_close) > float(sma200)
            returns = spy_df['Close'].pct_change().dropna().iloc[-20:]
            vol_20d = float(returns.std() * np.sqrt(252))
            raw_lev = 0.15 / vol_20d if vol_20d > 0.01 else 1.0
            est_leverage = max(0.3, min(1.0, raw_lev))

            regime_data = {
                'spy_close': round(float(spy_close), 2),
                'sma200': round(float(sma200), 2),
                'above_sma': above_sma,
                'regime': 'RISK_ON' if above_sma else 'RISK_OFF',
                'vol_20d': round(vol_20d * 100, 1),
                'est_leverage': round(est_leverage, 2),
            }
    except Exception as e:
        logger.warning(f"api_preflight failed: {e}")

    checks['regime'] = regime_data

    if not checks['data_feed']['ok'] and regime_data and regime_data.get('spy_close'):
        checks['data_feed']['ok'] = True
        checks['data_feed']['spy_price'] = regime_data['spy_close']

    # Chassis health checks
    chassis_ok = True
    chassis_info = {
        'async_fetching': True,
        'data_validation': True,
        'fill_circuit_breaker': True,
        'order_timeout': True,
    }
    if engine and hasattr(engine, 'validator'):
        try:
            stats = engine.validator.get_stats()
            rejection_rate = stats.get('rejection_rate', 0)
            chassis_info['validator_rejection_rate'] = round(rejection_rate * 100, 1)
            # Flag if rejection rate is unusually high (>10%)
            if rejection_rate > 0.10:
                chassis_info['data_validation_warning'] = 'High rejection rate'
                chassis_ok = False
        except Exception as e:
            logger.warning(f"api_preflight failed: {e}")
    checks['chassis'] = {
        'ok': chassis_ok,
        **chassis_info,
    }

    all_ok = (
        checks['data_feed']['ok']
        and checks['kill_switch']['ok']
        and checks['state_dir']['ok']
        and checks['config']['ok']
        and chassis_ok
    )

    return jsonify({
        'ready': all_ok,
        'checks': checks,
        'server_time': datetime.now().isoformat(),
    })


# ============================================================================
# SOCIAL FEED API (yfinance + Reddit + Finviz + SEC EDGAR + Google News + Stocktwits)
# ============================================================================

_social_cache: Dict = {}
_social_cache_time: Optional[datetime] = None
SOCIAL_CACHE_SECONDS = 300  # 5 min cache
_ultimate_risk_cache: Optional[List[dict]] = None
_ultimate_risk_cache_time: Optional[datetime] = None
ULTIMATE_RISK_CACHE_SECONDS = 300
_ultimate_risk_cache_lock = threading.Lock()

ULTIMATE_RISK_NEWS_QUERIES = [
    '"stock market" (crash OR selloff OR rout OR panic OR liquidation)',
    '("credit crisis" OR "liquidity crisis" OR "bank run" OR contagion) markets',
    '("systemic risk" OR "hard landing" OR recession OR stagflation) stocks',
    '("geopolitical escalation" OR "oil shock" OR "tariff escalation") markets',
]
ULTIMATE_RISK_ALWAYS_INCLUDE = (
    'stock market crash',
    'market crash',
    'liquidity crisis',
    'credit crisis',
    'bank run',
    'banking crisis',
    'systemic risk',
    'forced liquidation',
    'contagion',
)
ULTIMATE_RISK_MARKET_TERMS = (
    'market',
    'markets',
    'stocks',
    'equity',
    'equities',
    's&p',
    'wall street',
    'treasury',
    'fed',
    'economy',
    'economic',
)
ULTIMATE_RISK_RULES = (
    ('stock market crash', 5),
    ('market crash', 4),
    ('crash', 3),
    ('selloff', 2),
    ('rout', 2),
    ('panic', 2),
    ('liquidity crisis', 4),
    ('credit crisis', 4),
    ('credit event', 3),
    ('funding stress', 3),
    ('bank run', 4),
    ('banking crisis', 4),
    ('contagion', 4),
    ('systemic risk', 4),
    ('forced liquidation', 4),
    ('margin call', 3),
    ('default', 3),
    ('bankruptcy', 2),
    ('recession', 2),
    ('hard landing', 3),
    ('stagflation', 3),
    ('downgrade', 1),
    ('geopolitical escalation', 2),
    ('oil shock', 3),
    ('tariff escalation', 2),
    ('volatility spike', 2),
)


def _trim_feed_text(text, max_len=150):
    text = (text or '').strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].rsplit(' ', 1)[0] + '...'


def _coerce_rss_pubdate(pub_date_raw):
    if not pub_date_raw:
        return ''
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(pub_date_raw)
        return dt.isoformat()
    except Exception:
        return pub_date_raw


def _classify_ultimate_risk_text(text):
    normalized = ' '.join((text or '').lower().split())
    matched = []
    score = 0
    for phrase, weight in ULTIMATE_RISK_RULES:
        if phrase in normalized:
            matched.append(phrase)
            score += weight
    has_market_context = any(term in normalized for term in ULTIMATE_RISK_MARKET_TERMS)
    if has_market_context:
        score += 1
    qualifies = any(phrase in normalized for phrase in ULTIMATE_RISK_ALWAYS_INCLUDE)
    if not qualifies and has_market_context and score >= 4:
        qualifies = True
    return qualifies, sorted(set(matched))[:3], score


def _build_ultimate_risk_item(title, link, pub_iso, source, user, detail=''):
    qualifies, matched_keywords, risk_score = _classify_ultimate_risk_text(f'{title} {detail}')
    if not qualifies:
        return None
    return {
        'symbol': 'MKT',
        'body': _trim_feed_text(title),
        'detail': _trim_feed_text(detail, max_len=120),
        'user': user,
        'time': pub_iso,
        'url': link,
        'source': source,
        'sentiment': 'bearish',
        'matched_keywords': matched_keywords,
        'risk_score': risk_score,
    }


def _fetch_google_ultimate_risk_news(max_per_query: int = 3) -> List[dict]:
    items = []
    headers = {'User-Agent': 'COMPASS-Dashboard/1.0'}
    for query in ULTIMATE_RISK_NEWS_QUERIES:
        try:
            r = http_requests.get(
                'https://news.google.com/rss/search',
                params={'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'},
                headers=headers,
                timeout=8
            )
            if r.status_code != 200:
                continue
            root = XmlET.fromstring(r.content)
            count = 0
            for item_el in root.iter('item'):
                if count >= max_per_query:
                    break
                title = item_el.findtext('title', '').strip()
                if not title:
                    continue
                source_name = item_el.findtext('source', '').strip()
                if ' - ' in title and source_name:
                    title = title.rsplit(' - ', 1)[0].strip()
                item = _build_ultimate_risk_item(
                    title=title,
                    link=item_el.findtext('link', '').strip(),
                    pub_iso=_coerce_rss_pubdate(item_el.findtext('pubDate', '').strip()),
                    source='google',
                    user=source_name or 'Google News',
                    detail=source_name or 'Google News',
                )
                if item is None:
                    continue
                items.append(item)
                count += 1
        except Exception as e:
            logger.warning(f"_fetch_google_ultimate_risk_news failed: {e}")
    return items


def _fetch_marketwatch_ultimate_risk_news(max_items: int = 8) -> List[dict]:
    items = []
    headers = {'User-Agent': 'COMPASS-Dashboard/1.0'}
    try:
        r = http_requests.get(
            'https://feeds.marketwatch.com/marketwatch/topstories/',
            headers=headers,
            timeout=8
        )
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
            item = _build_ultimate_risk_item(
                title=title,
                link=item_el.findtext('link', '').strip(),
                pub_iso=_coerce_rss_pubdate(item_el.findtext('pubDate', '').strip()),
                source='marketwatch',
                user='MarketWatch',
                detail='MarketWatch',
            )
            if item is None:
                continue
            items.append(item)
            count += 1
    except Exception as e:
        logger.warning(f"_fetch_marketwatch_ultimate_risk_news failed: {e}")
    return items


def fetch_ultimate_risk_news() -> List[dict]:
    global _ultimate_risk_cache, _ultimate_risk_cache_time

    now = datetime.now()
    with _ultimate_risk_cache_lock:
        if (
            _ultimate_risk_cache is not None and
            _ultimate_risk_cache_time is not None and
            (now - _ultimate_risk_cache_time).total_seconds() < ULTIMATE_RISK_CACHE_SECONDS
        ):
            return list(_ultimate_risk_cache)

    fetchers = [
        lambda: _fetch_google_ultimate_risk_news(max_per_query=3),
        lambda: _fetch_marketwatch_ultimate_risk_news(max_items=8),
    ]
    all_items = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(fn) for fn in fetchers]
        for future in as_completed(futures):
            try:
                all_items.extend(future.result())
            except Exception as e:
                logger.warning(f"Ultimate risk source failed: {e}")

    deduped = []
    seen = set()
    for item in sorted(
        all_items,
        key=lambda entry: (entry.get('risk_score', 0), entry.get('time', '')),
        reverse=True,
    ):
        key = (item.get('url') or item.get('body') or '').strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    result = deduped[:6]
    with _ultimate_risk_cache_lock:
        _ultimate_risk_cache = result
        _ultimate_risk_cache_time = now
    return result



def _fetch_yfinance_news(symbols: List[str], max_per: int = 3) -> List[dict]:
    """Fetch news from yfinance for holdings."""
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
        except Exception as e:
            logger.warning(f"_fetch_yfinance_news failed: {e}")
    return items


def _fetch_reddit_posts(symbols: List[str], max_per: int = 2) -> List[dict]:
    """Fetch recent Reddit posts mentioning stock tickers."""
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
                # Determine sentiment from score and upvote ratio
                score = d.get('score', 0)
                ratio = d.get('upvote_ratio', 0.5)
                sentiment = 'bullish' if (score > 10 and ratio > 0.7) else 'bearish' if ratio < 0.4 else None

                created = d.get('created_utc', 0)
                pub_iso = datetime.fromtimestamp(created, tz=timezone.utc).isoformat() if created else ''
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
        except Exception as e:
            logger.warning(f"_fetch_reddit_posts failed: {e}")
    return items


def _fetch_seekingalpha_news(symbols: List[str], max_per: int = 2) -> List[dict]:
    """Fetch analysis from Seeking Alpha RSS for holdings (free, no API key)."""
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
        except Exception as e:
            logger.warning(f"_fetch_seekingalpha_news failed: {e}")
    return items


def _fetch_sec_filings(symbols: List[str], max_per: int = 2) -> List[dict]:
    """Fetch recent SEC EDGAR filings via EFTS full-text search (free, no key)."""
    items = []
    headers = {'User-Agent': 'COMPASS-Dashboard admin@omnicapital.com'}
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
        except Exception as e:
            logger.warning(f"_fetch_sec_filings failed: {e}")
    return items


def _fetch_google_news(symbols: List[str], max_per: int = 2) -> List[dict]:
    """Fetch stock news from Google News RSS (free, no API key)."""
    items = []
    headers = {'User-Agent': 'COMPASS-Dashboard/1.0'}
    for symbol in symbols:
        try:
            # Google News RSS search
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

                # Clean title (Google News appends " - Source Name")
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
        except Exception as e:
            logger.warning(f"_fetch_google_news failed: {e}")
    return items


def _fetch_marketwatch_news(max_items: int = 5) -> List[dict]:
    """Fetch top market headlines from MarketWatch RSS (free, no API key)."""
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
    except Exception as e:
        logger.warning(f"_fetch_marketwatch_news failed: {e}")
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

    # Clear stale entries when symbol set changes (prevent unbounded growth)
    if cache_key not in _social_cache:
        _social_cache.clear()

    # Fetch from all sources in parallel (reduces worst-case from ~48s to ~8s)
    fetchers = [
        lambda: _fetch_yfinance_news(symbols, max_per=3),
        lambda: _fetch_reddit_posts(symbols, max_per=2),
        lambda: _fetch_seekingalpha_news(symbols, max_per=2),
        lambda: _fetch_sec_filings(symbols, max_per=2),
        lambda: _fetch_google_news(symbols, max_per=2),
        lambda: _fetch_marketwatch_news(max_items=5),
    ]
    all_items = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fn) for fn in fetchers]
        for f in as_completed(futures):
            try:
                all_items.extend(f.result())
            except Exception as e:
                logger.warning(f"Social feed source failed: {e}")
    all_items.sort(key=lambda x: x.get('time', ''), reverse=True)
    result = all_items[:50]  # Increased from 20 to 50 (own tab now)

    _social_cache[cache_key] = result
    _social_cache_time = now
    return result


@app.route('/api/social-feed')
def api_social_feed():
    """Return social feed (news + reddit) for current holdings."""
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
    """Legacy news endpoint — redirects to social feed."""
    return api_social_feed()


@app.route('/api/ultimate-risk-news')
def api_ultimate_risk_news():
    messages = fetch_ultimate_risk_news()
    with _ultimate_risk_cache_lock:
        updated_at = _ultimate_risk_cache_time.isoformat() if _ultimate_risk_cache_time else datetime.now().isoformat()
    return jsonify({
        'status': 'alert' if messages else 'clear',
        'count': len(messages),
        'updated_at': updated_at,
        'messages': messages,
    })


# ============================================================================
# ANALYTICS API (Monte Carlo, Trade Analytics, Data Quality)
# ============================================================================

_montecarlo_cache = None
_montecarlo_cache_signature = None

_risk_cache = None
_risk_cache_time = None
RISK_CACHE_SECONDS = 300
_risk_cache_lock = threading.Lock()
_montecarlo_lock = threading.Lock()

_trade_analytics_cache = None
_trade_analytics_cache_time = None
TRADE_ANALYTICS_CACHE_SECONDS = 3600

_data_quality_cache = None
_data_quality_cache_time = None
DATA_QUALITY_CACHE_SECONDS = 1800

_exec_micro_cache = None
_exec_micro_cache_time = None
EXEC_MICRO_CACHE_SECONDS = 3600   # 1 hour (static backtest analysis)


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


@app.route('/api/risk')
def api_risk():
    """Return portfolio risk metrics (cached for 5 minutes)."""
    global _risk_cache, _risk_cache_time

    now = datetime.now()
    with _risk_cache_lock:
        if _risk_cache is not None and _risk_cache_time is not None and \
           (now - _risk_cache_time).total_seconds() < RISK_CACHE_SECONDS:
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
    if 'SPY' not in prices and '^GSPC' in prices:
        prices['SPY'] = prices['^GSPC']

    hist_data = _fetch_risk_histories(hist_symbols)
    results = compute_portfolio_risk(state, prices, hist_data)
    with _risk_cache_lock:
        _risk_cache = results
        _risk_cache_time = now
    return jsonify(results)


@app.route('/api/montecarlo')
def api_montecarlo():
    """Return Monte Carlo simulation results (10K paths, confidence bands)."""
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
        return jsonify({'error': str(e)})


@app.route('/api/trade-analytics')
def api_trade_analytics():
    """Return trade segmentation analytics (exit reason, regime, sector, etc.)."""
    global _trade_analytics_cache, _trade_analytics_cache_time
    now = datetime.now()
    if _trade_analytics_cache and _trade_analytics_cache_time and \
       (now - _trade_analytics_cache_time).total_seconds() < TRADE_ANALYTICS_CACHE_SECONDS:
        return jsonify(_trade_analytics_cache)
    try:
        from compass_trade_analytics import COMPASSTradeAnalytics
        ta = COMPASSTradeAnalytics()
        results = ta.run_all()
        _trade_analytics_cache = results
        _trade_analytics_cache_time = now
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)})


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
        return jsonify({'error': str(e)})


@app.route('/api/execution-microstructure')
def api_execution_microstructure():
    """Return execution microstructure analysis (strategy comparison, capital tiers)."""
    global _exec_micro_cache, _exec_micro_cache_time
    now = datetime.now()
    if _exec_micro_cache and _exec_micro_cache_time and \
       (now - _exec_micro_cache_time).total_seconds() < EXEC_MICRO_CACHE_SECONDS:
        return jsonify(_exec_micro_cache)
    try:
        from compass_execution_microstructure import COMPASSExecutionMicrostructure
        em = COMPASSExecutionMicrostructure()
        results = em.run_all()
        _exec_micro_cache = results
        _exec_micro_cache_time = now
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)})


# ============================================================================
# ENGINE CONTROL API
# ============================================================================

@app.route('/api/engine/start', methods=['POST'])
def api_engine_start():
    """Start the live trading engine."""
    ok, msg = start_engine()
    return jsonify({'ok': ok, 'message': msg, 'status': _engine_status})


@app.route('/api/engine/stop', methods=['POST'])
def api_engine_stop():
    """Stop the live trading engine."""
    ok, msg = stop_engine()
    return jsonify({'ok': ok, 'message': msg, 'status': _engine_status})


@app.route('/api/engine/status')
def api_engine_status():
    """Get current engine status."""
    state = read_state()
    cycles_completed, engine_iterations = _health_cycle_counts(state)
    payload = dict(_engine_status)
    payload['engine_iterations'] = engine_iterations
    payload['cycles_completed'] = cycles_completed
    return jsonify(payload)


@app.route('/api/overlay-status')
def api_overlay_status():
    """Return current overlay signals and diagnostics."""
    engine = _live_engine  # Capture once to avoid TOCTOU race
    # Prefer live engine data (state file may be stale after restart)
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


@app.route('/api/execution-stats')
def api_execution_stats():
    try:
        state = read_state()
        order_history = state.get('order_history', []) if state else []

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




def _maybe_regenerate_interpretation(ml_dir, entries, insights, bt_stats=None):
    interp_path = os.path.join(ml_dir, 'interpretation.md')
    # Check staleness: regenerate if file missing or 5+ days old
    try:
        mtime = os.path.getmtime(interp_path)
        age_days = (time_module.time() - mtime) / 86400
        if age_days < 5:
            return
    except OSError:
        pass  # file missing → regenerate

    # Count entries by type
    n_entries = sum(1 for r in entries if r.get('_type') == 'decision' and r.get('decision_type') == 'entry')
    n_exits = sum(1 for r in entries if r.get('_type') == 'decision' and r.get('decision_type') == 'exit')
    n_skips = sum(1 for r in entries if r.get('_type') == 'decision' and r.get('decision_type') == 'skip')
    n_snapshots = sum(1 for r in entries if r.get('_type') == 'snapshot')
    n_outcomes = sum(1 for r in entries if r.get('_type') == 'outcome')
    n_decisions = n_entries + n_exits + n_skips

    # Phase info
    phase = insights.get('learning_phase', 1)
    trading_days = insights.get('trading_days', 0)
    days_to_phase2 = max(0, 63 - trading_days)

    # Portfolio analytics
    pa = insights.get('portfolio_analytics', {})
    current_value = pa.get('current_value', 0)
    total_return = pa.get('total_return', 0)
    max_dd = pa.get('max_drawdown', 0)
    daily_sharpe = pa.get('daily_sharpe_annualized')

    # Trade analytics
    ta = insights.get('trade_analytics', {})
    overall = ta.get('overall', {})
    n_trades = overall.get('n', 0)
    win_rate = overall.get('win_rate')
    mean_return = overall.get('mean_return')
    stop_rate = overall.get('stop_rate')
    avg_days = overall.get('avg_days_held')
    best_trade = overall.get('best')
    worst_trade = overall.get('worst')

    # Regime distribution from snapshots
    regime_counts = {}
    snapshots = [r for r in entries if r.get('_type') == 'snapshot']
    for s in snapshots:
        bucket = s.get('regime_bucket', 'unknown')
        regime_counts[bucket] = regime_counts.get(bucket, 0) + 1

    # Exit reason breakdown
    by_exit = ta.get('by_exit_reason', {})

    # Recent activity (last 5 decisions)
    decisions = [r for r in entries if r.get('_type') == 'decision']
    recent = decisions[-5:] if len(decisions) > 5 else decisions

    # Outcome summaries
    outcomes = [r for r in entries if r.get('_type') == 'outcome']

    # Build markdown
    lines = []
    lines.append('### System Status\n')
    lines.append(f'COMPASS ML Learning is in **Phase {phase}** (data collection). {trading_days} trading days logged.')
    if phase < 2:
        lines.append(f' ML models activate at Phase 2 (~{days_to_phase2} trading days remaining).\n')
    else:
        lines.append('\n')

    lines.append('### Data Summary\n')
    lines.append(f'- **{n_decisions} decisions** logged: {n_entries} entries, {n_exits} exits, {n_skips} skips')
    lines.append(f'- **{n_snapshots} daily snapshots** tracking portfolio evolution')
    lines.append(f'- **{n_outcomes} completed trades** with full outcome data\n')

    lines.append('### Portfolio Performance\n')
    if current_value:
        lines.append(f'- Current value: **${current_value:,.0f}**')
        lines.append(f'- Total return: **{total_return * 100:+.2f}%**')
        lines.append(f'- Max drawdown: **{max_dd * 100:.2f}%**')
        if daily_sharpe is not None:
            lines.append(f'- Daily Sharpe (annualized): **{daily_sharpe:.2f}**')
    else:
        lines.append('- Insufficient data')
    lines.append('')

    lines.append('### Trade Analysis\n')
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

        # Individual outcome details
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
        lines.append('- No completed trades yet')
    lines.append('')

    lines.append('### Regime Observations\n')
    if regime_counts:
        total_snaps = sum(regime_counts.values())
        for bucket, count in sorted(regime_counts.items(), key=lambda x: -x[1]):
            pct = count / total_snaps * 100
            lines.append(f'- **{bucket}**: {count} days ({pct:.0f}%)')
    else:
        lines.append('- No regime data yet')
    lines.append('')

    if by_exit:
        lines.append('### Exit Reason Breakdown\n')
        for reason, stats in by_exit.items():
            n = stats.get('n', 0)
            mr = stats.get('mean_return')
            wr = stats.get('win_rate')
            reason_label = reason.replace('_', ' ').replace('position stop adaptive', 'adaptive stop').title()
            mr_str = f'{mr * 100:+.1f}%' if mr is not None else '--'
            wr_str = f'{wr * 100:.0f}%' if wr is not None else '--'
            lines.append(f'- **{reason_label}** ({n} trades): avg return {mr_str}, win rate {wr_str}')
        lines.append('')

    lines.append('### Recent Activity\n')
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
        lines.append('- No recent decisions')
    lines.append('')

    lines.append('### Next Milestone\n')
    if phase < 2:
        lines.append(f'Phase 2 ML begins in ~{days_to_phase2} trading days. Continue collecting entry/exit decisions and completed trade outcomes.')
    else:
        lines.append(f'Phase {phase} active. ML models are being trained on accumulated data.')
    lines.append('')

    # Backtest context
    if bt_stats:
        lines.append('### Backtest Reference (HYDRA + EFA/MSCI World)\n')
        lines.append(f'- Period: **{bt_stats.get("start_date", "?")}** to **{bt_stats.get("end_date", "?")}** ({bt_stats.get("years", "?")} years)')
        bt_cagr = bt_stats.get('cagr', 0)
        lines.append(f'- CAGR: **{bt_cagr * 100:.1f}%**')
        lines.append(f'- Sharpe: **{bt_stats.get("sharpe", 0):.3f}**')
        bt_dd = bt_stats.get('max_drawdown', 0)
        lines.append(f'- Max Drawdown: **{bt_dd * 100:.1f}%**')
        bt_ret = bt_stats.get('total_return', 0)
        lines.append(f'- Total Return: **{bt_ret * 100:.1f}%** (${bt_stats.get("start_value", 0):,.0f} → ${bt_stats.get("end_value", 0):,.0f})')
        lines.append(f'- Trading Days: **{bt_stats.get("trading_days", 0):,}**')
        lines.append('')
        if trading_days > 0 and total_return:
            lines.append('### Live vs Backtest\n')
            live_ann = ((1 + total_return) ** (252 / max(1, trading_days))) - 1 if trading_days > 0 else 0
            lines.append(f'- Live annualized return: **{live_ann * 100:+.1f}%** vs backtest CAGR **{bt_cagr * 100:.1f}%**')
            if live_ann < bt_cagr * 0.5:
                lines.append('- **Warning**: Live performance significantly below backtest expectations. Normal for early days with small sample size.')
            elif live_ann > bt_cagr * 1.5:
                lines.append('- Live performance above backtest — may indicate favorable market conditions.')
            else:
                lines.append('- Live performance tracking within expected range of backtest.')
            lines.append('')

    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines.append(f'---\n*Auto-generated on {now_str}. Refreshes every 5 days.*')

    md = '\n'.join(lines)
    try:
        with open(interp_path, 'w', encoding='utf-8') as f:
            f.write(md)
    except Exception as e:
        logger.warning(f"_maybe_regenerate_interpretation failed: {e}")


@app.route('/api/ml-diagnostics')
def api_ml_diagnostics():
    ml_dir = os.path.join(STATE_DIR, 'ml_learning')
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
                        total_decisions += 1
                        try:
                            rec = json.loads(line)
                            ts = rec.get('timestamp', rec.get('date', ''))
                            if ts:
                                last_decision_date = str(ts)[:10]
                        except Exception:
                            pass

        total_outcomes = 0
        if os.path.exists(outcomes_path):
            with open(outcomes_path, 'r') as f:
                for line in f:
                    if line.strip():
                        total_outcomes += 1

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


@app.route('/api/ml-learning')
def api_ml_learning():
    """Return ML learning log entries, insights, and interpretation."""
    ml_dir = os.path.join('state', 'ml_learning')
    entries = []

    # Read JSONL files
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
            except Exception as e:
                logger.warning(f"api_ml_learning failed: {e}")

    # Sort by timestamp/date
    def sort_key(r):
        return r.get('timestamp', r.get('date', ''))
    entries.sort(key=sort_key)

    # Read insights (sanitize NaN which breaks JSON standard / jsonify)
    insights = {}
    insights_path = os.path.join(ml_dir, 'insights.json')
    if os.path.exists(insights_path):
        try:
            insights = _load_json_with_invalid_constants(insights_path)
        except Exception as e:
            logger.warning(f"api_ml_learning failed: {e}")

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
                values = [float(r['value']) for r in bt_rows]
                start_val = 100000.0
                end_val = values[-1]
                n_bt_days = len(values)
                years = n_bt_days / 252.0
                total_bt_return = (end_val / start_val) - 1
                cagr = (end_val / start_val) ** (1 / years) - 1 if years > 0 else 0
                daily_rets = [(values[i] - values[i-1]) / values[i-1] for i in range(1, len(values))]
                import statistics
                dr_mean = statistics.mean(daily_rets) if daily_rets else 0
                dr_std = statistics.stdev(daily_rets) if len(daily_rets) > 1 else 1
                sharpe = dr_mean / dr_std * (252 ** 0.5) if dr_std > 0 else 0
                peak_val = values[0]
                max_dd = 0
                for v in values:
                    if v > peak_val:
                        peak_val = v
                    dd = (v - peak_val) / peak_val
                    if dd < max_dd:
                        max_dd = dd
                bt_stats = {
                    'start_date': bt_rows[0].get('date', ''),
                    'end_date': bt_rows[-1].get('date', ''),
                    'trading_days': n_bt_days,
                    'years': round(years, 1),
                    'start_value': round(start_val, 0),
                    'end_value': round(end_val, 0),
                    'total_return': round(total_bt_return, 4),
                    'cagr': round(cagr, 4),
                    'sharpe': round(sharpe, 3),
                    'max_drawdown': round(max_dd, 4),
                }
        except Exception as e:
            logger.warning(f"api_ml_learning failed: {e}")

    all_entries = backtest_entries + entries
    all_entries.sort(key=lambda r: r.get('timestamp', r.get('date', '')))

    # Auto-regenerate interpretation if stale (5+ days)
    _maybe_regenerate_interpretation(ml_dir, entries, insights, bt_stats)

    # Read interpretation
    interpretation = ''
    interp_path = os.path.join(ml_dir, 'interpretation.md')
    if os.path.exists(interp_path):
        try:
            with open(interp_path, 'r') as f:
                interpretation = f.read()
        except Exception as e:
            logger.warning(f"api_ml_learning failed: {e}")

    # Compute KPIs from loaded data
    outcomes = [r for r in entries if r.get('_type') == 'outcome']
    decisions = [r for r in entries if r.get('_type') == 'decision']
    snapshots = [r for r in entries if r.get('_type') == 'snapshot']
    n_entries = sum(1 for d in decisions if d.get('decision_type') == 'entry')
    n_exits = sum(1 for d in decisions if d.get('decision_type') == 'exit')

    trading_days = insights.get('trading_days', 0)
    phase = insights.get('learning_phase', 1)
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

    return jsonify({
        'log_entries': all_entries,
        'insights': insights,
        'interpretation': interpretation,
        'kpis': kpis,
    })


@app.route('/api/agent-scratchpad')
def api_agent_scratchpad():
    """Return today's HYDRA agent scratchpad entries."""
    sp_dir = os.path.join('state', 'agent_scratchpad')
    today = datetime.now().strftime('%Y-%m-%d')
    day = request.args.get('date', today)
    err = _validate_param(day, r'^\d{4}-\d{2}-\d{2}$', 'date')
    if err:
        return err
    entries = []
    path = os.path.join(sp_dir, f'{day}.jsonl')
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        entries.append(json.loads(line))
        except Exception as e:
            logger.warning(f"api_agent_scratchpad failed: {e}")
    # List available days
    available = []
    if os.path.isdir(sp_dir):
        available = sorted([f.replace('.jsonl', '') for f in os.listdir(sp_dir) if f.endswith('.jsonl')], reverse=True)
    return jsonify({'date': day, 'entries': entries, 'available_dates': available[:30]})


@app.route('/api/agent-heartbeat')
def api_agent_heartbeat():
    """Return HYDRA agent heartbeat status."""
    hb_path = os.path.join('state', 'agent_heartbeat.json')
    if not os.path.exists(hb_path):
        return jsonify({'alive': False, 'message': 'No heartbeat file found'})
    try:
        with open(hb_path, 'r') as f:
            data = json.load(f)
        # Check if heartbeat is recent (< 2 minutes)
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
        return jsonify({'alive': False, 'error': str(e)})


@app.route('/robots.txt')
def robots_txt():
    return app.response_class(
        "User-agent: *\nAllow: /\nSitemap: http://localhost:5000/sitemap.xml\n",
        mimetype='text/plain'
    )


@app.route('/sitemap.xml')
def sitemap_xml():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>http://localhost:5000/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>
</urlset>"""
    return app.response_class(xml, mimetype='application/xml')


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    # Ensure directories exist
    os.makedirs('state', exist_ok=True)
    os.makedirs('logs', exist_ok=True)

    # Configure rotating log handler for dashboard
    _dash_log_format = '%(asctime)s - %(levelname)s - %(message)s'
    _dash_formatter = logging.Formatter(_dash_log_format)
    _dash_file_handler = RotatingFileHandler(
        os.path.join(LOG_DIR, f'dashboard_{datetime.now().strftime("%Y%m%d")}.log'),
        maxBytes=50 * 1024 * 1024,  # 50 MB
        backupCount=5,
        encoding='utf-8',
    )
    _dash_file_handler.setFormatter(_dash_formatter)
    _dash_stream_handler = logging.StreamHandler(sys.stdout)
    _dash_stream_handler.setFormatter(_dash_formatter)
    logging.basicConfig(
        level=logging.INFO,
        format=_dash_log_format,
        handlers=[_dash_file_handler, _dash_stream_handler]
    )

    print("=" * 60)
    print("COMPASS v8.4 — Live Trading Dashboard")
    print("Adaptive Stops | Bull Override | Sector Limits")
    print("=" * 60)
    print(f"State file: {os.path.abspath(STATE_FILE)}")
    print(f"Log dir:    {os.path.abspath(LOG_DIR)}")
    print("Dashboard:  http://localhost:5000")
    print("Engine:     Controlled via dashboard UI")
    print(f"Stops:      Adaptive {COMPASS_CONFIG['STOP_FLOOR']:.0%} to {COMPASS_CONFIG['STOP_CEILING']:.0%} (vol-scaled)")
    print(f"Bull:       SPY > SMA200*{1+COMPASS_CONFIG['BULL_OVERRIDE_THRESHOLD']:.0%} -> +1 pos")
    print(f"Sectors:    Max {COMPASS_CONFIG['MAX_PER_SECTOR']} positions per sector")
    print(f"Leverage:   Max {COMPASS_CONFIG['LEVERAGE_MAX']:.1f}x (no leverage -- broker margin destroys value)")
    print("Execution:  Pre-close signal @ 15:30 ET -> same-day MOC (+0.79% CAGR)")
    print(f"Chassis:    async fetch | fill breaker {COMPASS_CONFIG['MAX_FILL_DEVIATION']:.0%} | "
          f"order timeout {COMPASS_CONFIG['ORDER_TIMEOUT_SECONDS']}s | data validation")
    print("=" * 60)

    # Auto-start engine on launch
    print("Starting live trading engine...")
    start_engine()

    # Start backtest auto-refresh scheduler
    start_backtest_scheduler()

    app.run(host='127.0.0.1', port=5000, debug=False, threaded=True)
