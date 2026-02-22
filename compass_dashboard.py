"""
COMPASS v8.2 — Live Dashboard + Trading Engine
================================================
All-in-one: Flask dashboard + COMPASSLive trading engine
running as a background thread. Single process, single launch.

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
# COMPASS v8.2 PARAMETERS (read-only reference, must match omnicapital_live.py)
# ============================================================================

COMPASS_CONFIG = {
    # Algorithm (LOCKED)
    'HOLD_DAYS': 5,
    'POSITION_STOP_LOSS': -0.08,
    'TRAILING_ACTIVATION': 0.05,
    'TRAILING_STOP_PCT': 0.03,
    'PORTFOLIO_STOP_LOSS': -0.15,
    'RECOVERY_STAGE_1_DAYS': 63,
    'RECOVERY_STAGE_2_DAYS': 126,
    'NUM_POSITIONS': 5,
    'NUM_POSITIONS_RISK_OFF': 2,
    'TARGET_VOL': 0.15,
    'LEVERAGE_MIN': 0.3,
    'LEVERAGE_MAX': 2.0,
    'INITIAL_CAPITAL': 100_000,
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
# BACKTEST AUTO-REFRESH SCHEDULER
# ============================================================================

BACKTEST_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'omnicapital_v8_compass.py')
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
    global _backtest_status

    while True:
        try:
            now_et = datetime.now(ZoneInfo('America/New_York'))
            today_str = now_et.strftime('%Y-%m-%d')
            is_weekday = now_et.weekday() < 5
            after_close = now_et.hour > 16 or (now_et.hour == 16 and now_et.minute >= 15)

            if is_weekday and after_close and _backtest_status['last_run_date'] != today_str and not _backtest_status['running']:
                # Time to run backtest
                print(f"[Backtest Scheduler] Starting daily backtest update at {now_et.strftime('%H:%M ET')}...")
                _backtest_status['running'] = True
                _backtest_status['started_at'] = datetime.now().isoformat()
                _backtest_status['last_run_date'] = today_str  # Set immediately to prevent duplicate runs

                try:
                    result = subprocess.run(
                        [sys.executable, BACKTEST_SCRIPT],
                        capture_output=True, text=True,
                        timeout=3600,  # 1 hour max
                        cwd=os.path.dirname(os.path.abspath(__file__))
                    )
                    if result.returncode == 0:
                        _backtest_status['last_result'] = 'success'
                        print(f"[Backtest Scheduler] Backtest completed successfully.")
                    else:
                        _backtest_status['last_result'] = f'exit code {result.returncode}'
                        print(f"[Backtest Scheduler] Backtest failed: exit code {result.returncode}")
                        if result.stderr:
                            print(f"[Backtest Scheduler] stderr: {result.stderr[:500]}")
                except subprocess.TimeoutExpired:
                    _backtest_status['last_result'] = 'timeout (1h)'
                    print("[Backtest Scheduler] Backtest timed out after 1 hour.")
                except Exception as e:
                    _backtest_status['last_result'] = str(e)
                    print(f"[Backtest Scheduler] Backtest error: {e}")
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

        # Try notifications
        try:
            from omnicapital_notifications import EmailNotifier
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    ext = json.load(f)
                email_cfg = ext.get('email', {})
                if email_cfg.get('smtp_server') and email_cfg.get('sender'):
                    trader.notifier = EmailNotifier(**email_cfg)
        except (ImportError, Exception):
            pass

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
_price_cache_time: Optional[datetime] = None


def _fetch_single_price(symbol: str) -> tuple:
    """Fetch a single price (for use in ThreadPoolExecutor)."""
    try:
        ticker = yf.Ticker(symbol)
        price = None
        try:
            price = ticker.fast_info.get('last_price', None)
        except Exception:
            pass
        if not price or price <= 0:
            hist = ticker.history(period='5d')
            if len(hist) > 0:
                price = float(hist['Close'].iloc[-1])
        if price and price > 0:
            return (symbol, float(price))
    except Exception:
        pass
    return (symbol, None)


def fetch_live_prices(symbols: List[str]) -> Dict[str, float]:
    """Fetch current prices via yfinance with 30-second cache (async)."""
    global _price_cache, _price_cache_time

    now = datetime.now()
    if _price_cache_time and (now - _price_cache_time).total_seconds() < PRICE_CACHE_SECONDS:
        missing = [s for s in symbols if s not in _price_cache]
        if not missing:
            return {s: _price_cache[s] for s in symbols if s in _price_cache}
    else:
        missing = symbols
        _price_cache = {}

    # Async fetch for all missing symbols
    if missing:
        with ThreadPoolExecutor(max_workers=min(10, len(missing))) as executor:
            futures = {executor.submit(_fetch_single_price, sym): sym for sym in missing}
            for future in as_completed(futures):
                try:
                    sym, price = future.result(timeout=30)
                    if price is not None:
                        _price_cache[sym] = price
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
        current_price = prices.get(symbol)
        entry_price = meta.get('entry_price', pos_data.get('avg_cost', 0))
        high_price = meta.get('high_price', entry_price)
        entry_day_index = meta.get('entry_day_index', 0)
        entry_date = meta.get('entry_date', '')
        shares = pos_data.get('shares', 0)

        if current_price and entry_price and entry_price > 0:
            pnl_pct = (current_price - entry_price) / entry_price
            pnl_dollar = (current_price - entry_price) * shares
            market_value = current_price * shares
        else:
            pnl_pct = 0
            pnl_dollar = 0
            market_value = entry_price * shares if entry_price else 0
            current_price = current_price or entry_price or 0

        days_held = trading_day - entry_day_index
        days_remaining = max(0, COMPASS_CONFIG['HOLD_DAYS'] - days_held)

        trailing_active = high_price > entry_price * (1 + COMPASS_CONFIG['TRAILING_ACTIVATION'])
        trailing_stop_level = high_price * (1 - COMPASS_CONFIG['TRAILING_STOP_PCT']) if trailing_active else None

        position_stop_level = entry_price * (1 + COMPASS_CONFIG['POSITION_STOP_LOSS'])

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
            'entry_date': entry_date,
            'near_stop': near_stop,
        })

    results.sort(key=lambda x: x['pnl_pct'], reverse=True)
    return results


def compute_portfolio_metrics(state: dict, prices: Dict[str, float]) -> dict:
    """Compute portfolio-level dashboard metrics."""
    portfolio_value = state.get('portfolio_value', 0)
    peak_value = state.get('peak_value', 0)
    cash = state.get('cash', 0)
    initial_capital = COMPASS_CONFIG['INITIAL_CAPITAL']

    drawdown = (portfolio_value - peak_value) / peak_value if peak_value > 0 else 0
    total_return = (portfolio_value - initial_capital) / initial_capital if initial_capital > 0 else 0

    invested = 0
    positions = state.get('positions', {})
    for sym, pos in positions.items():
        price = prices.get(sym, pos.get('avg_cost', 0))
        invested += pos.get('shares', 0) * price

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
        leverage = None

    if state.get('in_protection'):
        max_pos = 2 if state.get('protection_stage') == 1 else 3
    elif not state.get('current_regime', True):
        max_pos = COMPASS_CONFIG['NUM_POSITIONS_RISK_OFF']
    else:
        max_pos = COMPASS_CONFIG['NUM_POSITIONS']

    return {
        'portfolio_value': round(portfolio_value, 2),
        'cash': round(cash, 2),
        'invested': round(invested, 2),
        'peak_value': round(peak_value, 2),
        'drawdown': round(drawdown * 100, 2),
        'total_return': round(total_return * 100, 2),
        'initial_capital': initial_capital,
        'num_positions': len(positions),
        'max_positions': max_pos,
        'regime': regime_str,
        'regime_consecutive': state.get('regime_consecutive', 0),
        'in_protection': state.get('in_protection', False),
        'protection_stage': state.get('protection_stage', 0),
        'leverage': leverage,
        'recovery': recovery,
        'trading_day': state.get('trading_day_counter', 0),
        'last_trading_date': state.get('last_trading_date'),
        'stop_events': state.get('stop_events', []),
        'timestamp': state.get('timestamp', ''),
        'uptime_minutes': state.get('stats', {}).get('uptime_minutes', 0),
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
    symbols = ['SPY'] + list(state.get('positions', {}).keys())
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

    return jsonify({
        'status': 'online',
        'portfolio': portfolio,
        'position_details': position_details,
        'prices': prices,
        'universe': state.get('current_universe', []),
        'universe_year': state.get('universe_year'),
        'config': COMPASS_CONFIG,
        'chassis': chassis_status,
        'server_time': datetime.now().isoformat(),
        'engine': _engine_status,
    })


@app.route('/api/logs')
def api_logs():
    """Return recent log entries."""
    logs = read_recent_logs(max_lines=80)
    return jsonify({'logs': logs})


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
    df = df[df['date'] >= '2016-01-01'].copy()

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

    # Downsample every 5 rows
    sampled = df.iloc[::5]
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

    # --- Filter from 2016 (same as equity chart) ---
    merged = merged[merged['date_key'] >= '2016-01-01'].copy()
    if merged.empty:
        return jsonify({'error': 'No data from 2016 onward'})

    # --- Use real COMPASS values; scale SPY to same starting point ---
    compass_start = float(merged[val_col].iloc[0])
    spy_start = float(merged['close'].iloc[0])

    # COMPASS: real portfolio values (matches equity chart Y-axis)
    # SPY: scaled so it starts at the same value as COMPASS in 2016
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

    # --- Downsample every 5 rows ---
    sampled = merged.iloc[::5]
    result = []
    for _, row in sampled.iterrows():
        result.append({
            'date': row['date_key'].strftime('%Y-%m-%d'),
            'compass': round(float(row['compass_val']), 0),
            'spy': round(float(row['spy_val']), 0),
        })

    return jsonify({
        'data': result,
        'compass_cagr': round(compass_cagr, 2),
        'spy_cagr': round(spy_cagr, 2),
        'compass_final': round(compass_final, 0),
        'spy_final': round(spy_final, 0),
        'years': round(years, 1),
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
            raw_lev = 0.15 / vol_20d if vol_20d > 0.01 else 2.0
            est_leverage = max(0.3, min(2.0, raw_lev))

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
# SOCIAL FEED API (yfinance news + Reddit)
# ============================================================================

_social_cache: Dict = {}
_social_cache_time: Optional[datetime] = None
SOCIAL_CACHE_SECONDS = 300  # 5 min cache

import requests as http_requests  # for Reddit API


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


def fetch_social_feed(symbols: List[str]) -> List[dict]:
    """Fetch combined social feed for holdings (yfinance + Reddit)."""
    global _social_cache, _social_cache_time

    now = datetime.now()
    cache_key = ','.join(sorted(symbols))
    if _social_cache_time and (now - _social_cache_time).total_seconds() < SOCIAL_CACHE_SECONDS:
        cached = _social_cache.get(cache_key)
        if cached is not None:
            return cached

    # Fetch from both sources
    news_items = _fetch_yfinance_news(symbols, max_per=3)
    reddit_items = _fetch_reddit_posts(symbols, max_per=2)

    # Merge and sort by time (newest first)
    all_items = news_items + reddit_items
    all_items.sort(key=lambda x: x.get('time', ''), reverse=True)
    result = all_items[:20]

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
    print("COMPASS v8.2 — Live Trading Dashboard")
    print("=" * 60)
    print(f"State file: {os.path.abspath(STATE_FILE)}")
    print(f"Log dir:    {os.path.abspath(LOG_DIR)}")
    print(f"Dashboard:  http://localhost:5000")
    print(f"Engine:     Controlled via dashboard UI")
    print(f"Backtest:   Auto-refresh daily after 16:15 ET")
    print(f"Chassis:    async fetch | fill breaker {COMPASS_CONFIG['MAX_FILL_DEVIATION']:.0%} | "
          f"order timeout {COMPASS_CONFIG['ORDER_TIMEOUT_SECONDS']}s | data validation")
    print("=" * 60)

    # Auto-start engine on launch
    print("Starting live trading engine...")
    start_engine()

    # Start backtest auto-refresh scheduler
    start_backtest_scheduler()

    app.run(host='0.0.0.0', port=5000, debug=False)
