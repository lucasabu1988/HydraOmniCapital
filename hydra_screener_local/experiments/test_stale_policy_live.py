"""TASK-411 half (b) — the gap classifier on synthetic masks. No network."""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.fetch import attach_observed, observed_mask  # noqa: E402
from stale_policy_live import classify, gaps_for  # noqa: E402

IDX = pd.bdate_range("2026-01-05", periods=12)


def _mask(pattern: str) -> pd.Series:
    """'1' printed, '0' no print, one char per bar."""
    return pd.Series([c == "1" for c in pattern], index=IDX[:len(pattern)])


def test_bars_before_the_first_print_are_not_a_gap():
    assert gaps_for(_mask("000111111111")) == []
    assert gaps_for(_mask("000000000000")) == []


def test_gaps_are_maximal_runs_and_a_run_reaching_the_end_is_trailing():
    gs = gaps_for(_mask("110011100000"))
    assert gs == [dict(start=2, length=2, trailing=False), dict(start=7, length=5, trailing=True)]


def test_classify_buckets_hidden_delayed_and_trailing_with_the_production_limit():
    obs = pd.DataFrame({
        "HID": [c == "1" for c in "111011101111"],     # two gaps of 1: hidden entirely
        "DEL": [c == "1" for c in "110000011111"],     # gap of 5 > 3: 3 carried, clock 3 bars late
        "TRL": [c == "1" for c in "111111100000"],     # stopped printing: trailing, 3 carried
        "OK":  [True] * 12,
    }, index=IDX)
    r = classify(obs, limit=3, book_names={"TRL", "OK", "NOTINFRAME"})
    u, b = r["universe"], r["book"]
    assert r["totals"] == dict(tickers=4, bars=12, cells=48, printed=48 - 2 - 5 - 5)
    assert (u["gaps"], u["hidden"], u["delayed"], u["trailing"]) == (4, 2, 1, 1)
    assert u["hidden_lengths"] == {"1": 2}
    assert u["filled_bars"] == 1 + 1 + 3 + 3 and u["resets"] == u["filled_bars"]
    assert u["delay_bars_max"] == 3
    assert u["tickers_with_gap"] == 3
    # the live book sees only its own names; a name not in the frame is reported, not invented
    assert (b["tickers"], b["gaps"], b["trailing"], b["hidden"], b["delayed"]) == (2, 1, 1, 0, 0)
    assert r["book_names_missing_from_frame"] == ["NOTINFRAME"]
    kinds = sorted(e["kind"] for e in u["examples"])
    assert kinds == ["delayed", "trailing"]


def test_the_mask_round_trips_through_data_fetch_attach_observed():
    raw = pd.DataFrame({"A": [1.0, np.nan, np.nan, 2.0, np.nan, np.nan, np.nan, np.nan, 3.0, 3.0, 3.0, 3.0]}, index=IDX)
    filled = raw.ffill(limit=3)
    attach_observed(filled, raw.notna())
    obs = observed_mask(filled)
    assert obs is not None and obs.shape == raw.shape
    gs = gaps_for(obs["A"])
    assert [(g["length"], g["trailing"]) for g in gs] == [(2, False), (4, False)]
    r = classify(obs, limit=3)["universe"]
    assert (r["hidden"], r["delayed"], r["filled_bars"]) == (1, 1, 2 + 3)
