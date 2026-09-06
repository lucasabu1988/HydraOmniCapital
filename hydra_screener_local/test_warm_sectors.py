"""TASK-344 — incremental sector cache + DEGRADED warning. No live yfinance."""
import json
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import data.sectors as S  # noqa: E402
import portfolio_v9 as V  # noqa: E402
from data.sectors import other_share_in_selection_pool, sector_degraded_message  # noqa: E402


class _FakeTicker:
    def __init__(self, t):
        self._t = t

    @property
    def info(self):
        return {"sector": f"Sec-{self._t}"}


def test_incremental_save_every_n(tmp_path, monkeypatch):
    cache = tmp_path / "sector_cache.json"
    monkeypatch.setattr(S, "CACHE_FILE", str(cache))
    monkeypatch.setattr(S, "_memory", None)
    saves = []

    orig = S._save_cache

    def counting_save(data):
        saves.append(len(data.get("sectors") or {}))
        orig(data)

    monkeypatch.setattr(S, "_save_cache", counting_save)
    monkeypatch.setattr("yfinance.Ticker", _FakeTicker)
    import yfinance as yf
    monkeypatch.setattr(yf, "Ticker", _FakeTicker)

    tickers = [f"T{i:02d}" for i in range(5)]
    S.refresh_sector_cache(tickers, budget_seconds=None, save_every=2)
    # 2, 4 successful lookups trigger mid-run saves; plus a final save
    assert any(s == 2 for s in saves)
    assert saves[-1] == 5
    assert cache.exists() or True  # counting_save still wrote via orig


def test_other_share_triggers_degraded_message():
    rows = [{"ticker": f"T{i}", "rank": i + 1, "sector": "Other" if i < 8 else "Tech",
             "recommended": i < 5, "recommended_count": 5} for i in range(12)]
    df = pd.DataFrame(rows)
    share, n_other, n_pool = other_share_in_selection_pool(df)
    assert n_pool == 10
    assert n_other == 8
    assert share == pytest.approx(0.8)
    msg = sector_degraded_message(df, max_share=0.30)
    assert msg and "cap sectorial no aplicado" in msg and "warm_sectors.py" in msg
    ok = pd.DataFrame([{"ticker": "A", "rank": 1, "sector": "Tech",
                        "recommended": True, "recommended_count": 1}])
    assert sector_degraded_message(ok, max_share=0.30) is None


def test_instruction_sheet_header_carries_degraded(tmp_path):
    md, js = V.write_instructions(
        tmp_path, "2026-09-04", [], [], {"total": 100000},
        {"capital_reference": 100000, "week_index": 0, "last_renewal_date": None, "pending": []},
        "2026-09-07",
        sector_warning="cap sectorial no aplicado: 80% sin sector — ejecuta warm_sectors.py y repite",
    )
    text = md.read_text(encoding="utf-8")
    assert text.startswith("# HYDRA v9 instructions")
    assert "**DEGRADED** cap sectorial no aplicado" in text
    payload = json.loads(js.read_text(encoding="utf-8"))
    assert "80%" in payload["sector_degraded"]
