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
import subprocess
import threading
import time as time_module
from datetime import datetime, date, time as dtime, timedelta
from typing import Dict, Optional, List
from zoneinfo import ZoneInfo
import yfinance as yf
import numpy as np
import pandas as pd
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

# Suppress yfinance noise
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

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

# Moody's Aaa yield (FRED)
_aaa_yield_rate: Optional[float] = None
_aaa_yield_cache_time: Optional[datetime] = None
AAA_YIELD_CACHE_SECONDS = 3600
AAA_YIELD_FALLBACK = 4.8


def fetch_aaa_yield() -> float:
    """Fetch current Moody's Aaa Corporate Bond Yield from FRED. Cached 1 hour."""
    global _aaa_yield_rate, _aaa_yield_cache_time
    import requests as _req

    now = datetime.now()
    if _aaa_yield_rate is not None and _aaa_yield_cache_time and \
       (now - _aaa_yield_cache_time).total_seconds() < AAA_YIELD_CACHE_SECONDS:
        return _aaa_yield_rate

    try:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA&cosd=2025-01-01&coed=2026-12-31'
        resp = _req.get(url, timeout=10)
        resp.raise_for_status()
        lines = resp.text.strip().split('\n')
        for line in reversed(lines[1:]):
            parts = line.split(',')
            if len(parts) == 2 and parts[1].strip() != '.':
                try:
                    rate = float(parts[1].strip())
                    if 0 < rate < 20:
                        _aaa_yield_rate = rate
                        _aaa_yield_cache_time = now
                        return rate
                except ValueError:
                    continue
    except Exception:
        pass

    _aaa_yield_rate = AAA_YIELD_FALLBACK
    _aaa_yield_cache_time = now
    return _aaa_yield_rate

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
BACKTEST_CSV = os.path.join('backtests', 'v8_compass_daily.csv')

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
                        print(f"[Backtest Scheduler] Daily update completed successfully.")
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
        from omnicapital_live import COMPASSLive, CONFIG as LIVE_CONFIG

        config = LIVE_CONFIG.copy()

        # Load external config if available
        config_file = 'omnicapital_config.json'
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    json.load(f)  # validate JSON
            except Exception:
                pass

        trader = COMPASSLive(config)
        trader.load_state()

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
            except Exception:
                pass
        if not feed_ok:
            _engine_status['error'] = 'Data feed not connected'
            _engine_status['running'] = False
            return

        _live_engine = trader
        _engine_status['running'] = True
        _engine_status['started_at'] = datetime.now().isoformat()
        _engine_status['error'] = None
        _engine_status['cycles'] = 0

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


def start_engine():
    """Start the live engine in a background thread."""
    global _live_thread
    with _live_thread_lock:
        if _engine_status['running']:
            return False, 'Already running'
        _engine_status['running'] = True
        _engine_status['error'] = None
        _engine_status['cycles'] = 0
        _engine_status['started_at'] = datetime.now().isoformat()
        _live_thread = threading.Thread(target=_run_live_engine, daemon=True, name='COMPASS-Live')
        _live_thread.start()
        return True, 'Started'


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
        except Exception:
            pass
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
    except Exception:
        pass
    return (symbol, None)


def fetch_live_prices(symbols: List[str]) -> Dict[str, float]:
    """Fetch current prices via yfinance with 30-second cache (async).
    Returns {symbol: price_float} for backward compatibility.
    Previous close data stored in _prev_close_cache."""
    global _price_cache, _prev_close_cache, _price_cache_time

    now = datetime.now()
    if _price_cache_time and (now - _price_cache_time).total_seconds() < PRICE_CACHE_SECONDS:
        missing = [s for s in symbols if s not in _price_cache]
        if not missing:
            return {s: _price_cache[s] for s in symbols if s in _price_cache}
    else:
        missing = symbols
        _price_cache = {}
        _prev_close_cache = {}

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
                except Exception:
                    pass

    _price_cache_time = now
    return {s: _price_cache[s] for s in symbols if s in _price_cache}


