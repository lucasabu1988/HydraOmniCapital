"""TASK-361 — SQLite bar store + cached fetch. Fake provider, no network."""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import store_cli  # noqa: E402
from data.fetch import (  # noqa: E402
    fetch_prices_and_volume,
    fetch_prices_and_volume_cached,
    period_to_start,
)
from data.providers.yfinance_provider import YFinanceProvider  # noqa: E402
from data.store import BarStore  # noqa: E402

IDX = pd.bdate_range("2024-01-02", periods=40)
ASOF = IDX[-1]


def _long(tickers=("AAA", "BBB")) -> pd.DataFrame:
    rows = []
    for t in tickers:
        base = 10.0 if t == "AAA" else 20.0
        for i, d in enumerate(IDX):
            rows.append(
                {
                    "ticker": t,
                    "date": d,
                    "close_adj": base + i,
                    "close_raw": (base + i) * 2,
                    "volume": 1_000_000 + i,
                    "source": "fake",
                }
            )
    return pd.DataFrame(rows)


class FakeProvider:
    def __init__(self, frame: pd.DataFrame):
        self.df = frame.copy()
        self.calls: list[tuple[list[str], pd.Timestamp, pd.Timestamp]] = []

    def fetch(self, tickers, start, end) -> pd.DataFrame:
        names = [str(t) for t in tickers]
        start_ts = pd.Timestamp(start).normalize()
        end_ts = pd.Timestamp(end).normalize()
        self.calls.append((names, start_ts, end_ts))
        sub = self.df[self.df["ticker"].isin(names)].copy()
        dates = pd.to_datetime(sub["date"]).dt.normalize()
        sub = sub[(dates >= start_ts) & (dates <= end_ts)]
        return sub.reset_index(drop=True)


def _pivot(frame: pd.DataFrame, col: str, tickers, start, end) -> pd.DataFrame:
    sub = frame[frame["ticker"].isin(tickers)].copy()
    dates = pd.to_datetime(sub["date"]).dt.normalize()
    sub = sub[(dates >= pd.Timestamp(start)) & (dates <= pd.Timestamp(end))]
    wide = sub.pivot(index="date", columns="ticker", values=col)
    wide.index = pd.DatetimeIndex(pd.to_datetime(wide.index)).normalize()
    return wide.reindex(columns=list(tickers)).sort_index().astype(float)


# --------------------------------------------------------------------------- store


def test_upsert_roundtrip_closes_and_volumes(tmp_path):
    store = BarStore(tmp_path / "bars.sqlite")
    n = store.upsert(_long())
    assert n == 80
    px = store.closes(["AAA", "BBB"], IDX[0], IDX[-1], adjusted=True)
    raw = store.closes(["AAA"], IDX[0], IDX[-1], adjusted=False)
    vol = store.volumes(["AAA", "BBB"], IDX[0], IDX[-1])
    assert list(px.columns) == ["AAA", "BBB"]
    assert px.shape == (40, 2)
    assert px["AAA"].iloc[0] == pytest.approx(10.0)
    assert raw["AAA"].iloc[0] == pytest.approx(20.0)
    assert vol["AAA"].iloc[-1] == pytest.approx(1_000_000 + 39)
    store.close()


def test_coverage_and_last_dates(tmp_path):
    store = BarStore(tmp_path / "bars.sqlite")
    store.upsert(_long())
    lasts = store.last_dates(["AAA", "CCC"])
    assert lasts["AAA"] == pd.Timestamp(IDX[-1]).normalize()
    assert "CCC" not in lasts
    cov = store.coverage(["AAA", "BBB", "CCC"], IDX[-1])
    assert cov.set_index("ticker").loc["AAA", "n_bars"] == 40
    assert bool(cov.set_index("ticker").loc["AAA", "has_asof"]) is True
    assert bool(cov.set_index("ticker").loc["CCC", "has_asof"]) is False
    assert cov.set_index("ticker").loc["CCC", "n_bars"] == 0
    ostart = store.overlap_start("AAA", n=10)
    assert ostart == pd.Timestamp(IDX[-10]).normalize()
    store.close()


