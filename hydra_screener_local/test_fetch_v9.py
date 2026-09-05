"""TASK-339 — v9 data layer. yfinance is patched; these tests do not hit the network."""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.fetch import (  # noqa: E402
    ETF_UNIVERSE,
    FFILL_LIMIT_BARS,
    TBILL_SYMBOL,
    V9_PRICE_PERIOD,
    fetch_etf_closes,
    fetch_prices_and_volume,
    fetch_tbill,
)


IDX = pd.bdate_range("2025-01-02", periods=12)


def _close_df(tickers, values):
    """Single-level Close frame, one column per ticker (the 1-ticker yfinance shape)."""
    if len(tickers) == 1:
        return pd.DataFrame({"Close": values}, index=IDX[: len(values)])
    data = {("Close", t): values[t] for t in tickers}
    df = pd.DataFrame(data, index=IDX[: len(next(iter(values.values())))])
    df.columns = pd.MultiIndex.from_tuples(df.columns)
    return df


@pytest.fixture
def no_sleep(monkeypatch):
    monkeypatch.setattr("data.fetch.time.sleep", lambda *a, **k: None)


def test_v84_stock_fetch_still_requests_1y(monkeypatch, no_sleep):
    seen = {}

    def fake(batch, period="1y", **kw):
        seen["period"] = period
        return _close_df(batch, [10.0] * 12)

    monkeypatch.setattr("data.fetch.yf.download", fake)
    prices, _ = fetch_prices_and_volume(["AAA"])
    assert seen["period"] == "1y"
    assert list(prices.columns) == ["AAA"]


def test_stock_fetch_forwards_2y_when_asked(monkeypatch, no_sleep):
    seen = {}

    def fake(batch, period="1y", **kw):
        seen["period"] = period
        return _close_df(batch, [10.0] * 12)

    monkeypatch.setattr("data.fetch.yf.download", fake)
    fetch_prices_and_volume(["AAA"], period=V9_PRICE_PERIOD)
    assert seen["period"] == "2y"
    assert V9_PRICE_PERIOD == "2y"


def test_etf_closes_shape_default_universe(monkeypatch, no_sleep):
    def fake(batch, period="1y", **kw):
        assert period == "2y"
        values = {t: [100.0 + i] * 12 for i, t in enumerate(batch)}
        return _close_df(batch, values)

    monkeypatch.setattr("data.fetch.yf.download", fake)
    report = {}
    px = fetch_etf_closes(report=report)
    assert list(px.columns) == ETF_UNIVERSE
    assert px.shape == (12, 10)
    assert report["downloaded"] == 10 and report["failed_tickers"] == []


def test_etf_ffill_fills_three_bars_not_four(monkeypatch, no_sleep):
    assert FFILL_LIMIT_BARS == 3
    series = pd.Series([10.0] * 12, index=IDX, dtype=float)
    series.iloc[2:4] = np.nan          # 2-bar hole -> both filled
    series.iloc[6:10] = np.nan         # 4-bar hole -> first 3 filled, 4th stays NaN

    def fake(batch, period="1y", **kw):
        return _close_df(["SPY"], series.values)

    monkeypatch.setattr("data.fetch.yf.download", fake)
    px = fetch_etf_closes(["SPY"])
    col = px["SPY"]
    assert col.iloc[2] == pytest.approx(10.0) and col.iloc[3] == pytest.approx(10.0)
    assert col.iloc[6] == pytest.approx(10.0) and col.iloc[8] == pytest.approx(10.0)
    assert pd.isna(col.iloc[9])


def test_etf_failure_is_reported_not_raised(monkeypatch, no_sleep):
    def boom(*a, **k):
        raise RuntimeError("yahoo down")

    monkeypatch.setattr("data.fetch.yf.download", boom)
    report = {}
    out = fetch_etf_closes(["SPY", "QQQ"], report=report)
    assert out.empty
    assert report["failed_tickers"] == ["SPY", "QQQ"]
    assert report["missing_share"] == 1.0
    assert report["failed_batches"] == 1


def test_tbill_is_a_percent_series(monkeypatch, no_sleep):
    seen = {}

    def fake(batch, period="1y", auto_adjust=True, **kw):
        seen["batch"] = list(batch)
        seen["auto_adjust"] = auto_adjust
        seen["period"] = period
        return _close_df([TBILL_SYMBOL], [5.21, 5.18, 5.15, 5.15, 5.10, 5.10,
                                          5.08, 5.08, 5.07, 5.07, 5.06, 5.06])

    monkeypatch.setattr("data.fetch.yf.download", fake)
    report = {}
    s = fetch_tbill(report=report)
    assert seen["batch"] == ["^IRX"]
    assert seen["auto_adjust"] is False
    assert seen["period"] == "2y"
    assert isinstance(s, pd.Series)
    assert s.iloc[0] == pytest.approx(5.21)          # percent, not 0.0521
    assert report["downloaded"] == 1 and report["failed_tickers"] == []


def test_tbill_failure_is_reported_not_raised(monkeypatch, no_sleep):
    monkeypatch.setattr("data.fetch.yf.download", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no irx")))
    report = {}
    s = fetch_tbill(report=report)
    assert isinstance(s, pd.Series) and s.empty
    assert report["failed_tickers"] == ["^IRX"]
    assert report["missing_share"] == 1.0
