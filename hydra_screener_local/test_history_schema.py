"""core/history.py schema v2: versioned, records the scored bar, carries the optional secondary regime."""
import json
import pathlib
import tempfile

from core.history import save_daily_run, HISTORY_SCHEMA_VERSION


def _save(**extra):
    out_dir = pathlib.Path(tempfile.mkdtemp())
    path = save_daily_run(
        date="20260904", regime_score=0.693, regime_type="STRONG", special_modes=[],
        pillar_multipliers={"COMPASS": 1.15}, top_candidates=[], base_dir=str(out_dir), **extra)
    return json.load(open(path, encoding="utf-8"))


def test_v2_fields_are_present():
    rec = _save(data_last_bar="2026-09-04")
    assert rec["schema_version"] == HISTORY_SCHEMA_VERSION == 2
    assert rec["regime_source"] == "rich"
    assert rec["data_last_bar"] == "2026-09-04"
    assert rec["regime"]["score"] == 0.693


def test_secondary_regime_is_optional():
    assert _save()["regime_secondary"] is None
    sec = {"symbol": "IWM", "score": 0.41, "type": "CAUTIOUS", "gate_would_block": False}
    assert _save(regime_secondary=sec)["regime_secondary"] == sec
