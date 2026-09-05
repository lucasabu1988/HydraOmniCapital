"""
Tests for TASK-201: universe network hardening (retry, logging, cache fallback).
TASK-316: patch DATA_CACHE_DIR (the attribute that actually exists).
"""
import json
import os
import sys
import logging
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data import universe as universe_mod


_SP500_FETCHERS = [
    "_fetch_sp500_from_slickcharts",
    "_fetch_sp500_from_barchart",
    "_fetch_sp500_from_wikipedia",
    "_fetch_sp500_from_github",
    "_fetch_sp500_from_github_steven",
    "_fetch_sp500_from_github_saikr",
]


def test_universe_robustness_all_sources_fail_logs_and_uses_cache(tmp_path, caplog):
    """All live sources fail -> logs warnings, uses cache if present, emits explicit warning."""
    cache_dir = tmp_path / "data_cache"
    cache_dir.mkdir()
    cache_file = cache_dir / "universe_cache_sp500.json"
    fake_tickers = ["FAKE1", "FAKE2", "FAKE3"]
    cache_file.write_text(json.dumps({
        "date": "2026-06-11T10:00:00",
        "tickers": fake_tickers,
        "source": "test",
    }))

    def fake_get_cache(universe="sp500"):
        return str(tmp_path / "output" / f"{universe}_tickers.csv")

    fetcher_patches = [
        patch.object(universe_mod, name, return_value=None) for name in _SP500_FETCHERS
    ]
    with patch.object(universe_mod, "_get_cache_path", fake_get_cache), \
         patch.object(universe_mod, "DATA_CACHE_DIR", str(cache_dir)), \
         caplog.at_level(logging.WARNING):
        for p in fetcher_patches:
            p.start()
        try:
            result = universe_mod.get_sp500_tickers(use_cache=True)
        finally:
            for p in fetcher_patches:
                p.stop()

    assert result == fake_tickers
    assert any("failed" in rec.message.lower() or "using cached universe" in rec.message.lower()
               for rec in caplog.records)
    assert any("using cached universe" in rec.message.lower() for rec in caplog.records)


def test_universe_robustness_success_writes_cache(tmp_path):
    """Successful resolution writes the json cache file under DATA_CACHE_DIR."""
    cache_dir = tmp_path / "data_cache"
    cache_dir.mkdir()
    # Live sources require >400 tickers before they count as a hit.
    fake_tickers = [f"T{i:03d}" for i in range(401)]

    def fake_get_cache(universe="sp500"):
        out = tmp_path / "output" / f"{universe}_tickers.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        return str(out)

    other = [patch.object(universe_mod, name, return_value=None)
             for name in _SP500_FETCHERS if name != "_fetch_sp500_from_slickcharts"]
    with patch.object(universe_mod, "_get_cache_path", fake_get_cache), \
         patch.object(universe_mod, "DATA_CACHE_DIR", str(cache_dir)), \
         patch.object(universe_mod, "_fetch_sp500_from_slickcharts", return_value=fake_tickers):
        for p in other:
            p.start()
        try:
            result = universe_mod.get_sp500_tickers(use_cache=False)
        finally:
            for p in other:
                p.stop()

    assert result == sorted(fake_tickers)
    written = cache_dir / "universe_cache_sp500.json"
    assert written.exists()
    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["tickers"] == sorted(fake_tickers)


def test_universe_robustness_network_failures_are_logged(caplog):
    """_get_with_retry logs a warning when requests.get raises."""
    with caplog.at_level(logging.WARNING):
        with patch.object(universe_mod.requests, "get", side_effect=Exception("boom")):
            out = universe_mod._get_with_retry("http://example.invalid", attempts=1)
    assert out is None
    assert any("failed" in rec.message.lower() for rec in caplog.records)
