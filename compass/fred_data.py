"""
COMPASS v8.4 — FRED Macro Data Fetcher
Downloads and caches monetary/financial indicators for overlay backtesting.
All series from St. Louis FRED (free, no API key required).
"""

import os
import pandas as pd
import numpy as np
import logging

logger = logging.getLogger(__name__)

FRED_BASE_URL = 'https://fred.stlouisfed.org/graph/fredgraph.csv'
FRED_CACHE_DIR = 'data_cache/fred'

# Registry of all FRED series used by overlays
FRED_SERIES = {
    # Banking Stress Overlay
    'NFCI':          {'start': '1971-01-01', 'desc': 'Chicago Fed National Financial Conditions Index'},
    'STLFSI4':       {'start': '1993-12-01', 'desc': 'St. Louis Fed Financial Stress Index'},
    'BAMLH0A0HYM2':  {'start': '1996-12-31', 'desc': 'ICE BofA US High Yield OAS (pct, x100 for bps)'},
    # M2 Momentum
    'M2SL':          {'start': '1959-01-01', 'desc': 'M2 Money Stock (Billions USD, SA)'},
    # FOMC Surprise
    'DFF':           {'start': '1954-07-01', 'desc': 'Federal Funds Effective Rate (%)'},
    # Fed Emergency
    'WALCL':         {'start': '2002-12-18', 'desc': 'Fed Total Assets (Millions USD)'},
    # Cash Optimization
    'DTB3':          {'start': '1954-01-04', 'desc': '3-Month Treasury Bill Rate (%)'},
    # Base comparison (already cached by v84, but include for completeness)
    'AAA':           {'start': '1919-01-01', 'desc': "Moody's Aaa Corporate Bond Yield (%)"},
}


def download_fred_series(series_id: str, start: str = '1999-01-01',
                         end: str = '2026-12-31',
                         force_refresh: bool = False) -> pd.Series:
    """Download a single FRED series, cache to CSV, forward-fill to daily.

    Returns pd.Series indexed by DatetimeIndex (daily), or None on failure.
    """
    os.makedirs(FRED_CACHE_DIR, exist_ok=True)
    cache_file = os.path.join(FRED_CACHE_DIR, f'{series_id}.csv')

    if os.path.exists(cache_file) and not force_refresh:
        try:
            df = pd.read_csv(cache_file, parse_dates=['observation_date'],
                             index_col='observation_date')
            series = df.iloc[:, 0].dropna()
            daily = series.resample('D').ffill()
            return daily
        except Exception as e:
            logger.warning(f"Cache read failed for {series_id}: {e}")

    url = f'{FRED_BASE_URL}?id={series_id}&cosd={start}&coed={end}'
    print(f"  [FRED] Downloading {series_id}...", end=' ')

    try:
        df = pd.read_csv(url, parse_dates=['observation_date'],
                         index_col='observation_date')
        # FRED uses '.' for missing values
        col = df.columns[0]
        df[col] = pd.to_numeric(df[col], errors='coerce')
        df = df.dropna()

        # Cache raw data
        df.to_csv(cache_file)

        # Forward-fill to daily
        series = df.iloc[:, 0]
        daily = series.resample('D').ffill()
        print(f"{len(daily)} daily obs ({daily.index[0].date()} to {daily.index[-1].date()})")
        return daily

    except Exception as e:
        print(f"FAILED: {e}")
        logger.warning(f"FRED download failed for {series_id}: {e}")
        return None


def download_all_overlay_data(start: str = '1999-01-01',
                              end: str = '2026-12-31',
                              force_refresh: bool = False) -> dict:
    """Download all FRED series needed by overlays.

    Returns dict of {series_id: pd.Series} (daily, forward-filled).
    Missing series are None.
    """
    print("\n" + "=" * 60)
    print("DOWNLOADING FRED OVERLAY DATA")
    print("=" * 60)

    data = {}
    for series_id, meta in FRED_SERIES.items():
        series_start = meta['start'] if meta['start'] < start else start
        data[series_id] = download_fred_series(
            series_id, start=series_start, end=end,
            force_refresh=force_refresh
        )
        if data[series_id] is not None:
            desc = meta['desc']
            latest = data[series_id].iloc[-1] if len(data[series_id]) > 0 else 'N/A'
            print(f"    {series_id}: {desc} (latest={latest:.4f})")

    print(f"\n  Downloaded {sum(1 for v in data.values() if v is not None)}/{len(FRED_SERIES)} series")
    return data


def validate_fred_coverage(data: dict, start_date: str = '2000-01-03',
                           end_date: str = '2026-03-01') -> dict:
    """Validate that all FRED series cover the backtest period.

    Returns dict of {series_id: (first_date, last_date, pct_coverage, status)}.
    """
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    total_days = (end - start).days

    report = {}
    print("\n--- FRED Coverage Report ---")
    print(f"{'Series':<18} {'First':<12} {'Last':<12} {'Coverage':>8}  Status")
    print("-" * 65)

    for series_id, series in data.items():
        if series is None:
            report[series_id] = (None, None, 0.0, 'MISSING')
            print(f"{series_id:<18} {'N/A':<12} {'N/A':<12} {'0.0%':>8}  MISSING")
            continue

        # Clip to backtest range
        clipped = series[(series.index >= start) & (series.index <= end)]
        if len(clipped) == 0:
            report[series_id] = (None, None, 0.0, 'NO_DATA')
            print(f"{series_id:<18} {'N/A':<12} {'N/A':<12} {'0.0%':>8}  NO DATA IN RANGE")
            continue

        first = clipped.index[0].date()
        last = clipped.index[-1].date()
        coverage = len(clipped) / total_days * 100

        # Check for gaps > 5 business days
        diffs = clipped.index.to_series().diff().dt.days
        max_gap = diffs.max() if len(diffs) > 1 else 0

        status = 'OK' if coverage > 95 else 'PARTIAL'
        if max_gap > 7:
            status += f' (gap:{max_gap}d)'

        report[series_id] = (first, last, coverage, status)
        print(f"{series_id:<18} {str(first):<12} {str(last):<12} {coverage:>7.1f}%  {status}")

    print("-" * 65)
    ok_count = sum(1 for v in report.values() if 'OK' in v[3])
    print(f"  {ok_count}/{len(report)} series with >95% coverage\n")

    return report


if __name__ == '__main__':
    data = download_all_overlay_data()
    validate_fred_coverage(data)