# ============================================================================
# STATE READER
# ============================================================================

def read_state() -> Optional[dict]:
    """Read latest state from JSON file."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    pattern = os.path.join(STATE_DIR, 'compass_state_*.json')
    files = [f for f in glob.glob(pattern) if 'latest' not in f]
    if files:
        latest = max(files, key=os.path.getctime)
        try:
            with open(latest, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    return None


# ============================================================================
# LOG READER
# ============================================================================

def read_recent_logs(max_lines: int = 50) -> List[dict]:
    """Read recent log entries from today's log file."""
    today_str = datetime.now().strftime('%Y%m%d')
    log_file = os.path.join(LOG_DIR, f'compass_live_{today_str}.log')

    if not os.path.exists(log_file):
        from datetime import timedelta
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')
        log_file = os.path.join(LOG_DIR, f'compass_live_{yesterday}.log')
        if not os.path.exists(log_file):
            files = glob.glob(os.path.join(LOG_DIR, 'compass_live_*.log'))
            if not files:
                return []
            log_file = max(files, key=os.path.getctime)

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

def compute_position_details(state: dict, prices: Dict[str, float]) -> List[dict]:
    """Compute enriched position data for display."""
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
                today = date.today()
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
        })

    results.sort(key=lambda x: x['pnl_pct'], reverse=True)
    return results


def get_spy_start_price() -> Optional[float]:
    """Get SPY close price on live test start date (cached after first fetch).
    First tries cached value, then state files, then yfinance as fallback."""
    global _spy_start_price
    if _spy_start_price is not None:
        return _spy_start_price

    # Find earliest state file to determine live test start date
    state_files = sorted(glob.glob(os.path.join(STATE_DIR, 'compass_state_2*.json')))
    if not state_files:
        return None

    try:
        with open(state_files[0], 'r') as f:
            first_state = json.load(f)
        start_date = first_state.get('last_trading_date')
        if not start_date:
            return None

        spy = yf.Ticker('SPY')
        hist = spy.history(start=start_date, end=(date.fromisoformat(start_date) + timedelta(days=5)).isoformat())
        if not hist.empty:
            _spy_start_price = float(hist['Close'].iloc[0])
            return _spy_start_price
    except Exception:
        pass

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
    except Exception:
        return saved_day


