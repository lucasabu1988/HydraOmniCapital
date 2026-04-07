# HYDRA Reproducible Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `hydra_backtest/` — a reproducible COMPASS standalone backtest package that imports pure signal functions from `omnicapital_live.py` and produces a waterfall report (baseline live → +T-bill → +next-open → +slippage → NET HONEST), with blocking smoke-test validation.

**Architecture:** Python package at repo root. Pure-function consumer of live engine logic (not an owner). Data → engine → methodology → validation → reporting, where each stage is a pure function operating on frozen dataclasses. PIT universe from existing `data_cache/sp500_*.pkl` (827 tickers, 2000-2026).

**Tech Stack:** Python 3.14, pandas, numpy, pytest, pytest-cov. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-04-06-hydra-reproducible-backtest-design.md`

---

## File Structure

```
hydra_backtest/
├── __init__.py           — public API exports
├── __main__.py           — CLI entrypoint
├── errors.py             — exception hierarchy
├── data.py               — PIT loader, prices, yields, sector map, config validator
├── engine.py             — backtest loop + pure equivalents of live class methods
├── methodology.py        — waterfall corrections + metrics
├── reporting.py          — CSV / JSON / stdout writers
├── validation.py         — Layer A smoke tests
└── tests/
    ├── __init__.py
    ├── conftest.py       — shared fixtures
    ├── test_errors.py
    ├── test_data.py
    ├── test_engine.py
    ├── test_methodology.py
    ├── test_reporting.py
    ├── test_validation.py
    ├── test_integration.py
    └── test_e2e.py       — marked @pytest.mark.slow
```

---

## Task 1: Bootstrap package structure and errors hierarchy

**Files:**
- Create: `hydra_backtest/__init__.py`
- Create: `hydra_backtest/errors.py`
- Create: `hydra_backtest/tests/__init__.py`
- Create: `hydra_backtest/tests/conftest.py`
- Create: `hydra_backtest/tests/test_errors.py`

- [ ] **Step 1: Create package directories**

```bash
mkdir -p hydra_backtest/tests
```

- [ ] **Step 2: Write failing test for errors hierarchy**

Create `hydra_backtest/tests/test_errors.py`:
```python
import pytest
from hydra_backtest.errors import (
    HydraBacktestError,
    HydraDataError,
    HydraBacktestValidationError,
    HydraBacktestLookaheadError,
)

def test_base_error_inherits_exception():
    assert issubclass(HydraBacktestError, Exception)

def test_data_error_inherits_base():
    assert issubclass(HydraDataError, HydraBacktestError)

def test_validation_error_inherits_base():
    assert issubclass(HydraBacktestValidationError, HydraBacktestError)

def test_lookahead_error_inherits_validation():
    assert issubclass(HydraBacktestLookaheadError, HydraBacktestValidationError)

def test_errors_carry_message():
    err = HydraDataError("missing ticker XYZ")
    assert "XYZ" in str(err)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest hydra_backtest/tests/test_errors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hydra_backtest.errors'`

- [ ] **Step 4: Create empty __init__.py files**

```bash
touch hydra_backtest/__init__.py hydra_backtest/tests/__init__.py
```

- [ ] **Step 5: Create errors.py**

Create `hydra_backtest/errors.py`:
```python
"""Exception hierarchy for hydra_backtest package.

All errors raised by this package should inherit from HydraBacktestError.
Fail-loud philosophy: no try/except: pass anywhere. Offline analysis has
no reason to swallow errors.
"""


class HydraBacktestError(Exception):
    """Base class for all errors raised by the hydra_backtest package."""


class HydraDataError(HydraBacktestError):
    """Raised when input data is missing, corrupt, or inconsistent."""


class HydraBacktestValidationError(HydraBacktestError):
    """Raised when a smoke test or invariant check fails."""


class HydraBacktestLookaheadError(HydraBacktestValidationError):
    """Raised when lookahead is detected in a decision trace."""
```

- [ ] **Step 6: Create conftest.py with shared fixtures scaffold**

Create `hydra_backtest/tests/conftest.py`:
```python
"""Shared fixtures for hydra_backtest tests."""
import numpy as np
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def fixed_seed():
    """Force deterministic numpy RNG for every test."""
    np.random.seed(666)


@pytest.fixture
def minimal_config():
    """Smallest valid COMPASS config — matches live CONFIG schema."""
    from datetime import time
    return {
        'MOMENTUM_LOOKBACK': 90,
        'MOMENTUM_SKIP': 5,
        'MIN_MOMENTUM_STOCKS': 20,
        'NUM_POSITIONS': 5,
        'NUM_POSITIONS_RISK_OFF': 2,
        'HOLD_DAYS': 5,
        'HOLD_DAYS_MAX': 10,
        'RENEWAL_PROFIT_MIN': 0.04,
        'MOMENTUM_RENEWAL_THRESHOLD': 0.85,
        'POSITION_STOP_LOSS': -0.08,
        'TRAILING_ACTIVATION': 0.05,
        'TRAILING_STOP_PCT': 0.03,
        'STOP_DAILY_VOL_MULT': 2.5,
        'STOP_FLOOR': -0.06,
        'STOP_CEILING': -0.15,
        'TRAILING_VOL_BASELINE': 0.25,
        'BULL_OVERRIDE_THRESHOLD': 0.03,
        'BULL_OVERRIDE_MIN_SCORE': 0.40,
        'MAX_PER_SECTOR': 3,
        'DD_SCALE_TIER1': -0.10,
        'DD_SCALE_TIER2': -0.20,
        'DD_SCALE_TIER3': -0.35,
        'LEV_FULL': 1.0,
        'LEV_MID': 0.60,
        'LEV_FLOOR': 0.30,
        'CRASH_VEL_5D': -0.06,
        'CRASH_VEL_10D': -0.10,
        'CRASH_LEVERAGE': 0.15,
        'CRASH_COOLDOWN': 10,
        'QUALITY_VOL_MAX': 0.60,
        'QUALITY_VOL_LOOKBACK': 63,
        'QUALITY_MAX_SINGLE_DAY': 0.50,
        'TARGET_VOL': 0.15,
        'LEVERAGE_MAX': 1.0,
        'VOL_LOOKBACK': 20,
        'TOP_N': 40,
        'MIN_AGE_DAYS': 63,
        'INITIAL_CAPITAL': 100_000,
        'MARGIN_RATE': 0.06,
        'COMMISSION_PER_SHARE': 0.001,
    }
```

- [ ] **Step 7: Run tests and verify they pass**

Run: `pytest hydra_backtest/tests/test_errors.py -v`
Expected: 5 passed

- [ ] **Step 8: Commit**

```bash
git add hydra_backtest/__init__.py hydra_backtest/errors.py hydra_backtest/tests/__init__.py hydra_backtest/tests/conftest.py hydra_backtest/tests/test_errors.py
git commit -m "feat(hydra_backtest): bootstrap package structure and errors hierarchy"
```

---

## Task 2: Config validator (port from live)

**Files:**
- Modify: `hydra_backtest/data.py` (create)
- Modify: `hydra_backtest/tests/test_data.py` (create)

- [ ] **Step 1: Write failing test for config validation**

Create `hydra_backtest/tests/test_data.py`:
```python
import pytest
from hydra_backtest.data import validate_config
from hydra_backtest.errors import HydraDataError


def test_valid_config_passes(minimal_config):
    validate_config(minimal_config)  # should not raise

def test_missing_num_positions_raises(minimal_config):
    del minimal_config['NUM_POSITIONS']
    with pytest.raises(HydraDataError, match="NUM_POSITIONS"):
        validate_config(minimal_config)

def test_num_positions_out_of_range_raises(minimal_config):
    minimal_config['NUM_POSITIONS'] = 0
    with pytest.raises(HydraDataError, match="NUM_POSITIONS"):
        validate_config(minimal_config)
    minimal_config['NUM_POSITIONS'] = 25
    with pytest.raises(HydraDataError, match="NUM_POSITIONS"):
        validate_config(minimal_config)

def test_momentum_lookback_must_be_positive(minimal_config):
    minimal_config['MOMENTUM_LOOKBACK'] = 0
    with pytest.raises(HydraDataError, match="MOMENTUM_LOOKBACK"):
        validate_config(minimal_config)

def test_crash_leverage_must_be_below_lev_floor(minimal_config):
    minimal_config['CRASH_LEVERAGE'] = 0.5
    minimal_config['LEV_FLOOR'] = 0.30
    with pytest.raises(HydraDataError, match="CRASH_LEVERAGE"):
        validate_config(minimal_config)

def test_leverage_max_at_least_one(minimal_config):
    minimal_config['LEVERAGE_MAX'] = 0.5
    with pytest.raises(HydraDataError, match="LEVERAGE_MAX"):
        validate_config(minimal_config)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest hydra_backtest/tests/test_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'hydra_backtest.data'`

- [ ] **Step 3: Create data.py with validate_config**

Create `hydra_backtest/data.py`:
```python
"""Data loading and validation for hydra_backtest.

All functions here are pure — they take filesystem paths and date ranges
and return DataFrames, dicts, or series. No network I/O, no logging,
no computation of signals or execution of trades.
"""
from hydra_backtest.errors import HydraDataError


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
    # Required keys present
    missing = [k for k in _REQUIRED_KEYS if k not in config]
    if missing:
        raise HydraDataError(f"Config missing required keys: {missing}")

    # Range checks
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
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest hydra_backtest/tests/test_data.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/data.py hydra_backtest/tests/test_data.py
git commit -m "feat(hydra_backtest): config validator ported from live engine"
```

---

## Task 3: PIT universe loader and sector map

**Files:**
- Modify: `hydra_backtest/data.py`
- Modify: `hydra_backtest/tests/test_data.py`

- [ ] **Step 1: Write failing tests for universe loading**

Append to `hydra_backtest/tests/test_data.py`:
```python
import pandas as pd
from datetime import datetime
from hydra_backtest.data import load_pit_universe, load_sector_map


def test_load_pit_universe_returns_dict_by_year(tmp_path):
    # Create a minimal fake constituents history
    df = pd.DataFrame([
        {'date': pd.Timestamp('2000-06-05'), 'ticker': 'AAPL', 'action': 'added'},
        {'date': pd.Timestamp('2005-01-15'), 'ticker': 'GOOG', 'action': 'added'},
        {'date': pd.Timestamp('2020-06-22'), 'ticker': 'AAPL', 'action': 'removed'},
    ])
    path = tmp_path / 'constituents.pkl'
    df.to_pickle(path)

    universe = load_pit_universe(str(path))
    assert isinstance(universe, dict)
    assert 'AAPL' in universe[2010]
    assert 'AAPL' not in universe[2021]
    assert 'GOOG' in universe[2010]
    assert 'GOOG' in universe[2025]

def test_load_pit_universe_anti_survivorship():
    from pathlib import Path
    real_path = Path('data_cache/sp500_constituents_history.pkl')
    if not real_path.exists():
        pytest.skip("Real constituents history not available")
    universe = load_pit_universe(str(real_path))
    # Enron (ENE) must NOT appear in 2010 universe (bankrupted 2001)
    if 'ENE' in sum(universe.values(), []):
        assert 'ENE' not in universe.get(2010, [])
    # AAPL must be in 2010 (was in S&P 500)
    assert 'AAPL' in universe.get(2010, [])

def test_load_sector_map(tmp_path):
    import json
    path = tmp_path / 'sectors.json'
    path.write_text(json.dumps({'AAPL': 'Tech', 'JPM': 'Financials'}))
    sectors = load_sector_map(str(path))
    assert sectors['AAPL'] == 'Tech'
    assert sectors['JPM'] == 'Financials'

def test_load_sector_map_missing_file_raises(tmp_path):
    from hydra_backtest.errors import HydraDataError
    with pytest.raises(HydraDataError, match="sector map"):
        load_sector_map(str(tmp_path / 'nonexistent.json'))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest hydra_backtest/tests/test_data.py::test_load_pit_universe_returns_dict_by_year -v`
Expected: FAIL with `ImportError: cannot import name 'load_pit_universe'`

- [ ] **Step 3: Implement loaders in data.py**

Append to `hydra_backtest/data.py`:
```python
import json
import os
import pickle
from typing import Dict, List

import pandas as pd

from hydra_backtest.errors import HydraDataError


def load_pit_universe(path: str) -> Dict[int, List[str]]:
    """Load point-in-time S&P 500 membership by year.

    Input format: pickle of pd.DataFrame with columns (date, ticker, action)
    where action ∈ {'added', 'removed'}. One row per membership change.

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

    # Walk the change log and build year-by-year membership
    df = df.sort_values('date').reset_index(drop=True)
    current = set()
    membership_per_year: Dict[int, set] = {}

    min_year = df['date'].min().year
    max_year = df['date'].max().year

    for year in range(min_year, max_year + 2):
        membership_per_year[year] = set(current)

    for _, row in df.iterrows():
        year = row['date'].year
        ticker = row['ticker']
        if row['action'] == 'added':
            current.add(ticker)
        elif row['action'] == 'removed':
            current.discard(ticker)
        else:
            raise HydraDataError(f"Unknown action '{row['action']}' at row {row.name}")
        # From this year onwards, the set includes this change
        for y in range(year, max_year + 2):
            if row['action'] == 'added':
                membership_per_year[y].add(ticker)
            else:
                membership_per_year[y].discard(ticker)

    return {y: sorted(tickers) for y, tickers in membership_per_year.items()}


def load_sector_map(path: str) -> Dict[str, str]:
    """Load ticker → sector map from JSON file."""
    if not os.path.exists(path):
        raise HydraDataError(f"Could not load sector map: {path}")
    with open(path, 'r') as f:
        sectors = json.load(f)
    if not isinstance(sectors, dict):
        raise HydraDataError(f"Sector map must be a dict, got {type(sectors).__name__}")
    return sectors
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest hydra_backtest/tests/test_data.py -v`
Expected: All tests pass (10 total so far)

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/data.py hydra_backtest/tests/test_data.py
git commit -m "feat(hydra_backtest): PIT universe and sector map loaders"
```

---

## Task 4: Price history loader with hash fingerprint

**Files:**
- Modify: `hydra_backtest/data.py`
- Modify: `hydra_backtest/tests/test_data.py`

- [ ] **Step 1: Write failing tests**

Append to `hydra_backtest/tests/test_data.py`:
```python
def test_load_price_history_returns_dict_of_dataframes(tmp_path):
    import pickle
    fake_data = {
        'AAPL': pd.DataFrame({
            'Open': [100, 101, 102],
            'High': [102, 103, 104],
            'Low': [99, 100, 101],
            'Close': [101, 102, 103],
            'Volume': [1000, 1100, 1200],
        }, index=pd.date_range('2020-01-02', periods=3)),
        'MSFT': pd.DataFrame({
            'Open': [200, 201, 202],
            'High': [202, 203, 204],
            'Low': [199, 200, 201],
            'Close': [201, 202, 203],
            'Volume': [2000, 2100, 2200],
        }, index=pd.date_range('2020-01-02', periods=3)),
    }
    path = tmp_path / 'prices.pkl'
    with open(path, 'wb') as f:
        pickle.dump(fake_data, f)

    prices = load_price_history(str(path))
    assert set(prices.keys()) == {'AAPL', 'MSFT'}
    assert list(prices['AAPL'].columns) == ['Open', 'High', 'Low', 'Close', 'Volume']

