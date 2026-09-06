"""TASK-366 — sleeve adapters equal the engine targets. Synthetic frames, no network."""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import V9  # noqa: E402
import core.portfolio_engine as E  # noqa: E402
from sleeves.base import MarketSlice  # noqa: E402
from sleeves.registry import KNOWN, build  # noqa: E402
from sleeves.etf_trend import EtfTrend, target_weights  # noqa: E402
from sleeves.stocks_t20 import StocksT20  # noqa: E402

IDX = pd.bdate_range("2024-01-02", periods=280)
CFG = dict(V9)


def _ranking(names, n=None, vetoed=()):
    n = len(names) if n is None else n
    return pd.DataFrame({
        "ticker": list(names),
        "rank": range(1, len(names) + 1),
        "sector": ["Other"] * len(names),
        "reason": ["Vetado: gate" if t in vetoed else "" for t in names],
        "recommended_count": n,
    })


def _stock_prices():
    n = len(IDX)
    return pd.DataFrame({
        "A": np.linspace(10.0, 18.0, n),
        "B": np.linspace(20.0, 16.0, n),
        "C": np.linspace(30.0, 42.0, n),
    }, index=IDX)


def _stock_slice(ranking, prices=None) -> MarketSlice:
    px = prices if prices is not None else _stock_prices()
    return MarketSlice(
        stock_prices=px,
        volumes=px * 0 + 1_000_000.0,
        spy=px.iloc[:, 0],
        etf_closes=pd.DataFrame(index=IDX),
        tbill=pd.Series(0.05 / 252.0, index=IDX),
        ranking=ranking,
    )


def _etf_closes(spy_mu=0.0008, tlt_mu=-0.0008):
    spy = 100.0 * np.exp(np.cumsum(np.full(len(IDX), spy_mu)))
    tlt = 100.0 * np.exp(np.cumsum(np.full(len(IDX), tlt_mu)))
    return pd.DataFrame({"SPY": spy, "TLT": tlt}, index=IDX)


def _etf_slice(closes=None, tbill_ann=0.05) -> MarketSlice:
    px = closes if closes is not None else _etf_closes()
    tb = pd.Series(float(tbill_ann) / 252.0, index=IDX)
    dummy = pd.DataFrame({"A": np.ones(len(IDX))}, index=IDX)
    return MarketSlice(
        stock_prices=dummy,
        volumes=dummy,
        spy=dummy["A"],
        etf_closes=px,
        tbill=tb,
        ranking=_ranking(["A"], n=0),
    )


def _assert_w(a: pd.Series, b: pd.Series):
    a = pd.Series(a, dtype=float).sort_index()
    b = pd.Series(b, dtype=float).sort_index()
    if a.empty and b.empty:
        return
    pd.testing.assert_series_equal(a, b, check_names=False, atol=1e-12, rtol=0.0)


def test_stock_adapter_matches_engine():
    ranking = _ranking(["A", "B", "C"], n=2)
    market = _stock_slice(ranking)
    held = {"C"}
    eng = E.stock_targets(ranking, held, market.stock_prices, CFG)
    adp = StocksT20().targets(market, held, CFG)
    _assert_w(adp, eng)
    assert float(adp.sum()) <= 1.0 + 1e-12


def test_stock_zero_recommended_is_empty():
    ranking = _ranking(["A", "B", "C"], n=0)
    market = _stock_slice(ranking)
    eng = E.stock_targets(ranking, set(), market.stock_prices, CFG)
    adp = StocksT20().targets(market, set(), CFG)
    assert eng.empty and adp.empty


def test_etf_adapter_matches_engine():
    market = _etf_slice()
    eng = E.etf_targets(market.etf_closes, market.tbill, CFG)
    adp = EtfTrend().targets(market, set(), CFG)
    _assert_w(adp, eng)
    assert float(adp.sum()) <= 1.0 + 1e-12
    # existing function still there and agrees
    _assert_w(target_weights(market.etf_closes, market.tbill), eng)


def test_etf_all_off_is_empty():
    # 12m T-bill ≈ 1.0; neither ETF's 12m return beats it.
    market = _etf_slice(tbill_ann=1.0)
    eng = E.etf_targets(market.etf_closes, market.tbill, CFG)
    adp = EtfTrend().targets(market, set(), CFG)
    assert eng.empty and adp.empty


def test_registry_default_is_the_two_live_sleeves():
    reg = build(V9)
    assert list(reg) == ["stocks", "etf"]
    assert isinstance(reg["stocks"], StocksT20)
    assert isinstance(reg["etf"], EtfTrend)
    assert reg["stocks"].name == "stocks"
    assert reg["etf"].name == "etf"
    assert reg["stocks"].cost_bp == pytest.approx(V9["stock_cost_bp"])
    assert reg["etf"].cost_bp == pytest.approx(V9["etf_cost_bp"])


def test_registry_unknown_name_lists_known():
    with pytest.raises(KeyError, match="unknown sleeve 'mr'"):
        build({"sleeves": ["stocks", "mr"]})
    assert set(KNOWN) == {"stocks", "etf"}


def test_registry_override_cost_bp():
    reg = build({"sleeves": ["etf"], "etf_cost_bp": 7.5})
    assert list(reg) == ["etf"]
    assert reg["etf"].cost_bp == pytest.approx(7.5)
