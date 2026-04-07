"""Data loading and validation for hydra_backtest.

All functions here are pure — they take filesystem paths and date ranges
and return DataFrames, dicts, or series. No network I/O, no logging,
no computation of signals or execution of trades.
"""
import hashlib
import json
import os
import pickle
from typing import Dict, List

import pandas as pd

from hydra_backtest.errors import HydraDataError


# Config keys required by the backtest engine (ported from
# COMPASSLive._validate_config, omnicapital_live.py:1032).
_REQUIRED_KEYS = (
    'MOMENTUM_LOOKBACK', 'MOMENTUM_SKIP', 'MIN_MOMENTUM_STOCKS',
    'NUM_POSITIONS', 'NUM_POSITIONS_RISK_OFF', 'HOLD_DAYS',
    'POSITION_STOP_LOSS', 'TRAILING_ACTIVATION', 'TRAILING_STOP_PCT',
    'STOP_DAILY_VOL_MULT', 'STOP_FLOOR', 'STOP_CEILING',
    'MAX_PER_SECTOR', 'DD_SCALE_TIER1', 'DD_SCALE_TIER2', 'DD_SCALE_TIER3',
    'LEV_FULL', 'LEV_MID', 'LEV_FLOOR', 'CRASH_VEL_5D', 'CRASH_VEL_10D',
    'CRASH_LEVERAGE', 'CRASH_COOLDOWN',
    'TARGET_VOL', 'LEVERAGE_MAX', 'VOL_LOOKBACK', 'TOP_N',
    'INITIAL_CAPITAL', 'COMMISSION_PER_SHARE',
)


def validate_config(config: dict) -> None:
    """Validate a COMPASS config dict for the backtest engine.

    Ported from COMPASSLive._validate_config (omnicapital_live.py:1032).
    Raises HydraDataError on any violation.
    """
    missing = [k for k in _REQUIRED_KEYS if k not in config]
    if missing:
        raise HydraDataError(f"Config missing required keys: {missing}")

    if not isinstance(config['NUM_POSITIONS'], int) or not (1 <= config['NUM_POSITIONS'] <= 20):
        raise HydraDataError(
            f"NUM_POSITIONS must be int in [1, 20], got {config['NUM_POSITIONS']!r}"
        )
    if not isinstance(config['MOMENTUM_LOOKBACK'], int) or config['MOMENTUM_LOOKBACK'] < 1:
        raise HydraDataError(
            f"MOMENTUM_LOOKBACK must be positive int, got {config['MOMENTUM_LOOKBACK']!r}"
        )
    if config['CRASH_LEVERAGE'] >= config['LEV_FLOOR']:
        raise HydraDataError(
            f"CRASH_LEVERAGE ({config['CRASH_LEVERAGE']}) must be strictly below "
            f"LEV_FLOOR ({config['LEV_FLOOR']}) — otherwise the brake is a no-op"
        )
    if config['LEVERAGE_MAX'] < 1.0:
        raise HydraDataError(
            f"LEVERAGE_MAX must be >= 1.0, got {config['LEVERAGE_MAX']}"
        )
    if config['INITIAL_CAPITAL'] <= 0:
        raise HydraDataError(
            f"INITIAL_CAPITAL must be positive, got {config['INITIAL_CAPITAL']}"
        )