def test_load_price_history_fingerprint_deterministic(tmp_path):
    import pickle
    data = {'AAPL': pd.DataFrame({'Close': [100.0, 101.0]}, index=pd.date_range('2020-01-02', periods=2))}
    path = tmp_path / 'prices.pkl'
    with open(path, 'wb') as f:
        pickle.dump(data, f)

    h1 = compute_data_fingerprint(load_price_history(str(path)))
    h2 = compute_data_fingerprint(load_price_history(str(path)))
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex

def test_load_price_history_missing_raises():
    with pytest.raises(HydraDataError, match="price history"):
        load_price_history('/nonexistent/file.pkl')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest hydra_backtest/tests/test_data.py::test_load_price_history_returns_dict_of_dataframes -v`
Expected: FAIL with `ImportError: cannot import name 'load_price_history'`

- [ ] **Step 3: Implement loaders**

Append to `hydra_backtest/data.py`:
```python
import hashlib


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
    for ticker, df in data.items():
        if not isinstance(df, pd.DataFrame):
            raise HydraDataError(f"Price history[{ticker}] is not a DataFrame")
        required = {'Open', 'High', 'Low', 'Close', 'Volume'}
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
        # Hash the Close column and dates — sufficient fingerprint
        for ts, close in zip(df.index, df['Close'].values):
            h.update(str(ts).encode('utf-8'))
            h.update(f"{close:.8f}".encode('utf-8'))
    return h.hexdigest()
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest hydra_backtest/tests/test_data.py -v`
Expected: all tests pass (13 total so far)

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/data.py hydra_backtest/tests/test_data.py
git commit -m "feat(hydra_backtest): price history loader with sha256 fingerprint"
```

---

## Task 5: SPY, T-bill, and Aaa yield loaders

**Files:**
- Modify: `hydra_backtest/data.py`
- Modify: `hydra_backtest/tests/test_data.py`

- [ ] **Step 1: Write failing tests**

Append to `hydra_backtest/tests/test_data.py`:
```python
def test_load_spy_data_returns_dataframe(tmp_path):
    df = pd.DataFrame({
        'Open': [100, 101],
        'High': [102, 103],
        'Low': [99, 100],
        'Close': [101, 102],
        'Volume': [1000, 1100],
    }, index=pd.date_range('2020-01-02', periods=2))
    path = tmp_path / 'spy.pkl'
    df.to_pickle(path)
    spy = load_spy_data(str(path))
    assert isinstance(spy, pd.DataFrame)
    assert 'Close' in spy.columns

def test_load_yield_series_returns_daily_series(tmp_path):
    df = pd.DataFrame({
        'DATE': pd.date_range('2020-01-02', periods=5),
        'DGS3MO': [1.5, 1.5, 1.6, 1.6, 1.7],
    })
    path = tmp_path / 'tbill.csv'
    df.to_csv(path, index=False)
    series = load_yield_series(str(path), date_col='DATE', value_col='DGS3MO')
    assert isinstance(series, pd.Series)
    assert len(series) == 5
    # Values stored as annual percentage (1.5 = 1.5%), not basis points
    assert 0 <= series.iloc[0] <= 20  # sanity: not 150 or 0.015

def test_load_yield_series_fills_gaps(tmp_path):
    df = pd.DataFrame({
        'DATE': ['2020-01-02', '2020-01-06'],  # gap
        'V': [1.5, 1.6],
    })
    path = tmp_path / 'y.csv'
    df.to_csv(path, index=False)
    series = load_yield_series(str(path), date_col='DATE', value_col='V',
                                fill_business_days=True)
    # Should forward-fill business days between Jan 2 and Jan 6
    assert len(series) >= 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest hydra_backtest/tests/test_data.py -k yield -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement loaders**

Append to `hydra_backtest/data.py`:
```python
def load_spy_data(path: str) -> pd.DataFrame:
    """Load SPY daily OHLCV.

    Accepts pickle of DataFrame or CSV with 'Date' index.
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


def load_yield_series(path: str, date_col: str, value_col: str,
                      fill_business_days: bool = True) -> pd.Series:
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

    # Coerce to numeric, drop non-numeric (FRED uses '.' for missing)
    series = pd.to_numeric(df[value_col], errors='coerce').dropna()

    if fill_business_days and len(series) >= 2:
        full_idx = pd.date_range(series.index.min(), series.index.max(), freq='B')
        series = series.reindex(full_idx).ffill()

    return series
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest hydra_backtest/tests/test_data.py -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/data.py hydra_backtest/tests/test_data.py
git commit -m "feat(hydra_backtest): SPY and yield series loaders"
```

---

## Task 6: Engine dataclasses — BacktestState and BacktestResult

**Files:**
- Create: `hydra_backtest/engine.py`
- Create: `hydra_backtest/tests/test_engine.py`

- [ ] **Step 1: Write failing tests for dataclasses**

Create `hydra_backtest/tests/test_engine.py`:
```python
import pytest
import pandas as pd
from datetime import datetime

from hydra_backtest.engine import BacktestState, BacktestResult


def test_backtest_state_is_frozen():
    state = BacktestState(
        cash=100_000.0,
        positions={},
        peak_value=100_000.0,
        crash_cooldown=0,
        portfolio_value_history=(),
    )
    with pytest.raises((AttributeError, TypeError)):
        state.cash = 50_000.0  # frozen — mutation not allowed

def test_backtest_state_replace():
    state = BacktestState(
        cash=100_000.0, positions={}, peak_value=100_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    new = state._replace(cash=50_000.0)
    assert new.cash == 50_000.0
    assert state.cash == 100_000.0  # original unchanged

def test_backtest_result_required_fields():
    result = BacktestResult(
        config={'NUM_POSITIONS': 5},
        daily_values=pd.DataFrame(),
        trades=pd.DataFrame(),
        decisions=[],
        exit_events=[],
        universe_size={2020: 40},
        started_at=datetime(2026, 4, 6, 10, 0, 0),
        finished_at=datetime(2026, 4, 6, 10, 5, 0),
        git_sha='abc123',
        data_inputs_hash='def456',
    )
    assert result.config['NUM_POSITIONS'] == 5
    assert result.git_sha == 'abc123'
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest hydra_backtest/tests/test_engine.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create engine.py with dataclasses**

Create `hydra_backtest/engine.py`:
```python
"""Backtest engine — pure function consumer of live signal logic.

This module imports signal-computation functions directly from
omnicapital_live.py (the live production engine). When a live function
depends on class state (self.broker, threads, etc.) we reimplement a
pure equivalent here with a docstring pointing to the source line.

The engine is state-machine-free: each backtest run is a single call
to run_backtest() that produces a BacktestResult. No globals, no I/O,
no mutation of shared state.
"""
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Dict, List, Tuple

import pandas as pd


@dataclass(frozen=True)
class BacktestState:
    """Mutable backtest state snapshot — immutable via frozen dataclass.

    Each per-day iteration produces a NEW BacktestState via _replace().
    This eliminates a class of bugs where one function accidentally mutates
    shared state that another function expected to be fixed.
    """
    cash: float
    positions: dict          # symbol -> PositionDict
    peak_value: float
    crash_cooldown: int
    portfolio_value_history: tuple  # immutable — tuple, not list

    def _replace(self, **kwargs) -> 'BacktestState':
        return replace(self, **kwargs)


@dataclass(frozen=True)
class BacktestResult:
    """Result of a single backtest run — everything needed to inspect, audit, or export."""
    config: dict
    daily_values: pd.DataFrame       # date, portfolio_value, cash, n_positions, leverage, drawdown, regime_score, crash_active
    trades: pd.DataFrame             # symbol, entry_date, exit_date, exit_reason, entry_price, exit_price, pnl, return, sector
    decisions: list                  # list of dicts — JSONL-serializable
    exit_events: list                # subset of trades with extra metadata
    universe_size: Dict[int, int]    # year → count of tradeable tickers
    started_at: datetime
    finished_at: datetime
    git_sha: str                     # repo state at run time
    data_inputs_hash: str            # sha256 of price_data fingerprint
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest hydra_backtest/tests/test_engine.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/engine.py hydra_backtest/tests/test_engine.py
git commit -m "feat(hydra_backtest): BacktestState and BacktestResult frozen dataclasses"
```

---

## Task 7: _mark_to_market pure function

**Files:**
- Modify: `hydra_backtest/engine.py`
- Modify: `hydra_backtest/tests/test_engine.py`

- [ ] **Step 1: Write failing tests**

Append to `hydra_backtest/tests/test_engine.py`:
```python
from hydra_backtest.engine import _mark_to_market


def test_mark_to_market_empty_positions():
    state = BacktestState(cash=100_000.0, positions={}, peak_value=100_000.0,
                           crash_cooldown=0, portfolio_value_history=())
    price_data = {}
    date = pd.Timestamp('2020-01-02')
    pv = _mark_to_market(state, price_data, date)
    assert pv == 100_000.0

def test_mark_to_market_with_one_position():
    state = BacktestState(
        cash=50_000.0,
        positions={'AAPL': {'shares': 100.0, 'entry_price': 150.0, 'entry_date': pd.Timestamp('2020-01-02'),
                            'entry_idx': 0, 'original_entry_idx': 0, 'high_price': 150.0,
                            'entry_vol': 0.25, 'entry_daily_vol': 0.016, 'sector': 'Tech'}},
        peak_value=50_000.0,
        crash_cooldown=0,
        portfolio_value_history=(),
    )
    price_data = {
        'AAPL': pd.DataFrame({'Close': [155.0]}, index=[pd.Timestamp('2020-01-03')]),
    }
    pv = _mark_to_market(state, price_data, pd.Timestamp('2020-01-03'))
    assert pv == 50_000.0 + 100.0 * 155.0

def test_mark_to_market_skips_stale_symbol():
    """If a symbol's price data doesn't have today's date, use the stored entry_price."""
    state = BacktestState(
        cash=0.0,
        positions={'AAPL': {'shares': 10.0, 'entry_price': 150.0, 'entry_date': pd.Timestamp('2020-01-02'),
                            'entry_idx': 0, 'original_entry_idx': 0, 'high_price': 150.0,
                            'entry_vol': 0.25, 'entry_daily_vol': 0.016, 'sector': 'Tech'}},
        peak_value=1500.0,
        crash_cooldown=0,
        portfolio_value_history=(),
    )
    price_data = {'AAPL': pd.DataFrame({'Close': [150.0]}, index=[pd.Timestamp('2020-01-02')])}
    # Asking for 01-05, but price_data only has 01-02 — should fall back to entry_price
    pv = _mark_to_market(state, price_data, pd.Timestamp('2020-01-05'))
    assert pv == 1500.0  # fallback to entry_price
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest hydra_backtest/tests/test_engine.py -v -k mark_to_market`
Expected: FAIL with `ImportError: cannot import name '_mark_to_market'`

- [ ] **Step 3: Implement _mark_to_market**

Append to `hydra_backtest/engine.py`:
```python
def _mark_to_market(state: BacktestState, price_data: Dict[str, pd.DataFrame],
                    date: pd.Timestamp) -> float:
    """Compute total portfolio value at the end of `date`.

    = cash + sum(shares * Close[date]) for each open position.
    If a position's price data is missing for `date`, falls back to the
    stored entry_price (so a temporarily stale symbol doesn't blow up).
    """
    pv = state.cash
    for symbol, pos in state.positions.items():
        df = price_data.get(symbol)
        if df is not None and date in df.index:
            price = float(df.loc[date, 'Close'])
        else:
            price = float(pos['entry_price'])
        pv += float(pos['shares']) * price
    return pv
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest hydra_backtest/tests/test_engine.py -v`
Expected: all tests pass

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/engine.py hydra_backtest/tests/test_engine.py
git commit -m "feat(hydra_backtest): _mark_to_market pure function"
```

---

## Task 8: get_tradeable_symbols PIT resolver

**Files:**
- Modify: `hydra_backtest/engine.py`
- Modify: `hydra_backtest/tests/test_engine.py`

- [ ] **Step 1: Write failing tests**

Append to `hydra_backtest/tests/test_engine.py`:
```python
from hydra_backtest.engine import get_tradeable_symbols


def test_get_tradeable_symbols_intersects_pit_and_price_data():
    pit_universe = {2020: ['AAPL', 'GOOG', 'DELISTED']}
    price_data = {
        'AAPL': pd.DataFrame({'Close': [100.0]}, index=[pd.Timestamp('2020-01-02')]),
        'GOOG': pd.DataFrame({'Close': [1500.0]}, index=[pd.Timestamp('2020-01-02')]),
        # DELISTED has no price data — must be excluded
    }
    tradeable = get_tradeable_symbols(pit_universe, price_data, pd.Timestamp('2020-01-02'),
                                       min_age_days=0)
    assert 'AAPL' in tradeable
    assert 'GOOG' in tradeable
    assert 'DELISTED' not in tradeable

def test_get_tradeable_symbols_respects_min_age():
    pit_universe = {2020: ['AAPL', 'NEW_IPO']}
    price_data = {
        'AAPL': pd.DataFrame({'Close': list(range(100))},
                              index=pd.date_range('2019-01-01', periods=100)),
        'NEW_IPO': pd.DataFrame({'Close': [50.0, 51.0]},
                                 index=pd.date_range('2020-01-01', periods=2)),
    }
    tradeable = get_tradeable_symbols(pit_universe, price_data, pd.Timestamp('2020-01-02'),
                                       min_age_days=63)
    assert 'AAPL' in tradeable  # has > 63 days of history
    assert 'NEW_IPO' not in tradeable  # only 2 days
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest hydra_backtest/tests/test_engine.py -k tradeable -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement**

Append to `hydra_backtest/engine.py`:
```python
def get_tradeable_symbols(
    pit_universe: Dict[int, List[str]],
    price_data: Dict[str, pd.DataFrame],
    date: pd.Timestamp,
    min_age_days: int = 63,
) -> List[str]:
    """Intersect PIT membership for this year with symbols that have:
      (a) price data available for this date
      (b) at least min_age_days of price history prior to this date
    """
    year = date.year
    candidates = pit_universe.get(year, [])
    tradeable = []
    for sym in candidates:
        df = price_data.get(sym)
        if df is None or date not in df.index:
            continue
        # Must have min_age_days of history
        history_before_date = df.loc[:date]
        if len(history_before_date) < min_age_days:
            continue
        tradeable.append(sym)
    return tradeable
```

- [ ] **Step 4: Run tests**

Run: `pytest hydra_backtest/tests/test_engine.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/engine.py hydra_backtest/tests/test_engine.py
git commit -m "feat(hydra_backtest): get_tradeable_symbols PIT resolver"
```

---

## Task 9: get_current_leverage_pure (with crash brake)

**Files:**
- Modify: `hydra_backtest/engine.py`
- Modify: `hydra_backtest/tests/test_engine.py`

This is the most intricate pure equivalent — it mirrors `COMPASSLive.get_current_leverage` (line 1396) including the crash brake bypass of LEV_FLOOR (lines 1444-1446).

- [ ] **Step 1: Write failing tests**

Append to `hydra_backtest/tests/test_engine.py`:
```python
from hydra_backtest.engine import get_current_leverage_pure


