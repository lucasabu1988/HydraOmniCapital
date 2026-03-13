"""
Merge all data sources into a unified survivorship-bias-free dataset.
Priority order (highest quality first):
  1. data_cache_parquet/ (production yfinance data)
  2. data_sources/yfinance_bulk/ (newly downloaded from yfinance)
  3. data_sources/tiingo_bulk/ (delisted stocks from Tiingo)
  4. data_sources/eodhd/ (delisted stocks from EODHD)

Output: data_sources/merged_universe/ — one parquet per ticker, ready for backtest.
"""
import json
import os
import logging
import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOURCES = [
    ('data_cache_parquet', 'production'),
    ('data_sources/yfinance_bulk', 'yfinance'),
    ('data_sources/tiingo_bulk', 'tiingo'),
    ('data_sources/eodhd', 'eodhd'),
]

OUTPUT_DIR = os.path.join(BASE_DIR, 'data_sources', 'merged_universe')
REPORT_FILE = os.path.join(BASE_DIR, 'data_sources', 'merge_report.json')
MISSING_FILE = os.path.join(BASE_DIR, 'data_sources', 'missing_tickers_master.json')


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(MISSING_FILE) as f:
        master = json.load(f)
    all_tickers = set(master['missing_tickers'])

    # Also include production tickers
    prod_dir = os.path.join(BASE_DIR, 'data_cache_parquet')
    if os.path.exists(prod_dir):
        for f in os.listdir(prod_dir):
            if f.endswith('.parquet'):
                all_tickers.add(f.replace('.parquet', ''))

    logger.info(f'Total universe tickers: {len(all_tickers)}')

    # Track coverage
    covered = {}  # ticker -> source
    missing = set(all_tickers)

    for rel_path, source_name in SOURCES:
        src_dir = os.path.join(BASE_DIR, rel_path)
        if not os.path.exists(src_dir):
            logger.info(f'Source {source_name} ({rel_path}): not found, skipping')
            continue

        files = [f for f in os.listdir(src_dir) if f.endswith('.parquet')]
        logger.info(f'Source {source_name}: {len(files)} parquet files')

        added = 0
        for fname in files:
            ticker = fname.replace('.parquet', '')
            if ticker in covered:
                continue  # higher-priority source already has this ticker

            src_path = os.path.join(src_dir, fname)
            dst_path = os.path.join(OUTPUT_DIR, fname)

            try:
                df = pd.read_parquet(src_path)
                if len(df) < 10:
                    continue

                df.to_parquet(dst_path)
                covered[ticker] = source_name
                missing.discard(ticker)
                added += 1
            except Exception as e:
                logger.warning(f'Error reading {src_path}: {e}')

        logger.info(f'  Added {added} new tickers from {source_name}')

    # Report
    report = {
        'generated': pd.Timestamp.now().isoformat(),
        'total_universe': len(all_tickers),
        'covered': len(covered),
        'still_missing': len(missing),
        'coverage_pct': round(len(covered) / len(all_tickers) * 100, 1),
        'by_source': {},
        'still_missing_tickers': sorted(missing),
    }

    for source_name in ['production', 'yfinance', 'tiingo', 'eodhd']:
        count = sum(1 for v in covered.values() if v == source_name)
        report['by_source'][source_name] = count

    with open(REPORT_FILE, 'w') as f:
        json.dump(report, f, indent=2)

    logger.info(f'\n=== MERGE REPORT ===')
    logger.info(f'Total universe: {report["total_universe"]}')
    logger.info(f'Covered: {report["covered"]} ({report["coverage_pct"]}%)')
    logger.info(f'Still missing: {report["still_missing"]}')
    for src, count in report['by_source'].items():
        logger.info(f'  {src}: {count}')
    logger.info(f'Report saved to {REPORT_FILE}')


if __name__ == '__main__':
    main()
