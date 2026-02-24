"""
Refresh parquet data cache with latest data from yfinance.
Updates all ticker files in data_cache_parquet/ through today.
"""

import os
import sys
import pandas as pd
import yfinance as yf
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(SCRIPT_DIR, 'data_cache_parquet')
START_DATE = '2000-01-01'

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
    'PANW', 'NFLX', 'COF',  # Additional tickers from SECTOR_MAP
    'SPY',  # Regime filter
]


def refresh_cache():
    """Download fresh data for all tickers and save as parquet."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    today = datetime.now().strftime('%Y-%m-%d')

    # Deduplicate
    tickers = sorted(set(BROAD_POOL))
    total = len(tickers)
    updated = 0
    failed = []

    print(f"Refreshing {total} tickers through {today}...")
    print()

    for i, symbol in enumerate(tickers):
        pq_file = os.path.join(CACHE_DIR, f'{symbol}.parquet')

        try:
            df = yf.download(symbol, start=START_DATE, end=today, progress=False)
            if not df.empty and len(df) > 100:
                # Flatten multi-level columns from yfinance
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                df.to_parquet(pq_file, compression='snappy')
                updated += 1
            else:
                failed.append(symbol)
        except Exception as e:
            failed.append(symbol)

        if (i + 1) % 20 == 0 or (i + 1) == total:
            print(f"  [{i+1}/{total}] Updated: {updated} | Failed: {len(failed)}")

    print()
    print(f"Done. {updated}/{total} tickers refreshed.")
    if failed:
        print(f"Failed: {', '.join(failed)}")

    # Update manifest
    manifest_file = os.path.join(CACHE_DIR, f'manifest_{START_DATE}_{today}.txt')
    with open(manifest_file, 'w') as f:
        f.write(f"symbols={updated}\ndate={datetime.now().isoformat()}\n")
        for sym in tickers:
            pq = os.path.join(CACHE_DIR, f'{sym}.parquet')
            if os.path.exists(pq):
                rows = len(pd.read_parquet(pq))
                f.write(f"{sym}: {rows} rows\n")


if __name__ == '__main__':
    refresh_cache()