def compute_portfolio_metrics(state: dict, prices: Dict[str, float]) -> dict:
    """Compute portfolio-level dashboard metrics."""
    portfolio_value = state.get('portfolio_value', 0)
    peak_value = state.get('peak_value', 0)
    cash = state.get('cash', 0)
    initial_capital = COMPASS_CONFIG['INITIAL_CAPITAL']

    # Recompute invested value with live prices if available
    invested = 0
    positions = state.get('positions', {})
    for sym, pos in positions.items():
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

    # SPY benchmark return over same live test period
    spy_start = get_spy_start_price()
    spy_current = prices.get('SPY')
    if spy_start and spy_current and spy_start > 0:
        spy_return = round((spy_current - spy_start) / spy_start * 100, 2)
    else:
        spy_return = None

    # Cash yield (Moody's Aaa IG Corporate)
    aaa_rate = fetch_aaa_yield()
    trading_days_elapsed = _compute_real_trading_day(state)
    daily_yield = cash * (aaa_rate / 100 / 252) if cash > 0 else 0
    accumulated_yield = cash * (aaa_rate / 100 / 252) * trading_days_elapsed if cash > 0 else 0

    return {
        'portfolio_value': round(portfolio_value, 2),
        'cash': round(cash, 2),
        'invested': round(invested, 2),
        'peak_value': round(peak_value, 2),
        'drawdown': round(drawdown * 100, 2),
        'total_return': round(total_return * 100, 2),
        'spy_return': spy_return,
        'initial_capital': initial_capital,
        'num_positions': len(positions),
        'max_positions': max_pos,
        'regime': regime_str,
        'regime_score': round(regime_score, 2),
        'regime_consecutive': state.get('regime_consecutive', 0),
        'in_protection': state.get('in_protection', False),
        'protection_stage': state.get('protection_stage', 0),
        'leverage': leverage,
        'recovery': recovery,
        'trading_day': trading_days_elapsed,
        'last_trading_date': state.get('last_trading_date'),
        'stop_events': state.get('stop_events', []),
        'timestamp': state.get('timestamp', ''),
        'uptime_minutes': state.get('stats', {}).get('uptime_minutes', 0),
        'aaa_rate': round(aaa_rate, 2),
        'daily_yield': round(daily_yield, 2),
        'accumulated_yield': round(accumulated_yield, 2),
    }


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
    state = read_state()

    if not state:
        return jsonify({
            'status': 'offline',
            'error': 'No state file found',
            'server_time': datetime.now().isoformat(),
            'engine': _engine_status,
        })

    # Collect all symbols for price fetching
    symbols = ['SPY', '^GSPC', 'ES=F', 'NQ=F', '^TNX', 'DX-Y.NYB'] + list(state.get('positions', {}).keys())
    symbols = list(set(symbols))
    prices = fetch_live_prices(symbols)

    position_details = compute_position_details(state, prices)
    portfolio = compute_portfolio_metrics(state, prices)

    # Chassis status from COMPASS live engine
    chassis_status = {
        'async_fetching': True,
        'order_timeout_seconds': COMPASS_CONFIG['ORDER_TIMEOUT_SECONDS'],
        'max_fill_deviation': COMPASS_CONFIG['MAX_FILL_DEVIATION'],
        'data_validation': True,
        'max_price_change_pct': COMPASS_CONFIG['MAX_PRICE_CHANGE_PCT'],
    }

    if _live_engine and hasattr(_live_engine, 'validator'):
        try:
            chassis_status['validator_stats'] = _live_engine.validator.get_stats()
        except Exception:
            pass

    if _live_engine and hasattr(_live_engine, 'broker'):
        try:
            stale = _live_engine.broker.check_stale_orders(
                COMPASS_CONFIG['ORDER_TIMEOUT_SECONDS']
            )
            chassis_status['stale_orders'] = len(stale)
        except Exception:
            chassis_status['stale_orders'] = 0

    # Pre-close window status
    now_et = datetime.now(ET)
    is_weekday = now_et.weekday() < 5
    current_time = now_et.time()
    preclose_signal_time = dtime(15, 30)
    moc_deadline = dtime(15, 50)

    preclose_entries_done = False
    if _live_engine and hasattr(_live_engine, '_preclose_entries_done'):
        preclose_entries_done = _live_engine._preclose_entries_done

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
    if _live_engine and hasattr(_live_engine, 'broker'):
        try:
            history = getattr(_live_engine.broker, 'order_history', [])
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
                today_is = [t.get('is_bps') for t in getattr(_live_engine, 'trades_today', [])
                            if t.get('is_bps') is not None]
                if today_is:
                    is_metrics['today_avg_is_bps'] = round(sum(today_is) / len(today_is), 2)
                    is_metrics['today_fills'] = len(today_is)
        except Exception:
            pass

    return jsonify({
        'status': 'online',
        'portfolio': portfolio,
        'position_details': position_details,
        'prices': prices,
        'prev_closes': _prev_close_cache,
        'universe': state.get('current_universe', []),
        'universe_year': state.get('universe_year'),
        'config': COMPASS_CONFIG,
        'chassis': chassis_status,
        'preclose': preclose_status,
        'implementation_shortfall': is_metrics,
        'server_time': datetime.now().isoformat(),
        'engine': _engine_status,
    })


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

            positions = state.get('positions', {})
            position_meta = state.get('position_meta', {})
            # Fetch ^GSPC (S&P 500 index) — cycle_log stores index values, not SPY ETF
            symbols = list(positions.keys()) + ['^GSPC']
            prices = fetch_live_prices(symbols)

            # Portfolio value = sum(shares * current_price) + cash
            portfolio_now = state.get('cash', 0)
            for sym, pos in positions.items():
                price = prices.get(sym)
                if price:
                    portfolio_now += pos.get('shares', 0) * price
                else:
                    meta = position_meta.get(sym, {})
                    portfolio_now += pos.get('shares', 0) * meta.get('entry_price', pos.get('avg_cost', 0))

            port_start = c.get('portfolio_start')
            if port_start and port_start > 0:
                c['portfolio_end'] = round(portfolio_now, 2)
                c['compass_return'] = round((portfolio_now / port_start - 1) * 100, 2)

            # SPY return (use ^GSPC index to match spy_start stored in cycle_log)
            gspc_price = prices.get('^GSPC')
            spy_start = c.get('spy_start')
            if gspc_price and spy_start and spy_start > 0:
                c['spy_end'] = round(gspc_price, 2)
                c['spy_return'] = round((gspc_price / spy_start - 1) * 100, 2)

            # Alpha
            if c.get('compass_return') is not None and c.get('spy_return') is not None:
                c['alpha'] = round(c['compass_return'] - c['spy_return'], 2)
        except Exception:
            pass

    return jsonify(cycles)