def test_replace_ticker_drops_old_rows(tmp_path):
    store = BarStore(tmp_path / "bars.sqlite")
    store.upsert(_long())
    slim = _long(["AAA"]).iloc[-5:]
    store.replace_ticker("AAA", slim)
    px = store.closes(["AAA"], IDX[0], IDX[-1])
    assert len(px) == 5
    assert store.last_dates(["AAA"])["AAA"] == pd.Timestamp(IDX[-1]).normalize()
    store.close()


# --------------------------------------------------------------------------- cached fetch


def test_use_bar_store_defaults_false():
    assert config.USE_BAR_STORE is False


def test_cached_equals_direct(tmp_path):
    store = BarStore(tmp_path / "bars.sqlite")
    frame = _long()
    provider = FakeProvider(frame)
    start = period_to_start("1y", ASOF)
    prices, vols = fetch_prices_and_volume_cached(
        ["AAA", "BBB"], period="1y", provider=provider, store=store, asof=ASOF,
    )
    want_px = _pivot(frame, "close_adj", ["AAA", "BBB"], start, ASOF)
    want_vol = _pivot(frame, "volume", ["AAA", "BBB"], start, ASOF)
    pd.testing.assert_frame_equal(
        prices.sort_index(axis=1).astype(float), want_px.sort_index(axis=1),
        check_freq=False, check_names=False, atol=0, rtol=0,
    )
    pd.testing.assert_frame_equal(
        vols.sort_index(axis=1).astype(float), want_vol.sort_index(axis=1),
        check_freq=False, check_names=False, atol=0, rtol=0,
    )
    store.close()


def test_second_call_downloads_only_the_tail(tmp_path):
    store = BarStore(tmp_path / "bars.sqlite")
    provider = FakeProvider(_long())
    fetch_prices_and_volume_cached(
        ["AAA", "BBB"], period="1y", provider=provider, store=store, asof=ASOF,
    )
    assert len(provider.calls) == 1
    first_start = provider.calls[0][1]
    fetch_prices_and_volume_cached(
        ["AAA", "BBB"], period="1y", provider=provider, store=store, asof=ASOF,
    )
    assert len(provider.calls) == 2
    _, tail_start, tail_end = provider.calls[1]
    assert set(provider.calls[1][0]) == {"AAA", "BBB"}
    assert tail_start > first_start
    assert tail_start == pd.Timestamp(IDX[-10]).normalize()
    assert tail_end == pd.Timestamp(ASOF).normalize()
    store.close()


def test_readjust_refetches_full_history(tmp_path):
    store = BarStore(tmp_path / "bars.sqlite")
    frame = _long()
    provider = FakeProvider(frame)
    fetch_prices_and_volume_cached(
        ["AAA", "BBB"], period="1y", provider=provider, store=store, asof=ASOF,
    )
    # Retroactive split: last-10-bar overlap on AAA moves.
    bump_date = IDX[-5]
    mask = (provider.df["ticker"] == "AAA") & (pd.to_datetime(provider.df["date"]) == bump_date)
    provider.df.loc[mask, "close_adj"] = provider.df.loc[mask, "close_adj"] * 1.01
    report = {}
    fetch_prices_and_volume_cached(
        ["AAA", "BBB"], period="1y", report=report, provider=provider, store=store, asof=ASOF,
    )
    assert "AAA" in report["readjusted"]
    assert "BBB" not in report["readjusted"]
    # A full-period refetch for AAA after the tail call.
    aaa_full = [
        (names, start) for names, start, _end in provider.calls
        if names == ["AAA"] and start == period_to_start("1y", ASOF)
    ]
    assert aaa_full, f"expected a full-period refetch of AAA; calls={provider.calls}"
    stored = store.closes(["AAA"], bump_date, bump_date)["AAA"].iloc[0]
    assert stored == pytest.approx(float(provider.df.loc[mask, "close_adj"].iloc[0]))
    store.close()


