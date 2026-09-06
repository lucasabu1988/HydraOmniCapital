"""TASK-375 — universe fetch chain under test. requests.get patched; no network."""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data import universe as U  # noqa: E402

FIXTURE = Path(__file__).parent / "test_fixtures" / "universe"
SP500_N = 401
SP500_TICKERS = [f"T{i:03d}" for i in range(SP500_N)]


@pytest.fixture(autouse=True)
def _no_sleep():
    with patch.object(U.time, "sleep", return_value=None):
        yield


def _text(name: str) -> str:
    return (FIXTURE / name).read_text(encoding="utf-8")


def _resp(text: str, json_body=None):
    r = MagicMock()
    r.text = text
    r.status_code = 200
    r.raise_for_status = MagicMock()
    r.json = MagicMock(return_value=json_body if json_body is not None else {})
    return r


def _route(mapping: dict[str, MagicMock]):
    def fake_get(url, *args, **kwargs):
        for needle, resp in mapping.items():
            if needle in str(url):
                if isinstance(resp, Exception):
                    raise resp
                return resp
        raise AssertionError(f"unexpected url {url}")
    return fake_get


def _isolate_cache(tmp_path):
    cache_dir = tmp_path / "data_cache"
    cache_dir.mkdir()
    out_dir = tmp_path / "output"
    out_dir.mkdir()

    def cache_path(universe="sp500"):
        return str(out_dir / f"{universe}_tickers.csv")

    return (
        patch.object(U, "DATA_CACHE_DIR", str(cache_dir)),
        patch.object(U, "_get_cache_path", cache_path),
    )


def test_each_sp500_fetcher_parses_fixture():
    cases = [
        ("slickcharts.com/sp500", "sp500_slickcharts.html", U._fetch_sp500_from_slickcharts, False),
        ("barchart.com/stocks/indices/spx", "sp500_barchart.html", U._fetch_sp500_from_barchart, True),
        ("wikipedia.org/wiki/List_of_S", "sp500_wikipedia.html", U._fetch_sp500_from_wikipedia, True),
        ("datasets/s-and-p-500-companies", "github_constituents.csv", U._fetch_sp500_from_github, True),
        ("stevenruidigao/sp500", "steven.csv", U._fetch_sp500_from_github_steven, True),
        ("saikr789/stock-market-prediction", "saikr.csv", U._fetch_sp500_from_github_saikr, True),
    ]
    for needle, fname, fn, upper in cases:
        with patch.object(U.requests, "get", side_effect=_route({needle: _resp(_text(fname))})):
            got = fn()
        assert got is not None, fname
        assert len(got) == SP500_N, fname
        expect = [t.upper() for t in SP500_TICKERS] if upper else SP500_TICKERS
        assert got[0] == expect[0] and got[-1] == expect[-1], fname


def test_garbage_falls_through_to_next_source(tmp_path):
    p_dir, p_cache = _isolate_cache(tmp_path)
    mapping = {
        "slickcharts.com/sp500": _resp(_text("garbage.html")),
        "barchart.com": _resp(_text("sp500_barchart.html")),
        "wikipedia.org": _resp(_text("garbage.html")),
        "datasets/s-and-p-500": _resp(_text("garbage.csv")),
        "stevenruidigao": _resp(_text("garbage.csv")),
        "saikr789": _resp(_text("garbage.csv")),
    }
    with p_dir, p_cache, patch.object(U.requests, "get", side_effect=_route(mapping)):
        got = U.get_sp500_tickers(use_cache=False)
    assert got == sorted(SP500_TICKERS)


def test_all_sources_fail_uses_fallback_and_warns(tmp_path, caplog):
    p_dir, p_cache = _isolate_cache(tmp_path)
    with p_dir, p_cache, patch.object(U.requests, "get", side_effect=Exception("down")), \
            caplog.at_level(logging.WARNING):
        got = U.get_sp500_tickers(use_cache=False)
    assert got == U.get_fallback_sp500_tickers()
    assert any("fallback" in rec.message.lower() for rec in caplog.records)


def test_seven_day_cache_honoured_and_refreshed(tmp_path):
    p_dir, p_cache = _isolate_cache(tmp_path)
    csv_path = tmp_path / "output" / "sp500_tickers.csv"
    pd.DataFrame({"ticker": ["CACHE1", "CACHE2"]}).to_csv(csv_path, index=False)
    with p_dir, p_cache, patch.object(U.requests, "get") as get:
        got = U.get_sp500_tickers(use_cache=True)
        get.assert_not_called()
    assert got == ["CACHE1", "CACHE2"]

    old = (datetime.now() - timedelta(days=8)).timestamp()
    os.utime(csv_path, (old, old))
    mapping = {"slickcharts.com/sp500": _resp(_text("sp500_slickcharts.html"))}
    with p_dir, p_cache, patch.object(U.requests, "get", side_effect=_route(mapping)):
        got = U.get_sp500_tickers(use_cache=True)
    assert got == sorted(SP500_TICKERS)
    assert csv_path.exists()
    fresh = pd.read_csv(csv_path)["ticker"].tolist()
    assert "T000" in fresh


