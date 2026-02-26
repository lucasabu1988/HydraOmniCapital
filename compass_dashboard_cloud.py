"""
COMPASS v8.2 — Cloud Dashboard (Showcase)
==========================================
Full-featured Flask dashboard for Render.com deployment.
Shows live prices, backtest equity curves, trade analytics,
execution microstructure, social feed, and research paper.
NO live trading engine — showcase/portfolio mode.

Deploy: git push to GitHub → auto-deploy on Render.
"""

from flask import Flask, jsonify, render_template, request
import json
import os
import glob
import numpy as np
import pandas as pd
import logging
from datetime import datetime, date, timedelta, time as dtime
from zoneinfo import ZoneInfo
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

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

# ============================================================================
# COMPASS v8.2 PARAMETERS (read-only reference — ALGORITHM LOCKED)
# ============================================================================

COMPASS_CONFIG = {
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
    'LEVERAGE_MAX': 1.0,       # No leverage in production
    'INITIAL_CAPITAL': 100_000,
    'COMMISSION_PER_SHARE': 0.001,
    'ORDER_TIMEOUT_SECONDS': 300,
    'MAX_FILL_DEVIATION': 0.02,
    'MAX_PRICE_CHANGE_PCT': 0.20,
}

STATE_FILE = 'state/compass_state_latest.json'
STATE_DIR = 'state'
SPY_BENCHMARK_CSV = os.path.join('backtests', 'spy_benchmark.csv')

PRICE_CACHE_SECONDS = 30
SOCIAL_CACHE_SECONDS = 300  # 5 minutes

_spy_start_price = None

SHOWCASE_MODE = os.environ.get('COMPASS_MODE', 'showcase') == 'showcase'

# ============================================================================
# MOODY'S AAA YIELD (FRED)
# ============================================================================

_aaa_yield_rate: Optional[float] = None  # Annual % (e.g. 4.8 means 4.8%)
_aaa_yield_cache_time: Optional[datetime] = None
AAA_YIELD_CACHE_SECONDS = 3600  # refresh hourly
AAA_YIELD_FALLBACK = 4.8  # fallback if FRED unavailable


def fetch_aaa_yield() -> float:
    """Fetch current Moody's Aaa Corporate Bond Yield from FRED CSV endpoint.
    Returns annual yield as percentage (e.g. 4.8 for 4.8%). Cached for 1 hour."""
    global _aaa_yield_rate, _aaa_yield_cache_time

    now = datetime.now()
    if _aaa_yield_rate is not None and _aaa_yield_cache_time and \
       (now - _aaa_yield_cache_time).total_seconds() < AAA_YIELD_CACHE_SECONDS:
        return _aaa_yield_rate

    if not _HAS_REQUESTS:
        _aaa_yield_rate = AAA_YIELD_FALLBACK
        _aaa_yield_cache_time = now
        return _aaa_yield_rate

    try:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=AAA&cosd=2025-01-01&coed=2026-12-31'
        resp = http_requests.get(url, timeout=10)
        resp.raise_for_status()
        lines = resp.text.strip().split('\n')
        # Find last valid (non-".") value
        for line in reversed(lines[1:]):
            parts = line.split(',')
            if len(parts) == 2 and parts[1].strip() != '.':
                try:
                    rate = float(parts[1].strip())
                    if 0 < rate < 20:  # sanity check
                        _aaa_yield_rate = rate
                        _aaa_yield_cache_time = now
                        logger.info(f"Aaa yield fetched: {rate:.2f}%")
                        return rate
                except ValueError:
                    continue
    except Exception as e:
        logger.warning(f"FRED Aaa yield fetch failed: {e}")

    _aaa_yield_rate = AAA_YIELD_FALLBACK
    _aaa_yield_cache_time = now
    return _aaa_yield_rate


# ============================================================================
# DATA PRELOAD (at import time — shared across gunicorn workers via --preload)
# ============================================================================

_equity_df = None
_spy_df = None


def _preload_data():
    """Load CSV data at startup (not on first request)."""
    global _equity_df, _spy_df
    csv_path = os.path.join('backtests', 'v8_compass_daily.csv')
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
# PRICE CACHE (live prices via yfinance)
# ============================================================================

_price_cache: Dict[str, float] = {}
_price_cache_time: Optional[datetime] = None


def _fetch_single_price(symbol: str) -> tuple:
    """Fetch a single price (for use in ThreadPoolExecutor)."""
    if not _HAS_YFINANCE:
        return (symbol, None)
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
    """Fetch current prices via yfinance with 30-second cache."""
    global _price_cache, _price_cache_time

    if not _HAS_YFINANCE or not symbols:
        return {}

    now = datetime.now()
    if _price_cache_time and (now - _price_cache_time).total_seconds() < PRICE_CACHE_SECONDS:
        missing = [s for s in symbols if s not in _price_cache]
        if not missing:
            return {s: _price_cache[s] for s in symbols if s in _price_cache}
    else:
        missing = symbols
        _price_cache.clear()

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


