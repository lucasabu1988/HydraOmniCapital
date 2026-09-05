"""TASK-329: portfolio_state reader. Auto-discovered by run_all_tests.py."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.portfolio_state import current_positions


def _write(folder, date, tickers, *, recommended=True, data_last_bar=None, version=2):
    recs = [{"ticker": t, "recommended": recommended} for t in tickers]
    payload = {
        "schema_version": version,
        "date": date,
        "data_last_bar": data_last_bar,
        "top_candidates": recs,
    }
    if version == 1:
        payload.pop("schema_version", None)
        payload.pop("data_last_bar", None)
    path = os.path.join(folder, f"{date}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def test_empty_dir():
    with tempfile.TemporaryDirectory() as d:
        assert current_positions(d, "2026-09-01") == []
        assert current_positions(os.path.join(d, "missing"), "2026-09-01") == []


def test_latest_run_on_or_before_as_of():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "2026-08-01", ["AAA"], data_last_bar="2026-07-31")
        _write(d, "2026-08-08", ["BBB"], data_last_bar="2026-08-07")
        _write(d, "2026-08-15", ["CCC"], data_last_bar="2026-08-14")
        pos = current_positions(d, "2026-08-10")
        assert [p["ticker"] for p in pos] == ["BBB"]
        assert pos[0]["entry_bar"] == "2026-08-07"
        assert pos[0]["run_date"] == "2026-08-08"


def test_consecutive_streak_sets_entry_bar():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "2026-08-01", ["AAA", "BBB"], data_last_bar="2026-07-31")
        _write(d, "2026-08-08", ["AAA"], data_last_bar="2026-08-07")
        _write(d, "2026-08-15", ["AAA", "CCC"], data_last_bar="2026-08-14")
        pos = {p["ticker"]: p for p in current_positions(d, "2026-08-15")}
        assert set(pos) == {"AAA", "CCC"}
        # AAA held through all three runs -> entry is the first data_last_bar
        assert pos["AAA"]["entry_bar"] == "2026-07-31"
        assert pos["AAA"]["bars_held"] > pos["CCC"]["bars_held"]
        # CCC appeared only on the last run
        assert pos["CCC"]["entry_bar"] == "2026-08-14"
        assert pos["CCC"]["bars_held"] == 1  # Fri 14 -> Fri 15 is one weekday step? 14 to 15 inclusive left = 1 (Fri)


def test_v1_file_falls_back_to_run_date():
    with tempfile.TemporaryDirectory() as d:
        _write(d, "2026-08-01", ["OLD"], version=1)
        pos = current_positions(d, "2026-08-01")
        assert len(pos) == 1
        assert pos[0]["ticker"] == "OLD"
        assert pos[0]["entry_bar"] == "2026-08-01"
        assert pos[0]["schema_version"] == 1
        assert pos[0]["bars_held"] == 0


def test_ignores_non_recommended():
    with tempfile.TemporaryDirectory() as d:
        payload = {
            "schema_version": 2,
            "date": "2026-08-01",
            "data_last_bar": "2026-07-31",
            "top_candidates": [
                {"ticker": "YES", "recommended": True},
                {"ticker": "NO", "recommended": False},
            ],
        }
        with open(os.path.join(d, "2026-08-01.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f)
        pos = current_positions(d, "2026-08-01")
        assert [p["ticker"] for p in pos] == ["YES"]