def test_leverage_normal_regime(minimal_config):
    spy = pd.DataFrame({
        'Close': [100.0 + i * 0.01 for i in range(250)],
    }, index=pd.date_range('2019-01-01', periods=250))
    lev, cooldown, crash_active = get_current_leverage_pure(
        drawdown=0.0, portfolio_value_history=(100_000.0,) * 20,
        crash_cooldown=0, config=minimal_config, spy_hist=spy,
    )
    assert minimal_config['LEV_FLOOR'] <= lev <= minimal_config['LEVERAGE_MAX']
    assert not crash_active

def test_leverage_dd_scaling(minimal_config):
    spy = pd.DataFrame({'Close': [100.0] * 250},
                       index=pd.date_range('2019-01-01', periods=250))
    # -25% drawdown → tier2/3 of DD scaling
    lev, cooldown, crash_active = get_current_leverage_pure(
        drawdown=-0.25, portfolio_value_history=(100_000.0,) * 20,
        crash_cooldown=0, config=minimal_config, spy_hist=spy,
    )
    assert lev < minimal_config['LEV_FULL']
    assert not crash_active

def test_crash_brake_fires_on_5d_drop(minimal_config):
    spy = pd.DataFrame({'Close': [100.0] * 250},
                       index=pd.date_range('2019-01-01', periods=250))
    # 5-day return of -8% triggers CRASH_VEL_5D (-6%)
    history = (100_000.0, 100_000.0, 100_000.0, 100_000.0, 92_000.0)
    lev, cooldown, crash_active = get_current_leverage_pure(
        drawdown=-0.08, portfolio_value_history=history,
        crash_cooldown=0, config=minimal_config, spy_hist=spy,
    )
    assert crash_active
    assert lev <= minimal_config['CRASH_LEVERAGE'] + 1e-9
    assert cooldown == minimal_config['CRASH_COOLDOWN'] - 1

def test_crash_brake_bypasses_lev_floor(minimal_config):
    """When crash brake fires, return_lev must be BELOW LEV_FLOOR (0.15 < 0.30).
    Mirrors omnicapital_live.py:1444-1446."""
    spy = pd.DataFrame({'Close': [100.0] * 250},
                       index=pd.date_range('2019-01-01', periods=250))
    history = (100_000.0,) * 4 + (92_000.0,)
    lev, cooldown, crash_active = get_current_leverage_pure(
        drawdown=-0.08, portfolio_value_history=history,
        crash_cooldown=0, config=minimal_config, spy_hist=spy,
    )
    assert crash_active
    assert lev < minimal_config['LEV_FLOOR']  # bypass must work

def test_crash_cooldown_persists(minimal_config):
    """If we're already in cooldown, leverage stays at CRASH_LEVERAGE."""
    spy = pd.DataFrame({'Close': [100.0] * 250},
                       index=pd.date_range('2019-01-01', periods=250))
    lev, cooldown, crash_active = get_current_leverage_pure(
        drawdown=-0.02, portfolio_value_history=(100_000.0,) * 20,
        crash_cooldown=5, config=minimal_config, spy_hist=spy,
    )
    assert crash_active
    assert lev <= minimal_config['CRASH_LEVERAGE'] + 1e-9
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest hydra_backtest/tests/test_engine.py -k leverage -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement get_current_leverage_pure**

Append to `hydra_backtest/engine.py`:
```python
from omnicapital_live import (
    _dd_leverage,
    compute_dynamic_leverage,
)


def get_current_leverage_pure(
    drawdown: float,
    portfolio_value_history: tuple,
    crash_cooldown: int,
    config: dict,
    spy_hist: pd.DataFrame,
) -> Tuple[float, int, bool]:
    """Pure equivalent of COMPASSLive.get_current_leverage (omnicapital_live.py:1396).

    Returns (leverage, new_crash_cooldown, crash_active).

    Mirrors the live logic including the crash brake bypass of LEV_FLOOR
    at lines 1444-1446 of the live engine:

        if crash_brake_active:
            return target_lev
        return max(target_lev, config['LEV_FLOOR'])
    """
    # 1. DD scaling
    dd_lev = _dd_leverage(drawdown, config)
    crash_brake_active = False
    new_cooldown = crash_cooldown

    # 2. Crash brake — 3 pathways (cooldown active, 5d velocity, 10d velocity)
    if crash_cooldown > 0:
        dd_lev = min(config['CRASH_LEVERAGE'], dd_lev)
        crash_brake_active = True
    elif len(portfolio_value_history) >= 5:
        current_val = portfolio_value_history[-1]
        val_5d = portfolio_value_history[-5]
        if val_5d > 0:
            ret_5d = (current_val / val_5d) - 1.0
            if ret_5d <= config['CRASH_VEL_5D']:
                dd_lev = min(config['CRASH_LEVERAGE'], dd_lev)
                new_cooldown = config['CRASH_COOLDOWN'] - 1
                crash_brake_active = True
        if not crash_brake_active and len(portfolio_value_history) >= 10:
            val_10d = portfolio_value_history[-10]
            if val_10d > 0:
                ret_10d = (current_val / val_10d) - 1.0
                if ret_10d <= config['CRASH_VEL_10D']:
                    dd_lev = min(config['CRASH_LEVERAGE'], dd_lev)
                    new_cooldown = config['CRASH_COOLDOWN'] - 1
                    crash_brake_active = True

    # 3. Vol targeting
    vol_lev = compute_dynamic_leverage(
        spy_hist, config['TARGET_VOL'], config['VOL_LOOKBACK'],
        config['LEV_FLOOR'], config['LEVERAGE_MAX'],
    ) if spy_hist is not None else 1.0

    # 4. Final: minimum of DD and vol targeting, with crash brake bypass of floor
    target_lev = min(dd_lev, vol_lev)
    if crash_brake_active:
        return target_lev, new_cooldown, True
    return max(target_lev, config['LEV_FLOOR']), new_cooldown, False
```

- [ ] **Step 4: Run tests and verify they pass**

Run: `pytest hydra_backtest/tests/test_engine.py -v -k leverage`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/engine.py hydra_backtest/tests/test_engine.py
git commit -m "feat(hydra_backtest): get_current_leverage_pure with crash brake"
```

---

## Task 10: get_max_positions_pure (with bull override)

**Files:**
- Modify: `hydra_backtest/engine.py`
- Modify: `hydra_backtest/tests/test_engine.py`

- [ ] **Step 1: Write failing tests**

Append to `hydra_backtest/tests/test_engine.py`:
```python
from hydra_backtest.engine import get_max_positions_pure


def test_max_positions_risk_on(minimal_config):
    spy = pd.DataFrame({'Close': [100.0 + i * 0.1 for i in range(250)]},
                       index=pd.date_range('2019-01-01', periods=250))
    mp = get_max_positions_pure(regime_score=0.8, spy_hist=spy, config=minimal_config)
    assert mp >= minimal_config['NUM_POSITIONS']  # at least base, can be +1 via bull override

def test_max_positions_risk_off(minimal_config):
    spy = pd.DataFrame({'Close': [100.0] * 250},
                       index=pd.date_range('2019-01-01', periods=250))
    mp = get_max_positions_pure(regime_score=0.20, spy_hist=spy, config=minimal_config)
    assert mp == minimal_config['NUM_POSITIONS_RISK_OFF']

def test_max_positions_bull_override(minimal_config):
    """SPY > 1.03 * SMA200 AND score > 0.40 → +1 position."""
    spy_prices = [100.0] * 200 + [110.0] * 50  # SPY rallied well above SMA200
    spy = pd.DataFrame({'Close': spy_prices},
                       index=pd.date_range('2019-01-01', periods=250))
    mp = get_max_positions_pure(regime_score=0.70, spy_hist=spy, config=minimal_config)
    assert mp == minimal_config['NUM_POSITIONS']  # already at max, can't go above
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest hydra_backtest/tests/test_engine.py -k max_positions -v`
Expected: FAIL

- [ ] **Step 3: Implement**

Append to `hydra_backtest/engine.py`:
```python
from omnicapital_live import regime_score_to_positions


