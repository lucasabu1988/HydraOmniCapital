"""TASK-362 — PIT snapshots. Synthetic files, no network."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import snapshot_universe as SU  # noqa: E402
from data.pit import (  # noqa: E402
    changes,
    history,
    membership,
    write_sectors_snapshot,
    write_universe_snapshot,
)


def test_write_and_membership_and_pointer(tmp_path):
    a = write_universe_snapshot("sp500", ["AAPL", "MSFT", "XOM"], "20260105", "test", pit_dir=tmp_path)
    assert a.name == "universe_sp500_20260105.json"
    data = a.read_text(encoding="utf-8")
    assert "AAPL" in data and "count" in data
    b = write_universe_snapshot("sp500", ["MSFT", "AAPL", "XOM"], "20260112", "test", pit_dir=tmp_path)
    assert b.read_text(encoding="utf-8").strip() == "same_as_20260105"
    assert membership("sp500", "2026-01-10", pit_dir=tmp_path) == {"AAPL", "MSFT", "XOM"}
    assert membership("sp500", "20260112", pit_dir=tmp_path) == {"AAPL", "MSFT", "XOM"}
    write_universe_snapshot("sp500", ["AAPL", "MSFT", "NVDA"], "20260201", "test", pit_dir=tmp_path)
    added, dropped = changes("sp500", "20260105", "20260201", pit_dir=tmp_path)
    assert added == {"NVDA"} and dropped == {"XOM"}
    hist = history("sp500", pit_dir=tmp_path)
    assert list(hist["date"]) == ["20260105", "20260201"]
    assert list(hist["count"]) == [3, 3]
    assert int(hist.loc[hist["date"] == "20260201", "added"].iloc[0]) == 1
    assert int(hist.loc[hist["date"] == "20260201", "dropped"].iloc[0]) == 1
    assert membership("sp500", "2020-01-01", pit_dir=tmp_path) == set()


def test_sectors_pointer_and_unknown(tmp_path):
    p1 = write_sectors_snapshot(
        {"AAPL": "Technology", "JPM": "Financial Services"},
        "20260105", unknown=["ZZZ"], pit_dir=tmp_path,
    )
    assert "Technology" in p1.read_text(encoding="utf-8")
    p2 = write_sectors_snapshot(
        {"JPM": "Financial Services", "AAPL": "Technology"},
        "20260112", unknown=["ZZZ"], pit_dir=tmp_path,
    )
    assert p2.read_text(encoding="utf-8").strip() == "same_as_20260105"


def test_seed_from_local_csvs(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    (out / "sp500_tickers.csv").write_text("ticker\nAAPL\nMSFT\n", encoding="utf-8")
    (out / "nasdaq100_tickers.csv").write_text("ticker\nMSFT\nNVDA\n", encoding="utf-8")
    cache = tmp_path / "data_cache"
    cache.mkdir()
    (cache / "sector_cache.json").write_text(
        '{"updated": "2026-01-05", "sectors": {"AAPL": "Technology", "FOO": "Other"}}',
        encoding="utf-8",
    )
    monkey_root = tmp_path
    # point the CLI at the fake tree
    old_root = SU.ROOT
    SU.ROOT = monkey_root
    try:
        written = SU.seed(pit_dir=tmp_path / "pit")
    finally:
        SU.ROOT = old_root
    names = {p.name for p in written}
    assert any(n.startswith("universe_sp500_") for n in names)
    assert any(n.startswith("universe_all_") for n in names)
    pit = tmp_path / "pit"
    assert membership("sp500", "20991231", pit_dir=pit) == {"AAPL", "MSFT"}
    assert membership("all", "20991231", pit_dir=pit) == {"AAPL", "MSFT", "NVDA"}
    assert any(n.startswith("sectors_") for n in names)


def test_cli_seed(tmp_path, capsys):
    # empty tree: seed should not crash
    rc = SU.main(["--seed", "--pit-dir", str(tmp_path)])
    assert rc == 0
