"""TASK-418 — load_panel normalizes StringDtype axes from a pickle.

Parity with the engine failed locally only when the lab cache was present (StringDtype
vs object). CI had no cache, so the gate never fired. This test builds a cache whose
ticker axis is StringDtype and asserts the loader returns object.
"""
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "experiments"))

import redesign_lab as L  # noqa: E402


def _string_cache(tmp_path):
    idx = pd.bdate_range("2020-01-02", periods=40)
    cols = pd.Index(["AAA", "BBB"], dtype="string")
    close = pd.DataFrame(10.0, index=idx, columns=cols)
    volume = pd.DataFrame(1_000_000.0, index=idx, columns=cols)
    spy = pd.DataFrame({"SPY": 100.0}, index=idx)
    close.to_pickle(tmp_path / "close.pkl")
    volume.to_pickle(tmp_path / "volume.pkl")
    spy.to_pickle(tmp_path / "spy.pkl")
    assert str(close.columns.dtype).startswith("string")


def test_load_panel_plain_object_columns_from_stringdtype_cache(tmp_path):
    _string_cache(tmp_path)
    P = L.load_panel(oos=False, cache_dir=str(tmp_path), sectors={"AAA": "Tech", "BBB": "Energy"})
    assert not str(P.close.columns.dtype).startswith("string")
    assert P.close.columns.dtype == object
    assert list(P.close.columns) == ["AAA", "BBB"]
    assert P.rets.columns.dtype == object
    assert P.volume.columns.dtype == object