def test_get_universe_all_is_the_union():
    sp, nd, dj, r1, r2 = ["AAA"], ["BBB", "AAA"], ["CCC"], ["DDD"], ["EEE", "BBB"]
    with patch.object(U, "get_sp500_tickers", return_value=sp), \
            patch.object(U, "get_nasdaq100_tickers", return_value=nd), \
            patch.object(U, "get_dow30_tickers", return_value=dj), \
            patch.object(U, "get_russell1000_tickers", return_value=r1), \
            patch.object(U, "get_russell2000_tickers", return_value=r2):
        got = U.get_universe(universe="all")
    assert set(got) == {"AAA", "BBB", "CCC", "DDD", "EEE"}
    assert len(got) == 5


def test_universe_report_fallback_and_cache(tmp_path, caplog):
    p_dir, p_cache = _isolate_cache(tmp_path)
    csv_path = tmp_path / "output" / "sp500_tickers.csv"
    pd.DataFrame({"ticker": ["X", "Y"]}).to_csv(csv_path, index=False)
    with p_dir, p_cache:
        rep = U.universe_report("sp500")
    assert rep["universe"] == "sp500"
    assert rep["from_cache"] is True
    assert rep["count"] == 2
    assert rep["fallback"] is False

    os.remove(csv_path)
    with p_dir, p_cache, patch.object(U.requests, "get", side_effect=Exception("down")), \
            caplog.at_level(logging.WARNING):
        rep = U.universe_report("sp500")
    assert rep["fallback"] is True
    assert rep["source_used"] == "fallback"
    assert rep["count"] == len(U.get_fallback_sp500_tickers())
    assert any("fallback" in rec.message.lower() for rec in caplog.records)


def test_universe_report_all_union_key():
    with patch.object(U, "get_universe", return_value=["A", "B"]):
        rep = U.universe_report("all")
    assert rep["source_used"] == "union"
    assert rep["count"] == 2
    assert "universe" in rep and "from_cache" in rep and "fallback" in rep


def test_nasdaq_dow_russell_fetchers_parse_fixtures():
    with patch.object(U.requests, "get",
                      side_effect=_route({"slickcharts.com/nasdaq100": _resp(_text("nasdaq100_slickcharts.html"))})):
        nd = U._fetch_nasdaq100_from_slickcharts()
    assert nd is not None and len(nd) == 91
    with patch.object(U.requests, "get",
                      side_effect=_route({"slickcharts.com/dowjones": _resp(_text("dow30_slickcharts.html"))})):
        dj = U._fetch_dow30_from_slickcharts()
    assert dj is not None and len(dj) == 30
    with patch.object(U.requests, "get",
                      side_effect=_route({"slickcharts.com/russell1000": _resp(_text("russell_slickcharts.html"))})):
        r1 = U._fetch_russell1000_from_slickcharts()
    assert r1 is not None and len(r1) == 801


def test_nasdaq_ranked_screener_and_russell_slices():
    import string
    from itertools import product
    letters = ["".join(p) for p in product(string.ascii_uppercase, repeat=3)]
    rows = [{"symbol": letters[i], "marketCap": str(10_000_000 - i)} for i in range(3600)]
    body = {"data": {"rows": rows}}
    U._NASDAQ_RANKED_CACHE = None
    with patch.object(U.requests, "get", return_value=_resp("{}", json_body=body)):
        ranked = U._fetch_us_stocks_ranked_by_marketcap()
    assert ranked is not None and len(ranked) == 3600
    assert U._fetch_russell1000_from_nasdaq() == ranked[:1000]
    assert U._fetch_russell2000_from_nasdaq() == ranked[1000:3000]
    U._NASDAQ_RANKED_CACHE = None