def load_pit_universe(path: str) -> Dict[int, List[str]]:
    """Load point-in-time S&P 500 membership by year.

    Input format: pickle of pd.DataFrame with columns (date, ticker, action)
    where action in {'added', 'removed'}. One row per membership change.

    Output: dict {year: [tickers]} — the set of tickers in the S&P 500 at
    any point during that year. A ticker added 2005-01-15 and removed
    2020-06-22 appears in universe[2005] through universe[2020].
    """
    if not os.path.exists(path):
        raise HydraDataError(f"PIT universe file not found: {path}")

    with open(path, 'rb') as f:
        df = pickle.load(f)

    if not isinstance(df, pd.DataFrame):
        raise HydraDataError(f"Expected DataFrame in {path}, got {type(df).__name__}")
    required_cols = {'date', 'ticker', 'action'}
    if not required_cols.issubset(df.columns):
        raise HydraDataError(
            f"Constituents file missing columns {required_cols - set(df.columns)}"
        )

    df = df.sort_values('date').reset_index(drop=True)
    min_year = int(df['date'].min().year)
    max_year = int(df['date'].max().year)

    # Walk the change log and build year-by-year membership.
    # A ticker is considered "in the universe" for every year from the
    # year it was added through the year it was removed (inclusive).
    current: set = set()
    membership: Dict[int, set] = {y: set() for y in range(min_year, max_year + 2)}

    # We also need to know, for any year that has zero events, what the
    # current membership is. We walk events in date order and for each
    # year boundary snapshot the current set into that year and all
    # subsequent years. Then event-level updates overwrite.
    # Simpler approach: walk events and after each, stamp the year it
    # affects onwards.
    for _, row in df.iterrows():
        year = int(row['date'].year)
        ticker = row['ticker']
        action = row['action']
        if action == 'added':
            current.add(ticker)
        elif action == 'removed':
            current.discard(ticker)
        else:
            raise HydraDataError(f"Unknown action '{action}' at row {row.name}")
        # Stamp from this year through the tail
        for y in range(year, max_year + 2):
            if action == 'added':
                membership[y].add(ticker)
            else:
                membership[y].discard(ticker)

    return {y: sorted(tickers) for y, tickers in membership.items()}


def load_sector_map(path: str) -> Dict[str, str]:
    """Load ticker → sector map from JSON file."""
    if not os.path.exists(path):
        raise HydraDataError(f"Could not load sector map: {path}")
    with open(path, 'r') as f:
        sectors = json.load(f)
    if not isinstance(sectors, dict):
        raise HydraDataError(f"Sector map must be a dict, got {type(sectors).__name__}")
    return sectors


def load_price_history(path: str) -> Dict[str, pd.DataFrame]:
    """Load daily OHLCV price history from pickle.

    Input format: pickle of dict {ticker: pd.DataFrame with columns
    ['Open', 'High', 'Low', 'Close', 'Volume']}.

    Each DataFrame is indexed by Timestamp.
    """
    if not os.path.exists(path):
        raise HydraDataError(f"Could not load price history: {path}")
    with open(path, 'rb') as f:
        data = pickle.load(f)
    if not isinstance(data, dict):
        raise HydraDataError(f"Price history must be dict, got {type(data).__name__}")
    required = {'Open', 'High', 'Low', 'Close', 'Volume'}
    for ticker, df in data.items():
        if not isinstance(df, pd.DataFrame):
            raise HydraDataError(f"Price history[{ticker}] is not a DataFrame")
        missing = required - set(df.columns)
        if missing:
            raise HydraDataError(f"Price history[{ticker}] missing columns: {missing}")
    return data


def compute_data_fingerprint(price_data: Dict[str, pd.DataFrame]) -> str:
    """Compute a deterministic SHA256 fingerprint of the price data.

    Used to record data_inputs_hash in BacktestResult for reproducibility
    auditing. Same inputs → same hash, even across runs.
    """
    h = hashlib.sha256()
    for ticker in sorted(price_data.keys()):
        df = price_data[ticker]
        h.update(ticker.encode('utf-8'))
        for ts, close in zip(df.index, df['Close'].values):
            h.update(str(ts).encode('utf-8'))
            h.update(f"{float(close):.8f}".encode('utf-8'))
    return h.hexdigest()


def load_spy_data(path: str) -> pd.DataFrame:
    """Load SPY daily OHLCV.

    Accepts pickle of DataFrame or CSV with Date as the index column.
    """
    if not os.path.exists(path):
        raise HydraDataError(f"SPY data not found: {path}")
    if path.endswith('.pkl'):
        with open(path, 'rb') as f:
            df = pickle.load(f)
    elif path.endswith('.csv'):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
    else:
        raise HydraDataError(f"Unsupported SPY data format: {path}")
    if 'Close' not in df.columns:
        raise HydraDataError("SPY data must have 'Close' column")
    return df


