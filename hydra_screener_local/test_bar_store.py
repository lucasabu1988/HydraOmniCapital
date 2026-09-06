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
    slim = _long(["AAA"]).iloc[-15:]
    store.replace_ticker("AAA", slim)
    px = store.closes(["AAA"], IDX[0], IDX[-1])
    assert len(px) == 15
    assert store.last_dates(["AAA"])["AAA"] == pd.Timestamp(IDX[-1]).normalize()
    store.close()


def test_replace_ticker_refuses_empty_or_short_frame(tmp_path):
    store = BarStore(tmp_path / "bars.sqlite")
    store.upsert(_long())
    before = store.closes(["AAA"], IDX[0], IDX[-1])
    assert store.replace_ticker("AAA", pd.DataFrame()) == 0
    assert store.replace_ticker("AAA", _long(["AAA"]).iloc[-3:]) == 0
    after = store.closes(["AAA"], IDX[0], IDX[-1])
    assert len(after) == len(before) == 40
    assert after["AAA"].tolist() == before["AAA"].tolist()
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


def test_readjust_three_tickers_one_batched_fetch(tmp_path):
    store = BarStore(tmp_path / "bars.sqlite")
    frame = _long(("AAA", "BBB", "CCC"))
    provider = FakeProvider(frame)
    fetch_prices_and_volume_cached(
        ["AAA", "BBB", "CCC"], period="1y", provider=provider, store=store, asof=ASOF,
    )
    n_after_seed = len(provider.calls)
    bump = IDX[-5]
    for t in ("AAA", "BBB", "CCC"):
        mask = (provider.df["ticker"] == t) & (pd.to_datetime(provider.df["date"]) == bump)
        provider.df.loc[mask, "close_adj"] = provider.df.loc[mask, "close_adj"] * 1.01
    report = {}
    fetch_prices_and_volume_cached(
        ["AAA", "BBB", "CCC"], period="1y", report=report, provider=provider, store=store, asof=ASOF,
    )
    extra = provider.calls[n_after_seed:]
    assert set(report["readjusted"]) == {"AAA", "BBB", "CCC"}
    full = [c for c in extra if set(c[0]) == {"AAA", "BBB", "CCC"} and c[1] == period_to_start("1y", ASOF)]
    assert len(full) == 1, extra
    assert store.stats()["readjusted_last_run"] == 3
    store.close()


def test_readjust_empty_name_keeps_stored_rows(tmp_path):
    """TASK-376: one of three mismatching names comes back empty -> its bars survive."""
    store = BarStore(tmp_path / "bars.sqlite")
    frame = _long(("AAA", "BBB", "CCC"))
    provider = FakeProvider(frame)
    fetch_prices_and_volume_cached(
        ["AAA", "BBB", "CCC"], period="1y", provider=provider, store=store, asof=ASOF,
    )
    before_ccc = store.closes(["CCC"], IDX[0], IDX[-1])["CCC"].tolist()
    bump = IDX[-5]
    for t in ("AAA", "BBB", "CCC"):
        mask = (provider.df["ticker"] == t) & (pd.to_datetime(provider.df["date"]) == bump)
        provider.df.loc[mask, "close_adj"] = provider.df.loc[mask, "close_adj"] * 1.01

    class DropCCC(FakeProvider):
        def fetch(self, tickers, start, end):
            out = super().fetch(tickers, start, end)
            start_ts = pd.Timestamp(start).normalize()
            # Full-period readjust only (the tail uses the overlap start).
            if start_ts == period_to_start("1y", ASOF):
                out = out[out["ticker"].astype(str) != "CCC"]
            return out.reset_index(drop=True)

    dropper = DropCCC(provider.df)
    report = {}
    fetch_prices_and_volume_cached(
        ["AAA", "BBB", "CCC"], period="1y", report=report, provider=dropper, store=store, asof=ASOF,
    )
    assert set(report["readjusted"]) == {"AAA", "BBB"}
    assert "CCC" in report["failed_tickers"]
    assert (report.get("failed_reasons") or {}).get("CCC") == "readjust_empty"
    after_ccc = store.closes(["CCC"], IDX[0], IDX[-1])["CCC"].tolist()
    assert after_ccc == before_ccc
    bumped = store.closes(["AAA"], bump, bump)["AAA"].iloc[0]
    assert bumped == pytest.approx(float(provider.df.loc[
        (provider.df["ticker"] == "AAA") & (pd.to_datetime(provider.df["date"]) == bump),
        "close_adj",
    ].iloc[0]))
    store.close()


def test_partial_full_fetch_marks_absent_names(tmp_path):
    store = BarStore(tmp_path / "bars.sqlite")
    provider = FakeProvider(_long(("AAA", "BBB")))
    report = {}
    fetch_prices_and_volume_cached(
        ["AAA", "BBB", "CCC"], period="1y", report=report, provider=provider, store=store, asof=ASOF,
    )
    assert "CCC" in report["failed_tickers"]
    assert (report.get("failed_reasons") or {}).get("CCC") == "fetch_empty"
    assert "CCC" not in store.last_dates(["AAA", "BBB", "CCC"])
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
    long = YFinanceProvider(batch_size=10, two_pass=True).fetch(["AAA", "BBB"], "2024-01-02", "2024-01-08")
    assert {c["auto_adjust"] for c in calls} == {True, False}
    assert len(calls) == 2
    assert set(long["ticker"]) == {"AAA", "BBB"}
    aaa = long[long["ticker"] == "AAA"].sort_values("date")
    assert aaa["close_adj"].iloc[0] == pytest.approx(100.0)
    assert aaa["close_raw"].iloc[0] == pytest.approx(50.0)
    assert aaa["volume"].iloc[0] == pytest.approx(1000.0)


