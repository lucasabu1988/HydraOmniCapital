"""Tests for hydra_backtest.data module."""
import json
import pickle
from pathlib import Path

import pandas as pd
import pytest

from hydra_backtest.data import (
    compute_data_fingerprint,
    load_pit_universe,
    load_price_history,
    load_sector_map,
    load_spy_data,
    load_yield_series,
    validate_config,
)
from hydra_backtest.errors import HydraDataError


# -- validate_config ----------------------------------------------------------

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


# -- load_pit_universe --------------------------------------------------------

def test_load_pit_universe_returns_dict_by_year(tmp_path):
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
    assert 'GOOG' in universe[2021]


def test_load_pit_universe_anti_survivorship():
    real_path = Path('data_cache/sp500_constituents_history.pkl')
    if not real_path.exists():
        pytest.skip("Real constituents history not available")
    universe = load_pit_universe(str(real_path))
    # AAPL must be in 2010 (it was in the S&P 500)
    assert 'AAPL' in universe.get(2010, [])
    # There must be tickers in 2005 that are NOT in 2020 (demonstrates PIT behavior)
    tickers_2005 = set(universe.get(2005, []))
    tickers_2020 = set(universe.get(2020, []))
    removed_since_2005 = tickers_2005 - tickers_2020
    assert len(removed_since_2005) > 0, (
        "Expected at least some tickers to be dropped between 2005 and 2020"
    )


# -- load_sector_map ----------------------------------------------------------

def test_load_sector_map(tmp_path):
    path = tmp_path / 'sectors.json'
    path.write_text(json.dumps({'AAPL': 'Tech', 'JPM': 'Financials'}))
    sectors = load_sector_map(str(path))
    assert sectors['AAPL'] == 'Tech'
    assert sectors['JPM'] == 'Financials'


def test_load_sector_map_missing_file_raises(tmp_path):
    with pytest.raises(HydraDataError, match="sector map"):
        load_sector_map(str(tmp_path / 'nonexistent.json'))


# -- load_price_history + compute_data_fingerprint --------------------------

def test_load_price_history_returns_dict_of_dataframes(tmp_path):
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
    data = {
        'AAPL': pd.DataFrame(
            {'Open': [100.0, 101.0], 'High': [101.0, 102.0], 'Low': [99.0, 100.0],
             'Close': [100.0, 101.0], 'Volume': [1000, 1100]},
            index=pd.date_range('2020-01-02', periods=2),
        ),
    }
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


# -- load_spy_data ------------------------------------------------------------

def test_load_spy_data_returns_dataframe(tmp_path):
    df = pd.DataFrame({
        'Open': [100, 101], 'High': [102, 103], 'Low': [99, 100],
        'Close': [101, 102], 'Volume': [1000, 1100],
    }, index=pd.date_range('2020-01-02', periods=2))
    path = tmp_path / 'spy.pkl'
    df.to_pickle(path)
    spy = load_spy_data(str(path))
    assert isinstance(spy, pd.DataFrame)
    assert 'Close' in spy.columns


# -- load_yield_series --------------------------------------------------------

def test_load_vix_series_returns_daily_series(tmp_path):
    from hydra_backtest.data import load_vix_series
    df = pd.DataFrame({
        'Date': pd.date_range('2020-01-02', periods=5, freq='B'),
        'Close': [12.5, 13.1, 14.0, 18.5, 35.5],
    })
    path = tmp_path / 'vix.csv'
    df.to_csv(path, index=False)
    series = load_vix_series(str(path))
    assert isinstance(series, pd.Series)
    assert len(series) == 5
    assert series.iloc[-1] == 35.5


def test_load_vix_series_missing_file_raises(tmp_path):
    from hydra_backtest.data import load_vix_series
    with pytest.raises(HydraDataError, match="VIX"):
        load_vix_series(str(tmp_path / 'nonexistent.csv'))


def test_load_vix_series_handles_yfinance_format(tmp_path):
    """yfinance saves with index named 'Date' and 'Close' column."""
    from hydra_backtest.data import load_vix_series
    df = pd.DataFrame(
        {'Close': [13.5, 14.0, 15.0]},
        index=pd.date_range('2020-01-02', periods=3, freq='B'),
    )
    df.index.name = 'Date'
    path = tmp_path / 'vix_yf.csv'
    df.to_csv(path)
    series = load_vix_series(str(path))
    assert len(series) == 3
    assert series.iloc[0] == 13.5


def test_load_yield_series_returns_daily_series(tmp_path):
    # Use business-day frequency so reindexing to freq='B' preserves all rows.
    df = pd.DataFrame({
        'DATE': pd.date_range('2020-01-02', periods=5, freq='B'),
        'DGS3MO': [1.5, 1.5, 1.6, 1.6, 1.7],
    })
    path = tmp_path / 'tbill.csv'
    df.to_csv(path, index=False)
    series = load_yield_series(str(path), date_col='DATE', value_col='DGS3MO')
    assert isinstance(series, pd.Series)
    assert len(series) >= 5
    assert 0 <= series.iloc[0] <= 20  # sanity: annual percentage


def test_load_yield_series_fills_gaps(tmp_path):
    df = pd.DataFrame({
        'DATE': ['2020-01-02', '2020-01-06'],  # 1 business-day gap (Jan 3)
        'V': [1.5, 1.6],
    })
    path = tmp_path / 'y.csv'
    df.to_csv(path, index=False)
    series = load_yield_series(
        str(path), date_col='DATE', value_col='V', fill_business_days=True,
    )
    assert len(series) >= 3