def test_live_fetch_does_not_construct_the_store(monkeypatch):
    opened = []

    class Boom:
        def __init__(self, *a, **k):
            opened.append(True)
            raise AssertionError("BarStore must not be constructed on the live fetch")

    monkeypatch.setattr("data.store.BarStore", Boom)
    monkeypatch.setattr("data.fetch.time.sleep", lambda *a, **k: None)

    def fake(batch, period="1y", **kw):
        idx = pd.bdate_range("2024-01-02", periods=3)
        return pd.DataFrame({"Close": [1.0, 2.0, 3.0], "Volume": [10, 10, 10]}, index=idx)

    monkeypatch.setattr("data.fetch.yf.download", fake)
    prices, _ = fetch_prices_and_volume(["AAA"])
    assert list(prices.columns) == ["AAA"]
    assert opened == []


# --------------------------------------------------------------------------- yfinance provider (patched)


def test_yfinance_provider_two_downloads(monkeypatch):
    calls = []
    idx = pd.bdate_range("2024-01-02", periods=5)

    def fake(batch, start=None, end=None, period=None, auto_adjust=True, **kw):
        calls.append({"batch": list(batch), "start": start, "end": end, "auto_adjust": auto_adjust})
        cols = {}
        for t in batch:
            px = 100.0 if auto_adjust else 50.0
            cols[("Close", t)] = [px + i for i in range(5)]
            cols[("Volume", t)] = [1000 + i for i in range(5)]
        df = pd.DataFrame(cols, index=idx)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df

    monkeypatch.setattr("data.fetch.yf.download", fake)
    monkeypatch.setattr("data.fetch.time.sleep", lambda *a, **k: None)
    monkeypatch.setattr("data.providers.yfinance_provider.time.sleep", lambda *a, **k: None)
    long = YFinanceProvider(batch_size=10).fetch(["AAA", "BBB"], "2024-01-02", "2024-01-08")
    assert {c["auto_adjust"] for c in calls} == {True, False}
    assert len(calls) == 2
    assert set(long["ticker"]) == {"AAA", "BBB"}
    aaa = long[long["ticker"] == "AAA"].sort_values("date")
    assert aaa["close_adj"].iloc[0] == pytest.approx(100.0)
    assert aaa["close_raw"].iloc[0] == pytest.approx(50.0)
    assert aaa["volume"].iloc[0] == pytest.approx(1000.0)


# --------------------------------------------------------------------------- CLI


def test_cli_stats_and_vacuum(tmp_path, capsys):
    db = tmp_path / "bars.sqlite"
    store = BarStore(db)
    store.upsert(_long())
    store.close()
    rc = store_cli.main(["--stats", "--vacuum", "--db", str(db)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "tickers" in out.lower() or "tickers :" in out
    assert "vacuum: ok" in out
    assert "AAA" not in out or "bars" in out


def test_cli_backfill_uses_cached_fetch(monkeypatch, tmp_path):
    seen = {}

    def fake_cached(tickers, period="1y", report=None, **kw):
        seen["tickers"] = list(tickers)
        seen["period"] = period
        seen["store"] = kw.get("store")
        if report is not None:
            report.update(
                requested=len(tickers), downloaded=len(tickers),
                failed_tickers=[], missing_share=0.0, readjusted=[],
            )
        return pd.DataFrame(), pd.DataFrame()

    monkeypatch.setattr(store_cli, "fetch_prices_and_volume_cached", fake_cached)
    monkeypatch.setattr(store_cli, "get_universe", lambda universe=None: ["AAA", "BBB"])
    db = tmp_path / "bars.sqlite"
    rc = store_cli.main(["--backfill", "--period", "20y", "--universe", "custom", "--db", str(db)])
    assert rc == 0
    assert seen["period"] == "20y"
    assert seen["tickers"] == ["AAA", "BBB"]
    assert seen["store"] is not None