def test_yfinance_provider_one_download_per_batch(monkeypatch):
    calls = []
    idx = pd.bdate_range("2024-01-02", periods=5)

    def fake(batch, start=None, end=None, period=None, auto_adjust=True, **kw):
        calls.append({"batch": list(batch), "auto_adjust": auto_adjust})
        cols = {}
        for t in batch:
            cols[("Close", t)] = [50.0 + i for i in range(5)]
            cols[("Adj Close", t)] = [100.0 + i for i in range(5)]
            cols[("Volume", t)] = [1000 + i for i in range(5)]
        df = pd.DataFrame(cols, index=idx)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df

    monkeypatch.setattr("data.fetch.yf.download", fake)
    monkeypatch.setattr("data.providers.yfinance_provider.time.sleep", lambda *a, **k: None)
    # tail_batch_size pinned: this test is about one download per batch, not tail sizing (TASK-382)
    long = YFinanceProvider(batch_size=2, tail_batch_size=2).fetch(["AAA", "BBB", "CCC"], "2024-01-02", "2024-01-08")
    assert all(c["auto_adjust"] is False for c in calls)
    assert len(calls) == 2  # two batches of 2, one download each
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


# --------------------------------------------------------------------------- TASK-382 tail batches


def _fake_download_factory(calls, n_bars):
    idx = pd.bdate_range("2024-01-02", periods=n_bars)

    def fake(batch, start=None, end=None, period=None, auto_adjust=True, **kw):
        calls.append(list(batch))
        cols = {}
        for tk in batch:
            cols[("Close", tk)] = [50.0 + i for i in range(n_bars)]
            cols[("Adj Close", tk)] = [100.0 + i for i in range(n_bars)]
            cols[("Volume", tk)] = [1000 + i for i in range(n_bars)]
        df = pd.DataFrame(cols, index=idx)
        df.columns = pd.MultiIndex.from_tuples(df.columns)
        return df

    return fake


def test_tail_window_uses_the_big_batch(monkeypatch):
    calls = []
    monkeypatch.setattr("data.fetch.yf.download", _fake_download_factory(calls, 10))
    monkeypatch.setattr("data.providers.yfinance_provider.time.sleep", lambda *a, **k: None)
    prov = YFinanceProvider(batch_size=2, tail_batch_size=300)
    names = [f"T{i}" for i in range(7)]
    prov.fetch(names, "2024-01-02", "2024-01-15")           # 10 business days -> tail
    assert len(calls) == 1 and calls[0] == names
    assert prov.last_batches == 1
    assert prov.batch_plan("2024-01-02", "2024-01-15") == (300, 0.25)


def test_long_window_keeps_the_normal_batch(monkeypatch):
    calls = []
    monkeypatch.setattr("data.fetch.yf.download", _fake_download_factory(calls, 10))
    monkeypatch.setattr("data.providers.yfinance_provider.time.sleep", lambda *a, **k: None)
    prov = YFinanceProvider(batch_size=2, tail_batch_size=300)
    names = [f"T{i}" for i in range(5)]
    prov.fetch(names, "2022-01-03", "2024-01-15")           # two years -> full path
    assert len(calls) == 3                                   # ceil(5 / 2)
    assert prov.batch_plan("2022-01-03", "2024-01-15") == (2, 1.0)


def test_no_sleep_after_the_last_batch(monkeypatch):
    slept = []
    monkeypatch.setattr("data.fetch.yf.download", _fake_download_factory([], 10))
    monkeypatch.setattr("data.providers.yfinance_provider.time.sleep", lambda s: slept.append(s))
    prov = YFinanceProvider(batch_size=2, tail_batch_size=2, tail_sleep=0.5)
    prov.fetch(["A", "B", "C", "D"], "2024-01-02", "2024-01-15")   # two batches -> one pause
    assert slept == [0.5]


def test_stale_name_gets_its_own_window(tmp_path):
    """One name last stored in July must not turn the 3000-name tail into a 35-bar window (TASK-382)."""
    from data.fetch import fetch_prices_and_volume_cached
    from data.store import BarStore

    store = BarStore(tmp_path / "b.sqlite")
    recent_idx = pd.bdate_range("2026-08-03", "2026-09-04")
    stale_idx = pd.bdate_range("2026-06-01", "2026-07-17")

    def long(ticker, idx):
        return pd.DataFrame({"ticker": ticker, "date": idx, "close_adj": 10.0, "close_raw": 10.0,
                             "volume": 100.0, "source": "t", "fetched_at": "x"})

    store.upsert(pd.concat([long("AAA", recent_idx), long("BBB", recent_idx), long("OLDW", stale_idx)]))

    calls = []

    class Prov:
        def fetch(self, tickers, start, end):
            calls.append((sorted(tickers), pd.Timestamp(start), pd.Timestamp(end)))
            idx = pd.bdate_range(start, end)
            return pd.concat([long(t, idx) for t in tickers], ignore_index=True)

    fetch_prices_and_volume_cached(["AAA", "BBB", "OLDW"], period="1y", provider=Prov(), store=store,
                                   asof="2026-09-08")
    windows = {tuple(c[0]): (c[1], c[2]) for c in calls}
    assert ("AAA", "BBB") in windows and ("OLDW",) in windows
    recent_start, _ = windows[("AAA", "BBB")]
    assert recent_start >= pd.Timestamp("2026-08-21")            # the 10-bar overlap, not July
    stale_start, _ = windows[("OLDW",)]
    assert stale_start <= pd.Timestamp("2026-07-06")