def load_catalyst_assets(path: str) -> Dict[str, pd.DataFrame]:
    """Load Catalyst trend asset OHLCV from pickle.

    Format: pickle of dict {ticker: DataFrame with Open/High/Low/Close/Volume}.
    Required tickers: TLT, ZROZ, GLD, DBC (the CATALYST_TREND_ASSETS from
    catalyst_signals.py).

    Caller is responsible for download. One-time setup:

        import yfinance as yf
        import pickle
        data = {}
        for sym in ['TLT', 'ZROZ', 'GLD', 'DBC']:
            df = yf.download(sym, start='1999-01-01', end='2027-01-01',
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
            data[sym] = df
        with open('data_cache/catalyst_assets.pkl', 'wb') as f:
            pickle.dump(data, f)
    """
    if not os.path.exists(path):
        raise HydraDataError(f"Catalyst assets file not found: {path}")
    with open(path, 'rb') as f:
        data = pickle.load(f)
    if not isinstance(data, dict):
        raise HydraDataError(
            f"Catalyst assets must be dict, got {type(data).__name__}"
        )
    required_tickers = {'TLT', 'ZROZ', 'GLD', 'DBC'}
    missing_tickers = required_tickers - set(data.keys())
    if missing_tickers:
        raise HydraDataError(
            f"Catalyst assets missing required tickers: {missing_tickers}"
        )
    required_cols = {'Open', 'High', 'Low', 'Close', 'Volume'}
    for ticker in required_tickers:
        df = data[ticker]
        if not isinstance(df, pd.DataFrame):
            raise HydraDataError(f"Catalyst assets[{ticker}] is not a DataFrame")
        missing_cols = required_cols - set(df.columns)
        if missing_cols:
            raise HydraDataError(
                f"Catalyst assets[{ticker}] missing columns: {missing_cols}"
            )
    return data


def load_vix_series(path: str) -> pd.Series:
    """Load daily VIX close from CSV.

    Accepts two formats:
      - yfinance default: Date as index column + 'Close' column
      - Plain: 'Date' or 'date' column + 'Close' or 'close' column

    Returns a Series indexed by Timestamp, values in points (e.g. 35.5
    for VIX=35.5). The caller is responsible for download:

        import yfinance as yf
        yf.download('^VIX', start='1999-01-01', end='2027-01-01').to_csv(
            'data_cache/vix_history.csv'
        )
    """
    if not os.path.exists(path):
        raise HydraDataError(f"VIX series file not found: {path}")
    df = pd.read_csv(path)
    cols_lower = {c.lower(): c for c in df.columns}
    date_col = cols_lower.get('date')
    close_col = cols_lower.get('close')
    if date_col is None or close_col is None:
        raise HydraDataError(
            f"VIX CSV must have 'Date' and 'Close' columns, got {list(df.columns)}"
        )
    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
    df = df.dropna(subset=[date_col]).sort_values(date_col).set_index(date_col)
    series = pd.to_numeric(df[close_col], errors='coerce').dropna()
    series.name = 'vix'
    return series


def load_yield_series(
    path: str,
    date_col: str,
    value_col: str,
    fill_business_days: bool = True,
) -> pd.Series:
    """Load a daily yield series from CSV (FRED format).

    Returns a pandas Series indexed by date, values in annual percentage
    (e.g. 3.5 means 3.5% annual yield).
    """
    if not os.path.exists(path):
        raise HydraDataError(f"Yield series not found: {path}")
    df = pd.read_csv(path)
    if date_col not in df.columns or value_col not in df.columns:
        raise HydraDataError(
            f"Yield CSV missing required columns: {date_col}, {value_col}"
        )
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col).set_index(date_col)

    # FRED uses '.' for missing values; pd.to_numeric with errors='coerce' handles it.
    series = pd.to_numeric(df[value_col], errors='coerce').dropna()

    if fill_business_days and len(series) >= 2:
        full_idx = pd.date_range(series.index.min(), series.index.max(), freq='B')
        series = series.reindex(full_idx).ffill()

    return series
