"""TASK-379 — sector negative cache, overrides, sector_report. yfinance patched."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import data.sectors as S  # noqa: E402


class _Boom:
    def __init__(self, t):
        self._t = t

    @property
    def info(self):
        raise RuntimeError("rate limited")


class _Ok:
    def __init__(self, t):
        self._t = t

    @property
    def info(self):
        return {"sector": f"Sec-{self._t}"}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    cache = tmp_path / "sector_cache.json"
    ov = tmp_path / "sector_overrides.json"
    ov.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(S, "CACHE_FILE", str(cache))
    monkeypatch.setattr(S, "OVERRIDES_FILE", str(ov))
    monkeypatch.setattr(S, "_memory", None)
    monkeypatch.setattr(S, "_overrides", None)
    return cache, ov


def test_failure_is_not_retried_within_7_days(isolated, monkeypatch):
    cache, _ov = isolated
    calls = []

    class CountBoom(_Boom):
        def __init__(self, t):
            super().__init__(t)
            calls.append(t)

    monkeypatch.setattr("yfinance.Ticker", CountBoom)
    import yfinance as yf
    monkeypatch.setattr(yf, "Ticker", CountBoom)

    S.refresh_sector_cache(["FISV"])
    S._memory = None
    S.refresh_sector_cache(["FISV"])
    assert calls == ["FISV"]
    blob = json.loads(cache.read_text(encoding="utf-8"))
    rec = blob["sectors"]["FISV"]
    assert rec["sector"] is None and rec.get("failed_at")


def test_failure_is_retried_after_ttl(isolated, monkeypatch):
    cache, _ov = isolated
    old = (datetime.now() - timedelta(days=8)).isoformat()
    cache.write_text(json.dumps({
        "updated": old,
        "sectors": {"FISV": {"sector": None, "failed_at": old}},
    }), encoding="utf-8")
    S._memory = None
    monkeypatch.setattr("yfinance.Ticker", _Ok)
    import yfinance as yf
    monkeypatch.setattr(yf, "Ticker", _Ok)
    out = S.refresh_sector_cache(["FISV"])
    assert S._positive(out["FISV"]) == "Sec-FISV"


def test_override_wins_over_cache(isolated, monkeypatch):
    cache, ov = isolated
    cache.write_text(json.dumps({
        "updated": datetime.now().isoformat(),
        "sectors": {"AAPL": "Technology"},
    }), encoding="utf-8")
    ov.write_text(json.dumps({"AAPL": "Healthcare", "_comment": "x"}), encoding="utf-8")
    S._memory = None
    S._overrides = None
    monkeypatch.setattr("yfinance.Ticker", _Boom)
    assert S.lookup_sector("AAPL") == "Healthcare"
    got = S.resolve_sectors(["AAPL"], budget_seconds=0)
    assert got["AAPL"] == "Healthcare"
    rep = S.sector_report()
    assert rep["override"] == 1
    assert set(rep) >= {"cached", "fetched", "negative", "override", "unknown"}


def test_empty_overrides_parity_with_cache(isolated, monkeypatch):
    cache, _ov = isolated
    cache.write_text(json.dumps({
        "updated": datetime.now().isoformat(),
        "sectors": {"AAA": "Energy", "BBB": "Financial Services"},
    }), encoding="utf-8")
    S._memory = None
    S._overrides = None
    monkeypatch.setattr("yfinance.Ticker", _Boom)
    got = S.resolve_sectors(["AAA", "BBB", "ZZZ"], budget_seconds=0)
    assert got["AAA"] == "Energy"
    assert got["BBB"] == "Financial Services"
    assert got["ZZZ"] == "Other"
    assert S.lookup_sector("AAA") == "Energy"
