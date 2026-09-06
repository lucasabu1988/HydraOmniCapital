"""TASK-355 — journal builder and persistence. No network."""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.journal import build_record, cone, percentile_of, render_markdown  # noqa: E402
import journal as J  # noqa: E402
import daily as daily_mod  # noqa: E402
import portfolio_v9 as V  # noqa: E402
from test_portfolio_v9_cli import FakeEngine, _market, _rank  # noqa: E402


def _state():
    return {
        "algo_version": "v9",
        "schema_version": 1,
        "capital_reference": 100000.0,
        "week_index": 3,
        "last_renewal_date": "2026-09-04",
        "sleeves": {
            "stocks": {"tranches": [
                {"k": 0, "units": {"AAA": 10.0}, "cash": 1000.0, "last_px": {"AAA": 10.0}},
                {"k": 1, "units": {}, "cash": 4000.0, "last_px": {}},
            ]},
            "etf": {"tranches": [
                {"k": 0, "units": {"SPY": 5.0}, "cash": 500.0, "last_px": {"SPY": 100.0}},
                {"k": 1, "units": {}, "cash": 4500.0, "last_px": {}},
            ]},
        },
        "interest": [{"date": "2026-09-04", "sleeve": "stocks", "dollars": 1.5}],
        "write_offs": [],
        "pending": [],
        "ledger": [],
    }


def _ranking():
    return pd.DataFrame({
        "rank": [1, 2, 3],
        "ticker": ["AAA", "BBB", "CCC"],
        "sector": ["Technology", "Health Care", "Technology"],
        "recommended": [True, True, False],
        "recommended_count": 2,
        "regime": [0.62, 0.62, 0.62],
        "meta_regime_type": ["BULL", "BULL", "BULL"],
        "sector_penalty_applied": [False, False, True],
        "reason": ["ok", "ok", "Filtrado: límite por sector (SPEC 4.6)"],
    })


def _summary():
    return {
        "total": 110000.0,
        "sleeves": {
            "stocks": {"value": 55000.0, "share": 0.5, "cash": 5000.0, "exposure": 0.8,
                       "distinct": 1, "names": ["AAA"]},
            "etf": {"value": 55000.0, "share": 0.5, "cash": 5000.0, "exposure": 0.4,
                    "distinct": 1, "names": ["SPY"]},
        },
    }


def test_build_record_seen_did_book():
    rec = build_record(
        date="2026-09-04", state=_state(), ranking=_ranking(), summary=_summary(),
        orders=[{"sleeve": "stocks", "tranche": 0, "side": "buy", "ticker": "AAA", "dollars": 100}],
        fills=[{"status": "filled", "side": "buy", "sleeve": "stocks", "ticker": "AAA",
                "est_price": 10.0, "price": 10.05, "units": 10}],
        preflight={"hard": False, "warn": True, "ok": True, "rows": [{"check": "x", "status": "WARN"}]},
        observations=["hello"],
    )
    assert rec["schema"] == "journal-1"
    assert rec["seen"]["regime_score"] == pytest.approx(0.62)
    assert rec["seen"]["regime_label"] == "BULL"
    assert rec["seen"]["recommended_count"] == 2
    assert rec["seen"]["etf_on"] == ["SPY"]
    assert "QQQ" in rec["seen"]["etf_off"]
    assert rec["seen"]["sector_cap_displaced"][0]["ticker"] == "CCC"
    assert rec["did"]["n_orders"] == 1
    assert rec["did"]["fills_presumed"] == 1
    assert rec["did"]["interest_dollars"] == pytest.approx(1.5)
    assert rec["did"]["slippage"]["n"] == 1
    assert rec["did"]["slippage"]["mean_bp"] == pytest.approx(50.0)  # 10 -> 10.05
    assert rec["book"]["total"] == 110000.0
    assert rec["book"]["week_index"] == 3
    assert rec["process"]["preflight"]["warn"] is True
    assert rec["observations"] == ["hello"]


def test_missing_pieces_do_not_crash():
    rec = build_record(date="2026-09-04", state={})
    assert rec["seen"]["recommended_count"] is None
    assert rec["did"]["n_orders"] == 0
    assert rec["expectation"]["step_return"] is None