def get_max_positions_pure(
    regime_score: float,
    spy_hist: pd.DataFrame,
    config: dict,
) -> int:
    """Pure equivalent of COMPASSLive.get_max_positions (omnicapital_live.py:1448).

    Uses the top-level regime_score_to_positions from the live engine,
    passing SPY close/SMA200 for the bull override. Fed Emergency overlay
    is NOT applied in v1 (documented limitation in spec §12).
    """
    spy_close = None
    sma200 = None
    if spy_hist is not None and len(spy_hist) >= 200:
        spy_close = float(spy_hist['Close'].iloc[-1])
        sma200 = float(spy_hist['Close'].iloc[-200:].mean())
    return regime_score_to_positions(
        regime_score,
        config['NUM_POSITIONS'],
        config['NUM_POSITIONS_RISK_OFF'],
        spy_close=spy_close,
        sma200=sma200,
        bull_threshold=config['BULL_OVERRIDE_THRESHOLD'],
        bull_min_score=config['BULL_OVERRIDE_MIN_SCORE'],
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest hydra_backtest/tests/test_engine.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/engine.py hydra_backtest/tests/test_engine.py
git commit -m "feat(hydra_backtest): get_max_positions_pure with bull override"
```

---

## Task 11: apply_daily_costs (cash yield + margin)

**Files:**
- Modify: `hydra_backtest/engine.py`
- Modify: `hydra_backtest/tests/test_engine.py`

- [ ] **Step 1: Write failing tests**

Append to `hydra_backtest/tests/test_engine.py`:
```python
from hydra_backtest.engine import apply_daily_costs


def test_daily_cash_yield_positive(minimal_config):
    state = BacktestState(cash=10_000.0, positions={}, peak_value=10_000.0,
                           crash_cooldown=0, portfolio_value_history=())
    # 3.5% annual → daily rate = 0.035/252 ≈ 0.0001389
    new_state = apply_daily_costs(state, leverage=1.0, cash_yield_annual_pct=3.5,
                                   portfolio_value=10_000.0, config=minimal_config)
    expected = 10_000.0 * (1 + 0.035 / 252)
    assert abs(new_state.cash - expected) < 1e-6

def test_daily_cash_yield_zero_when_no_cash(minimal_config):
    state = BacktestState(cash=0.0, positions={}, peak_value=0.0,
                           crash_cooldown=0, portfolio_value_history=())
    new_state = apply_daily_costs(state, leverage=1.0, cash_yield_annual_pct=3.5,
                                   portfolio_value=0.0, config=minimal_config)
    assert new_state.cash == 0.0

def test_margin_cost_when_leveraged(minimal_config):
    state = BacktestState(cash=-20_000.0, positions={}, peak_value=100_000.0,
                           crash_cooldown=0, portfolio_value_history=())
    # leverage 1.2 → borrowed = pv * 0.2/1.2 ≈ 16,666 → daily margin = 0.06/252 * 16,666
    new_state = apply_daily_costs(state, leverage=1.2, cash_yield_annual_pct=0.0,
                                   portfolio_value=100_000.0, config=minimal_config)
    expected_borrowed = 100_000.0 * (0.2 / 1.2)
    expected_margin = expected_borrowed * (0.06 / 252)
    assert abs(new_state.cash - (-20_000.0 - expected_margin)) < 1e-6
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest hydra_backtest/tests/test_engine.py -k daily_costs -v`
Expected: FAIL

- [ ] **Step 3: Implement**

Append to `hydra_backtest/engine.py`:
```python
def apply_daily_costs(
    state: BacktestState,
    leverage: float,
    cash_yield_annual_pct: float,
    portfolio_value: float,
    config: dict,
) -> BacktestState:
    """Apply one trading day's margin cost (if leveraged) and cash yield.

    cash_yield_annual_pct is in percent (e.g. 3.5 for 3.5% annual).
    Margin cost uses config['MARGIN_RATE'] (default 6%).
    """
    cash = state.cash

    # Margin cost on borrowed amount (leverage > 1.0)
    if leverage > 1.0 and portfolio_value > 0:
        borrowed = portfolio_value * (leverage - 1.0) / leverage
        daily_margin = config['MARGIN_RATE'] / 252 * borrowed
        cash -= daily_margin

    # Cash yield on positive idle cash
    if cash > 0 and cash_yield_annual_pct > 0:
        daily_rate = cash_yield_annual_pct / 100.0 / 252
        cash += cash * daily_rate

    return state._replace(cash=cash)
```

- [ ] **Step 4: Run tests**

Run: `pytest hydra_backtest/tests/test_engine.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/engine.py hydra_backtest/tests/test_engine.py
git commit -m "feat(hydra_backtest): apply_daily_costs (margin + cash yield)"
```

---

## Task 12: _get_exec_price execution mode helper

**Files:**
- Modify: `hydra_backtest/engine.py`
- Modify: `hydra_backtest/tests/test_engine.py`

- [ ] **Step 1: Write failing tests**

Append to `hydra_backtest/tests/test_engine.py`:
```python
from hydra_backtest.engine import _get_exec_price


def test_get_exec_price_same_close():
    df = pd.DataFrame({'Open': [100.0, 101.0], 'Close': [100.5, 101.5]},
                      index=pd.date_range('2020-01-02', periods=2))
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    p = _get_exec_price('AAPL', all_dates[0], 0, all_dates, price_data, 'same_close')
    assert p == 100.5

def test_get_exec_price_next_open():
    df = pd.DataFrame({'Open': [100.0, 101.0], 'Close': [100.5, 101.5]},
                      index=pd.date_range('2020-01-02', periods=2))
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    p = _get_exec_price('AAPL', all_dates[0], 0, all_dates, price_data, 'next_open')
    assert p == 101.0  # next day's Open

def test_get_exec_price_next_open_last_bar_returns_none():
    df = pd.DataFrame({'Open': [100.0], 'Close': [100.5]},
                      index=pd.date_range('2020-01-02', periods=1))
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    p = _get_exec_price('AAPL', all_dates[0], 0, all_dates, price_data, 'next_open')
    assert p is None

def test_get_exec_price_unknown_mode_raises():
    df = pd.DataFrame({'Close': [100.0]}, index=pd.date_range('2020-01-02', periods=1))
    with pytest.raises(ValueError, match="execution_mode"):
        _get_exec_price('AAPL', df.index[0], 0, list(df.index), {'AAPL': df}, 'weird_mode')
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest hydra_backtest/tests/test_engine.py -k exec_price -v`
Expected: FAIL

- [ ] **Step 3: Implement**

Append to `hydra_backtest/engine.py`:
```python
def _get_exec_price(
    symbol: str,
    date: pd.Timestamp,
    i: int,
    all_dates: list,
    price_data: Dict[str, pd.DataFrame],
    execution_mode: str,
) -> float | None:
    """Single source of truth for execution pricing.

    same_close: fill at price_data[symbol].loc[date, 'Close']
    next_open:  fill at price_data[symbol].loc[all_dates[i+1], 'Open']

    Returns None if the trade cannot be executed (last bar, symbol doesn't
    trade next day, etc.). Callers must handle None by skipping the action.
    """
    if execution_mode == 'same_close':
        df = price_data.get(symbol)
        if df is None or date not in df.index:
            return None
        price = float(df.loc[date, 'Close'])
        return price if price > 0 else None
    if execution_mode == 'next_open':
        if i + 1 >= len(all_dates):
            return None  # last bar — no next day
        next_date = all_dates[i + 1]
        df = price_data.get(symbol)
        if df is None or next_date not in df.index:
            return None
        price = float(df.loc[next_date, 'Open'])
        return price if price > 0 else None
    raise ValueError(f"Unknown execution_mode: {execution_mode!r}")
```

- [ ] **Step 4: Run tests**

Run: `pytest hydra_backtest/tests/test_engine.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/engine.py hydra_backtest/tests/test_engine.py
git commit -m "feat(hydra_backtest): _get_exec_price (same_close / next_open)"
```

---

## Task 13: apply_exits pure function

**Files:**
- Modify: `hydra_backtest/engine.py`
- Modify: `hydra_backtest/tests/test_engine.py`

The exit loop mirrors the live logic in `COMPASSLive._check_exits` and related methods (roughly line 2700+). Priority order: hold_expired (with renewal check) → position_stop → trailing_stop → universe_rotation → regime_reduce.

- [ ] **Step 1: Write failing tests for core exit paths**

Append to `hydra_backtest/tests/test_engine.py`:
```python
from hydra_backtest.engine import apply_exits


def _make_position(entry_price, shares, entry_idx, high_price=None):
    return {
        'entry_price': float(entry_price),
        'shares': float(shares),
        'entry_date': pd.Timestamp('2020-01-02'),
        'entry_idx': entry_idx,
        'original_entry_idx': entry_idx,
        'high_price': float(high_price or entry_price),
        'entry_vol': 0.25,
        'entry_daily_vol': 0.016,
        'sector': 'Tech',
    }

def test_apply_exits_hold_expired_no_renewal(minimal_config):
    state = BacktestState(
        cash=50_000.0,
        positions={'AAPL': _make_position(100.0, 10, entry_idx=0)},
        peak_value=51_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame({'Open': [100.0] * 10, 'Close': [100.0] * 10},
                      index=pd.date_range('2020-01-02', periods=10))
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    # Day 5 (index 5): hold_days = 5 - 0 = 5 ≥ HOLD_DAYS → exit
    new_state, trades, decisions = apply_exits(
        state, all_dates[5], 5, price_data, scores={}, tradeable=['AAPL'],
        max_positions=5, config=minimal_config, sector_map={'AAPL': 'Tech'},
        execution_mode='same_close', all_dates=all_dates,
    )
    assert 'AAPL' not in new_state.positions
    assert len(trades) == 1
    assert trades[0]['exit_reason'] == 'hold_expired'

def test_apply_exits_position_stop_fires(minimal_config):
    state = BacktestState(
        cash=50_000.0,
        positions={'AAPL': _make_position(100.0, 10, entry_idx=0)},
        peak_value=51_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    # -10% drop triggers adaptive stop (default -6% floor)
    df = pd.DataFrame({'Open': [90.0, 90.0], 'Close': [100.0, 90.0]},
                      index=pd.date_range('2020-01-02', periods=2))
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    new_state, trades, _ = apply_exits(
        state, all_dates[1], 1, price_data, scores={}, tradeable=['AAPL'],
        max_positions=5, config=minimal_config, sector_map={'AAPL': 'Tech'},
        execution_mode='same_close', all_dates=all_dates,
    )
    assert 'AAPL' not in new_state.positions
    assert trades[0]['exit_reason'] == 'position_stop'

def test_apply_exits_trailing_stop_fires(minimal_config):
    """Entry at 100, high reaches 110 (+10%), drops to 105 → trailing stop fires
    at high * (1 - TRAILING_STOP_PCT scaled)"""
    pos = _make_position(100.0, 10, entry_idx=0, high_price=110.0)
    state = BacktestState(
        cash=50_000.0, positions={'AAPL': pos},
        peak_value=51_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame({'Open': [100.0, 105.0], 'Close': [100.0, 105.0]},
                      index=pd.date_range('2020-01-02', periods=2))
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    new_state, trades, _ = apply_exits(
        state, all_dates[1], 1, price_data, scores={}, tradeable=['AAPL'],
        max_positions=5, config=minimal_config, sector_map={'AAPL': 'Tech'},
        execution_mode='same_close', all_dates=all_dates,
    )
    # Trailing level = 110 * (1 - 0.03) = 106.7; 105 < 106.7 → exit
    assert 'AAPL' not in new_state.positions
    assert trades[0]['exit_reason'] == 'trailing_stop'

def test_apply_exits_universe_rotation(minimal_config):
    state = BacktestState(
        cash=50_000.0,
        positions={'AAPL': _make_position(100.0, 10, entry_idx=0)},
        peak_value=51_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame({'Open': [100.0, 100.0], 'Close': [100.0, 100.0]},
                      index=pd.date_range('2020-01-02', periods=2))
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    new_state, trades, _ = apply_exits(
        state, all_dates[1], 1, price_data, scores={}, tradeable=[],  # AAPL NOT in universe
        max_positions=5, config=minimal_config, sector_map={'AAPL': 'Tech'},
        execution_mode='same_close', all_dates=all_dates,
    )
    assert 'AAPL' not in new_state.positions
    assert trades[0]['exit_reason'] == 'universe_rotation'

def test_apply_exits_next_open_mode_uses_next_open(minimal_config):
    state = BacktestState(
        cash=50_000.0,
        positions={'AAPL': _make_position(100.0, 10, entry_idx=0)},
        peak_value=51_000.0, crash_cooldown=0, portfolio_value_history=(),
    )
    df = pd.DataFrame({
        'Open': [100.0, 100.0, 95.0, 95.0, 95.0, 95.0, 95.0],  # gap down to 95
        'Close': [100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
    }, index=pd.date_range('2020-01-02', periods=7))
    price_data = {'AAPL': df}
    all_dates = list(df.index)
    new_state, trades, _ = apply_exits(
        state, all_dates[5], 5, price_data, scores={}, tradeable=['AAPL'],
        max_positions=5, config=minimal_config, sector_map={'AAPL': 'Tech'},
        execution_mode='next_open', all_dates=all_dates,
    )
    # hold_expired fires at i=5, fills at Open[6] = 95 (gap down captured)
    assert trades[0]['exit_reason'] == 'hold_expired'
    assert trades[0]['exit_price'] == 95.0
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest hydra_backtest/tests/test_engine.py -k apply_exits -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement apply_exits**

Append to `hydra_backtest/engine.py`:
```python
from omnicapital_live import compute_adaptive_stop


def apply_exits(
    state: BacktestState,
    date: pd.Timestamp,
    i: int,
    price_data: Dict[str, pd.DataFrame],
    scores: Dict[str, float],
    tradeable: List[str],
    max_positions: int,
    config: dict,
    sector_map: Dict[str, str],
    execution_mode: str,
    all_dates: list,
) -> Tuple[BacktestState, list, list]:
    """Evaluate and apply all exit conditions for open positions.

    Order (mirrors COMPASSLive._check_exits):
      1. hold_expired (with renewal check)
      2. position_stop (adaptive, vol-scaled)
      3. trailing_stop (vol-scaled)
      4. universe_rotation
      5. regime_reduce (worst performer if len > max_positions)

    Returns (new_state, trades_list, decisions_list).
    """
    trades = []
    decisions = []
    cash = state.cash
    positions = dict(state.positions)  # shallow copy

    for symbol in list(positions.keys()):
        pos = positions[symbol]
        df = price_data.get(symbol)
        if df is None or date not in df.index:
            continue
        current_price = float(df.loc[date, 'Close'])
        exit_reason = None

        # 1. Hold expired
        days_held = i - pos['entry_idx']
        if days_held >= config['HOLD_DAYS']:
            # v1 scope: position renewal (keeping winners) is intentionally omitted.
            # See spec §3 non-goals. Renewal will be added in a later version
            # by wiring in should_renew_position from omnicapital_live.
            exit_reason = 'hold_expired'

        # 2. Position stop (adaptive, vol-scaled)
        pos_return = (current_price - pos['entry_price']) / pos['entry_price']
        adaptive_stop = compute_adaptive_stop(pos.get('entry_daily_vol', 0.016), config)
        if pos_return <= adaptive_stop:
            exit_reason = 'position_stop'

        # 3. Trailing stop
        if current_price > pos['high_price']:
            pos = {**pos, 'high_price': current_price}
            positions[symbol] = pos
        if pos['high_price'] > pos['entry_price'] * (1 + config['TRAILING_ACTIVATION']):
            vol_ratio = pos.get('entry_vol', config['TRAILING_VOL_BASELINE']) / config['TRAILING_VOL_BASELINE']
            scaled_trailing = config['TRAILING_STOP_PCT'] * vol_ratio
            trailing_level = pos['high_price'] * (1 - scaled_trailing)
            if current_price <= trailing_level:
                exit_reason = 'trailing_stop'

        # 4. Universe rotation
        if symbol not in tradeable:
            exit_reason = 'universe_rotation'

        # 5. Regime reduce (excess position)
        if exit_reason is None and len(positions) > max_positions:
            pos_returns = {}
            for s, p in positions.items():
                sdf = price_data.get(s)
                if sdf is not None and date in sdf.index:
                    cp = float(sdf.loc[date, 'Close'])
                    pos_returns[s] = (cp - p['entry_price']) / p['entry_price']
            if pos_returns:
                worst = min(pos_returns, key=pos_returns.get)
                if symbol == worst:
                    exit_reason = 'regime_reduce'

        if exit_reason is None:
            continue

        # Resolve execution price
        exit_price = _get_exec_price(symbol, date, i, all_dates, price_data, execution_mode)
        if exit_price is None:
            continue  # cannot execute — position carries

        shares = pos['shares']
        proceeds = shares * exit_price
        commission = shares * config['COMMISSION_PER_SHARE']
        cash += proceeds - commission
        pnl = (exit_price - pos['entry_price']) * shares - commission
        exit_date = date if execution_mode == 'same_close' else all_dates[i + 1]

        trades.append({
            'symbol': symbol,
            'entry_date': pos['entry_date'],
            'exit_date': exit_date,
            'exit_reason': exit_reason,
            'entry_price': pos['entry_price'],
            'exit_price': exit_price,
            'shares': shares,
            'pnl': pnl,
            'return': pnl / (pos['entry_price'] * shares) if pos['entry_price'] > 0 else 0.0,
            'sector': sector_map.get(symbol, pos.get('sector', 'Unknown')),
        })
        decisions.append({
            'type': 'exit', 'symbol': symbol, 'date': str(date),
            'reason': exit_reason, 'exit_price': exit_price,
        })
        del positions[symbol]

    new_state = state._replace(cash=cash, positions=positions)
    return new_state, trades, decisions
```

- [ ] **Step 4: Run tests**

Run: `pytest hydra_backtest/tests/test_engine.py -v`
Expected: all pass (including the 5 new apply_exits tests)

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/engine.py hydra_backtest/tests/test_engine.py
git commit -m "feat(hydra_backtest): apply_exits with 5 exit reasons and exec modes"
```

---

## Task 14: apply_entries pure function

**Files:**
- Modify: `hydra_backtest/engine.py`
- Modify: `hydra_backtest/tests/test_engine.py`

- [ ] **Step 1: Write failing tests**

Append to `hydra_backtest/tests/test_engine.py`:
```python
from hydra_backtest.engine import apply_entries


def test_apply_entries_opens_positions_up_to_max(minimal_config):
    state = BacktestState(
        cash=100_000.0, positions={}, peak_value=100_000.0,
        crash_cooldown=0, portfolio_value_history=(),
    )
    # 5 tradeable tickers with scores, same sector for simplicity (bypass concentration)
    dates = pd.date_range('2020-01-02', periods=2)
    price_data = {}
    scores = {}
    sector_map = {}
    for i, sym in enumerate(['A', 'B', 'C', 'D', 'E']):
        price_data[sym] = pd.DataFrame({
            'Open': [100.0, 101.0],
            'Close': [100.0, 101.0],
            'Volume': [1e6, 1e6],
        }, index=dates)
        # Need >= MIN_AGE_DAYS of history for compute_entry_vol to be non-trivial
        extended = pd.DataFrame({
            'Open': [100.0] * 100, 'High': [100.0] * 100, 'Low': [100.0] * 100,
            'Close': [100.0 + j * 0.1 for j in range(100)], 'Volume': [1e6] * 100,
        }, index=pd.date_range('2019-08-15', periods=100))
        price_data[sym] = extended
        scores[sym] = 1.0 - i * 0.1
        sector_map[sym] = f'Sector{i}'  # Each in its own sector

    all_dates = list(extended.index)
    state2, decisions = apply_entries(
        state, all_dates[-1], len(all_dates) - 1, price_data, scores,
        tradeable=list(scores.keys()), max_positions=5, leverage=1.0,
        config=minimal_config, sector_map=sector_map, all_dates=all_dates,
        execution_mode='same_close',
    )
    assert len(state2.positions) == 5

def test_apply_entries_respects_sector_limit(minimal_config):
    minimal_config['MAX_PER_SECTOR'] = 2
    extended = pd.DataFrame({
        'Open': [100.0] * 100, 'High': [100.0] * 100, 'Low': [100.0] * 100,
        'Close': [100.0 + j * 0.1 for j in range(100)], 'Volume': [1e6] * 100,
    }, index=pd.date_range('2019-08-15', periods=100))
    price_data = {sym: extended for sym in ['A', 'B', 'C']}
    scores = {'A': 1.0, 'B': 0.9, 'C': 0.8}
    sector_map = {'A': 'Tech', 'B': 'Tech', 'C': 'Tech'}
    all_dates = list(extended.index)
    state = BacktestState(cash=100_000.0, positions={}, peak_value=100_000.0,
                           crash_cooldown=0, portfolio_value_history=())
    state2, _ = apply_entries(
        state, all_dates[-1], len(all_dates) - 1, price_data, scores,
        tradeable=list(scores.keys()), max_positions=5, leverage=1.0,
        config=minimal_config, sector_map=sector_map, all_dates=all_dates,
        execution_mode='same_close',
    )
    assert len(state2.positions) <= 2  # MAX_PER_SECTOR=2

def test_apply_entries_skips_if_cash_insufficient(minimal_config):
    extended = pd.DataFrame({
        'Open': [100.0] * 100, 'High': [100.0] * 100, 'Low': [100.0] * 100,
        'Close': [100.0] * 100, 'Volume': [1e6] * 100,
    }, index=pd.date_range('2019-08-15', periods=100))
    price_data = {'A': extended}
    state = BacktestState(cash=500.0, positions={}, peak_value=500.0,
                           crash_cooldown=0, portfolio_value_history=())
    state2, _ = apply_entries(
        state, extended.index[-1], len(extended) - 1, price_data, {'A': 1.0},
        tradeable=['A'], max_positions=5, leverage=1.0, config=minimal_config,
        sector_map={'A': 'Tech'}, all_dates=list(extended.index),
        execution_mode='same_close',
    )
    assert len(state2.positions) == 0  # cash < 1000 threshold
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest hydra_backtest/tests/test_engine.py -k apply_entries -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement apply_entries**

Append to `hydra_backtest/engine.py`:
```python
from omnicapital_live import (
    compute_volatility_weights,
    compute_entry_vol,
    filter_by_sector_concentration,
)


def apply_entries(
    state: BacktestState,
    date: pd.Timestamp,
    i: int,
    price_data: Dict[str, pd.DataFrame],
    scores: Dict[str, float],
    tradeable: List[str],
    max_positions: int,
    leverage: float,
    config: dict,
    sector_map: Dict[str, str],
    all_dates: list,
    execution_mode: str,
) -> Tuple[BacktestState, list]:
    """Evaluate and apply all entry decisions for this bar.

    Mirrors the entry loop in COMPASSLive._run_cycle. Filters by score,
    sector concentration, cash buffer, sizing, then opens positions.
    """
    decisions = []
    cash = state.cash
    positions = dict(state.positions)

    needed = max_positions - len(positions)
    if needed <= 0 or cash < 1000 or len(tradeable) < 5:
        return state, decisions

    available_scores = {s: sc for s, sc in scores.items() if s not in positions}
    if len(scores) < config['MIN_MOMENTUM_STOCKS'] or len(available_scores) < needed:
        return state, decisions

    # Rank and apply sector concentration filter (uses position sectors)
    ranked = sorted(available_scores.items(), key=lambda x: x[1], reverse=True)
    # Need to materialize positions with sector for the filter
    positions_for_filter = {
        sym: {**p, 'sector': sector_map.get(sym, p.get('sector', 'Unknown'))}
        for sym, p in positions.items()
    }
    sector_filtered = filter_by_sector_concentration(ranked, positions_for_filter)
    selected = [sym for sym, _ in sector_filtered[:needed]]
    if not selected:
        return state, decisions

    weights = compute_volatility_weights(price_data, selected, date)
    effective_capital = cash * leverage * 0.95  # 5% buffer

    for symbol in selected:
        df = price_data.get(symbol)
        if df is None or date not in df.index:
            continue

        entry_price = _get_exec_price(symbol, date, i, all_dates, price_data, execution_mode)
        if entry_price is None:
            continue

        weight = weights.get(symbol, 1.0 / len(selected))
        position_value = effective_capital * weight
        position_value = min(position_value, cash * 0.40)  # max 40% per pos

        shares = position_value / entry_price
        cost = shares * entry_price
        commission = shares * config['COMMISSION_PER_SHARE']
        if cost + commission > cash * 0.90:
            continue  # respects the 0.90 cash buffer

        entry_vol, entry_daily_vol = compute_entry_vol(price_data, symbol)

        # Determine the effective entry_date/entry_idx based on execution_mode
        if execution_mode == 'next_open':
            effective_entry_date = all_dates[i + 1]
            effective_entry_idx = i + 1
        else:
            effective_entry_date = date
            effective_entry_idx = i

        positions[symbol] = {
            'entry_price': entry_price,
            'shares': shares,
            'entry_date': effective_entry_date,
            'entry_idx': effective_entry_idx,
            'original_entry_idx': effective_entry_idx,
            'high_price': entry_price,
            'entry_vol': entry_vol,
            'entry_daily_vol': entry_daily_vol,
            'sector': sector_map.get(symbol, 'Unknown'),
        }
        cash -= cost + commission
        decisions.append({
            'type': 'entry', 'symbol': symbol, 'date': str(effective_entry_date),
            'entry_price': entry_price, 'shares': shares, 'score': scores[symbol],
        })

    return state._replace(cash=cash, positions=positions), decisions
```

- [ ] **Step 4: Run tests**

Run: `pytest hydra_backtest/tests/test_engine.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/engine.py hydra_backtest/tests/test_engine.py
git commit -m "feat(hydra_backtest): apply_entries with sector filter and exec modes"
```

---

## Task 15: run_backtest orchestrator

**Files:**
- Modify: `hydra_backtest/engine.py`
- Modify: `hydra_backtest/tests/test_engine.py`

- [ ] **Step 1: Write failing integration test**

Append to `hydra_backtest/tests/test_engine.py`:
```python
from hydra_backtest.engine import run_backtest


def test_run_backtest_smoke(minimal_config):
    """Minimal 20-day backtest with 25 synthetic tickers. Just verify it runs
    to completion and returns a valid BacktestResult."""
    dates = pd.date_range('2020-01-02', periods=200)
    import numpy as np
    np.random.seed(666)

    price_data = {}
    for i in range(30):
        base = 100.0 + i
        returns = np.random.normal(0.0005, 0.015, 200)
        closes = base * np.exp(np.cumsum(returns))
        price_data[f'T{i:02d}'] = pd.DataFrame({
            'Open': closes, 'High': closes * 1.005, 'Low': closes * 0.995,
            'Close': closes, 'Volume': [1e6] * 200,
        }, index=dates)

    # SPY
    spy_close = 100.0 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, 200)))
    spy_data = pd.DataFrame({'Close': spy_close}, index=dates)

    pit_universe = {2020: [f'T{i:02d}' for i in range(30)]}
    sector_map = {f'T{i:02d}': f'Sector{i % 5}' for i in range(30)}
    cash_yield = pd.Series([3.5] * 200, index=dates)

    result = run_backtest(
        config=minimal_config, price_data=price_data, pit_universe=pit_universe,
        spy_data=spy_data, cash_yield_daily=cash_yield, sector_map=sector_map,
        start_date=dates[0], end_date=dates[-1], execution_mode='same_close',
    )
    assert isinstance(result, BacktestResult)
    assert len(result.daily_values) == 200
    assert 'portfolio_value' in result.daily_values.columns
    assert result.daily_values['portfolio_value'].iloc[0] > 0
    assert len(result.git_sha) > 0
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest hydra_backtest/tests/test_engine.py -k run_backtest_smoke -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement run_backtest**

Append to `hydra_backtest/engine.py`:
```python
import subprocess
from datetime import datetime

from omnicapital_live import (
    compute_live_regime_score,
    compute_momentum_scores,
    compute_quality_filter,
)

from hydra_backtest.data import compute_data_fingerprint


def _capture_git_sha() -> str:
    """Get current git commit sha, or 'unknown' if not in a repo."""
    try:
        out = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return 'unknown'


def run_backtest(
    config: dict,
    price_data: Dict[str, pd.DataFrame],
    pit_universe: Dict[int, List[str]],
    spy_data: pd.DataFrame,
    cash_yield_daily: pd.Series,
    sector_map: Dict[str, str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    execution_mode: str = 'same_close',
) -> BacktestResult:
    """Run a COMPASS backtest from start_date to end_date.

    Produces a BacktestResult with daily equity curve, all trades, and
    the full decision log. This function has no side effects — pure in
    / pure out.
    """
    started_at = datetime.now()

    # Aggregate all trading dates from price_data
    all_dates_set = set()
    for df in price_data.values():
        all_dates_set.update(df.index)
    all_dates = sorted(all_dates_set)

    state = BacktestState(
        cash=float(config['INITIAL_CAPITAL']),
        positions={},
        peak_value=float(config['INITIAL_CAPITAL']),
        crash_cooldown=0,
        portfolio_value_history=(),
    )

    trades: list = []
    decisions: list = []
    snapshots: list = []
    universe_size: Dict[int, int] = {}

    for i, date in enumerate(all_dates):
        if date < start_date or date > end_date:
            continue

        # 1. Mark-to-market
        portfolio_value = _mark_to_market(state, price_data, date)

        # 2. Universe
        tradeable = get_tradeable_symbols(
            pit_universe, price_data, date, min_age_days=config['MIN_AGE_DAYS']
        )
        universe_size[date.year] = max(universe_size.get(date.year, 0), len(tradeable))

        # 3. Regime + drawdown + leverage
        spy_slice = spy_data.loc[:date]
        regime_score = compute_live_regime_score(spy_slice)
        drawdown = (portfolio_value - state.peak_value) / state.peak_value if state.peak_value > 0 else 0.0

        leverage, new_cooldown, crash_active = get_current_leverage_pure(
            drawdown=drawdown,
            portfolio_value_history=state.portfolio_value_history + (portfolio_value,),
            crash_cooldown=state.crash_cooldown,
            config=config, spy_hist=spy_slice,
        )
        max_positions = get_max_positions_pure(regime_score, spy_slice, config)

        # 4. Daily costs
        daily_yield = float(cash_yield_daily.get(date, cash_yield_daily.iloc[0] if len(cash_yield_daily) else 0.0))
        state = apply_daily_costs(state, leverage, daily_yield, portfolio_value, config)

        # 5. Signals
        quality_syms = compute_quality_filter(price_data, tradeable, date)
        scores = compute_momentum_scores(price_data, quality_syms, date, all_dates, i)

        # 6. Exits
        state, exit_trades, exit_decisions = apply_exits(
            state, date, i, price_data, scores, tradeable,
            max_positions, config, sector_map, execution_mode, all_dates,
        )
        trades.extend(exit_trades)
        decisions.extend(exit_decisions)

        # 7. Entries
        state, entry_decisions = apply_entries(
            state, date, i, price_data, scores, tradeable,
            max_positions, leverage, config, sector_map, all_dates, execution_mode,
        )
        decisions.extend(entry_decisions)

        # 8. Record snapshot (AFTER exits and entries — reflects end-of-day state)
        pv_after = _mark_to_market(state, price_data, date)
        snapshots.append({
            'date': date,
            'portfolio_value': pv_after,
            'cash': state.cash,
            'n_positions': len(state.positions),
            'leverage': leverage,
            'drawdown': drawdown,
            'regime_score': regime_score,
            'crash_active': crash_active,
            'max_positions': max_positions,
        })

        # 9. Update state tail (history, cooldown, peak)
        new_peak = max(state.peak_value, pv_after)
        decayed_cooldown = max(new_cooldown - 1, 0) if not crash_active else new_cooldown
        state = state._replace(
            peak_value=new_peak,
            crash_cooldown=decayed_cooldown,
            portfolio_value_history=state.portfolio_value_history + (pv_after,),
        )

    finished_at = datetime.now()

    return BacktestResult(
        config=dict(config),
        daily_values=pd.DataFrame(snapshots),
        trades=pd.DataFrame(trades) if trades else pd.DataFrame(
            columns=['symbol', 'entry_date', 'exit_date', 'exit_reason', 'entry_price',
                     'exit_price', 'shares', 'pnl', 'return', 'sector']
        ),
        decisions=decisions,
        exit_events=[t for t in trades if t['exit_reason'] in ('position_stop', 'trailing_stop')],
        universe_size=universe_size,
        started_at=started_at,
        finished_at=finished_at,
        git_sha=_capture_git_sha(),
        data_inputs_hash=compute_data_fingerprint(price_data),
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest hydra_backtest/tests/test_engine.py -v`
Expected: all pass (the synthetic 200-day backtest should complete in a few seconds)

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/engine.py hydra_backtest/tests/test_engine.py
git commit -m "feat(hydra_backtest): run_backtest orchestrator"
```

---

## Task 16: methodology — compute_metrics

**Files:**
- Create: `hydra_backtest/methodology.py`
- Create: `hydra_backtest/tests/test_methodology.py`

- [ ] **Step 1: Write failing tests**

Create `hydra_backtest/tests/test_methodology.py`:
```python
import pandas as pd
import pytest
from hydra_backtest.methodology import compute_metrics


def test_compute_metrics_steady_5pct_growth():
    """A perfectly steady 5% annual growth should give CAGR ≈ 5%."""
    dates = pd.date_range('2020-01-01', periods=252 * 3)
    values = [100_000 * (1 + 0.05 / 252) ** i for i in range(len(dates))]
    daily = pd.DataFrame({'date': dates, 'portfolio_value': values})
    m = compute_metrics(daily, risk_free_rate_annual=0.0)
    assert abs(m['cagr'] - 0.05) < 0.002

def test_compute_metrics_max_drawdown():
    dates = pd.date_range('2020-01-01', periods=100)
    values = [100_000] * 50 + [50_000] * 50  # -50% drawdown
    daily = pd.DataFrame({'date': dates, 'portfolio_value': values})
    m = compute_metrics(daily, risk_free_rate_annual=0.0)
    assert abs(m['max_drawdown'] - (-0.5)) < 1e-9

def test_compute_metrics_sharpe_rf_adjustment():
    """Sharpe should decrease when rf is increased (excess return drops)."""
    dates = pd.date_range('2020-01-01', periods=252 * 2)
    values = [100_000 * (1 + 0.10 / 252) ** i for i in range(len(dates))]
    daily = pd.DataFrame({'date': dates, 'portfolio_value': values})
    m0 = compute_metrics(daily, risk_free_rate_annual=0.0)
    m3 = compute_metrics(daily, risk_free_rate_annual=0.03)
    assert m3['sharpe'] < m0['sharpe']
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest hydra_backtest/tests/test_methodology.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement**

Create `hydra_backtest/methodology.py`:
```python
"""Methodology — metrics computation and waterfall corrections.

All functions are pure: they take BacktestResult objects (or DataFrames)
and return new metrics or new results. No I/O, no side effects.
"""
import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, List, Optional

from hydra_backtest.engine import BacktestResult


def compute_metrics(daily_values: pd.DataFrame,
                     risk_free_rate_annual: float = 0.0) -> Dict[str, float]:
    """Compute standard performance metrics from a daily equity curve.

    daily_values must have columns ('date', 'portfolio_value').
    risk_free_rate_annual is in decimal (0.035 = 3.5%).
    """
    if len(daily_values) < 2:
        return {
            'cagr': 0.0, 'sharpe': 0.0, 'sortino': 0.0, 'calmar': 0.0,
            'max_drawdown': 0.0, 'volatility': 0.0, 'final_value': 0.0,
        }

    values = daily_values['portfolio_value'].astype(float).values
    dates = pd.to_datetime(daily_values['date'])
    start_val = values[0]
    final_val = values[-1]

    # CAGR
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    if years <= 0 or start_val <= 0:
        cagr = 0.0
    else:
        cagr = (final_val / start_val) ** (1 / years) - 1

    # Daily returns
    returns = pd.Series(values).pct_change().dropna().values
    if len(returns) < 2:
        return {'cagr': cagr, 'sharpe': 0.0, 'sortino': 0.0, 'calmar': 0.0,
                'max_drawdown': 0.0, 'volatility': 0.0, 'final_value': final_val}

    vol_ann = float(np.std(returns, ddof=1) * np.sqrt(252))

    daily_rf = risk_free_rate_annual / 252
    excess = returns - daily_rf
    sharpe = float((np.mean(excess) * 252) / (np.std(excess, ddof=1) * np.sqrt(252))) if np.std(excess, ddof=1) > 0 else 0.0

    downside = excess[excess < 0]
    sortino = float((np.mean(excess) * 252) / (np.std(downside, ddof=1) * np.sqrt(252))) if len(downside) > 1 and np.std(downside, ddof=1) > 0 else 0.0

    # Max drawdown
    peaks = np.maximum.accumulate(values)
    dd_series = (values - peaks) / peaks
    max_dd = float(dd_series.min())

    calmar = cagr / abs(max_dd) if max_dd < 0 else 0.0

    return {
        'cagr': float(cagr),
        'sharpe': sharpe,
        'sortino': sortino,
        'calmar': calmar,
        'max_drawdown': max_dd,
        'volatility': vol_ann,
        'final_value': float(final_val),
    }
```

- [ ] **Step 4: Run tests**

Run: `pytest hydra_backtest/tests/test_methodology.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/methodology.py hydra_backtest/tests/test_methodology.py
git commit -m "feat(hydra_backtest): compute_metrics (CAGR, Sharpe, MaxDD, Sortino, Calmar)"
```

---

## Task 17: methodology — waterfall builder + tier_3 post-process

**Files:**
- Modify: `hydra_backtest/methodology.py`
- Modify: `hydra_backtest/tests/test_methodology.py`

- [ ] **Step 1: Write failing tests**

Append to `hydra_backtest/tests/test_methodology.py`:
```python
from hydra_backtest.methodology import (
    WaterfallTier, WaterfallReport, apply_slippage_postprocess, build_waterfall,
)
from hydra_backtest.engine import BacktestResult
from datetime import datetime


def _fake_result(cagr_target=0.10):
    """Build a fake BacktestResult with a given CAGR."""
    dates = pd.date_range('2020-01-01', periods=252 * 3)
    values = [100_000 * (1 + cagr_target / 252) ** i for i in range(len(dates))]
    daily = pd.DataFrame({'date': dates, 'portfolio_value': values, 'cash': values,
                          'n_positions': [5] * len(dates), 'leverage': [1.0] * len(dates),
                          'drawdown': [0.0] * len(dates),
                          'regime_score': [0.7] * len(dates),
                          'crash_active': [False] * len(dates),
                          'max_positions': [5] * len(dates)})
    trades = pd.DataFrame([{
        'symbol': 'AAPL', 'entry_date': dates[0], 'exit_date': dates[5],
        'exit_reason': 'hold_expired', 'entry_price': 100.0, 'exit_price': 105.0,
        'shares': 10.0, 'pnl': 50.0, 'return': 0.05, 'sector': 'Tech',
    }])
    return BacktestResult(
        config={}, daily_values=daily, trades=trades, decisions=[], exit_events=[],
        universe_size={2020: 30}, started_at=datetime(2026, 4, 6), finished_at=datetime(2026, 4, 6),
        git_sha='test', data_inputs_hash='test',
    )


def test_apply_slippage_postprocess_reduces_pnl():
    result = _fake_result(cagr_target=0.12)
    adjusted = apply_slippage_postprocess(result, slippage_bps=2.0, half_spread_bps=0.5)
    # Original pnl = 50, adjusted should be lower (both entry and exit penalized)
    assert adjusted.trades['pnl'].iloc[0] < 50.0
    # Trades count unchanged
    assert len(adjusted.trades) == len(result.trades)

def test_apply_slippage_postprocess_affects_equity_curve():
    result = _fake_result(cagr_target=0.12)
    adjusted = apply_slippage_postprocess(result, slippage_bps=5.0, half_spread_bps=2.0)
    # Adjusted final value must be strictly less
    assert adjusted.daily_values['portfolio_value'].iloc[-1] < result.daily_values['portfolio_value'].iloc[-1]

def test_build_waterfall_returns_four_tiers():
    """build_waterfall takes 3 results (tier 0, 1, 2) and post-processes tier 3."""
    r0 = _fake_result(cagr_target=0.12)
    r1 = _fake_result(cagr_target=0.11)
    r2 = _fake_result(cagr_target=0.105)
    report = build_waterfall(
        tier_0=r0, tier_1=r1, tier_2=r2,
        t_bill_rf=0.03, slippage_bps=2.0, half_spread_bps=0.5,
    )
    assert len(report.tiers) == 5  # baseline, t_bill, next_open, real_costs, net_honest (alias of real_costs)
    names = [t.name for t in report.tiers]
    assert names == ['baseline', 't_bill', 'next_open', 'real_costs', 'net_honest']
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest hydra_backtest/tests/test_methodology.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement waterfall**

Append to `hydra_backtest/methodology.py`:
```python
from dataclasses import dataclass, field, replace as dc_replace


@dataclass(frozen=True)
class WaterfallTier:
    name: str
    description: str
    cagr: float
    sharpe: float
    sortino: float
    calmar: float
    max_drawdown: float
    volatility: float
    final_value: float
    delta_cagr_bps: float = 0.0
    delta_sharpe: float = 0.0
    delta_maxdd_bps: float = 0.0


@dataclass(frozen=True)
class WaterfallReport:
    tiers: List[WaterfallTier]
    baseline_result: BacktestResult
    net_honest_result: BacktestResult


def apply_slippage_postprocess(
    result: BacktestResult,
    slippage_bps: float,
    half_spread_bps: float,
) -> BacktestResult:
    """Apply per-trade slippage + half-spread to an existing BacktestResult.

    Works as post-process because costs are a small fraction that does not
    alter signal/stop decisions. Entry and exit prices are each penalized
    by (slippage + half_spread) bps, and the equity curve is rebuilt from
    the adjusted trades.
    """
    if result.trades.empty:
        return result

    total_bps = (slippage_bps + half_spread_bps) / 10000.0
    trades = result.trades.copy()

    # Entry penalty: pay (1 + cost) * price  →  higher cost
    # Exit penalty:  receive (1 - cost) * price → lower proceeds
    adjusted_entry = trades['entry_price'] * (1 + total_bps)
    adjusted_exit = trades['exit_price'] * (1 - total_bps)
    trades['entry_price'] = adjusted_entry
    trades['exit_price'] = adjusted_exit
    trades['pnl'] = (adjusted_exit - adjusted_entry) * trades['shares']
    trades['return'] = trades['pnl'] / (adjusted_entry * trades['shares'])

    # Rebuild equity curve from the original daily_values minus extra costs
    # Approximation: apply cumulative bps cost at exit dates
    daily = result.daily_values.copy()
    cumulative_drag = 0.0
    for _, trade in trades.iterrows():
        trade_notional = abs(trade['shares'] * (trade['entry_price'] + trade['exit_price']) / 2.0)
        extra_cost = trade_notional * 2 * total_bps  # round trip
        cumulative_drag += extra_cost
        # Apply the drag starting at the exit_date
        mask = pd.to_datetime(daily['date']) >= pd.to_datetime(trade['exit_date'])
        daily.loc[mask, 'portfolio_value'] -= extra_cost

    return BacktestResult(
        config=result.config, daily_values=daily, trades=trades,
        decisions=result.decisions, exit_events=result.exit_events,
        universe_size=result.universe_size, started_at=result.started_at,
        finished_at=result.finished_at, git_sha=result.git_sha,
        data_inputs_hash=result.data_inputs_hash,
    )


def _tier_from_result(name: str, desc: str, result: BacktestResult,
                       rf: float = 0.0) -> WaterfallTier:
    m = compute_metrics(result.daily_values, risk_free_rate_annual=rf)
    return WaterfallTier(
        name=name, description=desc,
        cagr=m['cagr'], sharpe=m['sharpe'], sortino=m['sortino'],
        calmar=m['calmar'], max_drawdown=m['max_drawdown'],
        volatility=m['volatility'], final_value=m['final_value'],
    )


def _with_deltas(tiers: List[WaterfallTier]) -> List[WaterfallTier]:
    """Return a new list of tiers with delta_* fields populated vs. previous tier."""
    out = [tiers[0]]
    for i in range(1, len(tiers)):
        prev = out[i - 1]
        curr = tiers[i]
        out.append(WaterfallTier(
            name=curr.name, description=curr.description,
            cagr=curr.cagr, sharpe=curr.sharpe, sortino=curr.sortino,
            calmar=curr.calmar, max_drawdown=curr.max_drawdown,
            volatility=curr.volatility, final_value=curr.final_value,
            delta_cagr_bps=(curr.cagr - prev.cagr) * 10000.0,
            delta_sharpe=(curr.sharpe - prev.sharpe),
            delta_maxdd_bps=(curr.max_drawdown - prev.max_drawdown) * 10000.0,
        ))
    return out


def build_waterfall(
    tier_0: BacktestResult,
    tier_1: BacktestResult,
    tier_2: BacktestResult,
    t_bill_rf: float,
    slippage_bps: float,
    half_spread_bps: float,
) -> WaterfallReport:
    """Build a full WaterfallReport from 3 backtest runs + post-processing.

    tier_0: baseline — Aaa cash yield, same_close execution
    tier_1: + T-bill cash yield (re-run)
    tier_2: + next_open execution (re-run)
    tier_3: + slippage + half-spread (post-process of tier_2)
    net_honest: alias for tier_3
    """
    tier_3_result = apply_slippage_postprocess(tier_2, slippage_bps, half_spread_bps)

    tiers_raw = [
        _tier_from_result('baseline', 'Live methodology (Aaa cash, same-close exec)', tier_0),
        _tier_from_result('t_bill', '+ T-bill 3M cash yield', tier_1, rf=t_bill_rf),
        _tier_from_result('next_open', '+ next-open execution', tier_2, rf=t_bill_rf),
        _tier_from_result('real_costs', '+ slippage and half-spread', tier_3_result, rf=t_bill_rf),
    ]
    tiers_raw.append(WaterfallTier(
        name='net_honest', description='NET HONEST — all corrections applied',
        cagr=tiers_raw[-1].cagr, sharpe=tiers_raw[-1].sharpe,
        sortino=tiers_raw[-1].sortino, calmar=tiers_raw[-1].calmar,
        max_drawdown=tiers_raw[-1].max_drawdown,
        volatility=tiers_raw[-1].volatility,
        final_value=tiers_raw[-1].final_value,
    ))
    tiers_with_deltas = _with_deltas(tiers_raw)

    return WaterfallReport(
        tiers=tiers_with_deltas,
        baseline_result=tier_0,
        net_honest_result=tier_3_result,
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest hydra_backtest/tests/test_methodology.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/methodology.py hydra_backtest/tests/test_methodology.py
git commit -m "feat(hydra_backtest): waterfall builder + slippage post-process"
```

---

## Task 18: Validation — smoke tests (Layer A, blocking)

**Files:**
- Create: `hydra_backtest/validation.py`
- Create: `hydra_backtest/tests/test_validation.py`

- [ ] **Step 1: Write failing tests**

Create `hydra_backtest/tests/test_validation.py`:
```python
import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from hydra_backtest.validation import run_smoke_tests
from hydra_backtest.engine import BacktestResult
from hydra_backtest.errors import HydraBacktestValidationError


def _good_result():
    dates = pd.date_range('2020-01-01', periods=500)
    values = [100_000 * (1 + 0.0005) ** i for i in range(500)]
    daily = pd.DataFrame({
        'date': dates, 'portfolio_value': values, 'cash': values,
        'n_positions': [5] * 500, 'leverage': [0.8] * 500,
        'drawdown': [0.0] * 500, 'regime_score': [0.7] * 500,
        'crash_active': [False] * 500, 'max_positions': [5] * 500,
    })
    trades = pd.DataFrame(columns=['symbol', 'entry_date', 'exit_date', 'exit_reason',
                                    'entry_price', 'exit_price', 'shares', 'pnl', 'return', 'sector'])
    return BacktestResult(
        config={'NUM_POSITIONS': 5, 'LEVERAGE_MAX': 1.0, 'CRASH_LEVERAGE': 0.15,
                'LEV_FLOOR': 0.30, 'BULL_OVERRIDE_THRESHOLD': 0.03, 'MAX_PER_SECTOR': 3,
                'HOLD_DAYS': 5, 'STOP_FLOOR': -0.06, 'STOP_CEILING': -0.15},
        daily_values=daily, trades=trades, decisions=[], exit_events=[],
        universe_size={2020: 40}, started_at=datetime(2026, 4, 6),
        finished_at=datetime(2026, 4, 6), git_sha='test', data_inputs_hash='test',
    )


def test_smoke_tests_pass_for_good_result():
    run_smoke_tests(_good_result())  # should not raise

def test_smoke_tests_detect_nan():
    r = _good_result()
    r.daily_values.loc[10, 'portfolio_value'] = float('nan')
    with pytest.raises(HydraBacktestValidationError, match="NaN"):
        run_smoke_tests(r)

def test_smoke_tests_detect_negative_cash():
    r = _good_result()
    r.daily_values.loc[5, 'cash'] = -1000.0
    with pytest.raises(HydraBacktestValidationError, match="cash"):
        run_smoke_tests(r)

def test_smoke_tests_detect_leverage_out_of_range():
    r = _good_result()
    r.daily_values.loc[10, 'leverage'] = 2.5
    with pytest.raises(HydraBacktestValidationError, match="leverage"):
        run_smoke_tests(r)

def test_smoke_tests_detect_too_many_positions():
    r = _good_result()
    r.daily_values.loc[10, 'n_positions'] = 20
    with pytest.raises(HydraBacktestValidationError, match="n_positions"):
        run_smoke_tests(r)

def test_smoke_tests_detect_drawdown_below_neg_one():
    r = _good_result()
    r.daily_values.loc[10, 'drawdown'] = -1.5
    with pytest.raises(HydraBacktestValidationError, match="drawdown"):
        run_smoke_tests(r)
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest hydra_backtest/tests/test_validation.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement validation**

Create `hydra_backtest/validation.py`:
```python
"""Layer A smoke tests — blocking for v1.

Mathematical invariants, statistical sanity, config consistency.
Runs after each backtest run, before reporting. Fails loud.
"""
import numpy as np
import pandas as pd
from hydra_backtest.engine import BacktestResult
from hydra_backtest.errors import HydraBacktestValidationError


# Known crash dates where daily returns can legitimately exceed ±15%
_CRASH_ALLOWLIST = {
    pd.Timestamp('2008-09-29'),  # Lehman
    pd.Timestamp('2008-10-13'),  # bounce
    pd.Timestamp('2008-10-15'),
    pd.Timestamp('2020-03-16'),  # COVID crash
    pd.Timestamp('2020-03-12'),
    pd.Timestamp('2020-03-13'),
    pd.Timestamp('2020-03-24'),
}


def run_smoke_tests(result: BacktestResult) -> None:
    """Run all Layer A smoke tests. Raises HydraBacktestValidationError on any failure."""
    daily = result.daily_values
    config = result.config

    if len(daily) == 0:
        raise HydraBacktestValidationError("Backtest produced empty daily_values")

    # 1. No NaN in daily_values
    for col in ('portfolio_value', 'cash', 'drawdown', 'leverage'):
        if col in daily.columns and daily[col].isna().any():
            raise HydraBacktestValidationError(
                f"NaN detected in daily_values column: {col}"
            )

    # 2. Cash conservation (loose check): cash never arbitrarily negative
    if (daily['cash'] < -1.0).any():
        raise HydraBacktestValidationError(
            f"Negative cash detected: min = {daily['cash'].min()}"
        )

    # 3. Drawdown bounds
    if (daily['drawdown'] < -1.0).any() or (daily['drawdown'] > 0.0001).any():
        raise HydraBacktestValidationError(
            f"drawdown out of [-1.0, 0] range: min={daily['drawdown'].min()}, max={daily['drawdown'].max()}"
        )

    # 4. Leverage bounds
    lev_min = config.get('CRASH_LEVERAGE', 0.15) - 1e-6
    lev_max = config.get('LEVERAGE_MAX', 1.0) + 1e-6
    if (daily['leverage'] < lev_min).any() or (daily['leverage'] > lev_max).any():
        raise HydraBacktestValidationError(
            f"leverage out of [{lev_min}, {lev_max}] range"
        )

    # 5. Position count bounds
    # bull override can add +1 to NUM_POSITIONS, so allow NUM_POSITIONS + 1
    n_max = config.get('NUM_POSITIONS', 5) + 1
    if (daily['n_positions'] < 0).any() or (daily['n_positions'] > n_max).any():
        raise HydraBacktestValidationError(
            f"n_positions out of [0, {n_max}] range"
        )

    # 6. Peak monotonic (drawdown is always ≤ 0)
    pv = daily['portfolio_value'].values
    peak = np.maximum.accumulate(pv)
    if not np.all(np.diff(peak) >= -1e-6):
        raise HydraBacktestValidationError("Peak portfolio value is not monotonic non-decreasing")

    # 7. Statistical sanity — vol
    returns = daily['portfolio_value'].pct_change().dropna()
    if len(returns) > 20:
        vol_ann = float(returns.std() * np.sqrt(252))
        if not (0.03 <= vol_ann <= 0.50):
            raise HydraBacktestValidationError(
                f"Annualized volatility out of sanity range [3%, 50%]: {vol_ann:.2%}"
            )

    # 8. Outlier daily returns (except allowlist)
    dates = pd.to_datetime(daily['date'])
    for i, (ts, ret) in enumerate(zip(dates.iloc[1:], returns)):
        if abs(ret) > 0.15 and ts not in _CRASH_ALLOWLIST:
            raise HydraBacktestValidationError(
                f"Outlier daily return {ret:.2%} on {ts.date()} not in crash allowlist"
            )

    # 9. Stop adherence (if trades exist)
    trades = result.trades
    if not trades.empty:
        stops = trades[trades['exit_reason'] == 'position_stop']
        if not stops.empty:
            bad_stops = stops[stops['return'] > 0.01]
            if len(bad_stops) > 0:
                raise HydraBacktestValidationError(
                    f"{len(bad_stops)} position_stop exits have positive return"
                )
```

- [ ] **Step 4: Run tests**

Run: `pytest hydra_backtest/tests/test_validation.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/validation.py hydra_backtest/tests/test_validation.py
git commit -m "feat(hydra_backtest): Layer A smoke tests (blocking validation)"
```

---

## Task 19: Reporting — CSV, JSON, and stdout writers

**Files:**
- Create: `hydra_backtest/reporting.py`
- Create: `hydra_backtest/tests/test_reporting.py`

- [ ] **Step 1: Write failing tests**

Create `hydra_backtest/tests/test_reporting.py`:
```python
import json
import pandas as pd
import pytest
from datetime import datetime
from hydra_backtest.reporting import (
    write_daily_csv, write_trades_csv, write_waterfall_json, format_summary_table,
)
from hydra_backtest.engine import BacktestResult
from hydra_backtest.methodology import WaterfallReport, WaterfallTier


def _mock_result():
    dates = pd.date_range('2020-01-01', periods=10)
    daily = pd.DataFrame({
        'date': dates,
        'portfolio_value': [100_000 + i * 100 for i in range(10)],
        'cash': [50_000] * 10, 'n_positions': [5] * 10, 'leverage': [0.8] * 10,
        'drawdown': [0.0] * 10, 'regime_score': [0.7] * 10,
        'crash_active': [False] * 10, 'max_positions': [5] * 10,
    })
    trades = pd.DataFrame([{
        'symbol': 'AAPL', 'entry_date': dates[0], 'exit_date': dates[5],
        'exit_reason': 'hold_expired', 'entry_price': 100.0, 'exit_price': 105.0,
        'shares': 10.0, 'pnl': 50.0, 'return': 0.05, 'sector': 'Tech',
    }])
    return BacktestResult(
        config={}, daily_values=daily, trades=trades, decisions=[], exit_events=[],
        universe_size={2020: 40}, started_at=datetime.now(), finished_at=datetime.now(),
        git_sha='abc', data_inputs_hash='def',
    )


def test_write_daily_csv(tmp_path):
    result = _mock_result()
    path = tmp_path / 'daily.csv'
    write_daily_csv(result, str(path))
    df = pd.read_csv(path)
    assert 'date' in df.columns
    assert 'portfolio_value' in df.columns
    assert len(df) == 10

def test_write_trades_csv(tmp_path):
    result = _mock_result()
    path = tmp_path / 'trades.csv'
    write_trades_csv(result, str(path))
    df = pd.read_csv(path)
    assert 'symbol' in df.columns
    assert len(df) == 1

def test_write_waterfall_json(tmp_path):
    tier = WaterfallTier(
        name='baseline', description='baseline', cagr=0.12, sharpe=0.85,
        sortino=1.1, calmar=0.4, max_drawdown=-0.30, volatility=0.14, final_value=2_000_000,
    )
    report = WaterfallReport(tiers=[tier], baseline_result=_mock_result(),
                              net_honest_result=_mock_result())
    path = tmp_path / 'waterfall.json'
    write_waterfall_json(report, str(path))
    with open(path) as f:
        data = json.load(f)
    assert 'tiers' in data
    assert data['tiers'][0]['name'] == 'baseline'

def test_format_summary_table():
    tier = WaterfallTier(
        name='baseline', description='live', cagr=0.1234, sharpe=0.85,
        sortino=1.1, calmar=0.4, max_drawdown=-0.30, volatility=0.14, final_value=2_000_000,
    )
    report = WaterfallReport(tiers=[tier], baseline_result=_mock_result(),
                              net_honest_result=_mock_result())
    text = format_summary_table(report)
    assert 'baseline' in text
    assert '12.34' in text  # CAGR as %
```

- [ ] **Step 2: Run to verify fail**

Run: `pytest hydra_backtest/tests/test_reporting.py -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement reporting**

Create `hydra_backtest/reporting.py`:
```python
"""Reporting — output writers for CSVs, JSON, and stdout summary."""
import json
import os

import pandas as pd

from hydra_backtest.engine import BacktestResult
from hydra_backtest.methodology import WaterfallReport


def write_daily_csv(result: BacktestResult, path: str) -> None:
    """Write the daily equity curve as CSV with schema matching hydra_clean_daily.csv.

    Columns: date, portfolio_value, cash, n_positions, leverage, drawdown,
             regime_score, crash_active, max_positions
    """
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    result.daily_values.to_csv(path, index=False)


def write_trades_csv(result: BacktestResult, path: str) -> None:
    """Write all trades as CSV."""
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    result.trades.to_csv(path, index=False)


def write_waterfall_json(report: WaterfallReport, path: str) -> None:
    """Write the waterfall report as JSON.

    Schema: { "tiers": [ { "name", "description", "cagr", "sharpe", ... } ],
              "metadata": { "git_sha", "data_inputs_hash", "started_at", "finished_at" } }
    """
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    baseline = report.baseline_result
    data = {
        'tiers': [
            {
                'name': t.name, 'description': t.description,
                'cagr': t.cagr, 'sharpe': t.sharpe, 'sortino': t.sortino,
                'calmar': t.calmar, 'max_drawdown': t.max_drawdown,
                'volatility': t.volatility, 'final_value': t.final_value,
                'delta_cagr_bps': t.delta_cagr_bps,
                'delta_sharpe': t.delta_sharpe,
                'delta_maxdd_bps': t.delta_maxdd_bps,
            }
            for t in report.tiers
        ],
        'metadata': {
            'git_sha': baseline.git_sha,
            'data_inputs_hash': baseline.data_inputs_hash,
            'started_at': baseline.started_at.isoformat(),
            'finished_at': baseline.finished_at.isoformat(),
        },
    }
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def format_summary_table(report: WaterfallReport) -> str:
    """Render the waterfall as a fixed-width ASCII table for stdout."""
    lines = []
    lines.append('=' * 90)
    lines.append(f"{'Tier':<14} {'CAGR':>8} {'Sharpe':>8} {'MaxDD':>10} {'Sortino':>9} {'Final':>18}")
    lines.append('-' * 90)
    for t in report.tiers:
        cagr_pct = t.cagr * 100
        mdd_pct = t.max_drawdown * 100
        line = (f"{t.name:<14} {cagr_pct:>7.2f}% {t.sharpe:>8.3f} "
                f"{mdd_pct:>9.2f}% {t.sortino:>9.3f} ${t.final_value:>16,.0f}")
        lines.append(line)
        if t.delta_cagr_bps != 0:
            lines.append(f"{'':<14}  Δ vs prev: {t.delta_cagr_bps:+.1f} bp CAGR, "
                         f"{t.delta_sharpe:+.3f} Sharpe, {t.delta_maxdd_bps:+.0f} bp MaxDD")
    lines.append('=' * 90)
    return '\n'.join(lines)
```

- [ ] **Step 4: Run tests**

Run: `pytest hydra_backtest/tests/test_reporting.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/reporting.py hydra_backtest/tests/test_reporting.py
git commit -m "feat(hydra_backtest): reporting writers (CSV, JSON, stdout table)"
```

---

## Task 20: CLI entrypoint (__main__.py)

**Files:**
- Create: `hydra_backtest/__main__.py`
- Modify: `hydra_backtest/__init__.py`
- Create: `hydra_backtest/tests/test_integration.py`

- [ ] **Step 1: Write failing integration test**

Create `hydra_backtest/tests/test_integration.py`:
```python
import subprocess
import sys
import os
import pytest


def test_cli_help():
    """Running `python -m hydra_backtest --help` should succeed and print usage."""
    result = subprocess.run(
        [sys.executable, '-m', 'hydra_backtest', '--help'],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert 'start' in result.stdout.lower()
    assert 'end' in result.stdout.lower()


@pytest.mark.skipif(not os.path.exists('data_cache/sp500_universe_prices.pkl'),
                    reason="Requires real PIT cache")
def test_cli_tiny_smoke():
    """Run a 1-year backtest end-to-end on real data. Should succeed."""
    result = subprocess.run(
        [sys.executable, '-m', 'hydra_backtest',
         '--start', '2020-01-02', '--end', '2020-06-30',
         '--out-dir', '/tmp/hydra_v2_smoke'],
        capture_output=True, text=True, timeout=600,
    )
    assert result.returncode == 0, f"CLI failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    assert os.path.exists('/tmp/hydra_v2_smoke/hydra_v2_daily.csv')
    assert os.path.exists('/tmp/hydra_v2_smoke/hydra_v2_waterfall.json')
```

- [ ] **Step 2: Update __init__.py to export public API**

Replace `hydra_backtest/__init__.py`:
```python
"""hydra_backtest — reproducible COMPASS standalone backtest.

See docs/superpowers/specs/2026-04-06-hydra-reproducible-backtest-design.md
"""
from hydra_backtest.errors import (
    HydraBacktestError,
    HydraDataError,
    HydraBacktestValidationError,
    HydraBacktestLookaheadError,
)
from hydra_backtest.engine import BacktestState, BacktestResult, run_backtest
from hydra_backtest.methodology import WaterfallTier, WaterfallReport, build_waterfall
from hydra_backtest.validation import run_smoke_tests
from hydra_backtest.reporting import (
    write_daily_csv, write_trades_csv, write_waterfall_json, format_summary_table,
)
from hydra_backtest.data import (
    validate_config, load_pit_universe, load_sector_map, load_price_history,
    load_spy_data, load_yield_series, compute_data_fingerprint,
)

__all__ = [
    'HydraBacktestError', 'HydraDataError', 'HydraBacktestValidationError',
    'HydraBacktestLookaheadError', 'BacktestState', 'BacktestResult',
    'run_backtest', 'WaterfallTier', 'WaterfallReport', 'build_waterfall',
    'run_smoke_tests', 'write_daily_csv', 'write_trades_csv',
    'write_waterfall_json', 'format_summary_table', 'validate_config',
    'load_pit_universe', 'load_sector_map', 'load_price_history',
    'load_spy_data', 'load_yield_series', 'compute_data_fingerprint',
]
```

- [ ] **Step 3: Implement __main__.py**

Create `hydra_backtest/__main__.py`:
```python
"""CLI entrypoint: python -m hydra_backtest

Reads PIT data from data_cache/, runs 3 backtests (baseline, T-bill, next-open),
post-processes for slippage tier, writes CSV + JSON + stdout summary.
"""
import argparse
import os
import sys
from datetime import time

import pandas as pd

from hydra_backtest import (
    run_backtest, validate_config, load_pit_universe, load_sector_map,
    load_price_history, load_spy_data, load_yield_series,
    build_waterfall, run_smoke_tests, write_daily_csv, write_trades_csv,
    write_waterfall_json, format_summary_table,
)

# Minimal canonical config — matches omnicapital_live.CONFIG for COMPASS
_CONFIG = {
    'MOMENTUM_LOOKBACK': 90, 'MOMENTUM_SKIP': 5, 'MIN_MOMENTUM_STOCKS': 20,
    'NUM_POSITIONS': 5, 'NUM_POSITIONS_RISK_OFF': 2, 'HOLD_DAYS': 5,
    'HOLD_DAYS_MAX': 10, 'RENEWAL_PROFIT_MIN': 0.04, 'MOMENTUM_RENEWAL_THRESHOLD': 0.85,
    'POSITION_STOP_LOSS': -0.08, 'TRAILING_ACTIVATION': 0.05, 'TRAILING_STOP_PCT': 0.03,
    'STOP_DAILY_VOL_MULT': 2.5, 'STOP_FLOOR': -0.06, 'STOP_CEILING': -0.15,
    'TRAILING_VOL_BASELINE': 0.25,
    'BULL_OVERRIDE_THRESHOLD': 0.03, 'BULL_OVERRIDE_MIN_SCORE': 0.40,
    'MAX_PER_SECTOR': 3,
    'DD_SCALE_TIER1': -0.10, 'DD_SCALE_TIER2': -0.20, 'DD_SCALE_TIER3': -0.35,
    'LEV_FULL': 1.0, 'LEV_MID': 0.60, 'LEV_FLOOR': 0.30,
    'CRASH_VEL_5D': -0.06, 'CRASH_VEL_10D': -0.10,
    'CRASH_LEVERAGE': 0.15, 'CRASH_COOLDOWN': 10,
    'QUALITY_VOL_MAX': 0.60, 'QUALITY_VOL_LOOKBACK': 63, 'QUALITY_MAX_SINGLE_DAY': 0.50,
    'TARGET_VOL': 0.15, 'LEVERAGE_MAX': 1.0, 'VOL_LOOKBACK': 20,
    'TOP_N': 40, 'MIN_AGE_DAYS': 63,
    'INITIAL_CAPITAL': 100_000, 'MARGIN_RATE': 0.06, 'COMMISSION_PER_SHARE': 0.0035,
}


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='python -m hydra_backtest',
        description='Reproducible COMPASS standalone backtest with waterfall reporting.',
    )
    parser.add_argument('--start', type=str, default='2000-01-01',
                        help='Backtest start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default='2026-03-05',
                        help='Backtest end date (YYYY-MM-DD)')
    parser.add_argument('--out-dir', type=str, default='backtests',
                        help='Output directory for CSVs and JSON')
    parser.add_argument('--constituents', type=str,
                        default='data_cache/sp500_constituents_history.pkl')
    parser.add_argument('--prices', type=str,
                        default='data_cache/sp500_universe_prices.pkl')
    parser.add_argument('--sectors', type=str,
                        default='data_cache/sp500_sector_map.json')
    parser.add_argument('--spy', type=str, default='data_cache/SPY_2000-01-01_2027-01-01.csv')
    parser.add_argument('--aaa', type=str, default='data_cache/moody_aaa_yield.csv')
    parser.add_argument('--tbill', type=str, default='data_cache/tbill_3m.csv')
    parser.add_argument('--slippage-bps', type=float, default=2.0)
    parser.add_argument('--half-spread-bps', type=float, default=0.5)
    parser.add_argument('--t-bill-rf', type=float, default=0.03)
    args = parser.parse_args(argv)

    validate_config(_CONFIG)

    print("Loading data...")
    pit = load_pit_universe(args.constituents)
    prices = load_price_history(args.prices)
    sectors = load_sector_map(args.sectors)
    spy = load_spy_data(args.spy)
    aaa_yield = load_yield_series(args.aaa, date_col='DATE', value_col='DAAA')
    tbill_yield = load_yield_series(args.tbill, date_col='DATE', value_col='DGS3MO')

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)

    print(f"\nTier 0: baseline (Aaa cash, same-close exec)")
    tier_0 = run_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        cash_yield_daily=aaa_yield, sector_map=sectors,
        start_date=start, end_date=end, execution_mode='same_close',
    )
    run_smoke_tests(tier_0)  # BLOCKING

    print(f"\nTier 1: + T-bill cash yield")
    tier_1 = run_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        cash_yield_daily=tbill_yield, sector_map=sectors,
        start_date=start, end_date=end, execution_mode='same_close',
    )
    run_smoke_tests(tier_1)

    print(f"\nTier 2: + next-open execution")
    tier_2 = run_backtest(
        config=_CONFIG, price_data=prices, pit_universe=pit, spy_data=spy,
        cash_yield_daily=tbill_yield, sector_map=sectors,
        start_date=start, end_date=end, execution_mode='next_open',
    )
    run_smoke_tests(tier_2)

    print(f"\nBuilding waterfall...")
    report = build_waterfall(
        tier_0=tier_0, tier_1=tier_1, tier_2=tier_2,
        t_bill_rf=args.t_bill_rf, slippage_bps=args.slippage_bps,
        half_spread_bps=args.half_spread_bps,
    )

    os.makedirs(args.out_dir, exist_ok=True)
    write_daily_csv(tier_0, os.path.join(args.out_dir, 'hydra_v2_daily.csv'))
    write_trades_csv(tier_0, os.path.join(args.out_dir, 'hydra_v2_trades.csv'))
    write_waterfall_json(report, os.path.join(args.out_dir, 'hydra_v2_waterfall.json'))

    print('\n' + format_summary_table(report))
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: Run tests**

Run: `pytest hydra_backtest/tests/test_integration.py::test_cli_help -v`
Expected: PASS (the real-data test is skipped unless data_cache exists)

- [ ] **Step 5: Commit**

```bash
git add hydra_backtest/__main__.py hydra_backtest/__init__.py hydra_backtest/tests/test_integration.py
git commit -m "feat(hydra_backtest): CLI entrypoint running 3 tiers + waterfall"
```

---

## Task 21: E2E smoke test (marked slow)

**Files:**
- Create: `hydra_backtest/tests/test_e2e.py`

- [ ] **Step 1: Write E2E tests**

Create `hydra_backtest/tests/test_e2e.py`:
```python
"""End-to-end tests — SLOW, marked @pytest.mark.slow.

Run with: pytest hydra_backtest/tests/test_e2e.py -m slow
"""
import hashlib
import os
import pytest
import subprocess
import sys


pytestmark = pytest.mark.slow


@pytest.mark.skipif(
    not os.path.exists('data_cache/sp500_universe_prices.pkl'),
    reason="Requires real PIT cache"
)
def test_e2e_full_backtest_2000_2026(tmp_path):
    """Full 2000 → 2026-03-05 backtest runs to completion with all tiers."""
    out = tmp_path / 'run1'
    result = subprocess.run(
        [sys.executable, '-m', 'hydra_backtest',
         '--start', '2000-01-01', '--end', '2026-03-05',
         '--out-dir', str(out)],
        capture_output=True, text=True, timeout=1200,
    )
    assert result.returncode == 0, f"CLI failed:\n{result.stderr}"
    assert (out / 'hydra_v2_daily.csv').exists()
    assert (out / 'hydra_v2_waterfall.json').exists()
    assert (out / 'hydra_v2_trades.csv').exists()
    # Verify stdout has the waterfall table
    assert 'baseline' in result.stdout
    assert 'net_honest' in result.stdout


@pytest.mark.skipif(
    not os.path.exists('data_cache/sp500_universe_prices.pkl'),
    reason="Requires real PIT cache"
)
def test_e2e_determinism(tmp_path):
    """Two runs with identical inputs produce byte-identical daily CSVs."""
    out1 = tmp_path / 'run1'
    out2 = tmp_path / 'run2'
    for out_dir in (out1, out2):
        result = subprocess.run(
            [sys.executable, '-m', 'hydra_backtest',
             '--start', '2010-01-01', '--end', '2012-12-31',
             '--out-dir', str(out_dir)],
            capture_output=True, text=True, timeout=600,
        )
        assert result.returncode == 0

    def _sha(path):
        with open(path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()

    assert _sha(out1 / 'hydra_v2_daily.csv') == _sha(out2 / 'hydra_v2_daily.csv')
```

- [ ] **Step 2: Run tests**

Run: `pytest hydra_backtest/tests/test_e2e.py -v -m slow`
Expected: PASS if data_cache exists, SKIP otherwise

- [ ] **Step 3: Commit**

```bash
git add hydra_backtest/tests/test_e2e.py
git commit -m "test(hydra_backtest): E2E full-run + determinism (@pytest.mark.slow)"
```

---

## Task 22: Pytest configuration — slow marker + coverage

**Files:**
- Modify: `pytest.ini` (or `pyproject.toml` if already configured)

- [ ] **Step 1: Check existing pytest config**

Run: `cat pytest.ini 2>/dev/null || cat pyproject.toml 2>/dev/null | grep -A 20 '\[tool.pytest'`

- [ ] **Step 2: Add `slow` marker registration**

If a `pytest.ini` exists, append:
```ini
[pytest]
markers =
    slow: marks tests as slow (deselect with '-m "not slow"')
```

If `pyproject.toml` has `[tool.pytest.ini_options]`, add:
```toml
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
]
```

- [ ] **Step 3: Verify marker registered**

Run: `pytest --markers | grep slow`
Expected: `@pytest.mark.slow: marks tests as slow`

- [ ] **Step 4: Commit**

```bash
git add pytest.ini pyproject.toml 2>/dev/null
git commit -m "test(hydra_backtest): register 'slow' pytest marker"
```

---

## Task 23: Full test suite green + coverage check

**Files:** none (verification task)

- [ ] **Step 1: Run the full unit + integration test suite**

Run: `pytest hydra_backtest/tests/ -v --cov=hydra_backtest --cov-report=term-missing -m "not slow"`
Expected: all tests pass, coverage ≥ 80%

- [ ] **Step 2: If any test fails, fix it**

Common issues:
- Import cycles: double-check that engine.py imports from omnicapital_live, not the reverse
- Fixture scope: ensure conftest.py is in `hydra_backtest/tests/`, not root
- Pandas version: if `tuple` concatenation fails, check BacktestState mutation patterns

- [ ] **Step 3: If coverage < 80%, add targeted tests**

Look at uncovered lines in `term-missing` output. Add tests only for lines that contain real logic, not defensive raises or unreachable branches.

- [ ] **Step 4: Commit any fixes + coverage improvements**

```bash
git add hydra_backtest/
git commit -m "test(hydra_backtest): green suite at ≥80% coverage"
```

---

## Task 24: README inside package

**Files:**
- Create: `hydra_backtest/README.md`

- [ ] **Step 1: Write package README**

Create `hydra_backtest/README.md`:
```markdown
# hydra_backtest

Reproducible COMPASS standalone backtest for the HYDRA quantitative trading system.

## What this is

A Python package that runs a COMPASS momentum backtest from 2000 to 2026 using
point-in-time S&P 500 membership, producing a waterfall methodology report
(baseline → +T-bill → +next-open → +slippage → NET HONEST).

**This package is a consumer of `omnicapital_live.py`'s signal logic, not an
owner.** Pure functions are imported directly from the live engine. Class
methods that can't be imported are reimplemented as pure equivalents with
docstrings pointing to the source line.

## Why this exists

The legacy HYDRA dashboard number (14.5% CAGR / -22.2% MaxDD / 1.01 Sharpe)
was a four-layer Frankenstein with no reproducible code path. Three nominally
equivalent v8.4 implementations in the repo diverge silently. This package
is the foundation for resolving #34 (unify backtest and live) and #37 (GO/NO-GO).

See `docs/superpowers/specs/2026-04-06-hydra-reproducible-backtest-design.md`
for the full design.

## How to run

```bash
python -m hydra_backtest --start 2000-01-01 --end 2026-03-05
```

Outputs written to `backtests/`:
- `hydra_v2_daily.csv` — daily equity curve
- `hydra_v2_trades.csv` — all trades
- `hydra_v2_waterfall.json` — waterfall report (5 tiers)

And a summary table printed to stdout.

## How to test

```bash
# Fast unit + integration tests (< 30s total)
pytest hydra_backtest/tests/ -v -m "not slow"

# E2E full-run tests (~5 min, requires real data cache)
pytest hydra_backtest/tests/ -v -m slow

# With coverage
pytest hydra_backtest/tests/ -v --cov=hydra_backtest --cov-report=term-missing
```

## Architecture

```
data.py         — PIT universe, prices, yields, sectors, config validator
engine.py       — Backtest loop (imports live pure fns + pure equivalents)
methodology.py  — Waterfall corrections (T-bill, next-open, slippage)
validation.py   — Layer A smoke tests (blocking)
reporting.py    — CSV / JSON / stdout writers
errors.py       — Exception hierarchy (HydraBacktestError + subclasses)
__main__.py     — CLI entrypoint
```

All modules use frozen dataclasses for immutability. Each stage is a pure
function that takes immutable inputs and returns immutable outputs.

## Limitations (v1)

- **COMPASS only**: Rattlesnake, Catalyst, EFA, and cash recycling come in v1.1-v1.4
- **Fed Emergency overlay NOT applied**: out of scope for v1
- **Position renewal NOT applied**: v1 uses conservative "exit at hold_expired" always
- **PIT universe is ~827 tickers** (vs 1194 full historical S&P 500): residual bias documented
- **BRK-B excluded** by `validate_universe` regex bug (#13): fix will be absorbed when landed in live
```

- [ ] **Step 2: Commit**

```bash
git add hydra_backtest/README.md
git commit -m "docs(hydra_backtest): package README"
```

---

## Task 25: CI integration

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Check existing CI workflow**

Run: `cat .github/workflows/ci.yml`

- [ ] **Step 2: Add a dedicated job step for hydra_backtest**

In the existing test job, after the current pytest step, add:
```yaml
      - name: Test hydra_backtest package
        run: |
          pytest hydra_backtest/tests/ -v \
            --cov=hydra_backtest \
            --cov-report=term-missing \
            --cov-fail-under=80 \
            -m "not slow"
```

- [ ] **Step 3: Verify YAML is valid**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: no output (valid YAML)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(hydra_backtest): add pytest + coverage gate to CI"
```

---

## Final Verification

- [ ] **Step 1: Run the full fast test suite one last time**

Run: `pytest hydra_backtest/tests/ -v -m "not slow" --cov=hydra_backtest --cov-fail-under=80`
Expected: all pass, coverage ≥ 80%

- [ ] **Step 2: Run a 3-year real backtest to confirm the whole pipeline works**

Run:
```bash
python -m hydra_backtest --start 2020-01-01 --end 2022-12-31 --out-dir /tmp/hydra_v1_check
```
Expected: exits with code 0, prints waterfall table, writes 3 files.

- [ ] **Step 3: Verify output files**

Run:
```bash
ls /tmp/hydra_v1_check/
head /tmp/hydra_v1_check/hydra_v2_daily.csv
python -c "import json; print(json.load(open('/tmp/hydra_v1_check/hydra_v2_waterfall.json'))['tiers'][0]['name'])"
```
Expected: 3 files present, CSV starts with date/value columns, JSON has "baseline" as first tier.

- [ ] **Step 4: Final commit if anything changed**

```bash
git status
git add .
git commit -m "chore(hydra_backtest): v1 complete — all tiers green on 3-year real run"
```

---

## Self-Review Checklist

Before handing off execution:

**Spec coverage**:
- ✅ §3 scope (COMPASS standalone) → Tasks 1-25
- ✅ §4 architecture (modular package) → File structure + Task 1
- ✅ §4.2 consumer principle → Tasks 9, 10, 13, 14, 15 (imports from live)
- ✅ §5 data flow → Task 15 orchestrator
- ✅ §6 backtest loop → Tasks 7-15
- ✅ §7 waterfall → Tasks 16, 17
- ✅ §8.1 Layer A smoke tests (blocking) → Task 18
- ✅ §8.2 Layer B, §8.3 Layer C → explicitly deferred to v1.1/v1.2 (not in this plan)
- ✅ §9 error handling → Task 1 (errors.py) + used throughout
- ✅ §10 testing pyramid → Tasks 2-21 (unit) + Task 20 (integration) + Task 21 (E2E)
- ✅ §11 fixed parameters → Task 20 CLI defaults + minimal_config fixture
- ✅ §12 open questions → Documented in README (Task 24)
- ✅ §13 roadmap → v1 complete, v1.1-v1.5 intentionally out of scope
- ✅ §15 success criteria → Task 26 verification steps

**Placeholder scan**: ✅ No "TODO", "TBD", "implement later", "similar to X" — every step has real code.

**Type consistency**: ✅ `BacktestState`, `BacktestResult`, `WaterfallTier`, `WaterfallReport` used consistently across tasks. `run_backtest` signature matches in Task 15 (definition) and Task 20 (CLI usage).

**One identified risk**: Task 17 (`apply_slippage_postprocess`) uses a simplified cumulative-drag approach for rebuilding the equity curve. If v1.1 exit analysis reveals the approximation is material, we revisit with a more rigorous formula. Documented inline in the implementation.
