"""TASK-387 — the lab's sector map is pinned to a PIT snapshot, so two runs pick the same names."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "experiments"))

from data.pit import sectors_at, write_sectors_snapshot  # noqa: E402
from redesign_lab import resolve_sector_map  # noqa: E402


def _seed(pit_dir):
    write_sectors_snapshot({"AAA": "Tech", "BBB": "Energy"}, "20260801", unknown=[], pit_dir=pit_dir)
    write_sectors_snapshot({"AAA": "Tech", "BBB": "Energy"}, "20260815", unknown=[], pit_dir=pit_dir)   # pointer
    write_sectors_snapshot({"AAA": "Tech", "BBB": "Health", "CCC": "Utilities"}, "20260905", unknown=[], pit_dir=pit_dir)


def test_sectors_at_picks_latest_on_or_before_and_resolves_pointers(tmp_path):
    _seed(tmp_path)
    m, d = sectors_at(pit_dir=tmp_path)
    assert d == "20260905" and m["BBB"] == "Health"
    m, d = sectors_at("2026-08-20", pit_dir=tmp_path)            # pointer 0815 -> 0801
    assert d == "20260815" and m["BBB"] == "Energy" and "CCC" not in m
    assert sectors_at("2026-07-01", pit_dir=tmp_path) == ({}, None)
    assert sectors_at(pit_dir=tmp_path / "empty") == ({}, None)


def test_pinned_map_is_deterministic_and_dated(tmp_path, monkeypatch):
    _seed(tmp_path)
    cols = ["AAA", "BBB", "CCC", "ZZZ"]
    m1, i1 = resolve_sector_map(cols, "pit", None, pit_dir=tmp_path)
    m2, i2 = resolve_sector_map(cols, "pit", None, pit_dir=tmp_path)
    assert m1 == m2 and i1 == i2
    assert i1["source"] == "pit" and i1["snapshot_date"] == "20260905"
    assert i1["n_mapped"] == 3 and i1["n_fallback"] == 1 and m1["ZZZ"] == "Other"   # never the live cache
    m_old, i_old = resolve_sector_map(cols, "pit", "20260820", pit_dir=tmp_path)
    assert i_old["snapshot_date"] == "20260815" and m_old["BBB"] == "Energy" and m_old != m1


def test_live_source_uses_lookup_and_is_labelled(tmp_path):
    calls = []

    def look(t):
        calls.append(t)
        return "Live"

    m, info = resolve_sector_map(["AAA", "BBB"], "live", lookup=look)
    assert m == {"AAA": "Live", "BBB": "Live"} and info["source"] == "live" and calls == ["AAA", "BBB"]
    with pytest.raises(ValueError):
        resolve_sector_map(["AAA"], "cache")


def test_missing_snapshot_falls_back_to_live_with_a_label(tmp_path):
    m, info = resolve_sector_map(["AAA"], "pit", None, pit_dir=tmp_path / "none", lookup=lambda t: "L")
    assert m == {"AAA": "L"} and info["source"] == "live-fallback"


def test_dict_source_for_tests():
    m, info = resolve_sector_map(["AAA", "QQQ"], {"AAA": "X"})
    assert m["AAA"] == "X" and m["QQQ"] == "Other" and info["source"] == "dict"
