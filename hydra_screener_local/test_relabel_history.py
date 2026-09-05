"""relabel_history_regime.py — v1 files get the rich score, keep the original, and v2 files are untouched."""
import numpy as np
import pandas as pd

from core.history import HISTORY_SCHEMA_VERSION
from relabel_history_regime import relabel_run, RELABELLED_SOURCE


def _spy(n=320, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end="2026-09-04", periods=n)
    return pd.Series(400 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, n))), index=idx)


V1 = {
    "date": "20260904",
    "regime": {"score": 0.793, "type": "STRONG", "special_modes": ["STRONG_BROAD_MOMENTUM"]},
    "top_candidates": [],
}


def test_v1_gets_rich_score_and_keeps_legacy_block():
    new, changed = relabel_run(dict(V1), _spy())
    assert changed
    assert new["regime_source"] == RELABELLED_SOURCE
    assert new["schema_version"] == HISTORY_SCHEMA_VERSION
    assert new["regime_legacy"] == V1["regime"]
    assert new["regime"]["score_legacy"] == 0.793
    assert 0.0 <= new["regime"]["score"] <= 1.0
    assert new["regime"]["breadth_assumed"] == 0.5
    # type and special modes were already the rich ones in v1: they must survive untouched
    assert new["regime"]["type"] == "STRONG"
    assert new["regime"]["special_modes"] == ["STRONG_BROAD_MOMENTUM"]
    assert new["regime"]["gate_blocked"] == new["regime_gate_blocked"]


def test_v2_file_is_left_alone():
    v2 = {**V1, "regime_source": "rich", "schema_version": 2}
    new, changed = relabel_run(v2, _spy())
    assert not changed and new is v2


def test_insufficient_spy_is_marked_not_guessed():
    new, changed = relabel_run(dict(V1), _spy(n=120))
    assert changed
    assert new["regime_source"] == "unrelabelled_insufficient_spy"
    assert new["regime"] == V1["regime"]           # score NOT touched when we cannot recompute it