def get_spy_start_price() -> Optional[float]:
    """Get SPY close price on live test start date (cached after first fetch)."""
    global _spy_start_price
    if _spy_start_price is not None:
        return _spy_start_price

    if not _HAS_YFINANCE:
        return None

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
        }

    regime_str = 'RISK_ON' if state.get('current_regime', True) else 'RISK_OFF'

    if state.get('in_protection'):
        leverage = 0.3 if state.get('protection_stage') == 1 else 1.0
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

    # SPY benchmark return over same live test period
    spy_start = get_spy_start_price()
    spy_current = prices.get('SPY') if prices else None
    if spy_start and spy_current and spy_start > 0:
        spy_return = round((spy_current - spy_start) / spy_start * 100, 2)
    else:
        spy_return = None

    # Cash yield (Moody's Aaa IG Corporate)
    aaa_rate = fetch_aaa_yield()  # annual % (e.g. 4.8)
    daily_yield = cash * (aaa_rate / 100 / 252) if cash > 0 else 0
    trading_days_elapsed = _compute_real_trading_day(state)
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
_data_quality_cache = None
_exec_micro_cache = None


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

    # Fetch live prices for positions + SPY
    symbols = ['SPY', '^GSPC'] + list(state.get('positions', {}).keys())
    symbols = list(set(symbols))
    prices = fetch_live_prices(symbols)

    position_details = compute_position_details(state, prices)
    portfolio = compute_portfolio_metrics(state, prices)

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
        'universe': state.get('current_universe', []),
        'universe_year': state.get('universe_year'),
        'config': COMPASS_CONFIG,
        'chassis': {},
        'preclose': preclose_status,
        'implementation_shortfall': {'available': False},
        'server_time': datetime.now().isoformat(),
        'engine': {
            'running': False,
            'started_at': None,
            'error': 'Showcase mode \u2014 view only',
            'cycles': 0,
        },
    })


@app.route('/api/logs')
def api_logs():
    """Return empty logs in showcase mode."""
    return jsonify({'logs': []})


@app.route('/api/cycle-log')
def api_cycle_log():
    """Return the 5-day cycle performance log (COMPASS vs SPY)."""
    log_file = os.path.join(STATE_DIR, 'cycle_log.json')
    if not os.path.exists(log_file):
        return jsonify([])
    try:
        with open(log_file, 'r') as f:
            return jsonify(json.load(f))
    except Exception:
        return jsonify([])


@app.route('/api/equity')
def api_equity():
    """Return COMPASS equity curve data (full period from 2000)."""
    df = _equity_df
    if df is None:
        csv_path = os.path.join('backtests', 'v8_compass_daily.csv')
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
        csv_path = os.path.join('backtests', 'v8_compass_daily.csv')
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
    if _montecarlo_cache:
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
    if _trade_analytics_cache:
        return jsonify(_trade_analytics_cache)
    try:
        from compass_trade_analytics import COMPASSTradeAnalytics
        ta = COMPASSTradeAnalytics()
        _trade_analytics_cache = ta.run_all()
        return jsonify(_trade_analytics_cache)
    except Exception as e:
        return jsonify({'error': f'Trade analytics unavailable: {str(e)}'})


@app.route('/api/data-quality')
def api_data_quality():
    """Return data pipeline quality scorecard (not available in showcase mode)."""
    return jsonify({'unavailable': True, 'message': 'Data pipeline runs locally — not available in showcase mode'})


@app.route('/api/execution-microstructure')
def api_execution_microstructure():
    """Return execution microstructure analysis."""
    global _exec_micro_cache
    if _exec_micro_cache:
        return jsonify(_exec_micro_cache)
    try:
        from compass_execution_microstructure import COMPASSExecutionMicrostructure
        em = COMPASSExecutionMicrostructure()
        _exec_micro_cache = em.run_all()
        return jsonify(_exec_micro_cache)
    except Exception as e:
        return jsonify({'error': f'Execution analysis unavailable: {str(e)}'})


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



# Terminal removed — replaced with WhatsApp contact FAB


# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print("=" * 60)
    print("COMPASS v8.2 \u2014 Cloud Dashboard (Showcase)")
    print("=" * 60)
    print(f"Port: {port}")
    print(f"Mode: {'SHOWCASE' if SHOWCASE_MODE else 'local'}")
    print(f"yfinance: {'available' if _HAS_YFINANCE else 'NOT available'}")
    print(f"requests: {'available' if _HAS_REQUESTS else 'NOT available'}")
    print(f"Equity data: {'loaded' if _equity_df is not None else 'NOT loaded'}")
    print(f"SPY data: {'loaded' if _spy_df is not None else 'NOT loaded'}")
    print("=" * 60)
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
