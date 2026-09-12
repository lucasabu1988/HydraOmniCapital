"""TASK-432: the holdout is data with a hash, and crossing it leaves a mark.

Auto-discovered by run_all_tests.py (pytest-routed: no __main__ block)."""
from __future__ import annotations

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
for _p in (HERE, os.path.dirname(HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import holdout as H  # noqa: E402


def test_the_declaration_hashes_to_the_pin_and_says_what_lucas_said():
    h = H.load_holdout()
    assert h["sha256"] == H.PINNED_HOLDOUT_SHA256
    p = h["partitions"]
    assert (p["research"]["start"], p["research"]["end"]) == ("2010-01-01", "2023-12-31")
    assert (p["validation"]["start"], p["validation"]["end"]) == ("2024-01-01", "2026-09-07")
    assert (p["live"]["start"], p["live"]["end"]) == ("2026-09-08", None)


def test_a_moved_declaration_fails_closed(tmp_path):
    h = H.load_holdout()
    h["partitions"]["validation"]["end"] = "2026-12-31"      # someone widens the test set
    bad = tmp_path / "holdout.json"
    bad.write_text(json.dumps(h), encoding="utf-8")
    with pytest.raises(SystemExit, match="partitions moved"):
        H.load_holdout(str(bad))
    assert H.load_holdout(str(bad), verify=False)["partitions"]["validation"]["end"] == "2026-12-31"


def test_partition_of_and_span():
    assert H.partition_of("2015-06-30") == "research"
    assert H.partition_of("2024-01-01") == "validation"
    assert H.partition_of("2026-09-07") == "validation"
    assert H.partition_of("2026-09-08") == "live"
    assert H.partition_of("2009-12-31") is None
    assert H.partitions_spanned("2010-06-28", "2023-06-30") == ["research"]
    assert H.partitions_spanned("2010-06-28", "2026-08-26") == ["research", "validation"]
    assert H.partitions_spanned("2026-09-08", "2026-09-10") == ["live"]


def test_crossing_on_purpose_leaves_the_mark_in_json_and_on_stdout(capsys):
    """The acceptance: an experiment that reads outside its partition is marked, not warned."""
    out = H.stamp({"task": "x"}, first="2010-06-28", last="2026-08-26", declared="research")
    assert out["holdout"]["breached"] is True
    assert any(ln.startswith(H.BREACH) and "'validation'" in ln for ln in out["holdout"]["breaches"])
    printed = capsys.readouterr().out
    assert H.BREACH in printed and "'validation'" in printed
    assert out["holdout"]["holdout_sha256"] == H.PINNED_HOLDOUT_SHA256


def test_staying_inside_leaves_no_mark_and_a_frozen_span_is_declared_not_breached(capsys):
    inside = H.stamp({}, first="2011-01-03", last="2023-12-29", declared="research")
    assert inside["holdout"]["breaches"] == [] and inside["holdout"]["breached"] is False
    both = H.stamp({}, first="2010-06-28", last="2026-08-26", declared="research+validation")
    assert both["holdout"]["breaches"] == []
    assert both["holdout"]["spanned"] == ["research", "validation"]
    assert H.BREACH not in capsys.readouterr().out


def test_reading_live_is_always_marked_unless_declared():
    marked = H.breaches("2026-09-01", "2026-09-10", "validation")
    assert any("'live'" in ln for ln in marked)
    assert H.breaches("2026-09-08", "2026-09-10", "live") == []


def test_before_2010_is_named_because_there_is_no_traded_universe_record():
    lines = H.breaches("2005-01-03", "2015-01-01", "research")
    assert any("before research" in ln for ln in lines)


def test_unknown_partition_names_are_refused():
    with pytest.raises(ValueError, match="unknown partition"):
        H.breaches("2015-01-01", "2016-01-01", "test")