def test_percentile_and_cone():
    dist = [0.01, 0.00, -0.01, 0.02, -0.02] * 20
    assert percentile_of(0.02, dist) == pytest.approx(100.0)
    assert percentile_of(-0.02, dist) > 0
    c = cone(dist, 4)
    assert c["n_steps"] == 4 and c["p5"] <= c["p50"] <= c["p95"]


def test_step_return_percentile_against_oos():
    rec = build_record(
        date="2026-09-04", state=_state(), summary=_summary(),
        prior_total=100000.0, oos_step_returns=[0.0, 0.05, 0.10, 0.20],
        live_curve=[100000.0, 110000.0],
    )
    assert rec["expectation"]["step_return"] == pytest.approx(0.10)
    # dist [0, 0.05, 0.10, 0.20] -> 3/4 of mass <= 0.10
    assert rec["expectation"]["step_return_percentile"] == pytest.approx(75.0)
    assert rec["expectation"]["cone"]["n_steps"] == 1


def test_note_appended_never_overwritten(tmp_path):
    rec = build_record(date="2026-09-04", state=_state(), summary=_summary())
    J.save_record(rec, tmp_path, note="first")
    rec2 = build_record(date="2026-09-04", state=_state(), summary=_summary())
    J.save_record(rec2, tmp_path, note="second")
    body = json.loads((tmp_path / "2026-09-04.json").read_text(encoding="utf-8"))
    assert body["observations"] == ["first", "second"]
    md = (tmp_path / "JOURNAL.md").read_text(encoding="utf-8")
    assert "> first" in md and "> second" in md


def test_rerender_cli(tmp_path):
    J.save_record(build_record(date="2026-09-03", state=_state(), summary=_summary()), tmp_path)
    J.save_record(build_record(date="2026-09-04", state=_state(), summary=_summary()), tmp_path)
    (tmp_path / "JOURNAL.md").write_text("stale\n", encoding="utf-8")
    rc = J.main(["--dir", str(tmp_path)])
    assert rc == 0
    text = (tmp_path / "JOURNAL.md").read_text(encoding="utf-8")
    assert "## 2026-09-03" in text and "## 2026-09-04" in text


def test_journal_never_changes_state():
    st = _state()
    snap = json.dumps(st, sort_keys=True)
    build_record(date="2026-09-04", state=st, ranking=_ranking(), summary=_summary(),
                 orders=[{"side": "buy"}], fills=[])
    assert json.dumps(st, sort_keys=True) == snap


def test_v9_run_returns_journal_pieces(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))
    out = V.run(tmp_path, capital=100000.0, fetch_fn=_market, rank_fn=_rank,
                engine=FakeEngine(), silent=True)
    assert "state" in out and "ranking" in out and "summary" in out and "preflight" in out
    rec = build_record(
        date=out["today"], state=out["state"], ranking=out["ranking"],
        summary=out["summary"], orders=out["orders"], fills=out["fills"],
        preflight=out["preflight"], last_bars=out["last_bars"],
    )
    assert rec["book"]["total"] == pytest.approx(100000.0)
    assert rec["did"]["n_orders"] >= 1


def test_daily_note_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("HYDRA_BACKUP_DIR", str(tmp_path / "off"))
    seen = {}
    monkeypatch.setattr(daily_mod, "run_screener", lambda universe: 0)
    monkeypatch.setattr(daily_mod, "backup_history_after_run", lambda: None)
    monkeypatch.setattr(daily_mod, "print_tv_instructions", lambda: None)
    monkeypatch.setattr(daily_mod, "maybe_refresh_pnl", lambda x: None)

    real_run = V.run

    def fake_run(*a, **k):
        return real_run(tmp_path / "state", capital=100000.0, fetch_fn=_market, rank_fn=_rank,
                        engine=FakeEngine(), silent=True)

    monkeypatch.setattr("portfolio_v9.run", fake_run)
    monkeypatch.setattr(J, "DEFAULT_DIR", tmp_path / "journal")
    import journal as journal_mod
    monkeypatch.setattr(journal_mod, "DEFAULT_DIR", tmp_path / "journal")
    rc = daily_mod.main(["--skip-screener", "--no-instructions", "--v9", "--note", "lucas note"])
    assert rc == 0
    files = list((tmp_path / "journal").glob("*.json"))
    assert files
    body = json.loads(files[0].read_text(encoding="utf-8"))
    assert "lucas note" in body["observations"]