@app.route('/api/live-chart')
def api_live_chart():
    """Return daily COMPASS vs S&P 500 indexed performance since live test start."""
    import yfinance as yf

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
    except Exception:
        pass

    # Use live SPY price for today (matches banner real-time value)
    today_str = date.today().strftime('%Y-%m-%d')
    if today_str in [d for d in dates]:
        try:
            live_spy = fetch_live_prices(['SPY'])
            if 'SPY' in live_spy:
                spy_data[today_str] = live_spy['SPY']
        except Exception:
            pass

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

    return jsonify({
        'dates': result_dates,
        'compass': result_compass,
        'spy': result_spy,
        'start_date': start_date,
    })


@app.route('/api/equity')
def api_equity():
    """Return COMPASS equity curve data."""
    csv_path = os.path.join('backtests', 'v8_compass_daily.csv')

    if not os.path.exists(csv_path):
        return jsonify({'equity': [], 'milestones': [], 'error': 'No backtest data'})

    try:
        df = pd.read_csv(csv_path, parse_dates=['date'])
    except Exception:
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

    # --- Net equity curve (Signal - 2.0% fixed annual execution costs) ---
    # Net CAGR = Signal CAGR - 2.0%.  Synthesis: net(t) = signal(t) * ((1+net)/(1+signal))^t
    import numpy as np
    EXECUTION_COST = 0.02  # 2.0% annual (MOC slippage + commissions)
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
    csv_path = os.path.join('backtests', 'v84_compass_daily.csv')
    if not os.path.exists(csv_path):
        csv_path = os.path.join('backtests', 'v8_compass_daily.csv')
    if not os.path.exists(csv_path):
        return jsonify({'error': 'No backtest data'})

    try:
        df = pd.read_csv(csv_path, parse_dates=['date'])
    except Exception:
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
        except Exception:
            pass

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
    """Return backtest data freshness and scheduler status."""
    result = {
        'running': _backtest_status['running'],
        'last_result': _backtest_status['last_result'],
        'last_run_date': _backtest_status['last_run_date'],
        'started_at': _backtest_status['started_at'],
        'completed_at': _backtest_status['completed_at'],
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
    except Exception:
        pass
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
    except Exception:
        pass

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
    if _live_engine and hasattr(_live_engine, 'validator'):
        try:
            stats = _live_engine.validator.get_stats()
            rejection_rate = stats.get('rejection_rate', 0)
            chassis_info['validator_rejection_rate'] = round(rejection_rate * 100, 1)
            # Flag if rejection rate is unusually high (>10%)
            if rejection_rate > 0.10:
                chassis_info['data_validation_warning'] = 'High rejection rate'
                chassis_ok = False
        except Exception:
            pass
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

import requests as http_requests  # for external APIs
import xml.etree.ElementTree as XmlET
import re as _re


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
        except Exception:
            pass
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
        except Exception:
            pass
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
        except Exception:
            pass
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
        except Exception:
            pass
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

    # Fetch from all sources
    news_items = _fetch_yfinance_news(symbols, max_per=3)
    reddit_items = _fetch_reddit_posts(symbols, max_per=2)
    sa_items = _fetch_seekingalpha_news(symbols, max_per=2)
    sec_items = _fetch_sec_filings(symbols, max_per=2)
    google_items = _fetch_google_news(symbols, max_per=2)
    mw_items = _fetch_marketwatch_news(max_items=5)

    # Merge and sort by time (newest first)
    all_items = news_items + reddit_items + sa_items + sec_items + google_items + mw_items
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


# ============================================================================
# ANALYTICS API (Monte Carlo, Trade Analytics, Data Quality)
# ============================================================================

_montecarlo_cache = None
_montecarlo_cache_time = None
MONTECARLO_CACHE_SECONDS = 3600

_trade_analytics_cache = None
_trade_analytics_cache_time = None
TRADE_ANALYTICS_CACHE_SECONDS = 3600

_data_quality_cache = None
_data_quality_cache_time = None
DATA_QUALITY_CACHE_SECONDS = 1800

_exec_micro_cache = None
_exec_micro_cache_time = None
EXEC_MICRO_CACHE_SECONDS = 3600   # 1 hour (static backtest analysis)


@app.route('/api/montecarlo')
def api_montecarlo():
    """Return Monte Carlo simulation results (10K paths, confidence bands)."""
    global _montecarlo_cache, _montecarlo_cache_time
    now = datetime.now()
    if _montecarlo_cache and _montecarlo_cache_time and \
       (now - _montecarlo_cache_time).total_seconds() < MONTECARLO_CACHE_SECONDS:
        return jsonify(_montecarlo_cache)
    try:
        from compass_montecarlo import COMPASSMonteCarlo
        mc = COMPASSMonteCarlo()
        results = mc.run_all()
        _montecarlo_cache = results
        _montecarlo_cache_time = now
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
    return jsonify(_engine_status)


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    # Ensure directories exist
    os.makedirs('state', exist_ok=True)
    os.makedirs('logs', exist_ok=True)

    print("=" * 60)
    print("COMPASS v8.4 — Live Trading Dashboard")
    print("Adaptive Stops | Bull Override | Sector Limits")
    print("=" * 60)
    print(f"State file: {os.path.abspath(STATE_FILE)}")
    print(f"Log dir:    {os.path.abspath(LOG_DIR)}")
    print(f"Dashboard:  http://localhost:5000")
    print(f"Engine:     Controlled via dashboard UI")
    print(f"Stops:      Adaptive {COMPASS_CONFIG['STOP_FLOOR']:.0%} to {COMPASS_CONFIG['STOP_CEILING']:.0%} (vol-scaled)")
    print(f"Bull:       SPY > SMA200*{1+COMPASS_CONFIG['BULL_OVERRIDE_THRESHOLD']:.0%} -> +1 pos")
    print(f"Sectors:    Max {COMPASS_CONFIG['MAX_PER_SECTOR']} positions per sector")
    print(f"Leverage:   Max {COMPASS_CONFIG['LEVERAGE_MAX']:.1f}x (no leverage -- broker margin destroys value)")
    print(f"Execution:  Pre-close signal @ 15:30 ET -> same-day MOC (+0.79% CAGR)")
    print(f"Chassis:    async fetch | fill breaker {COMPASS_CONFIG['MAX_FILL_DEVIATION']:.0%} | "
          f"order timeout {COMPASS_CONFIG['ORDER_TIMEOUT_SECONDS']}s | data validation")
    print("=" * 60)

    # Auto-start engine on launch
    print("Starting live trading engine...")
    start_engine()

    # Start backtest auto-refresh scheduler
    start_backtest_scheduler()

    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
