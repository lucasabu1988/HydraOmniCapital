"""The report only ROUTES: each footprint to the ADV panel of its sleeve, and F1 gates every number."""
from __future__ import annotations

import json
import math
import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import capacity as C  # noqa: E402
import capacity_report as CR  # noqa: E402

IDX = pd.bdate_range("2024-01-01", periods=30)


def _fp():
    d = IDX[10]
    return pd.DataFrame(dict(settle=[d, d, d], sleeve=["stocks", "etf", "etf"], ticker=["AAA", "SPY", "TLT"],
                             net_dollars=[1.0, 2.0, 3.0], gross_dollars=[1.0, 2.0, 3.0], n_fills=[1, 1, 1]))


def test_each_sleeve_reads_its_own_panel_and_a_missing_panel_is_unknown():
    adv_stocks = pd.DataFrame({"AAA": 100.0, "SPY": 999.0}, index=IDX)      # SPY here must NOT be used for the ETF sleeve
    adv_etf = pd.DataFrame({"SPY": 5000.0}, index=IDX)                       # TLT absent -> unknown
    fa = CR.attach_adv_by_sleeve(_fp(), {"stocks": adv_stocks, "etf": adv_etf})
    assert fa.loc[fa["ticker"] == "AAA", "adv_usd"].item() == 100.0
    assert fa.loc[fa["ticker"] == "SPY", "adv_usd"].item() == 5000.0, "ETF sleeve reads the ETF panel, not the stock panel"
    assert math.isnan(fa.loc[fa["ticker"] == "TLT", "adv_usd"].item()) and not fa.loc[fa["ticker"] == "TLT", "known"].item()
    fb = CR.attach_adv_by_sleeve(_fp(), {"stocks": adv_stocks, "etf": None})
    assert not fb.loc[fb["sleeve"] == "etf", "known"].any(), "no ETF panel -> every ETF footprint unknown"


def test_routing_uses_the_one_lookup_rule(monkeypatch):
    seen = []

    def spy(adv, ticker, settle):
        seen.append((ticker, settle))
        return 1.0

    monkeypatch.setattr(C, "adv_prev_bar", spy)
    CR.attach_adv_by_sleeve(_fp(), {"stocks": pd.DataFrame(), "etf": pd.DataFrame()})
    assert [t for t, _ in seen] == ["AAA", "SPY", "TLT"]


def test_a_failed_or_missing_f1_record_refuses_every_number(tmp_path):
    with pytest.raises(SystemExit, match="no F1 record"):
        CR.load_f1(str(tmp_path), "russell")
    (tmp_path / "russell_base.F1.json").write_text(json.dumps(dict(passed=False, n_problems=3)), encoding="utf-8")
    with pytest.raises(SystemExit, match="did not pass"):
        CR.load_f1(str(tmp_path), "russell")
    (tmp_path / "russell_base.F1.json").write_text(json.dumps(dict(passed=True, book_sha256="x", n_marks=1)), encoding="utf-8")
    assert CR.load_f1(str(tmp_path), "russell")["passed"] is True


def test_sheets_are_single_points_with_no_percentile(tmp_path, monkeypatch):
    """Prereg: a sheet "does not get a percentile of its own". Max, coverage, breaches - yes."""
    live = tmp_path / "state"; paper = tmp_path / "state_paper"
    live.mkdir(); paper.mkdir()
    sheet = dict(date="2024-01-15", exec_date="2024-01-16",
                 orders=[dict(sleeve="stocks", tranche=0, ticker="AAA", side="buy", dollars=100.0, planned="2024-01-15")])
    (live / "instructions_20240115.json").write_text(json.dumps(sheet), encoding="utf-8")
    (paper / "instructions_20240115.json").write_text(json.dumps(sheet), encoding="utf-8")
    monkeypatch.setattr(CR, "SHEET_GLOBS", (str(live / "instructions_*.json"), str(paper / "instructions_*.json")))
    adv = pd.DataFrame({"AAA": 1_000_000.0}, index=IDX)
    out = CR.sheet_payload({"russell": adv}, None)
    assert out["n_sheets"] == 2 and not out["none"]
    assert {r["source"] for r in out["sheets"]} == {"live", "paper"}
    row = out["sheets"][0]["by_when"]["planned"][0]
    assert "p95" not in row and "p95_descriptive" not in json.dumps(row)
    assert row["max_participation_pct"] == pytest.approx(100.0 / 1_000_000.0 * 100.0)
    monkeypatch.setattr(CR, "SHEET_GLOBS", (str(tmp_path / "nowhere" / "*.json"),))
    empty = CR.sheet_payload({"russell": adv}, None)
    assert empty["none"] is True and empty["n_sheets"] == 0, "none is printed, never skipped"
