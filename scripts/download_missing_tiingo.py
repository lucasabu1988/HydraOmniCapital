"""
Bulk download missing S&P 500 tickers from Tiingo (free tier: 500 req/hr).
Focuses on tickers that yfinance CANNOT provide (truly delisted/bankrupt).
Saves to data_sources/tiingo_bulk/ as parquet files.

Usage:
    python scripts/download_missing_tiingo.py                    # uses hardcoded token
    python scripts/download_missing_tiingo.py --token YOUR_TOKEN
    TIINGO_TOKEN=xxx python scripts/download_missing_tiingo.py
"""
import json
import os
import sys
import time
import logging
import argparse
import pandas as pd
import urllib.request
import urllib.error
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YFINANCE_STATE = os.path.join(BASE_DIR, 'data_sources', 'yfinance_download_state.json')
MISSING_FILE = os.path.join(BASE_DIR, 'data_sources', 'missing_tickers_master.json')
OUTPUT_DIR = os.path.join(BASE_DIR, 'data_sources', 'tiingo_bulk')
STATE_FILE = os.path.join(BASE_DIR, 'data_sources', 'tiingo_download_state.json')

TIINGO_TOKEN_FALLBACK = '2b4b5626b2849123c9dac0769e418f9b0ccd2a56'
TIINGO_BASE = 'https://api.tiingo.com/tiingo/daily'
SLEEP_BETWEEN_DEFAULT = 3.0  # seconds — keeps us at ~1200/hr, well under 500/hr hard limit
SLEEP_BETWEEN = SLEEP_BETWEEN_DEFAULT
MAX_DAILY_RETURN = 0.80  # filter corrupted data


def tiingo_get(url, token, timeout=30):
    req = urllib.request.Request(url, headers={
        'Authorization': f'Token {token}',
        'Content-Type': 'application/json'
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as e:
        if e.code == 429:
            return None, 'rate_limited'
        if e.code == 404:
            return None, 'not_found'
        return None, f'http_{e.code}'
    except Exception as e:
        return None, str(e)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {'completed': [], 'failed': [], 'no_data': [], 'rate_limited_at': None}


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def get_target_tickers():
    """Get tickers that yfinance couldn't download (truly missing)."""
    # If yfinance has run, use its no_data list
    if os.path.exists(YFINANCE_STATE):
        with open(YFINANCE_STATE) as f:
            yf_state = json.load(f)
        targets = yf_state.get('no_data', []) + yf_state.get('failed', [])
        if targets:
            logger.info(f'Targeting {len(targets)} tickers that yfinance could not fetch')
            return sorted(set(targets))

    # Fallback: use full missing list
    with open(MISSING_FILE) as f:
        data = json.load(f)
    return data['missing_tickers']


def download_ticker(ticker, token):
    # Step 1: metadata
    meta_data, meta_err = tiingo_get(f'{TIINGO_BASE}/{ticker}', token)
    time.sleep(SLEEP_BETWEEN)

    if meta_err:
        return None, meta_err

    start = (meta_data.get('startDate') or '')[:10]
    end = (meta_data.get('endDate') or '')[:10]

    if not start:
        return None, 'no_date_range'

    # Step 2: full price history
    url = f'{TIINGO_BASE}/{ticker}/prices?startDate={start}&endDate={end}'
    prices, price_err = tiingo_get(url, token, timeout=60)
    time.sleep(SLEEP_BETWEEN)

    if price_err:
        return None, price_err

    if not prices or len(prices) < 10:
        return None, 'insufficient_data'

    # Convert to DataFrame
    df = pd.DataFrame(prices)
    df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
    df = df.set_index('date').sort_index()

    # Use adjusted columns
    col_map = {'adjOpen': 'Open', 'adjHigh': 'High', 'adjLow': 'Low',
               'adjClose': 'Close', 'adjVolume': 'Volume'}
    for src, dst in col_map.items():
        if src in df.columns:
            df[dst] = df[src]

    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna(subset=['Close'])

    # Quality filter: remove >80% daily returns
    returns = df['Close'].pct_change().abs()
    mask = returns <= MAX_DAILY_RETURN
    mask.iloc[0] = True  # keep first row
    df = df[mask]

    if len(df) < 10:
        return None, 'insufficient_after_filter'

    return df, None


def main():
    parser = argparse.ArgumentParser(description='Download missing tickers from Tiingo')
    parser.add_argument('--token', default=None, help='Tiingo API token')
    parser.add_argument('--sleep', type=float, default=SLEEP_BETWEEN_DEFAULT, help='Sleep between calls')
    args = parser.parse_args()

    global SLEEP_BETWEEN  # noqa
    SLEEP_BETWEEN = args.sleep

    token = os.environ.get('TIINGO_TOKEN') or args.token or TIINGO_TOKEN_FALLBACK
    logger.info(f'Using token: {token[:8]}...{token[-4:]}')

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    state = load_state()
    targets = get_target_tickers()

    done = set(state['completed'] + state['failed'] + state['no_data'])
    todo = [t for t in targets if t not in done]

    logger.info(f'Targets: {len(targets)}, Already done: {len(done)}, Remaining: {len(todo)}')

    ok_count = len(state['completed'])
    nodata_count = len(state['no_data'])
    fail_count = len(state['failed'])

    for i, ticker in enumerate(todo):
        logger.info(f'[{i+1}/{len(todo)}] {ticker}...')

        df, err = download_ticker(ticker, token)

        if err == 'rate_limited':
            logger.warning(f'Rate limited at {ticker}. Waiting 60s then retrying...')
            state['rate_limited_at'] = ticker
            save_state(state)
            time.sleep(60)
            # Retry once
            df, err = download_ticker(ticker, token)
            if err == 'rate_limited':
                logger.error('Still rate limited. Stopping. Run again later.')
                save_state(state)
                break

        if df is not None:
            path = os.path.join(OUTPUT_DIR, f'{ticker}.parquet')
            df.to_parquet(path)
            state['completed'].append(ticker)
            ok_count += 1
            logger.info(f'  OK: {len(df)} rows ({df.index[0].date()} to {df.index[-1].date()})')
        elif err in ('not_found', 'no_date_range', 'insufficient_data', 'insufficient_after_filter'):
            state['no_data'].append(ticker)
            nodata_count += 1
            logger.info(f'  No data: {err}')
        else:
            state['failed'].append(ticker)
            fail_count += 1
            logger.info(f'  Failed: {err}')

        save_state(state)

        if (i + 1) % 20 == 0:
            total = ok_count + nodata_count + fail_count
            logger.info(f'--- Progress: {total}/{len(targets)} | OK: {ok_count} | No data: {nodata_count} | Failed: {fail_count} ---')

    logger.info(f'\n=== FINAL ===')
    logger.info(f'Downloaded from Tiingo: {ok_count}')
    logger.info(f'Not on Tiingo: {nodata_count}')
    logger.info(f'Errors: {fail_count}')
    truly_missing = nodata_count + fail_count
    logger.info(f'Truly unfixable (need Norgate): {truly_missing}')


if __name__ == '__main__':
    main()