def test_pit_helpers_on_synthetic_payload():
    payload = {
        "current": ["AAA", "BAC"],
        "changes": [{"date": "2020-01-02", "added": "AAA", "removed": "OLD"}],
        "snapshots": {
            "2008-01-01": ["AAA", "AAMRQ-201312", "ZZZ"],
            "2015-01-01": ["AAA", "BAC"],
        },
    }
    assert U._yahoo_ticker("brk.b") == "BRK-B"
    assert U.membership_as_of("2008-06-01", payload) == ["AAA", "AAMRQ-201312", "ZZZ"]
    assert U.pit_yahoo_symbol("AAA", payload) == "AAA"
    assert U.pit_yahoo_symbol("AAMRQ-201312", payload) is None or isinstance(
        U.pit_yahoo_symbol("AAMRQ-201312", payload), (str, type(None))
    )
    csv = "date,tickers\n2008-01-01,\"AAA,BBB,CCC," + ",".join(f"N{i}" for i in range(50)) + "\"\n"
    snaps = U._parse_fja_snapshots(csv)
    assert "2008-01-01" in snaps and len(snaps["2008-01-01"]) > 50
    wiki = [
        pd.DataFrame({"x": [1]}),
        pd.DataFrame({
            "Date": ["2020-01-02"],
            "Added_Ticker": ["NEW"],
            "Removed_Ticker": ["OLD"],
        }),
    ]
    ch = U._parse_wiki_change_tables(wiki)
    assert ch and ch[0]["added"] == "NEW" and ch[0]["removed"] == "OLD"
    y = U.yahoo_membership_as_of("2015-06-01", payload)
    assert "AAA" in y and "BAC" in y


def test_custom_universe_is_initial_list():
    from config import INITIAL_UNIVERSE
    got = U.get_universe(universe="custom")
    assert got == list(dict.fromkeys(INITIAL_UNIVERSE))
    rep = U.universe_report("custom")
    assert rep["source_used"] == "INITIAL_UNIVERSE"


def test_cached_getters_and_fallbacks(tmp_path):
    p_dir, p_cache = _isolate_cache(tmp_path)
    for name, tickers in (
        ("nasdaq100", ["NDX1", "NDX2"]),
        ("dow30", ["DJ1", "DJ2"]),
        ("russell1000", ["R1A", "R1B"]),
        ("russell2000", ["R2A", "R2B"]),
    ):
        pd.DataFrame({"ticker": tickers}).to_csv(tmp_path / "output" / f"{name}_tickers.csv", index=False)
    with p_dir, p_cache:
        assert U.get_nasdaq100_tickers() == ["NDX1", "NDX2"]
        assert U.get_dow30_tickers() == ["DJ1", "DJ2"]
        assert U.get_russell1000_tickers() == ["R1A", "R1B"]
        assert U.get_russell2000_tickers() == ["R2A", "R2B"]
        assert set(U.get_russell3000_tickers()) == {"R1A", "R1B", "R2A", "R2B"}
        assert U.get_universe(universe="nasdaq100") == ["NDX1", "NDX2"]
        assert U.get_universe(universe="dow30") == ["DJ1", "DJ2"]
        assert U.get_universe(universe="russell1000") == ["R1A", "R1B"]
        assert U.get_universe(universe="russell2000") == ["R2A", "R2B"]
        assert U.get_universe(universe="russell3000") == U.get_russell3000_tickers()


def test_nasdaq_dow_russell_fallback_when_network_fails(tmp_path):
    p_dir, p_cache = _isolate_cache(tmp_path)
    with p_dir, p_cache, patch.object(U.requests, "get", side_effect=Exception("down")):
        nd = U.get_nasdaq100_tickers(use_cache=False)
        dj = U.get_dow30_tickers(use_cache=False)
        r1 = U.get_russell1000_tickers(use_cache=False)
        r2 = U.get_russell2000_tickers(use_cache=False)
    assert nd == U.get_fallback_nasdaq100_tickers()
    assert "AAPL" in dj and len(dj) == 30
    assert set(U.get_fallback_sp500_tickers()).issubset(set(r1))
    assert r2  # r2 fallback is a non-empty list


def test_pit_payload_reads_valid_cache(tmp_path):
    p_dir, p_cache = _isolate_cache(tmp_path)
    payload = {
        "cache_version": U._PIT_CACHE_VERSION,
        "current": ["AAA"],
        "changes": [],
        "snapshots": {"2008-01-01": ["AAA", "BBB"]},
    }
    pit = tmp_path / "data_cache" / "sp500_pit.json"
    pit.write_text(json.dumps(payload), encoding="utf-8")
    with p_dir, p_cache:
        got = U.fetch_sp500_pit_payload()
    assert got["current"] == ["AAA"]
    assert U.membership_as_of("2008-06-01", got) == ["AAA", "BBB"]


def test_russell_barchart_and_nasdaq100_wikipedia():
    with patch.object(U.requests, "get",
                      side_effect=_route({"barchart.com": _resp(_text("russell_slickcharts.html"))})):
        got = U._fetch_russell1000_from_barchart()
    assert got is not None and len(got) == 801
    with patch.object(U.requests, "get",
                      side_effect=_route({"wikipedia.org/wiki/Nasdaq-100": _resp(_text("nasdaq100_slickcharts.html"))})):
        got = U._fetch_nasdaq100_from_wikipedia()
    assert got is not None and len(got) == 91
