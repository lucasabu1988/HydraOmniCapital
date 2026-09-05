"""
Bulk download missing S&P 500 historical tickers from yfinance.
Saves to data_sources/yfinance_bulk/ as parquet files.
Tracks progress in data_sources/yfinance_download_state.json.
"""
import json
import os
import sys
import time
import logging
import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MISSING_FILE = os.path.join(BASE_DIR, 'data_sources', 'missing_tickers_master.json')
OUTPUT_DIR = os.path.join(BASE_DIR, 'data_sources', 'yfinance_bulk')
STATE_FILE = os.path.join(BASE_DIR, 'data_sources', 'yfinance_download_state.json')

START_DATE = '2000-01-01'
END_DATE = '2026-03-13'
BATCH_SIZE = 10
SLEEP_BETWEEN_BATCHES = 2


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {'completed': [], 'failed': [], 'no_data': []}


def save_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2)


def download_ticker(ticker, output_dir):
    try:
        df = yf.download(ticker, start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
        if df is None or len(df) < 10:
            return 'no_data'

        # Flatten multi-level columns if present
        if hasattr(df.columns, 'levels'):
            df.columns = df.columns.get_level_values(0)

        path = os.path.join(output_dir, f'{ticker}.parquet')
        df.to_parquet(path)
        return 'ok'
    except Exception as e:
        logger.warning(f'{ticker}: {e}')
        return 'error'


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(MISSING_FILE) as f:
        data = json.load(f)
    missing = data['missing_tickers']

    state = load_state()
    done = set(state['completed'] + state['failed'] + state['no_data'])
    todo = [t for t in missing if t not in done]

    logger.info(f'Total missing: {len(missing)}, Already processed: {len(done)}, Remaining: {len(todo)}')

    ok_count = len(state['completed'])
    fail_count = len(state['failed'])
    nodata_count = len(state['no_data'])

    for i in range(0, len(todo), BATCH_SIZE):
        batch = todo[i:i+BATCH_SIZE]
        logger.info(f'Batch {i//BATCH_SIZE + 1}: {batch}')

        for ticker in batch:
            result = download_ticker(ticker, OUTPUT_DIR)
            if result == 'ok':
                state['completed'].append(ticker)
                ok_count += 1
            elif result == 'no_data':
                state['no_data'].append(ticker)
                nodata_count += 1
            else:
                state['failed'].append(ticker)
                fail_count += 1

        save_state(state)
        total_done = ok_count + fail_count + nodata_count
        logger.info(f'Progress: {total_done}/{len(missing)} | OK: {ok_count} | No data: {nodata_count} | Failed: {fail_count}')

        if i + BATCH_SIZE < len(todo):
            time.sleep(SLEEP_BETWEEN_BATCHES)

    logger.info(f'\n=== FINAL ===')
    logger.info(f'Downloaded: {ok_count}')
    logger.info(f'No data (truly missing): {nodata_count}')
    logger.info(f'Errors: {fail_count}')
    logger.info(f'Truly missing tickers need alternative sources: {nodata_count + fail_count}')


if __name__ == '__main__':
    main()
